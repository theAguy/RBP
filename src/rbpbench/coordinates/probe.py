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
- :func:`load_and_verify_b2_checkpoint` -- B3A-R1: the real trust anchor for
  the probe's pattern population. Loads the committed, accepted B2 sampling
  checkpoint manifest, verifies the manifest FILE ITSELF against a frozen
  expected hash (never a caller-supplied one), verifies its declared
  checkpoint/status identity, re-hashes every one of its named generated
  artifacts (``sample_ids.tsv``, the biological FASTA, the control FASTA)
  against the manifest's own recorded path/size/hash, and derives the exact
  accepted biological/control ID sets from that independently-verified
  evidence -- never from free-form caller-supplied hashes or counts.
- :func:`total_reference_bases` -- one streaming pass summing every base
  across an entire derived reference FASTA, used to fully validate
  ``contig_lengths`` (B3A-R2) before the largest contig is ever selected.
- :func:`compute_probe_projection` -- B3A-R6: the accepted wall-time/output/
  memory projection formulas and fail-closed gates
  (docs/tasks/001b_b3_hg38_preparation.md, "Probe projection and B4-safety
  decision") computed from one real probe's observed evidence.

Every one of these is pure/file-local: none of them perform authorization
checks, disk-budget accounting, or subprocess execution -- that orchestration
(gating, generation-directory management, disk budgets, and the actual
BWA/minimap2/SeqKit subprocess calls) lives in
``rbpbench.coordinates.runner.stage_probe``, reusing the same
``_new_generation_dir``/``_guarded_write_record``/``_check_disk_budget_or_fail``
machinery already used by ``stage_download``/``stage_derive``/``stage_index``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rbpbench.coordinates.hashing import content_fingerprint, stable_hash_rank
from rbpbench.data.audit import sha256_file

_ACGT = frozenset("ACGT")
_GIB = 1024**3

# Mirrors ``rbpbench.coordinates.runner.CONTROL_ID_PREFIX`` exactly (kept as
# an independent literal, not an import, to avoid probe.py <-> runner.py
# coupling: probe.py is pure/file-local and runner.py already imports it).
_CONTROL_ID_PREFIX = "control_"


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
# B3A-R1: the real B2-checkpoint trust anchor.
# ---------------------------------------------------------------------------


def _fasta_header_ids(path: Path) -> list[str]:
    ids: list[str] = []
    with Path(path).open() as handle:
        for line in handle:
            if line.startswith(">"):
                ids.append(line[1:].strip().split()[0])
    return ids


@dataclass(frozen=True)
class B2CheckpointEvidence:
    """The real trust anchor a real probe's pattern population is bound to:
    independently re-verified accepted-B2 sample/control FASTAs and the
    exact biological/control ID sets derived from them -- never a
    caller-supplied hash string alone.
    """

    manifest_path: Path
    manifest_sha256: str
    sample_ids_tsv: Path
    sample_fasta: Path
    control_fasta: Path
    sample_fasta_sha256: str
    control_fasta_sha256: str
    biological_ids: frozenset
    control_ids: frozenset

    def to_dict(self) -> dict:
        return {
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "sample_ids_tsv": str(self.sample_ids_tsv),
            "sample_fasta": str(self.sample_fasta),
            "sample_fasta_sha256": self.sample_fasta_sha256,
            "control_fasta": str(self.control_fasta),
            "control_fasta_sha256": self.control_fasta_sha256,
            "biological_count": len(self.biological_ids),
            "control_count": len(self.control_ids),
        }


def load_and_verify_b2_checkpoint(
    manifest_path: Path,
    *,
    repo_root: Path,
    expected_manifest_sha256: str | None,
    expected_checkpoint: str,
    expected_status: str,
    expected_biological_count: int | None,
    expected_control_count: int | None,
) -> tuple[B2CheckpointEvidence | None, tuple[str, ...]]:
    """B3A-R1: the real CLI trust anchor for the probe's pattern population.

    Unlike the old caller-supplied-hash pattern (a caller could hand
    ``stage_probe`` any two FASTAs and matching hash strings), this:

    1. hashes the accepted B2 checkpoint manifest FILE ITSELF and requires it
       to equal ``expected_manifest_sha256`` -- the frozen, committed
       trust-anchor hash from the accepted B2 acceptance review, never a
       value the caller can vary per invocation;
    2. requires the manifest's own declared ``checkpoint``/``status``
       identity to match exactly;
    3. re-hashes (path, byte size, sha256) every one of the manifest's
       ``generated_artifacts`` this probe depends on (``sample_ids.tsv``, the
       biological FASTA, the control FASTA) against what the manifest itself
       recorded -- never merely trusting that a path was supplied;
    4. derives the exact accepted biological ID set from the independently
       verified ``sample_ids.tsv`` (every row's ``sample_id`` column), and
       the exact accepted control ID set from the SAME evidence's declared
       representative stratum (the accepted first-N-sorted-representative
       rule the real B2 checkpoint manifest itself records under
       ``control_reconciliation``), cross-checked against the independently
       verified control FASTA's own actual headers -- a control FASTA whose
       real ID set does not match this derivation is flagged as a genuine
       control-ID-set mismatch, not silently accepted merely because its
       bytes hash-matched some recorded value;
    5. when supplied (real CLI mode), enforces the exact accepted population
       counts (10,000 biological + 100 controls) -- fixture/unit tests pass
       ``None`` for both to exercise this same function with a tiny
       synthetic checkpoint instead.

    Returns ``(evidence, ())`` on success, or ``(None, violations)`` -- never
    partially-populated evidence alongside violations.
    """
    manifest_path = Path(manifest_path)
    violations: list[str] = []
    if not manifest_path.is_file():
        return None, (f"B2 checkpoint manifest not found at {manifest_path}",)

    manifest_sha256 = sha256_file(manifest_path)
    if expected_manifest_sha256 is None:
        violations.append("no expected B2 checkpoint manifest sha256 supplied to bind the probe to")
    elif manifest_sha256 != expected_manifest_sha256:
        violations.append(
            f"B2 checkpoint manifest at {manifest_path} has sha256 {manifest_sha256!r}, but the accepted trust "
            f"anchor requires {expected_manifest_sha256!r} (accepted B2 checkpoint evidence has drifted)"
        )

    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        violations.append(f"B2 checkpoint manifest at {manifest_path} is unreadable/malformed: {exc}")
        return None, tuple(violations)

    if manifest.get("checkpoint") != expected_checkpoint:
        violations.append(
            f"B2 checkpoint manifest 'checkpoint' field is {manifest.get('checkpoint')!r}, expected "
            f"{expected_checkpoint!r}"
        )
    if manifest.get("status") != expected_status:
        violations.append(
            f"B2 checkpoint manifest 'status' field is {manifest.get('status')!r}, expected {expected_status!r}"
        )

    generated = ((manifest.get("input_output_hashes") or {}).get("generated_artifacts")) or {}

    def _resolve_and_verify(key: str) -> tuple[Path, str] | None:
        entry = generated.get(key)
        if not entry:
            violations.append(f"B2 checkpoint manifest is missing generated_artifacts[{key!r}]")
            return None
        raw_path = entry.get("path")
        if not raw_path:
            violations.append(f"B2 checkpoint manifest generated_artifacts[{key!r}] has no recorded path")
            return None
        resolved = Path(raw_path)
        if not resolved.is_absolute():
            resolved = Path(repo_root) / resolved
        if not resolved.is_file():
            violations.append(f"B2 checkpoint accepted artifact {key!r} not found at {resolved}")
            return None
        actual_size = resolved.stat().st_size
        expected_size = entry.get("byte_size")
        if expected_size is not None and actual_size != expected_size:
            violations.append(
                f"B2 checkpoint accepted artifact {key!r} at {resolved} has byte_size {actual_size}, but the "
                f"manifest recorded {expected_size} (drifted since acceptance)"
            )
        actual_sha256 = sha256_file(resolved)
        expected_sha256 = entry.get("sha256")
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            violations.append(
                f"B2 checkpoint accepted artifact {key!r} at {resolved} has sha256 {actual_sha256!r}, but the "
                f"manifest recorded {expected_sha256!r} (drifted since acceptance)"
            )
        return resolved, actual_sha256

    sample_ids_result = _resolve_and_verify("sample_ids_tsv")
    sample_fasta_result = _resolve_and_verify("sample_sequences_fasta")
    control_fasta_result = _resolve_and_verify("control_sequences_fasta")

    if violations or sample_ids_result is None or sample_fasta_result is None or control_fasta_result is None:
        return None, tuple(violations)

    sample_ids_path, _ = sample_ids_result
    sample_fasta_path, sample_fasta_sha256 = sample_fasta_result
    control_fasta_path, control_fasta_sha256 = control_fasta_result

    biological_ids: list[str] = []
    representative_ids: list[str] = []
    lines = sample_ids_path.read_text().splitlines()
    if not lines or not lines[0].startswith("sample_id\t"):
        violations.append(f"B2 sample_ids.tsv at {sample_ids_path} has an unexpected/missing header")
    else:
        for row in lines[1:]:
            if not row:
                continue
            cols = row.split("\t")
            if len(cols) < 3:
                violations.append(f"B2 sample_ids.tsv at {sample_ids_path} has a malformed row: {row!r}")
                continue
            sample_id, _row_index, stratum = cols[0], cols[1], cols[2]
            biological_ids.append(sample_id)
            if stratum == "representative":
                representative_ids.append(sample_id)

    biological_id_set = frozenset(biological_ids)
    if len(biological_id_set) != len(biological_ids):
        violations.append(f"B2 sample_ids.tsv at {sample_ids_path} has duplicate sample_id values")

    actual_control_ids = frozenset(_fasta_header_ids(control_fasta_path))
    derived_control_ids = frozenset(
        f"{_CONTROL_ID_PREFIX}{sid}" for sid in sorted(representative_ids)[: len(actual_control_ids)]
    )
    if actual_control_ids != derived_control_ids:
        violations.append(
            "B2 control FASTA's actual ID set does not match the accepted first-N-sorted-representative-IDs "
            "derivation from sample_ids.tsv (control-ID-set mismatch)"
        )

    if expected_biological_count is not None and len(biological_id_set) != expected_biological_count:
        violations.append(
            f"B2 accepted biological population is {len(biological_id_set)}, but real mode requires exactly "
            f"{expected_biological_count}"
        )
    if expected_control_count is not None and len(actual_control_ids) != expected_control_count:
        violations.append(
            f"B2 accepted control population is {len(actual_control_ids)}, but real mode requires exactly "
            f"{expected_control_count}"
        )

    if violations:
        return None, tuple(violations)

    return (
        B2CheckpointEvidence(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            sample_ids_tsv=sample_ids_path,
            sample_fasta=sample_fasta_path,
            control_fasta=control_fasta_path,
            sample_fasta_sha256=sample_fasta_sha256,
            control_fasta_sha256=control_fasta_sha256,
            biological_ids=biological_id_set,
            control_ids=actual_control_ids,
        ),
        (),
    )


# ---------------------------------------------------------------------------
# B3A-R2: full contig_lengths validation before selection.
# ---------------------------------------------------------------------------


def total_reference_bases(reference_fasta: Path) -> int:
    """One streaming pass (never materializing the file as one string)
    summing every non-header character across the ENTIRE derived reference
    FASTA -- every contig, not only the one about to be selected.

    B3A-R2: this is what actually proves ``contig_lengths``' declared
    per-accession values sum to the real, current on-disk reference content,
    independent of the manifest dict's own self-reported claims (a reference
    FASTA whose bytes/size/sha256 all still match ``reference_manifest`` can
    still carry a hand-edited ``contig_lengths`` entry that this exact check
    catches). Required to run BEFORE :func:`rbpbench.coordinates.derive_reference.largest_contig`
    is ever called on caller-supplied ``contig_lengths``.
    """
    total = 0
    with Path(reference_fasta).open() as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if line.startswith(">"):
                continue
            total += len(line)
    return total


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


_VALID_BED_STRANDS = frozenset({"+", "-"})


def validate_probe_bed_rows(
    lines: Iterable[str], *, known_pattern_ids: frozenset, contig_accession: str, contig_length: int
) -> BedValidationResult:
    """Validate every nonempty SeqKit ``locate --bed`` output row against the
    single selected contig: complete BED6 semantics (six columns, a known
    pattern ID, a non-negative integer score, a ``+``/``-`` strand), in-bounds
    ``0 <= start < end <= contig_length``, and no duplicate counting of an
    identical ``(pattern, contig, start, end, strand)`` hit. Zero hits is an
    honest, non-failing result (empty/exhausted ``lines`` -> zero violations).

    ``lines`` is only ever iterated once, never indexed or measured for
    length (B3A-R6): the real-mode caller passes an open file handle,
    streaming line-by-line rather than materializing a potentially
    ~1-GiB-scale BED file as one Python list via ``read_text().splitlines()``.
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
        chrom, start_s, end_s, name, score, strand = fields
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
        try:
            if int(score) < 0:
                violations.append(f"invalid BED6 score {score!r} (expected a non-negative integer): {line!r}")
        except ValueError:
            violations.append(f"non-integer BED6 score {score!r}: {line!r}")
        if strand not in _VALID_BED_STRANDS:
            violations.append(f"invalid BED6 strand {strand!r} (expected '+' or '-'): {line!r}")
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
    b2_manifest_sha256: str,
    b2_sample_sha256: str,
    b2_control_sha256: str,
    reference_sha256: str,
    reference_manifest_content_sha256: str,
    reference_manifest_raw_sha256: str | None,
    index_generation_digest: str | None,
    bwa_binary_sha256: str | None,
    minimap2_binary_sha256: str | None,
    seqkit_binary_sha256: str | None,
    bwa_binary_version: str | None,
    minimap2_binary_version: str | None,
    seqkit_binary_version: str | None,
    bwa_command: str,
    minimap2_command: str,
    seqkit_command: str,
    git_commit: str | None,
    git_clean: bool | None,
) -> str:
    """B3A-R3: the ONE stable, reproducible fingerprint contract used both to
    record an accepted probe generation's own evidence chain AND to
    recompute/compare restart validity before any skip decision -- accepted
    B2 checkpoint manifest hash plus B2 sample/control hashes, raw
    reference/manifest hashes (both canonical-content AND raw-file), the
    index generation digest, resolved binary identities (hash AND version),
    exact command parameters, the current implementation's Git commit, and
    whether the working tree is currently clean. Identical inputs always
    yield the same fingerprint, and any change to any one of these inputs
    changes it -- a change to accepted B2 evidence, reference/raw manifest,
    exact index generation, any resolved binary, command/parameter
    semantics, or implementation commit must force revalidation/re-execution
    rather than a skip.
    """
    return content_fingerprint(
        "probe_fingerprint",
        b2_manifest_sha256,
        b2_sample_sha256,
        b2_control_sha256,
        reference_sha256,
        reference_manifest_content_sha256,
        reference_manifest_raw_sha256,
        index_generation_digest,
        bwa_binary_sha256,
        minimap2_binary_sha256,
        seqkit_binary_sha256,
        bwa_binary_version,
        minimap2_binary_version,
        seqkit_binary_version,
        bwa_command,
        minimap2_command,
        seqkit_command,
        git_commit,
        git_clean,
    )


# ---------------------------------------------------------------------------
# B3A-R6: accepted wall-time/output/memory projection formulas and gates.
# ---------------------------------------------------------------------------

_WALL_TIME_PROJECTION_FACTOR = 1.5
_OUTPUT_PROJECTION_FACTOR = 2.0
_WALL_TIME_GATE_SECONDS = 4.5 * 60 * 60
_MEMORY_SAFETY_MARGIN_GIB = 2.0


@dataclass(frozen=True)
class ProbeProjection:
    largest_contig_length: int  # Lmax
    total_reference_bases: int  # Ltotal
    scale: float
    observed_wall_seconds: float
    observed_output_bytes: int
    observed_peak_rss_kib: int
    observed_hit_count: int
    zero_hit_limitation: bool
    projected_wall_seconds: float
    projected_output_bytes: float
    wall_time_gate_seconds: float
    wall_time_gate_ok: bool
    probe_output_allowance_bytes: int
    output_gate_ok: bool
    peak_rss_plus_margin_gib: float
    physical_ram_gib: float | None
    available_memory_gib: float | None
    memory_gate_ok: bool
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return len(self.violations) == 0

    def to_dict(self) -> dict:
        return {
            "largest_contig_length": self.largest_contig_length,
            "total_reference_bases": self.total_reference_bases,
            "scale": self.scale,
            "observed_wall_seconds": self.observed_wall_seconds,
            "observed_output_bytes": self.observed_output_bytes,
            "observed_peak_rss_kib": self.observed_peak_rss_kib,
            "observed_hit_count": self.observed_hit_count,
            "zero_hit_limitation": self.zero_hit_limitation,
            "projected_wall_seconds": self.projected_wall_seconds,
            "projected_output_bytes": self.projected_output_bytes,
            "wall_time_gate_seconds": self.wall_time_gate_seconds,
            "wall_time_gate_ok": self.wall_time_gate_ok,
            "probe_output_allowance_bytes": self.probe_output_allowance_bytes,
            "output_gate_ok": self.output_gate_ok,
            "peak_rss_plus_margin_gib": self.peak_rss_plus_margin_gib,
            "physical_ram_gib": self.physical_ram_gib,
            "available_memory_gib": self.available_memory_gib,
            "memory_gate_ok": self.memory_gate_ok,
            "violations": list(self.violations),
        }


def compute_probe_projection(
    *,
    largest_contig_length: int,
    total_reference_bases: int,
    observed_wall_seconds: float,
    observed_output_bytes: int,
    observed_peak_rss_kib: int,
    observed_hit_count: int,
    physical_ram_gib: float | None,
    available_memory_gib: float | None,
    probe_output_allowance_bytes: int,
) -> ProbeProjection:
    """B3A-R6: the accepted B4-safety projection formulas
    (docs/tasks/001b_b3_hg38_preparation.md, "Probe projection and B4-safety
    decision"), computed from one real probe's observed SeqKit evidence, with
    explicit fail-closed pass/fail results for all three accepted gates. A
    ``None`` physical-RAM or available-memory reading is never treated as
    passing -- the memory gate fails closed exactly like an actually-measured
    value that overflows the margin.
    """
    if largest_contig_length <= 0:
        raise ProbeError("largest_contig_length must be positive")
    if total_reference_bases < largest_contig_length:
        raise ProbeError("total_reference_bases must be >= largest_contig_length")

    scale = total_reference_bases / largest_contig_length
    projected_wall = observed_wall_seconds * scale * _WALL_TIME_PROJECTION_FACTOR
    projected_output = observed_output_bytes * scale * _OUTPUT_PROJECTION_FACTOR
    zero_hit_limitation = observed_hit_count == 0

    violations: list[str] = []

    wall_time_gate_ok = projected_wall < _WALL_TIME_GATE_SECONDS
    if not wall_time_gate_ok:
        violations.append(
            f"projected full-reference SeqKit wall time {projected_wall:.1f}s does not stay below the "
            f"{_WALL_TIME_GATE_SECONDS:.1f}s (4.5h) gate"
        )

    output_gate_ok = projected_output <= probe_output_allowance_bytes
    if not output_gate_ok:
        violations.append(
            f"projected full-reference SeqKit output {projected_output:.0f} bytes exceeds the "
            f"{probe_output_allowance_bytes}-byte provisional 1-GiB share"
        )
    # B3A-R6: zero observed hits is an honest result (never itself a
    # failure), but it must be recorded so a reviewer never misreads a
    # trivially-small projected output as real evidence of a bounded
    # full-reference output -- see the ``zero_hit_limitation`` field.

    peak_rss_plus_margin_gib = (observed_peak_rss_kib * 1024 / _GIB) + _MEMORY_SAFETY_MARGIN_GIB
    memory_gate_ok = True
    if physical_ram_gib is None:
        violations.append("physical RAM could not be determined; refusing to assume the peak-RSS-plus-2-GiB gate passes")
        memory_gate_ok = False
    elif peak_rss_plus_margin_gib > physical_ram_gib:
        violations.append(
            f"peak RSS + {_MEMORY_SAFETY_MARGIN_GIB:.0f} GiB ({peak_rss_plus_margin_gib:.2f} GiB) exceeds physical "
            f"RAM ({physical_ram_gib:.2f} GiB)"
        )
        memory_gate_ok = False
    if available_memory_gib is None:
        violations.append(
            "available/reclaimable memory could not be determined; refusing to assume the peak-RSS-plus-2-GiB "
            "gate passes"
        )
        memory_gate_ok = False
    elif peak_rss_plus_margin_gib > available_memory_gib:
        violations.append(
            f"peak RSS + {_MEMORY_SAFETY_MARGIN_GIB:.0f} GiB ({peak_rss_plus_margin_gib:.2f} GiB) exceeds measured "
            f"available/reclaimable memory ({available_memory_gib:.2f} GiB)"
        )
        memory_gate_ok = False

    return ProbeProjection(
        largest_contig_length=largest_contig_length,
        total_reference_bases=total_reference_bases,
        scale=scale,
        observed_wall_seconds=observed_wall_seconds,
        observed_output_bytes=observed_output_bytes,
        observed_peak_rss_kib=observed_peak_rss_kib,
        observed_hit_count=observed_hit_count,
        zero_hit_limitation=zero_hit_limitation,
        projected_wall_seconds=projected_wall,
        projected_output_bytes=projected_output,
        wall_time_gate_seconds=_WALL_TIME_GATE_SECONDS,
        wall_time_gate_ok=wall_time_gate_ok,
        probe_output_allowance_bytes=probe_output_allowance_bytes,
        output_gate_ok=output_gate_ok,
        peak_rss_plus_margin_gib=peak_rss_plus_margin_gib,
        physical_ram_gib=physical_ram_gib,
        available_memory_gib=available_memory_gib,
        memory_gate_ok=memory_gate_ok,
        violations=tuple(violations),
    )


__all__ = [
    "ProbeError",
    "PatternFastaResult",
    "build_pattern_fasta",
    "B2CheckpointEvidence",
    "load_and_verify_b2_checkpoint",
    "total_reference_bases",
    "ContigExtraction",
    "extract_contig_streaming",
    "ProbeWindow",
    "select_probe_window",
    "BedValidationResult",
    "validate_probe_bed_rows",
    "probe_fingerprint",
    "ProbeProjection",
    "compute_probe_projection",
]
