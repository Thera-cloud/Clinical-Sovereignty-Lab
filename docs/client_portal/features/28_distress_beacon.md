# Client Portal — Distress beacon

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 16** — **Distress beacon** — `distress_beacon_screen.dart:212` (**primary `build`**); **WebSocket separate** **`WebSocketChannel.connect`** — `distress_beacon_screen.dart:77–78`; **outbound** **`distress_beacon`** payload — `distress_beacon_screen.dart:173–178`; **`_ownSocket`**, **`_beaconActivated`** — `distress_beacon_screen.dart:49–52`.

**Plan:** `_PHASE_3_PLAN.md` **spec 28** — §3 **r16**, **inventory E6** — **“separate WS — stays one spec”** (**do not split** beacon transport from this file).

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` **§B YOUR TOOLS** — **Distress Beacon** — `2894–2898` → **`DistressBeaconScreen`**; gate **`!_isCoachOnly`** — `2872` (same **YOUR TOOLS** block as specs **25–27**). **E6** cites class entry — `distress_beacon_screen.dart:33`, `47`; payload — `173–178`.

---

## 1. Purpose (1 sentence)

Give **eligible clients** (**`2872`**) a **YOUR TOOLS** entry (**`2894–2898`**) to **`DistressBeaconScreen`** (**`212`**) that **opens its own bridge WebSocket** (**`77–78`**) and sends **`distress_beacon`** (**`173–178`**) so a **distinct** latency-sensitive path (**E6**) can signal crisis support **without assuming** reuse of **`NeuralInterfaceV2`**’s **`login_request`** (**§6 item 7**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 16**, §**4.B**, §**5**, §**6**, §**7**, §**8**; `_TAB_INVENTORY_2026-05-05.md` §**B** + **E6**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **YOUR TOOLS → Distress Beacon** — **`2894–2898`** — only when **`!_isCoachOnly`** — **`2872`**
- [ ] **`DistressBeaconScreen` `build`** — **`212`** — **distinct** UX for **inactive** vs **`_beaconActivated`** — **`49–52`** — no **ambiguous** **“did it send?”** state (**§7 debt** aligns)
- [ ] **`_ownSocket`** — **`49–52`** + connect — **`77–78`** — **`dispose`/`finally`** closes the **secondary** socket; **no** **orphan** connection after **`Navigator.pop`** (**template §116** analogue)
- [ ] **`distress_beacon`** JSON — **`173–178`** — matches **§4.B** contract; failures surface **retry** / **explain** (**not** empty UI — **`8c2a768`**-class rejection)
- [ ] **`swarm_relay.request(...)`** path — **`bridge_server.py:28669–28675`** — delivery **opaque** to client → UI must **not** promise **coach arrival time** unless product copy is added (**§5 persistence — TBD**)
- [ ] **`401`/`403`/disconnect** — user-visible distinction; **no** **loop** tying beacon socket errors to **`NeuralInterfaceV2`** health without copy (**dual-connection** literacy)
- [ ] **`expected_role` / CLIENT session** — user expectation: only **authenticated CLIENT** invokes beacon; **`§4.B` notes bridge handler** **`28663`** **lacks** shown **`role == "CLIENT"`** — treat **server parity** as **open risk** (**DB-SEC** backlog)
- [ ] **`COACH_ONLY`** — row **hidden** — **`2872`**
- [ ] **Touch targets** ≥ **44pt** on **activate / cancel / help** actions (**TBD** widget-level map)
- [ ] **Crisis-adjacent** copy — calming, **clear** escalation **limits** (**TBD** legal/clinical steward); **no** **911**/emergency substitutes unless product mandates (**OUT OF SCOPE** **jurisdiction text** unless in existing compliance docs)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| Class / entry cues | `33`, `47` (**E6**) | Screen lifecycle hooks (**TBD** detail) |
| State | `49–52` | **`_ownSocket`**, **`_beaconActivated`** |
| Connect | `77–78` | **Separate** **`WebSocketChannel.connect`** |
| Payload send | `173–178` | **`distress_beacon`** message body |
| `build` | `212` | Full UI |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2872` — **`!_isCoachOnly`** (**YOUR TOOLS**)
- `settings_screen.dart:2894–2898` — **Distress Beacon** nav row
- `distress_beacon_screen.dart:33`, `47` — **E6**
- `distress_beacon_screen.dart:49–52` — **`_ownSocket`**, **`_beaconActivated`**
- `distress_beacon_screen.dart:77–78` — **separate WS**
- `distress_beacon_screen.dart:173–178` — **`distress_beacon`**
- `distress_beacon_screen.dart:212` — **`build`**

### WebSocket / bridge

- **`distress_beacon`** Flutter → **`bridge_server.py:28663`** (**§4.B** — **role guard not shown** in excerpt)
- **`swarm_relay.request(...)`** — **`28669–28675`** (**§5** — **persistence TBD**)

### WebSocket — **primary chat** (**contrast only**)

- **`login_request`** + **`NeuralInterfaceV2`** — `updated_screens.dart:1467–1493` (**§6 items 4–5**) — beacon **explicitly diverges** — **§6 item 7**

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_ownSocket` | Must **cancel** subscriptions / **close** on **dispose** |
| `_beaconActivated` | UX must reflect **idempotent** re-tap (**TBD** product rule) |

---

## 6. WebSocket messages

### Outbound (this screen)

| Type | Flutter anchor | Bridge anchor |
|------|----------------|----------------|
| `distress_beacon` | `173–178` | `28663` |

### Inbound (**TBD**)

- **`_FOUNDATIONAL_SPEC.md`** §4.B marks **notes** column sparse for beacon — **investigation cache** on **ack/errors**.

---

## 7. Database tables touched

- **§5:** **`swarm_relay`** fan-out (**`28669–28675`**) — **persistence narrative — TBD**
- Any **immutable** **`skyeye_activity` / PHI** audit rows — **TBD** (**do not cite** **`action`** columns — **`type`** canonical per workspace rule when tracing)

---

## 8. Edge cases

- **Primary chat WS** **down** but **distress socket** **up** (**or inverse**) — user messaging (**TBD**)
- **`Navigator`** **rapid** push/pop — **`_ownSocket`** **still** **open** (**leak** risk)
- **Bridge** rejects **`distress_beacon`** without **`current_profile`** — mirror **`get_history`** pattern risk — **`bridge_server.py:14765–14768`** (**§4.D** analogue — **not** beacon-specific verified)

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

- ❌ **Hide** **`distress_beacon`** failures — **silent** drop (**`8c2a768`** analogue) on **lifeline** surface
- ❌ **`WebSocketChannel.connect`** **without** **documented** **auth** + **`dispose`** — **`_PIPELINE_TEMPLATE.md`** §116; **contrasts** **`ClientScheduleScreen`** **`38158cc`** intentional **hub** reuse
- ❌ **Assume** **second socket** inherits **`ACTIVE_TOKENS`** / **`login_request`** **timing** parity with **chat** — **§6.7**

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| DB-01 | **`distress_beacon`** handler **`28663`** — **no shown** **`role == "CLIENT"`** — **§4.B** |
| DB-02 | **`swarm_relay`** downstream **persistence / receipt** — **§5 TBD** — user **cannot verify** coach **got** ping |
| DB-03 | **`login_request`** **absent** in **traced snippet** (**`75–78`**) vs **authenticated** **`NeuralInterfaceV2`** story — **§6.7**, **§10** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **_FOUNDATIONAL_SPEC.md §10** plus **compound-session** note from **`08_critical_session_security_modals.md`**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | Medium | Second **WS** (**`75–78`**) **without obvious** **`login_request`** — **§10 row** | Auth story + **in-app FAQ** tying **tokens** (**28** ↔ **05** / **01**) |
| 2026-05-05 | Medium | Relation to **`_ClientWsHub`** + **hard-stop** teardown — **`08_critical_session_security_modals.md`** **§11** cites **`75–78`** | **Canonical** **multi-socket** **teardown order** (**08** § edge) |
| 2026-05-05 | High | Beacon sits beside **Brief**/**Coherence**/**Memory** (**`2872`** block — **25–27**) — **“insights vs emergency”** **IA clutter** | **Tiered** grouping or **sticky** crisis entry (**product**) |
| 2026-05-05 | Low | **`swarm_relay`** **opaque** — user **trust** hinges on **copy** alone | **DELIVERED**/timeout states when **persisted** (**DB-02**) |

---

## 12. Security boundaries

- Beacon must **never** escalate **privileged** **`coach`**/ **`ADMIN`** surfaces from **CLIENT** typo (**§8** posture)
- **Second connection** expands **attack surface** (token exposure, reconnect storms) — align with **`endpoint-websocket-sustainability.mdc`** backoff **when** patching (**workspace** meta — **not** re-derived here)

---

## 13. Manual test scenarios

1. **CLIENT**, **`!_isCoachOnly`** → **YOUR TOOLS** → **Beacon** **`2894–2898`**
2. Activate → **`_beaconActivated`** **true**
3. **Airplane mode** mid-flight → surfaced error (**not** silent)
4. **`Navigator.pop`** → **`_ownSocket`** **closed** (no leak heuristic)
5. **`COACH_ONLY`** → row **absent**

---

## 14. Foundational spec cross-reference

- **§3 row 16** — screen + WS + payload + state
- **§4.B** **`distress_beacon`** → **`28663`**
- **§5** **`28669–28675`**
- **§6 items 4, 7** — **dual-socket story**
- **§7** **distress socket without login snippet**

---

## 15. Daily health checks

Anchors **`2872`, `2894–2898`, `49–52`, `77–78`, `173–178`, `212`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/28_distress_beacon.md +
_FOUNDATIONAL_SPEC §3 row 16, §4.B distress_beacon, §6.7 +
_TAB_INVENTORY YOUR TOOLS 2894–2898 + E6.
Trace distress_beacon_screen dispose + second socket lifecycle vs _ClientWsHub (01).
Verify bridge_server.py 28663 role guard + 28669 swarm_relay persistence.
```

---

## 18. Explicit OUT OF SCOPE

- **`NeuralInterfaceV2`** **full** message matrix — **`01_chat_with_nate.md`**
- **`_ClientWsHub`** **schedule-only** reuse — **`16_client_schedule.md`** (**blocked**) / **`main.dart`** hub lines **§3 row 10**
- **Clinical** routing to **988/911** **jurisdictional** disclaimers unless already in **`38`** compliance text
- **`34_coaching_packs.md`** — inventory stub **filename drift** (**`275`**); **this** spec **`28`** is canonical per **`_PHASE_3_PLAN.md`**

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md`, **`08_critical_session_security_modals.md`** **§11** cross-cite — `2026-05-05`.*
