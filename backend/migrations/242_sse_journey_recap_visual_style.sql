-- QUANTUM-CRYSTAL-ARCH: Generation-time visual style for journey recap trailers
ALTER TABLE sse_journey_recap_jobs
    ADD COLUMN IF NOT EXISTS visual_style TEXT NOT NULL DEFAULT 'vault_match';
