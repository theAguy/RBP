"""Mapper/tool command construction as argv lists (never shell strings).

Every command builder returns a ``list[str]`` meant for
``subprocess.run(argv, shell=False)``. No function in this module
interpolates arguments into a shell string, so there is no shell-injection
surface regardless of what a path or sample ID contains.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolCommand:
    tool: str
    argv: tuple[str, ...]
    pinned_version: str


def format_command(argv) -> str:
    """Human-readable rendering for logs only; never fed back to a shell."""
    return shlex.join(str(part) for part in argv)


def bwa_mem_command(reference_fasta: Path, reads_fasta: Path, *, threads: int) -> ToolCommand:
    """``bwa mem -a -Y -t N REF READS`` (primary contiguous mapper, 0.7.19)."""
    if threads < 1:
        raise ValueError("threads must be >= 1")
    argv = (
        "bwa",
        "mem",
        "-a",
        "-Y",
        "-t",
        str(threads),
        str(reference_fasta),
        str(reads_fasta),
    )
    return ToolCommand(tool="bwa", argv=argv, pinned_version="0.7.19")


def bwa_index_command(reference_fasta: Path, prefix: Path) -> ToolCommand:
    """``bwa index -p PREFIX REFERENCE``: a build-specific index prefix under
    a disposable ``indices/<build>/`` directory, never bwa's default
    in-place index next to the reference FASTA. Pass ``PREFIX`` (not the
    FASTA) as the reference argument to :func:`bwa_mem_command` afterward.
    """
    argv = ("bwa", "index", "-p", str(prefix), str(reference_fasta))
    return ToolCommand(tool="bwa", argv=argv, pinned_version="0.7.19")


def minimap2_index_command(reference_fasta: Path, output_mmi: Path) -> ToolCommand:
    """``minimap2 -x splice:sr -I 8G -d OUTPUT REFERENCE``: the frozen
    one-part index shape (preset before ``-d``; resolves to ``k=15``,
    ``w=5``, non-HPC minimizers — verified against the installed binary's
    own stderr, see :mod:`rbpbench.coordinates.indexing`).
    """
    argv = ("minimap2", "-x", "splice:sr", "-I", "8G", "-d", str(output_mmi), str(reference_fasta))
    return ToolCommand(tool="minimap2", argv=argv, pinned_version="2.31")


def minimap2_splice_command(reference_fasta: Path, reads_fasta: Path, *, threads: int) -> ToolCommand:
    """``minimap2 -ax splice:sr --secondary=yes -N 20 --MD --eqx -t N REF READS``."""
    if threads < 1:
        raise ValueError("threads must be >= 1")
    argv = (
        "minimap2",
        "-ax",
        "splice:sr",
        "--secondary=yes",
        "-N",
        "20",
        "--MD",
        "--eqx",
        "-t",
        str(threads),
        str(reference_fasta),
        str(reads_fasta),
    )
    return ToolCommand(tool="minimap2", argv=argv, pinned_version="2.31")


def seqkit_locate_command(query_fasta: Path, reference_fasta: Path) -> ToolCommand:
    """Exact FM-index substring search of ``query_fasta`` sequences against ``reference_fasta``.

    ASSUMPTION (unverified against a real SeqKit binary; flag for 001B review):
    ``--pattern-file``/``--use-fmi``/``--bed`` are SeqKit 2.13.0 flags for
    exact-substring, FM-index-mode, BED-formatted output. Confirm with
    ``seqkit locate --help`` before relying on this in Task 001B.

    ``seqkit locate`` searches both strands of the reference by default and
    reports the matching strand per hit in the BED ``strand`` column, so both
    strands are covered by exactly one invocation of this command per query
    set. Do NOT also invoke this a second time against a reverse-complemented
    query set: since each invocation already searches both strands, a second
    reverse-complemented invocation reports the same genomic occurrence again
    under the mirrored strand label, turning one real occurrence into two
    (see :mod:`rbpbench.coordinates.exact_match`).
    """
    argv = (
        "seqkit",
        "locate",
        "--ignore-case",
        "--use-fmi",
        "--bed",
        "--pattern-file",
        str(query_fasta),
        str(reference_fasta),
    )
    return ToolCommand(tool="seqkit", argv=argv, pinned_version="2.13.0")


# B3A-F1: fixed placeholder paths for the probe stage's ONE stable
# command-semantics representation -- never a specific generation's random
# candidate-workspace paths (see canonical_probe_commands below).
_CANONICAL_REFERENCE_PATH = Path("REFERENCE")
_CANONICAL_READS_PATH = Path("READS")
_CANONICAL_QUERY_PATH = Path("QUERY")


def canonical_probe_commands(*, threads: int = 1) -> tuple[str, str, str]:
    """B3A-F1: the ONE stable command-semantics representation for the
    probe stage's BWA/minimap2/SeqKit commands -- fixed placeholder paths,
    so the rendered command string is sensitive only to command FLAGS
    (which never vary per generation), never to any specific probe
    generation's random candidate-workspace/index/query paths.

    Used both to compute an accepted probe's own ``probe_fingerprint``
    (``rbpbench.coordinates.runner.stage_probe``) AND every restart
    recomputation (``rbpbench.coordinates.runner._current_canonical_probe_fingerprint``)
    -- the two call sites share this exact helper so they can never
    structurally diverge again (docs/reviews/001b_b3a_correction_review.md,
    B3A-F1: an accepted fingerprint built from real executed argv/paths
    could never equal a restart recomputation built from placeholders, even
    with every other input unchanged). The exact executed argv/paths for a
    real attempt are still preserved separately in tool provenance
    (``command_text`` on each ``ToolProvenance``), never lost -- only the
    FINGERPRINT input is canonicalized.

    Returns ``(bwa_command, minimap2_command, seqkit_command)``.
    """
    return (
        format_command(bwa_mem_command(_CANONICAL_REFERENCE_PATH, _CANONICAL_READS_PATH, threads=threads).argv),
        format_command(minimap2_splice_command(_CANONICAL_REFERENCE_PATH, _CANONICAL_READS_PATH, threads=threads).argv),
        format_command(seqkit_locate_command(_CANONICAL_QUERY_PATH, _CANONICAL_REFERENCE_PATH).argv),
    )


def resolve_version(version_argv) -> str | None:
    """Run a `--version`-style command and return its stripped stdout, or None.

    Returns ``None`` (never raises) when the executable is unavailable, which
    is expected on this implementation host; callers must record that as a
    reported gap, not silently proceed as if a version were confirmed.
    """
    try:
        completed = subprocess.run(
            list(version_argv),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or "") + (completed.stderr or "")
    return output.strip() or None
