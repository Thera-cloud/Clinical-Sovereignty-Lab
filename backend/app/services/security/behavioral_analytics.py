"""
HIVE DEFENSE PROTOCOL — Behavioral Analytics Engine (Phase 8B)
Insider threat detection through continuous monitoring of HOW coaches
and staff access member data.

Anomaly Signals
---------------
* **bulk_access** — >3× average daily access volume.
* **off_hours** — access at unusual times → triggers MFA re-verification.
* **unassigned_access** — accessing records of non-assigned members → immediate block.
* **export_patterns** — sequential browsing + copy-paste timing → ML score >0.7 alert.
* **data_volume** — pulling full histories instead of summaries → rate limiting.

Principle: a coach viewing a briefing before a session is *normal*.
Fifty records at 2 AM with only 10 assigned members is *not*.

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

import structlog

from app.models.hive_defense import DefconLevel, ForensicRecord

logger = structlog.get_logger("hive.behavioral_analytics")


# =============================================================================
# CONSTANTS
# =============================================================================

# A user accessing >3× their personal daily average is flagged.
BULK_ACCESS_MULTIPLIER: float = 3.0

# Off-hours window (UTC).  Outside this range triggers an MFA re-verify.
BUSINESS_HOURS_START: int = 7   # 07:00 UTC
BUSINESS_HOURS_END: int = 22    # 22:00 UTC

# ML-style composite score threshold for export-pattern detection.
EXPORT_PATTERN_THRESHOLD: float = 0.7

# Maximum records accessible per minute before rate-limiting kicks in.
RATE_LIMIT_PER_MINUTE: int = 30

# Number of recent accesses to retain per user for pattern analysis.
ACCESS_HISTORY_WINDOW: int = 500

# Data-volume flag: pulling more than this many full records in a session.
FULL_HISTORY_THRESHOLD: int = 10


# =============================================================================
# ANOMALY FLAGS
# =============================================================================

class AnomalyFlag:
    """Enumeration of anomaly flag identifiers."""
    BULK_ACCESS = "bulk_access"
    OFF_HOURS = "off_hours"
    UNASSIGNED_ACCESS = "unassigned_access"
    EXPORT_PATTERN = "export_pattern"
    DATA_VOLUME = "data_volume"
    RATE_LIMIT = "rate_limit_exceeded"


# =============================================================================
# ACCESS RECORD
# =============================================================================

class AccessRecord:
    """Lightweight in-memory representation of a single data-access event."""

    __slots__ = (
        "user_id", "resource_type", "resource_id",
        "timestamp", "is_full_history", "metadata",
    )

    def __init__(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        timestamp: float,
        is_full_history: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.user_id = user_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.timestamp = timestamp
        self.is_full_history = is_full_history
        self.metadata = metadata or {}


# =============================================================================
# BEHAVIORAL ANALYTICS ENGINE
# =============================================================================

class BehavioralAnalytics:
    """
    Insider-threat detection through continuous behavioural monitoring.

    Tracks every data-access event by coaches and staff, maintaining
    per-user baselines and firing graduated alerts when access patterns
    diverge from the established norm.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for persistence and assignment lookups.
    forensic_logger : Any, optional
        Reference to :class:`ForensicLogger` for immutable audit records.
    defcon_provider : callable, optional
        Async callable returning the current DEFCON level.
    """

    def __init__(
        self,
        db_pool: Any = None,
        forensic_logger: Any = None,
        defcon_provider: Optional[Any] = None,
    ) -> None:
        self.db_pool = db_pool
        self.forensic_logger = forensic_logger
        self.defcon_provider = defcon_provider

        # Per-user access history (ring buffer)
        self._access_history: Dict[str, List[AccessRecord]] = defaultdict(list)

        # Per-user daily access counts  (date_str → count)
        self._daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Per-user running average of daily accesses
        self._daily_avg: Dict[str, float] = {}

        # Per-user assigned member set  (user_id → {member_ids})
        self._assignments: Dict[str, Set[str]] = defaultdict(set)

        # Per-user rate-limit tracking (timestamps within current minute)
        self._rate_window: Dict[str, List[float]] = defaultdict(list)

        # Sequential-browse detector state
        self._sequential_browse: Dict[str, List[float]] = defaultdict(list)

        # Cumulative metrics
        self._total_accesses_recorded: int = 0
        self._total_anomalies_flagged: int = 0
        self._total_blocks: int = 0

    # ------------------------------------------------------------------
    # Assignment management
    # ------------------------------------------------------------------

    async def load_assignments(self) -> None:
        """Load coach → member assignment mappings from the database.

        This populates the in-memory ``_assignments`` dict used by the
        unassigned-access check.  Should be called at startup and
        periodically refreshed.
        """
        if not self.db_pool:
            logger.warning("behavioral_analytics_no_db", msg="Cannot load assignments without db_pool")
            return

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT coach_id, member_id
                    FROM coach_member_assignments
                    WHERE active = true
                """)
                self._assignments.clear()
                for row in rows:
                    coach_id = str(row["coach_id"])
                    member_id = str(row["member_id"])
                    self._assignments[coach_id].add(member_id)

            logger.info(
                "assignments_loaded",
                coach_count=len(self._assignments),
                total_links=sum(len(v) for v in self._assignments.values()),
            )
        except Exception as exc:
            logger.error("assignment_load_failed", error=str(exc))

    def set_assignments(self, user_id: str, member_ids: Set[str]) -> None:
        """Manually set coach → member assignments (useful for tests)."""
        self._assignments[user_id] = set(member_ids)

    # ------------------------------------------------------------------
    # Core: Record Access
    # ------------------------------------------------------------------

    async def record_access(
        self,
        user_id: str,
        resource_type: str,
        resource_id: str,
        timestamp: Optional[float] = None,
        is_full_history: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a single data-access event and run real-time anomaly checks.

        Parameters
        ----------
        user_id : str
            Identifier of the coach or staff member performing the access.
        resource_type : str
            Kind of resource accessed (e.g. ``"member_record"``, ``"session_note"``).
        resource_id : str
            Unique identifier of the accessed resource.
        timestamp : float, optional
            UNIX epoch timestamp.  Defaults to ``time.time()``.
        is_full_history : bool
            Whether this access pulled a full record history (not a summary).
        metadata : dict, optional
            Extra context (IP, user-agent, etc.).

        Returns
        -------
        dict
            Evaluation result including any triggered flags and actions.
        """
        ts = timestamp or time.time()
        record = AccessRecord(
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            timestamp=ts,
            is_full_history=is_full_history,
            metadata=metadata,
        )

        # Append to in-memory history (bounded)
        history = self._access_history[user_id]
        history.append(record)
        if len(history) > ACCESS_HISTORY_WINDOW:
            self._access_history[user_id] = history[-ACCESS_HISTORY_WINDOW:]

        # Update daily count
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        self._daily_counts[user_id][date_str] += 1

        self._total_accesses_recorded += 1

        # Run real-time checks
        flags = await self._evaluate_access(record)

        # Persist to DB
        await self._persist_access(record, flags)

        if flags:
            self._total_anomalies_flagged += 1
            logger.warning(
                "anomaly_flags_triggered",
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                flags=[f["flag"] for f in flags],
            )

        return {
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": ts,
            "flags": flags,
            "action": self._determine_action(flags),
        }

    # ------------------------------------------------------------------
    # Core: Evaluate User
    # ------------------------------------------------------------------

    async def evaluate_user(self, user_id: str) -> Dict[str, Any]:
        """Compute an aggregate anomaly evaluation for a user.

        Analyses the full in-memory access history and returns a composite
        anomaly score (0.0–1.0) plus a list of specific flags.

        Returns
        -------
        dict
            ``anomaly_score``, ``flags``, ``access_count``, ``recommendation``.
        """
        history = self._access_history.get(user_id, [])
        if not history:
            return {
                "user_id": user_id,
                "anomaly_score": 0.0,
                "flags": [],
                "access_count": 0,
                "recommendation": "no_data",
            }

        now = time.time()
        flags: List[Dict[str, Any]] = []
        anomaly_score = 0.0

        # --- 1. Bulk access ---
        score, flag = self._check_bulk_access(user_id, now)
        anomaly_score += score
        if flag:
            flags.append(flag)

        # --- 2. Off-hours ---
        score, flag = self._check_off_hours(history, now)
        anomaly_score += score
        if flag:
            flags.append(flag)

        # --- 3. Unassigned access ---
        score, uflags = await self._check_unassigned_access(user_id, history)
        anomaly_score += score
        flags.extend(uflags)

        # --- 4. Export patterns ---
        score, flag = self._check_export_patterns(user_id, history)
        anomaly_score += score
        if flag:
            flags.append(flag)

        # --- 5. Data volume (full-history pulls) ---
        score, flag = self._check_data_volume(history, now)
        anomaly_score += score
        if flag:
            flags.append(flag)

        anomaly_score = min(1.0, anomaly_score)

        recommendation = "normal"
        if anomaly_score >= 0.8:
            recommendation = "block_and_investigate"
        elif anomaly_score >= 0.5:
            recommendation = "mfa_reverify_and_alert"
        elif anomaly_score >= 0.3:
            recommendation = "monitor_closely"

        # Log forensic record for non-trivial scores
        if anomaly_score >= 0.3 and self.forensic_logger:
            try:
                await self.forensic_logger.log_event(
                    event_type="hive.behavioral.anomaly_evaluation",
                    source_entity=user_id,
                    evidence={
                        "anomaly_score": round(anomaly_score, 4),
                        "flags": [f["flag"] for f in flags],
                        "recommendation": recommendation,
                        "access_count": len(history),
                    },
                )
            except Exception as exc:
                logger.debug("forensic_log_failed", error=str(exc))

        return {
            "user_id": user_id,
            "anomaly_score": round(anomaly_score, 4),
            "flags": flags,
            "access_count": len(history),
            "recommendation": recommendation,
            "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Core: Daily Report
    # ------------------------------------------------------------------

    async def get_daily_report(self) -> Dict[str, Any]:
        """Generate a summary report of all users' access patterns for today.

        Returns
        -------
        dict
            Per-user anomaly scores, flags, aggregate statistics, and a
            list of users requiring attention.
        """
        now = time.time()
        today_str = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        user_reports: List[Dict[str, Any]] = []
        attention_required: List[str] = []

        for user_id in list(self._access_history.keys()):
            evaluation = await self.evaluate_user(user_id)
            today_count = self._daily_counts.get(user_id, {}).get(today_str, 0)
            evaluation["today_access_count"] = today_count

            user_reports.append(evaluation)
            if evaluation["anomaly_score"] >= 0.3:
                attention_required.append(user_id)

        # Sort by anomaly score descending
        user_reports.sort(key=lambda r: r["anomaly_score"], reverse=True)

        report = {
            "date": today_str,
            "total_users_monitored": len(user_reports),
            "total_accesses_today": sum(
                self._daily_counts.get(uid, {}).get(today_str, 0)
                for uid in self._access_history
            ),
            "attention_required": attention_required,
            "user_reports": user_reports,
            "cumulative_stats": {
                "total_accesses_recorded": self._total_accesses_recorded,
                "total_anomalies_flagged": self._total_anomalies_flagged,
                "total_blocks": self._total_blocks,
            },
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        logger.info(
            "daily_report_generated",
            users=len(user_reports),
            attention=len(attention_required),
        )

        return report

    # ------------------------------------------------------------------
    # Anomaly Check: Bulk Access
    # ------------------------------------------------------------------

    def _check_bulk_access(
        self, user_id: str, now: float,
    ) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Flag if today's access count exceeds 3× the user's daily average."""
        today_str = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
        today_count = self._daily_counts.get(user_id, {}).get(today_str, 0)

        # Compute running daily average (exclude today)
        daily = self._daily_counts.get(user_id, {})
        past_days = {k: v for k, v in daily.items() if k != today_str}

        if not past_days:
            # Not enough history — update average and skip
            self._daily_avg[user_id] = float(today_count)
            return 0.0, None

        avg = sum(past_days.values()) / len(past_days)
        self._daily_avg[user_id] = avg

        threshold = max(avg * BULK_ACCESS_MULTIPLIER, 10)  # minimum threshold of 10
        if today_count > threshold:
            return 0.25, {
                "flag": AnomalyFlag.BULK_ACCESS,
                "severity": "high",
                "detail": (
                    f"Today's access count ({today_count}) exceeds "
                    f"{BULK_ACCESS_MULTIPLIER}× daily average ({avg:.1f})"
                ),
                "today_count": today_count,
                "daily_average": round(avg, 2),
            }

        return 0.0, None

    # ------------------------------------------------------------------
    # Anomaly Check: Off-Hours
    # ------------------------------------------------------------------

    def _check_off_hours(
        self, history: List[AccessRecord], now: float,
    ) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Flag access events occurring outside business hours (UTC)."""
        # Check the most recent access
        if not history:
            return 0.0, None

        latest = history[-1]
        hour = datetime.fromtimestamp(latest.timestamp, tz=timezone.utc).hour

        if hour < BUSINESS_HOURS_START or hour >= BUSINESS_HOURS_END:
            # Count how many off-hours accesses in the last 24h
            cutoff = now - 86400
            off_hours_count = sum(
                1 for r in history
                if r.timestamp >= cutoff
                and (
                    datetime.fromtimestamp(r.timestamp, tz=timezone.utc).hour < BUSINESS_HOURS_START
                    or datetime.fromtimestamp(r.timestamp, tz=timezone.utc).hour >= BUSINESS_HOURS_END
                )
            )

            severity = "medium" if off_hours_count <= 3 else "high"
            score = 0.15 if off_hours_count <= 3 else 0.25

            return score, {
                "flag": AnomalyFlag.OFF_HOURS,
                "severity": severity,
                "detail": (
                    f"Off-hours access detected at {hour:02d}:xx UTC "
                    f"({off_hours_count} off-hours accesses in last 24h)"
                ),
                "action": "mfa_reverify",
                "off_hours_count_24h": off_hours_count,
            }

        return 0.0, None

    # ------------------------------------------------------------------
    # Anomaly Check: Unassigned Access
    # ------------------------------------------------------------------

    async def _check_unassigned_access(
        self, user_id: str, history: List[AccessRecord],
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """Flag and block access to records of non-assigned members.

        This is the most critical signal — accessing unassigned members'
        data is an immediate-block event.
        """
        assigned = self._assignments.get(user_id, set())
        if not assigned:
            # No assignment data available — cannot check
            return 0.0, []

        # Check recent accesses for member-record types
        now = time.time()
        cutoff = now - 3600  # last hour
        flags: List[Dict[str, Any]] = []
        unassigned_ids: Set[str] = set()

        for record in history:
            if record.timestamp < cutoff:
                continue
            if record.resource_type in ("member_record", "session_note", "member_history"):
                if record.resource_id not in assigned:
                    unassigned_ids.add(record.resource_id)

        if unassigned_ids:
            self._total_blocks += 1
            score = min(0.5, 0.15 * len(unassigned_ids))
            flags.append({
                "flag": AnomalyFlag.UNASSIGNED_ACCESS,
                "severity": "critical",
                "detail": (
                    f"Accessed {len(unassigned_ids)} unassigned member(s): "
                    f"{', '.join(list(unassigned_ids)[:5])}"
                ),
                "action": "block_immediately",
                "unassigned_member_ids": list(unassigned_ids),
            })
            return score, flags

        return 0.0, []

    # ------------------------------------------------------------------
    # Anomaly Check: Export Patterns
    # ------------------------------------------------------------------

    def _check_export_patterns(
        self, user_id: str, history: List[AccessRecord],
    ) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Detect sequential browsing and rapid-access patterns (data exfiltration).

        Computes a composite ML-style score from:
        - Inter-access interval regularity (robotic pacing)
        - Sequential resource-ID access (alphabetical / numerical order)
        - Overall speed (accesses per minute)

        An aggregated score > 0.7 triggers an alert.
        """
        now = time.time()
        recent_cutoff = now - 600  # last 10 minutes
        recent = [r for r in history if r.timestamp >= recent_cutoff]

        if len(recent) < 5:
            return 0.0, None

        # --- Component 1: Interval regularity ---
        intervals = [
            recent[i + 1].timestamp - recent[i].timestamp
            for i in range(len(recent) - 1)
        ]
        mean_interval = sum(intervals) / len(intervals) if intervals else 0
        variance = (
            sum((iv - mean_interval) ** 2 for iv in intervals) / len(intervals)
            if intervals else 0
        )
        std_dev = math.sqrt(variance)
        # Low std-dev relative to mean → robotic pacing
        regularity_score = max(0, 1.0 - (std_dev / (mean_interval + 0.01)))
        regularity_score = min(1.0, regularity_score)

        # --- Component 2: Sequential resource ID access ---
        resource_ids = [r.resource_id for r in recent]
        sorted_ids = sorted(resource_ids)
        # Measure how close the access order is to sorted order
        matches = sum(1 for a, b in zip(resource_ids, sorted_ids) if a == b)
        sequential_score = matches / len(resource_ids) if resource_ids else 0

        # --- Component 3: Access speed ---
        time_span = recent[-1].timestamp - recent[0].timestamp
        rate = len(recent) / (time_span / 60.0) if time_span > 0 else 0
        speed_score = min(1.0, rate / RATE_LIMIT_PER_MINUTE)

        # --- Composite score (weighted average) ---
        composite = (
            regularity_score * 0.35
            + sequential_score * 0.35
            + speed_score * 0.30
        )

        # Track for sequential-browse detector
        self._sequential_browse[user_id] = [r.timestamp for r in recent[-20:]]

        if composite >= EXPORT_PATTERN_THRESHOLD:
            return 0.3, {
                "flag": AnomalyFlag.EXPORT_PATTERN,
                "severity": "high",
                "detail": (
                    f"Export pattern detected (composite={composite:.2f}): "
                    f"regularity={regularity_score:.2f}, "
                    f"sequential={sequential_score:.2f}, "
                    f"speed={speed_score:.2f}"
                ),
                "composite_score": round(composite, 4),
                "components": {
                    "regularity": round(regularity_score, 4),
                    "sequential": round(sequential_score, 4),
                    "speed": round(speed_score, 4),
                },
            }

        return 0.0, None

    # ------------------------------------------------------------------
    # Anomaly Check: Data Volume
    # ------------------------------------------------------------------

    def _check_data_volume(
        self, history: List[AccessRecord], now: float,
    ) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Flag users pulling full record histories instead of summaries."""
        cutoff = now - 3600  # last hour
        full_history_pulls = [
            r for r in history
            if r.timestamp >= cutoff and r.is_full_history
        ]

        if len(full_history_pulls) >= FULL_HISTORY_THRESHOLD:
            return 0.2, {
                "flag": AnomalyFlag.DATA_VOLUME,
                "severity": "medium",
                "detail": (
                    f"{len(full_history_pulls)} full-history pulls in last hour "
                    f"(threshold: {FULL_HISTORY_THRESHOLD})"
                ),
                "action": "rate_limit",
                "full_history_count": len(full_history_pulls),
            }

        return 0.0, None

    # ------------------------------------------------------------------
    # Action determination
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_action(flags: List[Dict[str, Any]]) -> str:
        """Determine the most severe action required based on triggered flags."""
        if not flags:
            return "allow"

        # Priority: block > mfa_reverify > rate_limit > monitor
        actions = set()
        for flag in flags:
            action = flag.get("action", "monitor")
            actions.add(action)

        if "block_immediately" in actions:
            return "block_immediately"
        if "mfa_reverify" in actions:
            return "mfa_reverify"
        if "rate_limit" in actions:
            return "rate_limit"
        return "monitor"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_access(
        self, record: AccessRecord, flags: List[Dict[str, Any]],
    ) -> None:
        """Write the access event and any flags to the database."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO behavioral_access_log
                        (user_id, resource_type, resource_id, accessed_at,
                         is_full_history, metadata, anomaly_flags)
                    VALUES ($1, $2, $3, to_timestamp($4), $5, $6, $7)
                    """,
                    record.user_id,
                    record.resource_type,
                    record.resource_id,
                    record.timestamp,
                    record.is_full_history,
                    json.dumps(record.metadata),
                    json.dumps(flags) if flags else None,
                )
        except Exception as exc:
            # Access logging is best-effort; never block the access itself.
            logger.debug("access_log_persist_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring dashboards."""
        return {
            "users_tracked": len(self._access_history),
            "total_accesses_recorded": self._total_accesses_recorded,
            "total_anomalies_flagged": self._total_anomalies_flagged,
            "total_blocks": self._total_blocks,
            "assignments_loaded": sum(len(v) for v in self._assignments.values()),
        }

    def __repr__(self) -> str:
        return (
            f"<BehavioralAnalytics users={len(self._access_history)} "
            f"accesses={self._total_accesses_recorded} "
            f"anomalies={self._total_anomalies_flagged}>"
        )
