# Ticket: CHAT-HISTORY-WITHIN-SESSION — user correction & session referent repair

**Status:** Open  
**Priority:** P1 — error-repair layer for main chat  
**Blocks:** Full seven-layer pass (Ryan turn 7, Lisa dissatisfaction turns)  
**Related:** `coaching_scope_gate_plan.md` Gap 3; `docs/lisa_transcript_investigation_2026-05-19.md`

## Problem

Scope gate and arc address **breadth/pacing**, not:

- User corrections (“that’s wrong”, “I didn’t say Lana”, “you made a mistake”)
- Within-session referent loss (Nate contradicts prior turns in same WebSocket session)
- Crystal/history bleed into wrong relational context

`NateResponseValidator` / Layer 8 factual grounding target **Nate assertions**, not **user pushback**. Bridge therapy path has **no** validator wiring (`bridge_server.py` — no `NateResponseValidator` import).

## Acceptance criteria

1. Audit: document which in-session turns are included in `system_prompt` / narrative block for `process_interaction()` (current session buffer vs PG `conversation_history` only).
2. Detect user correction intent (regex + optional classifier tag); do not conflate with dissatisfaction-only.
3. On correction: prefer acknowledge + re-anchor to last N in-session user turns; block crystal recall that contradicts explicit correction in same session.
4. Regression test: simulated 7-turn thread where turn 7 corrects turn 6 entity — response must not repeat wrong entity.
5. Optional audit row: `skyeye_activity` type `session_correction_handled` (no PII in content).

## Files (estimate)

- `backend/app/websocket/bridge_server.py` — session turn buffer audit + correction handler hook (feature-flagged)
- `backend/app/services/little_nate_adaptive.py` or new `session_referent_repair.py`
- `backend/tests/test_session_referent_repair.py`

## Out of scope

- Tier 6 / stabilization template text changes
- Sensitive Bridge 17-step path
