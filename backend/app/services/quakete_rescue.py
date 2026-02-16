"""
SOVEREIGN SWARM — Quakete Rescue in Live Therapy (S4)
CEE window Quakete activation protocol — must complete in <500ms total.
When a Fibre carrying a live therapy session detects a CEE window,
this protocol activates Quakete from ring partners to ensure the
session can capitalize on the window.

Applied Solution S4: Quakete Rescue in Live Therapy.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.solutions import (
    CEEWindowBriefing,
    QuaketeRescueProtocol,
)

logger = logging.getLogger("quakete_rescue")


class QuaketeRescueService:
    """
    Activates Quakete rescue protocol when a CEE window opens
    during a live therapy session.

    Total execution budget: 500ms.
    """

    def __init__(
        self,
        trail_map=None,
        ion_pool=None,
        ring_manager=None,
        session_interface=None,
        nevedal_engine=None,
    ):
        self._trail_map = trail_map
        self._ion_pool = ion_pool
        self._ring_manager = ring_manager
        self._session_interface = session_interface
        self._nevedal = nevedal_engine

    async def activate_rescue(
        self,
        session_id: str,
        target_fibre_id: str,
        member_name: str = "",
        emotional_state: str = "",
        recommended_action: str = "",
    ) -> QuaketeRescueProtocol:
        """
        Activate the Quakete rescue protocol for a CEE window.
        Must complete all steps in <500ms.
        """
        start_time = time.monotonic()

        protocol = QuaketeRescueProtocol(
            target_fibre_id=target_fibre_id,
        )

        # Step 1: Assess target fibre health (budget: 50ms)
        if self._trail_map:
            health = self._trail_map.get_fibre_health(target_fibre_id)
            protocol.target_fibre_health = health or 0.0

        # Step 2: Find ring partners (budget: 50ms)
        partner_fibres = []
        if self._ring_manager:
            try:
                ring = self._ring_manager.get_fibre_ring(target_fibre_id)
                if ring:
                    protocol.cosmic_ring_id = ring.ring_id
                    other_cords = ring.get_other_cords(target_fibre_id)
                    partner_fibres = [c.fibre_id for c in other_cords]
                    protocol.partner_fibres = partner_fibres
            except Exception as e:
                logger.warning("Ring partner lookup failed: %s", e)

        # Step 3: Initiate Quakete transfer from healthiest partner (budget: 100ms)
        if partner_fibres and self._ion_pool and self._trail_map:
            # Find healthiest partner
            partner_health = {}
            for pid in partner_fibres:
                h = self._trail_map.get_fibre_health(pid)
                if h is not None:
                    partner_health[pid] = h
            protocol.partner_health_scores = list(partner_health.values())

            if partner_health:
                donor_id = max(partner_health, key=partner_health.get)
                donation = min(partner_health[donor_id] * 0.2, 0.3)
                protocol.energy_donation_amount = donation
                try:
                    await asyncio.wait_for(
                        self._ion_pool.transfer(
                            from_fibre=donor_id,
                            to_fibre=target_fibre_id,
                            amount=donation,
                        ),
                        timeout=0.1,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Quakete transfer timed out (100ms budget)")
                except Exception as e:
                    logger.warning("Quakete transfer failed: %s", e)

        # Step 4: Generate and deliver CEE briefing (budget: 200ms)
        briefing = CEEWindowBriefing(
            member_name=member_name,
            emotional_state=emotional_state,
            recommended_action=recommended_action or "Lean into the emotional opening. This is the moment.",
            avoid="Do not ask analytical questions. Stay with the feeling.",
            estimated_window_duration_seconds=60,
        )

        if self._session_interface:
            try:
                briefing_start = time.monotonic()
                await self._session_interface.notify_cee_window(
                    session_id=session_id,
                    member_name=member_name,
                    emotional_state=emotional_state,
                    recommended_action=briefing.recommended_action,
                    estimated_duration=briefing.estimated_window_duration_seconds,
                )
                protocol.briefing_generated = True
                protocol.briefing_delivery_ms = (time.monotonic() - briefing_start) * 1000
            except Exception as e:
                logger.warning("CEE briefing delivery failed: %s", e)

        # Calculate total latency
        total_ms = (time.monotonic() - start_time) * 1000
        protocol.target_fibre_latency_ms = total_ms

        if total_ms > protocol.latency_threshold_ms:
            logger.warning(
                "Quakete rescue exceeded 500ms budget: %.1fms", total_ms
            )
        else:
            logger.info(
                "Quakete rescue completed in %.1fms (budget: 500ms)", total_ms
            )

        return protocol
