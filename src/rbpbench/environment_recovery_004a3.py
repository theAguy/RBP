"""Stdlib-only validation for the Task 004A-3C-2 stopped environment recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import zipfile


class EnvironmentRecoveryError(RuntimeError):
    pass


ALLOWED_CHANNELS = frozenset({"pytorch", "nvidia", "conda-forge"})
HEX64 = re.compile(r"[0-9a-f]{64}")
HEX32 = re.compile(r"[0-9a-f]{32}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_explicit_lock(
    path: Path,
    *,
    expected_sha256: str,
    expected_entry_count: int,
) -> dict[str, object]:
    path = Path(path)
    if not HEX64.fullmatch(expected_sha256):
        raise EnvironmentRecoveryError("malformed expected lock SHA-256")
    if expected_entry_count <= 0:
        raise EnvironmentRecoveryError("expected lock entry count must be positive")
    if path.is_symlink() or not path.is_file():
        raise EnvironmentRecoveryError("explicit lock is missing or is a symlink")
    if sha256_file(path) != expected_sha256:
        raise EnvironmentRecoveryError("explicit lock SHA-256 mismatch")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise EnvironmentRecoveryError("explicit lock is not UTF-8") from exc
    markers = [index for index, line in enumerate(lines) if line == "@EXPLICIT"]
    if len(markers) != 1:
        raise EnvironmentRecoveryError("explicit lock must contain one @EXPLICIT marker")
    entries = [line for line in lines[markers[0] + 1 :] if line]
    if len(entries) != expected_entry_count or len(set(entries)) != len(entries):
        raise EnvironmentRecoveryError("explicit lock entry count/uniqueness mismatch")
    channels: set[str] = set()
    for entry in entries:
        parsed = urlsplit(entry)
        parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.scheme != "https"
            or parsed.hostname != "conda.anaconda.org"
            or len(parts) < 3
            or parts[0] not in ALLOWED_CHANNELS
            or not HEX32.fullmatch(parsed.fragment)
        ):
            raise EnvironmentRecoveryError(f"forbidden/malformed explicit lock URL: {entry}")
        channels.add(parts[0])
    if channels != ALLOWED_CHANNELS:
        raise EnvironmentRecoveryError("explicit lock channel set mismatch")
    return {
        "environment_lock_sha256": expected_sha256,
        "entry_count": len(entries),
        "channels": sorted(channels),
    }


def validate_stopped_return(
    archive: Path,
    *,
    expected_sha256: str,
    expected_lock_sha256: str,
    expected_staging: str,
    expected_final: str,
) -> dict[str, object]:
    archive = Path(archive)
    if not HEX64.fullmatch(expected_sha256):
        raise EnvironmentRecoveryError("malformed expected stopped-return SHA-256")
    if archive.is_symlink() or not archive.is_file():
        raise EnvironmentRecoveryError("stopped return is missing or is a symlink")
    if sha256_file(archive) != expected_sha256:
        raise EnvironmentRecoveryError("stopped-return SHA-256 mismatch")
    status_name = "RBP_004A3_ENVIRONMENT_RETURN/STATUS.json"
    lock_name = "RBP_004A3_ENVIRONMENT_RETURN/environment.lock"
    if not HEX64.fullmatch(expected_lock_sha256):
        raise EnvironmentRecoveryError("malformed stopped-return lock SHA-256")
    try:
        with zipfile.ZipFile(archive) as handle:
            names = handle.namelist()
            if (
                len(names) != len(set(names))
                or names.count(status_name) != 1
                or names.count(lock_name) != 1
            ):
                raise EnvironmentRecoveryError("stopped return has invalid members")
            status = json.loads(handle.read(status_name))
            embedded_lock_sha256 = hashlib.sha256(handle.read(lock_name)).hexdigest()
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise EnvironmentRecoveryError("stopped return cannot be validated") from exc
    if status.get("status") != "STOPPED":
        raise EnvironmentRecoveryError("prior return is not STOPPED")
    if status.get("staging_prefix") != expected_staging:
        raise EnvironmentRecoveryError("prior staging-prefix binding mismatch")
    if status.get("final_prefix") != expected_final:
        raise EnvironmentRecoveryError("prior final-prefix binding mismatch")
    if embedded_lock_sha256 != expected_lock_sha256:
        raise EnvironmentRecoveryError("stopped-return lock SHA-256 mismatch")
    return {
        "stopped_return_sha256": expected_sha256,
        "environment_lock_sha256": expected_lock_sha256,
        "status": "STOPPED",
        "staging_prefix": expected_staging,
        "final_prefix": expected_final,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stopped-return", type=Path, required=True)
    parser.add_argument("--stopped-return-sha256", required=True)
    parser.add_argument("--staging-prefix", required=True)
    parser.add_argument("--final-prefix", required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--lock-sha256", required=True)
    parser.add_argument("--lock-entry-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise EnvironmentRecoveryError("recovery validation output already exists")
    result = {
        "lock": validate_explicit_lock(
            args.lock,
            expected_sha256=args.lock_sha256,
            expected_entry_count=args.lock_entry_count,
        ),
        "stopped_return": validate_stopped_return(
            args.stopped_return,
            expected_sha256=args.stopped_return_sha256,
            expected_lock_sha256=args.lock_sha256,
            expected_staging=args.staging_prefix,
            expected_final=args.final_prefix,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
