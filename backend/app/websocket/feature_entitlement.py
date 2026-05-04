"""
Feature-gating tiers for family dependents/spouses — NOT billing or token caps.

Implements max(own_billing_rank, head_billing_rank) mapped to UX bands:
  TOP_TIER, STANDARD (Inner Chamber equivalent), TRIAL (Threshold / dependent-only).

See compute_premium_features / effective_feature_tier — never use for Stripe/tokens.
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Dict, Optional, Tuple

from app.constants import tiers as tc

_LOGGER = logging.getLogger(__name__)


def _billing_norm(profile: dict) -> str:
    """Canonical billing tier (DEPENDENT, SPOUSE, STANDARD, TOP_TIER, …)."""
    return tc.normalize_tier(profile.get("subscription_plan") or profile.get("tier") or "")


def _joined_sort_key(profile: dict) -> float:
    """Earlier join sorts first among equal billing rank."""
    for key in ("created_at", "joined", "join_date"):
        raw = profile.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                d = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return float(d.timestamp())
            except Exception:
                continue
        if isinstance(raw, _dt.datetime):
            return float(raw.timestamp())
    return float("inf")


def _eligible_head_surrogate(profile: dict) -> bool:
    """Dependents/spouses cannot be inferred as payer head."""
    bn = _billing_norm(profile)
    return bn not in (tc.TIER_DEPENDENT, tc.TIER_SPOUSE)


def _find_family_head(
    family_id: str,
    registry: dict,
    *,
    exclude_hw: Optional[str] = None,
    exclude_username: Optional[str] = None,
) -> Optional[dict]:
    """
    Flat client-like profile dict for head of household.

    Priority:
      1. family_role == HEAD (prefer highest payer rank; tie earliest join).
      2. Highest billing rank among payer-tier surrogates (excludes DEPENDENT/SPOUSE buckets).
    """
    candidates: list[dict] = []
    for k, row in registry.items():
        if not isinstance(row, dict) or (isinstance(k, str) and k.startswith("_")):
            continue
        p = row.get("profile") or {}
        if not isinstance(p, dict):
            continue
        if (p.get("family_id") or "").strip() != family_id.strip():
            continue
        hw = p.get("hardware_id")
        un = p.get("username")
        if exclude_hw and hw and exclude_hw == hw:
            continue
        if exclude_username and un and exclude_username == un:
            continue
        candidates.append(p)

    if not candidates:
        return None

    def _rnk(pr: dict) -> int:
        return tc.tier_rank(_billing_norm(pr))

    heads = [
        pr
        for pr in candidates
        if (pr.get("family_role") or "").strip().upper() == "HEAD"
    ]
    if heads:
        if len(heads) > 1:
            _LOGGER.warning(
                "Multiple HEAD profiles for family_id=%s — using highest billing tier",
                family_id,
            )
        heads.sort(key=lambda pr: (-_rnk(pr), _joined_sort_key(pr)))
        return heads[0]

    payers = [pr for pr in candidates if _eligible_head_surrogate(pr)]
    if not payers:
        _LOGGER.info(
            "feature_entitlement: no payer-tier surrogate for family_id=%s — head unknown",
            family_id,
        )
        return None
    _LOGGER.info(
        "feature_entitlement: no explicit HEAD for family_id=%s — using highest payer tier surrogate",
        family_id,
    )
    payers.sort(key=lambda pr: (-_rnk(pr), _joined_sort_key(pr)))
    return payers[0]


def _band_from_billing_rank(r: int) -> str:
    """Map tier_rank ladder to UX band strings used throughout the bridge."""
    if r >= tc.tier_rank(tc.TIER_TOP_TIER):
        return "TOP_TIER"
    if r >= tc.tier_rank(tc.TIER_STANDARD):
        return "STANDARD"
    return "TRIAL"


def resolve_feature_entitlement(
    profile: dict, registry: dict
) -> Tuple[str, int, int, Optional[dict]]:
    """
    Returns:
      effective_band ('TOP_TIER' | 'STANDARD' | 'TRIAL'),
      own_billing_rank,
      max_billing_rank used for band,
      resolved head profile (or None).

    Coaches/admins skip family inheritance.
    """
    role = (profile.get("role") or "").upper()
    own_r = tc.tier_rank(_billing_norm(profile))
    fid = (profile.get("family_id") or "").strip()

    if role in ("COACH", "ADMIN") or not fid:
        band = _band_from_billing_rank(own_r)
        return band, own_r, own_r, None

    head = _find_family_head(
        fid,
        registry,
        exclude_hw=profile.get("hardware_id"),
        exclude_username=profile.get("username"),
    )
    hr = tc.tier_rank(_billing_norm(head)) if head else 0
    mx = max(own_r, hr)
    return _band_from_billing_rank(mx), own_r, mx, head


def effective_feature_tier(profile: dict, registry: dict) -> str:
    """Single effective band string for FEATURE GATING ONLY."""
    return resolve_feature_entitlement(profile, registry)[0]
