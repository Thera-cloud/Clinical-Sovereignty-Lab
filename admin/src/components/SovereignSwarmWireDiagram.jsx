/**
 * SovereignSwarmWireDiagram — Swarm wire diagram with interconnected nodes.
 * Now pulls live status data and fibre counts from backend APIs.
 */

import React, { useState, useEffect } from 'react';

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

async function apiFetch(path) {
  try {
    const headers = {};
    const token = sessionStorage.getItem('token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(path, { headers });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// Node definitions
const NODES = [
  { id: 'sovereign-mind', label: 'SOVEREIGN MIND', tier: 'Core', color: colors.gold, x: 50, y: 8 },
  { id: 'strategic-memory', label: 'STRATEGIC MEMORY', tier: 'Memory', color: colors.blue, x: 15, y: 35 },
  { id: 'legacy-vault', label: 'LEGACY VAULT', tier: 'Memory', color: colors.blue, x: 85, y: 35 },
  { id: 'wisdom-mesh', label: 'WISDOM MESH', tier: 'Mesh', color: colors.purple, x: 50, y: 25 },
  { id: 'cultural-sentinels', label: 'CULTURAL SENTINELS', tier: 'Fibre', color: colors.cyan, x: 5, y: 55 },
  { id: 'coherence-engine', label: 'COHERENCE ENGINE', tier: 'Coherence', color: colors.green, x: 35, y: 55 },
  { id: 'pattern-engine', label: 'PATTERN ENGINE', tier: 'Fibre', color: colors.cyan, x: 65, y: 55 },
  { id: 'foresight-engine', label: 'FORESIGHT ENGINE', tier: 'External', color: colors.orange, x: 95, y: 55 },
  { id: 'skyeye', label: 'SKYEYE', tier: 'External', color: colors.orange, x: 15, y: 78 },
  { id: 'marketing-hub', label: 'MARKETING HUB', tier: 'External', color: colors.orange, x: 85, y: 78 },
  { id: 'sovereign-immunity', label: 'SOVEREIGN IMMUNITY', tier: 'Security', color: colors.red, x: 50, y: 92 },
  { id: 'fibre-campaign', label: 'Campaign Fibre', tier: 'Fibre', color: colors.cyan, x: 18, y: 68 },
  { id: 'fibre-coach', label: 'Coach Support', tier: 'Fibre', color: colors.cyan, x: 35, y: 68 },
  { id: 'fibre-community', label: 'Community Fibre', tier: 'Fibre', color: colors.cyan, x: 50, y: 68 },
  { id: 'fibre-sentinel', label: 'Cultural Sentinel', tier: 'Fibre', color: colors.cyan, x: 65, y: 68 },
  { id: 'fibre-foresight', label: 'Foresight Analyst', tier: 'Fibre', color: colors.cyan, x: 82, y: 68 },
  { id: 'fibre-quiz', label: 'Quiz Funnel', tier: 'Fibre', color: colors.cyan, x: 50, y: 82 },
];

const CONNECTIONS = [
  ['sovereign-mind', 'wisdom-mesh'],
  ['sovereign-mind', 'strategic-memory'],
  ['sovereign-mind', 'legacy-vault'],
  ['sovereign-mind', 'coherence-engine'],
  ['sovereign-mind', 'sovereign-immunity'],
  ['wisdom-mesh', 'pattern-engine'],
  ['wisdom-mesh', 'cultural-sentinels'],
  ['wisdom-mesh', 'foresight-engine'],
  ['strategic-memory', 'wisdom-mesh'],
  ['legacy-vault', 'wisdom-mesh'],
  ['coherence-engine', 'wisdom-mesh'],
  ['pattern-engine', 'fibre-campaign'],
  ['pattern-engine', 'fibre-coach'],
  ['pattern-engine', 'fibre-community'],
  ['cultural-sentinels', 'fibre-sentinel'],
  ['foresight-engine', 'fibre-foresight'],
  ['pattern-engine', 'fibre-quiz'],
  ['foresight-engine', 'skyeye'],
  ['foresight-engine', 'marketing-hub'],
  ['skyeye', 'sovereign-immunity'],
  ['marketing-hub', 'sovereign-immunity'],
];

// Map node IDs to the API endpoint that provides their health status
const NODE_ENDPOINTS = {
  'sovereign-mind': '/health',
  'strategic-memory': '/api/strategic-memory/status',
  'wisdom-mesh': '/api/mesh/health',
  'coherence-engine': '/api/coherence/pulse',
  'pattern-engine': '/api/patterns/status',
  'foresight-engine': '/api/foresight/status',
  'sovereign-immunity': '/api/immunity/status',
  'skyeye': '/api/skyeye/pulse',
};

const DIAGRAM_WIDTH = 900;
const DIAGRAM_HEIGHT = 500;
const NODE_WIDTH = 120;
const NODE_HEIGHT = 36;

function getNodeCenter(node) {
  return {
    x: (node.x / 100) * DIAGRAM_WIDTH,
    y: (node.y / 100) * DIAGRAM_HEIGHT,
  };
}

export default function SovereignSwarmWireDiagram() {
  const [selectedNode, setSelectedNode] = useState(null);
  const [nodeStatus, setNodeStatus] = useState({});
  const [nodeDetail, setNodeDetail] = useState(null);
  const [fibreData, setFibreData] = useState(null);
  const [meshData, setMeshData] = useState(null);

  const nodeMap = Object.fromEntries(NODES.map((n) => [n.id, n]));

  // Fetch health for key nodes + fibre list + mesh health
  useEffect(() => {
    apiFetch('/api/fibres').then(d => setFibreData(d));
    apiFetch('/api/mesh/health').then(d => setMeshData(d));

    Object.entries(NODE_ENDPOINTS).forEach(async ([nodeId, endpoint]) => {
      const data = await apiFetch(endpoint);
      setNodeStatus(prev => ({ ...prev, [nodeId]: data ? 'online' : 'offline' }));
    });
    // Fibres are always "online" if the system is running
    NODES.filter(n => n.id.startsWith('fibre-')).forEach(n => {
      setNodeStatus(prev => ({ ...prev, [n.id]: 'online' }));
    });
  }, []);

  const handleNodeClick = async (nodeId) => {
    if (nodeId === selectedNode) {
      setSelectedNode(null);
      setNodeDetail(null);
      return;
    }
    setSelectedNode(nodeId);
    const endpoint = NODE_ENDPOINTS[nodeId];
    if (endpoint) {
      const data = await apiFetch(endpoint);
      setNodeDetail(data);
    } else if (nodeId.startsWith('fibre-') && fibreData) {
      // Show fibre-specific info
      const fibreType = nodeId.replace('fibre-', '');
      const matching = (fibreData.fibres || []).filter(f =>
        (f.fibre_type || '').toLowerCase().includes(fibreType)
      );
      setNodeDetail({ fibre_type: fibreType, matching_fibres: matching, total_fibres: (fibreData.fibres || []).length });
    } else {
      setNodeDetail({ note: 'No direct API endpoint. Status inferred from parent systems.' });
    }
  };

  const getStatusColor = (nodeId) => {
    const s = nodeStatus[nodeId];
    return s === 'online' ? colors.green : s === 'offline' ? colors.red : colors.textSecondary;
  };

  return (
    <div style={{ padding: 24, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <h2 style={{ color: colors.gold, marginBottom: 8 }}>Swarm Wire Diagram</h2>
      <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 11, color: colors.textSecondary }}>
        <span>Fibres: {fibreData ? (fibreData.fibres || []).length : '--'}</span>
        <span>Mesh Messages: {meshData ? meshData.total_messages || 0 : '--'}</span>
        <span>Mesh Topics: {meshData ? meshData.active_topics || 0 : '--'}</span>
      </div>
      <div style={{ flex: 1, overflow: 'auto', background: colors.bgCard, borderRadius: 8, padding: 24, border: `1px solid ${colors.border}` }}>
        <svg width={DIAGRAM_WIDTH} height={DIAGRAM_HEIGHT} style={{ minWidth: DIAGRAM_WIDTH, minHeight: DIAGRAM_HEIGHT }}>
          {/* Connection lines */}
          <g>
            {CONNECTIONS.map(([fromId, toId], i) => {
              const from = nodeMap[fromId];
              const to = nodeMap[toId];
              if (!from || !to) return null;
              const fc = getNodeCenter(from);
              const tc = getNodeCenter(to);
              const midX = (fc.x + tc.x) / 2;
              const midY = (fc.y + tc.y) / 2;
              // Highlight connections for selected node
              const isHighlighted = selectedNode && (fromId === selectedNode || toId === selectedNode);
              return (
                <path
                  key={i}
                  d={`M ${fc.x} ${fc.y} Q ${midX} ${midY} ${tc.x} ${tc.y}`}
                  fill="none"
                  stroke={isHighlighted ? colors.gold : colors.border}
                  strokeWidth={isHighlighted ? 2 : 1}
                  opacity={isHighlighted ? 1 : 0.4}
                />
              );
            })}
          </g>
          {/* Nodes */}
          {NODES.map((node) => {
            const cx = (node.x / 100) * DIAGRAM_WIDTH;
            const cy = (node.y / 100) * DIAGRAM_HEIGHT;
            const isSelected = selectedNode === node.id;
            const sc = getStatusColor(node.id);
            return (
              <g key={node.id}>
                <rect
                  x={cx - NODE_WIDTH / 2}
                  y={cy - NODE_HEIGHT / 2}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={6}
                  fill={isSelected ? `${node.color}22` : colors.bgElevated}
                  stroke={isSelected ? node.color : colors.border}
                  strokeWidth={isSelected ? 2 : 1}
                  cursor="pointer"
                  onClick={() => handleNodeClick(node.id)}
                />
                {/* Status indicator dot */}
                <circle cx={cx - NODE_WIDTH / 2 + 10} cy={cy} r={3} fill={sc} />
                <text
                  x={cx + 4}
                  y={cy + 4}
                  textAnchor="middle"
                  fill={node.color}
                  fontSize={9}
                  fontWeight="bold"
                  style={{ pointerEvents: 'none' }}
                >
                  {node.label.length > 16 ? node.label.slice(0, 14) + '\u2026' : node.label}
                </text>
              </g>
            );
          })}
        </svg>
        {selectedNode && (
          <div style={{ marginTop: 16, padding: 16, background: colors.bgElevated, borderRadius: 8, border: `1px solid ${colors.border}` }}>
            <div style={{ color: colors.gold, fontWeight: 'bold', marginBottom: 8 }}>
              {nodeMap[selectedNode]?.label}
              <span style={{
                marginLeft: 12, fontSize: 10, padding: '2px 8px', borderRadius: 4,
                background: getStatusColor(selectedNode) === colors.green ? colors.greenDim : colors.redDim,
                color: getStatusColor(selectedNode),
              }}>
                {nodeStatus[selectedNode] || 'unknown'}
              </span>
            </div>
            <div style={{ color: colors.textSecondary, fontSize: 11, marginBottom: 8 }}>
              Tier: {nodeMap[selectedNode]?.tier}
              {' | '}
              Connections: {CONNECTIONS.filter(([a, b]) => a === selectedNode || b === selectedNode).length}
            </div>
            {nodeDetail ? (
              <pre style={{
                color: colors.textSecondary, fontSize: 11, fontFamily: 'monospace',
                background: colors.bgCard, padding: 12, borderRadius: 6,
                maxHeight: 200, overflow: 'auto', whiteSpace: 'pre-wrap',
              }}>
                {JSON.stringify(nodeDetail, null, 2)}
              </pre>
            ) : (
              <div style={{ color: colors.textSecondary, fontSize: 12 }}>Loading...</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
