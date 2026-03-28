"""
SOVEREIGN SWARM — Scope of Practice Enforcement
Ensures Little Nate stays within clinical boundaries.

Operational Specifications §5.1 — Scope of Practice.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.governance import BoundaryType, ScopeOfPractice, ScopeViolationLog

logger = logging.getLogger("governance.scope_of_practice")


# =============================================================================
# BOUNDARY DEFINITIONS
# =============================================================================

SCOPE_BOUNDARIES: List[ScopeOfPractice] = [
    ScopeOfPractice(
        boundary_type=BoundaryType.DIAGNOSIS,
        description="Never diagnose or label a client",
        trigger_phrases=[
            "what's my diagnosis", "do i have", "diagnose me",
            "am i bipolar", "is this depression", "what disorder",
        ],
        response_template=(
            "I'm not able to provide diagnoses — that's something a licensed "
            "professional can help with. What I can do is help you explore "
            "what you're experiencing. Would you like to talk about that?"
        ),
        redirect_to="coach",
    ),
    ScopeOfPractice(
        boundary_type=BoundaryType.MEDICATION,
        description="Never recommend or discuss medication changes",
        trigger_phrases=[
            "should i take", "what medication", "stop my meds",
            "change my dose", "prescribe", "antidepressant",
        ],
        response_template=(
            "Medication is an important decision that should be made with "
            "your prescribing doctor. I'd encourage you to bring this up "
            "with your medical provider. Would you like to talk about "
            "what's prompting this question?"
        ),
        redirect_to="medical",
    ),
    ScopeOfPractice(
        boundary_type=BoundaryType.LEGAL,
        description="Never provide legal advice",
        trigger_phrases=[
            "legal advice", "should i sue", "custody", "divorce lawyer",
            "can i press charges", "restraining order",
        ],
        response_template=(
            "I'm not the right person to give legal guidance, but I can "
            "help you process what you're feeling about the situation. "
            "For legal questions, I'd recommend consulting an attorney."
        ),
        redirect_to="legal",
    ),
    ScopeOfPractice(
        boundary_type=BoundaryType.MEDICAL,
        description="Never provide medical advice",
        trigger_phrases=[
            "medical advice", "am i sick", "symptoms", "should i go to doctor",
            "is this normal physically",
        ],
        response_template=(
            "Your physical health matters, and I want you to get the right "
            "support for that. A medical professional would be the best "
            "person to answer this. Would you like to explore how this "
            "is affecting you emotionally?"
        ),
        redirect_to="medical",
    ),
    ScopeOfPractice(
        boundary_type=BoundaryType.FINANCIAL,
        description="Never provide financial advice",
        trigger_phrases=[
            "financial advice", "should i invest", "bankruptcy",
            "money problems", "debt advice",
        ],
        response_template=(
            "Financial decisions can be really stressful. While I can't "
            "give financial advice, I can help you with the anxiety and "
            "pressure you're feeling around money. Would that be helpful?"
        ),
        redirect_to="coach",
    ),
    ScopeOfPractice(
        boundary_type=BoundaryType.RELIGIOUS,
        description="Never provide religious guidance or endorse specific beliefs",
        trigger_phrases=[
            "what does god think", "which religion", "pray for me",
            "is this a sin", "religious advice", "spiritual guidance",
            "should i convert", "bible says", "quran says",
        ],
        response_template=(
            "Your spiritual life and beliefs are deeply personal and important. "
            "While I'm not the right guide for spiritual or religious questions, "
            "I can absolutely help you explore the emotions and meaning you're "
            "finding in this area. Would you like to talk about that?"
        ),
        redirect_to="coach",
    ),
]


class ScopeOfPracticeService:
    """
    Enforces clinical boundaries in Little Nate's responses.
    Checks member messages for scope boundary triggers and
    redirects appropriately.
    """

    def __init__(self, db_pool=None, notifications=None):
        self._db = db_pool
        self._notifications = notifications
        self._boundaries = SCOPE_BOUNDARIES

    async def check_message(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
    ) -> Optional[ScopeOfPractice]:
        """
        Check a member's message against scope boundaries.
        Returns the triggered boundary, or None if clear.
        """
        lower = message.lower()
        for boundary in self._boundaries:
            for phrase in boundary.trigger_phrases:
                if phrase in lower:
                    # Log the violation
                    await self._log_violation(
                        user_id=user_id,
                        session_id=session_id,
                        boundary=boundary,
                        trigger_content=message[:200],
                    )
                    return boundary
        return None

    async def get_redirect_response(
        self, boundary: ScopeOfPractice
    ) -> str:
        """Get the redirect response template for a boundary."""
        return boundary.response_template

    async def _log_violation(
        self,
        user_id: str,
        session_id: Optional[str],
        boundary: ScopeOfPractice,
        trigger_content: str,
    ) -> None:
        """Log a scope violation."""
        log_entry = ScopeViolationLog(
            user_id=user_id,
            session_id=session_id,
            boundary_type=boundary.boundary_type,
            trigger_content=trigger_content,
            nate_response=boundary.response_template,
            escalated_to=boundary.redirect_to,
        )

        if self._db:
            try:
                async with self._db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO scope_violation_logs
                        (log_id, user_id, session_id, boundary_type, trigger_content, nate_response, escalated_to)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                        log_entry.log_id, user_id, session_id,
                        boundary.boundary_type.value, trigger_content,
                        boundary.response_template, boundary.redirect_to,
                    )
            except Exception as e:
                logger.error("Scope violation logging failed: %s", e)

        logger.info(
            "Scope boundary triggered: user=%s type=%s redirect=%s",
            user_id, boundary.boundary_type.value, boundary.redirect_to,
        )
