"""Binomial confidence intervals for retention-rate reporting.

The parent task requires binomial confidence intervals on retention rates but
explicitly forbids comparative inferential tests on the feasibility sample.
Wilson score intervals (rather than the normal approximation) are used
because several strata here are as small as 20 observations, where the
normal approximation can produce out-of-range bounds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceInterval:
    point_estimate: float
    lower: float
    upper: float

    def to_dict(self) -> dict:
        return {"point_estimate": self.point_estimate, "lower": self.lower, "upper": self.upper}


def wilson_confidence_interval(successes: int, n: int, *, z: float = 1.96) -> ConfidenceInterval:
    """Wilson score interval for a binomial proportion.

    ``z=1.96`` is the standard two-sided 95% critical value. Returns a
    degenerate interval ``(0.0, 0.0, 0.0)`` for ``n == 0`` rather than
    raising, since a group with zero observations legitimately has no rate.
    """
    if successes < 0 or n < 0 or successes > n:
        raise ValueError(f"invalid successes={successes} for n={n}")
    if n == 0:
        return ConfidenceInterval(point_estimate=0.0, lower=0.0, upper=0.0)

    p_hat = successes / n
    denom = 1 + z**2 / n
    center = p_hat + z**2 / (2 * n)
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n)
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return ConfidenceInterval(
        point_estimate=p_hat,
        lower=max(0.0, lower),
        upper=min(1.0, upper),
    )


__all__ = ["ConfidenceInterval", "wilson_confidence_interval"]
