# Client Portal — Chat with Nate (Neural chat v2)

> Status: `ACTIVE`  
> Last full review: `2026-05-05`  
> Next review due: `2026-05-12` (weekly cadence)  
> Owner: Nathan  
> Steve Jobs UX score: `needs work`

**Naming note:** Spec file prefix `01_` is documentation order; `_FOUNDATIONAL_SPEC.md` §3 inventory index for this surface is **row 7** (“Neural chat (v2)”).

---

## 1. Purpose (1 sentence)

Let the signed-in **CLIENT** converse with Little Nate over the authenticated WebSocket using `NeuralInterfaceV2`, including queries, profile/nudge/metrics refresh, optional AI modes, nudges, and export completion signaling.

---

## 2. UX acceptance criteria (client perspective)

> Grounded in `_FOUNDATIONAL_SPEC.md` §3 row 7, §4.B, §6. Reject changes that break any item without updating this spec.

- [ ] First meaningful action is reachable without hunting (coach vs client IA — no coach roster noise) — template §2
- [ ] Loading states resolve or surface a **retry** within 30s — template §2
- [ ] Errors state **what failed** and **what to do next** — template §2
- [ ] No silent empty states when the server returned an error — template §2
- [ ] Touch targets ≥ 44pt on primary CTAs — template §2
- [ ] **WebSocket:** after `login_success`, no REST calls fire before token is usable where backend expects Bearer (Redis propagation race — template §2)
- [ ] **Dual-socket flows** (schedule-from-settings via `_ClientWsHub`) do not strand the user if hub channel is null — `main.dart:10419–10454` (template §2; adjacent to chat routing in `_FOUNDATIONAL_SPEC.md` §6)
- [ ] **Family / chat transitions** that close the parent socket document reconnect UX — `updated_screens.dart:3701–3712` (user returning to chat after Family Sanctuary)
- [ ] **`login_request` on the chat socket** uses `expected_role: "CLIENT"` per bridge contract — `updated_screens.dart:1488–1493` per `_FOUNDATIONAL_SPEC.md` §4.B
- [ ] **Post-login routing:** clients who lack chat access (`can_access_nate` / `COACH_ONLY` paths) are not misled into a dead-end chat affordance — `_FOUNDATIONAL_SPEC.md` §6 point 2 (`main.dart:6748–6787` anchor) and §3 row 10/notes
- [ ] **Biometric side channel:** high-frequency `biometric_update` (2s cadence per foundational §7) must not starve the UI thread or bury chat errors — evidence `nevedal_flutter.dart:471–472`, `_FOUNDATIONAL_SPEC.md` §3 row 8  
- [ ] **Legacy vs v2:** any link or deep-link to legacy `NeuralInterface` does not confuse users with two different chat UIs — `_FOUNDATIONAL_SPEC.md` §10 (legacy vs `NeuralInterfaceV2`)

---

## 3. UI components

| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `NeuralInterfaceV2` | `updated_screens.dart:1183–1192` | Stateful chat surface | Primary v2 entry per §3 row 7 |
| `build` (main scaffold) | `updated_screens.dart:3663` | Renders chat UI | Pair with message sends in §6 |
| `NeuralInterface` (legacy) | `main.dart:1339–1348`, `build` `main.dart:1931` | Legacy chat still in tree | Do not conflate with v2 — `_FOUNDATIONAL_SPEC.md` §10 |

---

## 4. Files (canonical references)

### Mobile
- `mobile/lib/updated_screens.dart:1183–1271` — `NeuralInterfaceV2` class + representative state (`_socket`, `_chatHistory`, `_connectionStatus`, `_pendingNudges`, `_metrics` per §3 row 7)
- `mobile/lib/updated_screens.dart:1410–1493` — `initState` / `_connectToCortex` / `login_request` with `expected_role: "CLIENT"` — `updated_screens.dart:1488–1493` (`_FOUNDATIONAL_SPEC.md` §6 point 4)
- `mobile/lib/updated_screens.dart:1775–1782` — nudge dismiss / mark opened sends
- `mobile/lib/updated_screens.dart:1877–1889` — `ai_mode_activate` / `ai_mode_deactivate`
- `mobile/lib/updated_screens.dart:2145` — `get_metrics`
- `mobile/lib/updated_screens.dart:3205–3209` — `nate_query`
- `mobile/lib/updated_screens.dart:3289–3294` — `export_completed`
- `mobile/lib/updated_screens.dart:3663` — `build`
- `mobile/lib/updated_screens.dart:3701–3712` — Family Sanctuary navigation closes parent socket / reconnect — `_FOUNDATIONAL_SPEC.md` §6 point 6
- `mobile/lib/main.dart:6748–6787` — post-login CLIENT branch; `_ClientWsHub.attach` — `main.dart:6751–6752` per `_FOUNDATIONAL_SPEC.md` §6 points 1–3
- `mobile/lib/main.dart:10316–10328` — `_ClientWsHub` definition (shared authenticated channel pattern)
- `mobile/lib/nevedal_flutter.dart:444–516` — `biometric_update` timer + send path (`_FOUNDATIONAL_SPEC.md` §3 row 8, §4.B)

### Bridge (WebSocket)
- `backend/app/websocket/bridge_server.py:10914–10930` — allowlisted types including `get_metrics`, `get_history`, `get_profile`, … (`_FOUNDATIONAL_SPEC.md` §4.C)
- `backend/app/websocket/bridge_server.py:12052` — `nate_query` handler entry — §4.B
- `backend/app/websocket/bridge_server.py:14734` — `get_metrics` — §4.B
- `backend/app/websocket/bridge_server.py:14765–14768` — `get_history` requires truthy `current_profile` — §4.D (**no explicit `CLIENT` string check** in cited lines)
- `backend/app/websocket/bridge_server.py:19922–19924` — `biometric_update` → `nevedal_handler.handle_biometric_update` — §4.B
- `backend/app/websocket/bridge_server.py:25481` — `mark_onboarding_complete` (tutorial path, not core chat, but same app — §3 row 5 / §4.B)
- `backend/app/websocket/bridge_server.py:28200` — `get_pending_nudges` — §4.B

### REST (FastAPI)
- **TBD** for pure chat if additional REST-only subflows are added; AI consent is **pre-chat** gate — `ai_consent_screen.dart:55–65`, `_FOUNDATIONAL_SPEC.md` §2 table “AI consent”

### Storage
- Chat transcript persistence via **`get_history`** and bridge — `bridge_server.py:14765–14768`; underlying table(s) for history **TBD** in foundational §5 (not enumerated for this path)

---

## 5. State variables

| Variable | Type | Set at | Clear at | Default |
|----------|------|--------|----------|---------|
| `_socket` | `WebSocketChannel?` | `_connectToCortex` success — see `updated_screens.dart:1472` region in spec §4 | disconnect / `onDone` / navigate away — **TBD detail** | `null` |
| `_chatHistory` | list (message model **TBD**) | inbound WS parsing | **TBD** | `[]` |
| `_connectionStatus` | string or enum **TBD** | connect / error handlers | reconnect success / error — **TBD** | see code |
| `_pendingNudges` | list | after `get_pending_nudges` response — `updated_screens.dart:1540` | dismiss / opened handlers — `1775–1782` | `[]` |
| `_metrics` | map | after `get_metrics` — `updated_screens.dart:2145` | refresh / error — **TBD** | `{}` |

**Rule:** every loading/sending flag must clear on error, timeout, `onDone`, and `dispose` — `_PIPELINE_TEMPLATE.md` §5.

---

## 6. WebSocket messages

| Direction | Type | Flutter `file:line` | Bridge `file:line` | Notes |
|-----------|------|---------------------|---------------------|-------|
| → | `login_request` | `updated_screens.dart:1488–1493` | shared auth — **TBD** single `elif` line — §4.B | `expected_role`: `"CLIENT"` |
| → | `nate_query` | `updated_screens.dart:3205–3209` | `bridge_server.py:12052` | core chat turn |
| → | `get_profile` | `updated_screens.dart:1426`, `1764` | **TBD** | |
| → | `get_pending_nudges` | `updated_screens.dart:1540` | `bridge_server.py:28200` | |
| → | `get_metrics` | `updated_screens.dart:2145` | `bridge_server.py:14734` | |
| → | `search_consent_approved` | `updated_screens.dart:1615–1618` | **TBD** | |
| → | `ai_mode_activate` / `ai_mode_deactivate` | `updated_screens.dart:1877–1889` | **TBD** | |
| → | `export_completed` | `updated_screens.dart:3289–3294` | **TBD** | |
| → | `nudge_mark_opened` / `nudge_dismiss` | `updated_screens.dart:1775–1782` | **TBD** | |
| → | `biometric_update` | `nevedal_flutter.dart:508–516` | `bridge_server.py:19922–19924` | 2s cadence — `nevedal_flutter.dart:471–472` |
| ← | *(server responses)* | **TBD** per handler | same rows | map to `_chatHistory` / toasts — **not redocumented here** |

**Critical pairings**
- `nate_query` ↔ response handling must not leave `_connectionStatus` stuck (implementer must verify handler tree in bridge — **outside foundational scope**)
- `get_history` / profile-backed memory: `current_profile` required — `bridge_server.py:14765–14768` — log out or null profile = **TBD** UX

---

## 7. Database tables touched

- **TBD** for exact tables behind `get_history` / conversation persistence — not listed per-feature in `_FOUNDATIONAL_SPEC.md` §5 (only schedule/billing-style tables enumerated there).
- **Cross-feature hazards:** not primary for chat, but shared PG/session typing issues in §5 mismatch note if any chat code later joins `coaching_sessions`.

---

## 8. Edge cases

- **Offline / flaky network:** distinguish from server errors — template `_PIPELINE_TEMPLATE.md` §8
- **Auth lost mid-session:** `onDone` / 401 — no auto-redirect loops — template §8
- **COACH_ONLY / no chat entitlement:** post-login may route to schedule — `_FOUNDATIONAL_SPEC.md` §6 anchor `main.dart:6748–6787` — chat UI must not appear as broken if tier disallows Nate
- **AI consent not completed:** `AiConsentScreen` before chat — `main.dart:6761–6779` region per `_FOUNDATIONAL_SPEC.md` §2 table + §6
- **Navigate to Family Sanctuary:** parent chat socket closed — `updated_screens.dart:3701–3703`; reconnect on return — `3712` (`_FOUNDATIONAL_SPEC.md` §6)
- **Nevedal biometrics:** parallel high-frequency `biometric_update` on chat path — §3 row 8
- **`get_history`:** `current_profile` truthiness gate only — §4.D (**no `CLIENT` string check** in cited bridge lines)

---

## 9. Anti-patterns from git history (reject without investigation)

≥3 commits taken from `_FOUNDATIONAL_SPEC.md` §9; interpretation for **chat / shared app socket**.

| Commit | Lesson for chat |
|--------|-----------------|
| `2145c9d` | Attach post-login socket to `_ClientWsHub` — chat must not leave orphan sockets when returning from screens that reuse hub — `_FOUNDATIONAL_SPEC.md` §9 |
| `38158cc` | Shared authenticated app WebSocket — regressions in hub attach or error surfacing affect every client surface including chat |
| `d7ec21a` | Bridge WebSocket control-flow bugs — can break `nate_query` / auth routing; avoid fragile `elif` duplication |
| `8c2a768` / `c43b9a3` | Instrument **silent** failures — chat must not swallow WS errors without UI + logs |
| `ea68dd3` | Session list deduping — adjacent client schedule; chat routing sometimes shares same session object model — don’t duplicate “ghost” states in UI |

**Also reject** (from `_PIPELINE_TEMPLATE.md` §9): second WebSocket without documented lifecycle (**contrast** distress beacon row — `_FOUNDATIONAL_SPEC.md` §3 row 16); `client_*` handlers without `role == "CLIENT"` when adding new bridge branches.

---

## 10. Known bugs

### Open

| ID | Symptom | Evidence | Owner |
|----|---------|----------|-------|
| OB-CHAT-01 | Several bridge handler lines for chat-adjacent messages still **TBD** in foundational §4.B | `_FOUNDATIONAL_SPEC.md` §4.B table | TBD |

### Resolved

| Date | Commit | Bug | Fix |
|------|--------|-----|-----|
| — | — | — | *(none recorded in foundational spec)* |

---

## 11. Steve Jobs UX debt (dated)

Pull ≥3 from `_FOUNDATIONAL_SPEC.md` §10, selected for **chat adjacency**.

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-05 | High | Opening **Family Sanctuary** **closes** the primary chat socket — `updated_screens.dart:3701–3703` — reconnect latency when returning to chat | TBD |
| 2026-05-05 | Low | **Legacy `NeuralInterface`** still exists alongside **`NeuralInterfaceV2`** — `main.dart:1339` vs `updated_screens.dart:1183` — two chat codepaths confuse users if both reachable | TBD |
| 2026-05-05 | Medium | **Service worker / web quirks** for chat bootstrap **TBD** — `_FOUNDATIONAL_SPEC.md` §7 | TBD |

---

## 12. Security boundaries

- **Client sees:** own conversation context delivered by bridge for authenticated `current_profile`; metrics/nudges scoped to own session (`get_metrics` / `get_pending_nudges` sends from `updated_screens.dart` per §4).
- **Must not see:** coach roster / other clients’ clinical data — `_FOUNDATIONAL_SPEC.md` §8 (“Coach roster … `updated_screens.dart:4566+` not client default route”).
- **`get_history`:** requires truthy `current_profile` — `bridge_server.py:14765–14768`; **explicit `CLIENT` role check not in cited lines** — treat as review item when hardening.
- **`biometric_update`:** streams affect Nevedal / metrics pipelines — do not expose raw payload in logs (operational hygiene; not re-derived here).

---

## 13. Manual test scenarios

1. From **Lobby** `main.dart:7405`, complete **`login_success`** path until `NeuralInterfaceV2` or preceding gates — `_FOUNDATIONAL_SPEC.md` §6 points 1–2
2. Send a **`nate_query`** from `updated_screens.dart:3205–3209`; confirm reply populates `_chatHistory` (**expected message types TBD**)
3. Trigger **`get_metrics`** / **`get_pending_nudges`** (`2145`, `1540`); verify UI doesn’t stick loading
4. Navigate to **Family Sanctuary** and back — `updated_screens.dart:3701–3712` — confirm chat reconnect affordance
5. Background app / resume WebSocket — exercise `onDone` paths — **TBD** exact UI

---

## 14. Foundational spec cross-reference

- **Inventory row:** `_FOUNDATIONAL_SPEC.md` §3 table **row 7** (Neural chat (v2)); doc filename `01_chat_with_nate.md` maps here (not row 1 Lobby)
- **Entry / routing:** §2 table rows “Primary chat”, “Legacy chat”, “AI consent”; §6 auth lifecycle points 2, 4, 6
- **WS inventory:** §4.B (`NeuralInterfaceV2` table), §4.C allowlist, §4.D `get_history`
- **DB / schema:** §5 (schedule-heavy; chat storage **TBD**)
- **Privacy / coach vs client:** §8
- **Known debt:** §7 (biometric cadence, SW TBD), §10 Steve Jobs register

---

## 15. Daily health checks

`client_portal_daily_check.sh` — **TBD.** Manual: verify §4 file paths; grep WS error swallow patterns in `updated_screens.dart` when touching chat.

---

## 16. Investigation cache

**Last investigation:** `2026-05-05` (foundational-spec-only pass)  
**Tokens saved (estimate):** `TBD`

---

## 17. Cursor prefix

```
Read docs/client_portal/features/01_chat_with_nate.md + docs/client_portal/_FOUNDATIONAL_SPEC.md §3 row 7 + §4.B before editing NeuralInterfaceV2 or bridge chat handlers.
```

---

*Spec derived only from `docs/client_portal/_FOUNDATIONAL_SPEC.md` + `docs/client_portal/_PIPELINE_TEMPLATE.md` — 2026-05-05.*
