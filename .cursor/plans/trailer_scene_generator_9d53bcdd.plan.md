---
name: Trailer Scene Generator
overview: Create a trailer scene generator that calls Grok Imagine for all 19 Thera-World storyboard scenes, stores results in R2, and exposes an admin endpoint + dashboard button to trigger it.
todos:
  - id: create-generator
    content: Create backend/app/sse/trailer_generator.py with corrected imports (infrastructure, not foundation) and bytes->R2 flow
    status: completed
  - id: add-endpoint
    content: Add POST /api/sse/admin/generate-trailer endpoint to admin.py sse_router
    status: completed
  - id: add-button
    content: Add Generate Trailer button + JS handler to sse_monitoring.html
    status: completed
  - id: deploy
    content: Deploy all 3 files to GREEN, restart backend, verify health
    status: completed
isProject: false
---

# Thera-World Trailer Scene Generator

## Key Discovery: Import Paths and Return Types

The user's provided code has two issues that need correction:

- **Wrong import path**: `generate_image` lives at `backend/app/sse/infrastructure/grok_imagine_client.py`, not `foundation/`
- **Wrong return type**: `generate_image(prompt)` returns **`bytes`** (raw image data), not a dict with a `url` field. R2 upload is a separate step via `r2_storage.store_image(image_bytes, key) -> str` (returns the public CDN URL)

Existing pattern from the codebase (e.g. `layer6_imagination_engine.py` and the `regenerate-panel` endpoint in `admin.py`):

```python
from app.sse.infrastructure.grok_imagine_client import generate_image
from app.sse.infrastructure.r2_storage import store_image

image_bytes = await generate_image(prompt)
r2_url = await store_image(image_bytes, f"sse/trailer/scenes/{title}.png")
```

## Files to Create/Modify

### 1. NEW: [backend/app/sse/trailer_generator.py](backend/app/sse/trailer_generator.py)

- Contains the 19 `SCENE_PROMPTS` list exactly as specified by the user
- `generate_all_scenes()` iterates prompts, calls `generate_image` (returns bytes), then `store_image` to R2 at key `sse/trailer/scenes/{title}.png`
- 5-second delay between scenes
- On failure: log, record error status, continue to next scene
- Saves `manifest.json` to `/tmp/trailer_scenes/` with all URLs and statuses

### 2. MODIFY: [backend/app/routers/admin.py](backend/app/routers/admin.py)

Two endpoints on `sse_router` (already admin-gated). Generation takes ~2-3 minutes (19 scenes), so it runs as a **background task** to avoid HTTP timeout:

```python
@sse_router.post("/admin/generate-trailer")
async def generate_trailer(request: Request, background_tasks: BackgroundTasks):
    from app.sse.trailer_generator import generate_all_scenes
    background_tasks.add_task(generate_all_scenes)
    return {"status": "started", "message": "Generating 19 scenes — check manifest in ~3 minutes"}

@sse_router.get("/admin/trailer-status")
async def trailer_status(request: Request):
    manifest_path = "/tmp/trailer_scenes/manifest.json"
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            return json.load(f)
    return {"status": "not_started"}
```

~12 lines. Additive only. `BackgroundTasks` is already imported by FastAPI.

### 3. MODIFY: [dashboard/sse_monitoring.html](dashboard/sse_monitoring.html)

Add a "Generate Trailer" button in the admin actions row, following the existing button pattern:

```html
<button class="btn btn-gold" onclick="sseGenerateTrailer()">Generate Trailer</button>
```

JS handler starts generation then polls `/admin/trailer-status` every 10 seconds until all scenes complete:

```javascript
function sseGenerateTrailer() {
    fetch('/api/sse/admin/generate-trailer', {method:'POST', headers: _authHeaders()})
      .then(r => r.json())
      .then(d => {
        alert('Trailer generation started — 19 scenes, ~3 minutes');
        let poll = setInterval(() => {
          fetch('/api/sse/admin/trailer-status', {headers: _authHeaders()})
            .then(r => r.json())
            .then(s => {
              if (s.total && s.success === s.total) {
                clearInterval(poll);
                alert('All ' + s.total + ' scenes generated!');
              }
            });
        }, 10000);
      });
}
```

### 4. DEPLOY to GREEN

- `scp` the new file `trailer_generator.py` and modified `admin.py` to GREEN
- `scp` updated `sse_monitoring.html` to all 3 dashboard directories
- Restart backend, verify 112/112 healthy

## Execution Notes

- Generation runs as a FastAPI `BackgroundTasks` job. The POST returns immediately; the admin polls via GET `/admin/trailer-status`.
- `generate_image` already has built-in 429 retry with fallback key and a 2-second post-success sleep, so the effective delay per scene is ~7 seconds.
- The manifest is written incrementally — the status endpoint reflects progress as scenes complete.
- No changes to protected files.
