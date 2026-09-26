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
#
# ``--cov-mode``, ``--min-seq-id``, ``-c``, and ``--max-seqs`` are NOT here:
# they are supplied by :func:`_width_similarity_flags`, keyed only on the
# caller's ``width`` argument (see below).
_CLUSTER_FLAGS: tuple[str, ...] = (
    "--alignment-mode",
    "3",
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
    "-e",
    "1000",
    "--mask",
    "0",
    "-s",
    "7.5",
)

# Frozen per-width similarity rule (docs/tasks/002_sequence_clustered_partitions.md,
# "Frozen grouping rule"; docs/DECISIONS.md 2026-09-25). Sequence identity is
# shared across widths; bidirectional coverage is selected only from this
# mapping. Never caller-configurable -- a command builder that accepted
# identity/coverage as arbitrary parameters would let a future call silently
# drift from the reviewed thresholds, which is exactly what commit `6321356`
# got wrong (docs/reviews/002a_sequence_partition_pipeline_review.md).
FROZEN_MIN_SEQ_ID = "0.90"
FROZEN_MAX_SEQS = "361180"  # the complete fixed dataset universe (361,180 rows)
_WIDTH_COVERAGE: dict[int, str] = {500: "0.80", 251: "0.95", 101: "0.95"}


class UnknownWidthError(ValueError):
    """``width`` is not one of the three frozen protected widths (500, 251,
    101 nt). Raised during command construction -- before any subprocess is
    ever started -- so an unknown width can never reach process execution.
    """


def _width_similarity_flags(width: int) -> tuple[str, ...]:
    """``--min-seq-id``/``-c``/``--cov-mode``/``--max-seqs`` for one of the
    three frozen protected widths. Raises :class:`UnknownWidthError` for any
    other width, and the coverage value is selected ONLY from the frozen
    table -- there is no way for a caller to pass an arbitrary identity or
    coverage value through this module.
    """
    try:
        coverage = _WIDTH_COVERAGE[width]
    except KeyError:
        raise UnknownWidthError(
            f"width {width!r} is not one of the frozen protected widths {sorted(_WIDTH_COVERAGE)}"
        ) from None
    return ("--min-seq-id", FROZEN_MIN_SEQ_ID, "-c", coverage, "--cov-mode", "0", "--max-seqs", FROZEN_MAX_SEQS)


def with_threads(command: ToolCommand, threads: int) -> ToolCommand:
    """Appends ``--threads N`` to an already-built command.

    Thread count is a resource-management setting, not one of the frozen
    identity/coverage/``--max-seqs`` scientific flags: unlike those, it never
    changes which similarity edges MMseqs2 reports, so it is deliberately
    kept out of :func:`cluster_command`/:func:`audit_search_command`
    themselves (which accept no override parameters at all) and is instead
    applied here, once, by the runner.
    """
    if threads < 1:
        raise ValueError("threads must be >= 1")
    return ToolCommand(tool=command.tool, argv=command.argv + ("--threads", str(threads)), pinned_version=command.pinned_version)


def with_split_memory_limit(command: ToolCommand, limit: str | None) -> ToolCommand:
    """Appends ``--split-memory-limit LIMIT`` to an already-built command, or
    returns ``command`` unchanged when ``limit`` is ``None``.

    Like :func:`with_threads`, this is a resource-management setting, not a
    scientific flag -- but unlike thread count, it is NOT applied by the
    production runner: the 002B-1 real-binary gate
    (``tests/test_splits_split_memory_gate.py``) proved the candidate 8-GiB
    production value fails closed on the pinned host even for a tiny
    fixture, and that no value below the observed ~9.1-GiB fixed per-split
    floor completes at all under the frozen ``-s 7.5`` sensitivity setting,
    so genuine forced multi-way splitting can never be safely demonstrated
    on a 16-GiB host. This helper is kept only so that gate test itself (and
    any future re-attempt on a higher-memory host) has one shared, correct
    way to construct the flag -- never silently invoked by the runner with a
    hard-coded limit.
    """
    if limit is None:
        return command
    return ToolCommand(
        tool=command.tool, argv=command.argv + ("--split-memory-limit", limit), pinned_version=command.pinned_version
    )


def createdb_command(input_fasta: Path, db_path: Path, *, mmseqs_bin: str = "mmseqs") -> ToolCommand:
    """``mmseqs createdb INPUT DB --dbtype 2``: the explicit nucleotide
    database every downstream ``cluster`` call is bound to. ``cluster``
    itself exposes no way to pin nucleotide-vs-nucleotide mode directly, so
    this is the one place that makes it explicit rather than default/auto.
    """
    argv = (mmseqs_bin, "createdb", str(input_fasta), str(db_path), "--dbtype", str(NUCLEOTIDE_DBTYPE))
    return ToolCommand(tool="mmseqs_createdb", argv=argv, pinned_version=PINNED_VERSION)


def cluster_command(
    db_path: Path, cluster_prefix: Path, tmp_dir: Path, *, width: int, mmseqs_bin: str = "mmseqs"
) -> ToolCommand:
    """``mmseqs cluster DB CLUSTER_PREFIX TMP --min-seq-id 0.90 -c <width
    coverage> --cov-mode 0 --max-seqs 361180 <frozen cluster flags>``.

    ``width`` selects the frozen per-width coverage value (500/251/101 nt
    only -- see :func:`_width_similarity_flags`) and is REQUIRED: there is no
    default, so a caller can never silently construct a cluster command with
    an unreviewed similarity rule. Does NOT include ``--search-type``/
    ``--strand``: MMseqs2 18.8cc5c's own ``cluster --help`` does not list
    them (see module docstring).
    """
    similarity_flags = _width_similarity_flags(width)
    argv = (
        (mmseqs_bin, "cluster", str(db_path), str(cluster_prefix), str(tmp_dir))
        + similarity_flags
        + _CLUSTER_FLAGS
    )
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
    query_db: Path, target_db: Path, result_prefix: Path, tmp_dir: Path, *, width: int, mmseqs_bin: str = "mmseqs"
) -> ToolCommand:
    """``mmseqs search QUERY TARGET RESULT TMP --min-seq-id 0.90 -c <width
    coverage> --cov-mode 0 --max-seqs 361180 <frozen audit-search flags>``:
    the ONE command in this module that pins ``--search-type``/``--strand``
    (both exposed by ``search``, unlike ``cluster`` -- see
    :func:`cluster_command`).

    ``width`` selects the frozen per-width coverage value (500/251/101 nt
    only) exactly like :func:`cluster_command`, and is likewise REQUIRED --
    the audit search must apply the identical width-specific rule as the
    clustering it is auditing.
    """
    similarity_flags = _width_similarity_flags(width)
    argv = (
        (mmseqs_bin, "search", str(query_db), str(target_db), str(result_prefix), str(tmp_dir))
        + similarity_flags
        + _AUDIT_SEARCH_FLAGS
    )
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

    Every invocation's stdout/stderr paths carry a unique per-call suffix,
    so two calls for the SAME tool sharing one ``log_dir`` (e.g. the two
    ``createdb`` calls building a query and a target database) never
    collide: each invocation's own returned/hashed path stays valid and
    unoverwritten for the life of the generation.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    invocation_id = uuid.uuid4().hex[:16]
    stdout_path = log_dir / f"{command.tool}.{invocation_id}.stdout.log"
    stderr_path = log_dir / f"{command.tool}.{invocation_id}.stderr.log"
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
    "FROZEN_MIN_SEQ_ID",
    "FROZEN_MAX_SEQS",
    "UnknownWidthError",
    "with_threads",
    "with_split_memory_limit",
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
