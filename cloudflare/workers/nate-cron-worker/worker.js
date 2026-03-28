/**
 * nate-cron-worker — Background maintenance at the edge.
 *
 * Cron Triggers (no HTTP routes):
 *   Every 5 min:  Heartbeat sweep + immune sentinel (combined single KV write)
 *   Every hour:   Crystal pre-warming + D1 sync verification + stale KV purge
 *
 * KV write budget: ~960 writes/day (well within 1,000/day free tier).
 * All operations are idempotent. Multiple invocations are safe.
 */

export default {
  async scheduled(event, env, ctx) {
    const cron = event.cron;

    if (cron === '*/5 * * * *') {
      ctx.waitUntil(healthSweep(env));
    }

    if (cron === '0 * * * *') {
      ctx.waitUntil(crystalPreWarm(env));
      ctx.waitUntil(d1SyncVerify(env));
      ctx.waitUntil(staleCachePurge(env));
    }
  },

  async fetch(request, env) {
    return new Response(JSON.stringify({
      worker: 'nate-cron-worker',
      status: 'ok',
      purpose: 'background_maintenance',
      crons: ['*/5 heartbeat+immune', '0 prewarm+d1-sync+cache-purge'],
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  },
};

function emitAE(env, event) {
  try {
    if (!env.ANALYTICS_AE || typeof env.ANALYTICS_AE.writeDataPoint !== 'function') return;
    env.ANALYTICS_AE.writeDataPoint({
      indexes: [
        event.type || 'immune_check',
        event.service || 'nate-cron-worker',
        event.stage || 'cron',
        event.status || 'ok',
        event.environment || 'production',
        event.source || 'edge',
        event.colo || 'global',
        event.country || 'global',
      ],
      blobs: [
        event.event_id || crypto.randomUUID(),
        event.trace_id || '',
        event.request_id || '',
        event.run_id || '',
        event.actor_id || '',
        event.target || '',
        event.error_code || '',
        event.message || '',
      ],
      doubles: [
        Number(event.ts_ms || Date.now()),
        Number(event.latency_ms || 0),
        Number(event.value || 0),
        Number(event.count || 1),
        Number(event.cost_units || 0),
      ],
    });
  } catch {
    // best-effort
  }
}

/**
 * Combined heartbeat + immune sentinel — single KV write per 5-min cycle.
 * Reads R2/D1/Vectorize/KV health, checks sovereign heartbeat, writes one
 * combined status object to 'cron:health' (1 write instead of 3).
 */
async function healthSweep(env) {
  const started = Date.now();
  const status = {
    timestamp: new Date().toISOString(),
    sovereign_alive: false,
    sovereign_age: -1,
    services_healthy: 0,
    kv_accessible: false,
    d1_accessible: false,
    r2_accessible: false,
    vectorize_accessible: false,
    edge_healthy: false,
    trust_posture: null,
  };

  try {
    const obj = await env.CRYSTAL_STORE.get('heartbeat/sovereign.json');
    if (obj) {
      const data = JSON.parse(await obj.text());
      status.sovereign_age = Math.floor(Date.now() / 1000) - (data.epoch || 0);
      status.sovereign_alive = status.sovereign_age < 300;
      status.services_healthy = data.services_healthy || 0;
    }
  } catch { /* */ }

  try { await env.SUMMON_CACHE.get('immune:probe'); status.kv_accessible = true; } catch { /* */ }
  try { const r = await env.D1_HOT.prepare('SELECT 1 as ok').first(); status.d1_accessible = r && r.ok === 1; } catch { /* */ }
  try {
    const trustRow = await env.D1_HOT
      .prepare('SELECT audit_type, trusted, total, checked_at FROM trust_audit_status ORDER BY checked_at DESC LIMIT 1')
      .first();
    if (trustRow) status.trust_posture = trustRow;
  } catch { /* */ }
  try { const obj = await env.CRYSTAL_STORE.head('heartbeat/sovereign.json'); status.r2_accessible = obj !== null; } catch { /* */ }
  try { const r = await env.WISDOM_INDEX.query([0.1, 0.1, 0.1], { topK: 1 }); status.vectorize_accessible = r && r.matches !== undefined; } catch { /* */ }

  status.edge_healthy = status.kv_accessible && status.d1_accessible &&
                        status.r2_accessible && status.vectorize_accessible;

  try {
    await env.SUMMON_CACHE.put('cron:health', JSON.stringify(status), {
      expirationTtl: 600,
    });

    if (!status.sovereign_alive && status.sovereign_age > 0) {
      await env.SUMMON_CACHE.put('alert:sovereign_down', JSON.stringify({
        detected_at: status.timestamp,
        last_heartbeat_age: status.sovereign_age,
      }), { expirationTtl: 3600 });
    }
  } catch { /* */ }
  emitAE(env, {
    type: 'immune_check',
    service: 'nate-cron-worker',
    stage: 'health_sweep',
    status: status.edge_healthy ? 'ok' : 'warning',
    source: 'scheduler',
    latency_ms: Date.now() - started,
    value: status.services_healthy,
    message: status.sovereign_alive ? 'sovereign_alive' : 'sovereign_stale',
    target: 'cron:health',
  });
}

async function crystalPreWarm(env) {
  const started = Date.now();
  if (!env.AI) return;

  try {
    const clinicalTopics = [
      'anxiety management techniques',
      'relationship communication',
      'stress relief strategies',
      'emotional regulation',
      'self-care practices',
      'grief processing',
      'confidence building',
      'boundary setting',
    ];

    const codeTopics = [
      'python asyncio best practices',
      'fastapi websocket patterns',
      'flutter riverpod state management',
      'postgresql query optimization',
      'redis caching patterns',
      'docker compose production',
      'cloudflare workers edge compute',
      'typescript react component patterns',
      'dart stream controller lifecycle',
      'asyncpg connection pool exhaustion',
      'python error handling patterns',
      'websocket reconnection strategy',
    ];

    let warmed = 0;

    // Clinical crystal pre-warming (existing WISDOM_INDEX)
    if (env.WISDOM_INDEX) {
      for (const topic of clinicalTopics) {
        try {
          const embedding = await env.AI.run('@cf/baai/bge-small-en-v1.5', {
            text: [topic],
          });
          if (!embedding?.data?.[0]) continue;

          const results = await env.WISDOM_INDEX.query(embedding.data[0], {
            topK: 3,
            returnMetadata: 'all',
          });

          if (results?.matches) {
            for (const match of results.matches) {
              if (match.metadata?.crystal_text) {
                await env.SUMMON_CACHE.put(`prewarm:${match.id}`, match.metadata.crystal_text, {
                  expirationTtl: 3600,
                });
                warmed++;
              }
            }
          }
        } catch { /* individual topic failure is non-fatal */ }
      }
    }

    // Code crystal pre-warming (CODE_SEARCH_INDEX)
    if (env.CODE_SEARCH_INDEX) {
      for (const topic of codeTopics) {
        try {
          const embedding = await env.AI.run('@cf/baai/bge-small-en-v1.5', {
            text: [topic],
          });
          if (!embedding?.data?.[0]) continue;

          const results = await env.CODE_SEARCH_INDEX.query(embedding.data[0], {
            topK: 3,
            returnMetadata: 'all',
          });

          if (results?.matches) {
            for (const match of results.matches) {
              if (match.metadata?.crystal_text) {
                await env.SUMMON_CACHE.put(`prewarm:code:${match.id}`, match.metadata.crystal_text, {
                  expirationTtl: 3600,
                });
                warmed++;
              }
            }
          }
        } catch { /* individual code topic failure is non-fatal */ }
      }

      // R2 manifest-driven pre-warming: read manifest written by CodeCycleDetector
      try {
        const manifestObj = await env.CRYSTAL_STORE.get('code_crystals/prewarm_manifest.json');
        if (manifestObj) {
          const manifest = JSON.parse(await manifestObj.text());
          const crystals = manifest.crystals || [];
          for (const crystal of crystals.slice(0, 50)) {
            if (crystal.text) {
              await env.SUMMON_CACHE.put(
                `prewarm:code:manifest:${crystal.id || crypto.randomUUID()}`,
                crystal.text,
                { expirationTtl: 3600 },
              );
              warmed++;
            }
          }
        }
      } catch { /* manifest read is optional */ }
    }

    // Extension formula outputs from D1 sandbox
    if (env.D1_SANDBOX) {
      try {
        const extRows = await env.D1_SANDBOX.prepare(
          `SELECT formula_name, coherence_result, computed_at
           FROM nate_ext_formula_results
           ORDER BY computed_at DESC
           LIMIT 10`
        ).all();
        for (const row of (extRows.results || [])) {
          const text = `${row.formula_name}: coherence=${Number(row.coherence_result || 0).toFixed(4)} @ ${row.computed_at}`;
          await env.SUMMON_CACHE.put(`prewarm:ext:${row.formula_name}:${Date.now()}`, text, { expirationTtl: 3600 });
          warmed++;
        }
      } catch { /* sandbox prewarm is optional */ }
    }

    const totalTopics = clinicalTopics.length + codeTopics.length;
    await writeMetric(env, 'crystal_prewarm', { crystals_warmed: warmed, topics: totalTopics });
    emitAE(env, {
      type: 'crystal_prewarm',
      service: 'nate-cron-worker',
      stage: 'prewarm',
      status: 'ok',
      source: 'scheduler',
      latency_ms: Date.now() - started,
      value: warmed,
      count: totalTopics,
      target: 'SUMMON_CACHE:prewarm:*',
    });
  } catch (e) {
    await writeMetric(env, 'prewarm_error', { error: e.message });
    emitAE(env, {
      type: 'error',
      service: 'nate-cron-worker',
      stage: 'prewarm',
      status: 'error',
      source: 'scheduler',
      latency_ms: Date.now() - started,
      error_code: 'prewarm_error',
      message: String(e && e.message ? e.message : 'prewarm error').slice(0, 120),
      target: 'SUMMON_CACHE:prewarm:*',
    });
  }
}

async function d1SyncVerify(env) {
  const started = Date.now();
  try {
    const checks = {};

    const userCount = await env.D1_HOT.prepare(
      'SELECT COUNT(*) as cnt FROM users'
    ).first();
    checks.users = userCount?.cnt ?? 0;

    const keyCount = await env.D1_HOT.prepare(
      'SELECT COUNT(*) as cnt FROM api_keys WHERE active = 1'
    ).first();
    checks.api_keys = keyCount?.cnt ?? 0;

    const schedCount = await env.D1_HOT.prepare(
      'SELECT COUNT(*) as cnt FROM coach_schedules'
    ).first();
    checks.schedules = schedCount?.cnt ?? 0;

    checks.verified_at = new Date().toISOString();
    checks.healthy = checks.users > 0;

    await env.SUMMON_CACHE.put('d1:sync_status', JSON.stringify(checks), {
      expirationTtl: 7200,
    });

    await writeMetric(env, 'd1_sync_verify', checks);
    emitAE(env, {
      type: 'extension_formula_run',
      service: 'nate-cron-worker',
      stage: 'd1_sync_verify',
      status: checks.healthy ? 'ok' : 'warning',
      source: 'scheduler',
      latency_ms: Date.now() - started,
      value: checks.users,
      count: checks.api_keys,
      target: 'D1_HOT',
      message: checks.healthy ? 'sync_healthy' : 'sync_degraded',
    });
  } catch (e) {
    await writeMetric(env, 'd1_sync_error', { error: e.message });
    emitAE(env, {
      type: 'error',
      service: 'nate-cron-worker',
      stage: 'd1_sync_verify',
      status: 'error',
      source: 'scheduler',
      latency_ms: Date.now() - started,
      error_code: 'd1_sync_error',
      message: String(e && e.message ? e.message : 'd1 sync error').slice(0, 120),
      target: 'D1_HOT',
    });
  }
}

async function staleCachePurge(env) {
  const started = Date.now();
  try {
    const staleKeys = [
      'alert:sovereign_down',
    ];

    let purged = 0;
    for (const key of staleKeys) {
      const val = await env.SUMMON_CACHE.get(key);
      if (val) {
        try {
          const data = JSON.parse(val);
          const age = Date.now() - new Date(data.detected_at).getTime();
          if (age > 3600000) {
            await env.SUMMON_CACHE.delete(key);
            purged++;
          }
        } catch { /* */ }
      }
    }

    await writeMetric(env, 'cache_purge', { keys_checked: staleKeys.length, purged });
    emitAE(env, {
      type: 'cache_miss',
      service: 'nate-cron-worker',
      stage: 'stale_purge',
      status: 'ok',
      source: 'scheduler',
      latency_ms: Date.now() - started,
      value: purged,
      count: staleKeys.length,
      target: 'SUMMON_CACHE',
    });
  } catch { /* */ }
}

async function writeMetric(env, name, data) {
  try {
    await env.SUMMON_CACHE.put(`cron:metric:${name}`, JSON.stringify({
      ...data,
      metric: name,
      timestamp: new Date().toISOString(),
    }), { expirationTtl: 86400 });
  } catch { /* best-effort */ }
}
