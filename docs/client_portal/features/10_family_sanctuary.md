# Client Portal — Family Sanctuary

> Status: `DRAFT` (**`sanctuary_*`** message enumeration per handler case **TBD** beyond **`3604`** / **`3882+`**)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 9**, §**6** point **6**, §**8**; `_TAB_INVENTORY_2026-05-05.md` **§A row 2** (AppBar **Family Sanctuary**), **D12** (nav + socket policy); `_PHASE_3_PLAN.md` **spec 10** (socket-close caveat **`_FOUNDATIONAL_SPEC.md` §10**). Prefix **`10_`**.

---

## 1. Purpose (1 sentence)

Let clients open **Family Sanctuary** from the chat **`AppBar`** (**`updated_screens.dart:3698–3715`** — §**A row 2** / **D12**) while the feature **`build`** lives on **`main.dart:5684`**, maintaining member/message state (**`2671–2678`**) over **`_channel`** (**`2667–2668`**) via **`sanctuary_*`** bridge messages (**`3604`**, **`3882+`**), with **parent chat WebSocket teardown before push** and **reconnect on return** (**`updated_screens.dart:3701–3712`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 row **9**, §**6**, §**7** (SW caveat); `_TAB_INVENTORY_2026-05-05.md` §**A** row **2**, **D12**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **Entry:** **`family_restroom`** action reaches sanctuary UI without dead-end — **`3698–3715`** (inventory §**A**); primary scaffold **`5684`** (§**3 row 9**)  
- [ ] **Socket lifecycle:** entering sanctuary **closes** the parent **`NeuralInterfaceV2`** chat socket before navigation — **`3701–3703`** (**D12**, §**6**.6); user-visible **latency / reconnect** story is acceptable or explained (**§10**)  
- [ ] **Return path:** **`3712`** — chat **reconnects** after pop; no stranded “connected” UI with a dead **`_socket`**  
- [ ] **iOS Safari:** WS contention rationale documented — **`3701–3703`** (**D12**) — regressions screened on Safari (**§7** SW **TBD** + workspace rules)  
- [ ] **Member list / messages:** state stays coherent — **`_sanctuaryId`, `_members`, `_messages`** **`2671–2678`**; empty vs error distinguished (**template**)  
- [ ] **Outbound typing:** **`sanctuary_*`** dispatch matches handler **`switch`** cases — **`3604`**, **`3882+`** — no silent drops (**TBD** per-case ACK map)  
- [ ] **`expected_role`:** Sanctuary rides **`main.dart`** WS context for **CLIENT** flows; dual-role testers use correct portal (**lobby rule**)  
- [ ] **Contrast `01_chat`:** chat **`login_request`** / **`1488–1493`** is **not** assumed live while Sanctuary is foreground (**§6**.6)  
- [ ] **`sanctuary_get_members`** in **Family management** (**`billing_screens.dart:900`** — §**3 row 21** / spec **20**) is a **related** surface — do not confuse roster settings UX with Sanctuary **conversation** UX  
- [ ] Touch targets ≥ **44pt** on sanctuary primary actions — template  

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| **Family Sanctuary scaffold / body** | `main.dart:5684` | Primary **`build`** (§**3 row 9**) | Entry from chat |
| **AppBar launch control** | `updated_screens.dart:3698–3715` | Push sanctuary route | §**A row 2**, **D12** |
| **Sanctuary WS + state** | `main.dart:2667–2668` (`_channel`); **`2671–2678`** | Transport + **`_sanctuaryId`**, **`_members`**, **`_messages`** | §**3 row 9** |

---

## 4. Files (canonical references)

### Mobile
- `main.dart:2667–2668` — **`_channel`** (Family Sanctuary WS)  
- `main.dart:2671–2678` — **`_sanctuaryId`, `_members`, `_messages`**  
- `main.dart:3604` — handler **`sanctuary_*`** (**representative**)  
- `main.dart:3882+` — **`sanctuary_*`** handler **`switch`** continuation  
- `main.dart:5684` — sanctuary **`build`**  
- `updated_screens.dart:3698–3715` — **Family Sanctuary** nav (**D12**)  
- `updated_screens.dart:3701–3712` — **close chat socket → push → reconnect** (**§6**.6)

### Bridge (WebSocket)

- **`sanctuary_*`** handlers — **TBD** line anchors in `bridge_server.py` (foundational §**4** does not list Sanctuary rows — trace when hardening §**6**)  

### REST (FastAPI)

- **N/A** for core sanctuary **WS** path on row **9** (**`sanctuary_get_members`** is **billing_screens / family mgmt** — spec **20**)

### Storage

- **TBD** — bridge persistence for **`sanctuary_*`** not enumerated in foundational §**5**

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_channel` | `WebSocketChannel?` | connect **TBD** | teardown **TBD** | **TBD** |
| `_sanctuaryId` | **TBD** | join / server **TBD** | exit **TBD** | **TBD** |
| `_members` | list / iterable **TBD** | server payloads **TBD** | exit **TBD** | **`[]`** / **TBD** |
| `_messages` | list / iterable **TBD** | server payloads **TBD** | exit **TBD** | **`[]`** / **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Notes |
|-----------|------|---------------------|-------|
| → / ← | **`sanctuary_*`** | **`3604`**, **`3882+`** (handler **switch**) | Prefix family — enumerate each **`elif`** **TBD** |
| *(lifecycle)* | *(parent chat socket close)* | **`3701–3703`** | Not a message **type** — **critical** UX pairing with **`01`** |
| *(lifecycle)* | *(reconnect on return)* | **`3712`** | Pop / resume chat |

---

## 7. Database tables touched

- **TBD** — link bridge **`sanctuary_*`** handlers → SQL when traced (foundational §**5** gap)

---

## 8. Edge cases

- **Pop quickly:** reconnect **`3712`** races with **Server** pushes — ordering **TBD**  
- **Hub / schedule:** **`_ClientWsHub`** (**`10316–10328`**) independent of Sanctuary **`_channel`** — clarify if user opened schedule via hub mid-session (**TBD**)  
- **Coach-only:** default client route may be **`ClientScheduleScreen`** — **`6755–6759`** — Sanctuary availability **TBD**  
- **Offline:** **`_channel`** **`onDone`** — distinguish offline vs sanctuary-specific errors  

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits — `_FOUNDATIONAL_SPEC.md` §**9** (verbatim).

| Commit | Summary (foundational) |
|--------|-------------------------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject:** navigating to Sanctuary **without** the **`3701–3712`** close/reconnect contract; assuming **`NeuralInterfaceV2`** **`_socket`** stays open under Sanctuary (**false** per §**6**.6).

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| FS-01 | Bridge **`sanctuary_*`** handler line inventory | §**4** gap | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows — `_FOUNDATIONAL_SPEC.md` §**10** (Family Sanctuary row) + adjacencies.

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | **High** | Opening **Family Sanctuary** **closes** primary chat socket — **`updated_screens.dart:3701–3703`** | User pays **reconnect latency** to mitigate **WS contention** — **§10**, **D12** |
| 2026-05-05 | Medium | **Service worker / web** quirks **TBD** — `_FOUNDATIONAL_SPEC.md` §**7** | Safari regression risk when **dual** socket story (chat teardown) interacts with stale SW (**workspace rules**) |
| 2026-05-05 | Medium | **`_ClientWsHub`** visibility vs dedicated **`2667`** sanctuary channel — **`10316–10328`** vs row **9** | Confusion when debugging “which socket failed?” |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** vs **V2** — **`main.dart:1339`** vs **`updated_screens.dart:1183`** | Wrong doc target if teardown code paths diverge |

---

## 12. Security boundaries

- **Privacy:** member list + messages stay in **sanctuary-local** Flutter state (**`2671–2678`**) until server **`sanctuary_*`** applies — **`§8`**  
- Only **authenticated** **`sanctuary_*`** traffic on user's channel — enforce on bridge (**TBD** handler audit)  
- **Family management** (**row 21**) **`sanctuary_get_members`** — **`billing_screens.dart:900`** — **coach / billing** framing; Sanctuary **conversation** ≠ settings roster (**spec 20**)  

---

## 13. Manual test scenarios

1. Login as **CLIENT** → **`NeuralInterfaceV2`** → tap **Family Sanctuary** **`3698–3715`**.  
2. Confirm chat socket **closes** before sanctuary visible — **`3701–3703`**.  
3. Send/receive **`sanctuary_*`**-driven UX (**TBD** case list).  
4. **Pop** → chat **reconnects** — **`3712`**.  
5. **Safari iOS:** repeat **2–4** after cold start (SW / cache sanity).  

---

## 14. Foundational spec cross-reference

- **§3 row:** **9**  
- **§2:** *(Family Sanctuary appears in §**3**; §**2** table excerpt in foundational doc does not list this row separately — cite §**3** as primary)*  
- **§6:** point **6** (teardown / reconnect)  
- **§8:** Sanctuary bullet  
- **§10:** first **High** debt row (socket close)  

---

## 15. Daily health checks

Manual: **`5684`**, **`2667–2678`**, **`3698–3715`**, **`3701–3712`**, **`3604`/`3882+`** anchors stable after edits.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational + inventory + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/10_family_sanctuary.md +
_FOUNDATIONAL_SPEC.md §3 row 9 + §6 point 6 (3701–3712).
Cross-ref 01_chat_with_nate.md — socket must not pretend live during Sanctuary.
Inventory: _TAB_INVENTORY §A row 2, D12.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
