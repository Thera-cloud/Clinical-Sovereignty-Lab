-- 151_add_token_balance.sql
-- Adds token_balance column to users table for tracking individual token economics

BEGIN;

-- Add the column with a safe default
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS token_balance DECIMAL(20,8) DEFAULT 0.0;

-- Create index for efficient balance lookups
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_token_balance 
ON users (token_balance) 
WHERE token_balance > 0;

-- Update existing users with initial balance from token_economics table logic
-- (assumes token_economics has family-level totals; individual allocation TBD)
UPDATE users 
SET token_balance = 0.0 
WHERE token_balance IS NULL;

COMMIT;

-- Post-migration verification
\echo '✅ Migration 151 complete. Token balances added to users table.';
SELECT 
  'token_balance column:' as check,
  column_name, 
  data_type, 
  is_nullable, 
  column_default 
FROM information_schema.columns 
WHERE table_name = 'users' AND column_name = 'token_balance';

\echo 'Sample balances:';
SELECT username, token_balance FROM users LIMIT 5;