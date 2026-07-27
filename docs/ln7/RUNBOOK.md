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

## Gap-close notes (2026-07-27)

- CLI path with `space=ln7` never falls through to Foundry/xAI. Missing local coder → hard error.
- Pack-hinted LN-FAB/DEBUG turns run `ln7_harness.run_task` (best-of-N + sandbox).
- `TIER_CODING` providers are `sovereign` + `home_gpu` only.
- Contestants auto-enable when credentials exist (`GET /api/ln7/contestants`).
- Seed packs: `POST /api/ln7/tasks/seed-packs` or migration `292`.
- Mine volume: `python backend/scripts/ln7_mine_tasks.py --limit 300 --sql /tmp/ln7_tasks.sql`.
- Extension 0.2.3: Bakeoff/Board bar + accept/reject → `/api/ln7/usage-event`.

## Three-node compute

| Workload | Node |
|---|---|
| Orchestration / API / ledger | GREEN |
| Interactive fast coder (7B) | ORANGE (Ollama) |
| Deep / bakeoff / train | BLUE (Home GPU / MLX) or rented GPU |
| Untrusted third-party task exec | Sandbox VPS (10.13.13.4) — not GREEN |
