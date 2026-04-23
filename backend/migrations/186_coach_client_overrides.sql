-- Coach ↔ client story overrides for Thera-World / SSE calibration

CREATE TABLE IF NOT EXISTS coach_client_overrides (
    id SERIAL PRIMARY KEY,
    coach_user_id VARCHAR NOT NULL,
    client_user_id VARCHAR NOT NULL,
    focus_domain VARCHAR,
    pacing VARCHAR DEFAULT 'normal'
        CHECK (pacing IN ('slow', 'normal', 'fast')),
    clinical_hold BOOLEAN DEFAULT false,
    mission_priority VARCHAR,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (coach_user_id, client_user_id)
);

CREATE INDEX IF NOT EXISTS idx_coach_client_overrides_client
    ON coach_client_overrides (client_user_id);

CREATE INDEX IF NOT EXISTS idx_coach_client_overrides_coach
    ON coach_client_overrides (coach_user_id);
