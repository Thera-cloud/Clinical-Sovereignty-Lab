# Client Portal — Community mesh

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

## Mesh VERIFY (paired with **`30_coaching_mesh.md`**)

**Decision:** **`CommunityMeshScreen`** (`**community_mesh_screen.dart:84**`) is **not** a view-mode fork of **`CoachingMeshScreen`** (`**111**`). **Separate spec `31`** retained.

---

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 19** — **`community_mesh_screen.dart:570`** (`**build`**); WS / payloads — **TBD** inventory row.

**Plan:** `_PHASE_3_PLAN.md` **spec 31** — §3 **r19**. Prefix **31_**.

**Inventory:** §**B COACHING TOOLS** — **Community Circle** — `2988–2994` → **`CommunityMeshScreen(profile)`** — **`!_isCoachOnly`** — `2975`.

---

## 1. Purpose

Route **eligible clients** to **peer Nate-to-Nate** **`CommunityMeshScreen`** (**`2988–2994`**) for **anonymous wisdom resonance** workflows per **`.cursor/rules/community-mesh-privacy.mdc`** (workspace rule — **conceptual cite only**).

---

## 2. UX acceptance (**8+**)

- [ ] Entry **`2988–2994`** only when **`!_isCoachOnly`** — **`2975`**
- [ ] **`_checkTierAccess()`** **`142–151`** — **`COACH_ONLY`** shows explicit **upgrade** copy (not silent empty)
- [ ] **`_canAccess`** getter — **`154–156`** respects tier error sentinel
- [ ] **`_connectWebSocket()`** **`158–174`** — failures log + **`_onWsError`** pathway (**`168–169`**) — surfaced in UI (**`8c2a768`** reject)
- [ ] **`build`** — **`570`** primary UI — distinguishes **idle / session / attendance** (**TBD** branch names)
- [ ] **`WisdomInsight` model** — **`65–78`** presentation never leaks **PII** in UI labels (**privacy rule §1–3** analogue)
- [ ] **`_userId`** resolution — **`117–118`** fallback chain — aligns with **`profile`** keys (**§8**)
- [ ] Animated pulse — **`123–139`** doesn’t mask functional errors (**accessibility**)
- [ ] **Airplane mode** UX — websocket catch **`171–173`**
- [ ] **`401`/token** mismatches degrade without destructive logout (**trust #71**)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| `CommunityMeshScreen` | `84–88` | **profile-only** ctor |
| Tier gate | `142–151` | **COACH_ONLY** messaging |
| `WebSocketChannel.connect` | `158–160` | Dedicated socket (**AppConfig.wsUrl**) |
| `build` | `570` | Primary UI |

*(Second **`build`** at **`1375`** — internal widget; cite only when patching nested UI.)*

---

## 4. Files

- `settings_screen.dart:2975`, `2988–2994`
- `community_mesh_screen.dart:65–174`, `570`
- Workspace: **`community-mesh-privacy.mdc`**

---

## 5–7. State / Messages / DB

- State fields — **`93–118`** (**`_peers`**, **`_wisdomFeed`**, **`_moodValence`**, **`_sessionId`**…)
- Inbound **`community_mesh_*`** **`178+`** (**`switch`** head) — **TBD exhaustive list**
- **DB** **`community_*`** tables referenced in **`community-mesh-privacy.mdc`** — **TBD REST mirror**

---

## 8. Edge cases

- **Opt-in attendance** tracking — **`community_attendance_records`** narrative — **`privacy md rule §2`**
- **Location fields** vs wisdom anonymity — **rule §7**

---

## 9. Anti-patterns (**§9 verbatim**)

Same table as **`_FOUNDATIONAL_SPEC.md` §9`.

**Reject:** silent websocket parse failures masking abuse | **BLE** mixing UUIDs (**rule §9**) | collapsing into **`Coaching`** product without PM sign-off (**VERIFY block**).

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| CC-01 | Foundational §3 row 19 **transport TBD** |
| CC-02 | **`jsonDecode` catch** **`164–167`** swallow — audit logging gap vs **`background-agent-error-visibility.mdc`** (**TBD** remediation spec) |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | High | Adjacent **`Group Session`** label (**`2979–2987`**) increases mis-tap anxiety | Larger section divider / icon differentiation |
| 2026-05-06 | Medium | Separate **`wsUrl`** socket — story overlaps **`28`** **dual channel** literacy | Consolidated FAQ |
| 2026-05-06 | Medium | **Attendance opt-in** copy must beat **silent enrollment** (**privacy §2**) | audit checklist |
| 2026-05-06 | Low | **`community_wisdom`** anonymity vs user's desire for credit — tension | Product messaging |

---

## 12–16. Security / Tests / refs / anchors / cache

- Enforce **`COACH_ONLY` blocklist** UI + API (**privacy §10**).
- Tests: gated nav, websocket drop, **`_canAccess`** false path.
- **§3 row 19**.

---

## 17. Cursor prefix

```
Prefix 31_. Pair with 30 VERIFY. Trace community_mesh message types ↔ bridge/community tables.
Privacy: community-mesh-privacy.mdc.
```

---

## 18. OUT OF SCOPE

- **`30_coaching_mesh.md`**
- **`20_family_management.md`** (**sanctuary** separate product)
- **Token sharing BLE** (**`BLE gkm`** specs)

---

*Phase 3 batch — `2026-05-06`.*
