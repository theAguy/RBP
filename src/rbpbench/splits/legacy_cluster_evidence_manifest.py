"""Task 002C-2A's dedicated cluster-membership evidence-validation
operation (docs/tasks/002c2a_legacy_cluster_evidence.md,
docs/handoffs/002c2a_legacy_cluster_evidence_claude_handoff.md,
"Real validation and stop boundary").

Deliberately SEPARATE from the ``rbp-splits-002c`` runner's ``legacy_diagnostic``
stage (:mod:`rbpbench.splits.runner_002c`): this checkpoint stops before any
real CSV access or legacy-fold execution, so it never binds an ``assign``
record or a CSV. It only:

1. re-verifies every one of the eight authorized returned Task 002B files'
   byte size and SHA-256 against the pinned production config;
2. parses/reconciles the three accepted per-width cluster-membership TSVs
   and their selected records
   (:mod:`rbpbench.splits.cluster_membership_evidence`); and
3. writes a small, deterministic, sanitized manifest containing only
   hashes, sizes, counts, generation digests, reconciliation status, and
   transcribed MMseqs2 command semantics -- never row-level IDs, cluster
   memberships, sequences, labels, or an absolute collaborator path.

Re-running this operation over the same eight authorized files must
reproduce the written manifest byte-for-byte.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from rbpbench.splits import cluster_membership_evidence as splits_cluster_evidence
from rbpbench.splits.config_002c import SplitsConfig002C, load_config_002c

MANIFEST_SCHEMA = "sequence_legacy_cluster_evidence_002c2a_v1"

_DIRECT_EDGE_LIMITATION_STATEMENT = (
    "Cluster co-membership under the frozen per-width MMseqs2 connected-component clustering "
    "(--cluster-mode 1) may be direct or transitive; it is NOT a retained direct pairwise "
    "similarity-alignment edge list, and a representative/member TSV row must never be described "
    "or consumed as a direct alignment."
)


def _resolve_pinned_child(root: Path, relative_path: str, *, label: str) -> Path:
    """Mirrors :func:`rbpbench.splits.runner_002c._resolve_pinned_child`
    (deliberately duplicated -- this operation never imports the pipeline
    runner, so it can never accidentally bind an ``assign``/CSV dependency):
    resolves ``relative_path`` only as a pinned child beneath ``root``,
    refusing a ``..`` traversal or a symlink resolving outside ``root``.
    """
    resolved_root = Path(root).resolve()
    resolved_candidate = (resolved_root / relative_path).resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        raise splits_cluster_evidence.ClusterEvidenceError(
            f"{label}: relative path {relative_path!r} resolves outside the authorized root {resolved_root}"
        ) from None
    return resolved_candidate


def _transcribe_command_semantics(command_text: str) -> str:
    """Keeps only the MMseqs2 subcommand name and its flags -- strips the
    absolute collaborator binary path and every positional database/output
    path argument, which never carries scientific meaning and would leak
    the collaborator's local filesystem layout into a committed manifest.
    """
    tokens = command_text.split()
    if not tokens:
        return ""
    subcommand = tokens[1] if len(tokens) > 1 and not tokens[1].startswith("-") else None
    flag_start = next((i for i, tok in enumerate(tokens) if tok.startswith("-")), len(tokens))
    flags = tokens[flag_start:]
    prefix = f"mmseqs {subcommand}" if subcommand else "mmseqs"
    return (prefix + " " + " ".join(flags)).strip()


def _transcribed_commands_from_selected_record(record: dict) -> list[str]:
    commands = []
    for entry in record.get("tool_provenance", []):
        command_text = entry.get("command_text")
        if command_text:
            commands.append(_transcribe_command_semantics(command_text))
    return commands


def validate_and_build_manifest(*, config: SplitsConfig002C, cluster_evidence_root: Path) -> dict:
    """Runs the complete dedicated evidence-validation operation and
    returns the sanitized manifest dict (not yet written to disk).

    Correction review C1/C2: delegates every hash/size revalidation AND the
    semantic cross-check of ``RETURN_MANIFEST.json``/``RETURN_INVENTORY.json``
    against the selected records and membership files to the one shared
    verifier (:func:`rbpbench.splits.cluster_membership_evidence.verify_live_cluster_evidence`),
    so this checkpoint and the ``rbp-splits-002c`` runner's ``legacy_diagnostic``
    stage can never silently diverge on what "verified" means.
    """
    live = splits_cluster_evidence.verify_live_cluster_evidence(
        config=config, cluster_evidence_root=Path(cluster_evidence_root),
    )
    return_manifest_expected = config.legacy_edges.return_manifest
    return_inventory_expected = config.legacy_edges.return_inventory

    per_width: dict[str, dict] = {}
    for width in config.protected_widths:
        expected = config.legacy_edges.cluster_membership[width]
        selected_record = live["per_width"][width]["selected_record"]
        membership = live["cluster_membership_by_width"][width]
        summary = splits_cluster_evidence.summarize_membership(membership)

        per_width[str(width)] = {
            "evidence_kind": expected.evidence_kind,
            "membership_relative_path": expected.membership_relative_path,
            "membership_byte_size": expected.membership_byte_size,
            "membership_sha256": expected.membership_sha256,
            "selected_record_relative_path": expected.selected_record_relative_path,
            "selected_record_byte_size": expected.selected_record_byte_size,
            "selected_record_sha256": expected.selected_record_sha256,
            "generation_digest": expected.expected_generation_digest,
            "accepted_mmseqs_commands": sorted(_transcribed_commands_from_selected_record(selected_record)),
            "member_count": summary.member_count,
            "cluster_count": summary.cluster_count,
            "largest_cluster_size": summary.largest_cluster_size,
            "reconciled": (
                summary.member_count == expected.expected_member_count
                and summary.cluster_count == expected.expected_cluster_count
                and summary.largest_cluster_size == expected.expected_largest_cluster_size
            ),
        }

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "checkpoint": "002C-2A",
        "evidence_kind": "connected_component_membership",
        "return_manifest": {
            "relative_path": return_manifest_expected.relative_path,
            "byte_size": return_manifest_expected.byte_size,
            "sha256": return_manifest_expected.sha256,
        },
        "return_inventory": {
            "relative_path": return_inventory_expected.relative_path,
            "byte_size": return_inventory_expected.byte_size,
            "sha256": return_inventory_expected.sha256,
        },
        "cluster_membership_by_width": per_width,
        "direct_edge_limitation_statement": _DIRECT_EDGE_LIMITATION_STATEMENT,
    }
    return manifest


def write_manifest(manifest: dict, path: Path) -> None:
    """Deterministic write: sorted keys, fixed separators, trailing
    newline -- re-running validation over the same evidence must reproduce
    this file byte-for-byte.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/splits/sequence_partitions_002c_v1.toml"))
    parser.add_argument("--cluster-evidence-root", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("manifests/sequence_legacy_cluster_evidence_002c2a.json")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config_002c(args.config)
    manifest = validate_and_build_manifest(config=config, cluster_evidence_root=args.cluster_evidence_root)
    write_manifest(manifest, args.output)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
