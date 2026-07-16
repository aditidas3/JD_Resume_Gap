# JD-to-Resume Gap & Tailoring Agent

A LangGraph agent that reads a job description and a resume, scores the
match, identifies real gaps, and drafts honest, evidence-grounded tailoring suggestions — appended to your actual resume as an editable `.docx`.

## Why this project

Tailoring a resume to a JD is a repetitive, judgment-heavy task: extract
what the JD actually wants, compare it honestly against what's really in
the resume, decide what's a genuine gap vs. a wording problem, and draft
suggestions without overclaiming. This agent automates that workflow, and because it's built as a LangGraph state machine (not a single hardcoded script), each step is a swappable, independently-testable node.

## Architecture

```
                START
                  │
                  ▼
        ┌──────────────────────┐
        │ extract_jd_profile   │   LLM call: JD text -> structured profile
        │ (title, location,    │   (title/must-have/preferred/mentioned/
        │  yoe, skill tiers)   │    nontech skills, education, YOE)
        └──────────┬───────────┘
                   │
                   ▼
        ┌───────────────────────┐
        │ score_match           │   LLM call: score EVERY requirement
        │ -> scored_requirements│   against the resume, 0-100, with
        │ -> gaps               │   evidence grounded in actual resume
        │ -> overall_score      │   text (anti-hallucination checked).
        └──────────┬────────────┘   overall_score = weighted formula
                   │                (must_have x3, preferred x2, rest x1)
                   ▼
        ┌──────────────────────┐
        │ draft_tailoring      │   LLM call: tailored summary + bullet
  ┌────>│ -> draft_bullets     │   suggestions addressing gaps, only
  |     └──────────┬───────────┘   from real resume content (no invented
  |                │                projects/metrics/tools)
  |                ▼
  |    ┌──────────────────────┐
  |    │   self_critique      │   LLM call: self critique tailored summary output
  └────│ -> critique_notes    |   for quality and honesty before updating 
       | -> needs_revision    │   resume. total tries = 2
       └──────────┬───────────┘   
                  │                
                  ▼
                 END
                  │
                  ▼ (outside the graph)
        write_tailored_docx()     Appends suggestions to your real resume
                                  .docx as a new, as highlighted section
```

## Files

| File | Role |
|---|---|
| `state.py` | `GraphState` / `JDProfile` / `ScoredRequirement` — the shared data schema that flows through every node |
| `nodes.py` | The four LLM-calling nodes: `extract_jd_profile`, `score_match`, `draft_tailoring`, `self_critique` plus `_flag_possible_hallucinations` (a code-only check, no extra LLM call, that flags evidence containing details not actually in the resume) and the `timed` decorator |
| `graph.py` | The actual LangGraph wiring (`StateGraph`, nodes, edges, `.compile()`) and the CLI entry point |
| `resume_reader.py` | Reads resume text from `.docx`, `.pdf`, or `.txt` |
| `docx_writer.py` | Appends the tailoring suggestions to your real resume `.docx` as a new section, leaving your original content untouched |


## Setup

```bash
python -m pip install -r requirements.txt
```

Create a `.env` file in the project folder as per .env.example file

Create an input folder and have jd.txt and resume.docx files. These are taken as inputs
Create an output folder, this will contain resume_tailored.docx

## Running it

```bash
python graph.py <path to jd_file.txt> <path to resume_file.docx>

or 

python graph.py
```

This runs the full graph end-to-end and prints:
- The extracted JD profile
- The weighted overall match score (0-100)
- The list of gaps, with evidence for each
- Writes `resume_tailored.docx` — your original resume with a updated sections
- Writes summary.json - jd_profile (technical and soft skills mentioned in jd), overall score, gaps, resume updates.

If your resume is `.pdf` or `.txt` instead of `.docx`, everything runs except the final docx-writing step (that step specifically edits an existing Word file in place).

