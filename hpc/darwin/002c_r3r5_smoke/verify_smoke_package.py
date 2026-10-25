#!/usr/bin/env python3
"""Verify the immutable smoke package or its small return ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path

MANIFEST = "SMOKE_PACKAGE_MANIFEST.json"
SIDECAR = MANIFEST + ".sha256"
IGNORED_ROOTS = {"runtime", "return"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_package(root: Path) -> dict:
    root = Path(root).resolve()
    manifest_path = root / MANIFEST
    sidecar = root / SIDECAR
    digest = sha256(manifest_path)
    if sidecar.read_text() != f"{digest}  {MANIFEST}\n":
        raise RuntimeError("package manifest sidecar mismatch")
    doc = json.loads(manifest_path.read_text())
    expected = {e["path"]: e for e in doc["entries"]}
    current = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_ROOTS]
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            rel = (rel_dir / name).as_posix()
            if name in {MANIFEST, SIDECAR, ".DS_Store"} or name.endswith((".pyc", ".pyo")):
                continue
            path = root / rel
            current[rel] = {"path": rel, "byte_size": path.stat().st_size, "sha256": sha256(path),
                            "executable": bool(path.stat().st_mode & 0o111)}
    if current != expected:
        raise RuntimeError(f"package inventory drift: missing={sorted(set(expected)-set(current))[:4]}, "
                           f"extra={sorted(set(current)-set(expected))[:4]}, "
                           f"changed={sorted(k for k in set(expected)&set(current) if expected[k] != current[k])[:4]}")
    return {"status": "VERIFIED", "source_commit": doc["source_commit"], "entries": len(expected),
            "manifest_sha256": digest}


def verify_return(path: Path) -> dict:
    path = Path(path).resolve()
    sidecar = Path(f"{path}.sha256")
    digest = sha256(path)
    if sidecar.read_text() != f"{digest}  {path.name}\n":
        raise RuntimeError("return sidecar mismatch")
    top = path.name[:-4]
    with zipfile.ZipFile(path) as handle:
        if handle.testzip() is not None:
            raise RuntimeError("return ZIP is corrupt")
        names = handle.namelist()
        if len(names) != len(set(names)) or any(not n.startswith(top + "/") for n in names):
            raise RuntimeError("return ZIP member layout is invalid")
        data = {n[len(top)+1:]: handle.read(n) for n in names}
    required = {"STATUS.json", "RETURN_INVENTORY.json", "CHECKSUMS.sha256", "test_stderr.log",
                "test_stdout.log", "resource.txt", "environment_verification.log"}
    if not required <= set(data):
        raise RuntimeError(f"return lacks {sorted(required-set(data))}")
    inv = json.loads(data["RETURN_INVENTORY.json"])
    entries = {e["path"]: e for e in inv["entries"]}
    if set(entries) | {"RETURN_INVENTORY.json", "CHECKSUMS.sha256"} != set(data):
        raise RuntimeError("return inventory does not cover the ZIP exactly")
    for rel, entry in entries.items():
        if len(data[rel]) != entry["byte_size"] or hashlib.sha256(data[rel]).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"return member differs from inventory: {rel}")
    expected_checks = {rel: hashlib.sha256(value).hexdigest() for rel, value in data.items() if rel != "CHECKSUMS.sha256"}
    checks = {}
    for line in data["CHECKSUMS.sha256"].decode().splitlines():
        token, rel = line.split("  ", 1)
        if rel in checks:
            raise RuntimeError(f"duplicate checksum entry: {rel}")
        checks[rel] = token
    if checks != expected_checks:
        raise RuntimeError("return checksums do not match members")
    status = json.loads(data["STATUS.json"])
    return {"status": status["status"], "exit_code": status["exit_code"], "archive_sha256": digest,
            "job_id": status.get("slurm_job_id"), "message": status.get("message")}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("package")
    p.add_argument("root", type=Path)
    r = sub.add_parser("return")
    r.add_argument("zip", type=Path)
    args = parser.parse_args()
    result = verify_package(args.root) if args.command == "package" else verify_return(args.zip)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
