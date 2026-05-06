# Client Portal — Check-in screen & widget intent (C11)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 24** — **`CheckinScreen build`** — `checkin_screen.dart:48`; **REST `POST`** — `checkin_screen.dart:25–31`; **`_submitted`, `_responseMsg`** — `checkin_screen.dart:16–17`.

**Plan:** `_PHASE_3_PLAN.md` **spec 36** — **`C11`**, **`row 24`**. Prefix **36_**.

**Inventory:** **`_TAB_INVENTORY_2026-05-05.md`** **`C11`** — home/widget → **`main.dart`** post-login **`open_checkin`**.

---

## 1. Purpose (1 sentence)

After **CLIENT** login, a **pending home-widget action** (**`main.dart:6788`**) pushes **`CheckinScreen`**, where the user submits an **emotion tag** via **`POST /api/sse-client/checkin`** (**`checkin_screen.dart:25–26`**) and auto-dismisses on success (**`checkin_screen.dart:43–44`**).

---

## 2. UX acceptance criteria (client perspective)

- [ ] **`CheckinScreen` ctor requires `profile`** — **`checkin_screen.dart:7–12`**
- [ ] **`_submit`** guards **double-send** via **`_submitted`** — **`checkin_screen.dart:19–21`**
- [ ] **`Authorization: Bearer`** from **`widget.profile['token']`** — **`checkin_screen.dart:23–28`**
- [ ] **`json.encode({'emotion': emotion})`** body — **`checkin_screen.dart:31`**
- [ ] **`8s` timeout** on HTTP — **`checkin_screen.dart:32`**
- [ ] **200** parses **`message`** into **`_responseMsg`** — **`checkin_screen.dart:33–35`**
- [ ] Non-200 **`else`** copies reassuring fallback — **`checkin_screen.dart:36–37`**
- [ ] **`catch`** uses same reassurance (no panic UI) — **`checkin_screen.dart:39–40`**
- [ ] **`2s` delay** then **`Navigator.pop`** if **`mounted`** — **`checkin_screen.dart:43–44`**
- [ ] **`build`** toggles **`_buildConfirmation()`** vs **`_buildEmotionPicker()`** — **`checkin_screen.dart:48–56`**

### Widget-intent bootstrap

- [ ] **`_pendingWidgetAction == 'open_checkin'`** gated to **`role == 'CLIENT'`** — **`main.dart:6788`**
- [ ] **`addPostFrameCallback`** before **`Navigator.push`** — **`main.dart:6789–6791`** (avoids nav race during **`pushReplacement`** — **`6787`**)
- [ ] **`profileWithToken`** passed into **`CheckinScreen`** — **`main.dart:6791`**

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| `CheckinScreen` | `checkin_screen.dart:6–13` | Entry widget |
| `build` / branch | `checkin_screen.dart:48–58` | Picker vs confirmation |
| Emotion **`Wrap`** | `checkin_screen.dart:61–79` | **TBD** full button map past **`79`** |
| Pending widget gate | `main.dart:6788–6793` | Home shortcut → screen |

---

## 4. Files (canonical references)

### Mobile

- `checkin_screen.dart:16–79` (**picker + HTTP** excerpt in foundational)
- `main.dart:6787–6793` (**post-login** stack + **`open_checkin`**)
- `main.dart:41` — **import** `checkin_screen.dart`

### REST (**from **`checkin_screen.dart:26`** header path only**)

- **`POST`** `.../api/sse-client/checkin` (**router linkage** — **TBD** backend file)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_submitted`, `_responseMsg` | **`16–17`** |
| **`_pendingWidgetAction`** (lobby/session) | **TBD** where set — **`main.dart` grep** deferred |

---

## 6. WebSocket messages

- **None** for **`CheckinScreen`** itself (**REST-only**).

---

## 7. Database tables touched

- **TBD** — SSE / check-in tables behind **`/api/sse-client/checkin`**.

---

## 8. Edge cases

- **Empty token** — HTTP may **401** — user sees **fallback** reassurance only (**`39–41`**) — **spec debt**: distinguish auth failure (**§8 foundational** parity)
- **`Navigator.pop`** after **`pushReplacement`** parent — **ensure** **`CheckinScreen`** still **`mounted`** — **`6787–6791`** ordering verified in code excerpt

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

- ❌ Hide **401** vs **network** failures behind identical reassurance copy (**`8c2a768`** class silent-drop analogue)
- ❌ **`POST`** without **`Content-Type: application/json`** — **`checkin_screen.dart:29`** contract break
- ❌ Fire **`open_checkin`** for **non-CLIENT** roles — **`6788`** guard removal

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| CK-01 | **Auth/export parity** — errors collapse to same string — **`39–40`** |
| CK-02 | **`_pendingWidgetAction` clearing** semantics — **TBD** (`main.dart` assignment sites) |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **Ultra-minimal chrome** (**`checkin_screen.dart:49–52`**) — no **privacy** reassurance before emotion send | preamble microcopy |
| 2026-05-06 | Medium | **`2s` stall** (**`43`**) feels **frozen** after submit | optimistic UI / haptics |
| 2026-05-06 | Low | Emoji grid density on **narrow** devices — **`70–79`** | dynamic scale |
| 2026-05-06 | Low | **`open_checkin`** invisible if user misses **notification** cadence — **widget contract** (**`35a`**) drift | settings deep link reminder |

---

## 12. Security boundaries

- **Bearer** token only — **`checkin_screen.dart:28`**; **no PHI** logged in client prints (**spot-check **`checkin_screen.dart`** beyond excerpt** — **TBD**).

---

## 13. Manual test scenarios

1. Set **`open_checkin`** intent (**TBD harness**) → **`CLIENT`** **`login_success`** → **`6788–6791`** push
2. Pick **emotion** → **200** vs **non-200** messaging
3. **Airplane mode** → fallback copy
4. **Rapid multi-tap** → **`_submitted`** gate

---

## 14–16. Foundational cross-ref / daily health / investigation cache

- **§3 row 24**, **`§7` Nevedal volume note** (**unrelated**) — biometric spec **`40`**;
- Investigation cache **`2026-05-06`**: **`_pendingWidgetAction` setter** — **TBD**

---

## 17. Cursor prefix

```
Prefix 36_. checkin_screen 6–80; widget intent main.dart 6788–6791.
Harden HTTP error taxonomy; trace /api/sse-client/checkin router.
```

---

## 18. OUT OF SCOPE

- **`35a_home_widget.md`** (installation sheet only)
- **`14_nudges_and_metrics.md`**
- **Coach Nate check-in variants** (**TBD**)

---

*Spec from foundational + plan — `2026-05-06`.*
