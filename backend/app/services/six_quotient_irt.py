"""
Six-Quotient IRT helpers — 2PL Fisher information + ability update.

Pure Python (no scipy). Used by adaptive selector and post-score calibration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Tuple

_QUOTIENTS = ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ")


def sigmoid(x: float) -> float:
    if x >= 20:
        return 1.0
    if x <= -20:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def prob_correct(theta: float, a: float, b: float) -> float:
    """2PL: P(θ) = 1 / (1 + exp(-a(θ-b)))."""
    return sigmoid(float(a) * (float(theta) - float(b)))


def fisher_information(theta: float, a: float, b: float) -> float:
    """I(θ) = a² P (1-P) for 2PL."""
    p = prob_correct(theta, a, b)
    return (float(a) ** 2) * p * (1.0 - p)


def score_to_theta(mean_total: float, max_total: float = 9.0) -> float:
    """Map mean scenario total (0-9) onto roughly [-2.5, 2.5]."""
    if max_total <= 0:
        return 0.0
    p = max(0.02, min(0.98, mean_total / max_total))
    # logit scale compressed
    return max(-2.5, min(2.5, math.log(p / (1.0 - p)) * 0.7))


def update_theta(
    prior: float,
    responses: Iterable[Tuple[float, float, bool]],
    *,
    lr: float = 0.25,
) -> float:
    """
    Gradient step on log-likelihood.
    responses: iterable of (a, b, correct) where correct = total_score >= 6.
    """
    theta = float(prior)
    for a, b, correct in responses:
        p = prob_correct(theta, a, b)
        # d/dθ log L ≈ a (y - P)
        grad = float(a) * ((1.0 if correct else 0.0) - p)
        theta += lr * grad
    return max(-3.0, min(3.0, theta))


def calibrate_item(
    a: float,
    b: float,
    n: int,
    totals: List[float],
    theta_admin: float,
) -> Tuple[float, float, int]:
    """
    Empirical nudge of b toward observed difficulty.
    If mean total low → item harder → raise b.
    """
    if not totals:
        return a, b, n
    mean_t = sum(totals) / len(totals)
    # target: at theta_admin, P ≈ mean_pass
    pass_rate = sum(1 for t in totals if t >= 6.0) / len(totals)
    # invert: b ≈ θ - logit(P)/a
    p = max(0.05, min(0.95, pass_rate if pass_rate > 0 else mean_t / 9.0))
    target_b = theta_admin - (math.log(p / (1.0 - p)) / max(a, 0.2))
    new_n = n + len(totals)
    # shrink toward target
    w = min(0.5, len(totals) / max(new_n, 1))
    new_b = (1 - w) * b + w * target_b
    # mild discrimination bump when variance informative
    var = sum((t - mean_t) ** 2 for t in totals) / len(totals)
    new_a = min(2.5, max(0.4, a + (0.05 if 2.0 < var < 12.0 else -0.02)))
    return new_a, new_b, new_n


def select_max_info(
    items: List[Dict[str, Any]],
    theta: float,
    *,
    k: int,
    exclude_keys: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """Pick up to k items with highest Fisher information at theta."""
    exclude_keys = exclude_keys or set()
    ranked = []
    for it in items:
        key = it.get("scenario_key") or it.get("id") or ""
        if key in exclude_keys:
            continue
        a = float(it.get("irt_a") or 1.0)
        b = float(it.get("irt_b") or 0.0)
        info = fisher_information(theta, a, b)
        # Prefer items near boundary (P≈0.5)
        p = prob_correct(theta, a, b)
        boundary_bonus = 1.0 - abs(p - 0.5) * 2.0
        ranked.append((info * (0.7 + 0.3 * boundary_bonus), it))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in ranked[:k]]


def section_thetas(theta_by_section: Dict[str, Any], default: float = 0.0) -> Dict[str, float]:
    out = {q: float(default) for q in _QUOTIENTS}
    for q in _QUOTIENTS:
        if q in (theta_by_section or {}):
            try:
                out[q] = float(theta_by_section[q])
            except (TypeError, ValueError):
                pass
    return out
