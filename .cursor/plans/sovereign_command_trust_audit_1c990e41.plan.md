---
name: Sovereign Command Trust Audit
overview: Create a `SovereignCommandAuditor` agent that tests all REST API endpoints behind the 7 Sovereign Command tabs (Command, My Clients, Calendar, Crisis Center, Users, System, Marketplace) 3x daily and emails a trust scorecard, following the same pattern as the SkyEye Tab Auditor.
todos:
  - id: audit-command-tabs
    content: Curl all 27 endpoints from production to verify current health before building the agent
    status: completed
  - id: build-command-auditor
    content: Create SovereignCommandAuditor agent in backend/app/services/command_tab_auditor.py
    status: completed
  - id: register-command-auditor
    content: Register in main.py (startup, shutdown, health check 51/51), add admin trigger endpoint, update rule
    status: completed
  - id: deploy-command-auditor
    content: Deploy, restart, verify 51/51, trigger initial scorecard email
    status: completed
isProject: false
---

# Sovereign Command 7-Tab Trust Audit

## Key Finding

Unlike SkyEye (which is 100% REST), these tabs use a **hybrid** architecture: the dashboard HTML files communicate via **WebSocket messages** to the bridge, but most data also has **REST API equivalents** in the backend routers. The auditor will test all REST endpoints, which validates that the same database queries, registry lookups, and service calls work end-to-end.

## Tab Inventory (7 tabs, REST endpoints to audit)

### Tab 1: Command (Dashboard Overview)

Router: `admin.py` prefix `/api/admin`

- `GET /api/admin/dashboard` -- system stats
- `GET /api/admin/crisis-watchlist` -- crisis overview
- `GET /api/admin/live-sessions` -- active sessions
- `GET /api/admin/community-health` -- health metrics
- `GET /api/admin/activity-feed` -- recent activity

### Tab 2: My Clients

Router: `coach.py` prefix `/api/coach`

- `GET /api/coach/clients/DrNevedal1` -- client list for admin
- `GET /api/coach/stats/DrNevedal1` -- coach stats

### Tab 3: Calendar

Router: `sessions.py` prefix `/api/sessions`

- `GET /api/sessions/coach/DrNevedal1` -- coach sessions
- `GET /api/sessions/upcoming/DrNevedal1` -- upcoming sessions

### Tab 4: Crisis Center

Router: `admin.py` prefix `/api/admin`

- `GET /api/admin/crisis-watchlist` -- watchlist
- `GET /api/admin/crisis-log` -- crisis log history

### Tab 5: Users

Router: `admin.py` prefix `/api/admin`

- `GET /api/admin/users` -- all users
- `GET /api/admin/coaches` -- coach list
- `GET /api/admin/coaches?status=PENDING_VERIFICATION` -- pending coaches

### Tab 6: System

Router: `admin.py` prefix `/api/admin`

- `GET /api/admin/settings` -- system settings
- `GET /api/admin/token-economics` -- token spend
- `GET /api/admin/dependency-report` -- dependency health
- `GET /api/admin/night-school/status` -- Night School status

### Tab 7: Marketplace

Routers: `analytics_api.py`, `campaign_api.py`, `quiz_api.py`, `prospect_api.py`, `golden_ticket_api.py`

- `GET /api/analytics/overview` -- analytics overview
- `GET /api/analytics/activity?limit=6` -- recent activity
- `GET /api/analytics/integrations/sendgrid/stats?days=30` -- SendGrid stats
- `GET /api/analytics/integrations/twilio/stats?days=30` -- Twilio stats
- `GET /api/campaigns` -- campaign list
- `GET /api/quizzes` -- quiz list
- `GET /api/prospects` -- prospect list
- `GET /api/golden-ticket/list` -- golden tickets

**Total: ~27 GET endpoints across 7 tabs**

## Implementation

### New file: [backend/app/services/command_tab_auditor.py](backend/app/services/command_tab_auditor.py)

Follow the exact same pattern as [backend/app/services/skyeye_tab_auditor.py](backend/app/services/skyeye_tab_auditor.py):

- Same class structure (`start()`, `stop()`, `_run_loop()`, `_build_and_send()`, `_audit_all_tabs()`, `_test_endpoint()`, `_render_html()`)
- Same schedule: 5am / 5pm / 11pm UTC
- Same email target: `support@sovereignsanctuary.net`
- Same Redis token scan for auth
- Same trust criteria: 200 = TRUSTED, 4xx = WARNING, 5xx = FAILED
- Stagger delay: 130 seconds (10s after SkyEye auditor's 120s)
- Email subject: "Sovereign Command Tab Trust Scorecard"

### Register in [backend/app/main.py](backend/app/main.py)

- Add startup block after `SkyEyeTabAuditor` registration
- Add `("command_tab_auditor", _cmd_auditor is not None)` to `_service_checks` (becomes 51/51)
- Add shutdown block

### Admin trigger endpoint in [backend/app/routers/admin.py](backend/app/routers/admin.py)

- `POST /api/admin/command-audit/send` -- same pattern as `/api/admin/skyeye-audit/send`

### Update rule in [.cursor/rules/service-health-49-49.mdc](.cursor/rules/service-health-49-49.mdc)

- Change target to 51/51
- Add `command_tab_auditor` to service registry table

