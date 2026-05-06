# Client Portal — AI Modes picker

> Status: `DRAFT` (mode catalog / labels **TBD** inside **`_showAiModePicker`**)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G2**, **§D D5**, **§A row 3** (`psychology` AppBar). `_PHASE_3_PLAN.md` **spec 13**. Outbound **`ai_mode_activate` / `ai_mode_deactivate`** — `_FOUNDATIONAL_SPEC.md` §**4.B** + §**3 row 7**. **Not** coach **`AIModesSelectorScreen`** — **`settings_screen.dart:5252–5255`** (coach-only — foundational non-finding). Prefix **`13_`**.

---

## 1. Purpose (1 sentence)

Let **CLIENT** users on **`NeuralInterfaceV2`** open the **AI Modes** picker (**`updated_screens.dart:3717–3724`**) via **`_showAiModePicker`** (**`1940`**), activating or deactivating server-backed AI modes using **`ai_mode_activate` / `ai_mode_deactivate`** (**`1877–1889`**) over the authenticated chat WebSocket (`_FOUNDATIONAL_SPEC.md` §**4.B**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**A row 3**, **D5**; `_FOUNDATIONAL_SPEC.md` §**4.B**, §**3 row 7**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **`psychology`** AppBar entry — **`3717–3724`** — always available on inventory table (**§A row 3**: “Conditional? **None**”); regressions screened after tier-gate changes (**TBD** product overrides)  
- [ ] **`_showAiModePicker`** **`1940`** presents a **chooser** users can dismiss without trapping focus (**TBD** a11y)  
- [ ] Selecting a mode sends **`ai_mode_activate`** — **`1877–1889`** subset **TBD** exact branch  
- [ ] Clearing / switching sends **`ai_mode_deactivate`** (or paired sequence) **`1877–1889`** — **no orphaned active mode** in UI (**TBD** server ack map)  
- [ ] **`login_request` / `expected_role: CLIENT`** must have succeeded — **`1488–1493`** (**`01`**) — before modes work on same **`_socket`**  
- [ ] Errors: failed activate/deactivate shows **recoverable** state (**template** — no silent no-op)  
- [ ] **Touch targets** ≥ **44pt** — template  
- [ ] **`nate_query`** **`3205–3209`** behavior with active mode labeled or discoverable (**TBD** composer chrome) — **`01`**  
- [ ] **`COACH_ONLY`** path — **`6755–6759`** — no picker on **`ClientScheduleScreen`** (**implicit**)  
- [ ] Contrasts **`ai_chat`** tier rules in workspace — do not confuse with **coach** AIModes tooling (**coach settings** **`5252–5255`**)  

---

## 3. UI components

| Inventory | Location | Purpose |
|-----------|----------|---------|
| **§A row 3** | **`3717–3724`** | AppBar AI Modes action |
| **D5** | **`1940`** | **`_showAiModePicker`** sheet / dialog |
| **WS sends** | **`1877–1889`** | activate / deactivate payloads |

---

## 4. Files (canonical references)

### Mobile
- `updated_screens.dart:1877–1889` — **`ai_mode_activate`**, **`ai_mode_deactivate`**  
- `updated_screens.dart:1940` — **`_showAiModePicker`**  
- `updated_screens.dart:3717–3724` — AppBar **`psychology`** control  
- `updated_screens.dart:3663` — **`NeuralInterfaceV2`** shell (**§3 row 7**)

### Bridge
- **`bridge_server.py`** handler for **`ai_mode_*`** — **TBD** (foundational §**4.B**)

### Explicit non-scope
- **`settings_screen.dart:5252–5255`** — **coach-only** AIModes (`_FOUNDATIONAL_SPEC.md` explicit non-findings bullet)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| Active mode id / label | **TBD** in **`NeuralInterfaceV2`** state — likely near **`1222–1271`** (**`01`**) |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` |
|-----------|------|---------------------|---------------------|
| → | `ai_mode_activate` | **`1877–1889`** | **TBD** |
| → | `ai_mode_deactivate` | **`1877–1889`** | **TBD** |

---

## 7. Database tables touched

- **TBD** — mode persistence (if any) via bridge — **not** enumerated in foundational §**5**

---

## 8. Edge cases

- **Reconnect:** **`login_request`** rerun — **`01`** §**6** — active mode UX vs server truth **TBD**  
- **Family nav socket close** — **`3701–3712`** — mode chip state after return — **TBD**  
- **Double-tap activate:** debounce vs server idempotency — **TBD**  

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

**Reject:** emitting **`ai_mode_*`** **before** auth’d profile on **`_socket`**; cloning **coach-only** AIModes UI into **`CLIENT`** picker without entitlement review (**TBD**).

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| AM-01 | Bridge **`TBD`** line — orphaned client sends |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10** + analogy.

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | High | **`ai_mode_*`** bridge lines **TBD** — §**4.B** | **Silent server drops** invisible to QA |
| 2026-05-05 | Medium | **`NeuralInterface`** legacy vs **`V2`** — **`main.dart:1339`** vs **`1183`** | Wrong surface for picker QA |
| 2026-05-05 | Medium | **`COACH_ONLY`** vs full chat split — **`6755–6759`** | User never sees picker — support confusion |
| 2026-05-05 | Low | Duplicate **AI modes** naming: **coach** settings **`5252–5255`** vs **CLIENT** **`3717`** | Doc / support glossary drift |

---

## 12. Security boundaries

- **Modes** may change prompt / tool behavior server-side — **must** enforce **role + entitlement** on bridge (**TBD**)  
- Never trust **client-only** toggle for PHI-sensitive behaviors — **`1877–1889`** is **intent** only  

---

## 13. Manual test scenarios

1. Open picker **`3717–3724`** → choose mode → **`ai_mode_activate`** observed (devtools / logs **TBD**).  
2. Deactivate / switch modes → **`ai_mode_deactivate`** / sequence.  
3. **Reconnect** WS → verify mode state (**TBD**).  
4. **Web** parity (**TBD**).  
5. Confirm **coach** portal picker is **distinct** (**non-scope** above).  

---

## 14. Foundational spec cross-reference

- **Parent:** §**3 row 7**  
- **WS:** §**4.B** **`ai_mode_*`**  
- **Lifecycle:** §**6**  

---

## 15. Daily health checks

Anchors **`1877–1889`**, **`1940`**, **`3717–3724`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/13_ai_modes_picker.md +
_TAB_INVENTORY §A row 3, §D D5, §G G2 + _FOUNDATIONAL_SPEC §4.B ai_mode_*.
Complements 01; bridge handler lines TBD.
Exclude coach AIModesSelectorScreen (settings 5252–5255).
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
