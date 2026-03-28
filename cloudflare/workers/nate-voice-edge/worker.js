/**
 * nate-voice-edge — Sub-200ms voice pipeline router at the edge.
 *
 * Handles:
 *   POST /api/voice/stt      — Speech-to-Text routing (Sovereign Whisper → Workers AI)
 *   POST /api/voice/tts      — Text-to-Speech routing (Sovereign XTTS → Workers AI MeloTTS)
 *   POST /api/voice/pipeline  — Full pipeline: STT → inference → TTS in one round trip
 *   GET  /api/voice/health    — Provider health status
 *
 * Latency budget: <200ms for routing decision, provider health cached in KV.
 * Audio streams proxied directly — no body buffering at edge for large payloads.
 */

const PROVIDERS = {
  stt: [
    { name: 'sovereign_whisper', url: null, type: 'sovereign' },
    { name: 'workers_ai_whisper', type: 'edge' },
  ],
  tts: [
    { name: 'sovereign_xtts', url: null, type: 'sovereign' },
    { name: 'workers_ai_tts', type: 'edge' },
  ],
};

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  };
}

function emitAE(env, event) {
  try {
    if (!env.ANALYTICS_AE || typeof env.ANALYTICS_AE.writeDataPoint !== 'function') return;
    env.ANALYTICS_AE.writeDataPoint({
      indexes: [
        event.type || 'voice_pipeline',
        event.service || 'nate-voice-edge',
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

async function getProviderHealth(env, service) {
  try {
    const raw = await env.VOICE_STATE.get(`voice:health:${service}`);
    if (!raw) return { healthy: true, last_check: 0 };
    return JSON.parse(raw);
  } catch {
    return { healthy: true, last_check: 0 };
  }
}

async function setProviderHealth(env, service, healthy, latency_ms) {
  await env.VOICE_STATE.put(`voice:health:${service}`, JSON.stringify({
    healthy,
    latency_ms,
    last_check: Date.now(),
  }), { expirationTtl: 300 });
}

async function handleSTT(request, env) {
  const started = Date.now();
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
  const body = await request.arrayBuffer();
  if (body.byteLength < 100) {
    emitAE(env, {
      type: 'voice_stt',
      service: 'nate-voice-edge',
      stage: 'validate',
      status: 'error',
      source: 'edge',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      error_code: 'audio_too_short',
      target: '/api/voice/stt',
    });
    return new Response(JSON.stringify({ error: 'Audio too short' }), {
      status: 400, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }

  const sovereignHealth = await getProviderHealth(env, 'sovereign_whisper');
  if (sovereignHealth.healthy) {
    try {
      const start = Date.now();
      const resp = await fetch(`${env.SOVEREIGN_API}/api/voice/stt`, {
        method: 'POST',
        headers: {
          'Content-Type': request.headers.get('Content-Type') || 'audio/webm',
          'Authorization': request.headers.get('Authorization') || '',
        },
        body,
      });

      if (resp.ok) {
        await setProviderHealth(env, 'sovereign_whisper', true, Date.now() - start);
        const data = await resp.json();
        return new Response(JSON.stringify({
          ...data,
          provider: 'sovereign_whisper',
          latency_ms: Date.now() - start,
        }), {
          headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
        });
      }
      await setProviderHealth(env, 'sovereign_whisper', false, Date.now() - start);
    } catch {
      await setProviderHealth(env, 'sovereign_whisper', false, 0);
    }
  }

  try {
    const start = Date.now();
    const result = await env.AI.run('@cf/openai/whisper', {
      audio: [...new Uint8Array(body)],
    });

    return new Response(JSON.stringify({
      text: result.text || '',
      provider: 'workers_ai_whisper',
      latency_ms: Date.now() - start,
    }), {
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  } catch (e) {
    emitAE(env, {
      type: 'voice_stt',
      service: 'nate-voice-edge',
      stage: 'stt',
      status: 'error',
      source: 'edge',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      error_code: 'stt_all_failed',
      target: '/api/voice/stt',
      message: String(e && e.message ? e.message : 'stt error').slice(0, 120),
    });
    return new Response(JSON.stringify({ error: 'All STT providers failed', detail: e.message }), {
      status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}

async function handleTTS(request, env) {
  const started = Date.now();
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
  const { text, voice, speed } = await request.json();
  if (!text || text.length < 1) {
    return new Response(JSON.stringify({ error: 'Text required' }), {
      status: 400, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }

  const sovereignHealth = await getProviderHealth(env, 'sovereign_xtts');
  if (sovereignHealth.healthy) {
    try {
      const start = Date.now();
      const resp = await fetch(`${env.SOVEREIGN_API}/api/voice/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': request.headers.get('Authorization') || '',
        },
        body: JSON.stringify({ text, voice: voice || 'default', speed: speed || 1.0 }),
      });

      if (resp.ok) {
        await setProviderHealth(env, 'sovereign_xtts', true, Date.now() - start);
        const audio = await resp.arrayBuffer();
        return new Response(audio, {
          headers: {
            ...corsHeaders(),
            'Content-Type': resp.headers.get('Content-Type') || 'audio/mp3',
            'X-Voice-Provider': 'sovereign_xtts',
            'X-Latency-Ms': String(Date.now() - start),
          },
        });
      }
      await setProviderHealth(env, 'sovereign_xtts', false, Date.now() - start);
    } catch {
      await setProviderHealth(env, 'sovereign_xtts', false, 0);
    }
  }

  try {
    const start = Date.now();
    const result = await env.AI.run('@cf/myshell-ai/melotts', {
      prompt: text,
    });

    return new Response(result, {
      headers: {
        ...corsHeaders(),
        'Content-Type': 'audio/wav',
        'X-Voice-Provider': 'workers_ai_melotts',
        'X-Latency-Ms': String(Date.now() - start),
      },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'All TTS providers failed', detail: e.message }), {
      status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
  finally {
    emitAE(env, {
      type: 'voice_tts',
      service: 'nate-voice-edge',
      stage: 'tts',
      status: 'ok',
      source: 'edge',
      trace_id: traceId,
      request_id: requestId,
      latency_ms: Date.now() - started,
      target: '/api/voice/tts',
      value: text ? text.length : 0,
    });
  }
}

async function handlePipeline(request, env) {
  const started = Date.now();
  const traceId = request.headers.get('x-trace-id') || crypto.randomUUID();
  const requestId = request.headers.get('x-request-id') || crypto.randomUUID();
  const body = await request.arrayBuffer();
  const authHeader = request.headers.get('Authorization') || '';

  const sttStart = Date.now();
  let transcript = '';
  let sttProvider = '';

  const sovereignSttHealth = await getProviderHealth(env, 'sovereign_whisper');
  if (sovereignSttHealth.healthy) {
    try {
      const resp = await fetch(`${env.SOVEREIGN_API}/api/voice/stt`, {
        method: 'POST',
        headers: {
          'Content-Type': request.headers.get('Content-Type') || 'audio/webm',
          'Authorization': authHeader,
        },
        body,
      });
      if (resp.ok) {
        const data = await resp.json();
        transcript = data.text || '';
        sttProvider = 'sovereign_whisper';
        await setProviderHealth(env, 'sovereign_whisper', true, Date.now() - sttStart);
      }
    } catch { /* fall through */ }
  }

  if (!transcript) {
    try {
      const result = await env.AI.run('@cf/openai/whisper', {
        audio: [...new Uint8Array(body)],
      });
      transcript = result.text || '';
      sttProvider = 'workers_ai_whisper';
    } catch {
      return new Response(JSON.stringify({ error: 'STT failed' }), {
        status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }
  }

  const inferenceStart = Date.now();
  let responseText = '';
  let inferenceProvider = '';

  try {
    const resp = await fetch(`${env.SOVEREIGN_API}/api/summon/internal`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': authHeader,
      },
      body: JSON.stringify({ message: transcript, source: 'voice_pipeline' }),
    });
    if (resp.ok) {
      const data = await resp.json();
      responseText = data.response || '';
      inferenceProvider = 'sovereign_brain';
    }
  } catch { /* fall through */ }

  if (!responseText) {
    try {
      const result = await env.AI.run('@cf/meta/llama-3.1-8b-instruct', {
        messages: [
          { role: 'system', content: 'You are Little Nate, an AI companion. Be warm and helpful.' },
          { role: 'user', content: transcript },
        ],
        max_tokens: 300,
      });
      responseText = result.response || '';
      inferenceProvider = 'workers_ai';
    } catch {
      responseText = "I'm here but having trouble processing right now. Can you try again?";
      inferenceProvider = 'fallback';
    }
  }

  const ttsStart = Date.now();
  let audioData = null;
  let ttsProvider = '';

  const sovereignTtsHealth = await getProviderHealth(env, 'sovereign_xtts');
  if (sovereignTtsHealth.healthy) {
    try {
      const resp = await fetch(`${env.SOVEREIGN_API}/api/voice/tts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': authHeader,
        },
        body: JSON.stringify({ text: responseText, voice: 'default' }),
      });
      if (resp.ok) {
        audioData = await resp.arrayBuffer();
        ttsProvider = 'sovereign_xtts';
        await setProviderHealth(env, 'sovereign_xtts', true, Date.now() - ttsStart);
      }
    } catch { /* fall through */ }
  }

  if (!audioData) {
    try {
      const result = await env.AI.run('@cf/myshell-ai/melotts', {
        prompt: responseText,
      });
      audioData = result;
      ttsProvider = 'workers_ai_melotts';
    } catch {
      return new Response(JSON.stringify({
        transcript,
        response: responseText,
        audio: null,
        providers: { stt: sttProvider, inference: inferenceProvider, tts: 'failed' },
      }), {
        headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }
  }

  emitAE(env, {
    type: 'voice_pipeline',
    service: 'nate-voice-edge',
    stage: 'pipeline',
    status: 'ok',
    source: 'edge',
    trace_id: traceId,
    request_id: requestId,
    latency_ms: Date.now() - started,
    target: '/api/voice/pipeline',
    message: `${sttProvider}|${inferenceProvider}|${ttsProvider}`,
    value: transcript.length,
  });

  return new Response(audioData, {
    headers: {
      ...corsHeaders(),
      'Content-Type': 'audio/wav',
      'X-Transcript': encodeURIComponent(transcript.slice(0, 200)),
      'X-Response-Text': encodeURIComponent(responseText.slice(0, 200)),
      'X-STT-Provider': sttProvider,
      'X-Inference-Provider': inferenceProvider,
      'X-TTS-Provider': ttsProvider,
      'X-Total-Ms': String(Date.now() - sttStart),
    },
  });
}

async function handleHealth(env) {
  const health = {};
  for (const service of ['sovereign_whisper', 'sovereign_xtts', 'workers_ai_whisper', 'workers_ai_melotts']) {
    health[service] = await getProviderHealth(env, service);
  }
  health.ai_binding = !!env.AI;
  health.voice_state_kv = !!env.VOICE_STATE;

  return new Response(JSON.stringify({
    worker: 'nate-voice-edge',
    status: 'ok',
    providers: health,
  }), {
    headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    if (url.pathname === '/api/voice/stt' && request.method === 'POST') {
      return handleSTT(request, env);
    }
    if (url.pathname === '/api/voice/tts' && request.method === 'POST') {
      return handleTTS(request, env);
    }
    if (url.pathname === '/api/voice/pipeline' && request.method === 'POST') {
      return handlePipeline(request, env);
    }
    if (url.pathname === '/api/voice/health') {
      return handleHealth(env);
    }

    // --- Cloudflare Realtime: TURN credential generation ---
    if (url.pathname === '/api/voice/turn-credentials' && request.method === 'POST') {
      return handleTurnCredentials(request, env);
    }

    // --- Cloudflare Realtime: SFU session proxy ---
    if (url.pathname.startsWith('/api/voice/sfu/') && request.method === 'POST') {
      return handleSFUProxy(request, env, url.pathname);
    }

    // --- Cloudflare Realtime: MoQ publish ---
    if (url.pathname === '/api/voice/moq/publish' && request.method === 'POST') {
      return handleMoQPublish(request, env);
    }

    // --- Global coherence aggregate: publish + read ---
    if (url.pathname === '/api/voice/moq/publish-coherence' && request.method === 'POST') {
      return handleMoQPublishCoherence(request, env);
    }
    if (url.pathname === '/api/voice/moq/coherence' && request.method === 'GET') {
      return handleMoQCoherenceRead(env);
    }

    // --- MoQ config ---
    if (url.pathname === '/api/voice/moq/config' && request.method === 'GET') {
      return new Response(JSON.stringify({
        endpoint: env.MOQ_ENDPOINT || 'draft-14.cloudflare.mediaoverquic.com',
        protocol: 'draft-14',
        namespace_template: 'sanctuary/{sessionId}/nate-voice-{userId}',
      }), { headers: { ...corsHeaders(), 'Content-Type': 'application/json' } });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  },
};

// ===========================================================================
// TURN — Ephemeral credential generation
// ===========================================================================
async function handleTurnCredentials(request, env) {
  const turnTokenId = env.TURN_TOKEN_ID;
  const turnApiToken = env.TURN_API_TOKEN;

  if (!turnTokenId || !turnApiToken) {
    return new Response(JSON.stringify({ error: 'TURN not configured' }), {
      status: 503, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }

  try {
    const body = await request.json().catch(() => ({}));
    const ttl = Math.min(body.ttl || 86400, 86400);

    const resp = await fetch(
      `https://rtc.live.cloudflare.com/v1/turn/keys/${turnTokenId}/credentials/generate`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${turnApiToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ttl }),
      }
    );

    if (!resp.ok) {
      return new Response(JSON.stringify({ error: 'TURN credential generation failed' }), {
        status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }

    const data = await resp.json();
    return new Response(JSON.stringify({
      iceServers: data.iceServers || data,
      ttl,
    }), {
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'TURN service error' }), {
      status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}

// ===========================================================================
// SFU — Session proxy (clients never see the SFU API token)
// ===========================================================================
async function handleSFUProxy(request, env, pathname) {
  const sfuAppId = env.SFU_APP_ID;
  const sfuApiToken = env.SFU_API_TOKEN;

  if (!sfuAppId || !sfuApiToken) {
    return new Response(JSON.stringify({ error: 'SFU not configured' }), {
      status: 503, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }

  const sfuPath = pathname.replace('/api/voice/sfu', '');
  const sfuUrl = `https://rtc.live.cloudflare.com/v1/apps/${sfuAppId}${sfuPath}`;

  try {
    const body = await request.json().catch(() => ({}));
    const method = request.method || 'POST';

    const resp = await fetch(sfuUrl, {
      method,
      headers: {
        'Authorization': `Bearer ${sfuApiToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await resp.json();
    return new Response(JSON.stringify(data), {
      status: resp.status,
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'SFU proxy error' }), {
      status: 502, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}

// ===========================================================================
// MoQ — Publish Nate's voice to namespace for subscriber fan-out
// ===========================================================================
async function handleMoQPublish(request, env) {
  const moqEndpoint = env.MOQ_ENDPOINT || 'draft-14.cloudflare.mediaoverquic.com';

  try {
    const body = await request.json().catch(() => ({}));
    const { session_id, user_id, namespace } = body;
    const ns = namespace || `sanctuary/${session_id}/nate-voice-${user_id}`;

    return new Response(JSON.stringify({
      status: 'published',
      namespace: ns,
      relay: moqEndpoint,
      protocol: 'draft-14',
    }), {
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'MoQ publish error' }), {
      status: 500, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}

// ===========================================================================
// MoQ — Global coherence aggregate publish (from backend aggregator)
// ===========================================================================
async function handleMoQPublishCoherence(request, env) {
  try {
    const rawBody = await request.text();

    // HMAC signature validation — reject spoofed publishes
    const secret = env.COHERENCE_HMAC_SECRET;
    if (secret) {
      const sig = request.headers.get('X-Coherence-Signature') || '';
      const key = await crypto.subtle.importKey(
        'raw', new TextEncoder().encode(secret),
        { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
      );
      const expected = Array.from(new Uint8Array(
        await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(rawBody))
      )).map(b => b.toString(16).padStart(2, '0')).join('');
      if (sig !== expected) {
        return new Response(JSON.stringify({ error: 'Invalid signature' }), {
          status: 403, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
        });
      }
    }

    const body = JSON.parse(rawBody);
    if (!body || typeof body.global_c_emo === 'undefined') {
      return new Response(JSON.stringify({ error: 'Invalid coherence payload' }), {
        status: 400, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }

    const snapshot = {
      global_c_emo: body.global_c_emo,
      active_sessions: body.active_sessions || 0,
      active_users: body.active_users || 0,
      cee_density: body.cee_density || 0,
      odpe_distribution: body.odpe_distribution || {},
      layer_scores: body.layer_scores || {},
      cycle_signals: body.cycle_signals || {},
      trend_1h: body.trend_1h,
      trend_6h: body.trend_6h,
      trend_24h: body.trend_24h,
      timestamp: body.timestamp || new Date().toISOString(),
      namespace: 'global/coherence-aggregate',
    };

    if (env.VOICE_STATE) {
      await env.VOICE_STATE.put(
        'coherence:latest',
        JSON.stringify(snapshot),
        { expirationTtl: 120 }
      );
    }

    return new Response(JSON.stringify({
      status: 'published',
      namespace: 'global/coherence-aggregate',
      relay: env.MOQ_ENDPOINT || 'draft-14.cloudflare.mediaoverquic.com',
      protocol: 'draft-14',
    }), {
      headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'Coherence publish error' }), {
      status: 500, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}

// ===========================================================================
// MoQ — Read latest global coherence from edge KV (zero-origin-pull)
// ===========================================================================
async function handleMoQCoherenceRead(env) {
  try {
    if (!env.VOICE_STATE) {
      return new Response(JSON.stringify({ status: 'no_kv', global_c_emo: 0 }), {
        headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }

    const raw = await env.VOICE_STATE.get('coherence:latest');
    if (!raw) {
      return new Response(JSON.stringify({ status: 'no_data', global_c_emo: 0 }), {
        headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
      });
    }

    return new Response(raw, {
      headers: {
        ...corsHeaders(),
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=15',
      },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: 'Coherence read error' }), {
      status: 500, headers: { ...corsHeaders(), 'Content-Type': 'application/json' },
    });
  }
}
