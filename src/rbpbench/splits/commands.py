"""Shell-free MMseqs2 command construction, guarded execution, and
transactional output generations.

Every builder returns a :class:`~rbpbench.coordinates.commands.ToolCommand`
whose ``argv`` is a tuple, never a shell string (same contract as
``rbpbench.coordinates.commands``) -- there is no shell-injection surface
regardless of what a path contains, and nothing here is ever run with
``shell=True``.

Command-flag distinction (frozen, ``docs/DECISIONS.md`` 2026-09-25 and
confirmed against the real pinned ``18.8cc5c`` binary's own ``--help``
text): ``mmseqs cluster`` exposes no ``--search-type``/``--strand`` flags at
all, so nucleotide clustering is instead bound by the explicit type-2
(nucleotide) input database, and both-orientation behavior is proven by a
real-binary reverse-complement fixture
(``tests/test_splits_real_binaries.py``), never by passing an unsupported
flag to ``cluster``. ``mmseqs search`` (the separate audit-search workflow)
DOES expose both flags explicitly and pins them.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from rbpbench.coordinates.commands import ToolCommand, format_command
from rbpbench.coordinates.provenance import BinaryProvenance, resolve_binary_provenance
from rbpbench.data.audit import sha256_file

PINNED_VERSION = "18.8cc5c"
PINNED_BUILD = "h8b377d6_0"
NUCLEOTIDE_DBTYPE = 2

# Frozen scientific flags (docs/tasks/002_sequence_clustered_partitions.md,
# "Frozen grouping rule"). Never caller-configurable: a command builder that
# accepted these as parameters would let a future call silently drift from
# the reviewed semantics.
_CLUSTER_FLAGS: tuple[str, ...] = (
    "--alignment-mode",
    "3",
    "--cov-mode",
    "0",
    "-e",
    "1000",
    "--mask",
    "0",
    "-s",
    "7.5",
    "--cluster-mode",
    "1",
    "--single-step-clustering",
    "1",
)

_AUDIT_SEARCH_FLAGS: tuple[str, ...] = (
    "--search-type",
    "3",
    "--strand",
    "2",
    "--alignment-mode",
    "3",
    "--cov-mode",
    "0",
    "-e",
    "1000",
    "--mask",
    "0",
    "-s",
    "7.5",
)


def createdb_command(input_fasta: Path, db_path: Path, *, mmseqs_bin: str = "mmseqs") -> ToolCommand:
    """``mmseqs createdb INPUT DB --dbtype 2``: the explicit nucleotide
    database every downstream ``cluster`` call is bound to. ``cluster``
    itself exposes no way to pin nucleotide-vs-nucleotide mode directly, so
    this is the one place that makes it explicit rather than default/auto.
    """
    argv = (mmseqs_bin, "createdb", str(input_fasta), str(db_path), "--dbtype", str(NUCLEOTIDE_DBTYPE))
    return ToolCommand(tool="mmseqs_createdb", argv=argv, pinned_version=PINNED_VERSION)


def cluster_command(db_path: Path, cluster_prefix: Path, tmp_dir: Path, *, mmseqs_bin: str = "mmseqs") -> ToolCommand:
    """``mmseqs cluster DB CLUSTER_PREFIX TMP <frozen cluster flags>``.

    Does NOT include ``--search-type``/``--strand``: MMseqs2 18.8cc5c's own
    ``cluster --help`` does not list them (see module docstring).
    """
    argv = (mmseqs_bin, "cluster", str(db_path), str(cluster_prefix), str(tmp_dir)) + _CLUSTER_FLAGS
    return ToolCommand(tool="mmseqs_cluster", argv=argv, pinned_version=PINNED_VERSION)


def createtsv_command(
    query_db: Path, target_db: Path, cluster_prefix: Path, output_tsv: Path, *, mmseqs_bin: str = "mmseqs"
) -> ToolCommand:
    """``mmseqs createtsv QUERY TARGET CLUSTER_PREFIX OUTPUT``: renders a
    cluster result as ``representative<TAB>member`` membership rows (see
    :mod:`rbpbench.splits.membership`).
    """
    argv = (mmseqs_bin, "createtsv", str(query_db), str(target_db), str(cluster_prefix), str(output_tsv))
    return ToolCommand(tool="mmseqs_createtsv", argv=argv, pinned_version=PINNED_VERSION)


def audit_search_command(
    query_db: Path, target_db: Path, result_prefix: Path, tmp_dir: Path, *, mmseqs_bin: str = "mmseqs"
) -> ToolCommand:
    """``mmseqs search QUERY TARGET RESULT TMP <frozen audit-search
    flags>``: the ONE command in this module that pins ``--search-type``/
    ``--strand`` (both exposed by ``search``, unlike ``cluster`` -- see
    :func:`cluster_command`).
    """
    argv = (mmseqs_bin, "search", str(query_db), str(target_db), str(result_prefix), str(tmp_dir)) + _AUDIT_SEARCH_FLAGS
    return ToolCommand(tool="mmseqs_search", argv=argv, pinned_version=PINNED_VERSION)


def createtsv_search_command(query_db: Path, target_db: Path, result_prefix: Path, output_tsv: Path, *, mmseqs_bin: str = "mmseqs") -> ToolCommand:
    """``mmseqs createtsv QUERY TARGET RESULT OUTPUT``: renders
    :func:`audit_search_command`'s result DB as ``query<TAB>target`` hit
    rows.
    """
    argv = (mmseqs_bin, "createtsv", str(query_db), str(target_db), str(result_prefix), str(output_tsv))
    return ToolCommand(tool="mmseqs_createtsv", argv=argv, pinned_version=PINNED_VERSION)


def _mmseqs_version_string(mmseqs_bin: str) -> str | None:
    try:
        completed = subprocess.run([mmseqs_bin, "version"], capture_output=True, text=True, timeout=30, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return (completed.stdout or "").strip() or None


def resolve_mmseqs_binary_provenance(mmseqs_bin: str = "mmseqs") -> BinaryProvenance:
    """Resolves ``mmseqs_bin`` on PATH and hashes the exact binary that
    would run, reusing ``rbpbench.coordinates.provenance``'s pattern: a
    self-reported version string alone is not sufficient identity evidence.
    """
    version = _mmseqs_version_string(mmseqs_bin)
    return resolve_binary_provenance(mmseqs_bin, version=version)


class MmseqsExecutionError(RuntimeError):
    """A pinned MMseqs2 invocation failed or timed out. Always a hard stop:
    never a signal to silently retry with different flags, and the caller's
    output-promotion step must never run afterward.
    """


_DEFAULT_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class ExecutedCommand:
    tool: str
    command_text: str
    elapsed_seconds: float
    stdout_path: Path
    stdout_sha256: str
    stderr_path: Path
    stderr_sha256: str
    binary: BinaryProvenance

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "command_text": self.command_text,
            "elapsed_seconds": self.elapsed_seconds,
            "stdout_path": str(self.stdout_path),
            "stdout_sha256": self.stdout_sha256,
            "stderr_path": str(self.stderr_path),
            "stderr_sha256": self.stderr_sha256,
            "binary": self.binary.to_dict(),
        }


def run_mmseqs_command(
    command: ToolCommand,
    *,
    log_dir: Path,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    binary: BinaryProvenance | None = None,
) -> ExecutedCommand:
    """Executes ``command.argv`` with ``shell=False``, capturing stdout and
    stderr to SEPARATE files under ``log_dir`` -- never combined, never sent
    to ``DEVNULL``, mirroring ``rbpbench.coordinates.runner``'s mapper
    convention: a tool's own diagnostics are load-bearing evidence, not
    noise.

    Raises :class:`MmseqsExecutionError` on a non-zero exit or a timeout
    (the subprocess is killed first); the caller's atomic output-promotion
    step (see :func:`new_generation_dir`) is then never reached, so a failed
    invocation can never be mistaken for -- or overwrite -- a prior accepted
    generation.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{command.tool}.stdout.log"
    stderr_path = log_dir / f"{command.tool}.stderr.log"
    if binary is None:
        binary = resolve_mmseqs_binary_provenance(command.argv[0])

    start = time.monotonic()
    with stdout_path.open("w") as out_handle, stderr_path.open("w") as err_handle:
        process = subprocess.Popen(list(command.argv), shell=False, stdout=out_handle, stderr=err_handle, text=True)
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise MmseqsExecutionError(
                f"{command.tool} timed out after {timeout_seconds}s: {format_command(command.argv)}"
            )
    elapsed = time.monotonic() - start
    if returncode != 0:
        raise MmseqsExecutionError(
            f"{command.tool} exited {returncode}: {format_command(command.argv)}; see {stderr_path}"
        )
    return ExecutedCommand(
        tool=command.tool,
        command_text=format_command(command.argv),
        elapsed_seconds=elapsed,
        stdout_path=stdout_path,
        stdout_sha256=sha256_file(stdout_path),
        stderr_path=stderr_path,
        stderr_sha256=sha256_file(stderr_path),
        binary=binary,
    )


def new_generation_dir(base_dir: Path, *, prefix: str) -> Path:
    """A fresh, uniquely-named home for one attempt's complete MMseqs2
    output set.

    Mirrors ``rbpbench.coordinates.runner._new_generation_dir``'s
    transactional-generation pattern: every file this attempt produces is
    written directly here, never at a fixed, reused final path, so
    promotion is nothing more than a caller-written record naming this
    directory afterward. A failure or interruption at any point before that
    record is written leaves any prior accepted generation completely
    untouched -- there is no shared mutable path for a partial attempt to
    corrupt.
    """
    gen_dir = base_dir / "generations" / f"{prefix}_{uuid.uuid4().hex[:16]}"
    gen_dir.mkdir(parents=True, exist_ok=False)
    return gen_dir


def hash_db_files(db_path: Path) -> dict[str, str]:
    """SHA-256 of every real file MMseqs2 produced for a ``DB`` prefix
    (``DB``, ``DB.dbtype``, ``DB.index``, ``DB.lookup``, ``DB_h``, ...):
    MMseqs2 databases are multi-file, so a single output hash is not
    sufficient provenance -- every sibling file sharing the prefix is
    included, keyed by its own name.
    """
    db_path = Path(db_path)
    hashes: dict[str, str] = {}
    for candidate in sorted(db_path.parent.glob(db_path.name + "*")):
        if candidate.is_file():
            hashes[candidate.name] = sha256_file(candidate)
    return hashes


__all__ = [
    "PINNED_VERSION",
    "PINNED_BUILD",
    "NUCLEOTIDE_DBTYPE",
    "createdb_command",
    "cluster_command",
    "createtsv_command",
    "audit_search_command",
    "createtsv_search_command",
    "resolve_mmseqs_binary_provenance",
    "MmseqsExecutionError",
    "ExecutedCommand",
    "run_mmseqs_command",
    "new_generation_dir",
    "hash_db_files",
]
