-- 152_token_balances.sql
-- User/family token balances with transfer ledger

CREATE TABLE IF NOT EXISTS token_balances (
    id BIGSERIAL PRIMARY KEY,
    family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    pending_in BIGINT NOT NULL DEFAULT 0,
    pending_out BIGINT NOT NULL DEFAULT 0,
    total_earned BIGINT NOT NULL DEFAULT 0,
    total_spent BIGINT NOT NULL DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(family_id, user_id)
);

CREATE TABLE IF NOT EXISTS token_transfers (
    id BIGSERIAL PRIMARY KEY,
    from_family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    from_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_family_id UUID NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    to_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount BIGINT NOT NULL CHECK (amount > 0),
    reason VARCHAR(100) NOT NULL,
    tx_hash VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    INDEX idx_token_transfers_from (from_family_id, from_user_id, created_at),
    INDEX idx_token_transfers_to (to_family_id, to_user_id, created_at)
);

-- Trigger: update balance on transfer
CREATE OR REPLACE FUNCTION update_token_balance()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO token_balances (family_id, user_id, balance, last_updated)
    VALUES (
        NEW.to_family_id, NEW.to_user_id, 
        COALESCE((SELECT balance FROM token_balances WHERE family_id = NEW.to_family_id AND user_id = NEW.to_user_id), 0) + NEW.amount,
        NOW()
    )
    ON CONFLICT (family_id, user_id)
    DO UPDATE SET
        balance = token_balances.balance + NEW.amount,
        last_updated = NOW();
    
    -- Deduct from sender
    UPDATE token_balances 
    SET balance = balance - NEW.amount, last_updated = NOW()
    WHERE family_id = NEW.from_family_id AND user_id = NEW.from_user_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER token_transfer_balance
    AFTER INSERT ON token_transfers
    FOR EACH ROW EXECUTE FUNCTION update_token_balance();

COMMENT ON TABLE token_balances IS 'Current token balances per user/family with pending tracking';
COMMENT ON TABLE token_transfers IS 'Immutable ledger of all token movements';

-- Initialize existing users
INSERT INTO token_balances (family_id, user_id, balance)
SELECT f.id, u.id, 1000 -- starter balance
FROM families f
JOIN users u ON u.family_id = f.id
ON CONFLICT (family_id, user_id) DO NOTHING;