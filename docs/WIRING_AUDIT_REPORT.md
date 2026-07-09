# WIRING_AUDIT_REPORT.md

**Audit date:** 2026-07-08  
**Scope:** ACTION TAKEN → WHAT HAPPENED NEXT → ADJUST MEMORY WEIGHTS OR BEHAVIOR  
**Excluded:** `public_trial` paths  
**Mode:** Read-only — no fixes, no proposals

---

## Executive verdict

**The loop is not wired end-to-end anywhere** for chat memory, crystal attribution, coherence outcomes, or counterfactual conclusions; one narrow **check-in snooze** sub-loop is **WIRED** (SMS reply → `checkin_snooze_until` → outreach suppression).

---

## Classification legend

| Class | Meaning |
|---|---|
| **WIRED** | Persisted write at file:line + consumer at file:line that changes weight, schedule, prompt, or behavior |
| **NOT_RECORDED** | No durable write of the signal |
| **RECORDED_NEVER_READ** | Durable write exists; no reader changes behavior from it |
| **READ_NO_EFFECT** | Reader exists; does not change weight/schedule/prompt/behavior on audited dimensions |
| **KEY_MISMATCH** | Write and read exist but identity keys differ (join fails silently) |
| **WIRED_BUT_OFF** | Both endpoints exist; gated off in production defaults |
| **DEAD_CODE** | Implementation exists; no production caller |

---

## Matrix (zero empty cells)

| ID | Edge | Action recorded | Outcome recorded | Adaptation | Class |
|---|---|---|---|---|---|
| A1 | Chat turn → injected `crystal_ids` on `conversation_history` | Chat INSERT | — | — | **NOT_RECORDED** |
| A2 | Chat turn → enrichment audit crystal attribution | JSONL `crystal_chars` count only | — | — | **NOT_RECORDED** |
| A3 | `nate_checkins` outreach actions | INSERT per send | status/snooze/responded | snooze → outreach skip (C9) | **WIRED** (snooze branch only) |
| A4 | `nate_nudges` proactive actions | INSERT pending | opened/dismissed UPDATE | — | **RECORDED_NEVER_READ** |
| A5 | `sensitive_bridge_log` clinical events | INSERT append-only | — | — | **RECORDED_NEVER_READ** |
| B1 | Text-chat CEE → `nevedal_metrics` | INSERT `c_emo` per CEE | — | — | **RECORDED_NEVER_READ** |
| B2 | Voice/session CEE → `nevedal_metrics` | INSERT via handlers | — | — | **RECORDED_NEVER_READ** |
| B3 | Check-in SMS reply (non-snooze) → `responded` | — | UPDATE `responded` | — | **RECORDED_NEVER_READ** |
| B4 | Check-in SMS snooze → profile + checkin row | — | `checkin_snooze_until` + `snoozed` | outreach skip | **WIRED** |
| B5 | Nudge tap / dismiss | — | `opened` / `dismissed` | — | **RECORDED_NEVER_READ** |
| B6 | Counterfactual engine conclusions | WS compute only | — | — | **NOT_RECORDED** |
| B7 | Crystal recall Layer-8 validation per crystal | — | — | in-prompt filter only | **READ_NO_EFFECT** |
| B8 | `crystal_recall_log` per recall | INSERT on recall | — | see C1/C5 | **RECORDED_NEVER_READ** (alone) |
| B9 | SSE panel engagement → `tmc_training_data` | — | `actual_engagement` INSERT | — | **RECORDED_NEVER_READ** |
| C1 | Recall → crystal `confidence` / `recall_count` (bridge path) | same-event recall | — | confidence +0.03 | **READ_NO_EFFECT**† |
| C2 | `NateMemoryCrystallizer.record_recall(odpe_signal)` | — | — | confidence by ODPE | **DEAD_CODE** |
| C3 | Decay cycle → archive by `recall_count` + age | recall_count writes | time elapsed | `scope='archived'` | **WIRED**‡ |
| C4 | Six-Quotient `assess_interaction` → growth crystals | same-turn heuristic | same-turn | new global crystals | **READ_NO_EFFECT**§ |
| C5 | `TimeCrystalForge` ← `crystal_recall_log` | recall log | co-activation patterns | `coherence_time_crystals` | **WIRED_BUT_OFF** |
| C6 | `QuantumCrystalOrchestrator.recall` reinforcement | orchestrator recall | — | confidence bump | **WIRED_BUT_OFF** |
| C7 | `AutonomousController` learn cycle | health-gate timer | — | crystallize/maintain | **WIRED_BUT_OFF** |
| C8 | `crystal_factory` harvest | heartbeat/watermark | — | external ingest | **READ_NO_EFFECT** |
| C9 | `NateCheckInAgent` cadence from outcomes | fixed 62h/72h constants | snooze read | skip outreach window | **WIRED** (snooze only) |
| C10 | `DeadmanSwitch` ← `nate_nudges.opened_at` | — | MAX(opened_at) read | new `deadman_alert` nudge | **READ_NO_EFFECT** |
| C11 | TMC trained model → classification | `tmc_training_data` | engagement rows | — | **RECORDED_NEVER_READ** |
| C12 | `wisdom_lifecycle` auto-absorb | pending extractions | confidence+age | absorb to wisdom | **READ_NO_EFFECT** |
| C13 | `BRIDGE_VALIDATOR_FILTER_RECALL` | — | — | filter at recall | **WIRED_BUT_OFF** |
| C14 | Counterfactual output terminus | WS `member_removal_scenario` | dashboard render | — | **NOT_RECORDED** |

† Same-event reinforcement; no separate “what happened next” outcome signal.  
‡ Outcome is calendar time + recall frequency, not user response.  
§ Adaptation uses same-turn text heuristics, not a delayed outcome.

---

## Per-edge evidence

### A1 — Chat `crystal_ids` not on `conversation_history`

**Write (chat only `turn_id` in metadata):**

```7574:7593:backend/app/websocket/bridge_server.py
async def _persist_chat_to_conversation_history(
    db_pool, username: str, user_text: str, ai_text: str, session_id: str = "",
    turn_id: str = "",
):
    ...
        _meta = json.dumps({"turn_id": turn_id}) if turn_id else "{}"
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversation_history "
                "(user_id, user_text, ai_text, session_id, metadata, created_at) "
                ...
                username,
```

**Recall fires reinforcement but does not attach IDs to history:**

```438:441:backend/app/websocket/crystal_recall_bridge.py
        crystal_ids = [c["id"] for c in crystals]

        import asyncio as _aio
        _aio.create_task(_reinforce_recalled_crystals(db_pool, hardware_id, crystal_ids, source))
```

**Class:** NOT_RECORDED

---

### A2 — Enrichment audit (no crystal IDs)

```614:638:backend/app/websocket/bridge_enrichment.py
def log_turn_audit(
    ...
    crystal_chars: int = 0,
    ...
    row = {
        ...
        "crystal_chars": crystal_chars,
```

Called from `process_interaction` with char count only (`bridge_server.py` 10642–10646). No reader consumes JSONL for weight changes.

**Class:** NOT_RECORDED (for crystal ID attribution)

---

### A3 / B4 / C9 — `nate_checkins` + snooze loop (**WIRED**)

**Action write:**

```825:833:backend/app/services/nate_checkin_agent.py
    async def _record_checkin(self, conn, username: str, role: str, checkin_type: str,
                              channel: Optional[str], content: str,
                              metadata: Optional[dict] = None):
        async with self.db_pool.acquire() as c:
            await c.execute("""
                INSERT INTO nate_checkins (user_id, role, checkin_type, channel, content, metadata)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, username, role, checkin_type, channel, content,
```

Schema (`077_nate_checkin.sql`): `user_id VARCHAR(64)` = **username**; `status` ∈ `sent|responded|snoozed|expired`.

**Outcome write (SMS snooze):**

```167:180:backend/app/routers/twilio_webhook.py
                        await conn.execute(
                            """UPDATE users SET profile_data = jsonb_set(
                                COALESCE(profile_data, '{}'::jsonb),
                                '{checkin_snooze_until}', to_jsonb($1::text)
                            ) WHERE username = $2""",
                            snooze_until.isoformat(), user_row["username"],
                        )
                        await conn.execute(
                            """UPDATE nate_checkins SET status = 'snoozed',
                                snooze_days = $1, snooze_until = $2, responded_at = NOW()
                            WHERE user_id = $3 AND status = 'sent'
```

**Adaptation read (suppress outreach):**

```258:265:backend/app/services/nate_checkin_agent.py
                snooze_until = profile.get("checkin_snooze_until")
                if snooze_until:
                    try:
                        snooze_dt = datetime.fromisoformat(snooze_until.replace("Z", "+00:00"))
                        ...
                        if now < snooze_dt:
                            continue
```

**Class:** WIRED for snooze→cadence suppression only. `responded` status is never read for cadence (`_recent_checkin` filters `status IN ('sent','snoozed')` only — lines 813–822).

---

### A4 / B5 — `nate_nudges`

**Schema:** `user_id UUID` → `users(id)` (`015_nate_nudges_wisdom_profiles.sql` lines 8–10).

**Action write:** `NateCheckInAgent._create_nudge` (`nate_checkin_agent.py` 835–845) resolves UUID from `hardware_id`.

**Outcome write:**

```311:324:backend/app/services/nate_nudge.py
    async def mark_opened(self, nudge_id: UUID) -> None:
        ...
            await conn.execute(
                "UPDATE nate_nudges SET status = 'opened', opened_at = NOW() WHERE id = $1",
                nudge_id,
            )

    async def dismiss(self, nudge_id: UUID) -> None:
        ...
            await conn.execute(
                "UPDATE nate_nudges SET status = 'dismissed' WHERE id = $1",
```

Handlers: `bridge_server.py` 30313–30344 (`nudge_mark_opened`, `nudge_dismiss`).

No code modulates `POLL_INTERVAL_SECONDS` (1800), `CLIENT_OUTREACH_HOURS` (72), or crystal weights from `opened_at`/`dismissed`.

**Class:** RECORDED_NEVER_READ (for adaptation)

---

### A5 — `sensitive_bridge_log`

**Schema:** `user_id TEXT REFERENCES users(username)` (`202_sensitive_clinical_bridge_core.sql` 49–51).

**Example write (check-in codeword):**

```1313:1327:backend/app/services/nate_checkin_agent.py
                await c.execute(
                    """
                    INSERT INTO sensitive_bridge_log
                        (user_id, session_id, event_type, event_severity,
                         payload_json, recorded_by, access_classification,
                         pii_screened_at)
                    VALUES ($1, $2, $3, $4, $5, 'nate_checkin_agent',
```

Readers: `sensitive_profile_api.py` (read-only audit window), `suicide_ideation_coach_alert.py` (recent event lookup for dedup). No reader adjusts crystal confidence, check-in schedule, or chat prompts from historical log rows.

**Class:** RECORDED_NEVER_READ

---

### B1 — `nevedal_metrics` (C_emo)

**Write (text chat CEE):**

```5458:5464:backend/app/websocket/bridge_server.py
                await conn.execute("""
                    INSERT INTO nevedal_metrics (
                        session_id, user_id, dyad_partner_id, recorded_at,
                        c_emo, p_ent, t_tunnel, gamma_env, e_g_joint,
                        cee_window, cee_duration_seconds
                    ) VALUES (NULL, $1, NULL, $2, $3, 0, 0, 0, 0, TRUE, 0)
                """, user_uuid, datetime.datetime.fromisoformat(timestamp_str), c_emo)
```

`user_id` resolved to **UUID** (`5452–5454`). Granularity: per CEE window event.

Consumers (`thera_world_engine.py`, `marketing_brain.py`, dashboards) read for display/SSE context — no path feeds C_emo back into `process_interaction` crystal weights or `NateCheckInAgent` intervals.

**Class:** RECORDED_NEVER_READ (for adaptation)

---

### B3 — Check-in `responded` (non-snooze)

```246:294:backend/app/routers/twilio_webhook.py
                                   SET status = 'responded', responded_at = NOW()
...
                                UPDATE nate_checkins SET status = 'responded', responded_at = NOW()
```

No reader uses `responded` or `responded_at` to change cadence or memory.

**Class:** RECORDED_NEVER_READ

---

### B6 / C14 — Counterfactual engine

**Compute + ephemeral send (no INSERT):**

```23977:23985:backend/app/websocket/bridge_server.py
            elif t == "admin_member_removal_scenario":
                if current_profile and current_profile.get("role") == "ADMIN":
                    ...
                    _rm_empty = {"type": "member_removal_scenario", ...
```

Handler ends in `await websocket.send(json.dumps(...))` (`~24220`). Dashboard renders in `nevedal_lab_family.html` — no persistence table.

**Class:** NOT_RECORDED

---

### B7 — Crystal recall validation persistence

**Filter at recall (no validation row):**

```795:828:backend/app/services/nate_response_validator.py
    def filter_recalled_crystals(cls, crystals: list) -> list:
        ...
            if not flagged:
                clean.append(crystal)
        return clean
```

Invoked when `BRIDGE_VALIDATOR_FILTER_RECALL` env true (`crystal_recall_bridge.py` 84, 420–432). Excludes crystals from prompt; does not persist per-crystal validation outcome.

**Class:** READ_NO_EFFECT (no durable validation log; no weight change from outcome)

---

### B8 / C1 — `crystal_recall_log` + bridge reinforcement

**Write:**

```485:494:backend/app/websocket/crystal_recall_bridge.py
            await conn.executemany(
                "INSERT INTO crystal_recall_log (user_id, crystal_id, source, recalled_at) VALUES ($1, $2, $3, NOW())",
                [(hardware_id, cid, source) for cid in crystal_ids],
            )
            await conn.execute(
                "UPDATE nate_intelligence_crystals SET recall_count = COALESCE(recall_count, 0) + 1, "
                "last_recalled_at = NOW(), confidence = GREATEST(confidence, LEAST(confidence + 0.03, 0.95)), "
```

`crystal_recall_log.user_id` = **hardware_id** (TEXT, migration 154 line 36).

Reinforcement is **same event** as recall injection — not a downstream outcome.

**Class:** C1 = READ_NO_EFFECT on full loop; B8 alone = RECORDED_NEVER_READ until C3/C5

---

### C2 — `record_recall(odpe_signal)` 

```2214:2268:backend/app/services/nate_memory_crystallizer.py
    async def record_recall(self, crystal_id: int, odpe_signal: Optional[str] = None, face_path: Optional[str] = None):
```

**Production callers:** `grep '\.record_recall\(' backend/app/**/*.py` → **zero matches** (tests only: `test_crystal_promotion_paths.py`, `_live_cap_test.py`).

**Class:** DEAD_CODE (production)

---

### C3 — Decay cycle (**WIRED**‡)

**Read:**

```2128:2138:backend/app/services/nate_memory_crystallizer.py
            decay_cutoff = now - timedelta(days=DECAY_THRESHOLD_DAYS)
            archived = await conn.execute(f"""
                UPDATE nate_intelligence_crystals
                SET scope = 'archived'
                WHERE superseded_by IS NULL
                  AND recall_count < $1
                  AND (last_recalled_at IS NULL OR last_recalled_at < $2)
```

**Write input:** `recall_count` / `last_recalled_at` from C1 reinforcement.

Outcome signal = elapsed time + low recall frequency, not user response quality.

**Class:** WIRED (recall-frequency → archive)

---

### C4 — Six-Quotient growth engine

**Same-turn write:**

```10630:10634:backend/app/websocket/bridge_server.py
                if _six_quotient_growth:
                    asyncio.create_task(_six_quotient_growth.assess_interaction(
                        user_text, _final_response, uid,
```

`uid` = `profile.hardware_id` (`8815`). Inserts `six_quotient_growth` (`six_quotient_growth_engine.py` 237–251).

**Delayed read (6h cycle):**

```385:391:backend/app/services/six_quotient_growth_engine.py
                rows = await conn.fetch(
                    """SELECT quotients_exercised, quality_positive, quality_negative,
                              growth_score, created_at
                       FROM six_quotient_growth
                       WHERE created_at > NOW() - INTERVAL '24 hours'
```

Synthesis forges new global clinical crystals from aggregated **same-turn** heuristics — not from a separate outcome channel.

**Class:** READ_NO_EFFECT (on action→outcome→adapt loop definition)

---

### C5 / C6 — Quantum crystal orchestrator (**WIRED_BUT_OFF**)

**Defaults:**

```193:197:backend/app/config/_settings.py
    ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR: bool = False
    ...
    ENABLE_TIME_CRYSTAL_FORGE: bool = False
    ...
    ENABLE_CRYSTAL_GRAPH: bool = False
```

**Init gated:**

```2844:2851:backend/app/main.py
    if getattr(settings, "ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR", True):
        ...
            if getattr(settings, "ENABLE_TIME_CRYSTAL_FORGE", True):
                await _quantum_orchestrator.start_forge_scheduler()
```

`getattr(settings, ...)` returns **False** from `_settings.py`; orchestrator not started; service check passes when disabled (`main.py` 3113).

**When on — recall reinforcement write+read:**

```315:322:backend/app/services/quantum_crystal_orchestrator.py
        await self.reinforce_and_log_recall_hits(
            ranked,
            user_id=user_id,
            source=source,
            ...
        )
```

`littlenate_inference._retrieve_crystals` calls orchestrator when present (`littlenate_inference.py` 281–286). Main bridge chat uses `crystal_recall_bridge`, not this path.

**Time forge read:**

```74:82:backend/app/services/time_crystal_forge.py
            rows = await conn.fetch(
                """
                SELECT crystal_hash, crystal_id, recalled_at, session_id, call_sid
                FROM crystal_recall_log
                WHERE user_id = $1
```

**Class:** WIRED_BUT_OFF (`ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR=false`, `ENABLE_TIME_CRYSTAL_FORGE=false`)

---

### C7 — AutonomousController (**WIRED_BUT_OFF**)

```31814:31846:backend/app/websocket/bridge_server.py
    if _AUTONOMOUS_AVAILABLE and os.environ.get("ENABLE_AUTONOMOUS", "false").lower() == "true":
        ...
            asyncio.create_task(_autonomous_controller.run())
    else:
        ...
            print(">>> [AUTONOMOUS] Disabled (set ENABLE_AUTONOMOUS=true to activate)")
```

Learn cycle (`autonomous_controller.py` 384+) crystallizes from harvest buffer on timer/health gates — not from user outcome tables.

**Class:** WIRED_BUT_OFF (`ENABLE_AUTONOMOUS` default `false`)

---

### C8 — `crystal_factory`

External harvest script (`backend/crystal_factory.py`); heartbeats via `nate_agent_api.py` 3196+. No consumption of check-in, nudge, C_emo, or chat outcome signals.

**Class:** READ_NO_EFFECT (on clinical adaptation loop)

---

### C10 — DeadmanSwitch ← nudge opens

**Read:**

```108:110:backend/app/services/deadman_switch.py
                last_nudge_open = await conn.fetchval(
                    "SELECT MAX(opened_at) FROM nate_nudges WHERE user_id = $1",
                    user_id,
```

`user_id` here is **UUID** (client loop uses `users.id`). Effect: may INSERT `deadman_alert` nudge — does not change `NateCheckInAgent` constants or crystal confidence.

**Class:** READ_NO_EFFECT (on audited adaptation dimensions)

---

### C11 — TMC training loop

**Outcome write:**

```31:59:backend/app/sse/ucd/tmc_trainer.py
async def record_training_sample(
    ...
        await conn.execute(
            "INSERT INTO tmc_training_data "
            "(sample_id, user_id, input_signals, classified_moment, "
            "actual_engagement, generation_id, crystal_response_ids, model_version) "
```

Triggered from `admin.py` 6256–6267 on engagement POST.

**Train endpoint exists:** `admin.py` 6333 → `train_tmc_model`. **No `load_trained_tmc` function** in codebase (`grep` zero). `temporal_orchestrator.py` 32 uses `TherapeuticMomentClassifier` rule engine only.

**Class:** RECORDED_NEVER_READ

---

### C13 — Validator filter recall (**WIRED_BUT_OFF**)

```84:84:backend/app/websocket/crystal_recall_bridge.py
_VALIDATOR_FILTER_RECALL = (_os.getenv("BRIDGE_VALIDATOR_FILTER_RECALL", "") or "").strip().lower() in ("1", "true", "yes", "on")
```

When off (default), filter skipped. When on: recall-time prompt exclusion only — no confidence update.

**Class:** WIRED_BUT_OFF (default off; effect is prompt filter not weight)

---

## Key-mismatch register

| Writer store | Writer key | Reader store / code | Reader key | Resolver | Join result |
|---|---|---|---|---|---|
| `crystal_recall_log` | `hardware_id` TEXT | `TimeCrystalForge._get_recall_history` | same TEXT column | none | OK if forge enabled |
| `crystal_recall_log` | `hardware_id` | `conversation_history` | `username` | `_fetch_pg_history` uses both in array (`7605–7607`) | Partial — dual lookup |
| `nate_checkins` | `username` | `DeadmanSwitch` | UUID `users.id` | different tables/keys | **KEY_MISMATCH** across subsystems |
| `nate_nudges` | UUID | `NateCheckInAgent._create_nudge` | resolves HW→UUID | inline SELECT | OK within nudge path |
| `nevedal_metrics` | UUID | `conversation_history` | username | separate surfaces | **KEY_MISMATCH** for unified outcome loop |
| `sensitive_bridge_log` | `username` FK | chat `therapeutic_controller` | `resolve_username()` at boundary | `_identity_resolver.py` 15–28 | OK when resolver used |
| `six_quotient_growth` | `hardware_id` (`uid` 8815) | no cross-user outcome reader | — | — | Isolated |

**Existing resolver path:**

```15:28:backend/app/services/_identity_resolver.py
async def resolve_username(db_pool: Any, identifier: str) -> Optional[str]:
    ...
            row = await conn.fetchrow(
                "SELECT username FROM users WHERE username = $1 "
                "OR hardware_id = $1 OR id::text = $1 LIMIT 1",
                identifier,
            )
```

Used at Sensitive Bridge boundary (`sensitive-bridge-identity-canonical` rule). **Not** applied on `crystal_recall_log` ↔ `conversation_history` ↔ `nevedal_metrics` unified adaptation edges.

---

## Adaptation path inventory (crystal confidence / tier)

| Path | Input signal | Effect | Production active | Class |
|---|---|---|---|---|
| `_reinforce_recalled_crystals` | recall event (injection) | confidence +0.03, recall_count++ | Yes (bridge chat) | Same-event only |
| `QuantumCrystalOrchestrator.reinforce_and_log_recall_hits` | orchestrator recall | confidence increment | No (flag off) | WIRED_BUT_OFF |
| `littlenate_inference` fallback UPDATE | Vectorize hit | confidence increment | If inference path used | Partial |
| `NateMemoryCrystallizer.record_recall` | odpe_signal | confidence / needs_reeval | No callers | DEAD_CODE |
| `_decay_cycle` | recall_count, last_recalled_at, age | archive scope | Yes (background) | WIRED‡ |
| `_warm_cold_crystals` | conversation_history keywords | recall_count++ once | Yes (6h) | KEY_MISMATCH risk (history=username) |
| Six-Quotient `_crystallize_lesson` | same-turn anti_patterns | new global crystal | Yes | Same-turn |
| `wisdom_lifecycle.auto_absorb` | extraction confidence+age | wisdom absorb | Yes (check-in cycle hook) | Not outcome-based |
| PG trigger `prevent_crystal_confidence_decay` | — | blocks confidence **decrease** | Yes (migration 154) | Constraint only |

No path reads chat outcome quality, nudge engagement, or post-hoc C_emo delta to adjust per-crystal confidence on the originating action.

---

## Autonomous / factory triggers

| Component | Trigger | Input signals | Class |
|---|---|---|---|
| `AutonomousController.run()` | `ENABLE_AUTONOMOUS=true` + health gates | harvest buffer, disk, PG health | WIRED_BUT_OFF |
| `NateMemoryCrystallizer._run_loop` | 30 min timer | harvest buffer fragments | Infra — not outcome-driven |
| `crystal_factory` | external cron / systemd on Hetzner | R2/HTTP harvest | READ_NO_EFFECT |
| `NateCheckInAgent._run_loop` | 1800s `POLL_INTERVAL_SECONDS` | `last_activity_at`, `checkin_snooze_until` | Fixed thresholds + snooze WIRED |
| `QuantumCrystalOrchestrator` forge scheduler | flag on | `crystal_recall_log` | WIRED_BUT_OFF |

---

## Three nearest-misses

Both endpoints exist; only the connecting read (or persistence) is missing.

### 1. `nate_nudges.opened_at` → cadence / memory weights

- **Write:** `nate_nudge.py` 311–316 (`mark_opened`)
- **Read exists:** `deadman_switch.py` 108–127 (silence detection only)
- **Missing:** `NateCheckInAgent` does not read `opened_at`/`dismissed`; constants at lines 58–64 unchanged

### 2. `tmc_training_data.actual_engagement` → moment classification

- **Write:** `tmc_trainer.py` 47–58 via `admin.py` 6261–6267
- **Train exists:** `train_tmc_model` (`tmc_trainer.py` 77+), admin endpoint 6333
- **Missing:** `load_trained_tmc` undefined; `TherapeuticMomentClassifier` never calls `classify_with_model`

### 3. `crystal_recall_log` → time-crystal prompt biasing (bridge chat)

- **Write:** `crystal_recall_bridge.py` 485–488
- **Read exists:** `time_crystal_forge.py` 74–82; orchestrator `get_time_crystal_context` when enabled
- **Missing:** feature flags off; bridge `recall_crystals_for_context` does not consume `coherence_time_crystals` when orchestrator absent

---

## What is wired today (complete chains only)

| Chain | Write | Read | Behavior change |
|---|---|---|---|
| SMS snooze reply | `twilio_webhook.py` 167–180 | `nate_checkin_agent.py` 258–265 | Skip 62h/72h outreach until snooze expires |
| Recall frequency decay | `crystal_recall_bridge.py` 489–493 | `nate_memory_crystallizer.py` 2128–2138 | Archive low-recall crystals after 90d |

Neither chain closes **chat action → user outcome → memory weight** for attributed crystals.

---

## Feature-flag production defaults (code)

| Flag | Default | File:line |
|---|---|---|
| `ENABLE_QUANTUM_CRYSTAL_ORCHESTRATOR` | `False` | `_settings.py` 193 |
| `ENABLE_TIME_CRYSTAL_FORGE` | `False` | `_settings.py` 195 |
| `ENABLE_CRYSTAL_GRAPH` | `False` | `_settings.py` 197 |
| `ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION` | `False` | `_settings.py` 194 |
| `ENABLE_AUTONOMOUS` | `false` (env) | `bridge_server.py` 31814 |
| `ENABLE_SUBCONSCIOUS` | `false` (env) | `bridge_server.py` 31849 |
| `BRIDGE_VALIDATOR_FILTER_RECALL` | off (unset env) | `crystal_recall_bridge.py` 84 |

`docker-compose.prod.yml`: no overrides found for these flags (`grep` zero matches).

---

*End of report.*
