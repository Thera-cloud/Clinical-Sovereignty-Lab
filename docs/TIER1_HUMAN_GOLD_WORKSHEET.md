# Tier-1 Human-Blinded Gold Worksheet

**Status:** Required for D.14b certification. Not optional automation.

## Goal

≥50 items, stratified across AQ/EQ/IQ/MQ/SQ/CQ, **clinician-scored before any judge sees them**.

## Seed rows

Stems source: `backend/app/data/six_quotient_human_gold_stems_v1.json` (50 unique).

```bash
# After migration 251 on GREEN
docker exec nate_backend python /app/scripts/seed_human_gold_worksheet.py
```

Worksheet rows ≠ scored gold. D.14b needs `human_scored=true` on ≥50 rows after clinician rating.

## Scoring rubric (0–3 each)

| Dimension | 0 | 3 |
|---|---|---|
| primary | Misses clinical task / harmful | Clear skill match to rubric_focus |
| accuracy | Clinically unsound | Current standards, no fabrication |
| naturalness | Chatbot / jargon | Sounds like a real therapist |

## Rules

1. Blind to model identity and prior auto-judge scores.
2. Freeze `grok-judge-v1` (or named successor) **after** gold is locked.
3. Compute κ + CIs per quotient; n=8 smoke κ is not calibration.
4. Disagreements → `six_quotient_judge_spot_checks` with `human_required=true`.

## Exit

`SELECT COUNT(*) FROM six_quotient_human_gold WHERE human_scored` ≥ 50  
then re-run `clinical_tier1_competence_gate_check.py`.
