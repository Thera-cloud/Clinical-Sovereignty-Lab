-- Sovereign Events AE query pack
-- Dataset: sovereign_events_ae
-- NOTE: Adapt syntax as needed in Cloudflare AE query UI.

-- 1) Runtime reliability: error rate by service (last 60m)
SELECT
  indexes[2] AS service,
  COUNT(*) AS total_events,
  SUM(CASE WHEN indexes[4] = 'error' THEN 1 ELSE 0 END) AS error_events,
  100.0 * SUM(CASE WHEN indexes[4] = 'error' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS error_rate_pct
FROM sovereign_events_ae
WHERE doubles[1] >= (UNIX_MILLIS(CURRENT_TIMESTAMP) - 3600000)
GROUP BY service
ORDER BY error_rate_pct DESC;

-- 2) Latency p95 by event type (last 24h)
SELECT
  indexes[1] AS event_type,
  APPROX_QUANTILE(doubles[2], 0.95) AS p95_latency_ms,
  COUNT(*) AS samples
FROM sovereign_events_ae
WHERE doubles[1] >= (UNIX_MILLIS(CURRENT_TIMESTAMP) - 86400000)
GROUP BY event_type
ORDER BY p95_latency_ms DESC;

-- 3) Cache efficiency (hit ratio)
SELECT
  SUM(CASE WHEN indexes[1] = 'cache_hit' THEN 1 ELSE 0 END) AS cache_hits,
  SUM(CASE WHEN indexes[1] = 'cache_miss' THEN 1 ELSE 0 END) AS cache_misses,
  100.0 * SUM(CASE WHEN indexes[1] = 'cache_hit' THEN 1 ELSE 0 END)
    / NULLIF(SUM(CASE WHEN indexes[1] IN ('cache_hit', 'cache_miss') THEN 1 ELSE 0 END), 0) AS hit_ratio_pct
FROM sovereign_events_ae
WHERE doubles[1] >= (UNIX_MILLIS(CURRENT_TIMESTAMP) - 86400000);

-- 4) Webhook trust chain (received vs forwarded)
SELECT
  indexes[6] AS source,
  SUM(CASE WHEN indexes[1] = 'webhook_received' THEN 1 ELSE 0 END) AS received,
  SUM(CASE WHEN indexes[1] = 'webhook_forwarded' THEN 1 ELSE 0 END) AS forwarded
FROM sovereign_events_ae
WHERE doubles[1] >= (UNIX_MILLIS(CURRENT_TIMESTAMP) - 86400000)
GROUP BY source
ORDER BY received DESC;

-- 5) CLI execution lifecycle durations
SELECT
  blobs[6] AS target,
  AVG(doubles[2]) AS avg_latency_ms,
  COUNT(*) AS completed_runs
FROM sovereign_events_ae
WHERE indexes[1] = 'cli_execution_completed'
  AND doubles[1] >= (UNIX_MILLIS(CURRENT_TIMESTAMP) - 2592000000)
GROUP BY target
ORDER BY avg_latency_ms DESC
LIMIT 50;

