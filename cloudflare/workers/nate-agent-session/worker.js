/**
 * nate-agent-session — Durable Object for edge-native Sovereign IDE staging.
 *
 * Each admin user gets a session-scoped Durable Object that handles:
 *   - Staging proposed diffs (proposed → accepted → executing → completed)
 *   - Per-file accept/revoke governance
 *   - Immutable audit trail
 *   - R2 plan artifact storage
 *
 * Routes (on the DO):
 *   POST /stage          — Stage a proposed plan with per-file diffs
 *   POST /accept         — Accept a plan or specific file
 *   POST /revoke         — Revoke a plan or specific file
 *   GET  /history        — Audit trail for this session
 *   GET  /pending        — All pending (un-decided) staged diffs
 *   POST /execute        — Notify VPS to execute accepted changes
 *
 * Routes (on the Worker):
 *   POST /api/edge/agent/session — Proxy to user's Durable Object
 *   GET  /api/edge/agent/health  — Worker health
 */

const ALLOWED_ORIGINS = new Set([
  'https://app.sovereignsanctuary.net',
  'https://coach.sovereignsanctuary.net',
  'https://command.sovereignsanctuary.net',
  'https://api.sovereignsanctuary.net',
]);
let _agentOrigin = '';

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': ALLOWED_ORIGINS.has(_agentOrigin) ? _agentOrigin : '',
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
        event.type || 'agent_session',
        event.service || 'nate-agent-session',
        event.stage || 'request',
        event.status || 'ok',
        event.environment || 'production',
        event.source || 'edge',
        '', '',
      ],
      blobs: [
        event.event_id || crypto.randomUUID(),
        event.trace_id || '',
        event.plan_id || '',
        event.actor || '',
        '', '', '', event.message || '',
      ],
      doubles: [
        Number(event.ts_ms || Date.now()),
        Number(event.latency_ms || 0),
        Number(event.value || 0),
        Number(event.count || 1),
        0,
      ],
    });
  } catch { /* best-effort */ }
}

async function extractAndValidateToken(request, env) {
  const auth = request.headers.get('Authorization') || '';
  if (!auth.startsWith('Bearer ')) return null;
  const token = auth.slice(7);

  const kvKey = `auth:session:${token.slice(0, 16)}`;
  try {
    const cached = await env.AUTH_CACHE.get(kvKey);
    if (cached) {
      const data = JSON.parse(cached);
      if (data.expires_at && Date.now() > data.expires_at) return null;
      if (data.role !== 'ADMIN') return null;
      return data;
    }
  } catch { /* fall through */ }

  try {
    const resp = await fetch(`${env.SOVEREIGN_API}/api/auth/validate`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data.role !== 'ADMIN') return null;
    return data;
  } catch {
    return null;
  }
}

export class SovereignAgentSession {
  constructor(state, env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request) {
    _agentOrigin = request.headers.get('Origin') || '';
    const url = new URL(request.url);
    const path = url.pathname;

    try {
      switch (path) {
        case '/stage': return await this.handleStage(request);
        case '/accept': return await this.handleAccept(request);
        case '/revoke': return await this.handleRevoke(request);
        case '/history': return await this.handleHistory();
        case '/pending': return await this.handlePending();
        case '/execute': return await this.handleExecute(request);
        default:
          return new Response(JSON.stringify({ error: 'Unknown route' }), {
            status: 404, headers: corsHeaders(),
          });
      }
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e) }), {
        status: 500, headers: corsHeaders(),
      });
    }
  }

  async handleStage(request) {
    const { planId, mode, files, content, actor } = await request.json();
    if (!planId || !content) {
      return new Response(JSON.stringify({ error: 'planId and content required' }), {
        status: 400, headers: corsHeaders(),
      });
    }

    const staged = (await this.state.storage.get('staged')) || {};
    staged[planId] = {
      planId,
      mode: mode || 'plan',
      files: files || [],
      fileDecisions: {},
      status: 'proposed',
      stagedAt: Date.now(),
      actor: actor || 'admin',
    };
    await this.state.storage.put('staged', staged);

    if (this.env.PLAN_STORE) {
      try {
        await this.env.PLAN_STORE.put(`cli-plans/${planId}.md`, content);
      } catch { /* R2 non-fatal */ }
    }

    await this._appendAudit(planId, 'stage', actor || 'admin', {
      mode, fileCount: (files || []).length,
    });

    return new Response(JSON.stringify({
      staged: true, planId, fileCount: (files || []).length,
    }), { headers: corsHeaders() });
  }

  async handleAccept(request) {
    const { planId, filePath, actor } = await request.json();
    if (!planId) {
      return new Response(JSON.stringify({ error: 'planId required' }), {
        status: 400, headers: corsHeaders(),
      });
    }

    const staged = (await this.state.storage.get('staged')) || {};
    const plan = staged[planId];
    if (!plan) {
      return new Response(JSON.stringify({ error: 'Plan not found' }), {
        status: 404, headers: corsHeaders(),
      });
    }

    if (filePath) {
      plan.fileDecisions[filePath] = {
        decision: 'accepted', decidedBy: actor || 'admin', decidedAt: Date.now(),
      };
      await this._appendAudit(planId, 'accept_file', actor || 'admin', { filePath });
    } else {
      plan.status = 'accepted';
      (plan.files || []).forEach(f => {
        plan.fileDecisions[f.path] = {
          decision: 'accepted', decidedBy: actor || 'admin', decidedAt: Date.now(),
        };
      });
      await this._appendAudit(planId, 'accept_plan', actor || 'admin', {
        fileCount: (plan.files || []).length,
      });
    }

    staged[planId] = plan;
    await this.state.storage.put('staged', staged);

    return new Response(JSON.stringify({
      accepted: true, planId, filePath: filePath || null,
      status: plan.status,
    }), { headers: corsHeaders() });
  }

  async handleRevoke(request) {
    const { planId, filePath, actor } = await request.json();
    if (!planId) {
      return new Response(JSON.stringify({ error: 'planId required' }), {
        status: 400, headers: corsHeaders(),
      });
    }

    const staged = (await this.state.storage.get('staged')) || {};
    const plan = staged[planId];
    if (!plan) {
      return new Response(JSON.stringify({ error: 'Plan not found' }), {
        status: 404, headers: corsHeaders(),
      });
    }

    if (filePath) {
      plan.fileDecisions[filePath] = {
        decision: 'revoked', decidedBy: actor || 'admin', decidedAt: Date.now(),
      };
      await this._appendAudit(planId, 'revoke_file', actor || 'admin', { filePath });
    } else {
      plan.status = 'revoked';
      await this._appendAudit(planId, 'revoke_plan', actor || 'admin', {});
    }

    staged[planId] = plan;
    await this.state.storage.put('staged', staged);

    return new Response(JSON.stringify({
      revoked: true, planId, filePath: filePath || null,
    }), { headers: corsHeaders() });
  }

  async handleHistory() {
    const trail = (await this.state.storage.get('auditTrail')) || [];
    return new Response(JSON.stringify({ trail }), { headers: corsHeaders() });
  }

  async handlePending() {
    const staged = (await this.state.storage.get('staged')) || {};
    const pending = Object.values(staged).filter(p => p.status === 'proposed');
    return new Response(JSON.stringify({ pending }), { headers: corsHeaders() });
  }

  async handleExecute(request) {
    const { planId, actor } = await request.json();
    if (!planId) {
      return new Response(JSON.stringify({ error: 'planId required' }), {
        status: 400, headers: corsHeaders(),
      });
    }

    const staged = (await this.state.storage.get('staged')) || {};
    const plan = staged[planId];
    if (!plan) {
      return new Response(JSON.stringify({ error: 'Plan not found' }), {
        status: 404, headers: corsHeaders(),
      });
    }

    if (plan.status !== 'accepted') {
      return new Response(JSON.stringify({ error: 'Plan must be accepted before execution' }), {
        status: 400, headers: corsHeaders(),
      });
    }

    const acceptedFiles = Object.entries(plan.fileDecisions || {})
      .filter(([_, d]) => d.decision === 'accepted')
      .map(([path]) => path);

    plan.status = 'executing';
    staged[planId] = plan;
    await this.state.storage.put('staged', staged);

    try {
      await fetch(`${this.env.SOVEREIGN_API}/api/nate-agent/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: planId,
          accepted_files: acceptedFiles,
          triggered_by: actor || 'admin',
        }),
      });
    } catch { /* VPS notification is best-effort */ }

    await this._appendAudit(planId, 'execute', actor || 'admin', {
      acceptedFiles,
    });

    return new Response(JSON.stringify({
      executing: true, planId, acceptedFiles,
    }), { headers: corsHeaders() });
  }

  async _appendAudit(planId, action, actor, detail) {
    const trail = (await this.state.storage.get('auditTrail')) || [];
    trail.push({
      id: crypto.randomUUID(),
      planId,
      action,
      actor,
      detail,
      timestamp: new Date().toISOString(),
    });
    if (trail.length > 500) trail.splice(0, trail.length - 500);
    await this.state.storage.put('auditTrail', trail);
  }
}

export default {
  async fetch(request, env) {
    _agentOrigin = request.headers.get('Origin') || '';
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const url = new URL(request.url);

    if (url.pathname === '/api/edge/agent/health') {
      return new Response(JSON.stringify({
        worker: 'nate-agent-session',
        status: 'ok',
        durable_objects: true,
        r2: !!env.PLAN_STORE,
      }), { headers: corsHeaders() });
    }

    if (url.pathname.startsWith('/api/edge/agent/session')) {
      const profile = await extractAndValidateToken(request, env);
      if (!profile) {
        emitAE(env, {
          type: 'agent_session', stage: 'auth', status: 'error',
          message: 'Unauthorized',
        });
        return new Response(JSON.stringify({ error: 'Unauthorized' }), {
          status: 401, headers: corsHeaders(),
        });
      }

      const sessionId = env.AGENT_SESSION.idFromName(profile.username || 'admin');
      const stub = env.AGENT_SESSION.get(sessionId);

      const action = url.searchParams.get('action') || url.pathname.split('/').pop();
      const targetPath = ['stage', 'accept', 'revoke', 'history', 'pending', 'execute'].includes(action)
        ? `/${action}`
        : '/pending';

      const doRequest = new Request(`https://do.internal${targetPath}`, {
        method: request.method,
        headers: request.headers,
        body: request.method !== 'GET' ? request.body : undefined,
      });

      const started = Date.now();
      const resp = await stub.fetch(doRequest);
      emitAE(env, {
        type: 'agent_session', stage: action, status: resp.ok ? 'ok' : 'error',
        actor: profile.username, latency_ms: Date.now() - started,
      });

      return new Response(resp.body, {
        status: resp.status,
        headers: corsHeaders(),
      });
    }

    return new Response(JSON.stringify({ error: 'Not found' }), {
      status: 404, headers: corsHeaders(),
    });
  },
};
