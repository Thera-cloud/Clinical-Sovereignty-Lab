# SSE Image & Video Generation Audit — 2026-05-07

## Summary

9 artifact types identified. 1 ALIGNED, 3 PARTIAL, 5 MISSING.

---

## 1. Journey Panels (Baseline — ALIGNED)

**A — Generator**: `thera_world_engine.py:563` → `generate_journey_panel()`. Inputs: `user_id`, `db_pool`.

**B — History**: Queries `nate_intelligence_crystals` (top 5 domains, 5 recent texts), `conversation_history` (session count), `sse_identity_forge` (intake themes for thin users), active quests/missions. Also enriches with coaching calibration, assessment calibration, and family context.

**C — Narrative**: LLM-composed via `compose_journey_narrative()` (:237). Separate `narrative_text` and `image_prompt`. Stored in `sse_panel_log.narrative_text`. Client API reads `narrative_text` directly.

**D — Anti-repetition**: Yes. Uses `last_panel_summary`, `last_panel_npcs`, `panel_sequence` from `sse_user_journeys`. Continuity block in LLM prompt references previous scene.

**E — Attunement**: Crystal domains, biome progression (session count + crystal count thresholds), character manifestation from dominant domain, coherence trend for couples, age gating, coach pacing/hold overrides, assessment risk flags.

**F — Classification: ALIGNED**

---

## 2. Daily Panels (Post-Fix — PARTIAL)

**A — Generator**: `delivery_runtime.py:68` → `generate_daily_panels()`. Inputs: `storyboard_id`, `db_pool`.

**B — History**: Calls `build_rich_panel_prompt()` which queries same crystal/session/intake/coaching/assessment data as journey panels.

**C — Narrative**: `build_rich_panel_prompt()` returns `narrative_text`. Stored in `sse_delivery_generation_log.client_narrative_text` (migration 200). Client API uses `COALESCE(client_narrative_text, fallback_blurb)`. Pre-fix rows lack `client_narrative_text` → safe generic fallback.

**D — Anti-repetition**: Inherits from `build_rich_panel_prompt()` → `compose_journey_narrative()` which reads `last_panel_summary` and `panel_sequence`. One panel per user per day dedup.

**E — Attunement**: Same enrichment pipeline as journey panels (crystal domains, coaching calibration, assessment, family context) via `build_rich_panel_prompt()`.

**F — Classification: PARTIAL** — History and attunement are present. Narrative is generated. Gap: daily panel does NOT update `sse_user_journeys.last_panel_summary` / `panel_sequence` after generation, so the next daily panel's continuity block may be stale (only journey panels update this).

---

## 3. Weekly Clips (Video — PARTIAL)

**A — Generator**: `delivery_runtime.py:158` → `generate_weekly_clips()`. Inputs: `storyboard_id`, `db_pool`.

**B — History**: Selects best daily panel image from the week as video source. Calls `build_rich_panel_prompt()` post-generation for narrative only.

**C — Narrative**: `client_narrative_text` populated via `build_rich_panel_prompt()` after video generation. Stored in `sse_delivery_generation_log.client_narrative_text`.

**D — Anti-repetition**: No explicit check on prior weekly clip narratives. Each week generates fresh.

**E — Attunement**: Video prompt is generic (`"Weekly therapeutic clip for {phase}"`). The image it animates inherits the daily panel's attunement. The narrative text IS attuned (via `build_rich_panel_prompt`).

**F — Classification: PARTIAL** — Narrative is attuned, but video prompt itself is generic. No anti-repetition on weekly narratives.

---

## 4. Monthly Recap (Video — PARTIAL)

**A — Generator**: `delivery_runtime.py:235` → `generate_monthly_recap()`. Inputs: `storyboard_id`, `db_pool`.

**B — History**: Checks monthly clip/panel counts. Uses archetype ref image for video.

**C — Narrative**: `client_narrative_text` populated via `build_rich_panel_prompt()`. Stored in `sse_delivery_generation_log.client_narrative_text`.

**D — Anti-repetition**: None. Monthly recap generates one per month.

**E — Attunement**: Video prompt is generic (`"Monthly therapeutic recap — three-act structure"`). Narrative text IS attuned.

**F — Classification: PARTIAL** — Same pattern as weekly clips. Narrative is attuned but video prompt is generic.

---

## 5. Quest Images — MISSING

**A — Generator**: `quest_mission_engine.py:236` → `compose_quest_panel()`. Inputs: `user_id`, `quest`, `profile`, `journey`, `db_pool`.

**B — History**: Reads quest NPCs from `progress_notes` JSON. Uses biome and character from profile.

**C — Narrative**: Returns hardcoded template: `"In the {biome}, the quest for {goal} continues."` No LLM generation. Comment: `# TODO Phase 3: LLM-composed quest panels with arc awareness`.

**D — Anti-repetition**: None. Same template every time.

**E — Attunement**: Biome and character from crystal domains, NPC visual fragments from crystal clusters. But no coaching/assessment/emotional state integration.

**F — Classification: MISSING** — Template narrative, no LLM, no Little Nate voice, no anti-repetition. Image prompt uses NPC fragments but no emotional attunement.

---

## 6. Mission Images — MISSING

**A — Generator**: `quest_mission_engine.py:256` → `compose_mission_panel()`. Inputs: `user_id`, `mission`, `profile`, `journey`, `db_pool`.

**B — History**: Uses biome and character. Does NOT read mission-specific crystal clusters or progress.

**C — Narrative**: Hardcoded template: `"In the {biome}, the relational journey with {target} deepens."` Comment: `# TODO Phase 3: LLM-composed mission panels`.

**D — Anti-repetition**: None.

**E — Attunement**: Only biome + character. No emotional state, no coaching calibration.

**F — Classification: MISSING** — Same gaps as quest panels, plus ignores mission crystal analysis entirely.

---

## 7. Workbook Prompts/Images — NOT APPLICABLE

**A — Generator**: `workbook_ingestion.py:16` → `ingest_workbooks()`. This is a Night School knowledge crystallizer, not a client-facing image generator. Reads protocol workbook text files and stores them as global crystals.

No image or video generation. No client-facing narrative. Not an SSE artifact type.

**F — Classification: N/A** — No imagery generated.

---

## 8. UCD-Driven Panels — PARTIAL (post-fix)

**A — Generator**: `delivery_runtime.py:317` → `generate_from_directive()`. Inputs: `user_id`, `directive` dict, `db_pool`.

**B — History**: Calls `build_rich_panel_prompt()` for panel/journal_prompt modalities. Coherence context from directive.

**C — Narrative**: `client_narrative_text` populated from `build_rich_panel_prompt()`. Stored in `sse_delivery_generation_log.client_narrative_text`.

**D — Anti-repetition**: None explicit. UCD directives are event-driven (TMC temporal moments), so repetition is structurally less likely.

**E — Attunement**: Image prompt is generic (`"Therapeutic {modality} for moment: {moment_class}"`). Narrative IS attuned via `build_rich_panel_prompt`. Coherence context from directive adds some signal.

**F — Classification: PARTIAL** — Same split: narrative attuned, image prompt generic.

---

## 9. Other Client-Facing Generated Imagery

### 9a. Storyboard Panel Images (Imagination Engine) — MISSING

`layer6_imagination_engine.py:61` → `generate_story_imagery()`. Generates images for story_plot panels from Stage 1 (story plot generator). Uses pre-built `grok_imagine_prompt` from the story plot JSON. No per-client history, no narrative text, no emotional attunement. These are workbook-level static images, not client-personalized.

### 9b. Identity Forge (Archetype Image) — N/A

`layer1_identity_forge.py` generates the client's archetype reference image during intake. One-time, not a recurring panel. Not exposed via journey/panels endpoint.

### 9c. Hero Video / Trailer — N/A

`hero_video_generator.py`, `trailer_generator.py`, `group_video_generator.py` — marketing/landing page assets. Not client-facing therapeutic content.

### 9d. Check-In Panels — MISSING

`sse_client_checkin` endpoint (:5647 in admin.py) returns a text message only — no imagery generated. If check-ins generate imagery in the future, they would need the full pipeline.

---

## Gap Summary

| # | Artifact | History | Narrative | Anti-Rep | Attunement | Classification |
|---|----------|---------|-----------|----------|------------|----------------|
| 1 | Journey panels | ✅ | ✅ LLM | ✅ | ✅ | **ALIGNED** |
| 2 | Daily panels | ✅ | ✅ LLM | ⚠️ stale continuity | ✅ | **PARTIAL** |
| 3 | Weekly clips | ⚠️ image only | ✅ LLM | ❌ | ⚠️ narrative only | **PARTIAL** |
| 4 | Monthly recap | ⚠️ counts only | ✅ LLM | ❌ | ⚠️ narrative only | **PARTIAL** |
| 5 | Quest images | ⚠️ NPCs only | ❌ template | ❌ | ⚠️ biome+char only | **MISSING** |
| 6 | Mission images | ⚠️ minimal | ❌ template | ❌ | ⚠️ biome+char only | **MISSING** |
| 7 | Workbook images | N/A | N/A | N/A | N/A | **N/A** |
| 8 | UCD panels | ✅ | ✅ LLM | ❌ | ⚠️ narrative only | **PARTIAL** |
| 9a | Storyboard images | ❌ | ❌ | ❌ | ❌ | **MISSING** |

## Priority Remediation

1. **Quest + Mission panels** — Replace template fallbacks with `compose_journey_narrative()` or equivalent LLM call. Wire crystal cluster data into the prompt. Highest impact: these are the most client-interactive artifacts.
2. **Daily panel continuity** — After `generate_daily_panels`, update `sse_user_journeys.last_panel_summary` and `panel_sequence` so the next panel's continuity block stays fresh.
3. **Video prompt enrichment** — Weekly clips and monthly recaps use generic video prompts. Enrich with biome/character/emotional context even though the video API has limited prompt influence.
4. **Anti-repetition for delivery_runtime** — Check recent `client_narrative_text` values before generating new ones to avoid narrative repetition across daily/weekly/monthly.
