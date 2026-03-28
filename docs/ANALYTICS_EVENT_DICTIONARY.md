# Sovereign Events AE Dictionary (v1.0.0)

Dataset: `sovereign_events_ae`  
Binding: `ANALYTICS_AE`

This is the canonical event contract used by edge workers and `nate-analytics-edge`.

## Column Order (Exact)

### `indexes` (string dimensions)
1. `type`
2. `service`
3. `stage`
4. `status`
5. `environment`
6. `source`
7. `colo`
8. `country`

### `blobs` (opaque string payloads)
1. `event_id`
2. `trace_id`
3. `request_id`
4. `run_id`
5. `actor_id`
6. `target`
7. `error_code`
8. `message`

### `doubles` (numeric measures)
1. `ts_ms`
2. `latency_ms`
3. `value`
4. `count`
5. `cost_units`

## Required Event Fields

- `type`
- `service`
- `stage`
- `status`

## Supported Event Types

- `summon_request`
- `summon_response`
- `voice_stt`
- `voice_tts`
- `voice_pipeline`
- `auth_validate`
- `auth_gate`
- `webhook_received`
- `webhook_forwarded`
- `crystal_recall`
- `crystal_prewarm`
- `immune_check`
- `cache_hit`
- `cache_miss`
- `session_start`
- `session_end`
- `token_usage`
- `page_view`
- `error`
- `extension_formula_run`
- `extension_webhook_fired`
- `extension_widget_rendered`
- `cli_proposal_created`
- `cli_proposal_approved`
- `cli_execution_started`
- `cli_execution_completed`

## Sampling Policy

- `page_view`: 20%
- `cache_hit`: 20%
- `cache_miss`: 50%
- `error`: 100%
- default: 100%

## PII Safety

The ingestion layer redacts likely:
- emails
- phone numbers
- SSN-like strings

before persistence to AE/R2 for `message` and `error_code`.

## Minimal Producer Payload Example

```json
{
  "type": "cli_execution_completed",
  "service": "nate-agent-api",
  "stage": "lifecycle",
  "status": "ok",
  "source": "cli_cloud",
  "actor_id": "cli-cloud",
  "target": "backend/app/services/trust_enforcer.py",
  "latency_ms": 182000,
  "value": 1,
  "count": 1
}
```

