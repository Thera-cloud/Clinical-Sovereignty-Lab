# Client Portal — Account deletion (soft-delete window)

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Gap:** **`G21`**. **`E14`** (inventory §E parity). **`39_`**.

**Foundational §2 anchor:** **`ClientSettingsScreen`** — **`settings_screen.dart:2236`**.

---

## 1. Purpose

**ACCOUNT** card (**`settings_screen.dart:3125–3136`**) **`Delete My Account`** (**`3128`**) opens **`DELETE` confirm dialog** (**`settings_screen.dart:2004–2059`**), then performs **`request_account_deletion`** over **`_ephemeralWsRequest`** (**`settings_screen.dart:2075–2080`**) awaiting **`account_deletion_confirmed` / `account_deletion_denied`**.

---

## 2. UX acceptance criteria (**8+**)

- [ ] Danger-styled **`_actionRow`** — **`3128`** (**`danger: true`** argument per call site excerpt)
- [ ] **`30-day` microcopy** in dialog (**`settings_screen.dart:2016–2019`**) aligns **marketing FAQ** (**TBD** web parity)
- [ ] **`DELETE` gated TextField** + uppercase compare — **`settings_screen.dart:2045–2049`**
- [ ] Cancel vs **async delete** **`Navigator.pop`** sequencing — **`2038–2053`**
- [ ] Spinner modal during WS — **`settings_screen.dart:2062–2069`**, dismissed **`2083`** / **`2114`**
- [ ] **`account_deletion_confirmed`** triggers **snackbar**, **delayed logout**, **`LobbyScreen`** reset — **`settings_screen.dart:2086–2100`**
- [ ] **Denied path** surfaces **`reason`** message — **`settings_screen.dart:2102–2110`**
- [ ] **`catch`** dismisses spinner + **snackbar** — **`settings_screen.dart:2112–2121`**

---

## 3–4. Anchors / files

| Concern | `file:line` |
|---------|-------------|
| Row | `settings_screen.dart:3125–3129` |
| `_requestAccountDeletion` | `settings_screen.dart:2004–2059` |
| **`_performAccountDeletion`** | `settings_screen.dart:2062–2122` |
| **`_ephemeralWsRequest`** helper | `settings_screen.dart:49+` *(signature only in foundational sprint — **expand TBD**)* |

---

## 5–7. Messages / Tables

**WebSocket:**

- **`request_account_deletion`** envelope — **`settings_screen.dart:2078`**
- Expected response types **`account_deletion_confirmed`**, **`account_deletion_denied`** — **`2079`**  
- Bridge **`request_account_deletion` handler** linkage — **TBD** (**`bridge_server.py` grep deferred**).

**PostgreSQL:**

- **`users`/`profile`** soft-archive semantics — **TBD** (**policy § no-account-change** aligns with admin approval stories).

---

## 8. Edge cases

| Risk | Anchor |
|------|--------|
| **Dual definitions**: coach **`CoachSettings`** duplicates at **`4556+`** — client spec anchors **`2004–2122`** | keep parity audits |
| **Logout clears biometrics vault** concurrently — **`settings_screen.dart:3130–3135`** (**`_bioIdentity.clearCredentials`** in **Logout row**) |

---

## 9. Anti-patterns from git history

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

- ❌ **Destructive deletes** skipping **`DELETE`** typing gate — **`2045`** baseline
- ❌ Omit **denied** snackbar (**`2110`**)
- ❌ Bypass **`LobbyScreen`** **`pushAndRemoveUntil`** after confirmation — **`2097–2099`** (session bleed)

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| AD-01 | **Duplicate **`_performAccountDeletion`** implementations** (**coach variant**) — divergence risk (**`4556+`**) |

---

## 11. Steve Jobs UX debt

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | High | **`AlertDialog`** only explains **aggregate** purge — users want **bullet checklist** (**what stays vs goes**) | accordion |
| 2026-05-06 | Medium | Placement adjacent **Logout** (**`3128–3136`**) invites **mis-tap** | spacing / confirmation layering |
| 2026-05-06 | Low | Spinner gives **no progress** narrative during **WS handshake** (**`2075`**) | status subtitles |
| 2026-05-06 | Low | **`Exception:` string strip** (**`2117`**) exposes **internal** wording | copy sanitizer |

---

## 17. Cursor prefix

```
Prefix 39_. Row 3128; flows 2004–2122 + _ephemeralWsRequest helper 49+.
Dedupe CoachSettings duplication; audit bridge denial reasons.
```

---

## 18. OUT OF SCOPE

- **`38_legal_agreements_and_data_export.md`**
- **Admin **`no-account`** DB operations** (**workspace governance**)

---

*`2026-05-06`*
