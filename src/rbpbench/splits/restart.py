"""Small restart-safety primitives shared by the Task 002C runner.

Deliberately DUPLICATED (never imported) from
:mod:`rbpbench.splits.runner`'s private helpers of the same shape, so that
extending Task 002C's orchestration can never destabilize the
already-accepted Task 002B runner module
(``docs/handoffs/002c1_partition_orchestration_claude_handoff.md``, item 1:
"a new console entry point is acceptable so extending 002C cannot
destabilize the accepted 002B runner").
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from rbpbench.data.audit import sha256_file


class PriorStageNotAcceptedError(RuntimeError):
    """A required upstream selection record is missing, not intact, or no
    longer CURRENT. Never silently runs the upstream stage on this stage's
    behalf, and never launches any subprocess before this check passes.
    """


def atomic_write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str) + "\n")
    os.replace(tmp_path, path)


def load_json(path: Path) -> dict | None:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def inventory_generation(generation_dir: Path) -> list[dict]:
    """Every retained regular file under ``generation_dir`` (path relative
    to it, byte size, SHA-256), sorted by path -- the complete evidence a
    later revalidation compares against.
    """
    generation_dir = Path(generation_dir)
    entries: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(generation_dir):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_file():
                rel = str(path.relative_to(generation_dir))
                entries.append({"path": rel, "size": path.stat().st_size, "sha256": sha256_file(path)})
    return sorted(entries, key=lambda e: e["path"])


def verify_generation_intact(record: dict | None) -> bool:
    """Re-hashes and re-lists EVERY file the record's generation directory
    currently contains and compares it to the exact inventory recorded at
    acceptance time.

    A record with a missing/empty ``generation_dir`` fails CLOSED (never
    fail-open): every 002C stage (``assign``, ``legacy_diagnostic``,
    ``exact_audit``, ``audit_probe``, ``audit_search``, ``finalize``) always
    creates its own generation directory, so there is no legitimate
    generation-less 002C selection record
    (docs/reviews/002c1_partition_orchestration_correction_review.md, C4:
    "``load_accepted()`` also returns true for a record without a
    generation directory, which is fail-open").
    """
    if record is None:
        return False
    generation_dir = record.get("generation_dir")
    if not generation_dir:
        return False
    path = Path(generation_dir)
    if not path.is_dir():
        return False
    return inventory_generation(path) == record.get("artifacts", [])


def selected_record_path(output_dir: Path, key: str) -> Path:
    return Path(output_dir) / "selected" / f"{key}.json"


def load_accepted(output_dir: Path, key: str) -> dict | None:
    record = load_json(selected_record_path(output_dir, key))
    if record is None or not record.get("executed") or not verify_generation_intact(record):
        return None
    return record


def require_accepted(output_dir: Path, key: str) -> dict:
    record = load_accepted(output_dir, key)
    if record is None:
        raise PriorStageNotAcceptedError(
            f"stage {key!r} has no accepted, currently-intact selection record under {output_dir}/selected/; "
            "run and accept it first"
        )
    return record


__all__ = [
    "PriorStageNotAcceptedError",
    "atomic_write_json",
    "load_json",
    "inventory_generation",
    "verify_generation_intact",
    "selected_record_path",
    "load_accepted",
    "require_accepted",
]
