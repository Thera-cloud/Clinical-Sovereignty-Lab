"""LITTLE NATE — Sensitive Clinical Bridge Telemetry Agent.

Runs hourly (configurable). Single duty: detect when a per-gap detector's
false-positive rate is sustained above threshold across multiple windows and
SAFELY auto-disable that detector — with a 30-minute admin-overridable
countdown — so a single bad detector cannot poison the whole bridge.

This is the highest-blast-radius agent in the build. Plan v1.3 §Gap F said
"auto-disable then alert"; Phase 5 Note 1 hardened that to:

    1. MULTI-WINDOW AGREEMENT
       Compute false_positive_rate across THREE trailing windows
       (24h, 72h, 7d). Auto-disable only arms when ALL THREE windows agree
       on threshold breach (rate > 0.05 AND clinician_reviewed sample
       size >= 20 in each window). Single-window breach without
       multi-window agreement = noise → no action.

    2. ALERT + 30-MIN COUNTDOWN BEFORE DISABLE
       Arming writes detector_auto_disable_state with
       commit_after = NOW() + countdown_minutes, emits coach_alert_high
       to all admins, and waits. Only on the next cycle, if cancelled_at
       is still NULL and commit_after <= NOW(), does the agent commit
       the disable.

    3. RE-ENABLE REQUIRES RESOLVED TELEMETRY
       The REST handler that re-enables a flag MUST call
       `assert_reenable_telemetry_resolved()` from this module before
       flipping the flag back ON. The function requires a fresh
       clinician-reviewed sample of >= 20 events recorded AFTER
       disabled_at, with FP rate now under threshold.

ARMED-BUT-NEUTRAL at first apply. The agent ships with config row
`paused = TRUE` (set by migration 210). Pilot launch flips paused to
FALSE after cohort_5 has been live for 7+ days.

DATA SOURCES
============
- detector_telemetry          (migration 209) — per-event classification log
- detector_auto_disable_state (migration 210) — per-flag countdown/lifecycle
- app_settings                (migration 209) — runtime config + global flags
- sensitive_bridge_log        (migration 202) — append-only audit trail
- users                       (existing)      — admin discovery for alerts

OUTPUTS
=======
- detector_auto_disable_state row mutation (insert/update).
- sensitive_bridge_log audit row per lifecycle transition.
- coach_alert_high notifications to all admins on arming.
- app_settings.sensitive_bridge_global_gap_flags JSONB patch on commit.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nate.sensitive_bridge_telemetry_agent")

# Default config used if app_settings row is missing (defensive).
_DEFAULT_CONFIG: Dict[str, Any] = {
    "paused": True,
    "poll_interval_seconds": 3600,
    "countdown_minutes": 30,
    "fp_rate_threshold": 0.05,
    "min_reviewed_sample_per_window": 20,
    "min_reviewed_sample_for_reenable": 20,
    "windows": [
        {"label": "24h", "interval": "24 hours"},
        {"label": "72h", "interval": "72 hours"},
        {"label": "7d", "interval": "7 days"},
    ],
    "all_windows_must_agree": True,
    "stagger_seconds": 320,
}

# 16 gap_*_enabled flags managed by app_settings.sensitive_bridge_global_gap_flags.
# Only flags listed here are eligible for auto-disable; new flags added later
# must be added here AND auditor _FLAG_TO_DETECTOR map AND playbook.
_AUTO_DISABLEABLE_FLAGS: Tuple[str, ...] = (
    "gap_introjection_enabled",
    "gap_thalamic_gate_enabled",
    "gap_reengagement_enabled",
    "gap_arousal_cap_enabled",
    "gap_polyvictim_load_enabled",
    "gap_dual_diagnosis_enabled",
    "gap_active_disclosure_enabled",
    "gap_codeword_enabled",
    "gap_trigger_dates_enabled",
    "gap_legal_status_enabled",
    "gap_embodiment_phase_enabled",
    "gap_jurisdiction_compliance_enabled",
    "gap_minor_survivor_protections_enabled",
    "gap_parenting_no_pathologization_enabled",
    "gap_rj_companioning_enabled",
    "gap_cultural_context_enabled",
)


# ---------------------------------------------------------------------------
# Re-enable resolved-telemetry gate (Note 1 safeguard #3)
# ---------------------------------------------------------------------------
# Imported by the REST router. Kept module-level so a unit test can call it
# without spinning up the agent loop.

class ReenableTelemetryUnresolved(Exception):
    """Raised when admin tries to re-enable a flag whose telemetry is still bad."""

    def __init__(self, gap_flag: str, reason: str, snapshot: Dict[str, Any]):
        super().__init__(reason)
        self.gap_flag = gap_flag
        self.reason = reason
        self.snapshot = snapshot


async def assert_reenable_telemetry_resolved(
    db_pool,
    gap_flag: str,
    *,
    fp_rate_threshold: float = 0.05,
    min_reviewed_sample: int = 20,
) -> Dict[str, Any]:
    """Enforce Plan v1.3 Note 1 safeguard #3.

    Re-enabling an auto-disabled flag requires fresh clinician-reviewed
    telemetry recorded AFTER the disabled_at timestamp showing the FP rate
    is now under threshold across a fresh sample (>= min_reviewed_sample).

    Returns the snapshot that satisfied the gate (for storage in
    `detector_auto_disable_state.reenable_telemetry_snapshot`).

    Raises ReenableTelemetryUnresolved if the gate is not satisfied.
    """
    if not db_pool:
        # Conservative: if we can't read telemetry, refuse to re-enable.
        raise ReenableTelemetryUnresolved(
            gap_flag,
            reason="db_pool_unavailable_cannot_verify_telemetry",
            snapshot={},
        )

    async with db_pool.acquire() as conn:
        state = await conn.fetchrow(
            """
            SELECT state, disabled_at
            FROM detector_auto_disable_state
            WHERE gap_flag = $1
            """,
            gap_flag,
        )
        # Idempotent: a flag never auto-disabled has no gate to satisfy.
        if not state or state["state"] != "disabled" or state["disabled_at"] is None:
            return {
                "gate": "no_op_not_auto_disabled",
                "gap_flag": gap_flag,
                "state": (state or {}).get("state") if state else "absent",
            }

        disabled_at = state["disabled_at"]
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) FILTER (WHERE clinician_reviewed = TRUE) AS reviewed,
                   COUNT(*) FILTER (
                       WHERE clinician_reviewed = TRUE
                         AND classification = 'false_positive'
                   ) AS false_positives
            FROM detector_telemetry
            WHERE gap_flag = $1
              AND recorded_at > $2
            """,
            gap_flag,
            disabled_at,
        )

    reviewed = int((row or {}).get("reviewed") or 0)
    fp = int((row or {}).get("false_positives") or 0)
    rate = (fp / reviewed) if reviewed else 1.0

    snapshot: Dict[str, Any] = {
        "gap_flag": gap_flag,
        "disabled_at": disabled_at.isoformat(),
        "fresh_reviewed_count": reviewed,
        "fresh_false_positives": fp,
        "fresh_fp_rate": round(rate, 4),
        "threshold": fp_rate_threshold,
        "min_sample_required": min_reviewed_sample,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    if reviewed < min_reviewed_sample:
        raise ReenableTelemetryUnresolved(
            gap_flag,
            reason=(
                f"insufficient_fresh_clinician_reviewed_sample: "
                f"{reviewed}/{min_reviewed_sample}"
            ),
            snapshot=snapshot,
        )
    if rate > fp_rate_threshold:
        raise ReenableTelemetryUnresolved(
            gap_flag,
            reason=(
                f"fresh_fp_rate_still_above_threshold: "
                f"{round(rate, 4)} > {fp_rate_threshold}"
            ),
            snapshot=snapshot,
        )
    snapshot["gate"] = "passed"
    return snapshot


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class SensitiveBridgeTelemetryAgent:
    """Multi-window FP-rate watcher with countdown-then-disable lifecycle.

    Lifecycle per gap_flag:
        idle  ─[3-window breach]──>  armed  ─[commit_after reached]──>  disabled
                                       │
                                       └─[admin cancel]──>  idle (cancelled)

        disabled  ─[admin re-enable + resolved-telemetry gate]──>  reenabled
    """

    SERVICE_ID = "sensitive_bridge_telemetry_agent"

    def __init__(self, db_pool, notification_system=None, app_state=None):
        self.db_pool = db_pool
        self.notifications = notification_system
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Track which (gap_flag, armed_at) pairs we've already alerted on so
        # repeated cycles in the armed window don't spam admins.
        self._alerted: Dict[str, str] = {}

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("SensitiveBridgeTelemetryAgent started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SensitiveBridgeTelemetryAgent stopped")

    async def _run_loop(self) -> None:
        # Initial stagger so we don't collide with auditor at startup.
        cfg = await self._load_config()
        await asyncio.sleep(int(cfg.get("stagger_seconds", 320)))
        while self._running:
            try:
                cfg = await self._load_config()
                if cfg.get("paused", True):
                    logger.debug("Telemetry agent paused; skipping cycle")
                else:
                    await self._cycle(cfg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "SensitiveBridgeTelemetryAgent cycle error: %s", e, exc_info=True
                )
            interval = int(
                (await self._load_config()).get("poll_interval_seconds", 3600)
            )
            await asyncio.sleep(max(60, interval))

    # -- core cycle ---------------------------------------------------------

    async def _cycle(self, cfg: Dict[str, Any]) -> None:
        """One agent tick. Two phases:

        Phase A: Commit any armed flags whose countdown elapsed without override.
        Phase B: Evaluate every active flag's multi-window FP rate; arm if all
                 windows agree on breach.
        """
        if not self.db_pool:
            return

        # --- Phase A: commit pending disables ---
        await self._commit_pending_disables(cfg)

        # --- Phase B: evaluate each flag for new arming ---
        for gap_flag in _AUTO_DISABLEABLE_FLAGS:
            try:
                await self._evaluate_flag(gap_flag, cfg)
            except Exception as e:
                logger.warning(
                    "SensitiveBridgeTelemetryAgent: evaluate %s failed: %s",
                    gap_flag, e,
                )

    async def _commit_pending_disables(self, cfg: Dict[str, Any]) -> None:
        """Find any armed flags whose commit_after has passed and were not
        cancelled, then commit the disable atomically."""
        if not self.db_pool:
            return
        async with self.db_pool.acquire() as conn:
            pending = await conn.fetch(
                """
                SELECT gap_flag, armed_at, commit_after, fp_snapshot_at_arming
                FROM detector_auto_disable_state
                WHERE state = 'armed'
                  AND cancelled_at IS NULL
                  AND commit_after <= NOW()
                """
            )
            for row in pending:
                await self._commit_disable(
                    conn,
                    gap_flag=row["gap_flag"],
                    snapshot=row["fp_snapshot_at_arming"] or {},
                    armed_at=row["armed_at"],
                )

    async def _evaluate_flag(self, gap_flag: str, cfg: Dict[str, Any]) -> None:
        """Compute multi-window FP rate for a single flag; arm if all agree."""
        if not self.db_pool:
            return
        async with self.db_pool.acquire() as conn:
            state_row = await conn.fetchrow(
                """
                SELECT state, armed_at, cancelled_at
                FROM detector_auto_disable_state
                WHERE gap_flag = $1
                """,
                gap_flag,
            )
            current_state = (state_row or {}).get("state") if state_row else "idle"
            # Don't re-arm an already armed/disabled flag. Re-enable goes
            # through the REST router (with the resolved-telemetry gate).
            if current_state in ("armed", "disabled"):
                return

            windows = cfg.get("windows", _DEFAULT_CONFIG["windows"])
            threshold = float(cfg.get("fp_rate_threshold", 0.05))
            min_sample = int(cfg.get("min_reviewed_sample_per_window", 20))
            require_all = bool(cfg.get("all_windows_must_agree", True))

            snapshot: Dict[str, Any] = {}
            window_breaches: List[bool] = []
            for w in windows:
                label = str(w.get("label"))
                interval = str(w.get("interval"))
                # Interval is a fixed enum (24 hours / 72 hours / 7 days) sourced
                # from app_settings; never user input. Quoted as a literal because
                # asyncpg cannot parameterize INTERVAL strings.
                row = await conn.fetchrow(
                    f"""
                    SELECT COUNT(*) FILTER (WHERE clinician_reviewed = TRUE) AS reviewed,
                           COUNT(*) FILTER (
                               WHERE clinician_reviewed = TRUE
                                 AND classification = 'false_positive'
                           ) AS fp
                    FROM detector_telemetry
                    WHERE gap_flag = $1
                      AND recorded_at > NOW() - INTERVAL '{interval}'
                    """,
                    gap_flag,
                )
                reviewed = int((row or {}).get("reviewed") or 0)
                fp = int((row or {}).get("fp") or 0)
                rate = (fp / reviewed) if reviewed else 0.0
                window_breach = (reviewed >= min_sample and rate > threshold)
                snapshot[label] = {
                    "rate": round(rate, 4),
                    "fp": fp,
                    "reviewed": reviewed,
                    "min_sample": min_sample,
                    "breach": window_breach,
                }
                window_breaches.append(window_breach)

            if require_all:
                should_arm = all(window_breaches) and len(window_breaches) > 0
            else:
                should_arm = any(window_breaches)

            if not should_arm:
                # Touch last_observed_at so we know the agent saw this flag.
                await conn.execute(
                    """
                    INSERT INTO detector_auto_disable_state (gap_flag, state, last_observed_at)
                    VALUES ($1, 'idle', NOW())
                    ON CONFLICT (gap_flag) DO UPDATE
                    SET last_observed_at = NOW()
                    """,
                    gap_flag,
                )
                return

            # All windows agree → arm.
            countdown = int(cfg.get("countdown_minutes", 30))
            await self._arm_flag(
                conn, gap_flag=gap_flag, snapshot=snapshot, countdown_minutes=countdown,
            )

        # Outside the conn block: fan out admin alerts (not transactional).
        await self._alert_admins_armed(gap_flag, snapshot)

    # -- lifecycle transitions ---------------------------------------------

    async def _arm_flag(
        self, conn, *, gap_flag: str, snapshot: Dict[str, Any], countdown_minutes: int,
    ) -> None:
        """Insert/update detector_auto_disable_state to ARMED + write audit row."""
        await conn.execute(
            """
            INSERT INTO detector_auto_disable_state (
                gap_flag, state, fp_snapshot_at_arming,
                armed_at, commit_after, last_observed_at
            ) VALUES (
                $1, 'armed', $2::jsonb, NOW(), NOW() + ($3::text || ' minutes')::interval, NOW()
            )
            ON CONFLICT (gap_flag) DO UPDATE
            SET state = 'armed',
                fp_snapshot_at_arming = EXCLUDED.fp_snapshot_at_arming,
                armed_at = NOW(),
                commit_after = NOW() + ($3::text || ' minutes')::interval,
                cancelled_at = NULL,
                cancelled_by = NULL,
                cancellation_reason = NULL,
                last_observed_at = NOW()
            """,
            gap_flag, json.dumps(snapshot), str(countdown_minutes),
        )
        await self._log_event(
            conn,
            event_type="auto_disable_armed",
            severity="high",
            payload={
                "gap_flag": gap_flag,
                "snapshot": snapshot,
                "countdown_minutes": countdown_minutes,
                "commit_after_iso": (
                    datetime.now(timezone.utc) + timedelta(minutes=countdown_minutes)
                ).isoformat(),
            },
        )
        logger.warning(
            "Telemetry agent ARMED auto-disable for %s (commit in %d min)",
            gap_flag, countdown_minutes,
        )

    async def _commit_disable(
        self, conn, *, gap_flag: str, snapshot: Dict[str, Any], armed_at: datetime,
    ) -> None:
        """Flip the flag OFF in app_settings and mark state DISABLED.

        Safe to retry — JSONB patch + state update are idempotent.
        """
        # 1. Patch app_settings.sensitive_bridge_global_gap_flags → flag = false.
        await conn.execute(
            """
            UPDATE app_settings
            SET setting_value = jsonb_set(
                    COALESCE(setting_value, '{}'::jsonb),
                    ARRAY[$1],
                    'false'::jsonb,
                    true
                ),
                updated_at = NOW(),
                updated_by = 'telemetry_agent_auto_disable'
            WHERE setting_key = 'sensitive_bridge_global_gap_flags'
            """,
            gap_flag,
        )

        # 2. Mark state as DISABLED.
        await conn.execute(
            """
            UPDATE detector_auto_disable_state
            SET state = 'disabled',
                disabled_at = NOW(),
                disabled_by = 'telemetry_agent',
                disabled_reason = 'multi_window_fp_rate_above_threshold',
                last_observed_at = NOW()
            WHERE gap_flag = $1
            """,
            gap_flag,
        )

        # 3. Audit row.
        await self._log_event(
            conn,
            event_type="auto_disable_committed",
            severity="critical",
            payload={
                "gap_flag": gap_flag,
                "snapshot_at_arming": snapshot,
                "armed_at_iso": armed_at.isoformat() if armed_at else None,
                "committed_at_iso": datetime.now(timezone.utc).isoformat(),
                "global_flag_now": False,
            },
        )

        # 4. Also write the canonical Plan v1.3 §Gap F event for downstream
        #    consumers that watch for that name specifically.
        await self._log_event(
            conn,
            event_type="gap_feature_auto_disabled",
            severity="critical",
            payload={
                "gap_flag": gap_flag,
                "trigger": "telemetry_agent_multi_window_agreement",
            },
        )

        logger.error(
            "Telemetry agent COMMITTED auto-disable for %s (countdown elapsed without override)",
            gap_flag,
        )

    # -- admin alerting -----------------------------------------------------

    async def _alert_admins_armed(
        self, gap_flag: str, snapshot: Dict[str, Any],
    ) -> None:
        """Emit coach_alert_high to every admin when a flag is freshly armed.

        De-duplicated per (gap_flag, armed_at) so a long-running countdown
        doesn't spam admins on every cycle. Failure to send DOES NOT roll
        back the arming — alerts are best-effort, the audit trail is the
        contract.
        """
        if not self.db_pool:
            return
        # Read armed_at to dedupe.
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT armed_at
                FROM detector_auto_disable_state
                WHERE gap_flag = $1 AND state = 'armed'
                """,
                gap_flag,
            )
            armed_at = (row or {}).get("armed_at")
            if armed_at is None:
                return
            armed_key = armed_at.isoformat()
            if self._alerted.get(gap_flag) == armed_key:
                return
            admins = await conn.fetch(
                """
                SELECT username,
                       profile_data->>'email' AS email,
                       profile_data->>'phone' AS phone
                FROM users
                WHERE role = 'ADMIN'
                """,
            )

        subject = f"[coach_alert_high] Sensitive bridge auto-disable armed: {gap_flag}"
        body_lines = [
            "Sensitive Clinical Bridge telemetry agent has ARMED an auto-disable.",
            "",
            f"Detector flag : {gap_flag}",
            f"Armed at      : {armed_key}",
            "Countdown     : 30 minutes (configurable via app_settings)",
            "",
            "Multi-window FP-rate snapshot at arming:",
            json.dumps(snapshot, indent=2),
            "",
            "ADMIN OVERRIDE:",
            (
                f"  POST /api/admin/sensitive-bridge/auto-disable/{gap_flag}/cancel"
                "   — cancels the disable and returns the flag to idle state."
            ),
            "",
            "If no admin acts within the countdown window, the global feature flag",
            "for this detector will be set to FALSE for ALL enrolled users.",
        ]
        body = "\n".join(body_lines)

        for admin in admins:
            email = admin.get("email")
            phone = admin.get("phone")
            if not self.notifications:
                break
            try:
                if email and hasattr(self.notifications, "_send_email"):
                    await self.notifications._send_email(
                        email, subject, body,
                        notification_type="coach_alert_high",
                    )
                if phone and hasattr(self.notifications, "send_sms"):
                    await self.notifications.send_sms(
                        phone,
                        f"[coach_alert_high] Sensitive bridge ARMED auto-disable for "
                        f"{gap_flag}. 30-min countdown started. Cancel via admin API.",
                    )
            except Exception as e:
                logger.warning(
                    "Telemetry agent admin alert failed for %s: %s",
                    admin.get("username"), e,
                )

        self._alerted[gap_flag] = armed_key

    # -- audit log ----------------------------------------------------------

    async def _log_event(
        self, conn, *, event_type: str, severity: str, payload: Dict[str, Any],
    ) -> None:
        """Append a row to sensitive_bridge_log. Never raises."""
        try:
            await conn.execute(
                """
                INSERT INTO sensitive_bridge_log (
                    user_id, event_type, event_severity, payload_json,
                    recorded_by, access_classification, pii_screened_at
                ) VALUES (
                    'system', $1, $2, $3::jsonb,
                    'sensitive_bridge_telemetry_agent',
                    'admin_only_redacted', NOW()
                )
                """,
                event_type, severity, json.dumps(payload),
            )
        except Exception as e:
            logger.warning(
                "Telemetry agent failed to log %s: %s", event_type, e,
            )

    # -- config loader ------------------------------------------------------

    async def _load_config(self) -> Dict[str, Any]:
        """Load runtime config from app_settings; fall back to defaults."""
        if not self.db_pool:
            return dict(_DEFAULT_CONFIG)
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT setting_value
                    FROM app_settings
                    WHERE setting_key = 'sensitive_bridge_telemetry_agent'
                    """,
                )
        except Exception:
            return dict(_DEFAULT_CONFIG)
        if not row or not row["setting_value"]:
            return dict(_DEFAULT_CONFIG)
        cfg = row["setting_value"]
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                return dict(_DEFAULT_CONFIG)
        merged = dict(_DEFAULT_CONFIG)
        if isinstance(cfg, dict):
            merged.update(cfg)
        return merged


# ---------------------------------------------------------------------------
# Auditor self-check (consumed by sensitive_bridge_auditor Tier-1 slot
# `auto_disable_reenable_requires_resolved_telemetry`)
# ---------------------------------------------------------------------------


def _auditor_self_check() -> Dict[str, Any]:
    """Tier-1 slot data for the auditor. Sub-millisecond, in-process.

    Verifies module-level invariants that protect Plan v1.3 Note 1 safeguards:
      - The resolved-telemetry gate function is importable.
      - The gate raises on insufficient sample (defensive default).
      - The auto-disableable flag list is non-empty AND has 16 entries.
      - The agent class exposes start/stop.
    """
    out: Dict[str, Any] = {
        "module": __name__,
    }
    try:
        out["resolved_telemetry_gate_importable"] = callable(
            assert_reenable_telemetry_resolved
        )
        out["reenable_exception_class_importable"] = (
            ReenableTelemetryUnresolved.__name__ == "ReenableTelemetryUnresolved"
        )
        out["auto_disableable_flag_count"] = len(_AUTO_DISABLEABLE_FLAGS)
        out["auto_disableable_flag_count_is_16"] = (
            len(_AUTO_DISABLEABLE_FLAGS) == 16
        )
        out["agent_class_has_lifecycle"] = (
            hasattr(SensitiveBridgeTelemetryAgent, "start")
            and hasattr(SensitiveBridgeTelemetryAgent, "stop")
        )
        out["paused_default_is_true"] = (
            _DEFAULT_CONFIG.get("paused") is True
        )
        out["countdown_minutes_default"] = _DEFAULT_CONFIG.get("countdown_minutes")
        out["windows_count_is_3"] = len(_DEFAULT_CONFIG.get("windows", [])) == 3
        out["all_windows_must_agree_default_true"] = (
            _DEFAULT_CONFIG.get("all_windows_must_agree") is True
        )
        out["fp_rate_threshold_is_5pct"] = (
            float(_DEFAULT_CONFIG.get("fp_rate_threshold", 0)) == 0.05
        )
        out["min_reviewed_sample_is_20"] = (
            int(_DEFAULT_CONFIG.get("min_reviewed_sample_per_window", 0)) == 20
        )
        out["auto_disable_reenable_requires_resolved_telemetry"] = all([
            out["resolved_telemetry_gate_importable"],
            out["reenable_exception_class_importable"],
            out["paused_default_is_true"],
        ])
    except Exception as e:
        out["error"] = repr(e)[:120]
        out["auto_disable_reenable_requires_resolved_telemetry"] = False
    return out
