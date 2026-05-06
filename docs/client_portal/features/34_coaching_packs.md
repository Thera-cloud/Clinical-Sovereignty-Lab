# Client Portal — Coaching packs & sessions

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 22** — **`CoachingPackScreen build`** — **`billing_screens.dart:1635`**; **GET** packs/sessions — **`1430–1447`**; **`_packs`, `_sessions`** — **`1405–1409`**.

**Plan:** `_PHASE_3_PLAN.md` **spec 34** — §3 **r22**. Prefix **34_**.

**Inventory:** SUBSCRIPTION quick link — **`settings_screen.dart:2578–2602`** includes **`CoachingPackScreen`** (**`2578–2602`** table — see inventory §**B** SUBSCRIPTION).

---

## 1. Purpose

Let **clients** view **coaching credit packs + scheduled sessions** sourced from **`GET /api/billing/coaching/packs/{hardware_id}`** & **`.../sessions/{hardware_id}`** (**`1430–1447`**) inside **`CoachingPackScreen`** scaffold **`1635+`**.

---

## 2. UX acceptance (**8+**)

- [ ] **`_CoachingPackScreenState._loadData`** — **`1426–1451`** — **`_loading`** toggled — **`1649–1650`**
- [ ] **GET packs** — **`1430–1437`** — parses **`packs`** + **`total_remaining_credits`**
- [ ] **GET sessions** — **`1440–1447`** — parses **`sessions`**
- [ ] **Errors** currently swallowed in outer **`catch (_) {}`** **`1449`** — **spec debt** — expansions must surface **snackbar** (**reject `8c2a768`**)
- [ ] **`_authHeaders`** dependency — **`1432`** (**method** — line **TBD** inside `_authHeaders`)
- [ ] Optional **`WebSocketChannel? socket`** ctor — **`1393`**, **`1420–1424`** — doc when used (**TBD**)
- [ ] **`purchasePack` dialog** — **`1454+`** — Stripe / payment path — **line scope TBD beyond dialog open**
- [ ] **`SUBSCRIPTION` gating** aligns **`!_isCoachOnly`** (**`2518`**, **`2740`**) for parent nav
- [ ] **Credits summary** UI — **`1654+`** — numbers match API totals
- [ ] **Accessibility** on **Cancel Session** destructive actions — **`1625–1628`** region — confirm copy

---

## 3. Files

- `billing_screens.dart:1391–1451`, `1635+`
- Settings entry — **`settings_screen.dart:2578–2602`** (**inventory**)

---

## 4–7. State / REST / DB

- **`_packs`, `_sessions`, `_totalCredits, _loading`** — **`1406–1409`**
- Tables — **TBD** (**billing + sessions** services)
- **`_sendWs`** stub — **`1420–1424`** — **TBD** mesh integration

---

## 8. Edge cases

- **`_userId`** empty — **`1411–1412`** — requests may 404 — **TBD** UX
- **Clone / multi-profile** hardware mismatch — **risk** — **§8** awareness

---

## 9. Anti-patterns (**§9 verbatim**)

**Reject:** widening silent catches on paid surfaces | missing cancellation audit trail

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| CP-01 | **`_loadData` catch** hides billing outage |
| CP-02 | **Coach month overview** **`role` gap** (foundational §**4.A**) may affect related calendar views — cross-link audit |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **“COACHING”** app bar — **`1638–1645`** — overlaps **Coaching mesh** naming | Section rename pass |
| 2026-05-06 | Medium | **Credits + sessions** stacked without **next action** CTA | Guided scheduling |
| 2026-05-06 | Low | **Purchase** dialog scroll length on small phones | bottom sheet |
| 2026-05-06 | Low | **Optional socket** unexplained to user | Tooltip for live session sync |

---

## 17. Cursor prefix

```
Prefix 34_. billing_screens CoachingPackScreen 1391–1647; settings entry 2578–2602.
Harden _loadData errors; map REST to trust billing auditor.
```

## 18. OUT OF SCOPE

- **`21_subscription_plan_and_billing_portal.md`**
- **`16_client_schedule.md`**
- **`30_coaching_mesh.md`**

---

*`2026-05-06`*
