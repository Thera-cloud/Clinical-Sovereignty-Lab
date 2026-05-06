# Client Portal — Legal agreements & data export

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gaps:** **`G19`** (terms/privacy viewer), **`G20`** (**JSON export UX**). **`E16`**, **`E17`** (**inventory §E modal ids** converge on same client settings rows).

**Foundational §2 anchor:** **`ClientSettingsScreen`** — **`settings_screen.dart:2236`** (hub).

**Plan:** `_PHASE_3_PLAN.md` **spec 38**. Prefix **38_**.

---

## 1. Purpose

From **LEGAL & PRIVACY** card (**`settings_screen.dart:3087–3092`**), **`CLIENT`** taps **Terms, Privacy & Waivers** (**`3090`**) → **`_LegalAgreementScreen`** (**`settings_screen.dart:2229–2232`**, class **`6128`**) OR **Download My Data** (**`3091`**) → **`_requestDataExport`** (**`settings_screen.dart:2134`**) backed by **`GET /api/users/{userId}/data-export`** (**`settings_screen.dart:2187`**).

---

## 2. UX acceptance criteria (**8+**)

### Legal viewer

- [ ] **`_showLegalAgreement`** pushes **`MaterialPageRoute`** — **`2229–2232`**
- [ ] **`_LegalAgreementScreen.build`** scaffold + gold chrome — **`settings_screen.dart:6132–6166`**
- [ ] Embedded **Consent Version** **`v13.0_2026`** — **`settings_screen.dart:6161–6165`** (**must track `REQUIRED_CONSENT_VERSION` rule** — **TBD parity with server**)

### Export flow

- [ ] Disclaimer dialog bullets — **`settings_screen.dart:2140–2149`**
- [ ] **`_performDataExport`** guards **`userId` + token** empties — **`2170–2177`**
- [ ] Spinner modal — **`2180–2184`**, dismissed **`2193`** / **`2221`**
- [ ] **`200`** triggers **`ConversationExportService().saveToLocal`** (**`settings_screen.dart:2204`**) (`filename` — **`settings_screen.dart:2202–2203`**)
- [ ] **`kIsWeb` vs native** messaging split — **`settings_screen.dart:2210`**
- [ ] Non-200 / **`catch`** surfaces **snackbars** — **`2196–2198`**, **`2222–2224`**

### About card cohesion

- [ ] **`consentVersion` info row** visible in same **`build`** context — **`settings_screen.dart:2237–2242`** binds display (**row placement **3092** refs `consentVersion` variable**) — cite **`3092`** with **`2237–2242`**

---

## 3–4. Files / REST

| Concern | `file:line` |
|---------|-------------|
| Legal rows | `settings_screen.dart:3087–3092` |
| Nav to legal viewer | `settings_screen.dart:2229–2232` |
| Legal screen class | `settings_screen.dart:6128–6183+` *(body continues)* |
| Export dialog | `settings_screen.dart:2134–2167` |
| Export HTTP | `settings_screen.dart:2169–2225` |

**REST:**

- **`GET`** `${AppConfig.apiBaseUrl}/api/users/$userId/data-export` — **`2187`**

---

## 5–7. State / WS / DB

- **Stateless legal screen** — **`6128`** (class head)
- **`ConversationExportService`** handles filesystem **parity** (**`2204`**)
- Backend **`data-export`** assembler tables — **TBD**

---

## 8. Edge cases

- **`60s` timeout** — **`2190`** — large exports may **feel hung** (**UX debt**)
- **Web download path** reliance on **`saveToLocal`** — **behavior** **`TBD`** file-by-browser

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

- ❌ Ship **embedded legal text** that **contradicts** live **`privacy.html`** / **`terms.html`** without version bump — **`6163`**
- ❌ Omit **`Authorization`** on export (**`2189`**)
- ❌ **Auto-email** PHI export link without **confirmation** (**current flow uses local save** — **`2204`** guard)

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| LE-01 | **Hard-coded consent version strings** (**`6163`** vs **`2242`** display) risk **desync** |
| LE-02 | **`user_id` vs `hardware_id` fallback string** (**`2170`**) ambiguous for **REST path** correctness |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | High | **`ScrollView` mega-text** (**`6141`+**) bury **crisis copy** (**`6181`**) | pinned crisis banner |
| 2026-05-06 | Medium | **`Download My Data`** promises categories (**`2141–2146`**) without **ordering / sensitivity** tiers | expandable detail |
| 2026-05-06 | Low | **`Legal Agreement`** app bar (**`6135`**) duplicates **marketing** serif tone vs **FAQ** (**`35b`**) | design system unify |
| 2026-05-06 | Low | Spinner-only **progress** (**`2180–2184`**) — no **percent** — **trust** friction | phased status text |

---

## 12–16. Security / Tests / Cache

- **Bearer-only export** (**`2188–2189`**)
- Manual tests: Legal open/close + export **happy path**, **403**, **`Not authenticated`** snackbar (**`2174–2176`**).

---

## 17. Cursor prefix

```
Prefix 38_. Rows 3090–3091; legal 6128+; export 2134–2225.
Unify consent version constant with AiConsentGate + REST profile.
```

---

## 18. OUT OF SCOPE

- **`39_account_deletion.md`**
- **`35b_help_faq.md`** (general help)
- **Store-delivered privacy URLs** (**App Store packaging** — **TBD**)

---

*Spec from foundational + settings anchors — `2026-05-06`.*
