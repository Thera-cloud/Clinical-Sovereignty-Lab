---
name: Sovereign Wiring Completion Plan
overview: "Walk through every partial and unwired .mdc rule in priority order. For each rule, read the rule file, identify missing components (tables not writing, classes not instantiated, files not found), implement the missing wiring, verify data flows, and mark complete. DO NOT mark a task complete until the table has rows or the class is instantiated in a running code path."
todos:
  # ══════════════════════════════════════════════════════════
  # PRIORITY 0: CRITICAL INFRASTRUCTURE (do first)
  # ══════════════════════════════════════════════════════════

  - id: P0-001
    content: "ODPE L1 TAXONOMY SEEDING — Read .cursor/rules/odpe-architecture.mdc. The odpe_l1_taxonomy table has 0 rows. The odpe_l1_taxonomy.py file has 99 CORE_CONCERN_CLUSTERS defined in code but no seed function writes them to PostgreSQL. Write a seed function that iterates CANONICAL_FUNCTIONS × SCOPE_LEVELS × CORE_CONCERN_CLUSTERS and inserts 2,400 rows into odpe_l1_taxonomy. Run it. Verify: SELECT COUNT(*) FROM odpe_l1_taxonomy should return 2400."
    status: pending

  - id: P0-002
    content: "ODPE SIGNAL LOGGING — The odpe_signal_log table has 0 rows. ODPEEngine.evaluate() runs on every turn but never writes its signal classification to the log table. Find where evaluate() returns its result in odpe_engine.py and add an INSERT INTO odpe_signal_log with user_id, session_id, signal (LOCKED/PROMOTED/PROVISIONAL/TENSION/DEEP_TENSION/NOISE), face_path, confidence, and timestamp. Verify: Send a chat message, then SELECT COUNT(*) FROM odpe_signal_log should be > 0."
    status: pending

  - id: P0-003
    content: "ODPE L2 SELF-ORGANIZING MAP ACTIVATION — The odpe_l2_faces table has 0 rows. HectakisL2Evaluator exists in odpe_engine.py. Find where crystals are created in nate_memory_crystallizer.py and add the L2 face assignment logic: when a crystal is created with an L1 face_path, compare its embedding to existing L2 clusters. If cosine > 0.85, assign existing L2 face. If novel, create new L2 face. Verify: After crystal production runs for 1 hour, SELECT COUNT(*) FROM odpe_l2_faces should be > 0."
    status: pending

  - id: P0-004
    content: "VECTORIZE RE-INDEX VERIFICATION — The Vectorize re-index of 135K crystals was initiated. Verify it completed: check the nate-wisdom index vector count via Cloudflare API. The count should be close to 135,000. If not, re-run the re-index script. Verify: Vectorize index vector count > 100,000."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 1: CORE THERAPY QUALITY
  # Rules that affect the therapy engine's effectiveness
  # ══════════════════════════════════════════════════════════

  - id: P1-001
    content: "VOICE SESSION RECORDS — Read .cursor/rules/nate-voice.mdc (7 missing). The voice_sessions table has 0 rows despite voice calls working. Find where voice calls end in the Twilio pipeline and add an INSERT INTO voice_sessions with call_sid, user_id, duration, start_time, end_time, provider, and status. Verify: Make a test call, then SELECT COUNT(*) FROM voice_sessions should be > 0."
    status: pending

  - id: P1-002
    content: "VOICE CRYSTALS — The voice_crystals table has 0 rows. Voice calls generate transcripts but never crystallize them. Find where voice call transcripts are finalized and wire them into the crystallization pipeline (nate_memory_crystallizer.py). The crystal should have source_type='voice' and include the call_sid. Verify: After a voice call, SELECT COUNT(*) FROM voice_crystals should be > 0."
    status: pending

  - id: P1-003
    content: "CALL METRICS — Read .cursor/rules/voice-call-pipeline.mdc. The call_metrics table has 0 rows. Voice calls should log latency, duration, provider, STT time, TTS time, and turn count. Find the voice call handler and add metrics logging. Verify: After a voice call, SELECT COUNT(*) FROM call_metrics should be > 0."
    status: pending

  - id: P1-004
    content: "NEURAL FINGERPRINTS — The neural_fingerprints table has 0 rows despite voice_session_biometrics having 13 rows. The voice biometric data is captured but never processed into fingerprints. Find where voice_session_biometrics are written and add the fingerprint extraction step that writes to neural_fingerprints. Verify: SELECT COUNT(*) FROM neural_fingerprints should be > 0."
    status: pending

  - id: P1-005
    content: "CONVERSATION CONTEXT — Read .cursor/rules/conversation-history-postgresql.mdc (3 missing). The conversation_context table has 0 rows. Chat sessions write to conversation_history but not to conversation_context. Find where conversation context is assembled in process_interaction and add a write to conversation_context with the assembled context blocks. Verify: After a chat session, SELECT COUNT(*) FROM conversation_context should be > 0."
    status: pending

  - id: P1-006
    content: "SESSION SUMMARIES — The session_summaries table has 0 rows. Sessions end but are never summarized. Add a post-session summary generation step (can use Workers AI) that writes a 2-3 sentence summary to session_summaries. Verify: After a session ends, SELECT COUNT(*) FROM session_summaries should be > 0."
    status: pending

  - id: P1-007
    content: "LIMINAL OBSERVATIONS — The liminal_observations table has 0 rows despite liminal_presence_analysis having 105 rows. The liminal detector runs but doesn't write observations. Find where liminal detection occurs and add writes to liminal_observations. Verify: SELECT COUNT(*) FROM liminal_observations should be > 0 after sessions with liminal content."
    status: pending

  - id: P1-008
    content: "LIMINAL RESOLVE STATES — The liminal_resolve_states table has 0 rows. The migration was applied (159) and the table exists. Find where LIMINAL_RESOLVE protocol activates and wire the state writes. Verify: Table populates when liminal state is detected."
    status: pending

  - id: P1-009
    content: "VOICE CALL MEMORY LIFECYCLE — Read .cursor/rules/voice-call-memory-lifecycle.mdc (1 missing). Identify the missing component and wire it. Voice calls should write to conversation_history with source='voice' just like chat writes with source='chat'. Verify: After a voice call, SELECT * FROM conversation_history WHERE source='voice' should return rows."
    status: pending

  - id: P1-010
    content: "VOICE WEB SEARCH SAFETY — Read .cursor/rules/voice-web-search-safety.mdc (3 missing). Identify the 3 missing components and implement them. This affects the safety of web search during live voice calls. Verify: Each missing component exists in code and is called."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 2: PREDICTIVE INTELLIGENCE
  # Rules that affect cycle detection and therapeutic prediction
  # ══════════════════════════════════════════════════════════

  - id: P2-001
    content: "CYCLE DETECTION — The cycle_detections table has 0 rows. The cycle detection engine exists in code but never writes results. Find the CycleDetectionEngine class, verify it runs, and wire its output to the cycle_detections table. Verify: SELECT COUNT(*) FROM cycle_detections should be > 0 after 24 hours of operation."
    status: pending

  - id: P2-002
    content: "CYCLE PREDICTIONS — The cycle_predictions table has 0 rows. Depends on cycle_detections having data. Once P2-001 is complete, verify the prediction engine reads from detections and writes predictions. Verify: SELECT COUNT(*) FROM cycle_predictions should be > 0."
    status: pending

  - id: P2-003
    content: "THERAPEUTIC PREDICTIONS — The therapeutic_predictions table has 0 rows. The PMB (Predictability Model) exists per pmb-predictability-model.mdc rule. Find where predictions are generated and wire writes to this table. Verify: Table populates."
    status: pending

  - id: P2-004
    content: "EMOTIONAL WEATHER SNAPSHOTS — The emotional_weather_snapshots table has 0 rows. This should capture periodic snapshots of the user's emotional state. Find or create the snapshot generator and wire it. Verify: Table populates."
    status: pending

  - id: P2-005
    content: "NEVEDAL COHERENCE LOG — The nevedal_coherence_log table has 0 rows despite nevedal_metrics having 6,229 rows. The Nevedal engine computes but doesn't log coherence events. Add coherence logging to nevedal_engine.py. Verify: SELECT COUNT(*) FROM nevedal_coherence_log should be > 0."
    status: pending

  - id: P2-006
    content: "NEVEDAL DOMAIN STATE — The nevedal_domain_state table has 0 rows. This should track per-domain Nevedal state (attachment, shame, trauma, etc.). Wire domain-level state tracking in the Nevedal engine. Verify: Table populates."
    status: pending

  - id: P2-007
    content: "COHERENCE TIME CRYSTALS — The coherence_time_crystals table has 0 rows. The QuantumCrystalOrchestrator flag is enabled. Find where time crystals should be created and wire the insertion. Verify: Table populates."
    status: pending

  - id: P2-008
    content: "CRYSTAL CO-ACTIVATION — The crystal_co_activation_events table has 0 rows. When two crystals are recalled in the same session, a co-activation event should be logged. Find crystal recall in the inference pipeline and add co-activation detection. Verify: Table populates after sessions that recall multiple crystals."
    status: pending

  - id: P2-009
    content: "CRYSTAL EDGES — The crystal_edges table has 0 rows. Crystal graph edges should be created when crystals co-activate or share themes. Wire edge creation from co-activation events. Verify: Table populates."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 3: NIGHT SCHOOL & IDENTITY
  # Rules that affect knowledge ingestion and identity systems
  # ══════════════════════════════════════════════════════════

  - id: P3-001
    content: "NIGHT SCHOOL INGESTION — The night_school_ingestions, night_school_indexes, and night_school_queue tables all have 0 rows. The Night School system was designed to ingest therapeutic workbooks. Find the Night School pipeline code, configure it with the two workbooks ('He Came For Every Part of Me' and 'The Father, The Broken Sons'), and run the ingestion. Verify: All three tables populate."
    status: pending

  - id: P3-002
    content: "ME2ME IDENTITY CRYSTALS — The me2me_identity_crystals table has 0 rows. Me2Me journaling should produce identity-specific crystals. Find where Me2Me entries are processed and wire crystallization to this table. Verify: Table populates when Me2Me journaling occurs."
    status: pending

  - id: P3-003
    content: "ME2ME FAMILY FABRICS — The me2me_family_fabrics table has 0 rows. This tracks relational patterns between family members via Me2Me. Wire the fabric detection. Verify: Table populates for users with family connections."
    status: pending

  - id: P3-004
    content: "IDENTITY INFERENCE LOG — The identity_inference_log table has 0 rows. The Therapeutic Identity Inference Engine runs but doesn't log. Wire logging. Verify: Table populates."
    status: pending

  - id: P3-005
    content: "NARRATIVE IDENTITY PROFILES — The narrative_identity_profiles table has 0 rows. This feeds the SSE Identity Forge. Wire profile creation from session data. Verify: Table populates."
    status: pending

  - id: P3-006
    content: "PARTS DETECTION FEEDBACK — The parts_detection_feedback table has 0 rows. IFS parts detection runs via liminal_detectors.py but doesn't log feedback. Wire feedback logging. Verify: Table populates."
    status: pending

  - id: P3-007
    content: "VIRTUAL EEG TRACES — The virtual_eeg_traces table has 0 rows. Neural Mirror Patent 11 produces virtual EEG bands but doesn't write traces. Wire trace logging from neural_mirror.py. Verify: Table populates during voice sessions."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 4: BUSINESS OPERATIONS
  # Rules that affect billing, registration, and families
  # ══════════════════════════════════════════════════════════

  - id: P4-001
    content: "STRIPE SUBSCRIPTIONS — Read .cursor/rules/stripe-payment-billing-architecture.mdc (4 missing). The subscriptions and subscription_items tables have 0 rows. Stripe webhook events should populate these. Find the webhook handler and wire subscription creation/update events to these tables. Verify: After a Stripe test subscription, tables populate."
    status: pending

  - id: P4-002
    content: "PAYMENT HISTORY — The payment_history table has 0 rows. Stripe payment_intent.succeeded webhooks should write here. Wire the webhook handler. Verify: After a test payment, table populates."
    status: pending

  - id: P4-003
    content: "PENDING SIGNUPS — The pending_signups table has 0 rows. The Stripe-first registration flow should write pending signups before checkout. Verify the registration_checkout.py flow writes to this table. Verify: Table populates during registration flow."
    status: pending

  - id: P4-004
    content: "REGISTRATION FLOW — Read .cursor/rules/registration-flow-integrity.mdc (3 missing). Identify and implement the 3 missing components. Verify: Complete a test registration end-to-end."
    status: pending

  - id: P4-005
    content: "FAMILIES TABLE — The families table has 0 rows. Family registration should create family records. Wire family creation in the registration or settings flow. Verify: Table populates when a family account is created."
    status: pending

  - id: P4-006
    content: "CONSENT RECORDS — The consent_records and consent_requests tables have 0 rows. BIPA/COPPA consent framework exists but never writes. Wire consent recording to user onboarding flow. Verify: Tables populate during registration."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 5: CRYSTAL INTELLIGENCE COMPLETENESS
  # Rules that affect crystal production quality
  # ══════════════════════════════════════════════════════════

  - id: P5-001
    content: "CRYSTAL REPLICATION — The crystal_replication table has 0 rows. Cross-node crystal sync between GREEN and ORANGE should be tracked. Wire replication logging. Verify: Table populates during factory operations."
    status: pending

  - id: P5-002
    content: "CRYSTAL PREWARM LOG — The crystal_prewarm_log table has 0 rows. Crystal prewarming exists in code but doesn't log. Wire logging. Verify: Table populates."
    status: pending

  - id: P5-003
    content: "TRANSFER CRYSTALS — The transfer_crystals table has 0 rows. Crystal transfers between users (e.g., ChatGPT import) should be tracked. Wire the Transfer Crystal pipeline. Verify: Table populates during import."
    status: pending

  - id: P5-004
    content: "TRANSGENERATIONAL PATTERNS — The transgenerational_patterns table has 0 rows. Cross-generational pattern detection should write here. Wire pattern detection from family crystal analysis. Verify: Table populates for users with family connections."
    status: pending

  - id: P5-005
    content: "CRYSTAL RECALL WIRING — Read .cursor/rules/crystal-recall-crystallization-wiring.mdc (1 missing). Identify the missing component and implement it. Verify: Crystal recall produces expected data flow."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 6: INFRASTRUCTURE & SECURITY
  # Rules that affect platform reliability
  # ══════════════════════════════════════════════════════════

  - id: P6-001
    content: "THREE NODE SYNC — Read .cursor/rules/three-node-sync-discipline.mdc (2 missing, UNWIRED). This governs GREEN↔ORANGE↔BLUE sync. Identify both missing components and implement. Critical for distributed crystal factory reliability."
    status: pending

  - id: P6-002
    content: "EDGE WORKER FLEET — Read .cursor/rules/edge-worker-fleet.mdc (1 missing, UNWIRED). Identify the missing component. This governs the Cloudflare Worker deployment. Implement. Verify: Workers are deployed and responding."
    status: pending

  - id: P6-003
    content: "CONTAINER REGISTRY DEPLOY — Read .cursor/rules/container-registry-deploy.mdc (1 missing, UNWIRED). Identify the missing component. Wire container registry CI/CD. Verify: Docker images build and deploy through the registry."
    status: pending

  - id: P6-004
    content: "CLOUDFLARE TUNNEL TWIN ENGINE — Read .cursor/rules/cloudflare-tunnel-twin-engine.mdc (4 missing). The tunnel connects CLI-Mac to CLI-Cloud. Identify and implement the 4 missing components. Verify: Tunnel is functional."
    status: pending

  - id: P6-005
    content: "TRUST ENFORCER — Read .cursor/rules/trust-enforcer-architecture.mdc (3 missing). The trust enforcement system is half-built. Identify and implement the 3 missing components. Verify: Trust enforcer runs and logs to trust tables."
    status: pending

  - id: P6-006
    content: "LOGIN ATTEMPTS — The login_attempts table has 0 rows. Login attempts should be logged for security. Wire login attempt logging in the auth handler. Verify: After a login, SELECT COUNT(*) FROM login_attempts should be > 0."
    status: pending

  - id: P6-007
    content: "HELIX COHERENCE HISTORY — The helix_coherence_history table has 0 rows. The Helix 7-step pipeline runs but doesn't log coherence. Wire coherence logging. Verify: Table populates."
    status: pending

  - id: P6-008
    content: "CRISIS EVENTS — The crisis_events table has 0 rows. Crisis detection runs via liminal detectors but doesn't write to crisis_events. Wire crisis event logging. This is SAFETY CRITICAL — crisis events must be tracked. Verify: Table populates when crisis signals are detected."
    status: pending

  - id: P6-009
    content: "CRISIS WATCHLIST — The crisis_watchlist table has 0 rows. Users flagged for crisis monitoring should be tracked here. Wire watchlist management. Verify: Table populates when crisis threshold is crossed."
    status: pending

  # ══════════════════════════════════════════════════════════
  # PRIORITY 7: REMAINING PARTIAL RULES
  # Walk through each remaining partial rule
  # ══════════════════════════════════════════════════════════

  - id: P7-001
    content: "LEARNED INTEGRATION PATTERNS — Read .cursor/rules/learned-integration-patterns.mdc (5 missing). This is the largest gap in the partial rules. Walk through the rule, identify all 5 missing components, implement each one. Verify each."
    status: pending

  - id: P7-002
    content: "BACKGROUND AGENT ERROR VISIBILITY — Read .cursor/rules/background-agent-error-visibility.mdc (2 missing). Agents run in background but errors aren't surfaced. Implement error visibility for the 2 missing components."
    status: pending

  - id: P7-003
    content: "HIVE DEFENSE WORKERS — Read .cursor/rules/hive-defense-workers.mdc (2 missing). Defense workers are mostly wired but 2 components are missing. Implement."
    status: pending

  - id: P7-004
    content: "AGENT DATABASE DISCIPLINE — Read .cursor/rules/agent-database-discipline.mdc (3 missing). Agents should follow database discipline rules. Implement the 3 missing components."
    status: pending

  - id: P7-005
    content: "MISSING MODULE PREVENTION — Read .cursor/rules/missing-module-prevention.mdc (3 missing). This prevents import errors from missing modules. Implement the 3 missing guards."
    status: pending

  - id: P7-006
    content: "DEPLOYMENT TRUST 100% — Read .cursor/rules/deployment-trust-100-percent.mdc (3 missing). Deployment verification has gaps. Implement the 3 missing checks."
    status: pending

  - id: P7-007
    content: "BLE TOKEN SHARING PROTOCOL — Read .cursor/rules/ble-token-sharing-protocol.mdc (2 missing). BLE proximity story handshake needs 2 components. Implement. This is a prerequisite for the SSE BLE/NFC feature."
    status: pending

  - id: P7-008
    content: "WEBAUTHN YUBIKEY SECURITY — Read .cursor/rules/webauthn-yubikey-security.mdc (2 missing). YubiKey auth has 2 missing components. Implement."
    status: pending

  - id: P7-009
    content: "CLOUDFLARE REALTIME WEBRTC — Read .cursor/rules/cloudflare-realtime-webrtc.mdc (3 missing). WebRTC infrastructure has 3 missing components. Implement."
    status: pending

  - id: P7-010
    content: "DEVICE HISTORY SYNC ON LOGIN — Read .cursor/rules/device-history-sync-on-login.mdc (2 missing). Device tracking has 2 missing components. Implement."
    status: pending

  - id: P7-011
    content: "TRUST REGRESSION PREVENTION — Read .cursor/rules/trust-regression-prevention.mdc (2 missing). Trust regression guards have 2 missing components. Implement."
    status: pending

  - id: P7-012
    content: "SOVEREIGN INFERENCE ROUTING — Read .cursor/rules/sovereign-inference-routing.mdc (2 missing). Inference routing has 2 missing components. Implement."
    status: pending

  - id: P7-013
    content: "QUANTUM SOVEREIGN ENTERPRISE — Read .cursor/rules/quantum-sovereign-enterprise.mdc (2 missing). Enterprise features have 2 missing components. Implement."
    status: pending

  - id: P7-014
    content: "ODPE ARCHITECTURE REMAINING — Read .cursor/rules/odpe-architecture.mdc (2 missing — after P0-001/P0-002/P0-003 are done). Verify all ODPE components are now wired. Any remaining gaps, implement."
    status: pending

  - id: P7-015
    content: "ALL REMAINING 1-MISSING PARTIAL RULES — Walk through every partial rule with exactly 1 missing component: checkin-followup-flow, clinical-agent-safety, clone-vps-operations, cloudflare-load-balancer, coach-login-diagnostics, code-intelligence-agent, community-mesh-privacy, cybersecurity-hardening, endpoint-websocket-sustainability, inference-env-pairs, me2me-table-names, old-code-hygiene, phase-11-edge-architecture, sase-request-flow, sentinel-false-positive-prevention, service-health-124, service-health-49-49, silent-exception-prevention, skyeye-trust-audit, steve-jobs-audit-rules, tiered-voice-pipeline, token-economics-architecture, trust-100-percent, voice-call-memory-lifecycle, voice-call-pipeline, voice-infrastructure, voice-therapy-pipeline. For EACH: read the rule, find the 1 missing component, implement it, verify."
    status: pending

  # ══════════════════════════════════════════════════════════
  # VERIFICATION GATE
  # ══════════════════════════════════════════════════════════

  - id: VERIFY-001
    content: "RE-RUN WIRING AUDIT — After all above tasks are complete, re-run the wiring audit script. Target: 90%+ fully wired (up from 51%). All Priority 0-3 rules should show FULLY WIRED. Report results to Big Nate for review."
    status: pending

  - id: VERIFY-002
    content: "RE-RUN DATABASE AUDIT — After all above tasks are complete, re-run: SELECT COUNT(*) as empty_tables FROM pg_stat_user_tables WHERE n_live_tup = 0. Target: fewer than 250 empty tables (down from 402). All tables in the CRITICAL GAPS category should have data."
    status: pending

  - id: VERIFY-003
    content: "HUMAN VERIFICATION — Big Nate tests: (1) Call 656-231-8192, verify voice works AND check voice_sessions table has a new row. (2) Send chat message, verify response AND check conversation_context table has a new row. (3) Check odpe_l1_taxonomy has 2400 rows. (4) Check odpe_signal_log has rows. (5) Check Vectorize nate-wisdom index has 135K+ vectors."
    status: pending

isProject: true
---

# Sovereign Wiring Completion Plan

## Context

A wiring audit on March 30, 2026 found:
- **143 rules** across .cursor/rules/ and .sovereign/rules/
- **175 plans** across .cursor/plans/ and .cursor/plans/archive/
- **51% fully wired**, 45% partial, 5% unwired
- **402 of 449 database tables empty** (55 critical gaps)
- **ODPE L1 taxonomy: 0 of 2,400 faces seeded**
- **ODPE L2 self-organizing map: 0 faces emerged**
- **ODPE signal log: 0 entries**
- **Voice sessions, voice crystals, call metrics: all 0**
- **Night School: never ingested workbooks**
- **Cycle detection, predictions: never produced output**

## Methodology

For EVERY task:
1. **READ** the referenced .mdc rule file first
2. **IDENTIFY** exactly which component is missing
3. **IMPLEMENT** the minimal code change to wire it
4. **VERIFY** by checking the database table has rows or the class is instantiated
5. **DO NOT** mark complete until verification passes

## Critical Rules

- **NEVER modify protected files** (bridge_server.py, main.py, littlenate_inference.py, nate_memory_crystallizer.py, docker-compose.prod.yml) beyond the minimal hook required
- **Flag any diff > 50 lines** on protected files for Big Nate review
- **Test voice and chat** after any change that touches the inference or session pipeline
- **Commit and push** after each completed priority tier

## Priority Order

- **P0**: ODPE taxonomy + signal logging + Vectorize verification (do FIRST)
- **P1**: Core therapy quality (voice sessions, crystals, context, liminal)
- **P2**: Predictive intelligence (cycles, predictions, coherence)
- **P3**: Night School + identity systems
- **P4**: Business operations (Stripe, registration, families)
- **P5**: Crystal intelligence completeness
- **P6**: Infrastructure and security
- **P7**: All remaining partial rules
- **VERIFY**: Re-run audits, human verification
