-- Migration 178: SSE Studio Projects table for Thera-World Studio
-- Tracks trailer/clip generation projects with manifests and cost data

CREATE TABLE IF NOT EXISTS sse_studio_projects (
    project_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    scene_count INT DEFAULT 0,
    status TEXT DEFAULT 'draft',
    manifest JSONB DEFAULT '{}',
    estimated_cost_cents INT DEFAULT 0,
    actual_cost_cents INT DEFAULT 0,
    manifest_url TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sse_studio_projects_created
    ON sse_studio_projects(created_at DESC);
