# Client Platform — Nevedal biometric streaming service

> Status: `DRAFT`  
> Last full review: `2026-05-06`  
> Next review due: `2026-05-13`  
> Owner: Nathan  
> Steve Jobs UX score: `not yet assessed`

**Foundational:** `_FOUNDATIONAL_SPEC.md` **§3 row 8** — **(service — no Flutter `build`)** — **`nevedal_flutter.dart:471–516`**; **`§7`** note timers — **`471–472`**; bridge dispatch — **`bridge_server.py:19922–19924`**.

**Plan:** `_PHASE_3_PLAN.md` **spec 40**. Prefix **40_**.

---

## 1. Purpose

Once **`NevedalService.initialize`** (**`459–476`**) receives the **authenticated chat `WebSocketChannel`**, a **`Timer.periodic` every 2s** (**`471–473`**) emits **`biometric_update`** payloads (**`'type': 'biometric_update'`** — **`508`**) comprising **`subject_a`/`subject_b`/`synchrony`** maps (**`411–419`**) to the bridge, which forwards **`elif t == 'biometric_update'`** (**`19922–19924`**) → **`nevedal_handler.handle_biometric_update`** (**`19924`**).

---

## 2. UX acceptance (**client-visible surface is indirect**) (**8+**)

- [ ] **Service exposes `stateStream` + `currentState`** getters — **`450–457`**
- [ ] **`BiometricCollector.getBiometricPayload()`** merges **Subjects + synchrony** — **`413–419`**
- [ ] **`initialize` stores `_socket/_sessionId/_userId`** — **`465–467`**
- [ ] **`_updateTimer`** cancel-before-reschedule avoids **duplicate timers** — **`470`** 
- [ ] **`_sendBiometricUpdate` noop** when **`socket` or `session` null** — **`505`** guard
- [ ] **`jsonEncode`** envelope includes **`ISO8601` timestamp** — **`512`** 
- [ ] **`catch` prints** biometric send errors (**`518`**) — **spec debt**: route to **`debug` logger** (**TBD**)
- [ ] **`dispose`** cancels timer + resets collector (**`523–527`**)
- [ ] **`handleServerUpdate` feeds `NevedalState`** for downstream widgets (**`488–493`**) (**UI coupling** **`NevedalStateWidget` `535`** — **TBD consumer mapping**)

---

## 3. Dart anchors

| Concern | `file:line` |
|---------|-------------|
| `BiometricCollector.getBiometricPayload` | `413–420` |
| `NevedalService.initialize` timer | `459–476` |
| `_sendBiometricUpdate` | `503–519` |
| `dispose` | `523–527` |

---

## 4. Bridge anchors

| Concern | `file:line` |
|---------|-------------|
| Dispatcher branch **`biometric_update`** | `19921–19924` |

---

## 5–7. Payload / Persistence

**Payload:**

```dart
'type': 'biometric_update'
'session_id': _sessionId
'user_id': _userId
'biometrics': _collector.getBiometricPayload()
'timestamp': DateTime.now().toIso8601String()
```
— **`508–513`** (**`503–513`** excerpt)

**PostgreSQL:**

- **`nevedal_handler.handle_biometric_update`** storage — **TBD** (**protected server file** trace deferred).

---

## 8. Edge cases

| Concern | Note |
|---------|------|
| **Frequency** (**2 Hz**) conflicts with uplink metering | foundational §**7 Nevedal biometric volume** |
| **Null `_socket`** mid-session | guarded — **`505`**, silent drop |
| **Audio feeding collector** relies on **`processClientAudio`, `processNateAudio`** — **`478–485`** (**call sites — **TBD** neural interface**) |

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

- ❌ Increase **`Timer`** frequency **without infra review** (**§7 foundational**)
- ❌ **`print`** sensitive payload contents (**sanitize** **`518`**)
- ❌ Bypass **`elif t == biometric_update`** allowlist reorder risk (**catch-all message handler**) — **`bridge_server.py` ordering** (**TBD**)

---

## 10. Known bugs

| ID | Symptom |
|----|---------|
| NB-01 | **Silent noop** when **`_socket`** null (**`505`**) — metrics blind spot |
| NB-02 | **`handleServerUpdate` catch logs `print`** only (**`498–499`**) |

---

## 11. Steve Jobs UX debt (**indirect UX**)

| Date | Severity | Friction | Target |
|------|----------|----------|--------|
| 2026-05-06 | Medium | **`NevedalStateWidget`** visualisation may **occlude chat** (**file beyond excerpt**) | compact vs immersive modes |
| 2026-05-06 | Medium | **`2s` cadence invisible** — user can't tell if **biometrics live** vs **paused** | status chip |
| 2026-05-06 | Low | Collector reset empties **`subject_*`** abruptly (**`526`**) — potential **telemetry cliffs** | soft decay animations |
| 2026-05-06 | Low | Distinction vs **`sanctuary_biometric_snapshot`** (**`bridge_server.py:19926+`**) unexplained client-side — **potential double-send risks** (**TBD** consumer audit) |

---

## 17. Cursor prefix

```
Prefix 40_. nevedal_flutter NevedalService 438–527; bridge 19921–19924.
Instrument send failures; document chat wiring from NeuralInterface*.
```

---

## 18. OUT OF SCOPE

- **`coach_live_biometric_update`** (**`bridge_server.py:18547`**, **`18678`**)
- **`sanctuary_biometric_snapshot`** (**`bridge_server.py:19926`**)
- **`11_neural_interface_interactions.md`** full chat spec

---

*`2026-05-06`*
