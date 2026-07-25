-- 282: Restore Principal-Review teaching wrongly collapsed by crystal_factory
-- near-dup merge (shared LEFT(crystal_text,80) boilerplate across scenarios).
-- Factory now exempts origin_surface='principal_review'; crystal text gets
-- unique lib: tag. Re-activate library-pointed survivors so crisis inject
-- can see them (reachable) and inject reinforcement can mark demonstrated.

UPDATE nate_intelligence_crystals c
SET scope = 'global',
    superseded_by = NULL,
    updated_at = NOW()
FROM principal_review_library l
WHERE l.promoted_crystal_id = c.id::text
  AND l.source_kind = 'gold_scored'
  AND l.status = 'promoted'
  AND c.origin_surface = 'principal_review'
  AND (
    c.scope = 'archived'
    OR c.superseded_by IS NOT NULL
  );
