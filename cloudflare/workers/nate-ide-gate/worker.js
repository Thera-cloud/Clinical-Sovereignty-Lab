/**
 * nate-ide-gate — Hard gate for ide.sovereignsanctuary.net
 *
 * Requires cookie ss_ide_session (HMAC, minted only after YubiKey verify).
 * Missing/invalid → 302 to Command IDE gateway (YubiKey required).
 * Valid → pass-through to Twin Engine tunnel origin (code-server).
 *
 * Secret: wrangler secret put IDE_GATE_SECRET
 * Must match backend IDE_GATE_SECRET (or JWT_SECRET derivation).
 */

const COOKIE_NAME = "ss_ide_session";
const GATEWAY = "https://command.sovereignsanctuary.net/ide.html";
const PURPOSE = "ide";

function parseCookie(header) {
  const out = {};
  if (!header) return out;
  for (const part of header.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    const v = part.slice(i + 1).trim();
    out[k] = v;
  }
  return out;
}

function b64urlToBytes(s) {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b64 = (s + pad).replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function deriveKey(secretText) {
  const enc = new TextEncoder();
  const material = await crypto.subtle.digest(
    "SHA-256",
    enc.encode("ide-gate-v1:" + secretText)
  );
  return crypto.subtle.importKey(
    "raw",
    material,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

async function verifyToken(token, secretText) {
  if (!token || !secretText || !token.includes(".")) {
    return { ok: false, reason: "missing" };
  }
  try {
    const idx = token.lastIndexOf(".");
    if (idx < 1) return { ok: false, reason: "malformed" };
    const body = token.slice(0, idx);
    const sig = token.slice(idx + 1);
    const key = await deriveKey(secretText);
    const sigBytes = b64urlToBytes(sig);
    const valid = await crypto.subtle.verify(
      "HMAC",
      key,
      sigBytes,
      new TextEncoder().encode(body)
    );
    if (!valid) return { ok: false, reason: "bad_signature" };
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(body)));
    if (payload.pur !== PURPOSE) return { ok: false, reason: "wrong_purpose" };
    if (!payload.exp || payload.exp < Math.floor(Date.now() / 1000)) {
      return { ok: false, reason: "expired" };
    }
    if (!payload.sub) return { ok: false, reason: "no_subject" };
    return { ok: true, payload };
  } catch {
    return { ok: false, reason: "verify_error" };
  }
}

function denyHtml(reason) {
  const body = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>IDE Locked</title>
<style>body{background:#050505;color:#C9A962;font-family:system-ui;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center}
a{color:#E8D5A3}p{color:#8B7355;max-width:28rem;line-height:1.5}</style></head>
<body><div><h1>SOVEREIGN IDE</h1><p>YubiKey session required. Open the Command gateway, tap your key, then retry.</p>
<p><a href="${GATEWAY}">Tap YubiKey at Command → IDE</a></p>
<p style="font-size:11px;opacity:.5">${reason}</p></div></body></html>`;
  return new Response(body, {
    status: 401,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-IDE-Gate": reason,
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Health for operators (no session leak)
    if (url.pathname === "/__ide_gate_health") {
      return Response.json({
        status: "ok",
        service: "nate-ide-gate",
        has_secret: Boolean(env.IDE_GATE_SECRET || env.JWT_SECRET),
      });
    }

    const secret = env.IDE_GATE_SECRET || env.JWT_SECRET || "";
    if (!secret) {
      return denyHtml("gate_misconfigured");
    }

    const cookies = parseCookie(request.headers.get("Cookie") || "");
    let token = cookies[COOKIE_NAME] || "";
    const auth = request.headers.get("Authorization") || "";
    if (!token && auth.toLowerCase().startsWith("bearer ")) {
      token = auth.slice(7).trim();
    }

    const check = await verifyToken(token, secret);
    if (!check.ok) {
      // Browsers: redirect to gateway; API/tools: 401 page
      const accept = request.headers.get("Accept") || "";
      if (accept.includes("text/html") || request.method === "GET") {
        return Response.redirect(GATEWAY + "?need_yk=1&reason=" + encodeURIComponent(check.reason), 302);
      }
      return denyHtml(check.reason);
    }

    // Pass through to Tunnel origin (code-server on Mac)
    return fetch(request);
  },
};
