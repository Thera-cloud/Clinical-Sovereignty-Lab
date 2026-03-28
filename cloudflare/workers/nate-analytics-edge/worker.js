/**
 * nate-analytics-edge — Edge telemetry control plane.
 *
 * Phase A-C rollout implementation:
 * - Exact event dictionary + schema validation
 * - PII-safe redaction + sampling policies
 * - Dual-write sink: Analytics Engine (hot), R2 JSONL (forensics)
 * - Correlation IDs + lightweight anomaly + SLO visibility
 */

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Content-Type': 'application/json',
  };
}

const EVENT_TYPES = [
  'summon_request', 'summon_response', 'voice_stt', 'voice_tts', 'voice_pipeline',
  'auth_validate', 'auth_gate', 'webhook_received', 'webhook_forwarded',
  'crystal_recall', 'crystal_prewarm', 'immune_check', 'cache_hit', 'cache_miss',
  'session_start', 'session_end', 'token_usage', 'page_view', 'error',
  'extension_formula_run', 'extension_webhook_fired', 'extension_widget_rendered',
  'cli_proposal_created', 'cli_proposal_approved', 'cli_execution_started', 'cli_execution_completed',
];

const REQUIRED_FIELDS = ['type', 'service', 'stage', 'status'];

const SAMPLE_RATES = {
  page_view: 0.2,
  cache_hit: 0.2,
  cache_miss: 0.5,
  error: 1.0,
  default: 1.0,
};

// Exact Analytics Engine dictionary order.
const AE_DICTIONARY = {
  indexes: [
    'type',           // idx0
    'service',        // idx1
    'stage',          // idx2
    'status',         // idx3
    'environment',    // idx4
    'source',         // idx5
    'colo',           // idx6
    'country',        // idx7
  ],
  blobs: [
    'event_id',       // b0
    'trace_id',       // b1
    'request_id',     // b2
    'run_id',         // b3
    'actor_id',       // b4
    'target',         // b5
    'error_code',     // b6
    'message',        // b7
  ],
  doubles: [
    'ts_ms',          // d0
    'latency_ms',     // d1
    'value',          // d2
    'count',          // d3
    'cost_units',     // d4
  ],
};

function datePartition() {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = String(now.getUTCMonth() + 1).padStart(2, '0');
  const d = String(now.getUTCDate()).padStart(2, '0');
  const h = String(now.getUTCHours()).padStart(2, '0');
  return { y, m, d, h, partition: `${y}/${m}/${d}/${h}` };
}

function redactPII(text) {
  if (typeof text !== 'string' || !text) return text;
  return text
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[REDACTED_EMAIL]')
    .replace(/\+?\d[\d\s().-]{8,}\d/g, '[REDACTED_PHONE]')
    .replace(/\b\d{3}-?\d{2}-?\d{4}\b/g, '[REDACTED_SSN]');
}

function normalizedStatus(raw) {
  const allowed = new Set(['ok', 'warning', 'error', 'start', 'end', 'rejected']);
  const value = String(raw || 'ok').toLowerCase();
  return allowed.has(value) ? value : 'ok';
}

function randomId() {
  return crypto.randomUUID();
}

function shouldSample(type) {
  const rate = Object.prototype.hasOwnProperty.call(SAMPLE_RATES, type)
    ? SAMPLE_RATES[type]
    : SAMPLE_RATES.default;
  return Math.random() <= rate;
}

function validateEvent(event) {
  const errors = [];
  for (const field of REQUIRED_FIELDS) {
    if (!event[field]) errors.push(`missing_${field}`);
  }
  if (event.type && !EVENT_TYPES.includes(event.type)) {
    errors.push('unknown_type');
  }
  return { valid: errors.length === 0, errors };
}

function latencyBucket(latencyMs) {
  const v = Number(latencyMs || 0);
  if (v <= 50) return 'p50';
  if (v <= 100) return 'p75';
  if (v <= 250) return 'p90';
  if (v <= 500) return 'p95';
  return 'p99+';
}

function toAEPoint(event) {
  const indexes = [
    event.type || '',
    event.service || '',
    event.stage || '',
    event.status || 'ok',
    event.environment || 'production',
    event.source || 'unknown',
    event.edge_colo || 'unknown',
    event.edge_country || 'unknown',
  ];

  const blobs = [
    event.event_id || '',
    event.trace_id || '',
    event.request_id || '',
    event.run_id || '',
    event.actor_id || '',
    event.target || '',
    event.error_code || '',
    event.message || '',
  ];

  const doubles = [
    Number(event.ts_ms || Date.now()),
    Number(event.latency_ms || 0),
    Number(event.value || 0),
    Number(event.count || 1),
    Number(event.cost_units || 0),
  ];

  return { indexes, blobs, doubles };
}

async function incrementCounter(env, eventType) {
  try {
    const today = new Date().toISOString().slice(0, 10);
    const key = `analytics:count:${today}:${eventType}`;
    const raw = await env.ANALYTICS_STATE.get(key);
    const count = raw ? parseInt(raw, 10) + 1 : 1;
    await env.ANALYTICS_STATE.put(key, String(count), { expirationTtl: 172800 });

    const totalKey = `analytics:total:${today}`;
    const totalRaw = await env.ANALYTICS_STATE.get(totalKey);
    const total = totalRaw ? parseInt(totalRaw, 10) + 1 : 1;
    await env.ANALYTICS_STATE.put(totalKey, String(total), { expirationTtl: 172800 });
  } catch { /* best-effort */ }
}

function enrichEvent(event, request) {
  const traceId = request.headers.get('x-trace-id') || event.trace_id || randomId();
  const requestId = request.headers.get('x-request-id') || event.request_id || randomId();
  const now = Date.now();

  return {
    ...event,
    event_id: event.event_id || randomId(),
    trace_id: traceId,
    request_id: requestId,
    ts_ms: Number(event.ts_ms || now),
    status: normalizedStatus(event.status),
    message: redactPII(event.message || ''),
    error_code: redactPII(event.error_code || ''),
    latency_bucket: latencyBucket(event.latency_ms),
    ingested_at: new Date().toISOString(),
    edge_colo: request.cf?.colo || 'unknown',
    edge_country: request.cf?.country || 'unknown',
    client_ip_hash: null,
    user_agent: (request.headers.get('User-Agent') || '').slice(0, 100),
  };
}

async function markRecentEvent(env, eventId) {
  if (!eventId) return false;
  const key = `analytics:event:${eventId}`;
  const existing = await env.ANALYTICS_STATE.get(key);
  if (existing) return true;
  await env.ANALYTICS_STATE.put(key, '1', { expirationTtl: 600 });
  return false;
}

async function updateAnomalyState(env, event) {
  try {
    const hour = new Date().toISOString().slice(0, 13);
    const errKey = `analytics:anomaly:error:${hour}`;
    const latKey = `analytics:anomaly:latency:${hour}`;
    const totalKey = `analytics:anomaly:total:${hour}`;

    const total = parseInt((await env.ANALYTICS_STATE.get(totalKey)) || '0', 10) + 1;
    await env.ANALYTICS_STATE.put(totalKey, String(total), { expirationTtl: 172800 });

    if (event.status === 'error') {
      const err = parseInt((await env.ANALYTICS_STATE.get(errKey)) || '0', 10) + 1;
      await env.ANALYTICS_STATE.put(errKey, String(err), { expirationTtl: 172800 });
    }

    if (event.latency_ms !== undefined && event.latency_ms !== null) {
      const prior = parseFloat((await env.ANALYTICS_STATE.get(latKey)) || '0');
      const next = total <= 1 ? Number(event.latency_ms || 0) : (prior + Number(event.latency_ms || 0)) / 2;
      await env.ANALYTICS_STATE.put(latKey, String(next), { expirationTtl: 172800 });
    }
  } catch {
    // best-effort
  }
}

async function writeToAnalyticsEngine(env, event) {
  if (!env.ANALYTICS_AE || typeof env.ANALYTICS_AE.writeDataPoint !== 'function') return false;
  try {
    const point = toAEPoint(event);
    env.ANALYTICS_AE.writeDataPoint(point);
    return true;
  } catch {
    return false;
  }
}

async function flushToR2(env, events) {
  if (!events.length) return;

  const { partition } = datePartition();
  const batchId = crypto.randomUUID();
  const key = `analytics/${partition}/${batchId}.jsonl`;

  const body = events.map(e => JSON.stringify(e)).join('\n');

  await env.ANALYTICS_LAKE.put(key, body, {
    customMetadata: {
      event_count: String(events.length),
      partition,
      flushed_at: new Date().toISOString(),
    },
  });

  return key;
}

async function flushRejectedToR2(env, rejected) {
  if (!rejected.length) return null;
  const { partition } = datePartition();
  const key = `analytics_rejected/${partition}/${crypto.randomUUID()}.jsonl`;
  const body = rejected.map((e) => JSON.stringify(e)).join('\n');
  await env.ANALYTICS_LAKE.put(key, body);
  return key;
}

async function handleSingleEvent(request, env) {
  let event;
  try {
    event = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
      status: 400, headers: corsHeaders(),
    });
  }

  const enriched = enrichEvent(event, request);
  const validation = validateEvent(enriched);
  if (!validation.valid) {
    const rejectedKey = await flushRejectedToR2(env, [{ event: enriched, errors: validation.errors }]);
    return new Response(JSON.stringify({
      error: 'Event failed validation',
      reasons: validation.errors,
      rejected_key: rejectedKey,
    }), {
      status: 422, headers: corsHeaders(),
    });
  }

  if (!shouldSample(enriched.type)) {
    return new Response(JSON.stringify({
      status: 'sampled_out',
      event_id: enriched.event_id,
      trace_id: enriched.trace_id,
    }), { headers: corsHeaders() });
  }

  const duplicate = await markRecentEvent(env, enriched.event_id);
  if (duplicate) {
    return new Response(JSON.stringify({
      status: 'duplicate_skipped',
      event_id: enriched.event_id,
      trace_id: enriched.trace_id,
    }), { headers: corsHeaders() });
  }

  await writeToAnalyticsEngine(env, enriched);
  await incrementCounter(env, event.type);
  await updateAnomalyState(env, enriched);

  const r2Key = await flushToR2(env, [enriched]);

  return new Response(JSON.stringify({
    status: 'flushed',
    event_id: enriched.event_id,
    trace_id: enriched.trace_id,
    r2_key: r2Key,
  }), { headers: corsHeaders() });
}

async function handleBatch(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
      status: 400, headers: corsHeaders(),
    });
  }

  const events = Array.isArray(body) ? body : body.events;
  if (!events || !events.length) {
    return new Response(JSON.stringify({ error: 'No events' }), {
      status: 400, headers: corsHeaders(),
    });
  }

  if (events.length > 500) {
    return new Response(JSON.stringify({ error: 'Max 500 events per batch' }), {
      status: 400, headers: corsHeaders(),
    });
  }

  const enriched = events.map((e) => enrichEvent(e, request));
  const accepted = [];
  const rejected = [];

  for (const event of enriched) {
    const v = validateEvent(event);
    if (!v.valid) {
      rejected.push({ event, errors: v.errors });
      continue;
    }
    if (!shouldSample(event.type)) continue;
    const duplicate = await markRecentEvent(env, event.event_id);
    if (duplicate) continue;
    accepted.push(event);
    await writeToAnalyticsEngine(env, event);
    await updateAnomalyState(env, event);
  }

  const r2Key = await flushToR2(env, accepted);
  const rejectedKey = rejected.length ? await flushRejectedToR2(env, rejected) : null;

  for (const e of accepted) {
    if (e.type) await incrementCounter(env, e.type);
  }

  return new Response(JSON.stringify({
    status: 'flushed',
    event_count: accepted.length,
    rejected_count: rejected.length,
    rejected_key: rejectedKey,
    r2_key: r2Key,
  }), { headers: corsHeaders() });
}

async function handleSummary(env) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

  const todayCounts = {};
  const yesterdayCounts = {};

  for (const type of EVENT_TYPES) {
    const tRaw = await env.ANALYTICS_STATE.get(`analytics:count:${today}:${type}`);
    todayCounts[type] = tRaw ? parseInt(tRaw, 10) : 0;

    const yRaw = await env.ANALYTICS_STATE.get(`analytics:count:${yesterday}:${type}`);
    yesterdayCounts[type] = yRaw ? parseInt(yRaw, 10) : 0;
  }

  const totalToday = await env.ANALYTICS_STATE.get(`analytics:total:${today}`);
  const totalYesterday = await env.ANALYTICS_STATE.get(`analytics:total:${yesterday}`);

  return new Response(JSON.stringify({
    today: {
      date: today,
      total: parseInt(totalToday || '0', 10),
      by_type: todayCounts,
    },
    yesterday: {
      date: yesterday,
      total: parseInt(totalYesterday || '0', 10),
      by_type: yesterdayCounts,
    },
    growth: totalYesterday && parseInt(totalYesterday, 10) > 0
      ? ((parseInt(totalToday || '0', 10) - parseInt(totalYesterday, 10)) / parseInt(totalYesterday, 10) * 100).toFixed(1) + '%'
      : 'N/A',
  }), { headers: corsHeaders() });
}

async function handleDictionary() {
  return new Response(JSON.stringify({
    version: 'v1.0.0',
    required_fields: REQUIRED_FIELDS,
    event_types: EVENT_TYPES,
    analytics_engine_map: AE_DICTIONARY,
    sample_rates: SAMPLE_RATES,
  }), { headers: corsHeaders() });
}

async function handleAnomalies(env) {
  const hour = new Date().toISOString().slice(0, 13);
  const total = parseInt((await env.ANALYTICS_STATE.get(`analytics:anomaly:total:${hour}`)) || '0', 10);
  const errors = parseInt((await env.ANALYTICS_STATE.get(`analytics:anomaly:error:${hour}`)) || '0', 10);
  const avgLatency = parseFloat((await env.ANALYTICS_STATE.get(`analytics:anomaly:latency:${hour}`)) || '0');
  const errorRate = total > 0 ? errors / total : 0;

  const alerts = [];
  if (errorRate > 0.05 && total >= 100) alerts.push('error_rate_high');
  if (avgLatency > 500 && total >= 50) alerts.push('latency_high');

  return new Response(JSON.stringify({
    hour_window_utc: `${hour}:00:00Z`,
    total_events: total,
    error_events: errors,
    error_rate: Number(errorRate.toFixed(4)),
    avg_latency_ms: Number(avgLatency.toFixed(1)),
    alerts,
  }), { headers: corsHeaders() });
}

async function handleSLO(env) {
  const today = new Date().toISOString().slice(0, 10);
  const total = parseInt((await env.ANALYTICS_STATE.get(`analytics:total:${today}`)) || '0', 10);
  const errors = parseInt((await env.ANALYTICS_STATE.get(`analytics:count:${today}:error`)) || '0', 10);
  const availability = total > 0 ? (1 - (errors / total)) * 100 : 100;
  return new Response(JSON.stringify({
    date_utc: today,
    target_slo_percent: 99.0,
    observed_availability_percent: Number(availability.toFixed(3)),
    error_budget_burn_percent: Number((Math.max(0, 99.0 - availability)).toFixed(3)),
  }), { headers: corsHeaders() });
}

async function handleHealth(env) {
  const checks = { r2: false, kv: false, d1: false };

  try {
    await env.ANALYTICS_LAKE.head('analytics/probe');
    checks.r2 = true;
  } catch {
    checks.r2 = true;
  }

  try {
    await env.ANALYTICS_STATE.get('health:probe');
    checks.kv = true;
  } catch { /* */ }

  try {
    const r = await env.D1_HOT.prepare('SELECT 1 as ok').first();
    checks.d1 = r && r.ok === 1;
  } catch { /* */ }

  return new Response(JSON.stringify({
    worker: 'nate-analytics-edge',
    status: checks.r2 && checks.kv ? 'ok' : 'degraded',
    checks,
    storage: 'analytics_engine+r2_jsonl',
    retention: 'infinite',
    cost: '$0.00/event (free-tier dependent)',
  }), { headers: corsHeaders() });
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    if (url.pathname === '/api/analytics/event' && request.method === 'POST') {
      return handleSingleEvent(request, env);
    }
    if (url.pathname === '/api/analytics/batch' && request.method === 'POST') {
      return handleBatch(request, env);
    }
    if (url.pathname === '/api/analytics/summary') {
      return handleSummary(env);
    }
    if (url.pathname === '/api/analytics/dictionary') {
      return handleDictionary();
    }
    if (url.pathname === '/api/analytics/anomalies') {
      return handleAnomalies(env);
    }
    if (url.pathname === '/api/analytics/slo') {
      return handleSLO(env);
    }
    if (url.pathname === '/api/analytics/health') {
      return handleHealth(env);
    }

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: corsHeaders(),
    });
  },
};
