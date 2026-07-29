# Nate Clinical Coevolution

Little Nate–only competitive clinical sandbox: dual-loop adaptation, twin bakeoffs, lessons, adversarial curriculum, DPO for sovereign checkpoints.

## Flags (all default false)

| Flag | Role |
|---|---|
| `ENABLE_NATE_CLINICAL_BAKEOFF` | Nightly twin matches |
| `ENABLE_NATE_CLINICAL_FAST_LOOP` | Hidden scratchpad on live bridge |
| `NATE_CLINICAL_FAST_LOOP_SHADOW` | Log only (default true) |
| `ENABLE_NATE_MODALITY_ROUTER` | DBT/MI/CBT/ACT routing |
| `ENABLE_NATE_CLINICAL_LESSONS` | Lesson candidates + crystallize ≥2 |
| `ENABLE_NATE_ADVERSARIAL_CURRICULUM` | Level escalate/de-escalate (seeds still serve bakeoff) |
| `ENABLE_NATE_CLINICAL_DPO_EXPORT` | JSONL export |
| `ENABLE_NATE_CLINICAL_AUTO_PROMOTE` | Locked false in code |
| `NATE_CLINICAL_DPO_EXPORT_DIR` | Durable export root (default `/app/data/nate_clinical_dpo`) |

## Floors

- κ ≥ 0.70, order-swap concordance ≥ 0.75, preference yield ≥ 0.30
- Coin-flip kill: win-rate 0.45–0.55 for 7 nights

## DPO target

Sovereign ORANGE / Home GPU checkpoints only. Vendor (Grok/Azure therapy) improves via prompt packs, router, and `clinical_lesson` crystals — not weight uploads.

## Admin API

`/api/nate-clinical/health`, `/bakeoff/run`, `/leaderboard`, `/export/dpo`, `/revisions`

Requires live `nate_inference_router` when bakeoff is enabled (no silent stub nights). Exhausted seeds recycle `reuse_count`. Default variants upsert into `nate_clinical_variants`.

## Chat safety

Fast-loop and bakeoff are gated off by default. Bridge hook is no-op unless `ENABLE_NATE_CLINICAL_FAST_LOOP=true`. Shadow mode never mutates client-visible prompts.

Deploy primary **and** clone after API changes so LB REST does not 404 `/api/nate-clinical/*`.
