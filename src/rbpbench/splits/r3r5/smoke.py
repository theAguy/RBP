"""E0 real-binary smoke fixture: reverse-complement and flag semantics.

Generated deterministically from the seed (never from real data), one tiny
FASTA per protected width.  Evenly spaced substitutions give exact identity
margins, so a local sub-alignment can never cross a threshold by chance:

* ``base``           random sequence;
* ``rc``             reverse complement of ``base`` (strand 2 must find it);
* ``hi``             1 substitution per 25 bases (96% identity) → qualifies;
* ``lo``             1 substitution per 5 bases (80% identity) → never;
* ``p88``            first 88% of ``base`` + random tail → coverage 0.88:
                     qualifies at 500 nt (-c 0.80) but not at 251/101 nt
                     (-c 0.95), proving the width-specific coverage rule;
* ``p60``            first 60% of ``base`` + random tail → never; and
* three random fillers (self-hits only).

The observed hit set must equal the expected set exactly.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Iterable

_BASES = "ACGT"


def _rng(seed: int, width: int) -> random.Random:
    return random.Random(f"r3r5-smoke-{seed}-{width}")


def _random(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(_BASES) for _ in range(n))


def _revcomp(sequence: str) -> str:
    return sequence[::-1].translate(str.maketrans("ACGT", "TGCA"))


def _substitute_every(sequence: str, step: int) -> str:
    chars = list(sequence)
    for index in range(step // 2, len(chars), step):
        chars[index] = _BASES[(_BASES.index(chars[index]) + 1) % 4]
    return "".join(chars)


def smoke_records(seed: int, width: int) -> dict[str, str]:
    rng = _rng(seed, width)
    base = _random(rng, width)
    keep88 = int(round(width * 0.88))
    keep60 = int(round(width * 0.60))
    records = {
        "smoke_base": base,
        "smoke_rc": _revcomp(base),
        "smoke_hi": _substitute_every(base, 25),
        "smoke_lo": _substitute_every(base, 5),
        "smoke_p88": base[:keep88] + _random(rng, width - keep88),
        "smoke_p60": base[:keep60] + _random(rng, width - keep60),
    }
    for i in range(3):
        records[f"smoke_filler_{i}"] = _random(rng, width)
    return records


def expected_pairs(width: int) -> set[tuple[str, str]]:
    names = ["smoke_base", "smoke_rc", "smoke_hi", "smoke_lo", "smoke_p88", "smoke_p60"] + [f"smoke_filler_{i}" for i in range(3)]
    linked = ["smoke_base", "smoke_rc", "smoke_hi"] + (["smoke_p88"] if width == 500 else [])
    pairs = {(n, n) for n in names}
    pairs |= {(a, b) for a in linked for b in linked}
    return pairs


def write_smoke_fasta(seed: int, width: int, path: Path) -> dict[str, str]:
    records = smoke_records(seed, width)
    with Path(path).open("w") as handle:
        for name, sequence in records.items():
            handle.write(f">{name}\n{sequence}\n")
    return records


def check_smoke_hits(lines: Iterable[str], width: int) -> dict:
    observed: set[tuple[str, str]] = set()
    for raw in lines:
        parts = raw.rstrip("\n").split("\t")
        if len(parts) < 2:
            raise ValueError(f"malformed smoke result row {raw!r}")
        observed.add((parts[0], parts[1]))
    expected = expected_pairs(width)
    return {
        "width": width,
        "expected_pair_count": len(expected),
        "observed_pair_count": len(observed),
        "missing": sorted(expected - observed),
        "unexpected": sorted(observed - expected),
        "passed": observed == expected,
    }


__all__ = ["smoke_records", "expected_pairs", "write_smoke_fasta", "check_smoke_hits"]
