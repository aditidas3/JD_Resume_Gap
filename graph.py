"""
graph.py

THIS is where LangGraph actually gets used -- until now we were calling node
functions directly and merging state ourselves (`state.update(...)`), which
works for testing one node in isolation but isn't LangGraph. Here we build a
real `StateGraph`: nodes + edges, compiled once, then run with `.invoke()`.

Current graph (linear for now -- branching/retry comes when we add
self_critique):

    START -> extract_jd_profile -> score_match -> draft_tailoring -> END
"""

# load_dotenv() MUST run before we import nodes.py below -- nodes.py reads
# os.environ["OPENROUTER_MODEL"] etc. at import time (module load), not
# inside a function, so env vars need to already be loaded before that
# import line runs, not after it.
from dotenv import load_dotenv
load_dotenv()

from langgraph.graph import StateGraph, START, END
from state import GraphState
from nodes import extract_jd_profile, score_match, draft_tailoring


def build_graph():
    builder = StateGraph(GraphState)

    # Register each node function under a name
    builder.add_node("extract_jd_profile", extract_jd_profile)
    builder.add_node("score_match", score_match)
    builder.add_node("draft_tailoring", draft_tailoring)

    # Wire the edges: START is a special LangGraph marker, not a real node.
    # Still a straight line -- draft_tailoring always runs once, no branching
    # yet. That comes when we add self_critique with a conditional edge.
    builder.add_edge(START, "extract_jd_profile")
    builder.add_edge("extract_jd_profile", "score_match")
    builder.add_edge("score_match", "draft_tailoring")
    builder.add_edge("draft_tailoring", END)

    # Compile turns the node/edge definitions into a runnable object
    return builder.compile()


if __name__ == "__main__":
    import sys
    import glob
    from pathlib import Path
    from resume_reader import read_resume
    from docx_writer import write_tailored_docx

    INPUT_DIR = Path("input")
    OUTPUT_DIR = Path("output")

    def find_input_files():
        """Auto-detect the JD (.txt) and resume (.docx/.pdf) inside input/,
        so you don't have to type filenames every time -- just drop the two
        files in input/ and run `python graph.py` with no arguments."""
        if not INPUT_DIR.exists():
            print(f"'{INPUT_DIR}/' doesn't exist. Create it and put your JD "
                  f"(.txt) and resume (.docx or .pdf) inside.")
            sys.exit(1)

        jd_candidates = list(INPUT_DIR.glob("*.txt"))
        resume_candidates = list(INPUT_DIR.glob("*.docx")) + list(INPUT_DIR.glob("*.pdf"))

        if len(jd_candidates) != 1:
            print(f"Expected exactly one .txt file (the JD) in '{INPUT_DIR}/', "
                  f"found {len(jd_candidates)}: {[str(p) for p in jd_candidates]}")
            sys.exit(1)
        if len(resume_candidates) != 1:
            print(f"Expected exactly one .docx or .pdf file (the resume) in "
                  f"'{INPUT_DIR}/', found {len(resume_candidates)}: "
                  f"{[str(p) for p in resume_candidates]}")
            sys.exit(1)

        return str(jd_candidates[0]), str(resume_candidates[0])

    # Two ways to run this:
    #   python graph.py                          -> auto-detect from input/
    #   python graph.py <jd_file> <resume_file>   -> explicit paths (old behavior, still works)
    if len(sys.argv) >= 3:
        jd_path = sys.argv[1]
        resume_path = sys.argv[2]
    else:
        jd_path, resume_path = find_input_files()

    print(f"JD:     {jd_path}")
    print(f"Resume: {resume_path}")

    with open(jd_path) as f:
        jd_text = f.read()
    resume_text = read_resume(resume_path)

    graph = build_graph()

    # .invoke() runs the whole graph: START -> ... -> END, following the
    # edges we defined, passing state through and merging each node's
    # returned dict into it automatically -- no manual state.update() needed.
    final_state = graph.invoke({"jd_text": jd_text, "resume_text": resume_text})

    print("\n=== JD PROFILE ===")
    print(final_state["jd_profile"])

    print("\n=== OVERALL SCORE ===")
    print(final_state["overall_score"])

    print("\n=== GAPS ===")
    for g in final_state["gaps"]:
        print(f"  [{g['tier']}] {g['requirement']} (score: {g['score']}) — {g['evidence']}")

    # Only .docx resumes can be edited in place -- if the input was
    # .pdf/.txt, we don't write a tailored .docx.
    if resume_path.lower().endswith(".docx"):
        OUTPUT_DIR.mkdir(exist_ok=True)  # create output/ automatically if missing
        output_filename = Path(resume_path).stem + "_tailored.docx"
        output_path = OUTPUT_DIR / output_filename

        result = write_tailored_docx(resume_path, final_state["draft_bullets"], str(output_path))

        print(f"\n=== TAILORED RESUME WRITTEN ===\n{result['output_path']}")
        print(f"Summary updated: {result['summary_updated']}")
        print(f"Bullets placed: {len(result['bullets_placed'])}")
        if result["bullets_skipped"]:
            print(f"Bullets skipped (no matching section found): {len(result['bullets_skipped'])}")
        if result["unaddressable_gaps"]:
            print("Gaps not addressed (for your own review, not written to resume):")
            for g in result["unaddressable_gaps"]:
                print(f"  - {g}")
    else:
        print(
            "\n=== TAILORED RESUME NOT WRITTEN ===\n"
            "docx_writer only edits .docx files in place. Your input was "
            f"'{resume_path}' -- convert your resume to .docx first."
        )