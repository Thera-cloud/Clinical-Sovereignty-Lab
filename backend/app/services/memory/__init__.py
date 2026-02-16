"""
SOVEREIGN SWARM — Memory Tier Architecture

Hot (Redis), Warm (Azure Blob Hot), Cold (Azure Blob Cool).

Provides a three-tier memory architecture for the Sovereign Swarm:
- Hot: Redis-backed active context for session state, fibre state
- Warm: Azure Blob Hot tier for archived sessions and insights
- Cold: Azure Blob Cool tier for long-term archives (Legacy Vault, evolution journals)
"""
from app.services.memory.hot import HotMemoryTier
from app.services.memory.warm import WarmMemoryTier
from app.services.memory.cold import ColdMemoryTier

__all__ = ["HotMemoryTier", "WarmMemoryTier", "ColdMemoryTier"]
