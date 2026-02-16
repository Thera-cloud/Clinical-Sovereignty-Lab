"""
HIVE DEFENSE PROTOCOL — Auto-Triage (Phase 8C, Third Cord)
Algorithmic threat prioritization during multi-vector siege.

During a coordinated attack, multiple threat vectors activate
simultaneously.  Human decision-making is too slow and error-prone
under pressure.  AutoTriage automatically ranks threats by damage
potential and allocates defensive resources according to absolute
priority rules:

Priority Hierarchy (Immutable)
------------------------------
1. **SAFETY-CRITICAL** — Member crisis paths, coach escalation,
   suicide/self-harm detection, emergency contacts.  These receive
   ABSOLUTE priority and are NEVER degraded.
2. **THERAPEUTIC** — Active session data, therapeutic notes,
   coherence measurements, session memory.  Second priority.
3. **OPERATIONAL** — Authentication, billing, coach scheduling,
   notification delivery.  Third priority.
4. **ANALYTICS** — Usage metrics, marketing data, engagement tracking,
   A/B test results.  Can degrade.
5. **NON-CRITICAL** — Feature flags, preference syncing, non-essential
   background jobs.  Can be fully suspended.

The triage engine is fully algorithmic — no human decision-making is
required during an active attack.

Event: ``hive.triage.activated``

Patent-Pending — Claim 53
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID, uuid4

from app.models.hive_defense import DefconLevel

logger = logging.getLogger("hive.auto_triage")


# =============================================================================
# PRIORITY LEVELS
# =============================================================================

class ThreatPriority(IntEnum):
    """
    Threat priority levels.  Lower number = higher priority.

    These are ABSOLUTE — safety-critical paths always come first.
    """
    SAFETY_CRITICAL = 1
    THERAPEUTIC = 2
    OPERATIONAL = 3
    ANALYTICS = 4
    NON_CRITICAL = 5


class ThreatCategory(str, Enum):
    """Categories of threats that can be triaged."""
    DATA_EXFILTRATION = "data_exfiltration"
    CREDENTIAL_STUFFING = "credential_stuffing"
    DDOS = "ddos"
    API_ABUSE = "api_abuse"
    SESSION_HIJACK = "session_hijack"
    INJECTION_ATTACK = "injection_attack"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    MIRROR_ESCAPE = "mirror_escape"
    INSIDER_THREAT = "insider_threat"
    SUPPLY_CHAIN = "supply_chain"
    SOCIAL_ENGINEERING = "social_engineering"
    CRYPTOGRAPHIC_ATTACK = "cryptographic_attack"


class ResourceState(str, Enum):
    """Current state of a defensive resource."""
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"


# =============================================================================
# PATH CLASSIFICATION — which system paths belong to which priority
# =============================================================================

# Safety-critical paths — NEVER degrade
SAFETY_CRITICAL_PATHS: Set[str] = {
    "crisis_detection",
    "suicide_prevention",
    "self_harm_alert",
    "emergency_contact",
    "coach_escalation",
    "mandatory_reporting",
    "crisis_session",
    "safety_plan_access",
    "911_integration",
    "crisis_center",
}

# Therapeutic data paths — second priority
THERAPEUTIC_PATHS: Set[str] = {
    "active_session",
    "session_memory",
    "therapeutic_notes",
    "coherence_measurement",
    "voice_biometrics",
    "nevedal_engine",
    "session_recording",
    "treatment_plan",
    "progress_tracking",
    "coach_session_tools",
}

# Operational paths — third priority
OPERATIONAL_PATHS: Set[str] = {
    "authentication",
    "authorization",
    "billing",
    "scheduling",
    "notifications",
    "coach_matching",
    "user_management",
    "payment_processing",
    "subscription_management",
    "email_delivery",
}

# Analytics paths — can degrade
ANALYTICS_PATHS: Set[str] = {
    "usage_metrics",
    "engagement_tracking",
    "marketing_analytics",
    "conversion_tracking",
    "ab_testing",
    "cohort_analysis",
    "revenue_reporting",
    "user_segmentation",
}

# Non-critical paths — can be fully suspended
NON_CRITICAL_PATHS: Set[str] = {
    "feature_flags",
    "preference_sync",
    "background_jobs",
    "cache_warming",
    "search_indexing",
    "recommendation_engine",
    "social_features",
    "gamification",
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ActiveThreat:
    """
    A single active threat vector during a siege.

    Attributes
    ----------
    threat_id : UUID
        Unique identifier for this threat.
    category : ThreatCategory
        Classification of the threat.
    severity : float
        Severity score in [0.0, 1.0] (1.0 = maximum damage potential).
    affected_paths : set[str]
        System paths affected by this threat.
    source_indicators : list[str]
        Observable indicators of this threat (IPs, patterns, etc.).
    detected_at : datetime
        When the threat was first detected.
    is_active : bool
        Whether the threat is currently active.
    damage_potential : float
        Estimated damage potential if unmitigated.
    """
    threat_id: UUID = field(default_factory=uuid4)
    category: ThreatCategory = ThreatCategory.API_ABUSE
    severity: float = 0.5
    affected_paths: Set[str] = field(default_factory=set)
    source_indicators: List[str] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    damage_potential: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        """Serialize threat for reporting."""
        return {
            "threat_id": str(self.threat_id),
            "category": self.category.value,
            "severity": self.severity,
            "affected_paths": list(self.affected_paths),
            "source_indicators": self.source_indicators,
            "detected_at": self.detected_at.isoformat(),
            "is_active": self.is_active,
            "damage_potential": self.damage_potential,
        }


@dataclass
class PrioritizedThreat:
    """
    A threat that has been ranked by the triage algorithm.

    Attributes
    ----------
    threat : ActiveThreat
        The underlying threat.
    priority : ThreatPriority
        Assigned priority level.
    triage_score : float
        Composite triage score (lower = higher priority).
    highest_affected_priority : ThreatPriority
        The highest-priority path affected by this threat.
    mitigation_urgency : str
        Human-readable urgency label.
    """
    threat: ActiveThreat = field(default_factory=ActiveThreat)
    priority: ThreatPriority = ThreatPriority.NON_CRITICAL
    triage_score: float = 100.0
    highest_affected_priority: ThreatPriority = ThreatPriority.NON_CRITICAL
    mitigation_urgency: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for reporting."""
        return {
            "threat_id": str(self.threat.threat_id),
            "category": self.threat.category.value,
            "priority": self.priority.value,
            "priority_label": self.priority.name,
            "triage_score": round(self.triage_score, 4),
            "highest_affected_priority": self.highest_affected_priority.name,
            "mitigation_urgency": self.mitigation_urgency,
            "severity": self.threat.severity,
            "damage_potential": self.threat.damage_potential,
        }


@dataclass
class ResourceAllocation:
    """
    Resource allocation plan produced by triage.

    Attributes
    ----------
    allocation_id : UUID
        Unique identifier for this allocation plan.
    defcon_level : DefconLevel
        Current DEFCON level at time of allocation.
    allocations : dict[str, dict]
        Path → allocation details (priority, state, resources_pct).
    suspended_paths : list[str]
        Paths that have been fully suspended.
    degraded_paths : list[str]
        Paths that have been degraded.
    protected_paths : list[str]
        Paths receiving full resource allocation.
    total_threats : int
        Number of threats being managed.
    created_at : datetime
        When this allocation was computed.
    """
    allocation_id: UUID = field(default_factory=uuid4)
    defcon_level: DefconLevel = DefconLevel.PEACE
    allocations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    suspended_paths: List[str] = field(default_factory=list)
    degraded_paths: List[str] = field(default_factory=list)
    protected_paths: List[str] = field(default_factory=list)
    total_threats: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


# =============================================================================
# AUTO TRIAGE ENGINE
# =============================================================================

class AutoTriage:
    """
    Algorithmic threat prioritization engine for multi-vector siege.

    Automatically ranks threats by damage potential and allocates
    resources according to the immutable priority hierarchy.  No human
    decision-making required during active attack.

    Usage
    -----
    ::

        triage = AutoTriage()

        # Rank threats
        prioritized = await triage.triage_threats(active_threats)

        # Allocate resources based on priorities
        allocation = await triage.allocate_resources(prioritized)
    """

    def __init__(self) -> None:
        # Path priority classification cache
        self._path_priority_map: Dict[str, ThreatPriority] = {}
        self._build_path_priority_map()

        # Triage history
        self._triage_history: List[Dict[str, Any]] = []

        # Active allocation
        self._current_allocation: Optional[ResourceAllocation] = None

        # Concurrency
        self._lock = asyncio.Lock()

        # Stats
        self._total_triages: int = 0
        self._total_allocations: int = 0

        logger.info(
            "AutoTriage initialised — %d path classifications loaded",
            len(self._path_priority_map),
        )

    def _build_path_priority_map(self) -> None:
        """Build the path → priority lookup from the defined path sets."""
        for path in SAFETY_CRITICAL_PATHS:
            self._path_priority_map[path] = ThreatPriority.SAFETY_CRITICAL
        for path in THERAPEUTIC_PATHS:
            self._path_priority_map[path] = ThreatPriority.THERAPEUTIC
        for path in OPERATIONAL_PATHS:
            self._path_priority_map[path] = ThreatPriority.OPERATIONAL
        for path in ANALYTICS_PATHS:
            self._path_priority_map[path] = ThreatPriority.ANALYTICS
        for path in NON_CRITICAL_PATHS:
            self._path_priority_map[path] = ThreatPriority.NON_CRITICAL

    # --------------------------------------------------------------------- #
    # THREAT TRIAGE
    # --------------------------------------------------------------------- #

    async def triage_threats(
        self,
        active_threats: List[ActiveThreat],
    ) -> List[PrioritizedThreat]:
        """
        Rank active threats by damage potential and priority.

        The algorithm considers:
        1. Which priority paths are affected (higher path priority =
           higher threat priority).
        2. Threat severity score.
        3. Damage potential.
        4. Number of affected paths.

        The resulting list is sorted by triage score (ascending = highest
        priority first).

        Parameters
        ----------
        active_threats : list[ActiveThreat]
            Currently active threat vectors.

        Returns
        -------
        list[PrioritizedThreat]
            Threats ranked by priority (most urgent first).
        """
        prioritized: List[PrioritizedThreat] = []

        for threat in active_threats:
            if not threat.is_active:
                continue

            # Determine highest-priority path affected
            highest_priority = ThreatPriority.NON_CRITICAL
            for path in threat.affected_paths:
                path_priority = self._path_priority_map.get(
                    path, ThreatPriority.NON_CRITICAL
                )
                if path_priority < highest_priority:
                    highest_priority = path_priority

            # Compute composite triage score
            # Lower score = higher priority
            triage_score = self._compute_triage_score(
                highest_priority=highest_priority,
                severity=threat.severity,
                damage_potential=threat.damage_potential,
                affected_path_count=len(threat.affected_paths),
            )

            # Determine urgency label
            urgency = self._classify_urgency(triage_score, highest_priority)

            pt = PrioritizedThreat(
                threat=threat,
                priority=highest_priority,
                triage_score=triage_score,
                highest_affected_priority=highest_priority,
                mitigation_urgency=urgency,
            )
            prioritized.append(pt)

        # Sort by triage score (ascending = most urgent first)
        prioritized.sort(key=lambda p: p.triage_score)

        async with self._lock:
            self._total_triages += 1
            self._triage_history.append({
                "event": "hive.triage.activated",
                "threat_count": len(prioritized),
                "safety_critical_threats": sum(
                    1 for p in prioritized
                    if p.priority == ThreatPriority.SAFETY_CRITICAL
                ),
                "timestamp": datetime.utcnow().isoformat(),
            })

        logger.info(
            "Triage complete — %d active threats ranked. "
            "Safety-critical: %d, Therapeutic: %d, Operational: %d, "
            "Analytics: %d, Non-critical: %d",
            len(prioritized),
            sum(1 for p in prioritized if p.priority == ThreatPriority.SAFETY_CRITICAL),
            sum(1 for p in prioritized if p.priority == ThreatPriority.THERAPEUTIC),
            sum(1 for p in prioritized if p.priority == ThreatPriority.OPERATIONAL),
            sum(1 for p in prioritized if p.priority == ThreatPriority.ANALYTICS),
            sum(1 for p in prioritized if p.priority == ThreatPriority.NON_CRITICAL),
        )

        return prioritized

    @staticmethod
    def _compute_triage_score(
        highest_priority: ThreatPriority,
        severity: float,
        damage_potential: float,
        affected_path_count: int,
    ) -> float:
        """
        Compute a composite triage score.

        The score is a weighted combination where:
        * Priority level is the dominant factor (weight 60%)
        * Severity contributes 20%
        * Damage potential contributes 15%
        * Path count contributes 5%

        Lower score = higher priority.

        Parameters
        ----------
        highest_priority : ThreatPriority
            Highest priority path affected.
        severity : float
            Threat severity in [0, 1].
        damage_potential : float
            Damage potential in [0, 1].
        affected_path_count : int
            Number of affected paths.

        Returns
        -------
        float
            Composite triage score.
        """
        # Priority component: 1-5 scaled to 0-1 (inverted: 1=highest → 0.0)
        priority_score = (highest_priority.value - 1) / 4.0

        # Severity component: inverted (high severity → low score)
        severity_score = 1.0 - min(1.0, max(0.0, severity))

        # Damage potential component: inverted
        damage_score = 1.0 - min(1.0, max(0.0, damage_potential))

        # Path count component: more paths → lower score (more urgent)
        path_score = max(0.0, 1.0 - (min(affected_path_count, 10) / 10.0))

        # Weighted combination
        return (
            0.60 * priority_score
            + 0.20 * severity_score
            + 0.15 * damage_score
            + 0.05 * path_score
        )

    @staticmethod
    def _classify_urgency(
        triage_score: float,
        priority: ThreatPriority,
    ) -> str:
        """
        Classify urgency from triage score and priority.

        Parameters
        ----------
        triage_score : float
            Composite triage score.
        priority : ThreatPriority
            Threat priority level.

        Returns
        -------
        str
            Urgency label: "immediate", "high", "medium", "low", "deferred".
        """
        if priority == ThreatPriority.SAFETY_CRITICAL:
            return "immediate"
        if triage_score < 0.2:
            return "immediate"
        if triage_score < 0.4:
            return "high"
        if triage_score < 0.6:
            return "medium"
        if triage_score < 0.8:
            return "low"
        return "deferred"

    # --------------------------------------------------------------------- #
    # RESOURCE ALLOCATION
    # --------------------------------------------------------------------- #

    async def allocate_resources(
        self,
        priorities: List[PrioritizedThreat],
        defcon_level: DefconLevel = DefconLevel.SUBSTANTIAL,
    ) -> ResourceAllocation:
        """
        Produce a resource allocation plan based on triaged threats.

        Resources are allocated according to the immutable priority
        hierarchy:
        * Safety-critical paths: 100% resources, never degraded
        * Therapeutic paths: high allocation, degraded only at DEFCON 1
        * Operational paths: moderate allocation, can be degraded
        * Analytics paths: minimal allocation, can be suspended
        * Non-critical paths: suspended during active siege

        Parameters
        ----------
        priorities : list[PrioritizedThreat]
            Triaged threat list (from :meth:`triage_threats`).
        defcon_level : DefconLevel
            Current defense condition level.

        Returns
        -------
        ResourceAllocation
            The computed resource allocation plan.
        """
        allocation = ResourceAllocation(
            defcon_level=defcon_level,
            total_threats=len(priorities),
        )

        # Collect all affected paths across all threats
        all_affected_paths: Set[str] = set()
        for pt in priorities:
            all_affected_paths.update(pt.threat.affected_paths)

        # Determine allocation per path priority level
        resource_budget = self._get_resource_budget(defcon_level)

        # Allocate safety-critical paths
        for path in SAFETY_CRITICAL_PATHS:
            allocation.allocations[path] = {
                "priority": ThreatPriority.SAFETY_CRITICAL.name,
                "state": ResourceState.ALLOCATED.value,
                "resources_pct": 100,
                "degradation": "never",
            }
            allocation.protected_paths.append(path)

        # Allocate therapeutic paths
        therapeutic_pct = resource_budget["therapeutic"]
        for path in THERAPEUTIC_PATHS:
            state = ResourceState.ALLOCATED if therapeutic_pct >= 80 else ResourceState.DEGRADED
            allocation.allocations[path] = {
                "priority": ThreatPriority.THERAPEUTIC.name,
                "state": state.value,
                "resources_pct": therapeutic_pct,
                "degradation": "only_at_defcon_1",
            }
            if state == ResourceState.DEGRADED:
                allocation.degraded_paths.append(path)
            else:
                allocation.protected_paths.append(path)

        # Allocate operational paths
        operational_pct = resource_budget["operational"]
        for path in OPERATIONAL_PATHS:
            if operational_pct <= 20:
                state = ResourceState.DEGRADED
            else:
                state = ResourceState.ALLOCATED
            allocation.allocations[path] = {
                "priority": ThreatPriority.OPERATIONAL.name,
                "state": state.value,
                "resources_pct": operational_pct,
                "degradation": "under_siege",
            }
            if state == ResourceState.DEGRADED:
                allocation.degraded_paths.append(path)

        # Allocate analytics paths
        analytics_pct = resource_budget["analytics"]
        for path in ANALYTICS_PATHS:
            if analytics_pct <= 0:
                state = ResourceState.SUSPENDED
                allocation.suspended_paths.append(path)
            elif analytics_pct <= 30:
                state = ResourceState.DEGRADED
                allocation.degraded_paths.append(path)
            else:
                state = ResourceState.ALLOCATED
            allocation.allocations[path] = {
                "priority": ThreatPriority.ANALYTICS.name,
                "state": state.value,
                "resources_pct": analytics_pct,
                "degradation": "can_degrade",
            }

        # Allocate non-critical paths
        non_critical_pct = resource_budget["non_critical"]
        for path in NON_CRITICAL_PATHS:
            if non_critical_pct <= 0:
                state = ResourceState.SUSPENDED
                allocation.suspended_paths.append(path)
            else:
                state = ResourceState.DEGRADED
                allocation.degraded_paths.append(path)
            allocation.allocations[path] = {
                "priority": ThreatPriority.NON_CRITICAL.name,
                "state": state.value,
                "resources_pct": non_critical_pct,
                "degradation": "can_suspend",
            }

        async with self._lock:
            self._current_allocation = allocation
            self._total_allocations += 1

        logger.info(
            "Resource allocation at DEFCON %d — "
            "protected: %d, degraded: %d, suspended: %d",
            defcon_level.value,
            len(allocation.protected_paths),
            len(allocation.degraded_paths),
            len(allocation.suspended_paths),
        )

        return allocation

    @staticmethod
    def _get_resource_budget(
        defcon_level: DefconLevel,
    ) -> Dict[str, int]:
        """
        Determine resource budget percentages per priority level
        based on current DEFCON.

        Safety-critical ALWAYS gets 100%.  Other levels scale down
        as DEFCON escalates.

        Parameters
        ----------
        defcon_level : DefconLevel
            Current defense condition.

        Returns
        -------
        dict[str, int]
            Priority level → resource percentage.
        """
        budgets = {
            DefconLevel.PEACE: {
                "therapeutic": 100,
                "operational": 100,
                "analytics": 100,
                "non_critical": 100,
            },
            DefconLevel.ELEVATED: {
                "therapeutic": 100,
                "operational": 90,
                "analytics": 70,
                "non_critical": 50,
            },
            DefconLevel.SUBSTANTIAL: {
                "therapeutic": 100,
                "operational": 75,
                "analytics": 30,
                "non_critical": 0,
            },
            DefconLevel.SEVERE: {
                "therapeutic": 90,
                "operational": 50,
                "analytics": 0,
                "non_critical": 0,
            },
            DefconLevel.CRITICAL: {
                "therapeutic": 70,
                "operational": 30,
                "analytics": 0,
                "non_critical": 0,
            },
        }
        return budgets.get(defcon_level, budgets[DefconLevel.SUBSTANTIAL])

    # --------------------------------------------------------------------- #
    # PATH CLASSIFICATION
    # --------------------------------------------------------------------- #

    def classify_path(self, path_name: str) -> ThreatPriority:
        """
        Classify a system path into its priority level.

        Parameters
        ----------
        path_name : str
            The system path name.

        Returns
        -------
        ThreatPriority
            The priority classification for this path.
        """
        return self._path_priority_map.get(
            path_name, ThreatPriority.NON_CRITICAL
        )

    def is_safety_critical(self, path_name: str) -> bool:
        """Check if a path is safety-critical (never degrade)."""
        return path_name in SAFETY_CRITICAL_PATHS

    # --------------------------------------------------------------------- #
    # STATE ACCESS
    # --------------------------------------------------------------------- #

    async def get_current_allocation(self) -> Optional[ResourceAllocation]:
        """Return the current resource allocation plan."""
        async with self._lock:
            return self._current_allocation

    async def get_triage_history(
        self,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent triage events."""
        return self._triage_history[-limit:]

    # --------------------------------------------------------------------- #
    # DIAGNOSTICS
    # --------------------------------------------------------------------- #

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic summary of triage engine state."""
        return {
            "total_triages": self._total_triages,
            "total_allocations": self._total_allocations,
            "path_classifications": len(self._path_priority_map),
            "safety_critical_paths": len(SAFETY_CRITICAL_PATHS),
            "therapeutic_paths": len(THERAPEUTIC_PATHS),
            "operational_paths": len(OPERATIONAL_PATHS),
            "analytics_paths": len(ANALYTICS_PATHS),
            "non_critical_paths": len(NON_CRITICAL_PATHS),
            "current_allocation_active": self._current_allocation is not None,
        }

    def __repr__(self) -> str:
        return (
            f"<AutoTriage triages={self._total_triages} "
            f"allocations={self._total_allocations} "
            f"paths={len(self._path_priority_map)}>"
        )
