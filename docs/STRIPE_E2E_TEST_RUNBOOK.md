# Stripe E2E Test Runbook (Test Mode -> Live Mode)

This runbook validates the full billing pipeline end-to-end for:
- Checkout launch from app
- Stripe hosted checkout completion
- Webhook processing
- Database subscription writes
- User tier/status updates reflected in app

## Canonical Tier Mapping (Important)

The backend uses canonical tier keys:
- `INNER CHAMBER` -> `STANDARD`
- `SOVEREIGN CIRCLE` -> `TOP_TIER`
- `TRIAL` -> `TRIAL` (free)
- `COACH_ONLY` -> `COACH_ONLY` (free)

Paid Stripe subscription checkout should only be expected for:
- `STANDARD` ($49)
- `TOP_TIER` ($149)

## Preconditions

1. App build uses production API URL:
   - `mobile/lib/config/app_config.dart` -> `useProduction = true`
2. Backend has Stripe keys configured in env:
   - `STRIPE_SECRET_KEY`
   - `STRIPE_PUBLISHABLE_KEY`
   - `STRIPE_WEBHOOK_SECRET`
   - `STRIPE_PRICE_STANDARD`
   - `STRIPE_PRICE_TOP_TIER`
3. Webhook endpoint is reachable at:
   - `POST /api/billing/webhook`
4. Promo endpoint is live:
   - `GET /api/billing/verify-promo/{code}?tier={TIER}`

## A. Test Mode Validation (Required Before Live)

### A1) Confirm backend is in Stripe test mode

On backend host/container, check:
- `STRIPE_SECRET_KEY` starts with `sk_test_`
- price IDs are test-mode `price_...` from Stripe test dashboard

### A2) App checkout launch + success flow (paid tiers)

For each paid tier:
1. From app billing screen, select tier:
   - Inner Chamber (`STANDARD`)
   - Sovereign Circle (`TOP_TIER`)
2. Start checkout and confirm Stripe hosted page opens.
3. Complete checkout with:
   - Card: `4242 4242 4242 4242`
   - Any future exp date, any CVC, any ZIP.
4. Confirm app returns to success URL and shows updated access.

### A3) Verify DB writes after successful checkout

Run these SQL checks (production DB shown; adapt if needed):

```sql
-- Latest Stripe subscription rows
SELECT user_id, tier, status, stripe_subscription_id, current_period_end, updated_at
FROM subscriptions
ORDER BY updated_at DESC
LIMIT 10;

-- User tier/status must be ACTIVE and match checkout tier
SELECT username, tier, subscription_status, stripe_customer_id
FROM users
WHERE username = '<test_username>';

-- Webhook event receipt proof
SELECT event_id, event_type, created_at
FROM webhook_events
WHERE provider = 'stripe'
ORDER BY created_at DESC
LIMIT 20;

-- Payment history record
SELECT user_id, stripe_invoice_id, amount_cents, status, event_type, created_at
FROM payment_history
WHERE user_id = (SELECT id FROM users WHERE username = '<test_username>')
ORDER BY created_at DESC
LIMIT 10;
```

Expected:
- `subscriptions.status = ACTIVE`
- `users.subscription_status = ACTIVE`
- `users.tier` equals `STANDARD` or `TOP_TIER`
- `webhook_events` includes `checkout.session.completed` and/or `invoice.paid`

### A4) Validate free tiers

For `COACH_ONLY` and `TRIAL`:
- Confirm app does not require Stripe checkout to assign/retain these tiers.
- Confirm resulting user tier/status are coherent and app is not stuck in checkout state.

### A5) Promo code test (`WELCOME20`)

1. Verify promo from API first:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" \
  "https://api.sovereignsanctuary.net/api/billing/verify-promo/WELCOME20?tier=STANDARD"
```

Expected: `valid: true` and discount metadata.

2. In app, apply `WELCOME20` before checkout.
3. Confirm discount appears on Stripe hosted checkout page.
4. Complete payment with test card and verify redemption increments only on successful completion.

Optional DB verification:

```sql
SELECT promo_code, current_redemptions, max_redemptions, active
FROM promotional_specials
WHERE promo_code = 'WELCOME20';
```

### A6) Failure-path validation

Run each and verify graceful app behavior (no stuck loading, clear error message, retry possible):

1. Generic decline: `4000 0000 0000 0002`
2. Expired card: `4000 0000 0000 0069`
3. Insufficient funds: `4000 0000 0000 9995`
4. User cancels at hosted checkout (`cancel_url` return)

DB expectations on failure:
- No incorrect `ACTIVE` tier promotion
- No orphaned subscription row in inconsistent state
- `invoice.payment_failed` events should set `subscriptions.status = PAST_DUE` if applicable

## B. Live Mode Validation (Minimal Real-Charge Proof)

### B1) Switch to live credentials

Verify backend env:
- `STRIPE_SECRET_KEY` starts with `sk_live_`
- live `price_...` IDs for `STANDARD` and `TOP_TIER`
- correct `STRIPE_WEBHOOK_SECRET` from live endpoint

### B2) Execute one real charge

1. Use Inner Chamber checkout (`STANDARD`, $49).
2. Complete with a real card.
3. Verify:
   - webhook received
   - DB tier/status updated to `STANDARD` / `ACTIVE`
   - app reflects paid tier features

### B3) Immediate refund

From Stripe dashboard:
1. Find successful payment/invoice/charge.
2. Issue full refund immediately.
3. Verify refund reflected in Stripe and internal finance reconciliation.

## C. FastAPI Endpoint References in This Codebase

- Checkout: `POST /api/billing/checkout`
- Subscription status: `GET /api/billing/subscription`
- Cancel subscription: `POST /api/billing/subscription/cancel`
- Promo verify: `GET /api/billing/verify-promo/{code}`
- Webhook receiver: `POST /api/billing/webhook`

## D. Sign-off Criteria

Do not go live until all are true:
- Test-mode paid checkout works for `STANDARD` and `TOP_TIER`
- Free tiers (`COACH_ONLY`, `TRIAL`) do not break billing flow
- `WELCOME20` discount is visible on hosted checkout and redeemed only on successful completion
- Failure cases recover cleanly in app
- Live $49 charge + webhook + app tier update + refund all verified end-to-end
