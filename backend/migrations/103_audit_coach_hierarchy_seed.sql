-- Seed coach_hierarchy so audit_coach (Audit Lawyer 1) is assistant under a master for Classroom audit scenario.
-- Master = CoachN if present, else first ADMIN (e.g. DrNevedal1).

INSERT INTO coach_hierarchy (master_coach_id, assistant_id, status, accepted_at)
SELECT m.hardware_id, 'audit_coach_hw', 'accepted', NOW()
FROM users m
WHERE m.role IN ('COACH', 'ADMIN')
  AND m.hardware_id IS NOT NULL
  AND m.hardware_id != ''
ORDER BY CASE WHEN m.username = 'CoachN' THEN 0 WHEN m.role = 'ADMIN' THEN 1 ELSE 2 END
LIMIT 1
ON CONFLICT (master_coach_id, assistant_id) DO NOTHING;
