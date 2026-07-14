# Agentic Phase 1 — Human Adversarial Walk Checklist

**Status:** staging bake signed — production flip blocked until Phase 0 prod stable ≥72h

| Gate | Question | Pass |
|---|---|---|
| Key | Are commitments keyed consistently with checkin/touch log? | ☑ |
| Lifecycle | Is trial/anonymous extraction blocked at write time? | ☑ |
| Surface | Can users view/edit/dismiss commitments in UI? | ☑ |
| Seam | Does sensitivity=sensitive block automated push only? | ☑ |
| Time | Does commitment agent respect shared global budget? | ☑ |

**Evidence:** Flutter `nate_commitments_screen.dart` + settings toggle deployed; `staging_phase_flags.sh phase1 on`; staging smoke phase1.

**Staging flags:** `ENABLE_PROACTIVE_TOUCH_POLICY=true`, `ENABLE_PROACTIVE_COMMITMENTS=true` on `nate_staging_backend` only.

**Reviewer 1:** Nathan Nevedal **Date:** 2026-07-14

**Reviewer 2 (required for prod flip):** Kristy Moore **Date:** 2026-07-14
