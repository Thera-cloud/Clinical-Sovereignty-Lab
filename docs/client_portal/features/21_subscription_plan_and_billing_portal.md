# Client Portal — Subscription plan & billing portal

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§B SUBSCRIPTION** (`2519`). Gate `!_isCoachOnly` — `2518` (inventory §H). Plan / token / usage — `2521–2523`. Pending downgrade — `2525–2547` (`pending_plan`). **Change Plan** — `2549–2561` → `_showChangePlanSheet` — `1092` (**E11**). **Manage Subscription** (Stripe customer portal) — `2563–2575` → `_openBillingPortal` — `1070` (**E10**). `PaymentMethodsScreen` — `2580–2582` (**G31**). Quick links — `2578–2602` (Family / Coaching → specs **20**, **22**). `_PaymentHistoryWidget` — `2604`.

**Foundational:** `_FOUNDATIONAL_SPEC.md` §**3 row 20** — `settings_screen.dart:2520–2605`, REST / Stripe (`PaymentMethodsScreen` at `2580–2582`, `_showChangePlanSheet`, `_openBillingPortal`; finer portal lines **TBD** in foundational pass). Token/plan display — `2237–2241`.

**Plan:** `_PHASE_3_PLAN.md` **spec 21** (row **20** UI + portal + change-plan + **E10**, **E11**, **G31**). Prefix **21_**.

---

## 1. Purpose (1 sentence)

In **Settings**, show **eligible CLIENT** users the **SUBSCRIPTION** block (`2519`) — plan/token summary, **`pending_plan`** banner, **Change Plan** (**E11** / **`1092`**), Stripe **billing portal** (**E10** / **`1070`**), **`PaymentMethodsScreen`** (**G31** / **`2580–2582`**), **`_PaymentHistoryWidget`** (**`2604`**), plus **Payments / Family / Coaching** row (**`2578–2602`**), gated by **`!_isCoachOnly`** (**`2518`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §**3 row 20**, §**6**, §**8**; `_TAB_INVENTORY_2026-05-05.md` §**B SUBSCRIPTION**, §**H**; `_PIPELINE_TEMPLATE.md` §**2**.

- [ ] Section **`2519`** visible **only** when **`!_isCoachOnly`** — **`2518`**; hidden state is intentional, **not** a silent **500**
- [ ] Plan / token / usage — **`2521–2523`** — matches **Stripe + profile** truth (**TBD** mapping); returning from portal refreshes headline values (**TBD**)
- [ ] **`2525–2547`** — when **`pending_plan`** set, messaging is neutral, actionable (**Change Plan** + **Manage Subscription** paths), **not** hopeless dead-air only
- [ ] **E11** — `2549–2561` / `1092` — loading / cancel / Stripe failure visible; ≤**30s** or **retry**; hosted flow cancel covered (**TBD**)  
- [ ] **E10** — `2563–2575` / `1070` — URL open **works** **or** user sees explained failure (`8c2a768` class: **no silent** no-op)
- [ ] **G31** — **`2580–2582`** — REST auth survives **Bearer / Redis propagation** lag (**`_PIPELINE_TEMPLATE.md`** §**2**) — avoid **dashboard** kick-out loops
- [ ] **`_PaymentHistoryWidget`** (**`2604`**) — **empty** roster ≠ **masked** fetch error
- [ ] Primary CTAs — touch targets ≥ **44pt** (**Change Plan**, **Manage Subscription**, payment-methods entry **`2578`**)  
- [ ] **`expected_role: CLIENT`** on **`login_request`** — foundational §**6**
- [ ] **`COACH_ONLY`** — **`6748–6756`** — user must **not** expect **Stripe** UI (**`2518`**); support doc alignment **TBD**
- [ ] **WS:** row **20** cites **REST/Stripe only** — do not invent **`_sendWs`** for subscription cards without trace (**TBD**)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|---|---|---|
| §B SUBSCRIPTION | `2519` | Section |
| Gate | `2518` | `!_isCoachOnly` |
| Snapshot | `2521–2523` | Plan + token + usage |
| Banner | `2525–2547` | `pending_plan` downgrade |
| E11 | `2549–2561` / `1092` | Change-plan sheet |
| E10 | `2563–2575` / `1070` | Billing portal launch |
| G31 | `2580–2582` | `PaymentMethodsScreen` |
| Quick row | `2578–2602` | Payments + Family + Coaching |
| History | `2604` | `_PaymentHistoryWidget` |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2518` — `!_isCoachOnly` (SUBSCRIPTION; shares spirit with TOKEN VAULT gate `2740` — inventory §**H**)  
- `settings_screen.dart:2519–2605` — SUBSCRIPTION block (foundational §3 row 20)  
- `settings_screen.dart:2237–2241` — tier/token headline fields (**foundational** owned state)  
- `settings_screen.dart:1070` — `_openBillingPortal` (**E10**)  
- `settings_screen.dart:1092` — `_showChangePlanSheet` (**E11**)  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`**  
- `PaymentMethodsScreen` **definition** `file:line` — **TBD** (**inventory only** lists navigator **`2580–2582`**)

### Backend / Stripe

- `backend/app/services/stripe_integration.py` + `/api/billing/*` — **TBD** exact endpoints (Checkout + portal sessions)

### Bridge / WS

- **None** in foundational §4 excerpt for §**3 row 20** — Stripe **REST/SDK** unless trace extends (**TBD**)

---

## 5. State variables

| Concern | Notes |
|---|---|
| Profile + **`pending_plan`** freshness | **`2525–2547`** + **`2521–2523`** |
| Stripe sheet / portal spinners | clear on **`dispose`**, **`catch`**, **`finally`** (**`_PIPELINE_TEMPLATE.md`** §**5**) |

---

## 6. WebSocket messages

- **Not enumerated** for subscription & billing (foundational §3 row 20, §4) — assume **REST + Stripe** unless later trace ties **`update_profile`** to plan changes (**TBD**).

---

## 7. Database tables touched

- **TBD** — typical **`subscriptions`**, Stripe identifiers, **`users`** tier linkage (**`stripe_integration`** + webhooks).

---

## 8. Edge cases

- **`COACH_ONLY`** — **`2518`** hides **`2519`** block  
- Returning from Stripe **portal** / **Checkout** — refresh path (**TBD**)  
- **`pending_plan`** null vs `{}` vs bad JSON — deterministic UI (**TBD**)  
- Push **`2580`** over modal stacks / keyboard (**TBD**)  
- Offline vs Stripe **HTTP** errors — differentiated copy (`_PIPELINE_TEMPLATE.md` §8)

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 — `_FOUNDATIONAL_SPEC.md` §**9** (verbatim).

| Commit | Summary |
|---|---|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject proposals that:**

- ❌ **`1070`** / **`1092`** launch Stripe URLs without user-visible failures on bad intent / missing session (silent **`8c2a768`** analogue)  
- ❌ **`PaymentMethodsScreen`** **401 →** auto-navigation loops (Bearer raced before Redis — trust regression **#71**)  
- ❌ **Optimistic** tier-celebration **before** **server** acknowledges **Stripe** webhooks (**stale tier** UX)

---

## 10. Known bugs

### Open

| ID | Symptom |
|---|---|
| BP-01 | Callee bodies beyond inventory anchors for **`1070`** / **`1092`** — Stripe stack lines **TBD** |
| BP-02 | Foundational **TBD** for internals of **`_openBillingPortal`** / **`_showChangePlanSheet`** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10 + subscription IA**.

| Date | Severity | Friction | Target |
|---|---|---|---|
| 2026-05-05 | Medium | Weekly brief **`X-User-Id`** only (`6321–6323`) — weaker than Bearer; billing REST must avoid duplicate header-only paths | Audit PaymentMethods / portal REST |  
| 2026-05-05 | Medium | Change plan (**`1092`**) vs Manage subscription (**`1070`**) — two Stripe doors confuse users | Routing copy |
| 2026-05-05 | Medium | **`2525–2547`** downgrade UX — **heavy** emotionally if CTAs vague | UX copy review |
| 2026-05-05 | Low | **`2578–2602`** bundles payments + family + coaching on billing canvas | IA grouping (**TBD**) |

---

## 12. Security boundaries

- Never log Stripe secrets or Checkout URLs with raw session secrets (`_PIPELINE_TEMPLATE.md` §12 spirit).
- Portal **return URLs** must not carry **Bearer** tokens in query (**TBD** routing review)  
- **Payment methods REST** scopes data to authenticated **own customer** (**server authoritative**)

---

## 13. Manual test scenarios

1. **`!_isCoachOnly`** CLIENT → Settings → SUBSCRIPTION **`2519`** visible  
2. Manage Subscription (**`1070`**) round-trip → plan/banner coherence (**assert TBD**)  
3. Change Plan (**`1092`**) happy path + user cancels Stripe  
4. Payment methods (**`2580–2582`**) add/remove sandbox card  
5. `pending_plan` fixture → **`2525–2547`** on vs appropriately off  
6. **`COACH_ONLY`** account → **`2518`** hides block  

---

## 14. Foundational spec cross-reference

- **§3 row 20** — REST/Stripe transport, calls, display state (**`2237–2241`**, **`2520–2605`**)  
- **§6** — **`login_success`**, **`ClientSettingsScreen`** parent  
- **§8** — client sees **own** billing aggregates only (**not** other households)

---

## 15. Daily health checks

Anchors **`2518`, `2519`, `2520–2605`, `1070`, `1092`, `2580–2582`, `2604`, `2237–2241`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/21_subscription_plan_and_billing_portal.md +
_FOUNDATIONAL_SPEC.md §3 row 20, §6 +
_TAB_INVENTORY §B SUBSCRIPTION, §H (2518), §E E10 + E11, gap G31.
Trace _openBillingPortal (1070), _showChangePlanSheet (1092), PaymentMethodsScreen (2580–2582) → Stripe + billing REST.
```

---

## 18. Explicit OUT OF SCOPE

- TOKEN VAULT subsection (`2660+`, gate **`2740`**) → **`23_token_vault.md`** (**inventory**)  
- `FamilyManagementScreen`, `CoachingPackScreen` deep specs → **20**, **22**  
- Buy Tokens sheet (**`787`**) → **`24_buy_tokens_flow.md`** (**related**)

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
