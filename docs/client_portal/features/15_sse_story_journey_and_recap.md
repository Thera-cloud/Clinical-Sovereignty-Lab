# Client Portal — SSE Story Journey, intake banner & welcome-back recap

> Status: `DRAFT` (**`_checkSseIntake`** / recap **payload shape** — **TBD** in foundational pass)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G8**, **G9**, **§D D10**, **§D D11**, **§B B2**, **§B B3**, **§E E22**. `_PHASE_3_PLAN.md` **spec 15**. Parent chrome: **`NeuralInterfaceV2`** — **`updated_screens.dart:3663–4137`** (inventory §**A** intro). **`IntakeConversationScreen`** build anchor **`onboarding_paid_screen.dart:550`**. Prefix **`15_`**.

---

## 1. Purpose (1 sentence)

On the **client chat** body above the composer (**`3796`** region), **`_checkSseIntake`** (**`1987–2000`**) gates an **SSE Story Journey** banner (**`3814–3840`**) that can launch **`IntakeConversationScreen`** (**`550`**), while a **welcome-back recap** card (**`3842–3867`**) summarizes journey/quest/mission context unless **suppressed** by intake pending or **`E22`** dismiss (**`2025`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` **§B2–B3**, **§D10–D11**, **§E22**; `_FOUNDATIONAL_SPEC.md` §**3 row 7** (parent **`NeuralInterfaceV2`**), §**6** (socket lifecycle); `_PIPELINE_TEMPLATE.md` §2.

- [ ] **`_checkSseIntake`** — **`1987–2000`** — sets **`_sseIntakePending`** consistently; failures are **visible** or **logged** (**TBD** exact UX — no silent perpetual spinner)  
- [ ] When **`_sseIntakePending`** is **true**, **SSE Story** banner **`3814–3840`** presents a **single** coherent CTA (**TBD** copy) toward **`IntakeConversationScreen`** — **`550`**  
- [ ] **`IntakeConversationScreen`** (**`550`**) respects **CLIENT** IA — does not impersonate unrelated onboarding routes (**cross-ref** **`04`** / **`paid`** flows — **TBD** nav stack)  
- [ ] Welcome-back recap — **`3842–3867`** — shows **only if** **`_recapData != null && !_recapDismissed && !_sseIntakePending`** (**§B3**) — **no** recap **under** active intake banner (precedence locked in inventory conditional)  
- [ ] **`E22`** recap dismiss — **`2025`** — persists or session-scopes **`_recapDismissed`** per product rule (**TBD**) and is **tap-target** ≥ **44pt** on primary dismiss control  
- [ ] **`login_request` + `expected_role: CLIENT`** — **`1488–1493`** — prerequisites for **`NeuralInterfaceV2`** (**`01`**) hosting this chrome  
- [ ] **`COACH_ONLY`** / **`ClientScheduleScreen`** — **`6755–6759`** — user **never** sees **§B2/B3** on schedule-only routing  
- [ ] **`Family Sanctuary`** round-trip (**`3701–3712`**) — returning user sees **deterministic** recap/intake eligibility vs **stale** flags (**TBD** refresh contract)  
- [ ] Errors state **what failed** + **next step** (template §2 — e.g. retry intake deeplink vs dismiss) — **no** generic empty body when server errored (**TBD** transport)  
- [ ] Loading states resolve or expose **retry** within **30s** (template §2 baseline)  
- [ ] Dual **Suppressed** narratives: recap hidden when intake pending — QA must assert **ordering** (**§B2** before **§B3**) in **`3842`** condition  
- [ ] **`main.dart` post-login CLIENT branch** **`6748–6787`** — user reaches **`3663`** before expecting banner/recap (**TBD** assert timing vs tutorials/consent **`6761–6780`**)  

---

## 3. UI components

| Inventory | Location | Purpose |
|-----------|----------|---------|
| **§B2** / **G8** / **D10** | **`3814–3840`** | SSE Story Journey **banner** (intake funnel) |
| **`IntakeConversationScreen`** | **`onboarding_paid_screen.dart:550`** | Destination conversation UI |
| **§B3** / **G9** / **D11** | **`3842–3867`** | Welcome-back **recap** card |
| **§E22** | **`2025`** | Recap **dismiss** handler |
| **Gate** | **`1987–2000`** | **`_checkSseIntake`** |

---

## 4. Files (canonical references)

### Mobile

- `updated_screens.dart:1987–2000` — **`_checkSseIntake`**, **`_sseIntakePending`**  
- `updated_screens.dart:3814–3840` — **SSE Story** banner (**§B2**)  
- `updated_screens.dart:3842–3867` — **Welcome-back recap** (**§B3**)  
- `updated_screens.dart:2025` — **§E22** recap dismiss wiring  
- `updated_screens.dart:3663` — **`NeuralInterfaceV2`** shell (**foundational §3 row 7**)  
- `updated_screens.dart:1222–1271` — representative state (**subset** `_recapData` etc. — **TBD** key names vs **`01`**)

- `onboarding_paid_screen.dart:550` — **`IntakeConversationScreen`** (**D10**)

### Bridge / REST

- **TBD** — whether intake/SSE funnel uses **REST**, **SSE**, **WebSocket pushes**, or **pure local** navigation flags (**not** itemized in `_FOUNDATIONAL_SPEC.md` §**4.B** excerpt for **`Neural chat`**).

### Explicit non-scope (related **sse-client** naming)

- **Check-in** widget **`POST …/api/sse-client/checkin`** — **`checkin_screen.dart:25–31`** — foundational §**3 row 24** — **spec `36`** *not this file*  
- **Archetype reset** **`POST …/sse-client/identity/reset`** — **`settings_screen.dart:3009–3020`** — **spec gap `33`** *not this file*

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| **`_sseIntakePending`** | Drives **`§B2`** visibility (**inventory §B table**) |
| **`_recapData`**, **`_recapDismissed`** | Drive **`§B3`** (**`3842`** predicate) |
| Intake/recap freshness after **socket** lifecycle | Tie to **`3701–3712`**, **`01`** reconnect |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` |
|-----------|------|---------------------|---------------------|
| **TBD** | SSE / WS / REST for journey | **`1987–2000`** + **TBD** downstream | **TBD** |

**Note:** **`Neural chat`** §**4.B** table lists **`nate_query`**, **`get_metrics`**, etc., but **does not** enumerate an **`sse_story_*`** type — treat transport as **`TBD`** until traced in a future **code** pass (**user requested doc-only authoring**).

---

## 7. Database tables touched

- **TBD** — recap / intake persistence (if any) not listed under foundational §**5** for §**3 row 7** excerpt.

---

## 8. Edge cases

- **Intake banner on** ⇒ **recap suppressed** (**`!_sseIntakePending`** guard on **`§B3`**) — product must avoid “where did recap go?” without copy (**TBD**)  
- **Dismiss recap** ⇒ later session still eligible if **`_recapDismissed`** resets — **policy TBD**  
- **Reconnect** (**`login_request`**) ⇒ **`_sseIntakePending`** / **`_recapData`** may **deserialize stale** (**TBD**)  
- **`COACH_ONLY`** — **Chrome N/A** — **`6755–6759`**  
- **`Family Sanctuary`:** socket close **`3701–3712`** — recap vs intake **`TBD`** after return (**`3712`** reconnect ref)

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

**Reject proposals that:**

- ❌ **Silently** clear **`_sseIntakePending`** on error without UI (**parallel** **`8c2a768`** culture).  
- ❌ Split **intake** across a **second** user-visible socket without **`login_request`** parity (**`distress_beacon`** warning pattern — foundational §**3 row 16**).  
- ❌ Push **recap** while **`Intake`** is **still** logically active — violates inventory **`§B3`** **`!_sseIntakePending`** contract.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence |
|----|---------|----------|
| SJ-01 | Transport **unknown** (**§6**) impedes QA | `_FOUNDATIONAL_SPEC.md` gap vs inventory **D10** |
| SJ-02 | **Dismiss** **`2025`** persistence story **unverified** | **TBD** |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §10** analogs + **`_TAB_INVENTORY`** precedence UX.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **`Family Sanctuary`** closes chat socket (**`3701–3703`**) — **intake/recap coherence** post-return undocumented | **TBD** |
| 2026-05-05 | Medium | **`Intake` suppresses recap** (**`§B3`** predicate) without user-facing explanation — “missing recap” confusion | Copy / **settings** FAQ **TBD** |
| 2026-05-05 | Medium | **`NeuralInterface`** legacy vs **`V2`** (**`§10`**) — QA may rehearse wrong screen | Maintainer doc |
| 2026-05-05 | Low | Narrative (**G8**) + recap (**G9**) coupling depends on **`_checkSseIntake`** internals **`1987–2000`** — **black-box** friction for support scripts | Observability **TBD** |

---

## 12. Security boundaries

- **Intake** content is **CLIENT-self** scoped — server must enforce **hardware_id / JWT** (**TBD** route audit).  
- **Recap** text must reflect **aggregate** milestones only — **never** leaks other households (**pattern:** foundational §**8**).  
- **`GET` / `POST` endpoints** with **`sse-client` path segments** (**check-in**, **identity reset**) are **distinct** scopes — verify **IAM** separately before merging analytics (**§4**, non-scope block above).

---

## 13. Manual test scenarios

1. **Healthy CLIENT** reaches **`3663`** — trigger **§B2** (**TBD** data seed) → navigates **`550`**.
2. With **`_sseIntakePending` true**, confirm recap **does not render** (**`3842` predicate**)  
3. Clear intake → recap eligible when **`_recapData`** present **TBD**.  
4. Tap **dismiss** — **`2025`** — recap gone this session (**TBD** persistence).  
5. **Reconnect** WS — parity of **`_sseIntakePending`** (**`01`**).  
6. **`3701–3712`** excursion → return chat → observe banner/recap order (**TBD**)  
7. **`COACH_ONLY`** — confirm **absent** — **`6755–6759`**

---

## 14. Foundational spec cross-reference

- **Parent:** §**3 row 7** — **`NeuralInterfaceV2`**  
- **Lifecycle:** §**6** (**Family** teardown **`3701–3712`**, reconnect **`3712`** note)  
- **Privacy posture:** §**8** (**aggregates**)  
- **Parallel rows:** §**3 row 24** check-in (**not** §B2 banner)

---

## 15. Daily health checks

Anchors **`1987–2000`**, **`2025`**, **`3814–3840`**, **`3842–3867`**, **`550`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/15_sse_story_journey_and_recap.md +
_TAB_INVENTORY §B2–B3, §D10–D11, §E E22, §G G8–G9 +
_FOUNDATIONAL_SPEC §3 row 7, §6. Trace §6 transport (SSE vs WS vs REST) before tightening §6–§7.
Outbound non-scope: checkin + archetype sse-client routes per §4 Explicit non-scope.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
