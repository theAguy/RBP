"""Strict one-hot sequence decoding with mandatory round-trip validation."""

from __future__ import annotations

ONE_HOT_ORDER = "ACGT"
_COMPLEMENT = str.maketrans("ACGT", "TGCA")


def decode_sequence(bits: str) -> str:
    """Decode a 4*N-bit one-hot string into N bases in A/C/G/T order.

    Rejects invalid length, non-binary characters, and positions that are not
    exactly one-hot. Never repairs invalid input.
    """
    if len(bits) == 0 or len(bits) % 4 != 0:
        raise ValueError(f"sequence length {len(bits)} is not a positive multiple of 4")

    bases = []
    for start in range(0, len(bits), 4):
        group = bits[start : start + 4]
        if any(c not in "01" for c in group):
            raise ValueError(f"non-binary character in one-hot group at bit {start}")
        if group.count("1") != 1:
            raise ValueError(f"group at bit {start} is not exactly one-hot: {group!r}")
        bases.append(ONE_HOT_ORDER[group.index("1")])
    return "".join(bases)


def encode_sequence(bases: str) -> str:
    """Re-encode decoded bases back into the one-hot bit string."""
    chunks = []
    for base in bases:
        if base not in ONE_HOT_ORDER:
            raise ValueError(f"unsupported base {base!r}; expected one of {ONE_HOT_ORDER}")
        group = ["0", "0", "0", "0"]
        group[ONE_HOT_ORDER.index(base)] = "1"
        chunks.append("".join(group))
    return "".join(chunks)


def decode_and_validate(bits: str) -> str:
    """Decode ``bits`` and confirm re-encoding reproduces the source field exactly."""
    decoded = decode_sequence(bits)
    if encode_sequence(decoded) != bits:
        raise ValueError("round-trip re-encoding does not reproduce the source field")
    return decoded


def reverse_complement(bases: str) -> str:
    return bases.translate(_COMPLEMENT)[::-1]


def fasta_record(sample_id: str, sequence: str) -> str:
    """FASTA text for one record, headed only by the canonical sample ID."""
    return f">{sample_id}\n{sequence}\n"
