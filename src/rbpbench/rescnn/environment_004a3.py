"""Exact-lock/runtime verification for the Task 004A-3 Newton environment."""

from __future__ import annotations

import hashlib
import argparse
import json
import os
from pathlib import Path


class ResCNN004A3EnvironmentError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside_prefix(path: Path, prefix: Path) -> bool:
    try:
        path.resolve().relative_to(prefix)
        return True
    except (OSError, ValueError):
        return False


def build_runtime_manifest(prefix: Path) -> dict[str, object]:
    """Inventory a complete immutable prefix without following symlinked dirs."""

    prefix = Path(prefix).resolve()
    if not prefix.is_dir():
        raise ResCNN004A3EnvironmentError("runtime prefix is not a directory")
    entries: list[dict[str, object]] = []
    for directory, dirnames, filenames in os.walk(prefix, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(list(dirnames)):
            path = directory_path / name
            if path.is_symlink():
                dirnames.remove(name)
                if not _inside_prefix(path, prefix):
                    raise ResCNN004A3EnvironmentError(
                        f"runtime symlink escapes prefix: {path.relative_to(prefix)}"
                    )
                entries.append({
                    "path": path.relative_to(prefix).as_posix(),
                    "type": "symlink", "target": os.readlink(path),
                })
        for name in sorted(filenames):
            path = directory_path / name
            relative = path.relative_to(prefix).as_posix()
            if path.is_symlink():
                if not _inside_prefix(path, prefix):
                    raise ResCNN004A3EnvironmentError(
                        f"runtime symlink escapes prefix: {relative}"
                    )
                entries.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
            elif path.is_file():
                entries.append({
                    "path": relative, "type": "file",
                    "byte_size": path.stat().st_size, "sha256": sha256_file(path),
                })
            else:
                raise ResCNN004A3EnvironmentError(f"unsupported runtime entry: {relative}")
    entries.sort(key=lambda entry: str(entry["path"]))
    if not entries:
        raise ResCNN004A3EnvironmentError("runtime prefix is empty")
    return {"schema_version": "task004a3_runtime_manifest_v1", "entries": entries}


def write_runtime_manifest(prefix: Path, output: Path) -> dict[str, object]:
    output = Path(output)
    if output.exists():
        raise ResCNN004A3EnvironmentError("runtime manifest output already exists")
    payload = build_runtime_manifest(prefix)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def verify_runtime(
    prefix: Path,
    *,
    manifest_path: Path,
    manifest_sha256: str,
    lock_path: Path,
    lock_sha256: str,
) -> dict[str, object]:
    prefix = Path(prefix).resolve()
    if sha256_file(manifest_path) != manifest_sha256:
        raise ResCNN004A3EnvironmentError("runtime manifest hash mismatch")
    if sha256_file(lock_path) != lock_sha256:
        raise ResCNN004A3EnvironmentError("environment lock hash mismatch")
    manifest = json.loads(Path(manifest_path).read_text())
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ResCNN004A3EnvironmentError("runtime manifest is empty")
    listed = set()
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or relative in listed:
            raise ResCNN004A3EnvironmentError("invalid/duplicate runtime path")
        listed.add(relative)
        path = prefix / relative
        if entry.get("type") == "file":
            if path.is_symlink() or not path.is_file():
                raise ResCNN004A3EnvironmentError(f"runtime file missing: {relative}")
            if path.stat().st_size != entry.get("byte_size") or sha256_file(path) != entry.get("sha256"):
                raise ResCNN004A3EnvironmentError(f"runtime file drift: {relative}")
        elif entry.get("type") == "symlink":
            if not path.is_symlink() or os.readlink(path) != entry.get("target"):
                raise ResCNN004A3EnvironmentError(f"runtime symlink drift: {relative}")
            if not _inside_prefix(path, prefix):
                raise ResCNN004A3EnvironmentError(f"runtime symlink escapes prefix: {relative}")
        else:
            raise ResCNN004A3EnvironmentError("unknown runtime manifest entry type")
    actual = set()
    for directory, dirnames, filenames in os.walk(prefix, followlinks=False):
        for name in list(dirnames):
            path = Path(directory) / name
            if path.is_symlink():
                actual.add(path.relative_to(prefix).as_posix())
                dirnames.remove(name)
        for name in filenames:
            actual.add((Path(directory) / name).relative_to(prefix).as_posix())
    if actual != listed:
        raise ResCNN004A3EnvironmentError("runtime contains missing or extra entries")
    return {
        "runtime_manifest_sha256": manifest_sha256,
        "environment_lock_sha256": lock_sha256,
        "entry_count": len(entries),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--bundle-config", type=Path, required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.bundle_config.read_text())
    result = verify_runtime(
        args.prefix, manifest_path=args.manifest,
        manifest_sha256=config["runtime_manifest_sha256"],
        lock_path=args.lock, lock_sha256=config["environment_lock_sha256"],
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
