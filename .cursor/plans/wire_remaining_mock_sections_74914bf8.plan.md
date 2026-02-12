---
name: Wire remaining mock sections
overview: Wire the Usage Breakdown and Throttle Control sections in the_eye.html to real backend data, replacing the remaining hardcoded values.
todos:
  - id: usage-breakdown-wire
    content: Add IDs to Usage Breakdown elements and populate from displayStats() using token split estimates
    status: completed
  - id: throttle-dynamic
    content: Make Throttle Control slider, status badge, and tier toggles react to live budget percentage
    status: completed
isProject: false
---

# Wire Remaining Mock Sections in the_eye.html

## What is still mock

### 1. Usage Breakdown (lines 254-258)

The three usage items (Voice $423.50, Text $312.80, Vision $110.93) are hardcoded HTML. The backend `admin_get_stats` response includes `today_tokens` as a single number but does **not** currently split tokens by modality (voice vs text vs vision).

**Fix:** Add `id` attributes to the usage amount and token count elements, then compute estimated splits from the total token count in `displayStats()` (same approach used in `the_eye_tokens.html` which already does this). When the backend eventually returns per-modality breakdown, the IDs are ready.

### 2. Throttle Control (lines 260-275)

The slider position, "NORMAL MODE" badge, and tier toggle buttons are static. The backend does not currently have a throttle API. However, the frontend can reflect current throttle state based on budget consumption percentage (which IS live):

- Budget < 70%: Full Features, NORMAL MODE
- Budget 70-85%: Balanced, BALANCED MODE
- Budget 85-95%: Text Only, THROTTLED
- Budget > 95%: Emergency, EMERGENCY

**Fix:** Update `displayStats()` to dynamically set the slider thumb position, status badge text/color, and tier toggle button states based on the live budget percentage.

### 3. Community Nevedal State -- NOT mock

This section is already wired to `admin_get_cohort_stats`. The zeros shown ("HIGH 100%" anxiety, "LOW 0%" stability) are correct computed values when `avg_c_emo = 0` and no sessions exist. No change needed -- it will populate correctly once real session data flows through the cohort stats handler.

## Changes

All changes are in [dashboard/the_eye.html](dashboard/the_eye.html):

- Add IDs to the 6 usage breakdown values (3 amounts + 3 token counts)
- In `displayStats()`, compute voice/text/vision token splits from total and update the usage elements
- In `displayStats()`, set throttle slider position, status badge, and tier toggle states based on budget percentage

