# Agentic Phase 5b — Human Adversarial Walk Checklist

**Status:** signed — `ENABLE_SYMBOLIC_VERIFIER` flip authorized 2026-07-21

| Gate | Question | Pass |
|---|---|---|
| Key | Are StateSymbol fields wired into audit_metadata? | [x] |
| Lifecycle | Is regen capped at 1 for symbolic violations? | [x] |
| Surface | Does crisis path skip regeneration? | [x] |
| Seam | Are distress+proud / admin_only / missing-988 caught? | [x] |
| Time | Is dual-write logged to skyeye_activity? | [x] |

**Evidence:** `PYTHONPATH=backend pytest backend/tests/test_symbolic_verifier_seams.py` → **8 passed** (local, 2026-07-20). Code landed at `fa8ab3b9`.

**Flag:** `ENABLE_SYMBOLIC_VERIFIER` — [x] approved to flip

**Reviewers:** Kristy Moore · Nathan Nevedal **Date:** 2026-07-21
