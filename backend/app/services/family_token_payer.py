"""HoH token pool + family id aliases — QUANTUM-CRYSTAL-ARCH

Spouse / partner usage draws from the head-of-household balance.
Daily Reconnect must treat FAM_ codes and families.id UUIDs as one household.
Family HoH Sovereign Circle is billed at $30/mo (not catalog $149).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set, Tuple

from app.services.token_balance_policy import split_balances_from_profile, total_balance

HOH_ROLES = frozenset({"HEAD", "HOH", "HEAD_OF_HOUSEHOLD"})
SPOUSE_ROLES = frozenset({"SPOUSE", "PARTNER", "WIFE", "HUSBAND", "FAMILY_SPOUSE"})
# Family HoH Circle — Lisa/Bill: $30/mo, not catalog $149.
FAMILY_HOH_CIRCLE_MONTHLY_CENTS = 3000


def _norm(val: Any) -> str:
    return str(val or "").strip()


def _role(profile: Dict[str, Any]) -> str:
    return _norm(profile.get("family_role") or profile.get("role_in_family")).upper()


def _profile_idents(profile: Dict[str, Any], registry_key: str = "") -> Set[str]:
    ids: Set[str] = set()
    for key in (
        "hardware_id",
        "username",
        "user_id",
        "id",
        "family_uuid",
    ):
        raw = _norm(profile.get(key))
        if raw:
            ids.add(raw)
    rk = _norm(registry_key)
    if rk:
        ids.add(rk)
    return ids


def profile_matches_ident(profile: Dict[str, Any], ident: str, registry_key: str = "") -> bool:
    needle = _norm(ident)
    if not needle:
        return False
    return needle in _profile_idents(profile, registry_key)


def find_registry_profile(
    registry: Optional[Dict[str, Any]], ident: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    needle = _norm(ident)
    if not needle or not registry:
        return None, None
    for key, entry in registry.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        profile = (entry or {}).get("profile") or entry or {}
        if not isinstance(profile, dict):
            continue
        if profile_matches_ident(profile, needle, str(key)):
            return str(key), profile
    return None, None


def family_id_set(profile: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in ("family_id", "family_uuid"):
        raw = _norm(profile.get(key))
        if raw:
            out.add(raw)
    return out


def family_id_aliases(
    family_id: str,
    registry: Optional[Dict[str, Any]] = None,
    extra: Optional[Iterable[str]] = None,
) -> list:
    aliases: Set[str] = set()
    root = _norm(family_id)
    if root:
        aliases.add(root)
    if extra:
        aliases.update(_norm(x) for x in extra if _norm(x))
    if registry and aliases:
        for _key, entry in registry.items():
            if isinstance(_key, str) and _key.startswith("_"):
                continue
            profile = (entry or {}).get("profile") or {}
            if not isinstance(profile, dict):
                continue
            keys = family_id_set(profile)
            if keys & aliases:
                aliases |= keys
    return [a for a in aliases if a]


def resolve_token_payer_hardware_id(
    registry: Optional[Dict[str, Any]],
    user_id: str,
    profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Return hardware_id (or username) of the household token payer."""
    _key, found = find_registry_profile(registry, user_id)
    merged: Dict[str, Any] = {}
    if found:
        merged.update(found)
    if profile:
        merged.update(profile)
    if not merged:
        return _norm(user_id)

    own_hw = _norm(merged.get("hardware_id") or user_id)
    role = _role(merged)
    if role in HOH_ROLES:
        return own_hw or _norm(user_id)

    hoh_ref = _norm(merged.get("head_of_household_id"))
    if hoh_ref:
        _hk, hoh_profile = find_registry_profile(registry, hoh_ref)
        if hoh_profile:
            return _norm(hoh_profile.get("hardware_id") or hoh_profile.get("username") or hoh_ref)

    fam = family_id_set(merged)
    if fam and registry:
        for key, entry in registry.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            other = (entry or {}).get("profile") or {}
            if not isinstance(other, dict):
                continue
            if not (family_id_set(other) & fam):
                continue
            if _role(other) in HOH_ROLES:
                return _norm(other.get("hardware_id") or other.get("username") or own_hw)

    if role in SPOUSE_ROLES or fam:
        return own_hw
    return own_hw or _norm(user_id)


def overlay_family_token_balance(
    profile: Dict[str, Any], registry: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Spouse/partner login sees the HoH household pool, not their leftover grant."""
    if not profile:
        return profile
    ident = _norm(profile.get("hardware_id") or profile.get("username"))
    payer = resolve_token_payer_hardware_id(registry, ident, profile)
    _pk, payer_profile = find_registry_profile(registry, payer)
    if not payer_profile:
        return profile
    self_hw = _norm(profile.get("hardware_id") or profile.get("username"))
    payer_hw = _norm(payer_profile.get("hardware_id") or payer_profile.get("username"))
    if self_hw and payer_hw and self_hw != payer_hw:
        sub, purch = split_balances_from_profile(payer_profile)
        total = total_balance(sub, purch)
        profile["token_balance"] = total
        profile["family_token_balance"] = total
        profile["token_payer"] = payer_profile.get("username") or payer_hw
        profile["token_pool"] = "household"
    if _role(profile) in HOH_ROLES or _role(profile) in SPOUSE_ROLES:
        profile["monthly_price_cents"] = FAMILY_HOH_CIRCLE_MONTHLY_CENTS
        profile["family_circle_monthly"] = 30
    return profile


def family_hoh_circle_cents(profile: Optional[Dict[str, Any]]) -> int:
    if not profile:
        return 14900
    if _role(profile) in HOH_ROLES:
        return FAMILY_HOH_CIRCLE_MONTHLY_CENTS
    return 14900
