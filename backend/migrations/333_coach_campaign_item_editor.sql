-- Additive hero + editor fields for Coach Command campaign items.
-- Mirrors Little Nate Dispatch stills, scoped per marketing_content row.
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS hero_image_prompt TEXT;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS hero_image_url TEXT;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS hero_image_r2_key TEXT;
ALTER TABLE marketing_content
  ADD COLUMN IF NOT EXISTS hero_image_generated_at TIMESTAMPTZ;
