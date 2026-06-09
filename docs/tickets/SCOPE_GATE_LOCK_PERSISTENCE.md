# Ticket: Scope-gate lock persistence when arc fires

**Status:** Open  
**Priority:** P1 — blocks sticky stabilization after arc trigger  
**Blocks:** Global `ENABLE_*` flip (with clinical sign-off)  
**Related:** `.cursor/plans/coaching_scope_gate_plan.md` Gap 6; `docs/40_turn_acceptance_2026-05-18_r3.md` turn 8→9 regression

## Problem

When `ENABLE_ARC_MEMORY=true`, `bridge_server.py` sets `adaptive_payload["direct_response"]` **after** `prepare_response()` but does **not** set `SessionState.scope_lock_since_turn`.

Continuation enforcement in `evaluate_scope_gate()` keys off `scope_lock_since_turn` set only inside `prepare_response()` when the **scope gate** (not arc) returns `direct_response`.

**Observed:** Turn 8 stabilization → turn 9 back to accommodating + LLM (acceptance r3). GREEN logs show repeated `>>> [ARC] … triggered=True` when `ENABLE_ARC_MEMORY` is off because `mark_arc_triggered()` never runs.

## Acceptance criteria

1. When arc sets `direct_response` on the payload, `scope_lock_since_turn` is set on `_ad_state` in the same turn.
2. Turns after arc fire use continuation branch until unlock phrase or session clear.
3. `>>> [SCOPE_GATE]` shows `lock=<turn>` after arc fire when flags on.
4. pytest + one turn in `run_40_turn_acceptance.py` shows `direct_response` true on turn N+1 after arc fire (same session).

## Files (estimate)

- `backend/app/websocket/bridge_server.py` — set lock when arc injects `direct_response` (~5 lines, `# QUANTUM-CRYSTAL-ARCH`)
- Optional: `backend/tests/test_coaching_scope_gate.py` — arc+lock integration

## Out of scope

- Per-user canary flags
- Sensitive Bridge enrollment path
