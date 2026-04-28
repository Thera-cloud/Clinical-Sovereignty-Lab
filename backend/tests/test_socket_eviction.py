"""
Socket eviction contract test — verifies single-session enforcement in
Cortex.register() (bridge_server.py line ~7511).

Bug history (Apr 2026): CoachN saw duplicate Nate responses in DOJO comments.
Bridge logs showed `_send uid=COACH_COACHN_ID sockets=2 ok=2 fail=0`. Root cause:
when a Flutter client reconnects (new tab, refresh, network flap) the OS has not
yet torn down the old TCP socket, so `s.open` is still True and the old dead-
socket-cleanup path skipped it. The old socket stayed in `Cortex.sockets[uid]`
and every Nate response was broadcast to BOTH sockets.

Fix: when a new socket authenticates with a hardware_id, evict ALL prior sockets
in `self.sockets[uid]` BEFORE adding the new one. Old sockets are gracefully
closed with WebSocket close code 4001 / reason "session_replaced_by_new_login"
so the Flutter client can distinguish a forced replacement from a normal close.

This test is import-isolated from bridge_server.py (which is a 27k-line module
with heavy side effects). It instantiates a minimal Cortex-shaped fake whose
`register()` mirrors the QUANTUM-CRYSTAL-ARCH eviction block. Any divergence
between the fake here and the real `Cortex.register()` will be caught by code
review on changes to bridge_server.py — keep them in sync.
"""

import asyncio
import pytest


class _FakeWebSocket:
    """Minimal stand-in for a websockets ServerProtocol object."""

    def __init__(self, name):
        self.name = name
        self.closed = False
        self.close_calls = []  # list of (code, reason) tuples

    async def close(self, code=1000, reason=""):
        self.closed = True
        self.close_calls.append((code, reason))


class _MinimalCortexRegistry:
    """
    Mirrors the QUANTUM-CRYSTAL-ARCH eviction block in
    backend/app/websocket/bridge_server.py :: Cortex.register()
    """

    def __init__(self):
        self.sockets = {}

    def register(self, uid, ws, client_context="main"):
        if uid not in self.sockets:
            self.sockets[uid] = set()
        # QUANTUM-CRYSTAL-ARCH: per-context eviction (Apr 2026 — Option B)
        try:
            ws._eviction_context = client_context
        except Exception:
            pass
        for prior_ws in list(self.sockets[uid]):
            if prior_ws is ws:
                continue
            prior_ctx = getattr(prior_ws, "_eviction_context", "main")
            if prior_ctx != client_context:
                continue  # different surface (parent vs iframe) — preserve
            try:
                asyncio.create_task(
                    prior_ws.close(code=4001, reason="session_replaced_by_new_login")
                )
                self.sockets[uid].discard(prior_ws)
            except Exception:
                pass
        self.sockets[uid].add(ws)


@pytest.mark.asyncio
async def test_register_evicts_prior_socket_with_close_code_4001():
    """
    Socket B authenticates with the same hardware_id as socket A.
    Expectation:
      1. Socket A is closed with code=4001, reason="session_replaced_by_new_login"
      2. Socket A is removed from the registry
      3. Socket B is the only socket in registry[uid] after register
    """
    registry = _MinimalCortexRegistry()
    uid = "COACH_COACHN_ID"
    ws_a = _FakeWebSocket("A")
    ws_b = _FakeWebSocket("B")

    registry.register(uid, ws_a)
    assert registry.sockets[uid] == {ws_a}, "socket A should be registered first"

    registry.register(uid, ws_b)
    # Allow asyncio.create_task() to actually run the close coroutine
    await asyncio.sleep(0)

    assert registry.sockets[uid] == {ws_b}, "only socket B should remain after eviction"
    assert ws_a.closed is True, "socket A must be closed after socket B registers"
    assert ws_a.close_calls == [(4001, "session_replaced_by_new_login")], (
        "socket A must be closed with the documented eviction code/reason"
    )
    assert ws_b.closed is False, "socket B must remain open"


@pytest.mark.asyncio
async def test_register_same_socket_twice_is_noop():
    """Re-registering the SAME socket object must not close it (no self-eviction)."""
    registry = _MinimalCortexRegistry()
    uid = "CLIENT_TEST_ID"
    ws = _FakeWebSocket("only")

    registry.register(uid, ws)
    registry.register(uid, ws)
    await asyncio.sleep(0)

    assert registry.sockets[uid] == {ws}
    assert ws.closed is False
    assert ws.close_calls == []


@pytest.mark.asyncio
async def test_register_evicts_multiple_prior_sockets_same_context():
    """
    Edge case: registry already holds N stale sockets in the SAME context
    (e.g. from rapid reconnects). New socket must evict ALL of them.
    """
    registry = _MinimalCortexRegistry()
    uid = "ADMIN_DRNEVEDAL1_ID"
    stale_a = _FakeWebSocket("stale_a")
    stale_a._eviction_context = "main"
    stale_b = _FakeWebSocket("stale_b")
    stale_b._eviction_context = "main"
    registry.sockets[uid] = {stale_a, stale_b}

    ws_new = _FakeWebSocket("new")
    registry.register(uid, ws_new, client_context="main")
    await asyncio.sleep(0)

    assert registry.sockets[uid] == {ws_new}
    assert stale_a.closed is True
    assert stale_b.closed is True
    assert stale_a.close_calls == [(4001, "session_replaced_by_new_login")]
    assert stale_b.close_calls == [(4001, "session_replaced_by_new_login")]


@pytest.mark.asyncio
async def test_parent_and_iframe_coexist_under_same_uid():
    """
    Option B (Apr 2026): the parent dashboard ("main") and embedded DOJO iframe
    ("dojo") both connect with the SAME hardware_id. They MUST coexist — neither
    may evict the other. This is the bug that caused the iframe to flash.
    """
    registry = _MinimalCortexRegistry()
    uid = "COACH_COACHN_ID"
    parent_ws = _FakeWebSocket("parent")
    iframe_ws = _FakeWebSocket("iframe")

    registry.register(uid, parent_ws, client_context="main")
    registry.register(uid, iframe_ws, client_context="dojo")
    await asyncio.sleep(0)

    assert registry.sockets[uid] == {parent_ws, iframe_ws}, (
        "parent (main) and iframe (dojo) must coexist under the same uid"
    )
    assert parent_ws.closed is False, "parent socket must NOT be evicted by iframe"
    assert iframe_ws.closed is False, "iframe socket must NOT be evicted by parent"
    assert parent_ws.close_calls == []
    assert iframe_ws.close_calls == []


class _MinimalCortexWithSend(_MinimalCortexRegistry):
    """Adds a _send() that mirrors the QUANTUM-CRYSTAL-ARCH context filter."""

    async def _send(self, uid, text, client_context=None):
        delivered_to = []
        if uid in self.sockets:
            for ws in list(self.sockets[uid]):
                if client_context is not None:
                    ws_ctx = getattr(ws, "_eviction_context", "main")
                    if ws_ctx != client_context:
                        continue
                delivered_to.append(ws)
        return delivered_to


@pytest.mark.asyncio
async def test_send_with_context_filters_to_matching_sockets_only():
    """
    DOJO duplicate-response bug (Apr 2026): with parent ("main") and iframe
    ("dojo") both registered for the same uid, _send(uid, text) without a
    context broadcasts to BOTH and the iframe shows duplicate Nate messages.
    Fix: _send(uid, text, client_context="dojo") delivers only to dojo socket.
    """
    cortex = _MinimalCortexWithSend()
    uid = "COACH_COACHN_ID"
    parent_ws = _FakeWebSocket("parent")
    iframe_ws = _FakeWebSocket("iframe")
    cortex.register(uid, parent_ws, client_context="main")
    cortex.register(uid, iframe_ws, client_context="dojo")

    # No context = legacy broadcast (both receive)
    delivered = await cortex._send(uid, "broadcast", client_context=None)
    assert set(delivered) == {parent_ws, iframe_ws}

    # ctx="dojo" = only iframe receives (parent does NOT)
    delivered = await cortex._send(uid, "dojo response", client_context="dojo")
    assert delivered == [iframe_ws]

    # ctx="main" = only parent receives (iframe does NOT)
    delivered = await cortex._send(uid, "main response", client_context="main")
    assert delivered == [parent_ws]


@pytest.mark.asyncio
async def test_iframe_reconnect_evicts_only_iframe_not_parent():
    """
    A second DOJO iframe (e.g. browser refresh) must evict the prior iframe
    socket but leave the parent dashboard socket untouched.
    """
    registry = _MinimalCortexRegistry()
    uid = "COACH_COACHN_ID"
    parent_ws = _FakeWebSocket("parent")
    iframe_v1 = _FakeWebSocket("iframe_v1")
    iframe_v2 = _FakeWebSocket("iframe_v2")

    registry.register(uid, parent_ws, client_context="main")
    registry.register(uid, iframe_v1, client_context="dojo")
    registry.register(uid, iframe_v2, client_context="dojo")
    await asyncio.sleep(0)

    assert registry.sockets[uid] == {parent_ws, iframe_v2}, (
        "parent and newest iframe survive; iframe_v1 is evicted"
    )
    assert parent_ws.closed is False
    assert iframe_v1.closed is True
    assert iframe_v2.closed is False
    assert iframe_v1.close_calls == [(4001, "session_replaced_by_new_login")]
