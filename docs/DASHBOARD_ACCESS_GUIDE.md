# CLINICAL SOVEREIGNTY LAB - DASHBOARD ACCESS GUIDE
## Complete Startup Commands & URLs

**Last Updated:** January 29, 2026  
**Backend Port:** 8765  
**Flutter Port:** Dynamic (typically 54683+)

---

## 🚀 QUICK START (Run in Order)

### Terminal 1: Backend Server
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
DATA_DIR=./data python3 bridge_server.py
```

**Expected Output:**
```
[*] Starting Sovereign Bridge v16.1 on 0.0.0.0:8765
[*] Bridge Online. Awaiting connections...
```

### Terminal 2: Flutter App
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter run -d chrome
```

**Expected Output:**
```
Launching lib/main.dart on Chrome...
Running on http://localhost:XXXXX
```

---

## 📊 DASHBOARD ACCESS

### 1. NEURAL INTERFACE (Little Nate Chat)
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` |
| **Login** | `client1` / `test123` |
| **Purpose** | Main AI therapy chat with Little Nate |
| **Features** | Chat, metrics display, Family Sanctuary access |

```bash
# Access after Flutter starts
open http://localhost:54683  # Port varies - check Flutter output
```

### 2. THE EYE (Analytics Dashboard)
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` → Click 📊 icon |
| **Login** | `admin1` / (check credentials) |
| **Purpose** | Platform analytics, revenue, user metrics |
| **Features** | Message counts, Azure costs, token usage, sessions |

**Access:** Login as admin or navigate via the analytics icon in the app header.

### 3. NEVEDAL LAB (Emotional Coherence)
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` → Nevedal section |
| **Login** | Any authenticated user |
| **Purpose** | C_emo tracking, emotional coherence over time |
| **Features** | Live analysis, longitudinal study, cohort analysis |

**Metrics Displayed:**
- C_emo (Emotional Coherence): 0-100%
- GAP (Growth Acceleration Potential)
- Quantum Score
- Risk Level (LOW/MEDIUM/HIGH)

### 4. NIGHT SCHOOL (Curriculum Management)
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` → Admin → Night School |
| **Login** | `admin1` / (admin credentials) |
| **Purpose** | Upload/manage therapeutic training materials |
| **Features** | File upload, category management, wisdom editing |

**Admin Access:**
```bash
# Login as admin to access Night School
Username: admin1
Password: [check user_registry.json or use known password]
```

### 5. FAMILY SANCTUARY (Group Therapy)
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` → 👨‍👩‍👧 icon |
| **Login** | `client1` / `test123` (John D.) or `client1b` / `test123` (Jane D.) |
| **Purpose** | AI-facilitated family conflict resolution |
| **Features** | Group chat, private coaching, session summaries |

**Multi-User Testing:**
```bash
# Browser 1 - John
open http://localhost:54683
# Login: client1 / test123

# Browser 2 (Incognito) - Jane  
# Login: client1b / test123
```

### 6. COACH DASHBOARD
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` |
| **Login** | `coach1` / `test123` |
| **Purpose** | Client management, session review, guidance notes |
| **Features** | Client list, flagged sessions, notes |

**Coach Accounts:**
| Username | Name | Specialty |
|----------|------|-----------|
| `coach1` | Coach Hope | CBT - Anxiety |
| `coach2` | Dr. Chen | Trauma - EMDR |
| `coach3` | Marcus Thompson | Life Coaching |
| `coach4` | Dr. Williams | Family Therapy |
| `coach5` | Dr. Amanda Wells | Adolescent |

### 7. ADMIN DASHBOARD
| Property | Value |
|----------|-------|
| **URL** | `http://localhost:{flutter_port}` |
| **Login** | `admin1` / (admin password) |
| **Purpose** | System administration, user management |
| **Features** | User registry, Night School, system config |

---

## 👥 TEST ACCOUNTS

### Clients (Family FAM_1834DACF)
| Username | Password | Name | Role |
|----------|----------|------|------|
| `client1` | `test123` | John D. | Head of Household |
| `client1b` | `test123` | Jane D. | Spouse |

### Other Clients
| Username | Password | Name |
|----------|----------|------|
| `client2` | `test123` | Sarah M. |
| `client3` | `test123` | Lisa P. |
| `client4` | `test123` | Alex C. |

### Coaches
| Username | Password | Name |
|----------|----------|------|
| `coach1` | `test123` | Coach Hope |
| `coach2` | `test123` | Dr. Chen |

### Admin
| Username | Password | Name |
|----------|----------|------|
| `admin1` | (hashed) | Admin User |

---

## 🔧 USEFUL COMMANDS

### Check Backend Status
```bash
# See if backend is running
lsof -i :8765

# Check WebSocket connections
curl -I http://localhost:8765
```

### Restart Backend
```bash
# Kill existing
pkill -f bridge_server.py

# Restart
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
DATA_DIR=./data python3 bridge_server.py
```

### Hot Restart Flutter
```bash
# In Flutter terminal, press:
r  # Hot reload
R  # Hot restart (full)
q  # Quit
```

### View Sanctuary History
```bash
# List completed sessions
ls -la ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/data/sanctuary_history/

# View specific session
cat ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/data/sanctuary_history/SANC_20260126_001.json | python3 -m json.tool | head -50
```

### View User Registry
```bash
cat ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/data/user_registry.json | python3 -m json.tool
```

### Check Night School Wisdom
```bash
cat ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/data/wisdom_database.json | python3 -m json.tool
```

---

## 🧪 TESTING FLOWS

### Test Neural Interface (Little Nate Chat)
1. Start backend
2. Start Flutter
3. Login as `client1`
4. Send message to Little Nate
5. Check backend logs for `>>> [AI] Cortex Active`

### Test Family Sanctuary
1. Start backend
2. Start Flutter
3. Login as `client1` in Browser 1
4. Click Family Sanctuary icon (👨‍👩‍👧)
5. Open incognito, login as `client1b`
6. Join same sanctuary
7. Exchange messages, trigger escalation
8. Accept coaching offer
9. Complete session, verify summary displays

### Test Night School
1. Login as `admin1`
2. Navigate to Night School
3. Upload a .txt file with coaching tips
4. Verify ingestion in backend logs
5. Chat with Little Nate, verify wisdom appears

---

## 📁 KEY FILE LOCATIONS

| File | Purpose |
|------|---------|
| `backend/app/websocket/bridge_server.py` | Main backend, all WebSocket handlers |
| `backend/app/websocket/sanctuary_engine.py` | Sanctuary state management |
| `backend/app/websocket/data/user_registry.json` | User accounts |
| `backend/app/websocket/data/sanctuary_history/*.json` | Completed sessions |
| `backend/app/websocket/data/wisdom_database.json` | Night School wisdom |
| `mobile/lib/main.dart` | Flutter app, all screens |

---

## 🐛 TROUBLESHOOTING

### "Connection refused" on Flutter
```bash
# Make sure backend is running first
DATA_DIR=./data python3 bridge_server.py
```

### "Module not found" errors
```bash
pip install aiohttp websockets stripe sendgrid --break-system-packages
```

### Flutter won't start
```bash
flutter clean
flutter pub get
flutter run -d chrome
```

### Sanctuary not loading history
```bash
# Check family_id matches
grep "family_id" ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/data/sanctuary_history/*.json
```

---

## 📊 SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                     FLUTTER APP (Chrome)                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Neural   │ │ Family   │ │ The Eye  │ │ Night    │           │
│  │ Interface│ │ Sanctuary│ │ Analytics│ │ School   │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │            │            │            │                  │
│       └────────────┴────────────┴────────────┘                  │
│                         │                                        │
│                    WebSocket                                     │
│                    :54683                                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                  BRIDGE SERVER (Python)                          │
│                     Port 8765                                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Azure    │ │ Sanctuary│ │ Nevedal  │ │ Night    │           │
│  │ Cortex   │ │ Engine   │ │ Metrics  │ │ School   │           │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │            │            │            │                  │
│       ▼            ▼            ▼            ▼                  │
│  ┌─────────────────────────────────────────────────┐           │
│  │              DATA LAYER (./data/)               │           │
│  │  user_registry.json | sanctuary_history/        │           │
│  │  wisdom_database.json | Vaults/                 │           │
│  └─────────────────────────────────────────────────┘           │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AZURE OPENAI                                  │
│              (GPT-4 Realtime API)                               │
└─────────────────────────────────────────────────────────────────┘
```

---

**Document Version:** 1.0  
**Status:** ✅ Complete
