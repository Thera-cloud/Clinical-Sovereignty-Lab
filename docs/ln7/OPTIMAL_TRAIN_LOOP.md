# LN7 optimal train → gate → activate loop

One-liner: **clean preference JSONL → all-linear QLoRA A/B → sandbox bakeoff → canary → CEO activate → (later) optional GGUF.**

## Train half

| Rule | Implementation |
|---|---|
| Data first | `backend/scripts/ln7_export_train_jsonl.py` — `passed=true` + real `patch_text`, reject→fix pairs, goldens for train packs; drops stubs / heldout `env_redis_prefix` |
| Length | Cap ~4k chars (pack-scale) |
| Persist diffs | Migration `294` + `record_outcome(patch_text=…)` |
| Base = serve | `LN7_QLORA_HF_BASE=Qwen/Qwen2.5-Coder-1.5B-Instruct` (= `:11435`) |
| Recipe A/B | `--lora-recipe default` (q/v r=16) vs `all_linear` (all proj r=32 α=64) |
| Thin refuse | `LN7_QLORA_MIN_ROWS=50` (target 200–500 before raising iters); override `LN7_QLORA_FORCE_THIN=1` |

```bash
# Rebuild clean JSONL (goldens offline; DB when DATABASE_URL set)
PYTHONPATH=backend python backend/scripts/ln7_export_train_jsonl.py --out data/ln7_train.jsonl

# A/B TOR drains (identical JSONL)
LN7_QLORA_MIN_ROWS=2 LN7_QLORA_FORCE_THIN=1 bash scripts/ln7_ab_qlora_drain.sh   # only while data thin — prefer real ≥50
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

When TOR/stock returns `Size is not available`, install a LaunchAgent that probes create→delete every 15m and **self-unloads** on first accept, optionally starting A/B drain:

```bash
bash scripts/ln7_install_gpu_capacity_watch.sh
# logs: ~/Library/Logs/ln7-gpu-capacity-watch*.log
# done: ~/.local/state/ln7_gpu_watch/AVAILABLE
# stop: bash scripts/ln7_install_gpu_capacity_watch.sh --uninstall
# re-arm: bash scripts/ln7_install_gpu_capacity_watch.sh --reset
```

- Lives under `~/sovereign-ln7` (Desktop TCC bypass).
- Default `LN7_GPU_WATCH_AUTO_DRAIN=1` + `LN7_QLORA_FORCE_THIN=1` (drop FORCE_THIN once clean JSONL ≥50).
- Not Workers AI — plain `doctl` poll ($0 LLM).

## Kill criteria

Empty/thin queue burn, recipe change without A/B, promote on vibe/judge, Ollama merge before PEFT clears gate.
