# Client Portal — Assessments (Quiz)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 17** — **Assessments** — `quiz_screen.dart:234` (**`build`**); transport / outbound messages — **TBD** in foundational inventory; **`QuizScreen` class + REST header** — `quiz_screen.dart:3–4`, `68–73`.

**Plan:** `_PHASE_3_PLAN.md` **spec 29** — §3 **r17**. Prefix **29_**.

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` §**B** YOUR TOOLS — **Assessments** — `2876–2880` → **`QuizScreen`**; gate **`!_isCoachOnly`** — `2872`.

---

## 1. Purpose (1 sentence)

Eligible clients (**`2872`**) open **`QuizScreen`** from **`2876–2880`** to complete **interactive assessments** surfaced by **`quiz_screen.dart:234`** with **REST** contracts declared in **`quiz_screen.dart:3–4`** (list / detail / submit — **handlers TBD line-level**).

---

## 2. UX acceptance criteria (client perspective)

- [ ] **YOUR TOOLS → Assessments** — **`2876–2880`** — only when **`!_isCoachOnly`** — **`2872`**
- [ ] **`build`** — **`234`** — **`_loading`** — **`256–258`** vs **list vs active quiz vs results** routing is **explicit** (**no silent blank** **`8c2a768`** class)
- [ ] **`_buildQuizList()`** empty state — **`269+`** ("No assessments available yet") surfaces when **`_quizzes.isEmpty`** — not confused with transport failure
- [ ] **`_backToList()`** — **`224–231`** restores list without orphaned **`_answers`/`_questions`** inconsistencies
- [ ] Submission failure — **`209–219`** snackbars on **HTTP** error / exception (not swallowed)
- [ ] **`_authHeaders`** — **`87–92`** — **Bearer `token`** from **`profile`**; **missing token** UX — **TBD**
- [ ] **`expected_role`/CLIENT**: profile passed from **`ClientSettingsScreen`** nav — **`TBD`** ctor wiring line
- [ ] **`401`/`403`** — inline handling (**trust #71** — no logout storm)
- [ ] **`COACH_ONLY`** — YOUR TOOLS block hidden — **`2872`**
- [ ] Theme per assessment title — **`62–66`**, **`34–59`** map — degraded assessment still readable
- [ ] Touch targets ≥ **44pt** on quiz controls — **TBD** per `_buildQuizView`

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| REST contract (header comment) | `3–4` | `GET /api/quizzes`, `GET …/{id}`, `POST …/{id}/submit` |
| `QuizScreen` | `68–73` | Entry widget |
| `build` | `234` | Scaffold + branch UI |
| List / empty | `268+` | `_buildQuizList` |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2872` — **`!_isCoachOnly`**
- `settings_screen.dart:2876–2880` — **Assessments** row → **`QuizScreen`**
- `quiz_screen.dart:3–4` — **REST endpoints** (doc comment)
- `quiz_screen.dart:68–92` — class / auth helpers
- `quiz_screen.dart:224–263` — navigation + **`build`** body branches

### REST (**from `quiz_screen.dart:3–4` only — router tables TBD**)

- **TBD** — OpenAPI / `backend/app/routers/**` linkage for **`/api/quizzes*`** (**do not cite** until traced)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_quizzes`, `_activeQuiz`, `_answers`, `_resultData` | Clear on **`_backToList`** — **`224–231`** |
| `_submitting` | Reset on **`catch`** — **`214–217`** |

---

## 6. WebSocket messages

- **§3 row 17** — **WS** — **TBD** (**foundational**)

---

## 7. Database tables touched

- **TBD** — quizzes storage behind **`/api/quizzes*`**

---

## 8. Edge cases

- **Malformed JSON** decode on submissions — **`202–203`** path — verify user-visible outcome (**TBD**)
- **Offline** handling — **`catch`** **`214–217`** surfaces error string

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

- ❌ **Silent** empty assessment UI (**`8c2a768`** analogue)
- ❌ Invent **coach DOJO quiz** parity without distinguishing **CLIENT `QuizScreen`** vs **coach** surfaces (**coach portal** glossary)
- ❌ **`POST`** submit **without** user-visible **`statusCode`** path — **`209–219`**

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| AS-01 | **§3 row 17** **WS**/bridge mapping — **foundational TBD** |
| AS-02 | **`QuizScreen`** optional **`profile?`** **`69`** — null-token path — **TBD** UX |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | Header comment **`3–4`** is **truth** until endpoint audit mismatches UX | Swagger / trust auditor hook |
| 2026-05-06 | Medium | **“Assessments”** naming vs coach **DOJO** language — glossary | **`_PHASE_3_PLAN`** cross-portal §E |
| 2026-05-06 | Low | **`_AssessmentTheme`** map keys vs API titles drift — **`34–59`** | Server-driven theme keys |

---

## 12. Security boundaries

- **Bearer** token from **`profile`** only — **`87–92`**; **no tokens in logs**
- Exported results — **screenshot PHI** mitigations — **TBD**

---

## 13. Manual test scenarios

1. **CLIENT**, **`!_isCoachOnly`** → **YOUR TOOLS** Assessments **`2876–2880`**
2. Empty list → copy **`269+`**
3. Start quiz → back → **`_backToList`**
4. Force **401** (**TBD** harness)
5. **`COACH_ONLY`** — row absent

---

## 14–16. Foundational cross-ref / daily health / investigation cache

- **§3 row 17**; **investigation cache:** `2026-05-06`, tokens **TBD**

---

## 17. Cursor prefix

```
Read docs/client_portal/features/29_assessments.md + foundational §3 r17 +
_TAB_INVENTORY 2876–2880, 2872.
Trace quiz_screen REST calls to routers; compare coach DOJO assessment docs.
Prefix 29_.
```

---

## 18. OUT OF SCOPE

- **Coach DOJO assessments** (`coach_portal` **05** analogue)
- **Neural chat** intake (`15_sse_story_journey_and_recap.md`)
- **Spec 30–31 mesh** BLE training vs community

---

*Spec from foundational + inventory + plan — `2026-05-06`.*
