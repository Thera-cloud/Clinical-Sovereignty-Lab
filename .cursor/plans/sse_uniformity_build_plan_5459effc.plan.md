---
name: SSE Uniformity Build Plan
overview: "Complete Items 0A-0C (uniformity fixes already deployed), then implement Items 1-5: Xcode docs, widget_engine column fixes, Phase 4 chat integration (recap card + suggestion buttons + recap endpoint), download verification, and widget test page."
todos:
  - id: xcode-instructions
    content: Create mobile/ios/WIDGET_SETUP_INSTRUCTIONS.md with 8-step Xcode setup guide
    status: completed
  - id: widget-engine-fix
    content: Fix 8 column mismatches in widget_engine.py (content->detail, title->goal, id->quest_id/mission_id, created_at->generated_at)
    status: completed
  - id: checkin-fix
    content: Fix checkin endpoint in admin.py (created_at->generated_at, add source_type, fix UUID cast)
    status: completed
  - id: recap-endpoint
    content: Add GET /api/sse-client/recap endpoint to admin.py (~20 lines)
    status: completed
  - id: recap-card
    content: Add recap card UI to NeuralInterfaceV2 in updated_screens.dart (~40 lines)
    status: completed
  - id: suggestion-buttons
    content: Add quest/mission suggestion detection + inline buttons in chat message renderer (~25 lines)
    status: completed
  - id: deploy-backend
    content: Deploy widget_engine.py + admin.py to GREEN, restart backend, verify
    status: completed
  - id: widget-test-html
    content: Create dashboard/widget_test.html preview page (~30 lines)
    status: completed
  - id: widget-name-rename
    content: Rename widget display name from 'Little Nate' to 'Sovereign Sanctuary' in 4 files (Swift, Android XML x2, settings_screen.dart)
    status: completed
  - id: deploy-flutter
    content: Build and deploy Flutter web via ./deploy-web.sh
    status: completed
isProject: false
---

# SSE Uniformity + Phase 4 Build Plan

## Item 0: Three Uniformity Fixes (COMPLETED)

All three have been deployed and verified (104/104 healthy):

- **0A Unified Vault View**: `GET /api/sse-client/journey/panels` now queries both `sse_panel_log` and `sse_delivery_generation_log`, merges by `generated_at DESC`. Uses `ANY($1)` with both `hardware_id` and `username` for backward compatibility.
- **0B User ID Consistency**: `layer0_orchestrator._run_journey_panels()` changed from `SELECT username` to `SELECT hardware_id`. Future panels use `hardware_id` matching delivery log.
- **0C LLM Narrative Fix**: Root cause was auth header mismatch (`Authorization: Bearer` vs Azure's `api-key`). Fixed in `thera_world_engine.py` with URL-based detection. Added 2s delay between users in orchestrator loop.

---

## Item 1: Xcode Widget Extension Setup Instructions

Create `mobile/ios/WIDGET_SETUP_INSTRUCTIONS.md` (~40 lines) documenting 8 manual Xcode steps:
1. Open `Runner.xcworkspace`
2. File > New > Target > Widget Extension (name: `NateWidget`, bundle: `net.sovereignsanctuary.littlenate.NateWidget`, no config intent, no live activity)
3. Activate scheme
4. Delete Xcode's auto-generated template files
5. Drag existing `ios/NateWidget/*.swift` files into the group
6. Add App Group `group.net.sovereignsanctuary.littlenate` to both Runner and NateWidget targets
7. Set deployment target to match Runner
8. Build and run

Documentation only -- no code changes.

### 1B: Widget Display Name Rename

Change "Little Nate" to "Sovereign Sanctuary" in 4 files (1 line each):

- `mobile/ios/NateWidget/NateWidget.swift` -- `displayName` and `description` strings
- `mobile/android/app/src/main/res/xml/nate_widget_info_small.xml` -- `android:label`
- `mobile/android/app/src/main/res/xml/nate_widget_info_medium.xml` -- `android:label`
- `mobile/lib/screens/settings_screen.dart` -- setup instructions text referencing the widget name

---

## Item 2: Fix widget_engine.py Column Mismatches + Checkin Endpoint

### 2A: widget_engine.py (11 fixes in [backend/app/sse/widget_engine.py](backend/app/sse/widget_engine.py))

Per schema audit against migration 174:

| Line | Table | Wrong | Correct |
|------|-------|-------|---------|
| 128 | `sse_admin_alerts` | `content` | `detail` |
| 136 | `sse_quests` | `title` | `goal` |
| 153 | `sse_quests` | `id` | `quest_id` |
| 153 | `sse_quests` | `title` | `goal` |
| 161 | `sse_missions` | `id` | `mission_id` |
| 161 | `sse_missions` | `title` | `relationship_target` |
| 183 | `sse_panel_log` | `created_at` | `generated_at` |
| 200 | `sse_panel_log` | `created_at` | `generated_at` |

Also update Python dict key references downstream (e.g. `aq["title"]` becomes `aq["goal"]`).

### 2B: Checkin endpoint (3 fixes in [backend/app/routers/admin.py](backend/app/routers/admin.py) line 5517)

Current INSERT is broken per schema:

```sql
-- WRONG (current):
INSERT INTO sse_panel_log (panel_id, user_id, panel_type, narrative_text, created_at)
VALUES (gen_random_uuid()::text, $1, 'checkin', $2, now())
```

Fix to:

```sql
-- CORRECT:
INSERT INTO sse_panel_log (panel_id, user_id, panel_type, source_type, narrative_text)
VALUES (gen_random_uuid(), $1, 'checkin', 'checkin', $2)
```

Changes: `created_at` removed (use `generated_at DEFAULT now()`), add `source_type='checkin'` (NOT NULL column), drop `::text` cast on UUID.

---

## Item 3: Phase 4 -- Flutter Chat Integration

### 3A: Backend Recap Endpoint (~20 lines in [admin.py](backend/app/routers/admin.py))

New endpoint: `GET /api/sse-client/recap` on `sse_client_router`

Returns:

```python
{
  "user_name": str,           # from profile_data->>'name' or username
  "journey": {
    "biome": str,             # from sse_user_journeys.current_biome
    "phase": str,             # from sse_user_journeys.dominant_character
    "panel_count": int,       # COUNT from sse_panel_log
    "archetype_hint": str,    # from sse_identity_forge.archetype_hint
    "archetype_image_url": str # from sse_identity_forge.archetype_image_url
  },
  "active_quests": [{
    "goal": str,
    "days_active": int,       # now() - started_at
    "quest_id": str
  }],
  "active_missions": [{
    "relationship_target": str,
    "days_active": int,
    "mission_id": str
  }],
  "workbooks": [{
    "storyboard_title": str,  # from sse_ip_provenance.story_plot_json->>'title'
    "source": str             # from sse_enrolled_users.source
  }],
  "crystal_insight": str,     # most recent crystal_text from nate_intelligence_crystals (confidence >= 0.5)
  "last_panel_url": str,      # most recent r2_url from sse_panel_log
  "widget_content": dict      # today's widget content (reuse widget cache)
}
```

Workbook enrollment query (~3 lines):

```sql
SELECT e.storyboard_id, e.source,
       p.story_plot_json::json->>'title' as storyboard_title
FROM sse_enrolled_users e
LEFT JOIN sse_ip_provenance p ON e.storyboard_id = (p.story_plot_json::json->>'id')
WHERE e.user_id = $1
```

Data sources: `sse_user_journeys`, `sse_identity_forge`, `sse_quests` (status='active'), `sse_missions` (status='active'), `sse_enrolled_users` + `sse_ip_provenance`, `nate_intelligence_crystals`, `sse_panel_log`, widget cache.

### 3B: Recap Card UI (~40 lines in [updated_screens.dart](mobile/lib/updated_screens.dart))

Insert after the SSE intake banner (line 3647) and before the main content `Expanded`:

- New state variables: `Map<String, dynamic>? _recapData`, `bool _recapDismissed = false`
- New method `_fetchRecap()` called from `initState()` -- fetches `GET /api/sse-client/recap` using `widget.currentUserProfile?['token']`
- Conditionally render recap card when `_recapData != null && !_recapDismissed && !_sseIntakePending`
- Card content:
  - Journey biome + panel count
  - Active quest goal (if any)
  - Active mission target (if any)
  - Crystal insight snippet (if any)
- Four action buttons in a `Wrap`: `[Continue Journey]`, `[Work on Quest]`, `[Talk About Mission]`, `[Just Chat]`
  - First three send a pre-written message to Nate via the existing `_sendMessage()` or WebSocket send
  - "Just Chat" dismisses the card
- Auto-dismiss after 30 seconds via `Timer`
- Dark theme matching existing SSE banner style (gold border, void background)

### 3C: Quest/Mission Suggestion Buttons (~25 lines in [updated_screens.dart](mobile/lib/updated_screens.dart))

In the chat message rendering (around line 3700 in the `ListView.builder`), after rendering a "Little Nate:" message:

- Check if message text contains `"make this a Quest"` or `"could be a Mission"`
- If detected, render inline action buttons below that message bubble:
  - `[Start Quest] [Not right now]` or `[Start Mission] [Not right now]`
  - "Start Quest" calls `POST /api/sse-client/quest/create` with goal extracted from context
  - "Start Mission" calls `POST /api/sse-client/mission/create`
  - "Not right now" hides the buttons for that message
- Track dismissed suggestions in a `Set<int>` keyed by message index

---

## Item 4: Download Button Verification (CONFIRMED WORKING)

Already verified in previous session. `web_download_web.dart` correctly uses blob-based approach:

```dart
final blob = html.Blob([response.bodyBytes], 'image/png');
final url = html.Url.createObjectUrlFromBlob(blob);
html.AnchorElement(href: url)..download = filename..click();
```

No changes needed.

---

## Item 5: Widget Device Test Preparation

### 5A: Android Widget Manifest Verification

Verify `AndroidManifest.xml` has `NateWidgetProvider` and `NateWidgetMediumProvider` receivers (already confirmed present). Run `flutter build apk --debug` to verify compiles.

### 5B: Widget Test HTML Page

Create `dashboard/widget_test.html` (~30 lines):
- Fetches `GET /api/sse-client/widget` with admin auth token from `sessionStorage`
- Renders: image (if present), primary text, secondary text, background color swatch
- Reuses `_authHeaders()` pattern from other dashboard pages
- Deploy to both `/opt/clinical-sovereignty-lab/dashboard/` and `/var/www/sovereign-command/`

---

## Deployment Order

1. Items 1 + 2 (docs + backend column fixes) -- deploy `widget_engine.py` + `admin.py` to GREEN, restart backend
2. Item 3A (recap endpoint) -- deploy `admin.py` update, restart backend
3. Items 3B + 3C (Flutter chat integration) -- edit `updated_screens.dart`, build web, deploy via `./deploy-web.sh`
4. Item 5B (widget test HTML) -- deploy to both dashboard directories
