-- Migration 165: Reconcile odpe_l2_faces schema
-- Migration 131 created the table with (l1_face_path, l2_label, keywords, ...)
-- Migration 132 tried to create it with (face_path TEXT PRIMARY KEY, activation_count, ...)
-- Since 131 ran first, the IF NOT EXISTS in 132 was a no-op.
-- Both the crystallizer and ODPEEngine need columns from both schemas.

ALTER TABLE odpe_l2_faces ADD COLUMN IF NOT EXISTS activation_count INT DEFAULT 0;
ALTER TABLE odpe_l2_faces ADD COLUMN IF NOT EXISTS last_activated TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE odpe_l2_faces ADD COLUMN IF NOT EXISTS face_path TEXT;

-- face_path needs a UNIQUE constraint for ON CONFLICT (face_path) in boost_from_cycle()
CREATE UNIQUE INDEX IF NOT EXISTS idx_odpe_l2_faces_face_path_uniq
    ON odpe_l2_faces (face_path) WHERE face_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_odpe_l2_faces_activation
    ON odpe_l2_faces (activation_count DESC);
CREATE INDEX IF NOT EXISTS idx_odpe_l2_faces_last
    ON odpe_l2_faces (last_activated DESC);
