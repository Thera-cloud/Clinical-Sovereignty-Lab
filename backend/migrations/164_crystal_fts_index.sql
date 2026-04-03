-- Migration 164: GIN index for full-text search on crystal_text
-- Enables topic-aware crystal recall without sequential scan on 80K+ rows

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_crystals_fts_english
  ON nate_intelligence_crystals
  USING GIN (to_tsvector('english', crystal_text));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_crystals_recall_cold
  ON nate_intelligence_crystals (user_id, confidence)
  WHERE recall_count IS NULL OR recall_count = 0;
