# Client Portal — Become a Coach (upgrade path)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap:** **`G18`**. **`E13`** (**About / upgrade affordance row** parity).  
**Foundational anchor (implicit §11 tools stack):** client settings **`ClientSettingsScreen`** — `settings_screen.dart:2236` (**per foundational §2 table**).

**Plan:** `_PHASE_3_PLAN.md` **spec 37**. Prefix **37_**.

---

## 1. Purpose (1 sentence)

Non-coach **`CLIENT`** profiles (**`!_isCoachOnly`**) launch **`_requestCoachUpgrade()`** (**`settings_screen.dart:1831`**) from **BECOME A COACH** rows (**`3112–3120`**) to pick **DOJO SKUs**, then **`POST`** checkout bootstrap (**`/api/registration/checkout/coach-upgrade`**) (**`settings_screen.dart:1957`**).

---

## 2. UX acceptance criteria

- [ ] **`PENDING`** short-circuit snackbar (**`1833–1837`**) blocks duplicate checkout
- [ ] **`REJECTED`** shows **Re-apply** row — **`3117–3118`**
- [ ] **`selected` DOJO checkbox list** binds **`dojoPrices` / `dojoLabels`** maps — **`1839–1888`**
- [ ] **`disc` stacking discount** maths — **`1856–1862`**
- [ ] **`judge`** always full-price copy — **`1893–1895`**
- [ ] **`Continue to Payment`** disabled when **`selected.isEmpty`** — **`1929`**
- [ ] **`Navigator.pop`** before **`await _launchCoachUpgradeCheckout`** — **`1930–1937`**
- [ ] **`_launchCoachUpgradeCheckout`** builds **`coach-upgrade`** URI — **`settings_screen.dart:1948–1972`**
- [ ] **`200`** + **`checkout_url`** sets **`pendingCheckout`** flags (**`1980–1983`**) → **`launchCheckoutUrl`** — **`1983`**
- [ ] **`PAYMENT_IN_PROGRESS`** profile mutation — **`settings_screen.dart:1982`**
- [ ] **Section guard** **`!_isCoachOnly`** — **`3111–3123`** (mirrors **`2872`** pattern)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| Section header/card | `settings_screen.dart:3112–3121` | Marketing + CTA rows |
| Dialog builder | `settings_screen.dart:1853–1944` | SKU selection + totals |
| Checkout launcher | `settings_screen.dart:1948–2000` | HTTP bootstrap |

---

## 4. Files

- **`settings_screen.dart:1831–2000`** (upgrade dialog + **`POST`**)
- **`settings_screen.dart:3111–3123`** (navigation rows)

---

## 5–6. State / WebSocket

- Uses **`http.post`** (**`settings_screen.dart:1960`**) — **no upgrade-specific WS frame** enumerated in foundational.

---

## 7. Database tables touched

- **TBD** — registration / checkout persistence server-side (**Stripe session metadata**).

---

## 8. Edge cases

- **Missing Bearer token** — **`1955`** — likely **422/401** — ensure snackbar readability (**`1990–1994`** covers non-200)
- **Price drift** vs **`stripe_integration.DOJO_*`** (**workspace rule**) — **`dojoPrices`** hardcoded (**`1839–1842`**) risks **SKU mismatch**

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 — `_FOUNDATIONAL_SPEC.md` §9 (verbatim).

| Commit | Summary |
|--------|---------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject proposals that:**

- ❌ Diverge **checkout URL** opener from **`PaymentConfirmationScreen.pendingCheckout`** contract — **`1980–1981`**
- ❌ Omit **`Authorization`** header — **`1963`**
- ❌ Auto-upgrade **coach assignment** fields without **explicit admin workflow** (**no-account-creation** workspace rule analogue)

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| BC-01 | **Hard-coded `dojoPrices`** vs live **Stripe Price IDs** — canonicality drift |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | High | **`UPGRADE TO COACH`** dialog (**`1866–1868`**) is **finance-dense** in one **`AlertDialog`** | stepped wizard |
| 2026-05-06 | Medium | **`zoomLink` optional** without **verification** (**`settings_screen.dart:1905–1908`**) — trust surface | Zoom URL sanity check UX |
| 2026-05-06 | Medium | **`Professional Email`** re-entry despite profile email — **`1910–1913`** duplication | prefilled rationale |
| 2026-05-06 | Low | **`Judge` SKU** (**`1893–1895`**) dominates visual hierarchy | progressive disclosure |

---

## 12. Security boundaries

- **Bearer token** travels only over **`HTTPS`** (**`PaymentConfirmationScreen` / **`launchCheckoutUrl`** stack** — **TBD exact implementation**).

---

## 13. Manual test scenarios

1. **`PENDING`** profile → snackbar (**`1833`**) + row (**`3115–3116`**)
2. **`REJECTED`** → **Re-apply** (**`3117`**) opens dialog
3. **`selected`** empty → **Continue** disabled (**`1929`**)
4. **`200`** no **`checkout_url`** path (**`1984–1987`**)

---

## 17. Cursor prefix

```
Prefix 37_. settings BECOME A COACH 3112–3120; logic 1831–2000.
Sync dojoPrices with stripe_integration.DOJO_PRICE_* source of truth.
```

---

## 18. OUT OF SCOPE

- **Coach onboarding after approval** ( **`coach_portal`** )
- **`21_subscription_plan_and_billing_portal.md`** (generic subscription surfaces)
- **Admin QB / corp billing**

---

*Spec from foundational + plan anchors — `2026-05-06`.*
