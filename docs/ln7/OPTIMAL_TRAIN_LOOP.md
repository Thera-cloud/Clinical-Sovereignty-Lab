# LN7 optimal train → gate → activate loop

One-liner: **clean preference JSONL (≥500 / target 2k) → 7B QLoRA A/B on Ada 20GB → private bakeoff → canary vs `LN7-fast-baseline` → CEO activate fast tier.** Deep 32B Ollama stays production deep.

## Serving tiers (Milestone A)

| Tier | Serve | Incumbent for promote | Notes |
|---|---|---|---|
| **fast** | PEFT `:11435` (`Qwen2.5-Coder-7B` + LoRA or bare) | `LN7-fast-baseline` (bare 7B) | Coding `harness_mode=fast` |
| **deep** | Ollama `qwen2.5-coder:32b` | `LN7-baseline` | Coding `max` / deep; **unchanged** this milestone |

Never compare a 7B LoRA candidate to `LN7-baseline` (32B) for activate.

## Train half

| Rule | Implementation |
|---|---|
| Data first | `backend/scripts/ln7_export_train_jsonl.py` — goldens + paraphrases + passed diffs; drops stubs / heldout `env_redis_prefix` |
| Length | Cap via `LN7_EXPORT_MAX_CHARS` (default 4000) |
| Persist diffs | Migration `294` + `record_outcome(patch_text=…)` |
| HF base | `LN7_QLORA_HF_BASE=Qwen/Qwen2.5-Coder-7B-Instruct` (= PEFT serve) |
| Recipe A/B | `--lora-recipe default` (q/v r=16) vs `all_linear` (all proj r=32 α=64) |
| Thin refuse | `LN7_QLORA_MIN_ROWS=500` for 7B burns; **no** `FORCE_THIN` for Milestone A |
| HARD_MAX | Default ~8h for 7B (`LN7_GPU_HARD_MAX_S` / ab drain 28800) |
| Export ceiling | Default `--limit` 2000; `LN7_EXPORT_PARAPHRASE_N=16` |
| Adapter keep | Last `LN7_ADAPTER_KEEP_N` (default 6) on BLUE + ORANGE |

```bash
# Seed micro packs then export (≥500 / stretch 2000)
PYTHONPATH=backend python3 backend/scripts/ln7_seed_train_packs.py
LN7_EXPORT_PARAPHRASE_N=16 LN7_EXPORT_LIMIT=2000 PYTHONPATH=backend \
  python3 backend/scripts/ln7_export_train_jsonl.py --out data/ln7_train.jsonl --goldens-only

# Bare 7B incumbent on ORANGE + register on GREEN
bash scripts/ln7_deploy_fast_baseline_orange.sh
bash scripts/ln7_register_fast_baseline.sh

# A/B TOR drains (identical JSONL) — refuse thin
LN7_QLORA_MIN_ROWS=500 bash scripts/ln7_ab_qlora_drain.sh
```

## Eval half (sovereign)

- Same packs / `build_pack_prompt` / seeds — never LLM-as-judge for promote
- Gate: candidate CI lower bound > **`LN7-fast-baseline`** point, `min_tasks≥3`
- Held-out pack `env_redis_prefix` never trains; bakeoff must cover ≥3 packs for canary
- `POST /api/ln7/canary/evaluate` with `start:true` resolves incumbent from revision tier

## Deploy half

- PEFT merge-on-load via `LN7_PEFT_URL` for fast shadow/active
- Deep path remains Ollama 32B (`LN7-baseline`)
- Tier-scoped activate (migration `300`) — activating fast does **not** roll back deep
- GGUF/Ollama merge only after ≥2 consecutive canary wins
- CEO activate only on `await_ceo` → `activate_revision`
- `ENABLE_LN7_AUTO_PROMOTE=false`

## DO GPU capacity watcher (BLUE)

LaunchAgent every 15m: **keep** probe → **detach** A/B on **one droplet** (both recipes) → private bakeoff compare → unload on `AB_OK` **or complete `AB_COMPARE`**. Prefail keeps `probe.env` for retry (capped by `LN7_MAX_DRAIN_FAILS`, default 2); then destroy probe + unload.

```bash
bash scripts/ln7_install_gpu_capacity_watch.sh
# success: ~/.local/state/ln7_gpu_watch/AB_OK
# compare: ~/.local/state/ln7_gpu_watch/AB_COMPARE  (winner hint; activate=false; incumbent=LN7-fast-baseline)
```

- Lives under `~/sovereign-ln7`; each tick syncs from Desktop (`LN7_SRC_REPO`) unless drain running.
- `FORCE_THIN` is **drain-time only** — never sticky in the LaunchAgent plist.

### Blocked-cycle one-shot (advance build)

Preferred SKU stays **`gpu-4000adax1-20gb`**. When every watch region returns inventory-unavailable, the watcher/drain may **one-shot** `LN7_GPU_ONESHOT_FALLBACK_SIZE` (default **`gpu-l40sx1-48gb`**) once per cooldown window to finish the A/B cycle — not a permanent SKU change.

| Env | Default | Role |
|---|---|---|
| `LN7_GPU_SIZE` / `LN7_GPU_PREFERRED_SIZE` | Ada 20GB | Steady-state probe |
| `LN7_GPU_ONESHOT_FALLBACK` | `1` | Allow blocked→advance |
| `LN7_GPU_ONESHOT_FALLBACK_SIZE` | `gpu-l40sx1-48gb` | One-shot only |
| `LN7_GPU_ONESHOT_COOLDOWN_S` | `21600` (6h) | After arm/consume |

Telemetry: `~/.local/state/ln7_gpu_watch/ONESHOT_TELEMETRY.jsonl` + `ONESHOT_LAST.json` (`primary_blocked` → `oneshot_attempt` → `oneshot_armed` → `oneshot_consume`).

## Bakeoff ops / watchdogs

See prior ops guards (`COMPARE_LOCK`, drain/orphan reapers, GREEN bakeoff sweep). Unchanged for Milestone A.

## Kill criteria

- Thin burn (`clean_n` &lt; 500) on 7B
- Default HF base still 1.5B
- Comparing 7B candidate to `LN7-baseline` (32B) for activate
- GGUF merge before 2 canary wins
- Auto-promote on
- Public SWE-bench as promote gate

## Milestone A status (2026-07-29)

| Gate | State |
|---|---|
| Clean JSONL | **2000** rows (`data/ln7_train.jsonl`) |
| `LN7_QLORA_MIN_ROWS` | **500** |
| HF / PEFT base | `Qwen2.5-Coder-7B-Instruct` |
| `LN7-fast-baseline` | Registered + **active fast**; PEFT `:11435` `loaded=true` bare |
| Deep | `LN7-baseline` 32B still active |
| A/B Ada drain | Preferred Ada still scarce; **oneshot L40S fallback wired** (telemetry + cooldown) so blocked cycles can advance; Ada remains default SKU |
| CEO activate LoRA | Deferred until private bakeoff CI lo &gt; `LN7-fast-baseline` |
