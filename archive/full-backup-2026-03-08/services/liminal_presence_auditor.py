"""
LITTLE NATE — Liminal Presence Auditor
Verifies that each of the three Liminal Presence agents (Silence Sentinel,
Language Drift Monitor, Field Response Parser) has produced a fresh result
within its expected interval. Reports 3/3 TRUSTED when all are current.

Scheduled 3x daily (5 AM, 5 PM, 11 PM UTC) with stagger delay of 320s.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nate.liminal_presence_auditor")

AUDIT_HOURS = {5, 17, 23}

AGENT_FRESHNESS = [
    {
        "agent": "silence_sentinel",
        "label": "Silence Sentinel",
        "max_age_minutes": 35,
    },
    {
        "agent": "language_drift",
        "label": "Language Drift Monitor",
        "max_age_minutes": 420,  # 7 hours
    },
    {
        "agent": "field_response",
        "label": "Field Response Parser",
        "max_age_minutes": 150,  # 2.5 hours
    },
]


class LiminalPresenceAuditor:

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._sent_windows: set = set()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("LiminalPresenceAuditor started (3x daily at UTC 05:00, 17:00, 23:00)")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("LiminalPresenceAuditor stopped")

    async def _run_loop(self):
        await asyncio.sleep(320)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                window_key = f"{now.date().isoformat()}_{now.hour}"
                if now.hour in AUDIT_HOURS and window_key not in self._sent_windows:
                    await self._build_and_send(now)
                    self._sent_windows.add(window_key)
                    self._sent_windows = {
                        k for k in self._sent_windows
                        if k.startswith(now.date().isoformat())
                    }
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("LiminalPresenceAuditor tick failed: %s", e, exc_info=True)
            await asyncio.sleep(60)

    async def _build_and_send(self, now: datetime):
        results = []
        latest_signals: dict = {}
        quality_warnings: list = []

        async with self.db_pool.acquire() as conn:
            for spec in AGENT_FRESHNESS:
                row = await conn.fetchrow("""
                    SELECT signal, score, detail, metadata, created_at
                    FROM liminal_presence_analysis
                    WHERE agent = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, spec["agent"])

                if not row:
                    results.append({
                        "agent": spec["label"],
                        "status": "WARNING",
                        "reason": "No analysis found — agent may be new",
                    })
                    continue

                age_minutes = (now - row["created_at"].replace(tzinfo=timezone.utc)).total_seconds() / 60.0

                if age_minutes <= spec["max_age_minutes"]:
                    result_entry = {
                        "agent": spec["label"],
                        "status": "TRUSTED",
                        "signal": row["signal"],
                        "age_minutes": round(age_minutes, 1),
                    }
                    latest_signals[spec["agent"]] = row["signal"]

                    # 6a: Signal quality checks
                    qw = await self._check_signal_quality(conn, spec, row)
                    if qw:
                        result_entry["quality_warnings"] = qw
                        quality_warnings.extend(qw)

                    results.append(result_entry)
                else:
                    results.append({
                        "agent": spec["label"],
                        "status": "WARNING",
                        "reason": f"Stale — last result {age_minutes:.0f}min ago (max {spec['max_age_minutes']}min)",
                    })

        # 6b: Compute LRI
        lri_score, lri_signal = self._compute_lri(latest_signals)

        # 6c: Correction-loop verification
        correction_warning = await self._check_correction_loop(latest_signals)
        if correction_warning:
            quality_warnings.append(correction_warning)

        trusted = sum(1 for r in results if r["status"] == "TRUSTED")
        total = len(results)

        # Email silenced — Trust Enforcer sends consolidated report

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (type, platform, content, created_at)
                    VALUES ($1, $2, $3, NOW())
                """, "liminal_presence_audit_sent", "system",
                    json.dumps({
                        "trusted": trusted,
                        "total": total,
                        "results": results,
                        "lri_score": lri_score,
                        "lri_signal": lri_signal,
                        "quality_warnings": quality_warnings,
                        "timestamp": now.isoformat(),
                    }))
        except Exception as e:
            logger.error("LiminalPresenceAuditor: failed to log activity: %s", e)

        logger.info(
            "LiminalPresenceAuditor: %d/%d TRUSTED | LRI: %s (%.2f)%s",
            trusted, total, lri_signal, lri_score,
            f" | {len(quality_warnings)} warnings" if quality_warnings else "",
        )

    async def _check_signal_quality(self, conn, spec: dict, latest_row) -> list:
        """Check for persistent RED signals and authority alerts."""
        warnings = []
        agent = spec["agent"]

        if agent == "language_drift" and latest_row["signal"] == "RED":
            meta = latest_row["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            consecutive = (meta or {}).get("consecutive_red_count", 0)
            if consecutive >= 3:
                warnings.append(
                    f"Persistent voice drift — RED for {consecutive} consecutive cycles (~{consecutive * 6}h)"
                )

        if agent == "field_response":
            meta = latest_row["metadata"]
            if isinstance(meta, str):
                meta = json.loads(meta)
            if (meta or {}).get("authority_alert"):
                warnings.append(
                    "Authority transfer detected in audience responses"
                )

        return warnings

    def _compute_lri(self, latest_signals: dict) -> tuple:
        """Compute Liminal Readiness Index from latest agent signals."""
        weight_map = {"GREEN": 1.0, "YELLOW": 0.5, "RED": 0.0}

        silence = weight_map.get(latest_signals.get("silence_sentinel", "GREEN"), 0.5)
        drift = weight_map.get(latest_signals.get("language_drift", "GREEN"), 0.5)
        field = weight_map.get(latest_signals.get("field_response", "GREEN"), 0.5)

        lri = silence * 0.3 + drift * 0.4 + field * 0.3

        if lri >= 0.8:
            signal = "GREEN"
        elif lri >= 0.5:
            signal = "YELLOW"
        else:
            signal = "RED"

        return round(lri, 2), signal

    async def _check_correction_loop(self, latest_signals: dict) -> Optional[str]:
        """Verify that voice corrections are being applied when drift is active."""
        drift_signal = latest_signals.get("language_drift", "GREEN")
        if drift_signal not in ("RED", "YELLOW"):
            return None

        try:
            async with self.db_pool.acquire() as conn:
                correction_count = await conn.fetchval("""
                    SELECT COUNT(*)
                    FROM skyeye_activity
                    WHERE type = 'voice_correction_applied'
                      AND created_at > NOW() - INTERVAL '24 hours'
                """)
            if (correction_count or 0) == 0:
                return (
                    f"Drift correction loop may not be active — "
                    f"language_drift is {drift_signal} but no voice_correction_applied "
                    f"events logged in last 24h"
                )
        except Exception as e:
            logger.debug("Correction loop check failed: %s", e)
        return None
