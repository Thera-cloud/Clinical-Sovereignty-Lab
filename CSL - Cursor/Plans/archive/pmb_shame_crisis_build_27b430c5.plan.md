---
name: PMB Shame Crisis Build
overview: Implement the Crisis Perception Model, Shame Detection Layer, Predictability Model of Behavior, Transgenerational Legacy Tracker, and Observer Protocol into the backend MetricsEngine and frontend dashboard -- exactly as specified in Provisional Patent 2.
todos:
  - id: init-state
    content: Add crisis_perception, shame_profile, and pmb to nevedal_state initialization in MetricsEngine.initialize_metrics()
    status: completed
  - id: perception-compute
    content: "Implement _compute_crisis_perception() method: objective/expressed distress, discrepancy EMA, minimization/sensitivity scores, normalization index, baseline classification"
    status: completed
  - id: shame-compute
    content: "Implement _compute_shame_profile() method: 3 indicator channels, perception-weighted shame index, core belief extraction, shame map, masking pattern"
    status: completed
  - id: pmb-compute
    content: "Implement _compute_pmb() method: cyclical patterns, trigger-topic mapping, reactivity classification, reconsolidation readiness, prediction generation"
    status: completed
  - id: legacy-extract
    content: "Implement _extract_legacy_patterns() method: family-of-origin reference detection, legacy pattern keyword matching"
    status: completed
  - id: wire-analyze
    content: Wire all new methods into analyze_and_update() after existing risk assessment
    status: completed
  - id: observer-prompt
    content: Inject Observer Protocol + perception/shame/PMB context into system prompt (95%+ gate)
    status: completed
  - id: ws-handlers
    content: Add admin_get_crisis_log, admin_resolve_crisis, admin_get_client_pmb WebSocket handlers
    status: completed
  - id: stats-update
    content: Update get_dashboard_stats() to return both crisis_count and watchlist_count
    status: completed
  - id: command-badge
    content: Update command.html to show dual crisis badges (live red + historical amber)
    status: completed
  - id: crisis-hybrid
    content: Redesign crisis_center.html with live watchlist panel + historical crisis log panel
    status: completed
  - id: clients-pmb
    content: Add PMB summary card to my_clients.html sidebar
    status: completed
  - id: deploy
    content: Deploy all updated files to production safely
    status: completed
isProject: false
---

# Code Build: Crisis Perception, Shame, PMB, Legacy, Observer Protocol

## Phase 1: Backend MetricsEngine Extensions

### 1A. Add crisis perception, shame, and PMB to `nevedal_state` initialization

**File:** `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` line ~1684

Add to `initialize_metrics()` default `nevedal_state`:

- `crisis_perception`: `{distress_discrepancy: 0, minimization_score: 0, sensitivity_score: 0, normalization_index: 0, perception_baseline: "CALIBRATING", calibration_count: 0, discrepancy_history: []}`
- `shame_profile`: `{shame_index: 0, shame_baseline: 0, core_beliefs: [], shame_map: [], shame_indicators_history: [], shame_masking_pattern: "UNKNOWN"}`
- `pmb`: `{cyclical_patterns: [], crisis_precursors: [], trigger_map: [], reactivity_type: "MIXED", reactivity_indicators: {fight:0,flight:0,freeze:0,fawn:0}, reconsolidation_readiness: 0, reconsolidation_targets: [], legacy_patterns: [], predictions: [], last_pmb_update: "", pmb_version: 1}`

### 1B. Extend `analyze_and_update()` with new computations

**File:** `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` line ~1977 (end of current method)

After existing risk assessment, add calls to:

1. `_compute_crisis_perception()` -- objective vs expressed distress, discrepancy EMA, baseline classification
2. `_compute_shame_profile()` -- 3 indicator channels, perception-weighted shame index, core belief extraction, shame map update, masking pattern classification
3. `_compute_pmb()` -- cyclical pattern detection, trigger-topic mapping, reactivity classification, reconsolidation readiness, prediction generation
4. `_extract_legacy_patterns()` -- family-of-origin reference detection, legacy pattern keyword matching

Each as a private method on MetricsEngine. All use the patent-specified formulas, weights, and thresholds exactly.

### 1C. Add Observer Protocol to system prompt

**File:** `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` line ~3508 (end of system prompt)

After existing GUIDELINES, inject:

- Crisis perception context (perception baseline for this user)
- Shame awareness (if shame_index elevated, slow-down instructions)
- PMB predictions at 95%+ confidence only
- Legacy patterns at 95%+ confidence only
- Observer Protocol rules (curiosity not diagnosis, never correct shame directly)

## Phase 2: New WebSocket Handlers

**File:** `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` -- add near existing admin handlers

- `admin_get_crisis_log` -- return full `crisis_log.json` with history
- `admin_resolve_crisis` -- mark entry as resolved, record resolver + notes
- `admin_get_client_pmb` -- return full PMB + shame + perception for a client (all confidence levels for admin)

## Phase 3: Dashboard Stats Update

**File:** `[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)` line ~2688

Update `get_dashboard_stats()` to return both `crisis_count` (historical from crisis_log) AND `watchlist_count` (live from metrics scan).

## Phase 4: Frontend Dashboard Updates

### 4A. `command.html` -- dual crisis badge

**File:** `[dashboard/command.html](dashboard/command.html)` lines ~1086-1088, 1591-1615

Update the crisis stat area to show two numbers:

- Live watchlist count (red, pulsing) -- from `stats.watchlist_count`
- Historical unresolved count (amber, static) -- from `stats.crisis_count`

### 4B. `crisis_center.html` -- hybrid two-panel layout

**File:** `[dashboard/crisis_center.html](dashboard/crisis_center.html)` -- full redesign

Left panel: "LIVE WATCHLIST" (red, urgent) -- from `crisis_watchlist` data
Right panel: "CRISIS HISTORY" (amber, reference) -- from new `admin_get_crisis_log` handler
Each history entry gets a "Resolve" button calling `admin_resolve_crisis`

### 4C. `my_clients.html` -- PMB summary card

**File:** `[dashboard/my_clients.html](dashboard/my_clients.html)` line ~270 (in `showSidebarActions()`)

Add a new button "View PMB" and inline PMB card showing:

- Perception baseline badge (MINIMIZER/AMPLIFIER/NORMALIZER/CALIBRATED)
- Shame index with color indicator
- Top core beliefs with confidence %
- Dominant reactivity type
- Top predictions (95%+ only highlighted green, others grayed)
- Reconsolidation readiness score
- Legacy patterns if any

## Key Implementation Details

- All weights/thresholds from Patent 2 Appendix B constants table
- Sentiment score reused from existing `analyze_and_update()` pos/neg word lists
- `perception_multiplier` for shame: MINIMIZER=1.3, NORMALIZER=1.5, other=1.0
- Core belief patterns: 8 beliefs from patent Section 12.4
- Reactivity channels: fight/flight/freeze/fawn with EMA alpha=0.1
- Confidence gate: `conf_threshold = 0.95` for AI prompt inclusion
- Admin sees ALL patterns at ALL confidence levels

