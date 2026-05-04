-- Align coach_folder_files URL columns with folder_api.
-- Migration 081 used storage_url; 081b used azure_blob_url. Whichever CREATE ran first
-- wins under IF NOT EXISTS, leaving production without one column → SELECT 500s.

BEGIN;

ALTER TABLE coach_folder_files ADD COLUMN IF NOT EXISTS azure_blob_url TEXT;
ALTER TABLE coach_folder_files ADD COLUMN IF NOT EXISTS storage_url TEXT;

UPDATE coach_folder_files
SET azure_blob_url = storage_url
WHERE (azure_blob_url IS NULL OR TRIM(azure_blob_url) = '')
  AND storage_url IS NOT NULL AND TRIM(storage_url) != '';

UPDATE coach_folder_files
SET storage_url = azure_blob_url
WHERE (storage_url IS NULL OR TRIM(storage_url) = '')
  AND azure_blob_url IS NOT NULL AND TRIM(azure_blob_url) != '';

COMMIT;
