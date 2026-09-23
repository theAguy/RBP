"""Safe, narrow cleanup of a disposable mapper-index directory.

Removes exactly ``indices/<build>/`` — never a reference-adjacent glob — and
only after index provenance, successful mapping outputs, and a passed
reconciliation are all already recorded. Refuses a symlinked target and any
target equal to, an ancestor of, or a descendant of the reference or output
directory, and always resolves and returns the deletion list *before*
deleting anything, so a caller can log/audit it first.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


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


def execute_index_cleanup(
    index_dir: Path,
    *,
    index_manifest_present: bool,
    mapping_outputs_present: bool,
    reconciliation_passed: bool,
    reference: Path | None = None,
    output_dir: Path | None = None,
) -> CleanupPlan:
    """Delete exactly ``index_dir`` after every required evidence check
    passes. Refuses (deleting nothing) unless index provenance, successful
    mapping outputs, and a passed reconciliation are all already recorded —
    cleanup must never destroy the only copy of reproducible-but-unrecorded
    index evidence.
    """
    if not index_manifest_present:
        raise CleanupRefused("refusing cleanup: no index manifest/provenance recorded for this directory yet")
    if not mapping_outputs_present:
        raise CleanupRefused("refusing cleanup: no successful mapping outputs recorded yet")
    if not reconciliation_passed:
        raise CleanupRefused("refusing cleanup: reconciliation has not passed")

    plan = plan_index_cleanup(index_dir, reference=reference, output_dir=output_dir)
    shutil.rmtree(plan.resolved_target)
    return plan


__all__ = ["CleanupRefused", "CleanupPlan", "plan_index_cleanup", "execute_index_cleanup"]
