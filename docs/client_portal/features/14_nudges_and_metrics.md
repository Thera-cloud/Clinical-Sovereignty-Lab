# Client Portal — Nudges & metrics (Neural chrome)

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G3**, **G4**, **§D D7–D9**, **§B B1**, **§A rows 4–5**. `_PHASE_3_PLAN.md` **spec 14**. Parent feature: `_FOUNDATIONAL_SPEC.md` §**3 row 7** (**`NeuralInterfaceV2`**). Outbound **`get_pending_nudges`**, **`get_metrics`**, **`nudge_mark_opened`**, **`nudge_dismiss`** — §**4.B**. Prefix **`14_`**.

---

## 1. Purpose (1 sentence)

On **`NeuralInterfaceV2`**, let **CLIENT** users **see actionable nudges**, **acknowledge or dismiss** them over the chat WebSocket, and **inspect Nevedal-style metrics** (**sheet** + **quick bar**) fed by **`get_pending_nudges`** / **`get_metrics`** with **`nudge_mark_opened` / `nudge_dismiss`** side effects documented in §**6**.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**A rows 4–5**, **§B B1**, **§D D7–D9**; `_FOUNDATIONAL_SPEC.md` §**3 row 7**, §**4.B**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **`notifications_active`** AppBar control — **`3726–3743`** — shown only when **`_pendingNudges.isNotEmpty`** (inventory: “Conditional?” **non-empty**); when **empty**, user is not misled into thinking the system is broken vs. “no nudges” (**TBD** copy)  
- [ ] **`_showNudgesSheet`** — **`1788`** — list is readable, dismissible, and does not trap focus (**TBD** a11y)  
- [ ] **`nudge_mark_opened` / `nudge_dismiss`** — **`1775–1782`** — each user action has **visible** outcome (optimistic or server-confirmed — **TBD**); **no** silent no-op on failure  
- [ ] **`get_pending_nudges`** — **`1540`** → bridge **`28200`** — refresh after login / reconnect aligns with **`01`** lifecycle  
- [ ] **`analytics`** AppBar metric entry — **`3745–3749`** — inventory: **no** extra condition; always reachable on chat surface  
- [ ] **`_showMetricsSheet`** — **`3392`** — presents **C_emo / mood / quantum**-class detail (inventory **D8**) without raw developer dumps (**TBD** copy guard)  
- [ ] **`get_metrics`** — **`2145`** → bridge **`14734`** — errors surface **what failed** + **retry** path (template §2)  
- [ ] **Quick metrics bar** — **`3799–3812`** (**§B1** / **D9**) — renders only when **`_metrics.isNotEmpty`**; **empty vs loading** states must be distinguishable (**TBD** implementation)  
- [ ] **`login_request` + `expected_role: CLIENT`** — **`1488–1493`** — prerequisite for all messages on **`_socket`** (**`01`**)  
- [ ] **Touch targets** ≥ **44pt** on AppBar actions and sheet CTAs (template)  
- [ ] **Dual-socket / hub** norms: do not assume schedule hub for nudges — this feature is **chat-socket** bound (**`01`**, `_PIPELINE_TEMPLATE.md` §2)  
- [ ] **`COACH_ONLY`** routing — **`6755–6759`** — **`ClientScheduleScreen`** users do **not** see this chrome; document **N/A** vs error (template edge case)  

---

## 3. UI components

| Inventory | Location | Purpose |
|-----------|----------|---------|
| **§A row 4** / **G3** / **D7** | **`3726–3743`** | Nudges AppBar + sheet entry |
| **D7** | **`1788`** | **`_showNudgesSheet`** |
| **§A row 5** / **G4** / **D8** | **`3745–3749`** | Metrics AppBar |
| **D8** | **`3392`** | **`_showMetricsSheet`** |
| **§B1** / **D9** | **`3799–3812`** | Quick metrics strip above composer |
| **WS footers** | **`1775–1782`**, **`2145`**, **`1540`** | Dismiss / metrics / poll |

---

## 4. Files (canonical references)

### Mobile

- `updated_screens.dart:3726–3743` — nudges AppBar region (**§A row 4**)  
- `updated_screens.dart:3745–3749` — metrics AppBar (**§A row 5**)  
- `updated_screens.dart:3799–3812` — **quick metrics bar** (**§B1**, **D9**)  
- `updated_screens.dart:1788` — **`_showNudgesSheet`**  
- `updated_screens.dart:3392` — **`_showMetricsSheet`**  
- `updated_screens.dart:1540` — **`get_pending_nudges`**  
- `updated_screens.dart:2145` — **`get_metrics`**  
- `updated_screens.dart:1775–1782` — **`nudge_mark_opened`**, **`nudge_dismiss`**  
- `updated_screens.dart:3663` — **`NeuralInterfaceV2`** shell (**§3 row 7**)  
- `updated_screens.dart:1222–1271` — **`_pendingNudges`**, **`_metrics`** (representative state — foundational §**3 row 7**)

### Bridge

- `bridge_server.py:28200` — **`get_pending_nudges`** handler (cited in `_FOUNDATIONAL_SPEC.md` §**4.B**)  
- `bridge_server.py:14734` — **`get_metrics`** handler (cited in `_FOUNDATIONAL_SPEC.md` §**4.B**)  
- **`nudge_mark_opened` / `nudge_dismiss`** handler line(s) — **TBD** in foundational §**4.B** table

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| **`_pendingNudges`** | List driving **§A row 4** visibility — `_FOUNDATIONAL_SPEC.md` §**3 row 7** + **`1222–1271`** |
| **`_metrics`** | Drives **quick bar** + **metrics sheet** — same block |
| Loading / error flags for poll | **TBD** — must clear on **`dispose`** per `_PIPELINE_TEMPLATE.md` §5 rule |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` |
|-----------|------|---------------------|---------------------|
| → | `get_pending_nudges` | **`1540`** | **`28200`** |
| → | `get_metrics` | **`2145`** | **`14734`** |
| → | `nudge_mark_opened` | **`1775–1782`** subset | **TBD** |
| → | `nudge_dismiss` | **`1775–1782`** subset | **TBD** |

**Critical pairings**

- Every **optimistic** list update **must** time out or reconcile with server list on next **`get_pending_nudges`** (**TBD** policy).  
- **`client_*` schedule messages** are **out of scope** here — do not conflate with nudge transport (`_FOUNDATIONAL_SPEC.md` §**4.A** vs §**4.B**).

---

## 7. Database tables touched

- **TBD** — resolve from bridge handlers **`28200`**, **`14734`**, and **`nudge_*`** branch (**not** enumerated in foundational §**5** for this slice).

**Cross-feature hazards**

- **Nevedal biometrics** (`biometric_update` — §**3 row 8**) may **correlate** with metrics UX; do not duplicate metrics sources without product review (`nevedal_flutter.dart:471–516` cited in foundational §**3**).

---

## 8. Edge cases

- **Reconnect:** **`login_request`** rerun — **`01`** — `_pendingNudges` / `_metrics` **stale vs server** until next poll — **TBD** refresh hook  
- **Family nav socket close** — **`3701–3712`** — returning to chat may need **explicit** nudge/metrics refresh — `_FOUNDATIONAL_SPEC.md` §**6**  
- **Empty nudges:** AppBar icon **hidden** — user education / settings link **TBD**  
- **Empty metrics quick bar:** bar **hidden** — composer layout jump **TBD**  
- **Auth lost mid-session:** prefer **manual recovery** after WS **`onDone`** — template §8  

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 — `_FOUNDATIONAL_SPEC.md` §**9** (verbatim).

| Commit | Summary |
|--------|---------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject proposals that**

- ❌ **Swallow** nudge or metrics errors in **`except`** without user-visible signal (cf. **`8c2a768` / `c43b9a3`** diagnostics culture).  
- ❌ Add **second WebSocket** for nudges without lifecycle + auth parity (**`distress_beacon`** pattern — foundational §**3 row 16**, §**6**).  
- ❌ **Merge** unrelated **`client_*`** schedule payloads into nudge polling without **`role == "CLIENT"`** review (**`38158cc`** / foundational §**4**).

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence |
|----|---------|----------|
| NM-01 | **`nudge_*`** bridge handler line **TBD** — audit risk | `_FOUNDATIONAL_SPEC.md` §**4.B** |
| NM-02 | **Loading vs empty** quick bar — possible indistinguishable states | `_TAB_INVENTORY` §**B1** |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10** + **`_TAB_INVENTORY_2026-05-05.md`** conditional UX.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **Family Sanctuary** closes primary chat socket — return path + refresh semantics for **nudges/metrics** — **`3701–3712`** | **TBD** |
| 2026-05-05 | Medium | **Nudges** AppBar **vanishes** when queue empty (**§A row 4**) — **discoverability** of “what nudges are” | **TBD** |
| 2026-05-05 | Medium | **Quick metrics bar** hidden when **`_metrics.isEmpty`** (**§B1**) — layout shift / “did metrics break?” | **TBD** |
| 2026-05-05 | Low | **`NeuralInterface`** legacy vs **`V2`** — wrong QA surface — **`main.dart:1339`** vs **`updated_screens.dart:1183`** | Doc / deprecate (**foundational §10**) |

---

## 12. Security boundaries

- **Nudges** are **server-authored** payloads for **`current_profile`** only — never render **coach roster** or other users’ queues.  
- **Metrics** (**C_emo**, mood, etc.) are **self** telemetry on the authenticated socket — align with HIPAA-adjacent “minimum necessary” UX (**TBD** legal copy).  
- **Bridge:** until **`nudge_*`** handler lines are verified, treat **missing `CLIENT` gate** as **`client_get_coach_month_overview`**-class review item (pattern: `_FOUNDATIONAL_SPEC.md` §**4.A** note).  

---

## 13. Manual test scenarios

1. **Login** **CLIENT** → confirm **`get_pending_nudges`** path fires (**devtools / logs `TBD`**) **`1540`**.  
2. With **≥1** nudge → open sheet **`3726–3743` / `1788`** → **mark opened** → **`1775–1782`** verified.  
3. **Dismiss** nudge → list + AppBar visibility update; **failure** inject → error UI (**TBD**).  
4. Open **metrics sheet** **`3745–3749` / `3392`** after **`2145`** success; verify **numbers** match **quick bar** subset **`3799–3812`**.  
5. **Reconnect** WS → parity of counts after **`login_request`**.  
6. Navigate **Family** → **`3701–3712`** → return → **`01`** reconnect → stale vs fresh **TBD**.

---

## 14. Foundational spec cross-reference

- **Parent:** §**3 row 7** (Neural chat **v2**)  
- **WS:** §**4.B** — **`get_pending_nudges`**, **`get_metrics`**, **`nudge_mark_opened`**, **`nudge_dismiss`**  
- **Lifecycle / sockets:** §**6** (**Family** teardown **`3701–3712`**)  
- **Related telemetry volume:** §**7** (**Nevedal biometric** **`2s` timer**)  

---

## 15. Daily health checks

Anchors **`1540`**, **`1775–1782`**, **`2145`**, **`1788`**, **`3392`**, **`3726–3749`**, **`3799–3812`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/14_nudges_and_metrics.md +
_TAB_INVENTORY §A rows 4–5, §B B1, §D D7–D9, §G G3–G4 +
_FOUNDATIONAL_SPEC §3 row 7, §4.B get_* / nudge_*.
Complements 01; bridge nudge handler lines TBD in §6.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
