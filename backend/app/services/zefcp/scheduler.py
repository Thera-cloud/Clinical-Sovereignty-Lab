"""
ZEFCP Scheduler — Fragment pacing across handshake events.
Patent Claim 25: Zero-Energy BLE Communication — Pacing fragment injection
to align with ambient BLE handshake events; rate-limited to prevent
channel saturation and preserve carrier device operation.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, TypeVar

from app.models.zefcp import MicroFragment

T = TypeVar("T")


# =============================================================================
# EMBEDDING SCHEDULER
# =============================================================================


class EmbeddingScheduler:
    """
    Paces fragment injection across BLE handshake events.
    Patent Claim 25: Yields one fragment per handshake, rate-limited to
    max_rate fragments/second to avoid saturating the channel.
    """

    def __init__(self, max_rate: int = 10, mode: str = "extended") -> None:
        """
        Initialize scheduler with rate limit.

        Args:
            max_rate: Maximum fragments per second; respects MAX_EMBEDDING_RATE.
            mode: "standard" or "extended" (for compatibility with fragment sizing).
        """
        self._max_rate = max(1, min(max_rate, 50))
        self._mode = mode.lower()
        self._min_interval = 1.0 / self._max_rate

    async def schedule_observation(
        self,
        fragments: List[MicroFragment],
    ) -> AsyncIterator[MicroFragment]:
        """
        Pace fragment injection: max_rate fragments/second.
        Yields one fragment per handshake event with asyncio.sleep for pacing.
        Patent Claim 25.

        Args:
            fragments: List of MicroFragments to emit in order.

        Yields:
            One MicroFragment per iteration, with rate-limited delays.
        """
        for i, fragment in enumerate(fragments):
            yield fragment
            # Space emissions to respect max_rate (except after last fragment)
            if i < len(fragments) - 1:
                await asyncio.sleep(self._min_interval)

    def get_estimated_time(
        self,
        fragment_count: int,
        handshake_rate: float,
    ) -> float:
        """
        Return estimated seconds to embed all fragments.

        When handshake_rate >= max_rate, limited by our rate.
        When handshake_rate < max_rate, limited by handshake availability.

        Args:
            fragment_count: Number of fragments to embed.
            handshake_rate: Ambient BLE handshakes per second.

        Returns:
            Estimated seconds to complete embedding.
        """
        if fragment_count <= 0:
            return 0.0
        # Rate limit: we can emit at most max_rate frags/sec
        our_rate = min(self._max_rate, handshake_rate) if handshake_rate > 0 else self._max_rate
        return fragment_count / our_rate
