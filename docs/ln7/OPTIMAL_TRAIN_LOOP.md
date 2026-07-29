# LN7 optimal train → gate → activate loop

One-liner: **clean preference JSONL → all-linear QLoRA A/B → sandbox bakeoff → canary → CEO activate → (later) optional GGUF.**

## Train half

| Rule | Implementation |
|---|---|
| Data first | `backend/scripts/ln7_export_train_jsonl.py` — `passed=true` + real `patch_text`, reject→fix pairs, goldens for train packs; drops stubs / heldout `env_redis_prefix` |
| Length | Cap via `LN7_EXPORT_MAX_CHARS` (default 4000) |
| Persist diffs | Migration `294` + `record_outcome(patch_text=…)` |
| Base = serve | `LN7_QLORA_HF_BASE=Qwen/Qwen2.5-Coder-1.5B-Instruct` (= `:11435`) |
| Recipe A/B | `--lora-recipe default` (q/v r=16) vs `all_linear` (all proj r=32 α=64) |
| Thin refuse | `LN7_QLORA_MIN_ROWS=50`; override `LN7_QLORA_FORCE_THIN=1` at **drain time only** (never baked into LaunchAgent plist) |
| Iters / HARD_MAX | Auto from `clean_n`: &lt;50→40/4h; 50–199→80/4h; 200–499→120/5h; ≥500→200/6h (`LN7_QLORA_ITERS` / `LN7_GPU_HARD_MAX_S` override) |
| Export ceiling | Default `--limit` 2000 (`LN7_EXPORT_LIMIT`); growth path = seed packs → export → re-arm watcher |
| Adapter keep | Last `LN7_ADAPTER_KEEP_N` (default 6) on BLUE `.ln7-adapters/` + ORANGE `/opt/ln7/adapters/`; active protected |

```bash
# Seed extra train packs (broken+test+golden) then export (≥50 via goldens×paraphrases)
PYTHONPATH=backend python backend/scripts/ln7_seed_train_packs.py
LN7_EXPORT_PARAPHRASE_N=3 LN7_EXPORT_LIMIT=2000 PYTHONPATH=backend \
  python backend/scripts/ln7_export_train_jsonl.py --out data/ln7_train.jsonl

# A/B TOR drains (identical JSONL) — refuse thin unless override
LN7_QLORA_MIN_ROWS=50 bash scripts/ln7_ab_qlora_drain.sh
# thin override only while bootstrapping (shell one-shot, not plist):
# LN7_QLORA_FORCE_THIN=1 bash scripts/ln7_ab_qlora_drain.sh
```

## Eval half (sovereign)

- Same packs / `build_pack_prompt` / seeds — never LLM-as-judge for promote
- Gate: candidate CI lower bound > incumbent point, `min_tasks≥3`
- Held-out pack `env_redis_prefix` never trains; bakeoff must cover ≥3 packs for canary

## Deploy half

- PEFT merge-on-load via `LN7_PEFT_URL` for shadow/active
- GGUF/Ollama only after ≥2 consecutive canary wins
- CEO activate only on `await_ceo` → `activate_revision`
- `ENABLE_LN7_AUTO_PROMOTE=false`

## DO GPU capacity watcher (BLUE)

LaunchAgent every 15m: **keep** probe → **detach** A/B on **one droplet** (both recipes) → private bakeoff compare → unload only on `AB_OK`. Prefail keeps `probe.env` for retry; `doctl` auth Forbidden backs off.

```bash
bash scripts/ln7_install_gpu_capacity_watch.sh
# logs: ~/Library/Logs/ln7-gpu-capacity-watch*.log  ~/Library/Logs/ln7_ab_qlora_drain.log
# success: ~/.local/state/ln7_gpu_watch/AB_OK
# compare: ~/.local/state/ln7_gpu_watch/AB_COMPARE  (winner hint; activate=false)
# stop: bash scripts/ln7_install_gpu_capacity_watch.sh --uninstall
# re-arm: bash scripts/ln7_install_gpu_capacity_watch.sh --reset
```

- Lives under `~/sovereign-ln7`; each tick syncs from Desktop (`LN7_SRC_REPO`) unless drain running.
- A/B: `LN7_KEEP_DROPLET` handoff — no second create TOCTOU; venv/torch reused on recipe B.
- SSH waits for cloud-init + apt locks; TTL is **idle heartbeat** (not hard kill mid-train); hard max 4h.
- Pauses `com.sovereign.ln7-continuous-worker` during A/B (GPU contention).
- `FORCE_THIN` is **drain-time only** — never sticky in the LaunchAgent plist. Drain refuses thin when clean JSONL &lt; `MIN_ROWS` unless `LN7_QLORA_FORCE_THIN=1` is exported for that shell run.
- Bakeoff compare: sequential PEFT deploy → `POST /bakeoff` with `background:true` → poll scorecard `?since=` (poll max `max(7200, packs×600)`).
- Adapter prune after persist keeps last N shadows (+ active).

## Kill criteria

Empty/thin queue burn, recipe change without A/B, promote on vibe/judge, Ollama merge before PEFT clears gate.
