"""Control-plane checks for the mirror and ghost deploy gate."""

import pytest

from app.models.hive_defense import GateDecision
from app.services.security.distributed_defense import MeshGhostSwarm
from app.services.security.ghost_swarm import GhostSwarm
from app.services.security.mirror_shell import MirrorShell


class _Log:
    async def log_event(self, **kwargs):
        return None


@pytest.mark.asyncio
async def test_normal_control_message_passes():
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    decision = await shell.assess_client_control(
        {"source_address": "203.0.113.5", "signal_type": "login_request", "payload_size": 400}
    )
    assert decision == GateDecision.PASS_TO_REAL


@pytest.mark.asyncio
async def test_oversized_control_message_is_contained():
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    decision = await shell.assess_client_control(
        {"source_address": "203.0.113.5", "signal_type": "login_request", "payload_size": 300000}
    )
    assert decision == GateDecision.MIRROR_CONTAIN


@pytest.mark.asyncio
async def test_control_burst_is_contained():
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    decision = GateDecision.PASS_TO_REAL
    for _ in range(31):
        decision = await shell.assess_client_control(
            {"source_address": "203.0.113.9", "signal_type": "login_request", "payload_size": 80}
        )
    assert decision == GateDecision.MIRROR_CONTAIN


@pytest.mark.asyncio
async def test_external_signal_does_not_use_the_heartbeat_gate():
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    decision = await shell.process_signal(
        {
            "external": True,
            "source_address": "203.0.113.8",
            "signal_type": "login_request",
            "payload_size": 120,
        }
    )
    assert decision == GateDecision.PASS_TO_REAL


@pytest.mark.asyncio
async def test_ghost_deploy_requires_recorded_approval():
    swarm = GhostSwarm(forensic_logger=_Log())
    with pytest.raises(PermissionError):
        await swarm.deploy("zone-a")
    token = swarm.grant_deployment("DrNevedal1", "zone-a")
    assert token


def test_phantom_deploy_requires_recorded_approval():
    swarm = MeshGhostSwarm()
    with pytest.raises(PermissionError):
        swarm.deploy(1)
    token = swarm.grant("DrNevedal1")
    ids = swarm.deploy(1, approval_token=token)
    assert len(ids) == 1
