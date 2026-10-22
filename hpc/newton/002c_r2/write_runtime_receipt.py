#!/usr/bin/env python3
"""Write the immutable Newton runtime receipt used by the R2 launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment-prefix", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.environment_prefix.resolve()
    python, mmseqs = prefix / "bin/python", prefix / "bin/mmseqs"
    lock = prefix / "rbpbench-r2-newton.explicit.txt"
    packages = prefix / "rbpbench-r2-newton.packages.json"
    if platform.system() != "Linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise SystemExit(f"expected Linux x86_64, got {platform.system()}/{platform.machine()}")
    version = subprocess.run(
        [str(mmseqs), "version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if version != "18.8cc5c":
        raise SystemExit(f"MMseqs2 version {version!r} is not 18.8cc5c")
    package_rows = json.loads(packages.read_text())
    matches = [row for row in package_rows if row.get("name") == "mmseqs2"]
    build = matches[0].get("build_string", matches[0].get("build")) if len(matches) == 1 else None
    if len(matches) != 1 or matches[0].get("version") != "18.8cc5c" or build != "hd6d6fdc_0":
        raise SystemExit(f"unexpected MMseqs2 conda package record: {matches!r}")
    receipt = {
        "schema_version": 1,
        "platform": "linux-64",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "environment_prefix": str(prefix),
        "python_executable": str(python.resolve()),
        "python_version": subprocess.run(
            [str(python), "--version"], capture_output=True, text=True, check=True
        ).stdout.strip(),
        "mmseqs_executable": str(mmseqs.resolve()),
        "mmseqs_version": version,
        "mmseqs_conda_build": "hd6d6fdc_0",
        "mmseqs_sha256": sha256(mmseqs.resolve()),
        "explicit_lock": str(lock.resolve()),
        "explicit_lock_sha256": sha256(lock),
        "package_list": str(packages.resolve()),
        "package_list_sha256": sha256(packages),
    }
    path = prefix / "newton_runtime_receipt.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    digest = sha256(path)
    path.with_suffix(path.suffix + ".sha256").write_text(f"{digest}  {path.name}\n")
    os.chmod(path, 0o444)
    os.chmod(path.with_suffix(path.suffix + ".sha256"), 0o444)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
