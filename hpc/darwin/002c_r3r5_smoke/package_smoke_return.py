#!/usr/bin/env python3
"""Create one small, sanitized smoke-test return ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = (
    "environment_verification.log", "test_stdout.log", "test_stderr.log",
    "resource.txt", "result_check.log", "job_metadata.json",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    runtime = root / "runtime"
    returns = root / "return"
    returns.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    host = os.uname().nodename.replace("/", "_")
    name = f"RBP_002C_R3R5_SMOKE_RETURN_{stamp}_{host}"
    archive = returns / f"{name}.zip"
    sidecar = Path(f"{archive}.sha256")
    if archive.exists() or sidecar.exists():
        raise RuntimeError("refusing to overwrite an existing return")
    members = {}
    for rel in ALLOWED:
        path = runtime / rel
        members[rel] = path.read_bytes() if path.is_file() else b""
        if len(members[rel]) > 64 * 1024 * 1024:
            raise RuntimeError(f"refusing oversized log {rel}")
    status = {
        "checkpoint": "002C-R3R5-DARWIN-SMOKE",
        "status": "PASSED" if args.exit_code == 0 else "FAILED",
        "exit_code": args.exit_code,
        "message": args.message[:2000],
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "host": host,
        "source_commit": (root / "SOURCE_COMMIT.txt").read_text().strip(),
        "real_dataset_accessed": False,
        "production_r3r5_started": False,
        "gpu_used": False,
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    members["STATUS.json"] = (json.dumps(status, indent=2, sort_keys=True) + "\n").encode()
    inventory = [{"path": rel, "byte_size": len(data), "sha256": sha(data)} for rel, data in sorted(members.items())]
    members["RETURN_INVENTORY.json"] = (json.dumps({"entries": inventory}, indent=2, sort_keys=True) + "\n").encode()
    members["CHECKSUMS.sha256"] = "".join(f"{sha(data)}  {rel}\n" for rel, data in sorted(members.items())).encode()
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as handle:
        for rel, data in sorted(members.items()):
            handle.writestr(f"{name}/{rel}", data)
    sidecar.write_text(f"{file_sha(archive)}  {archive.name}\n")
    print(archive)
    print(sidecar)


if __name__ == "__main__":
    main()
