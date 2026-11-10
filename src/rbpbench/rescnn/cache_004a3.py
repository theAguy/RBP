"""Memory-mappable, development-only cache contract for Task 004A-3."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

import numpy as np

from rbpbench.rescnn.data_004a2 import (
    CoverageSampler,
    SampleCandidate,
    audit_streams,
    build_cache_streams,
    canonical_content_sha256,
    require_count_reconciliation,
)
from rbpbench.rescnn.output import atomic_write, canonical_json, file_evidence


PRODUCTION_PARTITION_SIZE = 8_193
WINDOW = 500
OUTPUT_COUNT = 122
PARTITIONS = ("train", "validation")


class ResCNN004A3CacheError(ValueError):
    pass


@dataclass(frozen=True)
class CacheRow:
    sample_id: str
    component_id: str
    partition: str
    base_codes: Sequence[int]
    targets: Sequence[int]
    masks: Sequence[int]


@dataclass(frozen=True)
class MMapCache:
    root: Path
    metadata: Mapping[str, object]
    base_codes: np.ndarray
    targets: np.ndarray
    masks: np.ndarray
    partition_codes: np.ndarray

    def indices(self, partition: str) -> np.ndarray:
        if partition not in PARTITIONS:
            raise ResCNN004A3CacheError(f"unknown partition: {partition!r}")
        code = PARTITIONS.index(partition)
        return np.flatnonzero(self.partition_codes == code)


@dataclass(frozen=True)
class DevelopmentCacheEvidence:
    cache_metadata: Mapping[str, object]
    development_count_matrix: Mapping[str, object]
    selected_content_sha256: str
    gate_a_access: Mapping[str, int | bool]
    gate_b_access: Mapping[str, int | bool]


def _sha256_arrays(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        view = np.ascontiguousarray(array)
        digest.update(str(view.dtype).encode("ascii"))
        digest.update(bytes(str(tuple(view.shape)), "ascii"))
        digest.update(view.tobytes(order="C"))
    return digest.hexdigest()


def select_development_rows(
    rows: Iterable[tuple[SampleCandidate, Mapping[int, int]]],
    *,
    seed: int,
    sample_size: int = PRODUCTION_PARTITION_SIZE,
    output_count: int = OUTPUT_COUNT,
) -> dict[str, tuple[SampleCandidate, ...]]:
    """Use the accepted bounded quota-plus-label-blind-filler sampler."""

    sampler = CoverageSampler(
        output_count=output_count, sample_size=sample_size, seed=seed,
    )
    for candidate, labels in rows:
        sampler.observe(candidate, labels)
    return sampler.finalize()


def _build_development_cache_from_streams(
    root: Path,
    *,
    membership_factory: Callable[[], Iterable[str]],
    csv_factory: Callable[[], Iterable[str]],
    fasta_factory: Callable[[], Iterable[str]],
    seed: int,
    sample_size: int,
    width: int,
    output_count: int,
    expected_partition_rows: Mapping[str, int] | None = None,
    expected_component_count: int | None = None,
) -> DevelopmentCacheEvidence:
    """Run the accepted independent two-pass boundary and materialize mmap rows."""

    audit = audit_streams(
        membership_factory(), csv_factory(), fasta_factory(), width=width,
        output_count=output_count, sample_size=sample_size, seed=seed,
        expected_partition_rows=expected_partition_rows,
        expected_component_count=expected_component_count,
    )
    gate_b = build_cache_streams(
        membership_factory(), csv_factory(), fasta_factory(),
        selected=audit.selected, width=width, output_count=output_count,
    )
    require_count_reconciliation(audit.counts, gate_b.counts)
    if audit.selected_content_sha256 != gate_b.selected_content_sha256:
        raise ResCNN004A3CacheError("Gate A/Gate B selected-content digest mismatch")
    for access in (audit.access, gate_b.access):
        if access.get("test_accessed") is not False:
            raise ResCNN004A3CacheError("test fields were accessed during cache construction")
    cache_rows = (
        CacheRow(
            sample_id=gate_b.cache.sample_ids[index],
            component_id=gate_b.cache.component_ids[index],
            partition=gate_b.cache.partitions[index],
            base_codes=tuple(int(value) for value in gate_b.cache.base_codes[index].tolist()),
            targets=tuple(int(value) for value in gate_b.cache.targets[index].tolist()),
            masks=tuple(int(value) for value in gate_b.cache.masks[index].tolist()),
        )
        for index in range(len(gate_b.cache))
    )
    metadata = write_cache(
        root, cache_rows, expected_partition_size=sample_size,
        width=width, output_count=output_count,
    )
    return DevelopmentCacheEvidence(
        cache_metadata=metadata,
        development_count_matrix=audit.counts.matrix(),
        selected_content_sha256=audit.selected_content_sha256,
        gate_a_access=dict(audit.access), gate_b_access=dict(gate_b.access),
    )


def build_production_development_cache(
    root: Path,
    *,
    membership_factory: Callable[[], Iterable[str]],
    csv_factory: Callable[[], Iterable[str]],
    fasta_factory: Callable[[], Iterable[str]],
    seed: int,
    expected_partition_rows: Mapping[str, int],
    expected_component_count: int,
) -> DevelopmentCacheEvidence:
    """Reviewed real-data builder; dimensions cannot be caller-overridden."""

    return _build_development_cache_from_streams(
        root, membership_factory=membership_factory, csv_factory=csv_factory,
        fasta_factory=fasta_factory, seed=seed,
        sample_size=PRODUCTION_PARTITION_SIZE, width=WINDOW,
        output_count=OUTPUT_COUNT,
        expected_partition_rows=expected_partition_rows,
        expected_component_count=expected_component_count,
    )


def require_accepted_count_matrix(
    observed: Mapping[str, object], accepted_summary: Mapping[str, object],
) -> None:
    expected = accepted_summary.get("audit", {}).get("development_counts")
    normalized = json.loads(json.dumps(observed, sort_keys=True))
    if not isinstance(expected, dict) or normalized != expected:
        raise ResCNN004A3CacheError(
            "Gate-A development matrix differs from accepted Task 004A-2 evidence"
        )


def write_cache(
    root: Path,
    rows: Iterable[CacheRow],
    *,
    expected_partition_size: int = PRODUCTION_PARTITION_SIZE,
    width: int = WINDOW,
    output_count: int = OUTPUT_COUNT,
) -> dict[str, object]:
    """Write an immutable candidate cache with mmap-compatible ``.npy`` arrays."""

    root = Path(root)
    if root.exists():
        raise ResCNN004A3CacheError(f"cache path already exists: {root}")
    if expected_partition_size <= 0 or width <= 0 or output_count <= 0:
        raise ResCNN004A3CacheError("cache dimensions must be positive")
    materialized = tuple(rows)
    expected_total = expected_partition_size * len(PARTITIONS)
    if len(materialized) != expected_total:
        raise ResCNN004A3CacheError(
            f"cache has {len(materialized)} rows; expected {expected_total}"
        )
    root.mkdir(parents=True)
    arrays = {
        "base_codes": np.lib.format.open_memmap(
            root / "base_codes.npy", mode="w+", dtype=np.uint8,
            shape=(expected_total, width),
        ),
        "targets": np.lib.format.open_memmap(
            root / "targets.npy", mode="w+", dtype=np.uint8,
            shape=(expected_total, output_count),
        ),
        "masks": np.lib.format.open_memmap(
            root / "masks.npy", mode="w+", dtype=np.uint8,
            shape=(expected_total, output_count),
        ),
        "partition_codes": np.lib.format.open_memmap(
            root / "partition_codes.npy", mode="w+", dtype=np.uint8,
            shape=(expected_total,),
        ),
    }
    identity_lines = ["sample_id\tcomponent_id\tpartition\tcontent_sha256\n"]
    counts = {partition: 0 for partition in PARTITIONS}
    known_counts = {partition: [0] * output_count for partition in PARTITIONS}
    seen: set[str] = set()
    try:
        for index, row in enumerate(materialized):
            if row.sample_id in seen or not row.sample_id or not row.component_id:
                raise ResCNN004A3CacheError("cache identities must be unique and non-empty")
            seen.add(row.sample_id)
            if row.partition not in PARTITIONS:
                raise ResCNN004A3CacheError("cache may contain only train/validation rows")
            bases = np.asarray(row.base_codes, dtype=np.uint8)
            targets = np.asarray(row.targets, dtype=np.uint8)
            masks = np.asarray(row.masks, dtype=np.uint8)
            if bases.shape != (width,) or np.any(bases > 3):
                raise ResCNN004A3CacheError("invalid base-code row")
            if targets.shape != (output_count,) or masks.shape != (output_count,):
                raise ResCNN004A3CacheError("invalid target/mask row shape")
            if np.any(targets > 1) or np.any(masks > 1):
                raise ResCNN004A3CacheError("targets and masks must be binary")
            arrays["base_codes"][index] = bases
            arrays["targets"][index] = targets
            arrays["masks"][index] = masks
            arrays["partition_codes"][index] = PARTITIONS.index(row.partition)
            counts[row.partition] += 1
            for protein_index in np.flatnonzero(masks):
                known_counts[row.partition][int(protein_index)] += 1
            content = canonical_content_sha256(
                sample_id=row.sample_id, component_id=row.component_id,
                partition=row.partition, base_codes=bases, targets=targets, masks=masks,
            )
            identity_lines.append(
                f"{row.sample_id}\t{row.component_id}\t{row.partition}\t{content}\n"
            )
        if any(value != expected_partition_size for value in counts.values()):
            raise ResCNN004A3CacheError(f"partition counts drifted: {counts!r}")
        for value in arrays.values():
            value.flush()
        (root / "identities.tsv").write_text("".join(identity_lines))
        digest = _sha256_arrays(*(np.asarray(arrays[name]) for name in arrays))
        retained_inventory = [
            file_evidence(path, relative_to=root)
            for path in sorted(root.iterdir()) if path.is_file() and path.name != "cache.json"
        ]
        metadata = {
            "schema_version": "task004a3_mmap_cache_v1",
            "row_count": expected_total,
            "partition_counts": counts,
            "width": width,
            "output_count": output_count,
            "dtypes": {name: str(value.dtype) for name, value in arrays.items()},
            "shapes": {name: list(value.shape) for name, value in arrays.items()},
            "validation_known_counts": known_counts["validation"],
            "arrays_sha256": digest,
            "test_rows": 0,
            "test_accessed": False,
            "retained_inventory": retained_inventory,
        }
        atomic_write(root / "cache.json", canonical_json(metadata))
        return metadata
    except Exception:
        import shutil
        shutil.rmtree(root, ignore_errors=True)
        raise


def open_cache(root: Path) -> MMapCache:
    root = Path(root)
    metadata = json.loads((root / "cache.json").read_text())
    if metadata.get("schema_version") != "task004a3_mmap_cache_v1":
        raise ResCNN004A3CacheError("cache schema mismatch")
    arrays = {
        name: np.load(root / f"{name}.npy", mmap_mode="r", allow_pickle=False)
        for name in ("base_codes", "targets", "masks", "partition_codes")
    }
    for name, array in arrays.items():
        if list(array.shape) != metadata["shapes"][name] or str(array.dtype) != metadata["dtypes"][name]:
            raise ResCNN004A3CacheError(f"cache array drift: {name}")
    if _sha256_arrays(*(np.asarray(arrays[name]) for name in arrays)) != metadata["arrays_sha256"]:
        raise ResCNN004A3CacheError("cache array digest drift")
    if metadata.get("test_rows") != 0 or metadata.get("test_accessed") is not False:
        raise ResCNN004A3CacheError("cache does not prove test absence")
    current_inventory = [
        file_evidence(path, relative_to=root)
        for path in sorted(root.iterdir()) if path.is_file() and path.name != "cache.json"
    ]
    if current_inventory != metadata.get("retained_inventory"):
        raise ResCNN004A3CacheError("cache retained inventory drift")
    return MMapCache(root, metadata, **arrays)
