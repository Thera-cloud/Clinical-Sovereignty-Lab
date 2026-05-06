# Client Portal — Neural interface interactions (compose bar & chat chrome)

> Status: `DRAFT` (upload / vault **network pairing** detail **TBD**)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 7** (shell only — **composition** splits here); `_TAB_INVENTORY_2026-05-05.md` **§D** **D1, D2, D3, D4, D15, D16**; **§A** adornments **B4–B6**; **§G** **G5, G6, G7**. `_PHASE_3_PLAN.md` **spec 11** — complements **`01_chat_with_nate.md`**. Prefix **`11_`**.

---

## 1. Purpose (1 sentence)

Extend **`NeuralInterfaceV2`** (**`3663`** — §**3 row 7**) with **input-layer** behaviors: **mic dictation**, **vault token injection**, **TTS read-back** of draft, **custom vocabulary**, **vault upload visibility**, and **picker return → composer** — without re-documenting **`nate_query`** / **`login_request`** (**`01`**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**D** (D1,D2,D3,D4,D15,D16), §**A** (**B4–B6**), §**G** (**G5–G7**); `_FOUNDATIONAL_SPEC.md` §**3 row 7**, §**7**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **D1 Mic / dictation** — **`4051–4067`**; deeper control surface **`2922–2974`**; respects **`_speechAvailable`** (**B5**) — no “dead mic” silent failure  
- [ ] **D2 Vault attach** — **`4068–4080`** inserts **`[Vault:<id>]`** into **`_chatController`**; gated **`ENABLE_SOVEREIGN_VAULT && _canUseVault()`** — **`3510–3516`** (**B4**)  
- [ ] **D3 TTS read-back** — AppBar **`3755–3764`**; implementation **`_readBackDraft`** **`2445–2455`**; **Stop** state visible (**inventory §A row 7**)  
- [ ] **D4 Custom vocabulary** — **`3750–3754`** launches sheet; **`_openVocabularySheet`** **`2200`**; terms influence recognition (**inventory D4**)  
- [ ] **D15 Upload chrome** — **`4039–4044`** visible while **`_uploadProgressState.isVisible`** (**B6**)  
- [ ] **D16 Vault return path** — **`3779–3783`** merges **`Navigator.push`** result into draft (**token injection** continuity)  
- [ ] **`_speechAvailable`** false → mic affordance **does not** impersonate readiness (**B5**)  
- [ ] **`_uploadProgressState`** never stuck **true** after failed upload (**TBD** handler parity) — template dispose rule  
- [ ] Tier / feature drift: **`_canUseVault()`** and **`ENABLE_SOVEREIGN_VAULT`** stay aligned — **`3510–3516`**  
- [ ] **`01` boundary:** **`nate_query`** **`3205–3209`**, **`get_metrics`**, nudges, AI modes (**`1877–1889`**) documented in **`01`** — regressions traced there first  

---

## 3. UI components

| Inventory | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| **D1** Mic dictation | `4051–4067`; **`2922–2974`** | STT compose / edit-by-voice | **G6** |
| **D2** Vault attachment | **`4068–4080`** | `[Vault:<id>]` in composer | **B4**; pairs **D16** |
| **D3** Read draft aloud | **`3755–3764`**; **`2445–2455`** | TTS playback | **G7**; §**A row 7** |
| **D4** Custom vocabulary | **`3750–3754`**; **`2200`** | SR lexicon sheet | **G5**; §**A row 6** |
| **D15** Upload progress | **`4039–4044`** | Vault upload UX | **B6** |
| **D16** Vault picker return | **`3779–3783`** | `Navigator.pop` → composer | Requires **chat context** |

---

## 4. Files (canonical references)

### Mobile
- `updated_screens.dart:2200` — **`_openVocabularySheet`** (**D4**)
- `updated_screens.dart:2445–2455` — **`_readBackDraft`** (**D3**)
- `updated_screens.dart:2922–2974` — mic / dictation **controls** (**D1**)
- `updated_screens.dart:3510–3516` — **`_canUseVault()`** gate (**B4**)
- `updated_screens.dart:3663` — **`NeuralInterfaceV2`** **`build`** (shell — **`01`**)
- `updated_screens.dart:3750–3754` — Custom Vocabulary (**D4**/§**A row 6**)
- `updated_screens.dart:3755–3764` — Read aloud / Stop (**D3**/§**A row 7**)
- `updated_screens.dart:3779–3783` — **Vault item return** (**D16**)
- `updated_screens.dart:4039–4044` — Upload progress (**D15**/ **B6**)
- `updated_screens.dart:4051–4067` — Mic / dictation toggle (**D1**/ **B5**)
- `updated_screens.dart:4068–4080` — Vault attach button (**D2**/ **B4**)
- Scaffold span (inventory §**A intro**): **`3663–4137`**

### Bridge / REST

- **TBD** per sub-feature — foundational §**4.B** lists chat types (**`01`**); vault **upload** may pair with REST/R2 (**spec 24**) — **not** split in foundational pass  

### Storage

- **TBD** — vault bytes / citations persistence (**spec 24**)

---

## 5. State variables

| Concern | Representative | Notes |
|---------|----------------|-------|
| Speech | **`_speechAvailable`** (**B5**) | Gates **D1** |
| Upload UI | **`_uploadProgressState.isVisible`** (**B6**) | Gates **D15** |
| Vault eligibility | **`_canUseVault()`** — **`3510–3516`** | Gates **D2**/ **B4** |
| Composer | **`_chatController`** | **D2** / **D16** targets |

*(Full typed fields — **TBD** trace; rule: loading flags clear on **`dispose`** / error — template §5)*  

---

## 6. WebSocket messages

| Relation | Types | Notes |
|----------|-------|-------|
| **Primary chat** | `nate_query`, `login_request`, … | **`01`** §6 exclusively for **turn-taking** |
| **This spec** | *Indirect* | Mic/vault/TTS compose **toward** a later **`nate_query`**; **`export_completed`** **`3289–3294`** is **`01`** if upload/export pipeline ties to chat (**TBD**) |

---

## 7. Database tables touched

- **TBD** — vault + vocabulary persistence not enumerated under §**3 row 7** in foundational §**5**

---

## 8. Edge cases

- **Web:** **`kIsWeb`** STT/TTS parity vs native — **TBD**  
- **`_speechAvailable` false:** offer explanation / settings path (**TBD** copy)  
- **Tier downgrade:** **`_canUseVault()`** false mid-session → **D2**/ **D16** hidden or degraded gracefully  
- **Concurrent TTS + mic:** **D3** vs **D1** — prioritize **stop** UX (**3755–3764**)  

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

**Reject:** shipping **D15** stuck states; attaching **vault chrome** (`4068`) when **`ENABLE_SOVEREIGN_VAULT`** is false; routing **legacy** **`NeuralInterface`** (`main.dart:1931`) for **D1–D16** QA without **`01`** parity.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence |
|----|---------|----------|
| NII-01 | Upload/error → **`isVisible`** stuck | **TBD** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10–§7** (relevant).

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | Medium | **`NeuralInterface`** vs **`NeuralInterfaceV2`** coexist — **`main.dart:1339`** vs **`1183`** | Wrong QA target for compose-bar changes |
| 2026-05-05 | Medium | **`biometric_update` every 2s** — **`nevedal_flutter.dart:471–472`** | Competes for attention with mic/draft UX on same scaffold |
| 2026-05-05 | Low | **`get_history`** / profile truth — **`bridge_server.py:14765–14768`** (**`01`**) | After **D16** inject, user expectation of “saved” transcript vs server **TBD** |
| 2026-05-05 | Low | Vault browse entry also in **settings** (**inventory §B**) — **`2778–2786`** vs **D2**/ **D16** | Two mental models for same R2-backed asset |

---

## 12. Security boundaries

- **Vault IDs** embedded as **`[Vault:<id>]`** (**D2**) must be **ownership-checked** server-side when message is parsed — **bridge** (**TBD** handler)  
- **Custom vocabulary** (**D4**) is user-provided text — treat as sensitive preference; avoid logging raw lists (**TBD** policy)  
- **Compose bar** inherits **`01`** **`expected_role: CLIENT`** WS session — **no** second stealth socket  

---

## 13. Manual test scenarios

1. **Mic on/off** → dictation modifies `_chatController` — **`4051–4067`** / **`2922–2974`**.  
2. **Vault attach** when **`_canUseVault()`** → token appears → **send** — **`3510–3516`**, **`4068–4080`**.  
3. **Picker return** — **`3779–3783`** injects selection.  
4. **Upload** → **progress** **`4039–4044`** → completion / error dismiss.  
5. **Custom vocabulary sheet** **`3750–3754`** + **TTS** **`3755–3764`** + **Stop**.  

---

## 14. Foundational spec cross-reference

- **Shell:** §**3 row 7**  
- **WS vocabulary for turns:** §**4.B** (**`01`**)  
- **Lifecycle:** §**6** (Family nav closes socket — **`3701–3712`** — affects return to compose)  
- **Biometric cadence:** §**7**, §**3 row 8**  

---

## 15. Daily health checks

Anchors **`2200`, `2445–2455`, `2922–2974`, `3510–3516`, `3750–4080`** stable post-edit (`3663–4137` span).

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational + inventory + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/11_neural_interface_interactions.md +
_TAB_INVENTORY §D D1,D2,D3,D4,D15,D16 + §A B4-B6 + §G G5,G6,G7.
Do not duplicate 01_chat_with_nate.md nate_query / login_request tables.
Vault server contract: defer to specs 01 + 24.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
