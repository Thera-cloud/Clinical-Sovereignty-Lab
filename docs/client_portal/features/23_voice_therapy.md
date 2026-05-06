# Client Portal — Voice therapy (prepaid minutes)

> Status: `DRAFT`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **§B VOICE THERAPY** (`2609`). **Prepaid balance + Buy Voice Minutes** — `2611–2655`. Sheet — **`_showBuyVoiceMinutesSheet`** — `950` (**E9**). Gate column: **None** (inventory; contrast **TOKEN VAULT** **`!_isCoachOnly`** in spec **22**).

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 23** — **Voice therapy prefs** — `settings_screen.dart:2608+`, **REST**, balance fetch line **TBD**; state **`_voiceBalanceMinutes`** — `settings_screen.dart:242–244`.

**Plan:** `_PHASE_3_PLAN.md` **spec 23** — §3 **r23** + **E9** (`E9→23`). Prefix **23_**.

**Mental model:** **Prepaid voice-minute wallet + purchase** in **Settings** — **not** token packs (**spec 22**), **not** subscription / billing portal (**spec 21**), **not** in-chat mic dictation (**inventory §D1**).

---

## 1. Purpose (1 sentence)

In **client Settings**, show the **VOICE THERAPY** block (`2609`) with **prepaid minute balance** (`2611–2655`) and **Buy Voice Minutes** via **`_showBuyVoiceMinutesSheet`** (`950`, **E9**), backed by **REST**/**Stripe** voice-billing paths (**exact endpoints — TBD** per foundational row 23).

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §3 **row 23**, §6, §8; `_TAB_INVENTORY_2026-05-05.md` §**B** **VOICE THERAPY**, §**E** **E9**; `_PIPELINE_TEMPLATE.md` §2.

- [ ] **VOICE THERAPY** section — `2609` — layout and primary actions match inventory anchors `2611–2655`
- [ ] **Minute balance** reflects **authoritative** server / voice account after load and after purchase (**refresh behavior — TBD**)
- [ ] **Buy Voice Minutes** (**E9**) — row/surface → sheet `950` — **loading**, **cancel**, **failure**, and **success** are visible (no **`8c2a768`‑class** silent drop)
- [ ] Payment / checkout flow resolves within **30s** or offers **retry** / **support** path
- [ ] Primary purchase CTAs — touch targets ≥ **44pt**
- [ ] **Zero** balance is valid; **must** read differently from **balance fetch error** (no empty card on **401** / **5xx**)
- [ ] **`expected_role: CLIENT`** on primary app **`login_request`** where client session applies — §6
- [ ] REST calls that need **Bearer** tolerate **Redis token propagation** lag — no destructive **401→logout** loops on this surface (**trust** pattern)
- [ ] **Copy** distinguishes **voice minutes** (this spec) from **token vault** (**22**) and **subscription** (**21**)
- [ ] **`_voiceBalanceMinutes`** / sheet **in-flight** flags clear on **`dispose`**, **error**, **`finally`** — `_PIPELINE_TEMPLATE.md` §5
- [ ] **`COACH_ONLY`** routing — `main.dart:6748–6756` — if user still reaches **ClientSettingsScreen**, whether **VOICE THERAPY** remains appropriate is **TBD** (inventory gate **None**); document **hidden vs shown** once product rule is fixed

---

## 3. UI components

| Anchor | `file:line` | Purpose |
|--------|-------------|---------|
| §B VOICE THERAPY | `2609` | Section header |
| Balance + buy UI | `2611–2655` | Prepaid display + entry to purchase |
| **E9** sheet | `950` | `_showBuyVoiceMinutesSheet` |

---

## 4. Files (canonical references)

### Mobile

- `settings_screen.dart:2608+` — **Voice therapy prefs** region (foundational §3 **r23**)
- `settings_screen.dart:2609` — **VOICE THERAPY** marker (inventory)
- `settings_screen.dart:2611–2655` — balance + **Buy Voice Minutes** UI
- `settings_screen.dart:950` — **`_showBuyVoiceMinutesSheet`** (**E9**)
- `settings_screen.dart:242–244` — **`_voiceBalanceMinutes`** (foundational)

### REST / backend (workspace pointers only — no new trace)

- Voice billing / Stripe voice webhook architecture — see repo **`.cursor/rules/voice-therapy-pipeline.mdc`** and **`voice_billing_api`** / prepaid block products (**TBD** line-accurate client → API map)

### WebSocket / bridge

- **Not asserted** on this slice in foundational §3 row 23 — **assume REST-first** unless a later trace finds **`widget.socket`** Voice paths (**TBD**)

---

## 5. State variables

| Concern | Notes |
|---------|-------|
| `_voiceBalanceMinutes` | `242–244` — sync with fetched balance; avoid stale UI after purchase (**TBD** ack source) |
| Sheet + checkout in-flight | Clear on **`dispose`**, **`catch`**, **`finally`** |

---

## 6. WebSocket messages

- **None** cited for **voice therapy prefs** in foundational §3 **r23**. If settings reuses **`widget.socket`** elsewhere, any voice-specific **`_sendWs`** types are **TBD**.

---

## 7. Database tables touched

- **TBD** — voice account / session tables per **`voice-therapy-pipeline.mdc`** (**`voice_accounts`**, **`voice_sessions`**, etc.) — trace only when expanding this spec beyond inventory + foundational.

---

## 8. Edge cases

- **Offline / flaky network** — distinguish **offline** vs **Stripe** vs **API** errors
- **Purchase succeeds, balance API lags** — avoid showing **incorrect** remaining minutes (**webhook** truth — workspace Stripe voice path)
- **User confuses Settings “voice therapy” with in-chat mic / dictation** — see §18 (**§D1**)
- **`COACH_ONLY`** — see §2 last criterion

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

- ❌ **Balance** or **checkout** paths **drop** errors without UI (**`8c2a768`** class)
- ❌ **`401`** triggers **destructive logout** loops on monetized REST while Bearer is still propagating (**trust #71** analogue)
- ❌ **`UI`** shows **updated minutes** before **server** / webhook-aligned balance (**parity** with spec **22** reject pattern)

---

## 10. Known bugs

### Open

| ID | Symptom |
|----|---------|
| VT-01 | Exact **REST** URLs + line map for balance fetch (**foundational**: “**TBD** exact line”) |
| VT-02 | **`COACH_ONLY`** × **VOICE THERAPY** visibility — inventory **None** vs product intent |

---

## 11. Steve Jobs UX debt (dated)

≥3 — extend **`_FOUNDATIONAL_SPEC.md` §10** with **voice** / **dual-wallet IA**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | **Three** monetized metaphors stacked in Settings — **subscription** (**21**), **voice minutes** (**23**), **token vault** (**22**) — cognitive load | Single billing hub vs tightened section copy — **TBD** |
| 2026-05-05 | Medium | **`X-User-Id`‑style** weaker auth (**§10**) — if voice balance repeats it, inherits same review item | Bearer alignment on voice REST |
| 2026-05-05 | Medium | Balance fetch **line undocumented** (**row 23**) — maintainers lack **single anchor** | Close **VT-01** |
| 2026-05-05 | Low | Users may not link **in-app prefs** to **PSTN** voice therapy entry (**portal doc** gap vs backend voice pipeline docs) | Onboarding tooltip / FAQ — **TBD** |

---

## 12. Security boundaries

- Client sees **only** own **voice** balance / purchase state  
- Never log **raw** Stripe session / payment identifiers in client logs  
- **Admin-free** bypass (**DrNevedal1**) is **server** concern — UI must not leak other accounts (**foundational §8** spirit)

---

## 13. Manual test scenarios

1. CLIENT login → Settings → **VOICE THERAPY** **`2609`** visible  
2. Balance **`2611–2655`** matches fixture / known account (**TBD**)  
3. **Buy Voice Minutes** **`950`** — success + user cancel (**sandbox**)  
4. After purchase, balance updates without phantom minutes (**TBD** refresh rule)  
5. Airplane mode — **explicit** offline handling  
6. Compare copy vs **Buy Tokens** — no interchangeability  

---

## 14. Foundational spec cross-reference

- §3 **row 23** — Voice therapy prefs / REST / `_voiceBalanceMinutes`  
- §6 — auth lifecycle; **`expected_role`**  
- §8 — client-scoped data  

---

## 15. Daily health checks

Anchors **`2608+`, `2609`, `2611–2655`, `950`, `242–244`** unchanged after edits.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05`. **Tokens saved:** **TBD**.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/23_voice_therapy.md +
_FOUNDATIONAL_SPEC.md §3 row 23, §6, §8 +
_TAB_INVENTORY §B VOICE THERAPY, §E E9.
Trace _showBuyVoiceMinutesSheet (950) → REST + Stripe voice checkout → balance refresh.
Compare copy and gates vs spec 22 (tokens) and spec 21 (subscription).
```

---

## 18. Explicit OUT OF SCOPE

- **Token vault / pack purchase** — spec **22** (**E8** / **`787`**)  
- **Subscription / portal / payment methods** — spec **21**  
- **NeuralInterfaceV2** in-chat **mic dictation / STT buffer** — inventory **§D1** (not prepaid PSTN wallet)  
- **Twilio media stream / Grok pipeline** implementation detail — backend **`twilio_grok_xtts_pipeline`** / **`voice_billing_api`** (**reference rules only** unless a future spec folds client + server)

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
