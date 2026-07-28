# LN7 Continuous Gated Self-Improvement

Honest product name — **not AGI**. Coder-domain only. Identity firewall unchanged (zero vendor calls on LN7 path; no held-out training; no clinical AGI claims).

## Loop

```
green outcome / reject-edit usage-event
  → ln7_train_jobs (queue)
  → batch ≥ MIN_BATCH
  → GREEN stages job (status=training)
  → BLUE / CUDA worker: export JSONL → QLoRA → register revision
  → shadow canary (LN7_SHADOW_SPEND + ln7_canary_state)
  → statistical_gate vs incumbent
  → ENABLE_LN7_AUTO_PROMOTE ? activate(policy_auto) : await CEO
  → else hold / rollback on regression
```

## Flags

| Flag | Role |
|---|---|
| `ENABLE_LN7_CONTINUOUS` | Queue + agent on GREEN |
| `ENABLE_LN7_AUTO_PROMOTE` | Policy flip after gate (default off — CEO remains gate) |
| `LN7_CONTINUOUS_MIN_BATCH` | Min outcomes before claim |
| `LN7_CANARY_TRAFFIC_PCT` | Canary bookkeeping % |

## APIs

- `GET /api/ln7/train/jobs`
- `POST /api/ln7/train/enqueue` `{outcome_id}`
- `POST /api/ln7/canary/evaluate` `{revision_id, start?}` — on `await_ceo` + gate ok, re-notifies CEO with `[READY]` brief
- `GET /api/ln7/revision/{id}/readiness` — admin readiness snapshot for Dual-COO briefs

CEO inbox LN7 asks include readiness facts; first notify after train is often YELLOW HOLD, second after canary/bakeoff is RED READY (see RUNBOOK).

## Worker (never GREEN)

```bash
# On CUDA droplet or Apple Silicon:
python backend/scripts/ln7_export_train_jsonl.py --out /tmp/job.jsonl
python backend/scripts/ln7_qlora_train.py --train-jsonl /tmp/job.jsonl --backend cuda
python backend/scripts/ln7_micro_qlora_worker.py --job-id N --train-jsonl /tmp/job.jsonl --backend cuda
```

## Migration

`backend/migrations/293_ln7_continuous_train_queue.sql` → `ln7_train_jobs`, `ln7_canary_state`.

## Gap vs AGI

This is continuous **coding** self-improvement. Cross-domain world models, long-horizon agency, and reliable transfer are out of LN7 scope.

## Overnight proof (2026-07-28)

| Gate | Evidence |
|---|---|
| ORANGE SSH | GREEN `id_ed25519_orange` → `10.13.13.5` OK |
| CUDA train | DO `gpu-4000adax1-20gb` tor1; method `cuda_qlora_peft`; loss 4.2→2.86 / 40 steps |
| Revision | `LN7-2026-07-28T052742Z` shadow (CEO activate still required) |
| Continuous | GREEN agent on; `ENABLE_LN7_AUTO_PROMOTE=false` |
| Cost hygiene | Ephemeral droplet destroyed via `scripts/ln7_destroy_cuda_droplet.sh` |
| Durable drain | `scripts/ln7_continuous_drain.sh` → `LN7-2026-07-28T054529Z` + adapter `LN7-2026-07-28T054420Z` on ORANGE+BLUE; droplet `588078184` destroyed |
| Labels | Revisions store `hf_base=Qwen/Qwen2.5-Coder-1.5B-Instruct`, `quantization=nf4_qlora` (serve models remain Ollama `LN7_CODE_MODEL_*`) |
| Preference | `usage-event rejected` → `ln7_train_jobs` `trigger_source=usage_reject` |
| Canary CL | `_forgetting_monitor` + held-out outcome count on `canary/evaluate` |
| Auto-promote | stays **false** — gate may `await_ceo` only |
| PEFT serve | ORANGE `ln7_peft_server` `:11435` — active/shadow QLoRA revisions route via `LN7_PEFT_URL` |
| Always-on worker | `LN7_WORKER_LOOP=1 bash scripts/ln7_continuous_worker.sh` (TOR drain when queue > 0) |
| PEFT bakeoff (2026-07-28) | `LN7-2026-07-28T054529Z` via `:11435` → **1/3** packs; baseline ~0.53 — **no CEO activate**; status `shadow` / canary `hold_shadow` |
| ORANGE UFW | `11435/tcp` ALLOW from `10.13.13.0/24` (same posture as Ollama `11434`) |
| Train bugfix | `ln7_qlora_train.py` must write `train_meta.json` — never overwrite PEFT `adapter_config.json` |
