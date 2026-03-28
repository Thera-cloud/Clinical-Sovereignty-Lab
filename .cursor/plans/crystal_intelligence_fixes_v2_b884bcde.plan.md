---
name: Crystal Intelligence Fixes v2
overview: "Implement the Crystal Intelligence Fixes v2 spec: swap the Blue Harvester's one-size-fits-all filter for domain-aware prompts (highest leverage), fix the autonomous controller's forge pipeline by lowering CLUSTER_MIN_ITEMS for coding domain and adding solo forge, wire Blue Harvester heartbeat reporting to the dashboard, and enrich the dashboard with live metrics for the Blue Harvester card."
todos:
  - id: filter-prompts
    content: Replace BLUE_STAGE1_PROMPT with domain-aware filter prompts in blue_harvester.py (coding, therapeutic, architecture, operations, general)
    status: completed
  - id: forge-fix
    content: Lower CLUSTER_MIN_ITEMS to 2 for coding domain in nate_memory_crystallizer.py + update autonomous_controller.py buffer threshold + add solo forge for high-confidence fragments
    status: completed
  - id: heartbeat
    content: Add report_heartbeat() to blue_harvester.py + POST /admin/crystal-heartbeat endpoint in nate_agent_api.py
    status: completed
  - id: dashboard-bh
    content: Enrich Blue Harvester card in skyeye.html with live metrics (chunks progress, pass rate, scanner, crystals forged)
    status: completed
  - id: verify-sync
    content: Verify BLUE-to-GREEN sync is wired and PRODUCTION_DATABASE_URL is configured
    status: completed
isProject: false
---

# Crystal Intelligence Fixes v2

## Problem Summary

The Blue Harvester is currently running (chunk 580/2859) but rejecting ~85% of coding knowledge chunks because the single filter prompt (`BLUE_STAGE1_PROMPT`) evaluates everything through a therapeutic lens. The autonomous controller buffer is stuck at 2 fragments because the same filter rejects TENSION resolutions before they accumulate, and `CLUSTER_MIN_ITEMS = 3` means 2 fragments can never form a cluster. The dashboard Blue Harvester card shows zero live metrics.

## Step 1: Domain-Aware Filter Prompts (Highest Leverage)

**File:** `backend/blue_harvester.py`

Replace the single `BLUE_STAGE1_PROMPT` (lines 29-61) with domain-aware prompts from the v2 spec. The existing `OllamaFilter.evaluate()` method at line 523 already receives the chunk's `scanner_name` and `domain` — it just needs to select the right prompt instead of always using `BLUE_STAGE1_PROMPT`.

- Add 5 domain-specific prompt strings from Section 3 of the v2 spec: `coding`, `therapeutic`, `architecture`, `operations`, `general`
- Add `SCANNER_DOMAIN_MAP` dict mapping scanner names to domains
- Add `get_filter_prompt(scanner_name, chunk_domain)` that returns the appropriate prompt
- Modify `OllamaFilter.evaluate()` to call `get_filter_prompt()` instead of hardcoding `BLUE_STAGE1_PROMPT`
- Keep the existing PASS/FAIL/DOMAIN/CRYSTAL response parsing unchanged

**Expected impact:** Pass rate climbs from ~15% to ~50% for coding scanners (SovereignRules, CursorRules, GitHistory). NightSchool stays ~40% (already therapeutic-focused).

**Key code change in `OllamaFilter.evaluate()`:**

```python
# Replace:
prompt = BLUE_STAGE1_PROMPT.format(chunk_text=bounded_chunk)
# With:
base_prompt = get_filter_prompt(chunk.scanner_name, chunk.domain)
prompt = base_prompt + f"\n\nTEXT CHUNK:\n{bounded_chunk}"
```

The domain-aware coding prompt PASSes deployment patterns, error+fix pairs, Cursor rules, config rationale, architecture decisions — exactly what the current prompt labels "boilerplate" and rejects.

## Step 2: Autonomous Controller Forge Fix

**File:** `backend/app/services/nate_memory_crystallizer.py`

The root cause: `CLUSTER_MIN_ITEMS = 3` (line 275) prevents a buffer of 2 coding fragments from ever forming a cluster. Three changes:

- Change `CLUSTER_MIN_ITEMS` from `3` to `2` globally. This is safe because the cluster synthesis still requires semantic affinity (Jaccard threshold 0.75). A cluster of 2 unrelated items will not synthesize — they must overlap.
- Alternatively, make it domain-specific: coding/architecture/operations = 2, clinical/therapeutic = 3 (per v2 spec). This requires modifying `_cluster_and_synthesize_cycle()` to check domain before applying the threshold.

**File:** `backend/app/websocket/autonomous_controller.py`

- The buffer check at line 445 (`>= 3`) hardcodes 3. Update to match the new minimum (`>= 2`).
- Add solo forge for high-confidence fragments (>= 0.75): skip clustering entirely and write directly. This unblocks the "buffer=2, forged=0" deadlock immediately.

The forge pipeline is: fragments enter buffer via `_harvest_buffer.append()` -> `_cluster_and_synthesize_cycle()` groups by domain -> clusters with >= MIN items synthesize via LLM -> crystals written. The blockage is at the clustering gate.

## Step 3: Blue Harvester Heartbeat + Dashboard Metrics

**File:** `backend/blue_harvester.py`

Add a `report_heartbeat()` async function that POSTs metrics to the production API. Call it:

- Every 25 chunks during a scan
- At the end of each scanner
- On startup and shutdown

The heartbeat payload includes: `chunks_processed`, `chunks_total`, `chunks_passed`, `pass_rate`, `current_scanner`, `current_file`, `avg_filter_time_ms`, `crystals_forged_session`.

**File:** `backend/app/routers/nate_agent_api.py`

Add a `POST /admin/crystal-heartbeat` endpoint (around line 3094, before the status endpoint) that:

- Accepts the heartbeat JSON
- Writes to `crystal_factory_heartbeats` table (already exists — used by Hetzner/DO)
- Uses `node_id = "blue"` with `ON CONFLICT` upsert

The existing status endpoint at line 3097 already reads `crystal_factory_heartbeats` and the `crystal_system_status:blue_harvester` Redis key. Once heartbeats arrive, the Blue Harvester card auto-populates.

**File:** `dashboard/skyeye.html`

Enrich the Blue Harvester card rendering (lines 6068-6074) to display live metrics from the heartbeat data. Currently it only shows `status` and a static message. Add:

- Chunks progress (e.g., "580/2859 (20%)")
- Pass rate
- Current scanner
- Crystals forged
- Last crystal timestamp

The status endpoint response already includes `blue_harvester` object — it just needs the heartbeat data populated.

## Step 4: Dashboard Active Crystal Count Verification

The 7.8K and 8.9K "Crystals (active)" values that didn't change between screenshots are actually live queries (confirmed by reading the API at line 3105-3120). The query correctly filters `WHERE scope != 'archived' AND superseded_by IS NULL`. These counts are slow-moving (only change when new crystals are forged or old ones archived), so unchanged values over 10 minutes is expected behavior — not a bug. No fix needed.

## Step 5: BLUE-to-GREEN Sync Improvements

The autonomous controller already has `_sync_blue_to_green()` (line 998) that calls `crystallizer.sync_to_production()` when `PRODUCTION_DATABASE_URL` is set. This is already wired. The main bottleneck is that `PRODUCTION_DATABASE_URL` must be set on the Mac for the sync to run.

- Verify `PRODUCTION_DATABASE_URL` env var is set in the blue harvester config or Mac environment
- The sync already runs as Priority 7 in the learn cycle (line 469-473)
- GREEN-to-BLUE (reverse sync) is handled by the `_fetch_green_mac_total()` method for status display, but full reverse crystal pull needs the `CrystalSync` class from the v2 spec if not already wired — this is a separate step that can follow

## What This Does NOT Change

- No changes to `bridge_server.py` (protected file)
- No changes to `main.py` (protected file)
- No changes to the Nevedal formula constants
- No changes to trust baseline / auditor counts
- CLI-Cloud/CLI-Mac architecture mapping (Section 5 of v2 spec) is a design document, not code changes — it describes the existing dual-brain architecture
- VS Code extension crystallization wiring (future PR)
- Subconscious Engine worker bodies (future PR)

## Files Modified

- `backend/blue_harvester.py` — domain-aware filter + heartbeat reporter
- `backend/app/services/nate_memory_crystallizer.py` — lower CLUSTER_MIN_ITEMS for coding domain
- `backend/app/websocket/autonomous_controller.py` — lower buffer check threshold + solo forge
- `backend/app/routers/nate_agent_api.py` — heartbeat endpoint
- `dashboard/skyeye.html` — Blue Harvester card live metrics rendering

## Verification Runbook

### After Step 1: Domain-Aware Filter

**On Mac (where Blue Harvester runs):**

Stop the current harvester run (Ctrl+C), restart with the new code, and tail the output:

```bash
python3 backend/blue_harvester.py 2>&1 | tail -f
```

Watch for the FAIL reasons to change. Before the fix, you see:

> "boilerplate", "practical troubleshooting tips", "file paths which are boilerplate"

After the fix, coding chunks should show PASS. Verify visually:

```bash
# Count pass/fail over the next 50 chunks
python3 backend/blue_harvester.py --max-chunks 50 2>&1 | grep "Result:" | sort | uniq -c
```

- **PASS criteria:** Pass rate for SovereignRulesScanner / CursorRulesScanner chunks rises from ~15% to ~40-50%+
- **FAIL criteria:** Pass rate stays below 20% (prompt not taking effect, or model override still routing to clinical model for coding chunks)

### After Step 2: Controller Forge Fix

**On production server (GREEN):**

After deploying the updated `nate_memory_crystallizer.py` and `autonomous_controller.py` to GREEN and restarting the backend:

```bash
ssh root@68.183.168.75 "docker logs nate_bridge --since 5m 2>&1 | grep '\[AUTONOMOUS\]' | tail -20"
```

Watch for the learn cycle line to change from:

> `+0 new, buffer=2`

To:

> `+N new, buffer=0` (or any forged > 0)

Also check the dashboard Crystal Intelligence tab:

- SYSTEM 04 (Autonomous Controller): "Crystals forged" should be > 0
- SYSTEM 04: "Buffer size" should decrease or cycle between 0 and small numbers

**Direct DB verification:**

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') AS last_hour FROM nate_intelligence_crystals WHERE source = 'autonomous_controller' OR face_path LIKE '%bridge%'\""
```

- **PASS criteria:** `last_hour > 0` after the controller has run at least 2 learn cycles (~2 minutes)
- **FAIL criteria:** `last_hour = 0` after 5+ minutes — check bridge logs for `[FORGE]` errors

### After Step 3: Heartbeat + Dashboard Metrics

**On Mac (Blue Harvester heartbeat):**

After restarting the harvester with heartbeat code:

```bash
python3 backend/blue_harvester.py 2>&1 | grep -i "heartbeat"
```

Should see periodic lines like:

> `Heartbeat OK: running`

If you see `Heartbeat HTTP 401` or `Heartbeat failed`, check:

- `BRIDGE_ADMIN_TOKEN` env var is set
- The `/admin/crystal-heartbeat` endpoint is deployed on GREEN

**On production server (heartbeat arrived):**

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT node_id, status, crystals_forged, fragments_harvested, created_at FROM crystal_factory_heartbeats WHERE node_id = 'blue' ORDER BY created_at DESC LIMIT 3\""
```

- **PASS criteria:** Row exists with `node_id = 'blue'` and `created_at` within the last few minutes
- **FAIL criteria:** No rows — endpoint not deployed, auth failing, or heartbeat not sending

**On dashboard:**

Open SkyEye > Crystal Intelligence tab. The Blue Harvester card (SYSTEM 03) should show:

- Status badge: RUNNING (green dot) instead of STALE (gray/red)
- Chunks progress: e.g., "580/2859"
- Pass rate percentage
- Current scanner name
- **PASS criteria:** Card shows live metrics with non-zero chunk progress
- **FAIL criteria:** Card still shows "Status: stale" with the static message

### After Step 4: Crystal Count Verification (no fix needed)

No deployment action. This is a confirmation that the 7.8K / 8.9K counts are live queries. Verify with:

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT CASE WHEN face_path LIKE 'factory:hetzner%' THEN 'hetzner' WHEN face_path LIKE 'factory:digitalocean%' THEN 'digitalocean' ELSE 'other' END AS node, COUNT(*) FROM nate_intelligence_crystals WHERE scope != 'archived' AND superseded_by IS NULL GROUP BY 1\""
```

The counts should match what the dashboard displays (within rounding of the K suffix).

### After Step 5: BLUE-to-GREEN Sync

**On Mac (verify env var):**

```bash
echo $PRODUCTION_DATABASE_URL
```

Must return a valid `postgresql://nate_admin:...@68.183.168.75:5432/little_nate` connection string. If empty, sync cannot run.

**On Mac (verify sync ran):**

After the autonomous controller completes a learn cycle with sync enabled:

```bash
python3 backend/blue_harvester.py 2>&1 | grep -i "sync"
```

Or check autonomous controller logs on the bridge:

```bash
ssh root@68.183.168.75 "docker logs nate_bridge --since 10m 2>&1 | grep 'blue_green_sync'"
```

Should show: `"detail": "pushed N crystals"` or `"detail": "All crystals synced"`

**On production PG (confirm arrival):**

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT COUNT(*) AS blue_crystals, MIN(created_at) AS earliest, MAX(created_at) AS latest FROM nate_intelligence_crystals WHERE face_path LIKE 'factory:blue%' OR face_path LIKE 'factory:mac-blue%'\""
```

- **PASS criteria:** `blue_crystals > 0` and `latest` is recent
- **FAIL criteria:** `blue_crystals = 0` — either `PRODUCTION_DATABASE_URL` not set, or sync method not implemented on the crystallizer

### End-to-End Smoke Test

After all 5 steps are deployed, wait 10 minutes, then run this single composite check:

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
SELECT
  'crystals_total' AS metric, COUNT(*)::text AS value FROM nate_intelligence_crystals WHERE scope != 'archived'
UNION ALL
SELECT
  'crystals_last_hour', COUNT(*)::text FROM nate_intelligence_crystals WHERE created_at > NOW() - INTERVAL '1 hour'
UNION ALL
SELECT
  'blue_heartbeat_age', EXTRACT(EPOCH FROM NOW() - MAX(created_at))::int::text || 's' FROM crystal_factory_heartbeats WHERE node_id = 'blue'
UNION ALL
SELECT
  'blue_crystals_in_green', COUNT(*)::text FROM nate_intelligence_crystals WHERE face_path LIKE 'factory:%blue%'
ORDER BY 1
\""
```

- `crystals_total`: should be > previous total (growing)
- `crystals_last_hour`: should be > 0 (active forging)
- `blue_heartbeat_age`: should be < 300s (heartbeat alive)
- `blue_crystals_in_green`: should be > 0 (sync working)

