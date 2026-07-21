# Agentic Phase 5b — Human Adversarial Walk Checklist

**Status:** automated gates PASS (2026-07-20) — human sign-off still required before flag flip

| Gate | Question | Pass |
|---|---|---|
| Key | Are StateSymbol fields wired into audit_metadata? | [x] |
| Lifecycle | Is regen capped at 1 for symbolic violations? | [x] |
| Surface | Does crisis path skip regeneration? | [x] |
| Seam | Are distress+proud / admin_only / missing-988 caught? | [x] |
| Time | Is dual-write logged to skyeye_activity? | [x] |

**Evidence:** `PYTHONPATH=backend pytest backend/tests/test_symbolic_verifier_seams.py` → **8 passed** (local, 2026-07-20).

**Code (pending commit):** `therapeutic_controller.py` (state_symbol + crisis_exempt + 988/scope), `crystal_recall_bridge.py` (`crystal_scopes`), `bridge_server.py` (+12 lines scopes/crisis_exempt).

**Flag:** `ENABLE_SYMBOLIC_VERIFIER` — ☐ approved to flip (two humans + staging soak; keep **false** on prod until then)

**Reviewer:** _______________ **Date:** _______________
