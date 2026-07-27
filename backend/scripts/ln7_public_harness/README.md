# LN7 Public Benchmark Harnesses

Run on **ORANGE or BLUE only** — never execute full containers on GREEN.

## Layout

```
LN7_PUBLIC_HARNESS_ROOT/
  swe_bench_verified/run.sh      # official SWE-bench Verified harness
  livecodebench/run.sh
  aider_polyglot/run.sh
  terminal_bench/run.sh
```

Each `run.sh` must write `docs/ln7/public_results/<benchmark>.json` (or `$LN7_PUBLIC_RESULTS_DIR`) with:

```json
{
  "benchmark": "swe_bench_verified",
  "status": "ok",
  "mode": "full",
  "report_only": true,
  "pass_rate": {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0},
  "contestant_pins": {},
  "notes": ""
}
```

## Modes

| Env | Behavior |
|---|---|
| `LN7_PUBLIC_HARNESS_MODE=smoke` | Tiny in-repo tasks via sovereign LN7 (CI / wiring) |
| `LN7_PUBLIC_HARNESS_MODE=ingest` | Read JSON from results dir only |
| `LN7_PUBLIC_HARNESS_MODE=full` | Call `run.sh` under harness root |

## Operator flow

1. Clone official harnesses under `/opt/ln7-harness/<name>/` on ORANGE/BLUE.
2. Point models at LN7 Ollama (`LN7_INFERENCE_URL`).
3. `bash run.sh` → JSON results.
4. Copy JSON to GREEN `docs/ln7/public_results/` or set `LN7_PUBLIC_HARNESS_MODE=ingest` on GREEN bakeoff.
5. `POST /api/ln7/bakeoff` — public rows appear with real pass rates.

Smoke scores are **not** competitive claims. Full harness scores remain report-only vs private held-out gate.
