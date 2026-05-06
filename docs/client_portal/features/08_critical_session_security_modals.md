# Client Portal — Critical session security modals (force reset + security disconnect)

> Status: `DRAFT` (bridge event payload shape + exact dismiss/teardown lines **TBD** in foundational)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§E E1,E2**, **§C C9**, gaps **G22,G23**; `_PHASE_3_PLAN.md` **spec 08**. **Not** a dedicated `_FOUNDATIONAL_SPEC.md` §3 row — **server-push overlays** during an active client session (`main.dart` WS handler belt).

---

## 1. Purpose (1 sentence)

When the bridge emits **`force_password_reset`** (**E1**, **G22**) or **`security_disconnect`** (**E2**, **G23`), block further interaction with **hard-stop** modal UX — triggers **`main.dart:6797–6801`** and **`main.dart:6803–6830`** respectively, using **`_showForcePasswordResetDialog`** — **`main.dart:6430`** (dialog body **`6430–6500+`** per inventory).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §E,C; `_FOUNDATIONAL_SPEC.md` §6 (lifecycle); `_PIPELINE_TEMPLATE.md` §2, §8.

- [ ] **E1:** User cannot proceed without completing the **forced password reset** path implied by **`_showForcePasswordResetDialog`** — **`6430`**; server event wiring — **`6797–6801`**
- [ ] **E2:** **`security_disconnect`** produces explicit **why / what next** — handler block **`6803–6830`**; not a silent websocket `onDone`
- [ ] Hard-stop modals share **severity** (**high** per `_PHASE_3_PLAN.md`) — visual/IA parity so users treat both as authoritative security events
- [ ] Errors are **distinct** from generic network failures (user knows **policy** disconnected them vs flaky Wi‑Fi)
- [ ] Loading / recovery: primary CTA reaches **Lobby** or **password reset** without dead ends (**TBD** per-button lines)
- [ ] Touch targets ≥ 44pt on primary CTAs — template  
- [ ] After either flow, **no** stale authenticated REST calls assume Bearer validity (token/session cleared — **TBD** teardown map)
- [ ] No **dashboard-style auto-redirect on 401** loops — `_PIPELINE_TEMPLATE.md` §8 / workspace trust posture  
- [ ] **`COACH_ONLY` / alternate post-login shells:** hard-stop still leaves user in coherent state — `_FOUNDATIONAL_SPEC.md` §6 item 2–3 (**TBD** edge matrix)  
- [ ] Contrasts **`login_failed`** snackbar (**E4**, **`6831–6858`** — spec **05**) — pre-auth retry vs mid-session termination  

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `_showForcePasswordResetDialog` | `main.dart:6430` | **G22** / **E1** modal chrome | Inventory **C9** |
| **`force_password_reset` handler** | `main.dart:6797–6801` | Wires WS event → modal | **E1** |
| **`security_disconnect` handler** | `main.dart:6803–6830` | Second hard-stop branch | **E2** |

---

## 4. Files (canonical references)

### Mobile
- `main.dart:6430` — **`_showForcePasswordResetDialog`**
- `main.dart:6797–6801` — **`force_password_reset`** handling (**E1**)
- `main.dart:6803–6830` — **`security_disconnect`** handling (**E2**)
- **`main.dart:6656–6787`** — adjacent **`login_success`** / routing (cross-feature; spec **05**)

### Bridge (WebSocket)
- Push message types **`force_password_reset`**, **`security_disconnect`** — handler `file:line` **TBD** in foundational pass  

### REST (FastAPI)
- Password reset submission endpoints **TBD** (likely shared with lobby forgot-password; not row-mapped in §5)

### Storage
- **TBD** — password hash rotation / session revocation on server when events fire  

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| **(dialog / flags)** | **TBD** | WS events **`6797+`**, **`6803+`** | dismiss / nav to lobby | **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Expected response / side effect | Failure handling |
|-----------|------|---------------------|----------------------------------|------------------|
| ← | `force_password_reset` | **`6797–6801`** | **`_showForcePasswordResetDialog`** path | **TBD** if dialog fails to mount |
| ← | `security_disconnect` | **`6803–6830`** | session teardown + user messaging | **TBD** silent handler audit |

**Pairing:** both are **← server push** during active **`main.dart`** WS session (not **`NeuralInterfaceV2`**-local only — routing is app-level **`main.dart`** per inventory).

---

## 7. Database tables touched

- **TBD** — server-side revocation / `users.password_hash` / Sentinel flags (**not** enumerated in foundational §5 for these events).

---

## 8. Edge cases

- Event arrives during **nested navigation** (settings push, onboarding) — stacking **TBD**  
- Duplicate events / reconnect storm — dedupe **TBD**  
- **Flutter web / Safari SW** staleness — user sees blank shell instead of modal — `_FOUNDATIONAL_SPEC.md` §7  
- Relation to **`_ClientWsHub`** static channel **`10316–10328`** — must not leave orphaned hub auth after hard-stop (**TBD**)  

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

**Reject:** silent swallow of **`security_disconnect`**; non-modal “toast only” downgrade for **`force_password_reset`**; teardown that leaves **`NeuralInterfaceV2`** thinking it is authenticated (**TBD** verify).

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| CSS-01 | Bridge push → Flutter handler lines only; bridge emit sites **TBD** | `_FOUNDATIONAL_SPEC.md` §4 gap | TBD |
| CSS-02 | Password-reset completion vs lobby return — **TBD** | **`6430–6500+`** | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows — **`_FOUNDATIONAL_SPEC.md` §10** + **§7** where session fragility interacts with hard-stop UX.

| Date | Severity | Friction | Applicability |
|------|----------|----------|---------------|
| 2026-05-05 | High | **Schedule from settings** omits password — **`settings_screen.dart:2964–2968`**; hub errors **`main.dart:10447–10454`** — §10 | User may confuse **hub failure** with **policy disconnect** (**E2**) unless copy is crisp |
| 2026-05-05 | Medium | **Second WebSocket** (distress) — **`distress_beacon_screen.dart:75–78`** — §10 | Compound sessions: hard-stop must still define **canonical** teardown order |
| 2026-05-05 | High | Service worker / web quirks **TBD** — §7 | **E1/E2** modals must remain reachable on **`app.*`/`coach.*`** web shells |
| 2026-05-05 | High | Family Sanctuary **closes** chat socket **`3701–3703`** — §10 | After security modal, reconcile with **sanctuary-open** race (**TBD**) |

---

## 12. Security boundaries

- Treat **both** events as **integrity / account-control** signals — never log payloads that include reset tokens (**TBD** schema).  
- Client must not **replay** suppressed credentials into REST after **E2** until re-auth — **policy** (**TBD** enforcement lines).  
- Bridge-side auth allowlist (**§4.C**) irrelevant until **fresh** **`login_success`**.  

---

## 13. Manual test scenarios

1. Trigger **`force_password_reset`** (staging harness) → **E1** modal **`6430`**; complete reset → expect clean **lobby** or signed-in state (**TBD**).  
2. Trigger **`security_disconnect`** → **E2** **`6803–6830`**; confirm sockets down + no phantom chat send.  
3. Fire **E2** while **Family Sanctuary** or **schedule** foregrounded — navigation stack coherence (**TBD**).  
4. Compare copy to **`login_failed`** shake (**E4**) — user distinguishes **credential** vs **policy** failure.  
5. Web: cold load stale SW → hard-stop still renders (or documented failure per §7).  

---

## 14. Foundational spec cross-reference

- **§3 row:** *(none)* — overlays only; align with **`_FOUNDATIONAL_SPEC.md` §6** lifecycle + **§8** boundaries  
- **§6:** Lobby connect + **`login_success`** prerequisite context  
- **§7–§8:** downstream hazards + review items  

---

## 15. Daily health checks

Manual: inventory line anchors (**`6797–6830`**) still match `main.dart`; grep **`force_password_reset`/`security_disconnect`** on bridge when touched.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (inventory + foundational + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/08_critical_session_security_modals.md +
_TAB_INVENTORY_2026-05-05.md §E E1,E2 +
_FOUNDATIONAL_SPEC.md §6.
Do not merge with 05 (pre-auth failures) or 09_biometric_quick_login.md (E3).
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
