# Family Dependents ($75/mo) + Family Sanctuary Charges — Stripe & Apple IAP Outline

This outline covers: (1) adding the **family dependent add-on** to both Stripe and Apple IAP, (2) ensuring **all Family Sanctuary charges** are defined and used, (3) making the **client Settings → Subscription → Family tab** show a full **billing summary** (recurring + per-session) and a **record of completed Family Sanctuary sessions** (by date/reference).

---

## 1. Canonical list: Family Sanctuary charges

Use this as the single source of truth for copy, APIs, and UI.

### 1.1 Recurring (subscription + add-ons)

| Item | Amount | Notes |
|------|--------|--------|
| Base subscription (Inner Chamber) | $49/mo | Already IAP + Stripe |
| Base subscription (Sovereign Circle) | $149/mo | Already IAP + Stripe |
| **Family add-on 1st paid slot** | **$75/mo** | Dependent / additional member #1 |
| **Family add-on 2nd paid slot** | **$60/mo** | Dependent / additional member #2 |
| **Family add-on 3rd paid slot** | **$45/mo** | Dependent / additional member #3 |
| **Family add-on 4th+ paid slot** | **$30/mo** | Dependent / additional member #4+ |
| Spouse/partner | Free | First one |
| First dependent (e.g. first child) | Free | One free slot |

### 1.2 Per-session (Family Sanctuary session charges)

Canonical four charges (single source of truth in `sanctuary_engine.py`: `SANCTUARY_CHARGE_*`):

| Charge type | Amount | When it applies |
|-------------|--------|------------------|
| **Initial Family Sanctuary charge** | **$20.00** | When the group chat asks for help / session starts (charged to HoH once per session) |
| **Group Coaching** | **$20.00** | When family requests help together — Little Nate generates personalized lines; HoH approval required |
| **Individual coaching (Little Nate de-escalate)** | **$5.00** | When Little Nate is triggered to set in and de-escalate (first per member free, then $5 each) |
| **Get Help (assisted response)** | **$3.00** | Little Nate provides a guide; client can push this to the chat |

- First private coaching per member per session: **FREE**.
- These per-session charges are recorded in sanctuary JSON (`billing.charges[]` with `type`: `BASE_FEE`, `GROUP_COACHING`, `COACHING`, `ASSISTED_RESPONSE`) and in `sanctuary_history/*.json` when a session is ended.

---

## 2. Stripe: Family add-on products

### 2.1 Already in code

- **`stripe_integration.py`**: `FAMILY_TIER_1` ($75), `FAMILY_TIER_2` ($60), `FAMILY_TIER_3` ($45), `FAMILY_TIER_4` ($30) — env vars `STRIPE_PRICE_FAMILY_TIER_1` … `STRIPE_PRICE_FAMILY_TIER_4`.
- **`stripe_billing.py`** (bridge): `FAMILY_PRICING`: DEPENDENT 7500, DEPENDENT_2 6000, DEPENDENT_3 4500, DEPENDENT_4_PLUS 3000 (cents).
- **`billing.py`**: `POST /api/billing/checkout/family-member` creates Stripe Checkout for a family add-on using `family_tier_price_cents(ordinal)` and `FAMILY_TIER_{ordinal}` (or `FAMILY_MEMBER` fallback).

### 2.2 What to ensure

1. **Stripe Dashboard**: Create (if missing) four recurring Price objects:
   - Family Member Add-On 1st — $75/month
   - Family Member Add-On 2nd — $60/month
   - Family Member Add-On 3rd — $45/month
   - Family Member Add-On 4th+ — $30/month  
   Set env vars `STRIPE_PRICE_FAMILY_TIER_1` … `STRIPE_PRICE_FAMILY_TIER_4` to these Price IDs.

2. **Bridge**: When adding a family member with a paid role, the bridge currently uses a single `FAMILY_MONTHLY` price. For tiered pricing, either:
   - Have the bridge call a backend endpoint that creates Checkout with the correct `FAMILY_TIER_{ordinal}` price, or
   - Keep bridge creating one subscription item and have backend/bridge pass the correct price_id based on ordinal (already supported in `stripe_integration.py` via `_stripe_price_for_tier(ordinal)`).

3. **Web flow**: From the Family tab (web), “Add paid member” should call `POST /api/billing/checkout/family-member` with `dependent_username` and `ordinal` (1-based index of paid slot), then redirect to Stripe Checkout. Success/cancel URLs already point to app.sovereignsanctuary.net. The checkout session includes Stripe metadata: `type=family_member`, `hoh_username` (caller), `dependent_username`, `user_id` (dependent’s PostgreSQL `users.id` UUID), and `ordinal`. On `checkout.session.completed`, the main Stripe webhook (`/api/stripe/webhook`) activates the dependent in PostgreSQL, sets tier / `FAMILY_PLAN_ACTIVE` / add-on billing fields, and publishes `nate:user_reload` for the dependent.

---

## 3. Apple IAP: Family add-on subscription

### 3.1 App Store Connect

1. Create **auto-renewable subscriptions** (same subscription group as your main subscriptions, or a dedicated “Family add-ons” group):
   - **Product ID (1st slot)**: e.g. `net.sovereignsanctuary.family_addon_75`
   - **Product ID (2nd slot)**: e.g. `net.sovereignsanctuary.family_addon_60`
   - **Product ID (3rd slot)**: e.g. `net.sovereignsanctuary.family_addon_45`
   - **Product ID (4th+ slot)**: e.g. `net.sovereignsanctuary.family_addon_30`

   Prices: $75, $60, $45, $30 per month respectively.

2. Optional: one product “Family add-on” with one price ($75) and let backend map “first paid slot” to that product; additional slots could be a single “additional member” product at $75 (simplified). For full tiering, use four products as above.

### 3.2 Flutter `PaymentService`

- Add product IDs, e.g.:
  - `familyAddon75`, `familyAddon60`, `familyAddon45`, `familyAddon30`.
- Add to `subscriptionIds` (or a dedicated `familyAddonIds` set) so `purchase()` uses `buyNonConsumable` (subscription).

### 3.3 Backend receipt validation

- In `receipt_validation.py`, extend `PRODUCT_TO_PLAN` (or add a separate map) for family add-ons, e.g.:
  - `net.sovereignsanctuary.family_addon_75` → plan or entitlement key `FAMILY_ADDON_75`
  - (same for _60, _45, _30)
- On successful Apple (or Google) verification for a family-addon product:
  - Resolve `user_id` (head of household) from the request (e.g. from `user_id` in the verify request).
  - Create or update the **dependent** member’s billing record (e.g. in `billing["family_members"]` or in PostgreSQL) with:
    - `family_billing_price_cents`: 7500 / 6000 / 4500 / 3000
    - `family_billing_status`: `active`
    - Store Apple `original_transaction_id` or similar for restore/linking.
  - If your backend stores family membership in PostgreSQL, update the member’s `profile_data` (e.g. `family_billing_price_cents`, `family_billing_status`) and optionally a row in a `family_member_billing` table if you add one.

### 3.4 Client Settings → Family tab (native iOS)

- When the user taps “Invite Family Member” and selects a **paid** role (e.g. “Dependent (2nd)” or “Additional Member”):
  - **Native iOS**: If ordinal is known (e.g. “next paid slot is 1”), call `PaymentService.purchase(familyAddon75)` (or the correct product for that ordinal). On success, backend receipt verification runs and activates the add-on; then refresh family members and billing summary.
  - **Web**: Redirect to Stripe Checkout via `POST /api/billing/checkout/family-member` with `ordinal` and `dependent_username` (server adds `user_id` to session metadata for webhook idempotency). After successful payment, the webhook path above applies so the add-on is active in-app without a silent failure.

---

## 4. Billing summary in Client Settings → Family tab

### 4.1 What the billing summary should show

- **Recurring**
  - Base subscription: $49/mo or $149/mo (from current plan).
  - Spouse/partner: Free.
  - First child: Free.
  - Additional members: line per paid member with amount ($75 / $60 / $45 / $30) and **running total of add-ons**.
  - **Total (recurring):** base + add-ons.

- **Family Sanctuary session charges (optional but recommended)**
  - Either:
    - **Current period (e.g. this month)**: Sum of per-session charges (base fee $20, Assisted Response $3, coaching $5, Group Coaching $20) for the family in that period, **or**
    - **Running balance / last N sessions**: e.g. “Session charges this month: $XX” plus a short breakdown (e.g. “2 sessions, 1 group coaching”).
  - So the user sees that **recurring** (subscription + add-ons) and **per-session** (Family Sanctuary usage) are both accounted for.

### 4.2 Data source for billing summary

- **Recurring**: Already available from:
  - WebSocket `family_members` response: `billing` from `get_family_billing_summary(family_id)` (base_price_cents, members with price_cents, family_addon_cents, total_monthly_cents).
  - REST: today `GET /api/billing/family/members?family_id=` does **not** return `family_billing_price_cents` or `family_role`. Extend the API (see below) so the Family tab can compute (or receive) the same summary from REST.
- **Per-session**: New endpoint or bridge message that returns, for the family, either:
  - Aggregated “session charges this month” (and optionally last month), or
  - List of completed sessions with date + total_charges + reference (sanctuary_id or session date).

### 4.3 Backend changes for billing summary

1. **`GET /api/billing/family/members`**  
   Extend so each member includes:
   - `family_role` (from `profile_data` or users table),
   - `family_billing_price_cents` (from profile or family_member_billing),
   so the Flutter app can compute “Additional members” and “Total” when using REST fallback.

2. **`GET /api/billing/family/billing-summary?family_id=`** (new)  
   Returns:
   - `base_plan`, `base_price_cents`, `base_price_display`
   - `members`: list with `name`, `role`, `price_cents`, `price_display`
   - `family_addon_cents`, `total_monthly_cents`, `total_display`
   - Optionally: `session_charges_this_month` (sum of Family Sanctuary session charges for this calendar month for this family), `session_charges_last_month`, so the UI can show “Family Sanctuary usage this month: $XX”.

3. **Implementation of billing-summary**  
   - If bridge already has `get_family_billing_summary(family_id)`, the REST endpoint can call the same logic (e.g. via an internal call or by reading from the same registry/DB the bridge uses). If billing is in PostgreSQL (e.g. `users.profile_data` for `family_billing_price_cents`), the REST API can compute the summary from `users` where `family_id = $1` and sum add-ons + base from HoH’s plan.

### 4.4 Flutter Family tab (billing_screens.dart)

- When data is loaded via WebSocket `family_members`:
  - If `data['billing']` is present, use it for the “Billing Summary” card: base, member count, spouse/child free, “Additional members” with per-member breakdown (from `billing.members`) and total from `billing.total_display` or `billing.total_monthly_cents`.
- When data is loaded via REST:
  - Prefer `GET /api/billing/family/billing-summary?family_id=` if available; else use `GET /api/billing/family/members` and compute total from `family_billing_price_cents` on each member (requires API to return these fields).
- Add a second card or section: **“Family Sanctuary session charges”**
  - If you add `GET /api/billing/family/session-charges?family_id=&month=` (or include in billing-summary), show “This month: $XX” and optionally “Last month: $XX”.
- Ensure **Restore Purchases** (already in Settings) restores Apple family add-on subscriptions so that after restore, the backend or app re-applies `family_billing_price_cents` / status for the right members.

---

## 5. Record of completed Family Sanctuary sessions

### 5.1 What to show

- In the Family tab, a section **“Completed Family Sanctuary sessions”** (or “Session history”):
  - List entries: **date** (session date or end date), **reference** (e.g. sanctuary_id like `SANC_20260126_001`, or “Session Jan 26, 2026”), and optionally **total_charges** for that session.
- Purpose: user can see when sessions happened and match them to the billing summary.

### 5.2 Data source

- Today completed sessions are stored in **sanctuary_history** as JSON files (e.g. `SANC_20260126_001.json`) with:
  - `session_started_at`, `session_summary` (when ended), `billing.total_charges`, `billing.charges[]`.
- Options:
  - **A. REST endpoint** (recommended): `GET /api/billing/family/sanctuary-sessions?family_id=&limit=20` (or `GET /api/family/sanctuary-sessions`). Backend reads from:
    - A table that stores completed sanctuary sessions (if you add one), or
    - Files under `sanctuary_history/` keyed by family_id (if you store by family_id), or
    - A list of sanctuary IDs for the family and then load each SANC_*.json and return `{ sanctuary_id, date, total_charges, reference }`.
  - **B. WebSocket**: On `sanctuary_get_members` or a new type `family_sanctuary_sessions`, bridge sends back the last N completed sessions for the family (bridge would need to enumerate sanctuary_history or a DB table).

### 5.3 Backend: optional DB table for completed sessions

- To avoid parsing JSON on every request, add a table, e.g. `family_sanctuary_sessions`:
  - `id`, `family_id`, `sanctuary_id`, `started_at`, `ended_at`, `total_charges_cents`, `billed_to_user_id`, `created_at`.
- When a sanctuary session is ended (e.g. in bridge when `sanctuary_complete` is processed), insert one row. Then `GET /api/billing/family/sanctuary-sessions?family_id=` can query this table and return `{ date, sanctuary_id, total_charges, reference }`.

### 5.4 Flutter

- In the Family tab, below the billing summary (and below the member list), add:
  - **“Completed sessions”** (or “Session history”): call `GET /api/billing/family/sanctuary-sessions?family_id=...` (or use WebSocket data if you add it).
  - Render a list: date (formatted), reference (e.g. sanctuary_id or “Session {date}”), and optionally “Charges: $XX.XX”.

---

## 6. Checklist summary

| # | Item | Stripe | Apple IAP | Backend | Flutter (Family tab) |
|---|------|--------|-----------|---------|----------------------|
| 1 | Family add-on $75/mo (1st paid) | Price + env STRIPE_PRICE_FAMILY_TIER_1 | Product e.g. family_addon_75 | Receipt validation → set family_billing_price_cents 7500, status active | Purchase via IAP on iOS; Stripe on web; show in summary |
| 2 | Family add-on $60/$45/$30 (2nd/3rd/4th+) | FAMILY_TIER_2/3/4 + env | Products family_addon_60/45/30 | Same as above for 6000/4500/3000 | Same |
| 3 | Billing summary (recurring) | — | — | GET family/members with family_role + family_billing_price_cents; or GET family/billing-summary | Use billing from WS or REST; show base + add-ons + total |
| 4 | Family Sanctuary session charges (this month) | — | — | billing-summary or session-charges returns session_charges_this_month (sum) | Show “Session charges this month: $XX” in Family tab |
| 5 | Completed sessions list (date + reference) | — | — | GET family/sanctuary-sessions or bridge message; optional table family_sanctuary_sessions | “Completed sessions” list with date, reference, optional total_charges |

---

## 7. File reference (where to implement)

- **Stripe**: `backend/app/services/stripe_integration.py` (PRICES, FAMILY_TIER_*; `checkout.session.completed` → `activate_family_member_from_stripe_checkout` in `registration_finalize.py` when `metadata.type=family_member`), `backend/app/websocket/stripe_billing.py` (FAMILY_PRICING, add_family_member_billing), `backend/app/routers/billing.py` (`POST /api/billing/checkout/family-member` with metadata `type`, `hoh_username`, `dependent_username`, `user_id`, `ordinal`).
- **Apple IAP**: `mobile/lib/services/payment_service.dart` (product IDs, purchase), `backend/app/routers/receipt_validation.py` (PRODUCT_TO_PLAN or family-addon map, apply family_billing_price_cents after verify).
- **Billing summary API**: `backend/app/routers/billing.py` (extend get_family_members; add get family/billing-summary and optional family/session-charges).
- **Sanctuary sessions API**: New in `billing.py` or `client_data_api.py`, e.g. GET family/sanctuary-sessions; optional migration for `family_sanctuary_sessions` table; bridge: write row when session ends.
- **Flutter Family tab**: `mobile/lib/screens/billing_screens.dart` (FamilyManagementScreen: use billing from WS/REST, add “Session charges this month”, add “Completed sessions” list, and for “Add paid member” on iOS call PaymentService for family add-on product).

This outline gives you a single reference to implement family dependents ($75/mo and tiers) in both Stripe and Apple, and to surface all Family Sanctuary charges and completed session records in the client Settings → Subscription → Family tab billing summary.
