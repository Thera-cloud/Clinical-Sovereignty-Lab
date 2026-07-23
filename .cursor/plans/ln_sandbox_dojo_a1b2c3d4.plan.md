---
name: LN Sandbox DOJO
overview: Unsupervised dual-track practice loop (clinical strategy + engineering) with practice corpus, restraint seeds, promotion wall, and idle client-prep candidates. Draft learnings never auto-enter production crystals.
todos:
  - id: migration-267
    content: 267_ln_sandbox.sql — sessions, attempts, practice_corpus, promotion_queue + restraint seeds
    status: completed
  - id: engine
    content: ln_sandbox_engine.py — 30m cycle, clinical/engineering/client_prep tracks, retry+score
    status: completed
  - id: promotion
    content: ln_sandbox_promotion.py — enqueue/decide + NateResponseValidator + crystal write
    status: completed
  - id: context-inject
    content: ln_sandbox_context + directory_context_for_surface candidate inject
    status: completed
  - id: api-wire
    content: ln_sandbox_api + main.py service/digest + .env.template flags
    status: completed
  - id: tests
    content: test_ln_sandbox.py offline suite
    status: completed
  - id: green-enable
    content: Apply migration 267 on GREEN; set ENABLE_LN_SANDBOX=true after soak review
    status: pending
isProject: false
---

# LN Sandbox DOJO

## Principle

Failure is free inside the sandbox. Live clients stay behind restraints.

| Store | Role |
|---|---|
| `ln_sandbox_practice_corpus` | Practice memory (draft/queued) |
| `restraint_ref` rows | Binding safety reminders (seeded promoted) |
| `ln_sandbox_promotion_queue` | Human gate → `nate_intelligence_crystals` (`origin_surface=ln_sandbox_promoted`) |

## Tracks

1. **clinical_strategy** — scenario bank / AQ-SQ stems → LNI generate → deterministic judge → retry once → corpus
2. **engineering** — fixture tasks (`ln_sandbox_engineering_tasks.json`) → same loop (no GREEN code mutation)
3. **client_prep** — idle clients (≥6h) → user-scoped candidate approaches

## Flags

```
ENABLE_LN_SANDBOX=false          # master
LN_SANDBOX_CLINICAL=true
LN_SANDBOX_ENGINEERING=true
LN_SANDBOX_CLIENT_PREP=true
```

## API

- `GET /api/ln-sandbox/health|status|corpus`
- `GET /api/ln-sandbox/candidates/{username}`
- `POST /api/ln-sandbox/promote/enqueue|decide`
- `POST /api/ln-sandbox/run-cycle`

## Live inject

When `ENABLE_LN_SANDBOX`, `directory_context_for_surface` appends sandbox candidates (labeled CANDIDATE ONLY). Restraints listed first. Predictive Restraint / crisis / validator still gate speech.
