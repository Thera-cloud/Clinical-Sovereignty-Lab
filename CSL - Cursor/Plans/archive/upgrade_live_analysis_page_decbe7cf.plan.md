---
name: Upgrade Live Analysis Page
overview: Upgrade nevedal_lab_live.html to incorporate the rich features from nevedal_lab_old.html while preserving the live real-time WebSocket wiring that the new page already has.
todos:
  - id: header-upgrade
    content: "Upgrade header: add IRB badge, Export Data, Generate Report buttons, update title to NEVEDAL RESEARCH LABORATORY"
    status: completed
  - id: left-panel
    content: "Rebuild left panel: dyad selection (Subject A+B), filter tabs, rich subject list from admin_get_users, cross-reference matrix from admin_get_family_metrics"
    status: completed
  - id: formula-banner
    content: Add Master Formula banner with CSS-rendered Nevedal equation and COMPUTING LIVE badge
    status: completed
  - id: center-gauges
    content: "Side-by-side layout: C_emo gauge with needle + component variables (keep live WebSocket updating from nevedal_subscribe)"
    status: completed
  - id: interpretation
    content: Add dynamic Current State Interpretation section that generates text based on current variable values
    status: completed
  - id: biometric-mapping
    content: "Add dual-subject Biometric Signal Mapping panel: voice biometrics (HRV, Respiratory, Vocal, EDA) + Patent 4 visual biometrics (facial affect valence/arousal, gaze contact ratio, body lean angle, engagement score, primary emotion, d_extended)"
    status: completed
  - id: patent2-live-panel
    content: "Add Patent 2 real-time indicators: Crisis Perception (objective vs expressed distress, perception baseline), Shame Detection (shame_index, channels), PMB (reconsolidation readiness, reactivity signature) with confidence tier color coding"
    status: completed
  - id: patent3-alerts
    content: "Add Patent 3 live alerts panel: escalation detection with severity, ventriloquism detection alerts, EFT negative cycle markers, reconsolidation window status (open/closed + time remaining)"
    status: completed
  - id: trajectory-chart
    content: Replace placeholder timeline with Chart.js live-updating trajectory graph (C_emo, p_ent, CEE windows)
    status: completed
  - id: cee-window-detail
    content: "Add CEE Window threshold detail: show which conditions are met (p_ent >= threshold, d <= threshold, gamma_env <= threshold, E_G >= threshold, sustained duration) with checkmarks"
    status: completed
  - id: right-panel
    content: "Rebuild right panel: Active Research Study stats, Report Generator links, 12-week Trends, Session History, Ethics Notice"
    status: completed
  - id: websocket-wiring
    content: "Wire all panels to backend: nevedal_subscribe for live stream, admin_get_users for subjects, admin_get_user_metrics for biometrics, admin_get_cohort_stats for study stats, nevedal_get_history for session history, admin_get_client_metrics for Patent 2 data"
    status: completed
isProject: false
---

# Upgrade Live Analysis Page to Match Old Page Quality

## Current State

The [current live page](dashboard/nevedal_lab_live.html) (555 lines) is functional with real-time `nevedal_subscribe` WebSocket streaming, but is visually sparse compared to the [old page](dashboard/nevedal_lab_old.html) (1060 lines), which has a polished research lab aesthetic with many features.

**The "Back to Lab" button on the current live page literally links to `nevedal_lab_old.html**`, confirming the old page was the intended "main" page.

## Feature Gap Analysis

### Missing from Header

- IRB Approved badge (`IRB APPROVED - PROTOCOL #QEC-2026-001`)
- Export Data button
- Generate Report button  
- Title should read "NEVEDAL RESEARCH LABORATORY" (not just "NEVEDAL LAB")

### Missing from Left Panel (Subject Selection)

- **Dyad Selection**: Current Analysis Pair (Subject A + Subject B) with avatar display and connector
- **Filter tabs**: All / Clients / Coaches / Family
- **Rich subject items**: Family ID, session count, role badges (Client/Coach/Family), A/B selection tags
- **Cross-Reference Matrix**: Family coherence matrix with color-coded cells (high/medium/low) -- currently this data is available from `admin_get_family_metrics`

### Missing from Center Panel

- **Master Formula Banner**: Rendered Nevedal equation with CSS math notation and "COMPUTING LIVE" badge
- **Current State Interpretation**: Dynamic text interpreting each variable (e.g., "High entanglement (p_ent=0.81) indicates strong dyadic synchrony")
- **Biometric Signal Mapping**: Dual-column display for Subject A and B showing voice biometrics (HRV, Respiratory, Vocal, EDA) with sync percentages
- **Signal-to-Variable Mapping legend**: Shows which raw signals map to which Nevedal variables
- **Real Session Trajectory chart**: Chart.js live-updating line graph (C_emo, p_ent, CEE windows)
- **CEE Window Threshold Detail (Patent 1)**: Show which conditions are met with checkmarks: p_ent >= threshold, d <= threshold, gamma_env <= threshold, E_G_joint >= threshold, sustained duration

### Patent-Specific Additions (NOT in old page)

#### Patent 2: Real-Time Metrics Engine Panel

- **Crisis Perception**: Live objective_distress vs expressed_distress, distress_discrepancy gauge, perception baseline (MINIMIZER/AMPLIFIER/NORMALIZER/CALIBRATED)
- **Shame Detection**: shame_index (0-1) with channel breakdown (self_blame, unworthiness, deflection), shame_masking_pattern
- **PMB Indicators**: Reconsolidation readiness (0-1), reactivity signature (FIGHT/FLIGHT/FREEZE/FAWN), confidence tier color coding (LEARNING=red, OBSERVATION=amber, AWARENESS=yellow, REFLECTION=green)
- **Dysregulation Alert**: C_emo < 0.3 AND trend FALLING
- **Breakthrough Moment**: C_emo > 0.9 AND CEE active >= 15 seconds

#### Patent 3: Live Session Alerts (family sessions)

- **Escalation Detection**: Alert with severity badge, de-escalation tracking
- **Ventriloquism Detection**: Alert when proxy speech patterns detected
- **EFT Cycle Markers**: Negative cycle type (pursue-withdraw, blame-defend, attack-shutdown)
- **Reconsolidation Window**: Schema activation status, window OPEN/CLOSED with countdown, mismatch opportunities

#### Patent 4: Visual Biometric Extraction Panel

- **Facial Affect**: valence (-1 to +1), arousal (0-1), primary_emotion (8 categories)
- **Gaze Tracking**: gaze_contact_ratio, gaze_direction (toward/away/down)
- **Body Language**: body_lean_angle (-30 to +30 deg), posture (open/closed)
- **Engagement**: engagement_score (0-1), micro_expression_count
- **d_extended**: Multi-modal interpersonal distance (visual + voice)
- **Notable Moments**: Flagged with description when is_notable = true

### Missing from Right Panel

- **Active Research Study**: Stats panel (Total Sessions, Participants, Therapists, Families)
- **Report Generator**: 5 report types
- **Trends (12 weeks)**: Avg C_emo change, CEE Windows/Session, Baseline p_ent, Avg gamma_env
- **Session History**: Scrollable list with date, C_emo, CEE count, duration
- **Research Ethics Notice**: Fixed disclaimer

## Implementation Strategy

Rewrite [dashboard/nevedal_lab_live.html](dashboard/nevedal_lab_live.html) by merging:

- **HTML/CSS structure** from the old page (layout, styling, formula banner, biometric grids, research panels)
- **JavaScript WebSocket logic** from the current live page (`nevedal_subscribe` real-time streaming, auto-populate subjects, `nevedal_update` handler)
- **New backend data calls**: Add `admin_get_users` for subject list, `admin_get_cohort_stats` for study stats, `nevedal_get_history` for session history and trends

### Key architectural decisions:

- Keep the 3-column layout (320px | 1fr | 320px) from the old page
- Keep the `nevedal_subscribe` approach from the live page for real-time data
- Add `admin_get_user_metrics` polling for biometric signal mapping and Patent 2 metrics
- Add `admin_get_client_metrics` for Patent 2 crisis/shame/PMB data
- Use Chart.js (already loaded in other tabs) for the trajectory graph
- Dynamic Subject A/B selection wired to real backend data
- Interpretation section + Patent 2/3 alerts update dynamically on every `nevedal_update`
- Cross-Reference Matrix pulls from `admin_get_family_metrics` for the selected subject's family
- Patent 3 alerts (escalation, ventriloquism, EFT) only display when a family session is active
- Patent 4 visual biometrics panel shows when visual_biometrics data is available in the metrics response
- All Patent panels degrade gracefully: show "Awaiting data" when metrics aren't yet available

### No backend changes required -- all data sources already exist from our prior work.

