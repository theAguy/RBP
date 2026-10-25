"""Restart-safe workspace: immutable generations, atomic selection records,
current-input fingerprints, cleanup receipts, attempts, and the lock.

Layout under the bundle's ``r3r5_work/``::

    generations/<group>/<stage>__<token>/   one candidate per attempt
    selected/<stage>.json                   atomically promoted records
    receipts/<stage>__<token>.json          cleanup receipts (written before deletion)
    attempts/attempt_NNNN.json              one ledger entry per attempt
    state/lock.json                         active attempt owner
    state/terminal.json                     written once on a terminal stop
    budget/<cycle>_<width>.json             audit-search time ledger

A record is *current* only when its retained artifacts still hash to the
recorded inventory and its fingerprint equals the fingerprint recomputed
from the contract and the current upstream record digests.  A present but
non-current record is contradictory state and therefore an integrity stop;
it is never silently replaced.  Paths stored in records are relative to the
workspace, so no collaborator absolute path enters a fingerprint.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from rbpbench.data.audit import sha256_file
from rbpbench.splits.r3r5.stops import IntegrityStop, StopClass

RECORD_SCHEMA = 1

# Test hook: called with (stage_key, phase) at every promotion boundary.
PROMOTION_HOOK: Callable[[str, str], None] | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def digest(value: object) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(value)).hexdigest()


def atomic_write_json(path: Path, value: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with tmp.open("w") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _hook(stage_key: str, phase: str) -> None:
    if PROMOTION_HOOK is not None:
        PROMOTION_HOOK(stage_key, phase)


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------ layout
    @property
    def selected_dir(self) -> Path:
        return self.root / "selected"

    @property
    def generations_dir(self) -> Path:
        return self.root / "generations"

    @property
    def receipts_dir(self) -> Path:
        return self.root / "receipts"

    @property
    def attempts_dir(self) -> Path:
        return self.root / "attempts"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def budget_dir(self) -> Path:
        return self.root / "budget"

    def create(self) -> None:
        if self.root.exists():
            raise IntegrityStop(f"workspace {self.root} already exists; execute is single-use (use resume)")
        for path in (self.root, self.selected_dir, self.generations_dir, self.receipts_dir, self.attempts_dir,
                     self.state_dir, self.budget_dir):
            path.mkdir(parents=True, exist_ok=path != self.root)

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.root.resolve()))

    def abs(self, rel: str) -> Path:
        candidate = (self.root / rel).resolve()
        candidate.relative_to(self.root.resolve())
        return candidate

    # -------------------------------------------------------- generations
    def group_dir(self, group: str) -> Path:
        return self.generations_dir / group

    def new_generation(self, group: str, stage_key: str) -> Path:
        path = self.group_dir(group) / f"{stage_key}__{uuid.uuid4().hex[:12]}"
        path.mkdir(parents=True)
        return path

    # ------------------------------------------------------------ records
    def record_path(self, stage_key: str) -> Path:
        return self.selected_dir / f"{stage_key}.json"

    def inventory(self, generation: Path, files: Iterable[Path]) -> list[dict]:
        entries = []
        for path in sorted(Path(p) for p in files):
            if not path.is_file():
                raise IntegrityStop(f"retained artifact {path.name} is missing before promotion")
            entries.append({"path": self.rel(path), "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
        return entries

    def promote(self, stage_key: str, *, group: str, generation: Path, fingerprint: str, upstream: Mapping[str, str],
                retained: Iterable[Path], reconstructable: Iterable[Path] = (), payload: Mapping | None = None) -> dict:
        """Verifies the candidate completely, then atomically selects it."""
        _hook(stage_key, "before_inventory")
        if self.record_path(stage_key).exists():
            raise IntegrityStop(f"stage {stage_key} already has a selected record; accepted stages are never overwritten")
        record = {
            "schema": RECORD_SCHEMA,
            "stage": stage_key,
            "group": group,
            "generation": self.rel(generation),
            "fingerprint": fingerprint,
            "upstream": dict(sorted(upstream.items())),
            "retained": self.inventory(generation, retained),
            "reconstructable": sorted(self.rel(p) for p in reconstructable),
            "payload": dict(payload or {}),
            "promoted_at_utc": utc_now(),
        }
        _hook(stage_key, "before_atomic_write")
        atomic_write_json(self.record_path(stage_key), record)
        _hook(stage_key, "after_atomic_write")
        return record

    def load_record(self, stage_key: str) -> dict | None:
        path = self.record_path(stage_key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise IntegrityStop(f"selected record {stage_key} is not valid JSON") from exc

    def record_digest(self, stage_key: str) -> str:
        return sha256_file(self.record_path(stage_key))

    def verify_retained(self, record: Mapping) -> None:
        for entry in record["retained"]:
            path = self.abs(entry["path"])
            if not path.is_file():
                raise IntegrityStop(f"stage {record['stage']}: retained artifact {entry['path']} is missing")
            if path.stat().st_size != entry["byte_size"] or sha256_file(path) != entry["sha256"]:
                raise IntegrityStop(f"stage {record['stage']}: retained artifact {entry['path']} changed after acceptance")

    def current(self, stage_key: str, *, fingerprint: str) -> dict | None:
        """Returns the accepted record when current; ``None`` when absent;
        raises :class:`IntegrityStop` when present but stale or damaged."""
        record = self.load_record(stage_key)
        if record is None:
            return None
        if record.get("schema") != RECORD_SCHEMA or record.get("stage") != stage_key:
            raise IntegrityStop(f"selected record {stage_key} has an unexpected schema/stage")
        if record.get("fingerprint") != fingerprint:
            raise IntegrityStop(
                f"selected record {stage_key} is stale: its fingerprint no longer matches the current contract/upstream evidence"
            )
        self.verify_retained(record)
        return record

    def verify_provenance_closure(self, direct: Mapping[str, str]) -> dict[str, dict]:
        """Verifies the complete provenance graph reachable from ``direct``
        (``{stage: required selected-record digest}``) by recursively
        following every record's ``upstream`` mapping (H3).

        For every reachable record: the selected-record file must exist, its
        SHA-256 must equal the digest its child recorded, its schema and stage
        identity must match, and every retained artifact is rehashed.
        Missing records, digest mismatches (substitution), cycles, and
        contradictory duplicate references are integrity stops.  Returns the
        verified records keyed by stage."""
        required: dict[str, str] = {}
        state: dict[str, str] = {}
        verified: dict[str, dict] = {}

        def visit(stage: str, wanted: str, trail: tuple[str, ...]) -> None:
            if state.get(stage) == "visiting":
                raise IntegrityStop(f"provenance cycle: {' -> '.join(trail + (stage,))}")
            if stage in required and required[stage] != wanted:
                raise IntegrityStop(f"contradictory provenance references to {stage}: {required[stage][:12]}… vs {wanted[:12]}…")
            required[stage] = wanted
            if state.get(stage) == "done":
                return
            state[stage] = "visiting"
            path = self.record_path(stage)
            if not path.is_file():
                raise IntegrityStop(f"provenance: selected record {stage} referenced by {trail[-1] if trail else 'final'} is missing")
            actual = sha256_file(path)
            if actual != wanted:
                raise IntegrityStop(f"provenance: selected record {stage} digest {actual[:12]}… differs from the "
                                    f"{wanted[:12]}… recorded by {trail[-1] if trail else 'final'}")
            record = json.loads(path.read_text())
            if record.get("schema") != RECORD_SCHEMA or record.get("stage") != stage:
                raise IntegrityStop(f"provenance: selected record file {stage}.json declares stage {record.get('stage')!r}")
            upstream = record.get("upstream")
            if not isinstance(upstream, dict):
                raise IntegrityStop(f"provenance: record {stage} has no upstream mapping")
            self.verify_retained(record)
            for parent, parent_digest in sorted(upstream.items()):
                visit(parent, parent_digest, trail + (stage,))
            state[stage] = "done"
            verified[stage] = record

        for stage, wanted in sorted(direct.items()):
            visit(stage, wanted, ())
        return dict(sorted(verified.items()))

    def retained_path(self, record: Mapping, name: str) -> Path:
        for entry in record["retained"]:
            if Path(entry["path"]).name == name:
                return self.abs(entry["path"])
        raise IntegrityStop(f"stage {record['stage']} has no retained artifact named {name}")

    def selected_generations(self) -> set[str]:
        out = set()
        for path in self.selected_dir.glob("*.json"):
            record = json.loads(path.read_text())
            out.add(record["generation"])
        return out

    # ------------------------------------------------------------ cleanup
    def cleanup_reconstructable(self, record: Mapping, *, reason: str) -> dict | None:
        """Deletes only paths the record declared reconstructable, after a
        durable receipt, and refuses anything that is retained evidence."""
        targets = [self.abs(rel) for rel in record.get("reconstructable", [])]
        retained = {self.abs(entry["path"]) for entry in record["retained"]}
        protected_roots = {self.abs(entry["path"]) for entry in record["retained"]}
        generation = self.abs(record["generation"])
        items = []
        for target in targets:
            target.relative_to(generation)  # never outside its own generation
            if not target.exists():
                continue
            if target in retained or any(r == target or target in r.parents for r in protected_roots):
                raise IntegrityStop(f"cleanup refused: {self.rel(target)} contains accepted evidence")
            files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file())
            for path in files:
                if path in retained:
                    raise IntegrityStop(f"cleanup refused: {self.rel(path)} is accepted evidence")
                items.append({"path": self.rel(path), "byte_size": path.stat().st_size, "sha256": sha256_file(path)})
        if not items:
            return None
        receipt_path = self.receipts_dir / f"{Path(record['generation']).name}.cleanup.json"
        if receipt_path.exists():
            raise IntegrityStop(f"cleanup receipt {receipt_path.name} already exists")
        receipt = {"stage": record["stage"], "generation": record["generation"], "reason": reason,
                   "record_digest": self.record_digest(record["stage"]), "deleted": items,
                   "status": "receipt_written_before_deletion", "written_at_utc": utc_now()}
        atomic_write_json(receipt_path, receipt)
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        receipt["status"] = "deletion_complete"
        receipt["completed_at_utc"] = utc_now()
        atomic_write_json(receipt_path, receipt)
        self.verify_retained(record)
        return receipt

    def cleanup_abandoned_candidates(self) -> dict | None:
        """Removes unselected candidate generations left by an interrupted
        attempt; they were never evidence.  A receipt lists every file."""
        selected = self.selected_generations()
        abandoned = []
        if self.generations_dir.is_dir():
            for group in sorted(p for p in self.generations_dir.iterdir() if p.is_dir()):
                for generation in sorted(p for p in group.iterdir() if p.is_dir()):
                    if self.rel(generation) not in selected:
                        abandoned.append(generation)
        if not abandoned:
            return None
        items = []
        for generation in abandoned:
            for path in sorted(p for p in generation.rglob("*") if p.is_file()):
                items.append({"path": self.rel(path), "byte_size": path.stat().st_size})
        receipt_path = self.receipts_dir / f"abandoned_candidates__{uuid.uuid4().hex[:12]}.json"
        receipt = {"reason": "unselected candidates from an interrupted attempt", "generations": [self.rel(g) for g in abandoned],
                   "deleted": items, "status": "receipt_written_before_deletion", "written_at_utc": utc_now()}
        atomic_write_json(receipt_path, receipt)
        for generation in abandoned:
            shutil.rmtree(generation)
        receipt["status"] = "deletion_complete"
        atomic_write_json(receipt_path, receipt)
        return receipt

    # ------------------------------------------------------ attempts/lock
    def attempts(self) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(self.attempts_dir.glob("attempt_*.json"))]

    def start_attempt(self, *, mode: str, owner: Mapping) -> dict:
        index = len(list(self.attempts_dir.glob("attempt_*.json"))) + 1
        attempt = {"index": index, "mode": mode, "owner": dict(owner), "started_at_utc": utc_now(), "stop": None,
                   "signals_recorded": []}
        atomic_write_json(self.attempts_dir / f"attempt_{index:04d}.json", attempt)
        atomic_write_json(self.state_dir / "lock.json", {"attempt": index, **dict(owner)})
        return attempt

    def finish_attempt(self, attempt: dict, *, stop_class: StopClass, message: str, signals: list[str]) -> dict:
        attempt = dict(attempt)
        attempt["stop"] = {"class": stop_class.value, "message": message[:4000], "finished_at_utc": utc_now()}
        attempt["signals_recorded"] = list(signals)
        atomic_write_json(self.attempts_dir / f"attempt_{attempt['index']:04d}.json", attempt)
        if stop_class.value in {s.value for s in (StopClass.SUCCESS, StopClass.SCIENTIFIC, StopClass.INTEGRITY,
                                                  StopClass.RESOURCE_LIMIT, StopClass.TOOL_FAILURE)}:
            atomic_write_json(self.state_dir / "terminal.json", {"class": stop_class.value, "attempt": attempt["index"],
                                                                 "message": message[:4000], "at_utc": utc_now()})
        lock = self.state_dir / "lock.json"
        if lock.exists():
            lock.unlink()
        return attempt

    def terminal(self) -> dict | None:
        path = self.state_dir / "terminal.json"
        return json.loads(path.read_text()) if path.is_file() else None

    def lock(self) -> dict | None:
        path = self.state_dir / "lock.json"
        return json.loads(path.read_text()) if path.is_file() else None

    # ------------------------------------------------------------- budget
    def budget_path(self, cycle: int, width: int) -> Path:
        return self.budget_dir / f"cycle{cycle}_{width}.json"

    def budget_used(self, cycle: int, width: int) -> float:
        path = self.budget_path(cycle, width)
        if not path.is_file():
            return 0.0
        return float(sum(entry["elapsed_seconds"] for entry in json.loads(path.read_text())["entries"]))

    def charge_budget(self, cycle: int, width: int, *, label: str, elapsed: float, outcome: str) -> None:
        path = self.budget_path(cycle, width)
        data = json.loads(path.read_text()) if path.is_file() else {"cycle": cycle, "width": width, "entries": []}
        data["entries"].append({"label": label, "elapsed_seconds": elapsed, "outcome": outcome, "at_utc": utc_now()})
        atomic_write_json(path, data)


__all__ = ["Workspace", "atomic_write_json", "canonical_json", "digest", "utc_now", "PROMOTION_HOOK"]
