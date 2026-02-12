---
name: Wire Admin Mock Data
overview: Replace all remaining hardcoded mock data in sovereign-command-admin.html with real API-backed data. Six of eight tabs still have partially or fully hardcoded content.
todos:
  - id: dashboard-badges
    content: Remove or hide hardcoded change indicator badges (up 23%, etc.) on dashboard metric cards since API has no trend data yet
    status: completed
  - id: campaign-steps
    content: "Wire campaign steps visual: add loadCampaignSteps() that fetches GET /api/campaigns/{id}/steps and dynamically renders the step cards"
    status: completed
  - id: quiz-builder
    content: "Wire Quiz Builder tab: add loadQuizBuilder() and loadQuizDetail(quizId) to load quiz list and questions from API, replace all hardcoded questions/properties"
    status: completed
  - id: prospect-filters
    content: Wire search input (oninput debounce) and status dropdown (onchange) to call loadProspects() with query params
    status: completed
  - id: insights-tab
    content: "Wire Insights tab: add loadInsights() + loadInsightDetail(prospectId) to load real prospect insight timelines, story, and cumulative narrative from API"
    status: completed
  - id: golden-summary
    content: Wire Golden Tickets summary cards (Issued/Redeemed/Pending/Expired counts) from /api/analytics/overview data
    status: completed
  - id: webhook-table
    content: Wire Integrations webhook activity table to load real delivery log entries from API
    status: completed
  - id: settings-cleanup
    content: Remove fake API key form from Settings tab, keep Golden Ticket config as display-only with note that settings are env-managed on the server
    status: completed
isProject: false
---

# Wire All Remaining Mock Data to Real API

## Audit Results

Reviewing every tab in [dashboard/sovereign-command-admin.html](dashboard/sovereign-command-admin.html):

### Already Wired (working)

- **Dashboard** -- metric cards, funnel, and activity feed all call `/api/analytics/overview` and `/api/analytics/activity`
- **Campaigns** -- table body is replaced by `loadCampaigns()` from `/api/campaigns`
- **Prospects** -- table body + pagination replaced by `loadProspects()` from `/api/prospects`
- **Golden Tickets** -- ticket cards replaced by `loadGoldenTickets()` from `/api/golden-ticket/list`
- **Integrations** -- SendGrid/Twilio stat numbers updated by `loadIntegrations()`

### Still Hardcoded Mock Data (needs fixing)

**1. Dashboard -- change indicators (lines 207-211)**
The "up 23%", "up 18%", "up 12 new", "up 4%", "up 7%" badges are static HTML. The API doesn't return trend data, and the JS only overwrites `.mc-v` values, not `.mc-c` badges. Fix: hide the change badges or compute trends from analytics timeseries.

**2. Campaigns -- step cards (lines 279-319)**
The 5-step visual at the bottom ("Self-Awareness Pulse", "Emotional Regulation", etc.) is entirely hardcoded HTML. `loadCampaigns()` never touches this section. Fix: add a `loadCampaignSteps()` function that fetches `GET /api/campaigns/{id}/steps` and dynamically renders step cards.

**3. Quiz Builder -- entire tab (lines 322-413)**
All 4 questions, the sidebar, and the properties panel are static mock HTML. `showTab('quiz-builder')` triggers no data load. Fix: add `loadQuizBuilder()` that fetches quiz list from `GET /api/quizzes`, loads selected quiz questions from `GET /api/quizzes/{id}`, and renders them dynamically.

**4. Prospects -- search/filter controls (lines 421-422)**
The search input and status dropdown have no event handlers. Typing or selecting does nothing. Fix: add `oninput`/`onchange` handlers that call `loadProspects()` with query params.

**5. Insights -- entire tab (lines 440-496)**
The "Sarah Mitchell" profile with 3 quiz insights, strengths/growth areas, and cumulative narrative is entirely hardcoded. `showTab('insights')` triggers no data load. Fix: add `loadInsights()` that fetches the most recent prospects with insights from `GET /api/prospects` then loads individual insight timelines via `GET /api/prospects/{id}/insights` and `GET /api/prospects/{id}/story`.

**6. Golden Tickets -- summary cards (lines 501-506)**
The 4 metric cards (Issued: 38, Redeemed: 14, Pending: 16, Expired: 8) are hardcoded. `loadGoldenTickets()` only updates the ticket card grid below, not these summary numbers. Fix: compute counts from the ticket list data or from `/api/analytics/overview`.

**7. Integrations -- webhook activity table (lines 582-596)**
The 5-row webhook log (Sarah M. email.opened, quiz.completed, etc.) is entirely hardcoded. Fix: add `loadWebhookActivity()` that fetches recent delivery log entries from a new or existing endpoint.

**8. Settings -- all values and buttons (lines 599-628)**
All form inputs have hardcoded placeholder values. "Save Configuration" and "Update Keys" buttons do nothing. Fix: this is intentionally non-functional per the plan spec (API keys remain env-only, not editable from UI for security). We should remove the fake API key fields and wire only the Golden Ticket config to read/display current settings.

## Changes

All changes are in a single file: [dashboard/sovereign-command-admin.html](dashboard/sovereign-command-admin.html)

### HTML changes

- Replace hardcoded campaign steps section with a dynamic container `<div id="campaign-steps-area">`
- Replace hardcoded quiz builder center and properties panels with dynamic containers
- Replace hardcoded insights content with a dynamic container that loads prospect list + detail
- Replace hardcoded golden ticket summary cards `.mc-v` with ids for JS targeting
- Replace hardcoded webhook table body with placeholder "Loading..."
- Remove fake API key form (security concern), keep Golden Ticket config with note that settings are env-managed
- Add `oninput`/`onchange` to prospect search and filter controls

### JS additions (in the script block)

- `loadCampaignSteps(campaignId)` -- fetches `/api/campaigns/{id}/steps`, renders step cards
- `loadQuizBuilder()` -- fetches `/api/quizzes`, renders quiz sidebar list + loads first quiz questions
- `loadQuizDetail(quizId)` -- fetches `/api/quizzes/{id}`, renders question cards + properties
- `loadInsights()` -- fetches recent prospects with insights, renders first one as detail view
- `loadInsightDetail(prospectId)` -- fetches `/api/prospects/{id}` full profile, renders insight timeline + story
- Update `loadGoldenTickets()` to also populate summary metric cards from `/api/analytics/overview`
- `loadWebhookActivity()` -- fetches recent delivery log entries from `/api/analytics/activity`
- Wire prospect search/filter inputs to debounced `loadProspects()` calls
- Remove hardcoded change indicators from dashboard cards (or hide them until trend data exists)

