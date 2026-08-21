"""Retention Policy helper (Slice 1 of Bee HIV+ privacy plan).

Reads the admin-configured `memory_retention_policy` value (stored in the
`admin_settings.json` file under `DATA_DIR`) and exposes it as an integer
retention window in days — or `None` for the current "forever" default.

Also gates the enforcement pass behind the `ENABLE_RETENTION_ENFORCEMENT`
environment variable so the wiring can ship in a disabled state before we
flip it on across production. This mirrors the strict-mode encryption
pattern from Slice 0.5.

The retention worker itself lives inside `DatabaseMaintenanceAgent` so we
don't need to modify the protected `main.py` lifespan block. This module
is intentionally tiny and dependency-free so it is easy to unit test.

Design notes:
    * The admin setting was already validated to be one of
      {"forever", "1_year", "6_months"} at write time (see
      `VALID_SETTINGS` in `backend/app/routers/admin.py`). We still
      defensively guard against unknown values here — if the file is
      corrupted or edited by hand we fall back to "forever" (no purge).
    * We deliberately treat missing settings file / missing key / IO
      error as "forever" so a broken read never becomes an accidental
      mass-delete.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("retention_policy")

# Map admin dropdown values → integer days. `None` means unlimited retention
# (current default behaviour).
_POLICY_TO_DAYS: dict[str, Optional[int]] = {
    "forever": None,
    "1_year": 365,
    "6_months": 180,
    "30_days": 30,  # Slice D-prep: Bee HIV+ cohort override
}


# --------------------------------------------------------------------------- #
# Slice D-prep: cohort-scoped retention (Bee HIV+ program participants).      #
# --------------------------------------------------------------------------- #

# Program IDs that opt into the strict retention window. Kept as a set so we
# can extend to additional cohorts later without touching call sites.
_STRICT_RETENTION_PROGRAMS = {"bee_hiv_plus"}

# Default retention for strict cohorts when no explicit override is configured.
_STRICT_DEFAULT_DAYS = 30


def get_retention_days_for_user(program_id: Optional[str]) -> Optional[int]:
    """Return retention days for a user, honoring cohort program overrides.

    Non-cohort users get the global admin policy from ``get_retention_days``.
    Users whose ``program_id`` is in ``_STRICT_RETENTION_PROGRAMS`` get the
    stricter of (global policy, cohort default = 30 days). ``None`` means
    unlimited retention.
    """
    global_days = get_retention_days()

    pid = (program_id or "").strip().lower()
    if pid not in _STRICT_RETENTION_PROGRAMS:
        return global_days

    if global_days is None:
        return _STRICT_DEFAULT_DAYS
    return min(global_days, _STRICT_DEFAULT_DAYS)


def _settings_path() -> Path:
    """Return the path to admin_settings.json.

    Uses the same resolution logic as `app.routers.admin` so tests can
    override via the `DATA_DIR` env var. Live env vars take precedence
    over the cached pydantic settings singleton so test overrides work
    without having to reload `app.config`.
    """
    env_dir = os.getenv("DATA_DIR")
    if env_dir:
        base = Path(env_dir)
    else:
        try:
            from app.config import settings as _settings  # type: ignore

            base = Path(_settings.DATA_DIR)
        except Exception:
            base = Path("data/backend")
    return base / "admin_settings.json"


def get_retention_days() -> Optional[int]:
    """Return the configured retention window in days.

    Returns None when the policy is `forever`, the settings file is
    absent, or the value cannot be parsed. This is the fail-safe path:
    an unreadable settings file must not delete user data.
    """
    path = _settings_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("retention_policy: unable to read %s: %s", path, exc)
        return None

    raw = data.get("memory_retention_policy", "forever")
    if not isinstance(raw, str):
        return None
    return _POLICY_TO_DAYS.get(raw.strip().lower(), None)


def is_retention_enforcement_enabled() -> bool:
    """Feature flag gate for the retention worker.

    Returns True only when `ENABLE_RETENTION_ENFORCEMENT` is explicitly
    set to a truthy string. This lets us ship the code path in Slice 1
    and flip it on later once the tombstone pipeline is proven in
    production.
    """
    raw = (os.getenv("ENABLE_RETENTION_ENFORCEMENT") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def describe_policy() -> dict:
    """Compact summary for auditors and health probes."""
    days = get_retention_days()
    return {
        "policy_days": days,
        "policy_label": "forever" if days is None else f"{days}d",
        "enforcement_enabled": is_retention_enforcement_enabled(),
        "strict_cohorts": sorted(_STRICT_RETENTION_PROGRAMS),
        "strict_default_days": _STRICT_DEFAULT_DAYS,
    }
