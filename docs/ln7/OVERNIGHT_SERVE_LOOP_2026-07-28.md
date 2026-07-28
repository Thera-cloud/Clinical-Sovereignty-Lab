# Overnight serve→measure→activate loop (2026-07-28)

## Verdict

**Loop is real for serve + measure. Safe refuse to activate.**  
PEFT brain is live on ORANGE and used for revision-tagged bakeoff; it **lost** to `LN7-baseline` (1/3 vs ~0.53). Serving stays on baseline Ollama coders. `ENABLE_LN7_AUTO_PROMOTE=false`.

| Step | Status |
|---|---|
| 1 ORANGE Ollama | OK — `:11434` WG; 4 coder models |
| 2 Persist + wire adapter | OK — `/opt/ln7/adapters/LN7-2026-07-28T054420Z` + `ln7_peft_server` `:11435`; GREEN `LN7_PEFT_URL`; router/harness revision routing |
| 3 Held-out bakeoff | OK ran on PEFT — **1/3** (`asyncpg_cast` only) |
| 4 CEO activate | **SKIPPED** (gate fail) — revision `shadow`, canary `expired` |
| 5–6 Worker + continuous | GREEN `ENABLE_LN7_CONTINUOUS=true`; scripts + LaunchAgent attempted — **macOS TCC blocks Cursor/launchd SSH to GREEN**; run worker from Terminal.app or grant Full Disk Access |

## Key artifacts

- Serve: `http://10.13.13.5:11435` model `ln7-peft`
- UFW: `11435/tcp` from `10.13.13.0/24`
- Train bug: do not overwrite PEFT `adapter_config.json` (fixed → `train_meta.json`)
- Candidate: `LN7-2026-07-28T054529Z` (shadow)
- Active: `LN7-baseline`

## Next train (TOR)

Need more/better JSONL or larger HF base before another CEO gate. Worker:  
`LN7_WORKER_LOOP=1 LN7_GPU_REGION=tor1 bash scripts/ln7_continuous_worker.sh`  
(from Terminal outside Cursor sandbox).
