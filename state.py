"""
state.py

The shared "working memory" that flows through every node in the graph.
Each node reads whatever fields it needs and returns a dict of the fields
it wants to update -- LangGraph merges that into the running state.
"""

from typing import TypedDict


class JDProfile(TypedDict):
    """Structured profile extracted from a job description."""
    title: str                          # job post title
    location: str                       # "Bangalore, India" / "Remote" / "" if not stated
    yoe: str                            # years of experience as stated, e.g. "2-5 years"
    education_requirement: str          # e.g. "Bachelor's/Master's in CS or related field"

    must_have_skills: list[str]         # explicitly non-negotiable ("must have", "required")
    preferred_skills: list[str]         # explicitly nice-to-have ("preferred", "a plus", "good to have")
    mentioned_skills: list[str]         # listed with no priority language either way

    nontech_skills: list[str]           # soft skills / non-technical requirements


class ScoredRequirement(TypedDict):
    requirement: str
    tier: str             # which bucket it came from: "must_have" | "preferred" | "mentioned" | "nontech"
    score: int            # 0-100, how well the resume covers this
    evidence: str          # what in the resume supports this score (or "none found")
    is_gap: bool           # True if this is a meaningful gap


class GraphState(TypedDict):
    jd_text: str
    resume_text: str

    jd_profile: JDProfile
    scored_requirements: list[ScoredRequirement]
    gaps: list[ScoredRequirement]

    draft_bullets: dict         # {"tailored_summary": str, "suggested_bullets": [...], "unaddressable_gaps": [...]}
    overall_score: int

    critique_notes: str          # what self_critique found wrong, if anything
    needs_revision: bool

    revision_count: int
    final_output: str