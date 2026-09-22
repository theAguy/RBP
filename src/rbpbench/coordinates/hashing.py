"""Deterministic, process-independent stable ranking.

Python's built-in ``hash()`` is salted per-process for strings, so it must
never be used for reproducible sampling decisions. Every stable rank in this
package goes through :func:`stable_hash_rank`, which hashes an explicitly
encoded field string with SHA-256.
"""

from __future__ import annotations

import hashlib

_FIELD_SEP = "\x1f"  # ASCII unit separator; never appears in our field values


def encode_fields(*fields: object) -> str:
    """Join fields into one unambiguous string for hashing."""
    return _FIELD_SEP.join(str(field) for field in fields)


def stable_hash_rank(*fields: object) -> int:
    """Deterministic 64-bit rank derived from SHA-256 over the encoded fields."""
    encoded = encode_fields(*fields).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return int(digest[:16], 16)


def label_blind_rank(seed: int, sample_id: str) -> int:
    """Rank used for the representative and filler strata.

    Label-blind: depends only on the seed and the canonical sample ID, never
    on labels, sequence, or GC content.
    """
    return stable_hash_rank(seed, "label_blind", sample_id)


def quota_rank(seed: int, sample_id: str, protein_id: int, class_label: str) -> int:
    """Rank used to order candidates for one protein/class quota."""
    return stable_hash_rank(seed, sample_id, protein_id, class_label)


def control_seed(seed: int, sample_id: str, attempt: int) -> int:
    """Derive a deterministic RNG seed for one shuffle attempt of one control."""
    return stable_hash_rank(seed, "control", sample_id, attempt)


def content_fingerprint(*fields: object) -> str:
    """Full SHA-256 hex digest over the encoded fields.

    Used for restart-state validity (see ``rbpbench.coordinates.runner``):
    unlike :func:`stable_hash_rank`, this is an equality-check fingerprint,
    not a ranking value, so it is never truncated.
    """
    return hashlib.sha256(encode_fields(*fields).encode("utf-8")).hexdigest()
