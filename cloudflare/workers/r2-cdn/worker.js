/**
 * Sovereign Sanctuary — R2 CDN Worker
 *
 * Serves objects from R2 buckets through cdn.sovereignsanctuary.net with
 * aggressive caching headers. Smart Tiered Cache + this Worker = near-zero
 * R2 Class A/B operation costs at any scale.
 *
 * Routes:
 *   cdn.sovereignsanctuary.net/vault/*   → nate-vault bucket
 *   cdn.sovereignsanctuary.net/lake/*    → nate-analytics bucket
 *
 * Cache strategy:
 *   - Static assets (images, PDFs, videos): 30 days edge, 7 days browser
 *   - Dynamic exports: 1 hour edge, 10 min browser
 *   - Analytics parquet files: 24 hours edge (Iceberg partition immutable)
 *   - ETag-based revalidation for all content
 *
 * Deploy: cd cloudflare/workers/r2-cdn && npx wrangler deploy
 */

const CACHE_PROFILES = {
  avatar: { edgeTTL: 2592000, browserTTL: 604800 },       // 30d / 7d
  image: { edgeTTL: 2592000, browserTTL: 604800 },        // 30d / 7d
  pdf: { edgeTTL: 2592000, browserTTL: 604800 },          // 30d / 7d
  video: { edgeTTL: 2592000, browserTTL: 604800 },        // 30d / 7d
  export: { edgeTTL: 3600, browserTTL: 600 },             // 1h / 10m
  parquet: { edgeTTL: 86400, browserTTL: 3600 },          // 24h / 1h
  default: { edgeTTL: 86400, browserTTL: 3600 },          // 24h / 1h
};

const CONTENT_TYPES = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  pdf: "application/pdf",
  mp4: "video/mp4",
  webm: "video/webm",
  json: "application/json",
  csv: "text/csv",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  parquet: "application/octet-stream",
  html: "text/html",
  txt: "text/plain",
};

function getCacheProfile(key) {
  if (key.startsWith("avatars/")) return CACHE_PROFILES.avatar;
  if (key.endsWith(".pdf")) return CACHE_PROFILES.pdf;
  if (/\.(mp4|webm)$/.test(key)) return CACHE_PROFILES.video;
  if (/\.(png|jpg|jpeg|gif|webp|svg)$/.test(key)) return CACHE_PROFILES.image;
  if (/\.(xlsx|csv)$/.test(key)) return CACHE_PROFILES.export;
  if (key.endsWith(".parquet")) return CACHE_PROFILES.parquet;
  return CACHE_PROFILES.default;
}

function getContentType(key) {
  const ext = key.split(".").pop()?.toLowerCase();
  return CONTENT_TYPES[ext] || "application/octet-stream";
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: corsHeaders(),
      });
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    let bucket;
    let objectKey;

    if (path.startsWith("/vault/")) {
      bucket = env.VAULT_BUCKET;
      objectKey = path.slice(7); // strip "/vault/"
    } else if (path.startsWith("/lake/")) {
      bucket = env.ANALYTICS_BUCKET;
      objectKey = path.slice(6); // strip "/lake/"
    } else if (path === "/health") {
      return jsonResp({ status: "ok", buckets: ["vault", "analytics"] });
    } else {
      return new Response("Not Found", { status: 404 });
    }

    if (!bucket) {
      return jsonResp({ error: "Bucket binding not configured" }, 503);
    }

    if (!objectKey || objectKey === "/") {
      return jsonResp({ error: "Object key required" }, 400);
    }

    // Check Cloudflare Cache API first
    const cache = caches.default;
    const cacheKey = new Request(url.toString(), request);
    let cached = await cache.match(cacheKey);
    if (cached) {
      const resp = new Response(cached.body, cached);
      resp.headers.set("X-Cache-Status", "HIT");
      return resp;
    }

    // Fetch from R2
    const object = await bucket.get(objectKey);
    if (!object) {
      return new Response("Not Found", { status: 404 });
    }

    const profile = getCacheProfile(objectKey);
    const contentType = object.httpMetadata?.contentType || getContentType(objectKey);

    const headers = {
      "Content-Type": contentType,
      "Cache-Control": `public, max-age=${profile.browserTTL}, s-maxage=${profile.edgeTTL}`,
      "CDN-Cache-Control": `public, max-age=${profile.edgeTTL}`,
      "X-Cache-Status": "MISS",
      "X-R2-Key": objectKey,
      "ETag": object.httpEtag || `"${object.etag}"`,
      ...corsHeaders(),
    };

    if (object.size) {
      headers["Content-Length"] = object.size.toString();
    }

    const response = new Response(object.body, {
      status: 200,
      headers,
    });

    // Store in CF cache for edge TTL
    ctx.waitUntil(
      cache.put(cacheKey, response.clone())
    );

    return response;
  },
};

function jsonResp(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...corsHeaders(),
    },
  });
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, Range",
    "Access-Control-Expose-Headers": "Content-Length, ETag, X-Cache-Status",
  };
}
