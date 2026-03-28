---
name: Corporate Command Enhancement
overview: Add CORP_ADMIN approval gating (mirroring coach approval), company-wide wellness analytics (coherence, anxiety, stress, engagement, mood), coach team performance analytics with trend graphs, and coach ROI/attunement scoring to the Corporate Command dashboard.
todos:
  - id: corp-approval
    content: "CORP_ADMIN approval flow: pending state on creation, admin approval WebSocket + REST handlers, email notifications, Sovereign Command approval UI"
    status: completed
  - id: wellness-api
    content: "Company-wide wellness analytics API: /analytics/wellness (coherence, gap, quantum, anxiety, stress, engagement, mood, risk aggregates)"
    status: completed
  - id: trends-api
    content: "Trend analytics API: /analytics/trends with 30d/60d/90d/6m/12m periods, three trend lines (Nate<>Employees, Coaches<>Employees, Nate<>Coaches)"
    status: completed
  - id: coach-team-api
    content: "Coach team analytics API: /analytics/coach-team aggregate + /analytics/coach-roi with attunement index formula"
    status: completed
  - id: migration
    content: "Migration 088: performance indexes on nevedal_metrics, sessions, client_metrics for company-scoped analytics"
    status: completed
  - id: dashboard-ui
    content: "Corporate Command dashboard UI: wellness gauges, mood donut, trend Chart.js graphs, coach performance table, ROI insights"
    status: completed
  - id: auditor-update
    content: Update corporate_command_auditor TAB_ENDPOINTS (21->25) and trust_baseline
    status: completed
  - id: deploy-verify
    content: Deploy all changes, restart backend+bridge, verify endpoints and dashboard rendering
    status: completed
isProject: false
---

# Corporate Command Enhancement Plan

## 1. CORP_ADMIN Approval Flow (Mirror Coach Approval)

Currently, `POST /api/admin/create-corp-admin` creates a CORP_ADMIN with `subscription_status = 'ACTIVE'` immediately. This must be changed to require DrNevedal1 approval, mirroring the coach flow.

### Changes

**[backend/app/routers/admin.py](backend/app/routers/admin.py)** -- `create_corp_admin()`:

- Change INSERT to set `subscription_status = 'PENDING_VERIFICATION'` instead of `'ACTIVE'`
- Add `certification_status: "PENDING"` to profile_data
- Fire email to `admin_nevedalnj@sovereignsanctuary.net` on creation: "New Corporate Admin Awaiting Approval: {name} ({company_name})"

**[backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)** -- Add two WebSocket handlers:

- `admin_get_pending_corp_admins` -- Query users WHERE `role = 'CORP_ADMIN' AND subscription_status = 'PENDING_VERIFICATION'`, return list with company_name, email, name
- `admin_approve_corp_admin` / `admin_reject_corp_admin` -- Set `subscription_status = 'ACTIVE'` or `'REJECTED'`, `certification_status = 'APPROVED'`/`'REJECTED'`, send email notification to the corp admin

The existing `authenticate_user()` at line 2320 already blocks `PENDING_VERIFICATION` for all roles, so CORP_ADMIN login will be blocked until approved.

**[backend/app/routers/admin.py](backend/app/routers/admin.py)** -- REST alternative:

- `GET /api/admin/corp-admins?status=PENDING_VERIFICATION` -- List pending corp admins
- `POST /api/admin/corp-admins/approve` -- Approve/reject (same pattern as `POST /api/admin/coaches/approve`)

**[dashboard/command.html](dashboard/command.html)** -- Sovereign Command approvals section:

- Add CORP_ADMIN pending cards alongside coach pending cards (or a new "Corp Admin Approvals" sub-section)

---

## 2. Company-Wide Wellness Analytics API

New endpoints in [backend/app/routers/corporate_command_api.py](backend/app/routers/corporate_command_api.py) scoped by `company_id`:

### `GET /api/corp/analytics/wellness`

Aggregate across all company employees (no individual data exposed):

```sql
SELECT 
  AVG(cm.c_emo) as avg_coherence,
  AVG((cm.nevedal_state->>'gap')::float) as avg_gap,
  AVG((cm.nevedal_state->>'quantum')::float) as avg_quantum,
  AVG(cm.anxiety_level) as avg_anxiety,
  AVG(cm.stress_level) as avg_stress,
  AVG(cm.engagement) as avg_engagement,
  COUNT(*) as employees_with_data
FROM client_metrics cm
JOIN users u ON cm.hardware_id = u.hardware_id
WHERE u.role = 'CLIENT'
  AND (u.company_id = $1::uuid OR u.profile_data->>'company_id' = $2)
```

Mood distribution (aggregate, not individual):

```sql
SELECT mood_current, COUNT(*) as count
FROM client_metrics cm
JOIN users u ON cm.hardware_id = u.hardware_id
WHERE u.role = 'CLIENT' AND (u.company_id = $1::uuid ...)
GROUP BY mood_current
```

Response shape:

```json
{
  "employee_count": 45,
  "employees_with_data": 38,
  "coherence": { "avg": 0.72, "trend": "improving" },
  "gap": { "avg": 0.15 },
  "quantum": { "avg": 0.68 },
  "anxiety": { "avg": 0.31 },
  "stress": { "avg": 0.28 },
  "engagement": { "avg": 0.74 },
  "mood_distribution": { "positive": 18, "neutral": 12, "low": 5, "unknown": 3 },
  "risk_distribution": { "low": 28, "medium": 7, "high": 2, "critical": 1 }
}
```

### `GET /api/corp/analytics/trends?period=30d`

Time-series data for trend graphs. Periods: `30d`, `60d`, `90d`, `6m`, `12m`.

Source: `nevedal_metrics` joined with `users` filtered by `company_id`, grouped by date bucket.

```sql
SELECT DATE_TRUNC('day', nm.recorded_at) as bucket,
       AVG(nm.c_emo) as avg_coherence,
       COUNT(DISTINCT nm.user_id) as active_employees,
       COUNT(CASE WHEN nm.cee_window THEN 1 END) as cee_events
FROM nevedal_metrics nm
JOIN users u ON nm.user_id = u.id
WHERE u.company_id = $1::uuid
  AND nm.recorded_at >= NOW() - $2::interval
GROUP BY 1 ORDER BY 1
```

Also query `client_metrics` snapshots or `sessions` for session-based trends. For 6m/12m periods, use weekly buckets instead of daily.

Three trend lines:

- **Little Nate <> Employees**: AI sessions (`session_type = 'AI'`) count + avg coherence from `nevedal_metrics` where `coach_id IS NULL`
- **Coaches <> Employees**: Coach sessions (`session_type IN ('COACH','GROUP','FAMILY')`) count + avg coherence from `nevedal_metrics` where `coach_id IS NOT NULL`
- **Little Nate <> Coaches**: Sessions where the user IS a coach (join users role = 'COACH' on the company's assigned coaches)

### `GET /api/corp/analytics/coach-team`

Aggregate coach performance for all coaches assigned to the company:

```sql
SELECT 
  COUNT(DISTINCT ca.coach_id) as total_coaches,
  COUNT(DISTINCT s.id) as total_sessions,
  AVG(nm.c_emo) as avg_client_coherence,
  COUNT(CASE WHEN nm.cee_window THEN 1 END) as total_cee_events,
  AVG(cm.engagement) as avg_client_engagement
FROM coach_assignments ca
JOIN sessions s ON s.coach_id = (SELECT id FROM users WHERE hardware_id = ca.coach_id)
JOIN nevedal_metrics nm ON nm.session_id = s.id
JOIN client_metrics cm ON cm.user_id = s.user_id
WHERE ca.entity_type = 'company' AND ca.entity_id = $1
  AND s.started_at >= NOW() - $2::interval
```

### `GET /api/corp/analytics/coach-roi`

Per-coach ROI and attunement scoring (no conversation data):

For each coach assigned to the company:

- **Session volume**: COUNT of sessions in period
- **Client engagement delta**: AVG engagement of their clients now vs. start of period
- **Coherence improvement**: AVG c_emo of their clients now vs. first measurement
- **CEE rate**: CEE events per session (higher = better attunement)
- **Little Nate observation score**: Derived from `coach_nate_progress.average_score` and `coaching_mesh_messages.score` (DOJO performance)
- **Master/Assistant flag**: From `coach_hierarchy` table

Response (per coach, no employee names):

```json
{
  "coaches": [
    {
      "coach_id": "COACH_X_ID",
      "coach_name": "Coach Hope",
      "role_type": "master",
      "assistants": ["Coach Y"],
      "sessions_count": 42,
      "active_clients": 8,
      "avg_coherence_improvement": 0.15,
      "avg_engagement_delta": 0.22,
      "cee_rate_per_session": 1.4,
      "nate_observation_score": 0.78,
      "attunement_index": 0.82
    }
  ]
}
```

**Attunement Index formula** (new, computed in-memory):

```
attunement_index = (
  0.30 * normalized_coherence_improvement +
  0.25 * normalized_engagement_delta +
  0.20 * normalized_cee_rate +
  0.15 * nate_observation_score +
  0.10 * session_consistency
)
```

Where `session_consistency` = sessions in period / expected sessions (penalizes gaps).

---

## 3. Migration

`**backend/migrations/088_corp_analytics.sql**`:

- No new tables required -- all analytics are computed from existing tables (`nevedal_metrics`, `client_metrics`, `sessions`, `coach_assignments`, `coach_hierarchy`, `coach_nate_progress`)
- Add index for performance:

```sql
CREATE INDEX IF NOT EXISTS idx_nevedal_metrics_user_company 
  ON nevedal_metrics(user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_coach_started 
  ON sessions(coach_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_client_metrics_hardware 
  ON client_metrics(hardware_id);
```

---

## 4. Dashboard Frontend

**[dashboard/corporate_command.html](dashboard/corporate_command.html)** -- Add below existing Dashboard panel content:

### Wellness Overview Card (below Overview stats)

- 6-metric gauge grid: Coherence, Gap, Quantum, Anxiety, Stress, Engagement
- Each shows value (0-1), color-coded (green > 0.6, yellow 0.3-0.6, red < 0.3; inverted for anxiety/stress)
- Overall Mood donut chart (positive/neutral/low distribution)
- Risk distribution bar

### Trend Graphs Section

- Period selector: 30d | 60d | 90d | 6m | 12m (button group)
- Chart 1: "Employee Wellness Trends" -- line chart with coherence, engagement, anxiety over time
- Chart 2: "Coaches vs Little Nate" -- dual-axis showing session counts + avg coherence for Coach<>Employee and Nate<>Employee
- Chart 3: "Little Nate <> Coaches" -- line chart for coach engagement with Little Nate
- Use Chart.js (already available in the project) for rendering

### Coach Team Performance Section

- Summary row: Total Coaches | Total Sessions | Avg Client Coherence | CEE Events
- Per-coach table: Name | Role (Master/Assistant) | Sessions | Clients | Coherence Delta | Engagement Delta | CEE Rate | Attunement Index
- Sort by Attunement Index descending (best coaches first)
- No employee-level data in this view -- everything aggregated per coach

### Coach ROI Insights Card

- "Little Nate's Observation" narrative box -- a brief AI-style summary of which coaches have highest/lowest attunement
- Bar chart comparing attunement index across coaches

---

## 5. Auditor Updates

**[backend/app/services/corporate_command_auditor.py](backend/app/services/corporate_command_auditor.py)** -- Add new endpoints to TAB_ENDPOINTS:

- `/api/corp/analytics/wellness`
- `/api/corp/analytics/trends?period=30d`
- `/api/corp/analytics/coach-team`
- `/api/corp/analytics/coach-roi`

Update `trust_baseline` count for `corporate_command_check_count` (currently 21 -> 25).

---

## Deployment Sequence

1. Apply migration 088 (indexes only)
2. Deploy `corporate_command_api.py` (new endpoints)
3. Deploy `admin.py` (approval changes + REST approval endpoints)
4. Deploy `bridge_server.py` (WebSocket approval handlers)
5. Deploy `corporate_command.html` (dashboard UI with Chart.js)
6. Deploy `command.html` (corp admin approval section)
7. Deploy `corporate_command_auditor.py` (new check count)
8. Update trust baseline
9. Restart backend + bridge
10. Verify all tabs render and new endpoints return data

