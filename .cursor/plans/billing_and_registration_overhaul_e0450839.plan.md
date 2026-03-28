---
name: Billing and Registration Overhaul
overview: Remove all beta/testing-period UI elements, add unified discount code fields in client tier selection and coach registration, fix backend product alignment gaps (receipt validation, annual pricing, webhook handling).
todos:
  - id: unified-verify
    content: Create GET /api/billing/verify-discount-code/{code} public endpoint in billing.py that checks all 3 discount tables
    status: completed
  - id: client-discount-ui
    content: Add discount code field to _buildClientTierSelection() in main.dart with validate + display logic
    status: completed
  - id: coach-discount-ui
    content: Replace INVITE CODE section with DISCOUNT CODE in coach registration (main.dart ~8663), remove validation bypass
    status: completed
  - id: remove-beta
    content: Remove BETA_INVITE_CODE, is_beta, and beta skip logic from bridge_server.py
    status: completed
  - id: registration-discount
    content: Accept and store discount_code in register_new_user() profile_data in bridge_server.py
    status: completed
  - id: receipt-consumables
    content: Add consumable product mappings (4 token packs + 4 sanctuary charges) to receipt_validation.py
    status: completed
  - id: annual-pricing
    content: Add INNER_CHAMBER_ANNUAL and SOVEREIGN_CIRCLE_ANNUAL to PRICES dict in stripe_integration.py
    status: completed
  - id: bridge-checkout-unify
    content: Update stripe_billing.py WebSocket checkout to resolve school/corporate codes (not just promos)
    status: completed
  - id: build-deploy
    content: flutter build web, deploy backend + web to production, purge Cloudflare cache
    status: completed
isProject: false
---

# Billing, Registration, and Product Alignment Overhaul

## Context

The registration flow still carries "INVITE CODE" (deployed as "BETA ACCESS") language that needs to become "DISCOUNT CODE". Discount codes must accept all three code types in the system: promotional specials, school codes, and corporate sponsor codes. Additionally, the backend has product alignment gaps between App Store Connect, Stripe, and the webhook/receipt handlers.

---

## Part 1: Unified Discount Code Verification Endpoint

**File:** [backend/app/routers/billing.py](backend/app/routers/billing.py)

Create `GET /api/billing/verify-discount-code/{code}?tier=STANDARD` — a public endpoint (no auth required, IP-rate-limited) that checks all three discount tables in order:

1. `promotional_specials` (promo codes like WELCOME20)
2. `school_codes` (school discount codes)
3. `corporate_sponsors` (corporate sponsor codes)

Returns unified response:

```python
{
    "valid": True,
    "source": "promotional_specials",  # or school_codes, corporate_sponsors
    "name": "Welcome 20% Off",
    "discount_type": "percent",        # or "fixed", "pays_full"
    "discount_value": 20,
    "applicable_tiers": ["inner_chamber", "sovereign_circle"]
}
```

This mirrors the logic already in `_resolve_promo_coupon()` at [stripe_integration.py line 626](backend/app/services/stripe_integration.py) but exposed as a public REST endpoint for pre-registration validation.

---

## Part 2: Client Registration — Add Discount Code to Tier Selection

**File:** [mobile/lib/main.dart](mobile/lib/main.dart), `_buildClientTierSelection()` (~line 8261)

**Current state:** Tier cards (Coach-Only, Threshold, Inner Chamber, Sovereign Circle) followed by CONTINUE button.

**Changes:**

- Add a "DISCOUNT CODE" section between the tier cards and the CONTINUE button
- Gold-accented container with discount tag icon
- TextField with "Discount Code (optional)" label and an "APPLY" button
- On apply: call `GET /api/billing/verify-discount-code/{code}?tier={selectedTier}` (unauthenticated, via `http.get`)
- On success: show green confirmation with discount details (e.g., "20% off Inner Chamber")
- On failure: show red error ("Invalid or expired code")
- Store the validated code in a new state variable `_discountCode`
- Include `discount_code` in the registration payload (line ~7803)

**New state fields:**

- `_discountCodeCtrl` (TextEditingController)
- `_discountValidated` (bool)
- `_discountDetails` (Map — name, type, value from verify response)

---

## Part 3: Coach Registration — Replace Invite Code with Discount Code

**File:** [mobile/lib/main.dart](mobile/lib/main.dart), section "2.4 INVITE CODE (Coaches only)" (~line 8663)

**Current state:** Purple "INVITE CODE" box with `_inviteCodeCtrl`, entering a code skips contact info/W-9 validation.

**Changes:**

- Rename header from "INVITE CODE" to "DISCOUNT CODE"
- Change icon from `Icons.science` to `Icons.local_offer` (discount tag)
- Change subtitle to "Have a discount code? Enter it below to apply to your subscription."
- Change `labelText` from "Invite Code (optional)" to "Discount Code (optional)"
- Add "APPLY" button to validate against the unified endpoint
- Show validation result (same pattern as client)
- Remove the `_isInviteCodeEntered` validation bypass at lines 7748-7767 — coach email, phone, and W-9 are always required for production

**Registration payload change (line ~7803):**

- Change from `"invite_code": _inviteCodeCtrl.text.trim()` to `"discount_code": _inviteCodeCtrl.text.trim()`
- Keep `"invite_code"` as well for backward compatibility with bridge

---

## Part 4: Remove Beta Elements

**File:** [mobile/lib/main.dart](mobile/lib/main.dart)

- Remove the `is_beta` / `_isInviteCodeEntered` validation bypass logic (lines 7748-7767)
- The deployed version shows "Beta: No charge during testing period" at the bottom of tier selection and DOJO selection — confirm this is removed from the current code (grepped: not present in local code, so this is already resolved; just needs a fresh build + deploy)

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)

- `BETA_INVITE_CODE` env var (line 201) — remove or deprecate
- `is_beta` check (lines 3239-3244) — remove; all users follow the same registration path
- Beta skip for address validation (lines 9820-9822) — remove the `_is_beta_reg` guard

---

## Part 5: Backend — Store Discount Code on Registration

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py), `register_new_user()` (~line 3230)

- Accept `discount_code` from the registration payload
- Store in `profile_data["discount_code"]` so it's available at checkout time
- The `create_subscription_checkout` in [stripe_integration.py](backend/app/services/stripe_integration.py) already accepts `promo_code` and resolves across all three tables via `_resolve_promo_coupon()` — it will pick up the stored code at checkout

---

## Part 6: Backend — Fix Receipt Validation for Consumables

**File:** [backend/app/routers/receipt_validation.py](backend/app/routers/receipt_validation.py)

**Problem:** `PRODUCT_TO_PLAN` (line 26) only maps subscription products. The 8 consumable IAPs from App Store Connect will return "Unknown product."

**Changes:**

Add consumable product IDs to a new `CONSUMABLE_PRODUCTS` map:

```python
CONSUMABLE_PRODUCTS = {
    "net.sovereignsanctuary.token_light3": {"tokens": 15000, "type": "token_pack"},
    "net.sovereignsanctuary.token_standard7": {"tokens": 50000, "type": "token_pack"},
    "net.sovereignsanctuary.token_power": {"tokens": 150000, "type": "token_pack"},
    "net.sovereignsanctuary.token_ultimate": {"tokens": 1000000, "type": "token_pack"},
    "net.sovereignsanctuary.sanctuary_charge_base_fee": {"amount_cents": 2000, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_assisted_response": {"amount_cents": 300, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_group_coaching": {"amount_cents": 2000, "type": "sanctuary_charge"},
    "net.sovereignsanctuary.sanctuary_charge_individual_coaching": {"amount_cents": 500, "type": "sanctuary_charge"},
}
```

Update `verify_apple_receipt` to handle consumables: if `active_product` is in `CONSUMABLE_PRODUCTS`, call a new `_credit_consumable()` function that credits tokens or records the sanctuary charge instead of trying to activate a subscription plan.

---

## Part 7: Backend — Add Annual Pricing Keys

**File:** [backend/app/services/stripe_integration.py](backend/app/services/stripe_integration.py), `PRICES` dict (line 52)

Add:

```python
"INNER_CHAMBER_ANNUAL": os.getenv("STRIPE_PRICE_INNER_CHAMBER_ANNUAL"),    # $490/yr
"SOVEREIGN_CIRCLE_ANNUAL": os.getenv("STRIPE_PRICE_SOVEREIGN_CIRCLE_ANNUAL"),  # $749/6mo
```

Update `create_subscription_checkout` to accept a `billing_cycle` parameter (`monthly` or `annual`). When annual, look up `{TIER}_ANNUAL` instead of `{TIER}` in the PRICES dict.

---

## Part 8: Backend — Bridge WebSocket Checkout Unification

**File:** [backend/app/websocket/stripe_billing.py](backend/app/websocket/stripe_billing.py)

**Problem:** The WebSocket `create_checkout_session` only resolves promo codes from `promotional_specials`, not school/corporate codes. The REST `/api/billing/checkout` uses the full three-table `_resolve_promo_coupon()`.

**Fix:** Update `stripe_billing.py`'s checkout resolver to check all three tables (same logic as `_resolve_promo_coupon` in `stripe_integration.py`).

---

## Part 9: Apple Server Notifications V2 (Scoped Separately)

This is a significant undertaking (JWS signature verification, notification type handling, subscription lifecycle management). Recommend deferring to a separate task after the core fixes above ship. For now, the client-side receipt verification path covers the immediate need.

---

## Pricing Discrepancy Note

- **Sovereign Circle Annual**: App Store Connect says "6 months" duration. Stripe says "$749 every 6 months". The code calls it "annual". This needs a decision: either rename to "Semi-Annual" or change the Stripe price/ASC duration to 12 months at $1,490. This is a business decision, not a code fix.

---

## Deployment Sequence

1. Backend changes first (billing.py, receipt_validation.py, stripe_integration.py, bridge_server.py, stripe_billing.py)
2. Deploy backend to GREEN via scp + restart
3. Flutter changes (main.dart)
4. `flutter build web --release`
5. Deploy web build to GREEN (rsync without --delete)
6. Purge Cloudflare cache

