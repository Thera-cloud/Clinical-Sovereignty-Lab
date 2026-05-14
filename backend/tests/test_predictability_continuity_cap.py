"""Unit tests for `_resolve_predictability_continuity_cap` (Phase 3 v1.3 — Gap 4).

Per Note 2 (Phase 3 build): the predictability_continuity register's clinical
purpose — sustained predictable presence as the corrective mismatch — fails if
Nate's response length swings unpredictably while the register is active. This
function reads the *prior turn's actual emitted token count* from
`conversation_history`, applies a floor (so single-word ack turns don't
collapse the cap to zero), and returns the new cap.

These tests pin the resolver's contract against the four high-stakes cases:
    - normal prior turn (cap matches)
    - prior turn was very short (floor applies)
    - no prior turn exists (floor applies)
    - DB error path (floor applies, fail-closed)

Test surface is intentionally small and synchronous-via-asyncio.run() to
avoid pulling pytest-asyncio. Invoke directly:

    python3 backend/tests/test_predictability_continuity_cap.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any, List, Optional

# Repo-relative import shim (mirrors pattern used by other 2A/2B/2C tests).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from app.services.therapeutic_controller import (  # noqa: E402
    PREDICTABILITY_CONTINUITY_FLOOR_TOKENS,
    _resolve_predictability_continuity_cap,
)


# ─────────── Lightweight asyncpg pool/conn fakes ───────────

class _FakeRow:
    def __init__(self, value: Optional[int]) -> None:
        self._value = value

    def __getitem__(self, key: str) -> Optional[int]:
        if key == "word_count_ai":
            return self._value
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if key == "word_count_ai":
            return self._value if self._value is not None else default
        return default


class _FakeConn:
    def __init__(self, return_value: Optional[int], raise_exc: Optional[BaseException] = None) -> None:
        self._return_value = return_value
        self._raise = raise_exc
        self.queries: List[str] = []

    async def fetchrow(self, query: str, *args: Any) -> Optional[_FakeRow]:
        if self._raise is not None:
            raise self._raise
        self.queries.append(query)
        if self._return_value is None:
            return None
        return _FakeRow(self._return_value)


class _FakeAcquireCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquireCtx:
        return _FakeAcquireCtx(self._conn)


# ─────────── Tests ───────────

def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


def test_normal_prior_turn_uses_word_count_to_token_estimate() -> None:
    """200 words → ~266 tokens (200 / 0.75). Above floor → returns the
    estimated cap unchanged."""
    pool = _FakePool(_FakeConn(return_value=200))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=80,
    ))
    expected = int(round(200 / 0.75))
    assert cap == expected, f"expected {expected}, got {cap}"


def test_short_prior_turn_falls_back_to_floor() -> None:
    """Prior turn was a 5-word ack → ~6 tokens. Floor must apply."""
    pool = _FakePool(_FakeConn(return_value=5))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=80,
    ))
    assert cap == 80, f"expected floor=80, got {cap}"


def test_no_prior_turn_falls_back_to_floor() -> None:
    """First turn ever (no prior row) → floor applies."""
    pool = _FakePool(_FakeConn(return_value=None))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="brand_new_user", db_pool=pool, floor=80,
    ))
    assert cap == 80, f"expected floor=80, got {cap}"


def test_db_error_falls_back_to_floor_fail_closed() -> None:
    """DB exception → fail-closed to floor, never raise to caller."""
    pool = _FakePool(_FakeConn(return_value=None, raise_exc=RuntimeError("simulated db failure")))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=80,
    ))
    assert cap == 80, f"expected floor=80 on db error, got {cap}"


def test_none_db_pool_uses_scaled_floor_for_heavy_long_input() -> None:
    lisa_like = "x" * 2000 + " sexual assault grand jury "
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=None, floor=80, user_text=lisa_like,
    ))
    assert cap >= 400


def test_no_prior_row_uses_scaled_floor_when_input_heavy() -> None:
    lisa_like = "y" * 2100 + " trauma testimony "
    pool = _FakePool(_FakeConn(return_value=None))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=80, user_text=lisa_like,
    ))
    assert cap >= 400


def test_default_floor_constant_is_80() -> None:
    """Floor constant exported from module = 80 (per Phase 3 spec)."""
    assert PREDICTABILITY_CONTINUITY_FLOOR_TOKENS == 80


def test_custom_floor_is_respected() -> None:
    """Caller can pass a different floor (e.g., trafficking cohort 120)."""
    pool = _FakePool(_FakeConn(return_value=10))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=120,
    ))
    assert cap == 120, f"expected custom floor=120, got {cap}"


def test_high_word_count_above_floor_passes_through() -> None:
    """500 words → ~666 tokens. Above floor → returns full estimate."""
    pool = _FakePool(_FakeConn(return_value=500))
    cap = asyncio.run(_resolve_predictability_continuity_cap(
        user_id="alice", db_pool=pool, floor=80,
    ))
    expected = int(round(500 / 0.75))
    assert cap == expected, f"expected {expected}, got {cap}"


# ─────────── Direct invocation ───────────

if __name__ == "__main__":
    import traceback
    tests = [
        ("test_normal_prior_turn_uses_word_count_to_token_estimate",
         test_normal_prior_turn_uses_word_count_to_token_estimate),
        ("test_short_prior_turn_falls_back_to_floor",
         test_short_prior_turn_falls_back_to_floor),
        ("test_no_prior_turn_falls_back_to_floor",
         test_no_prior_turn_falls_back_to_floor),
        ("test_db_error_falls_back_to_floor_fail_closed",
         test_db_error_falls_back_to_floor_fail_closed),
        ("test_none_db_pool_falls_back_to_floor",
         test_none_db_pool_falls_back_to_floor),
        ("test_default_floor_constant_is_80",
         test_default_floor_constant_is_80),
        ("test_custom_floor_is_respected",
         test_custom_floor_is_respected),
        ("test_high_word_count_above_floor_passes_through",
         test_high_word_count_above_floor_passes_through),
        ("test_none_db_pool_uses_scaled_floor_for_heavy_long_input",
         test_none_db_pool_uses_scaled_floor_for_heavy_long_input),
        ("test_no_prior_row_uses_scaled_floor_when_input_heavy",
         test_no_prior_row_uses_scaled_floor_when_input_heavy),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {name}: {e}")
            failed += 1
        except Exception:
            print(f"ERROR {name}:")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
