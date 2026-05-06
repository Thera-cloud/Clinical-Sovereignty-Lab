# Client Portal — Onboarding trial (`OnboardingThresholdScreen`)

> Status: `DRAFT` (slide-level sends/HTTP endpoints **TBD** in foundational pass)  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Inventory mapping:** `_FOUNDATIONAL_SPEC.md` §3 **row 3**; file prefix `03_`.

---

## 1. Purpose (1 sentence)

Deliver the **Threshold / trial** walkthrough (`OnboardingThresholdScreen`) for clients after earlier login gates, using **HTTP** plus an **optional** pre-authenticated WebSocket from the constructor (`onboarding_threshold_screen.dart:19–26`), with primary UI at **`build`** — `onboarding_threshold_screen.dart:196`.

---

## 2. UX acceptance criteria (client perspective)

> Source: `_FOUNDATIONAL_SPEC.md` §2 (Trial onboarding row), §3 row 3; `_PIPELINE_TEMPLATE.md` §2.

- [ ] First meaningful action is reachable without hunting — template §2
- [ ] Loading states resolve or surface a **retry** within 30s — template §2
- [ ] Errors state **what failed** and **what to do next** — template §2
- [ ] No silent empty states when the server returned an error — template §2
- [ ] Touch targets ≥ 44pt on primary CTAs — template §2
- [ ] **WebSocket / REST timing:** no authenticated REST calls that race bridge token availability where Bearer is expected — template §2 (`_FOUNDATIONAL_SPEC.md` §6 context)
- [ ] **Optional `existingSocket`:** when a socket is passed into the ctor (`onboarding_threshold_screen.dart:19–26`), behaviour matches the **hub / chat** lifecycle — **do not** orphan or double-connect versus lobby attach pattern (`_FOUNDATIONAL_SPEC.md` §6 points 2–3) — **TBD** exact pairing until traced
- [ ] **Slide / inner UI:** WebSocket creation for per-slide builders is **TBD** — `onboarding_threshold_screen.dart:554+` per §2 table; if slides open their own sockets, document them in this spec when known
- [ ] **Design system:** token and animation state stay coherent — `onboarding_threshold_screen.dart:35–46`
- [ ] **Separation from paid path:** this feature is **row 3**; **Onboarding paid** is **row 4** (`onboarding_paid_screen.dart:149`) — do not merge specs

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `OnboardingThresholdScreen` | `onboarding_threshold_screen.dart:15–31` | Stateful trial onboarding | Class scope per §2 |
| `build` (primary scaffold) | `onboarding_threshold_screen.dart:196` | Main frame | §3 row 3 |
| Inner slide builders | **`onboarding_threshold_screen.dart:554+`** (§2) | Per-slide UI | WS **TBD** per slide — §2 |

---

## 4. Files (canonical references)

### Mobile
- `onboarding_threshold_screen.dart:15–31` — class `OnboardingThresholdScreen`
- `onboarding_threshold_screen.dart:19–26` — constructor params (**HTTP + optional `existingSocket`**)
- `onboarding_threshold_screen.dart:35–46` — design tokens + animation-related state
- `onboarding_threshold_screen.dart:196` — `build`
- `onboarding_threshold_screen.dart:554+` — inner slide builders (§2; line span **TBD** beyond `554+`)
- **TBD:** `Navigator.push` / `pushReplacement` call site from `login_success` — **not** line-cited in `_FOUNDATIONAL_SPEC.md` for this screen (§1 only says “onboarding gates” generically)

### Bridge (WebSocket)
- **TBD** — no onboarding-threshold-specific message types in foundational §4 (row 3 “Sends **TBD** (slide-level)”)

### REST (FastAPI)
- **TBD** — endpoints for Threshold onboarding not enumerated in foundational §5 for this row (HTTP transport asserted without path)

### Storage
- **TBD** — tables for `has_seen_onboarding` / trial flags not listed in foundational §5 for this feature (contrast **AI consent** row — `ai_consent_screen.dart:55–65`)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| Design / animation state | **TBD** (see §3 row 3 “Design tokens + animation state” + `onboarding_threshold_screen.dart:35–46`) | **TBD** | **TBD** | **TBD** |

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` | Notes |
|-----------|------|---------------------|----------------------|-------|
| → | **TBD** (slide-level) | **`554+` region** — **TBD** | **TBD** | §3 row 3 |
| → | *(optional ctor socket)* | `onboarding_threshold_screen.dart:19–26` | **TBD** | Reuse vs new — **TBD** |

**Contrast:** `mark_onboarding_complete` belongs to **tutorial** onboarding (`OnboardingTutorialScreen`, §3 **row 5** — `updated_screens.dart:356`), **not** row 3.

---

## 7. Database tables touched

- **TBD** — no row-3 onboarding entry in `_FOUNDATIONAL_SPEC.md` §5.

---

## 8. Edge cases

- **Optional WebSocket:** ctor allows `existingSocket` — `onboarding_threshold_screen.dart:19–26`; closing/disposal rules **TBD**
- **Slide builders `554+`:** if nested async HTTP or WS exists, failure modes **TBD**
- **Trial vs Standard / Inner / Sovereign plan parsing:** happens in post-login branch in app shell — **TBD** line in foundational (see `_FOUNDATIONAL_SPEC.md` §1 “after lobby authentication” only)
- **Offline / template edge cases:** `_PIPELINE_TEMPLATE.md` §8 when transport is fully documented

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits from `_FOUNDATIONAL_SPEC.md` §9 (shared history; apply to **any** multi-step client flow including trial onboarding).

| Commit | Lesson |
|--------|--------|
| `2145c9d` | Post-login socket / `_ClientWsHub` — trial path must not orphan the lobby socket when composing with optional `existingSocket` |
| `38158cc` | Surfacing errors instead of silent drops — slide-level **TBD** sends must not swallow failures |
| `d7ec21a` | Bridge / app control-flow fragility — gated onboarding order must stay deterministic |
| `8c2a768` / `c43b9a3` | Diagnostics for silent failure — multi-slide flows need visible stuck states |
| `ea68dd3` | De-duplication of “phantom” rows — profile/trial state shown on Threshold must stay consistent after login |

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OB-OT-01 | Slide-level outbound messages, REST paths, and DB persistence **TBD** | `_FOUNDATIONAL_SPEC.md` §3 row 3 | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | — |

---

## 11. Steve Jobs UX debt (dated)

≥3 items taken from `_FOUNDATIONAL_SPEC.md` §10 (catalog-wide; trial onboarding is one of several **post-login gates** in §1).

| Date | Severity | Friction | Applicability to trial onboarding |
|------|----------|----------|-----------------------------------|
| 2026-05-05 | Medium | **Service worker / web quirks** **TBD** — §7 | **High** for Flutter **web** first-run Threshold experience |
| 2026-05-05 | Medium | **Weekly brief** `X-User-Id` without Bearer — `settings_screen.dart:6321–6323` | **Pattern only** — if trial flow adds similar header-only calls, same risk class |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** vs **`NeuralInterfaceV2`** — `main.dart:1339` vs `updated_screens.dart:1183` | **Indirect** — many gates before stable chat shell |

---

## 12. Security boundaries

- **Threshold copy** may describe entitlements — keep aligned with server-side `subscription_plan` / tier truth (**TBD** binding — not in foundational for row 3)
- **Optional `existingSocket`:** must not leak tokens in logs — hygiene only (not expanded in foundational)
- **Coach vs client:** `OnboardingThresholdScreen` is a **client** surface per §2 table; coach-only tools remain out of scope — `_FOUNDATIONAL_SPEC.md` §8 first bullet

---

## 13. Manual test scenarios

1. Reach **Trial onboarding** after prior gates (**TBD** fixture: consent / ethics) — routing line **TBD** in foundational
2. Walk primary **Threshold** path with **HTTP-only** assumption — no unverified WS
3. If **`existingSocket` instantiated**, exercise optional socket path — `onboarding_threshold_screen.dart:19–26`
4. Deep-link / resume mid-slides — **TBD**
5. Error on HTTP failure — **TBD** endpoint

---

## 14. Foundational spec cross-reference

- **Inventory row:** §3 **row 3**
- **Entry:** §2 row “Trial onboarding”
- **Routing context:** §6 (generic `login_success` / hub; **no** Threshold-specific bullet in §6)
- **WS:** §4 (no row-3 types listed)
- **Debt / polish:** §7 (service worker), §10

---

## 15. Daily health checks

**TBD** script. Manual: confirm `onboarding_threshold_screen.dart` lines **15–31, 19–26, 35–46, 196** still valid; grep §9 anti-patterns when editing this file.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational only)  
**Tokens saved (estimate):** `TBD`

---

## 17. Cursor prefix

```
Read docs/client_portal/features/03_onboarding_trial.md + _FOUNDATIONAL_SPEC.md §3 row 3 + §2 (Trial onboarding) before editing OnboardingThresholdScreen or trial routing.
Slide-level WS/HTTP: TBD in foundational — update spec when traced.
```

---

*Spec derived only from `docs/client_portal/_FOUNDATIONAL_SPEC.md` + `docs/client_portal/_PIPELINE_TEMPLATE.md` — 2026-05-05.*
