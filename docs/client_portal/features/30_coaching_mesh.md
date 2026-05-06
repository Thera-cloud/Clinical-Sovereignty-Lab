# Client Portal — Coaching mesh (group session)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

## Mesh VERIFY (Phase 3 batch)

**Decision:** **`CoachingMeshScreen`** vs **`CommunityMeshScreen`** are **distinct Flutter products**.

| Screen | Anchor | Signals |
|--------|--------|---------|
| **Coaching** | `mobile/lib/screens/coaching_mesh_screen.dart:111` | **`CoachingMeshScreen(profile, token, isMaster)`** — coach-led DOJO / training vocabulary (**`dojo`**, **`isMaster`**, **`quiz`**, **BLE**) |
| **Community** | `mobile/lib/screens/community_mesh_screen.dart:84` | **`CommunityMeshScreen(profile)`** — peer **`WisdomInsight`**, **tier gate** |

**Committed outcome:** specs **`30`** + **`31`** (**not** collapsed to `30_mesh_screens.md`).

---

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 18** — **`coaching_mesh_screen.dart:669`** (`**build`**); WS / outbound — **TBD**; representative state — **TBD**.

**Plan:** `_PHASE_3_PLAN.md` **spec 30** — §3 **r18** + **inventory COACHING TOOLS**. Prefix **30_**.

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` §**B COACHING TOOLS** — **Group Session** — `2979–2987` → **`CoachingMeshScreen`** (**`profile`**, **`token`**, **`isMaster: false`**); **`!_isCoachOnly`** — `2975`.

---

## 1. Purpose (1 sentence)

Let **eligible clients** push **`CoachingMeshScreen`** (**`2979–2987`**) so they can participate in **coach-led group training mesh** sessions with **DOJO-typed flows** seeded in **`coaching_mesh_screen.dart:111`**+.

---

## 2. UX acceptance criteria (**8+**)

- [ ] **COACHING TOOLS → Group Session** — **`2979–2987`** — guarded **`2975`** (`**!_isCoachOnly`**)
- [ ] **`build`** — **`669`** shows **idle / loading / error** distinctively — **`149–150`** pattern region (**`_isLoading`**, **`_errorMessage`**)
- [ ] **`initState`** — **`180–184`** **`_tabController`** + **`_connectWebSocket()`** — **no orphan** **`TabController`**
- [ ] **`dispose`** — **`186–196`** cancels **`_wsSubscription`**, closes **`_wsChannel`**, disposes **`_tabController`** / timers (**template lifecycle**)
- [ ] **`WebSocket`** errors surface via **`_errorMessage`** / handlers — **not** silent (**`8c2a768`** reject)
- [ ] **`isMaster`** from nav is **`false`** for default client row — **`2982–2985`**
- [ ] **`COACH_ONLY`** — entire **`2975`** block omitted — aligns with **`_TAB_INVENTORY` §H**
- [ ] **BLE discovery** timeouts — **`158–159`** region — user-visible (**TBD** copy audit)
- [ ] **`401`/`403`** / hub token drift — degrade without logging user out blindly (**trust #71**)
- [ ] Touch targets — **quiz / chat tabs** ≥ **44pt** — **TBD**

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| `CoachingMeshScreen` | `111–121` | **StatefulWidget** ctor + fields |
| `initState` | `179–184` | **TabController**, **socket connect**
| `dispose` | `186–196` | Cleanup |
| `build` | `669` | Primary scaffold |

---

## 4. Files

- `settings_screen.dart:2975`, `2979–2987`
- `coaching_mesh_screen.dart:111–196`, `669`
- Bridge / DB — **TBD** (foundational §3 row 18)

---

## 5–7. State / WS inbound-outbound / DB

- Representative state rows — **§3 foundational TBD**
- **`distress_beacon`** / **dual-socket anti-pattern analogies** — see **`28_distress_beacon.md`**
- **DB** — **`coaching_mesh_*`** tables per workspace **`coaching-mesh-architecture.mdc`** — **TBD tie-in**

---

## 8. Edge cases

- **`token` empty string** navigation — **`2983`** — handler must fail soft (**TBD**)
- **Judge DOJO pricing** unrelated — **coach upgrade** (**`37`**) confusion — copy guard

---

## 9. Anti-patterns (**§9 verbatim + rejects**)

| Commit | Summary |
|--------|---------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject:** silent mesh failures | unauthorized master toggles surfaced to client | undocumented second-socket posture vs **`01`/`28`**.

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| CM-01 | Foundational §3 **transport TBD** for row 18 |
| CM-02 | Assistant coach visibility vs **coach hierarchy** bridge rules — workspace rule — **cross-audit** |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | High | **`Coaching`** vs **`Community`** names sit adjacent (**`2977–2994`**) — user confusion | Icon + subtitle copy QA |
| 2026-05-06 | Medium | **`DOJO` method matrix** exposes **seven** archetypes (**`162–168`**) vs client comprehension | Progressive disclosure |
| 2026-05-06 | Medium | Separate **`WebSocketChannel`** (**`147`**) lifecycle vs **`_ClientWsHub`** — parallels **`§6 item 7`** | Unified auth storytelling doc |
| 2026-05-06 | Low | BLE timeouts — **`158–159`** — anxiety if silent | Telemetry + microcopy |

---

## 12. Security / 13 Manual / 14 Cross-ref / 15 Health / 16 Cache

- Treat **participant broadcast** payloads as sensitive — **`coaching-mesh-architecture.mdc`**.
- Tests: gated nav, **`dispose`** storm, **`isMaster`** false path.
- **§3 row 18**; anchors stable.

---

## 17. Cursor prefix

```
Prefix 30_. VERIFY done: coaching_mesh_screen.dart:111 vs community:84 distinct.
Trace coaching_mesh_screen WebSocket messages ↔ bridge_mesh / coach hierarchy.
```

---

## 18. OUT OF SCOPE

- **`31_community_mesh.md`**
- **Coach assistants / master** dashboards
- **`16_client_schedule.md`** (**blocked**)

---

*Phase 3 batch — `2026-05-06`. Mesh VERIFY embedded above.*
