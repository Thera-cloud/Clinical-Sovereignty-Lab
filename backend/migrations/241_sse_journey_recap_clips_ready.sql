-- Allow clips_ready status used by render_all_recap_segments / Studio trailer pipeline.
-- QUANTUM-CRYSTAL-ARCH: journey recap trailer E2E status machine
ALTER TABLE sse_journey_recap_jobs
    DROP CONSTRAINT IF EXISTS sse_journey_recap_jobs_status_check;

ALTER TABLE sse_journey_recap_jobs
    ADD CONSTRAINT sse_journey_recap_jobs_status_check
    CHECK (status IN (
        'pending',
        'aligning',
        'rendering',
        'clips_ready',
        'stitching',
        'complete',
        'failed'
    ));
