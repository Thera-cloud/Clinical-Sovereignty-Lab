# Client Portal — Weekly brief

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 13** — **Weekly brief** — `settings_screen.dart:6345`; **REST** `GET .../api/research/nevedal/reports/brief` + **`X-User-Id`** — `settings_screen.dart:6321–6323`; state **`_loading`**, **`_briefText`**, **`_moodSummary`** — `settings_screen.dart:6305–6309`.

**Plan:** `_PHASE_3_PLAN.md` **spec 25** — §3 **r13** + **E15** (`E15→25`). Prefix **25_**.

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` **§B YOUR TOOLS** — **Weekly Brief** — `2886–2888` → **`_showWeeklyBrief`** — `2125` (**E15**). Section gate **`!_isCoachOnly`** — `2872`.

**Branding note:** `_PHASE_3_PLAN.md` fold table — client **Brief** vs coach **Briefings** — **`04_briefings.md`** (related doc, not re-traced here).

---

## 1. Purpose (1 sentence)

From **Settings → Your Tools** (**`2886–2888`**, gated **`2872`**), open **E15** — **`_showWeeklyBrief`** (`2125`) — which **REST**-loads the **Nevedal weekly brief** (`6321–6323`) and renders **`_briefText`** / **`_moodSummary`** (`6305–6309`) tied to foundational **`6345`** **build** entry.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 13**, §6, §8; `_TAB_INVENTORY_2026-05-05.md` §**B** YOUR TOOLS, §**E** **E15**; `_PIPELINE_TEMPLATE.md` §2 (**35s** example).

- [ ] **YOUR TOOLS** row **Weekly Brief** — `2886–2888` — only when **`!_isCoachOnly`** — **`2872`** (**inventory**)
- [ ] **`_showWeeklyBrief`** — `2125` — **modal** opens without **silent** stall; **`_loading`** visible during fetch (**`6305–6309`**)
- [ ] **`GET .../api/research/nevedal/reports/brief`** with **`X-User-Id`** — `6321–6323` — **success** maps to **`_briefText`** + **`_moodSummary`**; **failure** shows **actionable** copy (**not** empty modal — **`8c2a768`** class)
- [ ] Request **timeout** — `_PIPELINE_TEMPLATE.md` cites **`35s`** for this path — `settings_screen.dart:6324` — user gets **retry** or **dismiss** within that budget (align with **30s** template rule where product agrees)
- [ ] **Empty** server payload (valid “no brief yet”) **reads differently** from **HTTP error** / **timeout**
- [ ] **Touch targets** ≥ **44pt** on **open** control (`2886–2888`) and modal **primary** actions (**TBD** widget names)
- [ ] **`expected_role: CLIENT`** / **session** — user only sees **own** brief; **`X-User-Id`** must match **authenticated** client identity (**foundational §8** spirit — no cross-user bleed)
- [ ] **No** auto-redirect / kick-out loop on **`401`** while **Redis** Bearer propagation lags — **trust #71** pattern; prefer **inline** error + **manual** retry (**learned** **#13** analogue)
- [ ] **Modal** **dismiss** clears **`_loading`** and does not leave **orphan** timers (**`_PIPELINE_TEMPLATE.md`** §5)
- [ ] **`COACH_ONLY`** — **`main.dart:6748–6756`** — **YOUR TOOLS** hidden; user does not hunt a **ghost** Brief row (**2872**)

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| Tools row | `2886–2888` | **Weekly Brief** entry |
| **E15** | `2125` | **`_showWeeklyBrief`** modal |
| Implementation body | `6305–6324` (+ `6345` **build** anchor) | **Load state**, **`X-User-Id`** **GET**, **timeout** cite |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2872` — **`!_isCoachOnly`** (**YOUR TOOLS** gate)
- `settings_screen.dart:2886–2888` — **Weekly Brief** row
- `settings_screen.dart:2125` — **`_showWeeklyBrief`** (**E15**)
- `settings_screen.dart:6305–6309` — **`_loading`**, **`_briefText`**, **`_moodSummary`**
- `settings_screen.dart:6321–6324` — **REST GET** + **`X-User-Id`** + **timeout** reference (**6324**)
- `settings_screen.dart:6345` — foundational **row 13** **build**/entry anchor

### REST

- `GET /api/research/nevedal/reports/brief` — **foundational §3 row 13**, **§5** (**TBD** backing tables)

### WebSocket / bridge

- **None** for **row 13** — **REST-only** in foundational enumeration

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_loading` | Cleared on **`then`**, **`catch`**, **`finally`**, **`dispose`** / modal close |
| `_briefText` / `_moodSummary` | Reset or stale-guard when **hardware_id** changes (**TBD**) |

---

## 6. WebSocket messages

- **N/A** — **Weekly brief** is **REST** in **§3 row 13**.

---

## 7. Database tables touched

- **TBD** — **`_FOUNDATIONAL_SPEC.md` §5** lists **`/api/research/nevedal/reports/brief`** without verified table names in this pass

---

## 8. Edge cases

- **Offline** — distinguish **`SocketException`** vs **5xx**
- **`X-User-Id`** **spoofing** / mismatch — server must **enforce** caller == subject (**security** review item)
- **Large** brief text — **scroll** / **performance** (**TBD**)
- **`COACH_ONLY`** — **`2872`** — whole **YOUR TOOLS** strip including **Brief**

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

- ❌ **Brief** modal **swallows** **HTTP errors** — leaves **blank** content (**`8c2a768`** class)
- ❌ **`X-User-Id`‑only** pattern **spread** to **new** sensitive endpoints **without** **Bearer** parity review (**foundational §10** debt)
- ❌ **`401`** triggers **destructive logout** loops on this **REST** surface during **Redis** token lag (**trust #71**)

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| WB-01 | **`6345`** vs **`6305`** span — finer **widget** decomposition **TBD** for QA steps |
| WB-02 | **`/reports/brief`** **backing tables** — **§5 TBD** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §10** (+ plan **fold** note).

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **`X-User-Id` without Bearer** — `6321–6323` — **weaker** than other **authenticated** client **REST** | Align with **`Authorization: Bearer`** + server validation |
| 2026-05-05 | Medium | Client **Brief** vs coach **Briefings** — **`04_briefings.md`** / plan **fold** — **singular** vs **plural** **branding** | Copy / nav consistency |
| 2026-05-05 | Medium | **`35s`** **timeout** — **`6324`** — user may perceive **frozen** modal if **spinner** **copy** sparse | Explicit **“still loading”** thresholds (**TBD**) |
| 2026-05-05 | Low | **`moodSummary` + brief** dumped in **one** modal — **density** vs **Weekly** **readable** pacing | Typography / progressive disclosure (**TBD**) |

---

## 12. Security boundaries

- **Brief** payload is **individual** client data — **no** **coach** roster leakage through this **`GET`** (**§8**)
- **Never** log **`X-User-Id`** + full **response body** in **client** logs
- Prefer **server-side** **`get_current_user`** resolution over **trust** **`X-User-Id`** alone (**review** **item**)

---

## 13. Manual test scenarios

1. **CLIENT**, **`!_isCoachOnly`** → Settings → **YOUR TOOLS** → **Weekly Brief** **`2886–2888`** → modal **`2125`**
2. **Happy path** → **`_briefText`** / **`_moodSummary`** populated
3. **Airplane mode** → **offline** messaging
4. **Simulated 401** → **no** silent empty; **no** redirect storm
5. **Dismiss** modal → **`_loading`** false; re-open **re-fetches** or uses **fresh** rule (**TBD**)
6. **`COACH_ONLY`** → **`2872`** — **Brief** row **absent**

---

## 14. Foundational spec cross-reference

- **§3 row 13** — transport, **`X-User-Id`**, state fields  
- **§5** — **`/api/research/nevedal/reports/brief`** — **TBD** tables  
- **§6** — **auth** lifecycle (no **WS** for this feature)  
- **§8** — **client**-scoped data  

---

## 15. Daily health checks

Anchors **`2872`, `2886–2888`, `2125`, `6305–6324`, `6345`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/25_weekly_brief.md +
_FOUNDATIONAL_SPEC §3 row 13, §5 brief row, §10 +
_TAB_INVENTORY §B YOUR TOOLS (2872, 2886–2888), §E E15.
Trace _showWeeklyBrief (2125) → GET /api/research/nevedal/reports/brief (6321–6323) + timeout (6324).
Audit X-User-Id vs Bearer for parity with PaymentMethods / other client REST.
```

---

## 18. Explicit OUT OF SCOPE

- **Coherence reports** — **`nevedal_reports_screen.dart`** — **spec 14** / **foundational row 14**  
- **Coach “Briefings”** surface — **`04_briefings.md`** (**naming** cousin)  
- **NeuralInterfaceV2** recap / **SSE** journey cards — **inventory D10–D11** (**different** entry)  
- **Memory search** — **row 15** — **`secure_search_screen.dart`**

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
