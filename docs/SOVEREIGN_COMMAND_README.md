# Little Nate — Sovereign Command Admin Console
## Complete UX Mockup Documentation & Integration Guide

**Project:** Little Nate AI Therapy Platform  
**Version:** 2.0  
**Date:** January 21, 2026  
**Status:** HTML Mockups Complete — Ready for Implementation

---

## 📁 FILE INVENTORY

All files located in `/mnt/user-data/outputs/`:

| File | Size | Description |
|------|------|-------------|
| `sc_01_dashboard.html` | 33KB | Main admin dashboard |
| `sc_02_user_management.html` | 32KB | User management + Matchmaker Protocol |
| `sc_03_night_school.html` | 39KB | AI Training Center (The Dojo) |
| `sc_04_the_eye.html` | 40KB | Analytics & Surveillance |
| `sc_05_audit_log.html` | 26KB | Immutable Sovereignty Audit Log |
| `sc_06_nate_features.html` | 33KB | Little Nate AI Advanced Features |
| `sc_07_nevedal_lab.html` | 45KB | Nevedal Research Laboratory |
| `coach_portal_v2_complete.dart` | 75KB | Coach Portal Flutter UI (Phase 1) |
| `bridge_handlers_v2.py` | 29KB | Python WebSocket handlers (Phase 1) |

---

## 🎨 DESIGN SYSTEM

### Color Palette

```css
/* Backgrounds */
--bg-dark: #0A0A0A;        /* Main background */
--bg-card: #111111;        /* Card backgrounds */
--bg-elevated: #1A1A1A;    /* Elevated elements */
--border: #252525;         /* Borders */

/* Primary Colors */
--gold: #FFD700;           /* Admin actions, sovereign theme */
--gold-dim: rgba(255, 215, 0, 0.2);

/* Status Colors */
--red-critical: #FF3B3B;   /* Alerts, danger, crisis */
--red-dim: rgba(255, 59, 59, 0.15);
--green: #00FF88;          /* Success, safe, approved */
--green-dim: rgba(0, 255, 136, 0.1);
--orange: #FF9500;         /* Warnings, moderate alerts */

/* Feature Colors */
--cyan: #00D4FF;           /* Little Nate AI, client elements */
--cyan-dim: rgba(0, 212, 255, 0.1);
--purple: #9D4EDD;         /* Research, Night School, training */
--purple-dim: rgba(157, 78, 221, 0.15);
--blue: #4A90D9;           /* Informational, links */
--blue-dim: rgba(74, 144, 217, 0.15);

/* Text */
--text-primary: #FFFFFF;
--text-secondary: #888888;
```

### Color Usage by Context

| Context | Primary Color | Use Case |
|---------|---------------|----------|
| Admin/Sovereign | Gold (#FFD700) | Buttons, headers, admin actions |
| Little Nate AI | Cyan (#00D4FF) | AI chat, Nate features, client data |
| Crisis/Danger | Red (#FF3B3B) | Alerts, crisis watchlist, disconnect |
| Success/Safe | Green (#00FF88) | Approvals, safe status, CEE windows |
| Warning | Orange (#FF9500) | Moderate alerts, PII flags |
| Research/Training | Purple (#9D4EDD) | Night School, Nevedal Lab, Dojo |
| Coaches | Gold (#FFD700) | Coach avatars, performance |
| Clients | Cyan (#00D4FF) | Client avatars, user data |
| Minors/Family | Purple (#9D4EDD) | Family members, guardian mode |

### Component Patterns

```css
/* Cards */
border-radius: 12px;
border: 1px solid var(--border);
background: var(--bg-card);

/* Buttons */
border-radius: 8px;
padding: 10px 20px;
font-size: 12px;

/* Badges/Tags */
border-radius: 10px (pills) or 4px (tags);
padding: 3px 8px;
font-size: 9-10px;

/* Avatars */
border-radius: 50%;
border: 2px solid [role-color];

/* Progress Bars */
height: 6-8px;
border-radius: 3-4px;
```

### Typography

- **Font Family:** 'Segoe UI', system-ui, sans-serif
- **Monospace:** 'Consolas', 'Monaco', monospace (for code/JSON)
- **Math/Formulas:** 'Times New Roman', serif

---

## 📄 SCREEN-BY-SCREEN BREAKDOWN

### SC_01: Dashboard

**Purpose:** Main admin overview with real-time system health

**Key Components:**
- Header with system status indicators (Bridge, Azure, Night School)
- Crisis Watchlist with severity levels (critical/warning/normal)
- Live Sessions grid showing active WebSocket connections
- System Metrics (users, sessions, coaches, alerts)
- Pending Approvals queue
- Community Nevedal State health bars
- Token Economics spend tracking
- Activity Feed timeline

**Data Requirements:**
```python
{
    "system_status": {"bridge": "online", "azure": "online", "night_school": "training"},
    "crisis_watchlist": [{"user_id", "name", "severity", "trigger", "duration"}],
    "live_sessions": [{"user_id", "name", "type", "duration", "coach", "tier", "tokens_used"}],
    "metrics": {"active_users", "live_sessions", "coaches_online", "critical_alerts"},
    "pending_approvals": [{"coach_id", "name", "specialty", "submitted_date"}],
    "community_health": {"anxiety": 0-100, "stability": 0-100, "engagement": 0-100},
    "token_economics": {"daily_spend", "daily_budget", "percentage"}
}
```

---

### SC_02: User Management

**Purpose:** Individual user detail view with Matchmaker and Family tools

**Key Components:**
- User search sidebar with role filters
- Matchmaker Protocol (AI coach-client compatibility scoring)
- Basic Information panel
- Nevedal State metrics display
- Family Genealogy visual tree
- Identity Resolution tools (reset password, biometrics, ban, wipe)

**Matchmaker Protocol Algorithm:**
```python
def calculate_compatibility(client, coach):
    """
    Inputs:
    - client.anxiety_level (0-1)
    - client.regulation_score (0-1)
    - client.openness (0-1)
    - coach.specialties []
    - coach.style (directive/reflective/integrative)
    - coach.success_rate_by_issue {}
    
    Output: compatibility_score (0-100), reasoning_text
    """
```

**Family Genealogy Data Structure:**
```python
{
    "family_id": "FAM_0023",
    "head_of_household": {"user_id", "name", "role": "HoH"},
    "members": [
        {"user_id", "name", "relationship": "spouse|child|dependent", "is_minor": bool}
    ],
    "links": [{"from_id", "to_id", "relationship_type"}]
}
```

---

### SC_03: Night School Director

**Purpose:** AI training center for Little Nate's wisdom

**Key Components:**

#### The Dojo (Adversarial Simulation)
- Chat interface for stress-testing Nate
- Persona selector: Hostile, Crisis, Skeptic, Minor
- Real-time simulation analysis metrics
- Safety protocol verification

#### Model Versioning (Time Travel)
- Version timeline with snapshots
- Revert/Compare/Delete actions
- Current version indicator
- Change logs per version

#### Coach Notes Audit Queue
- PII detection with highlighting
- Approve/Reject/Redact workflow
- Source tracking (coach, session ID)

#### Curriculum Injection
- File upload zone (PDF, TXT, DOCX, MD)
- Processing status tracking
- Ingestion history

#### Wisdom Editor
- Direct JSON editing of `little_nate_wisdom.json`
- Syntax highlighting
- Snapshot-before-edit safety

**Wisdom Entry Schema:**
```json
{
    "id": 847,
    "category": "crisis_intervention|cbt_techniques|boundary_setting|...",
    "source": "coach_notes|curriculum_pdf|manual_entry",
    "content": "The actual wisdom text...",
    "confidence": 0.0-1.0,
    "approved": true|false,
    "timestamp": "ISO-8601"
}
```

---

### SC_04: The Eye (Analytics & Surveillance)

**Purpose:** System-wide analytics and real-time monitoring

**Key Components:**

#### Token Economics Monitor
- Daily/Weekly spend tracking
- Budget consumption bar with limit marker
- Throttle control slider
- Per-tier feature toggles (Voice/Vision for Top Tier/Standard/Trial)

#### Usage Breakdown
- Cost by modality (Voice/Text/Vision)
- Token counts per category

#### Coach Performance Heatmap
- Ranked table of all coaches
- Metrics: Breakthroughs, Retention, Satisfaction, Sessions/Week, Avg Duration, AI Collab Score, Revenue
- Heat coloring (green=high, gold=medium, red=low)

#### Live Session Monitor
- Grid of active sessions
- Tier badges (Top Tier, Standard, Trial)
- Type badges (AI, Coach, Crisis)
- Force Disconnect capability
- Real-time token spend per session

#### Crisis Feed
- Active crisis alerts
- Severity indicators
- Quick action buttons

#### Community Nevedal State
- Aggregate health metrics across all users

---

### SC_05: Audit Log

**Purpose:** Immutable record of all administrative actions

**Key Components:**
- Filter sidebar (date range, action types, administrators, targets)
- Audit statistics summary
- Immutability notice banner
- Timeline view grouped by date
- Entry types with color coding:
  - Access (cyan)
  - Modify (orange)
  - Create (green)
  - Delete (red)
  - Security (purple)

**Audit Entry Schema:**
```json
{
    "id": "AUD_20260121_001",
    "timestamp": "ISO-8601",
    "admin_id": "admin_sovereign",
    "admin_name": "Display Name",
    "admin_role": "Super Admin",
    "ip_address": "192.168.1.x",
    "action_type": "access|modify|create|delete|security",
    "target_type": "user|coach|system|wisdom",
    "target_id": "user_123",
    "target_name": "Display Name",
    "description": "Human readable action description",
    "old_value": "...",  // for modifications
    "new_value": "...",  // for modifications
    "compliance_flag": "RTBF|HIPAA|..."  // optional
}
```

**CRITICAL:** Audit log must be append-only. No modifications or deletions permitted.

---

### SC_06: Little Nate AI Features

**Purpose:** Advanced AI capabilities configuration and monitoring

**Key Components:**

#### Deadman Switch
- Silence threshold configuration (days)
- Active watchlist with auto-alert status
- Notifications sent log

```python
def check_deadman_switch():
    """
    For each user on crisis_watchlist:
    - If last_activity > silence_threshold_days:
        - Alert assigned coach
        - Alert guardian (if minor or has guardian)
        - Log to audit
    """
```

#### Swarm Intelligence (Transgenerational Pattern Detection)
- Family dynamics correlation detection via the **Pattern Engine** (`pattern_engine.py`)
- Cross-member emotional theme correlation, coping inheritance classification, trigger mapping
- Privacy-preserving insights (no individual content shared across family members)
- Powered by the broader Sovereign Swarm Intelligence (SSI) multi-agent architecture — see `docs/THEORETICAL_FRAMEWORK.md` §4-5

```python
def detect_family_correlations(family_id):
    """
    Analyze session data across family members via PatternEngineService.
    Detect: emotional theme correlation, coping mechanism inheritance,
    trigger pattern mapping, coherence trajectory correlation.
    Output confidence scores without revealing individual content.
    Uses: pattern_engine.full_transgenerational_analysis(family_id)
    """
```

#### Nate the Nudge
- Proactive notification system
- Types: Session prep, Mood logging, Milestone celebration
- Status tracking: Pending, Sent, Opened

#### AI Modes

**Tri-Corder Mode:**
- 30-second biometric baseline calibration
- Voice stress analysis, resting HR, stress index
- Waveform visualization

**Archivist Mode:**
- Legacy builder for elderly/terminally ill
- Biography chapters with voice recordings
- "Wisdom Memories" for family vault

**Guardian Mode:**
- Parental proxy summaries for minors
- Confidentiality-preserving (e.g., "anxious about school" not specifics)
- Summary generation on demand

**Supervisor Mode:**
- Coach session analysis
- Empathy and technique grading
- Training recommendations

---

### SC_07: Nevedal Research Laboratory

**Purpose:** Quantum emotional coherence research platform

**THIS IS THE MOST IMPORTANT THEORETICAL COMPONENT**

#### The Nevedal Formula

```
C_emo(t) = [β · p_ent · T₀ · e^(-d/λ)] / [γ_env + E_G^(joint)/ℏ] · exp[-(γ_env + E_G^(joint)/ℏ)t]
```

#### Variable Definitions

| Variable | Name | Range | Description |
|----------|------|-------|-------------|
| **C_emo(t)** | Quantum Emotional Coherence | 0-1 | The main output — emotional coherence between A and B at time t |
| **p_ent** | Emotional Entanglement | 0-1 | Degree of cross-person entanglement between tubulin ensembles |
| **T_tunnel** | Tunneling Transparency | 0-1 | How easily states tunnel across interpersonal gap (T₀·e^(-d/λ)) |
| **d** | Interpersonal Distance | 0-∞ | Effective distance (physical or relational) |
| **λ** | Tunneling Length | constant | Characteristic tunneling scale |
| **γ_env** | Decoherence Rate | 0-1 | Environmental noise / classical brain activity disruption |
| **E_G^(joint)** | Joint Mass-Energy | 0-1 | Penrose gravitational self-energy for A-B joint state |
| **β** | Coupling Constant | constant | Scales entanglement/tunneling into coherence growth |
| **ℏ** | Reduced Planck Constant | constant | Gives Penrose reduction time τ ≈ ℏ/E_G |

#### Biometric → Variable Mapping

| Nevedal Variable | Biometric Signals | Inference Method |
|------------------|-------------------|------------------|
| **p_ent** | HRV synchrony, Breath sync, Vocal prosody mirroring, Postural echo | Higher synchrony → higher p_ent |
| **T_tunnel** | Gaze contact %, Body lean angle, Verbal sharing rate | More approach behaviors → higher T_tunnel |
| **γ_env** | EDA spikes, HR elevation, Speech fragmentation, Interruptions | More arousal/noise → higher γ_env |
| **E_G^(joint)** | Sentiment polarity, Topic modeling weight, Trauma markers, Dissociation indicators | More emotional load → higher E_G |

#### CEE (Corrective Emotional Experience) Detection

A CEE window is detected when:
1. **p_ent(t) is HIGH** — Strong dyadic synchrony
2. **d(t) is LOW** — Reduced defensive distance
3. **γ_env(t) is LOW/DROPPING** — Client is regulated enough to feel
4. **E_G^(joint) is MODERATE-HIGH** — Significant therapeutic material present

```python
def detect_cee_window(p_ent, d, gamma_env, e_g_joint):
    """
    Returns True if conditions indicate optimal therapeutic moment.
    AI should prompt therapist: "Client shows sustained regulation with 
    high synchrony for 20-30 seconds; continue empathic reflection, 
    avoid premature problem-solving."
    """
    if p_ent > 0.7 and d < 0.4 and gamma_env < 0.3 and e_g_joint > 0.4:
        return True
    return False
```

#### Research Tools

- **Dyad Selection:** Choose Subject A and B from clients, coaches, family
- **Cross-Reference Matrix:** Family coherence heatmap
- **Report Generator:**
  - Individual Coherence Report
  - Dyad Comparison Report
  - Family Dynamics Report
  - Longitudinal Trends (12-week)
  - Coach Efficacy Analysis
- **Session History:** Historical C_emo scores and CEE counts

#### Ethics Notice

> This research platform operates under IRB Protocol #QEC-2026-001. All participants have provided informed consent for quantum coherence measurement. Data is de-identified for aggregate analysis. The "quantum" framework is a **metaphorical model** for organizing biometric synchrony data, not a claim of literal quantum effects between brains.

---

## 🔧 IMPLEMENTATION GUIDANCE

### Recommended Tech Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| **Mobile App** | Flutter/Dart | Cross-platform, existing coach_portal_v2 code |
| **Web Admin** | React or Flutter Web | Match HTML mockup fidelity |
| **Backend API** | Python FastAPI | Async, WebSocket support |
| **Real-time** | WebSockets | For live session monitoring, Nevedal streaming |
| **Database** | PostgreSQL | Relational for users, sessions, audit log |
| **Time-series** | InfluxDB or TimescaleDB | For Nevedal metrics streaming |
| **AI/ML** | Azure OpenAI | GPT-4 for Nate, Whisper for voice |
| **Biometrics** | Custom pipeline | HRV from wearables, voice analysis, video for gaze/posture |

### API Endpoints Needed

```
# Dashboard
GET  /api/admin/dashboard/stats
GET  /api/admin/dashboard/crisis-watchlist
GET  /api/admin/dashboard/live-sessions
WS   /ws/admin/live-feed

# User Management
GET  /api/admin/users
GET  /api/admin/users/{id}
GET  /api/admin/users/{id}/matchmaker
GET  /api/admin/users/{id}/family-tree
POST /api/admin/users/{id}/reset-password
POST /api/admin/users/{id}/wipe-memory
POST /api/admin/users/{id}/ban

# Night School
GET  /api/admin/night-school/versions
POST /api/admin/night-school/snapshot
POST /api/admin/night-school/revert/{version}
GET  /api/admin/night-school/coach-notes
POST /api/admin/night-school/coach-notes/{id}/approve
POST /api/admin/night-school/coach-notes/{id}/reject
POST /api/admin/night-school/curriculum/upload
WS   /ws/admin/dojo-simulation

# The Eye
GET  /api/admin/analytics/token-economics
GET  /api/admin/analytics/coach-heatmap
GET  /api/admin/analytics/live-sessions
POST /api/admin/analytics/throttle
POST /api/admin/sessions/{id}/disconnect

# Audit Log
GET  /api/admin/audit-log
GET  /api/admin/audit-log/export

# Nate Features
GET  /api/admin/nate/deadman-switch
POST /api/admin/nate/deadman-switch/configure
GET  /api/admin/nate/swarm-intelligence/{family_id}
GET  /api/admin/nate/ai-modes/status

# Nevedal Lab
GET  /api/research/nevedal/live/{session_id}
GET  /api/research/nevedal/history/{user_id}
GET  /api/research/nevedal/dyad/{user_a}/{user_b}
GET  /api/research/nevedal/family/{family_id}/matrix
POST /api/research/nevedal/reports/generate
WS   /ws/research/nevedal/stream/{session_id}
```

### WebSocket Message Format (Nevedal Streaming)

```json
{
    "type": "nevedal_update",
    "session_id": "sess_123",
    "timestamp": "2026-01-21T14:32:00.123Z",
    "c_emo": 0.73,
    "components": {
        "p_ent": 0.81,
        "t_tunnel": 0.68,
        "gamma_env": 0.23,
        "e_g_joint": 0.54
    },
    "biometrics": {
        "subject_a": {
            "hrv_rmssd": 68,
            "resp_rate": 14,
            "gaze_contact": 0.78,
            "body_lean": 15,
            "eda": 2.3
        },
        "subject_b": {
            "hrv_rmssd": 72,
            "resp_rate": 13,
            "gaze_contact": 0.82,
            "body_lean": 12,
            "eda": 1.8
        },
        "synchrony": {
            "hrv": 0.89,
            "breath": 0.92,
            "gaze": 0.71,
            "posture": 0.88
        }
    },
    "cee_window": true,
    "cee_duration_seconds": 23
}
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Core Admin (Weeks 1-2)
- [ ] Implement sc_01 Dashboard
- [ ] Implement sc_02 User Management (without Matchmaker AI)
- [ ] Implement sc_05 Audit Log
- [ ] Set up WebSocket infrastructure

### Phase 2: AI Training (Weeks 3-4)
- [ ] Implement sc_03 Night School
- [ ] Build Dojo simulation endpoint
- [ ] Implement coach notes approval workflow
- [ ] Build wisdom versioning system

### Phase 3: Analytics (Weeks 5-6)
- [ ] Implement sc_04 The Eye
- [ ] Build token economics tracking
- [ ] Implement coach heatmap queries
- [ ] Build live session monitor with force-disconnect

### Phase 4: Nate Features (Weeks 7-8)
- [ ] Implement sc_06 Nate Features
- [ ] Build Deadman Switch cron job
- [ ] Build Swarm Intelligence correlation engine (Pattern Engine — transgenerational analysis)
- [ ] Implement AI mode configurations

### Phase 5: Nevedal Lab (Weeks 9-12)
- [ ] Implement sc_07 Nevedal Lab
- [ ] Build biometric ingestion pipeline
- [ ] Implement Nevedal formula computation
- [ ] Build CEE window detection algorithm
- [ ] Create report generation system
- [ ] Build longitudinal analysis queries

---

## 💬 BIG NATE CHAT — 8-Mode Command Interface

### Overview

Big Nate Chat is the primary human-AI command interface between Big Nate (admin/creator) and Little Nate (AI companion). It is available in two locations:

- **SkyEye Dashboard** (`dashboard/skyeye.html`, "Big Nate Chat" tab) — HTML dashboard interface
- **Sovereign Command Admin Console** (`admin/src/components/BigNateChat.jsx`) — React admin component

Both frontends use a **single unified backend**: `POST /api/skyeye/chat` and `GET /api/skyeye/chat`, powered by `SkyEyeChatService` in `backend/app/services/skyeye_chat.py`.

### 8 Conversation Modes

| Mode | Triggers | Authority | Description |
|------|----------|-----------|-------------|
| **Strategy** (default) | General conversation | Swarm | Brainstorming, insights, performance discussion. Proposes actions with `[PROPOSAL: type]` markers. |
| **Command** | "approved", "go for it", "reject", "hold" | Swarm | Approve/reject pending proposals. Executes via Marketing Brain command protocol. |
| **Briefing** | "briefing", "brief me", "status report", "sitrep" | Swarm | Sovereign briefing from all 6 strategic memory layers (L1-L6). |
| **Inquiry** | "how many", "show me", "analytics", "stats" | Swarm | Data questions routed to platform metrics, campaign stats, and specific services. |
| **Swarm** | "swarm", "fibres", "spawn", "prune", "mesh health" | Swarm | Fibre inventory, Wisdom Mesh health, convergence alerts, spawn/prune commands. |
| **Marketing** | "marketing", "campaign", "playbook", "funnel", "audience" | Marketing | Full marketing authority: playbook review, pending actions, funnel stats, content strategy. |
| **Defense** | "defense", "security", "threat", "hive", "attack" | Defense | Full defense authority: Hive Defense v4 readiness, threat alerts, Guardian Fibre status. |
| **Admin** | "admin", "billing", "revenue", "subscription", "audit log" | Admin | Full admin authority: user stats, subscription billing, tier breakdown, audit log. |

### Three Authorities

**Marketing Authority** — Big Nate can:
- Review and update the marketing playbook (content pillars, audiences, content mix)
- View and decide on pending marketing actions (approve/reject/defer)
- Monitor funnel stats (prospects, conversions, by platform, by audience)
- Discuss campaign strategy with full context enrichment from MarketingBrain

**Defense Authority** — Big Nate can:
- Monitor Hive Defense v4 service readiness (GuardianFibre, PipelineDrum, SentinelMesh, etc.)
- View active threat alerts and recent security incidents (24h window)
- Check Guardian Fibre events and behavioral telemetry
- Review webhook fortress verification stats
- Recommend defensive actions (execution requires separate admin action)

**Administration Authority** — Big Nate can:
- View user statistics (total, active, by role, by tier)
- Monitor subscription and billing data (active, past due, canceled)
- Access recent audit log entries
- Discuss system health and administrative decisions
- Recommend admin actions (execution requires separate admin action)

### API Contract

```
GET  /api/skyeye/chat?limit=50     — Retrieve persistent chat history
POST /api/skyeye/chat               — Send message, get AI response
     Body: { "message": "...", "mode": "strategy" }
     Response: { "id", "sender", "message", "mode", "created_at", "follow_up_suggestions" }
```

The `mode` field is optional. When provided, it overrides auto-detection. When omitted, the service uses keyword-based mode detection from the message content.

### Backend Architecture

```
BigNateChat.jsx / skyeye.html
        ↓ POST /api/skyeye/chat { message, mode }
    skyeye_api.py router
        ↓
    SkyEyeChatService (skyeye_chat.py)
        ├── Mode Detection (8 modes)
        ├── Context Enrichment
        │   ├── Strategy/Briefing/Swarm → StrategicMemoryService
        │   ├── Marketing → MarketingBrain (playbook, actions, funnel)
        │   ├── Defense → Hive Defense tables (status, alerts, events)
        │   └── Admin → Users, subscriptions, audit_log tables
        ├── Marketing Context (appended to all modes)
        └── Azure OpenAI Realtime WebSocket → AI response
```

Messages are persisted in the `skyeye_chat` PostgreSQL table with sender, message, and metadata (including detected mode).

---

## 🧠 KEY CONTEXT FOR FUTURE SESSIONS

### What is Little Nate?
Little Nate is an AI therapy companion that works alongside human coaches. It provides 24/7 support between sessions, learns from coach notes, and tracks emotional coherence using the Nevedal framework.

### What is Sovereign Command?
The admin console for platform administrators. "Dark Sovereign" theme (black/gold/red) represents ultimate control over the system.

### What is the Nevedal Theory?
A "toy" theoretical framework that models emotional coherence between two people using quantum mechanics metaphors (Penrose objective reduction, microtubule tunneling). It's used as an organizing model for biometric synchrony data, NOT a claim of literal quantum effects.

### Who are the user types?
- **Clients:** People receiving therapy
- **Coaches:** Licensed therapists
- **Minors:** Children under 18 (special protections)
- **Guardians:** Parents/guardians who receive proxy summaries
- **Family (HoH):** Head of household in family accounts
- **Admins:** Platform administrators

### What files already exist?
- `coach_portal_v2_complete.dart` — Flutter UI for coach-facing features
- `bridge_handlers_v2.py` — Python WebSocket handlers
- `INTEGRATION_GUIDE.md` — Phase 1 integration docs

---

## 📞 QUICK START FOR NEW CLAUDE SESSION

Copy and paste this to any new Claude session:

```
I'm working on Little Nate, an AI therapy platform. We've completed 7 HTML 
mockups for the admin console called "Sovereign Command." I need help 
implementing these in [Flutter/React/Python].

The files are:
- sc_01_dashboard.html through sc_07_nevedal_lab.html

Design system: Dark theme, Gold (#FFD700) for admin, Cyan (#00D4FF) for 
Nate AI, Purple (#9D4EDD) for research, Red (#FF3B3B) for alerts.

Key feature: The Nevedal Theory (sc_07) implements a quantum emotional 
coherence formula: C_emo(t) computed from biometric synchrony between 
therapist and client.

Please read the SOVEREIGN_COMMAND_README.md file I'm uploading for full context.
```

---

## 📎 ATTACHED REFERENCE FILES

When starting a new session, upload these files:
1. `SOVEREIGN_COMMAND_README.md` (this file)
2. `NevedalTheory_LittleNate.pdf` (the original theory document)
3. Any specific HTML files you want to implement

---

---

## 📖 NATE CAMPAIGN EXECUTION SYSTEM

### Overview
Little Nate has full capability to design, execute, and manage multi-episode interactive storytelling campaigns across all connected social media platforms. This system bridges the gap between Big Nate Chat strategy discussions and real-world content publishing.

### Architecture

```
Big Nate Chat (strategy discussion)
        ↓
   Marketing Brain (design_campaign / execute_approved_action)
        ↓
   SkyEye Content Generator (generate posts / video scripts)
        ↓
   skyeye_content_queue (DB — with campaign_id, episode_number, sequence_order)
        ↓
   SkyEye Session Engine (_post_phase — respects scheduled_for + depends_on_post_id)
        ↓
   Platform Adapters (LinkedIn, Reddit, TikTok, Instagram, Facebook, Pinterest)
```

### Campaign Flow
1. **Design**: Big Nate or Little Nate (autonomously) calls `design_campaign()` in MarketingBrain
2. **Template Selection**: Optional use of built-in templates (romance_arc, heros_journey, community_challenge, educational_series, testimonial_showcase)
3. **AI Episode Generation**: Azure OpenAI generates episode content per platform, adapted to each platform's voice
4. **Queue**: All posts are queued in `skyeye_content_queue` with `campaign_id`, `episode_number`, `sequence_order`, `scheduled_for`, and `depends_on_post_id`
5. **Schedule Enforcement**: `get_queue(respect_schedule=True)` ensures posts only publish when their time arrives and their dependency (previous episode) has been posted
6. **Publishing**: Session engine picks up scheduled posts and publishes via platform adapters
7. **Feedback Loop**: During `_observe_phase()`, the session engine aggregates audience engagement on campaign posts, checks engagement thresholds, and auto-generates next episodes when ready

### Campaign Templates (DB: `campaign_templates`)
| Template | Episodes | Interval | Description |
|----------|----------|----------|-------------|
| romance_arc | 6 | 24h | Interactive romance with cliff-hangers and audience voting |
| heros_journey | 5 | 48h | Personal growth following departure → trials → transformation → return |
| community_challenge | 4 | 72h | Audience participation with tasks and leaderboard energy |
| educational_series | 6 | 48h | Deep-dive topic exploration with discussion prompts |
| testimonial_showcase | 4 | 72h | Anonymized client moments woven into narrative |

### A/B Testing
- When `ab_test_enabled` is true, each episode generates two variant hooks (A and B)
- Variant A posts to the first half of platforms, variant B to the rest
- Session engine picks the engagement winner and feeds it to the next episode's AI prompt

### Engagement Thresholds
- `min_engagement_threshold`: If total engagement (comments + likes + shares) falls below this, the campaign is auto-paused
- `extend_engagement_threshold`: If engagement exceeds this, the campaign auto-extends by 2 episodes

### Video Script Generation
- For video platforms (TikTok, Instagram Reels), `generate_video_script()` produces structured JSON:
  - `voiceover_text`, `shot_descriptions[]`, `on_screen_text[]`, `music_mood`, `duration_estimate_seconds`, `hashtags[]`
- Scripts are stored in the `video_script` JSONB column on `skyeye_content_queue`

### Me-2-Me Integration
- `LegacyVaultMe2Me.extract_thematic_content()` provides anonymized emotional themes from:
  - Imprint entries (emotion distributions)
  - Identity crystals (relationship patterns, life themes)
  - Family fabrics (intergenerational dynamics)
- NO PII, NO user-identifiable data is ever exposed to marketing content
- Themes enrich campaign storytelling with authentic emotional resonance

### Cross-Platform Story Threading
- When an episode posts across multiple platforms, each post stores `cross_thread_refs` (JSONB) mapping other platforms to their post IDs
- This enables "continued on TikTok" / "discussion on Reddit" cross-references

### Email/SMS Drip Integration
- Campaign `drip_touchpoints` (JSONB) can specify which episodes trigger outbound email/SMS
- Uses the existing `DripScheduler.send_campaign_touchpoint()` to reach subscribers
- Example: Episode 3 of a romance_arc triggers an email to all subscribers

### Execution Bridge
- `MarketingBrain.execute_approved_action()` routes actions by type:
  - `launch_campaign` → calls `design_campaign()` (full multi-episode generation)
  - `shift_content_mix` / `adjust_schedule` → updates playbook
  - Other → generates and queues a single strategic post
- `approve_action()` now automatically triggers execution (no separate manual step)

### Autonomous Operation
- Little Nate operates with full autonomy by default
- Approval is only required when Big Nate explicitly requests it
- Direct post commands ("post this to LinkedIn") are detected and queued immediately

### SkyEye Dashboard — Campaigns Tab
- Campaign list with status badges and progress bars
- Click into any campaign for detailed view:
  - Episode timeline with post status per platform
  - Audience feedback history
  - A/B test results
  - Pause / Resume / Extend controls

### Defense Posture Reporting
Little Nate reports defense status using the GREEN/AMBER/RED format:
- 🟢 GREEN — All systems healthy, no incidents
- 🟡 AMBER — Degraded service or warning-level alert
- 🔴 RED — Active threat or critical incident
Structured context blocks (hive_defense.services, active_threats, transit_guardian, webhook_fortress) are parsed and presented in this format.

### Admin Executive Summaries
Admin mode presents data in executive summary format:
- 📊 USERS: total, active, by-tier breakdown
- 💰 REVENUE: MRR, churn rate, failed payments
- 📝 AUDIT: recent event count and top types
- 🖥️ SYSTEM: container health, API uptime, database status

### Database Tables
| Table | Purpose |
|-------|---------|
| `campaign_templates` | Pre-built narrative structures (seeded) |
| `storytelling_campaigns` | Campaign instances with metadata, thresholds, feedback |
| `skyeye_content_queue` (extended) | +campaign_id, episode_number, sequence_order, depends_on_post_id, cross_thread_refs, ab_variant, video_script |

### API Endpoints (under `/api/skyeye/`)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/campaigns` | List campaigns (optional `?status=` filter) |
| GET | `/campaigns/{id}` | Campaign detail with posts and feedback |
| POST | `/campaigns/{id}/pause` | Pause an active campaign |
| POST | `/campaigns/{id}/resume` | Resume a paused campaign |
| POST | `/campaigns/{id}/extend` | Add 2 episodes to a campaign |

---

*Document updated February 15, 2026*
*Little Nate Project — Sovereign Command Admin Console v3.0 + Campaign Execution System*
