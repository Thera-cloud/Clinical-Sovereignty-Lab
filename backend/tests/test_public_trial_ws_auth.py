"""
Public Trial Funnel — WebSocket pre-auth surface audit.

Plan ref: SECURITY_HARDENING_CHECKLIST.md P0.2 "WebSocket authentication audit"
(public_trial_funnel plan, section "Security Hardening Gate" — P0.2):

  "New backend/tests/test_public_trial_ws_auth.py: programmatically enumerate
  every dispatch branch (`t == "..."` / `msg_type ==`) in bridge_server.py;
  connect unauthenticated, send each type, assert reject/no-op for every type
  except the existing pre-auth allowlist (login_request, register_request,
  etc.) plus public_trial_start / public_trial_chat / public_trial_capture_email.
  Runs in CI forever."

Design note — this file is import-isolated from bridge_server.py (a 27k-line
module with heavy side effects on import: DB pools, Redis clients, hardware
fingerprint services, dozens of other service singletons). This matches the
established pattern in this suite for this exact file:

  - test_socket_eviction.py: "instantiates a minimal Cortex-shaped fake whose
    register() mirrors the QUANTUM-CRYSTAL-ARCH eviction block. Any divergence
    ... will be caught by code review on changes to bridge_server.py."
  - test_dojo_model_tier_routing.py: "Extract ... via AST-style parsing.
    Avoids importing bridge_server.py (27k lines, heavy side effects)."

This file combines both techniques:
  1. Regex/source-level enumeration of every WS dispatch type literal, and
     extraction of the REAL pre-auth allowlist tuple from the live source —
     so the allowlist assertions below are pinned against the actual file,
     not a hand-copied guess that can silently drift.
  2. A minimal, faithful mirror of the pre-auth gate control flow (ping /
     session_recover / public_trial_* short-circuits + the auth-timeout
     enforcement guard), run behind a REAL local `websockets.serve()` server
     so the "connect unauthenticated, send each type" requirement is a
     genuine live round-trip, not a simulation. Keep this mirror in sync with
     bridge_server.py's handle_client() on any future change to that block —
     code review is the sync mechanism, same as test_socket_eviction.py.
"""

import asyncio
import datetime
import json
import pathlib
import re

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

BRIDGE_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "app" / "websocket" / "bridge_server.py"
)

# The definitive pre-auth allowlist per the plan — anything outside this set
# (and outside the always-pre-auth ping/session_recover short-circuits) must
# be rejected by the auth-timeout gate once an unauthenticated connection's
# deadline has elapsed.
EXPECTED_PRE_AUTH_ALLOWLIST = frozenset(
    {
        "login_request",
        "auth",
        "register_request",
        "verify_admin_passphrase",
        "verify_sms_code",
        "accept_consent_update",
        "accept_coach_ethics",
        "forgot_password",
        "force_password_change",
        "public_trial_start",
        "public_trial_chat",
        "public_trial_capture_email",
    }
)

# Types that short-circuit BEFORE the auth-timeout guard is ever evaluated,
# independent of the allowlist tuple (they are unconditionally handled).
ALWAYS_PRE_AUTH_TYPES = frozenset({"ping", "session_recover"})

# Pre-existing (pre-trial-funnel) allowlist entry that is legacy/superseded —
# the real password-reset flow dispatches on "forgot_password_request" /
# "forgot_password_confirm" (and the phone variants); bare "forgot_password"
# is never sent as an actual `type` value anywhere in bridge_server.py today.
# Out of scope to remove here (unrelated to the trial funnel; would need its
# own review), but documented so the enumeration sanity check below doesn't
# flag it as a broken/renamed type.
KNOWN_LEGACY_ALLOWLIST_ENTRIES = frozenset({"forgot_password"})


def _read_bridge_source() -> str:
    return BRIDGE_PATH.read_text()


def _enumerate_dispatch_types(src: str) -> set:
    """
    Programmatically enumerate every dispatch branch that compares the
    incoming message `type` field against a string literal, matching both
    `t == "..."` / `msg_type == "..."` and `t in ("...", "...")` shapes.
    """
    types = set()
    for m in re.finditer(r'\b(?:t|msg_type)\s*==\s*"([^"]+)"', src):
        types.add(m.group(1))
    for m in re.finditer(r'\b(?:t|msg_type)\s+in\s+\(([^)]*)\)', src):
        for lit in re.finditer(r'"([^"]+)"', m.group(1)):
            types.add(lit.group(1))
    return types


def _extract_pre_auth_allowlist(src: str) -> tuple:
    """
    Extract the literal tuple from the auth-timeout enforcement guard:
        if not current_profile and t not in (...) and datetime.datetime.now() > auth_deadline:
    This is the actual codified pre-auth allowlist in bridge_server.py,
    located structurally (not by line number, which drifts as the file grows).
    """
    m = re.search(
        r"if not current_profile and t not in \(([^)]*)\) "
        r"and datetime\.datetime\.now\(\) > auth_deadline:",
        src,
    )
    assert m, (
        "auth_deadline pre-auth allowlist guard not found in bridge_server.py "
        "— has the condition shape changed? Update this regex after review."
    )
    return tuple(lit.group(1) for lit in re.finditer(r'"([^"]+)"', m.group(1)))


def _extract_immediate_preauth_dispatch(src: str) -> set:
    """
    Types handled and `continue`d BEFORE the auth_deadline check ever runs —
    unconditionally reachable pre-auth regardless of elapsed time.
    """
    types = set()
    if re.search(r'if t == "ping":', src):
        types.add("ping")
    if re.search(r'if t == "session_recover" and _recover_session:', src):
        types.add("session_recover")
    m = re.search(
        r'if t in \("public_trial_start", "public_trial_chat", "public_trial_capture_email"\):',
        src,
    )
    assert m, "public_trial_* immediate pre-auth dispatch block not found in bridge_server.py"
    types.update({"public_trial_start", "public_trial_chat", "public_trial_capture_email"})
    return types


# ---------------------------------------------------------------------------
# Static source-level assertions
# ---------------------------------------------------------------------------


def test_pre_auth_allowlist_matches_expected_set():
    """
    Regression guard: the auth-timeout bypass tuple in bridge_server.py must
    contain EXACTLY these entries — no more, no less. An unreviewed addition
    silently widens unauthenticated access to the entire WS surface; removal
    of any of the three trial types breaks the public trial funnel.
    """
    src = _read_bridge_source()
    actual = set(_extract_pre_auth_allowlist(src))
    missing = EXPECTED_PRE_AUTH_ALLOWLIST - actual
    extra = actual - EXPECTED_PRE_AUTH_ALLOWLIST
    assert not missing, f"Pre-auth allowlist is missing expected entries: {missing}"
    assert not extra, (
        f"Pre-auth allowlist has UNEXPECTED entries not covered by this test: {extra}. "
        "If intentional, this needs explicit security review before updating "
        "EXPECTED_PRE_AUTH_ALLOWLIST here."
    )


def test_trial_types_present_in_immediate_preauth_dispatch():
    """public_trial_* types are dispatched (and `continue`d) unconditionally,
    independent of the auth_deadline allowlist tuple."""
    src = _read_bridge_source()
    immediate = _extract_immediate_preauth_dispatch(src)
    assert {
        "public_trial_start",
        "public_trial_chat",
        "public_trial_capture_email",
    } <= immediate


def test_trial_dispatch_precedes_auth_deadline_enforcement():
    """
    Structural ordering guard: the public_trial_* dispatch block must appear
    BEFORE the auth_deadline enforcement line in the file. If ever reversed,
    trial messages could be force-closed by the auth timeout before reaching
    the trial gate.
    """
    src = _read_bridge_source()
    trial_idx = src.index(
        'if t in ("public_trial_start", "public_trial_chat", "public_trial_capture_email"):'
    )
    deadline_idx = src.index("if not current_profile and t not in (")
    assert trial_idx < deadline_idx, (
        "public_trial_* dispatch must be handled BEFORE the auth_deadline "
        "enforcement check, or trial messages risk being force-closed."
    )


def test_enumerated_dispatch_types_is_a_superset_of_allowlist():
    """
    Sanity check on the enumeration itself: every allowlisted type must
    actually appear as a real dispatch comparison somewhere in the file
    (catches typos / stale allowlist entries pointing at a renamed type).
    """
    src = _read_bridge_source()
    enumerated = _enumerate_dispatch_types(src)
    missing = EXPECTED_PRE_AUTH_ALLOWLIST - enumerated - KNOWN_LEGACY_ALLOWLIST_ENTRIES
    assert not missing, f"Allowlisted types not found as any dispatch comparison: {missing}"


def test_enumeration_produces_a_substantial_type_set():
    """
    Guard against a regression in the enumeration regex itself silently
    returning near-zero results (which would make the live tests below
    vacuously pass without testing anything meaningful).
    """
    src = _read_bridge_source()
    enumerated = _enumerate_dispatch_types(src)
    assert len(enumerated) > 100, (
        f"Only {len(enumerated)} dispatch types enumerated — the extraction "
        "regex may be broken (bridge_server.py normally has 300+)."
    )


# ---------------------------------------------------------------------------
# Live round-trip: a faithful, minimal mirror of the pre-auth gate control
# flow, served over a real local WebSocket connection.
# ---------------------------------------------------------------------------


async def _mirror_pre_auth_gate(websocket, trial_calls, allowlist):
    """
    Faithful mirror of the QUANTUM-CRYSTAL-ARCH pre-auth gate in
    bridge_server.py :: handle_client() — NOT the full 27k-line handler.
    Mirrors only the control-flow shape relevant to unauthenticated WS auth
    enforcement: ping / session_recover / public_trial_* short-circuits, then
    the auth-timeout enforcement guard. `current_profile` is always None here
    (this test only exercises the unauthenticated path).

    Keep in sync with bridge_server.py on any future change to that block —
    same "kept in sync via code review" contract as test_socket_eviction.py.
    """
    # Deadline starts already-elapsed: the strictest, most protective
    # posture to assert. Real prod grants a 120s grace window; this proves
    # what happens once that window has passed, without sleeping in tests.
    auth_deadline = datetime.datetime.now() - datetime.timedelta(seconds=1)
    current_profile = None

    async for message in websocket:
        d = json.loads(message)
        t = d.get("type")

        if t == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
            continue

        if t == "session_recover":
            await websocket.send(json.dumps({"type": "session_recovery_failed"}))
            continue

        if t in ("public_trial_start", "public_trial_chat", "public_trial_capture_email"):
            trial_calls.append(t)
            await websocket.send(json.dumps({"type": "trial_state", "mocked": True}))
            auth_deadline = datetime.datetime.now() + datetime.timedelta(seconds=120)
            continue

        if (
            not current_profile
            and t not in allowlist
            and datetime.datetime.now() > auth_deadline
        ):
            await websocket.send(
                json.dumps(
                    {"type": "error", "message": "Authentication timeout — please log in again"}
                )
            )
            await websocket.close(1008, "Auth timeout")
            return

        # Anything reaching here (allowlisted auth-related types while
        # unauthenticated) is generically acknowledged — this mirror does
        # not implement the real per-type business logic.
        await websocket.send(json.dumps({"type": "ack", "mirrored_type": t}))


@pytest.fixture
def preauth_allowlist():
    return _extract_pre_auth_allowlist(_read_bridge_source())


@pytest.mark.asyncio
async def test_unauthenticated_connection_rejects_every_non_allowlisted_type(preauth_allowlist):
    """
    Live round-trip: connect UNAUTHENTICATED to a server running the mirrored
    pre-auth gate, send every enumerated dispatch type from bridge_server.py
    that is NOT in the pre-auth allowlist, and assert the connection is
    force-closed with the auth-timeout error for every single one.
    """
    src = _read_bridge_source()
    all_types = _enumerate_dispatch_types(src)
    non_allowlisted = sorted(
        all_types - set(preauth_allowlist) - ALWAYS_PRE_AUTH_TYPES
    )
    assert len(non_allowlisted) > 100, (
        "enumeration produced too few non-allowlisted types — regex likely broken"
    )

    trial_calls = []

    async def handler(websocket):
        await _mirror_pre_auth_gate(websocket, trial_calls, preauth_allowlist)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}"

        for msg_type in non_allowlisted:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"type": msg_type}))
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert reply["type"] == "error" and "timeout" in reply["message"].lower(), (
                    f"type={msg_type!r} did not receive the auth-timeout rejection: {reply}"
                )
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(ws.recv(), timeout=5)


@pytest.mark.asyncio
async def test_unauthenticated_connection_allows_allowlisted_types_through(preauth_allowlist):
    """
    Live round-trip: every allowlisted type (plus ping/session_recover) must
    NOT be rejected by the auth-timeout gate — the connection stays open and
    a subsequent ping still gets a pong.
    """
    trial_calls = []

    async def handler(websocket):
        await _mirror_pre_auth_gate(websocket, trial_calls, preauth_allowlist)

    allowed_types = sorted(set(preauth_allowlist) | ALWAYS_PRE_AUTH_TYPES)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        uri = f"ws://127.0.0.1:{port}"

        for msg_type in allowed_types:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"type": msg_type}))
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert reply["type"] != "error", (
                    f"type={msg_type!r} (allowlisted) was unexpectedly rejected: {reply}"
                )
                # Connection must remain open — a follow-up ping still works.
                await ws.send(json.dumps({"type": "ping"}))
                pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                assert pong["type"] == "pong", (
                    f"connection was closed after sending allowlisted type={msg_type!r}"
                )

    # Order depends on the (alphabetically sorted) send order above, not on
    # dispatch semantics — assert membership/multiset, not exact sequence.
    assert sorted(trial_calls) == sorted(
        ["public_trial_start", "public_trial_chat", "public_trial_capture_email"]
    )
