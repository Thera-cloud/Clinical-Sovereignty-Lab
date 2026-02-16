"""
HIVE DEFENSE v4.3 — Coach Integrity Shield (Window 2)
Monitors coach behavior for integrity issues.

1. Outcome comparison across coaches (detect underperformers)
2. Off-session access detection (accessing data outside session hours)
3. Note analysis (quality, length, consistency)
4. Attrition tracking (client dropout rates per coach)
"""

import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("coach_integrity_shield")

# Thresholds
ATTRITION_THRESHOLD = 0.30  # 30% dropout flags
ACCESS_HOUR_WINDOW = (7, 22)  # Normal access hours (7am-10pm)
MIN_NOTE_LENGTH = 50  # Minimum acceptable note length (chars)


class CoachIntegrityShield:
    """Monitors coach behavior and outcome integrity."""

    def __init__(self, db_pool=None):
        self._db = db_pool

    # ─── 1. Outcome Comparison ────────────────────────────────────────────────

    async def compare_outcomes(self) -> Dict[str, Any]:
        """
        Compare coherence outcomes across coaches.
        Flags coaches whose clients consistently show lower improvement.
        """
        if not self._db:
            return {"coaches_analyzed": 0}

        try:
            # Get average coherence improvement per coach
            rows = await self._db.fetch(
                """SELECT coach_id,
                          AVG(coherence_delta) as avg_improvement,
                          COUNT(*) as client_count
                   FROM (
                       SELECT s.coach_id,
                              (s.post_coherence - s.pre_coherence) as coherence_delta
                       FROM sessions s
                       WHERE s.pre_coherence IS NOT NULL
                         AND s.post_coherence IS NOT NULL
                         AND s.created_at > NOW() - INTERVAL '90 days'
                   ) sub
                   GROUP BY coach_id
                   HAVING COUNT(*) >= 5""",
            )

            if not rows:
                return {"coaches_analyzed": 0, "sufficient_data": False}

            improvements = [r["avg_improvement"] for r in rows]
            mean_improvement = statistics.mean(improvements) if improvements else 0
            std_improvement = statistics.stdev(improvements) if len(improvements) > 1 else 1

            flagged = []
            for row in rows:
                z_score = (row["avg_improvement"] - mean_improvement) / max(std_improvement, 0.01)
                if z_score < -1.5:  # 1.5 std below mean
                    flagged.append({
                        "coach_id": row["coach_id"],
                        "avg_improvement": row["avg_improvement"],
                        "client_count": row["client_count"],
                        "z_score": z_score,
                    })

            if flagged:
                _logger.warning(
                    "COACH OUTCOME FLAG: %d coaches below threshold",
                    len(flagged),
                )

            return {
                "coaches_analyzed": len(rows),
                "population_mean": mean_improvement,
                "flagged_coaches": flagged,
            }

        except Exception as exc:
            _logger.error("Outcome comparison error: %s", exc)
            return {"coaches_analyzed": 0, "error": str(exc)}

    # ─── 2. Off-Session Access Detection ──────────────────────────────────────

    async def detect_off_session_access(self, coach_id: str) -> Dict[str, Any]:
        """
        Detect when a coach accesses client data outside normal session hours
        or outside scheduled sessions.
        """
        if not self._db:
            return {"suspicious_accesses": 0}

        try:
            # Find data accesses outside 7am-10pm
            rows = await self._db.fetch(
                """SELECT endpoint, created_at
                   FROM login_attempts
                   WHERE identifier = $1 AND success = TRUE
                   AND created_at > NOW() - INTERVAL '30 days'
                   AND EXTRACT(HOUR FROM created_at) NOT BETWEEN $2 AND $3""",
                coach_id, ACCESS_HOUR_WINDOW[0], ACCESS_HOUR_WINDOW[1],
            )

            suspicious = [
                {"time": r["created_at"].isoformat(), "endpoint": r.get("endpoint", "")}
                for r in rows
            ]

            if suspicious:
                _logger.info(
                    "Off-session access for coach %s: %d instances",
                    coach_id[:8], len(suspicious),
                )

            return {
                "coach_id": coach_id,
                "suspicious_accesses": len(suspicious),
                "details": suspicious[:10],  # Limit output
            }

        except Exception as exc:
            _logger.error("Off-session access detection error: %s", exc)
            return {"suspicious_accesses": 0}

    # ─── 3. Note Analysis ─────────────────────────────────────────────────────

    async def analyze_notes(self, coach_id: str) -> Dict[str, Any]:
        """
        Analyze coach notes for quality indicators.
        Flags: very short notes, template-like repetition, missing notes.
        """
        if not self._db:
            return {"notes_analyzed": 0}

        try:
            rows = await self._db.fetch(
                """SELECT content, LENGTH(content) as note_length
                   FROM coach_notes
                   WHERE coach_id = $1
                   AND created_at > NOW() - INTERVAL '30 days'""",
                coach_id,
            )

            if not rows:
                return {"notes_analyzed": 0}

            lengths = [r["note_length"] or 0 for r in rows]
            avg_length = statistics.mean(lengths) if lengths else 0

            short_notes = sum(1 for l in lengths if l < MIN_NOTE_LENGTH)
            
            # Check for template repetition (same note content)
            contents = [r["content"] for r in rows if r["content"]]
            unique_ratio = len(set(contents)) / max(len(contents), 1)

            issues = []
            if avg_length < MIN_NOTE_LENGTH:
                issues.append("average_note_too_short")
            if short_notes > len(rows) * 0.5:
                issues.append("majority_notes_too_short")
            if unique_ratio < 0.5:
                issues.append("template_repetition_detected")

            return {
                "notes_analyzed": len(rows),
                "average_length": avg_length,
                "short_notes": short_notes,
                "unique_ratio": unique_ratio,
                "issues": issues,
            }

        except Exception as exc:
            _logger.error("Note analysis error: %s", exc)
            return {"notes_analyzed": 0}

    # ─── 4. Attrition Tracking ────────────────────────────────────────────────

    async def track_attrition(self, coach_id: str) -> Dict[str, Any]:
        """
        Track client dropout rates per coach.
        Flags coaches with high attrition.
        """
        if not self._db:
            return {"attrition_rate": 0}

        try:
            total = await self._db.fetchrow(
                """SELECT COUNT(DISTINCT user_id) as total
                   FROM sessions WHERE coach_id = $1
                   AND created_at > NOW() - INTERVAL '180 days'""",
                coach_id,
            )
            dropped = await self._db.fetchrow(
                """SELECT COUNT(DISTINCT user_id) as dropped
                   FROM sessions WHERE coach_id = $1
                   AND user_id NOT IN (
                       SELECT DISTINCT user_id FROM sessions
                       WHERE coach_id = $1
                       AND created_at > NOW() - INTERVAL '60 days'
                   )
                   AND created_at BETWEEN NOW() - INTERVAL '180 days' AND NOW() - INTERVAL '60 days'""",
                coach_id,
            )

            total_count = total["total"] if total else 0
            dropped_count = dropped["dropped"] if dropped else 0
            rate = dropped_count / max(total_count, 1)

            result = {
                "coach_id": coach_id,
                "total_clients_180d": total_count,
                "dropped_clients": dropped_count,
                "attrition_rate": rate,
                "flagged": rate > ATTRITION_THRESHOLD,
            }

            if result["flagged"]:
                _logger.warning(
                    "HIGH ATTRITION for coach %s: %.1f%% (%d/%d)",
                    coach_id[:8], rate * 100, dropped_count, total_count,
                )

            return result

        except Exception as exc:
            _logger.error("Attrition tracking error: %s", exc)
            return {"attrition_rate": 0}
