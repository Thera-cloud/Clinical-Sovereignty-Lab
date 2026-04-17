/**
 * Sovereign Sanctuary — Edge Cache + Semantic Search Worker
 *
 * Cloudflare Worker with two responsibilities:
 *
 * A) EDGE CACHING — Intelligent cache for API responses:
 *    1. Vault file downloads from R2 (zero egress on cache hit)
 *    2. Memory search results per-user for 60s
 *    3. Static API responses (templates, schemas) for 24h
 *    4. Coach folder file downloads for 1h
 *    5. DOJO assessment PDFs and exports for 1h
 *    6. Session memory data per-user for 2min
 *
 * B) EDGE SEMANTIC SEARCH — Vectorize-powered semantic queries:
 *    POST /api/edge/semantic-search → embed query via Workers AI → query
 *    Vectorize indexes → return scored results. Runs entirely at the edge
 *    with zero origin round-trips for cached embeddings.
 *
 * Deploy: npx wrangler deploy
 * Config: wrangler.toml in the same directory
 *
 * Bindings: AI (Workers AI), MEMORY_INDEX, VAULT_INDEX, WISDOM_INDEX,
 *           ME2ME_INDEX, SESSION_INDEX, ANNOTATION_INDEX (Vectorize),
 *           VAULT_BUCKET, ANALYTICS_BUCKET (R2), D1_HOT (D1)
 *
 * C) EDGE D1 QUERIES — Sub-millisecond reads from D1 SQLite at edge:
 *    GET /api/edge/d1/roster/:coach_id → client roster
 *    GET /api/edge/d1/schedule/:coach_id → upcoming sessions
 *    GET /api/edge/d1/presence → online users
 *    GET /api/edge/d1/balance/:username → token balance
 *    GET /api/edge/d1/gate/:username → tier gate check
 */

const CACHE_RULES = [
  {
    pattern: /^\/api\/coach\/folders\/files\/.+\/download$/,
    ttl: 3600,
    scope: "public",
    tag: "file-download",
  },
  {
    pattern: /^\/api\/dojo\/download-assessment\/.+$/,
    ttl: 3600,
    scope: "public",
    tag: "assessment-pdf",
  },
  {
    pattern: /^\/api\/dojo\/download-export\/.+$/,
    ttl: 3600,
    scope: "public",
    tag: "export-file",
  },
  {
    pattern: /^\/api\/sessions\/classroom\/video\/.+$/,
    ttl: 7200,
    scope: "public",
    tag: "classroom-video",
  },
  {
    pattern: /^\/api\/client\/memory\/search\/.+$/,
    ttl: 60,
    scope: "user",
    tag: "memory-search",
  },
  {
    pattern: /^\/api\/client\/memory\/sessions\/.+$/,
    ttl: 120,
    scope: "user",
    tag: "memory-sessions",
  },
  {
    pattern: /^\/api\/sessions\/classroom\/session\/.+$/,
    ttl: 120,
    scope: "user",
    tag: "classroom-session-data",
  },
  {
    pattern: /^\/api\/v1\/vault\/search$/,
    ttl: 30,
    scope: "user",
    tag: "vault-search",
  },
  {
    pattern: /^\/api\/v1\/vault\/stats$/,
    ttl: 120,
    scope: "user",
    tag: "vault-stats",
  },
  {
    pattern: /^\/api\/v1\/vault\/folders$/,
    ttl: 120,
    scope: "user",
    tag: "vault-folders",
  },
  {
    pattern: /^\/api\/corp\/template\/download$/,
    ttl: 86400,
    scope: "public",
    tag: "static-template",
  },
  {
    pattern: /^\/api\/skyeye\/platforms$/,
    ttl: 300,
    scope: "public",
    tag: "platform-list",
  },
  {
    pattern: /^\/api\/skyeye\/platform-health$/,
    ttl: 300,
    scope: "public",
    tag: "platform-health",
  },
];

const INDEX_BINDINGS = {
  conversation: "MEMORY_INDEX",
  vault: "VAULT_INDEX",
  wisdom: "WISDOM_INDEX",
  me2me: "ME2ME_INDEX",
  session: "SESSION_INDEX",
  annotation: "ANNOTATION_INDEX",
};

async function validateEdgeAuth(request, env) {
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ")) return null;
  const token = auth.slice(7);
  if (!token) return null;

  const cacheKey = `edge:auth:${token.slice(0, 16)}`;
  if (env.EDGE_CACHE_KV) {
    try {
      const cached = await env.EDGE_CACHE_KV.get(cacheKey);
      if (cached) return JSON.parse(cached);
    } catch { /* */ }
  }

  try {
    const resp = await fetch(`${env.SOVEREIGN_API || "https://api.sovereignsanctuary.net"}/api/edge/auth/validate`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (!data.valid) return null;
    if (env.EDGE_CACHE_KV) {
      try { await env.EDGE_CACHE_KV.put(cacheKey, JSON.stringify(data), { expirationTtl: 300 }); } catch { /* */ }
    }
    return data;
  } catch {
    return null;
  }
}

export default {
  async fetch(request, env, ctx) {
    _edgeCacheOrigin = request.headers.get("Origin") || "";
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "OPTIONS") {
      return jsonResponse({}, 204);
    }
    if (request.method === "POST") {
      const clientIP = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
      if (!checkRateLimit(clientIP)) {
        return jsonResponse({ error: "Rate limit exceeded" }, 429);
      }
    }

    // --- D1 edge queries (sub-ms reads) — require auth ---
    if (path.startsWith("/api/edge/d1/") && request.method === "GET") {
      const user = await validateEdgeAuth(request, env);
      if (!user) return jsonResponse({ error: "Authentication required" }, 401);
      return handleD1Query(path, url, env, user);
    }
    if (path === "/api/edge/d1/social-dashboard" && request.method === "GET") {
      const user = await validateEdgeAuth(request, env);
      if (!user) return jsonResponse({ error: "Authentication required" }, 401);
      return handleSocialDashboardEdge(url, env);
    }
    if (path.startsWith("/api/edge/d1/compliance/") && request.method === "GET") {
      const user = await validateEdgeAuth(request, env);
      if (!user) return jsonResponse({ error: "Authentication required" }, 401);
      const jurisdiction = decodeURIComponent(path.replace("/api/edge/d1/compliance/", ""));
      return handleComplianceEdge(jurisdiction, env);
    }

    // --- Semantic search at the edge — require auth, enforce ownership ---
    if (path === "/api/edge/semantic-search" && request.method === "POST") {
      const user = await validateEdgeAuth(request, env);
      if (!user) return jsonResponse({ error: "Authentication required" }, 401);
      return handleSemanticSearch(request, env, user);
    }

    // --- Vectorize pipeline health at the edge ---
    if (path === "/api/edge/vectorize/health" && request.method === "GET") {
      return handleVectorizeHealth(env);
    }

    // --- Edge caching for GET requests ---
    if (request.method !== "GET") {
      return fetch(request);
    }

    const rule = CACHE_RULES.find((r) => r.pattern.test(path));
    if (!rule) {
      return fetch(request);
    }

    let cacheKey = url.toString();
    if (rule.scope === "user") {
      const auth = request.headers.get("Authorization") || "";
      const tokenHash = await hashToken(auth);
      cacheKey = `${url.toString()}::user=${tokenHash}`;
    }

    const cacheKeyRequest = new Request(cacheKey, {
      method: "GET",
      headers: request.headers,
    });

    const cache = caches.default;
    let response = await cache.match(cacheKeyRequest);

    if (response) {
      const newResponse = new Response(response.body, response);
      newResponse.headers.set("X-Cache-Status", "HIT");
      newResponse.headers.set("X-Cache-Tag", rule.tag);
      return newResponse;
    }

    response = await fetch(request);

    if (response.status === 200) {
      const cloned = response.clone();
      const cachedResponse = new Response(cloned.body, {
        status: cloned.status,
        statusText: cloned.statusText,
        headers: new Headers(cloned.headers),
      });

      cachedResponse.headers.set(
        "Cache-Control",
        `public, max-age=${rule.ttl}`,
      );
      cachedResponse.headers.set("X-Cache-Tag", rule.tag);

      ctx.waitUntil(cache.put(cacheKeyRequest, cachedResponse));

      const returnResponse = new Response(response.body, response);
      returnResponse.headers.set("X-Cache-Status", "MISS");
      returnResponse.headers.set("X-Cache-Tag", rule.tag);
      return returnResponse;
    }

    return response;
  },
};

/**
 * D1 edge query handler — sub-millisecond reads from SQLite at the edge.
 *
 * Routes:
 *   /api/edge/d1/roster/:coach_id    → client roster for a coach
 *   /api/edge/d1/schedule/:coach_id  → upcoming sessions for a coach
 *   /api/edge/d1/presence            → currently online users
 *   /api/edge/d1/presence/count      → online user counts by role
 *   /api/edge/d1/balance/:username   → token balance
 *   /api/edge/d1/gate/:username      → tier gate check
 *   /api/edge/d1/live-sessions       → active coaching sessions
 */
async function handleD1Query(path, url, env, user) {
  if (!env.D1_HOT) {
    return jsonResponse({ error: "D1 not configured" }, 503);
  }

  const db = env.D1_HOT;
  const segments = path.replace("/api/edge/d1/", "").split("/");
  const resource = segments[0];
  const param = segments[1] || "";
  const now = new Date().toISOString();
  const TTL_FILTER = "(expires_at IS NULL OR expires_at > ?)";

  try {
    switch (resource) {
      case "roster": {
        if (!param) return jsonResponse({ error: "coach_id required" }, 400);
        const rows = await db
          .prepare(
            `SELECT username, display_name, tier, subscription_status, family_id, company_name, group_id, token_balance FROM client_roster WHERE coach_id = ? AND is_active = 1 AND ${TTL_FILTER} ORDER BY display_name`,
          )
          .bind(param, now)
          .all();
        return jsonResponse({
          coach_id: param,
          clients: rows.results || [],
          count: rows.results?.length || 0,
          source: "d1_edge",
        });
      }

      case "schedule": {
        if (!param) return jsonResponse({ error: "coach_id required" }, 400);
        const rows = await db
          .prepare(
            `SELECT session_id, client_id, client_name, status, session_type, scheduled_at, scheduled_start, duration_minutes, zoom_link, payment_status FROM coach_schedules WHERE coach_id = ? AND ${TTL_FILTER} ORDER BY scheduled_at`,
          )
          .bind(param, now)
          .all();
        return jsonResponse({
          coach_id: param,
          sessions: rows.results || [],
          count: rows.results?.length || 0,
          source: "d1_edge",
        });
      }

      case "presence": {
        if (param === "count") {
          const rows = await db
            .prepare(
              `SELECT role, COUNT(*) AS count FROM user_presence WHERE is_online = 1 AND ${TTL_FILTER} GROUP BY role`,
            )
            .bind(now)
            .all();
          const counts = { CLIENT: 0, COACH: 0, ADMIN: 0, total: 0 };
          for (const r of rows.results || []) {
            counts[r.role] = r.count;
            counts.total += r.count;
          }
          return jsonResponse({ ...counts, source: "d1_edge" });
        }
        const roleFilter = url.searchParams.get("role");
        let rows;
        if (roleFilter) {
          rows = await db
            .prepare(
              `SELECT username, role, portal, device_type, last_seen_at, connected_at FROM user_presence WHERE is_online = 1 AND role = ? AND ${TTL_FILTER}`,
            )
            .bind(roleFilter, now)
            .all();
        } else {
          rows = await db
            .prepare(
              `SELECT username, role, portal, device_type, last_seen_at, connected_at FROM user_presence WHERE is_online = 1 AND ${TTL_FILTER}`,
            )
            .bind(now)
            .all();
        }
        return jsonResponse({
          users: rows.results || [],
          count: rows.results?.length || 0,
          source: "d1_edge",
        });
      }

      case "balance": {
        if (!param) return jsonResponse({ error: "username required" }, 400);
        const row = await db
          .prepare(
            `SELECT username, balance, usage_today, usage_month, tier FROM token_balances WHERE username = ? AND ${TTL_FILTER}`,
          )
          .bind(param, now)
          .first();
        if (!row)
          return jsonResponse({ error: "User not found or expired" }, 404);
        return jsonResponse({ ...row, source: "d1_edge" });
      }

      case "gate": {
        if (!param) return jsonResponse({ error: "username required" }, 400);
        const row = await db
          .prepare(
            `SELECT username, role, tier, subscription_status, dojo_subscriptions, has_coaching, is_founding, consent_version FROM tier_gates WHERE username = ? AND ${TTL_FILTER}`,
          )
          .bind(param, now)
          .first();
        if (!row)
          return jsonResponse({ error: "User not found or expired" }, 404);
        return jsonResponse({ ...row, source: "d1_edge" });
      }

      case "live-sessions": {
        const rows = await db
          .prepare(
            `SELECT session_id, coach_id, client_id, status, started_at, zoom_link, nate_active FROM live_sessions WHERE status IN ('WAITING', 'IN_PROGRESS') AND ${TTL_FILTER} ORDER BY started_at`,
          )
          .bind(now)
          .all();
        return jsonResponse({
          sessions: rows.results || [],
          count: rows.results?.length || 0,
          source: "d1_edge",
        });
      }

      default:
        return jsonResponse({ error: "Unknown D1 resource: " + resource }, 404);
    }
  } catch (err) {
    return jsonResponse(
      { error: "D1 query failed", detail: err.message },
      500,
    );
  }
}

async function handleSocialDashboardEdge(url, env) {
  if (!env.D1_HOT) return jsonResponse({ error: "D1 not configured" }, 503);
  try {
    const platform = url.searchParams.get("platform");
    let rows;
    if (platform) {
      rows = await env.D1_HOT.prepare(
        `SELECT platform, metric_key, metric_value, captured_at
         FROM social_dashboard_cache
         WHERE platform = ?
         ORDER BY captured_at DESC
         LIMIT 200`
      ).bind(platform).all();
    } else {
      rows = await env.D1_HOT.prepare(
        `SELECT platform, metric_key, metric_value, captured_at
         FROM social_dashboard_cache
         ORDER BY captured_at DESC
         LIMIT 500`
      ).all();
    }
    return jsonResponse({
      platform: platform || "all",
      rows: rows.results || [],
      count: (rows.results || []).length,
      source: "d1_edge",
    });
  } catch (err) {
    return jsonResponse({ error: "social dashboard query failed", detail: err.message }, 500);
  }
}

async function handleComplianceEdge(jurisdiction, env) {
  if (!env.D1_HOT) return jsonResponse({ error: "D1 not configured" }, 503);
  if (!jurisdiction) return jsonResponse({ error: "jurisdiction required" }, 400);
  try {
    const rows = await env.D1_HOT.prepare(
      `SELECT jurisdiction, rule_key, rule_value, updated_at
       FROM compliance_rules_edge
       WHERE jurisdiction = ?
       ORDER BY updated_at DESC`
    ).bind(jurisdiction).all();
    return jsonResponse({
      jurisdiction,
      rules: rows.results || [],
      count: (rows.results || []).length,
      source: "d1_edge",
    });
  } catch (err) {
    return jsonResponse({ error: "compliance query failed", detail: err.message }, 500);
  }
}

/**
 * Edge semantic search handler.
 * Embeds the query via Workers AI, then queries specified Vectorize indexes.
 *
 * Request body: { query: string, user_id: string, indexes?: string[], top_k?: number }
 * Response: { results: { [index]: matches[] }, search_type: "edge_semantic" }
 */
async function handleSemanticSearch(request, env, user) {
  try {
    const body = await request.json();
    const { query, indexes, top_k } = body;
    const user_id = user.username || user.hardware_id;

    if (!query) {
      return jsonResponse(
        { error: "query required" },
        400,
      );
    }

    const k = Math.min(top_k || 10, 50);
    const targetIndexes = indexes || Object.keys(INDEX_BINDINGS);

    // BGE retrieval instruction prefix — free +1-2% nDCG recall boost
    const BGE_QUERY_PREFIX =
      "Represent this sentence for searching relevant passages: ";
    const prefixedQuery = BGE_QUERY_PREFIX + query.substring(0, 2000);

    // Generate embedding via Workers AI (free with Workers Paid plan)
    let embedding;
    try {
      const aiResult = await env.AI.run("@cf/baai/bge-small-en-v1.5", {
        text: [prefixedQuery],
      });
      embedding = aiResult.data?.[0];
      if (!embedding) {
        return jsonResponse({ error: "Embedding generation failed" }, 500);
      }
    } catch (aiErr) {
      return jsonResponse(
        { error: "Workers AI unavailable", detail: aiErr.message },
        503,
      );
    }

    // Query each requested Vectorize index concurrently
    const queryPromises = {};
    for (const idx of targetIndexes) {
      const bindingName = INDEX_BINDINGS[idx];
      if (!bindingName || !env[bindingName]) continue;

      queryPromises[idx] = env[bindingName]
        .query(embedding, {
          topK: k,
          returnMetadata: "all",
          filter: { user_id: user_id },
        })
        .catch((err) => {
          console.warn(`Vectorize query failed for ${idx}:`, err.message);
          return { matches: [] };
        });
    }

    const entries = Object.entries(queryPromises);
    const settled = await Promise.all(entries.map(([, p]) => p));
    const results = {};
    let totalMatches = 0;

    entries.forEach(([idx], i) => {
      const matches = settled[i]?.matches || [];
      results[idx] = matches.map((m) => ({
        id: m.id,
        score: m.score,
        metadata: m.metadata || {},
      }));
      totalMatches += matches.length;
    });

    return jsonResponse({
      query,
      total_matches: totalMatches,
      results,
      search_type: "edge_semantic",
      indexes_searched: Object.keys(results),
    });
  } catch (err) {
    return jsonResponse(
      { error: "Semantic search failed", detail: err.message },
      500,
    );
  }
}

/**
 * Edge-level Vectorize pipeline health check.
 * Tests Workers AI embedding + each Vectorize index reachability.
 */
async function handleVectorizeHealth(env) {
  const checks = {};
  const BGE_QUERY_PREFIX =
    "Represent this sentence for searching relevant passages: ";

  try {
    const t0 = Date.now();
    const aiResult = await env.AI.run("@cf/baai/bge-small-en-v1.5", {
      text: [BGE_QUERY_PREFIX + "health check probe"],
    });
    checks.workers_ai = {
      ok: !!aiResult?.data?.[0],
      ms: Date.now() - t0,
      dimension: aiResult?.data?.[0]?.length || 0,
    };

    if (checks.workers_ai.ok) {
      const embedding = aiResult.data[0];
      for (const [idx, bindingName] of Object.entries(INDEX_BINDINGS)) {
        if (!env[bindingName]) {
          checks[idx] = { ok: false, error: "binding missing" };
          continue;
        }
        try {
          const t1 = Date.now();
          const result = await env[bindingName].query(embedding, {
            topK: 1,
            returnMetadata: "none",
          });
          checks[idx] = {
            ok: true,
            ms: Date.now() - t1,
            matches: result?.matches?.length || 0,
          };
        } catch (err) {
          checks[idx] = { ok: false, error: err.message };
        }
      }
    }
  } catch (err) {
    checks.workers_ai = { ok: false, error: err.message };
  }

  const allOk = Object.values(checks).every((c) => c.ok);
  return jsonResponse({
    status: allOk ? "healthy" : "degraded",
    checks,
    source: "edge_worker",
  });
}

const _ALLOWED_ORIGINS = new Set([
  "https://app.sovereignsanctuary.net",
  "https://coach.sovereignsanctuary.net",
  "https://command.sovereignsanctuary.net",
  "https://api.sovereignsanctuary.net",
]);
let _edgeCacheOrigin = "";

const _rateLimitMap = new Map();
const RATE_LIMIT_WINDOW_MS = 60000;
const RATE_LIMIT_MAX_POST = 30;

function checkRateLimit(ip) {
  const now = Date.now();
  const entry = _rateLimitMap.get(ip);
  if (!entry || now - entry.start > RATE_LIMIT_WINDOW_MS) {
    _rateLimitMap.set(ip, { start: now, count: 1 });
    if (_rateLimitMap.size > 10000) {
      const oldest = _rateLimitMap.keys().next().value;
      _rateLimitMap.delete(oldest);
    }
    return true;
  }
  entry.count++;
  return entry.count <= RATE_LIMIT_MAX_POST;
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": _ALLOWED_ORIGINS.has(_edgeCacheOrigin) ? _edgeCacheOrigin : "",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}

async function hashToken(token) {
  if (!token) return "anon";
  const data = new TextEncoder().encode(token);
  const hash = await crypto.subtle.digest("SHA-256", data);
  const arr = Array.from(new Uint8Array(hash));
  return arr
    .slice(0, 8)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
