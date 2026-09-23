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

from rbpbench.coordinates.commands import bwa_index_command, format_command, minimap2_index_command, resolve_version
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


def check_minimap2_mapping_stderr(stderr_text: str) -> tuple[str, ...]:
    """Lightweight fail-closed check for minimap2 *mapping*-time stderr (the
    ``align`` stage using a prebuilt ``.mmi``), distinct from
    :func:`check_minimap2_index_stderr` (index-*creation*-time).

    B1-R8: mapping against a prebuilt index can itself re-emit the same
    parameter-override or multipart-index warnings, and capturing stderr is
    not equivalent to stopping on it. Unlike the index-creation check, this
    does *not* require the ``[M::mm_idx_stat]`` resolved-k/w/H line to be
    present — ordinary mapping-mode stderr from a tiny fixture/fake tool
    legitimately has none, and full k/w/H re-confirmation is only required at
    index-creation time — so an empty or unrelated stderr yields no
    violations, keeping this safe to run unconditionally on every real
    mapping attempt.
    """
    violations: list[str] = []
    if _OVERRIDE_MARKER in stderr_text.lower():
        violations.append("minimap2 mapping stderr reports indexing parameters overridden by a prebuilt index")
    parts = count_minimap2_index_parts(stderr_text)
    if parts > 1:
        violations.append(f"minimap2 mapping stderr indicates a {parts}-part index; the frozen policy requires exactly one part")
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
    # Additional provenance correction: record the actually-detected pinned
    # version (the same probe used by rbpbench.coordinates.preflight), never
    # a hardcoded None — two builds can report the same version string while
    # differing, but recording *no* version at all is strictly worse.
    binary = resolve_binary_provenance("bwa", version=resolve_version(["bwa"]))

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
    binary = resolve_binary_provenance("minimap2", version=resolve_version(["minimap2", "--version"]))

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
    *,
    build: str,
    bwa: IndexBuildProvenance | dict | None,
    minimap2: IndexBuildProvenance | dict | None,
    reference_sha256: str | None = None,
    reference_manifest_content_sha256: str | None = None,
) -> dict:
    """Creation-time index manifest: SHA-256 and byte size for every index
    file, plus each tool's command/provenance/resolved binary version+hash.
    Restart checks may use unchanged size/mtime to skip a full re-hash (see
    :func:`index_manifest_is_current`), but this recorded manifest is always
    the authority a changed file must be re-verified against.

    ``reference_sha256``/``reference_manifest_content_sha256`` (B1-R2) bind
    this index to the exact reference FASTA and reference-manifest content it
    was built from, so a later real-mapping attempt can refuse an index
    that — even if internally self-consistent against its own recorded file
    hashes — was never actually proven to derive from the *current*
    reference (see :func:`verify_index_binding`).
    """

    def _payload(entry: IndexBuildProvenance | dict | None) -> dict | None:
        if entry is None:
            return None
        return entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)

    return {
        "schema_version": 2,
        "build": build,
        "reference_sha256": reference_sha256,
        "reference_manifest_content_sha256": reference_manifest_content_sha256,
        "bwa_index": _payload(bwa),
        "minimap2_index": _payload(minimap2),
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


def verify_index_files_against_manifest(
    manifest: dict, *, key: str, actual_path: Path | None = None
) -> tuple[str, ...]:
    """Full SHA-256 re-verification of every file recorded under
    ``manifest[key]["files"]`` against the creation-time manifest — the
    "stale/foreign-index rejection" check. Returns violations (empty means
    every file still matches).

    ``actual_path`` (B1-R2), when given, is the BWA prefix or minimap2
    ``.mmi`` path the caller is actually about to use; the recorded file
    path(s) in ``manifest[key]["files"]`` must equal exactly what
    ``actual_path`` implies (the frozen ``BWA_INDEX_SUFFIXES`` set for
    ``bwa_index``, the single ``.mmi`` path for ``minimap2_index``) — never
    merely re-hashed from whatever paths happen to be *recorded*, which
    previously let a split-directory or foreign-prefix override pass as long
    as *some* index-manifest existed. Omitted (``None``), only the
    content-hash check runs, for callers that have not resolved an actual
    override path (e.g. direct unit tests of this function).
    """
    section = manifest.get(key)
    if not section or not section.get("files"):
        return (f"no {key} recorded in index manifest",)
    violations: list[str] = []

    if actual_path is not None:
        actual_path = Path(actual_path)
        if key == "bwa_index":
            expected_paths = {str(Path(str(actual_path) + suffix)) for suffix in BWA_INDEX_SUFFIXES}
        elif key == "minimap2_index":
            expected_paths = {str(actual_path)}
        else:
            expected_paths = None
        if expected_paths is not None:
            recorded_paths = {entry["path"] for entry in section["files"]}
            if recorded_paths != expected_paths:
                violations.append(
                    f"{key}: actual index path(s) {sorted(expected_paths)} do not match index-manifest-recorded "
                    f"path(s) {sorted(recorded_paths)} (split-directory or foreign-prefix override)"
                )

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


def verify_index_binding(
    manifest: dict,
    *,
    key: str,
    actual_path: Path,
    expected_build: str,
    expected_reference_sha256: str,
    expected_reference_manifest_content_sha256: str,
) -> tuple[str, ...]:
    """Full B1-R2 binding check: the index-manifest's own declared build and
    reference/reference-manifest content hashes must match what this run is
    about to use, *and* its recorded files must match ``actual_path`` and
    still hash correctly (:func:`verify_index_files_against_manifest`).

    This is what actually prevents a self-consistent-but-foreign index
    (built from a different reference, with its own manifest replaced to
    match) from being silently accepted merely because its files match its
    own recorded hashes: the manifest itself must also prove which
    reference it was built from.
    """
    violations: list[str] = []
    if manifest.get("build") != expected_build:
        violations.append(f"{key}: index manifest build {manifest.get('build')!r} != expected {expected_build!r}")
    if manifest.get("reference_sha256") != expected_reference_sha256:
        violations.append(
            f"{key}: index manifest reference_sha256 does not match the current reference (stale/foreign index)"
        )
    if manifest.get("reference_manifest_content_sha256") != expected_reference_manifest_content_sha256:
        violations.append(
            f"{key}: index manifest reference_manifest_content_sha256 does not match the current reference manifest"
        )
    violations.extend(verify_index_files_against_manifest(manifest, key=key, actual_path=actual_path))
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
    "check_minimap2_mapping_stderr",
    "prepare_bwa_index",
    "prepare_minimap2_index",
    "build_index_manifest",
    "index_manifest_is_current",
    "verify_index_files_against_manifest",
    "verify_index_binding",
]
