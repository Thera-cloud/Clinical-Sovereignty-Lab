# DATA SOURCE MAPPING & MIGRATION FLOWS
## Complete System Data Architecture - v2.0

**Last Updated:** January 26, 2026 3:20 AM  
**Status:** ✅ COMPLETE ANALYSIS  
**Scope:** All dashboards, mobile app, Azure integration, billing

---

## 📊 TABLE OF CONTENTS

1. [System Overview](#system-overview)
2. [Data Flow Trees](#data-flow-trees)
3. [Storage Architecture](#storage-architecture)
4. [Dashboard Data Sources](#dashboard-data-sources)
5. [Mobile Data Integration](#mobile-data-integration)
6. [Azure Integration](#azure-integration)
7. [Billing Data Flow](#billing-data-flow)
8. [Migration Paths](#migration-paths)

---

## 🎯 SYSTEM OVERVIEW

### Current Architecture: File-Based Storage

```
Clinical Sovereignty Lab Data Stack
├── User Data (user_registry.json)
├── Analytics (analytics.json)
├── Billing (stripe_billing.json)
├── Client Metrics (Vaults/Clients/{id}/metrics.json)
├── Coach Metrics (Vaults/Coaches/{id}/metrics.json)
├── Training Data (Vaults/Admin/wisdom_database.json)
└── Session Logs (sessions.json - planned)
```

### Target Architecture: Hybrid (File + PostgreSQL)

```
Production Data Stack
├── PostgreSQL Database (users, sessions, metrics)
├── Azure Blob Storage (training files, backups)
├── Redis Cache (real-time data, session state)
├── File System (temporary uploads, exports)
└── Azure OpenAI (conversation history)
```

---

## 🌳 DATA FLOW TREES

### Tree 1: Mobile → Backend → Storage → Dashboard

```
MOBILE APP (Flutter)
    │
    ├─ User Login
    │   ↓
    │   WebSocket (ws://server:8765)
    │   ↓
    │   login_request {username, password, hardware_id}
    │   ↓
    │   Bridge Server → user_registry.json
    │   ↓
    │   Validate PBKDF2 hash
    │   ↓
    │   login_success {token, profile}
    │   ↓
    │   Store in sessionStorage
    │
    ├─ Chat Message
    │   ↓
    │   send_message {user_message, session_id}
    │   ↓
    │   Bridge Server → Azure Cortex
    │   ↓
    │   Azure OpenAI GPT-4
    │   ↓
    │   AI Response (streaming)
    │   ↓
    │   Store message pair
    │   ↓
    │   AnalyticsEngine.record_event("message_sent")
    │   ↓
    │   analytics.json ← {total_messages++}
    │   ↓
    │   Dashboard: The Eye → admin_get_stats
    │
    └─ Biometric Data
        ↓
        Sensors: HRV, GSR, Voice, Breathing (1Hz)
        ↓
        Package: biometric_update {session_id, biometrics{}, timestamp}
        ↓
        WebSocket → Bridge Server
        ↓
        NevedalHandler.handle_biometric_update()
        ↓
        NevedalEngine.process_biometrics()
        ↓
        Calculate: C_emo = f(P_ent, T_tunnel, γ_env, E_g)
        ↓
        Store: Vaults/Clients/{id}/metrics.json
        {
            "nevedal_state": {
                "C_emo": 0.73,
                "P_ent": 0.81,
                "T_tunnel": 0.68,
                "gamma_env": 0.23,
                "E_g_joint": 0.54,
                "last_updated": "2026-01-26T02:30:45Z"
            }
        }
        ↓
        Broadcast: nevedal_update → WebSocket subscribers
        ↓
        Dashboard: Nevedal Lab Live → Real-time display
```

### Tree 2: Dashboard → Backend → Data Sources

```
DASHBOARD (Web Browser)
    │
    ├─ The Eye Overview (the_eye.html)
    │   ↓
    │   Page Load → Check sessionStorage
    │   ↓
    │   WebSocket connect ws://localhost:8765
    │   ↓
    │   Send: login_request
    │   ↓
    │   Receive: login_success
    │   ↓
    │   Send: admin_get_stats
    │   ↓
    │   Bridge Server → AnalyticsEngine.get_dashboard_stats()
    │   ↓
    │   Read: analytics.json
    │   {
    │       "platform_totals": {...},
    │       "revenue_metrics": {...},
    │       "session_analytics": {...}
    │   }
    │   ↓
    │   Return: dashboard_stats
    │   ↓
    │   Update UI: Cards, metrics, charts
    │
    ├─ The Eye Users (the_eye_users.html)
    │   ↓
    │   Send: admin_get_users
    │   ↓
    │   Bridge Server → load_registry()
    │   ↓
    │   Read: user_registry.json
    │   ↓
    │   Filter: role, status, search query
    │   ↓
    │   Return: user_list [{...}, {...}]
    │   ↓
    │   Display: User table with 156 users
    │
    ├─ Night School Coach Notes (night_school_coach_notes.html)
    │   ↓
    │   User uploads file: coaching_session_Jan25.txt
    │   ↓
    │   Read file as base64
    │   ↓
    │   Send: upload_coach_note {filename, content_base64, category}
    │   ↓
    │   Bridge Server → NightSchoolHandler
    │   ↓
    │   PII Detection (regex scan for SSN, phone, credit card)
    │   ↓
    │   Write: data/Vaults/Admin/COACH_NOTES_INBOX/coaching_session_Jan25.txt
    │   ↓
    │   Mark as: PENDING_REVIEW
    │   ↓
    │   Admin reviews → approve_coach_note
    │   ↓
    │   Move: INBOX → COACH_NOTES/
    │   ↓
    │   Extract wisdom → wisdom_database.json
    │   {
    │       "wisdom_items": [
    │           {
    │               "id": "wisdom_512",
    │               "source": "coach_notes",
    │               "content": "When client shows anxiety...",
    │               "category": "anxiety_techniques"
    │           }
    │       ]
    │   }
    │   ↓
    │   Next Night School training run includes new wisdom
    │
    └─ Nevedal Lab Cohort (nevedal_lab_cohort.html)
        ↓
        Send: admin_get_cohort_stats {filters: {...}}
        ↓
        Bridge Server → Handler (EXISTS!)
        ↓
        Load: user_registry.json → Find all role=CLIENT
        ↓
        For each client:
            Load: Vaults/Clients/{id}/metrics.json
            Extract: nevedal_state.C_emo
            Group by: age, diagnosis, treatment_type
        ↓
        Calculate:
            platform_avg = sum(all_c_emo) / count
            by_age_group = {...}
            by_diagnosis = {...}
            by_treatment = {...}
        ↓
        Return: cohort_stats
        ↓
        Display: Platform avg 0.64, 156 participants, breakdowns
```

### Tree 3: Azure Integration Flow

```
AZURE SERVICES
    │
    ├─ Azure OpenAI (GPT-4)
    │   ↑
    │   WebSocket: wss://nathanlhr-0393-resource.cognitiveservices.azure.com
    │   ↑
    │   Bridge Server: AzureCortex class
    │   ↑
    │   Request: {
    │       "model": "gpt-4-turbo",
    │       "messages": [
    │           {"role": "system", "content": "You are Little Nate..."},
    │           {"role": "user", "content": "I'm feeling anxious"}
    │       ],
    │       "context": wisdom_database (RAG)
    │   }
    │   ↓
    │   Response: Streaming tokens
    │   ↓
    │   Token Usage: {prompt_tokens: 1200, completion_tokens: 340}
    │   ↓
    │   Cost Calculation: $0.03/1K prompt + $0.06/1K completion
    │   ↓
    │   Update: Vaults/Clients/{id}/metrics.json
    │   {
    │       "token_usage_today": 1540,
    │       "token_usage_month": 45230
    │   }
    │   ↓
    │   Deduct from token_balance
    │   ↓
    │   Dashboard: The Eye Revenue → Token usage display
    │
    ├─ Azure Blob Storage (Planned)
    │   ↑
    │   Training Files Upload
    │   ├─ Coach notes (approved)
    │   ├─ Curriculum PDFs
    │   ├─ Session recordings (encrypted)
    │   └─ Analytics exports
    │   ↓
    │   Backup Schedule: Daily at 2 AM
    │   ↓
    │   Retention: 90 days
    │
    └─ Azure PostgreSQL (Planned)
        ↑
        Migration from JSON files
        ↑
        Tables:
        ├─ users (from user_registry.json)
        ├─ sessions (from session logs)
        ├─ nevedal_metrics (from metrics.json files)
        ├─ messages (from Azure OpenAI history)
        └─ billing (from stripe_billing.json)
        ↓
        Queries: Indexed, optimized for dashboards
        ↓
        Backup: Point-in-time recovery (7 days)
```

### Tree 4: Billing Flow

```
STRIPE INTEGRATION
    │
    ├─ User Subscribes
    │   ↓
    │   Stripe Checkout (hosted page)
    │   ↓
    │   User enters payment info
    │   ↓
    │   Stripe charges card
    │   ↓
    │   Webhook: checkout.session.completed
    │   ↓
    │   POST https://server.com:8766/webhook/stripe
    │   ↓
    │   Webhook Server (stripe_webhook_server.py)
    │   ↓
    │   Verify signature with STRIPE_WEBHOOK_SECRET
    │   ↓
    │   StripeBillingSystem.handle_webhook()
    │   ↓
    │   Update: stripe_billing.json
    │   {
    │       "subscriptions": {
    │           "user_id": {
    │               "stripe_subscription_id": "sub_1234",
    │               "plan": "TOP_TIER",
    │               "status": "active",
    │               "current_period_end": "2026-02-26"
    │           }
    │       }
    │   }
    │   ↓
    │   Update: user_registry.json
    │   {
    │       "subscription_status": "ACTIVE",
    │       "subscription_plan": "TOP_TIER",
    │       "token_balance": 10000
    │   }
    │   ↓
    │   Send: subscription_updated message to user's WebSocket
    │   ↓
    │   Dashboard: The Eye Revenue → Update subscription card
    │
    ├─ Payment Fails
    │   ↓
    │   Webhook: invoice.payment_failed
    │   ↓
    │   Update: subscription_status = "SUSPENDED"
    │   ↓
    │   Send: Email notification (SendGrid)
    │   ↓
    │   User login → Error: "SUBSCRIPTION_INACTIVE"
    │   ↓
    │   Show: "Please update payment method"
    │
    └─ Token Usage
        ↓
        Azure OpenAI call consumes tokens
        ↓
        Deduct from: token_balance in user_registry.json
        ↓
        If token_balance < 100:
            Alert: "Low token balance"
            Suggest: Upgrade plan or purchase tokens
        ↓
        Dashboard: The Eye Revenue → Token usage chart
```

---

## 💾 STORAGE ARCHITECTURE

### File Structure (Current)

```
backend/app/websocket/
├── data/
│   ├── user_registry.json (50KB, ~156 users)
│   ├── analytics.json (10KB, platform stats)
│   ├── stripe_billing.json (15KB, subscriptions)
│   │
│   ├── Vaults/
│   │   ├── Clients/
│   │   │   ├── CLIENT_EMMA_ID/
│   │   │   │   └── metrics.json (5KB per client)
│   │   │   ├── CLIENT_JOHN_ID/
│   │   │   │   └── metrics.json
│   │   │   └── ... (156 clients total)
│   │   │
│   │   ├── Coaches/
│   │   │   ├── COACH_HOPE_ID/
│   │   │   │   └── metrics.json (3KB per coach)
│   │   │   └── ... (42 coaches total)
│   │   │
│   │   └── Admin/
│   │       ├── ADMIN_ADMIN1_ID/
│   │       │   └── metrics.json
│   │       │
│   │       └── admin_LN_training_folder/
│   │           ├── COACH_NOTES_INBOX/ (pending review)
│   │           ├── COACH_NOTES/ (approved, 200+ files)
│   │           ├── ADMIN_CURRICULUM/ (approved, 50+ files)
│   │           └── wisdom_database.json (500KB-2MB)
│   │
│   └── legal/
│       └── consent_v12.6_2026_FINAL.txt
│
├── bridge_server.py (2,272 lines)
├── nevedal_handlers.py (300 lines)
├── night_school_handlers.py (400 lines)
├── stripe_billing.py (350 lines)
└── nevedal_engine.py (600 lines)
```

**Total Storage:** ~15MB (156 clients + 42 coaches)  
**Growth Rate:** ~50MB/month (with session recordings)

### PostgreSQL Schema (Target)

```sql
-- ==========================================
-- USERS & AUTHENTICATION
-- ==========================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('CLIENT', 'COACH', 'ADMIN')),
    email VARCHAR(255) UNIQUE NOT NULL,
    hardware_id VARCHAR(100) UNIQUE NOT NULL,
    family_id VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP,
    login_count INTEGER DEFAULT 0,
    INDEX idx_users_role (role),
    INDEX idx_users_hardware_id (hardware_id),
    INDEX idx_users_family_id (family_id)
);

CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(20),
    dob DATE,
    timezone VARCHAR(50) DEFAULT 'America/New_York',
    profile_photo_url TEXT,
    emergency_contact TEXT,
    consent_version VARCHAR(50) NOT NULL,
    assigned_coach_id UUID REFERENCES users(id),
    tier VARCHAR(20) DEFAULT 'STANDARD',
    joined_date DATE DEFAULT CURRENT_DATE
);

-- ==========================================
-- SESSIONS
-- ==========================================

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    coach_id UUID REFERENCES users(id),
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,
    duration_minutes INTEGER,
    message_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    c_emo_avg DECIMAL(4,2),
    c_emo_peak DECIMAL(4,2),
    cee_count INTEGER DEFAULT 0,
    risk_level VARCHAR(20),
    crisis_flag BOOLEAN DEFAULT FALSE,
    notes TEXT,
    INDEX idx_sessions_user_id (user_id),
    INDEX idx_sessions_coach_id (coach_id),
    INDEX idx_sessions_started_at (started_at),
    INDEX idx_sessions_crisis_flag (crisis_flag)
);

CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id),
    user_id UUID NOT NULL REFERENCES users(id),
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    token_count INTEGER,
    INDEX idx_messages_session_id (session_id),
    INDEX idx_messages_user_id (user_id),
    INDEX idx_messages_timestamp (timestamp)
);

-- ==========================================
-- NEVEDAL METRICS
-- ==========================================

CREATE TABLE nevedal_metrics (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    user_id UUID NOT NULL REFERENCES users(id),
    dyad_partner_id UUID REFERENCES users(id),
    recorded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Core Nevedal values
    c_emo DECIMAL(4,2) NOT NULL CHECK (c_emo >= 0 AND c_emo <= 1),
    p_ent DECIMAL(4,2) CHECK (p_ent >= 0 AND p_ent <= 1),
    t_tunnel DECIMAL(4,2) CHECK (t_tunnel >= -1 AND t_tunnel <= 1),
    gamma_env DECIMAL(4,2) CHECK (gamma_env >= 0 AND gamma_env <= 1),
    e_g_joint DECIMAL(4,2) CHECK (e_g_joint >= 0 AND e_g_joint <= 1),
    
    -- CEE detection
    cee_window BOOLEAN DEFAULT FALSE,
    cee_duration_seconds INTEGER DEFAULT 0,
    
    -- Biometric data (JSONB for flexibility)
    biometrics JSONB,
    
    INDEX idx_nevedal_user_id (user_id),
    INDEX idx_nevedal_session_id (session_id),
    INDEX idx_nevedal_recorded_at (recorded_at),
    INDEX idx_nevedal_cee_window (cee_window),
    INDEX idx_nevedal_c_emo (c_emo)
);

CREATE TABLE cee_events (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES sessions(id),
    user_id UUID NOT NULL REFERENCES users(id),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    duration_seconds INTEGER NOT NULL,
    peak_c_emo DECIMAL(4,2) NOT NULL,
    context TEXT,
    INDEX idx_cee_user_id (user_id),
    INDEX idx_cee_session_id (session_id),
    INDEX idx_cee_start_time (start_time)
);

-- ==========================================
-- TRAINING & WISDOM
-- ==========================================

CREATE TABLE training_wisdom (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL CHECK (source IN ('coach_notes', 'curriculum', 'manual')),
    category VARCHAR(100),
    content TEXT NOT NULL,
    effectiveness_rating DECIMAL(3,2),
    usage_count INTEGER DEFAULT 0,
    last_used TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('pending', 'approved', 'active', 'archived')),
    INDEX idx_wisdom_source (source),
    INDEX idx_wisdom_category (category),
    INDEX idx_wisdom_status (status)
);

CREATE TABLE training_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    source VARCHAR(50) NOT NULL,
    category VARCHAR(100),
    uploaded_by UUID REFERENCES users(id),
    uploaded_at TIMESTAMP DEFAULT NOW(),
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',
    pii_detected BOOLEAN DEFAULT FALSE,
    content_hash VARCHAR(64),
    file_size INTEGER,
    blob_url TEXT
);

-- ==========================================
-- BILLING
-- ==========================================

CREATE TABLE billing_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    stripe_subscription_id VARCHAR(100) UNIQUE,
    stripe_customer_id VARCHAR(100),
    plan VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    current_period_start TIMESTAMP,
    current_period_end TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    cancelled_at TIMESTAMP,
    INDEX idx_billing_user_id (user_id),
    INDEX idx_billing_stripe_subscription_id (stripe_subscription_id),
    INDEX idx_billing_status (status)
);

CREATE TABLE billing_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    subscription_id UUID REFERENCES billing_subscriptions(id),
    stripe_payment_intent_id VARCHAR(100),
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP,
    INDEX idx_transactions_user_id (user_id),
    INDEX idx_transactions_created_at (created_at)
);

CREATE TABLE token_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id),
    session_id UUID REFERENCES sessions(id),
    timestamp TIMESTAMP DEFAULT NOW(),
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    cost_usd DECIMAL(10,4),
    model VARCHAR(50),
    INDEX idx_token_user_id (user_id),
    INDEX idx_token_session_id (session_id),
    INDEX idx_token_timestamp (timestamp)
);

-- ==========================================
-- ANALYTICS
-- ==========================================

CREATE TABLE platform_analytics (
    id BIGSERIAL PRIMARY KEY,
    recorded_at TIMESTAMP DEFAULT NOW(),
    total_users INTEGER NOT NULL,
    active_users_today INTEGER,
    active_users_month INTEGER,
    total_sessions INTEGER NOT NULL,
    total_messages INTEGER NOT NULL,
    total_revenue_cents INTEGER NOT NULL,
    avg_session_duration_minutes DECIMAL(6,2),
    avg_c_emo DECIMAL(4,2),
    crisis_count_today INTEGER DEFAULT 0,
    INDEX idx_analytics_recorded_at (recorded_at)
);

CREATE TABLE crisis_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    session_id UUID REFERENCES sessions(id),
    detected_at TIMESTAMP DEFAULT NOW(),
    risk_level VARCHAR(20) NOT NULL,
    indicators JSONB,
    coach_notified BOOLEAN DEFAULT FALSE,
    coach_id UUID REFERENCES users(id),
    resolved_at TIMESTAMP,
    notes TEXT,
    INDEX idx_crisis_user_id (user_id),
    INDEX idx_crisis_detected_at (detected_at),
    INDEX idx_crisis_risk_level (risk_level),
    INDEX idx_crisis_coach_notified (coach_notified)
);

-- ==========================================
-- INDEXES FOR PERFORMANCE
-- ==========================================

-- Composite indexes for common queries
CREATE INDEX idx_sessions_user_started ON sessions(user_id, started_at DESC);
CREATE INDEX idx_nevedal_user_recorded ON nevedal_metrics(user_id, recorded_at DESC);
CREATE INDEX idx_messages_session_timestamp ON messages(session_id, timestamp);
CREATE INDEX idx_token_user_timestamp ON token_usage(user_id, timestamp DESC);

-- Partial indexes for active/crisis data
CREATE INDEX idx_sessions_active ON sessions(user_id) WHERE ended_at IS NULL;
CREATE INDEX idx_crisis_active ON crisis_alerts(user_id) WHERE resolved_at IS NULL;
```

---

## 📊 DASHBOARD DATA SOURCES

### The Eye Dashboard (6 pages)

**1. Overview (the_eye.html)**

| Metric | Data Source | Update Frequency | Handler |
|--------|-------------|------------------|---------|
| Total Users | `analytics.json → platform_totals.total_users` | Real-time | admin_get_stats |
| Total Sessions | `analytics.json → platform_totals.total_sessions` | Real-time | admin_get_stats |
| Revenue | `analytics.json → revenue_metrics.total_revenue` | Daily | admin_get_stats |
| Active Now | `connected_sessions.size()` (in-memory) | Real-time | admin_get_stats |
| Crisis Watchlist | `Vaults/Clients/*/metrics.json → risk_level=HIGH` | Real-time | admin_get_crisis_watchlist |

**Data Flow:**
```
Page Load
  ↓
admin_get_stats request
  ↓
AnalyticsEngine.get_dashboard_stats()
  ↓
Read analytics.json
  ↓
Return dashboard_stats
  ↓
Update UI cards (156 users, 847 sessions, $45,230 revenue)
```

**2. Users (the_eye_users.html)**

| Data | Source | Query |
|------|--------|-------|
| User List | `user_registry.json` | All entries |
| Search Filter | In-memory JS | regex match on name/email |
| Role Badge | `profile.role` | CLIENT/COACH/ADMIN |
| Status | `profile.subscription_status` | ACTIVE/TRIAL/SUSPENDED |

**Data Flow:**
```
admin_get_users request
  ↓
load_registry()
  ↓
Read user_registry.json
  ↓
Return all users (156 entries)
  ↓
Frontend filters/searches in browser
```

**3. Sessions (the_eye_sessions.html)**

| Data | Source | Status |
|------|--------|--------|
| Active Sessions | `connected_sessions` (in-memory) | ✅ Live |
| Session History | `sessions.json` (planned) | ⚠️ Not implemented |
| Duration | Calculated from start_time | ✅ Live |

**4. Revenue (the_eye_revenue.html)**

| Data | Source | Integration |
|------|--------|-------------|
| Subscriptions | `stripe_billing.json → subscriptions` | ✅ Stripe webhooks |
| Payment Methods | `stripe_billing.json → payment_methods` | ✅ Stripe API |
| Token Usage | `user_registry.json → token_usage_month` | ✅ Calculated locally |

**5. Crisis Watch (the_eye_crisis.html)**

| Data | Source | Trigger |
|------|--------|---------|
| High Risk Users | `Vaults/Clients/*/metrics.json → risk_level=HIGH` | ✅ Real-time |
| Crisis Count | `metrics.json → crisis_count` | ✅ Incremented on detection |
| Last Assessment | `metrics.json → last_risk_assessment` | ✅ Timestamp |

**6. Coaches (the_eye_coaches.html)**

| Data | Source | Calculation |
|------|--------|-------------|
| Coach List | `user_registry.json (role=COACH)` | ✅ Filter |
| Performance | `Vaults/Coaches/{id}/metrics.json` | ✅ Per coach |
| Client Count | Count of `assigned_coach_id` matches | ✅ Aggregation |

---

### Night School (6 pages)

**1. Coach Notes (night_school_coach_notes.html)**

| Data | Source | Flow |
|------|--------|------|
| Pending Notes | `Vaults/Admin/COACH_NOTES_INBOX/` | File list |
| Approved Notes | `Vaults/Admin/COACH_NOTES/` | File list |
| PII Detected | Regex scan on upload | Red flag UI |

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
  ↓
Admin clicks "Approve"
  ↓
approve_coach_note {filename}
  ↓
Move to COACH_NOTES/
  ↓
Extract wisdom → wisdom_database.json
```

**2. Curriculum (night_school_curriculum.html)**

| Data | Source | Supported Formats |
|------|--------|-------------------|
| Uploaded Files | `Vaults/Admin/ADMIN_CURRICULUM/` | TXT, MD, PDF, DOCX, PPTX |
| File Count | Directory listing | 50+ files |
| Categories | Metadata in filename | anxiety, depression, cbt, etc. |

**3. Wisdom Editor (night_school_wisdom.html)**

| Data | Source | Structure |
|------|--------|-----------|
| All Wisdom | `wisdom_database.json → wisdom_items[]` | Array of 1247 items |
| Categories | `wisdom_item.category` | 15 categories |
| Usage Count | `wisdom_item.usage_count` | Tracked in Little Nate |

**Edit Flow:**
```
get_night_school_wisdom request
  ↓
NightSchoolHandler.get_wisdom_structured()
  ↓
Read wisdom_database.json
  ↓
Return {wisdom_items: [...], metadata: {...}}
  ↓
Display in editor (1247 items)
  ↓
User edits item #512
  ↓
update_night_school_wisdom {id: "wisdom_512", content: "new text"}
  ↓
Update wisdom_database.json
  ↓
Next training run includes updated wisdom
```

---

### Nevedal Lab (6 pages)

**1. Landing Page (nevedal_lab_old.html)**

| Metric | Data Source | Update Frequency |
|--------|-------------|------------------|
| C_emo Gauge | `Vaults/Clients/{id}/metrics.json → C_emo` | 1Hz (live) |
| P_ent | `metrics.json → P_ent` | 1Hz |
| T_tunnel | `metrics.json → T_tunnel` | 1Hz |
| γ_env | `metrics.json → gamma_env` | 1Hz |
| E_g^(joint) | `metrics.json → E_g_joint` | 1Hz |
| CEE Detected | `metrics.json → cee_window=true` | Real-time |

**Data Flow:**
```
nevedal_subscribe {user_id: "CLIENT_EMMA_ID"}
  ↓
NevedalHandler.handle_subscribe(websocket, user_id)
  ↓
Subscribe websocket to user's updates
  ↓
Mobile app sends biometric_update (1Hz)
  ↓
NevedalEngine.process_biometrics()
  ↓
Calculate C_emo = f(HRV, GSR, voice, breathing)
  ↓
Update metrics.json
  ↓
Broadcast nevedal_update to all subscribers
  ↓
Dashboard receives update
  ↓
updateLiveData() → Animate gauge to 0.73
```

**2. Live Analysis (nevedal_lab_live.html)**

Same as landing page + biometric mapping display

**3. Longitudinal Study (nevedal_lab_longitudinal.html)**

| Data | Source | Time Range |
|------|--------|------------|
| Historical C_emo | `metrics.json → history[]` | 7d/30d/90d/all |
| CEE Events | `metrics.json → history[] where cee_window=true` | Filtered |
| Statistics | Calculated from history | Avg, peak, low |

**4. Dyad Comparisons (nevedal_lab_dyad.html)**

| Data | Source | Handler Status |
|------|--------|----------------|
| Client C_emo | `Vaults/Clients/{id}/metrics.json` | ✅ |
| Coach C_emo | `Vaults/Coaches/{id}/metrics.json` | ✅ |
| Synchrony Score | Calculated: 1.0 - abs(diff) | ⚠️ Handler pending |

**Expected Handler:**
```python
async def admin_get_dyad_sync(websocket, data):
    client_id = data['client_id']
    coach_id = data['coach_id']
    
    client_metrics = load_metrics(client_id)
    coach_metrics = load_metrics(coach_id)
    
    synchrony = 1.0 - abs(
        client_metrics['C_emo'] - coach_metrics['C_emo']
    )
    
    return {
        'synchrony_score': synchrony,
        'client_c_emo': client_metrics['C_emo'],
        'coach_c_emo': coach_metrics['C_emo'],
        'grade': get_grade(synchrony)
    }
```

**5. Family Dynamics (nevedal_lab_family.html)**

| Data | Source | Handler Status |
|------|--------|----------------|
| Family Members | `user_registry.json where family_id=X` | ✅ |
| Member C_emo | `Vaults/Clients/{each}/metrics.json` | ✅ |
| Coherence Matrix | Pairwise calculations | ⚠️ Handler pending |

**6. Cohort Analysis (nevedal_lab_cohort.html)**

| Data | Source | Handler Status |
|------|--------|----------------|
| All Clients | `user_registry.json (role=CLIENT)` | ✅ |
| Platform Avg | Calculated from all metrics | ✅ WORKING! |
| Age Groups | Grouped by birthdate (planned) | ⚠️ Placeholder data |
| Diagnosis | Grouped by diagnosis field (planned) | ⚠️ Placeholder data |
| Treatment | Grouped by assigned_coach_id | ✅ |

**Current Implementation:**
```python
async def admin_get_cohort_stats(websocket, data, current_profile):
    if current_profile.get('role') != 'ADMIN':
        return
    
    registry = load_registry()
    clients = [u for u in registry.values() if u['profile']['role'] == 'CLIENT']
    
    total_c_emo = 0
    count = 0
    
    for client in clients:
        metrics = load_metrics(client['profile'])
        c_emo = metrics['nevedal_state']['C_emo']
        total_c_emo += c_emo
        count += 1
    
    platform_avg = total_c_emo / count if count > 0 else 0
    
    return {
        'platform_avg_c_emo': platform_avg,
        'sample_size': count,
        'total_sessions': 847,  # from analytics
        ...
    }
```

---

## 📱 MOBILE DATA INTEGRATION

### Flutter App → Bridge Server

**Connection Flow:**
```dart
// 1. App startup
SharedPreferences prefs = await SharedPreferences.getInstance();

// 2. Establish WebSocket
final channel = WebSocketChannel.connect(
    Uri.parse('ws://production-server.com:8765')
);

// 3. Authenticate
channel.sink.add(jsonEncode({
    'type': 'login_request',
    'username': prefs.getString('username'),
    'password': prefs.getString('password'),
    'hardware_id': await getDeviceId(),
    'expected_role': 'CLIENT'
}));

// 4. Wait for login_success
channel.stream.listen((message) {
    final data = jsonDecode(message);
    if (data['type'] == 'login_success') {
        startSession(data['profile']);
    }
});
```

**Biometric Collection:**
```dart
// Import sensor packages
import 'package:health/health.dart';  // Apple Health / Google Fit
import 'package:heart_rate_monitor/heart_rate_monitor.dart';

// Start session with biometrics
void startTherapySession() {
    sessionId = Uuid().v4();
    
    // Subscribe to sensors (1Hz updates)
    Timer.periodic(Duration(seconds: 1), (timer) async {
        final hrv = await HeartRateMonitor().getHRV();
        final gsr = await GSRSensor().getValue();
        final breathing = await BreathingSensor().getRate();
        
        // Package biometrics
        final biometricUpdate = {
            'type': 'biometric_update',
            'session_id': sessionId,
            'user_id': profile['hardware_id'],
            'timestamp': DateTime.now().toIso8601String(),
            'biometrics': {
                'hrv': hrv,
                'gsr': gsr,
                'breathing_rate': breathing
            }
        };
        
        // Send via WebSocket
        channel.sink.add(jsonEncode(biometricUpdate));
    });
}
```

**Backend Processing:**
```python
# bridge_server.py - Line 1938
elif msg_type == "biometric_update":
    await nevedal_handler.handle_biometric_update(
        websocket, data, current_profile
    )
```

```python
# nevedal_handlers.py
async def handle_biometric_update(self, websocket, data, profile):
    biometrics = data['biometrics']
    
    # Process through Nevedal Engine
    state = self.engine.process_biometrics(
        session_id=data['session_id'],
        user_id=data['user_id'],
        biometrics=biometrics
    )
    
    # Calculate C_emo
    state.c_emo = self.engine.calculate_c_emo(
        hrv=biometrics['hrv'],
        gsr=biometrics['gsr'],
        breathing=biometrics['breathing_rate']
    )
    
    # Store in metrics.json
    await self._store_state(state)
    
    # Broadcast to dashboard subscribers
    await self._broadcast_state(data['session_id'], state)
```

**Dashboard Display:**
```javascript
// nevedal_lab_live.html - Real-time updates
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'nevedal_update') {
        // Animate gauge
        animateGauge(data.c_emo);
        
        // Update component variables
        document.getElementById('p_ent').textContent = data.p_ent.toFixed(2);
        document.getElementById('t_tunnel').textContent = data.t_tunnel.toFixed(2);
        
        // Update biometrics
        document.getElementById('hrv_value').textContent = data.biometrics.hrv;
        document.getElementById('gsr_value').textContent = data.biometrics.gsr;
        
        // Check for CEE
        if (data.cee_window) {
            showCEEAlert();
        }
    }
};
```

---

## ☁️ AZURE INTEGRATION

### Azure OpenAI Data Flow

**Request Path:**
```
Mobile/Web Client
  ↓
"I'm feeling anxious today"
  ↓
WebSocket → Bridge Server
  ↓
send_message {user_message, session_id}
  ↓
AzureCortex.send_message()
  ↓
Load context:
  • User history (last 10 messages)
  • Night School wisdom (RAG)
  • User profile (name, preferences)
  ↓
Build Azure OpenAI request:
{
    "model": "gpt-4-turbo",
    "messages": [
        {"role": "system", "content": "You are Little Nate..."},
        {"role": "assistant", "content": "Previous context..."},
        {"role": "user", "content": "I'm feeling anxious today"}
    ],
    "max_tokens": 2000,
    "temperature": 0.7,
    "stream": true
}
  ↓
POST wss://nathanlhr-0393-resource.cognitiveservices.azure.com/openai/deployments/gpt-4/chat/completions
  ↓
Azure OpenAI GPT-4 generates response (streaming)
  ↓
Tokens: {prompt_tokens: 1200, completion_tokens: 340, total: 1540}
  ↓
Cost: ($0.03/1K * 1.2) + ($0.06/1K * 0.34) = $0.056
  ↓
Stream response to client (word by word)
  ↓
Log message pair:
  • Save user message
  • Save AI response
  ↓
Update analytics:
  • analytics.json → total_messages += 2
  • user_registry.json → token_usage_today += 1540
  • user_registry.json → token_balance -= 1540
  ↓
Dashboard updates:
  • The Eye Revenue → Token usage chart
  • Analytics → Message count
```

**Cost Tracking:**
```python
# After Azure OpenAI response
usage = response['usage']
prompt_tokens = usage['prompt_tokens']
completion_tokens = usage['completion_tokens']

# GPT-4 Turbo pricing (as of Jan 2026)
PROMPT_COST = 0.03  # per 1K tokens
COMPLETION_COST = 0.06  # per 1K tokens

cost_usd = (
    (prompt_tokens / 1000) * PROMPT_COST +
    (completion_tokens / 1000) * COMPLETION_COST
)

# Update user token balance
user_profile['token_usage_today'] += usage['total_tokens']
user_profile['token_usage_month'] += usage['total_tokens']
user_profile['token_balance'] -= usage['total_tokens']

# Store in analytics
analytics['azure_costs_today'] += cost_usd
analytics['azure_costs_month'] += cost_usd

save_registry(registry)
save_analytics(analytics)
```

### Azure Blob Storage (Planned)

**Upload Flow:**
```python
from azure.storage.blob import BlobServiceClient

# Initialize client
blob_service = BlobServiceClient.from_connection_string(
    os.getenv('AZURE_STORAGE_CONNECTION_STRING')
)

# Upload training file
async def upload_to_blob(filename, content):
    container = blob_service.get_container_client('training-files')
    
    blob_name = f"{datetime.now().strftime('%Y%m%d')}_{filename}"
    blob_client = container.get_blob_client(blob_name)
    
    await blob_client.upload_blob(content, overwrite=True)
    
    return blob_client.url

# Usage in Night School
uploaded_url = await upload_to_blob('coaching_notes.txt', file_content)
```

**Backup Schedule:**
```python
# Daily backup job (runs at 2 AM)
async def backup_to_azure():
    # Backup user registry
    await upload_to_blob('backups/user_registry.json', 
                         open('data/user_registry.json').read())
    
    # Backup analytics
    await upload_to_blob('backups/analytics.json',
                         open('data/analytics.json').read())
    
    # Backup all client metrics
    for client_dir in Path('data/Vaults/Clients').iterdir():
        metrics_file = client_dir / 'metrics.json'
        if metrics_file.exists():
            await upload_to_blob(
                f'backups/clients/{client_dir.name}/metrics.json',
                metrics_file.read_text()
            )
```

---

## 💳 BILLING DATA FLOW

### Stripe Integration

**Subscription Creation:**
```
User clicks "Upgrade to Premium"
  ↓
Frontend: window.location.href = stripe_checkout_url
  ↓
Stripe Checkout (hosted by Stripe)
  ↓
User enters payment info
  ↓
Stripe processes payment
  ↓
Webhook: checkout.session.completed
  ↓
POST https://your-server.com:8766/webhook/stripe
  Headers: Stripe-Signature: t=timestamp,v1=signature
  ↓
Webhook Server (stripe_webhook_server.py)
  ↓
Verify signature:
  expected_sig = hmac.new(
      WEBHOOK_SECRET.encode(),
      f"{timestamp}.{payload}".encode(),
      hashlib.sha256
  ).hexdigest()
  ↓
StripeBillingSystem.handle_webhook(event)
  ↓
event.type == 'checkout.session.completed'
  ↓
Extract:
  • customer_id
  • subscription_id
  • user_email
  ↓
Update stripe_billing.json:
{
    "subscriptions": {
        "user_id": {
            "stripe_subscription_id": "sub_1234",
            "stripe_customer_id": "cus_5678",
            "plan": "PREMIUM",
            "status": "active",
            "created_at": "2026-01-26T03:00:00Z",
            "current_period_start": "2026-01-26",
            "current_period_end": "2026-02-26"
        }
    }
}
  ↓
Update user_registry.json:
{
    "subscription_status": "ACTIVE",
    "subscription_plan": "PREMIUM",
    "subscription_start_date": "2026-01-26",
    "token_balance": 5000  // PREMIUM plan tokens
}
  ↓
Send WebSocket message to user:
{
    "type": "subscription_updated",
    "plan": "PREMIUM",
    "token_balance": 5000
}
  ↓
Dashboard: The Eye Revenue → Update card
```

**Payment Failure:**
```
Stripe detects payment failure
  ↓
Webhook: invoice.payment_failed
  ↓
Webhook Server processes
  ↓
Update status: "SUSPENDED"
  ↓
Send email via SendGrid:
  To: user_email
  Subject: "Payment Failed - Update Required"
  Body: "Please update payment method at ..."
  ↓
Next login attempt:
  Check subscription_status
  ↓
  if status == "SUSPENDED":
      Show error: "SUBSCRIPTION_INACTIVE"
      Redirect to billing page
```

**Token Depletion:**
```
User sends message
  ↓
Azure OpenAI processes (1540 tokens)
  ↓
Deduct: token_balance -= 1540
  ↓
Check: if token_balance < 100:
    Send alert: "low_token_balance"
    ↓
    Mobile app shows: "You have 85 tokens remaining"
    ↓
    Suggest: "Upgrade to PREMIUM for 5000 tokens/month"
```

---

## 🔄 MIGRATION PATHS

### Phase 1: JSON → PostgreSQL (User Data)

**Week 1: Schema Creation**
```sql
-- Run migration scripts
psql -U postgres -d clinical_lab -f create_tables.sql
```

**Week 2: Data Migration**
```python
import json
import asyncpg
from pathlib import Path

async def migrate_users():
    # Load JSON
    with open('data/user_registry.json') as f:
        registry = json.load(f)
    
    # Connect to PostgreSQL
    conn = await asyncpg.connect(
        host='localhost',
        database='clinical_lab',
        user='postgres',
        password=os.getenv('DB_PASSWORD')
    )
    
    # Migrate each user
    for key, user_data in registry.items():
        creds = user_data['credentials']
        profile = user_data['profile']
        
        # Insert into users table
        user_id = await conn.fetchval('''
            INSERT INTO users (
                username, password_hash, role, email, 
                hardware_id, family_id
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        ''', 
            creds['username'],
            creds['password'],
            profile['role'],
            profile['email'],
            profile['hardware_id'],
            profile.get('family_id')
        )
        
        # Insert into user_profiles table
        await conn.execute('''
            INSERT INTO user_profiles (
                user_id, name, phone, consent_version,
                assigned_coach_id, tier
            ) VALUES ($1, $2, $3, $4, $5, $6)
        ''',
            user_id,
            profile['name'],
            profile.get('phone'),
            profile['consent_version'],
            profile.get('assigned_coach_id'),
            profile.get('tier', 'STANDARD')
        )
    
    await conn.close()
    print(f"✅ Migrated {len(registry)} users")

# Run migration
asyncio.run(migrate_users())
```

**Week 3: Nevedal Metrics Migration**
```python
async def migrate_nevedal_metrics():
    conn = await asyncpg.connect(...)
    
    # Iterate through all client metrics
    for client_dir in Path('data/Vaults/Clients').iterdir():
        metrics_file = client_dir / 'metrics.json'
        if not metrics_file.exists():
            continue
        
        with open(metrics_file) as f:
            metrics = json.load(f)
        
        nevedal_state = metrics['nevedal_state']
        
        # Get user_id from hardware_id
        user_id = await conn.fetchval(
            'SELECT id FROM users WHERE hardware_id = $1',
            client_dir.name
        )
        
        # Insert current state
        await conn.execute('''
            INSERT INTO nevedal_metrics (
                user_id, c_emo, p_ent, t_tunnel,
                gamma_env, e_g_joint, recorded_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ''',
            user_id,
            nevedal_state['C_emo'],
            nevedal_state.get('P_ent'),
            nevedal_state.get('T_tunnel'),
            nevedal_state.get('gamma_env'),
            nevedal_state.get('E_g_joint')
        )
        
        # Insert historical data
        for hist_entry in metrics.get('history', []):
            await conn.execute('''
                INSERT INTO nevedal_metrics (
                    user_id, c_emo, recorded_at
                ) VALUES ($1, $2, $3)
            ''',
                user_id,
                hist_entry['c_emo'],
                hist_entry['timestamp']
            )
    
    await conn.close()
    print("✅ Migrated Nevedal metrics")

asyncio.run(migrate_nevedal_metrics())
```

**Week 4: Switch Over**
```python
# bridge_server.py - Add database config
DATABASE_ENABLED = os.getenv('USE_DATABASE', 'false').lower() == 'true'

if DATABASE_ENABLED:
    db_pool = await asyncpg.create_pool(
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        min_size=10,
        max_size=20
    )
else:
    db_pool = None

# Update authentication
async def handle_login_request(websocket, data):
    if DATABASE_ENABLED:
        # Query PostgreSQL
        async with db_pool.acquire() as conn:
            user = await conn.fetchrow('''
                SELECT u.*, up.* FROM users u
                JOIN user_profiles up ON u.id = up.user_id
                WHERE u.username = $1
            ''', data['username'])
    else:
        # Query JSON file (fallback)
        registry = load_registry()
        user = find_user_in_registry(registry, data['username'])
```

### Phase 2: Azure Blob Migration (Training Files)

**Upload Script:**
```python
async def migrate_training_files_to_azure():
    blob_service = BlobServiceClient.from_connection_string(
        os.getenv('AZURE_STORAGE_CONNECTION_STRING')
    )
    container = blob_service.get_container_client('training-files')
    
    # Migrate coach notes
    notes_dir = Path('data/Vaults/Admin/COACH_NOTES')
    for note_file in notes_dir.glob('*.txt'):
        blob_name = f"coach_notes/{note_file.name}"
        
        with open(note_file, 'rb') as f:
            await container.upload_blob(blob_name, f, overwrite=True)
        
        print(f"✅ Uploaded {note_file.name}")
    
    # Migrate curriculum
    curriculum_dir = Path('data/Vaults/Admin/ADMIN_CURRICULUM')
    for curr_file in curriculum_dir.glob('*'):
        blob_name = f"curriculum/{curr_file.name}"
        
        with open(curr_file, 'rb') as f:
            await container.upload_blob(blob_name, f, overwrite=True)
        
        print(f"✅ Uploaded {curr_file.name}")
```

### Phase 3: Real-time Caching (Redis)

**Add Redis for Hot Data:**
```python
import aioredis

redis = await aioredis.create_redis_pool('redis://localhost')

# Cache active sessions
await redis.setex(
    f"session:{session_id}",
    3600,  # 1 hour TTL
    json.dumps(session_data)
)

# Cache real-time Nevedal state
await redis.setex(
    f"nevedal:{user_id}",
    60,  # 60 second TTL
    json.dumps({
        'c_emo': 0.73,
        'last_updated': datetime.now().isoformat()
    })
)

# Retrieve from cache first
cached = await redis.get(f"nevedal:{user_id}")
if cached:
    return json.loads(cached)
else:
    # Query database
    ...
```

---

## 📈 PERFORMANCE METRICS

### Current System (File-Based)

| Operation | Time | Method |
|-----------|------|--------|
| User Login | 50ms | JSON file read + PBKDF2 |
| Load Dashboard | 200ms | Read analytics.json |
| Biometric Update | 100ms | Calculate C_emo + write JSON |
| Query All Users | 150ms | Load user_registry.json |

### Target System (PostgreSQL)

| Operation | Estimated Time | Improvement |
|-----------|----------------|-------------|
| User Login | 20ms | 60% faster |
| Load Dashboard | 50ms | 75% faster |
| Biometric Update | 30ms | 70% faster |
| Query All Users | 40ms | 73% faster |

---

## ✅ MIGRATION CHECKLIST

**Pre-Migration:**
- [ ] Backup all JSON files
- [ ] Test PostgreSQL connection
- [ ] Verify schema creation
- [ ] Run test migrations on sample data

**Migration:**
- [ ] Migrate users table (156 users)
- [ ] Migrate user_profiles table
- [ ] Migrate nevedal_metrics (current state)
- [ ] Migrate nevedal_metrics (historical data)
- [ ] Migrate training_wisdom
- [ ] Migrate billing_subscriptions

**Post-Migration:**
- [ ] Verify data integrity
- [ ] Update bridge_server.py to use database
- [ ] Test all dashboards with PostgreSQL
- [ ] Monitor performance
- [ ] Keep JSON files as backup (30 days)
- [ ] Switch DATABASE_ENABLED=true in production

---

**Document Version:** 2.0  
**Last Updated:** January 26, 2026 3:20 AM  
**Total Data Mapped:** 18 dashboards, mobile app, Azure, billing  
**Migration Status:** Planned (4-6 weeks)  
**Status:** ✅ COMPLETE ANALYSIS
