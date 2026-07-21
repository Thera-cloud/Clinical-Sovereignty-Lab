# AGENTIC_WIRING_INVENTORY.md

**Inventory date:** 2026-07-10 (delta 2026-07-21)  
**Scope:** Typed extraction, verifier constraint locations, C_emo/nevedal state schema, dormant knowledge-graph flags  
**Related plan:** `.cursor/plans/little_nate_agentic_roadmap_ef224a28.plan.md`  
**Mode:** Read-only factual snapshot — no fixes, no proposals

---

## Executive verdict (updated 2026-07-21 — Track D + self-dev)

Phase **6** + Track D flags live on GREEN (battery, living, standards, gen, `LIVE_WS=true`). Self-dev agent: `ENABLE_SIX_QUOTIENT_SELF_DEV` (default false) → `SixQuotientSelfDevelopmentAgent` + `POST /api/admin/six-quotient/self-dev/trigger` → CEO YELLOW `six_quotient_self_dev`. Neuro-symbolic Phase 5a–5d remains ON.

## Executive verdict (updated 2026-07-21 — Phase 6.7 prod ON)

Phase **6** core flywheel live on GREEN: `ENABLE_SIX_QUOTIENT_BATTERY=true`, `SIX_QUOTIENT_BATTERY_LIVE_WS=false`. Staging 6.1–6.6 + prod smoke verified. Track D living/standards/gen remain **false** (D.8). Neuro-symbolic Phase 5a–5d remains ON. *(Superseded — see Track D + self-dev verdict.)*

## Executive verdict (updated 2026-07-21 — Phase 6 pre-flip ready)

Phase **6** six-quotient battery code + migration 245 live; staging 6.1–6.6 verified. Prod defaults: `ENABLE_SIX_QUOTIENT_BATTERY=false`, `SIX_QUOTIENT_BATTERY_LIVE_WS=false` (compose wires LIVE_WS + `TEST_PASSWORD`/`AUDIT_CLIENT_PASSWORD`). Pre-flip smoke: `backend/scripts/prod_phase6_battery_smoke.py`. Flip **6.7** = battery flag only; keep LIVE_WS false until post-flip soak. Track D living/standards/gen stay false on prod (D.8). *(Superseded — see 6.7 ON verdict above.)*

## Executive verdict (updated 2026-07-21 — Phase 5a–5d prod ON)

Phase **5** flags live on GREEN backend: `ENABLE_SYMBOLIC_EXTRACTION` / `ENABLE_SYMBOLIC_VERIFIER` / `ENABLE_FORWARD_REASONING` / `ENABLE_CRYSTAL_GRAPH` = **true**. Bridge carries extract/verifier/forward; graph constellation is **backend** `app.state.crystal_graph` only (`ENABLE_CRYSTAL_GRAPH` not required on bridge). Live `retrieve_constellation(..., requester_user_id=)` enforces `enforce_traversal_scope` (nodes load `scope`/`user_id`).

## Executive verdict (updated 2026-07-20 — Phase 0–4 + N.3 prod ON; TOUCH off)

Phases **0–4** + session negotiation live in prod (flags true; `ENABLE_SELF_MONITOR_TOUCH=false`). Propose/confirm wired via `maybe_propose_from_utterance` + `check_and_execute_confirmation`. Commitment extract + plan context + plan divergence log on bridge chat path. Commitment touches: `nate_nudges` + Redis `nate:commitment_touch` → bridge WS. *(Superseded for 5c/5d flags — see 2026-07-21 verdict.)* Consent fails closed when `proactive_presence_consent` absent (opt-in via Settings / soft prompt; test account opted in).

## Executive verdict (updated 2026-07-10 — implementation landed, flags default **off**)

Phases **0–5** code paths are **implemented behind feature flags** (see rollout table in roadmap). Production behavior is unchanged until operator adversarial review + per-phase flag flips.

| Phase | Key artifacts | Flag(s) |
|-------|---------------|---------|
| 0 | `237_proactive_touch_policy.sql`, `proactive_touch_policy.py`, check-in retrofit, `_touch_adaptation_pass()` | `ENABLE_PROACTIVE_TOUCH_POLICY` |
| 1 | `238_nate_commitments.sql`, extractor/agent/service, bridge WS handlers, Flutter consent + commitments UI | `ENABLE_PROACTIVE_COMMITMENTS` |
| 2 | `nate_tool_executor.py`, `session_booking_service.py`, bridge confirmation hook | `ENABLE_NATE_TOOL_EXECUTOR` |
| 3 | `239_nate_therapeutic_plans.sql`, plan service + coach REST, chat context injection | `ENABLE_THERAPEUTIC_PLANS` |
| 4 | `nate_self_monitor_agent.py`, `docs/AGENTIC_PHASE4_DISCOVERY.md` | `ENABLE_SELF_MONITOR_*` |
| 5a–5d | Symbolic extractor/verifier, forward reasoning, graph isolation, phi auditor extension | `ENABLE_SYMBOLIC_*`, `ENABLE_FORWARD_REASONING`, `ENABLE_CRYSTAL_GRAPH` |
| 6 | Six-quotient battery agent/API/runner, growth engine, auditor | `ENABLE_SIX_QUOTIENT_BATTERY`, `SIX_QUOTIENT_BATTERY_LIVE_WS` |
| D | Living battery v5 (bank/standards/gen) | `ENABLE_SIX_QUOTIENT_LIVING_*`, `*_STANDARDS_INDEX`, `*_SCENARIO_GEN` |
| D.9 | Bi-weekly self-dev → CEO YELLOW inbox | `ENABLE_SIX_QUOTIENT_SELF_DEV` |

**Prior snapshot (pre-build) below retained for audit trail.**

---

## Executive verdict (pre-build snapshot)

**Commitment + sensitivity typed extraction from the agentic plan is not implemented** (`nate_commitment_extractor.py`, `nate_commitments` table, `proactive_touch_policy.py` absent). Mirror/scope/crisis verifier primitives **exist today** in bridge enrichment, therapeutic controller, crystal recall, and SI coach alert paths. **Two graph flags** must not be conflated: Sensitive Bridge Layer 3 `crystal_knowledge_graph_opt_in` (preference only, no traversal) vs global `ENABLE_CRYSTAL_GRAPH` (code + `crystal_edges` table, flag off).

---

## 1. Typed extraction / classification (sensitivity + commitment)

### Planned (roadmap only — no runtime code)

| Item | Location | Emit shape |
|------|----------|------------|
| Commitment + sensitivity extractor | Plan → `backend/app/services/nate_commitment_extractor.py` (**file does not exist**) | `{text, type, target_date_iso, recurrence, sensitivity}` — `type ∈ {appointment, practice_goal, milestone, custom}`; `sensitivity ∈ {routine, sensitive}` |
| Persistence | Planned migration `238_nate_commitments.sql` (**not in repo**) | `nate_commitments`, `nate_proactive_touches` |
| Repo grep | `nate_commitment` under `backend/` | **0 matches** |

### What emits today (closest analogues)

| Pass | File | Emits | Persists to |
|------|------|-------|-------------|
| Conversation crystal forge (heuristic, not LLM JSON) | `backend/app/websocket/crystal_recall_bridge.py` → `crystallize_from_conversation()` | Returns `Optional[str]` (`content_hash`); INSERT fields: `crystal_text`, `domain`, `scope='user'`, `confidence=0.50`, `origin_surface`, optional `metadata` (`ifs_parts` if `BRIDGE_IFS_METADATA`) | `nate_intelligence_crystals` + Vectorize |
| Sensitive disclosure pipeline | `backend/app/services/sensitive_clinical_bridge.py` → `evaluate_disclosure()` | Frozen dataclass `BridgeDecision` (~19 fields): `register_directive`, `coach_alert: CoachAlertRef`, `resource_block`, `scope_statement`, `audit_event`, `novelty_gate_state`, `arousal_load`, `tmc_class`, `trafficking_classification`, … | `sensitive_bridge_log`, coach handoff refs (`clinician_only`) |
| PII detection | `backend/app/services/night_school_director.py` → `PIIDetector.detect()` | `List[PIIMatch]` — `{type: PIIType, start, end, original_text, confidence}` | Redaction path only |
| Response validator | `backend/app/services/nate_response_validator.py` → `validate()` | `Tuple[str, List[str]]` warnings e.g. `unverified_factual_assertion_about_person`, `hallucination_pattern:*` | `skyeye_activity` on Layer 8 hit |
| TMC classification | `backend/app/services/therapeutic_controller.py` → `_fetch_tmc()` | `dict` from `TherapeuticMomentClassifier.classify()` | Consumed in `prepare_therapeutic_context()` `audit_metadata` |
| IFS part hints | `backend/app/websocket/bridge_enrichment.py` → `ifs_part_hints()` | Part labels from regex | Optional crystal `metadata` only |

**Sensitivity tag for proactive commitments:** not emitted anywhere today. Plan reuses Sensitive Bridge / `PIIDetector` category signals at extraction — wiring is plan-only.

---

## 2. Verifier constraint locations

### A. Emotional-state / mirror logic

| Layer | File | Shape |
|-------|------|-------|
| Static priority overrides (OVERRIDE 1–4) | `backend/app/websocket/bridge_server.py` ~9738+ (`LITTLE_NATE_SYSTEM_PROMPT`) | Prose: parallel-process mirror, somatic interrupt, witnessing, therapeutic helplessness |
| Per-turn regex detectors | `backend/app/websocket/bridge_enrichment.py` → `detect_priority_overrides()`, `build_priority_override_addendum()` | `List[str]`: `parallel_process`, `somatic_interrupt`, `witnessing`, `therapeutic_helplessness` |
| Pre/post-flight verifier | `backend/app/services/therapeutic_controller.py` | `prepare_therapeutic_context()` → `{enriched_system_prompt, max_tokens, audit_metadata}`; `audit_therapeutic_response()` → `{response_text, audit_passed, violations, mismatch_delivered}` |
| Sensitive bridge register | `sensitive_clinical_bridge.py` → `BridgeDecision.register_directive` | String directive from addiction/trafficking/TMC pipeline |

### B. Scope-isolation rules

| Layer | File | Rule |
|-------|------|------|
| Recall query filters | `backend/app/websocket/crystal_recall_bridge.py` | User: `(scope = 'user' OR scope LIKE 'user:%')`; global: `scope = 'global'`; `superseded_by IS NULL`; user conf `>= 0.30`, global `>= 0.55` |
| Orphan write guard | `crystal_recall_bridge.py` → `crystallize_from_conversation()` | Refuses insert if `user_uuid` unresolved (fail-closed on `scope='user'`) |
| Crystallizer scope | `backend/app/services/nate_memory_crystallizer.py` | Fragment `scope`: `user:{id}`, `global`, `admin_only`, `response_pattern`; decay → `archived` |
| Sensitive factory L1/L2 | `sensitive_clinical_bridge.py` → `_load_crystal_factory_layer1/2()` | User `scope != 'archived'` OR global; L2 requires `scope='response_pattern'` |
| Validator recall filter | `nate_response_validator.py` → `filter_recalled_crystals()` | Layer 8 excludes unverifiable-assertion crystals at recall |
| Planned crystal-boundary for touches | Agentic plan Phase 0 gate check 5 | **Not implemented** (`proactive_touch_policy.py` absent) |

Scope invariant (documented): scope may only **narrow** (`global` → `archived`), never widen — enforced via crystallizer decay/archival.

### C. Crisis-detection path

| Path | File | Trigger → output |
|------|------|------------------|
| Universal SI → coach (flagged) | `backend/app/services/suicide_ideation_coach_alert.py` → `maybe_dispatch_si_coach_alert()` | `match_user_text()` → `dispatch_sensitive_alert()` → `sensitive_bridge_log` + `coach_notifications` ref |
| Flag | env `ENABLE_UNIVERSAL_SI_COACH_ALERT` | Default **false** |
| Bridge hook | `bridge_server.py` ~8898 | Calls `maybe_dispatch_si_coach_alert` after client turn |
| Sensitive Bridge coach alert | `sensitive_clinical_bridge.py` | `BridgeDecision.coach_alert: CoachAlertRef` (`severity`, `payload_ref`) |
| Dispatcher | `backend/app/services/sensitive_alert_dispatcher.py` | Single entry for addiction/trafficking/codeword/SI |
| Legacy crisis log | `bridge_server.py` → `MetricsEngine._log_crisis()` | JSON file append |
| Crisis warm referral | `sensitive_clinical_bridge.py` + `v1_4_crisis_warm_referral.mdc` | `sensitive_bridge_log` + `crisis_events` |

### D. Sensitive-commitment rule (proactive push)

| Status | Detail |
|--------|--------|
| **Not implemented** | No `nate_commitments`, no `proactive_touch_policy.py`, no `sensitivity` column |
| **Planned gate** | `can_send_proactive_touch()` check 6: deny `reason='sensitive_in_app_only'` when `sensitivity='sensitive'` |
| **Partial today** | Sensitive content handled in-bridge via `evaluate_disclosure` + enrollment; no automated commitment pushes |

---

## 3. Emotional / clinical state schema (forward-reasoning input)

### A. PostgreSQL `nevedal_metrics` (`backend/migrations/001_schema.sql` + deltas)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | PK |
| `session_id` | UUID FK | nullable in text-chat CEE writes |
| `user_id` | UUID FK → `users.id` | |
| `dyad_partner_id` | UUID FK | nullable |
| `recorded_at` | TIMESTAMPTZ | |
| `c_emo`, `p_ent`, `t_tunnel`, `gamma_env`, `e_g_joint` | DECIMAL(6,5) | Core Nevedal vars |
| `tau_emo`, `d_distance` | DECIMAL | derived |
| `cee_window` | BOOLEAN | |
| `cee_duration_seconds` | INTEGER | |
| `biometrics` | JSONB | subject_a/b, synchrony, voice_stress, … |
| `biometrics_enc` | BYTEA | migration 105 |
| `client_timezone` | TEXT | migration 143, default `'UTC'` |

**Writers:** `nevedal_engine.py` (CEE events); `bridge_server.py` ~5498 (text-chat CEE: `c_emo` only, other vars zeroed).

### B. In-memory `NevedalState` (`nevedal_engine.py`)

`c_emo`, `p_ent`, `t_tunnel`, `d_distance`, `gamma_env`, `e_g_joint`, `tau_emo`, `cee_window`, `cee_duration_seconds`, `cee_intensity`, `interpretation`, `recommendations` → `.to_dict()`.

### C. Per-client `metrics.json` / `nevedal_state` (`bridge_server.py` MetricsEngine ~4976)

- Top-level: `C_emo`, `E_warmth`, `T_tunnel`, `GAP`, `Velocity`, `Quantum`, `anxiety_level`, `depression_indicators`, `stress_level`, `engagement`, `mood_*`, `risk_level`, `crisis_count`
- `crisis_perception`: distress_discrepancy, minimization_score, perception_baseline, …
- `shame_profile`: shame_index, core_beliefs, shame_map, …
- `pmb`: cyclical_patterns, trigger_map, reactivity_type, reconsolidation_readiness, legacy_patterns, predictions, …

### D. Auxiliary tables (migration 145)

- `nevedal_domain_state`: per-domain `C_emo`, `p_ent`, `T_tunnel`, `gamma_env`, `E_G`, `crystal_count`
- `nevedal_coherence_log`: `{domain, C_emo, p_ent, T_tunnel, gamma_env, signal, provider, …}`

### E. ODPE modulation

`nevedal_engine.py` → `_apply_odpe_modulation()` — adjusts Nevedal params from ODPE amplitudes (cap ±0.10).

---

## 4. Dormant knowledge-graph flags

**Two flags — do not conflate.**

### A. Sensitive Bridge Layer 3: `crystal_knowledge_graph_enabled`

| Property | Value |
|----------|-------|
| Storage | `users.profile_data` → `crystal_knowledge_graph_opt_in` (`sensitive_profile_api.py`) |
| Surfaced | `sensitive_clinical_bridge.py` → `_load_framework_menu()` |
| Default | **false** |
| Why off | `v1_4_crystal_factory_layers.mdc`: Layer 3 deferred to Phase G; no schema or traversal |
| If enabled today | **Nothing traverses** — preference only; L1/L2 still run |
| Table | **None** (per-client clinical KG not created) |

### B. Global crystal graph: `ENABLE_CRYSTAL_GRAPH`

| Property | Value |
|----------|-------|
| Flag | `backend/app/config/_settings.py` → `ENABLE_CRYSTAL_GRAPH: bool = False` |
| Service | `backend/app/services/crystal_graph.py` → `CrystalGraph` |
| Table | `crystal_edges` (`152_crystal_edges.sql`; enhanced `154_quantum_crystal_orchestrator.sql`) |
| Columns | `crystal_a_hash`, `crystal_b_hash`, `similarity`, `edge_type`, `strength`, `co_activation_count`, `source`, … |
| Purpose | Constellation retrieval, meta-crystal synthesis, edge persistence |
| Prod (2026-07-21) | **ON** — `retrieve_constellation` filters by requester via `enforce_traversal_scope`; rebuild SELECTs `scope`,`user_id` |
| If enabled | `main.py` starts graph + 4h rebuild; `FederatedSearchCoordinator._search_constellation(user_id=)`; `EntanglementGraph` in `quantum_crystal_orchestrator.py`; co-activation from `crystal_recall_bridge.py` |

---

## Gap matrix (agentic verifier vs today)

| Planned verifier input | Exists today? |
|------------------------|---------------|
| `{text, type, target_date, sensitivity}` commitment extract | **No** |
| `can_send_proactive_touch()` gate | **No** |
| Mirror / somatic / witnessing overrides | **Yes** |
| Crystal scope isolation | **Yes** |
| Crisis / SI coach path | **Yes** (flag-gated) |
| `sensitivity='sensitive'` push block | **No** |
| `crystal_knowledge_graph` traversal | **No** (flag only) |
| `ENABLE_CRYSTAL_GRAPH` traversal | **Shipped (5d)** — prod flag on; live scope filter on constellation |

---

## 5. Phase 5 codebase confirm (2026-07-10)

Pre-build verification for Neuro-Symbolic Layer — merged into [`.cursor/plans/little_nate_agentic_roadmap_ef224a28.plan.md`](.cursor/plans/little_nate_agentic_roadmap_ef224a28.plan.md) Phase 5.

| Assumption | Verdict | Implementation note |
|------------|---------|-------------------|
| `audit_therapeutic_response()` return shape | **Confirmed** | `{response_text, audit_passed, violations, mismatch_delivered}` — `therapeutic_controller.py` ~1179–1184 |
| Post-flight on main CLIENT chat | **Confirmed** | `bridge_server.py` ~10383–10394 when `_ttc_audit_meta` set after `prepare_therapeutic_context()` |
| Extractor piggybacks crystallizer LLM | **False** | `crystallize_from_conversation()` is heuristic-only, zero LLM (`crystal_recall_bridge.py` ~907–916) |
| Phase 5a hook timing | **Locked** | Same post-turn `asyncio.create_task` bundle as crystallize (~10643–10648); StateSymbol deterministic; CommitmentSymbol utility-tier async LLM |
| `sensitivity` source | **Locked** | Set after LLM parse from PII/Sensitive-Bridge signals — **not** from LLM JSON |
| Verifier regen on symbolic violation | **Shipped (5b)** | `ENABLE_SYMBOLIC_VERIFIER`; max 1 LLM regen; 988 append always; `crisis_exempt` skips LLM only |
| Verifier logging | **Shipped (5b)** | `sse_therapeutic_audit_log` + `skyeye_activity` type `symbolic_verifier_action`; admin REST `/api/admin/symbolic-verifier/*` |
| Surfaces covered | **Chat + sanctuary/group/private/voice light path** | Full TTC on bridge chat; `light_symbolic_post_audit` on other WS/voice surfaces; prepare-fail falls back to light audit |
| Crystal scope isolation | **Fixed** | Recall SELECT includes `scope`; excludes `admin_only`; `scope_allows_recall` accepts plain `user` |
| Forward reasoning (5c) | **Shipped (5c)** | prod `ENABLE_FORWARD_REASONING=true`; `profile` → `build_forward_constraints`; compose `${ENABLE_FORWARD_REASONING:-false}` |
| `mismatch_delivered` as fallback | **Unchanged** | Existing mismatch path unchanged; symbolic second-failure uses transparent audit fallback, not mismatch semantics |

**Correction to gap matrix:** commitment extract row will be satisfied by **shared** Phase 1/5a `nate_commitment_extractor.py` — one module, not two extraction paths.

## 6. Sovereign Command Ask Nate surface (2026-07-16)

| Item | Status |
|------|--------|
| UI | `dashboard/ask_nate.html` → WS `ask_nate_coaching` |
| Clinical pack | `backend/app/services/ask_nate_clinical_intelligence.py` |
| Bridge hook | `bridge_server.py` `ask_nate_coaching` — additive pack inject + `ask_nate_intel_meta` |
| Live layers | crystals (`source=ask_nate_command`), main chat, lived wisdom, classroom, Nevedal metrics |
| Flag (default on) | `ENABLE_ASK_NATE_CLINICAL_INTEL=true` |
| Neuro-symbolic seam | `ENABLE_ASK_NATE_SYMBOLIC` → reads `conversation_history.metadata.symbols` + verify guidance; `symbolic_verify` capability flips **live** when symbolic or `ENABLE_SYMBOLIC_VERIFIER` on; Ask Nate replies still go through bridge `process_interaction` post-audit |
| Agentic seam | `ENABLE_ASK_NATE_AGENTIC` → capability envelope only (no tool dispatch yet) |
| Tests | `backend/tests/test_ask_nate_clinical_intelligence_seams.py` |

This is the Command-side **admin advisory** seat (Coach Command–class, not therapist-to-admin). Phase 5b/5c and Phase 2 tool-use should attach here via the reserved capability IDs (`symbolic_verify`, `forward_reason`, `agent_tools`), not via a second Ask Nate path.
