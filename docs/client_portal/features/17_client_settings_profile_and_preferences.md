# Client Portal — Settings: profile shell & preferences (CLIENT)

> Status: `DRAFT` (**full `settings_screen.dart` branching** trimmed per **Phase 3** mandate — **below** excludes **YOUR TOOLS**, **billing**, **vault**, etc.)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §**3 row 11**. `_PHASE_3_PLAN.md` **spec 17**: **§3 r11 shell** + **G27**, **G28–G30**, **§D D13** (**`widget.socket`** from chat **`3765–3786`**). **`ClientSettingsScreen`** — **`settings_screen.dart:2236`** (class **`220–`**, ctor **`204–214`**). Prefix **`17_`**.

---

## 1. Purpose (1 sentence)

Give **authenticated CLIENT** users a **`ClientSettingsScreen`** shell (**`2236`**) where they can **edit profile fields**, **persist notification / voice-default / preferred-contact prefs**, optionally using the **passed-through chat WebSocket** (**`3765–3786`** → **`2846–2849`**, **`1337+`**) alongside **REST** (**`_saveProfile`**, coach card **`476–481`**, ephemeral refresh **`327–331`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §**3 row 11**, §**6 point 5**; `_TAB_INVENTORY_2026-05-05.md` §**B** (**PROFILE**, **PREFERENCES**); **§D D13** — §**A row 8**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **`ClientSettingsScreen`** entry — **`2236`** — loads with coherent **`_profile`** / toggles (**`221–249`**) — **no** indefinite blank scaffold on network failure (**surfaced** error — template)  
- [ ] **`widget.socket`** — **`204–214`** — when **`D13`** supplies it, **`_sendWs`** / **`update_profile`** paths (**`2846–2849`**) work; when **null**, **REST-only** (**or** degraded paths) MUST **not** crash (**TBD** exact branch matrix)  
- [ ] **`D13`** **Settings** icon — **`3765–3786`** — passes active chat socket (**inventory**) — after **`login_success`** + **`CLIENT`** (**`6748–6787`**, **`01`**)  
- [ ] **`expected_role: CLIENT`** on **`login_request`** (**`1488–1493`**) prerequisite for **`Neural chat`** bearer/Redis coherence — **avoid** **`main.dart:10447–10454`**-class **silent** degradation when navigating **deep settings** triggers shared hub assumptions (**parallel** foundational §**6.5**)  
- [ ] **PROFILE —** **`2262–2265`** — REST **`_saveProfile`** — Email / Phone / Emergency / Timezone (**G27**) — success vs failure labeled (**not** snackbar-only **TBD** policy)  
- [ ] **PROFILE —** **`2266–2290`** — Edit/Save/Cancel — **`2846–2849`** **`update_profile`** WS — loading clears on **`dispose`** / **error** (`_PIPELINE_TEMPLATE.md` §5)  
- [ ] **`_refreshProfileFromServer`** ephemeral WS **`auth`** — **`327–331`** — does **not** assume immediate REST Bearer viability (**trust rule** §2 seventh bullet template) — **prefer** tolerant UI when probe races Redis  
- [ ] **`GET .../api/client/coach-info/$coachId`** — **`476–481`** — (**assigned coach**) — distinguish **empty coach** vs **HTTP error** (**`468`** coach field precedence — foundational §**8**)  
- [ ] **PREFERENCES —** **`2803–2814`** **Push / Reminders / Crisis** — **`_saveNotificationPrefs`** (**G28**)  
- [ ] **`2816–2819`** **Voice Mode by Default —** **`_saveVoicePref`** (**G29**)  
- [ ] **`2821–2868`** Preferred Contact (email/SMS) — **`2846–2849`** **`update_profile`** WS (**G30**)
- [ ] **Touch targets ≥ 44pt** on **Save**, **notification** toggles, **contact** controls (template §2)

---

## 3. UI components

| Gap / inventory | `file:line` | Purpose |
|-----------------|-------------|---------|
| **§3 row 11 shell** | **`2236`** | **`ClientSettingsScreen.build`** scroll root |
| **G27 PROFILE** | **`2260`, `2262–2290`** | Fields + REST + WS edit lifecycle |
| **G28–G30 PREFERENCES** | **`2801`, `2803–2814`, `2816–2829`** (pref block through **`2868`** per inventory) | Toggles / voice-default / preferred contact |
| **D13 / §A row 8** | **`3765–3786`** | Chat **`Settings`** **`Navigator`** + **`socket` pass-through** |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:204–214` — **`widget.socket`** optional ctor  
- `settings_screen.dart:220–269` — **`ClientSettingsScreen` state fields** (**foundational §2 table**)  
- `settings_screen.dart:2236` — primary **`build`** (**§3 row 11**)  
- `settings_screen.dart:327–331` — **`_refreshProfileFromServer`** ephemeral **`auth`** WS  
- `settings_screen.dart:468` — coach id resolution (**foundational §8 cross-ref**)  
- `settings_screen.dart:476–481` — **`GET`** coach info REST  
- `settings_screen.dart:1337+` — **`_sendWs`** continuation (**`+`** per foundational §**3 row 11**)
- `settings_screen.dart:2846–2849` — **`update_profile` WS sends** (+ prefs/contact)  
- `settings_screen.dart:3190` — **`_sectionHeader`** (layout helper)  

**PROFILE + PREFERENCES block anchors**

- **`2260–2290`** — **PROFILE** section (**inventory §B**)  
- **`2801–2868`** — **PREFERENCES** block (**inventory §B**)

### Neural entry (socket handoff only)

- `updated_screens.dart:3765–3786` — **`D13`** (**not** exhaustive settings tree)

### Bridge — **representative**

- **`update_profile`** **`elif`** line — **TBD** (**not isolated** in foundational §**4.B** excerpt)  
- **`get_profile`** used from chat (**`1426`**, **`1764`**) — **TBD** handler line — **distinct** from **`ClientSettingsScreen`** hydration path (**doc-only** caveat)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| **`_profile`** | Foundational **`221–249`** (**§3 row 11**) |
| **Notification toggle fields** | Same block + **`_saveNotificationPrefs`** (**`2803–2814`**) |
| **`_voice…` / prefs** (**G29**) | **`2816–2819`** naming **TBD** inside file |
| **Preferred-contact state** (**G30**) | **`2821–2868`** |
| **`_loading`/`_saving`** style flags | **TBD** per section — `_PIPELINE_TEMPLATE.md` §5 **clear-on-error** rule |

---

## 6. WebSocket messages

| Direction | Type | Trigger | Flutter `file:line` | Bridge |
|-----------|------|---------|---------------------|--------|
| → | **ephemeral `auth`/refresh envelope** (**TBD**) | `_refreshProfileFromServer` | **`327–331`** | **TBD** |
| → | **`update_profile`** | Save profile / prefs / preferred contact | **`2846–2849`**, **`1337+`** | **TBD** |

**Note:** Full **`Neural chat`** **`get_profile`** — **`updated_screens.dart:1426`**, **`1764`** belongs to **`01`**, **not** this spec’s hydration contract unless explicitly unified (**TBD**).

---

## 7. Database tables touched

- **Likely** `users` **+** `profile_data` JSONB — **implicit** REST/WS merges — **`TBD`** exact router (**foundational §5** does **not** list row **11**)  
- **`assigned_coach_id`/`coach_id`:** settings **`468`** (**foundational §8**)  

**Cross-feature hazards**

- **Bridge cache vs PG** merges — **`user_store`** sovereignty rules — regressions surface as **prefs appear saved → revert** (**workspace rules** abstract)

---

## 8. Edge cases

- **`widget.socket == null`** — **no **`D13`** pass** (**TBD**) — ensure **SETTINGS** reachable from alternate nav still functional (**deep link TBD**)  
- **Ephemeral **`auth`** refresh** (**`327–331`**) during **cold bridge** (**TBD** UX — retry copy)  
- **Settings → schedule** **without password** — **`2964–2968`** (**foundational §6.5**) — **outside** PROFILE/PREFERENCES subsection but **same file** — flag **routing debt** (**see §11**)  
- **`COACH_ONLY`** — **`6755–6759`** — may **omit** **`NeuralInterfaceV2`**, hence **`D13`** unavailable — **`ClientScheduleScreen`**-only CLIENT should still retain **SETTINGS** accessibility **via** **alternate** tree (**TBD** line) (**implicit** QA gap)  

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

- ❌ **Assume** **`Bearer`** REST parity immediately after **`connect`** (**Redis propagation** gap — **_PIPELINE_TEMPLATE.md` §2**).  
- ❌ **`update_profile` WS sends** **without** **awaiting**/surfacing **`bridge`** errors (**silent profile drift** — **`38158cc` culture**).  
- ❌ **Bundle unrelated §B sections** (**billing**, **quests**, **`YOUR TOOLS`**) into **this spec** (**Phase 3** scope denial).

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence |
|----|---------|----------|
| CSP-01 | **`update_profile` bridge line** unstated — audit fragility | Foundational §**4.B gap** vs **`2846–2849`** |
| CSP-02 | **`Coach-only` settings path** clarity | §**8 COACH_ONLY** ambiguity |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §10** (**settings-adjacent rows**) + **inventory**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **`Settings → schedule`** omits **`password`** — **`2964–2968`** relies on **`_ClientWsHub`** invisibility (**`10419–10454`**) | **Spec 16** / infra fix backlog |
| 2026-05-05 | Medium | **Dual transports** (REST `_saveProfile` + WS `update_profile`) risk **incoherent truths** on one screen | unify success model **TBD** |
| 2026-05-05 | Medium | **`_refreshProfileFromServer`** ephemeral **`327–331`** vs **immediate child REST calls** (**Bearer**) — **timing** confusion | **`01`** handshake doc |
| 2026-05-05 | Low | **`Legacy NeuralInterface`** vs **`V2`** (**§10**) — wrong QA entry for **`D13`** | Maintainer |

---

## 12. Security boundaries

- **Profile + prefs** expose **SELF PII only** (**email**, **phone**, **emergency**) — foundational §**8** boundary.  
- **Never leak** **`coach`** roster — client reads **single** **`coach-info`** (**`476–481`**) for **assigned** coach only  
- **Logging:** forbid bearer tokens in **`print`** (**template §12**)  
- **`get_user_discipline`:** bridge-only (**foundational non-finding**) — **do not expose** falsely in SETTINGS  

---

## 13. Manual test scenarios

1. **`D13`** → open Settings (**`3765–3786`**) → verify **`widget.socket`** non-null (**when from chat**)  
2. **`PROFILE`** field edit → **`Save`** → REST path (**`2262–2265`**) success/failure  
3. **Toggle Edit** → **`update_profile`** (**`2846–2849`**) round-trip (**devtools TBD**)  
4. **PREFERENCES** toggles (**`2803–2814`**) + voice default (**`2816–2819`**)  
5. **Preferred contact** (**`2821–2868`**) **`update_profile`**  
6. **Kill network** mid-save → **recovery** (**template §8**)  
7. **Open SETTINGS** lacking **`socket`** (**TBD** alt nav)  

---

## 14. Foundational spec cross-reference

- **Primary row:** §**3 row 11** (**Client settings hub**)  
- **Auth lifecycle:** §**6** (**points **2**, **5** — **`_ClientWsHub`**, **`2964–2968`**)  
- **`Coach`** REST **`476–481`:** §**4.A** (**vs unused **`client_get_coach_info`**)  
- **`D13` socket:** overlaps **`01`** (**Neural** **`3663`**)  
- **Privacy:** foundational §**8** — coach vs client scopes  

---

## 15. Daily health checks

Anchors **`204–214`, `2236`, `2260`, `2821`, `2846`, `327`, `3765`, `476`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/17_client_settings_profile_and_preferences.md +
_FOUNDATIONAL_SPEC §3 row 11, §6.5 +
_TAB_INVENTORY §B PROFILE + PREFERENCES + §D D13 §A row 8.
OUT OF SCOPE Phase 17: §3 row 12 YOUR TOOLS 2872–2899,
rows 13–23 screens (brief, reports, beacon, vault, billing, mesh, quests, archetype …).
```

---

## 18. Explicit OUT OF SCOPE (Phase 17 mandate)

Cross-reference **`_FOUNDATIONAL_SPEC.md`** rows **≠** PROFILE/PREFERENCES shell:

| Anchor | Reason |
|--------|--------|
| **`2872–2899`** | **§3 row 12 YOUR TOOLS** — separate **`29`/`14`/`15`/`28`** specs |
| **`2520–2605+`** tier/plan/token strip | **`21`/`22`** |
| **`2608+`** voice therapy card | **`23`** |
| **`2744+`** Sovereign vault | **`24`** |
| **`2295`** calendar OAuth | **`18`** |
| **`2303` SHARE**, **`2354` FAMILY**, **`2977` COACHING TOOLS**, **`2999` ARCHETYPE**, **`3025` QUESTS** | **`19`/`20`/`30`/`31`/`33`/`32`** |
| **`3046`** SECURITY biometric | **`09`** (**partial overlap** allowable only by cross-link — **do not duplicate §** here) |

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
