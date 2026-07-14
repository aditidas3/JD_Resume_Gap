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
    from resume_reader import read_resume
    from docx_writer import write_tailored_docx

    if len(sys.argv) < 3:
        print("Usage: python graph.py <jd_file.txt> <resume_file.docx>")
        sys.exit(1)

    jd_path = sys.argv[1]
    resume_path = sys.argv[2]

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

    # Only .docx resumes can be edited in place (appended to) -- if the
    # input was .pdf/.txt, we don't write a tailored .docx.
    if resume_path.lower().endswith(".docx"):
        output_path = resume_path.replace(".docx", "_tailored.docx")
        write_tailored_docx(resume_path, final_state["draft_bullets"], output_path)
        print(f"\n=== TAILORED RESUME WRITTEN ===\n{output_path}")
    else:
        print(
            "\n=== TAILORED RESUME NOT WRITTEN ===\n"
            "docx_writer only edits .docx files in place. Your input was "
            f"'{resume_path}' -- convert your resume to .docx first, or ask "
            "for a version of docx_writer that builds a new .docx from scratch."
        )