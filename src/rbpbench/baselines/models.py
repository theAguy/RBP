"""Frozen prevalence and logistic-regression baselines."""

from __future__ import annotations

from dataclasses import dataclass
import warnings

import numpy as np
from scipy.sparse import issparse
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


class BaselineFitError(RuntimeError):
    pass


@dataclass
class FittedLogistic:
    scaler: StandardScaler
    estimator: LogisticRegression
    converged: bool
    warning_messages: tuple[str, ...]
    n_iter: int

    def scores(self, matrix) -> np.ndarray:
        return self.estimator.predict_proba(self.scaler.transform(matrix))[:, 1]


def prevalence_score(labels) -> float:
    labels = np.asarray(labels, dtype=np.int8)
    if labels.ndim != 1 or not len(labels) or not np.isin(labels, [0, 1]).all():
        raise BaselineFitError("prevalence labels must be a non-empty binary vector")
    if labels.sum() in (0, len(labels)):
        raise BaselineFitError("prevalence fitting requires both classes")
    return float(labels.mean())


def fit_logistic(matrix, labels, *, c_value: float, seed: int, max_iter: int = 2000, tol: float = 1e-6) -> FittedLogistic:
    labels = np.asarray(labels, dtype=np.int8)
    if matrix.shape[0] != len(labels) or matrix.shape[0] == 0:
        raise BaselineFitError("feature and label rows must align")
    if labels.sum() in (0, len(labels)):
        raise BaselineFitError("logistic fitting requires both classes")
    if c_value <= 0:
        raise BaselineFitError("C must be positive")
    scaler = StandardScaler(with_mean=not issparse(matrix), with_std=True)
    transformed = scaler.fit_transform(matrix)
    estimator = LogisticRegression(
        C=float(c_value), penalty="l2", solver="liblinear", fit_intercept=True,
        class_weight=None, max_iter=int(max_iter), tol=float(tol),
        random_state=int(seed), intercept_scaling=1.0,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(transformed, labels)
    messages = tuple(str(item.message) for item in caught if issubclass(item.category, ConvergenceWarning))
    n_iter = int(np.max(estimator.n_iter_))
    converged = not messages and n_iter < max_iter
    return FittedLogistic(scaler, estimator, converged, messages, n_iter)


def select_c(candidate_metrics: dict[float, list[dict]]) -> tuple[float, list[dict]]:
    eligible: list[tuple[float, float]] = []
    evidence = []
    for c_value in sorted(candidate_metrics):
        rows = candidate_metrics[c_value]
        converged = bool(rows) and all(bool(row["converged"]) for row in rows)
        macro = float(np.mean([float(row["auroc"]) for row in rows])) if converged else None
        evidence.append({"c": c_value, "eligible": converged, "macro_validation_auroc": macro, "fit_count": len(rows)})
        if converged:
            eligible.append((macro, c_value))
    if not eligible:
        raise BaselineFitError("no candidate C fully converged")
    best_macro = max(item[0] for item in eligible)
    best_c = min(c_value for macro, c_value in eligible if np.isclose(macro, best_macro, rtol=0, atol=1e-12))
    return best_c, evidence
