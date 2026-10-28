"""Transactional generation selection for Task 003B."""

from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid


class OutputError(RuntimeError):
    pass


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def file_evidence(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"path": path.name, "byte_size": size, "sha256": digest.hexdigest()}


class Generation(AbstractContextManager):
    def __init__(self, output_root: Path, stage: str):
        self.output_root = output_root
        self.stage = stage
        self.name = f"{stage}_{uuid.uuid4().hex[:12]}"
        self.candidate = output_root / "generations" / f".{self.name}.candidate"
        self.final = output_root / "generations" / self.name
        self.committed = False

    def __enter__(self) -> "Generation":
        if self.candidate.exists() or self.final.exists():
            raise OutputError("generation collision")
        self.candidate.mkdir(parents=True)
        return self

    def commit(self, *, fingerprint: str, payload: dict) -> Path:
        if self.committed:
            raise OutputError("generation already committed")
        inventory = [file_evidence(path) for path in sorted(self.candidate.iterdir()) if path.is_file()]
        if not inventory or any(item["byte_size"] <= 0 for item in inventory):
            raise OutputError("generation must contain non-empty files")
        record = {
            "schema_version": "task003b_selection_v1", "stage": self.stage,
            "fingerprint": fingerprint, "generation": f"generations/{self.name}",
            "inventory": inventory, "payload": payload,
        }
        os.replace(self.candidate, self.final)
        try:
            atomic_write(self.output_root / "selected" / f"{self.stage}.json", canonical_json(record))
        except Exception:
            shutil.rmtree(self.final, ignore_errors=True)
            raise
        self.committed = True
        return self.final

    def __exit__(self, exc_type, exc, traceback):
        if not self.committed:
            shutil.rmtree(self.candidate, ignore_errors=True)
        return False


def verify_selected(output_root: Path, stage: str, *, fingerprint: str) -> dict | None:
    path = output_root / "selected" / f"{stage}.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    if record.get("fingerprint") != fingerprint:
        return None
    generation = output_root / record["generation"]
    if not generation.is_dir():
        raise OutputError("selected generation is missing")
    for expected in record["inventory"]:
        actual = file_evidence(generation / expected["path"])
        if actual != expected:
            raise OutputError(f"selected artifact drift: {expected['path']}")
    return record
