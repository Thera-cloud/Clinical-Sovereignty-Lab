> **HISTORICAL — READ ONLY as of 2026-04-30.** New open items go 
> in `docs/OPEN_TODOS.md`, not here. This file is preserved for 
> historical reference and pending reconciliation. See 
> docs/OPEN_TODOS.md for active work.

# CLINICAL SOVEREIGNTY LAB - MOBILE APP UX FLOW TREE V1.0
## Complete Flutter/Dart + WebSocket Protocol Reference

**Last Updated:** January 29, 2026  
**Version:** 1.0 (Top Tier Subscription Features)  
**Platform:** Flutter (iOS/Android/Web)  
**Backend:** Python WebSocket (bridge_server.py)

---

## 📱 APP ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CLINICAL SOVEREIGNTY LAB APP                             │
│                         Flutter Mobile Client                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │         main.dart             │
                    │    (Single File Architecture) │
                    └───────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  LobbyScreen  │         │ NeuralInterface │         │ FamilySanctuary │
│   (Login)     │         │    Screen       │         │     Screen      │
└───────────────┘         │ (1:1 AI Chat)   │         │ (Group Therapy) │
                          └─────────────────┘         └─────────────────┘
```

---

## 🔌 WEBSOCKET CONNECTIONS

### Connection Architecture
```
┌─────────────────┐     ws://10.0.0.99:8765     ┌─────────────────┐
│  Flutter App    │ ◄────────────────────────► │  bridge_server  │
│                 │                             │    (Python)     │
│  - Lobby WS     │                             │                 │
│  - Cortex WS    │                             │  - Auth         │
│  - Sanctuary WS │                             │  - AI (Azure)   │
└─────────────────┘                             │  - Billing      │
                                                │  - Sanctuary    │
                                                └─────────────────┘
```

### WebSocket Instances in Flutter
| Instance | Purpose | Screen |
|----------|---------|--------|
| `_lobbyChannel` | Login authentication | LobbyScreen |
| `_channel` (Cortex) | AI chat, metrics | NeuralInterfaceScreen |
| `_channel` (Sanctuary) | Family therapy session | FamilySanctuaryScreen |

---

## 🎨 SCREEN HIERARCHY

### 1. LobbyScreen (Entry Point)
```
┌─────────────────────────────────────────────────────────────────┐
│                        LOBBY SCREEN                              │
│                     (Authentication)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
  ┌───────────┐        ┌───────────┐        ┌───────────┐
  │  Username │        │  Password │        │   Role    │
  │   Field   │        │   Field   │        │  Selector │
  └───────────┘        └───────────┘        └───────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   Login Button  │
                    └─────────────────┘
                              │
                              ▼
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
    ┌─────────────────┐             ┌─────────────────┐
    │ CLIENT Role     │             │ COACH Role      │
    │ → Home Screen   │             │ → Coach Portal  │
    └─────────────────┘             └─────────────────┘
```

**WebSocket Messages:**
| Direction | Message Type | Payload | Response |
|-----------|--------------|---------|----------|
| Client → | `login_request` | `{username, password, expected_role}` | - |
| ← Server | `login_success` | `{token, profile}` | Navigate to Home |
| ← Server | `login_failed` | `{message}` | Show error |

---

### 2. HomeScreen (Main Navigation Hub)
```
┌─────────────────────────────────────────────────────────────────┐
│                        HOME SCREEN                               │
│                    (Top Tier Dashboard)                          │
└─────────────────────────────────────────────────────────────────┘
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    WELCOME, [NAME]                          │ │
│  │               Subscription: TOP_TIER ⭐                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   METRICS   │  │   TOKENS    │  │   COACH     │             │
│  │  Coherence  │  │   Balance   │  │  Assigned   │             │
│  │    50%      │  │   6,980     │  │ Coach Hope  │             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    FEATURE CARDS                            │ │
│  │                                                              │ │
│  │  ┌────────────────┐    ┌────────────────┐                   │ │
│  │  │ 🧠 Neural      │    │ 👨‍👩‍👧‍👦 Family    │                   │ │
│  │  │   Interface    │    │   Sanctuary    │                   │ │
│  │  │ Chat with      │    │ Group therapy  │                   │ │
│  │  │ Little Nate    │    │ with family    │                   │ │
│  │  └────────────────┘    └────────────────┘                   │ │
│  │                                                              │ │
│  │  ┌────────────────┐    ┌────────────────┐                   │ │
│  │  │ 📊 My Progress │    │ ⚙️ Settings    │                   │ │
│  │  │ View metrics   │    │ Preferences    │                   │ │
│  │  │ and growth     │    │ and account    │                   │ │
│  │  └────────────────┘    └────────────────┘                   │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**WebSocket Messages:**
| Direction | Message Type | Payload | Purpose |
|-----------|--------------|---------|---------|
| Client → | `get_metrics` | `{}` | Request user metrics |
| ← Server | `metrics_data` | `{coherence, wellness_score, ...}` | Update dashboard |

---

### 3. NeuralInterfaceScreen (1:1 AI Chat)
```
┌─────────────────────────────────────────────────────────────────┐
│                   NEURAL INTERFACE                               │
│                  (Little Nate Chat)                              │
└─────────────────────────────────────────────────────────────────┘
│  ← Back                              [Tokens: 6,980]             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 💙 Little Nate                                              │ │
│  │ Hello John! I remember our conversation about               │ │
│  │ your relationship with Jane. How are you feeling today?     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                          ┌────────────────────────────────────┐ │
│                          │ I'm feeling better, but still      │ │
│                          │ worried about how to talk to her   │ │
│                          │ about what happened.               │ │
│                          │                                John│ │
│                          └────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 💙 Little Nate                                              │ │
│  │ I understand. In our Family Sanctuary session, you         │ │
│  │ mentioned feeling rejected when Jane...                    │ │
│  │ [Relational context from story.json]                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  🎤 │ Type your message...                            │  ➤      │
└──────────────────────────────────────────────────────────────────┘
```

**State Variables (Dart):**
```dart
List<Map<String, dynamic>> _messages = [];
bool _isTyping = false;
int _tokenBalance = 0;
final TextEditingController _controller = TextEditingController();
```

**WebSocket Messages:**
| Direction | Message Type | Payload | Purpose |
|-----------|--------------|---------|---------|
| Client → | `login_request` | `{username, password, expected_role}` | Auth on screen open |
| Client → | `nate_query` | `{nate_query \| text}` | Send chat message (scheduling intent when `ENABLE_CHAT_SCHEDULING=true`) |
| ← Server | `nate_response` | `{text}` | Little Nate reply |
| ← Server | `scheduling_slots` | `{surface:"chat", coach_id, date, slots[]}` | Real open times (chip sheet); only when `surface==chat` |
| Client → | `client_book_session` | `{coach_id, scheduled_start, scheduled_end}` | Book from chip tap (same writer as Schedule screen) |
| ← Server | `session_booked` | `{session}` | `pending_approval` → "requested"; else "booked" |
| ← Server | `error` | `{message: COVENANT_REQUIRED \| SESSION_LIMIT_REACHED \| Time slot conflict}` | Booking blocked |
| ← Server | `token_update` | `{balance}` | Update token display |

**Chat scheduling branch** (`ENABLE_CHAT_SCHEDULING`, see `16_client_schedule.md` §18):
```
"nate_query" (book / open times + coach)
  → scheduling assistant + coach_slot_engine (no LLM-invented times)
  → nate_response + scheduling_slots (surface=chat)
  → tap chip → client_book_session → session_booked | error
```
Full calendar: Settings → **View Availability & Book Session** (`ClientScheduleScreen`).

**AI Context Injection (Backend):**
```
System Prompt includes:
├── story.json (relational depth)
│   ├── who_you_are (name, strengths)
│   ├── wounds (recent_hurts, core_wounds)
│   ├── growth (breakthroughs, edges)
│   └── relationships (family dynamics)
├── sanctuary_history (past sessions)
├── night_school wisdom (therapeutic techniques)
└── nevedal metrics (emotional coherence)
```

---

### 4. FamilySanctuaryScreen (Group Therapy)

#### 4.1 Entry Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                    FAMILY SANCTUARY                              │
│                    Entry Questions                               │
└─────────────────────────────────────────────────────────────────┘
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              Before we begin...                             │ │
│  │                                                              │ │
│  │  What brings you to the sanctuary today?                    │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Family conflict about household responsibilities      │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                              │ │
│  │  What would you like to work on?                            │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ Better communication with my spouse                   │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                              │ │
│  │  Any concerns you'd like to share?                          │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │ I'm worried things will escalate                      │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                                                              │ │
│  │                    [ Continue → ]                            │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.2 Main Chat View
```
┌─────────────────────────────────────────────────────────────────┐
│  Family Sanctuary                              $20.00    ⋮      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  MEMBERS          │  ┌─────────────────────────────────────────┐│
│  ● John D.        │  │     Waiting for family members...       ││
│    member         │  └─────────────────────────────────────────┘│
│  ● Jane D.        │                                             │
│    member         │  ┌─────────────────────────────────────────┐│
│                   │  │ 💙 Little Nate                          ││
│                   │  │ Welcome to the Family Sanctuary. This   ││
│                   │  │ is a safe space for open dialogue...    ││
│                   │  └─────────────────────────────────────────┘│
│                   │                                             │
│                   │                    ┌────────────────────────┐│
│                   │                    │ John D.                ││
│                   │                    │ I'm angry about what   ││
│                   │                    │ happened yesterday     ││
│                   │                    └────────────────────────┘│
│                   │                                             │
│                   │  ┌─────────────────────────────────────────┐│
│                   │  │ 💙 Little Nate                          ││
│                   │  │ John, I can see you're feeling angry... ││
│                   │  │ Would you like to step aside for        ││
│                   │  │ private coaching?                       ││
│                   │  └─────────────────────────────────────────┘│
│                   │                                             │
├───────────────────┴─────────────────────────────────────────────┤
│  🎤 │ Type your message...                            │  ➤      │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.3 Private Coaching UI
```
┌─────────────────────────────────────────────────────────────────┐
│  🔒 Private Coaching                        Step 2/5    $0.00   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ This is a private conversation between you and            │ │
│  │ Little Nate. Your family cannot see these messages.       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 💙 Little Nate                                              │ │
│  │ John, I can hear how frustrated you are. Tell me           │ │
│  │ more about what happened yesterday that made you           │ │
│  │ feel this way.                                              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│                          ┌────────────────────────────────────┐ │
│                          │ She hit me during the argument.    │ │
│                          │ I feel so disrespected.            │ │
│                          │                                John│ │
│                          └────────────────────────────────────┘ │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│  🎤 │ Type your message...                            │  ➤      │
├──────────────────────────────────────────────────────────────────┤
│  [ Return to Sanctuary ]                  [ Get Assisted Response $3 ]│
└──────────────────────────────────────────────────────────────────┘
```

#### 4.4 Coaching Limit Reached
```
┌─────────────────────────────────────────────────────────────────┐
│                   COACHING LIMIT REACHED                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│        You've used 5 coaching steps in this session.            │
│                                                                  │
│        Would you like to continue?                               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  [ Extend +5 Steps - $5.00 ]                                │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  [ Get Assisted Response - $3.00 ]                          │ │
│  │  Little Nate crafts a message for you to send               │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  [ Return to Sanctuary - Free ]                             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.5 Paused Sanctuary (Waiting for Others)
```
┌─────────────────────────────────────────────────────────────────┐
│                    SANCTUARY PAUSED                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│                         ⏸️                                       │
│                                                                  │
│         John D. is in private coaching with Little Nate         │
│                                                                  │
│              Please wait for them to return...                   │
│                                                                  │
│                    [ Exit Sanctuary ]                            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

#### 4.6 Session Summary
```
┌─────────────────────────────────────────────────────────────────┐
│                   🎉 SANCTUARY COMPLETE                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  SESSION SUMMARY                                                 │
│  ────────────────                                                │
│  Duration: 45 minutes                                            │
│  Messages: 28                                                    │
│  Coaching Sessions: 2                                            │
│  Total Charges: $25.00                                           │
│                                                                  │
│  KEY INSIGHTS                                                    │
│  ────────────────                                                │
│  • Both partners expressed desire for better communication       │
│  • John showed vulnerability discussing rejection sensitivity    │
│  • Jane acknowledged her physical response was inappropriate     │
│                                                                  │
│  PERSONALIZED FOR YOU (John)                                     │
│  ────────────────                                                │
│  Patterns: Anger escalates when feeling dismissed                │
│  Strengths: Kept returning to conversation despite frustration   │
│  Growth Focus: "I feel... when... because..." statements         │
│                                                                  │
│  RECOMMENDED NEXT STEPS                                          │
│  ────────────────                                                │
│  • Schedule follow-up within 48 hours                            │
│  • Practice repair conversation with Little Nate                 │
│                                                                  │
│                    [ Close Summary ]                             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🔄 STATE MANAGEMENT (Flutter)

### FamilySanctuaryScreen State Variables
```dart
class _FamilySanctuaryScreenState extends State<FamilySanctuaryScreen> 
    with WidgetsBindingObserver {
  
  // Connection
  WebSocketChannel? _channel;
  final String _serverUrl = 'ws://10.0.0.99:8765';
  StreamSubscription? _wsSubscription;
  
  // Sanctuary Core State
  String? _sanctuaryId;
  String _sanctuaryStatus = 'LOADING';
  List<Map<String, dynamic>> _members = [];
  List<Map<String, dynamic>> _messages = [];
  double _totalCharges = 20.00;
  bool _isCreator = false;  // Only creator can complete
  
  // Coaching State
  bool _inPrivateCoaching = false;
  bool _coachingLimitReached = false;
  int _coachingMaxSteps = 5;
  int _coachingAttempt = 0;
  List<Map<String, dynamic>> _coachingMessages = [];
  Map<String, dynamic>? _coachingOffer;
  bool _showCoachingModal = false;
  
  // Pause State
  bool _sanctuaryPaused = false;
  String _pausedReason = '';
  DateTime? _lastResumedAt;
  
  // Entry Questions State
  bool _showEntryQuestions = false;
  List<Map<String, dynamic>> _entryQuestions = [];
  Map<String, dynamic> _entryResponses = {};
  int _feelingScale = 5;
  
  // Session Summary State
  bool _showSessionSummary = false;
  bool _generatingSummary = false;
  Map<String, dynamic>? _sessionSummary;
  Map<String, dynamic>? _sessionStats;
  
  // Accessibility
  final SpeechToText _speech = SpeechToText();
  bool _isListening = false;
  bool _speechAvailable = false;
  
  // UI Controllers
  final TextEditingController _messageController = TextEditingController();
  final TextEditingController _coachingController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
}
```

---

## 📡 WEBSOCKET MESSAGE FLOWS

### Flow 1: Create/Join Sanctuary
```
┌─────────────┐                                    ┌─────────────┐
│   Flutter   │                                    │   Backend   │
└──────┬──────┘                                    └──────┬──────┘
       │                                                  │
       │  1. login_request                                │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  2. login_success {token, profile}               │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  3. sanctuary_get_or_create                      │
       │     {family_id, member_id, member_name}          │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ IF: No existing sanctuary                 │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  4a. sanctuary_created                           │
       │      {sanctuary_id, status, base_fee, is_creator}│
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  5a. sanctuary_onboarding {message}              │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ IF: Existing sanctuary found              │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  4b. sanctuary_joined                            │
       │      {sanctuary_id, status, members, messages}   │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
```

### Flow 2: Entry Questions → Chat
```
┌─────────────┐                                    ┌─────────────┐
│   Flutter   │                                    │   Backend   │
└──────┬──────┘                                    └──────┬──────┘
       │                                                  │
       │  (User completes entry questions form)           │
       │                                                  │
       │  1. sanctuary_onboarding_complete                │
       │     {sanctuary_id, responses}                    │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  2. sanctuary_entry_complete                     │
       │     {sanctuary_id, message}                      │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  3. sanctuary_entry_ready                        │
       │     {sanctuary_id, status, members, messages}    │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  [User now sees main chat view]                  │
       │                                                  │
```

### Flow 3: Private Coaching Session
```
┌─────────────┐                                    ┌─────────────┐
│   Flutter   │                                    │   Backend   │
└──────┬──────┘                                    └──────┬──────┘
       │                                                  │
       │  1. [Escalation detected in chat]                │
       │                                                  │
       │  2. sanctuary_coaching_offer                     │
       │     {intervention_id, is_free, cost, message}    │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  [User sees coaching offer modal]                │
       │                                                  │
       │  3. sanctuary_coaching_accept                    │
       │     {sanctuary_id, intervention_id}              │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  4. sanctuary_coaching_started                   │
       │     {coaching_session, message}                  │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  [User enters private coaching UI]               │
       │  [Other members see "stepped away" + pause]      │
       │                                                  │
       │  5. sanctuary_member_coaching                    │
       │     {member_name, message}                       │
       │ ◄───────── (to OTHER members) ────────────────  │
       │                                                  │
       │  6. sanctuary_coaching_message                   │
       │     {sanctuary_id, message}                      │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  7. sanctuary_coaching_response                  │
       │     {coaching_message, attempts_remaining}       │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  [Repeat 6-7 up to 5 times]                      │
       │                                                  │
       │  8. sanctuary_coaching_limit_reached             │
       │     {options: extend, assisted, return}          │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ OPTION A: Extend ($5)                     │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  9a. sanctuary_coaching_extend                   │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  10a. sanctuary_coaching_extended                │
       │       {new_max_steps: 10, charge_amount: 5.00}   │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ OPTION B: Assisted Response ($3)          │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  9b. sanctuary_request_assisted_response         │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  10b. sanctuary_assisted_response_generated      │
       │       {assisted_response, explanation}           │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ OPTION C: Return to Sanctuary             │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  9c. sanctuary_coaching_complete                 │
       │      {request_assisted_response: false}          │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  10c. sanctuary_coaching_completed               │
       │       {sanctuary_resumed, others_in_coaching}    │
       │ ◄─────────────────────────────────────────────  │
       │                                                  │
       │  11. sanctuary_resumed (if all back)             │
       │ ◄───────── (to ALL members) ──────────────────  │
       │                                                  │
```

### Flow 4: Complete Sanctuary (Creator Only)
```
┌─────────────┐                                    ┌─────────────┐
│   Flutter   │                                    │   Backend   │
└──────┬──────┘                                    └──────┬──────┘
       │                                                  │
       │  [Creator selects "Complete Session" from menu]  │
       │                                                  │
       │  1. sanctuary_complete                           │
       │     {sanctuary_id}                               │
       │ ─────────────────────────────────────────────►  │
       │                                                  │
       │  ┌──────────────────────────────────────────┐   │
       │  │ Backend checks: is sender creator/HEAD?   │   │
       │  │ If NO → error response                    │   │
       │  │ If YES → continue                         │   │
       │  └──────────────────────────────────────────┘   │
       │                                                  │
       │  2. sanctuary_generating_summary                 │
       │     {message: "Generating summary..."}           │
       │ ◄───────── (to ALL members) ──────────────────  │
       │                                                  │
       │  [Backend generates AI summary via Azure]        │
       │  [Backend updates story.json for each member]    │
       │  [Backend saves to sanctuary_history]            │
       │                                                  │
       │  3. sanctuary_summary                            │
       │     {summary, session_stats, member_insights}    │
       │ ◄───────── (personalized per member) ─────────  │
       │                                                  │
       │  [Members see Session Summary overlay]           │
       │                                                  │
```

---

## 💰 BILLING SUMMARY

| Action | Cost | When Charged | Who Pays |
|--------|------|--------------|----------|
| Create Sanctuary | $20.00 | `sanctuary_created` | Head of Household |
| First Coaching (per member) | **FREE** | `sanctuary_coaching_accept` | - |
| Subsequent Coaching | **$5.00** | `sanctuary_coaching_accept` (if `free_used`) | Head of Household |
| Coaching Extension (+5 steps) | **$5.00** | `sanctuary_coaching_extend` | Head of Household |
| Assisted Response | **$3.00** | `sanctuary_request_assisted_response` | Head of Household |
| Entry Questions | FREE | - | - |
| Session Summary | FREE | - | - |

---

## 🔐 PERMISSIONS & ROLES

### Family Roles
| Role | Can Create | Can Join | Can Message | Can Coach | Can Complete |
|------|------------|----------|-------------|-----------|--------------|
| HEAD | ✅ | ✅ | ✅ | ✅ | ✅ |
| MEMBER | ✅ (needs approval*) | ✅ | ✅ | ✅ | ❌ |

*When a MEMBER creates a sanctuary, HEAD receives approval request on join.

### User Profile Fields
```json
{
  "hardware_id": "CLIENT_001",
  "family_id": "FAM_1834DACF",
  "family_role": "HEAD",  // or "MEMBER"
  "subscription_plan": "TOP_TIER",
  "assigned_coach": "coach1"
}
```

---

## 📱 LIFECYCLE HANDLING (Mobile)

### App Background/Resume
```dart
@override
void didChangeAppLifecycleState(AppLifecycleState state) {
  if (state == AppLifecycleState.resumed) {
    // App came to foreground
    _reconnectIfNeeded();
  } else if (state == AppLifecycleState.paused) {
    // App going to background
    print('>>> SANCTUARY: App paused, connection may drop');
  }
}

void _reconnectIfNeeded() {
  if (_channel == null) {
    _connectToServer();  // Full reconnect
  } else {
    // Send ping to verify connection
    _channel?.sink.add(json.encode({"type": "ping"}));
  }
}
```

---

## 🧪 TEST ACCOUNTS

| Username | Password | Role | Family Role | Family ID |
|----------|----------|------|-------------|-----------|
| `client1` | `test123` | CLIENT (John D.) | **HEAD** | FAM_1834DACF |
| `client1b` | `test123` | CLIENT (Jane D.) | MEMBER | FAM_1834DACF |
| `coach1` | `test123` | COACH (Coach Hope) | - | - |

---

## 📁 FILE REFERENCES

### Flutter (Dart)
| File | Location | Purpose |
|------|----------|---------|
| `main.dart` | `mobile/lib/` | All screens, WebSocket handlers, UI components |
| `pubspec.yaml` | `mobile/` | Dependencies (web_socket_channel, speech_to_text, etc.) |

### Backend (Python)
| File | Location | Purpose |
|------|----------|---------|
| `bridge_server.py` | `backend/app/websocket/` | Main WebSocket handler |
| `sanctuary_engine.py` | `backend/app/websocket/` | Sanctuary state management |
| `stripe_billing.py` | `backend/app/websocket/` | Payment processing |
| `user_registry.json` | `backend/app/websocket/data/` | User accounts & profiles |

### Data Storage
| Path | Purpose |
|------|---------|
| `data/sanctuary_history/{id}.json` | Completed session archives |
| `data/sanctuary_engine_data.json` | Active sanctuary state |
| `data/Vaults/Clients/{id}/story.json` | Client relational context |

---

## ✅ FEATURE STATUS

### Core Features
- [x] Login/Authentication
- [x] Neural Interface (1:1 chat)
- [x] Family Sanctuary (group chat)
- [x] Private Coaching (5-step limit)
- [x] Coaching Extension ($5)
- [x] Assisted Response ($3)
- [x] Entry Questions
- [x] Session Summary with AI insights
- [x] Auto-story extraction
- [x] Relational context in AI responses
- [x] App lifecycle handling (reconnect)
- [x] Creator-only session completion
- [x] Family role permissions (HEAD/MEMBER)

### Accessibility
- [x] Speech-to-text input
- [x] Large touch targets
- [ ] Screen reader support
- [ ] High contrast mode

### Pending
- [ ] Push notifications
- [ ] Offline message queue
- [ ] 7-day coach check-in
- [ ] Nevedal coherence tracking in UI
- [ ] Night School client wisdom integration

---

**Document Version:** 1.0  
**Last Updated:** January 29, 2026  
**Author:** Clinical Sovereignty Lab Development Team
