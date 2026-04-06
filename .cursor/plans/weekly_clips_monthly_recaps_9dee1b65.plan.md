---
name: Weekly Clips Monthly Recaps
overview: Wire the already-built weekly clip and monthly recap pipeline into the widget engine and vault UI, then verify cron schedules exist in the database.
todos:
  - id: widget-engine
    content: Add clip/recap priority checks to widget_engine.py (5 lines)
    status: completed
  - id: vault-video
    content: Add video playback support in vault_browser_screen.dart (10 lines)
    status: completed
  - id: verify-crons
    content: Verify weekly_clip and monthly_recap schedules exist in sse_cron_schedules, insert if missing
    status: completed
  - id: deploy
    content: "Deploy: scp widget_engine.py to GREEN, flutter build web, ./deploy-web.sh"
    status: pending
isProject: false
---

# Phase 5 (Simplified): Wire What's Already Built

## What Already Exists

Everything in the generation and delivery pipeline is done:

- **`delivery_runtime.py`** has `generate_weekly_clips()` (lines 84-125) and `generate_monthly_recap()` (lines 128-167) using Grok Video API + R2 upload
- **`layer0_orchestrator.py`** dispatches `weekly_clip` and `monthly_recap` from `sse_cron_schedules` to `delivery_runtime`
- **`r2_storage.py`** has `store_video()` for MP4 upload
- **`vault_integration.py`** handles video types (`is_video = generation_type in ("weekly_clip", "monthly_recap")`)
- **`sse_panel_log`** stores all panel types including clips and recaps

## What's Missing (3 items)

### 1. Widget Engine -- 5 new lines

**File**: [backend/app/sse/widget_engine.py](backend/app/sse/widget_engine.py)

Insert after the "quest completed today" check (line 144) and before "crisis crystal" (line 146):

```python
# 2b. Weekly clip generated today
clip = await conn.fetchrow(
    "SELECT panel_id FROM sse_panel_log WHERE user_id=$1 AND panel_type='weekly_clip' AND generated_at >= $2", user_id, today_start)
if clip:
    return _content("milestone", biome, primary="Your weekly story clip is ready.", secondary="Watch your journey unfold.", action="open_journey", action_id=str(clip["panel_id"]))

# 2c. Monthly recap generated today
recap = await conn.fetchrow(
    "SELECT panel_id FROM sse_panel_log WHERE user_id=$1 AND panel_type='monthly_recap' AND generated_at >= $2", user_id, today_start)
if recap:
    return _content("milestone", biome, primary="Your monthly chapter is ready.", secondary="See how far you've come.", action="open_journey", action_id=str(recap["panel_id"]))
```

### 2. Vault Video Playback -- max 10 new lines

**File**: [mobile/lib/screens/vault_browser_screen.dart](mobile/lib/screens/vault_browser_screen.dart)

In `_openSSEPanel()` (line 788), detect video content and swap `Image.network` for a play button:

```dart
final isVideo = imgUrl.endsWith('.mp4') || sse['panel_type']?.toString().contains('clip') == true || sse['panel_type']?.toString().contains('recap') == true;
```

- If `isVideo` and image slot: show a dark container with a centered play icon instead of `Image.network`
- On tap of play icon: `launchUrl(Uri.parse(imgUrl), mode: LaunchMode.externalApplication)` (works on both web and mobile)
- Download button: use `.mp4` extension for videos, `.png` for images
- "Ask Nate About This" button: unchanged (uses narrative_text)

### 3. Verify Cron Schedules -- SQL only

Check `sse_cron_schedules` on the production database:

```sql
SELECT * FROM sse_cron_schedules 
WHERE schedule_type IN ('weekly_clip', 'monthly_recap');
```

If rows are missing for enrolled storyboards, insert them:

```sql
INSERT INTO sse_cron_schedules (schedule_id, storyboard_id, schedule_type, cron_expression, enabled)
SELECT gen_random_uuid(), storyboard_id, 'weekly_clip', '30 3 * * 0', true
FROM sse_enrolled_users WHERE status='active'
GROUP BY storyboard_id
ON CONFLICT DO NOTHING;

INSERT INTO sse_cron_schedules (schedule_id, storyboard_id, schedule_type, cron_expression, enabled)
SELECT gen_random_uuid(), storyboard_id, 'monthly_recap', '0 4 1 * *', true
FROM sse_enrolled_users WHERE status='active'
GROUP BY storyboard_id
ON CONFLICT DO NOTHING;
```

Cron expressions: `30 3 * * 0` = Sunday 03:30 UTC, `0 4 1 * *` = 1st of month 04:00 UTC.

## Deployment

1. `scp widget_engine.py` to GREEN, restart backend
2. `flutter build web --release && ./deploy-web.sh`
3. Verify 104/104 health
4. Run cron schedule verification SQL on production

## Files Changed

| File | Lines | Type |
|---|---|---|
| `backend/app/sse/widget_engine.py` | +5 | Backend |
| `mobile/lib/screens/vault_browser_screen.dart` | +10 | Flutter |
| `sse_cron_schedules` table | SQL insert if missing | Database |

No Dockerfile changes. No new files. No delivery_runtime changes.

## Grok Video Cost Analysis

The existing pipeline uses Grok Video API at $0.25/clip and Grok Imagine at $0.07/image. Current cost projections at 24 users:

| Event | Frequency | Per-user cost | Total cost |
|---|---|---|---|
| Daily panels | Daily, 03:15 UTC | $0.07 | $1.68/day |
| Weekly clips | Sunday, 03:30 UTC | $0.25 | $6.00/week |
| Monthly recap video | 1st of month, 04:00 UTC | $0.25 | $6.00/month |
| Monthly hero image | 1st of month, 04:00 UTC | $0.07 | $1.68/month |

**Sunday cost spike**: Daily panels (03:15) + weekly clips (03:30) fire the same day. Combined: $1.68 + $6.00 = **$7.68** -- well under the $50 daily circuit breaker.

**1st-of-month spike** (if Sunday): All three fire: $1.68 + $6.00 + $7.68 = **$15.36** -- still under $50.

**Annual total**: ~$312 clips + ~$92 recaps + ~$613 panels = **~$1,017/year** at 24 users.

**Growth threshold**: The $50/day breaker trips at ~200 daily panels ($14) + 200 clips ($50) = 200 users on a Sunday. No action needed now, but if user count exceeds 150, consider raising the breaker or staggering clip generation across Saturday/Sunday.
