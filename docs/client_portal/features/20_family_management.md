# Client Portal — Family management

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§B FAMILY** (**`2354`**). **Invite** — **`2356`** → **`_showFamilyInviteDialog`** — **`1522`** (**E7**). **Roster + pending** — **`2367–2513`** (**`sanctuary_get_members`** WS **etc.**). **Remove confirm** — **`2444`** (**E21**). Gate **`_isSovereignCircle`** — **`2353`** (**inventory §**H). **`FamilyManagementScreen`** entry from **subscription** strip — **`2578–2602`** → **`billing_screens.dart:1149`** (foundational §**3 row 21**). `_PHASE_3_PLAN.md` **spec 20**. Prefix **`20_`**.

---

## 1. Purpose (1 sentence)

For **eligible** **CLIENT** users on **Sovereign Circle** (**`2353`**), expose **family** invitation (**E7**), **roster / pending invites** (**`2367–2513`**), **dangerous removes** (**E21**), and navigation to **`FamilyManagementScreen`** (**`billing_screens.dart:1149`**, REST + **`sanctuary_get_members`** WS — foundational §**3 row 21**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §**3 row 21**, §**6**, §**8**; `_TAB_INVENTORY_2026-05-05.md` §**B FAMILY**, §**H**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **FAMILY** section — **`2354`** — **only when** **`_isSovereignCircle`** — **`2353`** — omission is **tier-gated**, not a dead **500** (**TBD** empty-state copy when section hidden elsewhere)  
- [ ] **Invite Family Members** — **`2356`** → **`1522`** — success / cancel / failure **surfaced** (no silent no-op)  
- [ ] **Roster + pending invites** — **`2367–2513`** — **loading** resolves or **retry** within **30s**; **errors** say **what** failed and **next step**  
- [ ] **`sanctuary_get_members`** (**WS**) — aligns with foundational row **21** (**`billing_screens.dart:900`**) — **empty** list only when server truly returned **none**, not after **silent** failure (**template**: no silent empty on error)  
- [ ] **Remove family member** (**E21**) — **`2444`** — **confirm** dialog; **destructive** action clearly labeled; outcome **confirmed** (**TBD** undo policy)  
- [ ] **`FamilyManagementScreen`** — **`1149`** — **`_members`**, **`_loading`** — **`857–859`** — same **loading / error** standards (**foundational**)  
- [ ] **Touch targets** ≥ **44pt** on primary CTAs (**invite**, **remove**, **nav** to management)  
- [ ] **`expected_role: CLIENT`** on **`login_request`** — **`_FOUNDATIONAL_SPEC.md` §**6  
- [ ] **`widget.socket`** / **REST** combo in **settings** (**`204–214`**, **`2236`**) — no **race** where **Bearer** REST fires before session ready where backend expects token (**trust** pattern **`_PIPELINE_TEMPLATE.md` §2**)  
- [ ] **`COACH_ONLY`** (**`6748–6756`**) — user may lack full **chat** — family UI **either** hidden **or** **documented** as N/A (**TBD** product rule)  
- [ ] **`family_id` / roster** respects **privacy** (**foundational §**8 — client sees **own** circle, not arbitrary users)  
- [ ] Transitions referencing **Family Sanctuary** aware of **socket close** on **sanctuary push** (**`3701–3712`** — spec **02** / §**10** debt)  

---

## 3. UI components

| Inventory / anchor | `file:line` | Purpose |
|---|---|---|
| **§B FAMILY** header | **`2354`** | Section |
| Gate | **`2353`** | **`_isSovereignCircle`** |
| **E7** | **`2356`** / **`1522`** | **Invite** dialog |
| Roster | **`2367–2513`** | Members + pending + WS |
| **E21** | **`2444`** | **Remove** confirmation |
| **FamilyManagementScreen** | **`billing_screens.dart:1149`** | Full-screen management (foundational §**3 row 21**) |
| Subscription **→** Family | **`2578–2602`** | **`FamilyManagementScreen`** link |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2353` — **`_isSovereignCircle`** (**FAMILY** visibility)  
- `settings_screen.dart:2354` — **FAMILY** section marker  
- `settings_screen.dart:2356` — **Invite Family Members** CTA  
- `settings_screen.dart:1522` — **`_showFamilyInviteDialog`**  
- `settings_screen.dart:2367–2513` — **Roster** / pending / **`sanctuary_get_members`**  
- `settings_screen.dart:2444` — **Family member remove** confirm (**E21**)  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`**  
- `settings_screen.dart:2578–2602` — **Subscription** row **→** **`FamilyManagementScreen`**  
- `billing_screens.dart:1149` — **`FamilyManagementScreen`** (**primary `build`** — foundational §**3 row 21**)  
- `billing_screens.dart:900` — **`sanctuary_get_members`** send site  
- `billing_screens.dart:857–859` — **`_members`**, **`_loading`**  

### Bridge

- **`sanctuary_get_members`** handler — **TBD** `bridge_server.py` line (not in foundational §**4** excerpt; trace when implementing)

### REST

- **TBD** exact paths on **`FamilyManagementScreen`** — foundational lists **REST + WS** only at row **21**

### Storage

- **`users`** / **`family_id`** / **`profile_data`** — **TBD** write paths vs **Sanctuary** tables (**foundational §**5 not row-specific)

---

## 5. State variables

| Concern | Notes |
|---|---|
| **`_members`**, **`_loading`** | **`billing_screens.dart:857–859`** — clear on **error** / **dispose** (`_PIPELINE_TEMPLATE.md` §5) |
| Settings **roster** state | Inside **`2367–2513`** — same **rule** |
| **`_isSovereignCircle`** | Drives **`2353`** |

---

## 6. WebSocket messages

| Direction | Type | Trigger | Expected / side effect | Failure |
|---|---|---|---|---|
| → | **`sanctuary_get_members`** | Roster load / screen open | Member + pending payload | Show error; do not fake **empty** |
| ← | **(response types)** | **TBD** | Update **`_members`** | Dedupe stale |

**Critical:** Row **21** pairs **REST** with this **WS** — verify **optimistic** UI has **timeout** or **ack** (`_PIPELINE_TEMPLATE.md` §6).

---

## 7. Database tables touched

- **TBD** — trace **`sanctuary_get_members`** bridge handler + any **REST** on **`FamilyManagementScreen`** for **`users`**, **`family`**, invite queue tables.

**Cross-feature:** **`family_id`** column vs **`profile_data->>'family_id'`** — workspace **group-corporate-assignment** / **coach-client** rules; keep **client** view scoped to **authorized** members only.

---

## 8. Edge cases

- **Not Sovereign Circle:** whole **FAMILY** block **omitted** — **`2353`**.  
- **Remove HOH / last admin** — **TBD** server rules — UI must surface **forbidden** clearly.  
- **Pending invite** stuck — **expiry** / **resend** — **TBD**.  
- **Offline / 5xx:** distinguish from **true** empty roster.  
- **Family Sanctuary** navigation: **socket** lifecycle — **`3701–3712`**.

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 — `_FOUNDATIONAL_SPEC.md` §**9** (verbatim).

| Commit | Summary |
|---|---|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject proposals that:**

- ❌ **`sanctuary_get_members`** / roster **silent** failure → **blank** UI (same rejection culture as **`8c2a768`**).  
- ❌ **Remove member** without **E21** (**`2444`**) confirmation pattern.  
- ❌ **Bypass** **`2353`** to show **invite** to **non**-circle **without** product + billing sign-off.

---

## 10. Known bugs

### Open

| ID | Symptom |
|---|---|
| FM-01 | **`sanctuary_get_members`** bridge **line** + **REST** list for **`1149`** — **TBD** audit |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §**10 + **FAMILY**-specific.

| Date | Severity | Friction | Target |
|---|---|---|---|
| 2026-05-05 | High | **Family Sanctuary** **closes** primary **chat** socket — **`3701–3703`** — users **managing** family may **bounce** **chat** ↔ **sanctuary** | Spec **02**; reconnect UX |
| 2026-05-05 | Medium | **FAMILY** in **Settings** **`2354`** **vs** **`FamilyManagementScreen`** from **Subscription** **`2578–2602`** — **two** entry **vectors** | **IA** consolidation **TBD** |
| 2026-05-05 | Medium | **`_isSovereignCircle`** — **no** **FAMILY** UI for **other** **tiers** — **support** “**missing** **family**” **tickets** | **FAQ** / **upgrade** **CTA** |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** **vs** **`V2`** — wrong **test** **entry** for **client** **family** flows | **Maintainer** |

---

## 12. Security boundaries

- Client sees **only** **own** **family** **roster** / **invites** authorized by **server** — **not** **other** **families** (**foundational §**8 **spirit**).  
- **Never** log **invite** **tokens** / **deep** links in **plaintext** (**template §**12).  
- If any **handler** lacks **`role == "CLIENT"`** on **`sanctuary_*`** family mutations — **file** security review (cf. **`client_get_coach_month_overview`** gap — §**4**).

---

## 13. Manual test scenarios

1. **Sovereign Circle** **CLIENT** → **Settings** → **FAMILY** section **`2354`** visible  
2. **Invite** **`2356`** → **`1522`** — happy path + failure path  
3. **Roster** **`2367–2513`** refresh after invite acceptance (**TBD** timing)  
4. **Remove** → **`2444`** confirm / cancel  
5. **Subscription** → **`FamilyManagementScreen`** **`1149`** parity with settings roster  
6. **Non**-circle account → confirm **`2353`** hides section    

---

## 14. Foundational spec cross-reference

- **§3 row 21** — **Family** **management** **`build`** / **transport** / **state**  
- **§6** — **hub**, **`login_success`**, **Family Sanctuary** **socket** **caveat** **`3701–3712`**  
- **§8** — family vs coach data walls  

---

## 15. Daily health checks

Anchors **`2353`, `2354`, `2356`, `1522`, `2367–2513`, `2444`, `1149`, `900`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/20_family_management.md +
_FOUNDATIONAL_SPEC.md §3 row 21, §6 item 6, §8 +
_TAB_INVENTORY §B FAMILY, §H FAMILY tier gate, §E E7 + E21.
Trace sanctuary_get_members (billing_screens.dart:900) → bridge handler; REST on FamilyManagementScreen.
```

---

## 18. Explicit OUT OF SCOPE

- **Family Sanctuary** live chat (`sanctuary_message` flows) — **`02_family_sanctuary.md`** (foundational §**3 row 9**)  
- Coach family assignment / admin SQL  
- **SHARE** (spec **19**), GKM BLE sharing (spec **22**)  

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
