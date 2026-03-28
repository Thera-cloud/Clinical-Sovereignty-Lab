---
name: Admin portal tier breakdown
overview: Enhance the Admin Portal's OVERVIEW, USERS, and CRISIS tabs with search, tier-based grouping, and user-type breakdowns.
todos:
  - id: backend-enrich-users
    content: Add subscription_plan, registration_type, selected_dojos, can_access_nate to admin_get_users response
    status: pending
  - id: backend-stats-breakdown
    content: Add clients_by_tier and coaches_by_dojo breakdowns to get_dashboard_stats()
    status: pending
  - id: backend-crisis-tier
    content: Add tier and subscription_plan fields to get_crisis_watchlist() entries
    status: pending
  - id: overview-tier-cards
    content: Add client tier breakdown and coach dojo subscription cards to _buildOverviewTab()
    status: pending
  - id: users-search-filter
    content: Add search bar, filter chips, and tier badges to _buildUsersTab()
    status: pending
  - id: crisis-tier-groups
    content: Group crisis alerts by tier with section headers in _buildCrisisTab()
    status: pending
  - id: rebuild-deploy-admin
    content: Rebuild Flutter web (skip index.html) + deploy bridge_server.py and web build
    status: pending
isProject: false
---

# Admin Portal Tier Breakdown

## Changes Overview

Three tabs in the Admin dashboard ([mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart)) need updates, plus the backend needs to send additional fields.

---

## 1. Backend: Enrich user and stats data

**File**: [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)

### `admin_get_users` handler (line ~4971)

Add these fields to each user entry so the frontend can group/filter:

- `subscription_plan` (COACH_ONLY, TRIAL, STANDARD, TOP_TIER, COACH)
- `registration_type` (from profile)
- `selected_dojos` (coaches only)
- `can_access_nate`

### `get_dashboard_stats()` (line ~2369)

Add tier/dojo breakdowns to the stats dict:

- `clients_by_tier`: `{"COACH_ONLY": N, "TRIAL": N, "STANDARD": N, "TOP_TIER": N}`
- `coaches_by_dojo`: `{"therapist": N, "cnc": N, "teacher": N, "project_pm": N, "business": N, "mcat": N}`
- `pending_coaches_count`: count of PENDING_VERIFICATION coaches

Computed by scanning the registry, grouping by `subscription_plan` for clients and counting `selected_dojos` entries for coaches.

### `get_crisis_watchlist()` (line ~2437)

Add `tier` and `subscription_plan` to each watchlist entry so the frontend can group crisis alerts by tier.

---

## 2. OVERVIEW Tab -- Tier/Dojo Breakdown Cards

**Method**: `_buildOverviewTab()` (line ~9410)

After the existing stats grid (Total Users, Active Today, Messages, Crisis Alerts, Coaches, Pending), add:

- **Client Tier Breakdown** section: A row of 4 compact stat cards showing count per tier:
  - Coach-Only (teal), Threshold/Trial (blue), Inner Chamber (purple), Sovereign Circle (gold)
- **Coach Dojo Subscriptions** section: A row/wrap of 6 compact badges showing count per dojo:
  - CNC, Therapist, Teacher, Project PM, Business, MCAT

Data comes from the new `clients_by_tier` and `coaches_by_dojo` fields in `_stats`.

---

## 3. USERS Tab -- Search Bar + Tier Grouping

**Method**: `_buildUsersTab()` (line ~9507)

Add:

- **Search bar** at the top: `TextField` with `_userSearchCtrl` that filters by name, email, role, or tier (case-insensitive)
- **Filter chips**: Horizontal row of filter chips (All, Clients, Coaches, Coach-Only, Trial, Standard, Top Tier) -- tapping one filters the list
- **User cards**: Enhanced to show tier/plan info:
  - Clients: show tier badge (e.g., "INNER CHAMBER" in purple)
  - Coaches: show selected dojos as small chips and subscription status

New state variables on `_AdminDashboardScreenState`:

- `_userSearchQuery` (String)
- `_userFilterRole` (String? -- null = all)
- `_userSearchCtrl` (TextEditingController)

---

## 4. CRISIS Tab -- Group by Tier

**Method**: `_buildCrisisTab()` (line ~9475)

Group crisis alerts by tier using section headers:

- "SOVEREIGN CIRCLE" section (gold divider)
- "INNER CHAMBER" section (purple divider)
- "THRESHOLD (TRIAL)" section (blue divider)
- "COACH-ONLY" section (teal divider)

Each section only appears if there are crisis entries for that tier. Entries without a tier default to a general "UNCLASSIFIED" section.

---

## Files to Modify

- [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) -- `admin_get_users`, `get_dashboard_stats`, `get_crisis_watchlist`
- [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) -- `_buildOverviewTab`, `_buildUsersTab`, `_buildCrisisTab` + new state vars

## Deployment

- Backend-only change: `scp bridge_server.py` to server + restart containers
- Flutter rebuild needed for the frontend tab changes (rsync web build, skip index.html)

