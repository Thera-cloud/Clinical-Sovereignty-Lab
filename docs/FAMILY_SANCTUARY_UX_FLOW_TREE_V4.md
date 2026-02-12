# FAMILY SANCTUARY - COMPLETE UX FLOW TREE V4.0
## WebSocket Protocol & Code Reference Guide

**Last Updated:** January 29, 2026  
**Version:** 4.0 (Phase 2 - Session Lifecycle Complete)  
**Status:** ✅ UI Working | ⚠️ Azure AI Pending

---

## 📁 FILE REFERENCES

### Backend (Python)
| File | Location | Purpose |
|------|----------|---------|
| `bridge_server.py` | `backend/app/websocket/` | Main WebSocket handler, all sanctuary message handlers |
| `sanctuary_engine.py` | `backend/app/websocket/` | Sanctuary state management, member tracking, coaching sessions |
| `stripe_billing.py` | `backend/app/websocket/` | Billing for coaching ($5), assisted responses ($3) |

### Frontend (Flutter/Dart)
| File | Location | Purpose |
|------|----------|---------|
| `main.dart` | `mobile/lib/` | FamilySanctuaryScreen, all WebSocket handlers, UI components |

### Data Storage
| File/Folder | Location | Purpose |
|-------------|----------|---------|
| `active_sanctuaries` | `data/sanctuary_engine_data.json` | Live sanctuary state |
| `sanctuary_history/` | `data/sanctuary_history/{id}.json` | Completed session archives |

### Key Code Locations in `bridge_server.py`
| Handler | Search Pattern |
|---------|---------------|
| sanctuary_get_or_create | `elif t == "sanctuary_get_or_create":` |
| sanctuary_message | `elif t == "sanctuary_message":` |
| sanctuary_coaching_accept | `elif t == "sanctuary_coaching_accept":` |
| sanctuary_coaching_message | `elif t == "sanctuary_coaching_message":` |
| sanctuary_coaching_complete | `elif t == "sanctuary_coaching_complete":` |
| sanctuary_coaching_extend | `elif t == "sanctuary_coaching_extend":` |
| sanctuary_request_assisted_response | `elif t == "sanctuary_request_assisted_response":` |
| sanctuary_exit | `elif t == "sanctuary_exit":` |
| **sanctuary_entry_responses** | `elif t == "sanctuary_entry_responses":` |
| **sanctuary_complete** | `elif t == "sanctuary_complete":` |

### Key Code Locations in `main.dart`
| Handler | Search Pattern |
|---------|---------------|
| WebSocket Message Switch | `switch (type) {` in `_handleSanctuaryMessage` |
| Coaching UI | `Widget _buildPrivateCoachingUI()` |
| Pause Screen | `Widget _buildPausedOverlay()` |
| Coaching Offer Modal | `void _showCoachingOfferModal()` |
| **Entry Questions Overlay** | `Widget _buildEntryQuestionsOverlay()` |
| **Session Summary Overlay** | `Widget _buildSessionSummaryOverlay()` |

---

## 🔄 WEBSOCKET MESSAGE TYPES (33 Total)

### Client → Server (15 messages)
| Message Type | Payload | Purpose |
|--------------|---------|---------|
| `sanctuary_get_or_create` | `{family_id, member_id, member_name}` | Join/create sanctuary |
| `sanctuary_message` | `{sanctuary_id, message}` | Send group chat message |
| `sanctuary_coaching_accept` | `{sanctuary_id, intervention_id}` | Accept coaching offer |
| `sanctuary_coaching_decline` | `{sanctuary_id, intervention_id}` | Decline coaching offer |
| `sanctuary_coaching_message` | `{sanctuary_id, message}` | Send message in private coaching |
| `sanctuary_coaching_complete` | `{sanctuary_id, request_assisted_response}` | End coaching session |
| `sanctuary_coaching_extend` | `{sanctuary_id}` | Pay $5 for 5 more steps |
| `sanctuary_request_assisted_response` | `{sanctuary_id}` | Request $3 assisted response |
| `sanctuary_exit` | `{sanctuary_id}` | Request to exit |
| `sanctuary_exit_confirm` | `{sanctuary_id, reason, inform_family}` | Confirm exit |
| `login_request` | `{username, password, expected_role}` | Authenticate |
| `get_metrics` | `{}` | Get user metrics |
| **`sanctuary_entry_responses`** | `{sanctuary_id, responses}` | Submit entry question answers |
| **`sanctuary_complete`** | `{sanctuary_id}` | Complete/close session |

### Server → Client (18 messages)
| Message Type | Payload | Purpose |
|--------------|---------|---------|
| `sanctuary_created` | `{sanctuary_id, status, base_fee_charged}` | New sanctuary created |
| `sanctuary_joined` | `{sanctuary_id, status, members, messages}` | Joined existing sanctuary |
| `sanctuary_reconnected` | `{sanctuary_id, status, members, messages}` | Reconnected after refresh |
| `sanctuary_rejoined` | `{sanctuary_id, status, members, messages}` | Returned after exit |
| `sanctuary_message` | `{sender_id, sender_name, content, timestamp}` | Broadcast chat message |
| `sanctuary_coaching_offer` | `{sanctuary_id, intervention_id, is_free, cost, trigger_member, message}` | Offer coaching popup |
| `sanctuary_coaching_started` | `{sanctuary_id, coaching_session, message}` | Entered private coaching |
| `sanctuary_coaching_response` | `{sanctuary_id, coaching_message, is_deescalated, attempts_remaining}` | Little Nate's response |
| `sanctuary_coaching_resumed` | `{sanctuary_id, coaching_session, message}` | Resume coaching after return |
| `sanctuary_coaching_limit_reached` | `{sanctuary_id, attempt_number, max_steps, is_deescalated, options, message}` | Hit 5-step limit |
| `sanctuary_coaching_extended` | `{sanctuary_id, new_max_steps, charge_amount, message}` | Session extended (+$5) |
| `sanctuary_assisted_response_generated` | `{sanctuary_id, assisted_response, explanation, charge_amount, message}` | $3 suggested response |
| `sanctuary_coaching_completed` | `{sanctuary_id, message, assisted_response?}` | Coaching ended |
| `sanctuary_member_coaching` | `{member_name, message}` | Show pause screen |
| `sanctuary_resumed` | `{message}` | Sanctuary unpaused |
| `sanctuary_member_returned` | `{member, member_id, member_name, message}` | Member returned |
| `sanctuary_member_exited` | `{message}` | Member left |
| `sanctuary_exit_checkin` | `{message}` | Exit confirmation dialog |
| `sanctuary_exited` | `{}` | Confirmed exit |
| **`sanctuary_entry_questions`** | `{questions}` | Send entry questions to member |
| **`sanctuary_entry_complete`** | `{sanctuary_id, message}` | Entry responses saved |
| **`sanctuary_entry_ready`** | `{sanctuary_id, status, members, messages}` | Entry complete, show chat |
| **`sanctuary_generating_summary`** | `{sanctuary_id, message}` | Summary being generated |
| **`sanctuary_summary`** | `{sanctuary_id, summary, session_stats, member_insights}` | Session summary for member |

---

## 🌳 PHASE 2 FLOW TREES

### ENTRY QUESTIONS FLOW (New in V4)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ENTRY QUESTIONS FLOW                                 │
│                    (First-time member joins sanctuary)                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ sanctuary_get_or_create       │
                    │ returns: JOINED (new member)  │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ CHECK: Has member completed   │
                    │ entry_responses?              │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ NO - First time   │           │ YES - Already     │
        │                   │           │ answered          │
        └───────────────────┘           └───────────────────┘
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ sanctuary_entry_  │           │ Go directly to    │
        │ questions         │           │ MAIN CHAT         │
        │ (Server → Client) │           └───────────────────┘
        └───────────────────┘
                    │
                    ▼
        ┌─────────────────────────────────────────┐
        │       ENTRY QUESTIONS OVERLAY           │
        │  ┌───────────────────────────────────┐  │
        │  │  Before we begin...               │  │
        │  │                                   │  │
        │  │  Q1: Why are you here today?      │  │
        │  │  [________________________________]│  │
        │  │                                   │  │
        │  │  Q2: What would you like to       │  │
        │  │      work on?                     │  │
        │  │  [________________________________]│  │
        │  │                                   │  │
        │  │  Q3: What does success look like? │  │
        │  │  [________________________________]│  │
        │  │                                   │  │
        │  │  Q4: How are you feeling? (1-10)  │  │
        │  │  [    Slider: 1 ──●────── 10    ] │  │
        │  │                                   │  │
        │  │         [ Continue → ]            │  │
        │  └───────────────────────────────────┘  │
        └─────────────────────────────────────────┘
                    │
                    │ User submits
                    ▼
        ┌───────────────────────────────┐
        │ sanctuary_entry_responses     │
        │ (Client → Server)             │
        │ {sanctuary_id, responses: {   │
        │   why_here, work_on,          │
        │   success_looks_like,         │
        │   feeling_scale               │
        │ }}                             │
        └───────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │ Backend stores in:            │
        │ sanctuary_data.entry_responses│
        │ [member_id] = {responses,     │
        │   member_name, timestamp}     │
        └───────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │ sanctuary_entry_complete      │
        │ (Server → Client)             │
        │ "Thank you for sharing."      │
        └───────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │ sanctuary_entry_ready         │
        │ (Server → Client)             │
        │ {status, members, messages}   │
        └───────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────────────┐
        │ MAIN SANCTUARY CHAT           │
        │ (Entry overlay dismissed)     │
        └───────────────────────────────┘
```

**Entry Questions Data Structure:**
```json
{
  "entry_responses": {
    "CLIENT_001": {
      "why_here": "We've been fighting a lot lately",
      "work_on": "Better communication with my spouse",
      "success_looks_like": "Having one conversation without yelling",
      "feeling_scale": 4,
      "member_name": "John D.",
      "timestamp": "2026-01-29T03:15:00.000Z"
    },
    "CLIENT_001B": {
      "why_here": "John wanted us to try this",
      "work_on": "Feeling heard",
      "success_looks_like": "John understands my perspective",
      "feeling_scale": 3,
      "member_name": "Jane D.",
      "timestamp": "2026-01-29T03:16:30.000Z"
    }
  }
}
```

---

### COMPLETE SESSION FLOW (New in V4)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE SESSION FLOW                                │
│                    (Head of Household ends session)                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ User clicks "Complete Session"│
                    │ from ⋮ menu                   │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ sanctuary_complete            │
                    │ (Client → Server)             │
                    │ {sanctuary_id}                │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ sanctuary_generating_summary  │
                    │ (Server → All Members)        │
                    │ "Generating session summary..." │
                    └───────────────────────────────┘
                                    │
                                    ▼
        ┌─────────────────────────────────────────────────────────┐
        │                 BACKEND PROCESSING                       │
        │                                                         │
        │  1. Gather all data:                                    │
        │     - entry_responses (per member)                      │
        │     - messages (all conversation)                       │
        │     - coaching_sessions (private coaching logs)         │
        │     - billing (charges incurred)                        │
        │     - metrics (interventions, escalations)              │
        │                                                         │
        │  2. Build AI prompt with full context                   │
        │                                                         │
        │  3. Call Azure OpenAI for analysis ──┐                  │
        │                                      │                  │
        │     ┌────────────────────────────────┴───────────┐      │
        │     │ AI generates:                              │      │
        │     │ - key_conflicts[]                          │      │
        │     │ - points_of_agreement[]                    │      │
        │     │ - corrective_experiences[]                 │      │
        │     │ - individual_insights{} (per member)       │      │
        │     │   • patterns_observed                      │      │
        │     │   • growth_areas                           │      │
        │     │   • strengths_shown                        │      │
        │     │   • suggested_focus                        │      │
        │     │ - overall_progress (1-10)                  │      │
        │     │ - recommended_next_steps[]                 │      │
        │     │ - coach_notes                              │      │
        │     └────────────────────────────────────────────┘      │
        │                                                         │
        │  4. Auto-flag for coach review if:                      │
        │     - Duration > 7 days                                 │
        │     - Progress score ≤ 4                                │
        │     - Concerning keywords detected:                     │
        │       "hurt myself", "suicide", "kill", "abuse",        │
        │       "hit me", "scared", "threatened", "weapon"        │
        │                                                         │
        │  5. Save to data/sanctuary_history/{id}.json            │
        │                                                         │
        │  6. Remove from active_sanctuaries                      │
        └─────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ sanctuary_summary             │
                    │ (Server → Each Member)        │
                    │ PERSONALIZED per member       │
                    └───────────────────────────────┘
                                    │
                                    ▼
        ┌─────────────────────────────────────────────────────────┐
        │              SESSION SUMMARY OVERLAY                     │
        │  ┌───────────────────────────────────────────────────┐  │
        │  │  📋 Session Summary                               │  │
        │  │                                                   │  │
        │  │  ┌─────────────────────────────────────────────┐  │  │
        │  │  │  45m        │  168        │  7/10          │  │  │
        │  │  │  Duration   │  Messages   │  Progress      │  │  │
        │  │  └─────────────────────────────────────────────┘  │  │
        │  │                                                   │  │
        │  │  ⚠️ Key Conflicts                                 │  │
        │  │  • Feeling rejected around intimacy               │  │
        │  │  • Unmet household expectations                   │  │
        │  │  • Physical response (Jane hit John)              │  │
        │  │                                                   │  │
        │  │  🤝 Points of Agreement                           │  │
        │  │  • Both want to feel heard                        │  │
        │  │  • Willingness to keep trying                     │  │
        │  │                                                   │  │
        │  │  ┌─────────────────────────────────────────────┐  │  │
        │  │  │  👤 Your Personal Insights                  │  │  │
        │  │  │                                             │  │  │
        │  │  │  Patterns: Anger escalates when dismissed   │  │  │
        │  │  │  Growth: Practice "I feel..." statements    │  │  │
        │  │  │  Strengths: Kept returning to conversation  │  │  │
        │  │  │  Focus: Managing rejection sensitivity      │  │  │
        │  │  └─────────────────────────────────────────────┘  │  │
        │  │                                                   │  │
        │  │  → Next Steps                                     │  │
        │  │  • Schedule follow-up family discussion           │  │
        │  │  • Consider live coaching session                 │  │
        │  │                                                   │  │
        │  │              [ Close & Exit ]                     │  │
        │  └───────────────────────────────────────────────────┘  │
        └─────────────────────────────────────────────────────────┘
                                    │
                                    │ User clicks "Close & Exit"
                                    ▼
                    ┌───────────────────────────────┐
                    │ Navigate back to lobby        │
                    │ (Sanctuary closed)            │
                    └───────────────────────────────┘
```

---

### COACH HISTORY & AUTO-FLAG FLOW (New in V4)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COACH HISTORY STORAGE FLOW                                │
│                 (Automatic on session complete)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ sanctuary_complete triggered  │
                    └───────────────────────────────┘
                                    │
                                    ▼
        ┌─────────────────────────────────────────────────────────┐
        │              ARCHIVE DATA STRUCTURE                      │
        │                                                         │
        │  data/sanctuary_history/SANC_20260126_001.json          │
        │  {                                                      │
        │    "sanctuary_id": "SANC_20260126_001",                 │
        │    "family_id": "FAM_1834DACF",                         │
        │    "status": "COMPLETED",                               │
        │    "created_at": "...",                                 │
        │    "completed_at": "...",                               │
        │                                                         │
        │    "members": [...],                                    │
        │    "entry_responses": {...},  ← Initial goals/feelings  │
        │    "messages": [...],         ← Full conversation       │
        │    "coaching_sessions": {...},← Private coaching logs   │
        │    "billing": {...},          ← All charges             │
        │    "metrics": {...},          ← Intervention stats      │
        │                                                         │
        │    "session_summary": {       ← AI-generated            │
        │      "generated_at": "...",                             │
        │      "summary": {...},                                  │
        │      "duration_minutes": 45,                            │
        │      "total_messages": 168,                             │
        │      "coaching_sessions": 2                             │
        │    },                                                   │
        │                                                         │
        │    "needs_coach_review": true, ← AUTO-FLAG              │
        │    "review_reasons": [                                  │
        │      "Concerning content detected",                     │
        │      "Progress score below threshold"                   │
        │    ]                                                    │
        │  }                                                      │
        └─────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ AUTO-FLAG TRIGGERS            │
                    │                               │
                    │ Flag if ANY of:               │
                    │ • Duration > 7 days           │
                    │ • Progress ≤ 4                │
                    │ • Keywords detected:          │
                    │   - "hurt myself"             │
                    │   - "suicide"                 │
                    │   - "kill"                    │
                    │   - "abuse"                   │
                    │   - "hit me"                  │
                    │   - "scared"                  │
                    │   - "threatened"              │
                    │   - "weapon"                  │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ FLAGGED           │           │ NOT FLAGGED       │
        │                   │           │                   │
        │ needs_coach_review│           │ needs_coach_review│
        │ = true            │           │ = false           │
        │                   │           │                   │
        │ → Coach dashboard │           │ → Archive only    │
        │   shows alert     │           │                   │
        └───────────────────┘           └───────────────────┘
```

---

### DATA FLOW TO OTHER SYSTEMS (Future Integration)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SYSTEM INTEGRATION FLOW                                   │
│                 (Sanctuary → The Eye → Nevedal → Night School)               │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │    COMPLETED SANCTUARY        │
                    │    (session_summary)          │
                    └───────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│     THE EYE       │   │     NEVEDAL       │   │   NIGHT SCHOOL    │
│  (Analytics)      │   │  (Coherence)      │   │  (LN Learning)    │
└───────────────────┘   └───────────────────┘   └───────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ Metrics:          │   │ Track:            │   │ Ingest:           │
│ • Session duration│   │ • feeling_scale   │   │ • Successful      │
│ • Message count   │   │   (entry vs exit) │   │   interventions   │
│ • Escalation count│   │ • Emotional tone  │   │ • De-escalation   │
│ • Progress scores │   │   over time       │   │   patterns        │
│ • Coaching usage  │   │ • Coherence trend │   │ • What worked     │
│ • Billing totals  │   │ • Family harmony  │   │ • What didn't     │
└───────────────────┘   └───────────────────┘   └───────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│ Display:          │   │ Display:          │   │ Train:            │
│ • Client dashboard│   │ • Coherence graph │   │ • Little Nate     │
│ • Coach overview  │   │ • Trend alerts    │   │   responses       │
│ • Family progress │   │ • Recommendations │   │ • Context-aware   │
│   over time       │   │                   │   │   coaching        │
└───────────────────┘   └───────────────────┘   └───────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │       LITTLE NATE             │
                    │   (Informed by all systems)   │
                    │                               │
                    │ Uses:                         │
                    │ • Entry responses for context │
                    │ • Historical patterns         │
                    │ • Coach guidance notes        │
                    │ • Learned intervention styles │
                    └───────────────────────────────┘
```

---

## 🔄 COMPLETE SESSION LIFECYCLE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FULL SESSION LIFECYCLE                                    │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │   CREATE     │  sanctuary_get_or_create → sanctuary_created ($20)
  │   SANCTUARY  │
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │   ENTRY      │  sanctuary_entry_questions → member answers 4 questions
  │   QUESTIONS  │  sanctuary_entry_responses → sanctuary_entry_ready
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │   FAMILY     │  Members chat, Little Nate monitors
  │   CHAT       │  Escalation detected → coaching_offer
  └──────┬───────┘
         │
         ├───────────────────────────────────────┐
         │                                       │
         ▼                                       ▼
  ┌──────────────┐                     ┌──────────────┐
  │   PRIVATE    │  Accept coaching    │   PAUSE      │  Others wait
  │   COACHING   │  1 free, then $5    │   SCREEN     │
  │              │  5-step limit       │              │
  │              │  Extend: +$5        │              │
  │              │  Assisted: $3       │              │
  └──────┬───────┘                     └──────┬───────┘
         │                                    │
         │ coaching_completed                 │ sanctuary_resumed
         │                                    │
         └────────────────┬───────────────────┘
                          │
                          ▼
                 ┌──────────────┐
                 │   RETURN TO  │  Resume chat, repeat as needed
                 │   CHAT       │
                 └──────┬───────┘
                        │
                        │ User clicks "Complete Session"
                        ▼
                 ┌──────────────┐
                 │   COMPLETE   │  sanctuary_complete
                 │   SESSION    │
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │   AI        │  Azure analyzes full session
                 │   SUMMARY    │  Generates personalized insights
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │   DISPLAY    │  sanctuary_summary → each member
                 │   SUMMARY    │  Session Summary Overlay
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │   ARCHIVE    │  Save to sanctuary_history/
                 │   & FLAG     │  Auto-flag if concerning
                 └──────┬───────┘
                        │
                        ▼
                 ┌──────────────┐
                 │   CLOSE      │  Remove from active
                 │              │  Navigate to lobby
                 └──────────────┘
```

---

## 💰 BILLING SUMMARY (Updated)

| Action | Cost | When Charged |
|--------|------|--------------|
| Create Sanctuary | $20.00 | `sanctuary_created` |
| First Coaching (per member) | FREE | `sanctuary_coaching_accept` |
| Subsequent Coaching | $5.00 | `sanctuary_coaching_accept` (if `free_coaching_used=true`) |
| Assisted Response | $3.00 | `sanctuary_request_assisted_response` |
| Coaching Extension | $5.00 | `sanctuary_coaching_extend` |
| Entry Questions | FREE | Always free |
| Session Summary | FREE | Always free |
| Complete Session | FREE | No charge to close |

**Billing charged to:** Head of Household's Stripe account

---

## 🔧 STATE VARIABLES (Flutter - Updated)

```dart
// Sanctuary State
String? _sanctuaryId;
String _sanctuaryStatus = 'WAITING';
List<Map<String, dynamic>> _members = [];
List<Map<String, dynamic>> _messages = [];

// Coaching State
bool _inPrivateCoaching = false;
bool _sanctuaryPaused = false;
bool _showCoachingModal = false;
bool _coachingLimitReached = false;
int _coachingAttempt = 1;
int _coachingMaxSteps = 5;
List<Map<String, dynamic>> _coachingMessages = [];
Map<String, dynamic>? _coachingOffer;
String _pausedByMember = '';
DateTime? _lastResumedAt;

// PHASE 2 - Entry Questions State
bool _showEntryQuestions = false;
List<Map<String, dynamic>> _entryQuestions = [];
Map<String, String> _entryResponses = {};

// PHASE 2 - Session Summary State
bool _showSessionSummary = false;
bool _generatingSummary = false;
Map<String, dynamic>? _sessionSummary;
Map<String, dynamic>? _sessionStats;
```

---

## ✅ TESTED & VERIFIED FEATURES

### Phase 1 (V3.0)
- [x] Sanctuary creation with $20 base fee
- [x] Member join/reconnect/return with message history
- [x] Escalation detection triggers coaching offer
- [x] Coaching offer popup with pricing
- [x] Private coaching UI with step counter
- [x] 5-step coaching limit
- [x] $5 coaching extension
- [x] $3 assisted response generation
- [x] Assisted response display in UI
- [x] "Oops" early exit detection
- [x] Pause screen for waiting members
- [x] Coaching offer on reconnect/return
- [x] Coaching session resume on return
- [x] Auto-dismiss pause screen on sanctuary_resumed
- [x] Exit dialog with check-in
- [x] Message history persistence
- [x] Green dot member status indicators

### Phase 2 (V4.0)
- [x] Entry questions overlay UI
- [x] Entry responses WebSocket handler (backend)
- [x] Entry responses stored per member
- [x] Complete Session menu option
- [x] sanctuary_complete WebSocket handler
- [x] AI summary generation (fallback working)
- [x] Session Summary overlay UI
- [x] Personalized insights per member
- [x] Coach history storage (JSON files)
- [x] Auto-flag for coach review
- [ ] Azure OpenAI integration (pending)
- [ ] The Eye data feed (pending)
- [ ] Nevedal coherence tracking (pending)
- [ ] Night School learning pipeline (pending)
- [ ] 7-day coach check-in (pending)

---

## 🐛 KNOWN EDGE CASES (Handled)

### Phase 1
1. **Stale `sanctuary_member_coaching` after resume**
   - Fix: 2-second ignore window after `sanctuary_resumed`
   
2. **Null member data in `sanctuary_member_returned`**
   - Fix: Null-safe parsing with fallback to `member_name` or `message`

3. **Coaching offer to member already in coaching**
   - Fix: Backend skips members with `status='IN_COACHING'`

4. **Message history lost on return**
   - Fix: Backend includes `messages` array in `sanctuary_rejoined`

### Phase 2
5. **`sanctuary_data` not defined in JOINED handler**
   - Fix: Changed to `existing.get("messages", [])` (line 3356)

6. **`call_azure_openai` not defined**
   - Fix: Fallback summary data used
   - Pending: Identify correct AI function name

7. **Session summary overlay not showing**
   - Fix: Added `_buildSessionSummaryOverlay()` call to Stack

8. **Flutter sed corruption (`cocolor`, `dydynamic`)**
   - Fix: Multiple sed recovery commands

---

## 📝 CHANGELOG

### V4.0 (January 29, 2026)
- **NEW:** Entry questions flow (4 questions at session start)
- **NEW:** sanctuary_entry_responses WebSocket handler
- **NEW:** Entry questions overlay UI
- **NEW:** Complete Session menu option
- **NEW:** sanctuary_complete WebSocket handler
- **NEW:** AI session summary generation (with fallback)
- **NEW:** Session Summary overlay UI
- **NEW:** Personalized insights per member
- **NEW:** Coach history storage (JSON archives)
- **NEW:** Auto-flag for coach review
- **FIX:** sanctuary_data undefined in JOINED handler
- **FIX:** Session summary overlay added to Stack
- **PENDING:** Azure OpenAI integration
- **PENDING:** System integration (The Eye, Nevedal, Night School)

### V3.0 (January 29, 2026)
- Added $5 coaching extension feature
- Added $3 assisted response display
- Fixed pause screen auto-dismiss
- Fixed message history on all reconnect scenarios
- Added coaching limit dialog
- Fixed null member data handling
- Completed end-to-end testing

### V2.0 (January 28, 2026)
- Added coaching offer on reconnect/return
- Added coaching session resume
- Fixed oops detection
- Added pause screen

### V1.0 (January 27, 2026)
- Initial implementation
- Basic sanctuary flow
- Private coaching UI

---

## 🔮 NEXT STEPS (Phase 3)

1. **Azure OpenAI Integration**
   - Find existing AI function in bridge_server.py
   - Hook up to summary generation
   - Real personalized insights

2. **The Eye Integration**
   - Feed session metrics on complete
   - Dashboard updates in real-time

3. **Nevedal Integration**
   - Track feeling_scale changes
   - Emotional coherence over sessions

4. **Night School Integration**
   - Ingest successful interventions
   - Train Little Nate on patterns

5. **7-Day Coach Check-in**
   - Background task to check session durations
   - Notify assigned coach for long sessions

6. **Coach Dashboard**
   - View flagged sessions
   - Review summaries
   - Add guidance notes
