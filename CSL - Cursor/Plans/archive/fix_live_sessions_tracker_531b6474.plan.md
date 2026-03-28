---
name: Fix live sessions tracker
overview: Change the "Live Sessions" dashboard metric from counting open WebSocket connections to counting actual active coaching sessions (from coach_live_sessions.json), and add a separate "App Users Online" metric for mobile app connections.
todos:
  - id: backend-stats
    content: Update get_dashboard_stats() to count ACTIVE entries from coach_live_sessions.json instead of LIVE_SESSION_TRACKER, and add app_users_online field
    status: completed
  - id: dashboard-display
    content: Update command.html stat box and updateStats() to show real coaching sessions and app users online
    status: completed
isProject: false
---

# Fix Live Sessions to Track Real Coaching Sessions

## Problem

The "Live Sessions" stat on Sovereign Command shows `len(LIVE_SESSION_TRACKER)` which counts anyone with an open WebSocket (admin dashboard, mobile app, any tab). It does not represent actual coaching sessions.

## Solution

Two changes:

### 1. Backend: Update `get_dashboard_stats()` in [bridge_server.py](backend/app/websocket/bridge_server.py)

At line ~3268, change the stats dict so that:

- `live_sessions` / `active_sessions` = count of entries in `coach_live_sessions.json` where `status == "ACTIVE"` (real coaching sessions)
- Add new field `app_users_online` = count of connected clients from mobile app (using existing `connected_clients` set, excluding ADMIN role connections)

The coach live sessions file is already loaded elsewhere in the file via `load_json_file(COACH_LIVE_SESSIONS_FILE, {})`. We just need to add the same load + filter inside `get_dashboard_stats()`:

```python
# Real coaching sessions (not WebSocket connections)
try:
    live_store = load_json_file(COACH_LIVE_SESSIONS_FILE, {}) or {}
    active_coaching = sum(1 for s in live_store.values() if isinstance(s, dict) and s.get("status") == "ACTIVE")
except Exception:
    active_coaching = 0

# ...
"live_sessions": active_coaching,
"active_sessions": active_coaching,
"app_users_online": len(connected_clients),  # mobile app users
```

### 2. Dashboard: Update stat box in [command.html](dashboard/command.html)

At line ~1075, update the "Live Sessions" stat box label and add a new stat box for app users:

- Change "Live Sessions / Currently" to show the real coaching session count (no code change needed -- it already reads `active_sessions`)
- Add subtitle showing app users online beneath it, or add a separate stat box

Update `updateStats()` at line ~1608 to also display `stats.app_users_online`.

## Files to Change

- [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) -- `get_dashboard_stats()` method (~line 3268)
- [dashboard/command.html](dashboard/command.html) -- stat box HTML (~~line 1075) and `updateStats()` function (~~line 1606)

