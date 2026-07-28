# Overnight serve→measure→activate loop (2026-07-28)

## Verdict

**Loop is real for serve + measure. Safe refuse to activate.**  
PEFT brain is live on ORANGE and used for revision-tagged bakeoff; earlier candidate **lost** to `LN7-baseline` (1/3 vs ~0.53). Serving stays on baseline Ollama coders. `ENABLE_LN7_AUTO_PROMOTE=false`.

| Step | Status |
|---|---|
| 1 ORANGE Ollama | OK — `:11434` WG; 4 coder models |
| 2 Persist + wire adapter | OK — PEFT `:11435`; GREEN `LN7_PEFT_URL`; revision routing |
| 3 Held-out bakeoff | Prior PEFT rev **1/3**; new shadow `LN7-2026-07-28T131841Z` canary **hold** (`insufficient_tasks`) |
| 4 CEO activate | **SKIPPED** until bakeoff beats baseline |
| 5–6 Worker + continuous | **ON** — LaunchAgent `com.sovereign.ln7-continuous-worker` → `~/sovereign-ln7` (Desktop TCC bypass); `LN7_GPU_REGION=tor1` |

## TOR drain (implemented 2026-07-28 ~13:08Z)

- Queue had 2 jobs (`usage_reject`, `outcome`) → drained on `gpu-4000adax1-20gb` @ tor1
- Adapter/revision: `LN7-2026-07-28T131841Z` (dir `LN7-2026-07-28T130851Z`) on ORANGE `/opt/ln7/adapters` + BLUE `.ln7-adapters/`
- Droplet `588163082` destroyed after register
- Jobs 2+4 status → `canary` (not auto-promoted)
- Logs: `~/Library/Logs/ln7-continuous-worker.{out,err}.log`

## Key artifacts

- Serve: `http://10.13.13.5:11435` model `ln7-peft` (active traffic still baseline)
- Active: `LN7-baseline`
- Worker home copy: `~/sovereign-ln7` (keep in sync with Desktop repo scripts when changing drain)

## Ops

```bash
# status
launchctl print gui/$(id -u)/com.sovereign.ln7-continuous-worker | egrep 'state|pid'
tail -f ~/Library/Logs/ln7-continuous-worker.out.log

# stop
launchctl bootout gui/$(id -u)/com.sovereign.ln7-continuous-worker

# start
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sovereign.ln7-continuous-worker.plist
```
