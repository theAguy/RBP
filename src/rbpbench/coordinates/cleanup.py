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
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
    """Whether ``path`` or any ancestor up to (and including) ``stop_at`` is
    itself a symlink. Bounded by ``stop_at`` so this never walks past the
    caller-supplied root (typically the pipeline's own output directory).
    """
    current = path
    for _ in range(256):
        if current.is_symlink():
            return True
        if current == stop_at or current.parent == current:
            return False
        current = current.parent
    raise CleanupRefused(f"path {path} has an implausibly deep directory tree; refusing")


def _validate_pinned_index_target(index_dir: Path, *, build: str) -> None:
    """Prove the target directory has exactly the pinned ``indices/<build>/``
    shape (B1-R5): its own name must equal ``build`` and its parent must be
    named ``indices``. This is a shape check, not an absolute-path pin, so a
    test can still root ``indices/`` under its own temporary directory.
    """
    index_dir = Path(index_dir)
    if index_dir.name != build:
        raise CleanupRefused(
            f"cleanup target directory name {index_dir.name!r} does not match build {build!r}; refusing"
        )
    if index_dir.parent.name != "indices":
        raise CleanupRefused(
            f"cleanup target parent {index_dir.parent} is not named 'indices'; refusing a non-pinned root"
        )


def plan_index_cleanup(
    index_dir: Path,
    *,
    reference: Path | None = None,
    output_dir: Path | None = None,
) -> CleanupPlan:
    """Resolve and validate the deletion target without deleting anything.

    Raises :class:`CleanupRefused` when:

    - the target does not exist or is not a directory;
    - the target itself, or any ancestor component up to its own parent, is
      a symlink;
    - the resolved target is equal to, contains, or is contained by the
      reference file's directory or the output directory.
    """
    index_dir = Path(index_dir)
    if not index_dir.exists():
        raise CleanupRefused(f"cleanup target {index_dir} does not exist")
    if not index_dir.is_dir():
        raise CleanupRefused(f"cleanup target {index_dir} is not a directory")
    if _contains_symlink(index_dir, stop_at=index_dir.parent):
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


def write_cleanup_receipt(
    receipt_path: Path, *, plan: CleanupPlan, index_manifest: dict | None, completed: bool
) -> dict:
    """Durably record cleanup evidence *outside* the disposable index
    directory (B1-R5): the preview list, each file's hash/size, the complete
    index-manifest content (so it survives after ``index_manifest.json``
    itself is deleted — cleanup must never destroy the only copy of index
    provenance), a timestamp, and completion status. Called once before
    deletion (``completed=False``, the persisted preview) and once after
    (``completed=True``, the confirmation).
    """
    payload = {
        "target": str(plan.resolved_target),
        "files": [
            {"path": str(f), "sha256": sha256_file(f) if f.is_file() else None, "byte_size": f.stat().st_size if f.is_file() else None}
            for f in plan.files
        ],
        "index_manifest": index_manifest,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "completed": completed,
    }
    receipt_path = Path(receipt_path)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def execute_index_cleanup(
    index_dir: Path,
    *,
    index_manifest_present: bool,
    mapping_outputs_present: bool,
    reconciliation_passed: bool,
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

    ``build``, when given, additionally proves the target has exactly the
    pinned ``indices/<build>/`` shape (B1-R5) before anything is resolved or
    deleted. ``receipt_path``, when given, durably records a preview receipt
    (:func:`write_cleanup_receipt`) *before* deletion and a completion
    receipt immediately after, so index provenance survives outside the
    disposable directory even after it is removed.
    """
    if not index_manifest_present:
        raise CleanupRefused("refusing cleanup: no index manifest/provenance recorded for this directory yet")
    if not mapping_outputs_present:
        raise CleanupRefused("refusing cleanup: no successful mapping outputs recorded yet")
    if not reconciliation_passed:
        raise CleanupRefused("refusing cleanup: reconciliation has not passed")
    if build is not None:
        _validate_pinned_index_target(index_dir, build=build)

    # Preview resolved and (optionally) durably persisted *before* anything
    # is deleted (B1-R5: the required preview previously happened only after
    # deletion via the CLI's print-after-execute ordering).
    plan = plan_index_cleanup(index_dir, reference=reference, output_dir=output_dir)
    if receipt_path is not None:
        write_cleanup_receipt(receipt_path, plan=plan, index_manifest=index_manifest, completed=False)

    shutil.rmtree(plan.resolved_target)

    if receipt_path is not None:
        write_cleanup_receipt(receipt_path, plan=plan, index_manifest=index_manifest, completed=True)
    return plan


__all__ = [
    "CleanupRefused",
    "CleanupPlan",
    "plan_index_cleanup",
    "execute_index_cleanup",
    "write_cleanup_receipt",
]
