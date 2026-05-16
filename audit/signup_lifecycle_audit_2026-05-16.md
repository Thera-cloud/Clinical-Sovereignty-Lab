# Signup & Lifecycle Audit — 2026-05-16

Read-only. Evidence-cited. No fixes proposed.

---

## Tier Definitions (Canonical Source: `backend/app/constants/tiers.py`)

| Tier constant | DB value | Initial tokens | Monthly tokens | Chat access |
|---|---|---|---|---|
| `TIER_COACH_ONLY` | `COACH_ONLY` | 0 | 0 | No |
| `TIER_TRIAL` | `TRIAL` | 10,000 | 0 | Yes |
| `TIER_STANDARD` | `STANDARD` | 50,000 | 50,000 | Yes (Inner Chamber) |
| `TIER_TOP_TIER` | `TOP_TIER` | 200,000 | 200,000 | Yes (Sovereign Sanctuary) |
| `TIER_DEPENDENT` | `DEPENDENT` | 5,000 | 5,000 | Yes |
| `TIER_SPOUSE` | `SPOUSE` | 5,000 | 5,000 | Yes |
| `TIER_COACH` | `COACH` | 50,000 | 0 | Gated |

Sources: `tiers.py:49–76`

---

## Summary Table

| Tier | Dim 1 Info | Dim 2 Tokens | Dim 3 Billing | Dim 4 Upgrade | Dim 5 Deductions | Dim 6 Purchase | Dim 7 Dependents | Dim 8 Family ID | Dim 9 Family Billing |
|---|---|---|---|---|---|---|---|---|---|
| **Coach-only** | FAIL | PASS | N/A | N/A | PASS | N/A | N/A | N/A | N/A |
| **Trial** | FAIL | FAIL | FAIL | FAIL | FAIL | N/A | N/A | N/A | N/A |
| **Inner Chamber** | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | N/A | N/A | N/A |
| **Sovereign Sanctuary** | FAIL | DEGRADING | FAIL | N/A | FAIL | FAIL | FAIL | FAIL | FAIL |
| **Dependents** | FAIL | FAIL | FAIL | N/A | FAIL | N/A | FAIL | FAIL | FAIL |

**Pass count by tier:** Coach 2/4, Trial 0/7, Inner Chamber 0/7, Sovereign Sanctuary 0/8, Dependents 0/7

---

## Dimension 1: Information Capture at Signup

### Coach-only — FAIL

**Expected:** `joined_date`, `consent_version`, `hardware_id` present for all coach accounts. No Stripe fields required (coaches don't pay).

**Found (query: `SELECT username, tier, subscription_status, joined_date, consent, cert, has_hwid FROM users WHERE role='COACH'`):**

```
audit_addiction_coach_01 | joined=NULL | consent=NULL | cert=NULL | has_hwid=t
audit_coach              | joined=NULL | consent=v13.0_2026 | cert=NULL | has_hwid=t
```

Production coaches (`CoachN`, `Wilsnaw`, `freeindeed`, `hector12`, `hnevedal`, `sweet2noend`, `yahwehsdaughter`) all have `joined_date` and `consent_version`.

**Gap:** `audit_addiction_coach_01` missing `joined_date` and `consent_version`. These are test-infrastructure accounts but they are active and receive coaching sessions.

**Severity:** Degrading (test accounts only; production coaches complete).

---

### Trial — FAIL

**Expected:** `joined_date`, `consent_version`, `trial_end_date` (14 days from signup), `hardware_id` present. No Stripe customer ID required for pure trial.

**Found (query: `SELECT username, subscription_status, trial_end_date, joined_date, consent_version, stripe_cust, has_hwid FROM users WHERE tier='TRIAL'`):**

```
Mbryce       | trial_end=NULL  | joined=NULL  | consent=v13.0_2026 | stripe_cust=NULL
Shelbylynne  | trial_end=NULL  | joined=2026-04-02 | consent=v13.0_2026 | stripe_cust=NULL
hmholod      | trial_end=2026-03-04 | joined=2026-02-18 | consent=v13.0_2026 ✓
katdenco     | trial_end=2026-03-10 | joined=2026-02-24 | consent=v13.0_2026 ✓
miggs        | trial_end=2026-03-13 | joined=2026-02-27 | consent=v13.0_2026 ✓
wilsnaw      | trial_end=2026-02-22 | joined=2026-02-15 | consent=v13.0_2026 ✓
```

**Gaps:**
- `Mbryce`: `trial_end_date` is NULL and `joined_date` is NULL. This is a real client, not a test account.
- `Shelbylynne`: `trial_end_date` is NULL despite having a `joined_date`. `subscription_status=ACTIVE` for a `TIER_TRIAL` user is also anomalous.

**Where:** `registration_finalize.py:162–200` sets `trial_end_date` as `joined_date + 14 days`. NULL here means the signup path completed without reaching that block, or the profile was created by an alternate path.

**Severity:** Blocking for `Mbryce` and `Shelbylynne` (no trial expiry tracking; conversion path cannot be driven by NULL date).

---

### Inner Chamber (STANDARD) — FAIL

**Expected:** `joined_date`, `subscription_start_date`, `consent_version`, `stripe_customer_id`, `stripe_subscription_id`, `hardware_id`.

**Found (query: `SELECT username, tier, subscription_status, stripe_cust, stripe_sub, trial_end, consent, joined, sub_start FROM users WHERE tier IN ('STANDARD') AND role='CLIENT'`):**

```
ALL 10 STANDARD users: stripe_cust=NULL, stripe_sub=NULL
HOLLISA, Williamhenderson, sandrahenderson: trial_end_date still set (stale from TRIAL)
audit_addiction_test_01, audit_test_2026q2_p2a, test_v14_behavior: joined=NULL, sub_start=NULL, consent=NULL
```

**Gaps:**
1. **No Stripe customer ID or subscription ID for any STANDARD client.** Every STANDARD user shows `subscription_status=ACTIVE` with empty Stripe fields. Either all were manually admin-upgraded (bypassing Stripe) or the Stripe link was created but not stored in `profile_data`.
2. **Stale `trial_end_date`** on 3 users who graduated from TRIAL. The trial upgrade path does not clear `trial_end_date`.
3. **3 audit/test accounts** missing `joined_date`, `sub_start`, `consent_version`.

**Where:** Stripe customer creation is in `stripe_integration.py:_handle_checkout_completed`. The `profile_data` update writes `stripe_customer_id` only when a Stripe checkout completes (`stripe_integration.py:1740+`). Since no Stripe IDs are stored, these users bypassed Stripe checkout entirely.

**Severity:** Blocking for Stripe-dependent flows (renewal, receipt, upgrade via Stripe). Degrading for all others (they can currently chat).

---

### Sovereign Sanctuary (TOP_TIER) — FAIL

**Expected:** Same as Inner Chamber plus `stripe_customer_id`, `stripe_subscription_id`, `joined_date`.

**Found:**

```
ALL TOP_TIER users: stripe_cust=NULL, stripe_sub=NULL
EricBando: joined=NULL, sub_start=NULL
SelenaBando: joined=NULL, sub_start=NULL
client1b: consent=v12.6_2026_FINAL (stale, not v13.0_2026)
```

**Gaps:** Same root cause as Inner Chamber. No Stripe IDs stored. Two users missing `joined_date`.

**Severity:** Blocking for Stripe-dependent flows; Degrading for stale consent version.

---

### Dependents — FAIL

**Expected:** `joined_date`, `consent_version`, `hardware_id`, `family_id`, `family_role` (e.g., `child`, `spouse`), `stripe_customer_id` on HoH (not dependent).

**Found (query: `SELECT username, tier, subscription_status, token_balance, family_id, family_role, stripe_cust, stripe_sub FROM users WHERE tier IN ('DEPENDENT','SPOUSE')`):**

```
zacks99 | DEPENDENT | FAMILY_PLAN_ACTIVE | 50000 | family_id=de4f3fa6... | family_role=NULL | stripe_cust=NULL | stripe_sub=NULL
```

Only 1 DEPENDENT user exists in production. `family_role` is not populated (should be `child` or `spouse`).

**Severity:** Degrading (account functional, but family_role missing prevents role-based safety rule enforcement).

---

## Dimension 2: Chat Access with Proper Tokens

### Coach-only — PASS

`TIER_COACH_ONLY` initial grant = 0 (`tiers.py:53`). Pure coach accounts (`CoachN`, `audit_addiction_coach_01`, `audit_coach`) all have `token_balance=0`, `pd_token_balance=0`. No drift. Chat is not expected for pure coach accounts.

Coaches with token balances (`Wilsnaw`, `freeindeed`, `hnevedal`, `sweet2noend`, etc.) are dual-role accounts; their balances track correctly with `token_balance = subscription_token_balance = pd_token_balance`.

---

### Trial — FAIL

**Expected:** `token_balance = 10,000`, `profile_data.token_balance = 10,000`, `split_balances` returns 10,000 usable.

**Found:**

```
Mbryce       | token_balance=10,000 ✓  | pd=10,000 ✓
miggs        | token_balance=10,000 ✓  | pd=10,000 ✓
Shelbylynne  | token_balance=50,000    | pd=50,000   ← TRIAL tier but STANDARD balance
hmholod      | token_balance=80,000    | pd=80,000   ← adjusted from reconciliation
katdenco     | token_balance=50,000    | pd=50,000   ← adjusted
wilsnaw      | token_balance=80,000    | pd=80,000   ← adjusted
```

**Gaps:**
- `Shelbylynne`, `hmholod`, `katdenco`, `wilsnaw` carry balances far above the TRIAL tier initial grant of 10,000. These were reconciliation adjustments (prior session) but the underlying issue is that the initial grant is not consistently enforced at signup. No `initial_grant` row exists in `token_transactions` for any user (all `total_granted=0` from ledger query), so there is no audit trail for how each balance was established.

**Where:** Initial grant is set directly via `UPDATE users SET token_balance = $1` in `registration_finalize.py` without a corresponding `INSERT INTO token_transactions` ledger row.

**Severity:** Degrading for adjusted users (they can chat, but ledger cannot reconcile grants). Would be blocking for new users if initial grant fails silently.

---

### Inner Chamber (STANDARD) — FAIL

**Expected:** `token_balance = 50,000` (initial grant; up to 200k with monthly top-ups), `profile_data.token_balance` matching, `split_balances` returns positive.

**Found:**

```
HOLLISA          | token_balance=0  | sub_bucket=10,000  → BLOCKING (can't chat)
Williamhenderson | token_balance=0  | sub_bucket=10,000  → BLOCKING
sandrahenderson  | token_balance=0  | sub_bucket=10,000  → BLOCKING
tomrip           | token_balance=0  | sub_bucket=0       → BLOCKING
N3WdayBill       | token_balance=200,000 ✓ (adjusted beyond initial)
N3WdayLisa       | token_balance=200,000 ✓
blakebarnes      | token_balance=200,000 ✓
```

Also — from profile_data drift query: `LetsGoLisa` (TOP tier, placed here as nearest equivalent): `pd_drift = -21,290`. For STANDARD clients: `HOLLISA`, `Williamhenderson`, `sandrahenderson` have `pd_token_balance = 0` matching the column, but `subscription_token_balance = 10,000`. Column vs bucket disagrees — column is the authority (`token_balance_policy.py`), but the bucket nonzero is confusing.

**Severity:** Blocking for 4 STANDARD users (0 token balance, no chat access). Degrading for bucket drift.

---

### Sovereign Sanctuary (TOP_TIER) — DEGRADING

**Expected:** `token_balance = 200,000` (initial or accumulated), matching `profile_data`.

**Found (ledger drift query):**

```
sweet2noend@yahoo.com | token_balance=484,940  | last_ledger=425,790 | drift=+59,150
LetsGoLisa (TOP)      | token_balance=319,180  | last_ledger=336,200 | drift=-17,020
christinabarnes       | token_balance=200,000  | last_ledger=193,730 | drift=+6,270
jaimecarpenter        | token_balance=100,000  | last_ledger=97,040  | drift=+2,960
client1               | token_balance=91,690   | last_ledger=93,430  | drift=-1,740
EricBando             | token_balance=197,590  | last_ledger=198,360 | drift=-770
```

Also pd_drift (from earlier session): `EricBando -2,410`, `client1 -2,140`.

Most TOP_TIER users can chat. However:
- `sweet2noend@yahoo.com` balance 484,940 exceeds the 200,000 TOP_TIER initial grant; ledger drift is +59,150 (column > latest ledger balance by 59k).
- Profile_data drift for 2 users means pd shows a different value than the column.

**Severity:** Degrading (users can chat; drift won't block). `LetsGoLisa` (TOP tier) has column higher than ledger by 17k, which means column may overstate available balance.

---

### Dependents — FAIL

**Expected:** `token_balance = 5,000` per `TIER_DEPENDENT` initial grant (`tiers.py:55`).

**Found:**

```
zacks99 | DEPENDENT | token_balance=50,000
```

`zacks99` has 50,000 tokens — 10× the TIER_DEPENDENT initial grant of 5,000. This is likely from an admin adjust, not a controlled grant. Profile_data matches (`pd=50,000`), so no drift. However, the initial grant was never enforced at the correct amount.

**Severity:** Degrading (over-granted, can chat, but tier definition not enforced).

---

## Dimension 3: Billing Flow Correctness

### Trial — FAIL

**Expected:** Trial period tracked with `trial_end_date = joined_date + 14 days`. When expired: `subscription_status` transitions to `TRIAL_EXPIRED` or similar; conversion path prompts upgrade.

**Found:**

```
hmholod   | trial_end=2026-03-04 | subscription_status=ACTIVE  ← expired 73 days ago, still ACTIVE
katdenco  | trial_end=2026-03-10 | subscription_status=ACTIVE  ← expired 67 days ago, still ACTIVE
miggs     | trial_end=2026-03-13 | subscription_status=ACTIVE  ← expired 64 days ago, still ACTIVE
wilsnaw   | trial_end=2026-02-22 | subscription_status=ACTIVE  ← expired 83 days ago, still ACTIVE
Mbryce    | trial_end=NULL       | subscription_status=TRIAL_ACTIVE
Shelbylynne | trial_end=NULL     | subscription_status=ACTIVE
```

4 of 6 real trial users have expired `trial_end_date` but remain `ACTIVE`. No automated status transition exists. Trial conversion path (`/api/billing/checkout`) is available in code but not triggered automatically.

**Where:** No background agent or cron job enforces trial expiry in the current service registry (checked `service-health-49-49.mdc` and `main.py` service checks — no `trial_expiry_agent` exists).

**Severity:** Blocking for revenue (expired trials continue to use platform for free indefinitely).

---

### Inner Chamber — FAIL

**Expected:** Stripe subscription created and active for all STANDARD clients; subscription product = Inner Chamber price (`STRIPE_PRICE_INNER_CHAMBER`).

**Found:** 0 of 10 STANDARD clients have `stripe_customer_id`. All show `subscription_status=ACTIVE` set manually, without Stripe backing.

```sql
-- Evidence: all Stripe IDs null
SELECT COUNT(*) FROM users WHERE tier='STANDARD' AND role='CLIENT'
  AND profile_data->>'stripe_customer_id' IS NOT NULL;
-- Result: 0
```

`STRIPE_PRICE_INNER_CHAMBER` and `STRIPE_PRICE_INNER_CHAMBER_ANNUAL` are defined in `.env` (verified from earlier session context) but were never used for these users.

**Severity:** Blocking for subscription renewal, payment failure handling, and any Stripe webhook-driven state change.

---

### Sovereign Sanctuary — FAIL

Same pattern as Inner Chamber. All 12 TOP_TIER clients: `stripe_customer_id=NULL`, `stripe_subscription_id=NULL`. `subscription_status=ACTIVE` set directly.

**UNVERIFIED — console access required:** Whether any Stripe subscription exists for these users via direct Stripe dashboard lookup. Based on DB evidence, none are linked.

**Severity:** Blocking (same as Inner Chamber).

---

### Dependents — FAIL

**Expected:** Dependent's HoH (`paula182`) has a Stripe subscription that includes the family plan tier cost. First dependent is free; subsequent dependents bill per `_family_tier_price_cents()`.

**Found:** `paula182` (HoH of `zacks99`) has `stripe_customer_id=NULL`. No Stripe subscription recorded for the family plan.

**Where:** `registration_finalize.py:355–388` describes the family pricing model. `finalize_paid_dependent_signup()` is called from the webhook to create Stripe charges for paid dependents. But if the HoH has no Stripe customer, this path cannot complete.

**Severity:** Blocking (HoH cannot be billed for family plan without Stripe customer).

---

## Dimension 4: Upgrade Handling

### Trial → Inner Chamber — FAIL

**Expected:** User can self-service upgrade from TRIAL to STANDARD via `/api/billing/checkout`; Stripe checkout created; on payment, `subscription_status`, `tier`, and token balance update; profile reflects `plan_changed_at`.

**Found:**
1. `/api/billing/checkout` endpoint exists and creates a Stripe checkout session for upgrades.
2. **The `/api/billing/upgrade` (`upgrade_subscription`) endpoint is restricted to `role in ('ADMIN','COACH')` only** (`billing.py:481–494`). Self-service users must use checkout — but there is no guarantee the checkout path runs for the currently active trial users since none have Stripe IDs.
3. `upgrade_subscription` uses `safe_balance = max(current_balance, plan_tokens)` — this prevents token loss but does NOT add an incremental grant or write a `token_transactions` record for the new allocation. No ledger evidence of upgrade token grants will exist.
4. No automated trial→paid conversion trigger exists. A user must initiate the upgrade themselves or an admin must act.

**Where:** `billing.py:520–535` (safe_balance logic), `billing.py:537–554` (Stripe modification — silently skips if no `stripe_customer`).

**Severity:** Degrading (code path exists but Stripe update silently fails for users without `stripe_customer_id`; no `token_transactions` record for upgrade grant).

---

### Inner Chamber → Sovereign Sanctuary — FAIL (same root)

Same issue: Stripe subscription modification at `billing.py:522–536` silently skips (`stripe_updated = False`) when `stripe_customer` is None — which it is for all current STANDARD users.

**Severity:** Degrading (upgrade changes PG tier and tokens but Stripe subscription is not updated).

---

## Dimension 5: Token Balance Measurement and Deductions

### All Tiers — FAIL

**Critical systemic finding:** **No `initial_grant` rows exist in `token_transactions` for any user.**

```sql
SELECT action, COUNT(*) FROM token_transactions GROUP BY action;
-- Result:
-- adjust  47
-- deduct  1982
-- refund  168
-- usage   37
-- (no initial_grant, no purchase rows)
```

Every token balance was established by a direct `UPDATE users SET token_balance = $1` (in `registration_finalize.py`) without a corresponding ledger entry. This means:
- The ledger cannot reconcile "what was granted" vs "what was used"
- Drift detection (initial_grant - deductions ≠ current balance) is impossible for the grant side

**Ghost deduction pattern (from `balance_after` drift query):**

```
Williamhenderson | token_balance=0 | last_ledger_balance=9,230  | drift=-9,230
LetsGoLisa       | token_balance=319,180 | last_ledger=336,200    | drift=-17,020
sweet2noend@yahoo| token_balance=484,940 | last_ledger=425,790    | drift=+59,150
```

`Williamhenderson` column=0 but ledger shows 9,230 was the last recorded balance — meaning a deduction drove the column to 0 but the WHERE clause in `_atomic_deduct` (`WHERE token_balance >= amount`) may have failed silently, leaving the ledger `balance_after` stale.

`sweet2noend@yahoo.com` column is 59,150 MORE than the last ledger entry — this means the column was bumped (by an `adjust` transaction or a upsert) after the last `deduct` log, leaving the ledger behind.

**Where:**
- `bridge_server.py:_atomic_deduct` — conditional UPDATE + unconditional ledger INSERT
- `user_store.py:upsert_user` — can overwrite `token_balance` independently of ledger

**Severity:** Blocking for `Williamhenderson` and `sandrahenderson` and `HOLLISA` (token_balance=0, cannot chat). Degrading for ledger-column mismatch users.

---

## Dimension 6: Token Purchase Flow

### Inner Chamber and Sovereign Sanctuary — FAIL

**Expected:** Users can purchase token packs via Stripe one-time checkout; `purchased_token_balance` increases; `token_transactions` row with `action=purchase` inserted.

**Code path verified:**
- `GET /api/billing/token-packs` lists 4 packs (Light 15k/$3, Standard 50k/$7, Power 150k/$20, Ultimate 1M/$125) — endpoint exists.
- `POST /api/billing/token-packs/purchase` creates Stripe checkout — endpoint exists.
- `stripe_integration.py:1889–1951` handles `checkout.session.completed` with `type=token_pack`, updates `purchased_token_balance`, inserts `token_transactions` row with `action=purchase, source=token_pack`.
- Stripe price IDs are configured in `.env`: `STRIPE_PRICE_TOKEN_LIGHT`, `STANDARD`, `POWER`, `ULTIMATE`.

**Found in production:**

```sql
SELECT COUNT(*) FROM token_transactions WHERE action='purchase' OR source='token_pack';
-- Result: 0
```

Zero token pack purchases have ever completed end-to-end. This could mean:
1. No user has attempted a purchase (possible given pre-launch state), OR
2. Stripe webhook for `token_pack` checkouts is not reaching the backend.

**UNVERIFIED — console access required:** Stripe dashboard webhook delivery logs for `checkout.session.completed` events to the backend.

**Severity:** UNVERIFIED for webhook (could be blocking if webhook isn't wired). No purchases in ledger.

---

## Dimension 7: Adding Dependents/Spouse

### Sovereign Sanctuary — FAIL

**Expected:** HoH on TOP_TIER can add dependents; each gets own `hardware_id`, `user` row, `family_id`, `family_role`; 1st dependent free; subsequent billed to HoH via Stripe; age-based safety rules enforced.

**Found:**

1. **Only 1 DEPENDENT user exists** (`zacks99`). No SPOUSE accounts. No child accounts with `tier=DEPENDENT` or `tier=SPOUSE` beyond this one.
2. **`family_role` is NULL** on `zacks99`. The field is written by `_build_dependent_profile` in `registration_finalize.py` but was either not set or cleared by a subsequent upsert.
3. **16 of 20 families have `head_of_household_id = NULL`** (from family orphan query). This means families were created via the HoH's initial signup path (`registration_finalize.py:422–434` creates a `families` row), but the link back was never completed.
4. **`is_minor` / date-of-birth** field: `zacks99` has no `dob` in `profile_data`. The `_compute_is_minor()` function in `registration_finalize.py:458–466` requires a DOB. Without it, `is_minor=False` and age-based safety rules do not apply.

**Where:** `registration_finalize.py:417–448` (`_ensure_family_row`), `registration_finalize.py:458+` (`_build_dependent_profile`).

**Severity:** Blocking (no family flow actually completes end-to-end in production beyond `zacks99`). Degrading for missing `family_role` and `is_minor`.

---

## Dimension 8: Family Sanctuary Access and Family ID Linkage

### Sovereign Sanctuary — FAIL

**Expected:** All family members linked via `family_id`; all can access Family Sanctuary; `process_sanctuary_message()` gates on TOP_TIER.

**Found:**

1. **16 of 20 families have NULL `head_of_household_id`** (query evidence above). A family with no HoH cannot pass the Sanctuary access check that gates on `is_top` (TOP_TIER) for the HoH.

2. **4 families have a valid HoH link** (`FAM_9A6BF65A`=paula182, `FAM_00B95B75`=client1b, `FAM_1834DACF`=client1, `FAM_0F708896`=LetsGoBill). For these families, Family Sanctuary should be accessible since HoH is TOP_TIER.

3. **1 family with 0 members** (`FAM_B59EA9D5`) — orphaned row.

4. **Cross-member crystal recall and family session data** flows through `process_sanctuary_message` using per-member `hardware_id` loops (`bridge_server.py:9508–9540`). This works for families where members have valid `family_id`.

**Where:** `bridge_server.py:2927` — `"family_sanctuary": is_top`. Registration creates `families` row but NULL HoH blocks all downstream use.

**Severity:** Blocking for 16/20 families. PASS for the 4 families with complete linkage (paula182, client1b, client1, LetsGoBill).

---

## Dimension 9: Family Sanctuary Billing to HoH

### Sovereign Sanctuary — FAIL

**Expected:** HoH's Stripe subscription reflects family plan; dependents have no separate subscription; token usage tracked per member, billed to HoH.

**Found:**

1. **HoH `paula182` has no `stripe_customer_id`** — no Stripe subscription to modify when `zacks99` was added.
2. **`zacks99` has no `stripe_customer_id` or `stripe_subscription_id`** — confirming dependent accounts correctly do not carry their own Stripe billing, but the HoH billing is also missing.
3. **`zacks99.subscription_status = FAMILY_PLAN_ACTIVE`** — this status was set in DB but there is no Stripe event that created it.
4. **Token usage on `zacks99`** is not pooled to `paula182.token_balance`; each account has its own balance. The policy per code (`bridge_server.py:9846`) is that sanctuary AI usage is billed to `hoh_id`. But if the HoH's `token_balance` is authoritative for Sanctuary consumption, this is separate from `zacks99`'s own chat token balance.

**Where:** `registration_finalize.py:355–360` (pricing comment: 1st dependent FREE), `stripe_integration.py:_handle_checkout_completed` (family plan checkout handling). Without HoH Stripe customer, `finalize_paid_dependent_signup` cannot create Stripe subscription modifications.

**Severity:** Blocking (HoH not billed; family billing chain is broken end-to-end).

---

## Cross-Cutting Failures

### F-A: No Stripe Customer IDs Stored (Affects Dims 1, 3, 4, 6, 9)

**All paid-tier clients (STANDARD, TOP_TIER, DEPENDENT)** have `profile_data.stripe_customer_id = NULL`. Every user classified as `ACTIVE` with a paid tier was manually upgraded via the admin-only endpoint (`billing.py:upgrade_subscription`) which bypasses Stripe, or the Stripe ID was created but not written back to `profile_data`.

**Root cause:** The `_handle_checkout_completed` webhook handler in `stripe_integration.py` stores the Stripe customer ID when a checkout completes. Since no Stripe IDs are present, either: (a) no paid users went through Stripe checkout, or (b) the webhook was not received/processed. All subscription-dependent lifecycle events (renewal, payment failure, upgrade) are dead for these users.

**Affected users:** All 10 STANDARD + all 12+ TOP_TIER clients.

---

### F-B: No `initial_grant` in `token_transactions` (Affects Dim 2, 5 for all tiers)

Token grants at signup and at tier change are applied directly to `users.token_balance` without a ledger row. This makes it impossible to audit "what was granted" vs "what was consumed" and prevents drift detection from the grant side.

**Affected:** All users. Confirmed by `SELECT COUNT(*) FROM token_transactions WHERE action='initial_grant'` = 0.

---

### F-C: `subscription_status` Not Enforced at Trial Expiry (Affects Dim 3 Trial)

4 trial users with expired `trial_end_date` (73–83 days past expiry) remain `ACTIVE`. No enforcement mechanism exists (no cron, no background agent, no webhook-driven expiry).

---

### F-D: 16/20 Families Missing `head_of_household_id` (Affects Dims 7, 8, 9)

The `families` table is populated during signup but the `head_of_household_id` column is only backfilled if the code path in `_ensure_family_row` runs (`registration_finalize.py:439–447`). For 16 families it did not run or the UUID was not written, leaving orphaned family records.

---

### F-E: Bucket Split Drift Causes Silent Chat Block (Affects Dim 2, 5 for STANDARD)

`HOLLISA`, `Williamhenderson`, `sandrahenderson` all have `token_balance=0` but `subscription_token_balance=10,000`. The `split_balances_from_profile` function (`token_balance_policy.py`) uses `token_balance` as authoritative when it's nonzero; at 0, it delegates to buckets. But if the column is 0 and the bridge's `_atomic_deduct` uses the column, these users cannot chat.

---

## Appendix: Key Evidence Sources

| Evidence | Source |
|---|---|
| Tier definitions | `backend/app/constants/tiers.py:49–76` |
| Family pricing model | `backend/app/services/registration_finalize.py:355–388` |
| `initial_grant` absence | `SELECT action, COUNT(*) FROM token_transactions GROUP BY action` → no initial_grant rows |
| Stripe ID absence | `SELECT profile_data->>'stripe_customer_id' FROM users WHERE tier IN ('STANDARD','TOP_TIER')` → all NULL |
| Trial expiry non-enforcement | `SELECT username, trial_end_date, subscription_status FROM users WHERE tier='TRIAL'` → 4 expired, still ACTIVE |
| Family HoH null | `SELECT family_code, head_of_household_id FROM families WHERE head_of_household_id IS NULL` → 16 rows |
| Upgrade endpoint admin-gate | `backend/app/routers/billing.py:494` — `if role not in ("ADMIN","COACH"): raise HTTPException(403)` |
| Token pack purchase ledger | `SELECT COUNT(*) FROM token_transactions WHERE action='purchase'` → 0 |
| Bucket split blocking | `SELECT token_balance, subscription_token_balance FROM users WHERE tier='STANDARD' AND token_balance=0` → HOLLISA, Williamhenderson, sandrahenderson, tomrip |
| Ledger column drift | `token_balance - last balance_after`: Williamhenderson -9,230; LetsGoLisa -17,020; sweet2noend +59,150 |
