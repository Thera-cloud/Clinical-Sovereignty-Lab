---
name: SSE Phase 3 Expansion
overview: "Phase 3: Build dashboard first (Part A), deploy, then Parts B-G sequentially: vault tab, image fix, response time, admin profile enrichment, journey override, feedback loop."
todos:
  - id: part-a-backend
    content: "PART A: Add users-summary + preview endpoints to admin.py, expand get_user_sse_status() in thera_world_engine.py"
    status: completed
  - id: part-a-dashboard
    content: "PART A: Build alerts feed + user explorer + admin actions in sse_monitoring.html (~500 lines)"
    status: completed
  - id: part-a-deploy
    content: "PART A DEPLOY: scp dashboard + backend to GREEN, restart, verify dashboard loads"
    status: completed
  - id: part-b-endpoint
    content: "PART B: Add GET /api/sse-client/journey/panels endpoint to admin.py (15 lines)"
    status: completed
  - id: part-b-flutter
    content: "PART B: Intercept Sovereign Journey folder + SSE Ask Nate flow in vault_browser_screen.dart (20 lines)"
    status: completed
  - id: part-c-image
    content: "PART C: Add positive image affirmation to bridge_server.py system prompt (1 line, PROTECTED)"
    status: completed
  - id: part-d-tokens
    content: "PART D: Change max_tokens 300/150 to 1500 in bridge_server.py (3 lines, PROTECTED)"
    status: completed
  - id: part-d-cache
    content: "PART D: Add 5-min TTL cache to get_user_story_context() in layer6_crystal_bridge.py (5 lines)"
    status: completed
  - id: part-d-trim
    content: "PART D: Shorten [STORY JOURNEY] to 1-line summary in littlenate_inference.py (2 lines, PROTECTED 18/20)"
    status: completed
  - id: part-e-enrichment
    content: "PART E: Add crystal health, coherence, crystal snippets per panel to get_user_sse_status() (~10 lines)"
    status: completed
  - id: part-f-override
    content: "PART F: Add POST /api/sse/admin/journey/override endpoint to admin.py (15 lines)"
    status: completed
  - id: part-g-feedback
    content: "PART G: Add POST /api/sse-client/panel/{panel_id}/viewed endpoint + migration 176 viewed_at column"
    status: completed
  - id: final-deploy
    content: "FINAL DEPLOY: scp all files, run migration 176, flutter build web, restart, verify 104/104, test all flows"
    status: completed
isProject: false
---

# Phase 3: SSE Monitor + Vault + Image Fix + Response Time + Admin Overrides + Feedback Loop

## BUILD ORDER

Build Part A first. Deploy and verify the dashboard. Then proceed through B-G in order:

1. **Part A** -- SSE Monitor dashboard (backend endpoints + HTML) -- deploy immediately
2. **Part B** -- Sovereign Vault "Story Journey" folder (endpoint + Flutter)
3. **Part C** -- Little Nate image inspection fix (bridge_server.py, 1 line)
4. **Part D** -- Response time optimization (max_tokens + cache + prompt trim)
5. **Part E** -- Admin profile enrichment (crystal health, coherence, crystal snippets)
6. **Part F** -- Journey override endpoint + dashboard button
7. **Part G** -- Panel-viewed feedback loop (endpoint + migration 176)

## Research Findings (Critical)

**Image Denial (Part C)**: There is NO denial text in `bridge_server.py` -- grep returned 0 matches. The vault image pipeline already works: lines 7978-7994 load the blob, create base64 `data:` URLs, and inject "[VAULT IMAGE ... The image is attached as a vision block. Describe what you see in detail.]". The `sovereign_chat_client.py` (lines 499-520) already builds multimodal messages with `image_url` blocks for Grok and Azure when `image_data_url` is set. The denial comes from LLM base behavior. Fix: add a **positive affirmation** to the system prompt.

**SSE Panels Not in vault_items (Part B)**: The "Ask Nate About This" button returns `item['id']` which becomes `[Vault:uuid]` in chat. The bridge looks up `vault_items` by UUID (line 7967). SSE panels live in `sse_panel_log`, NOT `vault_items` -- so the standard vault flow will fail silently. Fix: for SSE panels, the Flutter code must send the narrative text + panel metadata directly in the chat message instead of a `[Vault:uuid]` reference.

**Response Cutoff (Part D)**: `max_tokens` is overridden to `300` (streaming/generate) and `150` (race) in `bridge_server.py` lines 8307, 8334, 8348. The `sovereign_chat_client.py` default is `1500`. This causes the "we've" truncation.

**Story Context Size (Part D)**: The `[STORY JOURNEY]` block at `littlenate_inference.py` line 354-357 includes the full narrative text from `story_context.get('narrative', '')`. The `[ACTIVE QUEST]` and `[ACTIVE MISSION]` are already 1-liners. Trimming the narrative to a 1-sentence summary saves ~200 chars per message.

**Vault Tab Architecture (Part B)**: "Sovereign Journey" already exists as a pinned folder with green accent styling. Content comes from `GET /api/v1/vault/folders/{id}/items`. We intercept `_loadItems()` to call the SSE panels endpoint instead.

---

## Part A: SSE Monitor Dashboard

### A1. Backend endpoints in [admin.py](backend/app/routers/admin.py) on `sse_router` (20 lines)

**`GET /api/sse/monitor/users-summary`** -- all journey users with archetype/biome/quest/mission counts:

```python
@sse_router.get("/monitor/users-summary")
async def sse_monitor_users_summary(request: Request, _=Depends(require_admin)):
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT j.user_id, j.current_biome, j.dominant_character, j.panels_generated,
                   j.last_panel_at, j.panel_sequence,
                   f.archetype_hint, f.archetype_image_url,
                   (SELECT count(*) FROM sse_quests q WHERE q.user_id=j.user_id AND q.status='active') as active_quests,
                   (SELECT count(*) FROM sse_missions m WHERE m.user_id=j.user_id AND m.status='active') as active_missions
            FROM sse_user_journeys j LEFT JOIN sse_identity_forge f ON j.user_id=f.user_id
            ORDER BY j.last_panel_at DESC NULLS LAST""")
    return [dict(r) for r in rows]
```

**`POST /api/sse/thera-world/preview`** -- generate a single panel on demand:

```python
@sse_router.post("/thera-world/preview")
async def sse_thera_world_preview(request: Request, _=Depends(require_admin)):
    body = await request.json()
    from app.sse.thera_world_engine import generate_journey_panel
    return await generate_journey_panel(body["user_id"], request.app.state.db_pool)
```

### A2. Expand `get_user_sse_status()` in [thera_world_engine.py](backend/app/sse/thera_world_engine.py) (~20 lines)

Add to the returned dict:

- **Crystal health summary**: total crystal count, LOCKED count, top 5 domains by count, growth trend (compare count 30 days ago vs now: gaining/stable/declining). Query `nate_intelligence_crystals` with `WHERE user_id = (SELECT id FROM users WHERE username=$1)`.
- **Cycle detection**: query `nevedal_state` or PMB data for detected cycles. Format as list of `{pattern, frequency}` (e.g., "performance anxiety (weekly)").
- **Coherence trajectory**: query latest `nevedal_metrics` for the user's C/G/Q percentages. Return as `{coherence_pct, growth_pct, quantum_pct}`.
- **Per-panel crystal details**: for recent panels, include `crystal_domains_used` from `sse_panel_log` plus the actual crystal text snippets (join to `nate_intelligence_crystals`), their `confidence` (LOCKED >= 0.8, PROVISIONAL < 0.8), and whether any are SOVEREIGN-tier (server-canonical crystals with sovereignty_coefficient applied).
- `archetype_hint`, `archetype_image_url`, `data_richness`, workbook `source`, panel `prompt_used`/`narrative_text`.

### A3. Dashboard HTML -- 3 sections in [sse_monitoring.html](dashboard/sse_monitoring.html) (max 500 lines)

Insert ABOVE existing sections (after metric cards):

**Section A: SSE Alerts Feed**
- Calls `GET /api/sse/monitor/alerts?acknowledged=false`
- Color-coded badges: journey_started=green, biome_transition=blue, quest_created=gold, mission_created=purple, quest/mission_completed=green, quest/mission_paused=gray, workbook_assigned=cyan
- "Acknowledge" button per row, fade-out animation, auto-refresh 30s, count in header

**Section B: User Journey Explorer**
- Search box + "View All Users" button
- Summary table from `/users-summary`: User ID, Archetype thumbnail, Biome badge, Active Quests/Missions count, Total Panels, Last Panel Date
- Clickable rows load profile panel from `/user/{user_id}`
- **User Profile Panel** (two-column layout):
  - Left (40%): Journey card with archetype image (200px), archetype name + biome subtitle, biome-themed background color (dark_forest=#1a3a1a, fortress_plains=#3a2a0a, river_valley=#0a2a3a, crystal_mountains=#2a0a3a, open_sky=#3a3a0a), dominant character, data richness badge, panel count, journey start, last panel summary
  - Left (below journey card): **Crystal Health** card -- total crystals, LOCKED count, top 5 domains with counts, growth trend badge (gaining=green arrow, stable=gray, declining=red arrow)
  - Left (below crystal): **Coherence Trajectory** -- C/G/Q percentages with colored bars
  - Left (below coherence): **Detected Cycles** -- list of patterns with frequency badges
  - Right (60%): Active Quests section (goal, domain badge, NPC names, "View NPCs" expand with name/description/initial_form/transformed_form, status badge: active=green/climax_ready=pulsing gold/paused=gray), Active Missions, Workbook Enrollments (source badge: intake_auto=cyan/coach_assigned=gold/self_selected=green), Recent Panels (horizontal scrolling grid)
  - **Panel Detail Modal**: full-size image, narrative text, Grok Imagine prompt used, biome + character info, NPCs present, **crystal snippets used** (actual text, LOCKED/PROVISIONAL badge per crystal, SOVEREIGN-tier crystals highlighted in gold), crystal_domains_used

**Section C: Admin Actions**
- 5 buttons in a row:
  - "Assign Workbook" modal (user_id + storyboard dropdown, calls `POST /api/sse/admin/assign-workbook`)
  - "Backfill Single User" modal (user_id, calls `POST /api/sse/admin/backfill-intake/{user_id}`)
  - "Backfill All Users" confirm dialog (calls `POST /api/sse/admin/backfill-intake-all`)
  - "Generate Test Panel" modal (user_id, calls `POST /api/sse/thera-world/preview`, shows result)
  - "Journey Override" modal (user_id + action dropdown: force_biome_transition/pause_journey/resume_journey/reset_panel_sequence, calls `POST /api/sse/admin/journey/override`)

---

## Part B: Sovereign Vault -- SSE Panel Data

### B1. Client endpoint in [admin.py](backend/app/routers/admin.py) on `sse_client_router` (15 lines)

**`GET /api/sse-client/journey/panels`** -- returns panels + archetype + journey for authenticated user:

```python
@sse_client_router.get("/journey/panels")
async def sse_client_journey_panels(request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        journey = await conn.fetchrow("SELECT * FROM sse_user_journeys WHERE user_id=$1", uid)
        forge = await conn.fetchrow("SELECT archetype_hint, archetype_image_url, character_visual FROM sse_identity_forge WHERE user_id=$1", uid)
        panels = await conn.fetch(
            "SELECT panel_id, panel_type, r2_url, narrative_text, biome, character_manifest, panel_tone, generated_at, viewed_at "
            "FROM sse_panel_log WHERE user_id=$1 ORDER BY generated_at DESC LIMIT 100", uid)
    return {"journey": dict(journey) if journey else None,
            "archetype": dict(forge) if forge else None,
            "panels": [dict(p) for p in panels]}
```

### B2. Flutter -- intercept "Sovereign Journey" + SSE-aware Ask Nate in [vault_browser_screen.dart](mobile/lib/screens/vault_browser_screen.dart) (max 30 lines)

**Loading SSE panels**: In `_loadItems()`, detect "Sovereign Journey" folder and call the SSE endpoint:

```dart
final sjFolder = _folders.any((f) => f['id']?.toString() == folderId && f['name'] == 'Sovereign Journey');
if (sjFolder) {
  final sseUri = Uri.parse('$_baseUrl/api/sse-client/journey/panels');
  final sseResp = await http.get(sseUri, headers: _authHeaders());
  if (sseResp.statusCode == 200) {
    final data = jsonDecode(sseResp.body);
    final panels = (data['panels'] as List?) ?? [];
    setState(() => _items = panels.map((p) => <String, dynamic>{
      'id': p['panel_id'], 'name': (p['narrative_text'] ?? '').toString().length > 80
          ? p['narrative_text'].toString().substring(0, 80) + '...' : p['narrative_text'] ?? '',
      'thumbnail_url': p['r2_url'], 'file_url': p['r2_url'],
      'created_at': p['generated_at'], 'type': 'image',
      'dimensions': {'panel_type': p['panel_type'], 'biome': p['biome'],
                     'narrative': p['narrative_text'], 'is_sse_panel': true},
    }).toList());
    return;
  }
}
```

**SSE-aware "Ask Nate About This"**: The standard vault flow sends `[Vault:uuid]` which requires the item to be in `vault_items` table. SSE panels are in `sse_panel_log` instead. Override the `onAskNate` callback to detect SSE panels and send the narrative text directly:

```dart
onAskNate: () {
  Navigator.pop(ctx);
  final dims = item['dimensions'] as Map? ?? {};
  if (dims['is_sse_panel'] == true) {
    // SSE panel: send narrative + metadata as chat message instead of [Vault:uuid]
    final msg = '[Story Panel: ${dims['panel_type']}] ${dims['narrative'] ?? ''} '
                '(Biome: ${dims['biome']}, Character: ${item['name']})';
    Navigator.pop(context, msg);  // returned string becomes the chat message
  } else {
    Navigator.pop(context, item['id']?.toString());
  }
},
```

This way Little Nate receives the full narrative context of the panel in the chat message. Even without the image, he can discuss the therapeutic content. The image itself is in R2 at `item['file_url']` -- if we want Nate to see it too, the chat screen would need to fetch and attach it, which is a future enhancement.

### B3. Panel-viewed tracking: `POST /api/sse-client/panel/{panel_id}/viewed` in [admin.py](backend/app/routers/admin.py) (10 lines)

```python
@sse_client_router.post("/panel/{panel_id}/viewed")
async def sse_panel_viewed(panel_id: str, request: Request, _user: dict = Depends(_sse_auth)):
    uid = _user.get("user_id") or _user.get("username", "")
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE sse_panel_log SET viewed_at=now() WHERE panel_id=$1 AND user_id=$2 AND viewed_at IS NULL",
            panel_id, uid)
    return {"status": "viewed", "panel_id": panel_id}
```

Call this from Flutter when the user taps a panel to view it full-screen.

### B4. Migration 176 -- add viewed_at column

File: `backend/migrations/176_sse_panel_viewed.sql`

```sql
ALTER TABLE sse_panel_log ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_panel_log_viewed ON sse_panel_log(user_id, viewed_at) WHERE viewed_at IS NOT NULL;
```

---

## Part C: Fix Little Nate Image Inspection

### C0. PRE-BUILD VERIFICATION (REQUIRED -- pause here, share output)

Before modifying bridge_server.py, run these on the server and share the output:

```bash
# Find denial text
ssh root@68.183.168.75 "grep -n 'cannot.*view\|text-based.*model\|no.*capability.*image\|not.*visible\|liminal\|sight.*is' /opt/clinical-sovereignty-lab/backend/app/websocket/bridge_server.py | head -10"

# Check Grok model name (vision support depends on model)
ssh root@68.183.168.75 "grep -n 'model.*grok\|grok-3\|grok-2' /opt/clinical-sovereignty-lab/backend/app/websocket/bridge_server.py | head -5"
```

Wait for output before proceeding. The exact line numbers determine the surgical fix on this protected file.

### C1. Positive affirmation in system prompt -- [bridge_server.py](backend/app/websocket/bridge_server.py) (1 line)

Local grep returned 0 matches for denial text. The vision pipeline already works end-to-end: `bridge_server.py` creates `_vault_image_data_url` (line 7990), passes it to `_sovereign_stream(image_data_url=...)` (line 8309), and `sovereign_chat_client.py` builds a multimodal message with `image_url` block for Grok/Azure (lines 513-520).

The denial likely comes from LLM base behavior. The server grep (C0) will confirm whether there is explicit denial text on the deployed version. If found, replace it. If not found, add a positive affirmation after line ~8265:

```
        - When a user shares a photo, image, or video from their vault, you CAN see and engage with it. Describe what you notice, the emotions it evokes, and what it means for their journey. Never say you cannot view images — you have vision capability.
```

### C2. SSE panel "Ask Nate" -- handled in B2 above

SSE panels are NOT in `vault_items`, so the standard `[Vault:uuid]` lookup would fail. The fix in B2 sends the narrative text directly as a chat message. The panel's therapeutic content reaches Nate via text (the narrative IS the therapeutic content). The image itself would need the R2 URL fetched and converted to base64 for vision -- this is a future enhancement since the narrative text provides 90% of the value.

### C3. When Nate cannot see the image (non-vision provider fallback)

If the inference routes to Workers AI (non-vision), the `image_data_url` is silently dropped (sovereign_chat_client.py only builds multimodal messages for azure/grok, lines 513-520). In this case, Nate receives only the text context. With the positive affirmation in the prompt, he should acknowledge what was shared based on the `[VAULT IMAGE]` context text rather than deny seeing it.

---

## Part D: Fix Response Time and Cutoff

### D1. Increase max_tokens -- [bridge_server.py](backend/app/websocket/bridge_server.py) (3 lines changed)

- Line 8307: `max_tokens=300` to `max_tokens=1500`
- Line 8334: `max_tokens=300` to `max_tokens=1500`
- Line 8348: `max_tokens=150` to `max_tokens=1500`

Total bridge_server.py changes: **4 lines** (3 max_tokens + 1 system prompt affirmation). Within the 5-line protected budget.

### D2. Cache story context -- [layer6_crystal_bridge.py](backend/app/sse/layer6_crystal_bridge.py) (5 lines)

Add in-memory cache with 5-minute TTL to eliminate 3 DB queries per chat message:

```python
_story_ctx_cache: dict = {}
_STORY_CTX_TTL = 300

# At top of get_user_story_context(), before the try block:
    import time as _t
    _cached = _story_ctx_cache.get(user_id)
    if _cached and _t.time() - _cached[1] < _STORY_CTX_TTL:
        return _cached[0]

# At bottom, before return:
    _story_ctx_cache[user_id] = (ctx if ctx else None, _t.time())
```

### D3. Trim story narrative -- [littlenate_inference.py](backend/app/services/littlenate_inference.py) (2 lines, PROTECTED -- 16/20 used, 2 more = 18/20)

The `[STORY JOURNEY]` block at line 354-357 includes the full narrative text. Shorten to a 1-sentence summary:

```python
# Change line 354-357 from:
f"[STORY JOURNEY]\nThis person is on a healing journey. Their current story phase is "
f"'{story_context['phase_id']}' — {story_context.get('narrative', '')}. "
f"You may gently reference their story journey if it connects naturally to what they're sharing. "
f"Do not force story references. Let the conversation lead.\n"

# To (2 lines):
f"[STORY JOURNEY] Phase: {story_context['phase_id']}. "
f"Biome: {story_context.get('biome', 'dark_forest')}. Reference gently if relevant.\n"
```

This cuts ~200 chars per message while preserving the key info.

### D4. Monitor prompt size (verification only, no code)

After deploy:
```bash
ssh root@68.183.168.75 "docker logs nate_backend --tail 200 2>&1 | grep 'SYSTEM PROMPT\|PROMPT CAP'"
```

If prompts are being capped at 12k chars, the story context is competing with the therapy prompt for space. The D3 trim should resolve this.

---

## Part E: Manual Journey Intervention

### E1. Override endpoint in [admin.py](backend/app/routers/admin.py) on `sse_router` (15 lines)

```python
@sse_router.post("/admin/journey/override")
async def sse_journey_override(request: Request, _=Depends(require_admin)):
    body = await request.json()
    uid, action = body["user_id"], body["action"]
    pool = request.app.state.db_pool
    async with pool.acquire() as conn:
        if action == "force_biome_transition":
            new_biome = body.get("target_biome", "fortress_plains")
            await conn.execute("UPDATE sse_user_journeys SET current_biome=$1, panel_sequence=0 WHERE user_id=$2", new_biome, uid)
        elif action == "pause_journey":
            await conn.execute("UPDATE sse_user_journeys SET journey_metadata = journey_metadata || '{\"paused\": true}'::jsonb WHERE user_id=$1", uid)
        elif action == "resume_journey":
            await conn.execute("UPDATE sse_user_journeys SET journey_metadata = journey_metadata - 'paused' WHERE user_id=$1", uid)
        elif action == "reset_panel_sequence":
            await conn.execute("UPDATE sse_user_journeys SET panel_sequence=0 WHERE user_id=$1", uid)
        await conn.execute("INSERT INTO sse_admin_alerts (user_id, alert_type, title, detail) VALUES ($1, 'admin_override', 'Journey Override', $2)", uid, action)
    return {"status": "ok", "action": action, "user_id": uid}
```

### E2. Dashboard "Journey Override" button in Admin Actions section

Modal with: user_id text field, action dropdown (force_biome_transition with target_biome sub-field, pause_journey, resume_journey, reset_panel_sequence), confirm button. Success toast with action + user_id.

---

## Part F: Panel Feedback Loop

When a user VIEWS a panel (B3 endpoint) and then discusses it with Nate, the conversation gets crystallized with `panel_id` as metadata. This closes the loop: crystals inform panels, user views panel, user discusses panel, new crystals form.

The crystallization already happens via the standard `crystallize_from_conversation()` in `bridge_server.py`. The missing piece is tagging which panel was being discussed. This requires:

1. **Panel-viewed endpoint** (B3 above) marks the panel as viewed
2. **Flutter sends panel context** (B2 above) when "Ask Nate About This" is used
3. **Crystallization tagging** (deferred to Phase 3B): when a conversation message contains `[Story Panel: ...]`, the crystallizer should extract the panel_type and store it in crystal metadata. This ensures crystals born from panel discussions are traceable back to the panel.

The minimum viable loop for Phase 3: B3 marks viewed, B2 sends narrative to chat, standard crystallization stores the conversation. The panel_id tagging in crystal metadata is Phase 3B.

---

## Migration Summary

**176_sse_panel_viewed.sql** (new):
```sql
ALTER TABLE sse_panel_log ADD COLUMN IF NOT EXISTS viewed_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_panel_log_viewed ON sse_panel_log(user_id, viewed_at) WHERE viewed_at IS NOT NULL;
```

---

## Files Changed Summary

| File | Changes | Lines |
|---|---|---|
| `backend/app/routers/admin.py` | +users-summary, +preview, +journey/panels, +panel-viewed, +journey-override | ~55 |
| `backend/app/sse/thera_world_engine.py` | expand get_user_sse_status() with crystal health, cycles, coherence | ~20 |
| `backend/app/websocket/bridge_server.py` | +image affirmation (1), max_tokens x3 (3) | 4 (PROTECTED) |
| `backend/app/services/littlenate_inference.py` | trim [STORY JOURNEY] to 1-line | 2 (PROTECTED, 18/20) |
| `backend/app/sse/layer6_crystal_bridge.py` | +TTL cache | ~5 |
| `dashboard/sse_monitoring.html` | +alerts, +explorer (with crystal/coherence/cycles), +admin actions (5 buttons) | ~500 |
| `mobile/lib/screens/vault_browser_screen.dart` | intercept SJ folder + SSE Ask Nate flow + panel-viewed call | ~30 |
| `backend/migrations/176_sse_panel_viewed.sql` | +viewed_at column + index | 2 |

## Deploy Sequence

1. `scp` migration 176 to GREEN, run it via `nate_backend` asyncpg
2. `scp` backend files: `admin.py`, `thera_world_engine.py`, `layer6_crystal_bridge.py`, `littlenate_inference.py`, `bridge_server.py`
3. `scp` `sse_monitoring.html` to both `/opt/clinical-sovereignty-lab/dashboard/` and `/var/www/sovereign-command/`
4. Restart backend and bridge, verify 104/104
5. `flutter build web --release`, deploy to `app.sovereignsanctuary.net`
6. Verify:
   - SSE Monitor: alerts feed loads, user search works, profile shows crystal health + coherence + cycles, panel detail shows crystal snippets
   - Vault: Sovereign Journey tab shows SSE panels chronologically
   - Ask Nate: share a panel, Nate discusses therapeutic content
   - Image: share a regular vault image, Nate engages (no denial)
   - Response: under 5 seconds, no mid-sentence cutoff
   - Override: force biome transition, pause/resume journey
   - Feedback: panel-viewed endpoint marks viewed_at
