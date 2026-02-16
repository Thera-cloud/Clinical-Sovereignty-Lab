"""
PROJECTED HELIX — Offensive Active Defense (v3.2)
The shield becomes the sword. Requires human authorization for every deployment.
Patent-Pending — Claims 53-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from app.services.security.offensive.projected_helix import ProjectedHelix
from app.services.security.offensive.protocol_mirror import AttackerProtocolMirror
from app.services.security.offensive.topology_mirror import AttackerTopologyMirror
from app.services.security.offensive.behavior_mirror import AttackerBehaviorMirror
from app.services.security.offensive.recursive_projection import RecursiveProjection
from app.services.security.offensive.command_interceptor import (
    CommandInterceptor,
    ChannelSpec,
)
from app.services.security.offensive.agent_redirection import AgentRedirection
from app.services.security.offensive.attacker_model import AttackerBehavioralModel
from app.services.security.offensive.projection_authorization import (
    ProjectionAuthorization,
)
from app.services.security.offensive.projection_forensics import ProjectionForensics

__all__ = [
    "ProjectedHelix",
    "AttackerProtocolMirror",
    "AttackerTopologyMirror",
    "AttackerBehaviorMirror",
    "RecursiveProjection",
    "CommandInterceptor",
    "ChannelSpec",
    "AgentRedirection",
    "AttackerBehavioralModel",
    "ProjectionAuthorization",
    "ProjectionForensics",
]
