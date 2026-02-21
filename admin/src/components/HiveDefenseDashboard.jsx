/**
 * HiveDefenseDashboard — Phase 8 Hive Defense Protocol monitoring dashboard.
 * Fetches from /api/hive-defense/* endpoints (all admin-protected).
 */

import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = process.env.REACT_APP_API_BASE_URL || window.location.origin.replace(':3000', ':8000');

const colors = {
  bgDark: '#0A0A0A',
  bgCard: '#111111',
  bgElevated: '#1A1A1A',
  border: '#252525',
  gold: '#FFD700',
  goldDim: 'rgba(255, 215, 0, 0.2)',
  red: '#FF3B3B',
  redDim: 'rgba(255, 59, 59, 0.15)',
  green: '#00FF88',
  greenDim: 'rgba(0, 255, 136, 0.1)',
  orange: '#FF9500',
  orangeDim: 'rgba(255, 149, 0, 0.15)',
  cyan: '#00D4FF',
  cyanDim: 'rgba(0, 212, 255, 0.1)',
  purple: '#A78BFA',
  purpleDim: 'rgba(167, 139, 250, 0.12)',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
  textDim: '#555555',
};

const defconColors = {
  5: colors.green,
  4: colors.cyan,
  3: colors.orange,
  2: '#FF8C00',
  1: colors.red,
};

function Card({ children, style = {} }) {
  return (
    <div style={{
      background: colors.bgCard,
      border: `1px solid ${colors.border}`,
      borderRadius: 12,
      padding: 16,
      ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase', marginBottom: 12 }}>
      {children}
    </div>
  );
}

function StatBox({ label, value, color = colors.textPrimary }) {
  return (
    <div style={{ textAlign: 'center', padding: '12px 8px' }}>
      <div style={{ fontFamily: 'monospace', fontSize: 24, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4, textTransform: 'uppercase', letterSpacing: 1 }}>{label}</div>
    </div>
  );
}

function Badge({ text, color = colors.green }) {
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 10,
      fontWeight: 600,
      textTransform: 'uppercase',
      background: `${color}22`,
      color,
    }}>
      {text}
    </span>
  );
}

function MiniTable({ headers, rows }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
      <thead>
        <tr>
          {headers.map((h, i) => (
            <th key={i} style={{ textAlign: 'left', padding: '6px 8px', color: colors.textDim, fontWeight: 600, fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: `1px solid ${colors.border}` }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr><td colSpan={headers.length} style={{ padding: 20, textAlign: 'center', color: colors.textDim }}>No data</td></tr>
        ) : rows.map((row, ri) => (
          <tr key={ri}>
            {row.map((cell, ci) => (
              <td key={ci} style={{ padding: '6px 8px', color: colors.textSecondary, borderBottom: `1px solid ${colors.border}15` }}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

async function apiFetch(path) {
  try {
    const headers = {};
    const token = sessionStorage.getItem('token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`${API_BASE}${path}`, { credentials: 'include', headers });
    if (!resp.ok) throw new Error(`${resp.status}`);
    return await resp.json();
  } catch (e) {
    console.warn(`Hive API error ${path}:`, e);
    return null;
  }
}

export default function HiveDefenseDashboard() {
  const [overview, setOverview] = useState(null);
  const [defcon, setDefcon] = useState(null);
  const [mirror, setMirror] = useState(null);
  const [gate, setGate] = useState(null);
  const [curiosity, setCuriosity] = useState(null);
  const [heartbeat, setHeartbeat] = useState(null);
  const [drift, setDrift] = useState(null);
  const [containment, setContainment] = useState(null);
  const [quarantine, setQuarantine] = useState(null);
  const [ghosts, setGhosts] = useState(null);
  const [helix, setHelix] = useState(null);
  const [projections, setProjections] = useState(null);
  const [conservation, setConservation] = useState(null);
  const [attackers, setAttackers] = useState(null);
  const [forensics, setForensics] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const refresh = useCallback(async () => {
    const [ov, dc, ms, gt, cu, hb, dr, ct, qu, gh, hx, pj, cn, at, fo] = await Promise.all([
      apiFetch('/api/hive-defense/overview'),
      apiFetch('/api/hive-defense/defcon'),
      apiFetch('/api/hive-defense/mirror/stats'),
      apiFetch('/api/hive-defense/gate/metrics'),
      apiFetch('/api/hive-defense/curiosity/entities'),
      apiFetch('/api/hive-defense/heartbeat/registry'),
      apiFetch('/api/hive-defense/drift/scores?min_magnitude=0.1'),
      apiFetch('/api/hive-defense/containment/zones'),
      apiFetch('/api/hive-defense/quarantine/active'),
      apiFetch('/api/hive-defense/ghost/missions'),
      apiFetch('/api/hive-defense/helix/state'),
      apiFetch('/api/hive-defense/projection/deployments'),
      apiFetch('/api/hive-defense/conservation/latest'),
      apiFetch('/api/hive-defense/attackers/profiles'),
      apiFetch('/api/hive-defense/forensics/recent?limit=20'),
    ]);
    setOverview(ov); setDefcon(dc); setMirror(ms); setGate(gt);
    setCuriosity(cu); setHeartbeat(hb); setDrift(dr); setContainment(ct);
    setQuarantine(qu); setGhosts(gh); setHelix(hx); setProjections(pj);
    setConservation(cn); setAttackers(at); setForensics(fo);
    setLastUpdate(new Date().toLocaleTimeString());
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [refresh]);

  const defconLevel = defcon?.level || overview?.defcon_level || 5;
  const defconColor = defconColors[defconLevel] || colors.green;

  return (
    <div style={{ padding: 24 }}>
      {/* HEADER */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, fontFamily: 'Georgia, serif' }}>
            Hive <span style={{ color: colors.red }}>Defense</span> Protocol
          </h1>
          <div style={{ fontSize: 11, color: colors.textDim, marginTop: 4, letterSpacing: 1 }}>
            Patent-Pending &mdash; Claims 30-56 &bull; Phase 8 Security System
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            padding: '6px 16px',
            borderRadius: 20,
            fontFamily: 'monospace',
            fontSize: 13,
            fontWeight: 700,
            letterSpacing: 1,
            background: `${defconColor}22`,
            border: `1px solid ${defconColor}55`,
            color: defconColor,
          }}>
            DEFCON {defconLevel}
          </div>
          <button onClick={refresh} style={{
            background: colors.bgElevated,
            border: `1px solid ${colors.border}`,
            borderRadius: 8,
            padding: '6px 14px',
            color: colors.textSecondary,
            fontSize: 12,
            cursor: 'pointer',
          }}>
            Refresh
          </button>
          {lastUpdate && <span style={{ fontSize: 11, color: colors.textDim, fontFamily: 'monospace' }}>{lastUpdate}</span>}
        </div>
      </div>

      {/* OVERVIEW STRIP */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12, marginBottom: 24 }}>
        <Card><StatBox label="DEFCON" value={defconLevel} color={defconColor} /></Card>
        <Card><StatBox label="Services" value={overview?.services_loaded ?? '--'} color={colors.cyan} /></Card>
        <Card><StatBox label="Vectors" value={overview?.attack_vectors_defended ?? '--'} color={colors.purple} /></Card>
        <Card><StatBox label="Three Cord" value={overview?.three_cord_coverage ?? '--'} color={colors.gold} /></Card>
        <Card><StatBox label="Forensic" value={overview?.counts?.forensic_records ?? 0} color={colors.cyan} /></Card>
        <Card><StatBox label="Attackers" value={overview?.counts?.attacker_profiles ?? 0} color={colors.red} /></Card>
      </div>

      {/* ROW 1: DEFCON + MIRROR + GATE */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>DEFCON Controller</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Level" value={defconLevel} color={defconColor} />
            <StatBox label="HB Interval" value={`${defcon?.heartbeat_interval ?? '--'}s`} color={colors.cyan} />
          </div>
          <div style={{ fontSize: 11, color: colors.textSecondary, marginTop: 8 }}>
            <div><strong>Trigger:</strong> <span style={{ fontFamily: 'monospace' }}>{defcon?.trigger_reason || 'None'}</span></div>
            <div><strong>Mirror:</strong> <span style={{ fontFamily: 'monospace' }}>{defcon?.mirror_mode || 'standard'}</span></div>
          </div>
        </Card>

        <Card>
          <SectionTitle>Mirror Shell</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Processed" value={mirror?.total_processed ?? 0} color={colors.cyan} />
            <StatBox label="Passed" value={mirror?.passed ?? 0} color={colors.green} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Absorbed" value={mirror?.absorbed ?? 0} color={colors.orange} />
            <StatBox label="Contained" value={mirror?.contained ?? 0} color={colors.red} />
          </div>
        </Card>

        <Card>
          <SectionTitle>Coherence Gate</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Evaluated" value={gate?.total ?? 0} color={colors.cyan} />
            <StatBox label="Passed" value={gate?.passed ?? 0} color={colors.green} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Suspicious" value={gate?.suspicious ?? 0} color={colors.orange} />
            <StatBox label="Absorbed" value={gate?.absorbed ?? 0} color={colors.red} />
          </div>
        </Card>
      </div>

      {/* ROW 2: CURIOSITY + HEARTBEAT + DRIFT */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>Curiosity Protocol ({(curiosity?.entities || []).length})</SectionTitle>
          <MiniTable
            headers={['Entity', 'Level', 'Events']}
            rows={(curiosity?.entities || []).map(e => [
              <span style={{ fontFamily: 'monospace' }}>{(e.entity_id || '').substring(0, 8)}...</span>,
              <Badge text={e.level} color={e.level === 'alarm' ? colors.red : e.level === 'concern' ? colors.orange : colors.cyan} />,
              e.events_count,
            ])}
          />
        </Card>

        <Card>
          <SectionTitle>Heartbeat Registry</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Registered" value={heartbeat?.registered_entities ?? 0} color={colors.green} />
            <StatBox label="Silent" value={heartbeat?.silent_entities ?? 0} color={colors.red} />
          </div>
          {heartbeat?.silent_ids?.length > 0 && (
            <div style={{ fontSize: 10, color: colors.red, marginTop: 8 }}>
              Silent: {heartbeat.silent_ids.map(id => id.substring(0, 8)).join(', ')}
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle>Drift Scores ({(drift?.scores || []).length})</SectionTitle>
          <MiniTable
            headers={['Entity', 'Combined', 'Data', 'Comm']}
            rows={(drift?.scores || []).map(s => [
              <span style={{ fontFamily: 'monospace' }}>{(s.entity_id || '').substring(0, 8)}...</span>,
              <Badge text={s.combined?.toFixed(3)} color={s.combined >= 0.5 ? colors.red : s.combined >= 0.3 ? colors.orange : colors.cyan} />,
              <span style={{ fontFamily: 'monospace' }}>{(s.data_access || 0).toFixed(2)}</span>,
              <span style={{ fontFamily: 'monospace' }}>{(s.communication || 0).toFixed(2)}</span>,
            ])}
          />
        </Card>
      </div>

      {/* ROW 3: CONTAINMENT + QUARANTINE + GHOST */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>Containment Zones ({(containment?.zones || []).length})</SectionTitle>
          <MiniTable
            headers={['Zone', 'Status']}
            rows={(containment?.zones || []).map(z => {
              const id = typeof z === 'string' ? z : (z.id || z.zone_id || JSON.stringify(z));
              return [<span style={{ fontFamily: 'monospace' }}>{String(id).substring(0, 12)}</span>, <Badge text="Active" color={colors.red} />];
            })}
          />
        </Card>

        <Card>
          <SectionTitle>Active Quarantines ({(quarantine?.quarantines || []).length})</SectionTitle>
          <MiniTable
            headers={['Fibre', 'HB', 'Ring', 'Trail']}
            rows={(quarantine?.quarantines || []).map(q => [
              <span style={{ fontFamily: 'monospace' }}>{(q.fibre_id || '').substring(0, 8)}</span>,
              <Badge text={q.heartbeat_ok ? 'OK' : 'FAIL'} color={q.heartbeat_ok ? colors.green : colors.red} />,
              <Badge text={q.ring_ok ? 'OK' : 'FAIL'} color={q.ring_ok ? colors.green : colors.red} />,
              <Badge text={q.trail_ok ? 'OK' : 'FAIL'} color={q.trail_ok ? colors.green : colors.red} />,
            ])}
          />
        </Card>

        <Card>
          <SectionTitle>Ghost Missions ({(ghosts?.missions || []).length})</SectionTitle>
          <MiniTable
            headers={['Zone', 'Ghosts', 'Status']}
            rows={(ghosts?.missions || []).map(m => [
              <span style={{ fontFamily: 'monospace' }}>{(m.zone || '').substring(0, 10)}</span>,
              m.ghosts,
              <Badge text={m.status} color={m.status === 'active' ? colors.green : colors.orange} />,
            ])}
          />
        </Card>
      </div>

      {/* ROW 4: HELIX + PROJECTIONS + CONSERVATION */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>Trinity Helix State</SectionTitle>
          <div style={{ fontFamily: 'monospace', fontSize: 16, color: colors.purple, letterSpacing: 2, marginBottom: 12 }}>
            {(helix?.current_sequence || []).join(' ') || '--'}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <StatBox label="Rotations" value={helix?.rotation_count ?? 0} color={colors.purple} />
            <StatBox label="Interval (ms)" value={(helix?.rotation_interval_ms ?? 0).toFixed(0)} color={colors.cyan} />
          </div>
        </Card>

        <Card>
          <SectionTitle>Projected Helix ({(projections?.deployments || []).length})</SectionTitle>
          <MiniTable
            headers={['ID', 'Status', 'Accuracy', 'Intercepts']}
            rows={(projections?.deployments || []).map(d => [
              <span style={{ fontFamily: 'monospace' }}>{(d.id || '').substring(0, 8)}</span>,
              <Badge text={d.status} color={d.status === 'active' ? colors.red : colors.orange} />,
              `${((d.mirror_accuracy || 0) * 100).toFixed(1)}%`,
              d.commands_intercepted || 0,
            ])}
          />
        </Card>

        <Card>
          <SectionTitle>Conservation Ledger</SectionTitle>
          {conservation?.entry ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <StatBox label="Energy" value={(conservation.entry.total_energy || 0).toFixed(2)} color={colors.gold} />
                <StatBox label="Valid" value={conservation.entry.is_valid ? 'YES' : 'NO'} color={conservation.entry.is_valid ? colors.green : colors.red} />
              </div>
              <div style={{ fontSize: 11, color: colors.textSecondary, marginTop: 8 }}>
                <div><strong>Violations:</strong> {conservation.entry.violations || 0}</div>
              </div>
            </>
          ) : (
            <div style={{ textAlign: 'center', padding: 20, color: colors.textDim }}>No ledger data</div>
          )}
        </Card>
      </div>

      {/* ROW 5: HIVE INSPECT + EMAIL MONITOR */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>Inspect Content</SectionTitle>
          <InspectPanel />
        </Card>
        <Card>
          <SectionTitle>Email Hive Monitor</SectionTitle>
          <EmailMonitorPanel />
        </Card>
      </div>

      {/* ROW 6: ATTACKERS + FORENSICS */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <Card>
          <SectionTitle>Attacker Profiles ({(attackers?.profiles || []).length})</SectionTitle>
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            <MiniTable
              headers={['Profile', 'Sophistication', 'Timezone', 'First Seen']}
              rows={(attackers?.profiles || []).map(p => [
                <span style={{ fontFamily: 'monospace' }}>{(p.id || '').substring(0, 8)}</span>,
                p.sophistication || 'unknown',
                p.timezone || '--',
                p.first_seen ? new Date(p.first_seen).toLocaleDateString() : '--',
              ])}
            />
          </div>
        </Card>

        <Card>
          <SectionTitle>Forensic Log (Recent)</SectionTitle>
          <div style={{ maxHeight: 300, overflowY: 'auto' }}>
            <MiniTable
              headers={['Type', 'Source', 'Target', 'Time']}
              rows={(forensics?.records || []).map(r => [
                <Badge text={r.event_type} color={colors.purple} />,
                <span style={{ fontFamily: 'monospace' }}>{(r.source || '--').substring(0, 10)}</span>,
                <span style={{ fontFamily: 'monospace' }}>{(r.target || '--').substring(0, 10)}</span>,
                r.timestamp ? new Date(r.timestamp).toLocaleTimeString() : '--',
              ])}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════
   INSPECT PANEL — Submit text / email / URL for Hive analysis
   ═══════════════════════════════════════════════════════════════ */
function InspectPanel() {
  const [contentType, setContentType] = useState('email');
  const [fromAddr, setFromAddr] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [rawHeaders, setRawHeaders] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!body.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const resp = await fetch(`${API_BASE}/api/hive-defense/v4/inspect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content: body, content_type: contentType, from_address: fromAddr, subject, raw_headers: rawHeaders, attachment_names: [] }),
      });
      if (resp.ok) setResult(await resp.json());
      else setResult({ error: `HTTP ${resp.status}` });
    } catch (e) { setResult({ error: e.message }); }
    setLoading(false);
  };

  const vc = (v) => v === 'MALICIOUS' ? colors.red : v === 'SUSPICIOUS' ? colors.orange : colors.green;
  const iStyle = { width: '100%', padding: '6px 10px', fontSize: 12, background: colors.bgElevated, border: `1px solid ${colors.border}`, borderRadius: 6, color: colors.textPrimary, marginBottom: 8, outline: 'none', boxSizing: 'border-box' };

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {['email', 'url', 'text'].map(t => (
          <button key={t} onClick={() => setContentType(t)} style={{ padding: '4px 12px', fontSize: 10, borderRadius: 4, cursor: 'pointer', border: `1px solid ${contentType === t ? colors.gold : colors.border}`, background: contentType === t ? `${colors.gold}22` : colors.bgElevated, color: contentType === t ? colors.gold : colors.textSecondary, textTransform: 'uppercase', fontWeight: 600, letterSpacing: 0.5 }}>{t}</button>
        ))}
      </div>
      {contentType === 'email' && (<><input placeholder="From: address" value={fromAddr} onChange={e => setFromAddr(e.target.value)} style={iStyle} /><input placeholder="Subject" value={subject} onChange={e => setSubject(e.target.value)} style={iStyle} /></>)}
      <textarea placeholder={contentType === 'url' ? 'Paste URL to inspect...' : contentType === 'email' ? 'Paste email body here...' : 'Paste suspicious text...'} value={body} onChange={e => setBody(e.target.value)} rows={4} style={{ ...iStyle, resize: 'vertical', fontFamily: 'monospace' }} />
      {contentType === 'email' && (<details style={{ marginBottom: 8 }}><summary style={{ fontSize: 10, color: colors.textDim, cursor: 'pointer' }}>Raw headers (optional)</summary><textarea placeholder="Paste raw email headers for SPF/DKIM/DMARC analysis..." value={rawHeaders} onChange={e => setRawHeaders(e.target.value)} rows={3} style={{ ...iStyle, resize: 'vertical', fontFamily: 'monospace', marginTop: 6 }} /></details>)}
      <button onClick={submit} disabled={loading || !body.trim()} style={{ width: '100%', padding: '8px 0', fontSize: 12, fontWeight: 700, borderRadius: 6, cursor: loading ? 'wait' : 'pointer', border: `1px solid ${colors.gold}55`, background: loading ? colors.bgElevated : `${colors.gold}22`, color: loading ? colors.textDim : colors.gold, textTransform: 'uppercase', letterSpacing: 1 }}>{loading ? 'Analyzing...' : 'Run Hive Inspection'}</button>

      {result && !result.error && (
        <div style={{ marginTop: 12, padding: 12, background: colors.bgElevated, borderRadius: 8, border: `1px solid ${colors.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Badge text={result.aggregate_verdict || 'UNKNOWN'} color={vc(result.aggregate_verdict)} />
            <span style={{ fontFamily: 'monospace', fontSize: 20, fontWeight: 700, color: vc(result.aggregate_verdict) }}>{result.aggregate_score ?? '--'}/100</span>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            {Object.entries(result.systems || {}).map(([n, s]) => (
              <div key={n} style={{ padding: '4px 8px', background: colors.bgCard, borderRadius: 4, fontSize: 10 }}><span style={{ color: colors.textDim }}>{n}: </span><Badge text={s.verdict || 'N/A'} color={vc(s.verdict)} /></div>
            ))}
          </div>
          {(result.phishing?.signals || []).length > 0 && (
            <div style={{ maxHeight: 200, overflowY: 'auto' }}>
              {result.phishing.signals.map((s, i) => (
                <div key={i} style={{ padding: '4px 0', borderBottom: `1px solid ${colors.border}15`, fontSize: 11 }}>
                  <span style={{ color: vc(s.severity === 'critical' || s.severity === 'high' ? 'MALICIOUS' : 'SUSPICIOUS') }}>[{s.severity?.toUpperCase()}]</span>{' '}
                  <span style={{ color: colors.textSecondary }}>{s.detail}</span>
                  {s.evidence && <span style={{ fontFamily: 'monospace', fontSize: 10, color: colors.textDim, marginLeft: 6 }}>&mdash; {s.evidence}</span>}
                </div>
              ))}
            </div>
          )}
          {(result.recommendations || []).length > 0 && (
            <div style={{ marginTop: 8, padding: 8, background: `${colors.gold}08`, borderRadius: 6 }}>
              <div style={{ fontSize: 10, color: colors.gold, fontWeight: 600, marginBottom: 4 }}>RECOMMENDATIONS</div>
              {result.recommendations.map((r, i) => (<div key={i} style={{ fontSize: 10, color: colors.textSecondary, padding: '2px 0' }}>&bull; {r}</div>))}
            </div>
          )}
        </div>
      )}
      {result?.error && (<div style={{ marginTop: 8, padding: 8, background: colors.redDim, borderRadius: 6, fontSize: 11, color: colors.red }}>Error: {result.error}</div>)}
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════
   EMAIL MONITOR PANEL — Gmail Hive Monitor status + controls
   ═══════════════════════════════════════════════════════════════ */
function EmailMonitorPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchStatus = useCallback(async () => {
    const data = await apiFetch('/api/hive-defense/v4/email-monitor/status');
    setStatus(data);
  }, []);

  useEffect(() => { fetchStatus(); const iv = setInterval(fetchStatus, 30000); return () => clearInterval(iv); }, [fetchStatus]);

  const toggleMonitor = async () => {
    setLoading(true);
    const action = status?.running ? 'stop' : 'start';
    try { await fetch(`${API_BASE}/api/hive-defense/v4/email-monitor/${action}`, { method: 'POST', credentials: 'include' }); } catch (e) { console.warn('Toggle error:', e); }
    setTimeout(fetchStatus, 1000);
    setLoading(false);
  };

  if (!status) return <div style={{ textAlign: 'center', padding: 20, color: colors.textDim }}>Loading...</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: status.running ? colors.green : colors.red, boxShadow: status.running ? `0 0 6px ${colors.green}` : 'none' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: status.running ? colors.green : colors.red }}>{status.running ? 'MONITORING' : 'STOPPED'}</span>
        </div>
        <button onClick={toggleMonitor} disabled={loading} style={{ padding: '4px 12px', fontSize: 10, borderRadius: 4, cursor: 'pointer', border: `1px solid ${status.running ? colors.red : colors.green}55`, background: `${status.running ? colors.red : colors.green}15`, color: status.running ? colors.red : colors.green, fontWeight: 600 }}>{status.running ? 'Stop' : 'Start'}</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
        <StatBox label="Scanned" value={status.total_scanned || 0} color={colors.cyan} />
        <StatBox label="Threats" value={status.total_threats || 0} color={status.total_threats > 0 ? colors.red : colors.green} />
        <StatBox label="Inboxes" value={(status.monitored_inboxes || []).length} color={colors.purple} />
      </div>
      <div style={{ fontSize: 10, color: colors.textDim, marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>Protected Emails</div>
      {(status.protected_emails || []).map((email, i) => {
        const inbox = (status.monitored_inboxes || []).find(m => m.email === email);
        const mon = !!inbox;
        return (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: `1px solid ${colors.border}15` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: mon && inbox.healthy ? colors.green : mon ? colors.orange : colors.textDim }} />
              <span style={{ fontSize: 11, fontFamily: 'monospace', color: colors.textSecondary }}>{email}</span>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              {mon && (<><span style={{ fontSize: 9, color: colors.textDim }}>{inbox.messages_scanned} scanned</span>{inbox.threats_found > 0 && <Badge text={`${inbox.threats_found} threats`} color={colors.red} />}</>)}
              <Badge text={mon ? inbox.auth_mode : 'no auth'} color={mon ? colors.green : colors.textDim} />
            </div>
          </div>
        );
      })}
      {(status.unmonitored_emails || []).length > 0 && (
        <div style={{ marginTop: 8, padding: 8, background: colors.orangeDim, borderRadius: 6, fontSize: 10 }}>
          <span style={{ color: colors.orange, fontWeight: 600 }}>Setup Needed:</span>{' '}
          <span style={{ color: colors.textSecondary }}>{status.unmonitored_emails.join(', ')} &mdash; configure OAuth2 tokens or Service Account</span>
        </div>
      )}
      {(status.recent_threats || []).length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 10, color: colors.red, fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1 }}>Recent Threats</div>
          <MiniTable headers={['Inbox', 'From', 'Subject', 'Score']} rows={(status.recent_threats || []).slice(-5).reverse().map(t => [
            <span style={{ fontFamily: 'monospace', fontSize: 10 }}>{t.inbox_email?.split('@')[0]}@...</span>,
            <span style={{ fontFamily: 'monospace', fontSize: 10, color: colors.red }}>{(t.from_address || '').substring(0, 20)}</span>,
            <span style={{ fontSize: 10 }}>{(t.subject || '').substring(0, 25)}</span>,
            <Badge text={`${t.score}/100`} color={t.score >= 60 ? colors.red : colors.orange} />,
          ])} />
        </div>
      )}
    </div>
  );
}
