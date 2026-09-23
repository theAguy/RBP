"""Safe, narrow cleanup of a disposable mapper-index directory.

Removes exactly ``indices/<build>/`` — never a reference-adjacent glob — and
only after index provenance, successful mapping outputs, and a passed
reconciliation are all already recorded. Refuses a symlinked target and any
target equal to, an ancestor of, or a descendant of the reference or output
directory, and always resolves and returns the deletion list *before*
deleting anything, so a caller can log/audit it first.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from rbpbench.data.audit import sha256_file


class CleanupRefused(RuntimeError):
    """Raised when a cleanup target or precondition fails a safety check.
    Nothing is deleted when this is raised.
    """


@dataclass(frozen=True)
class CleanupPlan:
    target: Path
    resolved_target: Path
    files: tuple[Path, ...]

    def to_dict(self) -> dict:
        return {
            "target": str(self.target),
            "resolved_target": str(self.resolved_target),
            "files": [str(f) for f in self.files],
        }


def _is_within(candidate: Path, other: Path) -> bool:
    try:
        candidate.relative_to(other)
        return True
    except ValueError:
        return False


def _contains_symlink(path: Path, *, stop_at: Path) -> bool:
    """Whether ``path`` or ANY ancestor component up to and including
    ``stop_at`` is itself a symlink (B1-C4: the walk previously stopped at
    the immediate parent, so a symlinked ancestor further up — e.g. a
    directory nested two or more levels below ``stop_at`` — was never
    rejected). Both ``path`` and ``stop_at`` are converted to absolute
    (never resolved, which would silently follow the very symlinks this is
    checking for) paths first, so the walk reaches ``stop_at`` exactly once
    regardless of the caller's current working directory.
    """
    current = Path(path).absolute()
    boundary = Path(stop_at).absolute()
    for _ in range(256):
        if current.is_symlink():
            return True
        if current == boundary or current.parent == current:
            return False
        current = current.parent
    raise CleanupRefused(f"path {path} has an implausibly deep directory tree; refusing")


def _validate_pinned_index_target(index_dir: Path, *, build: str, repo_root: Path) -> None:
    """Prove the target is EXACTLY ``repo_root/indices/<build>`` (B1-C4): a
    prior shape-only check (name equals ``build``, parent named ``indices``)
    accepted any ``--indices-dir`` an attacker or mistake supplied, as long
    as it happened to end in an ``indices/<build>`` path segment, regardless
    of whether that root has anything to do with this run's actual pinned
    repository root. Pinning to the caller-supplied ``repo_root`` (the same
    root the rest of this invocation resolved every other pinned path
    against) closes that gap while still letting tests root their own
    isolated ``indices/`` under a temporary ``repo_root``.
    """
    index_dir = Path(index_dir)
    expected = Path(repo_root) / "indices" / build
    if index_dir.resolve() != expected.resolve():
        raise CleanupRefused(
            f"cleanup target {index_dir} does not match the pinned repository indices/{build} path ({expected}); "
            "refusing a non-pinned root"
        )


def plan_index_cleanup(
    index_dir: Path,
    *,
    repo_root: Path | None = None,
    reference: Path | None = None,
    output_dir: Path | None = None,
) -> CleanupPlan:
    """Resolve and validate the deletion target without deleting anything.

    Raises :class:`CleanupRefused` when:

    - the target does not exist or is not a directory;
    - the target itself, or any ancestor component up to and including
      ``repo_root`` (B1-C4: every symlinked path component, not merely the
      immediate parent), is a symlink;
    - the resolved target is equal to, contains, or is contained by the
      reference file's directory or the output directory.

    ``repo_root``, when omitted, defaults to ``index_dir.parent.parent`` —
    the same two-level span the original (immediate-parent-only) check
    covered — so existing low-level callers that never cared about a deeper
    pinned root keep their prior behavior; a caller enforcing the full B1-C4
    pin (see :func:`_validate_pinned_index_target`) passes its own resolved
    repository root explicitly.
    """
    index_dir = Path(index_dir)
    if not index_dir.exists():
        raise CleanupRefused(f"cleanup target {index_dir} does not exist")
    if not index_dir.is_dir():
        raise CleanupRefused(f"cleanup target {index_dir} is not a directory")
    symlink_boundary = Path(repo_root) if repo_root is not None else index_dir.parent.parent
    if _contains_symlink(index_dir, stop_at=symlink_boundary):
        raise CleanupRefused(f"cleanup target {index_dir} is (or contains) a symlink; refusing")

    resolved_target = index_dir.resolve()

    for guard_name, guard_path in (("reference", reference), ("output_dir", output_dir)):
        if guard_path is None:
            continue
        guard_resolved = Path(guard_path).resolve()
        guard_dir = guard_resolved if guard_resolved.is_dir() else guard_resolved.parent
        if (
            resolved_target == guard_dir
            or _is_within(guard_dir, resolved_target)
            or _is_within(resolved_target, guard_dir)
        ):
            raise CleanupRefused(
                f"cleanup target {resolved_target} is equal to, contains, or is contained by the "
                f"{guard_name} directory {guard_dir}; refusing"
            )

    files = tuple(sorted(p for p in resolved_target.rglob("*") if p.is_file()))
    return CleanupPlan(target=index_dir, resolved_target=resolved_target, files=files)


def _hash_files_payload(files: Sequence[Path]) -> list[dict]:
    return [
        {"path": str(f), "sha256": sha256_file(f), "byte_size": f.stat().st_size} for f in files if f.is_file()
    ]


def _write_json_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(tmp_path, path)


def write_cleanup_receipt(
    receipt_path: Path,
    *,
    plan: CleanupPlan,
    index_manifest: dict | None,
    completed: bool,
    files_payload: list[dict] | None = None,
    preview_confirmed_at: str | None = None,
) -> tuple[dict, list[dict]]:
    """Durably (and atomically) record cleanup evidence *outside* the
    disposable index directory (B1-C4): the preview file list with each
    file's hash/size, the complete index-manifest content (so it survives
    after ``index_manifest.json`` itself is deleted — cleanup must never
    destroy the only copy of index provenance), a timestamp, and completion
    status.

    ``files_payload``, when given, is used verbatim instead of re-hashing
    ``plan.files`` — required for the second (``completed=True``) call,
    whose files no longer exist on disk by the time it runs: recomputing
    hashes/sizes there previously replaced the valid preview evidence with
    nulls (the exact reproduced B1-C4 defect). The FIRST call (before
    deletion, ``files_payload=None``) computes it once and returns it so the
    caller can pass the identical value into the second call.
    """
    files_payload = files_payload if files_payload is not None else _hash_files_payload(plan.files)
    confirmed_at = preview_confirmed_at or datetime.now(timezone.utc).isoformat()
    payload = {
        "target": str(plan.resolved_target),
        "files": files_payload,
        "index_manifest": index_manifest,
        "confirmed_at": confirmed_at,
        "completed_at": datetime.now(timezone.utc).isoformat() if completed else None,
        "completed": completed,
    }
    _write_json_atomic(Path(receipt_path), payload)
    return payload, files_payload


def execute_index_cleanup(
    index_dir: Path,
    *,
    index_manifest_present: bool,
    mapping_outputs_present: bool,
    reconciliation_passed: bool,
    repo_root: Path | None = None,
    reference: Path | None = None,
    output_dir: Path | None = None,
    build: str | None = None,
    index_manifest: dict | None = None,
    receipt_path: Path | None = None,
) -> CleanupPlan:
    """Delete exactly ``index_dir`` after every required evidence check
    passes. Refuses (deleting nothing) unless index provenance, successful
    mapping outputs, and a passed reconciliation are all already recorded —
    cleanup must never destroy the only copy of reproducible-but-unrecorded
    index evidence.

    ``build``, when given, additionally proves the target is exactly
    ``repo_root/indices/<build>`` (B1-C4) before anything is resolved or
    deleted; ``repo_root`` defaults to ``index_dir.parent.parent`` when
    omitted (so it is always well-defined once ``build`` is given).
    ``receipt_path``, when given, durably records a preview receipt
    (:func:`write_cleanup_receipt`) *before* deletion and a completion
    receipt immediately after — reusing the SAME hashed file list computed
    for the preview rather than recomputing it against paths that no longer
    exist post-deletion (B1-C4) — so index provenance survives outside the
    disposable directory even after it is removed.
    """
    if not index_manifest_present:
        raise CleanupRefused("refusing cleanup: no index manifest/provenance recorded for this directory yet")
    if not mapping_outputs_present:
        raise CleanupRefused("refusing cleanup: no successful mapping outputs recorded yet")
    if not reconciliation_passed:
        raise CleanupRefused("refusing cleanup: reconciliation has not passed")
    resolved_repo_root = Path(repo_root) if repo_root is not None else Path(index_dir).parent.parent
    if build is not None:
        _validate_pinned_index_target(index_dir, build=build, repo_root=resolved_repo_root)

    # Preview resolved and (optionally) durably persisted *before* anything
    # is deleted (B1-R5/C4: the required preview previously happened only
    # after deletion via the CLI's print-after-execute ordering).
    plan = plan_index_cleanup(index_dir, repo_root=resolved_repo_root, reference=reference, output_dir=output_dir)
    files_payload = None
    preview_confirmed_at = None
    if receipt_path is not None:
        preview_payload, files_payload = write_cleanup_receipt(
            receipt_path, plan=plan, index_manifest=index_manifest, completed=False
        )
        preview_confirmed_at = preview_payload["confirmed_at"]

    shutil.rmtree(plan.resolved_target)

    if receipt_path is not None:
        write_cleanup_receipt(
            receipt_path,
            plan=plan,
            index_manifest=index_manifest,
            completed=True,
            files_payload=files_payload,
            preview_confirmed_at=preview_confirmed_at,
        )
    return plan


__all__ = [
    "CleanupRefused",
    "CleanupPlan",
    "plan_index_cleanup",
    "execute_index_cleanup",
    "write_cleanup_receipt",
]
