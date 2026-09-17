"""Tiny reference-sequence lookup for the canonical splice-junction diagnostic.

Task 001A only ever exercises this against tiny synthetic FASTA fixtures, so a
whole-file-in-memory reader is adequate here. Task 001B, which points this at
a real hg38/hg19 FASTA, must replace :func:`load_fasta_sequences` with indexed
random access (e.g. ``samtools faidx``) rather than loading a multi-GB file
whole.
"""

from __future__ import annotations

from pathlib import Path

from rbpbench.coordinates.decode import reverse_complement

CANONICAL_DONOR = "GT"
CANONICAL_ACCEPTOR = "AG"


def load_fasta_sequences(path: Path) -> dict[str, str]:
    """Load every record of a FASTA file into memory, keyed by header ID."""
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
    genomic coordinates. Returns ``""`` for an unknown chromosome or an
    out-of-range span rather than raising, since a diagnostic lookup must
    degrade to "unknown" (see :func:`is_canonical_junction`), never crash the
    classification pipeline.
    """

    def lookup(chrom: str, start: int, end: int) -> str:
        sequence = sequences.get(chrom)
        if sequence is None or start < 0 or end > len(sequence) or start >= end:
            return ""
        return sequence[start:end]

    return lookup


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
    "intron_junction_motif",
    "is_canonical_junction",
]
