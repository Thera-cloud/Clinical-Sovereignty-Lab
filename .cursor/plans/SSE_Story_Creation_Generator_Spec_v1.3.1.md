# SSE Story Creation Generator
## System Specification v1.3.1
### Sovereign Story Engine — Automated Story Plot Development & Delivery Pipeline
### All-In-One: Authoring + Video Generation + Runtime Delivery + Progressive Recovery
### Changelog: v1.3 → v1.3.1 — Progressive Recovery Protocol, concurrency semaphore, cost circuit breaker, dependency chain validation, delivery health heartbeat
### Previous: v1.1 → v1.2 — Pipeline concurrency, batched imagery, IP assignment
### Previous: v1.0 → v1.1 — Age-gating, conflict detection, multi-admin, space collision, rollback safety, cost guardrails, sunset, IP logging, preview mode, localization

---

## Overview

The Story Creation Generator is the single system that authors, validates, generates imagery and video for, and deploys therapeutic storyboards into the Sovereign Story Engine. Once a storyboard is approved, this same system defines and runs the delivery pipeline — daily static panels, weekly video clips, and monthly recap videos — for every enrolled user.

**Core Principle:** One system authors it. One system delivers it. Write the vision, approve the output, and the SSE runs it forever.

**What This System Does:**
1. Accepts a story document (any format) and parses it into a full SSE storyboard
2. Generates all static imagery AND sample video clips
3. Presents everything for admin review with interactive preview
4. On approval, deploys to R2 and activates the runtime delivery pipeline
5. Runs daily/weekly/monthly content generation on schedule for every enrolled user
6. Monitors engagement, manages versions, handles seasonal activation/sunset

---

## System Architecture

```
Admin or Coach uploads story document
        ↓
PIPELINE LOCK CHECK
  Single pipeline at a time (Redis + PostgreSQL dual-write)
        ↓
IP ASSIGNMENT GATE
  Coach/supervisor: mandatory acknowledgment
  Admin: implicit
        ↓
Step 0: IP LOGGING & PROVENANCE
  Immutable audit trail: author, timestamp, source hash, IP assignment
        ↓
Step 1: REVIEW & PARSE
  Crystal Intelligence analyzes document
  Extracts: phases, characters, spaces, biomes, world events
  Cross-reference + similarity check against existing library
  Age-tier analysis + conflict detection
  NEW v1.3: Video scene extraction (motion prompts, audio profiles, clip chains)
        ↓
Step 2: METADATA + DELIVERY DEFINITION
  Auto-generates story plot JSON with full phase definitions
  NEW v1.3: Generates video delivery config (daily/weekly/monthly cadence)
  NEW v1.3: Defines clip chain structures for weekly and monthly recaps
  NEW v1.3: Audio profile per biome and sacred space
  NEW v1.3: Cost projection per user per month
  Localization-ready text separation
  Age-variant scene generation
        ↓
Step 3: IMAGERY + VIDEO GENERATION (BATCHED)
  Batch 1-N: Static images (5-10 per batch, verified before next)
  NEW v1.3: Batch N+1: Sample video clips (1 per biome, 10s each)
  NEW v1.3: Sample monthly recap clip (30s preview, 3 chained clips)
  All batches verified → proceed to Step 4
  NEW v1.3: Staging write to R2 after each verified batch (crash recovery)
        ↓
Step 4: ADMIN REVIEW
  Static imagery gallery + NEW v1.3: video playback preview
  NEW v1.3: Delivery cadence configuration (admin can adjust daily/weekly/monthly)
  NEW v1.3: Per-user monthly cost projection displayed
  NEW v1.3: Video quality review with regeneration option
  Age-tier content map, conflict report, similarity report
  Preview Mode (static + animated walkthrough)
  Admin actions: approve, edit, delete, save, run-cycle, sunset
        ↓
Step 5: DEPLOYMENT
  R2 upload (staging → production promotion, transactional)
  Version control + active user version-pinning
  IP provenance finalization
  NEW v1.3: Delivery pipeline config deployed to Layer 0
  NEW v1.3: Cron schedules registered for daily/weekly/monthly generation
        ↓
Step 6: ACTIVATION + RUNTIME DELIVERY
  Layer 0 loads storyboard + delivery config
  Clinical eligibility gate for enrollment
  NEW v1.3: Delivery Pipeline Runtime begins executing:
    - Daily: static panel generation for each enrolled user
    - Weekly (weeks 1-3): 10s animated clip per user
    - Monthly (week 4): 2-min recap video per user
  Live monitoring dashboard
  Pipeline lock released → next queued storyboard can process
```

---

## Steps 0-1: Unchanged from v1.2

See v1.2 spec for:
- Step 0: IP Assignment Gate, Pipeline Concurrency Lock, Provenance Logging
- Step 1: Review & Parse (narrative extraction, therapeutic framework detection, world-building extraction, cross-reference, similarity check, age-tier analysis, conflict detection)

### Step 1 Addition (v1.3): Video Scene Extraction

During document parsing, the system also extracts:

```json
{
  "video_extraction": {
    "motion_scenes": [
      {
        "phase": "awakening",
        "scene": "Character stands at edge of dark forest, wind moves through trees",
        "motion_prompt": "Slow camera push toward figure, trees swaying gently, mist drifting",
        "audio_profile": "wind through pines, distant owl, soft ambient drone",
        "duration": 10
      }
    ],
    "key_animation_moments": [
      "Dragon first appears — smoke, then form emerging from cave",
      "Tower cracking — stones falling in slow motion, light breaking through",
      "Convergence — two characters walking toward each other from opposite biomes"
    ],
    "audio_atmosphere_per_biome": {
      "dark_forest": "crackling fire, night sounds, gentle wind, occasional owl",
      "fortress_plains": "wind across grass, distant birdsong, stone settling",
      "river_valley": "water flowing, birdsong, soft breeze, leaves rustling",
      "crystal_mountains": "cave echoes, dripping water, crystal resonance hum",
      "open_sky": "open air, multiple nature sounds, warm breeze, peace"
    }
  }
}
```

---

## Step 2: Metadata + Delivery Definition (REVISED v1.3)

### Story Plot JSON — Now Includes Delivery Config

All v1.2 metadata fields are retained. New fields added:

```json
{
  "id": "storyboard_[name]_v[version]",
  "name": "...",
  "phases": [],
  "scene_templates": [],
  "transition_conditions": {},
  "clinical_pacing_rules": {},
  "age_tier_classification": {},
  "provenance_id": "...",

  "delivery_config": {
    "cadence": {
      "daily_panel": {
        "enabled": true,
        "type": "static_image",
        "generation_time": "03:00 UTC",
        "prompt_source": "phase_scene_templates",
        "cost_per_user_per_day": 0.05
      },
      "weekly_clip": {
        "enabled": true,
        "type": "video_10s",
        "generation_day": "sunday",
        "generation_time": "04:00 UTC",
        "weeks": [1, 2, 3],
        "prompt_source": "weekly_highlight_from_crystals",
        "audio_profile": "biome_ambient",
        "cost_per_user_per_week": 0.50
      },
      "monthly_recap": {
        "enabled": true,
        "type": "video_chain",
        "generation_day": "last_sunday",
        "generation_time": "05:00 UTC",
        "structure": {
          "act_1": {
            "description": "Where you were — month's starting state",
            "clips": 4,
            "duration_per_clip": 10,
            "chain_method": "extend_from_frame"
          },
          "act_2": {
            "description": "What happened — key therapeutic moments",
            "clips": 4,
            "duration_per_clip": 10,
            "chain_method": "extend_from_frame"
          },
          "act_3": {
            "description": "Where you are — current state, growth visible",
            "clips": 4,
            "duration_per_clip": 10,
            "chain_method": "extend_from_frame"
          },
          "stitching": "cloudflare_stream",
          "total_duration_seconds": 120,
          "transition_between_acts": "1s_fade"
        },
        "cost_per_user_per_month": 6.00
      }
    },

    "monthly_cost_per_user": {
      "daily_panels": 1.50,
      "weekly_clips": 1.50,
      "monthly_recap": 6.00,
      "total": 9.00,
      "note": "Based on 30 days, 3 weekly clips, 1 monthly recap"
    },

    "tier_gating": {
      "daily_panel_static": "all_tiers",
      "weekly_clip_video": "inner_chamber_and_above",
      "monthly_recap_video": "sovereign_circle_only",
      "note": "Admin can override per-storyboard in SSE Story Generator tab"
    },

    "audio_profiles": {
      "dark_forest": {
        "ambient": "crackling fire, night sounds, gentle wind",
        "emotional_low": "deep drone, sparse, isolated",
        "emotional_high": "swelling strings, warmth, breakthrough"
      },
      "fortress_plains": {
        "ambient": "wind across plains, distant birdsong",
        "emotional_low": "hollow wind, stone settling, emptiness",
        "emotional_high": "horns in distance, walls crumbling gently, birdsong crescendo"
      },
      "river_valley": {
        "ambient": "water flowing, birdsong, soft breeze",
        "emotional_low": "still water, single bird, muted",
        "emotional_high": "river rushing, full birdsong, sunlight warmth in sound"
      },
      "crystal_mountains": {
        "ambient": "cave echoes, dripping water, crystal hum",
        "emotional_low": "deep cave silence, single drip, isolation",
        "emotional_high": "crystal resonance building, light-as-sound, clarity"
      },
      "open_sky": {
        "ambient": "open air, nature mix, warm breeze",
        "emotional_low": "vast silence, single breath, space",
        "emotional_high": "full orchestra of nature, everything alive, wholeness"
      }
    },

    "video_prompt_templates": {
      "daily_panel_to_weekly_clip": "Animate this scene: {scene_description}. The character ({archetype_visual_description}) is in {biome}. Motion: {motion_prompt}. Mood: {ec_derived_mood}. Audio: {audio_profile}. 10 seconds, 720p, painterly fantasy style.",
      "weekly_clips_to_monthly_recap": "Continue from the previous frame. This is {act_description}. The character has {progress_description}. Motion: slow, contemplative, {mood}. Audio: {audio_profile_emotional}. 10 seconds, 720p.",
      "sacred_space_animation": "Animate this sacred space: {space_name}. {space_visual_description}. Gentle ambient motion — {specific_motion}. Audio: {space_audio}. 10 seconds, 720p, no characters, atmospheric."
    }
  }
}
```

### Cost Projection Display
Step 2 auto-calculates and stores the per-user monthly cost:

```
Storyboard: storyboard_mens_healing_journey_v1.0
Delivery Cadence: daily panel + weekly clip (weeks 1-3) + monthly recap (week 4)

Per-user monthly cost breakdown:
  Daily static panels:  30 × $0.05 = $1.50/month
  Weekly video clips:    3 × $0.50 = $1.50/month
  Monthly recap video:   1 × $6.00 = $6.00/month
  ─────────────────────────────────────
  Total per user:                    $9.00/month

At 100 enrolled users: $900/month
At 500 enrolled users: $4,500/month
At Sovereign Circle pricing ($149/user): 94% margin at 100 users
```

---

## Step 3: Imagery + Video Generation (REVISED v1.3)

### Batch Structure (Updated)
Batches now include both static images AND sample video clips:

```
Batch 1-N:  Static images (5-10 per batch, same as v1.2)
Batch N+1:  Sample video clips — 1 per biome used in storyboard (10s each)
Batch N+2:  Sample monthly recap preview — 3 chained clips (30s total)
```

**Sample video clips** are generated so admin can review video quality in Step 4 before approving. These are not the actual user-facing deliverables — they're preview clips using a generic archetype (the Wanderer) to demonstrate how scenes will look animated.

**Sample monthly recap** chains 3 clips using Extend from Frame to demonstrate the three-act structure. Admin sees what the monthly recap will feel like.

### Video Batch Specifics

```json
{
  "video_batch": {
    "sample_clips": [
      {
        "biome": "dark_forest",
        "prompt": "Animate: A lone wanderer standing at the edge of a dark misty forest, gentle wind moving through pine trees, campfire flickering nearby. Painterly fantasy style, warm muted palette, atmospheric. 10 seconds, 720p.",
        "source_image": "sse/reference_library/imagery_guides/biome_scenes/dark_forest_01_fog_panel.jpg",
        "type": "image_to_video",
        "duration": 10,
        "cost": 0.50
      }
    ],
    "sample_recap": {
      "act_1_clip": {
        "prompt": "A wanderer enters the dark forest, walking slowly on a misty path, head down, armor visible. Painterly, warm muted palette. 10 seconds.",
        "chain_position": 1
      },
      "act_2_clip": {
        "prompt": "Continue from previous frame. The wanderer pauses at a campfire clearing, looks up at fireflies appearing. Subtle wonder. 10 seconds.",
        "chain_position": 2,
        "chain_method": "extend_from_frame"
      },
      "act_3_clip": {
        "prompt": "Continue from previous frame. Dawn breaks through the forest canopy, the wanderer stands straighter, light hitting their face for the first time. 10 seconds.",
        "chain_position": 3,
        "chain_method": "extend_from_frame"
      },
      "total_duration": 30,
      "total_cost": 1.50,
      "stitching": "local_ffmpeg_concat"
    },
    "total_video_batch_cost": 4.00,
    "note": "Sample clips only — actual user deliverables generated by the runtime delivery pipeline"
  }
}
```

### Staging Write to R2 (Storage Resilience — v1.3)
After each verified batch (static or video), assets are immediately written to R2 staging:

```
nate-vault/sse/staging/[storyboard_id]/
  batch_1/
    image_001.jpg
    image_002.jpg
    batch_1_verification.json
  batch_2/
    ...
  video_batch/
    dark_forest_sample_clip.mp4
    monthly_recap_preview.mp4
    video_batch_verification.json
```

**Crash recovery:** On pipeline restart, the system checks the staging prefix. If verified batches exist, it resumes from the next unverified batch. No regeneration of already-verified work.

---

## Step 4: Admin Review (REVISED v1.3)

### New Review Panel Sections

**Video Preview Player**
- Plays sample biome clips inline in the review panel
- Plays the 30-second monthly recap preview
- Audio playback included (admin hears the biome ambient audio)
- Admin can flag specific clips for regeneration
- Side-by-side: static panel vs animated version of the same scene

**Delivery Cadence Configuration**
- Admin sees the default cadence (daily panel, weekly clip, monthly recap)
- Can adjust per-storyboard:
  - Disable weekly clips (static panels only — reduces cost to $1.50/user/month)
  - Disable monthly recap (reduces to $3.00/user/month)
  - Enable daily video instead of daily static (premium — $15/user/month + weekly + monthly = $22.50)
- Tier gating: admin sets which subscription tiers get which delivery level
- Cost projection updates in real-time as cadence is adjusted

**Per-User Monthly Cost Display**
```
Current configuration:
  Daily static panels:  $1.50/user/month   [All Tiers]
  Weekly video clips:   $1.50/user/month   [Inner Chamber+]
  Monthly recap video:  $6.00/user/month   [Sovereign Circle]

  At current enrollment (145 eligible users):
    100 on daily panels only:       $150/month
     35 on daily + weekly:          $105/month
     10 on daily + weekly + recap:   $90/month
    ────────────────────────────────────────
    Total platform cost:            $345/month
    Total platform revenue:       $8,710/month
    Content generation margin:       96%
```

### Updated Admin Actions

| Action | Effect |
|--------|--------|
| **Suggest Edits** | Regenerates affected sections, bumps minor version |
| **Regenerate Video** | Re-generates specific flagged video clips only (NEW v1.3) |
| **Adjust Cadence** | Modifies delivery schedule without regenerating content (NEW v1.3) |
| **Delete** | Removes all staging assets |
| **Save for Later** | Draft status |
| **Set as Run Cycle** | Seasonal with start/end dates |
| **Preview Mode** | Static + animated walkthrough with audio (REVISED v1.3) |
| **Approve for Release** | Triggers Step 5 with delivery pipeline activation |
| **Sunset** | Graceful retirement |

---

## Step 5: Deployment (REVISED v1.3)

All v1.2 deployment steps retained. New additions:

### Delivery Pipeline Config Deployment
On approval, the storyboard's `delivery_config` is written to:
- R2: `nate-vault/sse/delivery/[storyboard_id]/config.json`
- PostgreSQL: `storyboard_delivery_config` table

### Cron Schedule Registration
The delivery scheduler reads the config and registers generation jobs:

```json
{
  "storyboard_id": "storyboard_mens_healing_journey_v1.0",
  "schedules": [
    {
      "type": "daily_panel",
      "cron": "0 3 * * *",
      "target": "all_enrolled_users",
      "generation_function": "generate_daily_panel"
    },
    {
      "type": "weekly_clip",
      "cron": "0 4 * * 0",
      "target": "tier_inner_chamber_plus",
      "generation_function": "generate_weekly_clip",
      "skip_week_4": true
    },
    {
      "type": "monthly_recap",
      "cron": "0 5 28-31 * *",
      "target": "tier_sovereign_circle",
      "generation_function": "generate_monthly_recap",
      "condition": "last_sunday_of_month"
    }
  ]
}
```

### R2 Staging → Production Promotion (Storage Resilience)
Instead of uploading directly to production paths, Step 5:
1. Verifies all staging batches are complete and verified
2. Copies from `sse/staging/[storyboard_id]/` to `sse/reference_library/imagery_guides/[subfolders]/`
3. Verifies copy integrity (object count + size match)
4. Deletes staging prefix only after production verification
5. If copy fails mid-way, staging remains intact for retry

---

## Step 6: Activation + Runtime Delivery (REVISED v1.3)

All v1.2 activation steps retained. Major addition: the Delivery Pipeline Runtime.

### Delivery Pipeline Runtime

This is the continuously running system that generates and delivers content to enrolled users based on approved storyboard delivery configs.

#### Architecture
```
Delivery Pipeline Runtime
        ↓
┌─────────────────────────────────┐
│  Scheduler (cron-based)          │
│  Reads: storyboard_delivery_config│
│  Runs on: GREEN (nate_backend)   │
│  Or: Cloudflare Worker (edge)    │
└──────────┬──────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│  Daily Panel Generator (03:00 UTC)        │
│                                           │
│  For each enrolled user:                  │
│    1. Read user's current phase + biome   │
│    2. Read user's archetype reference     │
│    3. Read today's crystal highlights     │
│    4. Select scene template from phase    │
│    5. Compose Grok Imagine prompt:        │
│       - Scene template + archetype ref    │
│       - Biome visual rules               │
│       - EC-derived mood (warm/cool/dark)  │
│    6. Generate static image ($0.05)       │
│    7. Score against quality filter        │
│    8. Store in R2:                        │
│       stories/{user_id}/daily_panel/      │
│       {date}/{hash}.png                   │
│    9. Push notification to Flutter app    │
│                                           │
│  Batched: 10 users per batch              │
│  Rate limited: 2s between API calls       │
│  Failure: retry 2x, then skip + log      │
│  Daily cost: $0.05 × enrolled users      │
└──────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│  Weekly Clip Generator (Sunday 04:00 UTC) │
│  Weeks 1, 2, 3 only                      │
│                                           │
│  For each eligible user (tier-gated):     │
│    1. Gather week's daily panels          │
│    2. Select highlight panel (highest     │
│       therapeutic significance from       │
│       crystal data)                       │
│    3. Compose video prompt:               │
│       - Highlight scene + motion prompt   │
│       - Archetype reference image         │
│       - Biome audio profile               │
│       - EC-derived emotional audio level  │
│    4. Generate 10s video via image-to-    │
│       video ($0.50)                       │
│    5. Poll for completion                 │
│    6. Score video quality                 │
│    7. Store in R2:                        │
│       stories/{user_id}/weekly_clip/      │
│       {date}/{hash}.mp4                   │
│    8. Upload to Cloudflare Stream for     │
│       adaptive bitrate delivery           │
│    9. Push notification                   │
│                                           │
│  Batched: 5 users per batch (video is     │
│  more expensive, smaller batches)         │
│  Rate limited: 5s between API calls       │
│  Weekly cost: $0.50 × eligible users     │
└──────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────┐
│  Monthly Recap Generator (Last Sunday     │
│  05:00 UTC)                               │
│                                           │
│  For each eligible user (tier-gated):     │
│    1. Gather month's panels + 3 clips    │
│    2. Determine three-act structure:      │
│       Act 1: Starting state (biome,      │
│              archetype posture, mood)     │
│       Act 2: Key moments (parts met,     │
│              thresholds crossed, spaces   │
│              visited)                     │
│       Act 3: Current state (any biome    │
│              shift, armor reduction,      │
│              color warming)              │
│    3. For each act (3 acts):             │
│       a. Generate 4 clips × 10s each    │
│       b. Chain via Extend from Frame     │
│       c. Each act is a separate chain    │
│          (avoids quality degradation)    │
│       d. Score each clip                 │
│    4. Stitch 3 acts via Cloudflare       │
│       Stream or ffmpeg with 1s fade      │
│       transitions                        │
│    5. Total: ~120s (2 minutes)           │
│    6. Store in R2:                       │
│       stories/{user_id}/monthly_recap/   │
│       {date}/{hash}.mp4                  │
│    7. Upload to Cloudflare Stream        │
│    8. Push notification                  │
│                                           │
│  Batched: 2 users per batch (12 API      │
│  calls per user, heavy workload)          │
│  Rate limited: 3s between API calls       │
│  Monthly cost: $6.00 × eligible users    │
│                                           │
│  QUALITY GATE: Each act's chain is       │
│  verified before the next act begins.    │
│  If Act 1 fails quality after 2 retries, │
│  fall back to a static panel slideshow   │
│  with audio overlay (cost: $0 extra,     │
│  uses existing daily panels)             │
└──────────────────────────────────────────┘
```

#### Delivery Pipeline Monitoring
Added to SSE Story Generator tab → Active Storyboards:

| Metric | Description |
|--------|-------------|
| Today's Panels | Generated / Failed / Queued |
| This Week's Clips | Generated / Failed / Queued |
| Monthly Recaps | Generated / Failed / Queued |
| API Spend Today | Dollar amount spent on Grok Imagine |
| API Spend This Month | Running monthly total |
| Average Generation Time | Per panel / per clip / per recap |
| Quality Pass Rate | % of generations that pass scoring filter on first attempt |
| Fallback Activations | Count of monthly recaps that fell back to slideshow |

#### Failure Handling

| Failure Type | Response |
|---|---|
| Single panel fails scoring (3 attempts) | Skip that user's daily panel, log, retry next day |
| Weekly clip fails | Retry once with adjusted prompt. If still fails, deliver best-scored attempt with admin flag |
| Monthly recap act fails chain | Fall back to static slideshow (user's best 12 daily panels with fade transitions + biome audio overlay). Cost: $0 additional (reuses existing panels) |
| Grok API outage | Queue pending generations. Progressive Recovery Protocol activates (see below) |
| R2 write failure | Retry 3x with backoff. If persistent, write to local disk + queue for R2 upload when available |
| User becomes ineligible mid-delivery | Stop generating for that user. Already-generated content remains in their vault |
| Cron daemon failure | Delivery Health Heartbeat detects within 30 minutes, alerts admin (see below) |
| Cost circuit breaker tripped | All generation pauses, admin notified, resumes on approval or next calendar day (see below) |

#### Generation Concurrency Semaphore (v1.3.1)

Only ONE delivery generation process runs at a time across the entire system. This prevents:
- Two daily panel runs overlapping (yesterday's retry + today's scheduled run)
- Weekly clip generation fighting daily panel generation for API rate limit
- Monthly recap (heavy — 12 API calls per user) starving daily panels

```json
{
  "delivery_semaphore": {
    "storage": "redis",
    "key": "sse_delivery_active",
    "max_concurrent": 1,
    "queue_behavior": "FIFO",
    "priority_order": [
      "daily_panel_current_day",
      "weekly_clip_current_week",
      "monthly_recap_current_month",
      "recovery_daily_panel",
      "recovery_weekly_clip"
    ],
    "starvation_prevention": "Recovery tasks limited to 1 batch per hour. Current-day tasks always preempt recovery."
  }
}
```

**How it works:**
- The daily 03:00 UTC cron fires → acquires semaphore → generates today's panels → releases
- If the weekly 04:00 UTC cron fires while daily is still running → enters queue at position 2
- Recovery tasks (filling missed days) are lowest priority and never block current-day delivery
- If any process holds the semaphore for more than 2 hours → auto-release + alert admin (stuck process)

#### Cost Circuit Breaker (v1.3.1)

Hard spending limits that pause all generation when exceeded:

```json
{
  "cost_circuit_breaker": {
    "daily_limit": 50.00,
    "monthly_limit": 500.00,
    "per_user_daily_limit": 1.00,
    "action_on_breach": "pause_all_generation",
    "notification": "admin_email_immediate",
    "resume_policy": "admin_approval OR next_calendar_day (whichever first)",
    "tracking_table": "delivery_monthly_spend"
  }
}
```

**Scenarios:**
- Normal day, 500 users: ~$25 in daily panels + $0 clips/recaps = well under $50 daily limit
- Scoring bug causing 3x retries on every image: $75 attempted → breaker trips at $50 → 333 panels generated, 167 skipped → admin alerted → fixes bug → approves resume
- Runaway monthly recap generation: 50 Sovereign Circle users × $6 each = $300 in one night → still under $500 monthly but admin sees the spike in monitoring

**Per-user daily limit** prevents a single user's content from consuming disproportionate budget (e.g., if their archetype reference image keeps failing scoring).

#### Dependency Chain Validation (v1.3.1)

Before generating dependent content, the pipeline validates source material exists:

**Weekly Clip Dependencies:**
```json
{
  "weekly_clip_validation": {
    "minimum_daily_panels_required": 4,
    "out_of": 7,
    "if_below_minimum": {
      "action": "substitute_fog_panels",
      "detail": "Fill missing days with pre-generated fog panels from user's current biome. Weekly clip still generates but highlight selection draws from available panels only.",
      "notification": "log_warning"
    },
    "if_zero_panels": {
      "action": "skip_weekly_clip",
      "detail": "No source material for the week. Skip clip generation, log gap, no user notification (they didn't receive panels either).",
      "notification": "admin_flag"
    }
  }
}
```

**Monthly Recap Dependencies:**
```json
{
  "monthly_recap_validation": {
    "minimum_weekly_clips_required": 2,
    "out_of": 3,
    "minimum_daily_panels_required": 20,
    "out_of_days": 30,
    "if_clips_below_minimum": {
      "action": "generate_recap_from_panels_only",
      "detail": "Use daily panels as source for all 3 acts instead of mixing panels and clips. Each act selects best 4 panels from its date range and generates image-to-video clips from those stills.",
      "cost_impact": "Same ($6.00) — still generating 12 video clips, just from panels instead of existing clips"
    },
    "if_panels_below_minimum": {
      "action": "shortened_recap",
      "detail": "Generate 2-act recap instead of 3-act. Act 1 (where you were) + Act 3 (where you are). Skip Act 2 (what happened) since there isn't enough data to represent it honestly.",
      "cost_impact": "Reduced to $4.00 (8 clips instead of 12)"
    },
    "if_panels_below_10": {
      "action": "skip_recap_deliver_slideshow",
      "detail": "Not enough content for a meaningful video recap. Deliver a static slideshow of available panels with biome audio overlay. User still gets a month-end summary, just not animated.",
      "cost_impact": "$0 additional"
    }
  }
}
```

#### Progressive Recovery Protocol (v1.3.1)

**The problem it solves:** After a multi-day outage, the system must NOT dump all missed content at once. This would overload the Grok API, blow through cost limits, and flood users with days of content simultaneously (therapeutically inappropriate — the daily cadence matters).

**Core Rules:**
1. **Current day ALWAYS generates first.** No recovery task ever delays today's scheduled delivery.
2. **Recovery is throttled.** Maximum 1 recovery batch per hour, alongside normal daily generation.
3. **Content older than the recovery window is abandoned.** It's logged as a gap, not regenerated.
4. **Users receive content in chronological order.** If we're recovering days 3, 4, and 5, the user sees day 3 first, then day 4 arrives an hour later, etc. Never out of order.
5. **Weekly clips and monthly recaps are NEVER recovered retroactively.** If a weekly clip was missed, it's gone. The monthly recap uses whatever panels exist.

```json
{
  "progressive_recovery": {
    "recovery_window": {
      "daily_panels": "3 days",
      "weekly_clips": "not_recoverable",
      "monthly_recaps": "not_recoverable"
    },
    "policy": {
      "day_0_missed": "Generate today's content as normal at scheduled time",
      "day_minus_1_missed": "Recover yesterday's panel — 1 recovery batch starting 1 hour after today's generation completes",
      "day_minus_2_missed": "Recover 2-days-ago panel — 1 recovery batch starting 2 hours after today's generation",
      "day_minus_3_missed": "Recover 3-days-ago panel — 1 recovery batch starting 3 hours after today's generation",
      "day_minus_4_plus": "ABANDONED. Log as delivery_gap in delivery_failure_log. Generate a 'week in review' summary panel instead that captures the gap period as a single scene."
    },
    "week_in_review_panel": {
      "trigger": "4+ consecutive daily panels missed",
      "description": "A single summary panel representing the missed period. Uses the user's current biome + archetype but with a 'time passing' visual treatment (sun moving across sky, seasons shifting, path stretching into distance).",
      "prompt_template": "Fantasy illustration, painterly style — time has passed in {biome}. {archetype_description} stands on a path where several days' worth of footprints are visible behind them. The light suggests multiple sunrises have occurred. Warm muted palette, atmospheric, a sense of continuity despite absence. Rest scene.",
      "cost": 0.05,
      "delivered_with_note": "Your journey continued even while we were apart. Here's where you are now."
    },
    "throttle": {
      "max_recovery_batches_per_hour": 1,
      "batch_size": 10,
      "api_call_spacing": "2 seconds",
      "priority": "lowest (after all current-day generation)"
    },
    "notification_to_user": {
      "single_missed_day": "none — panel arrives silently when recovered",
      "2_3_missed_days": "none — panels arrive in order over next few hours",
      "4_plus_missed_days": "week_in_review panel delivered with gentle note"
    }
  }
}
```

**Recovery Sequence Example — 3-Day Outage:**
```
Day 1-3: System down. No panels generated for 500 users.
Day 4: System recovers.

04:00 UTC — Daily cron fires
  → Detects 3 missed days per user
  → Generates Day 4 panels FIRST (current day, highest priority)
  → 500 users × 10 per batch = 50 batches
  → Completes by ~05:40 UTC

05:40 UTC — Recovery scheduler activates
  → Recovery batch 1: Day 3 panels (yesterday)
  → 10 users per batch, 1 batch now, next batch in 1 hour
  → First 10 users get Day 3 panel at ~05:45

06:40 UTC — Recovery batch 2: next 10 users' Day 3 panels
07:40 UTC — Recovery batch 3: next 10 users' Day 3 panels
  ... continues at 1 batch/hour ...

~10:40 UTC — All 500 users have Day 3 panels recovered
  → Recovery scheduler moves to Day 2 panels
  → Same 1-batch-per-hour throttle

~15:40 UTC — All Day 2 panels recovered
  → Recovery scheduler moves to Day 1 panels

~20:40 UTC — All Day 1 panels recovered
  → Recovery complete. System fully caught up.
  → Total recovery time: ~17 hours (spread across the day)
  → Cost: normal ($0.05 × 500 × 4 days = $100)
  → API load: never exceeded normal daily rate

Next day 04:00 UTC — Normal schedule resumes, no recovery needed
```

**Recovery Sequence Example — 7-Day Outage:**
```
Day 1-7: System down.
Day 8: System recovers.

04:00 UTC — Daily cron fires
  → Detects 7 missed days per user
  → Recovery window is 3 days → Days 1-4 are ABANDONED
  → Generates Day 8 panels (current day) FIRST
  → Then recovers Day 7, Day 6, Day 5 progressively

For Days 1-4 (abandoned):
  → Generates 1 "week in review" summary panel per user
  → Captures the gap as a single scene
  → Cost: $0.05 per user (1 panel, not 4)
  → Delivered with note: "Your journey continued even while we were apart"

Weekly clip for the missed week:
  → NOT recovered. Logged as gap.
  → Next week's clip generates normally.

Monthly recap:
  → If this outage falls in a recap week, the recap uses whatever panels exist.
  → Dependency validation handles partial source material (see above).
```

#### Delivery Health Heartbeat (v1.3.1)

A background process that runs every 30 minutes, independent of the delivery pipeline:

```json
{
  "heartbeat": {
    "check_interval": "30 minutes",
    "runs_on": "separate_process (not the delivery pipeline itself)",
    "checks": [
      {
        "name": "daily_panel_generation_check",
        "logic": "After 06:00 UTC, if today's expected panel count > actual generated count by more than 10%, alert.",
        "alert_level": "warning (10-25% gap) | critical (25%+ gap)"
      },
      {
        "name": "weekly_clip_generation_check",
        "logic": "On Sundays after 08:00 UTC, if expected clips > actual by more than 10%, alert.",
        "alert_level": "warning | critical"
      },
      {
        "name": "monthly_recap_generation_check",
        "logic": "On last Sunday after 12:00 UTC, if expected recaps > actual by more than 10%, alert.",
        "alert_level": "critical"
      },
      {
        "name": "cron_alive_check",
        "logic": "Verify the delivery cron process has written a heartbeat timestamp to Redis within the last 35 minutes. If stale, the cron daemon may have died.",
        "alert_level": "critical"
      },
      {
        "name": "cost_anomaly_check",
        "logic": "If today's spend is more than 2x the 7-day rolling average, alert. May indicate scoring bug causing excessive retries.",
        "alert_level": "warning"
      },
      {
        "name": "semaphore_stuck_check",
        "logic": "If the delivery semaphore has been held for more than 2 hours, the generation process is stuck. Auto-release and alert.",
        "alert_level": "critical"
      }
    ],
    "alert_channels": [
      "admin_email (DrNevedal1)",
      "SSE Story Generator tab — health indicator (green/yellow/red)",
      "SkyEye dashboard alert panel"
    ],
    "auto_remediation": {
      "stuck_semaphore": "auto-release after 2 hours, log the stuck process details",
      "dead_cron": "attempt restart via systemd, alert if restart fails",
      "cost_anomaly": "no auto-action — alert only, admin decides"
    }
  }
}
```

**Dashboard Health Indicator:**
The SSE Story Generator tab shows a health badge:
- 🟢 **Healthy** — all checks passing, generation on schedule
- 🟡 **Warning** — minor gaps detected, recovery in progress, or cost anomaly
- 🔴 **Critical** — cron dead, semaphore stuck, or 25%+ generation gap
The daily panel and weekly clip prompts are mood-adjusted based on the user's current Emotional Coherence score:

```json
{
  "ec_mood_mapping": {
    "0.0-0.3": {
      "mood": "rest",
      "scene_type": "fog_panel",
      "color_temperature": "cool_muted",
      "motion": "minimal_slow",
      "audio_level": "emotional_low",
      "note": "User is in clinical cool-down. Rest scenes only."
    },
    "0.3-0.5": {
      "mood": "cautious",
      "scene_type": "exploration",
      "color_temperature": "warm_muted",
      "motion": "gentle",
      "audio_level": "ambient",
      "note": "User is progressing. Gentle forward movement."
    },
    "0.5-0.7": {
      "mood": "engaged",
      "scene_type": "active",
      "color_temperature": "warm",
      "motion": "purposeful",
      "audio_level": "ambient_building",
      "note": "User is therapeutically engaged. Meaningful scenes."
    },
    "0.7-1.0": {
      "mood": "breakthrough",
      "scene_type": "transformation",
      "color_temperature": "warm_bright",
      "motion": "dynamic",
      "audio_level": "emotional_high",
      "note": "User is in breakthrough territory. Sacred space scenes, armor reduction, color warming."
    }
  }
}
```

---

## Storage Resilience (NEW v1.3)

### 8 Fixes Integrated

**1. Staging Write on Batch Verification**
Every verified batch (static or video) is immediately written to `nate-vault/sse/staging/[storyboard_id]/`. Pipeline crash recovery resumes from last verified batch.

**2. Pipeline Lock Dual-Write**
Redis (fast check) + PostgreSQL (durable). On startup, reconcile: if PostgreSQL shows `"processing"` but Redis has no lock, either resume or mark as `"failed_needs_cleanup"`.

**3. Metadata Backup Before Modification**
Before any metadata.json write: create `metadata_[timestamp].json.bak`. Keep last 5 backups. On JSON parse failure, auto-restore from most recent valid backup.

**4. Transactional R2 Upload**
Upload to staging prefix → verify all objects → copy to production prefix → verify production → delete staging. Any failure at any step leaves the previous valid state intact.

**5. Version-Pin State Dual-Write**
`user_storyboard_state` in PostgreSQL (primary) + per-user JSON in R2 (backup). On discrepancy, R2 is tiebreaker. Daily eligibility re-check validates all pinned versions still exist.

**6. Provenance Log Reconciliation**
On startup: compare PostgreSQL `ip_provenance_log` count against R2 `sse/provenance/` count. R2 is source of truth — re-insert missing records from R2 into PostgreSQL.

**7. Stale Document Detection**
Background job checks `story_creation_generator/processing/` every 15 minutes. Documents stuck longer than `max_processing_time` (2 hours) are retried or moved to `failed/` with error log. Admin notified.

**8. Large Document Chunking**
Documents exceeding context window are chunked (same method as Night School ingestion). Parse result includes `document_coverage` metric. Below 95% → flagged for admin review before Step 2.

---

## Database Tables (Updated v1.3)

```sql
-- From v1.1
ip_provenance_log              -- immutable IP audit trail
user_storyboard_state          -- version-pinning and migration tracking
storyboard_enrollment_log      -- eligibility checks and enrollment records
storyboard_sunset_log          -- sunset progress tracking

-- New in v1.3
storyboard_delivery_config     -- delivery cadence, tier gating, cost projections per storyboard
delivery_generation_log        -- every panel/clip/recap generated, with cost, score, status
delivery_failure_log           -- failures, retries, fallbacks
delivery_monthly_spend         -- running cost totals per storyboard per month
pipeline_lock_state            -- durable pipeline lock (PostgreSQL side of dual-write)
metadata_backup_registry       -- tracks metadata.json backup files for auto-restore

-- New in v1.3.1
delivery_recovery_log          -- tracks progressive recovery: missed days, recovery status, abandoned gaps
delivery_gap_log               -- permanent record of delivery gaps (abandoned days, missed clips/recaps)
cost_circuit_breaker_events    -- when breaker tripped, reason, spend at trip, resume timestamp
delivery_heartbeat_log         -- heartbeat check results, alert history, auto-remediation actions
```

---

## Development Stages (Updated v1.3)

### Stage 1: Foundation
- [ ] story_creation_generator/ watched folder or upload endpoint
- [ ] Pipeline concurrency lock (Redis + PostgreSQL dual-write)
- [ ] IP assignment gate UI
- [ ] Document parser (.txt, .md, .docx, .pdf)
- [ ] Narrative structure extraction (phases, characters, spaces, biomes)
- [ ] Video scene extraction (motion prompts, audio profiles) (NEW v1.3)
- [ ] Cross-reference engine + similarity check
- [ ] Age-tier analysis + conflict detection
- [ ] Story plot JSON auto-generation with delivery config (REVISED v1.3)
- [ ] IP provenance logging

### Stage 2: Imagery + Video Pipeline
- [ ] Grok Imagine API — static image batched generation (5-10/batch)
- [ ] Grok Imagine API — video generation with polling (NEW v1.3)
- [ ] Grok Imagine API — Extend from Frame chaining (NEW v1.3)
- [ ] Per-batch verification gate
- [ ] Rate limiting (2s images, 3-5s videos)
- [ ] Cost ceiling check with admin approval
- [ ] Image + video scoring filter
- [ ] Staging write to R2 after each verified batch (NEW v1.3)
- [ ] Auto-naming, subfolder placement, metadata auto-update

### Stage 3: Admin Interface
- [ ] SSE Story Generator tab in Sovereign Command
- [ ] Upload zone with batch progress (static + video)
- [ ] Pipeline queue position indicator
- [ ] Submissions Queue with IP acknowledgment
- [ ] Storyboard review panel (static + video preview) (REVISED v1.3)
- [ ] Video playback player with audio (NEW v1.3)
- [ ] Delivery cadence configuration UI (NEW v1.3)
- [ ] Per-user monthly cost projection display (NEW v1.3)
- [ ] Age-tier content map, conflict report, similarity report
- [ ] Preview Mode (static + animated walkthrough with audio) (REVISED v1.3)
- [ ] Admin actions (edit, delete, save, run-cycle, preview, approve, sunset, regenerate video)

### Stage 4: Deployment Automation
- [ ] Transactional R2 upload (staging → production promotion) (REVISED v1.3)
- [ ] Delivery pipeline config deployment to Layer 0 (NEW v1.3)
- [ ] Cron schedule registration (daily/weekly/monthly) (NEW v1.3)
- [ ] Version control, archiving, rollback with version-pinning
- [ ] Bridge scene generation for cross-version transitions
- [ ] IP provenance finalization
- [ ] Run cycle scheduler
- [ ] Clinical eligibility gate
- [ ] Sunset protocol

### Stage 5: Delivery Pipeline Runtime (REVISED v1.3.1)
- [ ] Generation concurrency semaphore (single process at a time, FIFO queue) (NEW v1.3.1)
- [ ] Daily panel generator (batched, rate-limited, scored)
- [ ] Weekly clip generator (image-to-video, tier-gated)
- [ ] Monthly recap generator (3-act chain, Cloudflare Stream stitching)
- [ ] EC-derived mood mapping for prompt adjustment
- [ ] Dependency chain validation (weekly needs 4/7 panels, monthly needs 2/3 clips) (NEW v1.3.1)
- [ ] Cost circuit breaker (daily + monthly + per-user limits) (NEW v1.3.1)
- [ ] Progressive Recovery Protocol (3-day window, throttled, current-day priority) (NEW v1.3.1)
- [ ] Week-in-review summary panel for gaps beyond recovery window (NEW v1.3.1)
- [ ] Failure handling (retry, fallback to slideshow, admin alerts)
- [ ] Delivery generation log (every generation recorded with cost + score)
- [ ] Delivery recovery log + delivery gap log (NEW v1.3.1)
- [ ] Cloudflare Stream integration for adaptive bitrate video delivery
- [ ] Push notification system for content delivery

### Stage 6: Monitoring Dashboard (REVISED v1.3.1)
- [ ] Active storyboards dashboard with real-time metrics
- [ ] Delivery pipeline monitoring (panels/clips/recaps generated today)
- [ ] Delivery health heartbeat (30-minute independent process) (NEW v1.3.1)
- [ ] Health badge indicator (green/yellow/red) in SSE Story Generator tab (NEW v1.3.1)
- [ ] API spend tracking (daily + monthly) with anomaly detection (REVISED v1.3.1)
- [ ] Cost circuit breaker dashboard (trip history, current status) (NEW v1.3.1)
- [ ] Quality pass rate monitoring
- [ ] Fallback activation alerts
- [ ] Progressive recovery status (recovery in progress, queue position, ETA) (NEW v1.3.1)
- [ ] Delivery gap report (historical gaps, abandoned days, reasons) (NEW v1.3.1)
- [ ] Semaphore status (idle/active, current holder, queue depth) (NEW v1.3.1)
- [ ] Per-storyboard analytics (users, phases, engagement, clinical outcomes)
- [ ] Biome distribution visualization
- [ ] World event threshold monitoring
- [ ] Run cycle + sunset management

### Stage 7: Intelligence Layer
- [ ] Crystal Intelligence document review
- [ ] Therapeutic consistency validation
- [ ] Auto-suggestion of clinical pacing rules
- [ ] Learning loop — delivery outcomes improve future generation

### Stage 8: Localization
- [ ] Narrative text locale separation
- [ ] Translation pipeline
- [ ] Locale selection in Flutter app
- [ ] Locale-aware rendering

---

## Cost Model (Updated v1.3)

### Per-Storyboard Creation (One-Time)
| Component | Cost |
|---|---|
| Document parsing | $0 |
| Metadata generation | $0 |
| Static images (est. 15-30) | $0.75-$1.50 |
| Sample video clips (est. 3-5) | $1.50-$2.50 |
| Sample monthly recap preview | $1.50 |
| **Typical new storyboard** | **$4-6 total** |

### Per-User Delivery (Monthly, Ongoing)
| Tier | Content | Monthly Cost/User |
|---|---|---|
| All Tiers | Daily static panels only | $1.50 |
| Inner Chamber ($49) | Daily panels + weekly clips | $3.00 |
| Sovereign Circle ($149) | Daily panels + weekly clips + monthly recap | $9.00 |

### Platform Scale Projections
| Users | Tier Mix | Monthly Content Cost | Monthly Revenue | Margin |
|---|---|---|---|---|
| 100 | 60/30/10 | $225 | $7,240 | 97% |
| 500 | 60/30/10 | $1,125 | $36,200 | 97% |
| 1,000 | 60/30/10 | $2,250 | $72,400 | 97% |

---

## v1.2 → v1.3 Changelog Summary

| # | Fix | Impact |
|---|-----|--------|
| 14 | Video scene extraction in Step 1 | Stories now define motion prompts, audio profiles, and clip chains during parsing |
| 15 | Delivery config in Step 2 metadata | Each storyboard defines its own daily/weekly/monthly cadence with tier gating |
| 16 | Sample video generation in Step 3 | Admin reviews video quality before approval, not just static images |
| 17 | Video preview + cadence config in Step 4 | Admin sees video playback, adjusts delivery schedule, sees cost projections |
| 18 | Delivery pipeline config deployment in Step 5 | Cron schedules registered on approval, Layer 0 reads delivery config |
| 19 | Delivery Pipeline Runtime in Step 6 | Daily panels, weekly clips, monthly recaps generated on schedule for all enrolled users |
| 20 | EC-derived mood mapping | Panel/clip mood adjusts based on user's current therapeutic state |
| 21 | Monthly recap three-act chain with fallback | 3 separate chains stitched via Cloudflare Stream, fallback to slideshow on failure |
| 22 | 8 storage resilience fixes | Staging writes, dual-write locks, metadata backups, transactional R2, provenance reconciliation |
| 23 | Delivery monitoring dashboard | Real-time API spend, quality pass rate, fallback alerts, generation counts |

## v1.3 → v1.3.1 Changelog Summary

| # | Fix | Impact |
|---|-----|--------|
| 24 | Generation Concurrency Semaphore | Only 1 delivery process at a time. FIFO queue with priority (current-day > recovery). Prevents API rate limit contention between daily/weekly/monthly/recovery generators |
| 25 | Cost Circuit Breaker | Daily ($50), monthly ($500), per-user ($1/day) spend caps. Auto-pauses generation on breach. Resumes on admin approval or next calendar day. Prevents runaway API costs from scoring bugs or retry loops |
| 26 | Dependency Chain Validation | Weekly clips require 4/7 daily panels. Monthly recaps require 2/3 weekly clips + 20/30 daily panels. Below threshold: substitute fog panels, shorten recap, or fall back to slideshow. Prevents broken content from missing source material |
| 27 | Progressive Recovery Protocol | 3-day recovery window. Current day always generates first. Recovery throttled to 1 batch/hour. Days beyond window abandoned with "week in review" summary panel. Prevents catch-up stampede after multi-day outage |
| 28 | Skip-and-Acknowledge Policy | Weekly clips and monthly recaps are NEVER recovered retroactively. Only daily panels are recoverable (within 3-day window). Gaps older than 3 days generate a single summary panel instead of multiple catch-up panels. Prevents content dump overload |
| 29 | Delivery Health Heartbeat | Independent 30-minute background check. Monitors: generation gaps, cron alive status, cost anomalies, stuck semaphores. Auto-remediates stuck semaphores and dead crons. Alerts admin on all other issues. Health badge (green/yellow/red) in SSE Story Generator tab |

---

*© 2026 Sovereign Sanctuary. Patent Pending.*
*SSE Story Creation Generator — System Specification v1.3.1*
*All-In-One: Authoring + Video Generation + Runtime Delivery + Progressive Recovery*
