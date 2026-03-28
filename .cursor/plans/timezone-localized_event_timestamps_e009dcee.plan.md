---
name: Timezone-Localized Event Timestamps
overview: "Ensure all clinical interaction timestamps carry the client's IANA timezone and UTC offset, preventing false positives in community aggregation, maintaining HIPAA-compliant audit precision, and enabling accurate cross-timezone event correlation."
todos:
  - id: tz-migration-143
    content: "Create migration 143_timezone_localization.sql — add client_timezone columns to conversation_history, nevedal_metrics, audit_log, community_check_ins, coaching_sessions, nate_intelligence_crystals"
    status: completed
  - id: tz-flutter-payload
    content: "Add client_timezone and utc_offset_minutes to every nate_query payload in main.dart and updated_screens.dart"
    status: completed
  - id: tz-bridge-extract
    content: "Extract client_timezone from WebSocket payload in bridge_server.py, inject into profile as _live_timezone, pass to memorize(), _memorize_pg(), nevedal_handler, temporal_anchor"
    status: completed
  - id: tz-normalize-datetimes
    content: "Replace datetime.now() and datetime.utcnow() with datetime.now(timezone.utc) across bridge_server.py, session_memory_store.py, nevedal_engine.py"
    status: completed
  - id: tz-crystallizer-spread
    content: "Add timezone_spread TEXT[] column to nate_intelligence_crystals, populate during crystal synthesis with distinct client timezones from cluster items"
    status: completed
  - id: tz-community-correlation
    content: "Verify community_mesh_engine convergence detection uses UTC-normalized timestamps (confirmed already correct)"
    status: completed
  - id: tz-compliance-rule
    content: "Create timestamp-localization.mdc cursor rule and add Timestamp Precision section to SOVEREIGN_STANDARD_v1.0.md"
    status: completed
  - id: tz-dashboard-display
    content: "Add fmtDualTz(ts, clientTz) utility to skyeye.html for dual-format timestamp display (client local + UTC)"
    status: completed
isProject: false
---

# Timezone-Localized Event Timestamps

## Problem Statement

Without client timezone context, two clients (PST and EST) discussing the same event generate different UTC timestamps. The crystallizer, insight accumulator, and community mesh treat these as separate events, causing false positives in global aggregation. Additionally, HIPAA 45 CFR 164.312(b) requires audit controls with precise timestamps traceable to the actor's context.

## Architecture

### Data Flow

```
Flutter Client (nate_query)
  ├── client_timezone: "America/Los_Angeles"
  └── utc_offset_minutes: -420
         ↓
Bridge Server (nate_query handler)
  ├── Injects _live_timezone into profile
  ├── Passes to process_interaction() → memorize()
  └── _memorize_pg() stores client_timezone + utc_offset_minutes
         ↓
PostgreSQL (conversation_history, nevedal_metrics)
  ├── created_at: TIMESTAMPTZ (UTC)
  ├── client_timezone: TEXT ('America/Los_Angeles')
  └── utc_offset_minutes: INTEGER (-420)
         ↓
Crystallizer (nate_memory_crystallizer.py)
  └── timezone_spread: TEXT[] (distinct client timezones per crystal)
         ↓
Dashboard (skyeye.html)
  └── fmtDualTz(ts, clientTz) → "Mar 13, 02:30 PM PDT (2026-03-13 21:30 UTC)"
```

## Files Modified

| File | Change |
|---|---|
| `backend/migrations/143_timezone_localization.sql` | New columns on 7 tables |
| `mobile/lib/main.dart` | Added `client_timezone` + `utc_offset_minutes` to nate_query |
| `mobile/lib/updated_screens.dart` | Same |
| `backend/app/websocket/bridge_server.py` | Extract timezone, inject into profile, update memorize/memorize_pg/store_chat_cee/temporal_anchor |
| `backend/app/services/session_memory_store.py` | Import timezone, normalize all datetime.now() calls |
| `backend/app/services/nevedal_engine.py` | Import timezone, normalize datetime.utcnow() to datetime.now(timezone.utc) |
| `backend/app/services/nate_memory_crystallizer.py` | Add timezone_spread to crystal INSERT |
| `backend/app/services/community_mesh_engine.py` | Added client_timezone param to record_attendance |
| `dashboard/skyeye.html` | Added fmtDualTz() utility function |
| `docs/SOVEREIGN_STANDARD_v1.0.md` | Added Timestamp Precision compliance section |
| `.cursor/rules/timestamp-localization.mdc` | New always-on rule for timestamp best practices |
