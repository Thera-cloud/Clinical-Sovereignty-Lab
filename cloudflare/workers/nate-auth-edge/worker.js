/**
 * nate-auth-edge — Edge-native token validation + session bootstrap.
 *
 * Validates bearer tokens at the edge using D1 as a read-replica of the
 * users table. Avoids a round-trip to the Sovereign Brain for every
 * authenticated API call.
 *
 * Routes:
 *   POST /api/edge/auth/validate   — Validate token, return user profile
 *   POST /api/edge/auth/bootstrap  — Bootstrap session (tier, features, config)
 *   GET  /api/edge/auth/gate/:user — Tier gate check from D1
 *   GET  /api/edge/auth/device-reputation/:device_id — Edge trust posture
 *   GET  /api/edge/auth/health     — Auth service status
 *
 * Token validation priority:
 *   1. KV cache (sub-ms) — token → user profile cached for 5 min
 *   2. D1 lookup — token hash → users table (edge-local)
 *   3. Sovereign Brain fallback — forward to VPS auth endpoint
 */

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Content-Type': 'application/json',
  };
}

function emitAE(env, event) {
  try {
    if (!env.ANALYTICS_AE || typeof env.ANALYTICS_AE.writeDataPoint !== 'function') return;
    env.ANALYTICS_AE.writeDataPoint({
      indexes: [
        event.type || 'auth_validate',
        event.service || 'nate-auth-edge',
        event.stage || 'request',
        event.status || 'ok',
        event.environment || 'production',
        event.source || 'edge',
        event.colo || 'unknown',
        event.country || 'unknown',
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

const TIER_FEATURES = {
  TRIAL: {
    max_sessions_per_day: 1,
    ai_chat: true,
    voice_chat: false,
    dojo_access: false,
    community_mesh: false,
    token_budget: 500,
  },
  STANDARD: {
    max_sessions_per_day: 3,
    ai_chat: true,
    voice_chat: true,
    dojo_access: true,
    community_mesh: true,
    token_budget: 5000,
  },
  TOP_TIER: {
    max_sessions_per_day: -1,
    ai_chat: true,
    voice_chat: true,
    dojo_access: true,
    community_mesh: true,
    token_budget: -1,
  },
  COACH_ONLY: {
    max_sessions_per_day: 0,
    ai_chat: false,
    voice_chat: false,
    dojo_access: false,
    community_mesh: false,
    token_budget: 0,
  },
};

async function sha256Token(token) {
  const data = new TextEncoder().encode(token);
  const hash = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, '0')).join('');
}

function extractToken(request) {
  const auth = request.headers.get('Authorization') || '';
  if (auth.startsWith('Bearer ')) return auth.slice(7);
  return null;
}

function isJWT(token) {
  if (!token) return false;
  const parts = token.split('.');
  return parts.length === 3 && parts[0].length > 10;
}

function base64UrlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return atob(str);
}

async function validateJWT(env, token) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;

    const payload = JSON.parse(base64UrlDecode(parts[1]));

    if (payload.iss !== (env.JWT_ISSUER || 'littlenate-1.x')) return null;
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) return null;

    const cachedKey = `auth:jwt:${token.slice(0, 32)}`;
    const cached = await env.AUTH_CACHE.get(cachedKey);
    if (cached) {
      const data = JSON.parse(cached);
      if (data.valid) return data;
      return null;
    }

    const resp = await fetch(`${env.SOVEREIGN_API}/api/oauth/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });

    if (!resp.ok) {
      await env.AUTH_CACHE.put(cachedKey, JSON.stringify({ valid: false }), {
        expirationTtl: 60,
      });
      return null;
    }

    const data = await resp.json();
    if (!data.valid) return null;

    const profile = {
      username: payload.sub,
      name: payload.name || payload.sub,
      role: 'API_CLIENT',
      tier: payload.tier || 'free',
      scopes: payload.scopes || [],
      source: 'jwt_validated',
      valid: true,
    };

    await env.AUTH_CACHE.put(cachedKey, JSON.stringify(profile), {
      expirationTtl: Math.min((payload.exp - Math.floor(Date.now() / 1000)), 3600),
    });

    return profile;
  } catch {
    return null;
  }
}

function hasScope(profile, requiredScope) {
  if (!profile || !profile.scopes) return false;
  return profile.scopes.includes(requiredScope);
}

async function validateFromKV(env, token) {
  try {
    const key = `auth:session:${token.slice(0, 16)}`;
    const raw = await env.AUTH_CACHE.get(key);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (data.expires_at && Date.now() > data.expires_at) {
      await env.AUTH_CACHE.delete(key);
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

async function validateFromD1(env, token) {
  try {
    const tokenHash = await sha256Token(token);
    const row = await env.D1_HOT.prepare(
      'SELECT username, role, tier, hardware_id FROM users WHERE token_hash = ?'
    ).bind(tokenHash).first();

    if (!row) return null;

    const profile = {
      username: row.username,
      role: row.role,
      tier: row.tier || 'STANDARD',
      hardware_id: row.hardware_id,
      source: 'edge_d1',
    };

    const cacheKey = `auth:session:${token.slice(0, 16)}`;
    await env.AUTH_CACHE.put(cacheKey, JSON.stringify({
      ...profile,
      expires_at: Date.now() + 300000,
    }), { expirationTtl: 300 });

    return profile;
  } catch {
    return null;
  }
}

async function validateFromSovereign(env, token) {
  try {
    const resp = await fetch(`${env.SOVEREIGN_API}/api/auth/validate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    if (!resp.ok) return null;
    const data = await resp.json();

    if (data.username) {
      const cacheKey = `auth:session:${token.slice(0, 16)}`;
      await env.AUTH_CACHE.put(cacheKey, JSON.stringify({
        ...data,
        source: 'sovereign_validated',
        expires_at: Date.now() + 300000,
      }), { expirationTtl: 300 });
    }

    return data;
  } catch {
    return null;
  }
}

async function handleJWTValidate(request, env) {
  const started = Date.now();
  const token = extractToken(request);
  if (!token || !isJWT(token)) {
    return new Response(JSON.stringify({ valid: false, error: 'JWT required' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  const profile = await validateJWT(env, token);
  if (!profile) {
    emitAE(env, {
      type: 'jwt_validate', service: 'nate-auth-edge',
      stage: 'validate', status: 'error', source: 'edge',
      error_code: 'invalid_jwt', latency_ms: Date.now() - started,
    });
    return new Response(JSON.stringify({ valid: false, error: 'Invalid JWT' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  const requiredScope = new URL(request.url).searchParams.get('scope');
  if (requiredScope && !hasScope(profile, requiredScope)) {
    return new Response(JSON.stringify({
      valid: false, error: 'Insufficient scope', required: requiredScope,
      granted: profile.scopes,
    }), { status: 403, headers: corsHeaders() });
  }

  emitAE(env, {
    type: 'jwt_validate', service: 'nate-auth-edge',
    stage: 'validate', status: 'ok', source: 'jwt',
    actor_id: profile.username, latency_ms: Date.now() - started,
  });

  return new Response(JSON.stringify({ valid: true, ...profile }), {
    headers: corsHeaders(),
  });
}

async function handleValidate(request, env) {
  const started = Date.now();
  const token = extractToken(request);
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();

  if (token && isJWT(token)) {
    return handleJWTValidate(request, env);
  }

  if (!token) {
    emitAE(env, {
      type: 'auth_validate',
      service: 'nate-auth-edge',
      stage: 'validate',
      status: 'error',
      source: 'edge',
      error_code: 'no_token',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      message: 'No bearer token provided',
      actor_id: 'anonymous',
      target: '/api/edge/auth/validate',
    });
    return new Response(JSON.stringify({ valid: false, error: 'No token' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  let profile = await validateFromKV(env, token);
  let source = 'kv_cache';

  if (!profile) {
    profile = await validateFromD1(env, token);
    source = 'edge_d1';
  }

  if (!profile) {
    profile = await validateFromSovereign(env, token);
    source = 'sovereign_fallback';
  }

  if (!profile) {
    emitAE(env, {
      type: 'auth_validate',
      service: 'nate-auth-edge',
      stage: 'validate',
      status: 'error',
      source: source,
      error_code: 'invalid_token',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      actor_id: 'anonymous',
      target: '/api/edge/auth/validate',
    });
    return new Response(JSON.stringify({ valid: false, error: 'Invalid token' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  emitAE(env, {
    type: 'auth_validate',
    service: 'nate-auth-edge',
    stage: 'validate',
    status: 'ok',
    source: source,
    trace_id: traceId,
    request_id: requestId,
    latency_ms: Date.now() - started,
    actor_id: profile.username || '',
    target: '/api/edge/auth/validate',
  });

  return new Response(JSON.stringify({
    valid: true,
    ...profile,
    validation_source: source,
  }), { headers: corsHeaders() });
}

async function handleBootstrap(request, env) {
  const started = Date.now();
  const token = extractToken(request);
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
  if (!token) {
    emitAE(env, {
      type: 'auth_gate',
      service: 'nate-auth-edge',
      stage: 'bootstrap',
      status: 'error',
      source: 'edge',
      error_code: 'no_token',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      target: '/api/edge/auth/bootstrap',
    });
    return new Response(JSON.stringify({ error: 'No token' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  let profile = await validateFromKV(env, token);
  if (!profile) profile = await validateFromD1(env, token);
  if (!profile) profile = await validateFromSovereign(env, token);

  if (!profile) {
    emitAE(env, {
      type: 'auth_gate',
      service: 'nate-auth-edge',
      stage: 'bootstrap',
      status: 'error',
      source: 'edge',
      error_code: 'invalid_token',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      target: '/api/edge/auth/bootstrap',
    });
    return new Response(JSON.stringify({ error: 'Invalid token' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  const tier = (profile.tier || 'STANDARD').toUpperCase();
  const features = TIER_FEATURES[tier] || TIER_FEATURES.STANDARD;

  let tokenBalance = null;
  try {
    const row = await env.D1_HOT.prepare(
      'SELECT token_balance FROM users WHERE username = ?'
    ).bind(profile.username).first();
    if (row) tokenBalance = row.token_balance;
  } catch { /* */ }

  emitAE(env, {
    type: 'auth_gate',
    service: 'nate-auth-edge',
    stage: 'bootstrap',
    status: 'ok',
    source: 'edge',
    trace_id: traceId,
    request_id: requestId,
    latency_ms: Date.now() - started,
    actor_id: profile.username || '',
    target: '/api/edge/auth/bootstrap',
    value: tokenBalance || 0,
  });

  return new Response(JSON.stringify({
    username: profile.username,
    role: profile.role,
    tier,
    features,
    token_balance: tokenBalance,
    session_config: {
      max_duration_minutes: 30,
      ws_endpoint: 'wss://api.sovereignsanctuary.net/ws',
      voice_endpoint: 'https://nate-voice-edge.thera-cloud.workers.dev/api/voice',
      summon_endpoint: 'https://nate-summon-worker.thera-cloud.workers.dev/api/summon',
    },
  }), { headers: corsHeaders() });
}

async function handleGate(env, username) {
  const started = Date.now();
  try {
    const row = await env.D1_HOT.prepare(
      'SELECT username, role, tier, token_balance FROM users WHERE username = ?'
    ).bind(username).first();

    if (!row) {
      emitAE(env, {
        type: 'auth_gate',
        service: 'nate-auth-edge',
        stage: 'gate',
        status: 'warning',
        source: 'edge',
        error_code: 'user_not_found',
        latency_ms: Date.now() - started,
        actor_id: username || '',
        target: '/api/edge/auth/gate',
      });
      return new Response(JSON.stringify({ error: 'User not found' }), {
        status: 404, headers: corsHeaders(),
      });
    }

    const tier = (row.tier || 'STANDARD').toUpperCase();
    const features = TIER_FEATURES[tier] || TIER_FEATURES.STANDARD;

    emitAE(env, {
      type: 'auth_gate',
      service: 'nate-auth-edge',
      stage: 'gate',
      status: 'ok',
      source: 'edge',
      latency_ms: Date.now() - started,
      actor_id: row.username || '',
      target: '/api/edge/auth/gate',
      value: row.token_balance || 0,
      message: tier,
    });

    return new Response(JSON.stringify({
      username: row.username,
      tier,
      role: row.role,
      token_balance: row.token_balance,
      features,
      gated: tier === 'TRIAL' || tier === 'COACH_ONLY',
    }), { headers: corsHeaders() });
  } catch (e) {
    emitAE(env, {
      type: 'error',
      service: 'nate-auth-edge',
      stage: 'gate',
      status: 'error',
      source: 'edge',
      error_code: 'gate_check_failed',
      latency_ms: Date.now() - started,
      actor_id: username || '',
      target: '/api/edge/auth/gate',
      message: String(e && e.message ? e.message : 'gate check failed').slice(0, 120),
    });
    return new Response(JSON.stringify({ error: 'Gate check failed' }), {
      status: 500, headers: corsHeaders(),
    });
  }
}

async function handleHealth(env) {
  const checks = {
    d1: false,
    kv: false,
  };

  try {
    const r = await env.D1_HOT.prepare('SELECT 1 as ok').first();
    checks.d1 = r && r.ok === 1;
  } catch { /* */ }

  try {
    await env.AUTH_CACHE.get('health:probe');
    checks.kv = true;
  } catch { /* */ }

  return new Response(JSON.stringify({
    worker: 'nate-auth-edge',
    status: checks.d1 && checks.kv ? 'ok' : 'degraded',
    checks,
  }), { headers: corsHeaders() });
}

async function handleDeviceReputation(env, deviceId) {
  if (!deviceId) {
    return new Response(JSON.stringify({ error: 'device_id required' }), {
      status: 400, headers: corsHeaders(),
    });
  }
  try {
    const row = await env.D1_HOT.prepare(
      `SELECT device_id, trust_score, quarantined, metadata, updated_at
       FROM device_reputation_edge
       WHERE device_id = ?`
    ).bind(deviceId).first();

    if (!row) {
      return new Response(JSON.stringify({
        device_id: deviceId,
        trusted: false,
        quarantined: false,
        trust_score: 0,
        source: 'd1_edge',
      }), { headers: corsHeaders() });
    }

    return new Response(JSON.stringify({
      device_id: row.device_id,
      trusted: Number(row.trust_score || 0) >= 70 && !Boolean(row.quarantined),
      quarantined: Boolean(row.quarantined),
      trust_score: Number(row.trust_score || 0),
      metadata: row.metadata || null,
      updated_at: row.updated_at || null,
      source: 'd1_edge',
    }), { headers: corsHeaders() });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'Device reputation lookup failed' }), {
      status: 500, headers: corsHeaders(),
    });
  }
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    if (url.pathname === '/api/edge/auth/validate' && request.method === 'POST') {
      return handleValidate(request, env);
    }
    if (url.pathname === '/api/edge/auth/bootstrap' && request.method === 'POST') {
      return handleBootstrap(request, env);
    }
    if (url.pathname.startsWith('/api/edge/auth/gate/')) {
      const username = url.pathname.split('/').pop();
      return handleGate(env, decodeURIComponent(username));
    }
    if (url.pathname.startsWith('/api/edge/auth/device-reputation/')) {
      const deviceId = url.pathname.split('/').pop();
      return handleDeviceReputation(env, decodeURIComponent(deviceId || ''));
    }
    if (url.pathname === '/api/edge/auth/jwt/validate' && request.method === 'POST') {
      return handleJWTValidate(request, env);
    }
    if (url.pathname === '/api/edge/auth/health') {
      return handleHealth(env);
    }

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: corsHeaders(),
    });
  },
};
