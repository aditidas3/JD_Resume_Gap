"""
graph.py

Current graph -- now with real branching:

START -> extract_jd_profile -> score_match -> draft_tailoring -> self_critique
                                                     ▲                  │
                                                     └──── retry ───────┤
                                                                        │
                                                                    (passes,
                                                                  or out of
                                                                   retries)
                                                                        │
                                                                        ▼
                                                                       END
"""

from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, START, END
from state import GraphState
from nodes import extract_jd_profile, score_match, draft_tailoring, self_critique

MAX_REVISIONS = 2  # cap: up to 2 retries, so total attempts = 3


def decide_after_critique(state: GraphState) -> str:
    """
    The conditional edge: looks at what self_critique found and decides
    where to go next. Returns a STRING naming the next step -- graph.py's
    add_conditional_edges() maps that string to an actual node/END below.
    """
    if not state.get("needs_revision"):
        return "done"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "give_up"  # safety cap so this can't loop forever
    return "retry"


def build_graph():
    builder = StateGraph(GraphState)

    # Register each node function under a name
    builder.add_node("extract_jd_profile", extract_jd_profile)
    builder.add_node("score_match", score_match)
    builder.add_node("draft_tailoring", draft_tailoring)
    builder.add_node("self_critique", self_critique)

    builder.add_edge(START, "extract_jd_profile")
    builder.add_edge("extract_jd_profile", "score_match")
    builder.add_edge("score_match", "draft_tailoring")
    builder.add_edge("draft_tailoring", "self_critique")

    # This is self_critique branch; decide_after_critique
    # looks at the state and picks one of three paths.
    builder.add_conditional_edges(
        "self_critique",
        decide_after_critique,
        {
            "retry": "draft_tailoring",  # loop back for another attempt
            "done": END,
            "give_up": END,
        },
    )

    # Compile turns the node/edge definitions into a runnable object
    return builder.compile()


if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path
    from resume_reader import read_resume
    from docx_writer import write_tailored_docx

    INPUT_DIR = Path("input")
    OUTPUT_DIR = Path("output")

    def resolve_input_path(arg: str, default_ext: str) -> Path:
        """Accepts a full path. Tries the path
        as given first, then falls back to looking inside input/."""
        p = Path(arg)
        if p.suffix == "":
            p = p.with_suffix(default_ext)
        if p.exists():
            return p
        candidate = INPUT_DIR / p.name
        if candidate.exists():
            return candidate
        print(f"Could not find '{arg}' as given or inside '{INPUT_DIR}/' "
              f"(tried '{p}' and '{candidate}').")
        sys.exit(1)

    def get_company_tag(jd_path: Path) -> str:
        """Derives a company tag from the JD filename for tagging output files"""
        stem = jd_path.stem
        lower = stem.lower()
        if lower.startswith("jd_"):
            return stem[3:] or stem
        if lower.startswith("jd"):
            return stem[2:].lstrip("_-") or stem
        return stem

    def find_input_files():
        if not INPUT_DIR.exists():
            print(f"'{INPUT_DIR}/' doesn't exist. Create it and put your JD "
                  f"(.txt) and resume (.docx or .pdf) inside.")
            sys.exit(1)

        jd_candidates = list(INPUT_DIR.glob("*.txt"))
        resume_candidates = list(INPUT_DIR.glob("*.docx")) + list(INPUT_DIR.glob("*.pdf"))

        if len(jd_candidates) != 1:
            print(f"Found {len(jd_candidates)} .txt files in '{INPUT_DIR}/': "
                  f"{[p.name for p in jd_candidates]}. With multiple JDs, "
                  f"specify which one explicitly: python graph.py <jd_name> <resume_name>")
            sys.exit(1)
        if len(resume_candidates) != 1:
            print(f"Expected exactly one .docx or .pdf file (the resume) in "
                  f"'{INPUT_DIR}/', found {len(resume_candidates)}: "
                  f"{[p.name for p in resume_candidates]}")
            sys.exit(1)

        return jd_candidates[0], resume_candidates[0]

    # Two ways to run this:
    #   python graph.py                            -> auto-detect (only works
    #                                                  with exactly one JD)
    #   python graph.py jd_com1 resume.docx         -> explicit, extension
    #                                                  optional, resolved
    #                                                  against input/
    if len(sys.argv) >= 3:
        jd_path = resolve_input_path(sys.argv[1], default_ext=".txt")
        resume_path = resolve_input_path(sys.argv[2], default_ext=".docx")
    else:
        jd_path, resume_path = find_input_files()

    company_tag = get_company_tag(jd_path)

    print(f"JD:      {jd_path}")
    print(f"Resume:  {resume_path}")
    print(f"Tag:     {company_tag}")

    with open(jd_path, encoding="utf-8") as f:
        jd_text = f.read()
    resume_text = read_resume(str(resume_path))

    graph = build_graph()

    final_state = graph.invoke({"jd_text": jd_text, "resume_text": resume_text})

    print("\n=== OVERALL SCORE ===")
    print(final_state["overall_score"])

    print("\n=== SELF-CRITIQUE ===")
    print(f"Revisions needed: {final_state.get('revision_count', 0)}")

    summary = {
        "company_tag": company_tag,
        "jd_file": str(jd_path),
        "resume_file": str(resume_path),
        "jd_profile": final_state["jd_profile"],
        "overall_score": final_state["overall_score"],
        "scored_requirements": final_state["scored_requirements"],
        "gaps": final_state["gaps"],
        "revision_count": final_state.get("revision_count", 0),
        "critique_notes": final_state.get("critique_notes", ""),
        "needs_revision": final_state.get("needs_revision", False),
        "resume_updates": None,
    }

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Only .docx resumes can be edited in place -- if the input was
    # .pdf/.txt, we don't write a tailored .docx.
    if str(resume_path).lower().endswith(".docx"):
        output_filename = f"tailored_resume_{company_tag}.docx"
        output_path = OUTPUT_DIR / output_filename

        result = write_tailored_docx(str(resume_path), final_state["draft_bullets"], str(output_path))

        summary["resume_updates"] = {
            "output_path": result["output_path"],
            "summary_updated": result["summary_updated"],
            "bullets_placed": result["bullets_placed"],
            "bullets_skipped": result["bullets_skipped"],
            "unaddressable_gaps": result["unaddressable_gaps"],
        }

        print(f"\n=== TAILORED RESUME WRITTEN ===\n{result['output_path']}")
        print(f"Summary updated: {result['summary_updated']}")
        print(f"Bullets placed: {len(result['bullets_placed'])}")
        if result["bullets_skipped"]:
            print(f"Bullets skipped (no matching section found): {len(result['bullets_skipped'])}")

    else:
        print(
            "\n=== TAILORED RESUME NOT WRITTEN ===\n"
            "docx_writer only edits .docx files in place. Your input was "
            f"'{resume_path}' -- convert your resume to .docx first."
        )

    summary_path = OUTPUT_DIR / f"summary_{company_tag}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\n=== SUMMARY WRITTEN ===\n{summary_path}")