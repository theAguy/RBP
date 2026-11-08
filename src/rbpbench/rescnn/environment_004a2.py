"""Discover and bind the local CPU environment before Task 004A-2 data access."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np
import torch


class ResCNNEnvironmentError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_safe_torch_load() -> None:
    if "weights_only" not in inspect.signature(torch.load).parameters:
        raise ResCNNEnvironmentError("PyTorch lacks torch.load(..., weights_only=...)")


def _packages() -> list[dict[str, str]]:
    rows = {
        (distribution.metadata.get("Name") or distribution.name).lower(): {
            "name": distribution.metadata.get("Name") or distribution.name,
            "version": distribution.version,
        }
        for distribution in importlib.metadata.distributions()
    }
    return [rows[name] for name in sorted(rows)]


def discover_environment_manifest() -> dict[str, object]:
    require_safe_torch_load()
    executable = Path(sys.executable).resolve()
    if not executable.is_file():
        raise ResCNNEnvironmentError("Python executable cannot be resolved")
    return {
        "schema_version": "task004a2_local_environment_v1",
        "python": {
            "version": platform.python_version(),
            "executable": str(executable),
            "executable_sha256": sha256_file(executable),
        },
        "libraries": {
            "torch": torch.__version__,
            "numpy": np.__version__,
        },
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
        },
        "torch": {
            "weights_only_interface": True,
            "cuda_available": bool(torch.cuda.is_available()),
        },
        "packages": _packages(),
    }


def canonical_manifest_bytes(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")


def environment_sha256(manifest: dict[str, object]) -> str:
    return hashlib.sha256(canonical_manifest_bytes(manifest)).hexdigest()
