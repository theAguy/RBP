"""Streaming strict one-hot decode into deterministic 500/251/101-nt
center-window FASTAs, keyed by canonical ``row_<index>`` sample IDs.

Reuses :mod:`rbpbench.coordinates.decode`'s strict, round-trip-validated
one-hot decoder rather than duplicating it: the production one-hot contract
(``docs/DATA.md``) is identical for both pipelines -- 2000 bits decode to
exactly 500 nt in A/C/G/T order, and any row that cannot be decoded and
re-encoded back to its exact source field is rejected, never repaired.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from rbpbench.coordinates.decode import decode_and_validate, fasta_record

FULL_WIDTH = 500
CENTER_WIDTHS: tuple[int, ...] = (500, 251, 101)


def sample_id(row_index: int) -> str:
    """The canonical, stable sample ID (``docs/DATA.md``): stable until
    genomic coordinates are recovered, and never replaced by them even then.
    """
    return f"row_{row_index}"


def center_window(sequence: str, width: int) -> str:
    """Deterministic centered crop of ``sequence`` to ``width`` nt.

    ``start = floor((len(sequence) - width) / 2)`` is a fixed rule (not a
    caller-tunable parameter), so regenerating the crop for the same input
    always produces the identical window. ``width == len(sequence)`` returns
    the sequence unchanged, so the 500-nt "crop" in :data:`CENTER_WIDTHS` is
    just the decoded full window.
    """
    if width <= 0:
        raise ValueError(f"crop width must be positive, got {width}")
    if width > len(sequence):
        raise ValueError(f"crop width {width} exceeds sequence length {len(sequence)}")
    if width == len(sequence):
        return sequence
    start = (len(sequence) - width) // 2
    return sequence[start : start + width]


class DecodeError(ValueError):
    """A strict-decode failure for one row: fails that row (and, for the
    streaming FASTA writer, the whole run) closed rather than silently
    dropping, repairing, or fabricating a sequence for it.
    """

    def __init__(self, row_index: int, row_sample_id: str, reason: str):
        self.row_index = row_index
        self.sample_id = row_sample_id
        self.reason = reason
        super().__init__(f"{row_sample_id} (row {row_index}): {reason}")


@dataclass(frozen=True)
class DecodedRow:
    row_index: int
    sample_id: str
    windows: Mapping[int, str]


def decode_row(row_index: int, one_hot_bits: str, *, widths: tuple[int, ...] = CENTER_WIDTHS) -> DecodedRow:
    """Strictly decodes one row's one-hot ``sequence`` field and crops it to
    every width in ``widths``. Raises :class:`DecodeError` (never a silent
    skip or repair) for invalid length, non-binary characters, a
    not-exactly-one-hot group, a failed round-trip re-encode, or a decoded
    length other than :data:`FULL_WIDTH`.
    """
    row_sample_id = sample_id(row_index)
    try:
        full = decode_and_validate(one_hot_bits)
    except ValueError as exc:
        raise DecodeError(row_index, row_sample_id, str(exc)) from exc
    if len(full) != FULL_WIDTH:
        raise DecodeError(row_index, row_sample_id, f"decoded length {len(full)} != {FULL_WIDTH}")
    windows = {width: center_window(full, width) for width in widths}
    return DecodedRow(row_index=row_index, sample_id=row_sample_id, windows=windows)


def iter_csv_one_hot_rows(csv_path: Path) -> Iterator[tuple[int, str]]:
    """Streams ``(row_index, one_hot_bits)`` pairs from a ``sequence,labels``
    CSV (``docs/DATA.md``) without materializing the file; ``labels`` is
    intentionally never read here -- grouping is label-blind by design
    (``docs/tasks/002_sequence_clustered_partitions.md``, "Scientific
    boundary").
    """
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row_index, row in enumerate(reader):
            yield row_index, row["sequence"]


def iter_decode_rows(
    rows: Iterable[tuple[int, str]], *, widths: tuple[int, ...] = CENTER_WIDTHS
) -> Iterator[DecodedRow]:
    """Streams :func:`decode_row` over ``rows``; propagates the first
    :class:`DecodeError` immediately (fail closed), never skipping past a
    bad row to keep the stream alive.
    """
    for row_index, one_hot_bits in rows:
        yield decode_row(row_index, one_hot_bits, widths=widths)


@dataclass(frozen=True)
class DecodeReport:
    total_rows: int
    accepted_sample_ids: tuple[str, ...]
    output_paths: Mapping[int, Path]


def stream_decode_to_fastas(
    csv_path: Path,
    output_dir: Path,
    *,
    widths: tuple[int, ...] = CENTER_WIDTHS,
    filename_template: str = "sequence_partitions_width_{width}.fasta",
) -> DecodeReport:
    """Single streaming pass over ``csv_path``: decodes and crops each row
    once, writing every width's FASTA record as it goes (never materializing
    all rows, or even all of one row's windows across the whole file, in
    memory at once).

    A single :class:`DecodeError` anywhere in the input aborts the ENTIRE
    run before any output is promoted: every width is written to a
    ``.tmp``-suffixed path first, and only renamed onto the final path (one
    atomic :meth:`Path.replace` per width) after every row has decoded
    successfully. A prior accepted generation at ``output_dir`` is therefore
    never partially overwritten by a failed or interrupted re-run.
    """
    if not widths:
        raise ValueError("widths must be non-empty")
    output_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {width: output_dir / filename_template.format(width=width) for width in widths}
    tmp_paths = {width: path.with_name(path.name + ".tmp") for width, path in final_paths.items()}

    accepted_ids: list[str] = []
    total_rows = 0
    handles = {width: tmp_paths[width].open("w") for width in widths}
    try:
        for row_index, one_hot_bits in iter_csv_one_hot_rows(csv_path):
            total_rows += 1
            decoded = decode_row(row_index, one_hot_bits, widths=widths)
            for width in widths:
                handles[width].write(fasta_record(decoded.sample_id, decoded.windows[width]))
            accepted_ids.append(decoded.sample_id)
    except BaseException:
        for handle in handles.values():
            handle.close()
        for tmp_path in tmp_paths.values():
            tmp_path.unlink(missing_ok=True)
        raise
    finally:
        for handle in handles.values():
            if not handle.closed:
                handle.close()

    if total_rows == 0:
        for tmp_path in tmp_paths.values():
            tmp_path.unlink(missing_ok=True)
        raise DecodeError(-1, "<none>", "no input rows to decode")

    for width in widths:
        tmp_paths[width].replace(final_paths[width])

    return DecodeReport(total_rows=total_rows, accepted_sample_ids=tuple(accepted_ids), output_paths=final_paths)
