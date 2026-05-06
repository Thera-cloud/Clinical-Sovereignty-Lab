# Client Portal — Quests & missions

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap coverage:** **`G13`** (`_TAB_INVENTORY_2026-05-05.md` §**G**) + **`E18`** dialogs.

**Plan:** `_PHASE_3_PLAN.md` **spec 32** (**G13**, **E18** folded). Prefix **32_**.

**Foundational gap:** §3 table has **no dedicated row** — feature lives inside **`settings_screen.dart`** (**hub row 11** child surface).

---

## 1. Purpose

Expose **quests** and **missions** lists plus **pause/complete** flows and **“New Quest / Mission”** dialogs (**`406`**, **`431`**) gated under **`YOUR QUESTS & MISSIONS`**.

---

## 2. UX acceptance (**8+**)

- [ ] Section header — **`3024–3025`** — icon & label coherent with **`15`** recap card wording (**cross-ref**, not duplicate UX)
- [ ] **`_fetchQuestsAndMissions`** — **`380–391`** dual **GET `api/sse-client/quests`** + **`.../missions`** using **Bearer** — **`382–385`**
- [ ] Silent **`catch (_) {}`** **`391`** — flagged as reliability debt — must not regress to masking **persistent** outages (**reject `8c2a768`** class enhancements)
- [ ] **`_questAction`** / **`_missionAction`** — **`394–397`**, **`400–403`** — POST **`quest/{id}/{action}`**, **`mission/{id}/{action}`** — optimistic UI prohibited without confirm (**TBD**)
- [ ] Row rendering — **`3029–3038`** **`_questMissionRow`** — **pause/complete** reachable ≥ **44pt**
- [ ] **New Quest** dialog — **`406–427`** **`http.post .../quest/create`** — validates non-empty **`goal`** — **`418–419`**
- [ ] **New Mission** dialog — **`431–451`** **`http.post .../mission/create`** — **`relationship_target`**
- [ ] **`!_isCoachOnly`** terminator — **`3043`** closes combined **Coaching Tools + Archetype + Quests** guard — aligns **§H** matrix **`2975`**, **`3043`**
- [ ] **`401`/token drift** UX — **`394–402`** naive await — failures invisible (**QM-03** debt)
- [ ] Offline — **SnackBar parity** (**TBD**)

---

## 3. Anchors (`settings_screen.dart`)

| Concern | `file:line` |
|---------|-------------|
| Fetch quests/missions | `380–391` |
| Actions | `394–403` |
| Dialogs (**E18**) | `406–427`, `431–451` |
| Section UI | `3024–3041` |
| Gate end | `3043` |

---

## 4. REST (**from Flutter only**)

- `GET /api/sse-client/quests`
- `GET /api/sse-client/missions`
- `POST /api/sse-client/quest/{questId}/{action}`
- `POST /api/sse-client/mission/{missionId}/{action}`
- `POST /api/sse-client/quest/create`
- `POST /api/sse-client/mission/create`

**(Router proofs — **TBD**.)**

---

## 5–8. WS / DB / edge

- Hub optional **`widget.socket`** — quests path **REST-only**
- Persisted quests tables — **TBD**
- **Edge:** partial JSON (`started_at`) — **`3031`** day calc fallback — **`DateTime.now()`** (**clock skew UX** debt)

---

## 9. Anti-patterns (**§9 verbatim`)

**Reject:** deepening silent catches | cross-user mission visibility regressions (**privacy**) | coach-assigned quests without **`CLIENT`** guard (**bridge** analogue).

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| QM-01 | **Silent `_fetchQuestsAndMissions` failures** (`**391**`) |
| QM-02 | **`_questAction`/`_missionAction` lack response checks** (**`394–402`**) |
| QM-03 | **No failure snackbars on POST `/quest/create`** success-only path (**`423–426`**) — **partial** (**TBD** error branch) |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **`Day N` maths** (**`3031`**) hides stalled server clocks | Relative timestamps |
| 2026-05-06 | Medium | **`Quest` vs `Mission` mental model** only in subtitles | onboarding tooltip |
| 2026-05-06 | Low | Adjacent **`Archetype`** reset (**`33`**) can confuse storyline ownership | Combined microcopy QA |
| 2026-05-06 | Low | Settings density — five stacked cards before **SECURITY** (**`2975–3043`**) | progressive disclosure roadmap |

---

## 12–16. Standard blocks

Security: Bearer only; quests text may include sensitive goals — discourage screenshots (**TBD**).

Manual: pause/complete, create flows, gated removal when **`CoachOnly`**.

---

## 17. Cursor prefix

```
Prefix 32_. settings_screen quests block 3024–3043;
fetch stack 380–403; dialogs 406/431.
Audit silent catches + POST status UX.
```

---

## 18. OUT OF SCOPE

- **`33_archetype_identity.md`** (**reset differs** from quest progress UI copy)
- **`15_sse_story_journey_and_recap.md`** recap engine
- **Coach dashboards**

---

*`2026-05-06`.*
