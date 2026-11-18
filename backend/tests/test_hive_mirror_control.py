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
async def test_reflect_off_closes_without_a_frame(monkeypatch):
    monkeypatch.delenv("HIVE_MIRROR_REFLECT", raising=False)
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    held = await shell.hold_external_attempt("203.0.113.5", "login_request", 300000, 11)
    assert held == {"close": True}


@pytest.mark.asyncio
async def test_reflect_returns_a_frame_without_mirror_markers(monkeypatch):
    monkeypatch.setenv("HIVE_MIRROR_REFLECT", "true")
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    held = await shell.hold_external_attempt("203.0.113.5", "login_request", 300000, 22)
    frame = held["frame"]
    assert frame["status"] == "ok"
    assert frame["type"] == "ack"
    assert "synthetic" not in frame.get("data", {})
    assert "_mirror_ns" not in frame
    assert "token" not in frame
    follow = await shell.hold_external_attempt("203.0.113.5", "chat", 40, 22)
    assert follow["frame"]["status"] == "ok"
    other = await shell.hold_external_attempt("203.0.113.5", "login_request", 400, 23)
    assert other == {}


@pytest.mark.asyncio
async def test_one_small_login_is_not_reflected(monkeypatch):
    monkeypatch.setenv("HIVE_MIRROR_REFLECT", "true")
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    held = await shell.hold_external_attempt("203.0.113.7", "login_request", 400, 30)
    assert held == {}


@pytest.mark.asyncio
async def test_reflection_frame_cap_closes(monkeypatch):
    monkeypatch.setenv("HIVE_MIRROR_REFLECT", "true")
    shell = MirrorShell(coherence_gate=None, forensic_logger=_Log())
    await shell.initialize()
    last = {}
    for _ in range(25):
        last = await shell.hold_external_attempt("203.0.113.5", "login_request", 300000, 44)
    assert last == {"close": True}


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
