# Client Platform — Home widget setup (G16)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap:** **`G16`**. **Plan:** `_PHASE_3_PLAN.md` **spec 35a** (split). Prefix **35a_**.

---

## 1. Purpose

Expose **platform instructions** for installing the **home-screen widget** via **modal bottom sheet** when **`!kIsWeb && !_isCoachOnly`** (**`2903`**).

---

## 2. UX acceptance (**8+**)

- [ ] **`HOME WIDGET` header** — **`2904`** — icon matches row **`2906`**
- [ ] **Gate `2903`** — **web builds** omit section entirely — **parity** with **§H** matrix
- [ ] **`_isCoachOnly`** branch removes widget marketing noise
- [ ] **Bottom sheet copy** bifurcates **`iOS` vs Android** (**`2908–2913`**) via **`defaultTargetPlatform`**
- [ ] **Scrolling** **`Column`** **`mainAxisSize.min`** (**`2909`**) — long copy still reachable on small phones
- [ ] **No deep-link** automation — expectations clear (**TBD** future universal link)
- [ ] **`Navigator`/sheet dismiss** gestures — predictable (**TBD** UX test)
- [ ] **Privacy** statement if widget pulls **quotes** (**TBD** product/legal)
- [ ] **`COACH_ONLY` + native** combos — gated by **`2903`** (coach can't be `_isCoachOnly` with widget? clarify **§H** **`3119`** combos) (**TBD**)
- [ ] Accessibility — instructions legible (**contrast**) — **`2909–2914`** text style

---

## 3. Anchors

| Concern | `file:line` |
|---------|-------------|
| Gate + header + row | `2903–2918` |

---

## 4–7. Implementation notes

No standalone Dart file root — UX lives **`settings_screen.dart`** only (**per plan G16 split**).

No REST / WS.

---

## 9. Anti-patterns (**§9 verbatim`)

**Reject:** shipping StoreKit/widget entitlements docs without versioning | hiding section on **`kIsWeb`** while marketing still references widget links on web FAQs (**`35b`**)

---

## 10. Bugs

| ID | Symptom |
|----|---------|
| HW-01 | **No verification** widget actually installed (instructional-only surface) |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **No preview image** inside sheet — user uncertainty | Screenshots asset pack |
| 2026-05-06 | Low | **`Widget` noun overload** (`Flutter widgets` vs `home widget`) — confusion for devs/support | Terminology glossary |
| 2026-05-06 | Low | Placement **below YOUR TOOLS** may reduce discovery | promotional **15** recap tie-in (**TBD** policy) |

---

## 17. Cursor prefix

```
Prefix 35a_. Native-only block 2903–2918. Future: deeplink/widget config API.
```

## 18. OUT OF SCOPE

- **`36_check_in_widget_intent.md`**
- **`35b_help_faq.md`**
- **iOS/Android store listings**

---

*`2026-05-06`*
