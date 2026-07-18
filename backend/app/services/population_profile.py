"""High-risk occupational population helpers — QUANTUM-CRYSTAL-ARCH.

profile_data keys (JSONB, no migration):
  population: veteran | first_responder_le | first_responder_fire_ems | military_family | general
  population_shielded: bool — when true, corp/employer roster queries must exclude
  family_concern_consent: bool — veteran consented that family may flag concern
  lethal_means_guidance_ok: bool — opt-in for secure-storage framing
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

POPULATION_GENERAL = "general"
POPULATION_VETERAN = "veteran"
POPULATION_FR_LE = "first_responder_le"
POPULATION_FR_FIRE_EMS = "first_responder_fire_ems"
POPULATION_MILITARY_FAMILY = "military_family"

VALID_POPULATIONS = frozenset(
    {
        POPULATION_GENERAL,
        POPULATION_VETERAN,
        POPULATION_FR_LE,
        POPULATION_FR_FIRE_EMS,
        POPULATION_MILITARY_FAMILY,
    }
)

HIGH_RISK_POPULATIONS = frozenset(
    {
        POPULATION_VETERAN,
        POPULATION_FR_LE,
        POPULATION_FR_FIRE_EMS,
        POPULATION_MILITARY_FAMILY,
    }
)


def _as_dict(profile_or_pd: Any) -> Dict[str, Any]:
    if profile_or_pd is None:
        return {}
    if isinstance(profile_or_pd, str):
        try:
            profile_or_pd = json.loads(profile_or_pd)
        except Exception:
            return {}
    if not isinstance(profile_or_pd, dict):
        return {}
    return profile_or_pd


def profile_data(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not profile:
        return {}
    pd = profile.get("profile_data")
    if pd is None and any(k in profile for k in ("population", "timezone", "name")):
        # Already a flat profile_data-like dict
        return _as_dict(profile)
    return _as_dict(pd)


def get_population(profile: Optional[Dict[str, Any]]) -> str:
    pd = profile_data(profile)
    raw = (pd.get("population") or profile.get("population") if profile else None) or POPULATION_GENERAL
    pop = str(raw).strip().lower()
    return pop if pop in VALID_POPULATIONS else POPULATION_GENERAL


def is_high_risk_population(profile: Optional[Dict[str, Any]]) -> bool:
    return get_population(profile) in HIGH_RISK_POPULATIONS


def is_population_shielded(profile: Optional[Dict[str, Any]]) -> bool:
    pd = profile_data(profile)
    if pd.get("population_shielded") is True:
        return True
    if str(pd.get("population_shielded", "")).lower() in ("1", "true", "yes"):
        return True
    # Auto-shield high-risk populations unless explicitly opted out
    if is_high_risk_population(profile) and pd.get("population_shielded") is not False:
        return True
    return False


def family_concern_consent(profile: Optional[Dict[str, Any]]) -> bool:
    pd = profile_data(profile)
    flag = pd.get("family_concern_consent")
    return flag is True or str(flag).lower() in ("1", "true", "yes")


def env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def population_resources_enabled() -> bool:
    return env_flag("ENABLE_POPULATION_CRISIS_RESOURCES", "true")


def night_register_enabled() -> bool:
    return env_flag("ENABLE_NIGHT_REGISTER", "true")


def peer_voice_enabled() -> bool:
    return env_flag("ENABLE_PEER_CULTURE_VOICE", "true")


def lethal_means_enabled() -> bool:
    return env_flag("ENABLE_LETHAL_MEANS_GUIDANCE", "false")


def risk_windows_enabled() -> bool:
    return env_flag("ENABLE_CHECKIN_RISK_WINDOWS", "true")


def get_timezone(profile: Optional[Dict[str, Any]], default: str = "America/New_York") -> str:
    pd = profile_data(profile)
    tz = (pd.get("timezone") or (profile or {}).get("timezone") or default)
    return str(tz).strip() or default
