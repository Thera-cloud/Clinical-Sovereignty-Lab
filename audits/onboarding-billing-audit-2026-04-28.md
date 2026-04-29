# Onboarding & Billing Pipeline Audit — Phase 1 (Diagnostic Only)

**Date:** 2026-04-28  
**Scope:** Tier strings, token grant paths, monthly renewal, Stripe webhooks, case study **paula182**.  
**Repository:** Clinical Sovereignty Lab workspace (`Clinical-Sovereignty-Lab-2`).  
**Production mirror path (deploy note):** `/opt/clinical-sovereignty-lab/audits/onboarding-billing-audit-2026-04-28.md`

---

## Executive Summary

| Finding | Severity | Notes |
|--------|----------|--------|
| **Tier alias gaps** | **P0** | `registration_finalize._tier_mapping()` only recognizes exact keys (`TOP_TIER`, `STANDARD`, etc.). **`SOVEREIGN_CIRCLE` / `INNER_CHAMBER` fall through to TRIAL-like defaults → 10,000 tokens and wrong plan.** Flutter may emit `SOVEREIGN_CIRCLE` (e.g. `settings_screen.dart` dropdown). Separate normalization exists in `bridge_server` (`normalize_tier`) but **finalize path does not use it.** |
| **Stripe subscription checkout without token grant** | **P0** | Legacy path `checkout.session.completed` + `mode == subscription` updates `users.tier` and `subscriptions` but **does not update `token_balance`** (`stripe_integration.py` ~1593–1597). |
| **Stripe `customer.subscription.updated`** | **P0** | Updates `subscriptions` + `users.tier` / `subscription_status` — **no token grant** (~2098–2101). |
| **TRIAL token inconsistency** | **P1** | **50,000** in `backend/app/routers/billing.py` `PLAN_DETAILS["TRIAL"]`; **10,000** in `bridge_server` `BillingSystem.PLAN_DETAILS`, `register_new_user`, `registration_finalize._tier_mapping` else-branch. |
| **Monthly subscription token refill** | **P0 gap** | **`invoice.paid`** only inserts `payment_history`, updates `subscriptions` period — **does not grant monthly AI tokens** (`_handle_invoice_paid` ~1783–1815). **No dedicated monthly allowance grant tied to billing.** `TokenUsageAgent` resets **usage counters** (`token_usage_today` / month), not tier allowances. |
| **Stripe-first registration vs `subscriptions` table** | **P0** | **`finalize_signup()` does not `INSERT INTO subscriptions`.** `_handle_pending_signup` does not pass **`stripe_subscription_id`** into finalize (only `stripe_customer_id`, checkout session id). Legacy checkout **with `user_id`** does insert/update `subscriptions`. Result: paying Stripe-first users can have **`stripe_subscription_id` only in profile JSON** and **zero rows in `subscriptions`** — **`invoice.paid` period updates may no-op**, webhook joins fail. |
| **Audit trail for initial grants** | **P1/P0** | **`finalize_signup` does not insert `token_transactions`**. Token pack purchases do log (`stripe_integration.py`). Admin/Token Lab adjusts log. **Initial tier grants are invisible in `token_transactions`.** |
| **Paula Swain (`paula182`)** | **P0 case study** | Production queries confirm **TOP_TIER**, **ACTIVE**, **`token_balance` 200,000 after manual admin adjust**; **`token_transactions` contains only one row** — manual **+200,000** by DrNevedal1 (2026-04-28). **`subscriptions` table: 0 rows.** **`pending_signups`**: completed row **`tier = TOP_TIER`**, checkout **`cs_live_...`**, created ~2026-04-26. **Flow:** Stripe-first registration via **`pending_signup_id`** → `_handle_pending_signup` → **`finalize_signup`** with tier from DB (**TOP_TIER**, not `SOVEREIGN_CIRCLE`). **Precise reason for 0 balance before manual adjust is not fully proven in SQL alone** (needs correlation with logs); contributing factors below are **likely**: missing **`subscriptions` row** → broken downstream sync; **no transaction row** for grant; possible subsequent balance overwrite or consumption (not ruled out by static analysis). |

---

## Phase 1A — Tier String Inventory

### Canonical DB / bridge columns

From schema rules and code: `users.tier` uses uppercase enums such as **`TRIAL`**, **`STANDARD`**, **`TOP_TIER`**, **`COACH_ONLY`**, **`DEPENDENT`** (see `users` CHECK constraints in workspace rules).

### `registration_finalize._tier_mapping()` (authoritative for Stripe-first finalize)

```48:62:backend/app/services/registration_finalize.py
def _tier_mapping(role: str, registration_type: str):
    ...
    elif rt == "STANDARD":
        return "STANDARD", "STANDARD", "ACTIVE", True, 50000, ""
    elif rt == "TOP_TIER":
        return "TOP_TIER", "TOP_TIER", "ACTIVE", True, 200000, ""
    else:
        ...
        return "STANDARD", "TRIAL", "TRIAL_ACTIVE", True, 10000, trial_end
```

**Missing aliases:** `SOVEREIGN_CIRCLE`, `INNER_CHAMBER`, `SOVEREIGN`, etc. → **else branch → 10,000 tokens.**

**Dependent eligibility elsewhere** uses `SOVEREIGN_CIRCLE`:

```279:281:backend/app/services/registration_finalize.py
DEPENDENT_ELIGIBLE_PARENT_TIERS = {"TOP_TIER", "TOP", "SOVEREIGN_CIRCLE"}
```

So **`SOVEREIGN_CIRCLE` is recognized for dependents but not in `_tier_mapping`.**

### Bridge `normalize_tier` / `tier_for_db_column` (WebSocket registration)

`bridge_server.py` (~2327+) maps **`THRESHOLD` → `TRIAL`**, documents canonical names — **WebSocket path can normalize; Stripe finalize path does not.**

### Flutter / UI samples

| Location | Variation |
|----------|-----------|
| `mobile/lib/screens/settings_screen.dart` | Dropdown **`SOVEREIGN_CIRCLE`** for Sovereign Circle pricing (~4736); helpers map Sovereign → **`TOP_TIER`** elsewhere (~651–656). |
| `mobile/lib/services/payment_service.dart` | `_productIdToTier`: **`sovereign_circle` → `TOP_TIER`** (~186). |
| `mobile/lib/screens/onboarding_paid_screen.dart` | Expects **`STANDARD` / `TOP_TIER`** in comments. |

**Risk:** Any code path that passes **`SOVEREIGN_CIRCLE`** into **`finalize_signup(tier=...)`** without normalization hits **else** in `_tier_mapping`.

### Canonical mapping that **should** exist (proposal — Phase 2)

Single module (per remediation spec): normalize **all** inbound aliases to **`TRIAL` / `STANDARD` / `TOP_TIER` / `COACH_ONLY` / `DEPENDENT`** before persistence or token math. **`SOVEREIGN_CIRCLE` → `TOP_TIER`**, **`INNER_CHAMBER` → `STANDARD`**, **`THRESHOLD` → `TRIAL`**.

---

## Phase 1B — Token Grant / `token_balance` Write Paths (Representative)

| Area | Trigger | Amount / behavior | `token_transactions`? |
|------|---------|-------------------|------------------------|
| `registration_finalize.finalize_signup` | Stripe-first / shared finalize | From `_tier_mapping` | **No** |
| `bridge_server.register_new_user` | WebSocket registration | 0 / 50k / 200k / 10k TRIAL (~3395–3416) | Via billing usage paths later, not necessarily initial grant row |
| `stripe_integration` token pack | `checkout.session.completed` payment | Adds tokens | **Yes** (`purchase`, `source` token_pack) |
| `stripe_integration` subscription (legacy `user_id`) | `checkout.session.completed` subscription | Sets tier, **not tokens** | No grant row |
| `token_lab_api` / `admin` | Admin adjust | Sets balance | Yes (adjust) |
| `gkm_api` | Token share | Updates balance | Via bridge billing patterns |
| `user_store.upsert_user` | Bridge cache → PG | **`GREATEST` on token_balance** — preserves DB higher balance | N/A |
| `drip_scheduler._sync_zero_balance` | Trial expiration sweep | Forces **0** | **Risk** if misapplied to paid users |
| `receipt_validation` | Receipt flows | Incremental | Partial |

**Gap:** **Initial tier grants are not consistently mirrored in `token_transactions`**, unlike token pack purchases.

---

## Phase 1C — Monthly “Renewal” / Recurring Jobs

| Component | What it does |
|-----------|----------------|
| **`TokenUsageAgent`** | Daily snapshot of **usage** + reset **`token_usage_today`**; monthly reset **`token_usage_month`**; **does not add monthly plan tokens to `token_balance`**. |
| **`invoice.paid`** (`_handle_invoice_paid`) | **Payment history + `subscriptions` period dates only** — **no token grant.** |
| **`grep` surface** | Many hits for “renewal” refer to **OAuth / marketing**, not AI token allowance. |

**Conclusion:** **No implemented monthly AI-token allowance refill** aligned with subscription invoices in the reviewed code. **Bug #4 confirmed** as product/engineering gap.

---

## Phase 1D — Stripe Webhook Handler Matrix

Handlers registered in `StripeWebhookHandler`:

```1493:1498:backend/app/services/stripe_integration.py
handlers = {
    'checkout.session.completed': self._handle_checkout_completed,
    'invoice.paid': self._handle_invoice_paid,
    'invoice.payment_failed': self._handle_payment_failed,
    'customer.subscription.updated': self._handle_subscription_updated,
    'customer.subscription.deleted': self._handle_subscription_deleted,
}
```

| Event | `users.tier` | `users.subscription_status` | `users.token_balance` | `subscriptions` table |
|-------|----------------|-------------------------------|------------------------|------------------------|
| `checkout.session.completed` (voice_block) | Skip | — | — | — |
| `checkout.session.completed` (family_member) | Specialized | — | — | — |
| `checkout.session.completed` (**pending_signup**) | Via **`finalize_signup`** | Via finalize | Via **`_tier_mapping`** | **Not inserted** |
| `checkout.session.completed` (coach_upgrade) | — | Profile JSON | — | — |
| `checkout.session.completed` (**subscription**, legacy `user_id`) | **UPDATE** tier | **ACTIVE** | **Unchanged** | **INSERT/UPDATE** |
| `checkout.session.completed` (token_pack) | — | — | **Increased** | — |
| `invoice.paid` | — | — | **Unchanged** | **Period update** |
| `invoice.payment_failed` | — | (email/crisis side paths) | — | **PAST_DUE** |
| `customer.subscription.updated` | **UPDATE** | Mapped status | **Unchanged** | **UPDATE** |
| `customer.subscription.deleted` | **TRIAL** downgrade paths | — | **Unchanged** in snippet | **CANCELLED** |

**Gaps:** Tier changes **without** token alignment; **`subscription.updated`** joins **`subscriptions`** — if Stripe-first user **has no row**, update may **silently affect 0 rows** for `subscriptions`, and **`uname`** may be **null** so **`users` may not update**.

---

## Phase 1E — Paula Swain (`paula182`) Forensic Reconstruction

**Source:** Production PostgreSQL via `docker exec nate_postgres` (2026-04-28).

### `users`

- **tier:** `TOP_TIER`
- **subscription_status:** `ACTIVE`
- **token_balance:** `200000` (after remediation)
- **stripe_customer_id:** present (`cus_...`)
- **profile_data:** includes **`tier`: TOP_TIER**, **`stripe_subscription_id`**, **`stripe_customer_id`**, **`subscription_status`**: ACTIVE, **`token_balance`**: 200000
- **`registration_type`:** Not surfaced in the condensed SELECT output; investigation noted empty — **confirm with** `profile_data->>'registration_type'` in a follow-up query if needed.

### `token_transactions`

- **Single row:** `action = adjust`, **amount = 200000**, **balance_before = 0**, **balance_after = 200000**, **initiated_by = DrNevedal1**, **created_at** 2026-04-28.
- **No** row for Stripe checkout or initial grant.

### `subscriptions`

- **0 rows** for this `user_id`.

### `pending_signups`

- Row **`status = completed`**, **`tier = TOP_TIER`**, **`stripe_checkout_session_id` = cs_live_...**, created **2026-04-26**.

### Reconstructed sequence

1. User attempted Stripe-first signup (**multiple expired `pending_signups`** for same username pattern).
2. **Successful** checkout linked to **`pending_signup_id`** → `_handle_pending_signup` → **`finalize_signup`** with **`tier = TOP_TIER`** from pending row (so **`SOVEREIGN_CIRCLE` alias was not the culprit for this account**).
3. **`subscriptions`** was **never** populated by finalize; **`invoice.paid`** / **`subscription.updated`** behavior **does not align** user rows via `subscriptions` the same way as legacy checkout.
4. **Balance discrepancy before manual fix** supports class **“paid tier + missing audit trail + missing subscription row + no monthly/refill contract in code”**; **exact mechanism for `balance_before = 0`** requires **application logs** around INSERT and first bridge sync.

---

## Business Decision Required Before Phase 2 (FIX #4)

**Monthly included tokens** for **STANDARD** / **TOP_TIER** paid subscribers — choose one:

| Option | Behavior |
|--------|----------|
| **(a) Additive** | Grant **N** tokens each billing period **on top of** existing balance (rollover). |
| **(b) Reset** | Set **`token_balance`** to **`TIER_MONTHLY_TOKENS[tier]`** on each invoice period (no rollover). |
| **(c) Top-up** | Increase balance **up to** cap **`TIER_MONTHLY_TOKENS[tier]`** if below cap. |

**Recommended engineering trigger (after decision):** **`invoice.paid`** for subscription invoices (authoritative payment signal), with idempotency keyed by **Stripe invoice id**, plus **`token_transactions`** rows.

---

## Phase 2 — Remediation (BLOCKED — Awaiting Explicit Approval)

Per engagement rules, **no code changes were applied** in this Phase 1 deliverable.

Planned work after approval (reference only):

1. **`backend/app/constants/tiers.py`** — canonical tiers, aliases, initial + monthly maps, **`normalize_tier()`**.
2. **Wire normalize + grants** through **`registration_finalize`**, **`stripe_integration`** (checkout + subscription events), **`bridge_server`**, **`billing` routers**, **`registration_checkout`** as needed.
3. **`monthly_token_grant`** or **`invoice.paid`** hook — per business decision above.
4. **`token_transactions`** for **every** grant (initial, upgrade, monthly, admin).
5. **Backfill script** — query under-granted users; **human review** before execution.
6. **`.cursor/rules/stripe-payment-billing-architecture.mdc`** — document canonical tiers + monthly flow + logging.

**Protected files:** Respect **`main.py`** / **`stripe_integration`** change discipline (large edits → split commits; feature flags if required).

---

## Phase 3 — Test Plan (Post-Implementation)

- Matrix: **each tier ×** direct registration, Stripe checkout, family invite, upgrade.
- DB assertions: **`users.tier`**, **`token_balance`**, **`token_transactions`**, **`subscriptions`** row when applicable.
- Stripe test mode: **`invoice.paid`** produces expected grant + idempotency.
- Paula-class users: **listed + reviewed** before bulk credit.

---

## Files Consulted (Primary)

- `backend/app/services/registration_finalize.py`
- `backend/app/services/stripe_integration.py`
- `backend/app/websocket/bridge_server.py`
- `backend/app/routers/billing.py`
- `backend/app/services/token_usage_agent.py`
- `backend/app/services/drip_scheduler.py`
- `mobile/lib/screens/settings_screen.dart`, `mobile/lib/services/payment_service.dart`
- `backend/migrations/072_token_lab.sql`

---

**End of Phase 1 diagnostic report.**  
**Next step:** Stakeholder **approval** of Phase 2 scope + **monthly grant policy (a/b/c)** → then implementation + Phase 3 verification.
