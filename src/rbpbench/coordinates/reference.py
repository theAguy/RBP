"""Reference-sequence lookup for the canonical splice-junction diagnostic.

Two access paths are provided:

- :func:`load_fasta_sequences`/:func:`make_reference_lookup`: whole-file
  in-memory loading. Adequate only for small FASTA files such as the
  decoded 500-nt sample/control sequences this package itself generates
  (megabytes, not gigabytes) — never for a reference genome.
- :class:`IndexedFastaReader` (backed by :func:`prepare_reference_index`):
  samtools-``faidx``-style indexed random access, suitable for hg38/hg19-
  scale references because it only ever does a single sequential pass to
  build a small index, then seeks directly to the requested span rather than
  loading the file whole. This is what ``rbpbench.coordinates.runner`` uses
  for the canonical-junction diagnostic against a real reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from rbpbench.coordinates.decode import reverse_complement
from rbpbench.data.audit import sha256_file

CANONICAL_DONOR = "GT"
CANONICAL_ACCEPTOR = "AG"


def load_fasta_sequences(path: Path) -> dict[str, str]:
    """Load every record of a FASTA file into memory, keyed by header ID.

    Only for small files (this package's own sample/control FASTAs); see the
    module docstring for the indexed alternative used for reference genomes.
    """
    sequences: dict[str, list[str]] = {}
    current: str | None = None
    with Path(path).open() as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(">"):
                current = line[1:].split()[0]
                sequences[current] = []
            elif current is not None:
                sequences[current].append(line)
    return {name: "".join(parts) for name, parts in sequences.items()}


def make_reference_lookup(sequences: dict[str, str]):
    """Build a ``(chrom, start, end) -> bases`` lookup over 0-based half-open
    genomic coordinates from an in-memory sequence dict (see
    :func:`load_fasta_sequences`). Returns ``""`` for an unknown chromosome
    or an out-of-range span rather than raising, since a diagnostic lookup
    must degrade to "unknown" (see :func:`is_canonical_junction`), never
    crash the classification pipeline.
    """

    def lookup(chrom: str, start: int, end: int) -> str:
        sequence = sequences.get(chrom)
        if sequence is None or start < 0 or end > len(sequence) or start >= end:
            return ""
        return sequence[start:end]

    return lookup


@dataclass(frozen=True)
class FastaIndexEntry:
    """One record of a samtools-``faidx``-compatible FASTA index.

    Assumes uniform line width within a record (standard for genome FASTA
    files, and what samtools itself assumes) except possibly a shorter final
    line.
    """

    name: str
    length: int
    offset: int  # byte offset of the first sequence base
    line_bases: int  # bases per line (excluding the newline)
    line_bytes: int  # bytes per full line (including the newline)

    def to_row(self) -> str:
        return f"{self.name}\t{self.length}\t{self.offset}\t{self.line_bases}\t{self.line_bytes}"

    @classmethod
    def from_row(cls, row: str) -> "FastaIndexEntry":
        name, length, offset, line_bases, line_bytes = row.rstrip("\n").split("\t")
        return cls(name=name, length=int(length), offset=int(offset), line_bases=int(line_bases), line_bytes=int(line_bytes))


def build_fasta_index(fasta_path: Path) -> tuple[FastaIndexEntry, ...]:
    """Build a FASTA index with a single sequential pass over the file.

    Never loads sequence content into memory beyond one line at a time, so
    this scales to a multi-gigabyte hg38/hg19 FASTA.
    """
    entries: list[FastaIndexEntry] = []
    name: str | None = None
    offset = 0
    length = 0
    line_bases: int | None = None
    line_bytes: int | None = None
    pos = 0

    def flush() -> None:
        if name is not None:
            entries.append(
                FastaIndexEntry(
                    name=name,
                    length=length,
                    offset=offset,
                    line_bases=line_bases or 0,
                    line_bytes=line_bytes or 0,
                )
            )

    with Path(fasta_path).open("rb") as handle:
        for raw_line in handle:
            line_len = len(raw_line)
            if raw_line.startswith(b">"):
                flush()
                name = raw_line[1:].split()[0].decode()
                length = 0
                line_bases = None
                line_bytes = None
                offset = pos + line_len
            else:
                stripped = raw_line.rstrip(b"\r\n")
                if line_bases is None and stripped:
                    line_bases = len(stripped)
                    line_bytes = line_len
                length += len(stripped)
            pos += line_len
    flush()
    return tuple(entries)


def write_fai(entries: Sequence[FastaIndexEntry], fai_path: Path) -> None:
    fai_path.parent.mkdir(parents=True, exist_ok=True)
    fai_path.write_text("\n".join(entry.to_row() for entry in entries) + ("\n" if entries else ""))


def load_fai(fai_path: Path) -> tuple[FastaIndexEntry, ...]:
    entries = []
    with Path(fai_path).open() as handle:
        for line in handle:
            if line.strip():
                entries.append(FastaIndexEntry.from_row(line))
    return tuple(entries)


def _index_paths_for(reference: Path) -> tuple[Path, Path]:
    reference = Path(reference)
    fai_path = reference.with_name(reference.name + ".fai")
    provenance_path = reference.with_name(reference.name + ".fai.provenance.json")
    return fai_path, provenance_path


def prepare_reference_index(reference: Path) -> tuple[tuple[FastaIndexEntry, ...], dict]:
    """Sequential index preparation/checking workflow for one reference build.

    A cached ``<reference>.fai`` is reused only when its companion
    provenance file records the *exact current* reference SHA-256 (checking,
    not blindly trusting, a stale index); otherwise the index is (re)built
    with one sequential pass (see :func:`build_fasta_index`) — never by
    loading the reference whole, so this is suitable for hg38/hg19.

    Returns the index entries and a provenance record (command, reference
    and index hashes, index size, and whether an existing index was reused)
    for :mod:`rbpbench.coordinates.provenance`.
    """
    reference = Path(reference)
    reference_sha256 = sha256_file(reference)
    fai_path, provenance_path = _index_paths_for(reference)

    reused = False
    entries: tuple[FastaIndexEntry, ...]
    if fai_path.is_file() and provenance_path.is_file():
        prior = json.loads(provenance_path.read_text())
        if prior.get("reference_sha256") == reference_sha256:
            entries = load_fai(fai_path)
            reused = True
    if not reused:
        entries = build_fasta_index(reference)
        write_fai(entries, fai_path)

    record = {
        # Task 001A builds this index in-process (no samtools dependency);
        # the command name documents the samtools-equivalent operation this
        # performs, for Task 001B provenance readability.
        "command": f"faidx {reference}",
        "reference_path": str(reference),
        "reference_sha256": reference_sha256,
        "index_path": str(fai_path),
        "index_sha256": sha256_file(fai_path),
        "index_byte_size": fai_path.stat().st_size,
        "num_contigs": len(entries),
        "reused_existing_index": reused,
    }
    provenance_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return entries, record


class IndexedFastaReader:
    """Random access to a FASTA file via a pre-built index, without ever
    loading the file whole. Suitable for hg38/hg19-scale references.
    """

    def __init__(self, fasta_path: Path, index: Sequence[FastaIndexEntry]):
        self._fasta_path = Path(fasta_path)
        self._by_name = {entry.name: entry for entry in index}

    def fetch(self, chrom: str, start: int, end: int) -> str:
        """Return bases in the 0-based half-open span ``[start, end)`` on
        ``chrom``, or ``""`` for an unknown contig or out-of-range span.
        """
        entry = self._by_name.get(chrom)
        if entry is None or start < 0 or end > entry.length or start >= end or entry.line_bases <= 0:
            return ""
        pad = entry.line_bytes - entry.line_bases
        start_line, start_col = divmod(start, entry.line_bases)
        first_byte = entry.offset + start_line * entry.line_bytes + start_col
        span = end - start
        lines_spanned = (span // entry.line_bases) + 2
        read_len = span + lines_spanned * max(pad, 1)
        with self._fasta_path.open("rb") as handle:
            handle.seek(first_byte)
            raw = handle.read(read_len)
        bases = raw.replace(b"\r", b"").replace(b"\n", b"")
        return bases[:span].decode()


def intron_junction_motif(
    reference_lookup, chrom: str, intron_start: int, intron_end: int, strand: str
) -> tuple[str, str]:
    """Return the (donor, acceptor) dinucleotide motif at one intron's
    boundaries, oriented to the transcribed strand.

    ``intron_start``/``intron_end`` are 0-based half-open genomic coordinates
    of the intron's own reference span (the bases the 'N' CIGAR op consumed).
    On a '-' strand locus the genomic 3' and 5' dinucleotides are swapped and
    reverse-complemented so a canonical intron always reads GT...AG regardless
    of strand.
    """
    genomic_donor = reference_lookup(chrom, intron_start, intron_start + 2)
    genomic_acceptor = reference_lookup(chrom, intron_end - 2, intron_end)
    if strand == "-":
        return reverse_complement(genomic_acceptor), reverse_complement(genomic_donor)
    return genomic_donor, genomic_acceptor


def is_canonical_junction(donor: str, acceptor: str) -> bool | None:
    """Whether a donor/acceptor pair is the canonical GT...AG motif.

    Returns ``None`` (unknown, never a silent "not canonical") when either
    side could not be read from the reference, e.g. no reference was
    supplied or the coordinates fell outside a known contig.
    """
    if not donor or not acceptor:
        return None
    return donor.upper() == CANONICAL_DONOR and acceptor.upper() == CANONICAL_ACCEPTOR


__all__ = [
    "CANONICAL_DONOR",
    "CANONICAL_ACCEPTOR",
    "load_fasta_sequences",
    "make_reference_lookup",
    "FastaIndexEntry",
    "build_fasta_index",
    "write_fai",
    "load_fai",
    "prepare_reference_index",
    "IndexedFastaReader",
    "intron_junction_motif",
    "is_canonical_junction",
]
