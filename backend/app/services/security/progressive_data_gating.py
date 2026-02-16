"""
HIVE DEFENSE PROTOCOL — Progressive Data Gating (Phase 8C, Third Cord)
Summary-first, click-through-for-detail access control for therapeutic data.

Coaches see summary-level data by default.  Full conversation history
and detailed therapeutic notes require an explicit click-through with
a stated reason.  All full-access requests are logged for audit, and
rate limiting prevents bulk data harvesting.

Access Levels
-------------
1. **SUMMARY** — Default view.  Aggregated statistics, coherence trends,
   session count, last session date, high-level notes.  No raw
   conversation text.
2. **DETAILED** — Expanded notes, session summaries with key quotes,
   coherence measurements per session.  Still not raw transcripts.
3. **FULL** — Complete conversation history, raw transcripts, verbatim
   notes.  Requires explicit click-through with reason.

Rate Limits
-----------
* > 3 full-access views in 1 hour → rate limit (soft block + warning)
* > 10 full-access views in 1 day → review queue (access paused pending
  review)

Every full-access request creates an immutable audit record.

Patent-Pending — Claim 54
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.progressive_data_gating")


# =============================================================================
# CONSTANTS
# =============================================================================

# Rate limit thresholds
HOURLY_FULL_ACCESS_LIMIT = 3
DAILY_FULL_ACCESS_LIMIT = 10

# Time windows
ONE_HOUR_SECONDS = 3600
ONE_DAY_SECONDS = 86400


# =============================================================================
# ENUMS
# =============================================================================

class AccessLevel(IntEnum):
    """Data access granularity levels. Higher = more detail."""
    SUMMARY = 1
    DETAILED = 2
    FULL = 3


class GateDecisionResult(str, Enum):
    """Outcome of a data gating request."""
    GRANTED = "granted"
    RATE_LIMITED = "rate_limited"
    REVIEW_REQUIRED = "review_required"
    DENIED = "denied"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class GatedDataResponse:
    """
    Response from a gated data request.

    Attributes
    ----------
    resource_id : str
        The requested resource.
    access_level : AccessLevel
        The level of data returned.
    data : dict
        The data at the appropriate detail level.
    gate_decision : GateDecisionResult
        Whether the request was granted, rate-limited, etc.
    audit_id : UUID or None
        Audit record ID for full-access requests.
    message : str
        Human-readable status message.
    """
    resource_id: str = ""
    access_level: AccessLevel = AccessLevel.SUMMARY
    data: Dict[str, Any] = field(default_factory=dict)
    gate_decision: GateDecisionResult = GateDecisionResult.GRANTED
    audit_id: Optional[UUID] = None
    message: str = ""


@dataclass
class FullAccessAuditRecord:
    """
    Immutable audit record for a full-access data request.

    Attributes
    ----------
    audit_id : UUID
        Unique audit record identifier.
    user_id : str
        The user who requested full access.
    resource_id : str
        The resource that was accessed.
    reason : str
        The stated reason for full access.
    access_level : AccessLevel
        The level of access granted.
    granted : bool
        Whether the access was actually granted.
    denial_reason : str
        If denied, the reason for denial.
    requested_at : datetime
        When the request was made.
    ip_address : str
        Requesting IP (if available).
    user_agent : str
        Requesting user agent (if available).
    """
    audit_id: UUID = field(default_factory=uuid4)
    user_id: str = ""
    resource_id: str = ""
    reason: str = ""
    access_level: AccessLevel = AccessLevel.FULL
    granted: bool = False
    denial_reason: str = ""
    requested_at: datetime = field(default_factory=datetime.utcnow)
    ip_address: str = ""
    user_agent: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for storage."""
        return {
            "audit_id": str(self.audit_id),
            "user_id": self.user_id,
            "resource_id": self.resource_id,
            "reason": self.reason,
            "access_level": self.access_level.value,
            "granted": self.granted,
            "denial_reason": self.denial_reason,
            "requested_at": self.requested_at.isoformat(),
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }


@dataclass
class UserAccessProfile:
    """
    Tracks a user's data access patterns for rate limiting.

    Attributes
    ----------
    user_id : str
        The user being tracked.
    full_access_timestamps : list[float]
        Monotonic timestamps of full-access requests.
    total_full_access_count : int
        Lifetime count of full-access requests.
    is_rate_limited : bool
        Whether the user is currently rate-limited.
    is_under_review : bool
        Whether the user's access is pending review.
    review_triggered_at : datetime or None
        When review was triggered.
    """
    user_id: str = ""
    full_access_timestamps: List[float] = field(default_factory=list)
    total_full_access_count: int = 0
    is_rate_limited: bool = False
    is_under_review: bool = False
    review_triggered_at: Optional[datetime] = None


# =============================================================================
# PROGRESSIVE DATA GATING ENGINE
# =============================================================================

class ProgressiveDataGating:
    """
    Summary-first, click-through-for-detail access control.

    Coaches see summary data by default.  Full conversation history
    requires explicit click-through with reason, subject to rate
    limiting and audit logging.

    Parameters
    ----------
    hourly_limit : int
        Maximum full-access views per hour before rate limiting (default 3).
    daily_limit : int
        Maximum full-access views per day before review (default 10).

    Usage
    -----
    ::

        gating = ProgressiveDataGating()

        # Default: get summary-level data
        response = await gating.get_gated_data(
            user_id="coach_123",
            resource_id="member_456_sessions",
            access_level=AccessLevel.SUMMARY,
        )

        # Explicit full-access request
        response = await gating.request_full_access(
            user_id="coach_123",
            resource_id="member_456_sessions",
            reason="Preparing for crisis intervention review",
        )
    """

    def __init__(
        self,
        *,
        hourly_limit: int = HOURLY_FULL_ACCESS_LIMIT,
        daily_limit: int = DAILY_FULL_ACCESS_LIMIT,
        db_pool: Any = None,
    ) -> None:
        self._hourly_limit = hourly_limit
        self._daily_limit = daily_limit
        self._db_pool = db_pool

        # User access tracking: user_id → UserAccessProfile
        self._user_profiles: Dict[str, UserAccessProfile] = {}

        # Audit log: chronological list of all full-access records
        self._audit_log: List[FullAccessAuditRecord] = []

        # Data providers: resource_type → callable that generates data at level
        self._data_providers: Dict[str, Any] = {}

        # Concurrency
        self._lock = asyncio.Lock()

        # Stats
        self._total_summary_requests: int = 0
        self._total_detailed_requests: int = 0
        self._total_full_requests: int = 0
        self._total_rate_limited: int = 0
        self._total_reviews_triggered: int = 0

        logger.info(
            "ProgressiveDataGating initialised — "
            "hourly_limit=%d, daily_limit=%d",
            self._hourly_limit,
            self._daily_limit,
        )

    # --------------------------------------------------------------------- #
    # GATED DATA ACCESS
    # --------------------------------------------------------------------- #

    async def get_gated_data(
        self,
        user_id: str,
        resource_id: str,
        access_level: AccessLevel = AccessLevel.SUMMARY,
    ) -> GatedDataResponse:
        """
        Return data at the appropriate detail level.

        For SUMMARY and DETAILED levels, access is granted immediately.
        For FULL level, use :meth:`request_full_access` instead (which
        requires a reason and is subject to rate limiting).

        Parameters
        ----------
        user_id : str
            The requesting user (typically a coach).
        resource_id : str
            The resource to access.
        access_level : AccessLevel
            Desired detail level (default SUMMARY).

        Returns
        -------
        GatedDataResponse
            Data at the requested level, or a rate-limit/denial message.
        """
        if access_level == AccessLevel.FULL:
            # Full access requires explicit request with reason
            return GatedDataResponse(
                resource_id=resource_id,
                access_level=AccessLevel.SUMMARY,
                data=await self._generate_summary_data(resource_id),
                gate_decision=GateDecisionResult.DENIED,
                message=(
                    "Full access requires explicit request with reason. "
                    "Use request_full_access() instead. "
                    "Returning summary data."
                ),
            )

        # Generate data at the requested level
        if access_level == AccessLevel.SUMMARY:
            data = await self._generate_summary_data(resource_id)
            async with self._lock:
                self._total_summary_requests += 1
        else:  # DETAILED
            data = await self._generate_detailed_data(resource_id)
            async with self._lock:
                self._total_detailed_requests += 1

        logger.debug(
            "Gated data served — user='%s', resource='%s', level=%s",
            user_id,
            resource_id,
            access_level.name,
        )

        return GatedDataResponse(
            resource_id=resource_id,
            access_level=access_level,
            data=data,
            gate_decision=GateDecisionResult.GRANTED,
            message=f"Data returned at {access_level.name} level.",
        )

    # --------------------------------------------------------------------- #
    # FULL ACCESS REQUEST
    # --------------------------------------------------------------------- #

    async def request_full_access(
        self,
        user_id: str,
        resource_id: str,
        reason: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> GatedDataResponse:
        """
        Request full-access data with audit logging and rate limiting.

        Creates an immutable audit record and checks rate limits before
        granting access.

        Parameters
        ----------
        user_id : str
            The requesting user.
        resource_id : str
            The resource to access at full detail.
        reason : str
            The stated reason for full access (required, cannot be empty).
        ip_address : str
            Requesting IP address (for audit record).
        user_agent : str
            Requesting user agent (for audit record).

        Returns
        -------
        GatedDataResponse
            Full data if granted, or denial/rate-limit response.
        """
        if not reason or not reason.strip():
            return GatedDataResponse(
                resource_id=resource_id,
                access_level=AccessLevel.SUMMARY,
                data=await self._generate_summary_data(resource_id),
                gate_decision=GateDecisionResult.DENIED,
                message="Full access requires a stated reason. Returning summary.",
            )

        # Check rate limits
        rate_check = await self._check_rate_limits(user_id)

        # Create audit record
        audit_record = FullAccessAuditRecord(
            user_id=user_id,
            resource_id=resource_id,
            reason=reason.strip(),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if rate_check == GateDecisionResult.RATE_LIMITED:
            audit_record.granted = False
            audit_record.denial_reason = (
                f"Rate limited: exceeded {self._hourly_limit} "
                f"full-access views in 1 hour."
            )
            async with self._lock:
                self._audit_log.append(audit_record)
                self._total_rate_limited += 1

            logger.warning(
                "Full access RATE LIMITED — user='%s', resource='%s'",
                user_id,
                resource_id,
            )

            return GatedDataResponse(
                resource_id=resource_id,
                access_level=AccessLevel.SUMMARY,
                data=await self._generate_summary_data(resource_id),
                gate_decision=GateDecisionResult.RATE_LIMITED,
                audit_id=audit_record.audit_id,
                message=(
                    f"Rate limited: you have exceeded {self._hourly_limit} "
                    f"full-history views in the past hour. "
                    f"Please try again later."
                ),
            )

        if rate_check == GateDecisionResult.REVIEW_REQUIRED:
            audit_record.granted = False
            audit_record.denial_reason = (
                f"Review required: exceeded {self._daily_limit} "
                f"full-access views in 1 day."
            )
            async with self._lock:
                self._audit_log.append(audit_record)
                self._total_reviews_triggered += 1

                # Flag user for review
                profile = self._get_or_create_profile(user_id)
                profile.is_under_review = True
                profile.review_triggered_at = datetime.utcnow()

            logger.warning(
                "Full access REVIEW REQUIRED — user='%s', resource='%s' — "
                "access paused pending review",
                user_id,
                resource_id,
            )

            return GatedDataResponse(
                resource_id=resource_id,
                access_level=AccessLevel.SUMMARY,
                data=await self._generate_summary_data(resource_id),
                gate_decision=GateDecisionResult.REVIEW_REQUIRED,
                audit_id=audit_record.audit_id,
                message=(
                    f"Access paused: you have exceeded {self._daily_limit} "
                    f"full-history views today. Access pending review."
                ),
            )

        # Access granted — record and serve full data
        audit_record.granted = True

        async with self._lock:
            self._audit_log.append(audit_record)
            self._total_full_requests += 1

            # Record the access timestamp
            profile = self._get_or_create_profile(user_id)
            profile.full_access_timestamps.append(time.monotonic())
            profile.total_full_access_count += 1

        # Generate full data
        data = await self._generate_full_data(resource_id)

        logger.info(
            "Full access GRANTED — user='%s', resource='%s', "
            "reason='%s', audit_id=%s",
            user_id,
            resource_id,
            reason[:50],
            audit_record.audit_id,
        )

        return GatedDataResponse(
            resource_id=resource_id,
            access_level=AccessLevel.FULL,
            data=data,
            gate_decision=GateDecisionResult.GRANTED,
            audit_id=audit_record.audit_id,
            message="Full access granted. This access has been logged.",
        )

    # --------------------------------------------------------------------- #
    # RATE LIMITING
    # --------------------------------------------------------------------- #

    async def _check_rate_limits(
        self,
        user_id: str,
    ) -> GateDecisionResult:
        """
        Check whether a user has exceeded rate limits.

        Parameters
        ----------
        user_id : str
            The user to check.

        Returns
        -------
        GateDecisionResult
            GRANTED if within limits, RATE_LIMITED or REVIEW_REQUIRED
            if limits exceeded.
        """
        async with self._lock:
            profile = self._get_or_create_profile(user_id)

            # Check if already under review
            if profile.is_under_review:
                return GateDecisionResult.REVIEW_REQUIRED

            now = time.monotonic()

            # Clean up expired timestamps (older than 24h)
            cutoff_24h = now - ONE_DAY_SECONDS
            profile.full_access_timestamps = [
                ts for ts in profile.full_access_timestamps
                if ts > cutoff_24h
            ]

            # Count accesses in the last hour
            cutoff_1h = now - ONE_HOUR_SECONDS
            hourly_count = sum(
                1 for ts in profile.full_access_timestamps
                if ts > cutoff_1h
            )

            # Count accesses in the last 24 hours
            daily_count = len(profile.full_access_timestamps)

            # Check daily limit first (more severe)
            if daily_count >= self._daily_limit:
                return GateDecisionResult.REVIEW_REQUIRED

            # Check hourly limit
            if hourly_count >= self._hourly_limit:
                profile.is_rate_limited = True
                return GateDecisionResult.RATE_LIMITED

            profile.is_rate_limited = False
            return GateDecisionResult.GRANTED

    def _get_or_create_profile(self, user_id: str) -> UserAccessProfile:
        """Get or create a user access profile (caller must hold lock)."""
        if user_id not in self._user_profiles:
            self._user_profiles[user_id] = UserAccessProfile(user_id=user_id)
        return self._user_profiles[user_id]

    # --------------------------------------------------------------------- #
    # DATA GENERATION — Queries real database when db_pool is available.
    # Falls back to availability metadata when the pool is unavailable.
    # --------------------------------------------------------------------- #

    async def _query_db(self, sql: str, *args) -> list:
        """Run a read-only query and return rows as dicts (or empty list)."""
        if not self._db_pool:
            return []
        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(sql, *args)
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("progressive_gating db query failed: %s", exc)
            return []

    async def _generate_summary_data(
        self,
        resource_id: str,
    ) -> Dict[str, Any]:
        """
        Generate summary-level data for a resource (member or session set).

        Queries the sessions and coherence tables for aggregate stats.
        """
        result: Dict[str, Any] = {
            "resource_id": resource_id,
            "level": "summary",
        }

        # Try to pull real aggregate data
        agg = await self._query_db(
            """
            SELECT
                COUNT(*)                       AS session_count,
                MAX(created_at)                AS last_session_date,
                AVG(coherence_score)           AS avg_coherence,
                BOOL_OR(risk_flag)             AS has_risk_flags
            FROM sessions
            WHERE member_id = $1
            """,
            resource_id,
        )
        if agg:
            row = agg[0]
            result["session_count"] = row.get("session_count", 0)
            result["last_session_date"] = str(row.get("last_session_date", ""))
            result["coherence_trend"] = round(float(row.get("avg_coherence") or 0), 3)
            result["risk_flags"] = bool(row.get("has_risk_flags"))
        else:
            result["session_count"] = "available"
            result["last_session_date"] = "available"
            result["coherence_trend"] = "available"
            result["risk_flags"] = "available"

        result["high_level_notes"] = "available"
        result["raw_conversations"] = "requires_full_access"
        result["detailed_notes"] = "requires_detailed_access"
        result["message"] = "Summary view. Click through for details."
        return result

    async def _generate_detailed_data(
        self,
        resource_id: str,
    ) -> Dict[str, Any]:
        """
        Generate detailed-level data for a resource.

        Includes per-session summaries and intervention history (no raw text).
        """
        summary = await self._generate_summary_data(resource_id)
        summary["level"] = "detailed"

        # Per-session summaries
        sessions = await self._query_db(
            """
            SELECT id, created_at, coherence_score, summary, interventions
            FROM sessions
            WHERE member_id = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            resource_id,
        )
        if sessions:
            summary["session_summaries"] = [
                {
                    "id": str(s.get("id", "")),
                    "date": str(s.get("created_at", "")),
                    "coherence": float(s.get("coherence_score") or 0),
                    "summary": s.get("summary", ""),
                }
                for s in sessions
            ]
            summary["intervention_history"] = [
                s.get("interventions", "")
                for s in sessions
                if s.get("interventions")
            ]
        else:
            summary["session_summaries"] = "available"
            summary["intervention_history"] = "available"

        summary["detailed_notes"] = "available"
        summary["raw_conversations"] = "requires_full_access"
        summary["message"] = "Detailed view. Full transcripts require explicit request."
        return summary

    async def _generate_full_data(
        self,
        resource_id: str,
    ) -> Dict[str, Any]:
        """
        Generate full-level data including raw conversation transcripts.

        This access level is rate-limited and audit-logged.
        """
        detailed = await self._generate_detailed_data(resource_id)
        detailed["level"] = "full"

        # Raw conversation data
        conversations = await self._query_db(
            """
            SELECT id, created_at, transcript, notes
            FROM sessions
            WHERE member_id = $1
            ORDER BY created_at DESC
            LIMIT 50
            """,
            resource_id,
        )
        if conversations:
            detailed["raw_conversations"] = [
                {
                    "id": str(c.get("id", "")),
                    "date": str(c.get("created_at", "")),
                    "transcript": c.get("transcript", ""),
                    "notes": c.get("notes", ""),
                }
                for c in conversations
            ]
            detailed["full_transcripts"] = "included_in_raw_conversations"
        else:
            detailed["raw_conversations"] = "available"
            detailed["full_transcripts"] = "available"

        detailed["verbatim_notes"] = "available"
        detailed["complete_history"] = "available"
        detailed["message"] = "Full access. This view has been logged for audit."
        return detailed

    # --------------------------------------------------------------------- #
    # AUDIT ACCESS
    # --------------------------------------------------------------------- #

    async def get_audit_log(
        self,
        user_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve audit records, optionally filtered by user.

        Parameters
        ----------
        user_id : str or None
            If provided, filter to this user's records.
        limit : int
            Maximum records to return (default 100).

        Returns
        -------
        list[dict]
            Audit records (most recent first).
        """
        async with self._lock:
            if user_id:
                records = [
                    r for r in self._audit_log
                    if r.user_id == user_id
                ]
            else:
                records = list(self._audit_log)

        return [r.to_dict() for r in records[-limit:]]

    async def get_user_profile(
        self,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return a user's access profile summary.

        Parameters
        ----------
        user_id : str
            The user to query.

        Returns
        -------
        dict or None
            Profile summary if found.
        """
        async with self._lock:
            profile = self._user_profiles.get(user_id)
            if profile is None:
                return None

            now = time.monotonic()
            hourly_count = sum(
                1 for ts in profile.full_access_timestamps
                if ts > now - ONE_HOUR_SECONDS
            )
            daily_count = sum(
                1 for ts in profile.full_access_timestamps
                if ts > now - ONE_DAY_SECONDS
            )

            return {
                "user_id": profile.user_id,
                "total_full_access_count": profile.total_full_access_count,
                "hourly_full_access_count": hourly_count,
                "daily_full_access_count": daily_count,
                "hourly_limit": self._hourly_limit,
                "daily_limit": self._daily_limit,
                "is_rate_limited": profile.is_rate_limited,
                "is_under_review": profile.is_under_review,
                "review_triggered_at": (
                    profile.review_triggered_at.isoformat()
                    if profile.review_triggered_at
                    else None
                ),
            }

    async def clear_review_flag(self, user_id: str) -> bool:
        """
        Clear the review flag for a user (admin action).

        Parameters
        ----------
        user_id : str
            The user whose review flag to clear.

        Returns
        -------
        bool
            True if a flag was cleared.
        """
        async with self._lock:
            profile = self._user_profiles.get(user_id)
            if profile and profile.is_under_review:
                profile.is_under_review = False
                profile.review_triggered_at = None
                profile.is_rate_limited = False
                logger.info(
                    "Review flag cleared for user '%s'", user_id
                )
                return True
            return False

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of gating engine state."""
        users_rate_limited = sum(
            1 for p in self._user_profiles.values()
            if p.is_rate_limited
        )
        users_under_review = sum(
            1 for p in self._user_profiles.values()
            if p.is_under_review
        )
        return {
            "total_summary_requests": self._total_summary_requests,
            "total_detailed_requests": self._total_detailed_requests,
            "total_full_requests": self._total_full_requests,
            "total_rate_limited": self._total_rate_limited,
            "total_reviews_triggered": self._total_reviews_triggered,
            "tracked_users": len(self._user_profiles),
            "users_rate_limited": users_rate_limited,
            "users_under_review": users_under_review,
            "audit_log_size": len(self._audit_log),
            "hourly_limit": self._hourly_limit,
            "daily_limit": self._daily_limit,
        }

    def __repr__(self) -> str:
        return (
            f"<ProgressiveDataGating "
            f"full_requests={self._total_full_requests} "
            f"rate_limited={self._total_rate_limited} "
            f"reviews={self._total_reviews_triggered}>"
        )
