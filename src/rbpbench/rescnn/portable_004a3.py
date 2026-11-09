"""Inventory, cross-process comparison and sanitized returns for Task 004A-3."""

from __future__ import annotations

import hashlib
import argparse
import json
from pathlib import Path
import re
import zipfile

from rbpbench.rescnn.output import atomic_write, canonical_json, file_evidence
from rbpbench.rescnn.runtime_004a3 import (
    ResCNN004A3RuntimeError,
    RuntimeIdentity,
    require_identity_match,
)


class ResCNN004A3PortableError(RuntimeError):
    pass


FORBIDDEN_KEY_PARTS = ("sequence", "sample_id", "row_id", "prediction_rows", "checkpoint_payload")
ROW_ID = re.compile(r"\brow_[0-9]+\b")
DNA_RUN = re.compile(r"[ACGT]{50,}")


def build_inventory(root: Path) -> list[dict[str, object]]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ResCNN004A3PortableError("inventory root is not a plain directory")
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ResCNN004A3PortableError(f"symlink is forbidden: {path}")
        if path.is_file():
            entries.append(file_evidence(path, relative_to=root))
    if not entries:
        raise ResCNN004A3PortableError("inventory is empty")
    return entries


def verify_inventory(root: Path, inventory: list[dict[str, object]]) -> None:
    if build_inventory(root) != inventory:
        raise ResCNN004A3PortableError("inventory drift")


def verify_bundle(root: Path) -> list[dict[str, object]]:
    root = Path(root)
    path = root / "BUNDLE_INVENTORY.json"
    if path.is_symlink() or not path.is_file():
        raise ResCNN004A3PortableError("bundle inventory is missing")
    expected = json.loads(path.read_text())
    actual = [
        entry for entry in build_inventory(root)
        if entry["path"] != "BUNDLE_INVENTORY.json"
    ]
    if actual != expected:
        raise ResCNN004A3PortableError("bundle inventory drift")
    return actual


def _require_sanitized(value, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                raise ResCNN004A3PortableError(f"forbidden return key at {path}.{key}")
            _require_sanitized(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _require_sanitized(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if ROW_ID.search(value) or DNA_RUN.search(value) or value.endswith((".pt", ".pth")):
            raise ResCNN004A3PortableError(f"row/sequence/checkpoint content at {path}")


def compare_process_records(primary: dict, repeat: dict) -> dict[str, object]:
    required = {
        "gpu_name", "gpu_uuid", "runtime_manifest_sha256", "config_records",
        "initial_state_sha256", "order_sha256", "dropped_sha256",
    }
    if not required.issubset(primary) or not required.issubset(repeat):
        raise ResCNN004A3PortableError("process record is incomplete")
    try:
        require_identity_match(
            RuntimeIdentity(primary["gpu_name"], primary["gpu_uuid"], primary["runtime_manifest_sha256"]),
            RuntimeIdentity(repeat["gpu_name"], repeat["gpu_uuid"], repeat["runtime_manifest_sha256"]),
        )
    except ResCNN004A3RuntimeError as exc:
        raise ResCNN004A3PortableError(str(exc)) from exc
    for key in ("initial_state_sha256", "order_sha256", "dropped_sha256"):
        if primary[key] != repeat[key]:
            raise ResCNN004A3PortableError(f"primary/repeat evidence mismatch: {key}")
    if set(primary["config_records"]) != set(repeat["config_records"]):
        raise ResCNN004A3PortableError("primary/repeat config identities differ")
    scientific_fields = (
        "checkpoint_sha256", "checkpoint_model_state_sha256",
        "reloaded_model_state_sha256", "prediction_sha256",
        "loss_steps_sha256", "gradient_steps_sha256", "validation_batch_sizes",
    )
    for config_id in sorted(primary["config_records"]):
        left = primary["config_records"][config_id]
        right = repeat["config_records"][config_id]
        for field in scientific_fields:
            if field not in left or field not in right or left[field] != right[field]:
                raise ResCNN004A3PortableError(
                    f"primary/repeat {config_id} evidence mismatch: {field}"
                )
    return {
        "schema_version": "task004a3_process_comparison_v1",
        "gpu_name": primary["gpu_name"], "gpu_uuid": primary["gpu_uuid"],
        "runtime_manifest_sha256": primary["runtime_manifest_sha256"],
        "same_process_forbidden": True, "all_required_digests_equal": True,
        "config_records": primary["config_records"],
        "primary_resources": primary.get("resources"),
        "repeat_resources": repeat.get("resources"),
    }


def package_sanitized_return(root: Path, payload: dict, destination: Path) -> dict[str, object]:
    _require_sanitized(payload)
    destination = Path(destination)
    if destination.exists() or destination.with_suffix(destination.suffix + ".sha256").exists():
        raise ResCNN004A3PortableError("return destination already exists")
    staging = Path(root) / "sanitized_return"
    if staging.exists():
        raise ResCNN004A3PortableError("sanitized return staging already exists")
    staging.mkdir(parents=True)
    atomic_write(staging / "STATUS.json", canonical_json(payload))
    inventory = build_inventory(staging)
    atomic_write(staging / "INVENTORY.json", canonical_json(inventory))
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.iterdir()):
            archive.write(path, arcname=f"RBP_004A3_RETURN/{path.name}")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    atomic_write(checksum, f"{digest}  {destination.name}\n".encode())
    return {"path": str(destination), "byte_size": destination.stat().st_size, "sha256": digest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    package = sub.add_parser("package-return")
    package.add_argument("--root", type=Path, required=True)
    package.add_argument("--payload", type=Path, required=True)
    package.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "verify":
        verify_bundle(args.bundle)
    else:
        payload = json.loads(args.payload.read_text())
        print(json.dumps(package_sanitized_return(args.root, payload, args.destination), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
