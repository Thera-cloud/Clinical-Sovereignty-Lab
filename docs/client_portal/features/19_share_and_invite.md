# Client Portal — Share & invite (Settings)

> Status: `DRAFT` (`_inviteFriend` transport + **SMS** carrier path **TBD** in foundational pass)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G25**, **G26**, **§E E12**, **§B SHARE** (**`2303`**). Invite — **`2305`** → **`_inviteFriend`** (**`1502`**). Copy link — **`2325–2344`**. Gate **`!_isCoachOnly`** — **`2301`** (**§**H row **SHARE section**). `_PHASE_3_PLAN.md` **spec 19**. Parent **`ClientSettingsScreen`** — **`2236`**. Prefix **`19_`**.

---

## 1. Purpose (1 sentence)

Give **eligible CLIENT** users (**not** **`COACH_ONLY`**) in **Settings** a **SHARE** section (**`2303`**) to **invite a friend** (**`2305`**, **`_inviteFriend`** at **`1502`**, **E12** / **G25**) and **copy a referral-style link** to the clipboard (**`2325–2344`**, **G26**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**B SHARE**, §**H**; `_FOUNDATIONAL_SPEC.md` §**3 row 11**, §**6**, §**8**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **SHARE** section — **`2303`** — **only when** **`!_isCoachOnly`** — **`2301`** / inventory §**H** — when **hidden**, user sees **planned** omission (**not** a dead-end error — **TBD** copy elsewhere)  
- [ ] **Invite a Friend** — **`2305`** — invokes **`_inviteFriend`** — **`1502`** — **success** / **cancel** / **failure** are **visible** (no **silent** no-op)  
- [ ] **Copy link** — **`2325–2344`** — **clipboard** write **confirms** to user (**snackbar / toast** — **TBD**) and handles **web vs mobile** permission denials  
- [ ] **Touch targets** ≥ **44pt** on **Invite** and **Copy** actions (template §2)  
- [ ] **Errors** state **what failed** (network, **SMS** not sent, share sheet dismissed, **clipboard** denied) and **what to do next**  
- [ ] **Loading** on **Invite** path resolves within **30s** or offers **retry** (template §2)  
- [ ] **No** fake “sent” state when the **OS** or **carrier** rejected the action (**TBD** signal from **`1502`** implementation)  
- [ ] **`expected_role: CLIENT`** / **Settings** entry consistent with **`6748–6787`** and **`17`** (hub / profile context)  
- [ ] **Privacy:** shared **link** must not **embed** secrets (tokens) in a way that violates **minimum necessary** — **TBD** link format review (**foundational §**8 spirit)  
- [ ] **Rate limiting / double-tap** — **TBD** — avoid **duplicate** mass invites from **accidental** double submit  
- [ ] **Accessibility:** **Invite** flow **dismissible** without trapping focus (**TBD** modal vs sheet)  
- [ ] **Cross-platform:** **`kIsWeb`** share/clipboard quirks — align with workspace **Safari** / Flutter **web** guidance when testing (**TBD**)  

---

## 3. UI components

| Inventory | `file:line` | Purpose |
|-----------|-------------|---------|
| **§B SHARE** | **`2303`** | Section header |
| **G25 / E12** | **`2305`** | **Invite** CTA → **`1502`** |
| **G26** | **`2325–2344`** | **Copy link** |
| §**H gate** | **`2301`** | **`!_isCoachOnly`** wrap |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2301` — **`!_isCoachOnly`** guard (**SHARE** visibility)  
- `settings_screen.dart:2303` — **SHARE** section marker  
- `settings_screen.dart:2305` — **Invite a Friend**  
- `settings_screen.dart:1502` — **`_inviteFriend`** implementation anchor  
- `settings_screen.dart:2325–2344` — **Copy link** / clipboard UI  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`** (parent)

### Bridge / REST

- **`_inviteFriend`** backing (**HTTP**, **SMS bridge**, **`share_sheet`** only) — **TBD** (not listed in foundational **§**4 excerpt)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| **`_isCoachOnly`** | From **`737`** (**inventory §**B preamble) — drives **`2301`** |
| **`_inviting`** / **`_copying`** (names **TBD**) | Must obey **`dispose`** clear rule (`_PIPELINE_TEMPLATE.md` §5) |

---

## 6. WebSocket messages

- **None cited** for **invite / copy-link** in `_FOUNDATIONAL_SPEC.md` §**4** — **default** REST / platform channel unless trace finds **`_sendWs`** — **TBD**.

---

## 7. Database tables touched

- **TBD** — referral logs, **`signup_sharing_ledger`**, etc. (**workspace **GKM**/sharing** stacks are **distinct** — **spec **22**/BLE** — do not assume without trace)

---

## 8. Edge cases

- **`_isCoachOnly` true:** whole **§B SHARE** **omitted** — **`2301`** — support scripts must not claim bug (**§**H**).  
- **Clipboard unsupported** (**web**/older OS) — **degrade** to **manual select** or **error** (**TBD**).  
- **SMS / A2P** policy: production **carrier** blocks on raw SMS are **Plausible** — **invite** UX must surface **failure** (**product** aligns with **`Twilio Verify`** patterns elsewhere — **TBD**, not traced in foundational).  
- **Offline:** **Invite** / **REST** failures distinguish **offline** vs **5xx** (template §8).

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

- ❌ **Silent** **`_inviteFriend`** / **share** failures (same rejection culture as **`8c2a768`** diagnostics for silent drops).  
- ❌ **`Copy link`** with **no** user feedback — looks **broken**.  
- ❌ Bypass **`2301`** gate to expose **invite** on **`COACH_ONLY`** without **product** sign-off (**tier model** clash).

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| SI-01 | **`1502`** body + outbound API **unknown** — audit **TBD** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **`_FOUNDATIONAL_SPEC.md` §**10 + **gates**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | Medium | **`SHARE`** **invisible** to **`COACH_ONLY`** (**`2301`**) — “**can’t invite**” **support** confusion | FAQ / **`35b`** (**TBD**) |
| 2026-05-05 | Medium | **SMS** invites vs **carrier** / **10DLC** reality — **`1502`** path may **opaque-fail** | Product + **Twilio** policy **TBD** |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** vs **`V2`** (**§**10) — wrong **manual** test entry for **Settings** flows | Maintainer |
| 2026-05-05 | Low | **Copy link** **without** **obvious** “**copied**” **affordance** — **trust** hit | **2325–2344** microcopy |

---

## 12. Security boundaries

- **Invite payloads** — **never** embed **refresh tokens** / **admin** bearer material in SMS body (**template §12**).  
- **Referral identifiers** — **rate-limit** server-side (**TBD**) to curb **spam** / **enumeration**.  
- **Clipboard** copies **PUBLIC** referrer URL tier only — confirm **no** PII leakage in query string (**TBD** audit).

---

## 13. Manual test scenarios

1. **`!_isCoachOnly`** CLIENT → **Settings** → **SHARE** section **`2303`** visible  
2. **Invite** **`2305`** → **`1502`** success / failure UX  
3. **Copy link** **`2325–2344`** → paste in external app → **URL** shape **TBD** assert  
4. **`COACH_ONLY`** → **confirm** section **missing** (**`2301`**)  
5. **Web Safari** clipboard — **permission** denial path  

---

## 14. Foundational spec cross-reference

- **§3 row 11** (**Client settings hub**) — SHARE is **subset**  
- **§8** — privacy / PII boundaries for **shared** links  
- **§6** — **login_success** before **Settings** from **chat** (**`D13`** **`3765–3786`** — **`17`**)  

---

## 15. Daily health checks

Anchors **`1502`, `2301`, `2303`, `2305`, `2325–2344`, `2236`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** `TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/19_share_and_invite.md +
_TAB_INVENTORY §B SHARE, §E E12, §G G25-G26, §H SHARE gate +
_FOUNDATIONAL_SPEC §3 row 11, §8. Trace _inviteFriend (1502) implementation + backends.
```

---

## 18. Explicit OUT OF SCOPE

- **GKM BLE token sharing**, **stripe invite purchases**, **`community_mesh`** — **other specs**  
- **Family Sanctuary** invitations (**`2356`**, **`_isSovereignCircle`**) — **spec `20`**

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
