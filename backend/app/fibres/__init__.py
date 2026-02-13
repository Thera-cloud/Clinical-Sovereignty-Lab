"""
SOVEREIGN SWARM — Fibre Architecture
Autonomous AI agents with frozen ethical cores, identity chains,
and Wisdom Mesh communication.
"""

from app.fibres.base_fibre import BaseFibre, FrozenEthicalCore
from app.fibres.campaign_fibre import CampaignFibre
from app.fibres.cultural_sentinel import CulturalSentinelFibre
from app.fibres.foresight_analyst import ForesightAnalystFibre
from app.fibres.coach_support import CoachSupportFibre
from app.fibres.quiz_funnel import QuizFunnelFibre
from app.fibres.community_fibre import CommunityFibre

# Fibre type → implementation class registry
FIBRE_REGISTRY = {
    "campaign": CampaignFibre,
    "cultural_sentinel": CulturalSentinelFibre,
    "foresight_analyst": ForesightAnalystFibre,
    "coach_support": CoachSupportFibre,
    "quiz_funnel": QuizFunnelFibre,
    "community": CommunityFibre,
}

__all__ = [
    "BaseFibre", "FrozenEthicalCore",
    "CampaignFibre", "CulturalSentinelFibre", "ForesightAnalystFibre",
    "CoachSupportFibre", "QuizFunnelFibre", "CommunityFibre",
    "FIBRE_REGISTRY",
]
