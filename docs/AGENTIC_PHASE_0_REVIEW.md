# Agentic Phase 0 — Human Adversarial Walk Checklist

**Status:** staging bake signed — production flip pending 72h soak

| Gate | Question | Pass |
|---|---|---|
| Key | Does identity resolution use username when gate receives hardware_id? | ☑ |
| Lifecycle | Are skipped_* touch statuses written for denied deliveries? | ☑ |
| Surface | Do all four touch producers call `can_send_proactive_touch`? | ☑ |
| Seam | Do seam tests use mixed identity keys (not same-key only)? | ☑ |
| Time | Are quiet-hours denials re-evaluated on next cycle (not queued)? | ☑ |

**Evidence:** `scripts/staging_smoke_agentic.sh phase0` on GREEN; seam tests `test_proactive_touch_seams.py`, `test_touch_adaptation_asymmetry.py` green.

**Staging flag:** `ENABLE_PROACTIVE_TOUCH_POLICY=true` on `nate_staging_backend` only (`staging_phase_flags.sh phase0 on`).

**Reviewer 1:** Nathan Nevedal **Date:** 2026-07-14

**Reviewer 2 (required for prod flip):** Kristy Moore **Date:** 2026-07-14
