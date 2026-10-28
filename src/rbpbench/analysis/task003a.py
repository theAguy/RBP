"""Transactional Task 003A analysis and report runner."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid

from rbpbench.analysis.figures import (
    figure1_process,
    figure2_leakage,
    figure3_components,
    figure4_edges,
    figure5_partitions,
    figure6_balance,
    figure7_support,
    figure8_composition,
    save_figure,
)
from rbpbench.analysis.reporting import build_markdown, build_supervisor_pdf
from rbpbench.analysis.split_validation import (
    PARTITIONS,
    ROW_COUNT,
    WIDTHS,
    ValidationError,
    component_distribution,
    composition_analysis,
    crossing_report,
    edge_overlap_counts,
    read_edge_set_from_zip,
    read_fold_codes,
    read_gzip_membership,
    read_proteins,
    read_tsv,
    read_zip_membership,
    require_file,
    sha256_bytes,
    sha256_file,
    stream_label_counts,
    summarize_protein_balance,
    verify_component_partition_integrity,
    verify_return_archive,
    write_tsv,
)


FINAL_RETURN_SIZE = 65_438_907
FINAL_RETURN_SHA256 = "ee781d1266b0b589dea7b05857eadd2a60fc311bc0a60d4d6c5b69854f210091"
CSV_SIZE = 724_425_277
CSV_SHA256 = "982c812631ce277ea95e10bd591b6d77b66bf3a8ed71b4120f1d65854107a945"
V1_MEMBERSHIP_SIZE = 14_578_797
V1_MEMBERSHIP_SHA256 = "6000c340056ba8204432e7f4c417fb811f8a3d1a5b1c091dea98461862c7b692"
V1_REPORT_SIZE = 13_036_977
V1_REPORT_SHA256 = "b8b5872a4cc5061c562de871ec4500876fcdb72afcab069b21ab2bb44cb3e186"
V1_AUDIT_RETURN_SIZE = 433_289
V1_AUDIT_RETURN_SHA256 = "d84b7b1125e9bf8ad8e60aba717dbdf119d53c1c5ada7465c3f42a99adb610cf"


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def locate_v1_audit_return(root: Path) -> Path:
    candidates = [
        root / "artifacts/teammate_run_results/RBP_002C3_RETURN_20261004T101131Z_Mayans-MBP.zip",
        root / "artifacts/teammate_run_results/return.zip",
    ]
    for path in candidates:
        if path.is_file() and path.stat().st_size == V1_AUDIT_RETURN_SIZE and sha256_file(path) == V1_AUDIT_RETURN_SHA256:
            return path
    raise ValidationError("accepted rejected-v1 audit return was not found under its frozen size/hash")


def verify_inputs(root: Path) -> dict:
    expected = {
        "closure_manifest": (root / "manifests/sequence_partitions_002c_v2.json", None, "b6f6f16fab4e6afc23c16a8dc5b3476130719d579f637cd3cf18002cc7fb7419"),
        "non_mmseqs_manifest": (root / "manifests/sequence_non_mmseqs_audits_002c2c.json", None, "991a43a61fcdcbfa0aa5734fd8bf7801b029cc34a02ad1d3b400b1c5773d31e8"),
        "v1_assignment_manifest": (root / "manifests/sequence_assignment_002c2b.json", None, "28aa6687fc335ffcba36eb441ebf2d55ae25565349fc8dfcb48a29be566267f6"),
        "dataset_audit": (root / "manifests/dataset_audit.json", None, "e53e02c665f90021974471bf8972bcf8d6fd384f9439f4d630e68773be856b5c"),
        "proteins": (root / "configs/proteins.tsv", None, "374e09ea1a32e8bd335ad25b57e189c08a537c4edee8700d533d95e87eaadad9"),
        "decode_manifest": (root / "manifests/sequence_decode_002b2.json", None, "d9826b471ef3f12539eaf51be5c21ba8be20190f3d7c6042143e839d6bb0a7b3"),
        "csv": (root / "dataset_K562_multilabel_with_NEGs.csv", CSV_SIZE, CSV_SHA256),
        "v1_membership": (root / "artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_membership.tsv.gz", V1_MEMBERSHIP_SIZE, V1_MEMBERSHIP_SHA256),
        "v1_report": (root / "artifacts/teammate_run_results/20260928T091014Z_87391_arm64/final_component_result/component_report.json", V1_REPORT_SIZE, V1_REPORT_SHA256),
    }
    evidence = {name: require_file(path, size=size, sha256=digest) for name, (path, size, digest) in expected.items()}
    v1_audit = locate_v1_audit_return(root)
    evidence["v1_audit_return"] = require_file(v1_audit, size=V1_AUDIT_RETURN_SIZE, sha256=V1_AUDIT_RETURN_SHA256)
    decode = json.loads((root / "manifests/sequence_decode_002b2.json").read_text())
    retained = {Path(item["path"]).name: item for item in decode["retained_artifacts"]}
    for width in WIDTHS:
        name = f"sequence_partitions_width_{width}.fasta"
        item = retained[name]
        path = root / item["path"]
        evidence[f"fasta_{width}"] = require_file(path, size=item["byte_size"], sha256=item["sha256"])
    return evidence


def run_legacy_export(root: Path, candidate: Path, legacy_python: Path) -> tuple[bytearray, dict]:
    if not legacy_python.is_file():
        raise ValidationError(f"pinned legacy Python is missing: {legacy_python}")
    scratch = candidate / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    output = scratch / "legacy_fold.tsv.gz"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    command = [
        str(legacy_python),
        "-m",
        "rbpbench.analysis.legacy_fold_export",
        "--csv",
        str(root / "dataset_K562_multilabel_with_NEGs.csv"),
        "--output",
        str(output),
    ]
    completed = subprocess.run(command, cwd=root, env=env, text=True, capture_output=True, timeout=1800, check=False)
    (scratch / "legacy_fold.stdout.log").write_text(completed.stdout)
    (scratch / "legacy_fold.stderr.log").write_text(completed.stderr)
    if completed.returncode:
        raise ValidationError(f"legacy-fold reproduction failed with exit {completed.returncode}: {completed.stderr[-2000:]}")
    return read_fold_codes(output)


def verify_v1_report(path: Path, membership) -> dict:
    report = json.loads(path.read_text())
    if report.get("total_rows") != ROW_COUNT or report.get("component_count") != 173_465:
        raise ValidationError("v1 component report count mismatch")
    recorded = {str(key): int(value) for key, value in report.get("component_sizes", {}).items()}
    derived = {membership.component_ids[index]: size for index, size in enumerate(membership.component_sizes)}
    if recorded != derived:
        raise ValidationError("v1 membership component sizes do not reproduce the accepted report")
    return report


def read_zip_json(archive, root: str, rel: str):
    return json.loads(archive.read(f"{root}/{rel}"))


def reconcile_label_counts(rows, assignment_summary: dict) -> None:
    actual = {(str(row["partition"]), str(row["protein_id"])): (0, 0) for row in rows}
    mutable: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        key = (str(row["partition"]), str(row["protein_id"]))
        mutable.setdefault(key, [0, 0])[0 if row["label_class"] == "positive" else 1] = int(row["count"])
    for partition, by_protein in assignment_summary["partition_label_counts"].items():
        for protein_id, accepted in by_protein.items():
            if mutable[(partition, protein_id)] != [int(accepted[0]), int(accepted[1])]:
                raise ValidationError(f"fresh label count disagrees with assignment summary for {partition}/protein {protein_id}")


def audit_matrix(archive, root: str) -> list[dict]:
    result = []
    for width in WIDTHS:
        prep = read_zip_json(archive, root, f"records/selected/cycle1_auditprep_{width}.json")
        if prep["payload"].get("positive_control_passed") is not True:
            raise ValidationError(f"positive control failed for width {width}")
        counts = prep["payload"]["partitions"]
        for query, target in (("train", "validation"), ("validation", "train"), ("train", "test"), ("test", "train"), ("validation", "test"), ("test", "validation")):
            record = read_zip_json(archive, root, f"records/selected/cycle1_audit_{width}_{query}_to_{target}.json")
            payload = record["payload"]
            if payload != {"cycle": 1, "query": query, "target": target, "violation_count": 0, "width": width}:
                raise ValidationError(f"unexpected audit payload for {width}/{query}->{target}: {payload}")
            result.append(
                {
                    "width": width,
                    "query_partition": query,
                    "target_partition": target,
                    "query_count": counts[query],
                    "target_count": counts[target],
                    "positive_control_passed_for_width": True,
                    "violation_count": 0,
                }
            )
    return result


def exact_rc_edge_count(root: Path) -> int:
    decode = json.loads((root / "manifests/sequence_decode_002b2.json").read_text())
    count = 0
    for width in WIDTHS:
        path = root / next(item["path"] for item in decode["retained_artifacts"] if Path(item["path"]).name == f"duplicate_edges_{width}.json")
        pairs = json.loads(path.read_text())
        count += len(pairs)
    return count


def write_split_summary(path: Path, closure: Mapping, v1: Mapping, v2: Mapping) -> list[dict]:
    rows = [
        {"section": "universe", "metric": "rows", "grouping": "v2", "value": ROW_COUNT, "numerator": "", "denominator": "", "unit": "rows", "note": "canonical row universe"},
        {"section": "universe", "metric": "components", "grouping": "v1", "value": 173465, "numerator": "", "denominator": "", "unit": "components", "note": "rejected grouping"},
        {"section": "universe", "metric": "components", "grouping": "v2", "value": closure["universe"]["component_count"], "numerator": "", "denominator": "", "unit": "components", "note": "accepted grouping"},
        {"section": "former_fold", "metric": "affected_holdout_rate", "grouping": "v1", "value": v1["crossing_holdout_row_rate"], "numerator": v1["crossing_holdout_row_count"], "denominator": v1["holdout_count"], "unit": "fraction", "note": "accepted historical result; lower bound under v2"},
        {"section": "former_fold", "metric": "affected_train_rate", "grouping": "v1", "value": v1["crossing_train_row_rate"], "numerator": v1["crossing_train_row_count"], "denominator": v1["train_count"], "unit": "fraction", "note": "accepted historical result; lower bound under v2"},
        {"section": "former_fold", "metric": "affected_holdout_rate", "grouping": "v2", "value": v2["crossing_holdout_row_rate"], "numerator": v2["crossing_holdout_row_count"], "denominator": v2["holdout_count"], "unit": "fraction", "note": "Task 003A recomputation after fold-digest reproduction"},
        {"section": "former_fold", "metric": "affected_train_rate", "grouping": "v2", "value": v2["crossing_train_row_rate"], "numerator": v2["crossing_train_row_count"], "denominator": v2["train_count"], "unit": "fraction", "note": "Task 003A recomputation after fold-digest reproduction"},
        {"section": "rejected_v1_audit", "metric": "qualifying_pairs", "grouping": "v1", "value": 4792, "numerator": "", "denominator": "", "unit": "pairs", "note": "first directed search only; 500 nt train-to-validation; 17/18 not run"},
        {"section": "rejected_v1_audit", "metric": "distinct_rows", "grouping": "v1", "value": 3576, "numerator": 1400, "denominator": 2176, "unit": "rows", "note": "train queries / validation targets; not a rate"},
        {"section": "accepted_v2_audit", "metric": "directed_searches_completed", "grouping": "v2", "value": 18, "numerator": 18, "denominator": 18, "unit": "searches", "note": "all frozen width/direction combinations"},
        {"section": "accepted_v2_audit", "metric": "cross_partition_hits", "grouping": "v2", "value": 0, "numerator": 0, "denominator": 18, "unit": "hits", "note": "positive controls passed per width"},
    ]
    for partition in PARTITIONS:
        rows.append({"section": "partition", "metric": "row_fraction", "grouping": partition, "value": closure["partition_fractions"][partition], "numerator": closure["partition_row_counts"][partition], "denominator": ROW_COUNT, "unit": "fraction", "note": "final accepted membership"})
    write_tsv(path, rows)
    return rows


def build_artifact_readme(results: Mapping) -> str:
    return f"""# Task 003A split-validation artifact

This package is the model-blind supervisor report for the accepted Task 002C
sequence split. It contains eight figures in SVG/PDF/300-dpi PNG, all numerical
source tables, the supervisor PDF, and provenance.

Key accepted result: {results['closure']['universe']['component_count']:,}
components, zero split components, zero exact/RC cross-partition groups, and
zero qualifying hits in all 18 directed final audits.

The package does not contain sequences, row-level labels, predictions, or model
metrics. TSV tables are the numerical source of truth.
"""


def output_inventory(root: Path, *, exclude: set[str] | None = None) -> list[dict]:
    exclude = exclude or set()
    result = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel in exclude:
            continue
        result.append({"path": rel, "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def run(args) -> Path:
    started = time.time()
    root = args.repo_root.resolve()
    output_root = args.output_dir.resolve()
    if output_root == root or root not in output_root.parents:
        raise ValidationError("output directory must be a descendant of the repository root")
    inputs = verify_inputs(root)
    closure = json.loads((root / "manifests/sequence_partitions_002c_v2.json").read_text())
    non_mmseq = json.loads((root / "manifests/sequence_non_mmseqs_audits_002c2c.json").read_text())

    generation_name = f"task003a_{uuid.uuid4().hex[:12]}"
    candidate = output_root / f".{generation_name}.candidate"
    final_generation = output_root / "generations" / generation_name
    if candidate.exists() or final_generation.exists():
        raise ValidationError("generation collision")
    candidate.mkdir(parents=True)
    try:
        # Preserve the venv launcher path itself: Path.resolve() follows its
        # python symlink to the base interpreter and would lose venv context.
        legacy_python = Path(os.path.abspath(args.legacy_python))
        fold_codes, fold_metadata = run_legacy_export(root, candidate, legacy_python)

        v1_membership = read_gzip_membership(Path(inputs["v1_membership"]["path"]))
        if v1_membership.component_count != 173_465:
            raise ValidationError(f"v1 membership reconstructed {v1_membership.component_count} components")
        verify_v1_report(Path(inputs["v1_report"]["path"]), v1_membership)
        v1_crossing = crossing_report(v1_membership, fold_codes)
        accepted_v1 = non_mmseq["legacy_diagnostic_report"]["component_crossing"]
        expected_pairs = {
            "components_represented_in_holdout": accepted_v1["components_represented_in_holdout"],
            "crossing_component_count": accepted_v1["crossing_component_count"],
            "crossing_holdout_row_count": accepted_v1["crossing_holdout_row_count"],
            "crossing_train_row_count": accepted_v1["crossing_train_row_count"],
        }
        for key, expected in expected_pairs.items():
            if v1_crossing[key] != expected:
                raise ValidationError(f"v1 former-fold reproduction mismatch for {key}: {v1_crossing[key]} != {expected}")

        archive_path = Path(closure["production_return"]["path"])
        archive, archive_root, _inventory = verify_return_archive(
            root / archive_path,
            expected_size=FINAL_RETURN_SIZE,
            expected_sha256=FINAL_RETURN_SHA256,
            sidecar=root / (str(archive_path) + ".sha256"),
        )
        with archive:
            final_membership = read_zip_membership(archive, f"{archive_root}/final/membership.tsv.gz", with_partition=True)
            if final_membership.component_count != closure["universe"]["component_count"]:
                raise ValidationError("final membership component count mismatch")
            integrity = verify_component_partition_integrity(final_membership)
            if integrity["split_component_count"] != 0 or integrity["partition_rows"] != closure["partition_row_counts"]:
                raise ValidationError("final component/partition reconciliation failed")
            v2_crossing = crossing_report(final_membership, fold_codes)
            assignment_summary = read_zip_json(archive, archive_root, "reports/cycle1_assignment/assignment_summary.json")
            audits = audit_matrix(archive, archive_root)
            edge_sets = {width: read_edge_set_from_zip(archive, f"{archive_root}/edges/normalized_edges_{width}.tsv.gz") for width in WIDTHS}
            for width, expected in closure["direct_edges"].items():
                if len(edge_sets[int(width)]) != expected:
                    raise ValidationError(f"width-{width} edge count mismatch")
            overlap = edge_overlap_counts(edge_sets)
            del edge_sets

        proteins = read_proteins(root / "configs/proteins.tsv")
        protein_rows, balance = stream_label_counts(root / "dataset_K562_multilabel_with_NEGs.csv", final_membership.row_partition, proteins)
        reconcile_label_counts(protein_rows, assignment_summary)
        if balance != closure["balance_disclosure"] | {
            "minimum_known_positive": closure["label_floor"]["minimum_known_positive"],
            "minimum_known_negative": closure["label_floor"]["minimum_known_negative"],
        }:
            raise ValidationError(f"fresh label-balance summary does not reproduce closure: {balance}")
        protein_summary = summarize_protein_balance(protein_rows)

        tables = candidate / "tables"
        split_rows = write_split_summary(tables / "split_summary.tsv", closure, v1_crossing, v2_crossing)
        component_rows = component_distribution(v1_membership.component_sizes, "v1") + component_distribution(final_membership.component_sizes, "v2")
        write_tsv(tables / "component_size_distribution.tsv", component_rows)
        write_tsv(tables / "edge_width_overlap.tsv", overlap)
        write_tsv(tables / "protein_partition_counts.tsv", protein_rows)
        write_tsv(tables / "protein_balance_summary.tsv", protein_summary)
        write_tsv(tables / "audit_matrix.tsv", audits)

        composition_summaries = []
        composition_effects = []
        for width in WIDTHS:
            summary_rows, effect_rows = composition_analysis(Path(inputs[f"fasta_{width}"]["path"]), width=width, row_partition=final_membership.row_partition)
            composition_summaries.extend(summary_rows)
            composition_effects.extend(effect_rows)
        write_tsv(tables / "sequence_composition_summary.tsv", composition_summaries)
        write_tsv(tables / "sequence_composition_effects.tsv", composition_effects)

        results = {
            "status": "complete",
            "closure": closure,
            "former_fold_v1": v1_crossing,
            "former_fold_v2": v2_crossing,
            "legacy_fold": fold_metadata,
            "balance": balance,
            "component_integrity": integrity,
            "direct_edge_counts": {str(width): closure["direct_edges"][str(width)] for width in WIDTHS},
            "exact_rc_edge_count": exact_rc_edge_count(root),
            "audit_searches": len(audits),
            "audit_violations": sum(int(row["violation_count"]) for row in audits),
        }
        (candidate / "results.json").write_bytes(json_bytes(results))

        figures = candidate / "figures"
        drawings = [
            ("figure_01_split_transition", figure1_process()),
            ("figure_02_leakage_evidence", figure2_leakage(v1_crossing, v2_crossing)),
            ("figure_03_component_structure", figure3_components(component_rows, closure)),
            ("figure_04_width_edges", figure4_edges({int(k): int(v) for k, v in closure["direct_edges"].items()}, overlap, results["exact_rc_edge_count"])),
            ("figure_05_partition_integrity", figure5_partitions(closure)),
            ("figure_06_protein_balance", figure6_balance(protein_rows, protein_summary)),
            ("figure_07_evaluation_support", figure7_support(protein_rows)),
            ("figure_08_sequence_composition", figure8_composition(composition_summaries, composition_effects)),
        ]
        figure_paths = {}
        for stem, drawing in drawings:
            figure_paths[stem] = save_figure(drawing, figures, stem)

        artifact_links = {f"figure{index}": f"figures/{stem}.svg" for index, (stem, _) in enumerate(drawings, 1)}
        artifact_report = build_markdown(results, composition_effects, artifact_links)
        (candidate / "supervisor_report.md").write_text(artifact_report)
        build_supervisor_pdf(candidate / "supervisor_report.pdf", [figure_paths[stem]["pdf"] for stem, _ in drawings], results, composition_effects)
        (candidate / "README.md").write_text(build_artifact_readme(results))

        # The reproduced row-level legacy fold is scratch evidence only.  Its
        # accepted index digests and aggregate crossing results are retained;
        # row assignments and subprocess logs are excluded from the package.
        shutil.rmtree(candidate / "scratch")

        provenance = {
            "schema_version": "task003a_provenance_v1",
            "task": "003A",
            "model_or_prediction_accessed": False,
            "split_modified": False,
            "input_evidence": inputs,
            "legacy_fold": fold_metadata,
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
                "numpy": __import__("numpy").__version__,
                "reportlab": __import__("reportlab").Version,
                "pypdf": __import__("pypdf").__version__,
                "pdftoppm": subprocess.run([shutil.which("pdftoppm") or "pdftoppm", "-v"], text=True, capture_output=True, check=False).stderr.splitlines()[0],
            },
            "elapsed_seconds_before_inventory": time.time() - started,
            "output_inventory": output_inventory(candidate, exclude={"provenance.json"}),
        }
        (candidate / "provenance.json").write_bytes(json_bytes(provenance))

        final_inventory = output_inventory(candidate)
        if not all(item["byte_size"] > 0 for item in final_inventory):
            raise ValidationError("generated package contains an empty file")
        if len(list(figures.glob("*.svg"))) != 8 or len(list(figures.glob("*.pdf"))) != 8 or len(list(figures.glob("*.png"))) != 8:
            raise ValidationError("figure format inventory is incomplete")

        final_generation.parent.mkdir(parents=True, exist_ok=True)
        os.replace(candidate, final_generation)
        selected = {
            "schema_version": "task003a_selected_v1",
            "generation": final_generation.relative_to(output_root).as_posix(),
            "results_sha256": sha256_file(final_generation / "results.json"),
            "provenance_sha256": sha256_file(final_generation / "provenance.json"),
            "supervisor_pdf_sha256": sha256_file(final_generation / "supervisor_report.pdf"),
        }
        atomic_write(output_root / "selected.json", json_bytes(selected))

        # Publish only small, reviewable sources into tracked documentation.
        docs_figures = root / "docs/reports/figures/003a"
        docs_figures.mkdir(parents=True, exist_ok=True)
        for stem, _ in drawings:
            atomic_write(docs_figures / f"{stem}.svg", (final_generation / "figures" / f"{stem}.svg").read_bytes())
        docs_links = {f"figure{index}": f"figures/003a/{stem}.svg" for index, (stem, _) in enumerate(drawings, 1)}
        docs_report = build_markdown(results, composition_effects, docs_links)
        atomic_write(root / "docs/reports/003a_supervisor_split_validation.md", docs_report.encode())

        sanitized = {
            "schema_version": "task003a_split_validation_report_v1",
            "status": "accepted_candidate_for_final_review",
            "task": "003A",
            "source_generation": final_generation.relative_to(root).as_posix(),
            "results": {
                "former_fold_v1": v1_crossing,
                "former_fold_v2": v2_crossing,
                "component_integrity": integrity,
                "balance": balance,
                "composition_max_abs_smd": max(abs(float(row["standardized_mean_difference"])) for row in composition_effects),
                "audit_searches_completed": 18,
                "audit_cross_partition_hits": 0,
            },
            "inputs": {name: {key: value for key, value in item.items() if key in ("byte_size", "sha256")} for name, item in inputs.items()},
            "outputs": {
                "supervisor_report_pdf": {"byte_size": (final_generation / "supervisor_report.pdf").stat().st_size, "sha256": sha256_file(final_generation / "supervisor_report.pdf")},
                "results_json": {"byte_size": (final_generation / "results.json").stat().st_size, "sha256": sha256_file(final_generation / "results.json")},
                "provenance_json": {"byte_size": (final_generation / "provenance.json").stat().st_size, "sha256": sha256_file(final_generation / "provenance.json")},
                "tracked_report_md": {"byte_size": (root / "docs/reports/003a_supervisor_split_validation.md").stat().st_size, "sha256": sha256_file(root / "docs/reports/003a_supervisor_split_validation.md")},
                "tracked_svg_figures": [
                    {"path": f"docs/reports/figures/003a/{stem}.svg", "byte_size": (docs_figures / f"{stem}.svg").stat().st_size, "sha256": sha256_file(docs_figures / f"{stem}.svg")}
                    for stem, _ in drawings
                ],
            },
            "boundary": {"model_accessed": False, "predictions_accessed": False, "split_modified": False, "mmseqs2_run": False, "network_accessed": False},
        }
        atomic_write(root / "manifests/task003a_split_validation_report.json", json_bytes(sanitized))
        return final_generation
    except Exception:
        if candidate.exists():
            shutil.rmtree(candidate)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/task003a_split_validation"))
    parser.add_argument("--legacy-python", type=Path, default=Path(".venv-002c-legacy/bin/python"))
    args = parser.parse_args(argv)
    if not args.output_dir.is_absolute():
        args.output_dir = args.repo_root / args.output_dir
    if not args.legacy_python.is_absolute():
        args.legacy_python = args.repo_root / args.legacy_python
    generation = run(args)
    print(generation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
