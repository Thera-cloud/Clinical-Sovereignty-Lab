"""
SOVEREIGN SWARM — Transgenerational Pattern Recognition Engine
Analyzes cross-generational family session data to identify:
    - Emotional theme correlation across generations
    - Coping mechanism inheritance detection
    - Trigger pattern mapping
    - Coherence trajectory correlation

Theoretical Basis:
    - Multigenerational Transmission Process (Bowen, 1978) — patterns of emotional
      functioning transmitted across generations through the family emotional system.
    - Intergenerational Trauma (van der Kolk, 2014) — traumatic experiences propagate
      through attachment patterns and coping mechanisms.
    - Structural Family Therapy (Minuchin, 1974) — family structure, boundaries, and
      subsystems as determinants of individual functioning.
    - Epigenetic Inheritance (Yehuda et al., 2016) — biological mechanisms by which
      environmental exposures affect gene expression across generations.

    References:
        Bowen, M. (1978). Family Therapy in Clinical Practice. Jason Aronson.
        Minuchin, S. (1974). Families and Family Therapy. Harvard University Press.
        van der Kolk, B. (2014). The Body Keeps the Score. Viking.
        Yehuda, R. et al. (2016). Holocaust Exposure Induced Intergenerational Effects
            on FKBP5 Methylation. Biological Psychiatry, 80(5), 372-380.

Phase 4A — Code Guidelines Section VI.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.services.exceptions import LegacyVaultException, InsufficientDataException

logger = logging.getLogger(__name__)


class TransgenerationalPatternEngine:
    """
    Analyzes family session data across generations to detect inherited
    emotional patterns, coping mechanisms, and transformation opportunities.
    """

    # Minimum data thresholds (from centralized swarm config)
    from app.swarm_config import swarm_settings as _cfg
    MIN_SESSIONS_PER_MEMBER = _cfg.PATTERN_MIN_SESSIONS_PER_MEMBER
    MIN_FAMILY_MEMBERS = _cfg.PATTERN_MIN_FAMILY_MEMBERS
    MIN_GENERATIONS = 1  # ideally 2+ for true transgenerational analysis

    def __init__(self, db_pool):
        self.db_pool = db_pool

    # =========================================================================
    # EMOTIONAL THEME CORRELATION
    # =========================================================================

    async def analyze_emotional_themes(self, family_id) -> Dict[str, Any]:
        """
        NLP-based comparison of family members' session content across generations.
        Identifies shared emotional themes and unique member-specific themes.
        """
        members = await self._get_family_members(family_id)
        if len(members) < self.MIN_FAMILY_MEMBERS:
            raise InsufficientDataException(
                layer="transgenerational",
                required=self.MIN_FAMILY_MEMBERS,
                available=len(members),
            )

        member_themes: Dict[str, List[str]] = {}
        member_sessions: Dict[str, int] = {}

        async with self.db_pool.acquire() as conn:
            for member in members:
                uid = member["id"]

                # Get session themes from nate_insights
                # nate_insights has: insight_text, patterns (JSONB), strength, growth_area
                insights = await conn.fetch("""
                    SELECT strength, growth_area, patterns
                    FROM nate_insights
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 50
                """, uid)

                themes = []
                for i in insights:
                    if i["strength"]:
                        themes.append(i["strength"])
                    if i["growth_area"]:
                        themes.append(i["growth_area"])
                    # Also extract pattern labels from JSONB
                    pats = i["patterns"]
                    if isinstance(pats, str):
                        import json as _json
                        try:
                            pats = _json.loads(pats)
                        except (ValueError, TypeError):
                            pats = None
                    if isinstance(pats, list):
                        for p in pats:
                            if isinstance(p, str):
                                themes.append(p)
                            elif isinstance(p, dict) and p.get("label"):
                                themes.append(p["label"])

                # Also extract from session notes
                sessions = await conn.fetch("""
                    SELECT COUNT(*) as cnt FROM sessions WHERE user_id = $1
                """, uid)

                member_themes[uid] = themes
                member_sessions[uid] = sessions[0]["cnt"] if sessions else 0

        # Find shared themes
        all_themes = defaultdict(list)
        for uid, themes in member_themes.items():
            for theme in themes:
                all_themes[theme].append(uid)

        shared = {theme: uids for theme, uids in all_themes.items() if len(uids) >= 2}
        unique_by_member = {}
        for uid, themes in member_themes.items():
            unique = [t for t in set(themes) if len(all_themes.get(t, [])) == 1]
            unique_by_member[uid] = unique

        # Jaccard-like correlation coefficient (PhD Spec §4.1):
        # J(Family) = |⋂ themes shared by ≥2 members| / |⋃ all unique themes|
        union_themes = set()
        for themes in member_themes.values():
            union_themes.update(themes)
        intersection_count = len(shared)  # themes present in ≥2 members
        correlation = intersection_count / max(len(union_themes), 1)

        return {
            "family_id": family_id,
            "member_count": len(members),
            "shared_themes": {k: [str(u) for u in v] for k, v in shared.items()},
            "unique_by_member": {str(k): v for k, v in unique_by_member.items()},
            "theme_correlation": round(correlation, 4),
            "total_themes_analyzed": len(union_themes),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # COPING MECHANISM INHERITANCE
    # =========================================================================

    async def detect_coping_inheritance(self, family_id) -> Dict[str, Any]:
        """
        Map adaptive strategies across generations.
        Detect whether coping mechanisms are inherited, adapted, or novel.
        """
        members = await self._get_family_members(family_id)

        coping_data: Dict[str, List[str]] = {}

        async with self.db_pool.acquire() as conn:
            for member in members:
                uid = member["id"]

                # Extract coping-related insights from strength/growth_area
                insights = await conn.fetch("""
                    SELECT insight_text, strength, growth_area
                    FROM nate_insights
                    WHERE user_id = $1
                      AND (strength ILIKE '%coping%' OR strength ILIKE '%strategy%'
                           OR strength ILIKE '%mechanism%' OR strength ILIKE '%adaptation%'
                           OR growth_area ILIKE '%coping%' OR growth_area ILIKE '%strategy%'
                           OR growth_area ILIKE '%mechanism%' OR growth_area ILIKE '%adaptation%')
                    ORDER BY created_at DESC
                    LIMIT 20
                """, uid)

                mechanisms = [i["strength"] or i["growth_area"] or "unclassified" for i in insights]
                coping_data[uid] = mechanisms

        # Classify per PhD Spec §4.2:
        #   - Inherited: identical mechanism shared by ≥2 members
        #   - Adapted: partial keyword overlap with another member's mechanism (≥50% word overlap)
        #   - Novel: unique to one member, no significant overlap
        all_mechanisms = set()
        for mechs in coping_data.values():
            all_mechanisms.update(mechs)

        inherited = {}
        adapted = {}
        novel = {}

        for mech in all_mechanisms:
            holders = [uid for uid, mechs in coping_data.items() if mech in mechs]
            if len(holders) >= 2:
                # Inherited: exact match across members
                inherited[mech] = holders
            else:
                # Check for adapted: partial keyword overlap with other members' mechanisms
                mech_words = set(mech.lower().split())
                is_adapted = False
                adapted_with = []
                holder_uid = holders[0] if holders else None

                for other_uid, other_mechs in coping_data.items():
                    if other_uid == holder_uid:
                        continue
                    for other_mech in other_mechs:
                        other_words = set(other_mech.lower().split())
                        if mech_words and other_words:
                            overlap = len(mech_words & other_words) / max(
                                min(len(mech_words), len(other_words)), 1
                            )
                            if overlap >= 0.5:
                                is_adapted = True
                                adapted_with.append({"member": other_uid, "similar_to": other_mech})

                if is_adapted:
                    adapted[mech] = {
                        "holder": holder_uid,
                        "adapted_from": adapted_with,
                    }
                else:
                    novel[mech] = holder_uid

        total_classified = len(inherited) + len(adapted) + len(novel)

        return {
            "family_id": family_id,
            "members_analyzed": len(coping_data),
            "inherited_mechanisms": {k: [str(u) for u in v] for k, v in inherited.items()},
            "adapted_mechanisms": {
                k: {"holder": str(v["holder"]), "adapted_from": [
                    {"member": str(a["member"]), "similar_to": a["similar_to"]}
                    for a in v["adapted_from"]
                ]}
                for k, v in adapted.items()
            },
            "novel_mechanisms": {k: str(v) for k, v in novel.items()},
            "total_mechanisms": len(all_mechanisms),
            "classification_summary": {
                "inherited": len(inherited),
                "adapted": len(adapted),
                "novel": len(novel),
            },
            "inheritance_rate": round(len(inherited) / max(total_classified, 1), 4),
            "adaptation_rate": round(len(adapted) / max(total_classified, 1), 4),
            "novelty_rate": round(len(novel) / max(total_classified, 1), 4),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # TRIGGER PATTERN MAPPING
    # =========================================================================

    async def map_trigger_patterns(self, family_id) -> Dict[str, Any]:
        """
        Identify environmental/relational triggers that activate
        inherited patterns across family members.
        """
        members = await self._get_family_members(family_id)

        trigger_map: Dict[str, List[Dict]] = defaultdict(list)

        async with self.db_pool.acquire() as conn:
            for member in members:
                uid = member["id"]

                # Look for crisis/trigger indicators
                # voice_stress is inside JSONB biometrics, c_emo < 0.3 as proxy
                metrics = await conn.fetch("""
                    SELECT recorded_at, c_emo, cee_window, biometrics
                    FROM nevedal_metrics
                    WHERE user_id = $1
                      AND c_emo < 0.3
                    ORDER BY recorded_at DESC
                    LIMIT 20
                """, uid)

                for m in metrics:
                    # Extract voice stress from JSONB biometrics
                    bio = m["biometrics"] or {}
                    if isinstance(bio, str):
                        import json as _json
                        try:
                            bio = _json.loads(bio)
                        except (ValueError, TypeError):
                            bio = {}
                    voice_stress = None
                    for subject_key in ["subject_a", "subject_b"]:
                        subject = bio.get(subject_key, {})
                        if subject.get("voice_stress") is not None:
                            voice_stress = float(subject["voice_stress"])
                            break

                    trigger_map["stress_spike"].append({
                        "user_id": uid,
                        "name": member.get("name", "?"),
                        "c_emo": float(m["c_emo"]) if m["c_emo"] else None,
                        "stress": voice_stress,
                        "when": m["recorded_at"].isoformat() if m["recorded_at"] else None,
                    })

        # Analyze temporal correlation of triggers across members
        correlated_triggers = []
        events = trigger_map.get("stress_spike", [])
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                if events[i]["user_id"] != events[j]["user_id"]:
                    # Check if within 48 hours of each other
                    try:
                        t1 = datetime.fromisoformat(events[i]["when"])
                        t2 = datetime.fromisoformat(events[j]["when"])
                        if abs((t1 - t2).total_seconds()) < self._cfg.PATTERN_TRIGGER_CORRELATION_WINDOW:
                            correlated_triggers.append({
                                "member_a": events[i]["name"],
                                "member_b": events[j]["name"],
                                "time_diff_hours": round(abs((t1 - t2).total_seconds()) / 3600, 1),
                            })
                    except Exception as e:
                        logger.debug("Timestamp parse in trigger correlation: %s", e)

        return {
            "family_id": family_id,
            "trigger_events": len(events),
            "correlated_triggers": correlated_triggers[:20],
            "correlation_count": len(correlated_triggers),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # COHERENCE TRAJECTORY CORRELATION
    # =========================================================================

    async def correlate_trajectories(self, family_id) -> Dict[str, Any]:
        """
        Measure whether therapeutic progress in one family member
        correlates with changes in others.
        """
        members = await self._get_family_members(family_id)

        trajectories: Dict[str, List[float]] = {}

        async with self.db_pool.acquire() as conn:
            for member in members:
                uid = member["id"]
                rows = await conn.fetch("""
                    SELECT score, measured_at
                    FROM coherence_measurements
                    WHERE user_id = $1 AND layer = 'individual'
                    ORDER BY measured_at ASC
                """, uid)
                if len(rows) >= 3:
                    trajectories[uid] = [float(r["score"]) for r in rows]

        if len(trajectories) < 2:
            return {
                "family_id": family_id,
                "correlation_possible": False,
                "reason": f"Need 2+ members with trajectories, found {len(trajectories)}",
            }

        # Compute pairwise correlation
        member_ids = list(trajectories.keys())
        correlations = []

        for i in range(len(member_ids)):
            for j in range(i + 1, len(member_ids)):
                a = trajectories[member_ids[i]]
                b = trajectories[member_ids[j]]
                min_len = min(len(a), len(b))
                if min_len >= 3:
                    arr_a = np.array(a[:min_len])
                    arr_b = np.array(b[:min_len])
                    corr = float(np.corrcoef(arr_a, arr_b)[0, 1])
                    if not math.isnan(corr):
                        correlations.append({
                            "member_a": member_ids[i],
                            "member_b": member_ids[j],
                            "correlation": round(corr, 4),
                            "sample_size": min_len,
                        })

        avg_corr = float(np.mean([c["correlation"] for c in correlations])) if correlations else 0.0

        return {
            "family_id": family_id,
            "correlation_possible": True,
            "pairwise_correlations": correlations,
            "average_correlation": round(avg_corr, 4),
            "interpretation": (
                "Strong positive correlation — progress is shared"
                if avg_corr > 0.5 else
                "Moderate correlation — some shared progress"
                if avg_corr > 0.2 else
                "Weak/no correlation — individual trajectories"
            ),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # HOH DECISION PATTERN ANALYSIS
    # =========================================================================

    async def analyze_hoh_decision_patterns(self, family_id) -> Dict[str, Any]:
        """
        Analyze Head of Household approval/decline patterns for Family Sanctuary
        charges. Detects gatekeeping, financial stress, avoidance, and
        transgenerational decision-making patterns.

        Nate observes silently — this data is never exposed to family members.
        It enriches his therapeutic understanding across generations.
        """
        async with self.db_pool.acquire() as conn:
            resolved_fid = await conn.fetchval(
                "SELECT COALESCE("
                "  (SELECT family_id FROM users WHERE id = $1::uuid LIMIT 1),"
                "  $1::uuid"
                ")",
                family_id,
            )
            observations = await conn.fetch("""
                SELECT id, decision, decline_reason, decline_note,
                       nate_classification, charge_type, charge_amount, created_at
                FROM hoh_decision_observations
                WHERE family_id = $1
                ORDER BY created_at DESC
                LIMIT 200
            """, resolved_fid)

        if not observations:
            return {
                "family_id": str(family_id),
                "status": "no_data",
                "message": "No HoH decision observations recorded yet",
            }

        total = len(observations)
        declines = [o for o in observations if o["decision"] == "declined"]
        approvals = total - len(declines)
        approval_rate = approvals / max(total, 1)

        # Reason frequency
        reason_freq = {}
        for o in declines:
            r = o["decline_reason"] or "unknown"
            reason_freq[r] = reason_freq.get(r, 0) + 1

        # Signal dimension analysis
        signal_counts = {"financial": 0, "timing": 0, "control": 0, "relational": 0, "unknown": 0}
        for o in declines:
            cls = o["nate_classification"] or {}
            sig = cls.get("primary_signal", "unknown")
            signal_counts[sig] = signal_counts.get(sig, 0) + 1

        dominant_signal = max(signal_counts, key=signal_counts.get) if signal_counts else "unknown"

        # Control risk trend (last 30 days vs prior 60)
        now = datetime.utcnow()
        recent = [o for o in declines if o["created_at"] and
                  (now - o["created_at"].replace(tzinfo=None)).days <= 30]
        older = [o for o in declines if o["created_at"] and
                 30 < (now - o["created_at"].replace(tzinfo=None)).days <= 90]

        control_reasons = {"not_needed", "can_handle_ourselves", "too_much_help", "family_doing_fine"}
        recent_control = sum(1 for o in recent if o["decline_reason"] in control_reasons)
        older_control = sum(1 for o in older if o["decline_reason"] in control_reasons)

        control_trend = "stable"
        if len(recent) > 0 and len(older) > 0:
            recent_rate = recent_control / len(recent)
            older_rate = older_control / len(older)
            if recent_rate > older_rate + 0.15:
                control_trend = "increasing"
            elif recent_rate < older_rate - 0.15:
                control_trend = "decreasing"

        # Generational pattern check
        generational_flags = sum(
            1 for o in observations
            if (o["nate_classification"] or {}).get("generational_flag")
        )

        # Cross-reference with coping inheritance
        coping_correlation = None
        try:
            coping = await self.detect_coping_inheritance(family_id)
            inherited_count = coping.get("classification_summary", {}).get("inherited", 0)
            if inherited_count > 0 and generational_flags > 0:
                coping_correlation = {
                    "inherited_mechanisms": inherited_count,
                    "generational_decision_flags": generational_flags,
                    "interpretation": (
                        "HoH decision patterns mirror inherited coping mechanisms — "
                        "suggests deeply rooted family role dynamics"
                    ),
                }
        except Exception:
            pass

        return {
            "family_id": str(family_id),
            "total_observations": total,
            "approvals": approvals,
            "declines": len(declines),
            "approval_rate": round(approval_rate, 4),
            "decline_reason_frequency": reason_freq,
            "signal_distribution": signal_counts,
            "dominant_signal": dominant_signal,
            "control_trend": control_trend,
            "generational_flags": generational_flags,
            "coping_correlation": coping_correlation,
            "interpretation": (
                "High gatekeeping pattern — HoH frequently blocks therapeutic services"
                if signal_counts.get("control", 0) > total * 0.4 else
                "Financial stress pattern — declines correlate with budget concerns"
                if signal_counts.get("financial", 0) > total * 0.4 else
                "Mixed pattern — no single dominant decision driver"
            ),
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # FULL FAMILY ANALYSIS
    # =========================================================================

    async def full_analysis(self, family_id) -> Dict[str, Any]:
        """Run all transgenerational analyses for a family."""
        results = {"family_id": family_id}

        try:
            results["emotional_themes"] = await self.analyze_emotional_themes(family_id)
        except Exception as e:
            results["emotional_themes"] = {"error": str(e)}

        try:
            results["coping_inheritance"] = await self.detect_coping_inheritance(family_id)
        except Exception as e:
            results["coping_inheritance"] = {"error": str(e)}

        try:
            results["trigger_patterns"] = await self.map_trigger_patterns(family_id)
        except Exception as e:
            results["trigger_patterns"] = {"error": str(e)}

        try:
            results["coherence_trajectories"] = await self.correlate_trajectories(family_id)
        except Exception as e:
            results["coherence_trajectories"] = {"error": str(e)}

        try:
            results["hoh_decision_patterns"] = await self.analyze_hoh_decision_patterns(family_id)
        except Exception as e:
            results["hoh_decision_patterns"] = {"error": str(e)}

        results["analyzed_at"] = datetime.utcnow().isoformat()
        return results

    # =========================================================================
    # SWARM INTELLIGENCE — Family Correlation Detection
    # =========================================================================

    async def detect_family_correlations(
        self, family_id, days: int = 84
    ) -> Dict[str, Any]:
        """
        Cross-reference family member C_emo trends to detect correlations.
        Returns a correlation matrix showing which members' emotional states
        track together, plus identified co-occurring patterns.

        Documented in SOVEREIGN_COMMAND_README.md (SC_07 Swarm Intelligence).
        """
        members = await self._get_family_members(family_id)
        if len(members) < 2:
            return {
                "family_id": str(family_id),
                "status": "insufficient_members",
                "message": "At least 2 family members needed for correlation analysis",
            }

        # Gather C_emo time-series per member
        member_series: Dict[str, List[float]] = {}
        member_names: Dict[str, str] = {}

        async with self.db_pool.acquire() as conn:
            for member in members:
                uid = member["id"]
                member_names[str(uid)] = member.get("name") or "Unknown"
                rows = await conn.fetch(
                    """SELECT c_emo, recorded_at FROM nevedal_metrics
                       WHERE user_id = $1
                         AND recorded_at > NOW() - ($2 || ' days')::interval
                       ORDER BY recorded_at""",
                    uid, str(days),
                )
                member_series[str(uid)] = [float(r["c_emo"] or 0) for r in rows]

        # Build pairwise correlation matrix
        ids = list(member_series.keys())
        correlations = {}
        co_patterns = []

        for i, id_a in enumerate(ids):
            for id_b in ids[i + 1:]:
                series_a = member_series[id_a]
                series_b = member_series[id_b]

                # Compute Pearson correlation (simplified — length-aligned)
                min_len = min(len(series_a), len(series_b))
                if min_len < 3:
                    corr = 0.0
                else:
                    a = series_a[:min_len]
                    b = series_b[:min_len]
                    mean_a = sum(a) / min_len
                    mean_b = sum(b) / min_len
                    num = sum((a[j] - mean_a) * (b[j] - mean_b) for j in range(min_len))
                    den_a = sum((a[j] - mean_a) ** 2 for j in range(min_len)) ** 0.5
                    den_b = sum((b[j] - mean_b) ** 2 for j in range(min_len)) ** 0.5
                    corr = num / (den_a * den_b) if den_a * den_b > 0 else 0.0

                pair_key = f"{member_names[id_a]} <-> {member_names[id_b]}"
                correlations[pair_key] = round(corr, 4)

                # Detect co-occurring patterns
                if corr > 0.7:
                    co_patterns.append({
                        "members": [member_names[id_a], member_names[id_b]],
                        "correlation": round(corr, 4),
                        "pattern": "strong_positive",
                        "interpretation": (
                            f"{member_names[id_a]} and {member_names[id_b]} show strongly "
                            f"correlated emotional states — their C_emo values rise and fall "
                            f"together (r={round(corr, 2)})."
                        ),
                    })
                elif corr < -0.5:
                    co_patterns.append({
                        "members": [member_names[id_a], member_names[id_b]],
                        "correlation": round(corr, 4),
                        "pattern": "inverse",
                        "interpretation": (
                            f"{member_names[id_a]} and {member_names[id_b]} show inverse "
                            f"emotional patterns — when one improves, the other declines "
                            f"(r={round(corr, 2)}). This may indicate an enmeshed dynamic."
                        ),
                    })

        # Compute family coherence index
        corr_values = list(correlations.values())
        family_coherence = sum(corr_values) / len(corr_values) if corr_values else 0

        return {
            "family_id": str(family_id),
            "period_days": days,
            "member_count": len(members),
            "correlation_matrix": correlations,
            "co_occurring_patterns": co_patterns,
            "family_coherence_index": round(family_coherence, 4),
            "members": {
                str(m["id"]): {
                    "name": m.get("name"),
                    "data_points": len(member_series.get(str(m["id"]), [])),
                }
                for m in members
            },
            "analyzed_at": datetime.utcnow().isoformat(),
        }

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _get_family_members(self, family_id) -> List[Dict]:
        """Get all members of a family."""
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, role, family_id
                FROM users
                WHERE family_id = $1
                ORDER BY id
            """, family_id)
            return [dict(r) for r in rows]
