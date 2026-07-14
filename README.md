JD-to-Resume Gap & Tailoring Agent 

Is a project where you feed it a job description + your resume; it extracts requirements, compares them against your resume, scores the match, drafts tailored bullets/cover-letter language, then critiques its own draft against the JD and loops back to revise if the match score is too low. This is literally the workflow you and I do manually every time you paste a JD — automating it is both a strong portfolio piece and something you'd actually use. Branching: extract → score → (if score low) revise → re-score → (if still low) ask you a clarifying question → finalize.


Part 2: Designing the JD-to-Resume Gap Agent
Step 1 — Define the State (what data flows through the graph):
State:
  jd_text: str              # the job description, as given
  resume_text: str          # your resume content
  requirements: list         # extracted from JD
  match_scores: dict         # requirement -> score/evidence
  gaps: list                 # requirements not well covered
  draft_bullets: list        # tailored resume bullets / cover letter lines
  overall_score: float       # how well resume matches JD, 0-100
  revision_count: int        # so we can cap retries
  final_output: str

Step 2 — Decide the nodes (each is one clear job):
| Node | What it does | 
| extract_requirements | LLM call: pull structured list of requirements from JD text |
| score_match | LLM call: for each requirement, check resume, assign a score + evidence + gap flag | 
| identify_gaps | Plain logic (or LLM): filter out low-scoring requirements into a  gaps list |
| draft_tailoring | LLM call: write tailored bullets/summary addressing the gaps honestly |
| self_critique | LLM call: re-score the draft against the JD — did it actually improve the match, and is anything overclaimed? |
| finalize | Assemble final output |

Step 3 — Decide the edges, including the branch/retry logic 
extract_requirements → score_match → identify_gaps → draft_tailoring → self_critique
                                                                              │
                                                              conditional edge:
                                                    ┌─────────────────────────┴───────────────┐
                                        overall_score improved AND                revision_count < 3
                                        no overclaiming detected                  AND score still weak
                                                    │                                          │
                                                    ▼                                          ▼
                                                finalize → END                    draft_tailoring (retry)
The key design decision: self_critique is a separate node from draft_tailoring, and it's what decides whether to loop back. This mirrors exactly what you and I did manually earlier in this conversation — I drafted, then flagged an overclaim, then we revised. You're automating that two-role dynamic (drafter vs. critic) as two distinct nodes.

Step 4 — Decide what's an LLM call vs. plain code:

extract_requirements, score_match, draft_tailoring, self_critique → need an LLM, since they require language understanding/judgment
identify_gaps, the conditional edge logic, finalize → plain Python, no LLM needed (cheaper, faster, more deterministic — good practice to point out in an interview: not everything needs to be an LLM call)

Step 5 — Build order (how I'd suggest we actually build this together, incrementally, so you can follow each piece):

Define the State schema (a TypedDict) — no LLM yet, just the data shape
Build extract_requirements alone, test it in isolation with your Optum JD
Build score_match, test it against your actual resume text
Build identify_gaps — pure logic, quick
Build draft_tailoring
Build self_critique + the conditional edge — this is the trickiest part, worth going slow
Wire the whole graph together, compile, run end-to-end
Test with a couple of real JDs (Optum, the earlier one) and see if the retry loop actually triggers

Want to start with step 1 — writing the State schema together — or do you want me to first show what one node (say, extract_requirements) looks like in actual LangGraph code so you can see the shape of it before we build the whole thing?



--------------------------------------------------

# JD-to-Resume Gap & Tailoring Agent

A LangGraph agent that reads a job description and a resume, scores the
match, identifies real gaps, and drafts honest, evidence-grounded tailoring
suggestions — appended to your actual resume as an editable `.docx`.

## Why this project

Tailoring a resume to a JD is a repetitive, judgment-heavy task: extract
what the JD actually wants, compare it honestly against what's really in
the resume, decide what's a genuine gap vs. a wording problem, and draft
suggestions without overclaiming. This agent automates that workflow, and
because it's built as a LangGraph state machine (not a single hardcoded
script), each step is a swappable, independently-testable node.

## Architecture

```
                START
                  │
                  ▼
        ┌──────────────────────┐
        │ extract_jd_profile    │   LLM call: JD text -> structured profile
        │ (title, location,     │   (title/must-have/preferred/mentioned/
        │  yoe, skill tiers)    │    nontech skills, education, YOE)
        └──────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │ score_match            │   LLM call: score EVERY requirement
        │ -> scored_requirements │   against the resume, 0-100, with
        │ -> gaps                │   evidence grounded in actual resume
        │ -> overall_score        │   text (anti-hallucination checked).
        └──────────┬───────────┘   overall_score = weighted formula
                   │                (must_have x3, preferred x2, rest x1)
                   ▼
        ┌──────────────────────┐
        │ draft_tailoring         │   LLM call: tailored summary + bullet
        │ -> draft_bullets        │   suggestions addressing gaps, only
        └──────────┬───────────┘   from real resume content (no invented
                   │                projects/metrics/tools)
                   ▼
                 END
                   │
                   ▼ (outside the graph)
        write_tailored_docx()     Appends suggestions to your real resume
                                  .docx as a new, clearly-labeled section
```

Current graph is a straight line. The natural next step (not yet built) is
a `self_critique` node with a **conditional edge**: re-score the draft
against the JD, and loop back to `draft_tailoring` if the match didn't
actually improve or something looks overclaimed — capped by a
`revision_count` to avoid infinite loops.

## Files

| File | Role |
|---|---|
| `state.py` | `GraphState` / `JDProfile` / `ScoredRequirement` — the shared data schema that flows through every node |
| `nodes.py` | The three LLM-calling nodes: `extract_jd_profile`, `score_match`, `draft_tailoring`, plus `_flag_possible_hallucinations` (a code-only check, no extra LLM call, that flags evidence containing details not actually in the resume) and the `timed` decorator |
| `graph.py` | The actual LangGraph wiring (`StateGraph`, nodes, edges, `.compile()`) and the CLI entry point |
| `resume_reader.py` | Reads resume text from `.docx`, `.pdf`, or `.txt` |
| `docx_writer.py` | Appends the tailoring suggestions to your real resume `.docx` as a new section, leaving your original content untouched |
| `debug_response.py` | Standalone script to inspect a raw API response (finish_reason, token usage, reasoning content) when something's not parsing right |

## Setup

```bash
pip install langgraph langchain-anthropic openai python-docx pypdf python-dotenv
```

Create a `.env` file in the project folder:
```
OPENROUTER_MODEL=deepseek/deepseek-chat
BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_API_KEY=sk-or-...
```

(Get a key at openrouter.ai — pay-as-you-go, no subscription. Cost for a
full run is a few cents.)

Optional — enables DeepSeek's thinking mode for deeper reasoning on a node
(not currently wired into the API calls; see note in `nodes.py` if you want
this active):
```
INTENT_DEEPSEEK_THINKING_ENABLED=true
INTENT_DEEPSEEK_REASONING_EFFORT=max
```

## Running it

```bash
python graph.py <jd_file.txt> <resume_file.docx>
```

Example:
```bash
python graph.py jd.txt star_resume.docx
```

This runs the full graph end-to-end and prints:
- The extracted JD profile
- The weighted overall match score (0-100)
- The list of gaps, with evidence for each
- Writes `star_resume_tailored.docx` — your original resume with a new
  "Suggested Tailored Additions" section appended (summary suggestion +
  gap-addressing bullets + honestly-flagged unaddressable gaps)

If your resume is `.pdf` or `.txt` instead of `.docx`, everything runs
except the final docx-writing step (that step specifically edits an
existing Word file in place).

## Design decisions worth knowing (good interview talking points)

- **Skill tiers, not a single priority field**: JDs vary wildly in
  structure (explicit Required/Preferred sections, flat bullet lists, bare
  tool lists with no framing at all). `extract_jd_profile` is instructed to
  infer priority from language cues when no explicit structure exists, and
  to *not* guess "required" when there's genuinely no signal.
- **Weighted score is computed in plain code, not asked from the model**:
  `must_have` counts 3x, `preferred` 2x, `mentioned`/`nontech` 1x. This
  keeps the final number transparent and reproducible instead of a
  black-box LLM judgment.
- **One LLM call scores everything at once** (not one call per requirement)
  — cheaper and faster, with generous `max_tokens` headroom to avoid
  truncation on long requirement lists.
- **Anti-hallucination is enforced two ways**: explicit prompt instructions
  (verify every proper noun in evidence actually appears in the resume) AND
  a cheap code-only regex check afterward that flags suspicious
  capitalized phrases not found in the source resume text. This caught a
  real fabricated company name ("CKE Restaurants") during development that
  the prompt-only approach missed.
- **`draft_tailoring` refuses to paper over real gaps**: if a gap has no
  honest way to be addressed from existing resume content, it goes in
  `unaddressable_gaps` instead of getting an invented bullet.
- **The docx output only appends, never overwrites**: safer than
  in-place editing of your real experience bullets, at the cost of you
  needing to manually merge suggestions you agree with.

## Known limitations (be ready to say these honestly)

- No `self_critique` or conditional/retry logic yet — the graph is
  currently a straight line, not yet demonstrating LangGraph's branching
  capability.
- No persistent memory across runs — each run is independent.
- Single-agent, single-session — no multi-agent orchestration.
- Not deployed anywhere — runs locally via CLI only.
- Hallucination checking is a heuristic (regex over capitalized phrases),
  not a guarantee — it can miss non-proper-noun fabrications.

## Next steps

- Add `self_critique`: re-score the draft against the JD; conditional edge
  loops back to `draft_tailoring` (capped by `revision_count`) if the score
  didn't improve or something looks overclaimed.
- Add a small eval set (JD + resume pairs with expected gaps) to measure
  scoring consistency across runs.
- Wrap as a simple CLI flag or small web UI instead of positional args.