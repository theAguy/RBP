"""Provenance capture for real tool execution: hashes, versions, timing, memory.

The parent task requires "commands, thread count, wall time, peak memory,
tool versions, index parameters, and output hashes" to be recorded for every
real mapping/exact-match invocation. :mod:`rbpbench.coordinates.preflight`
already hashes declared *input* files (references/reads); this module closes
the remaining gaps: which binary on PATH was actually resolved and its own
hash (not just its self-reported version string), wall time, an approximate
peak-memory reading, and a hash of the tool's own output file.
"""

from __future__ import annotations

import platform
import resource
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rbpbench.data.audit import sha256_file


@dataclass(frozen=True)
class BinaryProvenance:
    exe_name: str
    resolved_path: str | None
    sha256: str | None
    version: str | None

    def to_dict(self) -> dict:
        return {
            "exe_name": self.exe_name,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "version": self.version,
        }


def resolve_binary_provenance(exe_name: str, *, version: str | None) -> BinaryProvenance:
    """Resolve ``exe_name`` on PATH and hash the exact binary that would run.

    Recording only a self-reported ``--version`` string is not sufficient
    provenance: two builds could report the same version string while being
    different binaries. ``resolved_path`` and ``sha256`` are ``None`` (never
    a fabricated placeholder) when the executable cannot be found.
    """
    resolved = shutil.which(exe_name)
    digest = sha256_file(Path(resolved)) if resolved else None
    return BinaryProvenance(exe_name=exe_name, resolved_path=resolved, sha256=digest, version=version)


def peak_rss_kib_of_children() -> int:
    """Approximate peak RSS (KiB) across all reaped child processes so far.

    ``ru_maxrss`` is itself already a running maximum over every child this
    process has reaped, not a per-call delta, so a value read after running
    tool B can still reflect an earlier, larger tool A rather than B's own
    peak. This is recorded as the best available approximation, not an
    isolated per-process measurement; a real per-tool cgroup/psutil sampler
    would be needed for an exact figure, which is out of Task 001A's scope.
    """
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    raw = usage.ru_maxrss
    # Linux reports KiB; Darwin (macOS) reports bytes.
    return raw if platform.system() != "Darwin" else raw // 1024


@dataclass(frozen=True)
class ToolRunProvenance:
    tool: str
    command: str
    elapsed_seconds: float
    peak_rss_kib_of_children: int
    output_path: str
    output_sha256: str
    stderr_path: str
    stderr_sha256: str
    binary: BinaryProvenance

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "command": self.command,
            "elapsed_seconds": self.elapsed_seconds,
            "peak_rss_kib_of_children": self.peak_rss_kib_of_children,
            "output_path": self.output_path,
            "output_sha256": self.output_sha256,
            "stderr_path": self.stderr_path,
            "stderr_sha256": self.stderr_sha256,
            "binary": self.binary.to_dict(),
        }


def run_tool_with_provenance(
    argv: Sequence[str],
    *,
    tool: str,
    output_path: Path,
    stderr_path: Path,
    command_text: str,
    binary: BinaryProvenance,
    run_fn,
    run_kwargs: dict | None = None,
) -> ToolRunProvenance:
    """Run ``run_fn(argv, output_path=output_path, stderr_path=stderr_path)``
    and capture provenance.

    ``run_fn`` performs the actual ``subprocess.run(argv, shell=False, ...)``
    call (see ``rbpbench.coordinates.runner._run_tool_to_file``), writing
    stdout to ``output_path`` and stderr *separately* to ``stderr_path`` —
    stderr must never be sent to ``DEVNULL``, since a mapper's diagnostic
    warnings (e.g. minimap2's parameter-override or multipart-index
    warnings) are load-bearing evidence, not noise. This function only wraps
    that call with timing/memory/output-and-stderr-hash bookkeeping so the
    subprocess-invocation code path stays in one place. ``run_kwargs`` is
    forwarded to ``run_fn`` unchanged (e.g. a ``max_output_bytes`` cap; see
    B1-R4's live build-output-allowance enforcement).
    """
    start = time.monotonic()
    run_fn(argv, output_path=output_path, stderr_path=stderr_path, **(run_kwargs or {}))
    elapsed = time.monotonic() - start
    return ToolRunProvenance(
        tool=tool,
        command=command_text,
        elapsed_seconds=elapsed,
        peak_rss_kib_of_children=peak_rss_kib_of_children(),
        output_path=str(output_path),
        output_sha256=sha256_file(output_path),
        stderr_path=str(stderr_path),
        stderr_sha256=sha256_file(stderr_path),
        binary=binary,
    )


__all__ = [
    "BinaryProvenance",
    "ToolRunProvenance",
    "resolve_binary_provenance",
    "run_tool_with_provenance",
    "peak_rss_kib_of_children",
]
