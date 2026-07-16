"""
nodes.py

Each function here is a LangGraph "node": takes the current GraphState,
returns a dict of fields to update.

"""

import os
import json
import re
import time
from functools import wraps
from openai import OpenAI
from state import GraphState

MODEL = os.environ["OPENROUTER_MODEL"]  # OpenRouter's model naming; check openrouter.ai/models for current slugs

client = OpenAI(
    base_url=os.environ["BASE_URL"],
    api_key=os.environ["OPENROUTER_API_KEY"],
)


def timed(func):
    """Decorator: prints how long a node took to run. """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"[timing] {func.__name__} took {end - start:.2f}s")
        return result
    return wrapper


@timed
def extract_jd_profile(state: GraphState) -> dict:
    """List all the skills and other information from jd and stores in jd_profile node """
    prompt = f"""Extract a structured profile from this job description.

Job descriptions vary in structure -- some have explicit "Required" vs \
"Preferred/Nice to have" sections, some just list bullet points with no \
distinction, some bury requirements in prose, and some are just a flat list \
of tools/technologies with no other context. Handle all of these when \
sorting skills into the three tiers below:

- must_have_skills: things stated as non-negotiable -- "must have", \
"required", explicit years-of-experience-with-X, or core stack items \
framed as mandatory.
- preferred_skills: things explicitly framed as a bonus -- "preferred", \
"a plus", "nice to have", "good to have".
- mentioned_skills: anything listed with NO priority language either way \
-- e.g. a bare "Tech stack: Python, PyTorch, Docker" list, or a tool named \
once in passing. Do not guess a tier here; if there's no signal, it belongs \
in mentioned_skills, not must_have_skills.

Also extract:
- title: the job title as stated (best guess if not explicitly labeled)
- location: as stated, or "" if not mentioned
- yoe: years of experience as stated (e.g. "2-5 years"), or "" if not mentioned
- education_requirement: as stated, or "" if not mentioned
- nontech_skills: soft skills / non-technical requirements (communication, \
collaboration, ethics, etc.) -- keep these separate from the three technical \
skill tiers above.

Return ONLY a JSON object, no other text, in this exact shape:
{{
  "title": "...",
  "location": "...",
  "yoe": "...",
  "education_requirement": "...",
  "must_have_skills": ["...", ...],
  "preferred_skills": ["...", ...],
  "mentioned_skills": ["...", ...],
  "nontech_skills": ["...", ...]
}}

Job description:
{state['jd_text']}
"""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    message = response.choices[0].message
    if message.content is None:
        raise RuntimeError(
            f"Model returned empty content. finish_reason="
            f"{response.choices[0].finish_reason!r}. "
            f"reasoning_content present: {bool(getattr(message, 'reasoning_content', None))}. "
        )
    raw = message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    print(f"[debug] finish_reason={response.choices[0].finish_reason!r}, raw length={len(raw)}")

    try:
        jd_profile = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[debug] JSON parse failed: {e}")
        print(f"[debug] Full raw text:\n{raw}")
        raise
    return {"jd_profile": jd_profile}


# Weight per tier, used to compute the overall weighted score below.
# must_have counts 3x, preferred 2x, mentioned/nontech 1x -- a gap in a
# must-have should hurt the overall score far more than a gap in something
# just mentioned in passing.
TIER_WEIGHTS = {"must_have": 3, "preferred": 2, "mentioned": 1, "nontech": 1}


def _flag_possible_hallucinations(scored_requirements: list, resume_text: str) -> None:
    """
    Cheap, code-only sanity check (no extra LLM call): pull out proper-noun-looking phrases
    Catches: multi-word names
    Misses: single word fabrications like "Docker" 
    False positives: Legitimate proper nouns that resume spells differently. e.g., ML vs Machine Learning
    """
    resume_lower = resume_text.lower()
    proper_noun_pattern = re.compile(r"\b([A-Z][a-zA-Z0-9&]*(?:\s+[A-Z][a-zA-Z0-9&]*)+)\b")

    for r in scored_requirements:
        evidence = r.get("evidence", "")
        candidates = proper_noun_pattern.findall(evidence)
        for phrase in candidates:
            if phrase.lower() not in resume_lower:
                print(
                    f"[hallucination check] Possible fabricated detail in evidence "
                    f"for '{r.get('requirement')}': '{phrase}' not found in resume text -- verify manually."
                )


@timed
def score_match(state: GraphState) -> dict:
    """ Stores all skills scores after comparing them with resume and identify gaps
        Extracted nodes are scored_requirements, overall_score, gaps
    """
    jd_profile = state["jd_profile"]

    # Flatten all four skill buckets into one list, tagging each with its tier
    # so the prompt (and later, the weighted formula) knows which is which.
    all_requirements = (
        [(s, "must_have") for s in jd_profile["must_have_skills"]]
        + [(s, "preferred") for s in jd_profile["preferred_skills"]]
        + [(s, "mentioned") for s in jd_profile["mentioned_skills"]]
        + [(s, "nontech") for s in jd_profile["nontech_skills"]]
    )
    requirements_listing = "\n".join(f'- [{tier}] {text}' for text, tier in all_requirements)

    prompt = f"""You are comparing a candidate's resume against a list of job \
requirements. For EACH requirement below, judge how well the resume covers it.

CRITICAL -- do not fabricate evidence:
- The "evidence" field must be a near-verbatim quote or tight paraphrase of \
text that ACTUALLY APPEARS in the resume below. Do not invent company names, \
project names, metrics, or details that are not present in the resume text.
- Before writing each evidence string, double-check: does every specific \
noun in it (company, tool, dataset, number) genuinely appear in the resume? \
If you are not certain something is in the resume, leave it out rather than \
guessing or inferring a plausible-sounding detail.
- If there is truly no relevant evidence, say exactly "No evidence found in \
resume" -- do not soften this into a fabricated partial match.

Calibrating conceptual matches (be a careful recruiter, not a lenient one):
- A bare skill LISTED in a skills section with no supporting project, or a \
generic phrase resembling the requirement, is weak evidence -- cap this kind \
of match at roughly 40-55, even if the words look related.
- Real coverage -- an actual project, responsibility, or achievement in the \
resume that clearly demonstrates the requirement -- can score higher (60+), \
scaled to how directly and substantially it matches.
- A conceptual/adjacent match (related but not the same thing -- e.g. \
"data quality checks" as partial evidence for "data lineage") should land \
in the middle (40-65) and be described honestly as partial/adjacent in the \
evidence text, not treated as if it fully satisfies the requirement.
- Do not let a candidate's strong resume in ONE area create a halo effect \
that inflates unrelated requirements. Score each requirement independently \
based on what's actually written, not on overall resume quality.

For each requirement, return:
- requirement: the exact requirement text
- tier: copy the tier exactly as given ("must_have", "preferred", "mentioned", or "nontech")
- score: 0-100, how well the resume covers this ONE requirement
- evidence: the specific resume content that supports this score (verbatim/near-verbatim), or "No evidence found in resume" if genuinely absent
- is_gap: true if score is meaningfully low (below ~50) for this requirement, else false

Requirements to check (tier shown in brackets):
{requirements_listing}

Resume:
{state['resume_text']}

Return ONLY a JSON array, no other text, in this exact shape:
[{{"requirement": "...", "tier": "...", "score": 0, "evidence": "...", "is_gap": true}}, ...]
"""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt}],
    )
    message = response.choices[0].message
    if message.content is None:
        raise RuntimeError(
            f"Model returned empty content in score_match. finish_reason="
            f"{response.choices[0].finish_reason!r}. Try increasing max_tokens further."
        )
    raw = message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    print(f"[debug] finish_reason={response.choices[0].finish_reason!r}, raw length={len(raw)}")

    try:
        scored_requirements = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[debug] JSON parse failed: {e}")
        print(f"[debug] Full raw text:\n{raw}")
        raise

    # Weighted overall score: computed in plain code
    total_weight = 0
    weighted_sum = 0
    for r in scored_requirements:
        weight = TIER_WEIGHTS.get(r["tier"], 1)
        weighted_sum += r["score"] * weight
        total_weight += weight
    overall_score = round(weighted_sum / total_weight) if total_weight else 0

    _flag_possible_hallucinations(scored_requirements, state["resume_text"])

    gaps = [r for r in scored_requirements if r["is_gap"]]

    return {
        "scored_requirements": scored_requirements,
        "gaps": gaps,
        "overall_score": overall_score,
    }


@timed
def draft_tailoring(state: GraphState) -> dict:
    """ What to do about the gaps. Tailor actionable output """
    jd_profile = state["jd_profile"]
    gaps = state["gaps"]

    gaps_listing = "\n".join(
        f"- [{g['tier']}] {g['requirement']} (current score: {g['score']}) — {g['evidence']}"
        for g in gaps
    )

    prompt = f"""You are helping a candidate tailor their resume for a specific \
job, based on identified gaps between their resume and the job requirements.

Job title: {jd_profile.get('title', 'N/A')}

Gaps identified (things the resume currently covers weakly or not at all):
{gaps_listing}

Full resume for context:
{state['resume_text']}

Your task: suggest a tailored professional summary AND a short list of \
resume bullet additions/reframings that honestly address as many gaps as \
possible.

CRITICAL rules -- do not fabricate:
- Only reframe or better-surface experience that is ALREADY present in the \
resume. Do not invent projects, tools, metrics, or experience the candidate \
doesn't have.
- If a gap genuinely has no honest way to be addressed from existing resume \
content (e.g. a tool never used at all), do NOT invent a bullet for it -- \
instead include it in "unaddressable_gaps" so the candidate knows this is a \
real gap to close (e.g. via a project or course), not a wording problem.
- Every suggested bullet must be traceable to something real in the resume \
above -- if asked "where does this claim come from in the resume", you must \
be able to point to it.

Return ONLY a JSON object, no other text, in this exact shape:
{{
  "tailored_summary": "...",
  "suggested_bullets": [
    {{"target_gap": "...", "bullet_text": "...", "based_on": "brief note on what existing resume content this reframes"}},
    ...
  ],
  "unaddressable_gaps": ["...", ...]
}}
"""
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    message = response.choices[0].message
    if message.content is None:
        raise RuntimeError(
            f"Model returned empty content in draft_tailoring. finish_reason="
            f"{response.choices[0].finish_reason!r}. Try increasing max_tokens further."
        )
    raw = message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    print(f"[debug] finish_reason={response.choices[0].finish_reason!r}, raw length={len(raw)}")

    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[debug] JSON parse failed: {e}")
        print(f"[debug] Full raw text:\n{raw}")
        raise

    _flag_possible_hallucinations(
        [{"requirement": b["target_gap"], "evidence": b["bullet_text"]} for b in draft["suggested_bullets"]],
        state["resume_text"],
    )

    return {"draft_bullets": draft}