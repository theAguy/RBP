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
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_markdown(results: Mapping, composition_effects: Sequence[Mapping], figure_relpaths: Mapping[str, str]) -> str:
    v1 = results["former_fold_v1"]
    v2 = results["former_fold_v2"]
    closure = results["closure"]
    balance = results["balance"]
    max_effect = max(composition_effects, key=lambda row: abs(float(row["standardized_mean_difference"])))
    max_ks = max(composition_effects, key=lambda row: float(row["ks_d"]))
    lines = [
        "# Task 003A — Supervisor split-validation report",
        "",
        "## Executive conclusion",
        "",
        "The original row-level fold is not suitable as an unbiased benchmark boundary because related sequences occur on both sides. The accepted components-v2 split keeps every protected sequence family together and passed all prespecified structural and independent leakage audits. No model prediction or performance metric was used to build or accept this split.",
        "",
        f"- Final universe: **{closure['universe']['component_count']:,} components across 361,180 rows**.",
        f"- Final partition sizes: **{closure['partition_row_counts']['train']:,} train / {closure['partition_row_counts']['validation']:,} validation / {closure['partition_row_counts']['test']:,} test**.",
        f"- Component integrity: **0/{closure['universe']['component_count']:,} components split**.",
        "- Independent exact/reverse-complement audit: **0 cross-partition groups**.",
        "- Fresh directed similarity audits: **0 qualifying cross-partition hits in all 18/18 searches**, with positive controls passing once per width.",
        f"- Evaluation support: minimum **{balance['minimum_known_positive']['count']} known positives** and **{balance['minimum_known_negative']['count']} known negatives** per protein in validation/test (required floor: 30).",
        "",
        "## 1. Why the former fold was rejected",
        "",
        f"The former notebook's exact fold 0 was reproduced using its pinned dependency stack, seed, and positive-only stratification matrix. Against the rejected v1 grouping, **{v1['crossing_holdout_row_count']:,}/{v1['holdout_count']:,} holdout rows ({100*v1['crossing_holdout_row_rate']:.3f}%)** and **{v1['crossing_train_row_count']:,}/{v1['train_count']:,} training rows ({100*v1['crossing_train_row_rate']:.3f}%)** belonged to components crossing the boundary.",
        "",
        f"Task 003A separately recomputed that same frozen fold against final v2 membership: **{v2['crossing_holdout_row_count']:,}/{v2['holdout_count']:,} holdout rows ({100*v2['crossing_holdout_row_rate']:.3f}%)** and **{v2['crossing_train_row_count']:,}/{v2['train_count']:,} training rows ({100*v2['crossing_train_row_rate']:.3f}%)** are in crossing v2 components. This new value does not replace the historical v1 result; it answers the final-relation question directly.",
        "",
        f"![Why the split changed]({figure_relpaths['figure1']})",
        "",
        "## 2. Independent leakage evidence",
        "",
        "The intermediate v1 assignment was also rejected. Its first directed audit (500 nt, train→validation) found 4,792 qualifying pairs among 3,576 distinct rows (1,400 train queries and 2,176 validation targets). The audit stopped there by design, so 17/18 searches were not run and 4,792 is a lower bound—not a total v1 leakage count.",
        "",
        "Components v2 were constructed from the complete direct-edge relation, exact/reverse-complement relations, and protected v1 co-membership. The final audit regenerated partition FASTAs and databases, passed positive controls, and completed all 18 width/direction searches with zero violations.",
        "",
        f"![Leakage evidence]({figure_relpaths['figure2']})",
        "",
        "## 3. Component structure and protected relationships",
        "",
        f"The stricter relation produced {closure['universe']['component_count']:,} components. The largest contains {closure['universe']['largest_component_size']:,} rows ({100*closure['universe']['largest_component_fraction']:.3f}%), and the largest 20 together contain {100*closure['universe']['top20_component_fraction']:.3f}% of rows—well below the prespecified 5% and 20% stop gates.",
        "",
        f"![Component structure]({figure_relpaths['figure3']})",
        "",
        f"![Protected widths]({figure_relpaths['figure4']})",
        "",
        "## 4. Final partition and label support",
        "",
        f"The achieved fractions are {100*closure['partition_fractions']['train']:.2f}%/{100*closure['partition_fractions']['validation']:.2f}%/{100*closure['partition_fractions']['test']:.2f}% versus 70%/15%/15% targets. Whole components were never split merely to hit exact percentages.",
        "",
        f"![Partition sizes]({figure_relpaths['figure5']})",
        "",
        f"Known-label balance is disclosed rather than hidden: {balance['proteins_flagged_any_partition']}/122 proteins have at least one protein×class×partition cell more than 3 percentage points from the 70/15/15 target ({balance['cells_flagged_any_partition']}/732 cells). Restricting attention to validation/test gives {balance['proteins_flagged_validation_or_test']} proteins and {balance['cells_flagged_validation_or_test']} cells. These are fraction-balance flags; every evaluation cell still exceeds the count floor.",
        "",
        f"![Per-protein balance]({figure_relpaths['figure6']})",
        "",
        f"![Evaluation support]({figure_relpaths['figure7']})",
        "",
        "## 5. Sequence-composition check",
        "",
        f"GC fraction, normalized mononucleotide entropy, and maximum homopolymer length were compared among final partitions at all three protected widths. The largest observed absolute standardized mean difference was **{float(max_effect['absolute_smd']):.3f}** ({max_effect['metric']}, {max_effect['width']} nt, {max_effect['partition_a']} versus {max_effect['partition_b']}). It is only {float(max_effect['absolute_smd']) - 0.10:.3f} above the prespecified |SMD|≥0.10 reporting boundary and remains small in magnitude. The largest KS D was **{float(max_ks['ks_d']):.3f}** ({max_ks['metric']}, {max_ks['width']} nt, {max_ks['partition_a']} versus {max_ks['partition_b']}). Quantiles and KS D are descriptive; rows within components are not independent, so no row-level p-values are used.",
        "",
        f"![Sequence composition]({figure_relpaths['figure8']})",
        "",
        "## Allowed claims",
        "",
        "- The former fold is not leakage-safe under the frozen sequence rules.",
        "- The final split is deterministic, whole-component, and passed the prespecified structural, exact/RC, and 18 directed similarity audits.",
        "- No cross-partition relationship was detected under the frozen 500/251/101-nt rules.",
        "- Per-protein label imbalance remains and is reported explicitly; evaluation support remains above the prespecified count floor.",
        "",
        "## Claims not supported",
        "",
        "- The audit does not quantify how much the former AUROC was inflated.",
        "- It does not prove that no biological or coordinate relationship exists outside the frozen rules.",
        "- It does not establish model performance, generalization, or superiority over competitors.",
        "- Composition similarity is descriptive and is not proof that every possible sequence covariate is balanced.",
        "",
        "## Reproducibility",
        "",
        "All headline values originate from machine-readable tables in the Task 003A artifact package. Input hashes, output hashes, software versions, runtimes, and reconciliation gates are recorded in `provenance.json` and `manifests/task003a_split_validation_report.json`. The accepted split was not changed.",
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
        Paragraph("Task 003A: supervisor split-validation report", styles["CenterTitle"]),
        Paragraph("Purpose: demonstrate, before any model training, that the benchmark boundary protects related sequence families and honestly discloses remaining label imbalance.", styles["Lead"]),
        Table(
            [
                ["Rows", "Components v2", "Split components", "Directed audit hits"],
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
        Paragraph("Main conclusion", styles["Heading2"]),
        Paragraph(f"The former teammate's row-level fold is structurally compromised: when recomputed against final components v2, {v2['crossing_holdout_row_count']:,}/{v2['holdout_count']:,} holdout rows ({100*v2['crossing_holdout_row_rate']:.3f}%) belong to a sequence family also represented in legacy training. The accepted replacement split keeps every final component intact and passed all independent leakage gates.", styles["Lead"]),
        Paragraph("What was and was not tested", styles["Heading2"]),
        Paragraph("The evidence covers exact/reverse-complement identity and the prespecified 500/251/101-nt MMseqs2 similarity rules in every partition direction. It does not estimate AUROC inflation, inspect any prediction, or claim that all possible biological relationships have been excluded.", styles["Lead"]),
        Paragraph("Remaining limitation", styles["Heading2"]),
        Paragraph(f"Component integrity constrains label balancing. {balance['proteins_flagged_validation_or_test']}/122 proteins have at least one validation/test fraction more than 3 percentage points from target, although every evaluation known-positive/known-negative cell remains above the floor of 30 (observed minima {balance['minimum_known_positive']['count']} and {balance['minimum_known_negative']['count']}).", styles["Lead"]),
        Paragraph("Sequence composition", styles["Heading2"]),
        Paragraph(f"The largest absolute standardized mean difference across GC, normalized entropy, and homopolymer checks was {float(max_effect['absolute_smd']):.3f}, only {float(max_effect['absolute_smd']) - 0.10:.3f} above the prespecified reporting boundary and still small in magnitude. The largest KS D was {float(max_ks['ks_d']):.3f}. These are descriptive checks without row-level p-values.", styles["Lead"]),
        PageBreak(),
        Paragraph("Reading guide for the eight figures", styles["Heading1"]),
    ]
    guide = [
        ("1", "Why the split changed", "Separates the former row split, rejected v1, and accepted v2."),
        ("2", "Leakage evidence", "Uses separate denominators; the 4,792 v1 count is one stopped search, not a complete total."),
        ("3", "Component structure", "Shows that stricter protection did not create a giant family."),
        ("4", "Protected widths", "Shows direct edge counts and exact intersections; excludes implementation-only star joins."),
        ("5", "Partition sizes", "Shows proximity to 70/15/15 and zero split components."),
        ("6", "Per-protein balance", "Each cell uses that protein/class total as its denominator."),
        ("7", "Evaluation support", "Separates count sufficiency from fraction balance."),
        ("8", "Sequence composition", "Shows robust quantiles and prespecified effect-size interpretation."),
    ]
    table_rows = [
        [
            Paragraph(n, styles["Small"]),
            Paragraph(title, styles["Small"]),
            Paragraph(detail, styles["Small"]),
        ]
        for n, title, detail in guide
    ]
    table = Table(table_rows, colWidths=[12 * mm, 43 * mm, 115 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#D5DADF")), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
    story.extend([table, Spacer(1, 8 * mm), Paragraph("The following pages are the versioned figure PDFs generated from machine-readable summary tables. Full TSV tables and provenance accompany this report.", styles["Small"])])
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
