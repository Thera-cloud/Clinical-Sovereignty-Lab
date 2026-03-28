---
name: Test-Mode Session Billing
overview: "Wire the session billing pipeline end-to-end in test mode: set price_cents from the coach's fee at scheduling time, fix broken JOINs and column references in the payment agent, and add a simulated charge path that logs the full fee breakdown (gross, 30% platform cut, coach payout) without hitting Stripe."
todos:
  - id: fix-join-bug
    content: "Fix session_payment_agent.py JOIN: u.hardware_id = cs.client_id (not u.id) and use COALESCE(cs.scheduled_start, cs.scheduled_at)"
    status: completed
  - id: set-price-cents
    content: In sessions.py schedule_session, look up coach coaching_fee from users table and set price_cents = fee * 100
    status: completed
  - id: simulate-charge
    content: Add _simulate_charge method to SessionPaymentAgent with full fee breakdown (gross, 30% platform, coach payout), controlled by SESSION_BILLING_MODE env var
    status: completed
  - id: migration-check
    content: Create migration to add test_charge_simulated to session_payment_events event_type CHECK constraint
    status: completed
  - id: deploy-verify
    content: Deploy, verify test charge appears in session_payment_events with correct fee breakdown
    status: completed
isProject: false
---

# Test-Mode Session Billing Pipeline

## Current State

- `schedule_session` in [backend/app/routers/sessions.py](backend/app/routers/sessions.py) sets `price_cents: None` for non-consultations, which PG defaults to `0`
- `session_payment_agent.py` skips sessions where `price_cents <= 0`, so no billing event ever fires
- CoachN has `coaching_fee: 175.0` in `profile_data` (dollars per session)
- The `calculate_platform_fee()` function in `bridge_server.py` already computes the 30% / $30 minimum split

## Bugs Blocking the Pipeline (Must Fix First)

### 1. JOIN mismatch in `session_payment_agent.py`

The agent joins `LEFT JOIN users u ON u.id = cs.client_id`, but `client_id` is TEXT (hardware_id like `CLIENT_001`) and `users.id` is UUID. This JOIN always returns NULL for all user fields (name, email, stripe_customer_id).

**Fix:** Change to `LEFT JOIN users u ON u.hardware_id = cs.client_id`

### 2. Wrong date column in `session_payment_agent.py`

The agent queries `cs.scheduled_at`, but the new scheduling flow writes to `cs.scheduled_start`. Sessions created by the REST API have `scheduled_at = now()` (column default) while the actual scheduled time is in `scheduled_start`.

**Fix:** Use `COALESCE(cs.scheduled_start, cs.scheduled_at)` in the WHERE clause and SELECT

### 3. CHECK constraint on `session_payment_events`

The `event_type` CHECK only allows: `charge_attempted`, `charge_succeeded`, `charge_failed`, `refund`, `cancellation`, `reminder_sent`. Need to add `test_charge_simulated` to the allowed list.

**Fix:** `ALTER TABLE session_payment_events DROP CONSTRAINT ...; ALTER TABLE ADD CONSTRAINT ... CHECK (event_type = ANY (ARRAY[...existing..., 'test_charge_simulated']))` via migration

## Implementation

### Step 1: Set `price_cents` from coach fee at scheduling time

In `sessions.py` `schedule_session`, after building the session dict:

```python
# Look up coach fee from profile_data
coach_fee_dollars = 0
try:
    pool = request.app.state.db_pool
    coach_row = await pool.fetchrow(
        "SELECT profile_data->>'coaching_fee' as fee FROM users WHERE hardware_id = $1 AND role = 'COACH'",
        req.coach_id
    )
    if coach_row and coach_row['fee']:
        coach_fee_dollars = float(coach_row['fee'])
except Exception:
    pass

if not _is_consultation and coach_fee_dollars > 0:
    session["price_cents"] = int(coach_fee_dollars * 100)
```

For CoachN ($175), this sets `price_cents = 17500`.

### Step 2: Add test billing mode to `session_payment_agent.py`

Add env var check at the top:

```python
SESSION_BILLING_MODE = os.getenv("SESSION_BILLING_MODE", "test")
```

Add a `_simulate_charge` method:

```python
async def _simulate_charge(self, conn, session_id, fee_cents: int, client_name: str) -> bool:
    coach_fee = fee_cents / 100.0
    platform_fee = max(coach_fee * 0.30, 30.00)
    coach_payout = max(coach_fee - platform_fee, 0)

    await conn.execute(
        """UPDATE coaching_sessions
           SET payment_status = 'test_paid', payment_amount_cents = $1, updated_at = NOW()
           WHERE id = $2""",
        fee_cents, session_id,
    )
    await self._log_event(conn, session_id, "test_charge_simulated", fee_cents,
                          note=json.dumps({
                              "mode": "test",
                              "gross_fee": coach_fee,
                              "platform_fee_30pct": round(platform_fee, 2),
                              "coach_payout": round(coach_payout, 2),
                              "client_name": client_name or "",
                          }))
    logger.info("SessionPaymentAgent: TEST charge simulated — $%.2f gross, $%.2f platform (30%%), $%.2f coach payout (session %s, client %s)",
                coach_fee, platform_fee, coach_payout, session_id, client_name)
    return True
```

In `_run_one_cycle`, route to simulate vs real:

```python
if SESSION_BILLING_MODE == "test":
    success = await self._simulate_charge(conn, session_id, charge_amount, session.get("client_name", ""))
else:
    # existing Stripe path
    success = await self._charge_card(conn, session_id, stripe_customer, charge_amount)
```

### Step 3: Fix JOINs and column references

All 3 queries in `_run_one_cycle` need:

- `u.hardware_id = cs.client_id` instead of `u.id = cs.client_id`
- `COALESCE(cs.scheduled_start, cs.scheduled_at)` instead of `cs.scheduled_at`

### Step 4: Migration for CHECK constraint

```sql
ALTER TABLE session_payment_events
  DROP CONSTRAINT IF EXISTS session_payment_events_event_type_check;

ALTER TABLE session_payment_events
  ADD CONSTRAINT session_payment_events_event_type_check
  CHECK (event_type = ANY (ARRAY[
    'charge_attempted', 'charge_succeeded', 'charge_failed',
    'refund', 'cancellation', 'reminder_sent',
    'test_charge_simulated'
  ]));
```

## Fee Breakdown Example (CoachN at $175/session)

- Gross fee: **$175.00** (17500 cents)
- Platform fee (30%): **$52.50** (above the $30 minimum)
- Coach payout: **$122.50**
- Logged to `session_payment_events.metadata` as JSON

## Files to Modify

- [backend/app/routers/sessions.py](backend/app/routers/sessions.py) -- Look up coach fee, set `price_cents`
- [backend/app/services/session_payment_agent.py](backend/app/services/session_payment_agent.py) -- Fix JOINs, fix column refs, add `_simulate_charge` path
- New migration file -- Add `test_charge_simulated` to CHECK constraint
- `.env` (production) -- Add `SESSION_BILLING_MODE=test` (default is already `test` in code)

## Going Live Later

When ready to charge real money:

1. Set `SESSION_BILLING_MODE=live` in production `.env`
2. Recreate backend container (`docker compose -f docker-compose.prod.yml up -d backend`)
3. The existing `_charge_card` Stripe path activates automatically

