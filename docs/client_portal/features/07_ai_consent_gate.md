# Client Portal — AI consent gate (`AiConsentScreen`)

> Status: `DRAFT` (copy / legal text line map **TBD** inside **`build`**)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 6**, §2 (“AI consent (pre-chat)”); `_TAB_INVENTORY_2026-05-05.md` **§C C8**; `_PHASE_3_PLAN.md` **spec 07**. Prefix **`07_`**.

---

## 1. Purpose (1 sentence)

Block **`NeuralInterfaceV2`** until the client records **AI use consent** via REST **`POST /api/client/ai-consent`** (**`ai_consent_screen.dart:55–65`**, send block **`58–65`**) on **`AiConsentScreen`** (**`build`** **`96`**), shown when **`!hasConsent && !localConsent`** — **`main.dart:6770–6780`** (**C8**); broader client branch context **`6761–6780`**.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 row **6**, §6–§8; `_TAB_INVENTORY_2026-05-05.md` **C8**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] Primary **`build`** is reachable and completable — **`ai_consent_screen.dart:96`**  
- [ ] User must **explicitly agree** before submit — **`_agreed`** **`42–43`**  
- [ ] **`POST /api/client/ai-consent`** fires only after valid local state — **`58–65`**  
- [ ] **`_submitting`** resolves on **success**, **error**, **timeout**, and **`dispose`** (**`42–43`** — no stuck spinner)  
- [ ] Errors show **actionable** messaging (not generic); **no** silent empty state on failed REST  
- [ ] Touch targets ≥ **44pt** on primary CTAs — template  
- [ ] **Distinct from re-consent (`C3`):** **`ReConsentScreen`** is driven by **`consent_update_needed`** — **`main.dart:6660`**, **`6674–6681`**; **this** gate uses **`hasConsent` / `localConsent`** — **`6770–6780`** — no conflation in copy or routing tests  
- [ ] **Post-`login_success` ordering:** sits in client nav chain with **`_ClientWsHub.attach`** and **`NeuralInterfaceV2`** vs consent — **`main.dart:6748–6787`** (see **§6**); do not assume chat socket exists before consent completes  
- [ ] **`COACH_ONLY` / schedule-only** clients — **`main.dart:6748–6756`** — confirm product rule: consent **N/A** vs **required** (**TBD**)  
- [ ] **Web + Redis:** if any REST runs immediately after bridge token handoff, avoid **401 redirect loops** on transient auth (workspace trust pattern — consent is **REST**, not bridge WS)  

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| **`AiConsentScreen`** | `ai_consent_screen.dart:23` (**C8** class anchor) | Pre-chat consent shell | Inventory |
| **`build`** | `ai_consent_screen.dart:96` | Primary UI | §3 row **6** |
| **Agreement + submit state** | `ai_consent_screen.dart:42–43` | **`_agreed`**, **`_submitting`** | §3 row **6** |

---

## 4. Files (canonical references)

### Mobile
- `ai_consent_screen.dart:21–35` — profile / consent keys (**§8** privacy cross-ref)
- `ai_consent_screen.dart:42–43` — **`_agreed`**, **`_submitting`**
- `ai_consent_screen.dart:55–65` — REST **`/api/client/ai-consent`** (assembly **`55–57`**, **`58–65`**)
- `ai_consent_screen.dart:96` — **`build`**
- `main.dart:6748–6787` — **`_ClientWsHub`**, **`AiConsentScreen`** vs **`NeuralInterfaceV2`**, **`COACH_ONLY`** (**§1**, **§6**)
- `main.dart:6761–6780` — client branch (**§6**); predicate **`!hasConsent && !localConsent`** — **`6770–6780`** (**C8**, inventory §**H**)

### Bridge (WebSocket)

- **N/A** for this feature’s **primary** outbound path (REST-only per §3 row **6**). Chat **`login_request`** afterward — **`updated_screens.dart:1488–1493`** — see **`01_chat_with_nate.md`**.

### REST (FastAPI)

- **`POST /api/client/ai-consent`** — cited at **`ai_consent_screen.dart:58–65`**; router file / column mapping — **TBD** (`_FOUNDATIONAL_SPEC.md` §5 **AI consent** row)

### Storage

- **TBD** — foundational §5 lists **`/api/client/ai-consent`** with **TBD** column mapping

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_agreed` | `bool` | user toggles checkbox / equivalent **TBD** | reset **TBD** | **`false`** |
| `_submitting` | `bool` | before **`58–65`** | **`then` / `catch` / `finally`** / **`dispose`** | **`false`** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Notes |
|-----------|------|---------------------|-------|
| — | *(none for consent submit)* | — | **REST-only** gate per §3 row **6** |

**Lifecycle context (post-login, not a WS “type”):** **`_ClientWsHub.attach(_channel!)`** — **`main.dart:6751–6752`** — then **`NeuralInterfaceV2`** **or** **`AiConsentScreen`** per **`6748–6779`** branch.

---

## 7. Database tables touched

- **TBD** — **`POST /api/client/ai-consent`** persistence not enumerated in foundational §5 (mark **router trace** when authoring implementation notes)

---

## 8. Edge cases

- **`localConsent` true** but server **`hasConsent` false** (or inverse) — **`6770–6780`** predicates; drift = loop or skip — **TBD** product rule  
- **`consent_update_needed` true** (**`C3`**) **and** AI consent incomplete — ordering vs stacked modals — **TBD** (see **`02_re_consent.md`**)  
- **Network loss** mid-**`POST`** — idempotency / duplicate submit — **TBD**  
- **Admin / non-client** — gate not in client portal scope; predicate lives in client post-login branch **`6761–6780`** only  

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits — `_FOUNDATIONAL_SPEC.md` §9 (verbatim).

| Commit | Summary (foundational) |
|--------|-------------------------|
| `38158cc` | Client schedule: shared authenticated app WS + availability error handling |
| `2145c9d` | Attach `NeuralInterface` WS to `_ClientWsHub` after `login_success` |
| `8c2a768` | Gate diagnostic for `client_get_coach_availability` silent drop |
| `c43b9a3` | Diagnostic logging on `client_get_coach_availability` |
| `ea68dd3` | Tighten `client_get_upcoming_sessions` filter (duplicate AI rows) |
| `d7ec21a` | Bridge WebSocket `UnboundLocalError` / datetime shadowing fix |

**Reject:** treating AI consent as **`mark_onboarding_complete`** (**06**) or **trial/paid HTTP onboarding** (**03**/**04**); swapping **`C3`** re-consent payloads for **`C8`** profile keys without spec update.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| AC-01 | DB / column mapping for **`ai-consent`** | `_FOUNDATIONAL_SPEC.md` §5 **TBD** | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 rows — foundational §10 + §7–§8 where applicable to **consent / auth**.

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | High | **`login_success` → nav** cascade packs **many** gates (**tutorial `C7`**, **consent `C8`**, modals **`6669`**) — **`6656–6787`** | User can feel “stuck in compliance” before first chat turn; consent is one layer |
| 2026-05-05 | Medium | **`ReConsentScreen` (`C3`)** vs **`AiConsentScreen` (`C8`)** — different triggers (**`6660`** vs **`6770–6780`** — inventory §**H** gating table) | Copy/IA must not blur **platform consent update** vs **AI consent** |
| 2026-05-05 | Medium | **`recording_consent`** client storage story **TBD**; coach help text only in settings grep — **`settings_screen.dart:5786`** | Risk: user believes they “consented to recording” when only AI gate fired — align **38** legal spec later |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** vs **`NeuralInterfaceV2`** — **`main.dart:1339`** vs **`updated_screens.dart:1183`** | Wrong repair doc if post-consent routing regresses |

---

## 12. Security boundaries

- **AI consent + profile keys** — **`ai_consent_screen.dart:21–35`**, **`main.dart:6761–6779`** (`_FOUNDATIONAL_SPEC.md` §8).  
- **REST** must use **Bearer** (or project-standard client auth); do not log tokens.  
- **Pre-chat** means no **`nate_query`** until consent path satisfied — **`01_chat_with_nate.md`** cross-ref.  

---

## 13. Manual test scenarios

1. **CLIENT** with **`!hasConsent && !localConsent`** → lands on **`AiConsentScreen`** **`96`**.  
2. Accept + submit → **`58–65`** returns success → navigates toward **`NeuralInterfaceV2`** per **`6748–6779`** (assert destination **TBD** line).  
3. **Decline / error path** — **`_submitting`** clears; user sees next step (**TBD**).  
4. **Re-consent pending** — verify stack order vs **`6660–6681`** (**TBD** fixture).  
5. **`COACH_ONLY`** — consent shown or skipped per **`6748–6756`** (**TBD** assertion).  

---

## 14. Foundational spec cross-reference

- **§3 row:** **6**  
- **§2:** AI consent (pre-chat) table row  
- **§6:** Auth lifecycle **`6656–6787`**, **`_ClientWsHub`** **`6751–6752`**  
- **§5:** AI consent **TBD**  
- **§8:** Security / privacy **AI consent** bullet  

---

## 15. Daily health checks

Manual: **`96`**, **`58–65`**, **`6770–6780`** (predicate) / **`6761–6780`** (branch) anchors unchanged after edits; **`POST`** path still matches env base URL.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational + inventory + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/07_ai_consent_gate.md +
_FOUNDATIONAL_SPEC.md §3 row 6 + §8 AI consent.
Cross-ref 02_re_consent.md (C3) vs C8 — different triggers.
Cross-ref 01_chat_with_nate.md — consent is pre-chat; REST not WS.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` only — 2026-05-05.*
