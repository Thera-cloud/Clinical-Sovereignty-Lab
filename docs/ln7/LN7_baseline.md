# Little Nate 7 — Model Card (Baseline)

| Field | Value |
|---|---|
| Product | Little Nate 7 (major=7, immutable) |
| Revision | `LN7-baseline` |
| Base checkpoint | `qwen2.5-coder:32b-instruct-q5_K_M` |
| Quantization | `q5_K_M` (floor; q4 is a regression floor, not a target) |
| Non-clinical claim | **true** — never cite as clinical Tier 2/3 evidence |

## Purpose

Day-0 stock coder weights baseline. Every later revision's statistical gate and competitive claim uses this as the incumbent denominator after the first private pack bakeoff is recorded.

## Public benchmarks

Report-only until official harness containers run on ORANGE/BLUE.

## Notes

Seeded by migration `291_ln7_outcome_ledger.sql`. Activate replacements only with a model card + Dual-COO/CEO gate when `LN7_PROMOTE_REQUIRES_CEO=true`.
