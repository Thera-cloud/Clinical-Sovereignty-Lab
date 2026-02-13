"""
SOVEREIGN SWARM — Transgenerational Pattern Recognition Engine
Analyzes cross-generational family session data to identify:
    - Emotional theme correlation across generations
    - Coping mechanism inheritance detection
    - Trigger pattern mapping
    - Coherence trajectory correlation

Phase 4A — Code Guidelines Section VI.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.services.exceptions import LegacyVaultException, InsufficientDataException


class TransgenerationalPatternEngine:
    """
    Analyzes family session data across generations to detect inherited
    emotional patterns, coping mechanisms, and transformation opportunities.
    """

    # Minimum data thresholds
    MIN_SESSIONS_PER_MEMBER = 3
    MIN_FAMILY_MEMBERS = 2
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
                        pats = _json.loads(pats)
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

        # Correlation score: how much themes overlap across family
        total_themes = sum(len(t) for t in member_themes.values())
        shared_count = sum(len(uids) for uids in shared.values())
        correlation = shared_count / max(total_themes, 1)

        return {
            "family_id": family_id,
            "member_count": len(members),
            "shared_themes": {k: [str(u) for u in v] for k, v in shared.items()},
            "unique_by_member": {str(k): v for k, v in unique_by_member.items()},
            "theme_correlation": round(correlation, 4),
            "total_themes_analyzed": total_themes,
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

        # Classify: inherited (shared with parent), adapted (similar), novel (unique)
        all_mechanisms = set()
        for mechs in coping_data.values():
            all_mechanisms.update(mechs)

        shared_across = {}
        for mech in all_mechanisms:
            holders = [uid for uid, mechs in coping_data.items() if mech in mechs]
            if len(holders) >= 2:
                shared_across[mech] = holders

        return {
            "family_id": family_id,
            "members_analyzed": len(coping_data),
            "inherited_mechanisms": {k: [str(u) for u in v] for k, v in shared_across.items()},
            "total_mechanisms": len(all_mechanisms),
            "inheritance_rate": round(len(shared_across) / max(len(all_mechanisms), 1), 4),
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
                        bio = _json.loads(bio)
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
                        if abs((t1 - t2).total_seconds()) < 172800:  # 48 hours
                            correlated_triggers.append({
                                "member_a": events[i]["name"],
                                "member_b": events[j]["name"],
                                "time_diff_hours": round(abs((t1 - t2).total_seconds()) / 3600, 1),
                            })
                    except Exception:
                        pass

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

        results["analyzed_at"] = datetime.utcnow().isoformat()
        return results

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
