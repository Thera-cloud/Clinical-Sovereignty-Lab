---
name: Group Entity Video Architecture
overview: "Migrate the SSE delivery pipeline from xAI Grok Imagine (no LoRA support) to Replicate Flux (LoRA-enabled), then build the group entity layer: DB tables, group LoRA folder manager, participation tracker, group video generator, monthly cron integration, and BLE/NFC auto-enrollment."
todos:
  - id: section2-lora-resolver
    content: Create get_lora_ref() helper in lora_resolver.py and migrate delivery_runtime.py from Grok Imagine to Replicate Flux for daily panels, weekly clips, monthly recaps
    status: pending
  - id: section3-migration
    content: Create migration 180_group_entities.sql with group_entities, group_entity_members, group_videos tables + ALTER families/corporate_sponsors
    status: pending
  - id: section4-group-lora-manager
    content: Create GroupLoRAFolderManager with compile/sync/get/on_member_updated methods in group_lora_manager.py
    status: pending
  - id: section5-participation
    content: Create get_group_participation() function in participation_tracker.py querying session logs for active vs background members
    status: pending
  - id: section6-group-video-gen
    content: Create GroupVideoGenerator with generate_monthly_group_video() entry point (Replicate image -> Grok Video animation -> R2 store -> deliver)
    status: pending
  - id: section7-cron
    content: Add _run_group_videos handler to layer0_orchestrator.py, scheduled after individual monthly recaps
    status: pending
  - id: section8-ble-enrollment
    content: Add auto-enrollment to group_entities from ble_co_traveler.py and community_mesh_engine.py proximity events
    status: pending
isProject: false
---

# Group Entity Video Architecture

## Section 1 Audit Findings

### Where `lora_model_ref` lives today

- **DB table**: `character_lora_models` (migration 179) with columns `model_id`, `character_key`, `user_id`, `lora_weights_url`, `trigger_word`, `base_model`, `training_steps`, `status`, `metadata`, `created_at`
- **Registry adapter**: [lora_registry.py](backend/app/sse/adapters/lora_registry.py) -- `register_lora()`, `resolve_lora()`, `list_loras()`, `deactivate_lora()` against `character_lora_models`
- **UCD directive**: [creative_directive.py](backend/app/sse/ucd/creative_directive.py) -- `lora_model_ref` field on `CreativeDirective` dataclass, written to `ucd_creative_directives` table
- **R2 paths**: `sse/studio/projects/{project_id}/lora/{character}/train_*.png` and `*_training.zip` in [trailer_generator.py](backend/app/sse/trailer_generator.py)
- **API layer**: [replicate_client.py](backend/app/sse/infrastructure/replicate_client.py) -- `generate_with_loras(prompt, lora_urls, lora_scales)` calls Replicate Flux with `hf_loras`

### Gaps flagged (ALL generation calls missing LoRA)

| Generator | File:Line | API Used | LoRA Passed? |
|-----------|-----------|----------|-------------|
| `generate_daily_panels` | delivery_runtime.py:73 | `grok.generate_image(prompt)` | NO |
| `generate_weekly_clips` | delivery_runtime.py:113 | `grok.generate_video(prompt, src_url)` | NO |
| `generate_monthly_recap` | delivery_runtime.py:152 | `grok.generate_video(prompt)` | NO |
| `check_and_recover_gaps` | delivery_runtime.py:185 | `grok.generate_image(...)` | NO |
| `generate_from_directive` | delivery_runtime.py:225,257 | `grok.generate_image(prompt)` | NO |

**Root cause**: `grok_imagine_client.py` has no LoRA parameter -- xAI API does not support it. LoRA generation is exclusively on Replicate Flux via `replicate_client.generate_with_loras()`.

---

## Section 2 -- Fix LoRA Gaps (Migrate to Replicate Flux)

### 2a. Create `get_lora_ref(user_id, db_pool)` helper

New file: `backend/app/sse/adapters/lora_resolver.py`

```python
async def get_lora_ref(user_id: str, db_pool) -> Optional[str]:
    """Resolve user_id to their active LoRA weights URL.
    
    1. Query character_lora_models WHERE user_id = $1 AND status = 'active'
    2. Return lora_weights_url if found
    3. Return None with warning log if missing
    """
```

- Uses `lora_registry.resolve_lora()` internally but keyed by `user_id` not `character_key`
- Add a secondary lookup path: `resolve_lora` by `character_key` where `character_key` matches `user_id` pattern
- Log `logger.warning("No active LoRA for user %s -- skipping generation", user_id)` when None
- R2 path verification is deferred to Section 4 (group context); for individual resolution, trust the DB URL

### 2b. Migrate `generate_daily_panels`

In [delivery_runtime.py](backend/app/sse/foundation/delivery_runtime.py):

- Add import: `from app.sse.infrastructure import replicate_client`
- Add import: `from app.sse.adapters.lora_resolver import get_lora_ref`
- Before the prompt construction (line ~69), call `lora_url = await get_lora_ref(uid, db_pool)`
- If `lora_url is None`: log warning, skip this user, continue
- Replace `grok.generate_image(prompt)` with:

```python
image_urls = await replicate_client.generate_with_loras(
    prompt, lora_urls=[lora_url], lora_scales=[0.8])
# Download first image URL to bytes for R2 storage
img = await _download_image(image_urls[0])
```

- Add `_download_image(url) -> bytes` helper (aiohttp GET, return bytes)
- Update `_IMG_COST` constant or add `_REPLICATE_IMG_COST` for cost logging accuracy

### 2c. Migrate `generate_weekly_clips`

- Same `get_lora_ref` guard before generation
- Image-to-video stays on xAI Grok Video (it takes a source image URL, no LoRA needed at video step)
- The source image (`src["r2_url"]`) was generated by daily panels which now use Replicate+LoRA
- No change to `grok.generate_video()` call -- the LoRA identity is baked into the source image

### 2d. Migrate `generate_monthly_recap`

- Add `get_lora_ref` guard
- Current flow generates text-only video (no source image). Change to:
  1. Generate a recap scene image via `replicate_client.generate_with_loras(recap_prompt, [lora_url])`
  2. Pass that image URL to `grok.generate_video(prompt, source_image_url=recap_image_url)`
- This matches the user's chosen approach: Replicate Flux (image) then xAI Grok Video (animation)

### 2e. Migrate `generate_from_directive` and `check_and_recover_gaps`

- Same pattern: `get_lora_ref` guard, skip on None, use `replicate_client.generate_with_loras`
- Gap recovery summary images remain on Grok (non-personalized, acceptable)

### 2f. Update `grok_imagine_client.py` header

Add docstring note: "NOT used for personalized/LoRA generation. Kept for non-personalized admin preview and gap recovery summaries only."

---

## Section 3 -- Group Entity Tables

### Migration: `180_group_entities.sql`

```sql
CREATE TABLE IF NOT EXISTS group_entities (
    group_entity_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_type        VARCHAR(50) NOT NULL,
    group_name        VARCHAR(255),
    lora_folder_path  TEXT,
    scene_context     VARCHAR(100),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS group_entity_members (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_entity_id   UUID REFERENCES group_entities(group_entity_id),
    client_id         UUID NOT NULL,
    joined_at         TIMESTAMPTZ DEFAULT NOW(),
    lora_snapshot_path TEXT,
    is_active         BOOLEAN DEFAULT TRUE,
    UNIQUE(group_entity_id, client_id)
);

CREATE TABLE IF NOT EXISTS group_videos (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_entity_id   UUID REFERENCES group_entities(group_entity_id),
    month             INT NOT NULL,
    year              INT NOT NULL,
    video_url         TEXT,
    generated_at      TIMESTAMPTZ DEFAULT NOW(),
    status            TEXT DEFAULT 'pending',
    error_message     TEXT,
    UNIQUE(group_entity_id, month, year)
);

-- Link existing families table
ALTER TABLE families ADD COLUMN IF NOT EXISTS
    group_entity_id UUID REFERENCES group_entities(group_entity_id);

-- Link existing corporate_sponsors table
ALTER TABLE corporate_sponsors ADD COLUMN IF NOT EXISTS
    group_entity_id UUID REFERENCES group_entities(group_entity_id);

CREATE INDEX IF NOT EXISTS idx_gem_group ON group_entity_members(group_entity_id);
CREATE INDEX IF NOT EXISTS idx_gem_client ON group_entity_members(client_id);
CREATE INDEX IF NOT EXISTS idx_gv_group_month ON group_videos(group_entity_id, year, month);
```

`group_type` is VARCHAR, not enum -- new types addable without migration.

---

## Section 4 -- Group LoRA Folder Manager

### New file: `backend/app/sse/adapters/group_lora_manager.py`

Four methods as specified:

**`compile_group_lora_folder(group_entity_id, db_pool)`**
- Query `group_entity_members WHERE group_entity_id = $1 AND is_active = true`
- For each member: `get_lora_ref(client_id, db_pool)` -- skip members without LoRA
- R2 folder path: `groups/{group_entity_id}/lora/`
- For each member with LoRA: copy/upload their weights reference into the group folder as `{group_entity_id}/lora/{client_id}.safetensors` (or store the URL manifest as JSON)
- Update `group_entity_members.lora_snapshot_path` for each member
- Update `group_entities.lora_folder_path` and `updated_at`

**`sync_group_lora_folder(group_entity_id, db_pool)`**
- Compare each member's current `get_lora_ref()` against stored `lora_snapshot_path`
- Only recompile changed members' slots

**`get_group_lora_folder(group_entity_id, db_pool) -> list[str]`**
- Returns the list of LoRA URLs for all active members (for passing to `generate_with_loras` `lora_urls` parameter)
- If folder stale or missing, triggers `compile_group_lora_folder` first
- Note: Replicate Flux supports up to 4 `hf_loras` simultaneously (line 123 of `replicate_client.py`: `hf_loras = lora_urls[:4]`). Groups larger than 4 members will need batched scene composition or a different approach

**`on_member_lora_updated(client_id, db_pool)`**
- Query `group_entity_members WHERE client_id = $1 AND is_active = true`
- Call `sync_group_lora_folder` for each affected group

### 4-member LoRA limit

`replicate_client.generate_with_loras` caps at 4 LoRA URLs (line 123). For groups > 4, the manager will:
- Prioritize active members (foreground) over background members
- Generate in batches if needed, compositing results
- Log a warning when group exceeds 4 active LoRA-enabled members

---

## Section 5 -- Participation Tracker

### New file: `backend/app/sse/adapters/participation_tracker.py`

```python
async def get_group_participation(
    group_entity_id: str, month: int, year: int, db_pool
) -> dict:
    """Returns {active_members: [...], background_members: [...]}"""
```

- Query active members from `group_entity_members`
- For each member, check session activity in the given month across:
  - `family_sanctuary_sessions` + `sanctuary_members` (family context)
  - `community_sessions` / `community_attendance_records` (BLE/NFC)
  - `coaching_mesh_sessions` / `coaching_mesh_participants` (group coaching)
  - `sessions` with `session_type = 'GROUP'` (general group sessions)
- Members with any group-context session = `active_members`
- Members with zero group sessions (including those with individual-only sessions) = `background_members`
- Members with `is_active = false` are excluded entirely

---

## Section 6 -- Group Video Generator

### New file: `backend/app/sse/group_video_generator.py`

Single entry point: `generate_monthly_group_video(group_entity_id, month, year, db_pool)`

**Step 1 -- Load context**
- Read `group_type`, `scene_context` from `group_entities`
- `lora_urls = await get_group_lora_folder(group_entity_id, db_pool)`
- `participation = await get_group_participation(group_entity_id, month, year, db_pool)`

**Step 2 -- Generate base scene image (Replicate Flux)**
- Build prompt with `scene_context` and placement directives:
  - Active members: "foreground, visible, engaged"
  - Background members: "midground/background, present, not dominant"
- Call `replicate_client.generate_with_loras(prompt, lora_urls, lora_scales=[0.8]*len(lora_urls))`
- Handle the 4-LoRA cap: if > 4 members have LoRA, split into foreground (active, up to 4) and generate background members separately, then composite

**Step 3 -- Animate to video (xAI Grok Video)**
- Download the Replicate output image
- Upload to R2 as temp source
- Call `grok.generate_video(animation_prompt, source_image_url=temp_r2_url)`
- Poll with `_poll_video()`
- Duration/style varies by `group_type` (warm/intimate for family, grounded for therapy, etc.)

**Step 4 -- Store and deliver**
- R2 path: `groups/{group_entity_id}/videos/{year}-{month:02d}-monthly.mp4`
- Insert into `group_videos` table
- Deliver to all active members via their existing SSE delivery channels (insert rows into `sse_delivery_generation_log` with `generation_type='group_video'` per member)

---

## Section 7 -- Monthly Cron Integration

### Modify [layer0_orchestrator.py](backend/app/sse/layer0_orchestrator.py)

Add new handler `_run_group_videos` that:
1. Queries `group_entities` for all groups with active members
2. For each group: `sync_group_lora_folder` then `generate_monthly_group_video`
3. Runs AFTER individual monthly recaps complete (not blocking them)

Register as a new fixed job in `start()`:
```python
self.scheduler.add_job(
    self._run_group_videos,
    CronTrigger(minute=0, hour=6, day="28-31", month="*"),
    id="group_monthly_videos",
)
```

This fires at 6 AM on month-end days, after the monthly recap cron at 5 AM.

---

## Section 8 -- BLE/NFC Auto-Enrollment

### Modify [ble_co_traveler.py](backend/app/sse/ble_co_traveler.py) and [community_mesh_engine.py](backend/app/services/community_mesh_engine.py)

In `process_proximity_event`:
- After recording the co-traveler event, check if a `group_entity` exists for this family (`SELECT group_entity_id FROM families WHERE id = $1`)
- If not, create one with `group_type='ble_proximity'`, `scene_context='family_sanctuary'`
- Ensure both `user1_id` and `user2_id` are in `group_entity_members` (INSERT ON CONFLICT DO NOTHING)
- Call `compile_group_lora_folder` if this is the first member, or `sync_group_lora_folder` if adding to existing

In `community_mesh_engine.record_session`:
- After recording a community session, check/create `group_entity` with `group_type='ble_proximity'`
- Add participants to `group_entity_members`

---

## Files Created/Modified Summary

| Action | File |
|--------|------|
| CREATE | `backend/app/sse/adapters/lora_resolver.py` |
| CREATE | `backend/app/sse/adapters/group_lora_manager.py` |
| CREATE | `backend/app/sse/adapters/participation_tracker.py` |
| CREATE | `backend/app/sse/group_video_generator.py` |
| CREATE | `backend/migrations/180_group_entities.sql` |
| MODIFY | `backend/app/sse/foundation/delivery_runtime.py` (migrate to Replicate) |
| MODIFY | `backend/app/sse/infrastructure/grok_imagine_client.py` (header note) |
| MODIFY | `backend/app/sse/layer0_orchestrator.py` (group cron) |
| MODIFY | `backend/app/sse/ble_co_traveler.py` (auto-enrollment) |
| MODIFY | `backend/app/services/community_mesh_engine.py` (auto-enrollment) |

## Critical Constraints

- `replicate_client.generate_with_loras` caps at 4 LoRA URLs. Groups > 4 need batched composition.
- Missing LoRA = skip + warn, never generate generic. Enforced in `get_lora_ref`.
- Group LoRA folder compiled once, synced on changes. Never rebuilt per-generation.
- Individual and group monthly videos are always separate artifacts.
- `group_type` is VARCHAR, extensible without migration.
- All R2 paths verified before return from any function.
