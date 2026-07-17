# Agentic Phase 4 — Human Adversarial Walk Checklist

**Status:** adversarial walk signed — production flip blocked until Phase 0+1 proven; coach-alert staging first

| Gate | Question | Pass |
|---|---|---|
| Key | Does self-monitor resolve coach via assigned_coach fields? | [x] |
| Lifecycle | Are thresholds conservative (no single-day alerts)? | [x] |
| Surface | Is coach alert default; client touch opt-in separate? | [x] |
| Seam | Does optional touch call `can_send_proactive_touch`? | [x] |
| Time | Is daily cycle sufficient (not 30-min spam)? | [x] |

**Flags:** `ENABLE_SELF_MONITOR_COACH_ALERT`, `ENABLE_SELF_MONITOR_TOUCH` — staging walk approved; prod flip not yet authorized (flip coach-alert separately from touch)

**Reviewer:** Nathan Nevedal **Date:** 2026-07-17
