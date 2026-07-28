# Little Nate 7 Runbook

## Identity

- Product name stays **Little Nate 7** forever (major=7).
- Revisions are ISO UTC timestamps (`LN7-2026-07-27T153022Z`), never `8` / `9`.
- LN7 is a **sovereign system**: local coder weights + best-of-N + sandbox verifier + retrieval.
- Zero vendor calls inside the LN7 path. Foundry / xAI / Fable / Mythos are **contestants only**.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `ENABLE_LN7` | true | Master |
| `ENABLE_LN7_HARNESS` | true | Best-of-N / repair |
| `ENABLE_LN7_BAKEOFF` | true | Bakeoff API |
| `CLI_CODE_GENERATOR` | ln7 | `ln7` or `contestant` |
| `LN7_PROMOTE_REQUIRES_CEO` | true | Serving flip needs CEO |
| `LN7_DUAL_COO_NOTIFY` | true | Enqueue CEO inbox |
| `LN7_KILL_SWITCH` | false | Halt all LN7 generation |
| `LN7_CODE_MODEL_DEEP/MID/FAST` | qwen2.5-coder:* | Ollama coder weights |
| `NATE_CLI_REASONING_MODEL` | grok-4-1-fast-reasoning | Contestant (never `grok-4.5` on Foundry) |

## Revision bump (timestamp only)

1. Run bakeoff: `POST /api/ln7/bakeoff` with `{"revision_id":"LN7-baseline","mode":"max"}`.
2. Collect rejection samples / train adapter offline on BLUE (MLX QLoRA) or rented GPU — never GREEN.
3. `POST /api/ln7/revision/register` with scorecard + notes → writes `docs/ln7/LN7_<ts>.md`.
4. Shadow: set status `shadow` (candidate answers in parallel; not user-visible).
5. Statistical gate: candidate CI lower bound > incumbent point on private held-out.
6. Dual-COO + CEO APPROVE → `POST /api/ln7/revision/activate`.
7. Rollback: re-activate previous `revision_id`.

## Add a contestant

Insert/update `ln7_contestants` with `base_url`, `model_id`, credentials in env, `enabled=true`, and `version_captured_at=NOW()`. Nothing is reported as "working" without credentials.

## Leaderboard

`GET /api/ln7/leaderboard?days=30` — always shows cost/latency next to pass rate. Never cite as clinical AGI evidence.

## Reproduce a scorecard row

`GET /api/ln7/scorecard/{revision_id}` for stored outcomes; re-run private packs via `POST /api/ln7/bakeoff`.

## Kill switch

Set `LN7_KILL_SWITCH=true` and recreate bridge/backend containers. Harness returns immediately with `error=kill_switch`.

## Continuous gated self-improvement (2026-07-28)

See [CONTINUOUS_GATED_SELF_IMPROVEMENT.md](./CONTINUOUS_GATED_SELF_IMPROVEMENT.md) and **[OPTIMAL_TRAIN_LOOP.md](./OPTIMAL_TRAIN_LOOP.md)** (clean JSONL → A/B QLoRA → bakeoff → CEO).

| Piece | Status |
|---|---|
| Train queue + canary tables | migration `293` |
| Outcome `patch_text` | migration `294` — required for clean export |
| GREEN agent | `Ln7ContinuousAgent` behind `ENABLE_LN7_CONTINUOUS` |
| CUDA QLoRA | `ln7_qlora_train.py --backend cuda --lora-recipe {default\|all_linear}` |
| Clean export | `ln7_export_train_jsonl.py` (passed + pairs + goldens; no hash stubs) |
| Public upstream clones | BLUE `.ln7-harness/<bench>/upstream/` (gitignored) |
| ORANGE SSH from GREEN | **OK** — `id_ed25519_orange` (passphrase-locked default key is not used) |
| Durable adapters | ORANGE `/opt/ln7/adapters/` + BLUE `.ln7-adapters/` (gitignored) |
| One-shot GPU drain | `bash scripts/ln7_continuous_drain.sh` (refuses thin JSONL unless `LN7_QLORA_FORCE_THIN=1`) |
| A/B drain | `bash scripts/ln7_ab_qlora_drain.sh` — default vs all_linear on identical JSONL |

### (a) Real QLoRA

Intel BLUE cannot run mlx. On a CUDA GPU droplet:

```bash
pip install torch peft transformers bitsandbytes datasets accelerate
LN7_QLORA_BACKEND=cuda python backend/scripts/ln7_qlora_train.py \
  --train-jsonl data/ln7_train.jsonl --backend cuda --iters 80
```

### (b) ORANGE SSH

GREEN uses **`/root/.ssh/id_ed25519_orange`** (passwordless). Host alias `orange` → `10.13.13.5`.

```bash
ssh -o BatchMode=yes root@68.183.168.75 'ssh -o BatchMode=yes -i /root/.ssh/id_ed25519_orange root@10.13.13.5 true'
# Ollama binds WireGuard only: http://10.13.13.5:11434 (not 127.0.0.1)
```

### Durable QLoRA drain (recommended)

```bash
# BLUE — ~$0.76/hr while GPU lives; auto-destroy on EXIT + TTL
bash scripts/ln7_continuous_drain.sh
# Adapter: .ln7-adapters/LN7-<ts>  and  ORANGE:/opt/ln7/adapters/LN7-<ts>
# PEFT is durable store only until merge→Ollama path ships (serve still LN7_CODE_MODEL_*)
```

## Ops status (2026-07-28 overnight 1–5)

| Step | Result |
|---|---|
| 1 ORANGE SSH | **OK** — passwordless `/root/.ssh/id_ed25519_orange` on GREEN; pubkey on ORANGE. `ssh orange` / `root@10.13.13.5` works. (Old `id_ed25519` is passphrase-locked.) |
| 2 Real QLoRA | **OK** — DO `gpu-4000adax1-20gb` (tor1) trained `cuda_qlora_peft` on 7 JSONL rows → adapter + `LN7-2026-07-28T052742Z` (shadow). Droplet destroyed after train (`scripts/ln7_destroy_cuda_droplet.sh`) |
| 3 Continuous | **ON** GREEN: `ENABLE_LN7_CONTINUOUS=true`, `ENABLE_LN7_AUTO_PROMOTE=false`. Agent started; job `#1` batch_n=8 → trained |
| 4 E2E | Enqueue → CUDA train → `revision/register` → canary start. CEO activate still required |
| 5 Public benches | `.ln7-harness/*/upstream/run_official.sh` wired from examples; `mode=full` results in `docs/ln7/public_results/`. Competitive scores still need preds/`swebench`/aider/tb CLIs |

## Train host constraints (2026-07-28)

| Host | QLoRA path | Notes |
|---|---|---|
| BLUE Apple Silicon | `mlx-lm` via `ln7_qlora_train.py` | Preferred offline train |
| BLUE Intel (x86_64) | **blocked for mlx** | Use short-lived CUDA GPU (e.g. DO H100) or keep `dry_run_stub` |
| ORANGE | CUDA / Ollama serve only | Public harness full + inference; SSH key must allow GREEN→ORANGE |
| GREEN | never train | Export JSONL only |

`ln7_qlora_train.py` exits `mlx_requires_apple_silicon` on x86 unless `LN7_QLORA_ALLOW_X86_DRY_RUN=1`.

## Gap-close notes (2026-07-27)

- CLI path with `space=ln7` never falls through to Foundry/xAI. Missing local coder → hard error.
- Pack-hinted LN-FAB/DEBUG turns run `ln7_harness.run_task` (best-of-N + sandbox).
- `TIER_CODING` providers are `sovereign` + `home_gpu` only.
- Contestants auto-enable when credentials exist (`GET /api/ln7/contestants`).
- Seed packs: `POST /api/ln7/tasks/seed-packs` or migration `292`.
- Mine volume: `python backend/scripts/ln7_mine_tasks.py --limit 300 --sql /tmp/ln7_tasks.sql`.
- Extension 0.2.3: Bakeoff/Board bar + accept/reject → `/api/ln7/usage-event`.

## 1) Public benchmarks (report-only)

| Mode | Env | Where |
|---|---|---|
| `smoke` | `LN7_PUBLIC_HARNESS_MODE=smoke` | GREEN ok — tiny tasks via Ollama |
| `smoke` offline CI | `LN7_PUBLIC_SMOKE_OFFLINE=true` | pytest / no GPU |
| `ingest` | results JSON in `LN7_PUBLIC_RESULTS_DIR` | GREEN reads ORANGE/BLUE uploads |
| `full` | `LN7_PUBLIC_HARNESS_ROOT=/opt/ln7-harness` | **ORANGE/BLUE only** |

```bash
# ORANGE/BLUE — after cloning official harnesses under /opt/ln7-harness/<bench>/
LN7_PUBLIC_HARNESS_MODE=full LN7_PUBLIC_HARNESS_ROOT=/opt/ln7-harness \
  PYTHONPATH=backend python backend/scripts/ln7_run_public_benches.py --write

# GREEN — scorecard uses ingest or smoke
POST /api/ln7/public-benches  {"mode":"ingest"}
POST /api/ln7/bakeoff         {"include_public":true,"include_private":true}
```

See `backend/scripts/ln7_public_harness/README.md`. Smoke ≠ competitive SWE-bench.

## 2) Coder weights on ORANGE

```bash
ssh -J root@68.183.168.75 root@10.13.13.5 \
  'bash -s' < backend/scripts/ln7_pull_coder_weights.sh
# Verify: ollama list | grep coder
# GREEN: LN7_INFERENCE_URL=http://10.13.13.5:11434 + LN7_CODE_MODEL_*
```

## 3) Shadow spend + HOME_GPU failover

| Flag | Meaning |
|---|---|
| `LN7_SHADOW_SPEND=true` | When a revision has `status=shadow`, live LN7 answers also fire a second **sovereign** generate (fast tier) and ledger it as `ln7_shadow` |
| `HOME_GPU_URL` | BLUE Ollama OpenAI-compat base (`…/v1/chat/completions`). Coding tier: sovereign → home_gpu |

**HOME_GPU status (2026-07-28):** Mac Ollama is up locally (`127.0.0.1:11434`, coder 7b/14b). GREEN cannot use loopback. `twin-agent.sovereignsanctuary.net` is Access-gated (403). Set `HOME_GPU_URL` only when a Twin/VPC hostname reaches Mac Ollama from GREEN without 403 (Cloudflare Access service token or private tunnel hostname). Until then `home_gpu_configured=false` is expected.

Bakeoff prompts must use pack `task.json` + target file bodies (`build_pack_prompt`). Vague “fix pack X” prompts cause refusals.

```bash
POST /api/ln7/revision/shadow  {"revision_id":"LN7-<ts>"}
# Promote still requires CEO when LN7_PROMOTE_REQUIRES_CEO=true
```

## 4) Train / QLoRA (BLUE only)

```bash
# From GREEN DB (read) or BLUE with DATABASE_URL:
PYTHONPATH=backend python backend/scripts/ln7_export_train_jsonl.py \
  --out /tmp/ln7_train.jsonl --limit 500

# On BLUE (NODE_COLOR must not be green):
python backend/scripts/ln7_qlora_train.py \
  --train-jsonl /tmp/ln7_train.jsonl \
  --base qwen2.5-coder:7b-instruct \
  --out-dir /tmp/ln7_adapters/LN7-<ts>

# Register shadow candidate from manifest:
POST /api/ln7/revision/register  # body = revision_manifest.json → register_body
POST /api/ln7/revision/shadow    {"revision_id":"LN7-<ts>"}
# Statistical gate + CEO → activate
```

API: `POST /api/ln7/train/export` returns sample metadata (not weights).

## Three-node compute

| Workload | Node |
|---|---|
| Orchestration / API / ledger | GREEN |
| Interactive fast coder (7B) | ORANGE (Ollama) |
| Deep / bakeoff / train | BLUE (Home GPU / MLX) or rented GPU |
| Untrusted third-party task exec | Sandbox VPS (10.13.13.4) — not GREEN |
| Full public harness containers | ORANGE / BLUE — never GREEN |
