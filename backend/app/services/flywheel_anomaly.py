"""Flywheel anomaly bus (W17) — email/CEO alert WITHOUT decidable inbox.

Kinds: rollback_storm, queens_disagree_lineage, confound_spike,
burst_destroy_fail, watchdog_blind, fence_manifest_mismatch,
bootstrap_cap, fingerprint_drift, honeytoken, fallback_drill_fail,
drift_sentinel, merge_disk_low, merge_drain_fail.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("flywheel_anomaly")

ANOMALY_KINDS = frozenset({
    "rollback_storm",
    "queens_disagree_lineage",
    "confound_spike",
    "burst_destroy_fail",
    "watchdog_blind",
    "fence_manifest_mismatch",
    "bootstrap_cap",
    "fingerprint_drift",
    "honeytoken",
    "fallback_drill_fail",
    "drift_sentinel",
    "merge_disk_low",  # QUANTUM-CRYSTAL-ARCH — Phase C: <120GB free before merge
    "merge_drain_fail",  # QUANTUM-CRYSTAL-ARCH — Phase C: merge_drain orchestrator exception
})

_COOLDOWN: Dict[str, float] = {}
_COOLDOWN_S = int(os.getenv("FLYWHEEL_ANOMALY_COOLDOWN_S", "3600"))


def _admin_email() -> str:
    try:
        from app.config import settings

        raw = (getattr(settings, "ADMIN_ALERT_EMAILS", None) or "").split(",")
        if raw and raw[0].strip():
            return raw[0].strip()
    except Exception:
        pass
    return os.getenv("ADMIN_ALERT_EMAIL", "support@sovereignsanctuary.net")


async def notify_flywheel_anomaly(
    kind: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    db_pool=None,
    notification_system=None,
) -> Dict[str, Any]:
    """Alert humans without creating a CEO inbox decide row."""
    kind = (kind or "").strip()
    if kind not in ANOMALY_KINDS:
        logger.warning("flywheel_anomaly: unknown kind %s", kind)
        kind = "confound_spike"
    payload = payload or {}
    now = time.time()
    last = _COOLDOWN.get(kind, 0.0)
    if now - last < _COOLDOWN_S:
        return {"ok": True, "deduped": True, "kind": kind}
    _COOLDOWN[kind] = now

    body = (
        f"[FLYWHEEL ANOMALY] {kind}\n\n"
        f"{json.dumps(payload, default=str, indent=2)[:4000]}\n\n"
        "This is informational. No CEO inbox decision was created. "
        "Use reverse pad / suppress if needed."
    )
    emailed = False
    if notification_system and hasattr(notification_system, "_send_email"):
        try:
            await notification_system._send_email(
                _admin_email(),
                f"Flywheel anomaly: {kind}",
                body,
            )
            emailed = True
        except Exception as e:
            logger.warning("flywheel_anomaly: email failed: %s", e)
    else:
        logger.error("flywheel_anomaly: %s | %s", kind, body[:500])

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                    VALUES ('flywheel', 'flywheel_anomaly', $1, 'warning', $2::jsonb, NOW())
                    """,
                    f"{kind}: {json.dumps(payload, default=str)[:800]}",
                    json.dumps({"kind": kind, **payload}, default=str),
                )
        except Exception as e:
            logger.warning("flywheel_anomaly: activity log failed: %s", e)

    return {"ok": True, "kind": kind, "emailed": emailed, "deduped": False}
