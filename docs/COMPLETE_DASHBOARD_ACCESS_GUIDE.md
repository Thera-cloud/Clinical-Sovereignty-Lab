# CLINICAL SOVEREIGNTY LAB - COMPLETE DASHBOARD ACCESS GUIDE
## All HTML Dashboards + Flutter App + Execution Commands

**Last Updated:** January 29, 2026  
**Backend Port:** 8765  
**Dashboard Base Path:** `~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/`

---

## 🚀 STARTUP SEQUENCE

### Step 1: Start Backend (REQUIRED FIRST)
```bash
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
DATA_DIR=./data python3 bridge_server.py
```

### Step 2: Open Desired Dashboard
```bash
# Quick open any dashboard (replace filename)
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/FILENAME.html
```

---

## 📊 THE EYE (Analytics Platform)

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Main Dashboard** | `the_eye.html` | Overview analytics |
| **Token Analytics** | `the_eye_tokens.html` | Token usage tracking |
| **Crisis Center** | `the_eye_crisis.html` | Crisis monitoring |
| **Coach Performance** | `the_eye_coaches.html` | Coach metrics |
| **Community** | `the_eye_community.html` | Community analytics |
| **Live Monitor** | `the_eye_monitor.html` | Real-time monitoring |

```bash
# Open The Eye dashboards
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye_tokens.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye_crisis.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye_coaches.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye_community.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye_monitor.html
```

---

## 🧠 NEVEDAL LAB (Emotional Coherence)

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Live Analysis** | `nevedal_lab_live.html` | Real-time C_emo tracking |
| **Longitudinal Study** | `nevedal_lab_longitudinal.html` | Long-term trends |
| **Cohort Analysis** | `nevedal_lab_cohort.html` | Group comparisons |
| **Dyad Analysis** | `nevedal_lab_dyad.html` | Relationship dynamics |
| **Family Analysis** | `nevedal_lab_family.html` | Family system tracking |

```bash
# Open Nevedal Lab dashboards
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/nevedal_lab_live.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/nevedal_lab_longitudinal.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/nevedal_lab_cohort.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/nevedal_lab_dyad.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/nevedal_lab_family.html
```

---

## 🎓 NIGHT SCHOOL (AI Training & Curriculum)

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Main Night School** | `night_school.html` | Training overview |
| **Dojo** | `night_school_dojo.html` | Practice environment |
| **Curriculum** | `night_school_curriculum.html` | Course management |
| **Wisdom Editor** | `night_school_wisdom.html` | Knowledge base editing |
| **Notes** | `night_school_notes.html` | Session notes |
| **Versions** | `night_school_versions.html` | Version history |

```bash
# Open Night School dashboards
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school_dojo.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school_curriculum.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school_wisdom.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school_notes.html
```

---

## 🎮 COMMAND CENTER & ADMIN

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Command Center** | `command.html` | Main control panel |
| **Main Index** | `index.html` | Dashboard hub/login |
| **System Status** | `system.html` | System health |
| **User Management** | `users.html` | User administration |
| **Coach Approvals** | `coach_approvals.html` | Pending approvals |

```bash
# Open Command & Admin dashboards
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/command.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/index.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/system.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/users.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/coach_approvals.html
```

*Removed 2026-04-30:* `admin_bypass.html` was a dev backdoor and is **purged** everywhere (`ca8b3ef`). Use `command.html` and normal admin auth only.

---

## 💬 LITTLE NATE & CLIENT TOOLS

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Ask Nate** | `ask_nate.html` | AI chat interface |
| **Pre-Session Brief** | `presession_brief.html` | Session preparation |
| **My Clients** | `my_clients.html` | Coach client list |
| **Calendar** | `calendar.html` | Scheduling |
| **Crisis Center** | `crisis_center.html` | Crisis management |

```bash
# Open Client & Coaching tools
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/ask_nate.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/presession_brief.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/my_clients.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/calendar.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/crisis_center.html
```

---

## 🧪 DEBUG & TESTING

| Dashboard | File | Purpose |
|-----------|------|---------|
| **Debug Console** | `debug.html` | System debugging |
| **WebSocket Test** | `ws_test.html` | WS connection test |
| **Test WebSocket** | `test_websocket.html` | Alternative WS test |
| **Test Simple** | `test_simple.html` | Basic functionality |
| **Check Session** | `check_session.html` | Session verification |

```bash
# Open Debug tools
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/debug.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/ws_test.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/test_websocket.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/check_session.html
```

---

## 📱 FLUTTER APP (Mobile/Web)

```bash
# Start Flutter web app
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile
flutter run -d chrome
```

**Features in Flutter:**
- Neural Interface (Little Nate chat)
- Family Sanctuary (group therapy)
- Metrics display (Nevedal integration)
- Real-time WebSocket connection

---

## 🎨 MOCKUPS (Design Reference)

### Admin Mockups
```bash
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_01_dashboard.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_02_user_management.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_03_night_school.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_04_the_eye.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_05_audit_log.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_06_nate_features.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/admin/sc_07_nevedal_lab.html
```

### E-Commerce Mockups
```bash
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/ecommerce/ec_01_membership_selection.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/ecommerce/ec_02_family_management.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/ecommerce/ec_03_coaching_booking.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/docs/mockups/ecommerce/ec_04_trial_expiration.html
```

---

## 🚀 QUICK LAUNCH SCRIPTS

### Open All Core Dashboards
```bash
#!/bin/bash
# Save as: open_all_dashboards.sh

BASE=~/Desktop/Clinical-Sovereignty-Lab-2/dashboard

# Command Center
open "$BASE/command.html"

# The Eye
open "$BASE/the_eye.html"

# Nevedal Lab
open "$BASE/nevedal_lab_live.html"

# Night School
open "$BASE/night_school.html"

# Ask Nate
open "$BASE/ask_nate.html"
```

### Open Full Suite
```bash
#!/bin/bash
# Save as: open_full_suite.sh

BASE=~/Desktop/Clinical-Sovereignty-Lab-2/dashboard

# Core
open "$BASE/index.html"
open "$BASE/command.html"

# The Eye Suite
open "$BASE/the_eye.html"
open "$BASE/the_eye_tokens.html"
open "$BASE/the_eye_coaches.html"

# Nevedal Suite
open "$BASE/nevedal_lab_live.html"
open "$BASE/nevedal_lab_longitudinal.html"
open "$BASE/nevedal_lab_family.html"

# Night School Suite
open "$BASE/night_school.html"
open "$BASE/night_school_dojo.html"
open "$BASE/night_school_curriculum.html"

# Client Tools
open "$BASE/ask_nate.html"
open "$BASE/my_clients.html"
open "$BASE/crisis_center.html"
```

---

## 📋 COMPLETE FILE LIST

### `/dashboard/` Directory (Main Dashboards)
| File | Category |
|------|----------|
| `ask_nate.html` | Little Nate |
| `calendar.html` | Scheduling |
| `check_session.html` | Debug |
| `coach_approvals.html` | Admin |
| `command.html` | Command Center |
| `crisis_center.html` | Crisis |
| `debug.html` | Debug |
| `index.html` | Main Entry |
| `my_clients.html` | Coach Tools |
| `nevedal_lab_cohort.html` | Nevedal |
| `nevedal_lab_dyad.html` | Nevedal |
| `nevedal_lab_family.html` | Nevedal |
| `nevedal_lab_live.html` | Nevedal |
| `nevedal_lab_longitudinal.html` | Nevedal |
| `nevedal_lab_old.html` | Nevedal (legacy) |
| `nevedal_lab_old_backup.html` | Nevedal (backup) |
| `night_school.html` | Night School |
| `night_school_curriculum.html` | Night School |
| `night_school_dojo.html` | Night School |
| `night_school_notes.html` | Night School |
| `night_school_versions.html` | Night School |
| `night_school_wisdom.html` | Night School |
| `presession_brief.html` | Coach Tools |
| `system.html` | Admin |
| `test_simple.html` | Debug |
| `test_websocket.html` | Debug |
| `the_eye.html` | The Eye |
| `the_eye_coaches.html` | The Eye |
| `the_eye_community.html` | The Eye |
| `the_eye_crisis.html` | The Eye |
| `the_eye_monitor.html` | The Eye |
| `the_eye_tokens.html` | The Eye |
| `users.html` | Admin |
| `ws_test.html` | Debug |

---

## 🔑 TEST ACCOUNTS

| Username | Password | Role | Access |
|----------|----------|------|--------|
| `client1` | `test123` | Client (John D.) | Ask Nate, Family Sanctuary |
| `client1b` | `test123` | Client (Jane D.) | Ask Nate, Family Sanctuary |
| `coach1` | `test123` | Coach (Coach Hope) | My Clients, Presession |
| `admin1` | (hashed) | Admin | All dashboards |

---

## 🌐 TYPICAL WORKFLOW

### For Developers
```bash
# 1. Start backend
cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket
DATA_DIR=./data python3 bridge_server.py

# 2. Open Command Center
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/command.html

# 3. Monitor in The Eye
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye.html

# 4. Debug if needed
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/debug.html
```

### For Coaches
```bash
# 1. Start backend (or connect to production)
# 2. Open coach tools
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/my_clients.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/presession_brief.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/night_school.html
```

### For Admins
```bash
# 1. Open admin suite
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/command.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/users.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/the_eye.html
open ~/Desktop/Clinical-Sovereignty-Lab-2/dashboard/system.html
```

### For Testing Family Sanctuary
```bash
# Terminal 1: Backend
DATA_DIR=./data python3 bridge_server.py

# Terminal 2: Flutter
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile && flutter run -d chrome

# Browser 1: Login as John (client1)
# Browser 2 (incognito): Login as Jane (client1b)
# Both join Family Sanctuary
```

---

**Document Version:** 2.0  
**Total Dashboards:** 35+ HTML files  
**Status:** ✅ Complete
