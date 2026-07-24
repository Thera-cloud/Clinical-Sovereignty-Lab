# Ticket: test-infra — event-loop teardown hardening

**Status:** Open
**Priority:** P2 — non-blocking, but re-arms silently
**Filed:** 2026-07-09
**Related:** WIRE_WHAT_EXISTS Commits 3, 4, 5, 6 (`docs/WIRING_AUDIT_REPORT.md`); the 29-failure test-pollution incident fixed in the same commit series

## Problem

`unittest.IsolatedAsyncioTestCase` calls `asyncio.set_event_loop(None)` on
teardown. That sets asyncio's internal `_set_called` flag and disables
`get_event_loop()`'s auto-create fallback for the **rest of the pytest
session** — not just the current module. Any later-collected suite that
still calls the legacy `asyncio.get_event_loop().run_until_complete(...)`
pattern then crashes with `RuntimeError: There is no current event loop`,
depending on pytest's collection/alphabetical order.

This is exactly what happened during the WIRE_WHAT_EXISTS task: four new
`IsolatedAsyncioTestCase`-based files landed
(`test_checkin_backoff.py`, `test_digest_shadow_row.py`,
`test_shadow_weighting_no_update.py`, `test_wiring_smoke_e2e.py`) and
broke 29 previously-passing tests in three unrelated suites purely
through import/collection-order side effects — not through any change to
production behavior. Confirmed via `git stash` → clean-tree baseline
(42/42 passing) → `git stash pop` → same 29 failures reproduced.

**The fix that shipped is a convention, not a guard.** Each of the four
new files carries its own `tearDownModule()` that manually restores a
fresh event loop:

```python
def tearDownModule():
    """Restore a fresh main-thread event loop after IsolatedAsyncioTestCase
    runs. ..."""
    import asyncio
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
```

This works today because all four files remembered to add it. It does
**not** work for the next contributor who adds a fifth
`IsolatedAsyncioTestCase` file without copying the boilerplate — the same
29-test-style failure returns, attributed to whatever suite pytest
happens to collect next, with no obvious connection to the actual cause.

### Scope correction

The original note assumed three legacy suites were exposed
(`test_counter_intelligence.py`, `test_cross_member_attribution.py`,
`test_family_system_field.py` — the three that failed in the incident).
A repo-wide grep for the deprecated pattern turns up **five**:

```
backend/tests/test_counter_intelligence.py
backend/tests/test_cross_member_attribution.py
backend/tests/test_family_system_field.py
backend/tests/test_hardening_scenarios.py
backend/tests/test_predictability_continuity_cap.py
```

`test_hardening_scenarios.py` and `test_predictability_continuity_cap.py`
didn't fail in the incident only because pytest's collection order didn't
put them after a pollinating module that run — they carry the identical
latent fragility and will fail the same way once collection order shifts
(e.g. a new test file alphabetically between them and the polluter).

## Proposal (pick one)

**Option A — conftest.py autouse fixture (preferred).**
`backend/tests/conftest.py` already exists with shared fixtures
(`fake_pool`, `fake_redis`, `fake_conn`) but no event-loop management. Add
a session- or module-scoped autouse fixture that restores a fresh event
loop after every module, regardless of test style:

```python
@pytest.fixture(autouse=True, scope="module")
def _restore_event_loop_after_module():
    yield
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
```

This fixes the whole suite once. No per-file discipline required. The
four `tearDownModule()` copies become redundant (but harmless) and can be
deleted once the fixture is proven equivalent.

**Option B — migrate the five legacy suites off `get_event_loop()`.**
Replace `asyncio.get_event_loop().run_until_complete(...)` /
`loop = asyncio.get_event_loop(); loop.run_until_complete(...)` with
`asyncio.run(...)` (Python 3.9+ compatible, no ambient loop dependency) in
all five files listed above. Removes the fragility at the source instead
of papering over it, but requires touching five files including
`test_counter_intelligence.py`, which has ~40+ call sites — larger diff,
more regression surface for a non-blocking cleanup.

**Recommendation:** Option A first (small, low-risk, fixes it for every
future file including ones not yet written), Option B opportunistically
when any of the five files is touched for an unrelated reason.

## Acceptance criteria

1. A new `IsolatedAsyncioTestCase`-based test file, added with **no**
   `tearDownModule()`, does not break any other suite in the same
   `pytest` run.
2. `bash backend/scripts/run_ci_tests.sh` still passes in full after the
   fixture/migration lands (currently 1200/1200).
3. If Option A: the four existing `tearDownModule()` blocks may be
   deleted as a follow-up once verified redundant (not required for this
   ticket to close).
4. If Option B: no file in the five-file list above calls
   `asyncio.get_event_loop()` directly.

## Out of scope

- Rewriting the four new files' test style (they can stay
  `IsolatedAsyncioTestCase`; the fixture, not the style, is the fix).
- Any change to production code — this is test-infrastructure only.
