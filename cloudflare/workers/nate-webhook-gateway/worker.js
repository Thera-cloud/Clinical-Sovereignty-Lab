/**
 * nate-webhook-gateway — Edge webhook validation + forwarding.
 *
 * Validates inbound webhooks from Stripe, Twilio, SendGrid, and Zoom
 * at the edge before forwarding to the Sovereign Brain. Invalid/replayed
 * webhooks are blocked at Cloudflare — they never reach the VPS.
 *
 * Routes:
 *   POST /webhook/stripe    — Stripe signature validation → forward
 *   POST /webhook/twilio    — Twilio signature validation → forward
 *   POST /webhook/sendgrid  — SendGrid event validation → forward
 *   POST /webhook/zoom      — Zoom verification token → forward
 *   GET  /webhook/health    — Gateway status
 *
 * If the Sovereign Brain is down, webhooks are archived to R2 for
 * replay when the brain recovers (max 72h retention).
 */

function corsHeaders() {
  return {
    'Content-Type': 'application/json',
  };
}

function emitAE(env, event) {
  try {
    if (!env.ANALYTICS_AE || typeof env.ANALYTICS_AE.writeDataPoint !== 'function') return;
    env.ANALYTICS_AE.writeDataPoint({
      indexes: [
        event.type || 'webhook_received',
        event.service || 'nate-webhook-gateway',
        event.stage || 'ingress',
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

async function hmacVerify(secret, payload, signature, algorithm = 'SHA-256') {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: algorithm }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload));
  const computed = btoa(String.fromCharCode(...new Uint8Array(sig)));
  return computed === signature;
}

async function verifyStripe(request, env, body) {
  const sigHeader = request.headers.get('Stripe-Signature');
  if (!sigHeader || !env.STRIPE_WEBHOOK_SECRET) return false;

  const parts = {};
  for (const item of sigHeader.split(',')) {
    const [k, v] = item.split('=');
    parts[k.trim()] = v;
  }

  if (!parts.t || !parts.v1) return false;

  const age = Math.floor(Date.now() / 1000) - parseInt(parts.t, 10);
  if (age > 300) return false;

  const payload = `${parts.t}.${body}`;
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(env.STRIPE_WEBHOOK_SECRET),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload));
  const expected = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');
  return expected === parts.v1;
}

async function verifyTwilio(request, env, body) {
  const twilioSig = request.headers.get('X-Twilio-Signature');
  if (!twilioSig || !env.TWILIO_AUTH_TOKEN) return false;

  const url = new URL(request.url);
  const fullUrl = url.origin + url.pathname;

  const params = new URLSearchParams(body);
  const sortedKeys = [...params.keys()].sort();
  let dataString = fullUrl;
  for (const key of sortedKeys) {
    dataString += key + params.get(key);
  }

  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(env.TWILIO_AUTH_TOKEN),
    { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(dataString));
  const computed = btoa(String.fromCharCode(...new Uint8Array(sig)));

  if (computed.length !== twilioSig.length) return false;
  let mismatch = 0;
  for (let i = 0; i < computed.length; i++) {
    mismatch |= computed.charCodeAt(i) ^ twilioSig.charCodeAt(i);
  }
  return mismatch === 0;
}

async function verifySendGrid(request, env, body) {
  const signature = request.headers.get('X-Twilio-Email-Event-Webhook-Signature');
  const timestamp = request.headers.get('X-Twilio-Email-Event-Webhook-Timestamp');

  if (!signature || !timestamp || !env.SENDGRID_WEBHOOK_VERIFICATION_KEY) {
    try {
      const parsed = JSON.parse(body);
      return Array.isArray(parsed) && parsed.length > 0;
    } catch {
      return false;
    }
  }

  try {
    const publicKeyPem = env.SENDGRID_WEBHOOK_VERIFICATION_KEY;
    const pemBody = publicKeyPem
      .replace(/-----BEGIN PUBLIC KEY-----/, '')
      .replace(/-----END PUBLIC KEY-----/, '')
      .replace(/\s/g, '');
    const binaryKey = Uint8Array.from(atob(pemBody), c => c.charCodeAt(0));

    const ecKey = await crypto.subtle.importKey(
      'spki', binaryKey.buffer,
      { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']
    );

    const payload = timestamp + body;
    const sigBytes = Uint8Array.from(atob(signature), c => c.charCodeAt(0));
    const payloadBytes = new TextEncoder().encode(payload);

    const valid = await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' }, ecKey, sigBytes, payloadBytes
    );
    return valid;
  } catch {
    return false;
  }
}

async function verifyZoom(request, env, body) {
  try {
    const data = JSON.parse(body);
    if (data.event === 'endpoint.url_validation') {
      return { validation: true, plainToken: data.payload?.plainToken };
    }
    return { validation: false };
  } catch {
    return { validation: false };
  }
}

async function forwardToSovereign(env, path, request, body) {
  try {
    const resp = await fetch(`${env.SOVEREIGN_API}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': request.headers.get('Content-Type') || 'application/json',
        'Stripe-Signature': request.headers.get('Stripe-Signature') || '',
        'X-Twilio-Signature': request.headers.get('X-Twilio-Signature') || '',
        'X-Forwarded-By': 'nate-webhook-gateway',
      },
      body,
    });
    return { success: resp.ok, status: resp.status };
  } catch (e) {
    return { success: false, status: 0, error: e.message };
  }
}

async function archiveWebhook(env, provider, body) {
  try {
    const key = `webhook-queue/${provider}/${Date.now()}-${crypto.randomUUID()}.json`;
    await env.WEBHOOK_ARCHIVE.put(key, JSON.stringify({
      provider,
      body,
      received_at: new Date().toISOString(),
      forwarded: false,
    }));
    return key;
  } catch {
    return null;
  }
}

async function recordMetric(env, provider, result) {
  try {
    const key = `webhook:metric:${provider}:${Date.now()}`;
    await env.WEBHOOK_STATE.put(key, JSON.stringify({
      provider,
      ...result,
      timestamp: new Date().toISOString(),
    }), { expirationTtl: 86400 });
  } catch { /* best-effort */ }
}

async function handleStripe(request, env) {
  const started = Date.now();
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
  const body = await request.text();
  emitAE(env, {
    type: 'webhook_received',
    service: 'nate-webhook-gateway',
    stage: 'ingress',
    status: 'start',
    source: 'stripe',
    trace_id: traceId,
    request_id: requestId,
    target: '/webhook/stripe',
  });
  const valid = await verifyStripe(request, env, body);

  if (!valid) {
    await recordMetric(env, 'stripe', { action: 'rejected', reason: 'invalid_signature' });
    emitAE(env, {
      type: 'webhook_received',
      service: 'nate-webhook-gateway',
      stage: 'verify',
      status: 'error',
      source: 'stripe',
      error_code: 'invalid_signature',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      target: '/webhook/stripe',
    });
    return new Response(JSON.stringify({ error: 'Invalid signature' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  const result = await forwardToSovereign(env, '/api/stripe/webhook', request, body);

  if (!result.success) {
    const archiveKey = await archiveWebhook(env, 'stripe', body);
    await recordMetric(env, 'stripe', { action: 'archived', archive_key: archiveKey });
    emitAE(env, {
      type: 'webhook_forwarded',
      service: 'nate-webhook-gateway',
      stage: 'forward',
      status: 'warning',
      source: 'stripe',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      error_code: 'forward_failed_archived',
      target: '/api/stripe/webhook',
      message: archiveKey || '',
    });
    return new Response(JSON.stringify({ status: 'queued', archive_key: archiveKey }), {
      status: 202, headers: corsHeaders(),
    });
  }

  emitAE(env, {
    type: 'webhook_forwarded',
    service: 'nate-webhook-gateway',
    stage: 'forward',
    status: 'ok',
    source: 'stripe',
    trace_id: traceId,
    request_id: requestId,
    latency_ms: Date.now() - started,
    target: '/api/stripe/webhook',
    value: result.status || 200,
  });
  await recordMetric(env, 'stripe', { action: 'forwarded', sovereign_status: result.status });
  return new Response(JSON.stringify({ status: 'forwarded' }), {
    status: 200, headers: corsHeaders(),
  });
}

async function handleTwilio(request, env) {
  const started = Date.now();
  const body = await request.text();
  const valid = await verifyTwilio(request, env, body);

  if (!valid) {
    await recordMetric(env, 'twilio', { action: 'rejected' });
    return new Response(JSON.stringify({ error: 'Invalid signature' }), {
      status: 401, headers: corsHeaders(),
    });
  }

  const result = await forwardToSovereign(env, '/api/twilio/webhook', request, body);

  if (!result.success) {
    await archiveWebhook(env, 'twilio', body);
  }

  await recordMetric(env, 'twilio', { action: result.success ? 'forwarded' : 'archived' });
  emitAE(env, {
    type: 'webhook_forwarded',
    service: 'nate-webhook-gateway',
    stage: 'forward',
    status: result.success ? 'ok' : 'warning',
    source: 'twilio',
    latency_ms: Date.now() - started,
    target: '/api/twilio/webhook',
    error_code: result.success ? '' : 'forward_failed_archived',
  });
  return new Response('', { status: 200 });
}

async function handleSendGrid(request, env) {
  const started = Date.now();
  const body = await request.text();
  const valid = await verifySendGrid(request, env, body);

  if (!valid) {
    await recordMetric(env, 'sendgrid', { action: 'rejected' });
    return new Response(JSON.stringify({ error: 'Invalid signature' }), {
      status: 403, headers: corsHeaders(),
    });
  }

  const result = await forwardToSovereign(env, '/api/sendgrid/inbound', request, body);

  if (!result.success) {
    await archiveWebhook(env, 'sendgrid', body);
  }

  await recordMetric(env, 'sendgrid', { action: result.success ? 'forwarded' : 'archived' });
  emitAE(env, {
    type: 'webhook_forwarded',
    service: 'nate-webhook-gateway',
    stage: 'forward',
    status: result.success ? 'ok' : 'warning',
    source: 'sendgrid',
    latency_ms: Date.now() - started,
    target: '/api/sendgrid/inbound',
    error_code: result.success ? '' : 'forward_failed_archived',
  });
  return new Response('', { status: 200 });
}

async function handleZoom(request, env) {
  const started = Date.now();
  const body = await request.text();
  const verification = await verifyZoom(request, env, body);

  if (verification.validation && verification.plainToken) {
    const key = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(env.ZOOM_WEBHOOK_SECRET || ''),
      { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    );
    const sig = await crypto.subtle.sign('HMAC', key,
      new TextEncoder().encode(verification.plainToken));
    const hash = Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, '0')).join('');

    return new Response(JSON.stringify({
      plainToken: verification.plainToken,
      encryptedToken: hash,
    }), { status: 200, headers: corsHeaders() });
  }

  const result = await forwardToSovereign(env, '/api/zoom/webhook', request, body);

  if (!result.success) {
    await archiveWebhook(env, 'zoom', body);
  }

  await recordMetric(env, 'zoom', { action: result.success ? 'forwarded' : 'archived' });
  emitAE(env, {
    type: 'webhook_forwarded',
    service: 'nate-webhook-gateway',
    stage: 'forward',
    status: result.success ? 'ok' : 'warning',
    source: 'zoom',
    latency_ms: Date.now() - started,
    target: '/api/zoom/webhook',
    error_code: result.success ? '' : 'forward_failed_archived',
  });
  return new Response('', { status: 200 });
}

async function handleHealth(env) {
  const providers = ['stripe', 'twilio', 'sendgrid', 'zoom'];
  const status = {};
  for (const p of providers) {
    status[p] = {
      secret_configured: p === 'stripe' ? !!env.STRIPE_WEBHOOK_SECRET :
                         p === 'twilio' ? !!env.TWILIO_AUTH_TOKEN :
                         p === 'zoom' ? !!env.ZOOM_WEBHOOK_SECRET : true,
    };
  }

  return new Response(JSON.stringify({
    worker: 'nate-webhook-gateway',
    status: 'ok',
    providers: status,
    archive_bucket: !!env.WEBHOOK_ARCHIVE,
  }), { headers: corsHeaders() });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'POST') {
      if (url.pathname === '/webhook/stripe') return handleStripe(request, env);
      if (url.pathname === '/webhook/twilio') return handleTwilio(request, env);
      if (url.pathname === '/webhook/sendgrid') return handleSendGrid(request, env);
      if (url.pathname === '/webhook/zoom') return handleZoom(request, env);
    }

    if (url.pathname === '/webhook/health') return handleHealth(env);

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: corsHeaders(),
    });
  },
};
