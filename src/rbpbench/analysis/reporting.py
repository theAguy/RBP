"""Supervisor-facing Markdown and PDF assembly for Task 003A."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_markdown(results: Mapping, composition_effects: Sequence[Mapping], figure_relpaths: Mapping[str, str]) -> str:
    v2 = results["former_fold_v2"]
    closure = results["closure"]
    balance = results["balance"]
    max_effect = max(composition_effects, key=lambda row: abs(float(row["standardized_mean_difference"])))
    max_ks = max(composition_effects, key=lambda row: float(row["ks_d"]))
    lines = [
        "# Task 003A — Why we replaced the former data split",
        "",
        "## One-sentence conclusion",
        "",
        "The former teammate split individual rows, allowing closely related sequences to appear in both training and evaluation; our split assigns complete sequence families and passed every frozen leakage audit.",
        "",
        "| Question | Former teammate | Our accepted benchmark |",
        "|---|---|---|",
        "| What is assigned? | Individual rows | Whole connected sequence components |",
        "| Can related rows cross the boundary? | Yes | No under the frozen rules |",
        f"| Holdout rows in a family also seen in training | **{v2['crossing_holdout_row_count']:,}/{v2['holdout_count']:,} ({100*v2['crossing_holdout_row_rate']:.2f}%)** | **0 split components** |",
        "| Independent similarity audit | Not protected by construction | **0 hits in 18/18 searches** |",
        "| Exact/reverse-complement groups crossing | Not protected by construction | **0** |",
        "| Final proportions | 80% train / 20% holdout | 68.11% train / 15.94% validation / 15.95% test |",
        "",
        "## 1. Direct comparison",
        "",
        f"![Former row split versus our component split]({figure_relpaths['figure1']})",
        "",
        "## 2. A concrete 500-nt example",
        "",
        "Sequence identity is the fraction of aligned nucleotide positions that match in order. For a 500-nt pair, 450 matching aligned positions means 90% identity. A direct edge also requires enough of both windows to align: at 500 nt the frozen threshold is 80% bidirectional coverage. The search checks the forward sequence and its reverse complement.",
        "",
        f"![Worked similarity example]({figure_relpaths['figure2']})",
        "",
        "A qualifying pair is placed in the same connected component. Components are transitive: if A is related to B and B to C, all three stay together even if A and C do not directly qualify.",
        "",
        "## 3. What the audit found",
        "",
        f"When the former fold is evaluated using the final sequence-family definition, **{v2['crossing_holdout_row_count']:,}/{v2['holdout_count']:,} former holdout rows ({100*v2['crossing_holdout_row_rate']:.2f}%)** and **{v2['crossing_train_row_count']:,}/{v2['train_count']:,} former training rows ({100*v2['crossing_train_row_rate']:.2f}%)** belong to components crossing that old boundary.",
        "",
        f"![Former versus accepted leakage evidence]({figure_relpaths['figure3']})",
        "",
        "Our final split contains zero divided components, zero cross-partition exact/reverse-complement groups, and zero qualifying hits in all 18 fresh directed searches.",
        "",
        "## 4. Is the replacement usable?",
        "",
        f"Yes. It contains {closure['partition_row_counts']['train']:,} train, {closure['partition_row_counts']['validation']:,} validation, and {closure['partition_row_counts']['test']:,} test rows. The minimum evaluation support is {balance['minimum_known_positive']['count']} known positives and {balance['minimum_known_negative']['count']} known negatives per protein, above the floor of 30.",
        "",
        f"![Final split quality]({figure_relpaths['figure4']})",
        "",
        f"The tradeoff is disclosed: {balance['proteins_flagged_validation_or_test']}/122 proteins have at least one validation/test fraction more than 3 percentage points from target. We do not divide related families merely to improve these percentages.",
        "",
        "## What this establishes",
        "",
        "- The former fold is not leakage-safe under the frozen sequence rules.",
        "- The final split is deterministic, whole-component, and passed the prespecified structural, exact/RC, and 18 directed similarity audits.",
        "- No cross-partition relationship was detected under the frozen 500/251/101-nt rules.",
        "- Per-protein label imbalance remains and is reported explicitly; evaluation support remains above the prespecified count floor.",
        "",
        "## What this does not establish",
        "",
        "- The audit does not quantify how much the former AUROC was inflated.",
        "- It does not prove that no biological or coordinate relationship exists outside the frozen rules.",
        "- It does not establish model performance, generalization, or superiority over competitors.",
        "- Composition similarity is descriptive and is not proof that every possible sequence covariate is balanced.",
        "",
        "## Reproducibility",
        "",
        f"All headline values originate from machine-readable tables in the Task 003A artifact package. The internal construction history, edge intersections, component distributions, per-protein heatmap, and sequence-composition checks remain available in the technical appendix. The largest composition effect is small/borderline (|SMD|={float(max_effect['absolute_smd']):.3f}; maximum KS D={float(max_ks['ks_d']):.3f}). Input hashes, output hashes, software versions, and reconciliation gates are recorded in `provenance.json` and `manifests/task003a_split_validation_report.json`.",
    ]
    return "\n".join(lines) + "\n"


def _front_matter_pdf(path: Path, results: Mapping, max_effect: Mapping, max_ks: Mapping) -> None:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor("#17324D"), spaceAfter=10 * mm))
    styles.add(ParagraphStyle(name="Lead", parent=styles["BodyText"], fontSize=12, leading=17, spaceAfter=5 * mm))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=9, leading=12))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title="Task 003A supervisor split validation")
    closure = results["closure"]
    v2 = results["former_fold_v2"]
    balance = results["balance"]
    story = [
        Paragraph("Task 003A: why we replaced the former split", styles["CenterTitle"]),
        Paragraph("Purpose: compare the former row-level boundary directly with our leakage-safe sequence-family boundary before any model training.", styles["Lead"]),
        Table(
            [
                ["Rows", "Final components", "Split components", "Directed audit hits"],
                [f"361,180", f"{closure['universe']['component_count']:,}", "0", "0 in 18/18"],
            ],
            colWidths=[42 * mm] * 4,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EDF2")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#222222")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFC7CF")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
            ]),
        ),
        Spacer(1, 9 * mm),
        Paragraph("Direct conclusion", styles["Heading2"]),
        Paragraph(f"The former teammate split individual rows. Under the final sequence-family definition, {v2['crossing_holdout_row_count']:,}/{v2['holdout_count']:,} former holdout rows ({100*v2['crossing_holdout_row_rate']:.2f}%) belong to a family also represented in former training. Our replacement assigns complete connected components and passed every frozen leakage audit.", styles["Lead"]),
        Paragraph("What counts as related", styles["Heading2"]),
        Paragraph("A direct pair requires at least 90% identity across an alignment covering both sequences sufficiently (80% for 500 nt; 95% for 251/101 nt), with both strands checked. Exact/reverse-complement relations are also protected. Transitive paths define connected components.", styles["Lead"]),
        Paragraph("Practicality and remaining limitation", styles["Heading2"]),
        Paragraph(f"The accepted split has {closure['partition_row_counts']['train']:,}/{closure['partition_row_counts']['validation']:,}/{closure['partition_row_counts']['test']:,} train/validation/test rows and zero split components. Every evaluation cell remains above the floor of 30 (observed minima {balance['minimum_known_positive']['count']} positives and {balance['minimum_known_negative']['count']} negatives), although {balance['proteins_flagged_validation_or_test']}/122 proteins retain a validation/test fraction-balance flag.", styles["Lead"]),
        Paragraph("Scope", styles["Heading2"]),
        Paragraph(f"This report validates the data boundary; it does not compare model AUROC or estimate leakage inflation. Detailed construction history and diagnostics are retained in a separate technical appendix. The largest composition effect was small/borderline (|SMD|={float(max_effect['absolute_smd']):.3f}; maximum KS D={float(max_ks['ks_d']):.3f}).", styles["Lead"]),
    ]
    doc.build(story)


def _numbered_page(page, *, page_number: int, page_count: int):
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    buffer = BytesIO()
    footer = canvas.Canvas(buffer, pagesize=(width, height))
    footer.setFillColor(colors.HexColor("#666666"))
    footer.setFont("Helvetica", 7.5)
    footer.drawString(18 * mm, 8 * mm, "Task 003A split validation")
    footer.drawRightString(width - 18 * mm, 8 * mm, f"Page {page_number} of {page_count}")
    footer.save()
    buffer.seek(0)
    page.merge_page(PdfReader(buffer).pages[0])
    return page


def build_supervisor_pdf(output_path: Path, figure_pdfs: Sequence[Path], results: Mapping, composition_effects: Sequence[Mapping]) -> None:
    front = output_path.with_name("_front_matter.pdf")
    max_effect = max(composition_effects, key=lambda row: abs(float(row["standardized_mean_difference"])))
    max_ks = max(composition_effects, key=lambda row: float(row["ks_d"]))
    _front_matter_pdf(front, results, max_effect, max_ks)
    writer = PdfWriter()
    pages = []
    for source in [front, *figure_pdfs]:
        reader = PdfReader(str(source))
        pages.extend(reader.pages)
    for page_number, page in enumerate(pages, 1):
        writer.add_page(_numbered_page(page, page_number=page_number, page_count=len(pages)))
    writer.add_metadata({"/Title": "Task 003A supervisor split-validation report", "/Subject": "Model-blind validation of the leakage-safe RBP benchmark split"})
    with output_path.open("wb") as handle:
        writer.write(handle)
    front.unlink()


def build_technical_appendix_pdf(output_path: Path, figure_pdfs: Sequence[Path]) -> None:
    cover = output_path.with_name("_technical_appendix_cover.pdf")
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(cover), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm, title="Task 003A technical appendix")
    doc.build([
        Paragraph("Task 003A: technical appendix", styles["Title"]),
        Spacer(1, 8 * mm),
        Paragraph("This appendix preserves the internal construction history and detailed diagnostics omitted from the supervisor-facing report: the rejected intermediate v1 audit, component-size distributions, per-width edge intersections, full per-protein balance heatmap, evaluation counts, and sequence-composition summaries.", styles["BodyText"]),
        Spacer(1, 6 * mm),
        Paragraph("The supervisor-facing conclusion does not depend on understanding v1. The appendix exists for reproducibility and technical review.", styles["BodyText"]),
    ])
    pages = []
    for source in [cover, *figure_pdfs]:
        pages.extend(PdfReader(str(source)).pages)
    writer = PdfWriter()
    for page_number, page in enumerate(pages, 1):
        writer.add_page(_numbered_page(page, page_number=page_number, page_count=len(pages)))
    writer.add_metadata({"/Title": "Task 003A technical appendix", "/Subject": "Detailed construction and diagnostic evidence for the leakage-safe split"})
    with output_path.open("wb") as handle:
        writer.write(handle)
    cover.unlink()
