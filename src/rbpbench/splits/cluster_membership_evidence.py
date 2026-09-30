"""Deterministic preparation/validation of the Task 002C-2A legacy-diagnostic
cluster-MEMBERSHIP evidence (docs/tasks/002c2a_legacy_cluster_evidence.md,
docs/handoffs/002c2a_legacy_cluster_evidence_claude_handoff.md).

The accepted Task 002B return retained, per protected width, the raw
``mmseqs createtsv`` cluster-membership TSV (``representative<TAB>member``
rows) and its own selected record -- not the internal alignment-result
databases. MMseqs2 documents ``--cluster-mode 1`` as connected-component
clustering (breadth-first reachability), so a membership row proves cluster
CO-MEMBERSHIP, direct or transitive, never a direct pairwise similarity
edge. This module never converts a membership row into an invented "direct
edge": it only verifies, parses, and reconciles the accepted membership
TSVs, and computes the per-width cluster-BOUNDARY diagnostic
(:func:`cluster_boundary_report`) that replaces the retired
``directly_edge_matched_by_width`` claim.

Every one of the three per-width membership TSVs and their selected records
is bound to explicit, pinned ``(width, size, hash)`` provenance
(:func:`bind_cluster_membership_evidence`) and reconciled against the closed
canonical ``row_0..row_{N-1}`` sample universe before use -- missing,
duplicate, foreign, malformed, or hash-mismatched evidence is always a hard
failure, never silently repaired or partially accepted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rbpbench.data.audit import sha256_file
from rbpbench.splits import legacy_edges as splits_legacy_edges
from rbpbench.splits.config_002c import SplitsConfig002C
from rbpbench.splits.membership import (
    MembershipReconciliationError,
    parse_cluster_tsv_lines,
    reconcile_membership,
    reconcile_representatives,
)

EVIDENCE_KIND = "connected_component_membership"


class ClusterEvidenceError(ValueError):
    """A legacy-diagnostic cluster-membership evidence file (membership TSV
    or selected record) failed pinned hash/size verification, contained a
    malformed or non-reconciling entry, or disagreed with its accepted
    summary counts. Never silently repaired or partially accepted.
    """


@dataclass(frozen=True)
class ClusterMembershipSummary:
    member_count: int
    cluster_count: int
    largest_cluster_size: int


def verify_frozen_sized_file(path: Path, *, expected_sha256: str, expected_byte_size: int, label: str) -> str:
    """Hash/size-verifies ``path`` BEFORE it is ever parsed -- a bare file,
    even one whose own current hash happens to be recorded elsewhere, can
    never qualify merely by existing at the expected path.
    """
    path = Path(path)
    if not path.is_file():
        raise ClusterEvidenceError(f"{label} not found at {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_byte_size:
        raise ClusterEvidenceError(
            f"{label} at {path} is {actual_size} bytes, expected exactly {expected_byte_size} per its pinned "
            "provenance"
        )
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise ClusterEvidenceError(
            f"{label} at {path} hashes to {actual_sha256}, expected exactly {expected_sha256} per its pinned "
            "provenance"
        )
    return actual_sha256


def summarize_membership(membership: dict[str, str]) -> ClusterMembershipSummary:
    """Groups ``{member: representative}`` by representative to derive the
    cluster count and largest-cluster size -- the same grouping
    :func:`cluster_boundary_report` uses, so the accepted summary and the
    boundary diagnostic can never silently disagree about what a "cluster"
    is.
    """
    cluster_sizes: dict[str, int] = {}
    for representative in membership.values():
        cluster_sizes[representative] = cluster_sizes.get(representative, 0) + 1
    return ClusterMembershipSummary(
        member_count=len(membership),
        cluster_count=len(cluster_sizes),
        largest_cluster_size=max(cluster_sizes.values()) if cluster_sizes else 0,
    )


def load_and_verify_cluster_membership(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int,
    canonical_ids: frozenset[str],
    expected_member_count: int,
    expected_cluster_count: int,
    expected_largest_cluster_size: int,
    label: str,
) -> dict[str, str]:
    """Hash/size-verifies, then stream-parses ``path`` as exactly two
    tab-separated fields per non-empty line (:func:`rbpbench.splits.membership.parse_cluster_tsv_lines`),
    requires every canonical ID exactly once as a member and every
    representative to be canonical, and reproduces the accepted cluster
    count and largest-cluster size. Returns the parsed ``{member:
    representative}`` mapping.
    """
    verify_frozen_sized_file(path, expected_sha256=expected_sha256, expected_byte_size=expected_byte_size, label=label)

    try:
        with Path(path).open() as handle:
            membership = parse_cluster_tsv_lines(handle)
        reconcile_membership(membership, canonical_ids)
        reconcile_representatives(membership, canonical_ids)
    except MembershipReconciliationError as exc:
        raise ClusterEvidenceError(f"{label} at {path}: {exc}") from exc

    summary = summarize_membership(membership)
    problems: list[str] = []
    if summary.member_count != expected_member_count:
        problems.append(f"member count {summary.member_count} != expected exactly {expected_member_count}")
    if summary.cluster_count != expected_cluster_count:
        problems.append(f"cluster count {summary.cluster_count} != expected exactly {expected_cluster_count}")
    if summary.largest_cluster_size != expected_largest_cluster_size:
        problems.append(
            f"largest cluster size {summary.largest_cluster_size} != expected exactly {expected_largest_cluster_size}"
        )
    if problems:
        raise ClusterEvidenceError(f"{label} at {path}: " + "; ".join(problems))

    return membership


def verify_selected_record(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int,
    expected_width: int,
    expected_generation_digest: str,
    expected_member_count: int,
    membership_sha256: str,
    membership_byte_size: int,
    label: str,
) -> dict:
    """Hash/size-verifies the accepted Task 002B ``selected_records/cluster_<width>.json``
    record, then requires it to declare the expected width, ``stage`` ==
    ``"cluster"``, ``executed`` is ``True``, the expected sample count and
    generation digest, and an ``artifacts`` entry named ``"membership.tsv"``
    whose own recorded hash/size matches the SAME pinned membership
    hash/size this checkpoint independently verified against the real
    membership TSV -- never trusted merely because the selected record says
    so.
    """
    verify_frozen_sized_file(path, expected_sha256=expected_sha256, expected_byte_size=expected_byte_size, label=label)
    record = json.loads(Path(path).read_text())

    problems: list[str] = []
    if record.get("stage") != "cluster":
        problems.append(f"stage {record.get('stage')!r} != expected exactly 'cluster'")
    if record.get("executed") is not True:
        problems.append(f"executed {record.get('executed')!r} != expected exactly True")
    if record.get("width") != expected_width:
        problems.append(f"width {record.get('width')!r} != expected exactly {expected_width}")
    if record.get("sample_count") != expected_member_count:
        problems.append(f"sample_count {record.get('sample_count')!r} != expected exactly {expected_member_count}")
    if record.get("generation_digest") != expected_generation_digest:
        problems.append(
            f"generation_digest {record.get('generation_digest')!r} != expected exactly {expected_generation_digest!r}"
        )

    artifacts = record.get("artifacts")
    membership_artifact = None
    if isinstance(artifacts, list):
        membership_artifact = next((entry for entry in artifacts if entry.get("path") == "membership.tsv"), None)
    if membership_artifact is None:
        problems.append("has no 'membership.tsv' entry in its artifacts inventory")
    else:
        if membership_artifact.get("sha256") != membership_sha256:
            problems.append(
                f"artifacts['membership.tsv'].sha256 {membership_artifact.get('sha256')!r} != the pinned "
                f"membership hash {membership_sha256!r}"
            )
        if membership_artifact.get("size") != membership_byte_size:
            problems.append(
                f"artifacts['membership.tsv'].size {membership_artifact.get('size')!r} != the pinned "
                f"membership byte size {membership_byte_size!r}"
            )

    if problems:
        raise ClusterEvidenceError(f"{label} at {path}: " + "; ".join(problems))
    return record


def bind_cluster_membership_evidence(
    *,
    width: int,
    membership_path: Path,
    membership_sha256: str,
    membership_byte_size: int,
    selected_record_path: Path,
    selected_record_sha256: str,
    selected_record_byte_size: int,
    generation_digest: str,
    member_count: int,
    cluster_count: int,
    largest_cluster_size: int,
) -> dict:
    """One explicit ``(width, evidence kind, membership hash/size, selected
    record hash/size, generation digest)`` binding -- never a bare hash
    string folded into a flat list that loses which file/checkpoint it
    belongs to.
    """
    return {
        "width": width,
        "evidence_kind": EVIDENCE_KIND,
        "membership_path": str(membership_path),
        "membership_sha256": membership_sha256,
        "membership_byte_size": membership_byte_size,
        "selected_record_path": str(selected_record_path),
        "selected_record_sha256": selected_record_sha256,
        "selected_record_byte_size": selected_record_byte_size,
        "generation_digest": generation_digest,
        "member_count": member_count,
        "cluster_count": cluster_count,
        "largest_cluster_size": largest_cluster_size,
    }


_RELATIONSHIP_NOTE = (
    "cluster co-membership under the frozen per-width MMseqs2 connected-component clustering (--cluster-mode 1) "
    "may be direct or transitive; it does not establish a direct pairwise alignment for every affected row"
)


def cluster_boundary_report(
    *,
    width: int,
    membership: dict[str, str],
    holdout_ids,
    train_ids,
) -> dict:
    """The per-width cluster-BOUNDARY diagnostic that replaces the retired,
    unsupported ``directly_edge_matched_by_width`` claim
    (docs/tasks/002c2a_legacy_cluster_evidence.md, "Correct replacement
    diagnostic"): for each width, the total cluster count, the clusters
    represented in the legacy holdout, the clusters crossing the legacy
    train/holdout boundary (containing at least one row of each), the
    crossing-cluster rate over clusters represented in holdout, and the
    train/holdout row counts (with their own denominators) that fall inside
    a crossing cluster.

    A member is grouped into exactly one cluster by its representative
    (mirrors :func:`summarize_membership`'s own grouping); ``width`` is
    carried only for a caller-side label and never changes the grouping.
    """
    del width  # carried by the caller for report keying only

    cluster_members: dict[str, list[str]] = {}
    for member, representative in membership.items():
        cluster_members.setdefault(representative, []).append(member)

    clusters_represented_in_holdout = 0
    crossing_cluster_count = 0
    train_rows_in_crossing = 0
    holdout_rows_in_crossing = 0

    for members in cluster_members.values():
        holdout_members = [m for m in members if m in holdout_ids]
        train_members = [m for m in members if m in train_ids]
        if holdout_members:
            clusters_represented_in_holdout += 1
        if holdout_members and train_members:
            crossing_cluster_count += 1
            train_rows_in_crossing += len(train_members)
            holdout_rows_in_crossing += len(holdout_members)

    total_holdout = len(holdout_ids)
    total_train = len(train_ids)

    return {
        "total_cluster_count": len(cluster_members),
        "clusters_represented_in_holdout": clusters_represented_in_holdout,
        "crossing_cluster_count": crossing_cluster_count,
        "crossing_cluster_rate_over_holdout_clusters": (
            crossing_cluster_count / clusters_represented_in_holdout if clusters_represented_in_holdout else 0.0
        ),
        "train_rows_in_crossing_clusters_count": train_rows_in_crossing,
        "train_rows_in_crossing_clusters_rate_over_train_rows": (
            train_rows_in_crossing / total_train if total_train else 0.0
        ),
        "holdout_rows_in_crossing_clusters_count": holdout_rows_in_crossing,
        "holdout_rows_in_crossing_clusters_rate_over_holdout_rows": (
            holdout_rows_in_crossing / total_holdout if total_holdout else 0.0
        ),
        "relationship_note": _RELATIONSHIP_NOTE,
    }


def _resolve_pinned_child(root: Path, relative_path: str, *, label: str) -> Path:
    """Mirrors the pinned-child confinement rule duplicated across every
    Task 002C-2A cluster-evidence consumer (deliberately not imported from
    :mod:`rbpbench.splits.runner_002c`, so this shared verifier never binds a
    pipeline-runner dependency): resolves ``relative_path`` only as a pinned
    child beneath ``root``, refusing a ``..`` traversal or a symlink
    resolving outside ``root``.
    """
    resolved_root = Path(root).resolve()
    resolved_candidate = (resolved_root / relative_path).resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        raise ClusterEvidenceError(
            f"{label}: relative path {relative_path!r} resolves outside the authorized root {resolved_root}"
        ) from None
    return resolved_candidate


def _require_single_inventory_entry(
    entries: list, *, relative_path: str, expected_byte_size: int, expected_sha256: str, label: str,
) -> None:
    """Correction review C2: ``RETURN_INVENTORY.json`` must contain EXACTLY
    one entry for ``relative_path``, with matching byte size and SHA-256 --
    a missing, duplicate, or contradictory entry is a hard failure even when
    the outer file hash-verifies.
    """
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("path") == relative_path]
    if len(matches) != 1:
        raise ClusterEvidenceError(f"{label}: expected exactly one entry for {relative_path!r}, found {len(matches)}")
    entry = matches[0]
    if entry.get("byte_size") != expected_byte_size:
        raise ClusterEvidenceError(
            f"{label}: entry for {relative_path!r} has byte_size {entry.get('byte_size')!r}, expected exactly "
            f"{expected_byte_size}"
        )
    if entry.get("sha256") != expected_sha256:
        raise ClusterEvidenceError(
            f"{label}: entry for {relative_path!r} has sha256 {entry.get('sha256')!r}, expected exactly "
            f"{expected_sha256!r}"
        )


def _require_cluster_stage_entry(
    manifest_raw: object,
    *,
    width: int,
    expected_generation_digest: str,
    expected_membership_relative_path: str,
    expected_member_count: int,
    expected_cluster_count: int,
    expected_largest_cluster_size: int,
    label: str,
) -> dict:
    """Correction review C2: ``RETURN_MANIFEST.json`` must declare, for this
    width's ``cluster_<width>`` selected stage, ``executed: true``, the
    expected generation digest, returned membership path, member count,
    cluster count, and largest-cluster size -- a syntactically valid but
    contradictory entry is a hard failure even when the outer file
    hash-verifies.
    """
    stage_key = f"cluster_{width}"
    stages = manifest_raw.get("selected_stages") if isinstance(manifest_raw, dict) else None
    entry = stages.get(stage_key) if isinstance(stages, dict) else None
    if not isinstance(entry, dict):
        raise ClusterEvidenceError(f"{label}: missing selected_stages[{stage_key!r}] entry")

    problems: list[str] = []
    if entry.get("stage") != "cluster":
        problems.append(f"selected_stages[{stage_key!r}].stage {entry.get('stage')!r} != expected exactly 'cluster'")
    if entry.get("executed") is not True:
        problems.append(f"selected_stages[{stage_key!r}].executed {entry.get('executed')!r} != expected exactly True")
    if entry.get("width") != width:
        problems.append(f"selected_stages[{stage_key!r}].width {entry.get('width')!r} != expected exactly {width}")
    if entry.get("generation_digest") != expected_generation_digest:
        problems.append(
            f"selected_stages[{stage_key!r}].generation_digest {entry.get('generation_digest')!r} != expected "
            f"exactly {expected_generation_digest!r}"
        )
    if entry.get("returned_membership_path") != expected_membership_relative_path:
        problems.append(
            f"selected_stages[{stage_key!r}].returned_membership_path {entry.get('returned_membership_path')!r} "
            f"!= expected exactly {expected_membership_relative_path!r}"
        )
    summary = entry.get("membership_summary")
    if not isinstance(summary, dict):
        problems.append(f"selected_stages[{stage_key!r}] has no membership_summary")
    else:
        if summary.get("member_count") != expected_member_count:
            problems.append(
                f"selected_stages[{stage_key!r}].membership_summary.member_count {summary.get('member_count')!r} "
                f"!= expected exactly {expected_member_count}"
            )
        if summary.get("cluster_count") != expected_cluster_count:
            problems.append(
                f"selected_stages[{stage_key!r}].membership_summary.cluster_count {summary.get('cluster_count')!r} "
                f"!= expected exactly {expected_cluster_count}"
            )
        if summary.get("largest_cluster_size") != expected_largest_cluster_size:
            problems.append(
                f"selected_stages[{stage_key!r}].membership_summary.largest_cluster_size "
                f"{summary.get('largest_cluster_size')!r} != expected exactly {expected_largest_cluster_size}"
            )
    if problems:
        raise ClusterEvidenceError(f"{label}: " + "; ".join(problems))
    return entry


def verify_live_cluster_evidence(*, config: SplitsConfig002C, cluster_evidence_root: Path) -> dict:
    """THE one shared, content-derived verifier for the accepted Task 002B
    cluster-membership evidence bundle (correction review C1/C2): resolves
    all eight pinned children beneath ``cluster_evidence_root``, re-hashes/
    revalidates every one of them against the config's pinned provenance
    (never trusting a cached hash from configuration alone), parses and
    semantically cross-checks ``RETURN_MANIFEST.json``/``RETURN_INVENTORY.json``
    against the selected records and membership files, and performs the
    existing selected-record/membership reconciliation.

    Used identically before a ``legacy_diagnostic`` restart-skip decision,
    inside a real ``legacy_diagnostic`` execution, and during ``finalize``'s
    current-evidence revalidation -- so a changed/missing metadata file,
    membership TSV, selected record, or generation binding can never remain
    apparently current merely because the config's static expectation
    hasn't changed.

    Returns a complete, content-derived evidence binding:
    ``{"return_manifest_path", "return_manifest_sha256", "return_manifest_byte_size",
    "return_inventory_path", "return_inventory_sha256", "return_inventory_byte_size",
    "per_width": {width: {"membership_path", "selected_record_path", "selected_record"}},
    "cluster_evidence": {"<width>": {...}}, "cluster_membership_by_width": {width: {member: representative}}}``.
    """
    cluster_evidence_root = Path(cluster_evidence_root).resolve()
    canonical_ids = splits_legacy_edges.canonical_sample_ids(config.dataset.expected_row_count)

    return_manifest_expected = config.legacy_edges.return_manifest
    return_manifest_path = _resolve_pinned_child(
        cluster_evidence_root, return_manifest_expected.relative_path, label="RETURN_MANIFEST.json"
    )
    verify_frozen_sized_file(
        return_manifest_path, expected_sha256=return_manifest_expected.sha256,
        expected_byte_size=return_manifest_expected.byte_size, label="RETURN_MANIFEST.json",
    )
    manifest_raw = json.loads(return_manifest_path.read_text())

    return_inventory_expected = config.legacy_edges.return_inventory
    return_inventory_path = _resolve_pinned_child(
        cluster_evidence_root, return_inventory_expected.relative_path, label="RETURN_INVENTORY.json"
    )
    verify_frozen_sized_file(
        return_inventory_path, expected_sha256=return_inventory_expected.sha256,
        expected_byte_size=return_inventory_expected.byte_size, label="RETURN_INVENTORY.json",
    )
    inventory_raw = json.loads(return_inventory_path.read_text())
    if not isinstance(inventory_raw, list):
        raise ClusterEvidenceError("RETURN_INVENTORY.json: expected a JSON list of file entries")

    per_width: dict[int, dict] = {}
    cluster_evidence: dict[str, dict] = {}
    cluster_membership_by_width: dict[int, dict[str, str]] = {}

    for width in config.protected_widths:
        expected = config.legacy_edges.cluster_membership[width]

        membership_path = _resolve_pinned_child(
            cluster_evidence_root, expected.membership_relative_path, label=f"cluster membership width {width}"
        )
        selected_record_path = _resolve_pinned_child(
            cluster_evidence_root, expected.selected_record_relative_path,
            label=f"cluster selected record width {width}",
        )

        selected_record = verify_selected_record(
            selected_record_path, expected_sha256=expected.selected_record_sha256,
            expected_byte_size=expected.selected_record_byte_size, expected_width=width,
            expected_generation_digest=expected.expected_generation_digest,
            expected_member_count=expected.expected_member_count,
            membership_sha256=expected.membership_sha256, membership_byte_size=expected.membership_byte_size,
            label=f"cluster selected record width {width}",
        )
        membership = load_and_verify_cluster_membership(
            membership_path, expected_sha256=expected.membership_sha256,
            expected_byte_size=expected.membership_byte_size, canonical_ids=canonical_ids,
            expected_member_count=expected.expected_member_count,
            expected_cluster_count=expected.expected_cluster_count,
            expected_largest_cluster_size=expected.expected_largest_cluster_size,
            label=f"cluster membership width {width}",
        )

        _require_single_inventory_entry(
            inventory_raw, relative_path=expected.membership_relative_path,
            expected_byte_size=expected.membership_byte_size, expected_sha256=expected.membership_sha256,
            label="RETURN_INVENTORY.json",
        )
        _require_single_inventory_entry(
            inventory_raw, relative_path=expected.selected_record_relative_path,
            expected_byte_size=expected.selected_record_byte_size, expected_sha256=expected.selected_record_sha256,
            label="RETURN_INVENTORY.json",
        )
        _require_cluster_stage_entry(
            manifest_raw, width=width, expected_generation_digest=expected.expected_generation_digest,
            expected_membership_relative_path=expected.membership_relative_path,
            expected_member_count=expected.expected_member_count,
            expected_cluster_count=expected.expected_cluster_count,
            expected_largest_cluster_size=expected.expected_largest_cluster_size,
            label="RETURN_MANIFEST.json",
        )

        cluster_membership_by_width[width] = membership
        per_width[width] = {
            "membership_path": membership_path,
            "selected_record_path": selected_record_path,
            "selected_record": selected_record,
        }
        cluster_evidence[str(width)] = bind_cluster_membership_evidence(
            width=width, membership_path=membership_path, membership_sha256=expected.membership_sha256,
            membership_byte_size=expected.membership_byte_size, selected_record_path=selected_record_path,
            selected_record_sha256=expected.selected_record_sha256,
            selected_record_byte_size=expected.selected_record_byte_size,
            generation_digest=expected.expected_generation_digest, member_count=expected.expected_member_count,
            cluster_count=expected.expected_cluster_count, largest_cluster_size=expected.expected_largest_cluster_size,
        )

    return {
        "return_manifest_path": return_manifest_path,
        "return_manifest_sha256": return_manifest_expected.sha256,
        "return_manifest_byte_size": return_manifest_expected.byte_size,
        "return_inventory_path": return_inventory_path,
        "return_inventory_sha256": return_inventory_expected.sha256,
        "return_inventory_byte_size": return_inventory_expected.byte_size,
        "per_width": per_width,
        "cluster_evidence": cluster_evidence,
        "cluster_membership_by_width": cluster_membership_by_width,
    }


__all__ = [
    "EVIDENCE_KIND",
    "ClusterEvidenceError",
    "ClusterMembershipSummary",
    "verify_frozen_sized_file",
    "summarize_membership",
    "load_and_verify_cluster_membership",
    "verify_selected_record",
    "bind_cluster_membership_evidence",
    "cluster_boundary_report",
    "verify_live_cluster_evidence",
]
