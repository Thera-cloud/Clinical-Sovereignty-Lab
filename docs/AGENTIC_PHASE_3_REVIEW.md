# Agentic Phase 3 — Human Adversarial Walk Checklist

**Status:** adversarial walk signed — staging 3.2 + prod 3.3 flipped 2026-07-20 (`ENABLE_THERAPEUTIC_PLANS=true`)

| Gate | Question | Pass |
|---|---|---|
| Key | Are plans scoped to correct client user_id? | [x] |
| Lifecycle | Does step advance require coach (or admin) action? | [x] |
| Surface | Is plan context injected alongside crystal recall? | [x] |
| Seam | Does divergence log without auto-pausing plan? | [x] |
| Time | Is adaptation_log append-only per event? | [x] |

**Flag:** `ENABLE_THERAPEUTIC_PLANS` — staging + prod authorized/flipped 2026-07-20

**Reviewer:** Nathan Nevedal **Date:** 2026-07-17
