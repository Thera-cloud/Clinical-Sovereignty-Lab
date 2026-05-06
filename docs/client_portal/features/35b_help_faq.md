# Client Portal — Help & FAQ

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap:** **`G17`**. **`E20`** (**modal/screen launch** path). **`_TAB_INVENTORY_2026-05-05.md` §**E**.

**Plan:** `_PHASE_3_PLAN.md` **spec 35b**. Prefix **35b_`.

---

## 1. Purpose

Route **clients** from **About → Help & FAQ** (**`3099–3104`**) to **`_HelpFAQScreen`** (**`5575`**), fulfilling **dual inventory entries** (**section row + §E modal id**) as **single spec**.

---

## 2. UX acceptance (**8+**)

- [ ] Row label **Help & FAQ** — **`3099–3104`** subtitle “Ask Little Nate anything” aligns with **`Neural chat`** (**`01`**)
- [ ] **`Navigator.push`** constructs **`_HelpFAQScreen(role: 'CLIENT', profile: _profile)`** — **`3101–3103`**
- [ ] **`_HelpFAQScreen` class definition** — **`5575`** — ensures **maintainers** tune **FAQ** markdown / remote config (**TBD**)
- [ ] **Back navigation** returns to **About** vs **chat** parity — **`Default AppBar`** behavior inside `_HelpFAQScreen` — **TBD** snippet
- [ ] **`Contact Support`** row immediately below (**`3105–3107`**) funnel — **`mailto:support@sovereignsanctuary.net`**
- [ ] **`COACH`** variant exists elsewhere (**`CoachSettings`** mirror) — out of scope but **prevent copy drift**
- [ ] Accessibility — search field (if any) — **TBD**
- [ ] Offline **FAQ** readability — cached assets (**TBD**)
- [ ] **Web vs native** nuances — bridging doc cross-ref **Safari SW** workspace rule
- [ ] **`E20` parity** satisfied because **navigator path** identical to **`§E`** table intent

---

## 3. Anchors

| Concern | `file:line` |
|---------|-------------|
| Nav row | `3099–3104` |
| Widget class head | `5575` |

---

## 4–7. Facts

**No dedicated REST name** surfaced in foundational — **FAQ content sourcing TBD**.

---

## 9. Anti-patterns (**§9 verbatim**)

**Reject:** stuffing **FAQ** with **privileged admin URLs** (login security rule) | **mailto** spam prompts without rate limit (**TBD**)

---

## 10. Bugs

| ID | Symptom |
|----|---------|
| HF-01 | **`_HelpFAQScreen` internals** unstaged in foundational — **risk** referencing stale onboarding |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **FAQ** divorced from **`01`** contextual help | deep link intents |
| 2026-05-06 | Low | Adjacent **`Contact Support`** duplicates **AI** expectation | clarify escalation ladder |
| 2026-05-06 | Low | Potential **overlap** with **`coach_portal`** help copy | glossary |

---

## 17. Cursor prefix

```
Prefix 35b_. Help row 3099–3104; widget 5575+.
Dedupe FAQ content source vs web static pages (/privacy etc).
```

## 18. OUT OF SCOPE

- **`38_legal_agreements_and_data_export.md`**
- **Deep link `command.*` URLs** (**login security`)
- **`35a_home_widget.md`**

---

*`2026-05-06`*
