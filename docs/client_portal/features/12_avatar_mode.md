# Client Portal — Avatar Mode (3D)

> Status: `DRAFT` (Spline / iframe load-failure copy **TBD**)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_TAB_INVENTORY_2026-05-05.md` **G1**, **§D D6**, **§A row 1** (`face` AppBar action); **§H** (Avatar Mode gating). `_PHASE_3_PLAN.md` **spec 12**. Complements **`NeuralInterfaceV2`** shell — `_FOUNDATIONAL_SPEC.md` §**3 row 7**. Prefix **`12_`**.

---

## 1. Purpose (1 sentence)

On **`NeuralInterfaceV2`**, expose an optional **Avatar Mode** toggle (**`updated_screens.dart:3688–3696`**) backed by **Spline / 3D iframe** semantics (**inventory D6**), gated by **`premium_features.avatar`** or tier **`TOP_TIER` / `SOVEREIGN_CIRCLE`** — **`3494–3507`** (**§H**), with **`_toggleAvatarMode`** at **`3519`**.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_TAB_INVENTORY_2026-05-05.md` §**A row 1**, **D6**, **§H**; `_FOUNDATIONAL_SPEC.md` §**3 row 7**, §**7** (web); `_PIPELINE_TEMPLATE.md` §2.

- [ ] **Gating:** Avatar affordance only when **`_canUseAvatarMode()`** true — **`3494–3507`** matches **`§H`** (**`premium_features.avatar == true`** **OR** tier ∈ **`{TOP_TIER, SOVEREIGN_CIRCLE}`**)  
- [ ] **Discoverability:** **`face`** icon path — **`3688–3696`** — no “phantom” toggle for ineligible users (**TBD** hide vs disabled UX)  
- [ ] **Toggle:** **`_toggleAvatarMode`** **`3519`** persists expected on/off state (**TBD** server sync)  
- [ ] **3D / iframe:** latency, memory, and failure states surface **non-silent** UX (**TBD** copy) — inventory flags **3D iframe**  
- [ ] **Contrast non-avatar chat:** core **`build`** **`3663`** remains usable with avatar off — **`01`**  
- [ ] **Tier drift:** admin changes tier / `premium_features` mid-session → UI reconciles without crash (**TBD**)  
- [ ] **`COACH_ONLY` / no chat:** users on **`ClientScheduleScreen`** — **`6755–6759`** — never see this control (**TBD** assert)  
- [ ] **Web / Safari:** iframe + service-worker stack — align with workspace **SW** guidance + foundational §**7** **TBD**  
- [ ] Touch targets ≥ **44pt** on **`3688–3696`** control — template  
- [ ] **Billing truth:** if user paid for tier that should unlock avatar, **`3494–3507`** and profile JSON stay consistent — cross-ref spec **21** (**TBD**)  

---

## 3. UI components

| Inventory | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| **§A row 1** | **`3688–3696`** | AppBar **Avatar Mode** toggle | `face` icon |
| **D6** | **`3494`** (`_canUseAvatarMode`); **`3519`** (`_toggleAvatarMode`) | Eligibility + toggle | **Spline** 3D |
| **Gate** | **`3494–3507`** | **`§H`** predicate | `premium_features` **OR** tier set |

---

## 4. Files (canonical references)

### Mobile
- `updated_screens.dart:3494–3507` — **`_canUseAvatarMode`** + **§H** mirror  
- `updated_screens.dart:3519` — **`_toggleAvatarMode`**  
- `updated_screens.dart:3688–3696` — AppBar **Avatar Mode** UI (**§A row 1**)  
- `updated_screens.dart:3663` — **`NeuralInterfaceV2`** scaffold (**§3 row 7**)

### Bridge / REST / Storage

- **TBD** — no dedicated **`avatar_*`** WS row in foundational §**4**; profile / `premium_features` likely via **`get_profile`** / settings — **`01`** / **17**

---

## 5. State variables

| Concern | Location | Notes |
|---------|----------|-------|
| Avatar on/off | **`3519`** + **TBD** fields | Persist **TBD** |
| Eligibility cache | **`3494–3507`** | Must track profile/tier freshness **TBD** |

---

## 6. WebSocket messages

| Relation | Types | Notes |
|----------|-------|-------|
| **Indirect** | `get_profile` — **`updated_screens.dart:1426`**, **`1764`** (**`01`** §4.B) | **TBD** if avatar flag travels in profile payload |
| **Not enumerated** | *none specific* | foundational pass has **no** `avatar_*` bridge row |

---

## 7. Database tables touched

- **TBD** — `premium_features` / tier columns on **`users`**.**`profile_data`** (typical pattern; **not** cited in foundational §**5** for this sub-feature)

---

## 8. Edge cases

- **Downgrade:** tier drops below **`SOVEREIGN_CIRCLE` / `TOP_TIER`** and **`premium_features.avatar`** false → **force-off** (**TBD**)  
- **`kIsWeb`:** iframe performance / keyboard focus — **TBD**  
- **Family Sanctuary / socket teardown:** **`3701–3712`** — avatar state vs reconnect — **TBD**  

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

**Reject:** showing **3D iframe** when **`3494–3507`** is false; duplicating tier logic in a second file without **`§H`** single source; testing only on **legacy** **`NeuralInterface`** (**`main.dart:1931`**).

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence |
|----|---------|----------|
| AV-01 | Iframe failure / blank avatar — user messaging | **TBD** |

---

## 11. Steve Jobs UX debt (dated)

≥3 — `_FOUNDATIONAL_SPEC.md` §**10** + **`§H`** relevance.

| Date | Severity | Friction | Applicability |
|------|----------|----------|----------------|
| 2026-05-05 | Medium | **`NeuralInterface`** vs **`NeuralInterfaceV2`** dual tree — **`main.dart:1339`** vs **`1183`** | Avatar QA on wrong class |
| 2026-05-05 | Medium | **`premium_features`** JSON vs **tier** string — **`3494–3507`** (**§H**) | Two inputs → entitlement bugs if one lags Stripe (**spec 21**) |
| 2026-05-05 | Low | **Service worker / web** — §**7** **TBD** | Heavy iframe + SW cache = stale or blank **TBD** |
| 2026-05-05 | Low | **Biometric 2s** traffic — **`nevedal_flutter.dart:471–472`** | Same scaffold as 3D — CPU contention on low-end devices |

---

## 12. Security boundaries

- **3D asset URL** (Spline) must be **allowlisted** / **HTTPS** — **TBD** implementation audit  
- **No PII** in avatar session telemetry without consent — **TBD**  
- **Gating** must be **server-authoritative** on features that cost money — client **`3494–3507`** is **UX only**; backend must enforce on any future **`avatar_*`** APIs (**TBD**)  

---

## 13. Manual test scenarios

1. **Eligible** user — toggle **`3688–3696`** → **3D** visible → **`3519`** off → plain chat.  
2. **Ineligible** user — **`3494–3507`** false → no **`face`** / disabled (**TBD**).  
3. **Web** + **Safari** — cold load + toggle (**TBD**).  
4. **Tier change** (fixture) — mid-session revoke → UI safe.  
5. **Schedule-only** client — **`6755–6759`** — no avatar path.  

---

## 14. Foundational spec cross-reference

- **Parent surface:** §**3 row 7** (`NeuralInterfaceV2`)  
- **Lifecycle / nav:** §**6** (Family nav **TBD** interaction)  
- **Privacy:** §**8** (generic; avatar **TBD** extension)  

---

## 15. Daily health checks

Anchors **`3494–3507`**, **`3519`**, **`3688–3696`** stable post-edit.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (inventory + foundational + phase plan only). **Tokens saved:** `TBD`.

---

## 17. Cursor prefix

```
Read docs/client_portal/features/12_avatar_mode.md +
_TAB_INVENTORY §A row 1, §D D6, §G G1, §H Avatar Mode row.
Complements 01_chat_with_nate.md (shell); do not restate nate_query.
```

---

*Spec from `_FOUNDATIONAL_SPEC.md`, `_TAB_INVENTORY_2026-05-05.md`, `_PHASE_3_PLAN.md`, `_PIPELINE_TEMPLATE.md` — 2026-05-05.*
