# FAMILY SANCTUARY - COMPLETE UX FLOW TREE V3.0
## WebSocket Protocol & Code Reference Guide

**Last Updated:** January 29, 2026  
**Version:** 3.0 (Post-Testing Complete)  
**Status:** ✅ All Features Tested & Working

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

### Key Code Locations in `main.dart`
| Handler | Search Pattern |
|---------|---------------|
| WebSocket Message Switch | `switch (type) {` in `_handleSanctuaryMessage` |
| Coaching UI | `Widget _buildPrivateCoachingUI()` |
| Pause Screen | `Widget _buildPausedOverlay()` |
| Coaching Offer Modal | `void _showCoachingOfferModal()` |
| Coaching Limit Dialog | `void _showCoachingLimitDialog()` |

---

## 🔄 WEBSOCKET MESSAGE TYPES (27 Total)

### Client → Server (12 messages)
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

### Server → Client (15 messages)
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

---

## 🌳 COMPLETE FLOW TREE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FAMILY SANCTUARY ENTRY                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  sanctuary_get_or_create      │
                    │  (Client → Server)            │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ No existing       │           │ Existing sanctuary │
        │ sanctuary         │           │ found              │
        └───────────────────┘           └───────────────────┘
                    │                               │
                    ▼                               │
        ┌───────────────────┐           ┌──────────┴──────────┐
        │ sanctuary_created │           │                     │
        │ ($20 base fee)    │           │   Check member      │
        └───────────────────┘           │   status            │
                                        │                     │
                              ┌─────────┼─────────┬───────────┤
                              │         │         │           │
                              ▼         ▼         ▼           ▼
                         JOINED    RECONNECTED  RETURNED   REFRESHED
                         (new)     (refresh)    (after     (same as
                                               exit)       reconnected)
                              │         │         │           │
                              ▼         ▼         ▼           ▼
                    sanctuary_  sanctuary_  sanctuary_  sanctuary_
                    joined      reconnected rejoined    reconnected
                    (+messages) (+messages) (+messages) (+messages)
                              │         │         │           │
                              └─────────┴────┬────┴───────────┘
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    │           CHECK: Is coaching active?            │
                    │           (sanctuary.status == 'COACHING_ACTIVE')│
                    └────────────────────────────────────────────────┘
                                             │
                         ┌───────────────────┴───────────────────┐
                         │                                       │
                         ▼                                       ▼
            ┌────────────────────────┐             ┌────────────────────────┐
            │ YES - Someone in       │             │ NO - Normal sanctuary  │
            │ coaching               │             │                        │
            └────────────────────────┘             └────────────────────────┘
                         │                                       │
        ┌────────────────┴────────────────┐                      ▼
        │                                 │         ┌────────────────────────┐
        ▼                                 ▼         │ MAIN SANCTUARY CHAT    │
┌───────────────────┐         ┌───────────────────┐ │ (see CHAT FLOW below)  │
│ Am I the one in   │         │ Someone ELSE is   │ └────────────────────────┘
│ coaching?         │         │ in coaching       │
└───────────────────┘         └───────────────────┘
        │                                 │
        ▼                                 ▼
sanctuary_coaching_         sanctuary_coaching_offer
resumed                     (popup: Accept/Decline)
(resume my session)                   │
        │                     ┌───────┴───────┐
        ▼                     │               │
┌───────────────────┐   ACCEPT           DECLINE
│ PRIVATE COACHING  │         │               │
│ (see flow below)  │         ▼               ▼
└───────────────────┘   sanctuary_      sanctuary_
                        coaching_       member_coaching
                        started         (PAUSE SCREEN)
                              │
                              ▼
                    ┌───────────────────┐
                    │ PRIVATE COACHING  │
                    │ (see flow below)  │
                    └───────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                           MAIN SANCTUARY CHAT                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  User types message           │
                    │  sanctuary_message            │
                    │  (Client → Server)            │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Little Nate AI Analysis      │
                    │  (Escalation Detection)       │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ No escalation     │           │ ESCALATION        │
        │ detected          │           │ DETECTED          │
        └───────────────────┘           └───────────────────┘
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ Broadcast message │           │ sanctuary_message │
        │ to all members    │           │ (broadcast)       │
        │ sanctuary_message │           │         +         │
        └───────────────────┘           │ Little Nate reply │
                                        │ sanctuary_message │
                                        │         +         │
                                        │ COACHING OFFER    │
                                        │ to ALL members    │
                                        └───────────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │ sanctuary_coaching_offer  │
                                    │ (sent to each member)     │
                                    │                           │
                                    │ • is_free: true/false     │
                                    │ • cost: $0 or $5          │
                                    │ • trigger_member: name    │
                                    └───────────────────────────┘
                                                    │
                                        ┌───────────┴───────────┐
                                        │                       │
                                    ACCEPT                  DECLINE
                                        │                       │
                                        ▼                       ▼
                            sanctuary_coaching_    sanctuary_member_coaching
                            started                (PAUSE SCREEN)
                                        │
                                        ▼
                            ┌───────────────────────┐
                            │ PRIVATE COACHING      │
                            └───────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         PRIVATE COACHING FLOW                                │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │  PRIVATE COACHING UI          │
                    │  "This conversation is        │
                    │   confidential"               │
                    │                               │
                    │  Step counter: X/5            │
                    │  (or X/10 if extended)        │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  User sends message           │
                    │  sanctuary_coaching_message   │
                    │  (Client → Server)            │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  Check: attempt_number        │
                    │  > max_steps (default 5)?     │
                    └───────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ NO - Under limit  │           │ YES - Limit       │
        │                   │           │ reached           │
        └───────────────────┘           └───────────────────┘
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────────────┐
        │ OOPS Detection    │           │ sanctuary_coaching_       │
        │ (first msg only)  │           │ limit_reached             │
        │                   │           │                           │
        │ Keywords: "oops", │           │ Shows dialog:             │
        │ "wrong", "back",  │           │ • Return to Family (free) │
        │ "exit", "leave"   │           │ • Get Help + Return ($3)  │
        └───────────────────┘           │ • Continue Coaching ($5)  │
                    │                   └───────────────────────────┘
        ┌───────────┴───────────┐                   │
        │                       │       ┌───────────┼───────────┐
        ▼                       ▼       │           │           │
    OOPS DETECTED         NO OOPS   RETURN     GET HELP    CONTINUE
        │                       │       │       (+$3)       (+$5)
        ▼                       │       │           │           │
    End coaching                │       │           ▼           ▼
    immediately                 │       │   sanctuary_     sanctuary_
    sanctuary_coaching_         │       │   request_       coaching_
    completed                   │       │   assisted_      extend
        │                       │       │   response           │
        ▼                       │       │       │              ▼
    Return to                   │       │       ▼         sanctuary_
    sanctuary                   │       │   sanctuary_    coaching_
                                │       │   assisted_     extended
                                │       │   response_     (max=10)
                                │       │   generated         │
                                │       │       │              │
                                │       │       ▼              │
                                │       │   Display in         │
                                │       │   coaching UI        │
                                │       │       │              │
                                │       └───────┴──────────────┘
                                │               │
                                ▼               │
                    ┌───────────────────┐       │
                    │ Process message   │◄──────┘
                    │ with Little Nate  │
                    │ AI                │
                    └───────────────────┘
                                │
                                ▼
                    ┌───────────────────────────────┐
                    │ sanctuary_coaching_response   │
                    │ (Server → Client)             │
                    │                               │
                    │ • coaching_message            │
                    │ • attempt_number              │
                    │ • is_deescalated              │
                    │ • attempts_remaining          │
                    │ • offer_assisted_response?    │
                    └───────────────────────────────┘
                                │
                                ▼
                    ┌───────────────────────────────┐
                    │  User can:                    │
                    │  • Send another message       │
                    │  • Click "Get Help (+$3)"     │
                    │  • Click "Return to Sanctuary"│
                    └───────────────────────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            │                   │                   │
            ▼                   ▼                   ▼
    ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
    │ Send message  │   │ Get Help      │   │ Return to     │
    │ (loop back)   │   │ (+$3)         │   │ Sanctuary     │
    └───────────────┘   └───────────────┘   └───────────────┘
                                │                   │
                                ▼                   │
                        sanctuary_request_          │
                        assisted_response           │
                                │                   │
                                ▼                   │
                        sanctuary_assisted_         │
                        response_generated          │
                        (shows in UI)               │
                                │                   │
                                └───────────────────┤
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │ sanctuary_coaching_       │
                                    │ complete                  │
                                    │ (Client → Server)         │
                                    └───────────────────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │ Backend:                  │
                                    │ • Ends coaching session   │
                                    │ • Updates member status   │
                                    │ • Checks if all done      │
                                    └───────────────────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │ sanctuary_coaching_       │
                                    │ completed                 │
                                    │ (Server → Client)         │
                                    │                           │
                                    │ + sanctuary_member_       │
                                    │   returned (broadcast)    │
                                    └───────────────────────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │ All coaching done?        │
                                    └───────────────────────────┘
                                                    │
                                    ┌───────────────┴───────────┐
                                    │                           │
                                    ▼                           ▼
                            ┌───────────────┐           ┌───────────────┐
                            │ YES           │           │ NO            │
                            │               │           │               │
                            │ sanctuary_    │           │ Others still  │
                            │ resumed       │           │ in coaching   │
                            │ (broadcast)   │           │               │
                            └───────────────┘           └───────────────┘
                                    │
                                    ▼
                            ┌───────────────────┐
                            │ ALL MEMBERS       │
                            │ return to main    │
                            │ sanctuary chat    │
                            │                   │
                            │ Pause screens     │
                            │ auto-dismiss      │
                            └───────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                              EXIT FLOW                                       │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │  User clicks Exit (X)         │
                    │  or back button               │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  sanctuary_exit               │
                    │  (Client → Server)            │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  sanctuary_exit_checkin       │
                    │  (Server → Client)            │
                    │                               │
                    │  "Hi [Name], I notice you     │
                    │   want to leave..."           │
                    │                               │
                    │  • Are you feeling unsafe?    │
                    │  • Is this too much?          │
                    │  • Do you need a break?       │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  EXIT DIALOG                  │
                    │                               │
                    │  [How are you feeling?]       │
                    │  ☑ Let family know I'm        │
                    │    taking a break             │
                    │                               │
                    │  [Stay]        [Exit]         │
                    └───────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        │                       │
                    STAY                      EXIT
                        │                       │
                        ▼                       ▼
                    (dismiss)           sanctuary_exit_confirm
                                        (Client → Server)
                                        {reason, inform_family}
                                                │
                                                ▼
                                        sanctuary_exited
                                        (Server → Client)
                                                │
                                                ▼
                                        ┌───────────────────┐
                                        │ If inform_family: │
                                        │ Broadcast:        │
                                        │ sanctuary_member_ │
                                        │ exited            │
                                        │                   │
                                        │ "[Name] is taking │
                                        │  a break..."      │
                                        └───────────────────┘
                                                │
                                                ▼
                                        ┌───────────────────┐
                                        │ Navigate back     │
                                        │ to lobby          │
                                        └───────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         PAUSE SCREEN FLOW                                    │
└─────────────────────────────────────────────────────────────────────────────┘

                    ┌───────────────────────────────┐
                    │  PAUSE SCREEN                 │
                    │  (shown when another member   │
                    │   is in coaching)             │
                    │                               │
                    │  ┌─────────────────────────┐  │
                    │  │    ⏸️ Sanctuary Paused  │  │
                    │  │                         │  │
                    │  │  [Name] is receiving    │  │
                    │  │  private support from   │  │
                    │  │  Little Nate.           │  │
                    │  │                         │  │
                    │  │  💙 Take this moment    │  │
                    │  │     to breathe          │  │
                    │  └─────────────────────────┘  │
                    └───────────────────────────────┘
                                    │
                                    │
                    Automatically dismissed when:
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐
        │ sanctuary_resumed │           │ User exits and    │
        │ received          │           │ re-enters         │
        │                   │           │                   │
        │ (All coaching     │           │ (Gets fresh       │
        │  complete)        │           │  state check)     │
        └───────────────────┘           └───────────────────┘
```

---

## 💰 BILLING SUMMARY

| Action | Cost | When Charged |
|--------|------|--------------|
| Create Sanctuary | $20.00 | `sanctuary_created` |
| First Coaching (per member) | FREE | `sanctuary_coaching_accept` |
| Subsequent Coaching | $5.00 | `sanctuary_coaching_accept` (if `free_coaching_used=true`) |
| Assisted Response | $3.00 | `sanctuary_request_assisted_response` |
| Coaching Extension | $5.00 | `sanctuary_coaching_extend` |

**Billing charged to:** Head of Household's Stripe account

---

## 🔧 STATE VARIABLES (Flutter)

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
DateTime? _lastResumedAt;  // For stale message filtering
```

---

## ✅ TESTED & VERIFIED FEATURES

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

---

## 🐛 KNOWN EDGE CASES (Handled)

1. **Stale `sanctuary_member_coaching` after resume**
   - Fix: 2-second ignore window after `sanctuary_resumed`
   
2. **Null member data in `sanctuary_member_returned`**
   - Fix: Null-safe parsing with fallback to `member_name` or `message`

3. **Coaching offer to member already in coaching**
   - Fix: Backend skips members with `status='IN_COACHING'`

4. **Message history lost on return**
   - Fix: Backend includes `messages` array in `sanctuary_rejoined`

---

## 📝 CHANGELOG

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
