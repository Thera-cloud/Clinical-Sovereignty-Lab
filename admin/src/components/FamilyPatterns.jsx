/**
 * Transgenerational Pattern Analysis
 * Family analysis, emotional themes, coping mechanisms,
 * trigger patterns, and legacy vault consent.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { authFetch } from '../apiClient';

// =============================================================================
// DESIGN SYSTEM
// =============================================================================

const colors = {
  bgVoid: '#050505',
  bgChamber: '#0A0A0A',
  bgElevated: '#111111',
  bgCard: '#1A1A1A',
  border: '#252525',
  gold: '#C9A962',
  goldBright: '#E8D5A3',
  goldDim: '#8B7355',
  cyan: '#4ECDC4',
  purple: '#9D4EDD',
  red: '#EF4444',
  green: '#00FF88',
  orange: '#FF9500',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

// =============================================================================
// SHARED COMPONENTS
// =============================================================================

const Card = ({ children, style = {} }) => (
  <div style={{
    background: colors.bgElevated,
    border: `1px solid ${colors.border}`,
    borderRadius: 12,
    padding: 16,
    ...style,
  }}>
    {children}
  </div>
);

const Badge = ({ children, color = colors.gold }) => (
  <span style={{
    background: `${color}22`,
    color,
    padding: '3px 8px',
    borderRadius: 10,
    fontSize: 10,
    fontWeight: 'bold',
    whiteSpace: 'nowrap',
  }}>
    {children}
  </span>
);

const SectionTitle = ({ children, badge }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
    <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase' }}>
      {children}
    </span>
    {badge && <Badge>{badge}</Badge>}
  </div>
);

const Button = ({ children, onClick, variant = 'default', style = {}, disabled = false }) => {
  const variants = {
    default: { bg: colors.bgCard, border: colors.border, color: colors.textPrimary },
    primary: { bg: `${colors.gold}22`, border: colors.gold, color: colors.gold },
    danger: { bg: `${colors.red}22`, border: colors.red, color: colors.red },
    success: { bg: `${colors.green}22`, border: colors.green, color: colors.green },
    purple: { bg: `${colors.purple}22`, border: colors.purple, color: colors.purple },
  };
  const v = variants[variant] || variants.default;
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: v.bg,
        border: `1px solid ${v.border}`,
        color: v.color,
        padding: '8px 16px',
        borderRadius: 8,
        fontSize: 12,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...style,
      }}
    >
      {children}
    </button>
  );
};

const ProgressBar = ({ value, max, color = colors.cyan }) => (
  <div style={{ background: colors.bgCard, borderRadius: 4, height: 8, overflow: 'hidden' }}>
    <div style={{
      width: `${Math.min((value / max) * 100, 100)}%`,
      height: '100%',
      background: color,
      borderRadius: 4,
      transition: 'width 0.3s ease',
    }} />
  </div>
);

const Spinner = () => (
  <div style={{ textAlign: 'center', padding: 32 }}>
    <div style={{ fontSize: 24, marginBottom: 8 }}>⏳</div>
    <div style={{ fontSize: 11, color: colors.textSecondary }}>Loading...</div>
  </div>
);

const ErrorBox = ({ message, onRetry }) => (
  <div style={{ padding: 16, background: `${colors.red}15`, border: `1px solid ${colors.red}44`, borderRadius: 8, textAlign: 'center' }}>
    <div style={{ fontSize: 12, color: colors.red, marginBottom: 8 }}>{message}</div>
    {onRetry && <Button variant="danger" onClick={onRetry} style={{ fontSize: 10 }}>Retry</Button>}
  </div>
);

const formatTime = (ts) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
};

const formatPct = (v) => {
  if (v == null) return '—';
  if (typeof v === 'number') return v <= 1 ? `${(v * 100).toFixed(0)}%` : `${v.toFixed(0)}%`;
  return v;
};

// UUID validation (loose)
const isValidUUID = (s) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s);

// =============================================================================
// FAMILY PATTERNS COMPONENT
// =============================================================================

export default function FamilyPatterns() {
  const [familyId, setFamilyId] = useState('');
  const [submittedId, setSubmittedId] = useState(null);

  const [analysis, setAnalysis] = useState(null);
  const [themes, setThemes] = useState(null);
  const [coping, setCoping] = useState(null);
  const [triggers, setTriggers] = useState(null);
  const [consent, setConsent] = useState(null);

  const [loading, setLoading] = useState({});
  const [errors, setErrors] = useState({});

  const fetchData = useCallback(async (key, url, setter) => {
    setLoading((prev) => ({ ...prev, [key]: true }));
    setErrors((prev) => ({ ...prev, [key]: null }));
    try {
      const res = await authFetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setter(data);
    } catch (err) {
      setErrors((prev) => ({ ...prev, [key]: err.message }));
    } finally {
      setLoading((prev) => ({ ...prev, [key]: false }));
    }
  }, []);

  const loadFamilyData = useCallback((id) => {
    if (!id) return;
    fetchData('analysis', `/api/patterns/family/${id}`, setAnalysis);
    fetchData('themes', `/api/patterns/themes/${id}`, setThemes);
    fetchData('coping', `/api/patterns/coping/${id}`, setCoping);
    fetchData('triggers', `/api/patterns/triggers/${id}`, setTriggers);
    fetchData('consent', `/api/legacy-vault/consent/${id}`, setConsent);
  }, [fetchData]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const cleanId = familyId.trim();
    if (!cleanId) return;
    setSubmittedId(cleanId);
    loadFamilyData(cleanId);
  };

  // Reload when submittedId changes
  useEffect(() => {
    if (submittedId) {
      loadFamilyData(submittedId);
    }
  }, [submittedId, loadFamilyData]);

  const hasData = submittedId != null;

  return (
    <div style={{ padding: 24, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <h1 style={{ color: colors.gold, fontSize: 20, margin: '0 0 24px 0', fontFamily: "'Cormorant Garamond', serif" }}>
        🧬 Transgenerational Pattern Analysis
      </h1>

      {/* ========== Family Selector ========== */}
      <Card style={{ marginBottom: 24 }}>
        <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontSize: 10, color: colors.textSecondary, display: 'block', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 }}>
              Family ID
            </label>
            <input
              type="text"
              value={familyId}
              onChange={(e) => setFamilyId(e.target.value)}
              placeholder="Enter family UUID (e.g. 550e8400-e29b-41d4-a716-446655440000)"
              style={{
                width: '100%', padding: '10px 14px', background: colors.bgCard,
                border: `1px solid ${familyId && !isValidUUID(familyId) ? colors.orange : colors.border}`,
                borderRadius: 8, color: colors.textPrimary, fontSize: 13, fontFamily: 'monospace',
                boxSizing: 'border-box',
              }}
            />
            {familyId && !isValidUUID(familyId) && (
              <div style={{ fontSize: 9, color: colors.orange, marginTop: 4 }}>UUID format expected but any ID will be attempted</div>
            )}
          </div>
          <Button variant="primary" disabled={!familyId.trim()} style={{ padding: '10px 24px', whiteSpace: 'nowrap' }}>
            🔍 Analyze Family
          </Button>
        </form>

        {submittedId && (
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 10, color: colors.textSecondary }}>Viewing:</span>
            <Badge color={colors.purple}>{submittedId}</Badge>
            {consent && (
              <Badge color={consent.granted || consent.consent_given || consent.status === 'granted' ? colors.green : colors.red}>
                {consent.granted || consent.consent_given || consent.status === 'granted' ? '✓ Vault Consent Given' : '✗ No Vault Consent'}
              </Badge>
            )}
          </div>
        )}
      </Card>

      {!hasData ? (
        <div style={{ textAlign: 'center', padding: 64 }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🧬</div>
          <div style={{ fontSize: 14, color: colors.textSecondary }}>Enter a Family ID to view transgenerational patterns</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
          {/* ========== Full Analysis ========== */}
          <Card style={{ gridColumn: '1 / -1' }}>
            <SectionTitle>Full Family Analysis</SectionTitle>

            {loading.analysis ? <Spinner /> : errors.analysis ? (
              <ErrorBox message={errors.analysis} onRetry={() => fetchData('analysis', `/api/patterns/family/${submittedId}`, setAnalysis)} />
            ) : analysis ? (
              <div>
                {/* Summary metrics */}
                <div style={{ display: 'flex', gap: 16, marginBottom: 16 }}>
                  {analysis.member_count != null && (
                    <div style={{ textAlign: 'center', flex: 1, padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.cyan }}>{analysis.member_count}</div>
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>Family Members</div>
                    </div>
                  )}
                  {analysis.generation_count != null && (
                    <div style={{ textAlign: 'center', flex: 1, padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.purple }}>{analysis.generation_count}</div>
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>Generations</div>
                    </div>
                  )}
                  {analysis.coherence_score != null && (
                    <div style={{ textAlign: 'center', flex: 1, padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 24, fontWeight: 'bold', color: colors.gold }}>
                        {typeof analysis.coherence_score === 'number' ? analysis.coherence_score.toFixed(2) : analysis.coherence_score}
                      </div>
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>Family Coherence</div>
                    </div>
                  )}
                  {analysis.risk_level != null && (
                    <div style={{ textAlign: 'center', flex: 1, padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 20, fontWeight: 'bold', color: analysis.risk_level === 'high' ? colors.red : analysis.risk_level === 'medium' ? colors.orange : colors.green }}>
                        {(analysis.risk_level || '').toUpperCase()}
                      </div>
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>Risk Level</div>
                    </div>
                  )}
                </div>

                {/* Summary text */}
                {(analysis.summary || analysis.description) && (
                  <div style={{ fontSize: 12, color: colors.textSecondary, lineHeight: 1.6, padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                    {analysis.summary || analysis.description}
                  </div>
                )}

                {/* Members list */}
                {Array.isArray(analysis.members) && analysis.members.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Members</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {analysis.members.map((m, i) => (
                        <div key={m.id || i} style={{ padding: '8px 12px', background: colors.bgCard, borderRadius: 8, border: `1px solid ${colors.border}` }}>
                          <div style={{ fontSize: 12, fontWeight: 500 }}>{m.name || m.user_id || `Member ${i + 1}`}</div>
                          <div style={{ fontSize: 9, color: colors.textSecondary }}>
                            {m.role && <span>{m.role}</span>}
                            {m.generation && <span> • Gen {m.generation}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No analysis data.</div>
            )}
          </Card>

          {/* ========== Emotional Theme Correlation ========== */}
          <Card>
            <SectionTitle badge={themes && Array.isArray(themes.themes || themes) ? `${(themes.themes || themes).length} Themes` : null}>
              Emotional Theme Correlation
            </SectionTitle>

            {loading.themes ? <Spinner /> : errors.themes ? (
              <ErrorBox message={errors.themes} onRetry={() => fetchData('themes', `/api/patterns/themes/${submittedId}`, setThemes)} />
            ) : themes ? (
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                {(Array.isArray(themes) ? themes : themes.themes || themes.correlations || []).map((theme, i) => (
                  <div key={theme.id || theme.name || i} style={{ padding: '10px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: colors.goldBright }}>
                        {theme.name || theme.theme || theme.label || `Theme ${i + 1}`}
                      </span>
                      {theme.correlation != null && (
                        <span style={{ fontSize: 11, fontWeight: 'bold', color: theme.correlation >= 0.7 ? colors.red : theme.correlation >= 0.4 ? colors.orange : colors.green }}>
                          r={typeof theme.correlation === 'number' ? theme.correlation.toFixed(2) : theme.correlation}
                        </span>
                      )}
                    </div>
                    {theme.strength != null && (
                      <ProgressBar
                        value={typeof theme.strength === 'number' ? (theme.strength <= 1 ? theme.strength * 100 : theme.strength) : 50}
                        max={100}
                        color={colors.purple}
                      />
                    )}
                    {theme.description && (
                      <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4 }}>{theme.description}</div>
                    )}
                    {Array.isArray(theme.members_affected) && (
                      <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 2 }}>
                        Affects: {theme.members_affected.join(', ')}
                      </div>
                    )}
                  </div>
                ))}
                {(Array.isArray(themes) ? themes : themes.themes || []).length === 0 && (
                  <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No themes identified.</div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No theme data.</div>
            )}
          </Card>

          {/* ========== Coping Mechanism Inheritance ========== */}
          <Card>
            <SectionTitle>Coping Mechanism Inheritance</SectionTitle>

            {loading.coping ? <Spinner /> : errors.coping ? (
              <ErrorBox message={errors.coping} onRetry={() => fetchData('coping', `/api/patterns/coping/${submittedId}`, setCoping)} />
            ) : coping ? (
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                {(Array.isArray(coping) ? coping : coping.mechanisms || coping.patterns || []).map((mech, i) => (
                  <div key={mech.id || mech.name || i} style={{
                    padding: 10, marginBottom: 8, borderRadius: 8,
                    background: colors.bgCard, border: `1px solid ${colors.border}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 500 }}>
                        {mech.name || mech.mechanism || mech.label || `Mechanism ${i + 1}`}
                      </span>
                      {mech.type && (
                        <Badge color={mech.type === 'adaptive' ? colors.green : mech.type === 'maladaptive' ? colors.red : colors.orange}>
                          {mech.type}
                        </Badge>
                      )}
                    </div>
                    {mech.inheritance_path && (
                      <div style={{ fontSize: 10, color: colors.cyan, fontFamily: 'monospace' }}>
                        {Array.isArray(mech.inheritance_path) ? mech.inheritance_path.join(' → ') : mech.inheritance_path}
                      </div>
                    )}
                    {mech.prevalence != null && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 2 }}>
                          <span style={{ color: colors.textSecondary }}>Prevalence</span>
                          <span>{formatPct(mech.prevalence)}</span>
                        </div>
                        <ProgressBar
                          value={typeof mech.prevalence === 'number' ? (mech.prevalence <= 1 ? mech.prevalence * 100 : mech.prevalence) : 0}
                          max={100}
                          color={mech.type === 'maladaptive' ? colors.red : colors.green}
                        />
                      </div>
                    )}
                    {mech.description && (
                      <div style={{ fontSize: 10, color: colors.textSecondary, marginTop: 4 }}>{mech.description}</div>
                    )}
                  </div>
                ))}
                {(Array.isArray(coping) ? coping : coping.mechanisms || []).length === 0 && (
                  <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No coping mechanisms identified.</div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No coping data.</div>
            )}
          </Card>

          {/* ========== Trigger Pattern Mapping ========== */}
          <Card>
            <SectionTitle>Trigger Pattern Mapping</SectionTitle>

            {loading.triggers ? <Spinner /> : errors.triggers ? (
              <ErrorBox message={errors.triggers} onRetry={() => fetchData('triggers', `/api/patterns/triggers/${submittedId}`, setTriggers)} />
            ) : triggers ? (
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                {(Array.isArray(triggers) ? triggers : triggers.triggers || triggers.patterns || []).map((trigger, i) => (
                  <div key={trigger.id || trigger.name || i} style={{ padding: '10px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: 12, fontWeight: 500, color: colors.red }}>
                        {trigger.name || trigger.trigger || trigger.pattern || `Trigger ${i + 1}`}
                      </span>
                      {trigger.severity && (
                        <Badge color={trigger.severity === 'high' ? colors.red : trigger.severity === 'medium' ? colors.orange : colors.gold}>
                          {trigger.severity}
                        </Badge>
                      )}
                    </div>
                    {trigger.description && (
                      <div style={{ fontSize: 10, color: colors.textSecondary, marginBottom: 4 }}>{trigger.description}</div>
                    )}
                    {trigger.frequency != null && (
                      <div style={{ fontSize: 10, color: colors.textSecondary }}>
                        Frequency: <span style={{ color: colors.orange }}>{trigger.frequency}</span>
                      </div>
                    )}
                    {Array.isArray(trigger.affected_members) && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                        {trigger.affected_members.map((m, j) => (
                          <Badge key={j} color={colors.textSecondary}>{typeof m === 'string' ? m : m.name || m.id}</Badge>
                        ))}
                      </div>
                    )}
                    {trigger.cascade_risk != null && (
                      <div style={{ marginTop: 4 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, marginBottom: 2 }}>
                          <span style={{ color: colors.textSecondary }}>Cascade Risk</span>
                          <span style={{ color: colors.red }}>{formatPct(trigger.cascade_risk)}</span>
                        </div>
                        <ProgressBar
                          value={typeof trigger.cascade_risk === 'number' ? (trigger.cascade_risk <= 1 ? trigger.cascade_risk * 100 : trigger.cascade_risk) : 0}
                          max={100}
                          color={colors.red}
                        />
                      </div>
                    )}
                  </div>
                ))}
                {(Array.isArray(triggers) ? triggers : triggers.triggers || []).length === 0 && (
                  <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No triggers identified.</div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No trigger data.</div>
            )}
          </Card>

          {/* ========== Legacy Vault Consent Status ========== */}
          <Card>
            <SectionTitle>Legacy Vault Consent</SectionTitle>

            {loading.consent ? <Spinner /> : errors.consent ? (
              <ErrorBox message={errors.consent} onRetry={() => fetchData('consent', `/api/legacy-vault/consent/${submittedId}`, setConsent)} />
            ) : consent ? (
              <div>
                <div style={{ textAlign: 'center', marginBottom: 16 }}>
                  <div style={{ fontSize: 48, marginBottom: 8 }}>
                    {consent.granted || consent.consent_given || consent.status === 'granted' ? '🔓' : '🔒'}
                  </div>
                  <div style={{
                    fontSize: 16, fontWeight: 'bold',
                    color: consent.granted || consent.consent_given || consent.status === 'granted' ? colors.green : colors.red,
                  }}>
                    {consent.granted || consent.consent_given || consent.status === 'granted' ? 'Consent Granted' : 'No Consent'}
                  </div>
                </div>

                {consent.granted_at && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Granted At</span>
                    <span>{formatTime(consent.granted_at)}</span>
                  </div>
                )}
                {consent.granted_by && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Granted By</span>
                    <span>{consent.granted_by}</span>
                  </div>
                )}
                {consent.scope && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Scope</span>
                    <span>{Array.isArray(consent.scope) ? consent.scope.join(', ') : consent.scope}</span>
                  </div>
                )}
                {consent.expires_at && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '8px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <span style={{ color: colors.textSecondary }}>Expires</span>
                    <span>{formatTime(consent.expires_at)}</span>
                  </div>
                )}

                {consent.members && Array.isArray(consent.members) && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Member Consent Status</div>
                    {consent.members.map((m, i) => (
                      <div key={m.id || i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: `1px solid ${colors.border}` }}>
                        <span style={{ fontSize: 11 }}>{m.name || m.user_id || `Member ${i + 1}`}</span>
                        <Badge color={m.consented ? colors.green : colors.red}>
                          {m.consented ? '✓ Yes' : '✗ No'}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No consent data.</div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
