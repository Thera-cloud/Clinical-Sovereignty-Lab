-- Migration 167: Face path activation tracking for ODPE geometric topologies
-- Adds face_path columns to odpe_signal_log and creates L0 face activation table

-- Extend odpe_signal_log with face path data from each evaluation
ALTER TABLE odpe_signal_log ADD COLUMN IF NOT EXISTS face_path TEXT;
ALTER TABLE odpe_signal_log ADD COLUMN IF NOT EXISTS face_scores JSONB DEFAULT '{}'::jsonb;
ALTER TABLE odpe_signal_log ADD COLUMN IF NOT EXISTS hierarchical_depth INTEGER DEFAULT 0;

-- L0 face activation counts: track how often each geometric face fires
-- across dodecahedron (12 faces) and icositetrahedron (24 faces)
CREATE TABLE IF NOT EXISTS odpe_face_activations (
    id              SERIAL PRIMARY KEY,
    topology        VARCHAR(16) NOT NULL,          -- 'dodec' or 'icosi'
    face_index      VARCHAR(64) NOT NULL,          -- '0'..'11' for dodec, key string for icosi
    activation_count INTEGER NOT NULL DEFAULT 1,
    cumulative_score NUMERIC(10,4) NOT NULL DEFAULT 0.0,
    last_score      NUMERIC(6,4),
    last_activated  TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (topology, face_index)
);

CREATE INDEX IF NOT EXISTS idx_face_act_topology ON odpe_face_activations(topology);
CREATE INDEX IF NOT EXISTS idx_face_act_count ON odpe_face_activations(activation_count DESC);

-- Seed dodecahedron faces (12)
INSERT INTO odpe_face_activations (topology, face_index, activation_count, cumulative_score)
VALUES
    ('dodec', '0', 0, 0), ('dodec', '1', 0, 0), ('dodec', '2', 0, 0),
    ('dodec', '3', 0, 0), ('dodec', '4', 0, 0), ('dodec', '5', 0, 0),
    ('dodec', '6', 0, 0), ('dodec', '7', 0, 0), ('dodec', '8', 0, 0),
    ('dodec', '9', 0, 0), ('dodec', '10', 0, 0), ('dodec', '11', 0, 0)
ON CONFLICT (topology, face_index) DO NOTHING;

-- Seed icositetrahedron faces (24) using func:scope naming
INSERT INTO odpe_face_activations (topology, face_index, activation_count, cumulative_score)
VALUES
    ('icosi', 'vectorize_retrieval:user', 0, 0),
    ('icosi', 'vectorize_retrieval:global', 0, 0),
    ('icosi', 'vectorize_retrieval:superseded_chain', 0, 0),
    ('icosi', 'noetic_fusion:user', 0, 0),
    ('icosi', 'noetic_fusion:global', 0, 0),
    ('icosi', 'noetic_fusion:superseded_chain', 0, 0),
    ('icosi', 'metacognition:user', 0, 0),
    ('icosi', 'metacognition:global', 0, 0),
    ('icosi', 'metacognition:superseded_chain', 0, 0),
    ('icosi', 'quantum_self_coherence:user', 0, 0),
    ('icosi', 'quantum_self_coherence:global', 0, 0),
    ('icosi', 'quantum_self_coherence:superseded_chain', 0, 0),
    ('icosi', 'generative_wisdom:user', 0, 0),
    ('icosi', 'generative_wisdom:global', 0, 0),
    ('icosi', 'generative_wisdom:superseded_chain', 0, 0),
    ('icosi', 'world_coherence:user', 0, 0),
    ('icosi', 'world_coherence:global', 0, 0),
    ('icosi', 'world_coherence:superseded_chain', 0, 0),
    ('icosi', 'crystal_lake:user', 0, 0),
    ('icosi', 'crystal_lake:global', 0, 0),
    ('icosi', 'crystal_lake:superseded_chain', 0, 0),
    ('icosi', 'emergent:user', 0, 0),
    ('icosi', 'emergent:global', 0, 0),
    ('icosi', 'emergent:superseded_chain', 0, 0)
ON CONFLICT (topology, face_index) DO NOTHING;
