# Agentic Phase 4 — Human Adversarial Walk Checklist

**Status:** adversarial walk signed — production flip blocked until Phase 0+1 proven; coach-alert staging first

| Gate | Question | Pass |
|---|---|---|
| Key | Does self-monitor resolve coach via assigned_coach fields? | [x] |
| Lifecycle | Are thresholds conservative (no single-day alerts)? | [x] |
| Surface | Is coach alert default; client touch opt-in separate? | [x] |
| Seam | Does optional touch call `can_send_proactive_touch`? | [x] |
| Time | Is daily cycle sufficient (not 30-min spam)? | [x] |

**Flags:** `ENABLE_SELF_MONITOR_AGENT` + `ENABLE_SELF_MONITOR_COACH_ALERT` prod **true** (2026-07-20); `ENABLE_SELF_MONITOR_TOUCH` remains **false** until consent population (checklist 4.4).

**Reviewer:** Nathan Nevedal **Date:** 2026-07-17 (prod coach-alert flip 2026-07-20)
