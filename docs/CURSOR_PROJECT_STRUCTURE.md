# Little Nate — Project Structure for Cursor
## Optimized for Multi-File Navigation & AI-Assisted Development

---

## 📁 SERVER STRUCTURE (Python)

```
server/
├── main.py                      # Entry point - starts WebSocket server
├── config.py                    # Environment, constants, feature flags
├── requirements.txt             # Dependencies
│
├── core/
│   ├── __init__.py
│   ├── websocket_gateway.py     # Connection management, message routing
│   ├── database.py              # PostgreSQL pool, queries
│   ├── cache.py                 # Redis connection, caching helpers
│   └── auth.py                  # JWT, password hashing, session management
│
├── models/
│   ├── __init__.py
│   ├── user.py                  # User, UserProfile, UserRole
│   ├── session.py               # Session, SessionType, Message
│   ├── nevedal.py               # NevedalState, CEEEvent, BiometricSample
│   ├── coach.py                 # CoachProfile, Assignment, Schedule
│   ├── wisdom.py                # WisdomEntry, CoachNote, WisdomVersion
│   └── audit.py                 # AuditLogEntry
│
├── services/
│   ├── __init__.py
│   ├── auth_service.py          # Login, register, token refresh
│   ├── session_service.py       # Start/end session, messages, AI relay
│   ├── nevedal_service.py       # Biometric processing, CEE detection
│   ├── coach_service.py         # Dashboard, clients, notes, schedule
│   ├── night_school_service.py  # Wisdom, Dojo, PII detection
│   └── admin_service.py         # Stats, crisis watchlist, audit
│
├── nevedal/
│   ├── __init__.py
│   ├── engine.py                # ← FROM nevedal_engine.py (core computation)
│   ├── voice_extractor.py       # Voice biometric extraction
│   └── constants.py             # Tunable parameters
│
├── night_school/
│   ├── __init__.py
│   ├── director.py              # ← FROM night_school_director.py
│   ├── pii_detector.py          # PII detection & redaction
│   └── dojo.py                  # Adversarial testing
│
└── integrations/
    ├── __init__.py
    ├── azure_openai.py          # Azure realtime API
    └── hippocampus.py           # Memory ledger system
```

---

## 📁 CLIENT STRUCTURE (Flutter/Dart)

```
lib/
├── main.dart                    # Entry point
├── app.dart                     # MaterialApp, theme, routes
│
├── core/
│   ├── constants.dart           # Colors, dimensions, strings
│   ├── theme.dart               # ThemeData
│   ├── routes.dart              # Named routes
│   └── providers.dart           # Riverpod providers setup
│
├── data/
│   ├── datasources/
│   │   ├── websocket_client.dart    # Single WS connection
│   │   ├── local_storage.dart       # Hive/SharedPrefs
│   │   └── secure_storage.dart      # FlutterSecureStorage
│   │
│   ├── repositories/
│   │   ├── auth_repository.dart
│   │   ├── session_repository.dart
│   │   ├── nevedal_repository.dart
│   │   ├── coach_repository.dart
│   │   └── user_repository.dart
│   │
│   └── models/
│       ├── user.dart
│       ├── session.dart
│       ├── message.dart
│       ├── nevedal_state.dart
│       ├── coach_client.dart
│       └── family.dart
│
├── domain/
│   ├── hardware_identity.dart   # ← FROM main_hybrid.dart (as-is)
│   ├── vagus_engine.dart        # ← FROM main_hybrid.dart (as-is)
│   └── voice_biometrics.dart    # ← FROM nevedal_flutter.dart
│
├── presentation/
│   ├── viewmodels/
│   │   ├── auth_viewmodel.dart
│   │   ├── session_viewmodel.dart
│   │   ├── nevedal_viewmodel.dart
│   │   ├── coach_viewmodel.dart
│   │   └── admin_viewmodel.dart
│   │
│   ├── screens/
│   │   ├── auth/
│   │   │   ├── lobby_screen.dart
│   │   │   ├── login_dialog.dart
│   │   │   └── signup_wizard.dart
│   │   │
│   │   ├── client/
│   │   │   ├── chat_screen.dart
│   │   │   └── session_summary.dart
│   │   │
│   │   ├── coach/
│   │   │   ├── coach_dashboard.dart
│   │   │   ├── client_detail.dart
│   │   │   ├── session_notes.dart
│   │   │   ├── calendar_view.dart
│   │   │   └── ask_nate_dialog.dart
│   │   │
│   │   └── admin/
│   │       └── admin_console.dart
│   │
│   └── widgets/
│       ├── common/
│       │   ├── loading_indicator.dart
│       │   ├── error_dialog.dart
│       │   └── connection_status.dart
│       │
│       ├── visual_persona/
│       │   ├── visual_persona.dart      # ← FROM main_hybrid.dart (as-is)
│       │   └── nervous_system_painter.dart
│       │
│       ├── nevedal/
│       │   ├── nevedal_indicator.dart
│       │   ├── nevedal_dashboard.dart
│       │   └── cee_notification.dart
│       │
│       └── coach/
│           ├── client_card.dart
│           ├── schedule_tile.dart
│           └── quick_actions.dart
│
└── utils/
    ├── extensions.dart
    ├── validators.dart
    └── formatters.dart
```

---

## 📋 FILE MIGRATION MAP

Use this checklist when moving code in Cursor:

### Server Migration

| Source File | Target Location | What to Extract |
|-------------|-----------------|-----------------|
| `bridge_server_hybrid.py` | `core/websocket_gateway.py` | WebSocket handler loop |
| `bridge_server_hybrid.py` | `services/session_service.py` | `handle_nate_query`, `handle_login` |
| `bridge_server_hybrid.py` | `integrations/hippocampus.py` | `Hippocampus` class |
| `bridge_server_hybrid.py` | `integrations/azure_openai.py` | `AzureLobe` class |
| `nevedal_engine.py` | `nevedal/engine.py` | Entire file (as-is) |
| `nevedal_engine.py` | `nevedal/voice_extractor.py` | `VoiceBiometricExtractor` class |
| `nevedal_handlers.py` | `services/nevedal_service.py` | Handler methods |
| `night_school_director.py` | `night_school/director.py` | `NightSchoolDirector` class |
| `night_school_director.py` | `night_school/pii_detector.py` | `PIIDetector` class |
| `night_school_director.py` | `night_school/dojo.py` | Dojo-related classes |
| `night_school_handlers.py` | `services/night_school_service.py` | Handler methods |
| `api_server.py` | `models/*.py` | Pydantic models |
| `bridge_handlers_v2.py` | `services/coach_service.py` | Coach handlers |

### Client Migration

| Source File | Target Location | What to Extract |
|-------------|-----------------|-----------------|
| `main_hybrid.dart` | `domain/hardware_identity.dart` | `HardwareIdentity` class |
| `main_hybrid.dart` | `domain/vagus_engine.dart` | `VagusEngine` class |
| `main_hybrid.dart` | `presentation/widgets/visual_persona/` | `VisualPersona`, `NervousSystemPainter` |
| `main_hybrid.dart` | `presentation/screens/auth/lobby_screen.dart` | `LobbyScreen` |
| `main_hybrid.dart` | `presentation/screens/auth/signup_wizard.dart` | `SignUpWizard` |
| `main_hybrid.dart` | `presentation/screens/client/chat_screen.dart` | `NeuralInterface` → `ChatScreen` |
| `coach_portal_v2_complete.dart` | `presentation/screens/coach/` | All coach screens |
| `nevedal_flutter.dart` | `data/models/nevedal_state.dart` | `NevedalState` model |
| `nevedal_flutter.dart` | `domain/voice_biometrics.dart` | `VoiceBiometricExtractor` |
| `nevedal_flutter.dart` | `presentation/widgets/nevedal/` | Nevedal widgets |

---

## 🔧 CURSOR WORKFLOW

### Step 1: Create Structure
```bash
# In terminal, create all folders first
mkdir -p server/{core,models,services,nevedal,night_school,integrations}
mkdir -p lib/{core,data/{datasources,repositories,models},domain,presentation/{viewmodels,screens/{auth,client,coach,admin},widgets/{common,visual_persona,nevedal,coach}},utils}
```

### Step 2: Extract Classes
In Cursor, select a class and use:
- `Cmd+Shift+P` → "Move to new file"
- Or manually cut/paste with Cursor's multi-file awareness

### Step 3: Fix Imports
Cursor will highlight broken imports. Use:
- `Cmd+.` → "Add import"
- Or let Cursor AI suggest fixes

### Step 4: Create Barrel Files
Each folder gets an `index.dart` or `__init__.py`:

```dart
// lib/data/models/index.dart
export 'user.dart';
export 'session.dart';
export 'nevedal_state.dart';
```

```python
# server/services/__init__.py
from .auth_service import AuthService
from .session_service import SessionService
from .nevedal_service import NevedalService
```

---

## 🎯 CURSOR-SPECIFIC TIPS

### 1. Use `.cursorrules` File
Create in project root:
```
# .cursorrules
This is a Flutter + Python WebSocket project.
Architecture: MVVM with Riverpod
State flows: View → ViewModel → Repository → DataSource
Server uses service-based message routing.
Nevedal engine computes quantum emotional coherence.
```

### 2. Reference Files in Prompts
```
@nevedal_engine.py extract the NevedalEngine class 
and create nevedal/engine.py with proper imports
```

### 3. Multi-File Edits
```
Update all files in services/ to use the new 
DatabasePool from core/database.py
```

### 4. Architecture Validation
```
Check if presentation/screens/coach/coach_dashboard.dart 
follows MVVM - it should only call ViewModel methods, 
never Repository directly
```

---

## ✅ INTEGRATION CHECKLIST FOR CURSOR

### Server
- [ ] Create folder structure
- [ ] Move `NevedalEngine` → `nevedal/engine.py`
- [ ] Move `PIIDetector` → `night_school/pii_detector.py`
- [ ] Move `NightSchoolDirector` → `night_school/director.py`
- [ ] Create `core/websocket_gateway.py` with message router
- [ ] Create services with handler methods
- [ ] Create `main.py` entry point
- [ ] Test: `python main.py`

### Client
- [ ] Create folder structure
- [ ] Move `HardwareIdentity` → `domain/hardware_identity.dart`
- [ ] Move `VagusEngine` → `domain/vagus_engine.dart`
- [ ] Move `VisualPersona` → `widgets/visual_persona/`
- [ ] Create `WebSocketClient` in `datasources/`
- [ ] Create Repositories
- [ ] Create ViewModels
- [ ] Refactor screens to use ViewModels
- [ ] Test: `flutter run`

---

This structure lets Cursor's AI understand your project holistically and assist with cross-file refactoring.
