-- promoted_crystal_id was UUID; nate_intelligence_crystals.id is integer.
ALTER TABLE principal_review_library
  ALTER COLUMN promoted_crystal_id TYPE text
  USING promoted_crystal_id::text;
