"""Whole-run transactional artifacts; interrupted runs are never resumable."""

from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid


class ResCNNOutputError(RuntimeError):
    pass


PREDICTION_FIELDS = (
    "sample_id", "component_id", "protein_id", "fold", "partition", "seed",
    "window", "config_id", "config_hash", "label", "score",
)


PREDICTION_ROLES = {
    "validation_pilot": ("task004a_prediction_v1", "components_v2_pilot"),
    "coverage_smoke": ("task004a_smoke_prediction_v1", "components_v2_coverage_smoke"),
}


def validate_prediction_rows(
    rows, *, artifact_role: str = "validation_pilot",
    schema_version: str = "task004a_prediction_v1",
) -> int:
    if artifact_role not in PREDICTION_ROLES:
        raise ResCNNOutputError(f"unknown prediction artifact role: {artifact_role!r}")
    expected_schema, expected_fold = PREDICTION_ROLES[artifact_role]
    if schema_version != expected_schema:
        raise ResCNNOutputError(
            f"prediction role {artifact_role!r} requires schema {expected_schema!r}"
        )
    identities = set()
    count = 0
    for row in rows:
        if tuple(row) != PREDICTION_FIELDS:
            raise ResCNNOutputError(f"prediction fields drift: {tuple(row)!r}")
        if row["fold"] != expected_fold or row["partition"] != "validation":
            raise ResCNNOutputError(
                f"Task 004A {artifact_role} predictions must be validation-only {expected_fold} rows"
            )
        if int(row["window"]) != 500 or int(row["protein_id"]) not in range(1, 123):
            raise ResCNNOutputError("prediction width or protein ID drift")
        label = int(row["label"])
        score = float(row["score"])
        if label not in (0, 1) or not (0.0 <= score <= 1.0):
            raise ResCNNOutputError("prediction label or score is invalid")
        identity = (row["sample_id"], int(row["protein_id"]), int(row["seed"]), row["config_id"])
        if identity in identities:
            raise ResCNNOutputError(f"duplicate prediction identity: {identity!r}")
        identities.add(identity)
        count += 1
    if count == 0:
        raise ResCNNOutputError("prediction table is empty")
    return count


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def file_evidence(path: Path, *, relative_to: Path | None = None) -> dict[str, object]:
    if path.is_symlink():
        raise ResCNNOutputError(f"artifact symlinks are forbidden: {path}")
    if not path.is_file():
        raise ResCNNOutputError(f"artifact is not a file: {path}")
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_size += len(chunk)
    recorded_path = path.name if relative_to is None else path.relative_to(relative_to).as_posix()
    return {"path": recorded_path, "byte_size": byte_size, "sha256": digest.hexdigest()}


def generation_inventory(root: Path) -> list[dict[str, object]]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ResCNNOutputError(f"generation is not a plain directory: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ResCNNOutputError(f"generation contains a symlink: {path}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    inventory = [file_evidence(path, relative_to=root) for path in files]
    if not inventory or any(item["byte_size"] <= 0 for item in inventory):
        raise ResCNNOutputError("whole run must contain only non-empty evidence files")
    return inventory


class WholeRunGeneration(AbstractContextManager):
    def __init__(self, output_root: Path, stage: str):
        if not stage or "/" in stage or ".." in stage:
            raise ResCNNOutputError("invalid stage name")
        self.output_root = Path(output_root)
        self.stage = stage
        self.name = f"{stage}_{uuid.uuid4().hex[:12]}"
        self.candidate = self.output_root / "generations" / f".{self.name}.candidate"
        self.final = self.output_root / "generations" / self.name
        self.committed = False

    def __enter__(self):
        if self.candidate.exists() or self.final.exists():
            raise ResCNNOutputError("generation collision")
        self.candidate.mkdir(parents=True)
        return self

    def commit(self, *, fingerprint: str, payload: dict) -> Path:
        inventory = generation_inventory(self.candidate)
        record = {
            "schema_version": "task004a_whole_run_selection_v1",
            "stage": self.stage,
            "fingerprint": fingerprint,
            "generation": f"generations/{self.name}",
            "mid_run_resume_supported": False,
            "inventory": inventory,
            "payload": payload,
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
    if not stage or "/" in stage or ".." in stage:
        raise ResCNNOutputError("invalid stage name")
    selected_path = Path(output_root) / "selected" / f"{stage}.json"
    if not selected_path.exists():
        return None
    record = json.loads(selected_path.read_text())
    if record.get("schema_version") != "task004a_whole_run_selection_v1":
        raise ResCNNOutputError("selection-record schema mismatch")
    if record.get("stage") != stage:
        raise ResCNNOutputError("selection-record stage mismatch")
    if record.get("fingerprint") != fingerprint:
        return None
    if record.get("mid_run_resume_supported") is not False:
        raise ResCNNOutputError("selection record does not forbid mid-run resume")
    expected_generation_pattern = rf"generations/{re.escape(stage)}_[0-9a-f]{{12}}"
    if not isinstance(record.get("generation"), str) or re.fullmatch(
        expected_generation_pattern, record["generation"]
    ) is None:
        raise ResCNNOutputError("selection-record generation path is invalid")
    generation = Path(output_root) / record["generation"]
    if not generation.is_dir():
        raise ResCNNOutputError("selected generation is missing")
    if generation_inventory(generation) != record.get("inventory"):
        raise ResCNNOutputError("selected generation inventory drift")
    return record
