# Client Portal — Biometric & quick login (`E3` opt-in + Settings SECURITY)

> Status: `DRAFT` (bridge acks for biometric enrollment + **TBD** copy audit)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§E E3**, **§C C10**, **§B SECURITY** (`3046`), gap **G24**; `_PHASE_3_PLAN.md` **spec 09**. **Distinct** from **`biometric_update`** / Nevedal pipe — `_FOUNDATIONAL_SPEC.md` §3 **row 8** → spec **`40_nevedal_biometrics_service.md`**.

---

## 1. Purpose (1 sentence)

After **`login_success`**, optionally show **`_showBiometricOptInDialog`** driven by **`_showBiometricOptIn`** — **`main.dart:6667–6669`** (**E3**, **C10**); and let clients toggle **Biometric / Quick Login** in **`ClientSettingsScreen`** — **`settings_screen.dart:3048–3083`** via **`_bioIdentity.setBiometricEnabled`** (**G24**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 row **1** (`login_request` biometric example `6407–6412`), §3 row **11**; `_TAB_INVENTORY_2026-05-05.md` §B, §C, §E, §**H**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **E3** opt-in appears only when product flag **`_showBiometricOptIn`** warrants it — **`6667–6669`**; dismiss / accept paths **TBD** beyond invoke line  
- [ ] Opt-in copy states **what is stored** (device keychain / platform equivalent) and **how to turn off** (`3048–3083`)  
- [ ] **Settings → SECURITY** toggle reflects true OS capability; errors are **not** silent — **`_bioIdentity.setBiometricEnabled`** path  
- [ ] **`kIsWeb`** branch for Biometric Login (**`settings_screen.dart:3066–3083`** — inventory §**H**) explains **web limitations** plainly (no fake “enable” that no-ops)  
- [ ] Lobby **`login_request`** biometric shortcut — **`main.dart:6407–6412`** — stays consistent with enrollment state (spec **05** cross-ref)  
- [ ] Touch targets ≥ 44pt on primary CTAs — template  
- [ ] No **auto-redirect loops** if subsequent REST fires before token propagation — template / §6  
- [ ] **Contrast Nevedal:** voice/presence **`biometric_update`** — `nevedal_flutter.dart:471–516` — is **not** this feature; avoids user confusion (“two biometrics”)  
- [ ] **Loading / failure:** **`setBiometricEnabled`** failures surface retry or settings deep-link (**TBD** lines)  

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| Opt-in gate | **`main.dart:6667–6669`** | Post-login biometric offer | **E3**, flag **`_showBiometricOptIn`** |
| **`_showBiometricOptInDialog`** | invoked **`6669`** (per **C10**) | Modal chrome | Inventory |
| SECURITY section header | **`settings_screen.dart:3046`** | Settings IA | Inventory §B |
| Biometric / Quick Login row | **`settings_screen.dart:3048–3083`** | Persisted pref | **`_bioIdentity.setBiometricEnabled`** |
| **`kIsWeb`** caveat UI | **`settings_screen.dart:3066–3083`** | Platform honesty | Inventory §**H** |

---

## 4. Files (canonical references)

### Mobile
- **`main.dart:6667–6669`** — **`_showBiometricOptIn`**, dialog invoke (**E3**)  
- **`main.dart:6407–6412`** — **`login_request`** biometric payload example (§3 row **1**)  
- **`settings_screen.dart:3046`** — **SECURITY** section anchor  
- **`settings_screen.dart:3048–3083`** — toggles + web branch (**G24**)  

### Bridge (WebSocket)
- **TBD** — enrollment / opt-in ACK message types (**not** in foundational §4 table)

### REST (FastAPI)
- **TBD** — if quick-login state syncs via REST

### Storage
- **TBD** — platform secure storage + `profile_data` keys (**not** §5-mapped)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_showBiometricOptIn` | `bool` (**inferred**) | post-login branch | dialog outcome **TBD** | **TBD** |
| Biometric enabled (service) | platform + `_bioIdentity` | toggle **`3048–3083`** | user off / reset **TBD** | **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Notes |
|-----------|------|----------------------|-------|
| → | **`login_request`** (biometric) | **`6407–6412`** | §3 row **1**; spec **05** |
| *(TBD)* | enrollment / handshake | — | bridge lines **not** in foundational §4 |

**Do not** list **`biometric_update`** — §3 row **8** / spec **40**.

---

## 7. Database tables touched

- **TBD** — `_FOUNDATIONAL_SPEC.md` §5 has no **device biometrics** row

---

## 8. Edge cases

- Opt-in **`6669`** while another modal (re-consent, **08** security) is pending — stacking **TBD**  
- User enables biometrics then **forces password reset** (**08**) — re-prompt rules **TBD**  
- **Dual-account** username resolution with biometric shortcut — **`expected_role`** contract (process; not line-mapped in foundational)

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits from `_FOUNDATIONAL_SPEC.md` §9 (verbatim summaries).

| Commit | Summary (foundational) |
|--------|-------------------------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject:** treating **Nevedal** **`biometric_update`** cadence as **device login** enrollment; web UI that implies hardware biometrics work when **`kIsWeb`** — inventory §**H**.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| BQL-01 | Bridge enrollment message map **TBD** | `_FOUNDATIONAL_SPEC.md` §4 gap | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows — `_FOUNDATIONAL_SPEC.md` §10 + §7 **web** caveat.

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | High | **Service worker / web quirks** — §7 — **TBD** | **E3**/**Settings** biometric story on **`app.` / `coach.`** Flutter web |
| 2026-05-05 | Low | Legacy **`NeuralInterface`** vs **V2** — §10 | Maintainer confusion bleeds into **wrong** biometric hook site |
| 2026-05-05 | High | **`login_success`** + hub wiring — §6 (`6656–6752`) | Opt-in **`6669`** fires in dense gate stack; fragile ordering |
| 2026-05-05 | Medium | **`biometric_update` 2s** timer — §7 (`471–472`) | User may think Nevedal stream = “Face ID”; copy must diverge (**row 8** vs **G24**) |

---

## 12. Security boundaries

- Device biometric secrets **never** leave secure enclave / platform store into logs.  
- Opt-in / toggle must not leak **password** into analytics.  
- Distinct from **Sentinel** / YubiKey admin flows (not client lobby).  

---

## 13. Manual test scenarios

1. Fresh **`login_success`** → **E3** path **`6667–6669`** (when flag true) → accept → Settings shows **enabled** coherence.  
2. Decline opt-in → later enable via **`3048–3083`**.  
3. **`kIsWeb`** — verify **`3066–3083`** text matches capability.  
4. Biometric **`login_request`** **`6407–6412`** after enrollment (spec **05**).  
5. Toggle off → lobby password path still works (**TBD** assertion).  

---

## 14. Foundational spec cross-reference

- **§3 rows:** **1** (credential pattern), **11** (settings hub contains SECURITY)  
- **§6:** **`login_success`** ordering around **`6669`** invoke  
- **§7:** biometric **volume** is **Nevedal** — do not conflate  
- **§8:** boundaries  

---

## 15. Daily health checks

Manual: inventory anchors **`3048–3083`**, **`6667–6669`**, **`6407–6412`**.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational + phase plan + inventory only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/09_biometric_quick_login.md +
_TAB_INVENTORY_2026-05-05.md §E E3, §H biometrics +
_FOUNDATIONAL_SPEC.md §3 rows 1, 11.
Do not merge with 40_nevedal_biometrics_service.md (§3 row 8).
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
