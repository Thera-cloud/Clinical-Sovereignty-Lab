# Little Nate — MVVM Integration Architecture
## Complete Refactoring & Assembly Guide

**Version:** 3.0  
**Date:** January 21, 2026  
**Status:** Architecture Specification

---

## 🎯 OBJECTIVE

Consolidate all platform components into:
1. **ONE unified `bridge_server.py`** (~2,500 lines) - Python backend
2. **ONE unified `main.dart`** (~4,000 lines) - Flutter frontend with MVVM

Using proper:
- MVVM (Model-View-ViewModel) architecture
- Clean state management (Riverpod)
- Single WebSocket connection with message routing
- Microservice-ready internal structure
- Mobile-optimized data flow

---

## 📐 ARCHITECTURE OVERVIEW

### Client-Side (Flutter/Dart)

```
┌─────────────────────────────────────────────────────────────┐
│                         VIEWS                                │
│  LobbyScreen │ ChatScreen │ CoachDashboard │ AdminConsole   │
└──────────────────────────┬──────────────────────────────────┘
                           │ watches
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      VIEWMODELS                              │
│  AuthViewModel │ SessionViewModel │ NevedalViewModel │ ...  │
│                                                              │
│  • Extend ChangeNotifier (or use Riverpod StateNotifier)    │
│  • NO direct API calls - only through Repository            │
│  • Transform data for View consumption                       │
│  • Handle UI state (loading, error, success)                │
└──────────────────────────┬──────────────────────────────────┘
                           │ calls
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      REPOSITORIES                            │
│  AuthRepository │ SessionRepository │ NevedalRepository     │
│                                                              │
│  • Abstract data sources (WebSocket vs REST vs Cache)       │
│  • Single source of truth                                    │
│  • Handle offline/retry logic                                │
└──────────────────────────┬──────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                             │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ WebSocketClient │  │  RestClient  │  │  LocalCache   │  │
│  │  (Single conn)  │  │ (Fallback)   │  │ (Hive/SQLite) │  │
│  └─────────────────┘  └──────────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                        MODELS                                │
│  User │ Session │ NevedalState │ Message │ CoachNote │ ... │
│                                                              │
│  • Immutable data classes (freezed)                         │
│  • JSON serialization                                        │
│  • No business logic                                         │
└─────────────────────────────────────────────────────────────┘
```

### Server-Side (Python)

```
┌─────────────────────────────────────────────────────────────┐
│                    WEBSOCKET GATEWAY                         │
│  • Single entry point                                        │
│  • Connection management                                     │
│  • Authentication middleware                                 │
│  • Rate limiting                                             │
│  • Message routing by type prefix                           │
└──────────────────────────┬──────────────────────────────────┘
                           │ routes to
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    SERVICE LAYER                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ AuthSvc  │ │SessionSvc│ │NevedalSvc│ │ CoachSvc │       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
│       │            │            │            │              │
│  • Business logic lives here                                │
│  • Services can call other services                         │
│  • Async/await throughout                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATA ACCESS LAYER                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ PostgreSQL   │  │    Redis     │  │  File Vault  │      │
│  │  (Primary)   │  │   (Cache)    │  │  (Legacy)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## ✅ INTEGRATION CHECKLIST

### Phase 1: Foundation (Day 1-2)

#### 1.1 Server Foundation
- [ ] Create unified `bridge_server.py` with:
  - [ ] Single WebSocket endpoint on port 8765
  - [ ] Connection registry with metadata
  - [ ] Message router with type-based dispatch
  - [ ] Authentication middleware
  - [ ] Graceful shutdown handling

```python
# Message routing pattern
MESSAGE_HANDLERS = {
    "auth.": AuthService,
    "session.": SessionService,
    "nevedal.": NevedalService,
    "coach.": CoachService,
    "admin.": AdminService,
    "night_school.": NightSchoolService,
}

async def route_message(ws, msg_type, data, context):
    for prefix, service in MESSAGE_HANDLERS.items():
        if msg_type.startswith(prefix):
            handler = getattr(service, f"handle_{msg_type.replace(prefix, '')}", None)
            if handler:
                return await handler(ws, data, context)
    raise UnknownMessageType(msg_type)
```

#### 1.2 Client Foundation
- [ ] Create unified `main.dart` with:
  - [ ] Single WebSocketClient class
  - [ ] Message stream with type filtering
  - [ ] Auto-reconnect with exponential backoff
  - [ ] Connection state management

```dart
// WebSocket message routing pattern
class WebSocketClient {
  final _messageController = StreamController<Map<String, dynamic>>.broadcast();
  
  Stream<T> messagesOfType<T>(String type, T Function(Map<String, dynamic>) fromJson) {
    return _messageController.stream
        .where((msg) => msg['type'] == type)
        .map((msg) => fromJson(msg['data']));
  }
}
```

---

### Phase 2: Models & Data Layer (Day 2-3)

#### 2.1 Dart Models
- [ ] Create `models/` directory with:
  - [ ] `user.dart` - User, UserProfile, UserRole
  - [ ] `session.dart` - Session, SessionType, SessionState
  - [ ] `nevedal.dart` - NevedalState, CEEEvent, BiometricSample
  - [ ] `coach.dart` - CoachProfile, CoachNote, Assignment
  - [ ] `message.dart` - ChatMessage, MessageType
  - [ ] `family.dart` - Family, FamilyMember, Relationship

```dart
// Example model with freezed
@freezed
class NevedalState with _$NevedalState {
  const factory NevedalState({
    required double cEmo,
    required double pEnt,
    required double tTunnel,
    required double gammaEnv,
    required double eGJoint,
    required double tauEmo,
    required bool ceeWindow,
    required int ceeDuration,
    String? interpretation,
    List<String>? recommendations,
  }) = _NevedalState;
  
  factory NevedalState.fromJson(Map<String, dynamic> json) => 
      _$NevedalStateFromJson(json);
}
```

#### 2.2 Python Models
- [ ] Create `models/` module with:
  - [ ] Pydantic models for all entities
  - [ ] Database ORM models (SQLAlchemy or raw)
  - [ ] Validation rules

---

### Phase 3: Repository Layer (Day 3-4)

#### 3.1 Dart Repositories
- [ ] Create `repositories/` directory:

```dart
// Base repository pattern
abstract class BaseRepository<T> {
  final WebSocketClient _ws;
  final LocalCache _cache;
  
  Future<T> get(String id);
  Future<List<T>> getAll();
  Future<T> create(T entity);
  Future<T> update(T entity);
  Future<void> delete(String id);
  
  // Real-time stream
  Stream<T> watch(String id);
}

// Concrete implementation
class NevedalRepository extends BaseRepository<NevedalState> {
  Stream<NevedalState> watchState(String sessionId) {
    return _ws.messagesOfType('nevedal.state', NevedalState.fromJson)
        .where((state) => state.sessionId == sessionId);
  }
  
  Future<void> sendBiometrics(BiometricPayload payload) async {
    await _ws.send('nevedal.biometrics', payload.toJson());
  }
}
```

- [ ] Implement repositories:
  - [ ] `AuthRepository` - login, register, token refresh
  - [ ] `SessionRepository` - start, end, messages
  - [ ] `NevedalRepository` - biometrics, state stream
  - [ ] `CoachRepository` - clients, notes, schedule
  - [ ] `UserRepository` - profile, settings, family

---

### Phase 4: ViewModel Layer (Day 4-5)

#### 4.1 State Management Setup
- [ ] Configure Riverpod providers:

```dart
// Provider setup
final authViewModelProvider = ChangeNotifierProvider<AuthViewModel>(
  (ref) => AuthViewModel(ref.read(authRepositoryProvider)),
);

final sessionViewModelProvider = ChangeNotifierProvider.family<SessionViewModel, String>(
  (ref, sessionId) => SessionViewModel(
    ref.read(sessionRepositoryProvider),
    ref.read(nevedalRepositoryProvider),
    sessionId,
  ),
);
```

#### 4.2 ViewModels
- [ ] Create `viewmodels/` directory:

```dart
// Example ViewModel
class SessionViewModel extends ChangeNotifier {
  final SessionRepository _sessionRepo;
  final NevedalRepository _nevedalRepo;
  final String sessionId;
  
  // State
  SessionState _state = SessionState.initial;
  NevedalState? _nevedalState;
  List<ChatMessage> _messages = [];
  bool _isLoading = false;
  String? _error;
  
  // Getters (View reads these)
  SessionState get state => _state;
  NevedalState? get nevedalState => _nevedalState;
  List<ChatMessage> get messages => _messages;
  bool get isLoading => _isLoading;
  String? get error => _error;
  
  // Derived state for View
  Color get coherenceColor => _getCoherenceColor(_nevedalState?.cEmo ?? 0);
  bool get showCEENotification => _nevedalState?.ceeWindow ?? false;
  
  // Commands (View calls these)
  Future<void> startSession() async { ... }
  Future<void> sendMessage(String text) async { ... }
  Future<void> endSession() async { ... }
  
  // Private
  void _subscribeToStreams() {
    _nevedalRepo.watchState(sessionId).listen((state) {
      _nevedalState = state;
      notifyListeners();
    });
  }
}
```

- [ ] Implement ViewModels:
  - [ ] `AuthViewModel` - login state, current user
  - [ ] `SessionViewModel` - active session, messages, Nevedal
  - [ ] `CoachDashboardViewModel` - clients, schedule, notes
  - [ ] `AdminViewModel` - system stats, crisis list, approvals

---

### Phase 5: View Layer (Day 5-7)

#### 5.1 Screen Organization
- [ ] Create `screens/` directory:

```
screens/
├── auth/
│   ├── lobby_screen.dart
│   ├── login_dialog.dart
│   └── signup_wizard.dart
├── session/
│   ├── chat_screen.dart
│   ├── nevedal_overlay.dart
│   └── session_summary.dart
├── coach/
│   ├── coach_dashboard.dart
│   ├── client_detail.dart
│   └── session_notes.dart
├── admin/
│   ├── admin_dashboard.dart
│   ├── user_management.dart
│   └── night_school.dart
└── shared/
    ├── widgets/
    └── dialogs/
```

#### 5.2 View Pattern
```dart
// View only reads ViewModel, never Repository
class ChatScreen extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vm = ref.watch(sessionViewModelProvider(sessionId));
    
    return Scaffold(
      body: Column(
        children: [
          // Nevedal indicator reads derived state
          NevedalIndicator(
            coherence: vm.nevedalState?.cEmo ?? 0,
            color: vm.coherenceColor,
            showCEE: vm.showCEENotification,
          ),
          
          // Messages list
          Expanded(
            child: ListView.builder(
              itemCount: vm.messages.length,
              itemBuilder: (ctx, i) => MessageBubble(vm.messages[i]),
            ),
          ),
          
          // Input calls ViewModel command
          MessageInput(
            onSend: (text) => vm.sendMessage(text),
            enabled: !vm.isLoading,
          ),
        ],
      ),
    );
  }
}
```

---

### Phase 6: Server Services (Day 7-9)

#### 6.1 Service Architecture
- [ ] Create service classes:

```python
# Base service pattern
class BaseService:
    def __init__(self, db_pool, redis, config):
        self.db = db_pool
        self.redis = redis
        self.config = config
    
    async def emit(self, ws, msg_type: str, data: dict):
        await ws.send(json.dumps({"type": msg_type, "data": data}))
    
    async def broadcast(self, msg_type: str, data: dict, filter_fn=None):
        for ws, ctx in connections.items():
            if filter_fn is None or filter_fn(ctx):
                await self.emit(ws, msg_type, data)

# Concrete service
class NevedalService(BaseService):
    def __init__(self, *args):
        super().__init__(*args)
        self.engine = NevedalEngine()
        self.subscribers = defaultdict(set)  # session_id -> {websockets}
    
    async def handle_biometrics(self, ws, data, ctx):
        """Process biometric update and broadcast state"""
        state = self.engine.process_biometrics(
            session_id=data['session_id'],
            user_id=ctx['user_id'],
            biometrics=data['biometrics']
        )
        
        # Store in database
        await self._store_state(state)
        
        # Broadcast to session subscribers
        await self._broadcast_state(data['session_id'], state)
        
        # Check crisis indicators
        await self._check_crisis(ctx['user_id'], state)
        
        return state
    
    async def handle_subscribe(self, ws, data, ctx):
        """Subscribe to session Nevedal stream"""
        session_id = data['session_id']
        self.subscribers[session_id].add(ws)
        
        # Send current state immediately
        current = self.engine.get_current_state(session_id)
        if current:
            await self.emit(ws, 'nevedal.state', current.to_dict())
```

#### 6.2 Service Integration
- [ ] Consolidate into single server:
  - [ ] `AuthService` - from bridge_server_auth.py
  - [ ] `SessionService` - from bridge_server_hybrid.py
  - [ ] `NevedalService` - from nevedal_handlers.py + nevedal_engine.py
  - [ ] `CoachService` - from bridge_handlers_v2.py
  - [ ] `NightSchoolService` - from night_school_handlers.py + night_school_director.py
  - [ ] `AdminService` - new, from admin endpoints

---

### Phase 7: Optimization (Day 9-10)

#### 7.1 Mobile Optimization
- [ ] Implement message batching:
```dart
// Batch biometric updates (don't send every frame)
class BiometricBatcher {
  final Duration interval;
  Timer? _timer;
  BiometricPayload? _pending;
  
  void add(BiometricPayload payload) {
    _pending = payload;
    _timer ??= Timer(interval, _flush);
  }
  
  void _flush() {
    if (_pending != null) {
      _ws.send('nevedal.biometrics', _pending!.toJson());
      _pending = null;
    }
    _timer = null;
  }
}
```

- [ ] Implement connection health monitoring:
```dart
class ConnectionMonitor {
  bool get isOnWifi => _connectivity.isWifi;
  bool get isLowBandwidth => _latency > 500;
  
  // Reduce Nevedal update frequency on slow connections
  Duration get nevedalInterval => isLowBandwidth 
      ? Duration(seconds: 5) 
      : Duration(seconds: 2);
}
```

#### 7.2 Server Optimization
- [ ] Connection pooling:
```python
# Database connection pool
db_pool = await asyncpg.create_pool(
    DATABASE_URL,
    min_size=10,
    max_size=50,
    command_timeout=30
)

# Redis connection pool
redis_pool = aioredis.from_url(
    REDIS_URL,
    max_connections=20
)
```

- [ ] Caching layer:
```python
class CacheService:
    async def get_or_compute(self, key, compute_fn, ttl=300):
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        
        result = await compute_fn()
        await self.redis.setex(key, ttl, json.dumps(result))
        return result
```

#### 7.3 Load Distribution
- [ ] Message priority queues:
```python
# Priority: CRISIS > AUTH > NEVEDAL > CHAT > ADMIN
PRIORITY = {
    'crisis.': 0,
    'auth.': 1,
    'nevedal.': 2,
    'session.': 3,
    'coach.': 4,
    'admin.': 5,
}
```

---

### Phase 8: Testing & Validation (Day 10-11)

#### 8.1 Unit Tests
- [ ] Test all Models (serialization, validation)
- [ ] Test all Repositories (mock WebSocket)
- [ ] Test all ViewModels (state transitions)
- [ ] Test all Services (mock database)

#### 8.2 Integration Tests
- [ ] Full auth flow (register → login → token refresh)
- [ ] Full session flow (start → chat → Nevedal → end)
- [ ] Full coach flow (view clients → session → notes)
- [ ] Full admin flow (dashboard → approve → audit)

#### 8.3 Load Tests
- [ ] 100 concurrent WebSocket connections
- [ ] 50 concurrent Nevedal streams
- [ ] Message throughput (target: 1000 msg/sec)

---

### Phase 9: Final Assembly (Day 11-12)

#### 9.1 File Structure

**Server (Python):**
```
server/
├── bridge_server.py          # Main entry point (~300 lines)
├── services/
│   ├── __init__.py
│   ├── auth_service.py       # ~200 lines
│   ├── session_service.py    # ~300 lines
│   ├── nevedal_service.py    # ~400 lines
│   ├── coach_service.py      # ~300 lines
│   ├── night_school_service.py # ~400 lines
│   └── admin_service.py      # ~200 lines
├── models/
│   ├── __init__.py
│   └── *.py                  # ~500 lines total
├── core/
│   ├── database.py           # ~100 lines
│   ├── cache.py              # ~100 lines
│   └── config.py             # ~50 lines
└── nevedal/
    ├── engine.py             # ~600 lines
    └── voice_extractor.py    # ~200 lines
```

**Client (Dart):**
```
lib/
├── main.dart                 # Entry point (~100 lines)
├── app.dart                  # App configuration (~100 lines)
├── models/
│   └── *.dart                # ~800 lines total
├── repositories/
│   └── *.dart                # ~600 lines total
├── viewmodels/
│   └── *.dart                # ~800 lines total
├── screens/
│   └── *.dart                # ~1500 lines total
├── widgets/
│   └── *.dart                # ~500 lines total
└── core/
    ├── websocket_client.dart # ~200 lines
    ├── local_cache.dart      # ~100 lines
    └── providers.dart        # ~100 lines
```

#### 9.2 Single-File Alternative

If you truly want ONE `bridge_server.py` and ONE `main.dart`:

**bridge_server.py** (~2,500 lines):
```python
# Sections:
# 1. IMPORTS & CONFIG (50 lines)
# 2. MODELS (300 lines)
# 3. DATABASE LAYER (200 lines)
# 4. NEVEDAL ENGINE (600 lines)
# 5. NIGHT SCHOOL DIRECTOR (400 lines)
# 6. SERVICES (800 lines)
# 7. WEBSOCKET GATEWAY (150 lines)
```

**main.dart** (~4,000 lines):
```dart
// Sections:
// 1. IMPORTS & CONFIG (50 lines)
// 2. MODELS (600 lines)
// 3. CORE - WebSocket, Cache (300 lines)
// 4. REPOSITORIES (500 lines)
// 5. VIEWMODELS (700 lines)
// 6. WIDGETS (500 lines)
// 7. SCREENS (1200 lines)
// 8. APP & MAIN (150 lines)
```

---

## 📊 EFFORT ESTIMATE

| Phase | Duration | Lines of Code |
|-------|----------|---------------|
| 1. Foundation | 2 days | ~600 |
| 2. Models | 1 day | ~800 |
| 3. Repositories | 1 day | ~600 |
| 4. ViewModels | 2 days | ~800 |
| 5. Views | 2 days | ~1,500 |
| 6. Services | 2 days | ~1,500 |
| 7. Optimization | 1 day | ~300 |
| 8. Testing | 1 day | ~500 |
| 9. Assembly | 1 day | - |
| **TOTAL** | **~13 days** | **~6,600** |

---

## ⚠️ CRITICAL SUCCESS FACTORS

1. **Single WebSocket Connection**
   - All communication through ONE connection
   - Message types determine routing
   - No REST API calls during active session

2. **Unidirectional Data Flow**
   - View → ViewModel → Repository → Server
   - Server → Repository → ViewModel → View
   - Never View → Repository directly

3. **State Immutability**
   - All Models are immutable
   - ViewModels create new state objects
   - Use `copyWith()` patterns

4. **Separation of Concerns**
   - Views: Only UI rendering
   - ViewModels: UI state + business logic
   - Repositories: Data access abstraction
   - Services: Server-side business logic

5. **Mobile-First Optimization**
   - Batch updates (biometrics every 2s, not 60fps)
   - Lazy loading (load clients on scroll)
   - Offline support (queue messages when disconnected)
   - Memory management (dispose streams properly)

---

## 🚀 READY TO PROCEED?

If you want me to execute this integration:

1. I will create the **unified bridge_server.py** with proper service architecture
2. I will create the **unified main.dart** with MVVM + Riverpod
3. Both will be production-ready, not prototypes
4. Estimated: 2-3 sessions of focused work

**Say "integrate" to begin.**
