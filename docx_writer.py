"""
docx_writer.py

Takes an EXISTING resume .docx and appends a clearly-labeled new section
with tailored suggestions from draft_tailoring, producing a new editable
.docx. Your original resume content is left completely untouched -- the
new section is added at the end, so you can review each suggestion and
manually merge whichever ones you want into your actual resume sections
in Word.
"""

from docx import Document
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH


def write_tailored_docx(original_resume_path: str, draft: dict, output_path: str) -> str:
    doc = Document(original_resume_path)

    # A visual divider so it's obvious where your original resume ends and
    # the suggestions begin.
    divider = doc.add_paragraph()
    divider.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = divider.add_run("— " * 20)
    run.font.size = Pt(9)

    heading = doc.add_heading("SUGGESTED TAILORED ADDITIONS (Review Before Adding)", level=1)

    note = doc.add_paragraph()
    note_run = note.add_run(
        "The section below was generated to help tailor this resume to a specific "
        "job description. Nothing here has been added to your resume above -- "
        "review each suggestion and copy anything you agree with into the "
        "appropriate section yourself."
    )
    note_run.italic = True
    note_run.font.size = Pt(9)

    doc.add_heading("Suggested Professional Summary", level=2)
    doc.add_paragraph(draft.get("tailored_summary", ""))

    suggested_bullets = draft.get("suggested_bullets", [])
    if suggested_bullets:
        doc.add_heading("Suggested Bullet Additions", level=2)
        for b in suggested_bullets:
            # Using a manual bullet character rather than the "List Bullet"
            # style -- documents not created from Word's default template
            # (e.g. ones built programmatically) often don't have that style
            # defined, which raises a KeyError.
            p = doc.add_paragraph()
            p.add_run(f"•  {b['bullet_text']}")
            note_p = doc.add_paragraph()
            note_run = note_p.add_run(
                f"    (addresses: {b['target_gap']} — based on: {b['based_on']})"
            )
            note_run.italic = True
            note_run.font.size = Pt(8)

    unaddressable = draft.get("unaddressable_gaps", [])
    if unaddressable:
        doc.add_heading("Gaps Not Addressed (real gaps -- consider a project or course)", level=2)
        for gap in unaddressable:
            doc.add_paragraph(f"•  {gap}")

    doc.save(output_path)
    return output_path


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 4:
        print("Usage: python docx_writer.py <original_resume.docx> <draft_json_file> <output.docx>")
        sys.exit(1)

    with open(sys.argv[2]) as f:
        draft = json.load(f)

    out = write_tailored_docx(sys.argv[1], draft, sys.argv[3])
    print(f"Wrote tailored resume to {out}")