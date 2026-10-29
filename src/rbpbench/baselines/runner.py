"""Command-line entry point for Task 003B baselines."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform

from rbpbench.baselines.config import load_config
from rbpbench.baselines.phase_a import run_phase_a
from rbpbench.baselines.phase_b import run_phase_b
from rbpbench.baselines.pilot import run_pilot, sha256_file


class RunnerError(RuntimeError):
    pass


PILOT_MANIFEST_SHA256 = "de7ae98749ba4338d334ef1ba15db575b1dcaae8c425ad24cfa7153a782d4529"
PHASE_A_MANIFEST_SHA256 = "77922d6d906b7a4fd9ba8cae091e93072b0e1b09735a0397cdead2b2dfeed257"
PHASE_A_SELECTION_SHA256 = "6e997c6fe9e3acc48baa4df8a36a82a2b5aa270ac4eea7f7f7ba5aefd82bf567"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--stage", choices=("preflight", "pilot", "final", "final-phase-a", "final-phase-b"), required=True
    )
    result.add_argument("--config", type=Path, default=Path("configs/baselines/task003b_v1.toml"))
    result.add_argument("--repo-root", type=Path, default=Path("."))
    result.add_argument("--csv", type=Path)
    result.add_argument("--membership", type=Path)
    result.add_argument("--fasta-500", type=Path)
    result.add_argument("--fasta-251", type=Path)
    result.add_argument("--fasta-101", type=Path)
    result.add_argument("--pilot-manifest", type=Path, default=Path("manifests/task003b_pilot_003b2.json"))
    result.add_argument("--phase-a-manifest", type=Path, default=Path("manifests/task003b_phase_a_003b3.json"))
    result.add_argument("--output-dir", type=Path, default=Path("artifacts/task003b_simple_baselines"))
    result.add_argument("--expected-rows", type=int)
    result.add_argument("--authorize-test", action="store_true")
    result.add_argument("--force", action="store_true")
    result.add_argument("--dry-run", action="store_true")
    return result


def verify_production_inputs(args, config) -> None:
    root = args.repo_root.resolve()
    paths = {
        "csv_sha256": args.csv,
        "dataset_audit_sha256": root / "manifests/dataset_audit.json",
        "proteins_sha256": root / "configs/proteins.tsv",
        "decode_manifest_sha256": root / "manifests/sequence_decode_002b2.json",
        "partition_manifest_sha256": root / "manifests/sequence_partitions_002c_v2.json",
        "membership_sha256": args.membership,
        "fasta_500_sha256": args.fasta_500,
        "fasta_251_sha256": args.fasta_251,
        "fasta_101_sha256": args.fasta_101,
    }
    for key, path in paths.items():
        if path is None or not Path(path).is_file():
            raise RunnerError(f"required production input is missing: {key}")
        actual = sha256_file(Path(path))
        expected = config.raw["inputs"][key]
        if actual != expected:
            raise RunnerError(f"production input hash mismatch for {key}: {actual} != {expected}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    config = load_config(args.config)
    if args.dry_run:
        print({
            "stage": args.stage, "config_sha256": config.config_sha256,
            "would_access_test": args.stage in {"final", "final-phase-b"},
        })
        return 0
    if args.stage == "preflight":
        import numpy, scipy, sklearn
        expected = (platform.python_version().startswith("3.12"), numpy.__version__ == "2.0.2", scipy.__version__ == "1.16.1", sklearn.__version__ == "1.6.1")
        if not all(expected):
            raise RunnerError("Task 003B environment version mismatch")
        print({"status": "passed", "config_sha256": config.config_sha256})
        return 0
    if args.stage == "final":
        if not args.authorize_test:
            raise RunnerError("final stage requires --authorize-test")
        raise RunnerError("final execution is unavailable until an accepted pilot freezes C values")
    if args.stage == "final-phase-b" and not args.authorize_test:
        raise RunnerError("final-phase-b requires --authorize-test")
    if args.stage == "final-phase-a" and args.authorize_test:
        raise RunnerError("final-phase-a must not receive --authorize-test")
    required = {"csv": args.csv, "membership": args.membership, "fasta_500": args.fasta_500, "fasta_251": args.fasta_251, "fasta_101": args.fasta_101}
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise RunnerError(f"{args.stage} requires: {missing}")
    verify_production_inputs(args, config)
    if args.stage == "final-phase-a":
        if not args.pilot_manifest.is_file() or sha256_file(args.pilot_manifest) != PILOT_MANIFEST_SHA256:
            raise RunnerError("accepted pilot manifest is missing or has drifted")
        generation = run_phase_a(
            config=config, csv_path=args.csv, membership_path=args.membership,
            fasta_by_width={500: args.fasta_500, 251: args.fasta_251, 101: args.fasta_101},
            pilot_manifest_path=args.pilot_manifest,
            output_root=args.output_dir, expected_rows=args.expected_rows, force=args.force,
        )
    elif args.stage == "final-phase-b":
        if not args.phase_a_manifest.is_file() or sha256_file(args.phase_a_manifest) != PHASE_A_MANIFEST_SHA256:
            raise RunnerError("accepted Phase-A manifest is missing or has drifted")
        selection_path = args.output_dir / "selected/final_phase_a.json"
        if not selection_path.is_file() or sha256_file(selection_path) != PHASE_A_SELECTION_SHA256:
            raise RunnerError("accepted Phase-A selection is missing or has drifted")
        generation = run_phase_b(
            config=config, csv_path=args.csv, membership_path=args.membership,
            fasta_by_width={500: args.fasta_500, 251: args.fasta_251, 101: args.fasta_101},
            phase_a_manifest_path=args.phase_a_manifest,
            partition_manifest_path=args.repo_root.resolve() / "manifests/sequence_partitions_002c_v2.json",
            output_root=args.output_dir, expected_rows=args.expected_rows,
            authorize_test=True, force=args.force,
        )
    else:
        generation = run_pilot(
            config=config, csv_path=args.csv, membership_path=args.membership,
            fasta_by_width={500: args.fasta_500, 251: args.fasta_251, 101: args.fasta_101},
            output_root=args.output_dir, expected_rows=args.expected_rows, force=args.force,
        )
    print(generation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
