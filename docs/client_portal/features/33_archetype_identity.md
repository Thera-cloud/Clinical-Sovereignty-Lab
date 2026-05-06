# Client Portal — Archetype identity

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap:** **`G14`** — **YOUR ARCHETYPE** block.

**Plan:** `_PHASE_3_PLAN.md` **spec 33**. Prefix **33_**.

---

## 1. Purpose

Surface **archetype portrait + name** fetched via **`GET .../api/sse-client/identity/status`** and allow **reset** via **`POST .../api/sse-client/identity/reset`** (**`3018`**) after confirm dialog (**`3010–3020`**).

---

## 2. UX acceptance (**8+**)

- [ ] **`_fetchArchetypeStatus`** — **`370–377`** — Bearer token; silent catch **`377`** flagged as debt (**background logging TBD**)
- [ ] **`_archetypeName` / `_archetypeImageUrl`** display paths — **`2998–3007`**
- [ ] **Confirm dialog** warns about **regenerated character** while preserving **quests / story** (**`3013`**) — must stay accurate vs server (**TBD contract**)
- [ ] **POST reset** — **`3017–3019`** — **`200`** triggers snackbar (**`3019`**); non-200 UX **TBD** (currently silent)
- [ ] Section sits under **`!_isCoachOnly`** block ending **`3043`** — same guard as **`2975`**
- [ ] **NetworkImage** failure for **`_archetypeImageUrl`** — **`3002`** fallback polish — **TBD**
- [ ] **COACH_ONLY** — block hidden with **Coaching tools** stack
- [ ] **Token missing** — early return on GET — **TBD** surface
- [ ] **Accessibility** — archetype text + alt image semantics — **TBD**
- [ ] **SSE intake** cross-link — user must know to open **chat** after reset (**copy already** **`3019`**)

---

## 3. Anchors

| Concern | `file:line` |
|---------|-------------|
| Fetch status | `370–377` |
| Section UI | `2998–3021` |
| Reset POST | `3010–3020` |

---

## 4. REST

- `GET /api/sse-client/identity/status`
- `POST /api/sse-client/identity/reset`

---

## 9. Anti-patterns (**§9 verbatim**)

**Reject:** silent reset failures | misaligned copy vs actual data wipe scope | missing **`expected_role`** interplay if identity endpoint role-specific (**TBD**)

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| AI-01 | **Non-200 reset** silent after snackbar branch |
| AI-02 | **GET status** catch swallows diagnostics — **`377`** |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **Image + text hero** competes with dense settings | dedicated sheet |
| 2026-05-06 | Medium | **Archetype vs Avatar mode** naming collision risk | glossary (`12` vs **`33`**) |
| 2026-05-06 | Low | **Long legalistic confirm** text — **`3013`** | progressive bullet list |
| 2026-05-06 | Low | **No preview** of forthcoming intake questions | marketing copy hook |

---

## 17. Cursor prefix

```
Prefix 33_. Archetype stack 2998–3021; fetch 370–377; intake cross-ref 01/15.
```

## 18. OUT OF SCOPE

- **`12_avatar_mode.md`** (3D **`NeuralInterface`**)
- **`32_quests_and_missions.md`**
- **`01_chat_with_nate.md`** **`IntakeConversationScreen`** deep spec

---

*`2026-05-06`*
