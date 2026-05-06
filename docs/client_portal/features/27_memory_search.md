# Client Portal — Memory search

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 15** — **Memory search** — `secure_search_screen.dart:249` (**primary `build`**); **REST** `GET .../api/client/memory/search/$hwId` — `secure_search_screen.dart:120–123`; **`_results`**, **`_tabController`** — `secure_search_screen.dart:52–71`.

**Plan:** `_PHASE_3_PLAN.md` **spec 27** — §3 **r15**. Prefix **27_**.

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` **§B YOUR TOOLS** — **Memory Search** — `2889–2893` → **`SecureSearchScreen`**; gate **`!_isCoachOnly`** — `2872` (same **YOUR TOOLS** block as specs **25**, **26**).

---

## 1. Purpose (1 sentence)

Let **eligible clients** (**`2872`**) open **`SecureSearchScreen`** from Settings (**`2889–2893`**) to **REST**-search **`/api/client/memory/search/{hardware_id}`** (**`120–123`**) and present hits across **`TabController`** + **`_results`** (**`52–71`**, **`249`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 15**, §6, §8; `_TAB_INVENTORY_2026-05-05.md` §**B** YOUR TOOLS; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **YOUR TOOLS → Memory Search** — **`2889–2893`** — only when **`!_isCoachOnly`** — **`2872`**
- [ ] **`SecureSearchScreen`** — **`249`** — **loading**, **zero hits**, and **transport errors** are **distinct** (no **`8c2a768`**-class **silent** empty **`_results`**)
- [ ] **`GET .../api/client/memory/search/$hwId`** — **`120–123`** — **`hwId`** is **only** the **authenticated** client’s id (**§8**)
- [ ] **`_tabController`** — **`52–71`** — **tabs** switch without **thrown** exceptions or **orphan** listeners; **`dispose`** **disposes** controller (**template §5**)
- [ ] **`_results`** — **`52–71`** — updates after **new** search / **refresh**; **no** stale mix of **old** + **new** query rows **without** label (**TBD** query UX)
- [ ] **Request** completes or **fails** within **~30s** or surfaces **retry** / **timeout** copy (**template §2**)
- [ ] **`401` / `403`** — **inline** handling; **no** **destructive logout** loop during **Bearer** propagation lag (**trust #71**)
- [ ] **Offline** vs **5xx** — user-visible distinction
- [ ] **Touch targets** ≥ **44pt** on **search** / **tab** / **primary** row actions (**TBD** widget map)
- [ ] **`expected_role: CLIENT`** — **§6** — session **`hwId`** aligns with **CLIENT** account
- [ ] **Long** result snippets — **truncate** + **expand** or **scroll** without clipping **legally** sensitive context **unlabeled** (**TBD**)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| Tools row | `2889–2893` | **Memory Search** → **`SecureSearchScreen`** |
| Screen `build` | `249` | Full UI |
| HTTP | `120–123` | **GET** memory search |
| State | `52–71` | **`_results`**, **`_tabController`** |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2872` — **`!_isCoachOnly`** (**YOUR TOOLS**)
- `settings_screen.dart:2889–2893` — **Memory Search** row
- `secure_search_screen.dart:249` — **`build`**
- `secure_search_screen.dart:52–71` — **`_results`**, **`_tabController`**
- `secure_search_screen.dart:120–123` — **REST** **GET**

### REST

- `GET /api/client/memory/search/{hwId}` — **foundational §3 row 15**, **§5** (**backing tables — TBD**)

### WebSocket / bridge

- **None** for **§3 row 15** — **REST-only** in foundational table.

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_tabController` | **`dispose`** in **`dispose()`** — avoid **Ticker** leaks |
| `_results` | Reset on **new** query / **logout** |
| **`_loading`** (if present outside **52–71** span) | Clear on **`catch`/`finally`** — **TBD** line |

---

## 6. WebSocket messages

- **N/A** for **row 15** surface.
- **`search_consent_approved`** in **NeuralInterfaceV2** (**`updated_screens.dart:1615–1618`**) — **different** pathway — **`01`** (**cross-ref**, **not** this spec’s transport).

---

## 7. Database tables touched

- **TBD** — **`_FOUNDATIONAL_SPEC.md` §5**

---

## 8. Edge cases

- **`hwId`** missing from profile/session → block **GET** or show **explain** error (**TBD**)
- **Tab** count **vs** empty **categories** — **do not** show **meaningless** **blank** tabs **without** copy (**TBD**)
- **`COACH_ONLY`** — **`2872`** hides **Memory Search** row

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

- ❌ **Silent** **search failure** — empty **`_results`** with **no** message (**`8c2a768`** class)
- ❌ **`TabController`** **dispose** regressions — **tabs** leak or **crash** on **Navigator** pop
- ❌ **`GET`** with **wrong** **`hwId`** (stale **`Navigator`** **args**) — **privacy** regression

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| MS-01 | **`/api/client/memory/search`** **DB** backing — **§5 TBD** |
| MS-02 | **REST memory search** vs chat **`search_consent_approved`** / **`get_history`** — user-facing terminology not unified (**CR risk**) |

---

## 11. Steve Jobs UX debt (dated)

≥3 — extend **§10** + **inventory** proximity to **Brief**/**Coherence**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | Three **YOUR TOOLS** **insights** (**25** Brief, **26** Coherence, **27** Memory) — **overlapping** “what Nate knows about me” narrative | IA / consolidated **insights** hub **TBD** |
| 2026-05-05 | Medium | **`search_consent_approved`** (**chat**) vs **Settings Memory Search** — users think **one** toggle controls both | Copy + **`01`** cross-link (**MS-02**) |
| 2026-05-05 | Medium | **`hwId` in URL** — same **shoulder-surf** concern as coherence **report** (**26**) | Defense depth **policy** |
| 2026-05-05 | Low | **`SecureSearchScreen`** naming vs **marketing** **“sanctuary memory”** — brand drift | Glossary |

---

## 12. Security boundaries

- Results **scoped** to **`hwId`** of **authenticated** **CLIENT** (**server** must enforce — **§8**)
- **No** clipboard **dump** of **full** PHI-heavy rows **without** **confirm** (**TBD** product)
- **HTTPS** only; **no** **token** in **query string** (**TBD** current client — audit on trace)

---

## 13. Manual test scenarios

1. **CLIENT**, **`!_isCoachOnly`** → Settings → **Memory Search** **`2889–2893`**
2. **Successful** search → **`_results`** populated; **tabs** sane
3. **Zero hits** explicit
4. **401** path
5. **Airplane** mode → **offline** message
6. **`TabController`** **dispose** — open/close/reopen **without** crash
7. **`COACH_ONLY`** → row **hidden**

---

## 14. Foundational spec cross-reference

- **§3 row 15** — screen + REST + state
- **§5** — endpoint; tables **TBD**
- **§6**, **§8**

---

## 15. Daily health checks

Anchors **`2872`, `2889–2893`, `secure_search_screen.dart:52–71`, `120–123`, `249`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/27_memory_search.md +
_FOUNDATIONAL_SPEC §3 row 15, §5 memory row +
_TAB_INVENTORY §B YOUR TOOLS (2872, 2889–2893).
Trace SecureSearchScreen GET (120–123) → backend / FTS tables.
Contrast search_consent_approved + get_history (01) vs REST memory/search.
```

---

## 18. Explicit OUT OF SCOPE

- **Weekly brief** — **`25_weekly_brief.md`**
- **Coherence reports** — **`26_coherence_reports.md`**
- **Neural chat** **`search_consent_approved`** / **`get_history`** mechanics — **`01_chat_with_nate.md`**
- **Device-history sync** bridge doc — **`device-history-sync-on-login.mdc`** (**workspace**) — parallel concern, **different** UX entry

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
