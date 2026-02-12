---
name: Fix Nevedal Lab pages
overview: Make all four Nevedal Lab dashboard tabs fully functional with real-time data, patent-aligned formula variable visualization, and missing Patent 2/3/4 feature surfaces.
todos:
  - id: longitudinal
    content: "Fix Longitudinal Study: Chart.js trajectory with all 7 Nevedal variables, load real subjects, rebuild CEE/breakthroughs from data, add Patent 2 metrics panel (crisis perception, shame, PMB), add polling"
    status: completed
  - id: dyad
    content: "Fix Dyad Comparisons: Chart.js dual timeline with p_ent/T_tunnel/d_distance overlays, wire gauges, rebuild shared CEEs, load real dyads, add visual biometric panel (Patent 4)"
    status: completed
  - id: family
    content: "Fix Family Dynamics: load real families, add network viz, add EFT Tracker panel, add Reconsolidation Tracker panel, add Escalation Detection alerts, implement Ventriloquism Detection backend"
    status: completed
  - id: cohort
    content: "Fix Cohort Analysis: Chart.js bar chart, wire filters, update all stats, add treatment modality comparison, add crisis perception/shame/PMB distributions, add CSV export"
    status: completed
isProject: false
---

# Fix Nevedal Lab Pages -- Patent-Aligned Remediation

All four backend handlers exist and return data. The main issues are (1) frontend components that show hardcoded mock values or ignore backend data, and (2) patent-claimed features that are computed in the backend but never surfaced on the research dashboard.

---

## Patent Gap Analysis

The Nevedal Formula computes **7 variables per sample** (`c_emo`, `p_ent`, `t_tunnel`, `d_distance`, `gamma_env`, `e_g_joint`, `tau_emo`). The dashboard only ever shows `c_emo`. All 7 are returned by the backend in every `nevedal_update` and should be plottable for research purposes.

Patent 2 features (crisis perception, shame detection, PMB, legacy analysis) are computed per-client but only appear on `my_clients.html` -- they belong on the Longitudinal Study research tab too.

Patent 3 features (EFT tracker, reconsolidation tracker, escalation detection) are implemented in `sanctuary_engine.py` but never shown on Family Dynamics. Ventriloquism Detection has zero code anywhere.

Patent 4 features (classroom analyzer, coach matcher, live observation, visual biometrics) have zero dashboard representation.

---

## Tab 1: Longitudinal Study (`nevedal_lab_longitudinal.html`)

### Current Broken/Mock Components

- Subject selector: hardcoded 3 options
- C_emo Trajectory graph: placeholder, no charting library
- Statistics panel: partially wired (updates if data arrives, but hardcoded initial values)
- CEE Events list: only count updates, list items hardcoded
- CEE Frequency by Week: fully hardcoded
- Breakthroughs panel: fully hardcoded
- Trend text: static "+12%"
- Real-time: one-shot only, no polling

### Patent-Critical Additions

- **Nevedal Formula Variable Selector (Patent 1)**: Add toggle checkboxes to overlay `p_ent`, `t_tunnel`, `d_distance`, `gamma_env`, `e_g_joint`, `tau_emo` as additional traces on the trajectory chart. Each variable is in the `nevedal_update` payload. This is fundamental -- researchers need to see which components drive coherence changes.
- **Crisis Perception Panel (Patent 2)**: Show the client's `perception_baseline` classification (NORMALIZER / MINIMIZER / AMPLIFIER / CALIBRATED), distress discrepancy, minimization score, sensitivity score. Backend already computes this in `_compute_crisis_perception()`.
- **Shame Profile Panel (Patent 2)**: Show `shame_index`, `shame_baseline`, `shame_masking_pattern`, and core beliefs. Backend already computes in `_compute_shame_profile()`.
- **PMB Summary (Patent 2)**: Show `reactivity_type` (FIGHT/FLIGHT/FREEZE/FAWN), `reconsolidation_readiness`, top predictions. Backend already computes in `_compute_pmb()`.
- **Trend computation**: Calculate actual trend from `data.timeline` instead of hardcoded "+12%".

### Implementation

- Add `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>`
- Replace graph placeholder with `<canvas id="trajectory-chart">`
- Render multi-line chart from `data.timeline` with variable toggle (default: C_emo only, checkboxes for others)
- Request client list on auth via `admin_get_stats` (which returns registry); populate subject dropdown
- Rebuild CEE events list from `data.cee_events`, CEE Frequency from events, Breakthroughs from `data.breakthroughs`
- Add right-sidebar sections for Patent 2 metrics (request via existing `admin_get_client_metrics` or add to `nevedal_history` response)
- Add 10-second polling

---

## Tab 2: Dyad Comparisons (`nevedal_lab_dyad.html`)

### Current Broken/Mock Components

- Dyad selector: hardcoded 3 pairs, click doesn't change data
- C_emo gauges: backend sends values, frontend ignores them
- Temporal Correlation graph: placeholder only
- Shared CEE Moments: hardcoded 3 entries
- Analysis panel: all static text, no IDs

### Patent-Critical Additions

- **Formula Variable Overlays (Patent 1)**: The dual timeline chart should allow overlaying `p_ent` (entanglement between the dyad -- the core cross-person metric), `T_tunnel` (barrier penetration), and `d_distance` (interpersonal distance). These are what make dyad analysis meaningful -- not just two C_emo lines.
- **Visual Biometric Overlay (Patent 4)**: If session has video data, show `gaze_contact_ratio`, `body_lean_angle`, `facial_affect_valence` alongside voice biometrics. Backend `visual_biometric_extractor.py` provides these. Add a "Visual Biometrics" toggle section.
- **Extended Distance Formula (Patent 4)**: Show `d_extended` vs `d_distance` when visual data is available, demonstrating the multi-modal improvement.

### Implementation

- Add Chart.js
- Replace graph placeholder with `<canvas id="dyad-chart">`
- Render dual-line chart (client purple, coach cyan) with variable overlay toggles
- Wire `#client-c-emo` / `#coach-c-emo` gauge updates in `displayDyadSync()`
- Rebuild Shared CEE Moments from `data.shared_cees`
- Add IDs to Analysis panel; update from `data.high_sync_pct`, `data.avg_difference`, `data.peak_sync`
- Load real dyad pairs on auth; wire click handlers
- Add "Visual Biometrics" collapsible section (populated when video data exists)

---

## Tab 3: Family Dynamics (`nevedal_lab_family.html`)

### Current Broken/Mock Components

- Family selector: hardcoded 3 families
- Coherence Network: placeholder only
- (Everything else works: matrix, wellness index, bonds, collective CEEs, individual scores)

### Patent-Critical Additions (Patent 3)

- **EFT Tracker Panel**: Show per-family: `session_stage` (CYCLE_IDENTIFICATION, etc.), `negative_cycle` pattern, `member_longings`, `corrective_moments`. Backend `sanctuary_engine.py` (lines 1526-1682) computes this. Need a new sidebar section with the cycle visualization.
- **Reconsolidation Tracker Panel**: Show active schemas, activation count, mismatch events, verified reconsolidations, active windows. Backend `sanctuary_engine.py` (lines 1743-2022). Need a sidebar section showing schema cards with activation/mismatch/reconsolidation status.
- **Escalation Detection Alerts**: Show per-member escalation events detected via `detect_escalation()` in `sanctuary_engine.py` (lines 605-664). Display as alert badges on member cards in the Individual C_emo Scores section.
- **Ventriloquism Detection (NOT IMPLEMENTED)**: This is the one Patent 3 feature with zero backend code. Need to implement detection in `sanctuary_engine.py` that analyzes when a family member's speech patterns suggest they are speaking for another member (e.g., "He feels..." / "She thinks..." / "They want..."). Surface alerts on the Family Dynamics tab.

### Implementation

- Add `admin_get_families` handler in backend (or use existing registry family data) to load real families
- Canvas 2D network visualization for Coherence Network (circle nodes, line edges, thickness = bond score)
- Add "EFT Cycle" section to right sidebar -- request from `sanctuary_engine` state
- Add "Reconsolidation" section to right sidebar
- Add escalation badge indicators on member score cards
- **Backend**: Implement `VentriloquismDetector` in `sanctuary_engine.py` -- regex patterns for proxy speech ("he feels", "she thinks", "they want", "my husband is", "my wife needs") plus frequency tracking per member. Surface on family tab as alerts.

---

## Tab 4: Cohort Analysis (`nevedal_lab_cohort.html`)

### Current Broken/Mock Components

- Age Group bar chart: placeholder only
- Age group bars: hardcoded values
- Study Overview stats: hardcoded
- Key Findings: hardcoded
- Filters: only time_range wired, checkboxes disconnected
- Export: no handler

### Patent-Critical Additions

- **Treatment Modality Comparison (Patent 3)**: Add a chart section comparing C_emo outcomes across AI-Only, AI + Human Coach, and Family Therapy. This validates Patent 3's family therapy claims. Backend `admin_get_cohort_stats` returns `by_treatment_type`.
- **Crisis Perception Distribution (Patent 2)**: Bar chart showing percentage of clients classified as NORMALIZER / MINIMIZER / AMPLIFIER / CALIBRATED across the population. Validates Patent 2 claims.
- **Shame Masking Distribution (Patent 2)**: Bar chart of masking patterns (FEAR / ANGER / WITHDRAWAL / PEOPLE_PLEASING) across population.
- **PMB Reactivity Distribution (Patent 2)**: Bar chart of reactivity types (FIGHT / FLIGHT / FREEZE / FAWN) across population.
- **CEE Frequency by Treatment Modality**: Shows which treatment approach produces more corrective emotional experiences -- key research metric.

### Implementation

- Add Chart.js
- Replace chart placeholder with `<canvas id="cohort-chart">`
- Render bar chart from `data.by_age_group`
- Update age group bars, Study Overview, Key Findings dynamically from backend
- Wire filter checkboxes to `filters` object (read checked state on change)
- Add new chart sections: Treatment Modality, Crisis Perception Distribution, Shame Distribution, PMB Distribution
- Backend: extend `admin_get_cohort_stats` to return `by_treatment_type`, `crisis_perception_distribution`, `shame_distribution`, `pmb_distribution`
- Add CSV export button handler

---

## Backend Changes Required

### Existing handlers to extend

- `nevedal_get_history` response: include all 7 formula variables in `timeline` entries (verify they are already there)
- `admin_get_dyad_sync` response: include formula variables in timeline data, include visual biometric data if available
- `admin_get_family_metrics` response: include EFT tracker state, reconsolidation tracker state, escalation events per member
- `admin_get_cohort_stats` response: add `by_treatment_type`, `crisis_perception_distribution`, `shame_distribution`, `pmb_distribution`

### New backend code

- **Ventriloquism Detection**: New class in `sanctuary_engine.py` -- pattern-based detection of proxy speech in family sessions
- **admin_get_families**: New handler (or extend existing) to return list of real families from registry for the family selector

