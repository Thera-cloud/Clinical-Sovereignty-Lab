# Intake + Pharma Fix — 2026-05-20

## What was broken

### Bug A — Medication names in chat
Little Nate named Sildenafil/Viagra, Tadalafil/Cialis, and Vardenafil/Levitra after a disclaimer when asked to list ED medications. The clinical runtime gate only matched **interaction-style** pharma questions (e.g. “safe together”, “do these interact”) and had **no output-side scan**, so LLM responses could still deliver drug names.

### Bug B — Intake walkthrough hijacking
After the user said **“later”** at the intake offer, the walkthrough still ran via the LLM **navigator** (e.g. “Focus on my journey” triggered resume). Non-intake turns (communication tools, medication questions) were classified as intake **answers**, fields were saved (including garbage `q1_preferred_name`), and **1000 tokens were credited per turn** — up to 9000/12000 for an intake the user declined. Stop phrases (“stop it here”, “Stop doing the intake”, “not supposed to be doing the intake”) were not handled.

## What changed

### Bug A (`little_nate_clinical_runtime_gate.py`, `bridge_server.py`)
- Expanded `PHARMA_PATTERNS` for list/name/compare/prescribe medication requests (including transcript phrasing).
- Added `CANONICAL_MEDICATION_NAMES` + `enforce_output_backstop()` — blocks responses that introduce drug names the user did not mention; logs `[PHARMA_BLOCK] uid=… turn=… drug_detected=…`.
- Bridge `_send()` hook (≤15 lines): applies backstop on CLIENT turns using last user message.
- User-stated carve-out: names the user already said may appear in reflection; Nate-introduced names are blocked.

### Bug B (`intake_walkthrough.py`)
- Sticky `declined` + `stopped` flags — no navigator, no resume, no re-offer after decline/stop.
- Removed LLM navigator from the default non-active path (rule-based accept/decline/restart only).
- Added `awaiting_answer` guard — save + `credit_walkthrough_question` only when walkthrough is active **and** awaiting a reply to the last intake question.
- Expanded stop/decline term lists; hard exit on stop/off-topic (falls through to normal chat).
- `reset_runtime()` for tests.

### Tests + red-team
- `backend/tests/test_pharma_boundary.py` — 6 cases (all green).
- `backend/tests/test_intake_walkthrough_fsm.py` — 6 cases including **`test_full_transcript_regression`** (all green).
- `run_clinical_redteam.py` — scenario 17 (ED medication listing) + `_no_named_drugs()` check.

## Test results

```
pytest tests/test_pharma_boundary.py tests/test_intake_walkthrough_fsm.py -v
12 passed

test_full_transcript_regression: PASSED (0 intake token credits, 0 field saves, declined+stopped sticky)
```

Existing `test_clinical_runtime_gate.py`: run locally before deploy.

Clinical red-team scenario 17 requires live WebSocket run against audit_client (`python3 backend/scripts/run_clinical_redteam.py`); gate now blocks input before LLM and output backstop catches any leak.

## Production

**`ENABLE_INTAKE_SYSTEM` remains off on production** until this commit is deployed to GREEN and manually smoke-tested. Enablement is a separate decision.
