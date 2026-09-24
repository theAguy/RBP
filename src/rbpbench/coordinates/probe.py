"""B3A-A3: the guarded, build-scoped feasibility ``probe`` stage.

Pure, independently-testable building blocks for the probe stage implemented
in :func:`rbpbench.coordinates.runner.stage_probe`:

- :func:`build_pattern_fasta` -- transactional 10,100(-equivalent) pattern
  FASTA construction from the accepted biological + control FASTAs, with
  exact ID-set/count/hash evidence. Deliberately does NOT reuse
  ``rbpbench.coordinates.runner._prepare_mapping_reads``, which writes a
  mutable, fixed-path file and is not transactional.
- :func:`extract_contig_streaming` -- streams exactly one named contig's
  sequence out of an already-derived reference FASTA, never materializing
  the whole (potentially ~249-Mb) contig as one Python string.
- :func:`select_probe_window` -- a deterministic, streaming selection of one
  500-nt A/C/G/T-only window from an extracted contig.
- :func:`validate_probe_bed_rows` -- BED6/bounds/duplicate validation of
  SeqKit's ``locate`` output against the single selected contig and the
  known pattern-ID set, honestly accepting zero hits as a valid outcome.
- :func:`probe_fingerprint` -- the restart-validity fingerprint chaining
  every upstream binding (B2 sample/control hashes, reference/manifest,
  index generation, binaries, command parameters, and the current clean Git
  commit) that a probe generation is bound to.

Every one of these is pure/file-local: none of them perform authorization
checks, disk-budget accounting, or subprocess execution -- that orchestration
(gating, generation-directory management, disk budgets, and the actual
BWA/minimap2/SeqKit subprocess calls) lives in
``rbpbench.coordinates.runner.stage_probe``, reusing the same
``_new_generation_dir``/``_guarded_write_record``/``_check_disk_budget_or_fail``
machinery already used by ``stage_download``/``stage_derive``/``stage_index``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.hashing import content_fingerprint, stable_hash_rank
from rbpbench.data.audit import sha256_file

_ACGT = frozenset("ACGT")


class ProbeError(ValueError):
    """Raised when the probe stage's own consistency checks fail."""


# ---------------------------------------------------------------------------
# A3 item 2: transactional pattern-FASTA construction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternFastaResult:
    output_path: Path
    id_set: frozenset
    count: int
    biological_count: int
    control_count: int
    sha256: str
    byte_size: int

    def to_dict(self) -> dict:
        return {
            "output_path": str(self.output_path),
            "count": self.count,
            "biological_count": self.biological_count,
            "control_count": self.control_count,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
        }


def _fasta_ids_and_copy(src_path: Path, dst_handle) -> list[str]:
    ids: list[str] = []
    with Path(src_path).open() as src:
        for line in src:
            dst_handle.write(line if line.endswith("\n") else line + "\n")
            if line.startswith(">"):
                ids.append(line[1:].strip().split()[0])
    return ids


def build_pattern_fasta(
    biological_fasta: Path,
    control_fasta: Path,
    output_path: Path,
    *,
    expected_biological_ids: frozenset | None = None,
    expected_control_ids: frozenset | None = None,
) -> PatternFastaResult:
    """Concatenate ``biological_fasta`` + ``control_fasta`` into one
    transactional pattern FASTA at ``output_path`` (written to a sibling
    temporary file and only atomically promoted after every check below
    passes -- never a partially-written file left at ``output_path``).

    Validates: every biological/control record contributes exactly one ID,
    the combined ID set has no duplicates (a duplicate ID across the two
    inputs would silently merge two distinct patterns into one SeqKit hit),
    and -- when the caller supplies the accepted B2 ID sets -- that the
    biological/control ID sets exactly match what B2 actually accepted
    (real mode: exactly the 10,000/100 accepted IDs; fixture tests pass a
    smaller ``expected_*_ids`` set, or omit it to skip this specific check).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + f".tmp{os.getpid()}")
    try:
        with tmp_path.open("w") as dst:
            biological_ids = _fasta_ids_and_copy(biological_fasta, dst)
            control_ids = _fasta_ids_and_copy(control_fasta, dst)
        all_ids = biological_ids + control_ids
        id_set = frozenset(all_ids)
        if len(id_set) != len(all_ids):
            raise ProbeError(
                f"pattern FASTA has duplicate IDs across biological+control inputs: "
                f"{len(all_ids)} records but only {len(id_set)} distinct IDs"
            )
        if expected_biological_ids is not None and frozenset(biological_ids) != expected_biological_ids:
            raise ProbeError(
                "pattern FASTA biological ID set does not exactly equal the accepted B2 biological ID set "
                f"(got {len(biological_ids)} IDs, expected {len(expected_biological_ids)})"
            )
        if expected_control_ids is not None and frozenset(control_ids) != expected_control_ids:
            raise ProbeError(
                "pattern FASTA control ID set does not exactly equal the accepted B2 control ID set "
                f"(got {len(control_ids)} IDs, expected {len(expected_control_ids)})"
            )
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    os.replace(tmp_path, output_path)
    return PatternFastaResult(
        output_path=output_path,
        id_set=id_set,
        count=len(all_ids),
        biological_count=len(biological_ids),
        control_count=len(control_ids),
        sha256=sha256_file(output_path),
        byte_size=output_path.stat().st_size,
    )


# ---------------------------------------------------------------------------
# A3 item 3: streaming single-contig extraction.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContigExtraction:
    accession: str
    output_path: Path
    length: int
    upper_count: int
    lower_count: int
    ambiguous_count: int
    sha256: str

    def to_dict(self) -> dict:
        return {
            "accession": self.accession,
            "output_path": str(self.output_path),
            "length": self.length,
            "upper_count": self.upper_count,
            "lower_count": self.lower_count,
            "ambiguous_count": self.ambiguous_count,
            "sha256": self.sha256,
        }


def extract_contig_streaming(source_fasta: Path, *, accession: str, output_path: Path) -> ContigExtraction:
    """Stream exactly the ``accession`` record out of ``source_fasta`` (an
    already-derived, accepted reference FASTA -- never the raw ~1-GB
    compressed NCBI source) to ``output_path``, one line at a time. Never
    materializes the whole contig (up to ~249 Mb for a real chr1) as one
    Python string; stops reading as soon as the following record's header is
    reached.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(output_path.name + f".tmp{os.getpid()}")
    length = 0
    upper = lower = ambiguous = 0
    found = False
    try:
        with Path(source_fasta).open() as src, tmp_path.open("w") as dst:
            writing = False
            for raw_line in src:
                line = raw_line.rstrip("\r\n")
                if line.startswith(">"):
                    if found and writing:
                        # Already fully wrote the target contig; a later
                        # header means we are done -- stop without reading
                        # the rest of a potentially multi-hundred-Mb file.
                        break
                    current = line[1:].split()[0]
                    writing = current == accession
                    if writing:
                        found = True
                        dst.write(f">{current}\n")
                    continue
                if writing:
                    dst.write(line + "\n")
                    length += len(line)
                    for ch in line:
                        if ch in "ACGT":
                            upper += 1
                        elif ch in "acgt":
                            lower += 1
                        else:
                            ambiguous += 1
        if not found:
            raise ProbeError(f"accession {accession!r} not found in {source_fasta}")
    except BaseException:
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    os.replace(tmp_path, output_path)
    return ContigExtraction(
        accession=accession,
        output_path=output_path,
        length=length,
        upper_count=upper,
        lower_count=lower,
        ambiguous_count=ambiguous,
        sha256=sha256_file(output_path),
    )


# ---------------------------------------------------------------------------
# A3 item 4: deterministic A/C/G/T-only smoke-window selection.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeWindow:
    accession: str
    start: int  # 0-based
    end: int  # half-open


_SKIP_MODULUS = 997  # a fixed, arbitrary-but-deterministic bound; see module docstring


def select_probe_window(contig_path: Path, *, accession: str, contig_length: int, window_length: int = 500) -> ProbeWindow:
    """Deterministically select one ``window_length``-nt window of the
    extracted ``accession`` contig (see :func:`extract_contig_streaming`)
    that is entirely uppercase A/C/G/T -- never a window straddling an
    ambiguous ('N') base or a soft-masked (lowercase) run.

    Deterministic via :func:`rbpbench.coordinates.hashing.stable_hash_rank`
    over the accession/length (never Python's per-process-salted ``hash()``,
    and never true randomness): a fixed skip-count selects the
    ``(skip+1)``-th valid window start found while streaming the contig file
    one line at a time, so the choice depends only on the contig's own
    identity/length and content, not on incidental scan order or process
    state. Falls back to the very first valid window found if the contig has
    fewer than ``skip`` valid starts.
    """
    if window_length <= 0:
        raise ProbeError("window_length must be positive")
    skip = stable_hash_rank(accession, contig_length, "probe_window") % _SKIP_MODULUS

    found = 0
    run_len = 0
    pos = 0
    first_start: int | None = None
    with Path(contig_path).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.startswith(">"):
                continue
            for ch in line:
                if ch in _ACGT:
                    run_len += 1
                    if run_len >= window_length:
                        start = pos - window_length + 1
                        if first_start is None:
                            first_start = start
                        if found == skip:
                            return ProbeWindow(accession=accession, start=start, end=start + window_length)
                        found += 1
                else:
                    run_len = 0
                pos += 1
    if first_start is not None:
        # Fewer valid window starts than `skip` demanded: fall back to the
        # first one found rather than raising -- still fully deterministic.
        return ProbeWindow(accession=accession, start=first_start, end=first_start + window_length)
    raise ProbeError(
        f"no {window_length}-nt A/C/G/T-only window found in contig {accession!r} (length {contig_length})"
    )


# ---------------------------------------------------------------------------
# A3 item 7: BED6/bounds/duplicate validation of SeqKit's probe output.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BedValidationResult:
    hit_count: int
    distinct_hit_count: int
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> dict:
        return {"hit_count": self.hit_count, "distinct_hit_count": self.distinct_hit_count, "violations": list(self.violations)}


def validate_probe_bed_rows(
    lines: Sequence[str], *, known_pattern_ids: frozenset, contig_accession: str, contig_length: int
) -> BedValidationResult:
    """Validate every nonempty SeqKit ``locate --bed`` output row against the
    single selected contig: BED6 shape, a known pattern ID, in-bounds
    ``0 <= start < end <= contig_length``, and no duplicate counting of an
    identical ``(pattern, contig, start, end, strand)`` hit. Zero hits is an
    honest, non-failing result (empty ``lines`` -> zero violations).
    """
    violations: list[str] = []
    seen: set[tuple[str, str, int, int, str]] = set()
    hit_count = 0
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        hit_count += 1
        fields = line.split("\t")
        if len(fields) != 6:
            violations.append(f"expected exactly 6 BED6 columns, got {len(fields)}: {line!r}")
            continue
        chrom, start_s, end_s, name, _score, strand = fields
        if chrom != contig_accession:
            violations.append(f"hit on unexpected contig {chrom!r} (expected only {contig_accession!r}): {line!r}")
            continue
        if name not in known_pattern_ids:
            violations.append(f"hit has unknown pattern ID {name!r}: {line!r}")
        try:
            start, end = int(start_s), int(end_s)
        except ValueError:
            violations.append(f"non-integer BED start/end: {line!r}")
            continue
        if not (0 <= start < end <= contig_length):
            violations.append(f"out-of-bounds hit start={start} end={end} contig_length={contig_length}: {line!r}")
        key = (chrom, name, start, end, strand)
        if key in seen:
            violations.append(f"duplicate-counted hit {key}")
        seen.add(key)
    return BedValidationResult(hit_count=hit_count, distinct_hit_count=len(seen), violations=tuple(violations))


# ---------------------------------------------------------------------------
# A3 item 8: the probe restart/acceptance fingerprint.
# ---------------------------------------------------------------------------


def probe_fingerprint(
    *,
    b2_sample_sha256: str,
    b2_control_sha256: str,
    reference_sha256: str,
    reference_manifest_content_sha256: str,
    index_generation_digest: str | None,
    bwa_binary_sha256: str | None,
    minimap2_binary_sha256: str | None,
    seqkit_binary_sha256: str | None,
    bwa_command: str,
    minimap2_command: str,
    seqkit_command: str,
    git_commit: str | None,
) -> str:
    """B3A-A3 item 8: the exact chain a probe generation is bound to --
    accepted B2 sample/control hashes, raw reference/manifest hashes, the
    index generation digest, resolved binary identities, exact command
    parameters, and the current implementation's clean Git commit. Identical
    inputs always yield the same fingerprint (used both to decide whether a
    new probe attempt would reproduce an already-accepted one, and as
    restart-validity evidence), and any change to any one of these inputs
    changes it.
    """
    return content_fingerprint(
        "probe_fingerprint",
        b2_sample_sha256,
        b2_control_sha256,
        reference_sha256,
        reference_manifest_content_sha256,
        index_generation_digest,
        bwa_binary_sha256,
        minimap2_binary_sha256,
        seqkit_binary_sha256,
        bwa_command,
        minimap2_command,
        seqkit_command,
        git_commit,
    )


__all__ = [
    "ProbeError",
    "PatternFastaResult",
    "build_pattern_fasta",
    "ContigExtraction",
    "extract_contig_streaming",
    "ProbeWindow",
    "select_probe_window",
    "BedValidationResult",
    "validate_probe_bed_rows",
    "probe_fingerprint",
]
