-- Migration 131: ODPE Hierarchical Topology (L1 + L2 faces)
-- Supports the Deltoidal Hectakismyrioicositetrahedron (24M faces)

-- L1 taxonomy table (2,400 faces — seeded from clinical ontology)
CREATE TABLE IF NOT EXISTS odpe_l1_taxonomy (
    id SERIAL PRIMARY KEY,
    l0_face_key VARCHAR(100) NOT NULL,
    l1_index INT NOT NULL,
    l1_label VARCHAR(100) NOT NULL,
    keywords JSONB DEFAULT '[]'::jsonb,
    clinical_weight FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(l0_face_key, l1_index)
);

CREATE INDEX IF NOT EXISTS idx_l1_taxonomy_l0_key ON odpe_l1_taxonomy(l0_face_key);
CREATE INDEX IF NOT EXISTS idx_l1_taxonomy_label ON odpe_l1_taxonomy(l1_label);

-- L2 self-organizing faces (emergent from crystal corpus)
CREATE TABLE IF NOT EXISTS odpe_l2_faces (
    id SERIAL PRIMARY KEY,
    l1_face_path VARCHAR(200) NOT NULL,
    l2_label VARCHAR(100) NOT NULL,
    keywords JSONB DEFAULT '[]'::jsonb,
    clinical_weight FLOAT DEFAULT 1.0,
    crystal_count INT DEFAULT 0,
    last_crystal_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(l1_face_path, l2_label)
);

CREATE INDEX IF NOT EXISTS idx_l2_faces_l1_path ON odpe_l2_faces(l1_face_path);
CREATE INDEX IF NOT EXISTS idx_l2_faces_crystal_count ON odpe_l2_faces(crystal_count DESC);

-- Face path column on intelligence crystals for tagged retrieval
ALTER TABLE nate_intelligence_crystals
    ADD COLUMN IF NOT EXISTS face_path VARCHAR(300);

CREATE INDEX IF NOT EXISTS idx_crystals_face_path ON nate_intelligence_crystals(face_path)
    WHERE face_path IS NOT NULL;
