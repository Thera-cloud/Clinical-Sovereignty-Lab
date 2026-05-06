# Client Portal — Coherence reports

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 14** — **Coherence reports** — `nevedal_reports_screen.dart:130` (**primary `build`**); **REST** `GET .../api/coherence/report/$hwId` — `nevedal_reports_screen.dart:69–79`; **`_report`**, **`_selectedRange`** — `nevedal_reports_screen.dart:37–43`.

**Plan:** `_PHASE_3_PLAN.md` **spec 26** — §3 **r14**. Prefix **26_**.

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` **§B YOUR TOOLS** — **Coherence Reports** — `2881–2885` → **`NevedalReportsScreen`**; gate **`!_isCoachOnly`** — `2872` (same **YOUR TOOLS** block as **Weekly Brief** — spec **25**).

**Naming / IA note:** `_PHASE_3_PLAN.md` fold table — coach **`03_insights.md`** **Insights** umbrella vs client **Nevedal coherence** — **`clarify in specs`** (no duplicate trace).

---

## 1. Purpose (1 sentence)

Let **eligible clients** (**`2872`**) open **`NevedalReportsScreen`** from Settings (**`2881–2885`**) and **REST**-load **`/api/coherence/report/{hardware_id}`** (**`69–79`**) into **`_report`** with a **`_selectedRange`**-driven view (**`37–43`**, **`130`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 14**, §6, §8; `_TAB_INVENTORY_2026-05-05.md` §**B** YOUR TOOLS; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **YOUR TOOLS → Coherence Reports** — **`2881–2885`** — only when **`!_isCoachOnly`** — **`2872`**
- [ ] **`NevedalReportsScreen`** — **`130`** — first paint handles **`_loading`** / **empty report** vs **hard error** distinctly (**no** **`8c2a768`**-class silent card)
- [ ] **`GET .../api/coherence/report/$hwId`** — **`69–79`** — **`hwId`** matches **authenticated** client (**foundational §8** — no accidental **other-user** **`hwId`** from stale profile)
- [ ] **`_selectedRange`** — **`37–43`** — changing range **re-fetches** or **updates** chart consistently (**TBD** exact pattern); **no** stuck **spinners**
- [ ] **`401` / `403`** — surfaced inline; **no** **destructive logout** loops during **Bearer** propagation lag (**trust #71**)
- [ ] **Offline** vs **5xx** — user-visible distinction (**`_PIPELINE_TEMPLATE.md`** §8)
- [ ] **Touch targets** ≥ **44pt** on **range controls** / **primary navigation** (**TBD** widget inventory)
- [ ] **`expected_role: CLIENT`** on **`login_request`** prerequisite for coherent **CLIENT** **`hwId`** in profile/session (**§6**)
- [ ] **Long** coherence payload — **scroll** / **truncate** strategy does not **truncate** clinically critical labels **without** “more” affordance (**TBD**)
- [ ] **Back** navigation from **`NevedalReportsScreen`** → Settings preserves **prior** Settings scroll state (**TBD** `Navigator` policy)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| Tools row | `2881–2885` | **Coherence Reports** entry → **`NevedalReportsScreen`** |
| Screen `build` | `130` | Full-screen report UI |
| HTTP | `69–79` | **GET** coherence report |
| State | `37–43` | **`_report`**, **`_selectedRange`** |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2872` — **`!_isCoachOnly`** (**YOUR TOOLS** gate)
- `settings_screen.dart:2881–2885` — **Coherence Reports** row  
- `nevedal_reports_screen.dart:130` — **`build`** (foundational **row 14**)  
- `nevedal_reports_screen.dart:37–43` — **`_report`**, **`_selectedRange`**  
- `nevedal_reports_screen.dart:69–79` — **REST** fetch  

### REST

- `GET /api/coherence/report/{hwId}` — **foundational §3 row 14**, **§5** (**router table detail — TBD**)

### WebSocket / bridge

- **None** enumerated for **row 14** (**REST-only** in foundational §3).

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_report` | Clear or replace on **range** change / **logout** (**TBD**) |
| `_selectedRange` | Stable default; persists only if product requires (**TBD**) |
| `_loading` (if separate) | **Clear** on **`dispose`**, **error**, **timeout** — template §5 |

---

## 6. WebSocket messages

- **N/A** for **§3 row 14** surface.

---

## 7. Database tables touched

- **TBD** — **`_FOUNDATIONAL_SPEC.md` §5**: endpoint listed, **backing tables not** enumerated in foundational pass  

---

## 8. Edge cases

- **`hwId`** missing / malformed in profile → **explicit** UI (**not** request with **empty** path)
- **`200` + empty body** vs **placeholder zeros** — product must declare which is canonical (**TBD**)
- **`COACH_ONLY`** — **`2872`** hides **YOUR TOOLS** including this row (**same** as **25**)

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

- ❌ **Silent** coherence **failure** — blank **`NevedalReportsScreen`** (**`8c2a768`** class)  
- ❌ **Substitution** of **another user's** **`hwId`** in **path** (stale **`Navigator`** args, QA fixtures) — **privacy** regression  
- ❌ **`GET`** **hammering** without **debounce** on **`_selectedRange`** changes — **battery** / **rate-limit** (**TBD** server policy — design defensively)

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| CR-01 | **`/api/coherence/report`** **router ↔ DB** mapping **TBD** — **§5** |
| CR-02 | Feature overlap with **`get_metrics`** / **metrics sheet** (**inventory §D8–D9**, spec **`14_nudges_and_metrics.md`**) — **single** user mental model **undocumented** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §10** posture + **`_PHASE_3_PLAN.md`** fold row.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | Coach **Insights** vs client **Nevedal coherence** — **`03_insights.md`** vs **`26`** (**plan fold**) — naming **collision** risk | Unified glossary / IA |
| 2026-05-05 | Medium | **`NeuralInterfaceV2`** **quick metrics** (**D9**) vs **standalone** coherence **report** — user does not know **which** is authoritative | Cross-link **`14`** vs **`26`** (**CR-02**) |
| 2026-05-05 | Medium | **`hwId`** in **URL path** enables **bookmark** / shoulder-surf leakage on **shared devices** (**defense depth**) | Screen lock / ephemeral URL policy (**TBD**) |
| 2026-05-05 | Low | **Clinical** jargon in report body **without** **plain-language** layer — empathy debt | Readable summary strip (**TBD**) |

---

## 12. Security boundaries

- **Report** scoped to **`hwId`** of **authenticated** client only — server must enforce (**§8**)  
- **No** caching **full** **`_report`** JSON in **`SharedPreferences`** without **risk** review (**PHI**/sensitive analogue **TBD**)  
- Prefer **HTTPS**-only; **never** downgrade to **HTTP** in prod builds  

---

## 13. Manual test scenarios

1. **CLIENT**, **`!_isCoachOnly`** → Settings → **Coherence Reports** **`2881–2885`**  
2. **`_selectedRange`** toggles (**if UI exposes**) → data updates / explicit **reload** feedback  
3. **Revoked** **`hwId`** / **401** path  
4. **Airplane mode** → **offline** UX  
5. Confirm **Weekly Brief** (**25**) and **Coherence** entries **distinct** (**2872** list)  
6. **`COACH_ONLY`** → **YOUR TOOLS** absent  

---

## 14. Foundational spec cross-reference

- **§3 row 14** — screen + REST + state  
- **§5** — endpoint present; tables **TBD**  
- **§6**, **§8** — CLIENT scope  

---

## 15. Daily health checks

Anchors **`2872`, `2881–2885`, `nevedal_reports_screen.dart:37–43`, `69–79`, `130`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/26_coherence_reports.md +
_FOUNDATIONAL_SPEC §3 row 14, §5 coherence row +
_TAB_INVENTORY §B YOUR TOOLS (2872, 2881–2885).
Compare nevedal_reports_screen.dart GET (69–79) to backend router tables.
Contrast with NeuralInterfaceV2 metrics (spec 14 — D8/D9) vs full report UX.
```

---

## 18. Explicit OUT OF SCOPE

- **Weekly brief** — **`25_weekly_brief.md`** (**row 13**)  
- **Memory search** — **row 15** — **`secure_search_screen.dart`**  
- **Neural chat** **`get_metrics`** / **metrics sheet** / **quick bar** detail — **`14_nudges_and_metrics.md`** (**document cross-ref**, do not duplicate **`01`** WS matrix)  
- **Coach Insights** authoring — **`03_insights.md`**

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
