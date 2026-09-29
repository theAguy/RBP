"""Exact reproduction of the submitted notebook's row-level first
cross-validation fold, used ONLY as a leakage diagnostic against the new
whole-component assignment -- it never rescues, alters, or is used to
select the new split
(``docs/tasks/002c_partition_assignment_and_audit.md``, "Former-split
diagnostic").

The pinned dependency stack (``numpy==2.0.2``, ``scipy==1.16.1``,
``scikit-learn==1.6.1``, ``iterative-stratification==0.1.9`` under Python
3.12) is imported lazily, inside the functions that actually need it, so
importing this module never fails merely because the accepted
``rbpbench-splits-002`` environment (which this module must not modify)
does not itself carry these packages -- only actually running the fold
requires the separate isolated environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from rbpbench.coordinates.hashing import content_fingerprint

N_SPLITS = 5
SHUFFLE = True
RANDOM_STATE = 42
FOLD_INDEX = 0


class LegacyDependencyError(RuntimeError):
    """The pinned numpy/scipy/scikit-learn/iterative-stratification stack
    is not importable in the current interpreter. The legacy-fold stage
    must stop and report rather than silently substituting a different
    version or synthesizing a result
    (``docs/handoffs/002c1_partition_orchestration_claude_handoff.md``,
    "Environment boundary").
    """


@dataclass(frozen=True)
class LegacyDependencyVersions:
    python_version: str
    numpy_version: str
    scipy_version: str
    scikit_learn_version: str
    iterative_stratification_version: str

    def to_dict(self) -> dict:
        return {
            "python_version": self.python_version,
            "numpy_version": self.numpy_version,
            "scipy_version": self.scipy_version,
            "scikit_learn_version": self.scikit_learn_version,
            "iterative_stratification_version": self.iterative_stratification_version,
        }


def resolve_dependency_versions() -> LegacyDependencyVersions:
    """Imports and records the ACTUAL resolved versions of every pinned
    legacy-diagnostic dependency in the current interpreter -- never a
    literal copied from configuration -- so a silent version drift can
    never be reported as if it matched the pinned contract.
    """
    import platform

    try:
        import numpy
        import scipy
        import sklearn
        import iterstrat  # noqa: F401  (import-availability check only)
    except ImportError as exc:
        raise LegacyDependencyError(
            f"the pinned legacy-diagnostic dependency stack is not importable in this interpreter: {exc}"
        ) from exc

    iterstrat_version = getattr(iterstrat, "__version__", None)
    if iterstrat_version is None:
        try:
            from importlib.metadata import version as _pkg_version

            iterstrat_version = _pkg_version("iterative-stratification")
        except Exception:  # pragma: no cover - defensive only
            iterstrat_version = "unknown"

    return LegacyDependencyVersions(
        python_version=platform.python_version(),
        numpy_version=numpy.__version__,
        scipy_version=scipy.__version__,
        scikit_learn_version=sklearn.__version__,
        iterative_stratification_version=iterstrat_version,
    )


def require_pinned_versions(actual: LegacyDependencyVersions, *, expected: Mapping[str, str]) -> None:
    """Fails closed if any resolved version differs from the pinned
    configuration -- the notebook contract is reproduced with the exact
    pinned versions or not at all, never a silently newer substitute.
    """
    problems = []
    for field_name, key in (
        ("python_version", "python_version"),
        ("numpy_version", "numpy_version"),
        ("scipy_version", "scipy_version"),
        ("scikit_learn_version", "scikit_learn_version"),
        ("iterative_stratification_version", "iterative_stratification_version"),
    ):
        actual_value = getattr(actual, field_name)
        expected_value = expected[key]
        if key == "python_version":
            if not actual_value.startswith(expected_value):
                problems.append(f"{field_name} {actual_value!r} does not match pinned {expected_value!r}")
        elif actual_value != expected_value:
            problems.append(f"{field_name} {actual_value!r} != pinned {expected_value!r}")
    if problems:
        raise LegacyDependencyError("resolved legacy-diagnostic dependency versions do not match pinned: " + "; ".join(problems))


def build_positive_only_matrix(signed_labels_by_row: Sequence[Mapping[int, int]], *, protein_ids: Sequence[int]):
    """``strat_labels = targets * masks`` reduces exactly to a positive-only
    binary matrix: ``1`` where the row's signed-label map has
    ``+protein_id``, ``0`` everywhere else -- including every unknown AND
    every known-negative entry. Known negatives are therefore
    indistinguishable from unknowns to the legacy fold; this module only
    reproduces that documented defect, never repairs it.
    """
    import numpy as np

    protein_ids = list(protein_ids)
    index = {protein_id: i for i, protein_id in enumerate(protein_ids)}
    matrix = np.zeros((len(signed_labels_by_row), len(protein_ids)), dtype=np.int8)
    for row_index, labels in enumerate(signed_labels_by_row):
        for protein_id, sign in labels.items():
            if sign > 0 and protein_id in index:
                matrix[row_index, index[protein_id]] = 1
    return matrix


def index_set_digest(indices: Sequence[int]) -> str:
    """Deterministic digest of an index SET: sorted before hashing, so it
    is order-independent (as a set semantically is), and a differently-
    ordered but identical fold result still digests identically.
    """
    return content_fingerprint("legacy_fold_index_set", *sorted(int(i) for i in indices))


@dataclass(frozen=True)
class LegacyFoldResult:
    train_indices: tuple[int, ...]
    holdout_indices: tuple[int, ...]
    train_digest: str
    holdout_digest: str
    dependency_versions: LegacyDependencyVersions

    def to_dict(self) -> dict:
        return {
            "train_count": len(self.train_indices),
            "holdout_count": len(self.holdout_indices),
            "train_digest": self.train_digest,
            "holdout_digest": self.holdout_digest,
            "dependency_versions": self.dependency_versions.to_dict(),
            "n_splits": N_SPLITS,
            "shuffle": SHUFFLE,
            "random_state": RANDOM_STATE,
            "fold_index": FOLD_INDEX,
        }


def run_legacy_fold(signed_labels_by_row: Sequence[Mapping[int, int]], *, protein_ids: Sequence[int]) -> LegacyFoldResult:
    """Exactly reproduces the submitted notebook's fold-0 first CV split:
    ``MultilabelStratifiedKFold(n_splits=5, shuffle=True,
    random_state=42)`` over the positive-only ``targets * masks`` matrix, in
    canonical row order (``signed_labels_by_row[i]`` is ``row_<i>``).
    """
    versions = resolve_dependency_versions()
    from iterstrat.ml_stratifiers import MultilabelStratifiedKFold

    matrix = build_positive_only_matrix(signed_labels_by_row, protein_ids=protein_ids)
    splitter = MultilabelStratifiedKFold(n_splits=N_SPLITS, shuffle=SHUFFLE, random_state=RANDOM_STATE)
    folds = list(splitter.split(matrix, matrix))
    train_idx, holdout_idx = folds[FOLD_INDEX]
    train_indices = tuple(int(i) for i in train_idx)
    holdout_indices = tuple(int(i) for i in holdout_idx)
    return LegacyFoldResult(
        train_indices=train_indices,
        holdout_indices=holdout_indices,
        train_digest=index_set_digest(train_indices),
        holdout_digest=index_set_digest(holdout_indices),
        dependency_versions=versions,
    )


def build_leakage_diagnostic_report(
    *,
    legacy_result: LegacyFoldResult,
    sample_ids_by_index: Sequence[str],
    sample_to_component: Mapping[str, str],
    sample_to_partition: Mapping[str, str] | None = None,
    similarity_edges_by_width: Mapping[int, Sequence[tuple[str, str]]] | None = None,
    exact_rc_edges_by_width: Mapping[int, Sequence[tuple[str, str]]] | None = None,
) -> dict:
    """Compares the legacy fold's holdout against the new whole-component
    assignment with an explicit denominator/rate alongside every raw count
    (docs/reviews/002c_partition_assignment_reconciliation.md, "Legacy
    leakage results require denominators"). Contains only IDs, component/
    partition identities, counts, and rates -- never a sequence or a model
    result.
    """
    similarity_edges_by_width = similarity_edges_by_width or {}
    exact_rc_edges_by_width = exact_rc_edges_by_width or {}

    holdout_ids = {sample_ids_by_index[i] for i in legacy_result.holdout_indices}
    train_ids = {sample_ids_by_index[i] for i in legacy_result.train_indices}

    holdout_components = {sample_to_component[sid] for sid in holdout_ids}
    train_components = {sample_to_component[sid] for sid in train_ids}
    crossing_components = holdout_components & train_components

    crossing_holdout_rows = {sid for sid in holdout_ids if sample_to_component[sid] in crossing_components}
    crossing_train_rows = {sid for sid in train_ids if sample_to_component[sid] in crossing_components}

    report: dict = {
        "legacy_fold": legacy_result.to_dict(),
        "component_crossing": {
            "crossing_component_count": len(crossing_components),
            "components_represented_in_holdout": len(holdout_components),
            "crossing_component_rate_over_holdout_components": (
                len(crossing_components) / len(holdout_components) if holdout_components else 0.0
            ),
            "crossing_holdout_row_count": len(crossing_holdout_rows),
            "crossing_holdout_row_rate_over_holdout_rows": (
                len(crossing_holdout_rows) / len(holdout_ids) if holdout_ids else 0.0
            ),
            "crossing_train_row_count": len(crossing_train_rows),
            "crossing_train_row_rate_over_train_rows": (
                len(crossing_train_rows) / len(train_ids) if train_ids else 0.0
            ),
        },
        "directly_edge_matched_by_width": {},
        "exact_rc_by_width": {},
    }

    for width, edges in similarity_edges_by_width.items():
        matched_holdout = set()
        for a, b in edges:
            if a in holdout_ids and b in train_ids:
                matched_holdout.add(a)
            elif b in holdout_ids and a in train_ids:
                matched_holdout.add(b)
        report["directly_edge_matched_by_width"][str(width)] = {
            "matched_holdout_row_count": len(matched_holdout),
            "matched_holdout_row_rate_over_holdout_rows": (
                len(matched_holdout) / len(holdout_ids) if holdout_ids else 0.0
            ),
        }

    for width, edges in exact_rc_edges_by_width.items():
        affected_holdout = set()
        raw_pair_count = 0
        for a, b in edges:
            crosses = (a in holdout_ids and b in train_ids) or (b in holdout_ids and a in train_ids)
            if crosses:
                raw_pair_count += 1
                if a in holdout_ids:
                    affected_holdout.add(a)
                if b in holdout_ids:
                    affected_holdout.add(b)
        report["exact_rc_by_width"][str(width)] = {
            "affected_holdout_row_count": len(affected_holdout),
            "affected_holdout_row_rate_over_holdout_rows": (
                len(affected_holdout) / len(holdout_ids) if holdout_ids else 0.0
            ),
            "raw_violating_pair_count": raw_pair_count,
        }

    if sample_to_partition is not None:
        holdout_partitions = {sample_to_partition[sid] for sid in holdout_ids}
        report["new_assignment_holdout_partition_spread"] = sorted(holdout_partitions)

    return report


__all__ = [
    "N_SPLITS",
    "SHUFFLE",
    "RANDOM_STATE",
    "FOLD_INDEX",
    "LegacyDependencyError",
    "LegacyDependencyVersions",
    "resolve_dependency_versions",
    "require_pinned_versions",
    "build_positive_only_matrix",
    "index_set_digest",
    "LegacyFoldResult",
    "run_legacy_fold",
    "build_leakage_diagnostic_report",
]
