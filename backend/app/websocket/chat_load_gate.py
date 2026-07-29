"""
In-flight chat turn counter — lets autonomous learn yield to live chat.

Bridge chat and autonomous LearnMode share the bridge event loop. When a
learn cycle runs for 100s+ during nate_query, clients see multi‑10s stalls.
This gate is advisory: learn skips/aborts when count > 0; chat never waits.
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import AsyncIterator, Iterator

# Thread-safe: learn loop and WS handlers may touch from same loop; belt+suspenders.
_lock = threading.Lock()
_in_flight = 0


def chat_in_flight() -> bool:
    with _lock:
        return _in_flight > 0


def chat_in_flight_count() -> int:
    with _lock:
        return _in_flight


def chat_turn_begin() -> None:
    global _in_flight
    with _lock:
        _in_flight += 1


def chat_turn_end() -> None:
    global _in_flight
    with _lock:
        if _in_flight > 0:
            _in_flight -= 1


@contextlib.contextmanager
def chat_busy() -> Iterator[None]:
    chat_turn_begin()
    try:
        yield
    finally:
        chat_turn_end()


@contextlib.asynccontextmanager
async def chat_busy_async() -> AsyncIterator[None]:
    chat_turn_begin()
    try:
        yield
    finally:
        chat_turn_end()


async def wait_while_chat_busy(poll_s: float = 0.25, max_wait_s: float = 120.0) -> bool:
    """
    Cooperative wait for learn mode. Returns True if clear to proceed,
    False if still busy after max_wait_s (caller should skip the cycle).
    """
    elapsed = 0.0
    while chat_in_flight():
        if elapsed >= max_wait_s:
            return False
        await asyncio.sleep(poll_s)
        elapsed += poll_s
    return True
