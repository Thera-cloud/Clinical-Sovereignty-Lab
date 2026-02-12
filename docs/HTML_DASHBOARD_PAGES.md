# CLINICAL SOVEREIGNTY LAB - WEB DASHBOARD HTML PAGES
## Complete Landing Pages & Sub-Page Structure

**Last Updated:** January 27, 2026  
**Total Pages:** 28+ HTML pages across 5 dashboard sections

---

## 📊 DASHBOARD ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         WEB DASHBOARD STRUCTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │    THE EYE      │  │   NEVEDAL LAB   │  │  NIGHT SCHOOL   │            │
│   │  (Admin Panel)  │  │  (Analytics)    │  │   (Training)    │            │
│   │    6 pages      │  │    6 pages      │  │    6 pages      │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│                                                                              │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│   │  CLIENT PORTAL  │  │  COACH PORTAL   │  │ FAMILY SANCTUARY│            │
│   │  (Web Version)  │  │ (Web Version)   │  │  (Web Version)  │            │
│   │    4 pages      │  │    6 pages      │  │    3 pages      │            │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔴 THE EYE (Admin Dashboard) - 6 Pages

### Landing Page: `the_eye.html`
**Purpose:** Central admin overview with real-time platform metrics  
**Access:** ADMIN role only

| Metric | Data Source | Handler |
|--------|-------------|---------|
| Total Users | `analytics.json → platform_totals.total_users` | `admin_get_stats` |
| Total Sessions | `analytics.json → platform_totals.total_sessions` | `admin_get_stats` |
| Revenue | `analytics.json → revenue_metrics.total_revenue` | `admin_get_stats` |
| Active Now | `connected_sessions.size()` (in-memory) | `admin_get_stats` |
| Crisis Watchlist | `Vaults/Clients/*/metrics.json → risk_level=HIGH` | `admin_get_crisis_watchlist` |

**Navigation to Sub-Pages:**
```
┌─────────────────────────────────────────────────┐
│               THE EYE - OVERVIEW                 │
├─────────────────────────────────────────────────┤
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       │
│  │USERS│ │SESS │ │ REV │ │CRISIS│ │COACH│       │
│  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘       │
│     │       │       │       │       │           │
│     ▼       ▼       ▼       ▼       ▼           │
│  _users  _sessions _revenue _crisis _coaches    │
│   .html    .html    .html   .html   .html       │
└─────────────────────────────────────────────────┘
```

---

### Sub-Page 1: `the_eye_users.html`
**Purpose:** User management - view, search, edit users

| Feature | Data Source | Handler |
|---------|-------------|---------|
| User List | `user_registry.json` | `admin_get_users` |
| Search Filter | In-memory JS | Frontend regex |
| Role Badge | `profile.role` | Display only |
| Status | `profile.subscription_status` | `admin_update_user` |
| Edit User | Modal form | `admin_update_user` |
| Delete User | Confirm dialog | `admin_delete_user` |

**WebSocket Messages:**
```javascript
// Get all users
{type: "admin_get_users"}

// Update user
{type: "admin_update_user", user_id: "...", updates: {...}}

// Delete user
{type: "admin_delete_user", user_id: "..."}
```

---

### Sub-Page 2: `the_eye_sessions.html`
**Purpose:** Monitor active and historical sessions

| Feature | Data Source | Status |
|---------|-------------|--------|
| Active Sessions | `connected_sessions` (in-memory) | ✅ Live |
| Session History | `sessions.json` | ⚠️ Planned |
| Duration | Calculated from start_time | ✅ Live |
| View Session | Session detail modal | ✅ Working |

**WebSocket Messages:**
```javascript
// Get active sessions
{type: "admin_get_active_sessions"}

// Get session details
{type: "admin_get_session_detail", session_id: "..."}
```

---

### Sub-Page 3: `the_eye_revenue.html`
**Purpose:** Financial metrics, Stripe integration, token usage

| Feature | Data Source | Integration |
|---------|-------------|-------------|
| Subscriptions | `stripe_billing.json → subscriptions` | ✅ Stripe webhooks |
| Payment Methods | `stripe_billing.json → payment_methods` | ✅ Stripe API |
| Token Usage | `user_registry.json → token_usage_month` | ✅ Local calc |
| Revenue Chart | `analytics.json → revenue_history` | ✅ Chart.js |
| Azure Costs | `analytics.json → azure_costs_month` | ✅ Tracked |

**WebSocket Messages:**
```javascript
// Get revenue stats
{type: "admin_get_revenue_stats"}

// Get subscription list
{type: "admin_get_subscriptions"}
```

---

### Sub-Page 4: `the_eye_crisis.html`
**Purpose:** Crisis watchlist - high-risk users requiring attention

| Feature | Data Source | Trigger |
|---------|-------------|---------|
| High Risk Users | `Vaults/Clients/*/metrics.json → risk_level=HIGH` | Real-time |
| Crisis Count | `metrics.json → crisis_count` | On detection |
| Last Assessment | `metrics.json → last_risk_assessment` | Timestamp |
| Alert History | `crisis_log.json` | Append-only |
| Contact Coach | Button → notification | `notify_coach` |

**Crisis Levels (per ANALYTICS_AND_CRISIS_PROTOCOL.md):**
```
P0 - IMMEDIATE: Keywords like "suicide", "kill myself", "end it all"
     → Auto-notify coach + show 988 resources
     
P1 - HIGH RISK: Keywords like "hopeless", "worthless", "can't go on"
     → Flag for review within 4 hours
     
P2 - ESCALATING: Keywords like "angry", "frustrated", "overwhelmed"
     → Monitor closely, may need intervention
```

**WebSocket Messages:**
```javascript
// Get crisis watchlist
{type: "admin_get_crisis_watchlist"}

// Resolve crisis alert
{type: "admin_resolve_crisis", user_id: "...", resolution: "..."}
```

---

### Sub-Page 5: `the_eye_coaches.html`
**Purpose:** Coach performance metrics and management

| Feature | Data Source | Calculation |
|---------|-------------|-------------|
| Coach List | `user_registry.json (role=COACH)` | Filter |
| Performance | `Vaults/Coaches/{id}/metrics.json` | Per coach |
| Client Count | Count of `assigned_coach_id` matches | Aggregation |
| Session Hours | `schedule.json` per coach | Sum |
| Avg C_emo Improvement | Calculated from client metrics | Complex |

**WebSocket Messages:**
```javascript
// Get coach list with metrics
{type: "admin_get_coaches"}

// Get coach detail
{type: "admin_get_coach_detail", coach_id: "..."}
```

---

## 🔬 NEVEDAL LAB (Emotional Analytics) - 6 Pages

### Landing Page: `nevedal_lab.html` (or `nevedal_lab_old.html`)
**Purpose:** Real-time emotional coherence monitoring

| Metric | Data Source | Update Frequency |
|--------|-------------|------------------|
| C_emo Gauge | `metrics.json → C_emo` | 1Hz (live) |
| P_ent | `metrics.json → P_ent` | 1Hz |
| T_tunnel | `metrics.json → T_tunnel` | 1Hz |
| γ_env | `metrics.json → gamma_env` | 1Hz |
| E_g^(joint) | `metrics.json → E_g_joint` | 1Hz |
| CEE Detected | `metrics.json → cee_window=true` | Real-time |

**Navigation to Sub-Pages:**
```
┌─────────────────────────────────────────────────┐
│            NEVEDAL LAB - LANDING                 │
├─────────────────────────────────────────────────┤
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       │
│  │LIVE │ │LONG │ │DYAD │ │FAMILY│ │COHORT│      │
│  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘       │
│     │       │       │       │       │           │
│     ▼       ▼       ▼       ▼       ▼           │
│  _live   _longit  _dyad  _family _cohort       │
│  .html   .html    .html   .html   .html         │
└─────────────────────────────────────────────────┘
```

---

### Sub-Page 1: `nevedal_lab_live.html`
**Purpose:** Live biometric analysis with real-time gauges

| Feature | Data Source | Update |
|---------|-------------|--------|
| C_emo Animated Gauge | WebSocket stream | 1Hz |
| Biometric Display | `biometrics: {hrv, gsr, breathing}` | 1Hz |
| Component Breakdown | P_ent, T_tunnel, γ_env, E_g | 1Hz |
| CEE Alert | `cee_window === true` | Instant |

**WebSocket Messages:**
```javascript
// Subscribe to user's live data
{type: "nevedal_subscribe", user_id: "CLIENT_EMMA_ID"}

// Incoming updates (server → client)
{type: "nevedal_update", c_emo: 0.73, p_ent: 0.65, ...}
```

---

### Sub-Page 2: `nevedal_lab_longitudinal.html`
**Purpose:** Historical C_emo trends over time

| Feature | Data Source | Time Range |
|---------|-------------|------------|
| Historical C_emo | `metrics.json → history[]` | 7d/30d/90d/all |
| CEE Events | `history[] where cee_window=true` | Filtered |
| Statistics | Calculated from history | Avg, peak, low |
| Trend Line | Chart.js line chart | Smoothed |

**WebSocket Messages:**
```javascript
// Get historical data
{type: "nevedal_get_history", user_id: "...", range: "30d"}
```

---

### Sub-Page 3: `nevedal_lab_dyad.html`
**Purpose:** Compare C_emo between client and coach (dyadic sync)

| Feature | Data Source | Status |
|---------|-------------|--------|
| Client C_emo | `Vaults/Clients/{id}/metrics.json` | ✅ |
| Coach C_emo | `Vaults/Coaches/{id}/metrics.json` | ✅ |
| Synchrony Score | `1.0 - abs(client - coach)` | ⚠️ Pending |
| Side-by-side Gauges | Dual display | ✅ |

**WebSocket Messages:**
```javascript
// Get dyad comparison
{type: "admin_get_dyad_sync", client_id: "...", coach_id: "..."}
```

---

### Sub-Page 4: `nevedal_lab_family.html`
**Purpose:** Family coherence matrix for Family Sanctuary

| Feature | Data Source | Status |
|---------|-------------|--------|
| Family Members | `user_registry.json where family_id=X` | ✅ |
| Member C_emo | `Vaults/Clients/{each}/metrics.json` | ✅ |
| Coherence Matrix | Pairwise calculations | ⚠️ Pending |
| Family Avg | Mean of all members | ✅ |

**WebSocket Messages:**
```javascript
// Get family metrics
{type: "nevedal_get_family", family_id: "FAM_123"}
```

---

### Sub-Page 5: `nevedal_lab_cohort.html`
**Purpose:** Platform-wide emotional analytics by cohort

| Feature | Data Source | Status |
|---------|-------------|--------|
| All Clients | `user_registry.json (role=CLIENT)` | ✅ |
| Platform Avg | Calculated from all metrics | ✅ |
| By Age Groups | Grouped by birthdate | ⚠️ Placeholder |
| By Diagnosis | Grouped by diagnosis field | ⚠️ Placeholder |
| By Treatment | Grouped by assigned_coach_id | ✅ |

**WebSocket Messages:**
```javascript
// Get cohort stats
{type: "admin_get_cohort_stats"}
```

---

## 🎓 NIGHT SCHOOL (AI Training) - 6 Pages

### Landing Page: `night_school.html`
**Purpose:** Training status overview, quick actions

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Total Wisdom Items | `wisdom_database.json → count` | `night_school_stats` |
| Pending Reviews | `COACH_NOTES_INBOX/ → count` | `night_school_stats` |
| Last Training | `learning_history.json → last_run` | Display |
| Run Training | Button → trigger | `run_night_school_session` |

**Navigation to Sub-Pages:**
```
┌─────────────────────────────────────────────────┐
│            NIGHT SCHOOL - LANDING                │
├─────────────────────────────────────────────────┤
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       │
│  │NOTES│ │CURRI│ │WISDOM│ │DOJO │ │STATS│       │
│  └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘ └──┬──┘       │
│     │       │       │       │       │           │
│     ▼       ▼       ▼       ▼       ▼           │
│  _coach  _curric _wisdom  _dojo  _analytics    │
│  _notes   .html   .html   .html    .html        │
│  .html                                          │
└─────────────────────────────────────────────────┘
```

---

### Sub-Page 1: `night_school_coach_notes.html`
**Purpose:** Coach notes inbox with PII detection

| Feature | Data Source | Flow |
|---------|-------------|------|
| Pending Notes | `Vaults/Admin/COACH_NOTES_INBOX/` | File list |
| Approved Notes | `Vaults/Admin/COACH_NOTES/` | File list |
| PII Detected | Regex scan on upload | Red flag UI |
| Approve/Reject | Admin action buttons | Move files |

**Upload Flow:**
```
User selects file → Read as base64
     ↓
upload_coach_note {filename, content_base64}
     ↓
NightSchoolHandler.handle_upload()
     ↓
PII detection (SSN, phone, credit card patterns)
     ↓
Write to COACH_NOTES_INBOX/
     ↓
Status: PENDING_REVIEW
```

**WebSocket Messages:**
```javascript
// Upload note
{type: "upload_coach_note", filename: "...", content_base64: "..."}

// Get pending notes
{type: "get_pending_coach_notes"}

// Approve note
{type: "approve_coach_note", filename: "..."}

// Reject note
{type: "reject_coach_note", filename: "...", reason: "..."}
```

---

### Sub-Page 2: `night_school_curriculum.html`
**Purpose:** Upload and manage training curriculum files

| Feature | Data Source | Supported Formats |
|---------|-------------|-------------------|
| Uploaded Files | `Vaults/Admin/ADMIN_CURRICULUM/` | TXT, MD, PDF, DOCX, PPTX |
| File Count | Directory listing | Display |
| Categories | Filename metadata | cbt, crisis, family, etc. |
| Upload New | Drag & drop | Multi-format |

**Categories (per night_school_curriculum.py):**
```
cbt/           - Cognitive Behavioral Therapy
crisis/        - Crisis intervention & safety
family/        - Family systems & relationships
workplace/     - Career & workplace issues
compliance/    - HIPAA, ethics, legal
attachment/    - Attachment theory
trauma/        - Trauma-informed care
mindfulness/   - Mindfulness & grounding
communication/ - Communication skills
general/       - Uncategorized
_inbox/        - New uploads (unsorted)
```

**WebSocket Messages:**
```javascript
// Upload curriculum file
{type: "upload_curriculum", filename: "...", content_base64: "...", category: "cbt"}

// Get curriculum list
{type: "get_curriculum_list"}

// Move to category
{type: "move_curriculum", filename: "...", target_category: "..."}
```

---

### Sub-Page 3: `night_school_wisdom.html`
**Purpose:** View and edit wisdom database (RAG content)

| Feature | Data Source | Structure |
|---------|-------------|-----------|
| All Wisdom | `wisdom_database.json → wisdom_items[]` | 1247+ items |
| Categories | `wisdom_item.category` | 15 categories |
| Usage Count | `wisdom_item.usage_count` | Tracked |
| Edit Item | Inline editor | Save to JSON |

**Wisdom Item Structure:**
```json
{
  "id": "wisdom_512",
  "content": "When a client expresses hopelessness...",
  "category": "crisis",
  "source": "coach_note_20260115.txt",
  "created_at": "2026-01-15T10:30:00Z",
  "usage_count": 47,
  "effectiveness_score": 0.89
}
```

**WebSocket Messages:**
```javascript
// Get all wisdom
{type: "get_night_school_wisdom"}

// Update wisdom item
{type: "update_night_school_wisdom", id: "wisdom_512", content: "..."}

// Delete wisdom item
{type: "delete_night_school_wisdom", id: "wisdom_512"}

// Add new wisdom
{type: "add_night_school_wisdom", content: "...", category: "..."}
```

---

### Sub-Page 4: `night_school_dojo.html`
**Purpose:** Adversarial testing of Little Nate responses

| Feature | Data Source | Purpose |
|---------|-------------|---------|
| Test Prompts | Manual entry | Challenge AI |
| Response Display | AI response | Evaluate |
| Grade Response | Pass/Fail | Quality check |
| Edge Cases | Predefined tests | Safety |

**Test Categories:**
```
1. Safety Tests
   - Suicide ideation response
   - Dangerous advice rejection
   - Boundary maintenance

2. Quality Tests
   - Empathy presence
   - Appropriate techniques
   - Night School usage

3. Edge Cases
   - Gibberish input
   - Very long input
   - Emotional manipulation
```

**WebSocket Messages:**
```javascript
// Run dojo test
{type: "dojo_test", prompt: "...", expected_behavior: "..."}

// Get test history
{type: "get_dojo_history"}
```

---

### Sub-Page 5: `night_school_analytics.html`
**Purpose:** Training metrics and wisdom usage analytics

| Feature | Data Source | Calculation |
|---------|-------------|-------------|
| Total Wisdom | Count of items | Simple |
| By Category | Group by category | Aggregation |
| Most Used | Sort by usage_count | Top 10 |
| Effectiveness | Average effectiveness_score | Mean |
| Training Runs | `learning_history.json` | List |

**WebSocket Messages:**
```javascript
// Get night school stats
{type: "get_night_school_stats"}
```

---

## 👤 CLIENT PORTAL (Web Version) - 4 Pages

### Landing Page: `client_portal.html`
**Purpose:** Web-based client dashboard (mirrors Flutter app)

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Welcome Message | `profile.name` | Display |
| Token Balance | `profile.token_balance` | Display |
| Recent Sessions | `sessions.json` | List |
| Quick Chat | Button → chat page | Navigate |

---

### Sub-Page 1: `client_chat.html` / `ask_nate.html`
**Purpose:** Chat interface with Little Nate

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Message History | Session memory | Load on connect |
| Send Message | Text input | `send_message` |
| AI Response | Streaming | WebSocket |
| Voice Input | Microphone | Optional |

**WebSocket Messages:**
```javascript
// Send chat message
{type: "send_message", user_message: "...", session_id: "..."}

// Receive streaming response
{type: "ai_response_chunk", content: "...", done: false}
```

---

### Sub-Page 2: `client_metrics.html`
**Purpose:** Personal C_emo and wellness metrics

| Feature | Data Source | Display |
|---------|-------------|---------|
| C_emo Score | `metrics.json → C_emo` | Gauge |
| Mood History | `metrics.json → history` | Chart |
| Session Stats | `metrics.json → sessions_total` | Numbers |
| Breakthroughs | `metrics.json → breakthroughs` | Count |

---

### Sub-Page 3: `client_settings.html`
**Purpose:** Profile and notification settings

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Profile Edit | `profile` object | `update_profile` |
| Notifications | `profile.notifications` | Toggle |
| Change Password | Modal | `change_password` |
| Subscription | Stripe portal | External link |

---

## 👨‍⚕️ COACH PORTAL (Web Version) - 6 Pages

### Landing Page: `coach_portal.html`
**Purpose:** Coach dashboard with client overview

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Client List | `assigned_coach_id` matches | `coach_get_clients` |
| Today's Schedule | `schedule.json` | `get_calendar_data` |
| Pending Reviews | Count of flagged | Display |
| Quick Actions | Buttons | Navigate |

---

### Sub-Page 1: `coach_clients.html`
**Purpose:** Detailed client management

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Client Cards | Profile + metrics | `coach_get_client_detail` |
| Risk Flags | `metrics.risk_level` | Color-coded |
| Session History | Per client | `get_client_sessions` |
| Notes | Coach notes | `get_client_notes` |

---

### Sub-Page 2: `coach_calendar.html`
**Purpose:** Schedule management

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Calendar View | `schedule.json` | `get_calendar_data` |
| Add Session | Modal form | `schedule_session` |
| Cancel Session | Button | `cancel_session` |
| Availability | `availability.json` | `set_availability` |

---

### Sub-Page 3: `coach_session_notes.html`
**Purpose:** Session documentation

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Note Entry | Text area | `save_session_notes` |
| Client Context | Pre-loaded | `get_pre_session_brief` |
| AI Summary | Optional | `generate_session_summary` |
| Upload to Night School | Button | `upload_coach_note` |

---

### Sub-Page 4: `coach_ask_nate.html`
**Purpose:** Coach-specific AI assistance

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Coaching Advice | AI response | `ask_nate_coaching` |
| Client Context | Optional include | Toggle |
| Technique Lookup | Night School | RAG query |

**WebSocket Messages:**
```javascript
// Ask for coaching advice
{type: "ask_nate_coaching", query: "...", client_id: "...", context: "..."}
```

---

### Sub-Page 5: `coach_reports.html`
**Purpose:** Generate reports for clients/supervisors

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Client Progress | Aggregated metrics | `generate_progress_report` |
| Session Summary | Session data | `generate_session_report` |
| Export PDF | jsPDF | Client-side |

---

## 👨‍👩‍👧‍👦 FAMILY SANCTUARY (Web Version) - 3 Pages

### Landing Page: `family_sanctuary.html`
**Purpose:** Create or join Family Sanctuary session

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Create Session | Button (HOH only) | `sanctuary_create` |
| Join Existing | Invitation code | `sanctuary_join` |
| Session Status | Active sanctuary | `sanctuary_get_status` |

---

### Sub-Page 1: `sanctuary_session.html`
**Purpose:** Active Family Sanctuary chat room

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Member List | `sanctuary.members` | Live update |
| Chat Messages | `sanctuary.messages` | WebSocket stream |
| Little Nate | AI responses | Auto-triggered |
| Coaching Offer | Modal popup | `sanctuary_coaching_accept` |
| Exit Button | Confirm dialog | `sanctuary_exit` |

**WebSocket Messages:**
```javascript
// Send sanctuary message
{type: "sanctuary_message", sanctuary_id: "...", message: "..."}

// Accept coaching
{type: "sanctuary_coaching_accept", sanctuary_id: "...", intervention_id: "...", assisted_response: false}

// Exit sanctuary
{type: "sanctuary_exit_confirm", sanctuary_id: "...", reason: "..."}
```

---

### Sub-Page 2: `sanctuary_summary.html`
**Purpose:** Post-session summary and billing

| Feature | Data Source | Handler |
|---------|-------------|---------|
| Duration | `sanctuary.duration` | Calculated |
| Message Count | `sanctuary.metrics.total_messages` | Display |
| Breakthroughs | `sanctuary.metrics.breakthrough_moments` | Display |
| Total Charges | `sanctuary.billing.total_charges` | Display |
| Transcript | Optional download | `sanctuary_get_transcript` |

---

## 📄 COMPLETE FILE LIST

### The Eye (Admin)
```
dashboard/the_eye/
├── the_eye.html                  # Landing - Overview
├── the_eye_users.html            # Sub - User management
├── the_eye_sessions.html         # Sub - Session monitoring
├── the_eye_revenue.html          # Sub - Financial metrics
├── the_eye_crisis.html           # Sub - Crisis watchlist
└── the_eye_coaches.html          # Sub - Coach performance
```

### Nevedal Lab (Analytics)
```
dashboard/nevedal_lab/
├── nevedal_lab.html              # Landing - Overview
├── nevedal_lab_live.html         # Sub - Live analysis
├── nevedal_lab_longitudinal.html # Sub - Historical trends
├── nevedal_lab_dyad.html         # Sub - Client-coach sync
├── nevedal_lab_family.html       # Sub - Family coherence
└── nevedal_lab_cohort.html       # Sub - Platform cohorts
```

### Night School (Training)
```
dashboard/night_school/
├── night_school.html             # Landing - Overview
├── night_school_coach_notes.html # Sub - Coach notes inbox
├── night_school_curriculum.html  # Sub - Training files
├── night_school_wisdom.html      # Sub - Wisdom editor
├── night_school_dojo.html        # Sub - Adversarial testing
└── night_school_analytics.html   # Sub - Training metrics
```

### Client Portal (Web)
```
dashboard/client/
├── client_portal.html            # Landing - Dashboard
├── client_chat.html              # Sub - AI chat
├── client_metrics.html           # Sub - Personal metrics
└── client_settings.html          # Sub - Settings
```

### Coach Portal (Web)
```
dashboard/coach/
├── coach_portal.html             # Landing - Dashboard
├── coach_clients.html            # Sub - Client management
├── coach_calendar.html           # Sub - Schedule
├── coach_session_notes.html      # Sub - Documentation
├── coach_ask_nate.html           # Sub - AI assistance
└── coach_reports.html            # Sub - Reports
```

### Family Sanctuary (Web)
```
dashboard/sanctuary/
├── family_sanctuary.html         # Landing - Create/Join
├── sanctuary_session.html        # Sub - Active session
└── sanctuary_summary.html        # Sub - Post-session
```

---

## 🔗 COMMON NAVIGATION PATTERN

All pages share consistent navigation:

```html
<!-- Shared Header -->
<nav class="dashboard-nav">
  <a href="/the_eye.html">The Eye</a>
  <a href="/nevedal_lab.html">Nevedal Lab</a>
  <a href="/night_school.html">Night School</a>
  <a href="/client_portal.html">Client</a>
  <a href="/coach_portal.html">Coach</a>
</nav>

<!-- Shared WebSocket Connection -->
<script>
  const ws = new WebSocket('ws://localhost:8765');
  
  ws.onopen = () => {
    // Authenticate
    ws.send(JSON.stringify({
      type: 'login_request',
      username: sessionStorage.getItem('username'),
      password: sessionStorage.getItem('password'),
      expected_role: 'ADMIN'
    }));
  };
</script>
```

---

**Total HTML Pages:** 28  
**Landing Pages:** 6  
**Sub-Pages:** 22  

**Document Version:** 1.0  
**Last Updated:** January 27, 2026
