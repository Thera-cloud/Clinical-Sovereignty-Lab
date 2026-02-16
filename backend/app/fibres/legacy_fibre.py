"""
SOVEREIGN SWARM — Legacy Fibre
Specialized Fibre for Me-2-Me imprint management.
Absorbs data during the member's lifetime, transitions to
maintaining the avatar post-migration.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("fibres.legacy_fibre")


class LegacyFibre:
    """
    Specialized Fibre type dedicated to Me-2-Me operations.

    Lifecycle:
    1. COLLECTING — Absorbs session data, voice notes, milestones
    2. CRYSTALLIZING — Assists Identity Crystallizer during synthesis
    3. MAINTAINING — Post-migration: maintains avatar state and growth
    """

    def __init__(
        self,
        fibre_id: str,
        user_id: str,
        imprint_accumulator=None,
        identity_crystallizer=None,
        consent_service=None,
    ):
        self.fibre_id = fibre_id
        self.user_id = user_id
        self.fibre_type = "legacy"
        self.state = "collecting"
        self._accumulator = imprint_accumulator
        self._crystallizer = identity_crystallizer
        self._consent = consent_service
        self._created_at = datetime.utcnow()
        self._total_imprints = 0
        self._total_crystals = 0

    async def absorb_session_data(
        self,
        session_id: str,
        content: str,
        themes: List[str],
        emotions: List[str],
        c_emo: float = 0.0,
        gamma: float = 0.0,
    ) -> bool:
        """Absorb data from a therapy session."""
        if self.state != "collecting":
            return False

        if self._accumulator:
            entry = await self._accumulator.absorb(
                user_id=self.user_id,
                source="session",
                content=content,
                themes=themes,
                emotions=emotions,
                c_emo=c_emo,
                gamma=gamma,
            )
            if entry:
                self._total_imprints += 1
                return True
        return False

    async def absorb_voice_note(
        self,
        content: str,
        voice_biometrics: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Absorb a voice note."""
        if self.state != "collecting":
            return False

        if self._accumulator:
            entry = await self._accumulator.absorb(
                user_id=self.user_id,
                source="voice_note",
                content=content,
                voice_biometrics=voice_biometrics,
            )
            if entry:
                self._total_imprints += 1
                return True
        return False

    async def absorb_homework(
        self,
        homework_id: str,
        content: str,
        themes: Optional[List[str]] = None,
        emotions: Optional[List[str]] = None,
        c_emo: float = 0.0,
    ) -> bool:
        """Absorb data from a homework assignment."""
        if self.state != "collecting":
            return False

        if self._accumulator:
            entry = await self._accumulator.absorb(
                user_id=self.user_id,
                source="homework",
                content=content,
                themes=themes,
                emotions=emotions,
                c_emo=c_emo,
            )
            if entry:
                self._total_imprints += 1
                return True
        return False

    async def absorb_journal(
        self,
        journal_id: str,
        content: str,
        themes: Optional[List[str]] = None,
        emotions: Optional[List[str]] = None,
        c_emo: float = 0.0,
    ) -> bool:
        """Absorb data from a journal entry."""
        if self.state != "collecting":
            return False

        if self._accumulator:
            entry = await self._accumulator.absorb(
                user_id=self.user_id,
                source="journal",
                content=content,
                themes=themes,
                emotions=emotions,
                c_emo=c_emo,
            )
            if entry:
                self._total_imprints += 1
                return True
        return False

    async def absorb_milestone(
        self,
        milestone_id: str,
        content: str,
        themes: Optional[List[str]] = None,
        c_emo: float = 0.0,
    ) -> bool:
        """Absorb data from a milestone event."""
        if self.state != "collecting":
            return False

        if self._accumulator:
            entry = await self._accumulator.absorb(
                user_id=self.user_id,
                source="milestone",
                content=content,
                themes=themes,
                c_emo=c_emo,
            )
            if entry:
                self._total_imprints += 1
                return True
        return False

    async def transition_to_crystallizing(self) -> None:
        """Transition to crystallizing state (assists Identity Crystallizer)."""
        self.state = "crystallizing"
        logger.info(
            "Legacy Fibre transitioned to crystallizing: fibre=%s user=%s imprints=%d",
            self.fibre_id, self.user_id, self._total_imprints,
        )

    async def trigger_crystallization(self) -> bool:
        """Trigger an identity crystal synthesis."""
        if self._crystallizer:
            crystal = await self._crystallizer.synthesize(self.user_id)
            if crystal:
                self._total_crystals += 1
                return True
        return False

    async def transition_to_maintaining(self) -> None:
        """Transition this fibre from collecting to maintaining."""
        self.state = "maintaining"
        logger.info(
            "Legacy Fibre transitioned to maintaining: fibre=%s user=%s imprints=%d crystals=%d",
            self.fibre_id, self.user_id, self._total_imprints, self._total_crystals,
        )

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of this Legacy Fibre."""
        return {
            "fibre_id": self.fibre_id,
            "user_id": self.user_id,
            "fibre_type": self.fibre_type,
            "state": self.state,
            "total_imprints": self._total_imprints,
            "total_crystals": self._total_crystals,
            "created_at": self._created_at.isoformat(),
        }
