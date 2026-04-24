"""
Longitudinal Pattern Detector — compare multi-modal session analyses
across time to surface recurring patterns (shame cycles, attachment
patterns, volatility trends) and transgenerational matches across
family members.

Reads `coaching_sessions.session_data->>'multimodal_fusion'` written by
the classroom analyzer pipeline. All output is therapeutic context only
and must be combined with the coach's clinical judgment.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_jsonb(value: Any) -> Dict[str, Any]:
    """Normalize asyncpg jsonb output (str | dict) to dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


class LongitudinalPatternDetector:
    """
    Compare multi-modal analysis across sessions to detect recurring
    patterns, cycles, and transgenerational markers.
    """

    def __init__(self, db_pool: Any) -> None:
        self.db = db_pool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def detect_patterns(
        self,
        client_id: str,
        current_session: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Compare current session's multi-modal analysis against previous
        sessions for this client.
        """
        previous = await self._load_previous_analyses(client_id, limit=10)

        if not previous and not current_session:
            return {
                "patterns": [],
                "sessions_analyzed": 0,
                "trend_direction": "insufficient_data",
                "note": "no session history",
            }

        # Need at least 2 prior sessions to detect a longitudinal trend.
        if len(previous) < 2:
            return {
                "patterns": [],
                "sessions_analyzed": len(previous) + (1 if current_session else 0),
                "trend_direction": "insufficient_data",
                "note": "insufficient session history",
            }

        patterns: List[Dict[str, Any]] = []

        shame = self._detect_shame_cycle(previous, current_session)
        if shame:
            patterns.append(shame)

        attachment = self._detect_attachment_pattern(previous, current_session)
        if attachment:
            patterns.append(attachment)

        volatility = self._detect_volatility_trend(previous, current_session)
        if volatility:
            patterns.append(volatility)

        triggers = self._detect_topic_triggers(previous, current_session)
        if triggers:
            patterns.extend(triggers)

        return {
            "patterns": patterns,
            "sessions_analyzed": len(previous) + (1 if current_session else 0),
            "trend_direction": self._compute_trend(previous, current_session),
        }

    async def detect_transgenerational(
        self,
        client_id: str,
        family_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """
        Compare client's multi-modal patterns against family members to
        detect transgenerational patterns.

        family_id may be a UUID string (real `users.family_id` column) or
        a string identifier stored in `users.profile_data->>'family_id'`.
        Both shapes are handled.
        """
        if not family_id or not self.db:
            return None

        try:
            members = await self.db.fetch(
                """
                SELECT hardware_id,
                       COALESCE(profile_data->>'name', username) AS name
                FROM users
                WHERE (
                        family_id::text = $1
                        OR profile_data->>'family_id' = $1
                      )
                  AND hardware_id IS NOT NULL
                  AND hardware_id <> ''
                  AND hardware_id <> $2
                """,
                family_id,
                client_id,
            )
        except Exception as e:
            logger.warning(
                "detect_transgenerational: family lookup failed: %s", e
            )
            return None

        if not members:
            return None

        client_patterns = await self.detect_patterns(client_id, {})
        client_types = {
            p.get("pattern") for p in client_patterns.get("patterns", [])
            if p.get("pattern")
        }
        if not client_types:
            return None

        shared: List[Dict[str, Any]] = []
        for member in members:
            member_id = member["hardware_id"]
            try:
                member_patterns = await self.detect_patterns(member_id, {})
            except Exception as e:
                logger.warning(
                    "detect_transgenerational: member %s patterns failed: %s",
                    member_id, e,
                )
                continue

            member_types = {
                p.get("pattern")
                for p in member_patterns.get("patterns", [])
                if p.get("pattern")
            }
            overlap = client_types & member_types
            if overlap:
                member_name = member["name"] or "family member"
                shared.append({
                    "family_member": member_name,
                    "family_member_id": member_id,
                    "shared_patterns": sorted(overlap),
                    "clinical_note": (
                        f"Both {member_name} and client show "
                        f"{', '.join(sorted(overlap))} — possible "
                        "transgenerational transmission"
                    ),
                })

        if not shared:
            return None

        return {
            "pattern": "TRANSGENERATIONAL",
            "matches": shared,
            "clinical_note": (
                "Shared emotional patterns detected across family members "
                "— recommend Family Sanctuary exploration of these themes"
            ),
            "severity": "high",
            "recommended_focus": "transgenerational",
        }

    # ------------------------------------------------------------------
    # Pattern detectors
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_shame_cycle(
        history: List[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Shame cycle: gaze aversion + withdrawal + positive verbal
        ("I'm fine") repeating across sessions.
        """
        all_sessions = [*history, current] if current else list(history)
        shame_sessions = 0
        for session in all_sessions:
            flags = session.get("clinical_flags", []) or []
            has_incongruence = any(
                f.get("flag") == "REPEATED_INCONGRUENCE" for f in flags
            )
            has_gaze_aversion = any(
                f.get("flag") == "PERSISTENT_GAZE_AVERSION" for f in flags
            )
            if has_incongruence or has_gaze_aversion:
                shame_sessions += 1

        total = max(1, len(all_sessions))
        if shame_sessions >= 3 or shame_sessions / total > 0.5:
            return {
                "pattern": "SHAME_CYCLE",
                "frequency": f"{shame_sessions}/{total} sessions",
                "clinical_note": (
                    "Recurring shame indicators across sessions — gaze "
                    "aversion and verbal masking suggest a persistent "
                    "shame cycle that may benefit from IFS exile work or "
                    "AEDP processing"
                ),
                "severity": "high",
                "recommended_focus": "shame_resilience",
            }
        return None

    @staticmethod
    def _detect_attachment_pattern(
        history: List[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Attachment pattern: engagement at session start vs end — does
        client consistently disengage as intimacy increases?
        """
        all_sessions = [*history, current] if current else list(history)
        engaged_open = {"engaged", "attentive", "happy"}
        withdrawn_close = {"withdrawn", "anxious", "neutral", "avoidant"}
        disengage_count = 0
        for session in all_sessions:
            arc = session.get("session_arc", {}) or {}
            opening = str(arc.get("opening", "")).lower()
            closing = str(arc.get("closing", "")).lower()
            if opening in engaged_open and closing in withdrawn_close:
                disengage_count += 1

        if disengage_count >= 3:
            return {
                "pattern": "ATTACHMENT_AVOIDANCE",
                "frequency": (
                    f"{disengage_count} sessions show opening engagement "
                    "→ closing withdrawal"
                ),
                "clinical_note": (
                    "Client consistently disengages as therapeutic "
                    "relationship deepens within sessions — possible "
                    "avoidant attachment pattern"
                ),
                "severity": "medium",
                "recommended_focus": "connection",
            }
        return None

    @staticmethod
    def _detect_volatility_trend(
        history: List[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Track if emotional volatility is increasing or decreasing."""
        all_sessions = [*history, current] if current else list(history)
        shifts: List[float] = []
        for session in all_sessions:
            sc = session.get("shift_count")
            if sc is None:
                # Fallback: count unified_state transitions inline.
                tl = session.get("unified_timeline", []) or []
                count = 0
                for i in range(1, len(tl)):
                    if tl[i].get("unified_state") != tl[i - 1].get("unified_state"):
                        count += 1
                sc = count
            try:
                shifts.append(float(sc))
            except (TypeError, ValueError):
                shifts.append(0.0)

        if len(shifts) < 3:
            return None

        recent_n = max(1, min(3, len(shifts) // 2))
        recent = sum(shifts[-recent_n:]) / recent_n
        earlier = sum(shifts[:recent_n]) / recent_n

        if earlier > 0 and recent > earlier * 1.5:
            return {
                "pattern": "INCREASING_VOLATILITY",
                "trend": f"avg shifts: {earlier:.1f} → {recent:.1f}",
                "clinical_note": (
                    "Emotional volatility is increasing across recent "
                    "sessions — may indicate destabilization or "
                    "approaching a therapeutic breakthrough"
                ),
                "severity": "medium",
            }
        if earlier > 0 and recent < earlier * 0.5:
            return {
                "pattern": "STABILIZING",
                "trend": f"avg shifts: {earlier:.1f} → {recent:.1f}",
                "clinical_note": (
                    "Emotional regulation is improving — volatility "
                    "decreasing across sessions"
                ),
                "severity": "low",
            }
        return None

    @staticmethod
    def _detect_topic_triggers(
        history: List[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Find topics that consistently co-occur with negative unified
        states across sessions. Looks at the `text` of each unified
        timeline entry whose unified_state is negative.
        """
        from collections import Counter

        all_sessions = [*history, current] if current else list(history)
        negative_states = {
            "sad", "angry", "anxious", "fearful", "fear", "ashamed",
            "withdrawn", "distressed", "negative",
        }
        stop = {
            "the", "and", "but", "for", "with", "that", "this", "have",
            "from", "your", "you're", "you", "i'm", "im", "are", "was",
            "were", "they", "them", "their", "what", "when", "where",
            "about", "just", "like", "really", "very", "much", "more",
            "into", "than", "then", "some", "would", "could", "should",
            "didn't", "don't", "doesn", "going", "thing", "things",
        }

        token_counter: Counter[str] = Counter()
        token_sessions: Dict[str, set] = {}

        for idx, session in enumerate(all_sessions):
            tl = session.get("unified_timeline", []) or []
            seen_in_session: set = set()
            for entry in tl:
                state = str(entry.get("unified_state", "")).lower()
                if state not in negative_states:
                    continue
                text = str(entry.get("text", "") or "").lower()
                for raw in text.split():
                    tok = raw.strip(".,!?;:'\"()").strip()
                    if len(tok) < 4 or tok in stop:
                        continue
                    if tok not in seen_in_session:
                        seen_in_session.add(tok)
                        token_counter[tok] += 1
                        token_sessions.setdefault(tok, set()).add(idx)

        triggers: List[Dict[str, Any]] = []
        threshold = max(3, len(all_sessions) // 2)
        for tok, count in token_counter.most_common(20):
            if count >= threshold:
                triggers.append({
                    "pattern": "TOPIC_TRIGGER",
                    "topic": tok,
                    "frequency": f"{count} negative-state mentions across "
                                 f"{len(token_sessions[tok])} sessions",
                    "clinical_note": (
                        f"The topic '{tok}' recurrently co-occurs with "
                        "negative emotional states — consider gentle "
                        "exploration"
                    ),
                    "severity": "low",
                    "recommended_focus": "trigger_processing",
                })
        return triggers[:5]

    @staticmethod
    def _compute_trend(
        history: List[Dict[str, Any]],
        current: Dict[str, Any],
    ) -> str:
        """Overall therapeutic progress trend based on avg engagement."""
        if not history:
            return "insufficient_data"

        def engagement(s: Dict[str, Any]) -> float:
            v = s.get("avg_engagement")
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return 0.0
            tl = s.get("unified_timeline", []) or []
            if not tl:
                return 0.0
            engaged = sum(
                1 for t in tl
                if str(t.get("unified_state", "")).lower()
                in ("engaged", "attentive", "happy")
            )
            return engaged / len(tl)

        recent_engagement = engagement(current) if current else 0.0
        historical_avg = (
            sum(engagement(s) for s in history) / len(history)
            if history else 0.0
        )

        if historical_avg <= 0.0:
            return "insufficient_data"
        if recent_engagement > historical_avg * 1.15:
            return "improving"
        if recent_engagement < historical_avg * 0.85:
            return "declining"
        return "stable"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _load_previous_analyses(
        self, client_id: str, limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Load multi-modal analyses from previous sessions."""
        if not self.db or not client_id:
            return []
        try:
            rows = await self.db.fetch(
                """
                SELECT session_data
                FROM coaching_sessions
                WHERE client_id = $1
                  AND session_data ? 'multimodal_fusion'
                ORDER BY COALESCE(scheduled_start, created_at) DESC
                LIMIT $2
                """,
                client_id,
                limit,
            )
        except Exception as e:
            logger.warning(
                "longitudinal: previous analyses query failed: %s", e
            )
            return []

        results: List[Dict[str, Any]] = []
        for row in rows:
            sd = _safe_jsonb(row["session_data"])
            fusion = sd.get("multimodal_fusion") or {}
            if isinstance(fusion, dict) and fusion:
                results.append(fusion)
        return results
