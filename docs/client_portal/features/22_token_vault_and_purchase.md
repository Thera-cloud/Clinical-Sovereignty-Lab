# Client Portal — Token vault & purchase

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§B TOKEN VAULT** (`2660`). **Balance / today / this month** — `2662–2723` (display). **Buy Tokens** — `2725–2737` → **`_showBuyTokensSheet`** — `787` (**E8**). Gate **`!_isCoachOnly`** — `2740` (inventory §H: **SUBSCRIPTION + TOKEN VAULT** also references `2518` — subscription lead-in; **vault** wrap **`2740`**).

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 20** — **Subscription & billing** economy (`2520–2605`, REST/Stripe) + headline **token/plan** fields `2237–2241`. **This spec** is the **wallet / pack-purchase** mental model (**distinct** from **plan / portal / payment methods** — **spec `21`**). **Line truth for vault UI:** inventory **`2660–2737`**, not the row-20 `2520–2605` span alone.

**Plan:** `_PHASE_3_PLAN.md` **spec 22** (§3 row **20** token vault strip + **E8**). Prefix **22_**.

---

## 1. Purpose (1 sentence)

Show **eligible CLIENT** users (**not** **`COACH_ONLY`**) a **TOKEN VAULT** section (`2660`) with **balance + usage snapshot** (`2662–2723`) and a **Buy Tokens** path (`2725–2737` / **`787`**, **E8**) driven by **REST/Stripe**, **separate** from **subscription plan / billing portal** flows (**`21`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §**3 row 20** (billing context), §**6**, §**8**; `_TAB_INVENTORY_2026-05-05.md` §**B TOKEN VAULT**, §**H**; `_PIPELINE_TEMPLATE.md` §**2**.

- [ ] **TOKEN VAULT** — `2660` — visible only under **`!_isCoachOnly`** — gate `2740` (and consistent with §H pairing `2518` for coach-only omission)
- [ ] **Balance / today / this month** — `2662–2723` — matches **authoritative** server + Stripe-side truth after purchases (**TBD** refresh triggers)
- [ ] **Buy Tokens** (**E8**) — `2725–2737` / `787` — **loading**, **Stripe cancel**, **failure**, **success** are all **visible** (no **`8c2a768`‑class** silent no-op)
- [ ] Checkout / payment intent resolves within **30s** or surfaces **retry** / **support** path
- [ ] Primary **Buy** controls — touch targets ≥ **44pt**
- [ ] **`_showBuyTokensSheet`** must not present **fake** “credited” state before server/webhook-aligned balance update (**stale wallet** guard)
- [ ] **Empty** or **zero** balance is a **valid** state — distinguish from **fetch error** (no silent empty on **5xx** / **401**)
- [ ] **`expected_role: CLIENT`** on **`login_request`** — §**6**
- [ ] **Bearer** REST for purchase endpoints survives **Redis token propagation** lag — avoid **auto-kick** loops (**`_PIPELINE_TEMPLATE.md`** §**2**)
- [ ] **Copy** distinguishes **token packs** (this spec) from **subscription / Inner Chamber** (**`21`**) so users know **which** surface fixes **which** problem
- [ ] **`COACH_ONLY`** — `6748–6756` — vault **hidden**; support docs state **why** (**not** a bug)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|---|---|---|
| §B TOKEN VAULT | `2660` | Section |
| Gate | `2740` | `!_isCoachOnly` (vault; see also `2518` §H) |
| Snapshot | `2662–2723` | Balance + today + month |
| **E8** | `2725–2737` / `787` | Buy Tokens → sheet |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2660` — TOKEN VAULT section marker  
- `settings_screen.dart:2662–2723` — balance / usage display  
- `settings_screen.dart:2725–2737` — Buy Tokens row  
- `settings_screen.dart:787` — **`_showBuyTokensSheet`** (**E8**)  
- `settings_screen.dart:2740` — **`!_isCoachOnly`** gate (inventory §H)  
- `settings_screen.dart:2518` — **`!_isCoachOnly`** (subscription + vault region — §H)  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`**  
- `settings_screen.dart:2237–2241` — headline tier/token fields (foundational row 20 — may duplicate numbers vs vault; see §11)

### Backend / Stripe

- `backend/app/services/stripe_integration.py` — **token pack** **`Checkout`** (env `STRIPE_PRICE_TOKEN_*` — workspace **`token-economics-architecture.mdc`**); exact client call sites **TBD**

### Bridge / WS

- **None** asserted for vault/pack purchase in foundational §**4** excerpt — **REST + Stripe** unless trace finds **`WS`** (**TBD**)

---

## 5. State variables

| Concern | Notes |
|---|---|
| Sheet open + **purchase-in-flight** | Clear on **`dispose`**, **`catch`**, **`finally`** (**`_PIPELINE_TEMPLATE.md`** §**5**) |
| **Balance** display state | Refresh after **`Checkout`** **`return`** (**TBD**) |

---

## 6. WebSocket messages

- **Not enumerated** for **token pack purchase** in foundational §**4** — assume **REST/Stripe** unless trace adds **`WS`** (**TBD**).

---

## 7. Database tables touched

- **TBD** — `token_transactions`, `users.token_balance` / `profile_data`, Stripe `metadata.type == token_pack` path (workspace token-economics rule / `stripe_integration`)

---

## 8. Edge cases

- **Coach-only** account — **`2740`** / **`2518`** — whole vault **omitted**
- **`Checkout`** canceled / **`timeout`** — user returns to sheet with **recoverable** state
- `token_balance` vs `profile_data` JSON drift — bridge `UserStore` merge rules (workspace) — vault must not fight Token Lab adjusts (support caveat — TBD)
- Offline vs Stripe HTTP errors — differentiated copy (`_PIPELINE_TEMPLATE.md` §8)

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 — `_FOUNDATIONAL_SPEC.md` §9 (verbatim table + reject bullets below).

| Commit | Summary |
|---|---|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject proposals that:**

- ❌ **Buy Tokens** **`787`** path **drops** errors — **silent** wallet (**`8c2a768`** class)  
- ❌ **`401`** → destructive logout loops on payment surface during Bearer propagation lag (trust rule #71 analogue)  
- ❌ UI credits tokens before `checkout.session.completed` / server ack (`stripe_integration` webhook truth)

---

## 10. Known bugs

### Open

| ID | Symptom |
|---|---|
| TV-01 | `_showBuyTokensSheet` body + REST endpoints — fine-grained lines beyond `787` — TBD |
| TV-02 | Reconciliation `2521–2523` vs `2662–2723` — duplicate or divergent numbers — needs UX decision — TBD |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §10 + token economy IA friction.

| Date | Severity | Friction | Target |
|---|---|---|---|
| 2026-05-05 | High | Two token summaries: SUBSCRIPTION strip `2521–2523` vs TOKEN VAULT `2662–2723` — unclear which is “truth” when balances worry users | Single hierarchy or clarified copy vs one ledger surface — TBD |
| 2026-05-05 | Medium | Weekly brief `X-User-Id` pattern (`6321–6323`); if pack REST repeats header-only auth, same weakness as §10 | Audit E8 callees |
| 2026-05-05 | Medium | Buy Tokens vs Buy Voice Minutes — parallel wallet metaphors on long Settings scroll | IA / section headers — TBD |
| 2026-05-05 | Low | Legacy `NeuralInterface` vs V2 — wrong manual test entry surface for wallet | Maintainer docs |

---

## 12. Security boundaries

- Never log Stripe secrets or raw PaymentIntent identifiers in client logs (`_PIPELINE_TEMPLATE.md` §12 spirit)  
- Pack Checkout `metadata` must scope credited tokens to authenticated user only (server authoritative)  
- No exposing other users’ balances (same spirit as foundational §8 family/coach separation)

---

## 13. Manual test scenarios

1. **`!_isCoachOnly`** CLIENT → Settings → TOKEN VAULT `2660` visible  
2. **`2662–2723`** matches known fixture account balances (**assert TBD**)  
3. **Buy Tokens** **`787`** — sandbox **`success`** + **user **`cancel`**  
4. After **success**, **`2662–2723`** updates without **cold** restart (**assert TBD**)  
5. **Offline** tap **Buy** — **specific** offline message  
6. **`COACH_ONLY`** — vault **hidden**  

---

## 14. Foundational spec cross-reference

- §3 row 20 — Stripe/REST billing context (subscription slice `2520–2605`)  
- §6 — `login_success`, Settings parent shell  
- §8 — client-scoped data only  

---

## 15. Daily health checks

Anchors **`2660`, `2662–2737`, `787`, `2740`, `2518`, `2236`** stable **post-edit**.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/22_token_vault_and_purchase.md +
_FOUNDATIONAL_SPEC.md §3 row 20, §6, §8 +
_TAB_INVENTORY §B TOKEN VAULT, §H (2518 + 2740), §E E8.
Trace _showBuyTokensSheet (787) → Stripe checkout + webhook credit path.
Compare token display 2521–2523 vs 2662–2723 — single source or hierarchy.
```

---

## 18. Explicit OUT OF SCOPE

- Subscription plan / portal / `PaymentMethods`-class flows — spec `21`  
- Deep-dive `24_buy_tokens_flow.md` — inventory maps E8 → 24 alternate stub  
- Transfer Crystal `2787–2789` — G12 / Sovereign Vault / spec `26` as applicable  
- Token Lab admin / REST analytics — not client vault UX

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
