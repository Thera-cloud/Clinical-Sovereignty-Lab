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
- `POST /api/ln7/canary/evaluate` `{revision_id, start?}`

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
