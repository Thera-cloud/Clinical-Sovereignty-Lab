# Recovered Transcripts — Provenance

`six_quotient_human_gold` has a hard `UNIQUE(scenario_id)` constraint — one row per
scenario, period. `live_stack_run_id` is a label *column* on that single row, not a
key for multiple generations. Regenerating a scenario under a new run label
overwrites the prior row's `nate_response_live` in place. These files are the only
surviving record of two generations that were overwritten before they could be
pulled into a permanent multi-row store.

Both files are pipe-delimited: `SCENARIO_ID|response text`, one line per scenario,
covering the safety quartet (AQ-1, AQ-2, AQ-G07, AQ-G08). Captured via direct
`psql` SELECT against `nate_response_live` on production (68.183.168.75),
2026-08-01.

## `quartet_before_no_affinity_fuel_burning_verify_20260801.txt`

- **Original `run_id`**: `fuel_burning_verify_20260801`
- **Condition**: recall-logging fix landed (crisis/class guides write to
  `crystal_recall_log`); lexical-overlap ranking in `select_crisis_guides` **not
  yet applied**.
- **Used as**: `condition_label='before_no_affinity'` in the
  `quartet_dose_response_v1` scoring session (see
  `backend/scripts/seed_quartet_dose_response.py`).
- Captured immediately before regenerating under
  `fuel_burning_verify_20260801_affinity`, which overwrote this row in
  `six_quotient_human_gold`.

## `quartet_pre_recall_fix_baseline_two_days_ago.txt`

- **Original `run_id`**: `live_pr_crisis_*` (pre-dates the fuel-cycle work in this
  session by ~2 days)
- **Condition**: the original two-days-ago clinician-scored baseline, before the
  crystal scrub, the recall-logging fix, and the affinity fix.
- **Not currently wired into any scoring session** — preserved here as the
  earliest evidence point in the chain (pre-recall-fix → before_no_affinity →
  after_affinity_fix) in case a three-way comparison is wanted later.

## Rule

Both files are read-only historical evidence. Never overwrite them. If a future
regeneration needs to preserve a run before it gets clobbered, capture it here
with the same naming convention (`quartet_<condition>_<run_id>.txt`) and add a
section to this file before running the regeneration that would destroy it.
