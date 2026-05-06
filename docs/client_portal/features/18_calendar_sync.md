# Client Portal — Calendar sync (Google)

> Status: `DRAFT` (OAuth callback / token storage lines **TBD** in foundational pass)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G15**, **§B CALENDAR SYNC** (`2295`). **`GoogleCalendarSection`** — **`settings_screen.dart:2296–2298`**. `_PHASE_3_PLAN.md` **spec 18**. Parent surface: **`ClientSettingsScreen`** **`2236`** (foundational §**2** table, §**3 row 11**). Prefix **`18_`**.

---

## 1. Purpose (1 sentence)

Let **CLIENT** users in **Settings** hook **Google Calendar** via **`GoogleCalendarSection`** (**`2296–2298`**) using the **OAuth REST** path noted in the inventory, so availability-related flows can respect **Google busy** data (**`google_external_busy`** — `_FOUNDATIONAL_SPEC.md` §**5** alongside **`client_get_coach_availability`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**B CALENDAR SYNC**; `_FOUNDATIONAL_SPEC.md` §**3 rows 10–11**, §**6**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **Section header** **`CALENDAR SYNC`** — **`2295`** — always present for traced **CLIENT** **`ClientSettingsScreen`** build (**inventory**: Conditional? **None**)  
- [ ] **`GoogleCalendarSection`** — **`2296–2298`** — loads without **indefinite** spinner; **error** states **name the failure** + **retry/next step**  
- [ ] **OAuth** completion (or cancel) returns user to a **predictable** Settings state — **no** stranded **WebView**/browser tab story (**TBD** implementation)  
- [ ] **`expected_role: CLIENT`** — lobby / session contract consistent with **Settings** entry (**`6748–6787`**, **`01`**, **`17`**)  
- [ ] **`_loading` / `_connecting`-class** flags (**TBD** inside widget) clear on **`dispose`**, **cancel**, **timeout**, and **error** (`_PIPELINE_TEMPLATE.md` §5)  
- [ ] **Touch targets** ≥ **44pt** on connect / disconnect / primary CTAs  
- [ ] **Silent empty** forbidden when server returned **401/403/5xx** — template §2  
- [ ] **Safari / Flutter web** — OAuth return + **sessionStorage** quirks — cross-check workspace **Safari** caching rules when testing (**TBD** scenario link)  
- [ ] **Disconnect / revoke** (**TBD**) — user understands **coach availability** may lose **Google overlap** accuracy (**§5** `google_external_busy` — **conceptual** coupling to **spec `16`**)  
- [ ] **No** misleading “synced” badge before **server acknowledges** token/link (**TBD**)  
- [ ] **COACH_ONLY** users’ access to this block — **implicit** via **Settings** routing — if **hidden**, document **N/A** vs **error** (**TBD** **`_isCoachOnly`** guard on section **TBD**)  
- [ ] **Privacy copy** — user knows **which** calendar scopes are read (**healthcare-adjacent** trust — **TBD** product/legal)  

---

## 3. UI components

| Inventory | `file:line` | Purpose |
|-----------|-------------|---------|
| **§B CALENDAR SYNC** | **`2295`** | Section container |
| **`GoogleCalendarSection`** | **`2296–2298`** | OAuth / link UI |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2295` — **CALENDAR SYNC** section marker  
- `settings_screen.dart:2296–2298` — **`GoogleCalendarSection`**  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`** (parent)  
- **`GoogleCalendarSection` implementation file** — **TBD** (**not** enumerated in foundational excerpt)

### REST / backend

- **OAuth endpoints + token persistence** — **TBD** (**not** listed in `_FOUNDATIONAL_SPEC.md` §**5** calendar row)

### Related (read-only contract)

- **`client_get_coach_availability`** path references **`google_external_busy`** — **`bridge_server.py:12166–12237`** (**foundational §**5) — **booking UX** spec **`16`**

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| OAuth / linked-account flags | **Inside** **`GoogleCalendarSection`** — **TBD** |
| **Settings**-level **`_profile`** | May carry calendar connection metadata — **TBD** |

---

## 6. WebSocket messages

- **None asserted** for **G15** in foundational **§4** excerpt — **OAuth via REST** only per inventory. If a **future** bridge message appears, **append** here after trace.

---

## 7. Database tables touched

- **TBD** — expect **`users` / `profile_data` / OAuth token table`** — **not** named in foundational §**5** for this widget.

**Cross-feature hazards**

- **`google_external_busy`** ingestion must stay **consistent** with **`client_get_coach_availability`** — **`12166–12237`** (foundational §**5**)  
- **Schema mismatch** risk on **`coaching_sessions.coach_id`** remains a **schedule** concern (**foundational §**5 footer) — calendar sync must **not** mask that failure mode

---

## 8. Edge cases

- **OAuth denied** / **back button** — user not stuck (**TBD**)  
- **Token expiry / refresh** — **TBD** — user messaging when slots show **stale** busy  
- **Multiple Google accounts** — **TBD** account picker UX  
- **`main.dart:10419–10454`** hub-dependent **schedule** path — calendar data may still affect **availability** display when user books from **Settings → schedule** (**`2964–2968`** — foundational §**6.5**)  

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

**Reject proposals that**

- ❌ **Silently** swallow OAuth or token exchange errors (**8c2a768** diagnostic culture).
- ❌ Claim **“calendar connected”** UI before **server-side** validation (**double-booking** trust risk).  
- ❌ **Couple** calendar OAuth to **secondary WebSocket** identity without **`login_request`** story (**distress beacon** anti-pattern — foundational §**6.7** analogue).

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| CS-01 | **`GoogleCalendarSection` file + REST routes** unstated in foundational — audit **TBD** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10** (**schedule-adjacent**) + **OAuth** product gap.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **Schedule from settings** relies on **invisible hub** + **no password** — **`2964–2968`** / **`10419–10454`** — calendar state may **appear** linked while **booking** still fails | **`16`** |
| 2026-05-05 | Medium | **OAuth** flows on **mobile web** (**Safari**) — redirect / **storage** fragility — workspace **SW** rules | **QA matrix TBD** |
| 2026-05-05 | Medium | **`client_get_coach_availability`** **`8c2a768`** history — **silent** external-busy drop confuses **calendar** vs **coach** fault | Observability |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** vs **`V2`** — irrelevant to widget but **wrong** screen for manual OAuth QA | §**10** |

---

## 12. Security boundaries

- **Tokens** must **never** log to **client** consoles in **prod** (**template §12**).  
- **Scopes**: **minimum** read calendars needed for **busy** blocks — **product** must list (**TBD**).  
- **CLIENT**-only: no **coach** calendar management here (**inventory** §**B** is **`ClientSettingsScreen`**).

---

## 13. Manual test scenarios

1. Open **Settings** → **CALENDAR SYNC** **`2295–2298`**.  
2. **Connect** Google → complete OAuth → return → **success** surface (**TBD**).  
3. **Deny** OAuth → recoverable UI.  
4. **Disconnect** (**TBD**) → confirm **availability** changes (**spec `16`** when unblocked).  
5. **Cold start** → token still valid — **TBD** refresh.  
6. **Web Safari** — parity spot-check (**TBD**).

---

## 14. Foundational spec cross-reference

- **Settings parent:** §**3 row 11**  
- **Schedule / busy integration:** §**3 row 10** + §**5** (`google_external_busy`, **`12166–12237`**)  
- **Lifecycle:** §**6** (**hub** **`10419–10427`**)  

---

## 15. Daily health checks

Anchors **`2295`, `2296–2298`, `2236`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/18_calendar_sync.md +
_TAB_INVENTORY §B CALENDAR SYNC, §G G15 +
_FOUNDATIONAL_SPEC §3 rows 10–11, §5 google_external_busy.
Trace GoogleCalendarSection impl + OAuth routes; then fill §4–§7.
```

---

## 18. Explicit OUT OF SCOPE

- **Full client schedule / booking** UX — **spec `16`**  
- **Coach / admin** calendar tools  
- **Microsoft / Apple** calendars — **inventory names “Google”** only until product expands  

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
