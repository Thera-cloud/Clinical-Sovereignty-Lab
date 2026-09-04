-- 432: hashed client IP on public trial rows (digest unique-IP; no raw IP).
-- Additive only. QUANTUM-CRYSTAL-ARCH

ALTER TABLE public_summon_usage
    ADD COLUMN IF NOT EXISTS ip_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_public_summon_usage_ip_hash_last_seen
    ON public_summon_usage (last_seen)
    WHERE ip_hash IS NOT NULL;
