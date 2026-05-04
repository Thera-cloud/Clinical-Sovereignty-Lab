# Coach Portal — FINANCIALS (Tab 7)

> Status: ACTIVE  
> Last full review: 2026-05-04  
> Next review due: 2026-05-11 (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: needs work  

---

## 1. Purpose (1 sentence)

The FINANCIALS tab lets coaches **refresh** earnings/context via **`coach_get_financials`**, set **session fee** and **payment mode**, **submit a W-9** to **`coach_w9_vault`**, and manage **DOJO Stripe subscriptions** — all via **`bridge_server.py`** WebSocket handlers tied to **`coaching_sessions`**, **`profile_data`**, and Stripe.

---

## 2. UX Acceptance Criteria

These are the conditions a redesign must satisfy. If a code change breaks any of these, reject the change.

- [ ] Loads in under 2 seconds on cellular  
- [ ] First action a coach can take is visible without scrolling  
- [ ] No more than 3 primary CTAs visible at once  
- [ ] Error states have a clear next step (not just "something went wrong")  
- [ ] Loading states never persist beyond 30 seconds without user feedback  
- [ ] Touch targets are at least 44pt  
- [ ] Critical flows work offline or with clear offline state  
- [ ] **Refresh** (`16171`, `_requestFinancials()`, `coach_get_financials` `14383`) sets **`_financialsLoading`** (`4231`) and **always** clears it on success **or** structured failure  
- [ ] **Fee update** (`16237–16254`, `coach_set_fee` `14141`) shows **confirmed** stored value after ack — no silent discard  
- [ ] **Payment mode tiles** (`16286–16333`, `coach_set_payment_mode` `14167`) reflect **exactly one** canonical mode post-round-trip  
- [ ] **W-9 submit** (`coach_submit_w9` `14459`) gives **vault confirmation** or actionable rejection (missing fields, upload failure)  
- [ ] **DOJO subscriptions** (`16499+`, `get_dojo_subscriptions` / `cancel_dojo_subscription` `15574`, `add_dojo_subscription` `15594`) require **confirm** before cancel; success updates list without stale rows  
- [ ] **Stripe / web checkout** flows reachable from coach financial actions on **Flutter Web** — no dead “Manage billing” (`f228353` class)  
- [ ] **Trial / tier expiry** paths that downgrade or gate **COACH_ONLY** (or related) are reflected in financials copy or banners (`65eb7ca` class)  
- [ ] No **PII / tax** surfaces log full W-9 payloads client-side (defense in depth with vault storage)  

---

## 3. UI Components

| Component | Location | Purpose | Notes |
|---|---|---|---|
| Financials tab scaffold | `mobile/lib/updated_screens.dart:16148+` (`_buildFinancialsTab`) | Tab shell | Revenue + settings |
| Refresh control | `mobile/lib/updated_screens.dart:16171` | `_requestFinancials()` | WS `coach_get_financials` |
| Fee editor | `mobile/lib/updated_screens.dart:16237–16254` | `_setCoachFee` | WS `coach_set_fee` |
| Payment mode tiles | `mobile/lib/updated_screens.dart:16286–16333` | `_setPaymentMode` | WS `coach_set_payment_mode` |
| W-9 submit | — | flow in tab | WS `coach_submit_w9` |
| DOJO subscriptions | `mobile/lib/updated_screens.dart:16499+` | `_buildDojoSubscriptionsSection` | list / cancel / add |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:16148+` — `_buildFinancialsTab()`  
- `mobile/lib/updated_screens.dart:16171` — refresh → `coach_get_financials`  
- `mobile/lib/updated_screens.dart:16237–16254` — fee update  
- `mobile/lib/updated_screens.dart:16286–16333` — payment mode tiles  
- `mobile/lib/updated_screens.dart:16499+` — DOJO subscriptions section  
- `mobile/lib/updated_screens.dart:4231` — `_financialsLoading`  
- `mobile/lib/updated_screens.dart:4260` — `_dojoSubsLoading` (DOJO list fetch in this tab)  
- `mobile/lib/updated_screens.dart:4301` — `_dojoBusy` (may gate DOJO actions)  

### Backend WebSocket (`bridge_server.py`)
- `coach_get_financials` — `14383`  
- `coach_set_fee` — `14141`  
- `coach_set_payment_mode` — `14167`  
- `coach_submit_w9` — `14459`  
- `get_dojo_subscriptions` / `cancel_dojo_subscription` — `15574`  
- `add_dojo_subscription` — `15594`  

### Storage / DB
- `coaching_sessions` — revenue/session linkage  
- `coach_w9_vault` — W-9 storage (migration **041** per global inventory)  
- `profile_data` — fee + payment mode fields  
- **Stripe** — subscription objects for DOJO add/cancel paths  

---

## 5. State Variables

| Variable | Type | Set true at | Set false at | Default |
|---|---|---|---|---|
| `_financialsLoading` | bool | `_requestFinancials()` `16171` | WS response handled | false |
| `_dojoSubsLoading` | bool | DOJO list fetch | list done / error | false |
| `_dojoBusy` | bool | cancel/add DOJO action | action complete | false |

---

## 6. WebSocket Messages

| Direction | Type | Trigger | State change | Failure handling |
|---|---|---|---|---|
| → | `coach_get_financials` | Refresh / tab focus | summary model | clear `_financialsLoading`; show error banner |
| → | `coach_set_fee` | Fee save | updated profile snapshot | revert optimistic UI on NACK |
| → | `coach_set_payment_mode` | Tile tap | mode | same |
| → | `coach_submit_w9` | Submit | vault row | never silent fail on tax path |
| → | `get_dojo_subscriptions` | Section load | subscription list | clear `_dojoSubsLoading` |
| → | `cancel_dojo_subscription` | Cancel confirm | remove/update row | Stripe errors explicit |
| → | `add_dojo_subscription` | Add tier | Stripe checkout handoff | handle `f228353` class web parity |

**Critical pairings (must always co-occur):**
- Every financial refresh **must** clear `_financialsLoading`  
- **Cancel subscription** must pair **Stripe cancel** + **list refresh**  
- **W-9** submit success must **not** imply IRS filing — copy must stay precise  

---

## 7. Database Schema

```sql
-- coaching_sessions — tied to coach revenue in coach_get_financials
-- coach_w9_vault — W-9 blobs / metadata (041)
-- users.profile_data — fee + payment_mode keys
-- Stripe — subscription IDs for DOJO SKUs (out-of-DB but authoritative for cancel/add)
```

**Approval gates:** W-9 and tax artifacts may need admin audit — follow compliance policy.  
**Soft delete:** follow `coach_w9_vault` retention; subscriptions follow Stripe cancel semantics.  

---

## 8. Known Bugs (Resolved)

| Date | Commit | Bug | Fix |
|---|---|---|---|
| — | `f228353` | Stripe **checkout/portal blocked on Web** for billing flows | Unblocked Stripe checkout/portal on web |
| — | `65eb7ca` | **Trial billing** gaps — **COACH_ONLY** downgrade on expiry not enforced cleanly | Trial gate with SetupIntent + contact validation + downgrade path |
| — | `c819947` | **Billing leak** in analytics/display layer (internal audit fix) | sealed leak + related hardening in same patch set |
| — | `0aba250` | Regression risk across **coach Stripe flows** | Stripe billing test suite 27/27 incl. coach path |

---

## 9. Anti-Patterns (Reject Without Investigation)

- ❌ **Shipping Flutter Web coach billing entry points that don’t open Stripe** — `f228353`.  
- ❌ **Ignoring trial expiry / tier gates** that leave coaches in impossible payout states — `65eb7ca`.  
- ❌ **Logging or echoing full W-9 payloads** in client logs, support tickets, or non-vault stores.  
- ❌ **`cancel_dojo_subscription` UI without Stripe-round-trip confirmation** — user thinks they canceled but Stripe still bills.  
- ❌ **Clearing `_financialsLoading` only on HTTP 200-equivalent** while WS errors reuse spinner forever.  

**Why this section exists:** money + tax + Stripe triples the blast radius of a silent failure.

---

## 10. Daily Health Checks (run by `coach_portal_daily_check.sh`)

- [ ] WS lines `14383`, `14141`, `14167`, `14459`, `15574`, `15594` still match bridge  
- [ ] `_financialsLoading` still declared at `4231`  
- [ ] DOJO subscription section still begins `16499+`  
- [ ] `coach_w9_vault` migration still present  
- [ ] No new `print()` of tax payloads in Flutter financial flows  

---

## 11. Investigation Cache

1. Read THIS FILE FIRST  
2. Any fee/mode change must be validated against **`coach_set_fee` / `coach_set_payment_mode`** parity tests  
3. Cross-check **Stripe dashboard** SKUs when altering DOJO subscription message handlers  
4. Update §8 when a production billing bug is fixed with commit hash  
5. If REST migration replaces WS for financials, rewrite §6 + §4 in same PR  

**Last full investigation:** 2026-05-04 (spec-only from `_FOUNDATIONAL_SPEC.md` Tab 7)  
**Cost-saved estimate:** TBD after first code-level pass  

---

## 12. Steve Jobs Review

Apply quarterly. The standard is "would Steve ship this."

- [ ] Does the first interaction feel inevitable? **— Debt:** first action unclear: refresh vs change rate vs W-9 vs DOJO  
- [ ] Is anything on this screen unnecessary? **— Debt:** DOJO retail inside **financials** may confuse “my earnings” vs “my training SKUs”  
- [ ] Could a non-technical user complete the primary action without instruction? **— Debt:** payment mode verbs need plain language  
- [ ] Does the empty state teach the value of the tab? **— Debt:** $0 earnings must teach “sessions + fee”, not shame  
- [ ] Does the error state preserve trust? **— Debt:** Stripe 402/decline must never read as “you’re hacked”  
- [ ] Is the most important thing the most prominent thing? **— Debt:** net earnings vs compliance (W-9) vs DOJO subs — pick a hero  

### Logged UX debt (target ship dates)

| Item | Issue | Target |
|------|--------|--------|
| SJ-1 | **WebSocket-only financial snapshot** — no historical chart, weak “why did my balance change?” | 2026-07-01 |
| SJ-2 | **DOJO subscription management embedded in financials** — cognitive load vs dedicated billing surface | 2026-08-01 |
| SJ-3 | **Tax (W-9) adjacent to gamified training purchases** — tone clash; needs calmer subsection | 2026-06-15 |

---

## 13. Cloning This Template (For New Tabs)

See `docs/coach_portal/_PIPELINE_TEMPLATE.md` §13.

---

## 14. Adapter Comments For Cursor

```
Read docs/coach_portal/features/08_financials.md before any investigation.
Source: docs/coach_portal/_FOUNDATIONAL_SPEC.md Tab 7 (FINANCIALS).
All paths are bridge WS today: coach_get_financials 14383, fees 14141, mode 14167, W-9 14459, DOJO subs 15574/15594.
Web Stripe parity is a hard requirement (f228353). Never log W-9 content.
```
