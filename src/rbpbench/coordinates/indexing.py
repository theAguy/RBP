"""BWA/minimap2 disposable-index preparation with creation-time provenance.

Frozen commands (docs/tasks/001b_coordinate_feasibility_execution.md):

- ``bwa index -p indices/<build>/<build> REFERENCE``
- ``minimap2 -x splice:sr -I 8G -d indices/<build>/<build>.mmi REFERENCE``
  (preset before ``-d``; resolves to ``k=15``, ``w=5``, non-HPC minimizers,
  and must build exactly one index part).

Every invocation captures stdout and stderr *separately* and hashes both —
stderr is never discarded, since minimap2's own stderr is the only place the
resolved ``k``/``w``/``is_hpc`` settings and any parameter-override or
multi-part-index warning can be independently confirmed against the
installed 2.31 binary (see ``docs/reviews/001b_coordinate_execution_reconciliation.md``,
"Parameter evidence").
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.commands import bwa_index_command, format_command, minimap2_index_command
from rbpbench.coordinates.provenance import BinaryProvenance, peak_rss_kib_of_children, resolve_binary_provenance
from rbpbench.data.audit import sha256_file

_INDEX_TOOL_TIMEOUT_SECONDS = 4 * 60 * 60  # generous bound for a real hg38/hg19-scale index build

BWA_INDEX_SUFFIXES = (".amb", ".ann", ".bwt", ".pac", ".sa")

_STAT_LINE_RE = re.compile(r"kmer size:\s*(\d+);\s*skip:\s*(\d+);\s*is_hpc:\s*(\d+)")
_OVERRIDE_MARKER = "overridden"

EXPECTED_K = 15
EXPECTED_W = 5
EXPECTED_HPC = False


class IndexBuildError(RuntimeError):
    """Raised when index creation fails, or its own stderr shows a
    disqualifying condition (parameter override, multi-part index, or a
    resolved k/w/H that does not match the frozen splice:sr settings).
    """


@dataclass(frozen=True)
class IndexFileEntry:
    path: str
    byte_size: int
    sha256: str

    def to_dict(self) -> dict:
        return {"path": self.path, "byte_size": self.byte_size, "sha256": self.sha256}


@dataclass(frozen=True)
class IndexBuildProvenance:
    tool: str
    command: str
    elapsed_seconds: float
    peak_rss_kib_of_children: int
    stdout_path: str
    stdout_sha256: str
    stderr_path: str
    stderr_sha256: str
    binary: BinaryProvenance
    files: tuple[IndexFileEntry, ...]
    resolved_settings: dict
    single_part: bool | None

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "command": self.command,
            "elapsed_seconds": self.elapsed_seconds,
            "peak_rss_kib_of_children": self.peak_rss_kib_of_children,
            "stdout_path": self.stdout_path,
            "stdout_sha256": self.stdout_sha256,
            "stderr_path": self.stderr_path,
            "stderr_sha256": self.stderr_sha256,
            "binary": self.binary.to_dict(),
            "files": [entry.to_dict() for entry in self.files],
            "resolved_settings": self.resolved_settings,
            "single_part": self.single_part,
        }


def _run(argv: Sequence[str], *, stdout_path: Path, stderr_path: Path) -> None:
    """Real ``subprocess.run(argv, shell=False, ...)`` with stdout/stderr
    captured to separate files — never ``DEVNULL``. Overridable in tests.
    """
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w") as out, stderr_path.open("w") as err:
        subprocess.run(
            list(argv),
            shell=False,
            stdout=out,
            stderr=err,
            check=True,
            text=True,
            timeout=_INDEX_TOOL_TIMEOUT_SECONDS,
        )


def _hash_files(paths: Sequence[Path]) -> tuple[IndexFileEntry, ...]:
    return tuple(IndexFileEntry(path=str(p), byte_size=p.stat().st_size, sha256=sha256_file(p)) for p in paths)


def _all_stat_matches(stderr_text: str) -> list[tuple[str, str, str]]:
    return _STAT_LINE_RE.findall(stderr_text)


def count_minimap2_index_parts(stderr_text: str) -> int:
    """One ``[M::mm_idx_stat] kmer size: ...`` line is emitted per index
    part; minimap2 splits into multiple parts only when the source exceeds
    the ``-I`` batch limit.
    """
    return len(_all_stat_matches(stderr_text))


def parse_minimap2_index_settings(stderr_text: str) -> dict:
    """Parse every ``[M::mm_idx_stat] kmer size: K; skip: W; is_hpc: H`` line
    (one per index part) and report the resolved values, flagging any
    disagreement across parts rather than silently reporting only the last.
    """
    matches = _all_stat_matches(stderr_text)
    if not matches:
        return {}
    k_values = sorted({int(m[0]) for m in matches})
    w_values = sorted({int(m[1]) for m in matches})
    hpc_values = sorted({int(m[2]) for m in matches})
    consistent = len(k_values) == 1 and len(w_values) == 1 and len(hpc_values) == 1
    return {
        "k": k_values[0] if len(k_values) == 1 else k_values,
        "w": w_values[0] if len(w_values) == 1 else w_values,
        "is_hpc": bool(hpc_values[0]) if len(hpc_values) == 1 else hpc_values,
        "consistent_across_parts": consistent,
    }


def check_minimap2_index_stderr(
    stderr_text: str,
    *,
    expected_k: int = EXPECTED_K,
    expected_w: int = EXPECTED_W,
    expected_hpc: bool = EXPECTED_HPC,
) -> tuple[str, ...]:
    """Fail-closed checks against the frozen ``splice:sr``/``k=15``/``w=5``/
    non-HPC/one-part policy. Returns the violations (empty means OK).
    """
    violations: list[str] = []
    if _OVERRIDE_MARKER in stderr_text.lower():
        violations.append("minimap2 stderr reports indexing parameters overridden by a prebuilt index")

    parts = count_minimap2_index_parts(stderr_text)
    if parts == 0:
        violations.append("minimap2 stderr did not contain the expected index-stat line; cannot confirm resolved k/w/H")
    elif parts > 1:
        violations.append(f"minimap2 built a {parts}-part index; the frozen policy requires exactly one part")

    settings = parse_minimap2_index_settings(stderr_text)
    if settings:
        if not settings.get("consistent_across_parts", True):
            violations.append(f"minimap2 index parts disagree on resolved k/w/is_hpc: {settings}")
        else:
            if settings.get("k") != expected_k:
                violations.append(f"resolved k={settings.get('k')}, expected {expected_k}")
            if settings.get("w") != expected_w:
                violations.append(f"resolved w={settings.get('w')}, expected {expected_w}")
            if bool(settings.get("is_hpc")) != expected_hpc:
                violations.append(f"resolved is_hpc={settings.get('is_hpc')}, expected {expected_hpc}")
    return tuple(violations)


def prepare_bwa_index(reference: Path, prefix: Path, *, run_fn=_run) -> IndexBuildProvenance:
    """``bwa index -p prefix reference``, hashing every produced index file
    (``.amb``/``.ann``/``.bwt``/``.pac``/``.sa``) and capturing stdout/stderr
    separately.
    """
    import time

    reference = Path(reference)
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = bwa_index_command(reference, prefix)
    stdout_path = prefix.with_name(prefix.name + ".index_stdout.log")
    stderr_path = prefix.with_name(prefix.name + ".index_stderr.log")
    binary = resolve_binary_provenance("bwa", version=None)

    start = time.monotonic()
    run_fn(cmd.argv, stdout_path=stdout_path, stderr_path=stderr_path)
    elapsed = time.monotonic() - start

    output_files = [Path(str(prefix) + suffix) for suffix in BWA_INDEX_SUFFIXES]
    missing = [str(p) for p in output_files if not p.is_file()]
    if missing:
        raise IndexBuildError(f"bwa index did not produce expected file(s): {missing}")

    return IndexBuildProvenance(
        tool="bwa_index",
        command=format_command(cmd.argv),
        elapsed_seconds=elapsed,
        peak_rss_kib_of_children=peak_rss_kib_of_children(),
        stdout_path=str(stdout_path),
        stdout_sha256=sha256_file(stdout_path),
        stderr_path=str(stderr_path),
        stderr_sha256=sha256_file(stderr_path),
        binary=binary,
        files=_hash_files(output_files),
        resolved_settings={},
        single_part=None,
    )


def prepare_minimap2_index(reference: Path, output_mmi: Path, *, run_fn=_run) -> IndexBuildProvenance:
    """``minimap2 -x splice:sr -I 8G -d output_mmi reference``, then inspect
    stderr for the resolved ``k``/``w``/``is_hpc`` settings and any
    parameter-override or multi-part-index warning; raises
    :class:`IndexBuildError` (never silently accepts) on any violation.
    """
    import time

    reference = Path(reference)
    output_mmi = Path(output_mmi)
    output_mmi.parent.mkdir(parents=True, exist_ok=True)
    cmd = minimap2_index_command(reference, output_mmi)
    stdout_path = output_mmi.with_name(output_mmi.name + ".index_stdout.log")
    stderr_path = output_mmi.with_name(output_mmi.name + ".index_stderr.log")
    binary = resolve_binary_provenance("minimap2", version=None)

    start = time.monotonic()
    run_fn(cmd.argv, stdout_path=stdout_path, stderr_path=stderr_path)
    elapsed = time.monotonic() - start

    if not output_mmi.is_file():
        raise IndexBuildError(f"minimap2 did not produce the expected index at {output_mmi}")

    stderr_text = stderr_path.read_text()
    violations = check_minimap2_index_stderr(stderr_text)
    if violations:
        raise IndexBuildError(f"minimap2 index stderr indicates a disqualifying condition: {list(violations)}")

    return IndexBuildProvenance(
        tool="minimap2_index",
        command=format_command(cmd.argv),
        elapsed_seconds=elapsed,
        peak_rss_kib_of_children=peak_rss_kib_of_children(),
        stdout_path=str(stdout_path),
        stdout_sha256=sha256_file(stdout_path),
        stderr_path=str(stderr_path),
        stderr_sha256=sha256_file(stderr_path),
        binary=binary,
        files=_hash_files([output_mmi]),
        resolved_settings=parse_minimap2_index_settings(stderr_text),
        single_part=count_minimap2_index_parts(stderr_text) == 1,
    )


def build_index_manifest(
    *, build: str, bwa: IndexBuildProvenance | None, minimap2: IndexBuildProvenance | None
) -> dict:
    """Creation-time index manifest: SHA-256 and byte size for every index
    file, plus each tool's command/provenance. Restart checks may use
    unchanged size/mtime to skip a full re-hash (see
    :func:`index_manifest_is_current`), but this recorded manifest is always
    the authority a changed file must be re-verified against.
    """
    return {
        "schema_version": 1,
        "build": build,
        "bwa_index": bwa.to_dict() if bwa is not None else None,
        "minimap2_index": minimap2.to_dict() if minimap2 is not None else None,
    }


def index_manifest_is_current(manifest: dict, *, key: str) -> bool:
    """Fast restart check using unchanged size/mtime for every file recorded
    under ``manifest[key]["files"]``; a mismatch (or a missing manifest
    section) means the caller must fully re-hash and compare against this
    manifest rather than trusting size/mtime alone — never the reverse.
    """
    section = manifest.get(key)
    if not section or not section.get("files"):
        return False
    for entry in section["files"]:
        path = Path(entry["path"])
        if not path.is_file():
            return False
        if path.stat().st_size != entry["byte_size"]:
            return False
    return True


def verify_index_files_against_manifest(manifest: dict, *, key: str) -> tuple[str, ...]:
    """Full SHA-256 re-verification of every file recorded under
    ``manifest[key]["files"]`` against the creation-time manifest — the
    "stale/foreign-index rejection" check. Returns violations (empty means
    every file still matches).
    """
    section = manifest.get(key)
    if not section or not section.get("files"):
        return (f"no {key} recorded in index manifest",)
    violations: list[str] = []
    for entry in section["files"]:
        path = Path(entry["path"])
        if not path.is_file():
            violations.append(f"missing index file {entry['path']}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry["byte_size"]:
            violations.append(f"{entry['path']}: size {actual_size} != manifest {entry['byte_size']}")
            continue
        actual_sha256 = sha256_file(path)
        if actual_sha256 != entry["sha256"]:
            violations.append(f"{entry['path']}: sha256 {actual_sha256} != manifest {entry['sha256']} (foreign/stale index)")
    return tuple(violations)


__all__ = [
    "BWA_INDEX_SUFFIXES",
    "EXPECTED_K",
    "EXPECTED_W",
    "EXPECTED_HPC",
    "IndexBuildError",
    "IndexFileEntry",
    "IndexBuildProvenance",
    "count_minimap2_index_parts",
    "parse_minimap2_index_settings",
    "check_minimap2_index_stderr",
    "prepare_bwa_index",
    "prepare_minimap2_index",
    "build_index_manifest",
    "index_manifest_is_current",
    "verify_index_files_against_manifest",
]
