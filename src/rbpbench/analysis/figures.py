"""Deterministic ReportLab figures for Task 003A."""

from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
from typing import Mapping, Sequence

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
from reportlab.lib import colors

from rbpbench.analysis.split_validation import PARTITIONS


BLUE = colors.HexColor("#0072B2")
ORANGE = colors.HexColor("#E69F00")
GREEN = colors.HexColor("#009E73")
RED = colors.HexColor("#D55E00")
PURPLE = colors.HexColor("#CC79A7")
SKY = colors.HexColor("#56B4E9")
BLACK = colors.HexColor("#222222")
GREY = colors.HexColor("#777777")
LIGHT = colors.HexColor("#E8EDF2")
WHITE = colors.white
PARTITION_COLOR = {"train": BLUE, "validation": ORANGE, "test": GREEN}


def text(d: Drawing, x: float, y: float, value: str, *, size: float = 10, anchor: str = "start", color=BLACK, bold: bool = False) -> None:
    d.add(String(x, y, str(value), fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, textAnchor=anchor, fillColor=color))


def wrapped(d: Drawing, x: float, y: float, value: str, *, width_chars: int = 90, size: float = 8, leading: float | None = None, color=GREY) -> float:
    import textwrap

    leading = leading or size * 1.25
    for line in textwrap.wrap(value, width=width_chars):
        text(d, x, y, line, size=size, color=color)
        y -= leading
    return y


def title(d: Drawing, value: str, subtitle: str | None = None) -> None:
    text(d, 28, d.height - 34, value, size=17, bold=True)
    if subtitle:
        text(d, 28, d.height - 52, subtitle, size=9, color=GREY)


def save_figure(drawing: Drawing, figures_dir: Path, stem: str) -> dict[str, Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths = {suffix: figures_dir / f"{stem}.{suffix}" for suffix in ("svg", "pdf", "png")}
    renderSVG.drawToFile(drawing, str(paths["svg"]))
    renderPDF.drawToFile(drawing, str(paths["pdf"]))
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm (Poppler) is required for deterministic 300-dpi PNG export")
    completed = subprocess.run(
        [pdftoppm, "-png", "-r", "300", "-singlefile", str(paths["pdf"]), str(paths["png"].with_suffix(""))],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode or not paths["png"].is_file():
        raise RuntimeError(f"pdftoppm failed for {stem}: {completed.stderr}")
    return paths


def figure1_process() -> Drawing:
    d = Drawing(1000, 520)
    title(d, "Figure 1. Why the benchmark split had to change", "Three distinct states; no model result was used to construct or accept the final split")
    boxes = [
        (45, "Former row split", "Rows stratified independently", "Rejected: related sequences can cross"),
        (365, "v1 component split", "Tool cluster co-membership", "Rejected: direct audit found missed edges"),
        (685, "Accepted components v2", "Full direct edges + exact/RC + v1", "Accepted: all frozen audits passed"),
    ]
    for index, (x, heading, body, outcome) in enumerate(boxes):
        color = RED if index < 2 else GREEN
        d.add(Rect(x, 210, 270, 150, rx=8, ry=8, fillColor=colors.Color(color.red, color.green, color.blue, alpha=0.08), strokeColor=color, strokeWidth=2))
        text(d, x + 135, 326, heading, size=13, anchor="middle", bold=True)
        text(d, x + 135, 293, body, size=10, anchor="middle")
        text(d, x + 135, 245, outcome, size=9, anchor="middle", color=color, bold=True)
        if index < 2:
            d.add(Line(x + 275, 285, x + 315, 285, strokeColor=BLACK, strokeWidth=2))
            d.add(Line(x + 305, 292, x + 315, 285, strokeColor=BLACK, strokeWidth=2))
            d.add(Line(x + 305, 278, x + 315, 285, strokeColor=BLACK, strokeWidth=2))
    text(d, 180, 170, "Recorded former-fold crossing: 63.593% of holdout rows", size=10, anchor="middle", bold=True)
    text(d, 180, 151, "computed against rejected v1 components; lower bound under v2", size=8.5, anchor="middle", color=GREY)
    text(d, 500, 170, "First directed audit only: 4,792 pairs / 3,576 rows", size=10, anchor="middle", bold=True)
    text(d, 500, 151, "500 nt train→validation; 17/18 searches not run", size=8.5, anchor="middle", color=GREY)
    text(d, 820, 170, "0 detected relationships in 18/18 directed audits", size=10, anchor="middle", bold=True)
    text(d, 820, 151, "plus independent exact/reverse-complement audit", size=8.5, anchor="middle", color=GREY)
    wrapped(d, 45, 82, "Interpretation: the underlying dataset remains usable, but evaluation requires a boundary that keeps every protected sequence family together. The final statement is zero detected cross-partition relationships under the prespecified rules—not proof of zero possible biological relatedness.", width_chars=145, size=9)
    return d


def _bar(d: Drawing, x: float, y: float, width: float, height: float, fraction: float, color, label: str, value: str) -> None:
    d.add(Rect(x, y, width, height, fillColor=LIGHT, strokeColor=None))
    d.add(Rect(x, y, width * max(0, min(1, fraction)), height, fillColor=color, strokeColor=None))
    text(d, x, y + height + 7, label, size=8)
    text(d, x + width + 8, y + 3, value, size=8, bold=True)


def figure2_leakage(v1: Mapping, v2: Mapping) -> Drawing:
    d = Drawing(1050, 620)
    title(d, "Figure 2. Leakage evidence before and after correction", "Panels intentionally use separate denominators and scales")
    panel_x = (35, 375, 715)
    for x, label in zip(panel_x, ("A  Former fold crossing", "B  Rejected v1 audit", "C  Accepted v2 audits")):
        text(d, x, 530, label, size=12, bold=True)
        d.add(Line(x, 518, x + 300, 518, strokeColor=LIGHT))
    _bar(d, 45, 430, 235, 18, v1["crossing_holdout_row_rate"], RED, "v1 grouping: holdout rows", f"{100*v1['crossing_holdout_row_rate']:.3f}%")
    _bar(d, 45, 370, 235, 18, v1["crossing_train_row_rate"], RED, "v1 grouping: train rows", f"{100*v1['crossing_train_row_rate']:.3f}%")
    _bar(d, 45, 290, 235, 18, v2["crossing_holdout_row_rate"], PURPLE, "v2 grouping: holdout rows", f"{100*v2['crossing_holdout_row_rate']:.3f}%")
    _bar(d, 45, 230, 235, 18, v2["crossing_train_row_rate"], PURPLE, "v2 grouping: train rows", f"{100*v2['crossing_train_row_rate']:.3f}%")
    wrapped(d, 45, 170, "The accepted historical percentages used v1 components. Since v2 only merges v1 components, the v1 values are lower bounds; Task 003A recomputed the same legacy fold against v2.", width_chars=52, size=8)

    text(d, 390, 455, "4,792", size=32, bold=True, color=RED)
    text(d, 390, 430, "qualifying sequence pairs", size=10)
    text(d, 390, 380, "3,576", size=28, bold=True)
    text(d, 390, 357, "distinct affected rows", size=10)
    text(d, 390, 318, "1,400 train queries", size=10)
    text(d, 390, 296, "2,176 validation targets", size=10)
    text(d, 390, 245, "Only 1 of 18 searches ran", size=11, bold=True, color=RED)
    wrapped(d, 390, 220, "The audit stopped on the first failure (500 nt, train→validation). Therefore 4,792 is a lower bound, not v1's total leakage.", width_chars=48, size=8)

    cell_w, cell_h = 43, 42
    directions = ("Tr→V", "V→Tr", "Tr→Te", "Te→Tr", "V→Te", "Te→V")
    for col, direction in enumerate(directions):
        text(d, 755 + col * cell_w, 477, direction, size=7, anchor="middle")
    for row, width in enumerate((500, 251, 101)):
        y = 420 - row * 72
        text(d, 730, y + 13, str(width), size=9, anchor="end", bold=True)
        for col in range(6):
            x = 735 + col * cell_w
            d.add(Rect(x, y, 35, 35, fillColor=colors.Color(GREEN.red, GREEN.green, GREEN.blue, alpha=0.20), strokeColor=GREEN))
            text(d, x + 17.5, y + 11, "0", size=10, anchor="middle", color=GREEN, bold=True)
        text(d, 735, y - 16, "positive control passed (once for this width)", size=7.5, color=GREY)
    text(d, 735, 170, "18 / 18 directed searches completed", size=11, bold=True, color=GREEN)
    text(d, 735, 145, "0 exact/RC cross-partition groups", size=10)
    text(d, 735, 122, "0 audit-discovered remediation edges", size=10)
    wrapped(d, 35, 72, "No panel estimates AUROC inflation. These are structural leakage diagnostics with different units: component/row rates, pair/row counts from one stopped search, and a complete final audit matrix.", width_chars=160, size=9)
    return d


def figure3_components(distribution: Sequence[Mapping], closure: Mapping) -> Drawing:
    d = Drawing(1000, 610)
    title(d, "Figure 3. Component structure remained usable after stricter protection", "Complementary cumulative component-size distributions; log scales")
    x0, y0, w, h = 90, 120, 560, 390
    d.add(Rect(x0, y0, w, h, fillColor=None, strokeColor=GREY))
    grouped = {"v1": [], "v2": []}
    for row in distribution:
        grouped[str(row["grouping"])].append(row)
    all_sizes = [float(r["component_size"]) for rows in grouped.values() for r in rows]
    max_size = max(all_sizes)
    max_count = max(float(r["components_ge_size"]) for rows in grouped.values() for r in rows)
    def sx(value): return x0 + math.log10(max(1, value)) / math.log10(max_size) * w
    def sy(value): return y0 + math.log10(max(1, value)) / math.log10(max_count) * h
    for power in range(0, int(math.log10(max_size)) + 1):
        value = 10**power
        x = sx(value)
        d.add(Line(x, y0, x, y0 + h, strokeColor=LIGHT))
        text(d, x, y0 - 18, f"{value:,}", size=8, anchor="middle")
    for power in range(0, int(math.log10(max_count)) + 1):
        value = 10**power
        y = sy(value)
        d.add(Line(x0, y, x0 + w, y, strokeColor=LIGHT))
        text(d, x0 - 10, y - 3, f"{value:,}", size=8, anchor="end")
    for name, color in (("v1", RED), ("v2", BLUE)):
        points = [(sx(float(r["component_size"])), sy(float(r["components_ge_size"]))) for r in grouped[name]]
        d.add(PolyLine(points, strokeColor=color, strokeWidth=2.5))
    text(d, x0 + w / 2, 83, "Component size (rows)", size=10, anchor="middle")
    text(d, 25, y0 + h / 2, "Components at least this size", size=9)
    d.add(Line(710, 480, 735, 480, strokeColor=RED, strokeWidth=3)); text(d, 745, 476, "v1 (rejected)", size=9)
    d.add(Line(710, 455, 735, 455, strokeColor=BLUE, strokeWidth=3)); text(d, 745, 451, "v2 (accepted)", size=9)
    stats = [
        ("v1 components", "173,465"),
        ("v2 components", f"{closure['universe']['component_count']:,}"),
        ("v2 singletons", f"{closure['universe']['singleton_count']:,}"),
        ("largest v2 component", f"{closure['universe']['largest_component_size']:,} rows ({100*closure['universe']['largest_component_fraction']:.3f}%)"),
        ("largest 20 v2", f"{100*closure['universe']['top20_component_fraction']:.3f}% of rows"),
        ("single-component gate", "5% — passed"),
        ("top-20 gate", "20% — passed"),
    ]
    y = 405
    for label, value in stats:
        text(d, 710, y, label, size=8, color=GREY)
        text(d, 955, y, value, size=8, anchor="end", bold=True)
        y -= 34
    wrapped(d, 90, 48, "The stricter v2 relation merged additional related rows but did not create a dominant component. Whole-component partitioning therefore remained feasible.", width_chars=130, size=9)
    return d


def figure4_edges(direct_counts: Mapping[int, int], overlap: Sequence[Mapping], exact_rc_count: int) -> Drawing:
    d = Drawing(1000, 610)
    title(d, "Figure 4. Protected sequence relationships by input width", "Direct-edge counts and exact edge-set intersections; no order-dependent union count is shown")
    max_count = max(direct_counts.values())
    x0, y0, bw = 85, 250, 150
    for index, width in enumerate((500, 251, 101)):
        x = x0 + index * 190
        height = 230 * direct_counts[width] / max_count
        d.add(Rect(x, y0, bw, height, fillColor=(BLUE, ORANGE, GREEN)[index], strokeColor=None))
        text(d, x + bw / 2, y0 - 23, f"{width} nt", size=10, anchor="middle", bold=True)
        text(d, x + bw / 2, y0 + height + 10, f"{direct_counts[width]:,}", size=10, anchor="middle", bold=True)
    text(d, 315, 210, "Qualifying direct edges", size=10, anchor="middle")
    text(d, 665, 485, "Exact intersection categories", size=11, bold=True)
    max_overlap = max(int(row["edge_count"]) for row in overlap)
    y = 445
    for row in sorted(overlap, key=lambda r: int(r["edge_count"]), reverse=True):
        count = int(row["edge_count"])
        text(d, 630, y + 4, str(row["category"]), size=8, anchor="end")
        d.add(Rect(645, y, 265 * count / max_overlap if max_overlap else 0, 13, fillColor=SKY, strokeColor=None))
        text(d, 920, y + 2, f"{count:,}", size=8, bold=True)
        y -= 37
    text(d, 75, 140, f"Independent exact/reverse-complement relations: {exact_rc_count:,} pair(s)", size=9, bold=True)
    text(d, 75, 116, "v1 protection: 6,406 v1 components merged into 2,640 v2 components", size=9, bold=True)
    text(d, 75, 96, "Rows covered by those v1→v2 merges: 54,610", size=9)
    wrapped(d, 75, 64, "The stored protected-v1 star-join count is intentionally omitted: it is an implementation artifact (members−1), not a count of biological or direct-similarity pairs.", width_chars=140, size=8)
    return d


def figure5_partitions(closure: Mapping) -> Drawing:
    d = Drawing(900, 540)
    title(d, "Figure 5. Final partition sizes and component integrity", "Targets guide assignment; whole components are never split to force exact percentages")
    x0, y0, w = 120, 150, 580
    for index, partition in enumerate(PARTITIONS):
        y = 385 - index * 95
        achieved = float(closure["partition_fractions"][partition])
        target = {"train": 0.7, "validation": 0.15, "test": 0.15}[partition]
        d.add(Rect(x0, y, w, 28, fillColor=LIGHT, strokeColor=None))
        d.add(Rect(x0, y, w * achieved, 28, fillColor=PARTITION_COLOR[partition], strokeColor=None))
        d.add(Line(x0 + w * target, y - 8, x0 + w * target, y + 36, strokeColor=BLACK, strokeWidth=2))
        text(d, x0 - 15, y + 8, partition.title(), size=10, anchor="end", bold=True)
        text(d, x0 + w + 12, y + 8, f"{closure['partition_row_counts'][partition]:,} rows  ({100*achieved:.2f}%)", size=10)
        text(d, x0 + w * target, y + 42, f"target {100*target:.0f}%", size=7, anchor="middle", color=GREY)
    text(d, 120, 95, f"0 / {closure['universe']['component_count']:,} components split across partitions", size=14, bold=True, color=GREEN)
    wrapped(d, 120, 65, "The 68.11/15.94/15.95% outcome is close to 70/15/15 while preserving the scientifically required unit: every connected sequence family stays entirely in one partition.", width_chars=115, size=9)
    return d


def _diverging(value: float, limit: float = 20.0):
    value = max(-limit, min(limit, value)) / limit
    if value < 0:
        t = -value
        return colors.Color(WHITE.red * (1 - t) + BLUE.red * t, WHITE.green * (1 - t) + BLUE.green * t, WHITE.blue * (1 - t) + BLUE.blue * t)
    return colors.Color(WHITE.red * (1 - value) + ORANGE.red * value, WHITE.green * (1 - value) + ORANGE.green * value, WHITE.blue * (1 - value) + ORANGE.blue * value)


def figure6_balance(rows: Sequence[Mapping], balance_summary: Sequence[Mapping]) -> Drawing:
    d = Drawing(1200, 1500)
    title(d, "Figure 6. Per-protein known-label balance", "Cell value = partition share minus 70/15/15 target (percentage points); rows ordered by evaluation deviation")
    order = [int(r["protein_id"]) for r in sorted(balance_summary, key=lambda r: (-float(r["max_abs_deviation_pp_evaluation"]), int(r["protein_id"])))]
    lookup = {(int(r["protein_id"]), str(r["label_class"]), str(r["partition"])): r for r in rows}
    panel = {"positive": 80, "negative": 630}
    cell_w, row_h = 58, 10.6
    top = 1380
    for label_class in ("positive", "negative"):
        x0 = panel[label_class]
        text(d, x0, 1420, f"Known {label_class}s", size=12, bold=True)
        for col, partition in enumerate(PARTITIONS):
            text(d, x0 + 310 + col * cell_w + cell_w / 2, 1395, partition[:5], size=8, anchor="middle")
        for row_index, protein_id in enumerate(order):
            y = top - row_index * row_h
            first = lookup[(protein_id, label_class, "train")]
            name = str(first["protein_name"])
            total = int(first["protein_class_total"])
            text(d, x0 + 265, y + 1.5, f"{protein_id:03d} {name}", size=6.3, anchor="end", color=BLACK)
            text(d, x0 + 585, y + 1.5, f"n={total:,}", size=6.3, color=GREY)
            for col, partition in enumerate(PARTITIONS):
                item = lookup[(protein_id, label_class, partition)]
                value = float(item["deviation_percentage_points"])
                x = x0 + 310 + col * cell_w
                d.add(Rect(x, y - 2, cell_w - 2, row_h, fillColor=_diverging(value), strokeColor=None))
                if abs(value) > 3:
                    d.add(Rect(x + 1, y - 1, cell_w - 4, row_h - 2, fillColor=None, strokeColor=BLACK, strokeWidth=0.5))
                text(d, x + cell_w / 2 - 1, y + 1.3, f"{value:+.1f}", size=5.8, anchor="middle")
    text(d, 80, 55, "Blue = below target; orange = above target; outlined cells exceed the strict ±3-percentage-point reporting boundary.", size=8)
    text(d, 80, 35, "Global achieved row fractions (68.11/15.94/15.95%) are context only; flags remain defined against the prespecified 70/15/15 targets.", size=8, color=GREY)
    return d


def figure7_support(rows: Sequence[Mapping]) -> Drawing:
    d = Drawing(1050, 590)
    title(d, "Figure 7. Evaluation support for every protein", "Known-positive and known-negative counts in validation and test; logarithmic count scale")
    x0, y0, w, h = 80, 110, 880, 370
    d.add(Rect(x0, y0, w, h, fillColor=None, strokeColor=GREY))
    lookup = {(int(r["protein_id"]), str(r["label_class"]), str(r["partition"])): int(r["count"]) for r in rows}
    all_counts = [value for key, value in lookup.items() if key[2] != "train"]
    max_count = max(all_counts)
    def sx(pid): return x0 + (pid - 1) / 121 * w
    def sy(value): return y0 + (math.log10(value) - math.log10(30)) / (math.log10(max_count) - math.log10(30)) * h
    for value in (30, 100, 300, 1000):
        if value <= max_count:
            y = sy(value)
            d.add(Line(x0, y, x0 + w, y, strokeColor=RED if value == 30 else LIGHT, strokeWidth=1.5 if value == 30 else 1))
            text(d, x0 - 10, y - 3, str(value), size=8, anchor="end", color=RED if value == 30 else GREY)
    series = [
        ("validation", "positive", ORANGE, 3.2),
        ("validation", "negative", PURPLE, 2.2),
        ("test", "positive", GREEN, 3.2),
        ("test", "negative", SKY, 2.2),
    ]
    for partition, label_class, color, radius in series:
        for protein_id in range(1, 123):
            d.add(Circle(sx(protein_id), sy(lookup[(protein_id, label_class, partition)]), radius, fillColor=color, strokeColor=None))
    for value in (1, 20, 40, 60, 80, 100, 122):
        text(d, sx(value), y0 - 20, str(value), size=8, anchor="middle")
    text(d, x0 + w / 2, 70, "Protein ID", size=10, anchor="middle")
    text(d, x0, 505, "● validation positive", size=8, color=ORANGE)
    text(d, x0 + 155, 505, "● validation negative", size=8, color=PURPLE)
    text(d, x0 + 320, 505, "● test positive", size=8, color=GREEN)
    text(d, x0 + 450, 505, "● test negative", size=8, color=SKY)
    text(d, 720, 505, "Hard floor = 30", size=9, color=RED, bold=True)
    text(d, 80, 35, "Observed minima: 97 known positives (protein 93, test) and 80 known negatives (protein 53, test). Count sufficiency does not imply perfect fraction balance.", size=8)
    return d


def figure8_composition(summaries: Sequence[Mapping], effects: Sequence[Mapping]) -> Drawing:
    d = Drawing(1150, 940)
    title(d, "Figure 8. Sequence composition is similar across final partitions", "Whiskers: 5th–95th percentiles; thick bars: 25th–75th; points: medians")
    summary = {(int(r["width"]), str(r["metric"]), str(r["partition"])): r for r in summaries}
    effect_groups: dict[tuple[int, str], list[float]] = {}
    for row in effects:
        effect_groups.setdefault((int(row["width"]), str(row["metric"])), []).append(abs(float(row["standardized_mean_difference"])))
    metrics = (("gc_fraction", "GC fraction"), ("normalized_entropy", "Normalized entropy"), ("max_homopolymer", "Maximum homopolymer (nt)"))
    for row_index, width in enumerate((500, 251, 101)):
        for col_index, (metric, label) in enumerate(metrics):
            x0 = 55 + col_index * 365
            y0 = 610 - row_index * 255
            w, h = 300, 155
            records = [summary[(width, metric, p)] for p in PARTITIONS]
            low = min(float(r["q05"]) for r in records)
            high = max(float(r["q95"]) for r in records)
            if high == low:
                high = low + 1
            pad = (high - low) * 0.06
            low -= pad; high += pad
            def sx(v): return x0 + 92 + (float(v) - low) / (high - low) * (w - 100)
            text(d, x0, y0 + h + 28, f"{width} nt — {label}", size=9, bold=True)
            d.add(Rect(x0 + 92, y0, w - 100, h, fillColor=None, strokeColor=LIGHT))
            for part_index, partition in enumerate(PARTITIONS):
                r = records[part_index]
                y = y0 + h - 35 - part_index * 45
                text(d, x0 + 82, y - 3, partition[:5], size=7.5, anchor="end")
                color = PARTITION_COLOR[partition]
                d.add(Line(sx(r["q05"]), y, sx(r["q95"]), y, strokeColor=color, strokeWidth=1.5))
                d.add(Line(sx(r["q25"]), y, sx(r["q75"]), y, strokeColor=color, strokeWidth=7))
                d.add(Circle(sx(r["median"]), y, 4, fillColor=BLACK, strokeColor=None))
            max_smd = max(effect_groups[(width, metric)])
            text(d, x0 + w, y0 - 17, f"max |SMD| = {max_smd:.3f}", size=7.5, anchor="end", color=RED if max_smd >= 0.10 else GREY, bold=max_smd >= 0.10)
            text(d, x0 + 92, y0 - 17, f"{low:.3g}", size=6.5)
            text(d, x0 + w, y0 - 17, "", size=6.5)
    text(d, 55, 32, "Prespecified interpretation: |SMD| ≥ 0.10 is notable; smaller effects are negligible. KS D and robust quantiles are descriptive; no row-level p-values are used.", size=8)
    return d
