"""
SOVEREIGN SWARM — Pre-Session Briefing Renderer
Formats PredictiveCoachBriefing data into human-readable and
WebSocket-deliverable formats for the coach dashboard.

Operational Specifications §2.2 — Pre-Session Briefing Display.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.models.solutions import PredictiveCoachBriefing

logger = logging.getLogger("coach_experience.briefing_renderer")


class BriefingRenderer:
    """Renders briefings for coach dashboard and mobile display."""

    def render_for_dashboard(self, briefing: PredictiveCoachBriefing) -> Dict[str, Any]:
        """Render a briefing as a structured dashboard payload."""
        return {
            "briefing_id": briefing.briefing_id,
            "member": {
                "id": briefing.member_id,
                "name": briefing.member_name,
            },
            "session_datetime": (
                briefing.session_datetime.isoformat()
                if briefing.session_datetime else None
            ),
            "generated_at": briefing.briefing_generated.isoformat(),
            "current_state": {
                "c_emo": briefing.current_state.c_emo_current,
                "c_emo_7d_avg": briefing.current_state.c_emo_7day_average,
                "primary_emotion": briefing.current_state.primary_emotion,
                "active_themes": briefing.current_state.active_themes,
                "unresolved": briefing.current_state.unresolved_from_last_session,
                "homework": briefing.current_state.homework_completion,
            },
            "trajectory": {
                "direction": briefing.trajectory.c_emo_direction,
                "velocity": briefing.trajectory.c_emo_velocity,
                "key_shift": briefing.trajectory.key_shift,
            },
            "prediction": {
                "theme": briefing.prediction.predicted_theme,
                "confidence": briefing.prediction.confidence,
                "emotional_state": briefing.prediction.predicted_emotional_state,
                "cee_opportunity": briefing.prediction.cee_opportunity,
            },
            "recommended_focus": {
                "primary": briefing.recommended_focus.primary_recommendation,
                "opening": briefing.recommended_focus.opening_approach,
                "frame": briefing.recommended_focus.therapeutic_frame,
                "techniques": briefing.recommended_focus.specific_techniques,
                "avoid": briefing.recommended_focus.things_to_avoid,
            },
            "risk": {
                "level": briefing.risk_assessment.current_risk_level,
                "factors": briefing.risk_assessment.risk_factors_present,
                "safety_plan": briefing.risk_assessment.safety_plan_active,
            },
            "context": {
                "total_sessions": briefing.session_context.total_sessions,
                "presenting_problem": briefing.session_context.presenting_problem_current,
                "goals": briefing.session_context.treatment_goals,
            },
        }

    def render_summary_card(self, briefing: PredictiveCoachBriefing) -> Dict[str, Any]:
        """Render a compact summary card for notifications."""
        direction_emoji_map = {
            "improving": "trending_up",
            "declining": "trending_down",
            "stable": "stable",
        }
        return {
            "type": "briefing_card",
            "member_name": briefing.member_name,
            "session_time": (
                briefing.session_datetime.strftime("%I:%M %p")
                if briefing.session_datetime else "Unscheduled"
            ),
            "c_emo": round(briefing.current_state.c_emo_current, 2),
            "direction": briefing.trajectory.c_emo_direction,
            "direction_indicator": direction_emoji_map.get(
                briefing.trajectory.c_emo_direction, "stable"
            ),
            "risk_level": briefing.risk_assessment.current_risk_level,
            "recommended_focus": briefing.recommended_focus.primary_recommendation,
            "predicted_theme": briefing.prediction.predicted_theme,
        }

    def render_as_text(self, briefing: PredictiveCoachBriefing) -> str:
        """Render a briefing as human-readable text for display."""
        lines = [
            f"=== PRE-SESSION BRIEFING ===",
            f"Member: {briefing.member_name}",
            f"Session: {briefing.session_datetime.strftime('%B %d, %Y at %I:%M %p') if briefing.session_datetime else 'TBD'}",
            "",
            f"--- CURRENT STATE ---",
            f"C_emo: {briefing.current_state.c_emo_current:.2f} (7d avg: {briefing.current_state.c_emo_7day_average:.2f})",
            f"Direction: {briefing.trajectory.c_emo_direction}",
            f"Active themes: {', '.join(briefing.current_state.active_themes) or 'None identified'}",
        ]

        if briefing.current_state.unresolved_from_last_session:
            lines.append(f"Unresolved: {', '.join(briefing.current_state.unresolved_from_last_session)}")

        lines.extend([
            "",
            f"--- PREDICTION ---",
            f"Predicted theme: {briefing.prediction.predicted_theme or 'N/A'}",
            f"Confidence: {briefing.prediction.confidence:.0%}",
        ])

        if briefing.prediction.cee_opportunity:
            lines.append(f"CEE opportunity: {briefing.prediction.cee_opportunity}")

        lines.extend([
            "",
            f"--- RECOMMENDED FOCUS ---",
            f"{briefing.recommended_focus.primary_recommendation}",
            f"Frame: {briefing.recommended_focus.therapeutic_frame}",
        ])

        if briefing.recommended_focus.things_to_avoid:
            lines.append(f"Avoid: {', '.join(briefing.recommended_focus.things_to_avoid)}")

        lines.extend([
            "",
            f"--- RISK ---",
            f"Level: {briefing.risk_assessment.current_risk_level}",
            f"Safety plan: {'Active' if briefing.risk_assessment.safety_plan_active else 'Not active'}",
        ])

        return "\n".join(lines)
