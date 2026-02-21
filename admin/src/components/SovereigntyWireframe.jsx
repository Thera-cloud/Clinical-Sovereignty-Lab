/**
 * SovereigntyWireframe — 8-Layer Architecture Visualization
 * Now pulls live system health from backend APIs.
 */

import React, { useState, useEffect, useCallback } from 'react';

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
  purple: '#9D4EDD',
  purpleDim: 'rgba(157, 78, 221, 0.15)',
  blue: '#4A90D9',
  textPrimary: '#FFFFFF',
  textSecondary: '#888888',
};

const API = process.env.REACT_APP_API_BASE_URL || '';

async function apiFetch(path) {
  try {
    const headers = {};
    const token = sessionStorage.getItem('token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API}${path}`, { headers });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

const LAYERS = [
  { id: 'L1', name: 'Physical Transport', sub: 'ZEFCP', color: '#4ECDC4', endpoint: '/api/zefcp/health' },
  { id: 'L2', name: 'Command', sub: 'Sovereign Mind', color: '#FFD700', endpoint: '/health' },
  { id: 'L3', name: 'Swarm Intelligence', sub: 'Fibres + Wisdom Mesh', color: '#9D4EDD', endpoint: '/api/mesh/health' },
  { id: 'L4', name: 'Security', sub: 'Sovereign Immunity', color: '#FF3B3B', endpoint: '/api/immunity/status' },
  { id: 'L5', name: 'Coherence', sub: '5-Layer Measurement', color: '#00FF88', endpoint: '/api/coherence/pulse' },
  { id: 'L6', name: 'Foresight', sub: 'Prediction Engine', color: '#FF9500', endpoint: '/api/foresight/status' },
  { id: 'L7', name: 'External', sub: 'SkyEye + Marketing', color: '#4A90D9', endpoint: '/api/skyeye/pulse' },
  { id: 'L8', name: 'Swarm Solidarity', sub: 'Quakete Protocol', color: '#E8D5A3', endpoint: '/api/quakete/status' },
];

export default function SovereigntyWireframe() {
  const [selectedLayer, setSelectedLayer] = useState(null);
  const [layerHealth, setLayerHealth] = useState({});
  const [layerDetail, setLayerDetail] = useState(null);

  // Fetch health status for all layers on mount
  useEffect(() => {
    LAYERS.forEach(async (layer) => {
      const data = await apiFetch(layer.endpoint);
      setLayerHealth(prev => ({
        ...prev,
        [layer.id]: data ? 'online' : 'offline',
      }));
    });
  }, []);

  // Fetch detail when a layer is selected
  const selectLayer = useCallback(async (layerId) => {
    if (layerId === selectedLayer) {
      setSelectedLayer(null);
      setLayerDetail(null);
      return;
    }
    setSelectedLayer(layerId);
    const layer = LAYERS.find(l => l.id === layerId);
    if (layer) {
      const data = await apiFetch(layer.endpoint);
      setLayerDetail(data);
    }
  }, [selectedLayer]);

  const statusColor = (id) => {
    const s = layerHealth[id];
    return s === 'online' ? colors.green : s === 'offline' ? colors.red : colors.textSecondary;
  };

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ color: colors.gold, marginBottom: 8 }}>8-Layer Architecture</h2>
      <div style={{ color: colors.textSecondary, fontSize: 11, marginBottom: 24 }}>
        Live system status — click any layer to inspect
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {LAYERS.map((layer) => (
          <div
            key={layer.id}
            onClick={() => selectLayer(layer.id)}
            style={{
              padding: 16,
              borderRadius: 8,
              cursor: 'pointer',
              background: selectedLayer === layer.id ? `${layer.color}22` : colors.bgCard,
              border: `1px solid ${selectedLayer === layer.id ? layer.color : colors.border}`,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{
                display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                background: statusColor(layer.id),
              }} />
              <span style={{ color: layer.color, fontWeight: 'bold', marginRight: 8 }}>
                {layer.id}
              </span>
              <span style={{ color: colors.textPrimary }}>{layer.name}</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ color: colors.textSecondary, fontSize: 12 }}>{layer.sub}</span>
              <span style={{
                fontSize: 9, padding: '2px 8px', borderRadius: 4,
                background: layerHealth[layer.id] === 'online' ? colors.greenDim : colors.redDim,
                color: layerHealth[layer.id] === 'online' ? colors.green : colors.red,
              }}>
                {layerHealth[layer.id] || 'checking...'}
              </span>
            </div>
          </div>
        ))}
      </div>
      {selectedLayer && (
        <div style={{ marginTop: 16, padding: 16, background: colors.bgElevated, borderRadius: 8 }}>
          <div style={{ color: colors.gold, fontWeight: 'bold', marginBottom: 8 }}>
            {selectedLayer}: {LAYERS.find(l => l.id === selectedLayer)?.name}
          </div>
          {layerDetail ? (
            <pre style={{
              color: colors.textSecondary, fontSize: 11, fontFamily: 'monospace',
              background: colors.bgCard, padding: 12, borderRadius: 6,
              maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap',
            }}>
              {JSON.stringify(layerDetail, null, 2)}
            </pre>
          ) : (
            <div style={{ color: colors.textSecondary, fontSize: 12 }}>
              Layer not responding or not initialized.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
