#!/usr/bin/env python3
"""Build the immutable Task 002C-R3–R5 Darwin bundle (production contract only).

Every frozen input is supplied explicitly; repository-tracked manifests and
the proteins table come from the clean source checkout.  The builder
refuses missing, extra, drifted, or unreviewed inputs and a dirty worktree.
Building the real bundle is a separate, reviewed step; this script performs
no MMseqs2, scheduler, network, or model action.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rbpbench.splits.r3r5 import bundle  # noqa: E402
from rbpbench.splits.r3r5.contract import PRODUCTION  # noqa: E402

REPO_TRACKED_ROLES = {
    "dataset_audit": "manifests/dataset_audit.json",
    "proteins_tsv": "configs/proteins.tsv",
    "decode_manifest": "manifests/sequence_decode_002b2.json",
    "r2_return_manifest": "manifests/sequence_r2_darwin_convergence_return.json",
}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--dataset-csv", type=Path, required=True)
    parser.add_argument("--decode-dir", type=Path, required=True,
                        help="accepted decode generation holding sequence_partitions_width_*.fasta and duplicate_edges_*.json")
    parser.add_argument("--v1-component-membership", type=Path, required=True)
    parser.add_argument("--v1-component-report", type=Path, required=True)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    sources = {role: repo / rel for role, rel in REPO_TRACKED_ROLES.items()}
    sources["dataset_csv"] = args.dataset_csv
    for width in (500, 251, 101):
        sources[f"fasta_{width}"] = args.decode_dir / f"sequence_partitions_width_{width}.fasta"
        sources[f"exact_rc_{width}"] = args.decode_dir / f"duplicate_edges_{width}.json"
    sources["v1_component_membership"] = args.v1_component_membership
    sources["v1_component_report"] = args.v1_component_report
    result = bundle.build_bundle(repo, args.destination, sources, contract=PRODUCTION)
    if args.archive:
        result["archive"] = bundle.archive_bundle(args.destination)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
