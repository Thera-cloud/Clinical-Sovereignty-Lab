# CLINICAL SOVEREIGNTY LAB - COMPLETE PROJECT TREE
## Version 2.0 | January 27, 2026

**Status:** ✅ PRODUCTION READY (Family Sanctuary in beta)  
**Architecture:** WebSocket-based real-time therapy platform  
**AI Integration:** Azure OpenAI GPT-4 Realtime + RAG (Night School)

---

## 📊 SYSTEM OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CLINICAL SOVEREIGNTY LAB                                  │
│                    "Little Nate" AI Therapy Platform                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐    WebSocket    ┌──────────────────────────────────────┐ │
│   │   FLUTTER    │◄──────────────►│        SOVEREIGN BRIDGE               │ │
│   │   MOBILE     │     :8765       │     (bridge_server.py)               │ │
│   │              │                 │                                      │ │
│   │ ├─ iOS       │                 │  ┌────────────┐  ┌────────────────┐  │ │
│   │ ├─ Android   │                 │  │ AZURE      │  │ NIGHT SCHOOL   │  │ │
│   │ └─ Web       │                 │  │ CORTEX     │  │ (RAG/Wisdom)   │  │ │
│   └──────────────┘                 │  │ (GPT-4)    │  │                │  │ │
│                                    │  └────────────┘  └────────────────┘  │ │
│   ┌──────────────┐                 │                                      │ │
│   │   WEB        │                 │  ┌────────────┐  ┌────────────────┐  │ │
│   │   DASHBOARDS │                 │  │ NEVEDAL    │  │ BILLING        │  │ │
│   │              │                 │  │ (C_emo)    │  │ (Stripe)       │  │ │
│   │ ├─ The Eye   │                 │  └────────────┘  └────────────────┘  │ │
│   │ ├─ Nevedal   │                 │                                      │ │
│   │ └─ Night Sch │                 │  ┌────────────────────────────────┐  │ │
│   └──────────────┘                 │  │ FAMILY SANCTUARY ENGINE        │  │ │
│                                    │  │ (Multi-member group therapy)   │  │ │
│                                    │  └────────────────────────────────┘  │ │
│                                    └──────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📁 COMPLETE FILE TREE

```
Clinical-Sovereignty-Lab-2/
│
├── 📁 backend/
│   └── 📁 app/
│       └── 📁 websocket/
│           │
│           ├── 🐍 bridge_server.py              # MAIN SERVER (3570 lines)
│           │   │
│           │   ├── [Part 1] Infrastructure
│           │   │   ├── HOST = "0.0.0.0", PORT = 8765
│           │   │   ├── Environment loading (.env)
│           │   │   ├── Azure OpenAI config
│           │   │   └── Stripe/SendGrid config
│           │   │
│           │   ├── [Part 2] Utility Functions
│           │   │   ├── hash_password() / verify_password()
│           │   │   ├── load_registry() / save_registry()
│           │   │   └── load_user_profile()
│           │   │
│           │   ├── [Part 3] Classes
│           │   │   ├── class Hippocampus          # Memory system
│           │   │   ├── class MetricsEngine        # Nevedal metrics I/O
│           │   │   ├── class AnalyticsEngine      # The Eye tracking
│           │   │   ├── class BillingSystem        # Token/billing
│           │   │   ├── class NightSchool          # Wisdom RAG
│           │   │   └── class AzureCortex          # GPT-4 integration
│           │   │       ├── process_interaction()
│           │   │       └── process_sanctuary_message()  # NEW
│           │   │
│           │   ├── [Part 4] System Initialization
│           │   │   ├── nevedal_handler init
│           │   │   ├── sanctuary_engine init
│           │   │   ├── billing init
│           │   │   └── analytics init
│           │   │
│           │   └── [Part 5] WebSocket Handler
│           │       └── async def handle_client(websocket)
│           │           ├── login_request
│           │           ├── get_metrics / update_metrics
│           │           ├── send_message (AI chat)
│           │           ├── ask_nate_coaching
│           │           ├── sanctuary_* handlers
│           │           └── admin_* / coach_* handlers
│           │
│           ├── 🐍 sanctuary_engine.py            # FAMILY SANCTUARY (1062 lines)
│           │   │
│           │   └── class FamilySanctuaryEngine
│           │       ├── __init__(data_dir, azure_cortex, nevedal_handler, billing, analytics)
│           │       ├── _websocket_registry: Dict[sanctuary_id, Dict[user_id, ws]]
│           │       │
│           │       ├── Sanctuary Lifecycle:
│           │       │   ├── create_sanctuary()
│           │       │   ├── add_or_reconnect_member()   # Handles duplicates
│           │       │   ├── get_or_create_sanctuary()
│           │       │   └── complete_sanctuary()
│           │       │
│           │       ├── Messaging:
│           │       │   ├── add_message()
│           │       │   ├── broadcast_to_sanctuary()
│           │       │   └── detect_escalation()          # Triggers Little Nate
│           │       │
│           │       └── Coaching (NEW v2):
│           │           ├── offer_coaching_to_all()
│           │           ├── accept_coaching()
│           │           ├── decline_coaching()
│           │           ├── add_coaching_message()
│           │           ├── complete_coaching_session()
│           │           ├── get_coaching_synthesis()
│           │           ├── resume_sanctuary()
│           │           └── can_send_message()
│           │
│           ├── 🐍 nevedal_engine.py              # EMOTIONAL COHERENCE (1122 lines)
│           │   │
│           │   ├── class NevedalConstants
│           │   │   ├── BETA, ALPHA, H_BAR (quantum params)
│           │   │   ├── CEE_* thresholds
│           │   │   └── SYNC_* weights
│           │   │
│           │   ├── @dataclass BiometricSample
│           │   │   ├── heart_rate, hrv_rmssd
│           │   │   ├── voice_pitch_mean, voice_stress_index
│           │   │   └── posture_openness, facial_valence
│           │   │
│           │   ├── @dataclass NevedalState
│           │   │   ├── c_emo (coherence 0-1)
│           │   │   ├── p_ent (entanglement)
│           │   │   ├── t_tunnel (tunneling)
│           │   │   ├── gamma_env (decoherence)
│           │   │   ├── e_g_joint (emotional load)
│           │   │   └── cee_window (bool)
│           │   │
│           │   ├── @dataclass CEEEvent
│           │   │   └── Corrective Emotional Experience tracking
│           │   │
│           │   └── class NevedalEngine
│           │       ├── process_biometrics()
│           │       ├── compute_c_emo()            # Master formula
│           │       ├── detect_cee_window()
│           │       └── get_session_summary()
│           │
│           ├── 🐍 nevedal_handlers.py            # NEVEDAL WEBSOCKET (200 lines)
│           │   │
│           │   └── class NevedalHandler
│           │       ├── handle_biometric_update()
│           │       ├── handle_subscribe()
│           │       ├── handle_get_history()
│           │       ├── handle_session_summary()
│           │       └── _check_crisis_indicators()
│           │
│           ├── 🐍 night_school_curriculum.py     # RAG SYSTEM (776 lines)
│           │   │
│           │   ├── CATEGORIES dict
│           │   │   ├── cbt, crisis, family, workplace
│           │   │   ├── compliance, attachment, trauma
│           │   │   └── mindfulness, communication, general
│           │   │
│           │   └── class NightSchoolCurriculum
│           │       ├── upload_file()
│           │       ├── ingest_file()
│           │       ├── extract_wisdom()
│           │       ├── search_wisdom()            # RAG query
│           │       └── run_night_school_session()
│           │
│           ├── 🐍 stripe_billing.py              # BILLING SYSTEM (762 lines)
│           │   │
│           │   └── class StripeBillingSystem
│           │       ├── PLANS dict (STANDARD, TOP_TIER, FAMILY, TRIAL)
│           │       ├── create_checkout_session()
│           │       ├── handle_webhook()
│           │       ├── record_transaction()
│           │       └── deduct_tokens()
│           │
│           ├── 🐍 stripe_webhook_server.py       # WEBHOOK HANDLER (150 lines)
│           │   │
│           │   └── FastAPI app
│           │       ├── POST /webhook/stripe
│           │       └── POST /admin/subscription/activate
│           │
│           ├── 🐍 bridge_handlers_v2.py          # COACH HANDLERS (811 lines)
│           │   │
│           │   └── class CoachNexusV2
│           │       ├── get_calendar_data()
│           │       ├── get_pre_session_brief()
│           │       ├── cancel_session()
│           │       ├── record_session_notes()
│           │       └── get_coaching_advice()     # Ask Nate (for coaches)
│           │
│           ├── 🐍 device_protection.py           # DEVICE SECURITY (280 lines)
│           │   │
│           │   ├── DEVICE_LIMITS dict
│           │   ├── validate_device()
│           │   ├── remove_device()
│           │   ├── force_logout_all_devices()
│           │   └── detect_suspicious_activity()
│           │
│           ├── 🐍 sanctuary_handlers.py          # SANCTUARY HANDLERS (300 lines)
│           │   │
│           │   └── Handler implementations for:
│           │       ├── sanctuary_create
│           │       ├── sanctuary_join
│           │       ├── sanctuary_message
│           │       ├── sanctuary_coaching_accept
│           │       ├── sanctuary_exit
│           │       └── sanctuary_complete
│           │
│           └── 📁 data/                          # RUNTIME DATA
│               │
│               ├── 📄 user_registry.json         # All users + profiles
│               ├── 📄 analytics.json             # The Eye data
│               ├── 📄 billing.json               # Stripe records
│               ├── 📄 device_registry.json       # Device tracking
│               ├── 📄 family_sanctuaries.json    # Active sanctuaries
│               ├── 📄 crisis_log.json            # Crisis events
│               │
│               └── 📁 Vaults/
│                   ├── 📁 Admin/
│                   │   ├── 📄 wisdom_database.json      # Night School RAG
│                   │   ├── 📄 learning_history.json
│                   │   └── 📁 admin_LN_training_folder/
│                   │       ├── 📁 _inbox/
│                   │       ├── 📁 cbt/
│                   │       ├── 📁 crisis/
│                   │       ├── 📁 family/
│                   │       └── 📁 ... (other categories)
│                   │
│                   ├── 📁 Coaches/
│                   │   └── 📁 {coach_hardware_id}/
│                   │       ├── 📄 metrics.json
│                   │       ├── 📄 schedule.json
│                   │       └── 📄 availability.json
│                   │
│                   └── 📁 Clients/
│                       └── 📁 {client_hardware_id}/
│                           ├── 📄 metrics.json          # Nevedal data
│                           ├── 📄 memory_ledger.json    # Hippocampus
│                           └── 📄 session_history.json
│
├── 📁 mobile/
│   └── 📁 lib/
│       │
│       ├── 🎯 main.dart                          # FLUTTER MAIN (2589 lines)
│       │   │
│       │   ├── main() → LobbyScreen
│       │   │
│       │   ├── class HardwareIdentity
│       │   │   └── getDeviceFingerprint()
│       │   │
│       │   ├── class LobbyScreen
│       │   │   ├── CLIENT PORTAL button
│       │   │   ├── COACH ACCESS button
│       │   │   └── ADMIN ACCESS button
│       │   │
│       │   ├── class SignUpWizard
│       │   │   └── Multi-step registration
│       │   │
│       │   ├── class NeuralInterface
│       │   │   └── AI chat screen
│       │   │
│       │   ├── class FamilySanctuaryScreen       # NEW
│       │   │   ├── _sanctuaryId, _members, _messages
│       │   │   ├── _sanctuaryChannel (separate WS)
│       │   │   ├── _handleSanctuaryMessage()
│       │   │   ├── _buildMembersList()
│       │   │   ├── _buildChatArea()
│       │   │   └── _buildMessageBubble()
│       │   │
│       │   └── class ClientPortal
│       │       ├── Dashboard with metrics
│       │       ├── Family Sanctuary button
│       │       └── Settings
│       │
│       ├── 🎯 shared_widgets.dart                # SHARED WIDGETS (220 lines)
│       │   │
│       │   ├── class VagusEngine
│       │   │   ├── initializeSystem()
│       │   │   ├── startListening()
│       │   │   ├── stopListening()
│       │   │   └── processAudioChunk()
│       │   │
│       │   ├── class VisualPersona               # Little Nate avatar
│       │   │   └── Animated avatar with breathing + blinking
│       │   │
│       │   └── class NervousSystemPainter
│       │       └── Background grid effect
│       │
│       ├── 🎯 metrics_widgets.dart               # METRICS UI
│       │   │
│       │   ├── class MetricsDashboard
│       │   ├── class MoodTrendChart
│       │   └── class SessionHistoryList
│       │
│       ├── 🎯 updated_screens.dart               # UPDATED SCREENS (1454 lines)
│       │   │
│       │   ├── class NeuralInterfaceV2
│       │   │   └── Chat + metrics integration
│       │   │
│       │   └── class CoachPortalScreen
│       │       ├── Dashboard
│       │       ├── Client list
│       │       └── Calendar
│       │
│       └── 🎯 device_widgets.dart                # DEVICE MANAGEMENT
│           │
│           └── class DeviceManagementScreen
│               ├── List registered devices
│               └── Remove device button
│
├── 📁 dashboard/                                 # WEB DASHBOARDS (HTML)
│   │
│   ├── 📁 the_eye/
│   │   ├── the_eye.html                          # Overview
│   │   ├── the_eye_users.html                    # User management
│   │   ├── the_eye_sessions.html                 # Active sessions
│   │   ├── the_eye_revenue.html                  # Billing/revenue
│   │   ├── the_eye_crisis.html                   # Crisis watchlist
│   │   └── the_eye_coaches.html                  # Coach performance
│   │
│   ├── 📁 nevedal_lab/
│   │   ├── nevedal_live.html                     # Real-time C_emo
│   │   ├── nevedal_longitudinal.html             # Historical trends
│   │   └── nevedal_cohort.html                   # Group analysis
│   │
│   └── 📁 night_school/
│       ├── night_school_coach_notes.html         # Coach notes inbox
│       ├── night_school_curriculum.html          # Upload training
│       ├── night_school_wisdom.html              # Wisdom editor
│       ├── night_school_dojo.html                # Adversarial testing
│       └── night_school_analytics.html           # Training metrics
│
├── 📁 docs/                                      # DOCUMENTATION
│   │
│   ├── 📄 FAMILY_SANCTUARY_SPEC.md               # Full sanctuary spec (2806 lines)
│   │   ├── Member lifecycle: INVITED → JOINED → ACTIVE → PAUSED → EXITED
│   │   ├── Billing: $20 base, $5 coaching, $3 assisted
│   │   ├── Little Nate intervention modes
│   │   └── Database schema (PostgreSQL)
│   │
│   ├── 📄 LITTLE_NATE_INTEGRATION_GUIDE.md       # Integration guide
│   │   ├── Azure OpenAI connection
│   │   ├── The Eye analytics flow
│   │   ├── Nevedal metrics integration
│   │   └── Night School RAG flow
│   │
│   ├── 📄 DATA_SOURCE_MAPPING_V2.md              # Data architecture (1610 lines)
│   │   ├── File-based storage (current)
│   │   ├── PostgreSQL schema (target)
│   │   ├── Dashboard data sources
│   │   └── Mobile data integration
│   │
│   ├── 📄 CURSOR_PROJECT_STRUCTURE.md            # Cursor AI guide
│   │   ├── Server folder structure
│   │   ├── Client folder structure
│   │   └── File migration map
│   │
│   ├── 📄 LOGIN_REQUIREMENTS_GUIDE.md            # Auth requirements
│   │
│   ├── 📄 ANALYTICS_AND_CRISIS_PROTOCOL.md       # Crisis detection
│   │   ├── P0: Immediate danger (suicide, kill)
│   │   ├── P1: High risk (hopeless, worthless)
│   │   └── P2: Escalating (angry, frustrated)
│   │
│   ├── 📄 DEVELOPMENT_PROTOCOL.md                # Development checklist
│   │
│   └── 📄 SANCTUARY_COACHING_FLOW_V2.py          # Coaching implementation
│       ├── offer_coaching_to_all()
│       ├── accept_coaching()
│       ├── Private 1-on-1 coaching session
│       ├── Synthesis and reunion
│       └── Full billing integration
│
├── 📄 .env                                       # ENVIRONMENT VARIABLES
│   ├── AZURE_API_KEY
│   ├── AZURE_OPENAI_ENDPOINT
│   ├── AZURE_OPENAI_DEPLOYMENT
│   ├── STRIPE_SECRET_KEY
│   ├── STRIPE_WEBHOOK_SECRET
│   └── SENDGRID_API_KEY
│
├── 📄 .cursorrules                               # CURSOR AI RULES
│   └── Project context for AI assistance
│
├── 📄 requirements.txt                           # PYTHON DEPENDENCIES
│   ├── websockets==12.0
│   ├── aiohttp==3.9.1 (CRITICAL for Azure)
│   ├── stripe==7.0.0
│   ├── sendgrid==6.11.0
│   ├── python-dotenv==1.0.0
│   ├── numpy, scipy, pandas
│   └── PyPDF2, python-docx (optional)
│
└── 📄 pubspec.yaml                               # FLUTTER DEPENDENCIES
    ├── web_socket_channel
    ├── permission_handler
    ├── speech_to_text
    ├── flutter_secure_storage
    ├── local_auth
    └── intl
```

---

## 🔄 DATA FLOW DIAGRAMS

### 1. Login Flow

```
┌─────────────┐     login_request      ┌─────────────┐     verify      ┌─────────────┐
│   Flutter   │ ───────────────────► │   Bridge    │ ─────────────► │  Registry   │
│   Mobile    │                       │   Server    │                 │    JSON     │
└─────────────┘                       └─────────────┘                 └─────────────┘
       ▲                                     │
       │         login_success               │
       └─────────────────────────────────────┘
             {profile, token, metrics}
```

### 2. AI Chat Flow

```
┌─────────────┐   send_message    ┌─────────────┐   RAG query    ┌─────────────┐
│   Flutter   │ ───────────────► │   Bridge    │ ─────────────► │ Night School│
│             │                   │             │                 │   Wisdom    │
└─────────────┘                   └──────┬──────┘                 └─────────────┘
       ▲                                 │
       │                                 │ build prompt
       │                                 ▼
       │                          ┌─────────────┐
       │    streaming response    │   Azure     │
       └───────────────────────── │   Cortex    │
                                  │   (GPT-4)   │
                                  └─────────────┘
```

### 3. Family Sanctuary Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FAMILY SANCTUARY SESSION                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌────────┐      ┌────────┐      ┌────────────────┐      ┌────────┐       │
│   │ John D.│      │ Jane D.│      │  Little Nate   │      │ Backend │       │
│   │(iPhone)│      │(Chrome)│      │  (Observer)    │      │         │       │
│   └───┬────┘      └───┬────┘      └───────┬────────┘      └────┬────┘       │
│       │               │                   │                    │            │
│       │ join          │ join              │                    │            │
│       │───────────────┼───────────────────┼──────────────────►│            │
│       │               │                   │                    │            │
│       │               │ "You hurt me!"    │                    │            │
│       │               │──────────────────►│ detect_escalation()│            │
│       │               │                   │──────────────────►│            │
│       │               │                   │                    │            │
│       │               │                   │ offer_coaching_to_all()         │
│       │◄──────────────┼───────────────────│◄───────────────────│            │
│       │ $5 offer      │ $0 offer (FREE)   │                    │            │
│       │               │                   │                    │            │
│       │               │ ACCEPT            │                    │            │
│       │               │──────────────────►│ accept_coaching()  │            │
│       │               │                   │──────────────────►│            │
│       │               │                   │                    │            │
│       │ PAUSED        │ PRIVATE SESSION   │                    │            │
│       │◄──────────────│◄──────────────────│                    │            │
│       │               │  1-on-1 coaching  │                    │            │
│       │               │                   │                    │            │
│       │               │ coaching_complete │                    │            │
│       │               │──────────────────►│ resume_sanctuary() │            │
│       │               │                   │──────────────────►│            │
│       │               │                   │                    │            │
│       │ RESUMED       │ RESUMED           │ synthesis message  │            │
│       │◄──────────────┼───────────────────│◄───────────────────│            │
│       │               │                   │                    │            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4. Nevedal Metrics Flow

```
┌─────────────┐   biometric_update   ┌─────────────┐   process    ┌─────────────┐
│   Flutter   │ ──────────────────► │  Nevedal    │ ──────────► │  C_emo      │
│   (voice,   │   {hrv, voice,      │  Handler    │              │  compute()  │
│    HRV)     │    breath}          │             │              │             │
└─────────────┘                     └──────┬──────┘              └──────┬──────┘
                                           │                            │
                                           │ store & broadcast          │
                                           ▼                            │
                                    ┌─────────────┐                     │
                                    │   metrics   │◄────────────────────┘
                                    │    .json    │   {c_emo, cee_window,
                                    └─────────────┘    risk_level}
```

---

## 📊 DATABASE SCHEMAS

### Current: File-Based (JSON)

| File | Contents | Updated By |
|------|----------|------------|
| `user_registry.json` | All users, profiles, credentials | Login, signup, profile updates |
| `analytics.json` | The Eye metrics, costs | Every AI interaction |
| `billing.json` | Stripe subscriptions, transactions | Stripe webhooks |
| `family_sanctuaries.json` | Active sanctuary sessions | Sanctuary engine |
| `wisdom_database.json` | Night School RAG data | Night School ingestion |
| `Vaults/Clients/{id}/metrics.json` | Individual Nevedal data | Biometric updates |

### Target: PostgreSQL (per DATA_SOURCE_MAPPING_V2.md)

```sql
-- Core tables
users (id, username, password_hash, role, hardware_id, family_id)
user_profiles (user_id, name, tier, subscription_plan, token_balance)
sessions (id, user_id, coach_id, started_at, c_emo_avg, cee_count)
messages (id, session_id, role, content, timestamp, token_count)

-- Nevedal tables  
nevedal_metrics (id, session_id, user_id, c_emo, p_ent, cee_window)

-- Sanctuary tables
family_sanctuary_sessions (id, family_id, hoh_id, status, total_charges)
sanctuary_members (id, sanctuary_id, user_id, status, free_coaching_used)
sanctuary_messages (id, sanctuary_id, sender_id, content, is_private)
sanctuary_interventions (id, sanctuary_id, recipient_id, charge_amount)
```

---

## 🎯 KEY INTEGRATION POINTS

### 1. AzureCortex ↔ Night School (RAG)

```python
# In bridge_server.py AzureCortex.process_interaction()
relevant_wisdom = self._search_wisdom(user_message)  # Night School query
system_prompt = self._build_prompt(profile, nevedal_context, relevant_wisdom)
# Azure GPT-4 call with enriched prompt
```

### 2. AzureCortex ↔ Nevedal

```python
# Before AI call
nevedal_context = self.metrics.load_metrics(profile)  # Get C_emo, risk_level

# After AI response
if breakthrough_detected:
    self.metrics.record_breakthrough(profile)
```

### 3. Sanctuary ↔ All Systems

```python
# In sanctuary_engine.py
self.azure_cortex  # For Little Nate AI responses
self.nevedal_handler  # For member emotional metrics
self.billing  # For charging coaching fees
self.analytics  # For The Eye tracking
```

---

## 🚀 STARTUP COMMANDS

### Backend
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
DATA_DIR=./data python3 bridge_server.py

# Output:
# [*] Database Root: data
# >>> [BILLING] Stripe initialized
# >>> [NEVEDAL] Handler initialized
# [*] Starting Sovereign Bridge v16.1 on 0.0.0.0:8765
# [*] Bridge Online. Awaiting connections...
```

### Flutter (iPhone)
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter run
```

### Flutter (Chrome)
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter run -d chrome
```

### Stripe Webhooks (separate terminal)
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
uvicorn stripe_webhook_server:app --host 0.0.0.0 --port 8766
```

---

## ✅ CURRENT STATUS

### Working ✅
- [x] Multi-role login (CLIENT, COACH, ADMIN)
- [x] AI chat with Night School RAG
- [x] Nevedal metrics tracking
- [x] The Eye analytics dashboard
- [x] Stripe billing integration
- [x] Device protection
- [x] Family Sanctuary core messaging
- [x] Little Nate intervention (escalation detection)
- [x] Real-time member sync (fixed duplicate bug)
- [x] Cross-device messaging

### In Progress 🔄
- [ ] Private coaching flow (v2 implementation)
- [ ] Coaching synthesis and reunion
- [ ] Message history on reconnect
- [ ] Assisted response generation

### Planned 📋
- [ ] PostgreSQL migration
- [ ] Redis caching
- [ ] Push notifications
- [ ] Voice biometrics (full)
- [ ] CEE window detection (production)

---

## 📝 RECENT FIXES (This Session)

1. **Duplicate member bug** - Fixed with `add_or_reconnect_member()` 
2. **Stream already listened** - Fixed with independent WebSocket connections
3. **datetime.datetime error** - Fixed import in sanctuary_engine
4. **MetricsEngine.get_metrics** - Changed to `load_metrics()`
5. **process_sanctuary_message** - Added to AzureCortex class
6. **Reconnect handler** - Added message history to `sanctuary_reconnected`

---

**Document Version:** 2.0  
**Last Updated:** January 27, 2026 2:45 AM  
**Maintainer:** Clinical Sovereignty Lab Development Team
