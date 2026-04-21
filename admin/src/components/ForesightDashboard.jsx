/**
 * Foresight Engine Dashboard
 * Active predictions, trigger forecast, accuracy metrics,
 * and prediction detail view.
 */

import React, { useState, useEffect } from 'react';
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

const Card = ({ children, style = {}, onClick }) => (
  <div
    onClick={onClick}
    style={{
      background: colors.bgElevated,
      border: `1px solid ${colors.border}`,
      borderRadius: 12,
      padding: 16,
      cursor: onClick ? 'pointer' : 'default',
      transition: onClick ? 'border-color 0.2s' : undefined,
      ...style,
    }}
  >
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

const SectionTitle = ({ children, badge, action }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
    <span style={{ color: colors.textSecondary, fontSize: 11, letterSpacing: 1.5, textTransform: 'uppercase' }}>
      {children}
    </span>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      {badge && <Badge>{badge}</Badge>}
      {action}
    </div>
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
    return new Date(ts).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts;
  }
};

const formatPct = (v) => {
  if (v == null) return '—';
  if (typeof v === 'number') return v <= 1 ? `${(v * 100).toFixed(1)}%` : `${v.toFixed(1)}%`;
  return v;
};

const confidenceColor = (c) => {
  const n = typeof c === 'number' ? (c <= 1 ? c : c / 100) : 0;
  if (n >= 0.8) return colors.green;
  if (n >= 0.5) return colors.orange;
  return colors.red;
};

// =============================================================================
// FORESIGHT DASHBOARD COMPONENT
// =============================================================================

export default function ForesightDashboard() {
  const [predictions, setPredictions] = useState([]);
  const [accuracy, setAccuracy] = useState(null);
  const [selectedPrediction, setSelectedPrediction] = useState(null);

  const [loading, setLoading] = useState({ predictions: true, accuracy: true });
  const [errors, setErrors] = useState({});

  const [forecasting, setForecasting] = useState(false);
  const [forecastResult, setForecastResult] = useState(null);

  const fetchData = async (key, url, setter) => {
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
  };

  const loadAll = () => {
    fetchData('predictions', '/api/foresight/predictions', (d) => setPredictions(Array.isArray(d) ? d : d.predictions || d.items || []));
    fetchData('accuracy', '/api/foresight/accuracy', setAccuracy);
  };

  useEffect(() => { loadAll(); }, []);

  const triggerForecast = async () => {
    setForecasting(true);
    setForecastResult(null);
    setErrors((prev) => ({ ...prev, forecast: null }));
    try {
      const res = await authFetch('/api/foresight/forecast', {
        method: 'POST',
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setForecastResult(data);
      // Refresh predictions after triggering
      fetchData('predictions', '/api/foresight/predictions', (d) => setPredictions(Array.isArray(d) ? d : d.predictions || d.items || []));
    } catch (err) {
      setErrors((prev) => ({ ...prev, forecast: err.message }));
    } finally {
      setForecasting(false);
    }
  };

  return (
    <div style={{ padding: 24, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h1 style={{ color: colors.gold, fontSize: 20, margin: 0, fontFamily: "'Cormorant Garamond', serif" }}>
          🔮 Foresight Engine
        </h1>
        <Button
          variant="purple"
          onClick={triggerForecast}
          disabled={forecasting}
          style={{ padding: '10px 24px' }}
        >
          {forecasting ? '⏳ Generating...' : '🔮 Trigger Forecast'}
        </Button>
      </div>

      {/* Forecast result banner */}
      {forecastResult && (
        <div style={{
          padding: 12, marginBottom: 16, borderRadius: 8,
          background: `${colors.purple}15`, border: `1px solid ${colors.purple}44`,
        }}>
          <div style={{ fontSize: 12, color: colors.purple, fontWeight: 'bold', marginBottom: 4 }}>Forecast Generated</div>
          <div style={{ fontSize: 11, color: colors.textSecondary }}>
            {forecastResult.message || forecastResult.summary || `Generated ${forecastResult.predictions_count || forecastResult.count || 'new'} predictions.`}
          </div>
        </div>
      )}

      {errors.forecast && (
        <div style={{ padding: 12, marginBottom: 16, borderRadius: 8, background: `${colors.red}15`, border: `1px solid ${colors.red}44` }}>
          <div style={{ fontSize: 12, color: colors.red }}>Forecast error: {errors.forecast}</div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: selectedPrediction ? '1fr 1fr' : '2fr 1fr', gap: 20 }}>
        {/* ========== Active Predictions ========== */}
        <Card>
          <SectionTitle badge={`${predictions.length} Active`}>Active Predictions</SectionTitle>

          {loading.predictions ? <Spinner /> : errors.predictions ? (
            <ErrorBox message={errors.predictions} onRetry={() => fetchData('predictions', '/api/foresight/predictions', (d) => setPredictions(Array.isArray(d) ? d : d.predictions || d.items || []))} />
          ) : (
            <div style={{ maxHeight: 500, overflowY: 'auto' }}>
              {predictions.length === 0 && (
                <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 24 }}>
                  No active predictions. Trigger a forecast to generate new ones.
                </div>
              )}
              {predictions.map((pred, i) => {
                const isSelected = selectedPrediction && (selectedPrediction.id === pred.id);
                return (
                  <div
                    key={pred.id || i}
                    onClick={() => setSelectedPrediction(isSelected ? null : pred)}
                    style={{
                      padding: 12, marginBottom: 8, borderRadius: 8, cursor: 'pointer',
                      background: isSelected ? `${colors.purple}15` : colors.bgCard,
                      border: `1px solid ${isSelected ? colors.purple : colors.border}`,
                      transition: 'border-color 0.2s',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                      <div style={{ fontSize: 12, fontWeight: 500, flex: 1, marginRight: 8 }}>
                        {pred.title || pred.description || pred.prediction || `Prediction #${i + 1}`}
                      </div>
                      <Badge color={confidenceColor(pred.confidence)}>
                        {formatPct(pred.confidence)}
                      </Badge>
                    </div>

                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      {pred.time_horizon && (
                        <span style={{ fontSize: 9, color: colors.textSecondary }}>
                          ⏱ {pred.time_horizon}
                        </span>
                      )}
                      {pred.category && <Badge color={colors.cyan}>{pred.category}</Badge>}
                      {pred.status && (
                        <Badge color={pred.status === 'active' ? colors.green : pred.status === 'expired' ? colors.textSecondary : colors.orange}>
                          {pred.status}
                        </Badge>
                      )}
                      <span style={{ fontSize: 9, color: colors.textSecondary, marginLeft: 'auto' }}>
                        {formatTime(pred.created_at || pred.timestamp)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        {/* ========== Detail or Accuracy panel ========== */}
        <div>
          {selectedPrediction ? (
            /* Prediction Detail View */
            <Card style={{ marginBottom: 20 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <SectionTitle>Prediction Detail</SectionTitle>
                <button
                  onClick={() => setSelectedPrediction(null)}
                  style={{ background: 'none', border: 'none', color: colors.textSecondary, cursor: 'pointer', fontSize: 14 }}
                >
                  ✕
                </button>
              </div>

              <div style={{ fontSize: 14, fontWeight: 'bold', color: colors.goldBright, marginBottom: 12 }}>
                {selectedPrediction.title || selectedPrediction.prediction || 'Prediction'}
              </div>

              {selectedPrediction.description && (
                <div style={{ fontSize: 12, color: colors.textSecondary, lineHeight: 1.6, marginBottom: 16 }}>
                  {selectedPrediction.description}
                </div>
              )}

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
                <div style={{ padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>Confidence</div>
                  <div style={{ fontSize: 22, fontWeight: 'bold', color: confidenceColor(selectedPrediction.confidence) }}>
                    {formatPct(selectedPrediction.confidence)}
                  </div>
                  <ProgressBar
                    value={selectedPrediction.confidence <= 1 ? selectedPrediction.confidence * 100 : selectedPrediction.confidence}
                    max={100}
                    color={confidenceColor(selectedPrediction.confidence)}
                  />
                </div>
                <div style={{ padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>Time Horizon</div>
                  <div style={{ fontSize: 18, fontWeight: 'bold', color: colors.cyan }}>
                    {selectedPrediction.time_horizon || '—'}
                  </div>
                </div>
              </div>

              {selectedPrediction.factors && Array.isArray(selectedPrediction.factors) && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Contributing Factors</div>
                  {selectedPrediction.factors.map((f, i) => (
                    <div key={i} style={{ fontSize: 11, padding: '4px 0', borderBottom: `1px solid ${colors.border}` }}>
                      • {typeof f === 'string' ? f : f.name || f.factor || JSON.stringify(f)}
                    </div>
                  ))}
                </div>
              )}

              {selectedPrediction.recommended_actions && Array.isArray(selectedPrediction.recommended_actions) && (
                <div>
                  <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Recommended Actions</div>
                  {selectedPrediction.recommended_actions.map((a, i) => (
                    <div key={i} style={{ fontSize: 11, color: colors.goldBright, padding: '4px 0' }}>
                      → {typeof a === 'string' ? a : a.action || a.text}
                    </div>
                  ))}
                </div>
              )}

              <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 12, fontFamily: 'monospace' }}>
                ID: {selectedPrediction.id || '—'} | Created: {formatTime(selectedPrediction.created_at || selectedPrediction.timestamp)}
              </div>
            </Card>
          ) : null}

          {/* ========== Accuracy Metrics ========== */}
          <Card>
            <SectionTitle>Accuracy Metrics</SectionTitle>

            {loading.accuracy ? <Spinner /> : errors.accuracy ? (
              <ErrorBox message={errors.accuracy} onRetry={() => fetchData('accuracy', '/api/foresight/accuracy', setAccuracy)} />
            ) : accuracy ? (
              <div>
                {/* Overall accuracy */}
                <div style={{ textAlign: 'center', marginBottom: 20 }}>
                  <div style={{ fontSize: 36, fontWeight: 'bold', color: colors.green }}>
                    {formatPct(accuracy.overall || accuracy.accuracy || accuracy.overall_accuracy)}
                  </div>
                  <div style={{ fontSize: 10, color: colors.textSecondary }}>Overall Accuracy</div>
                </div>

                {/* Breakdown */}
                {accuracy.by_category && typeof accuracy.by_category === 'object' && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 10, color: colors.textSecondary, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>By Category</div>
                    {Object.entries(accuracy.by_category).map(([cat, val]) => (
                      <div key={cat} style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 4 }}>
                          <span>{cat}</span>
                          <span style={{ color: confidenceColor(val) }}>{formatPct(val)}</span>
                        </div>
                        <ProgressBar value={typeof val === 'number' ? (val <= 1 ? val * 100 : val) : 0} max={100} color={confidenceColor(val)} />
                      </div>
                    ))}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  {accuracy.total_predictions != null && (
                    <div style={{ textAlign: 'center', padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 20, fontWeight: 'bold', color: colors.cyan }}>{accuracy.total_predictions.toLocaleString()}</div>
                      <div style={{ fontSize: 9, color: colors.textSecondary }}>Total Predictions</div>
                    </div>
                  )}
                  {accuracy.correct != null && (
                    <div style={{ textAlign: 'center', padding: 12, background: colors.bgCard, borderRadius: 8 }}>
                      <div style={{ fontSize: 20, fontWeight: 'bold', color: colors.green }}>{accuracy.correct.toLocaleString()}</div>
                      <div style={{ fontSize: 9, color: colors.textSecondary }}>Correct</div>
                    </div>
                  )}
                </div>

                {accuracy.last_updated && (
                  <div style={{ fontSize: 9, color: colors.textSecondary, marginTop: 12, textAlign: 'center' }}>
                    Last updated: {formatTime(accuracy.last_updated)}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: colors.textSecondary, textAlign: 'center', padding: 16 }}>No accuracy data available.</div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
