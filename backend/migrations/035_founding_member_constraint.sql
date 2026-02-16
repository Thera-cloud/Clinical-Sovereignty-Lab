-- =============================================================================
-- Migration 035: Founding Member Constraint (Defense-in-depth)
-- Prevents founding_member_number from exceeding 100; enforces via DB constraint
-- and platform_config trigger.
-- =============================================================================

-- Prevent founding_member_number from exceeding 100
ALTER TABLE users ADD CONSTRAINT chk_founding_member_number
    CHECK (founding_member_number IS NULL OR (founding_member_number >= 1 AND founding_member_number <= 100));

-- Also enforce via trigger on platform_config for defense-in-depth
CREATE OR REPLACE FUNCTION check_founding_limit() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.key = 'founding_member_count' THEN
        IF COALESCE((NEW.value->>'count')::int, 0) > 100 THEN
            RAISE EXCEPTION 'Founding member count cannot exceed 100';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_founding_limit ON platform_config;
CREATE TRIGGER trg_founding_limit
    BEFORE INSERT OR UPDATE ON platform_config
    FOR EACH ROW EXECUTE FUNCTION check_founding_limit();
