---
name: Nate Coherence Matrix Enhancement
overview: Enhance the Nevedal Lab Family Dynamics tab to include Little Nate as a coherence node, with a three-graph layout (2D baseline with Nate, 2D baseline without Nate, and a 3D interactive selector graph), expanded group selection (families, groups, companies, coach teams), and a Nate-centric wellness index measuring coherence vs decoherence.
todos:
  - id: backend-nate-coherence
    content: Add _calculate_nate_coherence() and _calculate_decoherence_signals() to bridge_server.py
    status: completed
  - id: backend-group-handler
    content: Add admin_get_all_groups WebSocket handler for unified group selection (families, communities, companies, coach teams)
    status: completed
  - id: backend-group-coherence
    content: Add admin_get_group_coherence handler returning with-Nate/without-Nate matrices and decoherence signals
    status: completed
  - id: frontend-layout
    content: Restructure nevedal_lab_family.html with three-panel graph layout (2x 2D top, 1x 3D bottom)
    status: completed
  - id: frontend-2d-graphs
    content: Implement two baseline 2D graphs (with/without Nate) using existing Canvas 2D drawNetwork style
    status: completed
  - id: frontend-3d-graph
    content: Implement 3D interactive selector graph with Three.js, OrbitControls, member toggles, and DNA helix layout option
    status: completed
  - id: frontend-matrix
    content: Expand coherence matrix to include Little Nate row/column with toggle
    status: completed
  - id: frontend-wellness
    content: Add Nate-centric wellness index panel with contribution delta and decoherence alerts
    status: completed
  - id: frontend-group-selector
    content: Expand group selector from families-only to all group types (families, groups, companies, coach teams)
    status: completed
isProject: false
---

# Nate Coherence Matrix Enhancement

## Current Architecture

- **Dashboard**: `dashboard/nevedal_lab_family.html` -- Canvas 2D circular network, HTML coherence matrix, WebSocket-driven data
- **Bridge handler**: `bridge_server.py` `admin_get_family_metrics` (~line 17027) -- calculates pairwise bond as `1.0 - abs(c_emo_A - c_emo_B)`
- **Data tables**: `nevedal_metrics` (C_emo time series), `client_metrics` (snapshot), `token_transactions` (engagement), `sessions` (session history)
- **Current bond formula**: `bond = 1 - |c_emo_A - c_emo_B|` (proximity of emotional coherence states)

## What Changes

### 1. Little Nate Coherence Score (Backend)

Add a new method to bridge_server.py: `_calculate_nate_coherence(user_profile)` that produces a 0-1 score per user representing Little Nate's "bond" with that individual.

**Balanced formula (engagement 50% + outcomes 50%)**:

```
nate_engagement = normalize(session_count, token_usage, login_frequency, message_count)
nate_outcomes   = normalize(mood_trend, anxiety_reduction, breakthrough_count, c_emo_trend)
nate_coherence  = 0.5 * nate_engagement + 0.5 * nate_outcomes
```

Data sources (all already captured):

- `client_metrics`: `session_count`, `breakthrough_count`, `mood_trend`, `anxiety_level`, `stress_level`, `engagement`
- `token_transactions`: usage count/volume per source (`ai_chat`, `sanctuary_ai`, etc.)
- `nevedal_metrics`: `c_emo` trend over time (slope of recent measurements)

### 2. Decoherence Detection (Backend)

Add `_calculate_decoherence_signals(family_members)` to detect interpersonal tension markers:

- Compare individual C_emo divergence trends (members moving apart over time, not just snapshot)
- Flag sessions where user mentions conflict/stress about family members (mood drops correlated with family context keywords already tracked by MetricsEngine sentiment)
- Track escalation events and ventriloquism events (already returned by `admin_get_family_metrics`)
- Output: per-pair `decoherence_risk` score (0-1)

### 3. Expand Group Selection (Backend + Frontend)

Currently `admin_get_families` returns only `family_id`-grouped users. Expand to return ALL grouping types:


| Group Type            | Source                                                   | Key       |
| --------------------- | -------------------------------------------------------- | --------- |
| Families              | `users.family_id`                                        | `FAM_*`   |
| Community Groups      | `community_attendance_records.group_name`                | `GRP_*`   |
| Companies             | `profile_data->>'company_id'`                            | `CORP_*`  |
| Coach Teams           | `profile_data->>'coach_id'` (clients sharing same coach) | `COACH_*` |
| Assistant Coach Teams | `coach_hierarchy` table                                  | `ASST_*`  |


New WebSocket handler: `admin_get_all_groups` that returns a unified list with `group_type`, `group_id`, `group_name`, `member_count`.

### 4. Enhanced WebSocket Response

Modify `admin_get_family_metrics` (or create `admin_get_group_coherence`) to return:

```json
{
  "type": "group_coherence_metrics",
  "group_type": "family|community|company|coach_team",
  "group_id": "FAM_0F708896",
  "members": [
    {"id": "...", "name": "Bill West", "role": "CLIENT", "c_emo_avg": 0.72},
    {"id": "...", "name": "Lisa West", "role": "CLIENT", "c_emo_avg": 0.68}
  ],
  "nate_node": {
    "nate_coherence_per_member": {"bill_hw_id": 0.81, "lisa_hw_id": 0.74},
    "nate_wellness_contribution": 0.12,
    "engagement_breakdown": {"bill_hw_id": {"sessions": 14, "tokens": 8200}, "lisa_hw_id": {"sessions": 8, "tokens": 3100}}
  },
  "with_nate": {
    "wellness_index": 0.78,
    "coherence_matrix": {"bill:lisa": 0.96, "bill:nate": 0.81, "lisa:nate": 0.74},
    "network_bonds": [...]
  },
  "without_nate": {
    "wellness_index": 0.70,
    "coherence_matrix": {"bill:lisa": 0.96},
    "network_bonds": [...]
  },
  "decoherence_signals": {
    "bill:lisa": {"risk": 0.15, "trend": "stable", "escalation_count": 0}
  }
}
```

### 5. Three-Graph Dashboard Layout (Frontend)

Replace the current single Canvas 2D network with a three-panel layout:

#### Top Row: Two 2D Baseline Graphs (Canvas 2D, keep existing style)

- **Left**: "With Little Nate" -- full network including Nate as a gold node, all pairwise bonds visible
- **Right**: "Without Little Nate" -- same network but Nate removed, showing organic family coherence only
- Both use the existing circular layout and bond-strength line rendering from `drawNetwork()`

#### Bottom: 3D Interactive Selector Graph (Three.js + OrbitControls)

- **Library**: Three.js (CDN) with `OrbitControls` for rotation/zoom
- **Layout**: Force-directed 3D graph (nodes as spheres, edges as lines with opacity/thickness = bond strength)
- **Little Nate**: Central gold sphere (slightly larger), connected to all selected members
- **Controls**:
  - Checkboxes to toggle individual members on/off
  - Toggle Little Nate on/off
  - Rotation: mouse drag (orbit), scroll wheel (zoom)
  - Optional "DNA helix" layout toggle: arranges nodes along a double-helix spiral path instead of force-directed, with Nate at the central axis
- **Color coding**:
  - Gold (#C9A962): Little Nate node
  - Cyan (#4ECDC4): High coherence bonds (>= 0.85)
  - Purple (#9D4EDD): Medium coherence bonds (>= 0.70)
  - Red (#EF4444): Low coherence / decoherence bonds (< 0.70)
  - Node size: proportional to individual wellness score

### 6. Coherence Matrix Expansion

Expand the existing HTML matrix table to include a "Little Nate" row and column:

```
         Bill    Lisa    Dep1    Nate
Bill      --     0.96    0.82    0.81
Lisa     0.96     --     0.79    0.74
Dep1     0.82    0.79     --     0.68
Nate     0.81    0.74    0.68     --
```

Add a toggle to show/hide the Nate row/column (matching the with/without baseline concept).

### 7. Nate-Centric Wellness Index Panel

New summary panel showing:

- **Family wellness WITH Nate**: avg of all C_emo including Nate bonds
- **Family wellness WITHOUT Nate**: avg of C_emo excluding Nate
- **Nate's contribution delta**: the difference (how much Nate improves coherence)
- **Per-member Nate bond**: sparkline or bar for each member's engagement + outcome score with Nate
- **Decoherence alerts**: flagged pairs with rising divergence

## Files to Modify


| File                                     | Changes                                                                                                              |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `dashboard/nevedal_lab_family.html`      | Three-graph layout, Three.js 3D graph, expanded group selector, Nate matrix row/column, wellness panel               |
| `backend/app/websocket/bridge_server.py` | New handlers: `admin_get_all_groups`, `admin_get_group_coherence`; Nate coherence calculation; decoherence detection |
| `backend/app/websocket/bridge_server.py` | `_calculate_nate_coherence()`, `_calculate_decoherence_signals()` methods                                            |


## Dependencies

- **Three.js**: CDN link (`https://unpkg.com/three@0.160.0/build/three.module.js`) -- no npm install needed
- **OrbitControls**: CDN (`https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js`)
- No new database tables or migrations required -- all data sources already exist

