# Client Portal — Sovereign Vault (browse, organizer, transfer)

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Plan:** `_PHASE_3_PLAN.md` **spec 24** — **G10** (browser), **G11** (Nate Organizer), **G12** (Transfer Crystal), **E19** (transfer flow modal) — **one product**, **three Settings sub-entries** + **one overlay flow**. Prefix **24_**.

**Foundational:** Sovereign Vault UI lives under **Client settings hub** — **`_FOUNDATIONAL_SPEC.md` §3 row 11** (`settings_screen.dart:2236`, REST + optional `widget.socket`). **Not** §3 **row 24** — that row is **Check-in widget** (`checkin_screen.dart:48`).

**Inventory:** `_TAB_INVENTORY_2026-05-05.md` **§B SOVEREIGN VAULT** (`2744`) + **§H** gating + **§E E19**.

**IA note:** Coach **Folder** uploads vs client **Sovereign Vault** — related blob/R2 concepts, **distinct product names** (`_PHASE_3_PLAN.md` fold table — `09_folder.md`).

---

## 1. Purpose (1 sentence)

For **eligible clients**, surface **Sovereign Vault** inside **Settings** as **Browse** (`VaultBrowserScreen`), **Organize with Nate** (`NateOrganizerScreen`, **Sovereign Circle**), and **Transfer Crystal** (**E19** / **`_showTransferCrystalFlow`**), each **gated** independently per **inventory §H**, **without** conflating **token economy** (**spec 22**) or **chat attach / upload chrome** (**spec 11**).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 11**, §6, §8; `_TAB_INVENTORY_2026-05-05.md` §**B** SOVEREIGN VAULT, §**H**, §**E** **E19**; `_PIPELINE_TEMPLATE.md` §2.

### 2.A Product shell (`2744`)

- [ ] Section **SOVEREIGN VAULT** — `2744` — only when **`AppConfig.ENABLE_SOVEREIGN_VAULT && _hasVaultAccess`** — **`2743`** (and helper alignment **`499–502`** per **§H**)
- [ ] **Tier** truth matches **§H**: browse + transfer — **`{STANDARD, TOP_TIER, FAMILY}`**; **Organize** — **`_isSovereignCircle`** — **`2790`**, **`739–742`**
- [ ] **Hidden** state is **explainable** (feature flag off, tier lacks access) — not a blank gap with no copy (**TBD** product strings)

### 2.B **G10** — Browse Vault

- [ ] **Browse Vault** — `2778–2786` → `VaultBrowserScreen` — **loading**, **empty**, **error** states differ; no **silent empty** on **401** / **5xx**
- [ ] Navigation back to Settings restores **prior** scroll/context without stranded routes (**TBD** depth)

### 2.C **G11** — Nate Organizer

- [ ] **Organize with Nate** — `2790–2795` — **`_isSovereignCircle`** at **`2790`** — weaker tiers see **omit** or **disabled** consistent with **`739–742`** (no **dead** tap)
- [ ] REST/WS specifics **TBD** — any **`_sendWs`** / **`update_profile`** coupling follows **row 11** timeouts + **Bearer** propagation rules

### 2.D **G12** + **E19** — Transfer Crystal

- [ ] **Transfer Crystal** — `2787–2789` invokes **`_showTransferCrystalFlow`** — **E19** (inventory §E lists helper line **TBD**; §B anchors **`2787–2789`**)
- [ ] Transfer flow: **confirmation**, **recipient scope**, **failure** rollback — no **optimistic “sent”** without server ack (**TBD** contract)
- [ ] **`dispose` / cancel** clears modal + in-flight flags — `_PIPELINE_TEMPLATE.md` §5

### 2.E Cross-cutting

- [ ] **`expected_role: CLIENT`** on primary **`login_request`** — §6
- [ ] Touch targets ≥ **44pt** on primary **Browse / Organize / Transfer** entries
- [ ] **Copy** distinguishes **Sovereign Vault** (files/crystals) from **TOKEN VAULT** — **spec 22** — and from **coach Folder** — **`09_folder.md`**
- [ ] **Chat-side** vault attach / upload — **`updated_screens.dart:4068–4080`**, **`4039–4044`** — **spec 11**; this spec **does not** re-test **`nate_query`**

---

## 3. UI components (one table, tagged by gap)

| Gap | Anchor | `file:line` | Purpose |
|-----|--------|-------------|---------|
| **G10** | Browse | `2778–2786` | `VaultBrowserScreen` |
| **G12** / **E19** | Transfer | `2787–2789` | `_showTransferCrystalFlow` |
| **G11** | Organizer | `2790–2795` | `NateOrganizerScreen` (**`_isSovereignCircle`** `2790`) |
| Shell | Section | `2744` | **SOVEREIGN VAULT** header |
| Gate | Access | `2743` | `ENABLE_SOVEREIGN_VAULT && _hasVaultAccess` |

---

## 4. Files (canonical references)

### Mobile — Settings

- `settings_screen.dart:2744` — section marker  
- `settings_screen.dart:2743` — gate  
- `settings_screen.dart:499–502` — `_hasVaultAccess` alignment (**§H**)  
- `settings_screen.dart:739–742` — **`_isSovereignCircle`** (**§H**)  
- `settings_screen.dart:2778–2786` — **Browse Vault**  
- `settings_screen.dart:2787–2789` — **Transfer Crystal**  
- `settings_screen.dart:2790–2795` — **Organize with Nate**  
- `settings_screen.dart:2236` — **`ClientSettingsScreen.build`** (**row 11**)  
- `settings_screen.dart:204–214` — optional **`widget.socket`** (**row 11**)

### Mobile — Chat (cross-ref **spec 11** only)

- `updated_screens.dart:3510–3516`, `4068–4080` — attach  
- `updated_screens.dart:4039–4044` — upload progress (**D15**)

### Backend / storage

- R2 / `folder_api` / vault routers — **`TBD`** line trace; workspace **`r2-cloudflare-storage.mdc`** (**no new investigation** here)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| Browser list / selection | Cleared on **`dispose`**; no stale **`Navigator`** results (**spec 11** **D16** pattern) |
| Transfer modal (**E19**) | **`finally`** resets **in-flight** |
| Organizer | **TBD** screen-local state |

---

## 6. WebSocket messages

- **Settings** hub may use **`widget.socket`** for prefs — **`row 11`** — vault-specific **`_sendWs`** types **TBD**
- **Chat** vault paths use **authenticated** neural socket — **§4.B** (**spec 01** / **11**)

---

## 7. Database tables touched

- **TBD** — vault file metadata / crystal tables per backend (**no trace** this pass)

---

## 8. Edge cases

- **Flag off** (`ENABLE_SOVEREIGN_VAULT` false) — entire **`2744`** region omitted vs partial (**TBD** code path)
- **Tier downgrade** mid-session — user returns from **`VaultBrowserScreen`** with **revoked** access (**TBD** guard)
- **Organizer vs Browse** mismatch — user has **browse** but **not** Sovereign Circle; **Organize** row behavior (**§H**)
- **Transfer** — partial failure (**network** vs **permission**) — differentiable copy

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

- ❌ **Bypass** **`ENABLE_SOVEREIGN_VAULT`** or **`_hasVaultAccess`** / **`_isSovereignCircle`** checks to “fix” QA (**§H** regressions)
- ❌ **Transfer Crystal** (**E19**) ships with **silent** failure — **`8c2a768`** class
- ❌ **Conflate** coach **Folder** upload UX with client **Vault** routes without **explicit** IA copy (**`_PHASE_3_PLAN.md`** naming split)

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| SV-01 | **E19** table lists **`_showTransferCrystalFlow` line TBD** while §**B** cites **`2787–2789`** — reconcile helper definition vs inventory §**E** |
| SV-02 | REST contract for browse / organizer / transfer — **not** enumerated in foundational **§5** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — **§10** alignment + vault-specific **IA**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **Two “vault” words** — **TOKEN VAULT** (**22**, **economy**) vs **SOVEREIGN VAULT** (**this spec**, **files/crystals**) — users confuse **pricing** vs **library** | Glossary / section subtitles |
| 2026-05-05 | High | **G11** Organizer gated **`_isSovereignCircle`** (**`2790`**) while **G10/G12** use **`_hasVaultAccess`** — **different** bars under **one** section **`2744`** | Inline **tier key** or progressive disclosure |
| 2026-05-05 | Medium | **`widget.socket`** optional on Settings — **`204–214`** — vault flows needing **live** WS may **fight** ephemeral refresh paths (**row 11**) | Document **REST vs WS** per sub-feature (**TBD**) |
| 2026-05-05 | Low | Inventory **§E** **E19** line lag vs **§B** **`2787–2789`** — maintainer **distrust** of docs | Close **SV-01** |

---

## 12. Security boundaries

- Client sees **only** own vault objects + **approved** transfer targets (**TBD** server rules)
- **No** leaking other users’ filenames / crystal text through **browse** SSRF-style paths (**template §12** spirit)
- **Bearer** preferred over **`X-User-Id`‑only** for new vault endpoints (**§10 weekly brief** lesson)

---

## 13. Manual test scenarios

1. **Eligible** tier + flag on → **SOVEREIGN VAULT** **`2744`** shows **Browse** **`2778–2786`**
2. **Sovereign Circle** → **Organize** **`2790–2795`** reachable; non-Circle → row **hidden** or **disabled** per **`739–742`**
3. **Transfer** **`2787–2789`** — cancel + success + network fail
4. **Flag off** → section **hidden**
5. **Downgrade tier** (fixture **TBD**) → **graceful** loss of organizer / vault
6. Confirm **TOKEN VAULT** (**22**) section **different** scroll position / copy — **no merge**

---

## 14. Foundational spec cross-reference

- **§3 row 11** — Client settings hub, **`2236`**, transport, **`widget.socket`**  
- **§6** — auth lifecycle  
- **§8** — client scope; **coachFolder** analogue **not** in client roster  

---

## 15. Daily health checks

Anchors **`2743`, `2744`, `2778–2795`, `499–502`, `739–742`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/24_sovereign_vault.md +
_TAB_INVENTORY §B SOVEREIGN VAULT, §H, §E E19 +
_FOUNDATIONAL_SPEC §3 row 11 (not row 24).
Trace _hasVaultAccess (499–502, 2743) vs _isSovereignCircle (739–742, 2790).
Trace _showTransferCrystalFlow — reconcile §E TBD vs 2787–2789.
Cross-check NeuralInterfaceV2 vault attach — spec 11 only.
```

---

## 18. Explicit OUT OF SCOPE

- **Foundational §3 row 24** — **Check-in widget** (`checkin_screen.dart`) — **`36`** / intent specs  
- **Token vault / BUY tokens** economy — **`22`** (**`2660+`**)  
- **In-chat composer** vault attach / upload chrome — **`11`** (**`4068–4080`**, **`4039–4044`**)  
- Coach **Folder** product — **`09_folder.md`** (naming cousin only)

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
