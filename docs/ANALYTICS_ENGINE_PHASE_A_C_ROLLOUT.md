# Analytics Engine Rollout (Phase A-C)

This rollout operationalizes `sovereign_events_ae` as the hot event plane, with R2 JSONL as immutable forensic backup.

## Phase A — Foundation (Implemented)

- Added `ANALYTICS_AE` binding to:
  - `nate-summon-worker`
  - `nate-auth-edge`
  - `nate-webhook-gateway`
  - `nate-voice-edge`
  - `nate-cron-worker`
  - `nate-analytics-edge`
  - `nate-edge-cache`
- Added strict event dictionary and required field validation in `nate-analytics-edge`.
- Added correlation IDs (`trace_id`, `request_id`) and event dedupe window.
- Added PII redaction guard for `message` and `error_code`.
- Added dual-write sink:
  - Analytics Engine (fast operational telemetry)
  - R2 JSONL (`analytics/`) for immutable replay/audit

## Phase B — Quality + Safety (Implemented)

- Added validation reject path to `analytics_rejected/` in R2.
- Added sampling strategy by event class.
- Added anomaly state tracking (hourly):
  - error-rate
  - average latency
- Added endpoints:
  - `GET /api/analytics/dictionary`
  - `GET /api/analytics/anomalies`
  - `GET /api/analytics/slo`

## Phase C — System-Wide Uses 1-5 (Implemented + Ready)

1. **Runtime reliability**
   - Use `summon_*`, `voice_*`, `immune_check` events for p95/p99 latency and failure trend tracking.
2. **CLI lifecycle observability**
   - `cli_proposal_*` and `cli_execution_*` event classes reserved in dictionary.
3. **Webhook trust chain**
   - `webhook_received` and `webhook_forwarded` telemetry now emitted at gateway.
4. **Auth and gating quality**
   - `auth_validate` and `auth_gate` emitted with stage/status/error signal.
5. **Cost/perf control**
   - Sampling + AE-free-tier aware counters + SLO endpoint for operational error budget.

## Practical Queries (Start Here)

- Error rate by service/stage
- p95 latency by event type
- cache hit ratio (`cache_hit` vs `cache_miss`)
- webhook forward success ratio
- auth invalid-token spike detection

## Rollout Commands

Deploy worker updates after validating wrangler auth:

```bash
cd cloudflare/workers/nate-analytics-edge && npx wrangler deploy
cd cloudflare/workers/nate-summon-worker && npx wrangler deploy
cd cloudflare/workers/nate-auth-edge && npx wrangler deploy
cd cloudflare/workers/nate-webhook-gateway && npx wrangler deploy
cd cloudflare/workers/nate-voice-edge && npx wrangler deploy
cd cloudflare/workers/nate-cron-worker && npx wrangler deploy
cd cloudflare/workers && npx wrangler deploy
```

## Acceptance Criteria

- `/api/analytics/dictionary` returns v1.0.0 map.
- `/api/analytics/health` returns `ok`.
- `/api/analytics/anomalies` returns hourly alert payload.
- At least one event appears from each instrumented worker class.

