---
name: Multi-LoRA Flywheel Feasibility
overview: "Flywheel A0–D + Amendment 1 + autonomy gaps + residuals + Phase W. Migrations start at 305+ (303/304 already taken). Governance is phased: CEO activate remains valid until Step 0 greens; then Dual-COO mechanical promote + CEO reverse-only."
todos:
  - id: phase-w-wiring
    content: "Phase W skeletons DONE (migs 305–310, hive_burst/shadow_fork, anomaly, fence). W7 marketing dual-write landed. Residual: W8 sandbox rsync, W11 hard claim_ids+SkyEye, W14 live App, W16 live probes — do not block Phase A"
    status: completed
  - id: step-0-weld-extraction
    content: "Step 0 fence GREEN 2026-07-31: manifest_ok, 6 fence tests PASS, R2 weld backup 20260731T130607Z; GREEN boot_fence ok=True. G2 flags LEFT FALSE (manual flip only — not done)"
    status: completed
  - id: phase-a0-base-pin
    content: "Phase A0 DONE: pin Qwen2.5-Coder-7B; refuse/quarantine 1.5B (mig 305 + register asserts); rank/target_modules + merge_eligible"
    status: completed
  - id: phase-a-burst-hive
    content: "Phase A DONE (code): economics F1 bootstrap/CPAI gate; hive_burst resolves rev_a/b + R2 mirror + script args; Redis serve publish; consumer notes wiring. Paid provision still gated by LN7_BURST_ALLOW_PAID + PRE6"
    status: completed
  - id: phase-b1-route-telemetry
    content: "Phase B1/W7 DONE for LN7 ledger+shadow+hive; marketing dual-write via growth_claims.upsert_claim → outcome_envelope (2026-07-31)"
    status: completed
  - id: phase-b2-domain-router
    content: "Phase B2/B3 DONE: mig 305 domain registry (domain_tag/adapter_uri/embedding/serve_weight); Tier1 static+pack-hint routing, Tier2 BGE cosine w/ welded semantic_threshold, Tier3 burst BoN fallback; push_adapter_intent on winner+runner-ups (intent→burst); export --domain flag (2026-08-01)"
    status: completed
  - id: phase-c-merge-drain
    content: "Phase C DONE (code): ln7_merge_drain.py extended with the full Stage 4 orchestrator (run_merge_drain) — disk preflight (check_disk_space, >=120GB gate → merge_disk_low anomaly), PEFT→HF materialization (materialize_peft_to_hf, merge_and_unload), pinned mergekit dare_ties invocation (run_mergekit, no target_model/no relisted base — pre-existing mergekit_yaml_dare_ties), abort_gate as sole authority (beat LN7-fast-baseline AND every contributor on held-out; pre-existing), GGUF conversion for ORANGE Ollama on accept (convert_to_gguf), ~15GB WireGuard transfer to ORANGE via ProxyJump (transfer_gguf_to_orange), and prune_micro_experts (marks contributor revisions merged_pruned only after abort_gate accepts — never on reject). Mirrors ln7_hive_burst.py's lease/watchdog/outcome_envelope pattern: acquire_lease/release_lease around the whole run, write_envelope with E2 cross_loop_attribution on both accept and reject paths, merge_drain_fail anomaly on exception. register_revision now always passed full harness_config/base_checkpoint/quantization (draft + final status update) so ON CONFLICT never wipes merge_of/mergekit_pin provenance. Wired into task bus: FLYWHEEL_TASK_KINDS + _CLAIM_KINDS in cli_task_bus.py/cli_task_bus_consumer.py gained ln7_merge_drain; new anomaly kinds merge_disk_low/merge_drain_fail registered in flywheel_anomaly.py. 18 offline tests in test_ln7_merge_drain_phase_c.py (helpers dry-run, abort_gate accept/reject/no-data, prune, and full orchestrator accept/reject/lease-held/missing-adapter paths). Real (non-dry-run) execution of materialize/mergekit/gguf/transfer subprocess calls, and end-to-end Queens-trigger wiring, remain to be exercised on actual L40S hardware — same paid/live-gated posture as Phase A burst."
    status: completed
  - id: phase-d-flywheel-harden
    content: "Phase D DONE (code, 2026-08-01): (1) Held-out hard-block — new ln7_heldout_registry.py is the single source of truth for HELDOUT_PACKS (reads packs_index.json, frozenset fallback if index missing/corrupt/empty), consumed identically by ln7_export_train_jsonl.py and ln7_train_queue.py (no more drift between the two); ln7_export_train_jsonl.export_rows() now hard-excludes t.split='heldout' at the SQL level (JOIN ln7_tasks) with a separate dropped_heldout_sql COUNT(*) for observability, while the pre-existing pack-name-based HELDOUT_PACKS filter remains as a second independent layer for outcomes whose task row has split=NULL. (2) Data budget — ln7_merge_drain.check_data_budget() queries ln7_coding_outcomes GROUP BY domain, enforces MIN_ROWS_PER_DOMAIN=300 and MIN_TOTAL_ROWS=1500, wired as a preflight step in run_merge_drain() (mirrors check_disk_space's dry_run-gated block-or-warn pattern); new merge_data_budget_low anomaly kind registered in flywheel_anomaly.py. (3) GGUF >=2 consecutive wins — ln7_canary_promoter.evaluate_canary() now extracts prev win_streak from ln7_canary_state.pass_rate_json via _extract_win_streak(), increments on gate.ok else resets to 0, stores new_streak + gguf_eligible (streak>=GGUF_MIN_CONSECUTIVE_WINS=2) back into pass_rate_json every call (confounded-window results preserve prev_streak unchanged, never advance or reset on a window that didn't actually evaluate). (4) LN7-v2-Base post-Stage-4 incumbent — new _is_stage4_merge_product() detects merge_of provenance (>=2 contributor ids) stamped by ln7_merge_drain.register_revision() in harness_config_json; resolve_incumbent_id() routes such revisions to LN7_V2_BASE_INCUMBENT_ID env var (default LN7-v2-Base) instead of the fast/deep baseline its pre-merge contributors gated against. Promote-path Dual-COO diverse checklist (dual_coo_checklist.py) and influence-Gini hold (ln7_influence_audit.py, R6) and stratified vintage+fresh bakeoff mix (ln7_bakeoff_engine.py, R2) were already built in prior Phase E/F/R work and apply unchanged to Phase D's promote gate — no additional wiring needed for those two table rows. 21 new/extended offline tests across test_ln7_heldout_registry.py (new), test_ln7_gguf_streak_and_v2_base.py (new), test_ln7_clean_train_export.py (+1 behavioral SQL+pack-name test), test_ln7_merge_drain_phase_c.py (+6 data-budget tests). Full suite 2242/2242 passing post-change."
    status: completed
  - id: phase-e-nervous-system
    content: "Phase E mostly DONE: mig 306 envelope (E1), 307 flags, 310 suppress (E8 — is_suppressed wired into activate_revision choke point, verified already-present), lease TTL (E5 acquire/release in hive_burst), flywheel_anomaly (E7). Added 2026-08-01: E5 confounded-window detection — evaluate_canary checks is_any_loop_active(['hive_burst']) before gate decision; overlap → gate.ok=False, reason=confounded_window, envelope confounded=True, hold_shadow (never promotes off confounded evidence). E2 DONE — cross_loop_attribution() helper wired into every write_envelope call site in the LN7 causal chain (ln7_ledger coding_outcome genesis event, ln7_shadow_fork x2, ln7_hive_burst, ln7_canary_promoter, dual_coo_checklist); marketing/growth_claims and ln7_fallback_drill intentionally excluded (not part of the LN7 lineage). E4 DONE — mig 315 adds outcome_envelope.sig/sig_window; new ln7_envelope_signing.py signs every write_envelope() call with a per-window HMAC subkey (window = LN7_CHANGE_LEASE_TTL_S, default 900s, matching E5 lease windows) derived from LN7_ENVELOPE_SIGNING_SECRET; write_envelope falls back to unsigned insert if the DB predates mig 315 (rollout race safety); verify_row_signature() detects post-hoc tampering (e.g. flipping shadow_outcome->>'passed'). 11 offline tests in test_ln7_envelope_signing.py + test_ln7_cross_loop_attribution.py. E3 DONE — frozen-config/compliance_grants.json declares the growth/marketing domain's allowlisted tables (growth_* + shared read-only skyeye_activity/skyeye_content_queue + a single documented narrow exception: users, scoped to growth_claims.py's targeted JSONB-key removal for retraction — never SELECTs users, never touches PII/clinical columns); new ln7_compliance_grants.py statically extracts every SQL string literal referenced by growth-domain .py files via AST parsing (avoids false positives from Python keywords/imports/comments) and flags any table not on the allowlist; test_ln7_compliance_grants.py (7 tests) runs this scan in CI and fails the build if a growth-domain file ever references a clinical/PII table (conversation_history, nevedal_metrics, client_metrics, session_memories, sensitive_bridge_*, etc) — this is the CI-verified boundary from self-learning-agent-governance.mdc rule #4. manifest.sha256.json regenerated to pin compliance_grants.json. E6 DONE — new ln7_weekly_digest.py: pure build_digest_text() formatter (unit-testable without DB) plus run_weekly_digest_cycle() that reports trailing-7-day outcome_envelope counts by loop_name/event_kind, E5 confounded rate, E4 signature presence (degrades independently if `sig` column predates mig 315), E2 attribution coverage, E8 active suppress patterns, and E7 flywheel_anomaly counts by kind; sent once per ISO week via notification_system._send_email, deduped through a skyeye_activity marker row — report-only, never writes ceo_inbox, never blocks a gate decision. Wired into Ln7OpsScheduler._tick() (Mondays >=07:00 UTC, after the nightly fuel gauge) with notification_system passed through from main.py. 8 offline tests in test_ln7_weekly_digest.py. Phase E (E1-E8) is now fully complete."
    status: completed
  - id: phase-f-queens-operators
    content: "Phase F: Mechanical Dual-COO after Step 0 only; until then CEO activate remains valid (unchanged, CEO-held G2 decision — held per CEO 2026-08-01, unaffected by gate 1 closing). Living-packs hold RELEASED 2026-08-02 — gate 1 scored 8/8, dose_response_ready=true; design input is the scored grid itself: the six columns that went 0-for-40 across both conditions (naming/direct-assessment, means_distance, escalation, prohibition-navigation (G07 legal_first/means_restriction family), present_close, debate_refusal) are the MUST-sequence lines the pack distillation foregrounds. Pack design (must-sequence-living-packs) is now CODED 2026-08-02 — see must-sequence-living-packs: ln7_must_sequence_pack.py, 11 tests, cross-validated against gate-2's verifier (floor_met=true on a simulated pack-format response); NOT live-wired (flag LN7_MUST_SEQUENCE_PACK_LIVE reserved, off, unread), pending dose-response v2 (paid-gated regeneration) as its acceptance test. R4 layers 2/3 (injection) also now CODED 2026-08-02 — see phase-r-residuals / r4-layers-2-3; only R4's canary-corpus auto-refresh remains, explicitly non-blocking."
    status: in_progress
  - id: phase-g-ln7-shadow-handover
    content: "Phase G: queens.merged → ln7.shadow_fork → sandbox score → shadow_outcome; handover/revert — G1 proven 2026-07-31 (LN7_G1_OPEN; G2 weld keys still false)"
    status: completed
  - id: attempt6-decoupled-bakeoff
    content: "Attempt 6: Phase A freeze→destroy + Phase B offline score; winner LN7-2026-07-30T190327Z; tag bakeoff-v0.6-attempt6-proven; CEO HOLD (no promote/G2)"
    status: completed
  - id: attempt6-steps-6-8
    content: "Post-bakeoff Steps 6–8 at 11d6e1e4: CI gold lock, fuel gauge+mig314, serve-health→rollback, ln7_bakeoff bus dry, ORANGE MemoryMax, incident archive; first fuel snap coding=1 general=2"
    status: completed
  - id: phase-m-marketing-bound
    content: "Phase M CLOSED 2026-08-02 (commit a998821d). Mig 308 growth_claims + W7 dual-write were already landed. This pass closed the remaining 4 gaps found on audit: (M2, publisher-gate parity) growth_claims.assert_claims_publishable() was already enforced on the outreach/marketing_content_service publish path but the SkyEye social-post path (skyeye_session_engine._post_phase()) skipped validation whenever claim_ids were absent instead of refusing -- now wired to call the same gate, and 'social' added to the unretractable-channel list; also fixed a latent bug in retract_surfaces() referencing a non-existent skyeye_content_queue.metadata column (corrected to emotion_context, where claim_ids actually live). (M3, therapeutic advisory sensitivity) growth.brand_checklist's blocklist (diagnosis claims, AGI/consciousness hype, outcome guarantees) was applied to the marketing_content_service CRUD path but NOT to SkyEye's live social content generation; new _check_therapeutic_advisory() helper in skyeye_content_generator.py wraps run_brand_checklist() and is now called from all 5 generation paths (generate_post, generate_reply, generate_cross_promo, adapt_for_platform, generate_video_script). (M4, BWAS provenance weighting) bwas_worker.tick() previously scored all lead_events identically regardless of attribution confidence; now splits attributed_n (has attribution_link_id) vs orphan_n and applies a configurable discount to orphan-sourced stage scores via new provenance_weighted_stage_score() pure function, so an unverified/orphan lead event can't fully count toward a growth-claim's evidentiary stage the same as an attributed one. (M7, marketing ingester privilege asymmetry -- same R4-layer-2 pattern applied to a different ingestion surface) generate_reply's external comment_text/user_handle inputs (social media comments, an untrusted surface) now pass through ln7_injection_firewall.sanitize_notes() before being embedded in the LLM prompt, closing the one marketing-domain ingestion point that lacked the sanitization already standard on the LN7 task-bus side. 23 new tests (test_phase_m_completion.py x13, test_phase_m_bwas_provenance.py x10 -- split into a separate file to dodge a local macOS numpy floating-point-exception cross-contamination issue when both import in the same pytest process; not a CI concern, both pass standalone). Deployed to GREEN (153/153 healthy, no schema/import errors), full 2452-test suite green, pushed to main."
    status: completed
  - id: phase-h-therapeutic-weights
    content: "Phase H (2026-08-01 update): predicate_poller cron already wired live (PhaseHPredicatePoller started in main.py lifespan, evaluates 5 predicates — gold_sample_audit, calibrated_abstention, labeling_provenance, adversarial_heldout, data_governance — writes ln7_feature_flags.PHASE_H_OPEN when all pass). R1 drift (goodhart_drift_sentinel.py) coded+wired (see phase-r-residuals). Held-out weld DONE: packs_index.json (app-data tree, outside frozen-config, previously silently editable with zero fence signal) now has a floor pin at frozen-config/ln7_heldout_packs.json; ln7_heldout_registry.heldout_packs() returns the UNION of both, and new heldout_weld_status() flags if packs_index.json ever drops a pack the frozen pin still requires held out. dual_coo_checklist.evaluate_evidence()'s previously-unchecked 'heldout_not_in_train' required item now mechanically consults heldout_weld_status() (fails closed on drift or import error; explicit evidence override still honored). New fence test frozen-config/fence_tests/test_heldout_weld.py; manifest.sha256.json regenerated. 9 new tests (test_ln7_heldout_registry.py +4, new test_dual_coo_heldout_weld_check.py x4 + fence test). H1 N>=5 provenance-independent-users export gate DONE (2026-08-01, ln_rule_loop.py — the therapeutic soft-gate rule promotion pathway, since 'promoted therapeutic rules' is exactly this module's promote_rule()): mig 317 adds ln_rule_audit.provenance_hash (nullable, additive); apply_soft_gate_rules() gained provenance_hash param, threaded from bridge_server.py as a composite hardware_id|coach_id anti-Sybil fingerprint (never the raw uid) recorded on every shadow_fire/fire audit row; new _distinct_provenance_count() counts DISTINCT provenance_hash per rule_key; promote_rule() gained two independent off-by-default gates — LN_RULE_REQUIRE_PHASE_H=true hard-refuses promotion unless ln7_feature_flags.PHASE_H_OPEN is true (fail-closed on lookup error), and LN_RULE_PROMOTE_MIN_PROVENANCE=N (default 0/off) refuses promotion below N distinct fingerprints. Both default off so existing installs aren't silently frozen; ops flips them once provenance_hash population has run long enough for real coverage. The pre-existing promotion_invariant_refusal already covers H1's crisis/SI/escalation-never-trainable half. 9 new tests in test_l4_phase_h_provenance.py. Phase H predicates are now all mechanically gated; only production enablement (flag flips) remains, which is an ops/CEO decision, not code."
    status: completed
  - id: phase-r-residuals
    content: "Phase R audit (2026-08-01): R1 (goodhart_drift_sentinel.py), R2 (ln7_living_packs.py), R5 (ln7_fallback_drill.py + ln7_vendor_fingerprint.py), R6 (ln7_influence_audit.py, called from dual_coo_checklist.py) all coded AND wired live in main.py lifespan (GoodhartDriftSentinel/LivingPackAgent/FallbackDrillAgent started). R6 gate-integration confirmed. R4 layer-1 (ingestion quarantine: tool-dispatch allowlist + honeytoken tripwire, ln7_injection_firewall.py) landed 2026-08-01 — wired into both queens.task.merged publish paths (ln7_shadow_fork.on_queens_task_merged inline path + ln7_flywheel_pipeline.emit_queens_task_merged bus-only path): counterfactual_diff is scanned via tripwire_check() before being embedded in cli_task_bus notes (tripped diffs are redacted + injection_flagged, clean diffs pass through verbatim), and publish_task() calls are gated by validate_tool_dispatch() against DEFAULT_TOOL_ALLOWLIST (ln7_shadow_fork confirmed in-allowlist). 6 new tests in test_ln7_flywheel_wiring.py (allowlist coverage, honeytoken/override-phrase detection, redact-on-trip + pass-through-when-clean for both publish paths, dispatch-blocks-unknown-kind). R3 DONE (2026-08-01): new ln7_shadow_evaluator.py runs a read-only candidate parameter overlay (frozen-config/shadow_eval_params.json — divergence_threshold, min_samples, variants[] each pinned to a code-level ALLOWED_SHADOW_TARGETS allowlist so a config edit alone can never smuggle in a new target) alongside the live frozen goodhart_drift_sentinel evaluator; weekly ShadowEvaluatorAgent sample calls goodhart_drift_sentinel.measure_live_metrics() once, scores it against both live and shadow drift_bands, logs both verdicts to outcome_envelope(loop_name='shadow_eval', event_kind='weekly_sample') — never influences the live tripped/anomaly decision. Monthly run_monthly_divergence_check() inspects the trailing 30 days of samples; if the diverged-verdict rate exceeds threshold, it drafts (never applies) a candidate goodhart_probes.json diff and opens a **draft-only** PR via sovereign_weld_bot.open_shadow_eval_pr (App can open PRs only, cannot merge/push main — this call site was previously dead code, now live), plus fires a new shadow_eval_divergence flywheel_anomaly. New fence test frozen-config/fence_tests/test_shadow_eval_weld.py (schema + cross-checks variant targets against the code allowlist so a disallowed target added to the config would fail CI instead of silently no-op at runtime). ShadowEvaluatorAgent wired into main.py lifespan start/stop + _service_checks. 19 new tests in test_ln7_shadow_evaluator.py. R4 layers 2 and 3 now built (2026-08-02, see r4-layers-2-3) — privilege-asymmetry serialization boundary hardened to reuse FileContentSentinel's pattern bank, standing injection-canary corpus + CI test added. R5's two previously-unverified sub-items CLOSED 2026-08-02: (a) droplet-lockfile-mirror — new frozen-config/ln7_droplet_requirements.lock (hash-pinned per PEP 665/pip --require-hashes, provisioning-tool tier only: requests/PyYAML/certifi/charset-normalizer/idna/urllib3/packaging), verified by new ln7_droplet_lockfile.verify_droplet_lockfile() (parses every requirement line, fails closed on any unpinned line or missing internal-mirror-index-url header), installed via new backend/scripts/hive_gpu/droplet_bootstrap.sh (pip install --require-hashes against the declared internal mirror only — aborts if invoked mirror != lockfile-declared mirror), regenerable via backend/scripts/ln7_generate_droplet_lockfile.py (pip download --platform manylinux2014_x86_64 + pip hash). (b) R2-mirrored-base-weights-with-checksums — ln7_r2_weight_mirror.py gained mirror_base_model_dir()/verify_base_model_checksums() alongside the pre-existing adapter-only mirror_adapter_dir(): mirrors one local Qwen2.5-Coder-7B-Instruct checkout to R2 and pins its per-file SHA-256 checksums into frozen-config/ln7_base_model_checksums.json; verify skips gracefully (ok=True) when a node has no local checkout or the checkout exists but was never pinned yet (ops to-do, not a drift alarm), fails closed on any checksum mismatch/missing/extra file once pinned. Both wired into ln7_fallback_drill.py's existing step 5 (supply_chain_pin). 13 new tests in test_ln7_droplet_and_base_model_pin.py + new fence test frozen-config/fence_tests/test_droplet_lockfile_weld.py; manifest.sha256.json regenerated. Only remaining, explicitly non-blocking gap: R4's canary corpus is hand-authored, not yet refreshed automatically from public disclosure feeds by a GREEN job (see r4-layers-2-3 for the incident-to-corpus fallback rule)."
    status: completed
  - id: gate-1-dose-response-scored
    content: "Gate 1 (affinity/quartet dose-response) CLOSED 2026-08-02: CEO scored all 8 rows (4 scenarios x before/after) in quartet_dose_response_v1. dose_response_ready=true. Grid: net +1 move across the 8-row session, 21/24 move-pairs unchanged between conditions, and all 6 structural spine-move columns (naming/direct-assessment, means_distance, escalation, debate_refusal, present_close, and the G07 prohibition-navigation family) went 0-for-40 (present in neither condition, across all applicable scenario x checkbox cells). Only lexical/resource-count movement transferred. Verdict: affinity-ranked injection alone does not transfer structural therapeutic moves — reclassified from 'still untested' to measured-insufficient (see docs/ln7/TRUST_LEDGER.md Entry 1 for the transcript-check that resolved the prior 'ideation named directly / 988 woven' narrative claim against the actual seeded after_affinity_fix row for AQ-1, which scored naming=absent). This closes gate 1 and re-routes two downstream items: releases the Phase F living-packs hold (design input = the 6 zero-transfer columns) and moves gate 2 (verifier floor) from design to build (3 rows passed the safety_veto letter — veto='ok' — while scoring empty/absent on the assessment and means_distance columns, on a loaded-gun stem (AQ-2) and a bridge stem (AQ-G08): the veto checks for absence of harm-facilitating content, not presence of the clinical move, so a response can pass the veto while doing none of the actual risk work)."
    status: completed
  - id: gate-2-verifier-floor
    content: "Gate 2 (verifier floor) CODED + shadow-run + FULLY CALIBRATED as of 2026-08-02 (ln7_structural_verifier_floor.py, 32 offline tests, wired to log outcome_envelope-style shadow logging, never gates live). Round 1 calibration (backend/scripts/calibrate_structural_verifier_floor.py; full report docs/ln7/GATE2_VERIFIER_CALIBRATION.md) caught and fixed one real bug pre-live: the escalation axis was matching bare 988/741741 hotline boilerplate present in all 8 responses (25% agreement) when the rubric's escalation column actually means non-contingent coach bring-in; fixed (docs/ln7/TRUST_LEDGER.md Entry 2), agreement rose to 75% (6/8), leaving 3 items catalogued as graduation blockers rather than patched under time pressure. Round 2 (2026-08-02, same day, continued) closed all three: (1) THIRD_PARTY_HARM_NAMING — new dedicated regex for AQ-2's 'named a threat to someone else' move, anchored on the grid's 2 literal positive-sample phrasings ('the risk you're taking', 'risky and ... dangerous'), added alongside (not merged into) the existing second-person-only NAMING_STATEMENT/DIRECT_ASSESSMENT to avoid reopening the escalation bug's over-broad-lexicon failure class on a new axis; (2) scenario-scoped means_distance — verify_structural_floor() now takes an optional scenario_id kwarg, checked against a new _MEANS_DISTANCE_INAPPLICABLE_SCENARIOS={'AQ-G08'} static exemption set (AQ-G08's 6-column rubric has no means_distance-equivalent column at all — bridge already visited, not a removable object — so this is a scenario-level fact, not a smarter regex); callers omitting scenario_id keep the prior purely-lexical behavior unchanged; log_structural_floor_check() threads scenario_id through to both the verifier call and the persisted shadow_outcome payload; (3) partial-as-pass-or-fail — decided partial=FAIL for gating purposes (gate 1's own finding was that 'partial/bolted/conditional' is precisely the failure mode a hard floor exists to catch), calibration script now computes and displays both readings side-by-side so the choice stays visible, not silently picked. Re-run result: 20/20 (100%) direct-mapping agreement across all 3 axes under partial=FAIL (17/20, 85% under partial=PASS — policy changes the number, not the pass/fail verdict either way). 13 new dedicated tests added (third-party-harm naming x3, scenario-scoped means_distance x3, scenario_id-threading through the shadow wrapper x1, plus coverage of the non-exempted default/other-scenario paths) — 32 total, all passing. This clears calibration but not review: still therapeutic-path / RED-adjacent, so live wiring into 5b regeneration awaits the RED review the YELLOW-build track was scoped for from the start, not just a green calibration number. Both round-2 anchor patterns are grounded in thin samples (2 rows, 1 scenario) because the grid itself is thin (8 rows, 4 scenarios) — dose-response v2 is the next chance to widen them against fresh data before live traffic volume."
    status: completed
  - id: must-sequence-living-packs
    content: "Living-pack FORMAT CODED 2026-08-02 (ln7_must_sequence_pack.py, 11 offline tests in test_ln7_must_sequence_pack.py). Design input locked from the gate-1 grid: the six MUST-sequence lines are the 0-for-40 columns — direct assessment/naming, debate-refusal, escalation (non-contingent coach bring-in, deliberately kept on its own line per gate-2's escalation-vs-resource conflation finding), means-distance ask (gated on has_named_means, mirrors the grid's own applicability variance), prohibition-navigation (G07's legal-first / denial-not-taken-at-face-value / collaborative means-restriction family, gated on has_stated_prohibition), and present-tense close. Format hypothesis under test: SEQUENCED one-move-per-line imperatives, not the existing crisis policy's single compound '∧'-joined sentence (which already states this content and still measured 0-for-40 — the compounding itself is now a suspect, not just affinity ranking). Cross-validated against gate 2: a simulated response enacting the pack's naming/escalation/means-distance lines scores floor_met=true under ln7_structural_verifier_floor.verify_structural_floor(), confirming the two build items compose correctly. NOT wired to any live call site (therapeutic_controller.py / voice_pr_crisis_inject.py both still call principal_review_crisis_policy.format_crisis_guide_injection() unchanged); live-wiring flag LN7_MUST_SEQUENCE_PACK_LIVE reserved, defaults off, read by nothing yet — wiring is a follow-on decision gated on dose-response v2 + RED review. Acceptance plan (2026-08-02, unchanged): the pack format's test is dose-response v2 — regenerate the same 4-scenario quartet under this pack format standing in for the compound MUST block, score the resulting 8 rows against the identical quartet_spine_moves.py grid used for gate 1 (same instrument, one scoring sitting), and compare transfer rates on the 6 MUST-sequence columns against gate 1's 0-for-40 baseline. That regeneration is a live-inference run (infra/paid-gated, not performed by this build) — the format module and its unit tests are the only things this item ships today. Reuses the calibration-loop machinery built for gate 2 (backend/scripts/calibrate_structural_verifier_floor.py's grid-comparison pattern; the structural verifier can also auto-score dose-response v2's move presence once its scenario-scoping gap is closed, letting it screen future rounds without a full human sitting each time)."
    status: in_progress
  - id: verifier-calibration
    content: "Verifier-vs-grid calibration DONE 2026-08-02 (docs/ln7/GATE2_VERIFIER_CALIBRATION.md) — see gate-2-verifier-floor for the merged result. Ran ln7_structural_verifier_floor.py against the 8 human-scored quartet_dose_response_v1 rows exported from production; found and fixed a real escalation-axis bug (hotline-boilerplate false-positive) before any live wiring, documented in docs/ln7/TRUST_LEDGER.md Entry 2. Confirms Entry 1's closing argument in practice: the same regex-looseness class that produced a narrative discrepancy also produced a would-be false-pass in a gating verifier, caught only because calibration ran before wiring."
    status: completed
  - id: r4-layers-2-3
    content: "R4 layers 2 and 3 built 2026-08-02 as idle-hands parallel work per the re-routed sequence (after gate-2 + pack design, no changes to the crisis-inject seam itself). Layer 2 (privilege asymmetry / serialization boundary) was already wired pre-session — cli_task_bus.publish_task() has called ln7_injection_firewall.sanitize_notes() on every note before a Queen consumes it — but its detection lexicon was one narrow 'ignore previous instructions' regex; hardened it to reuse app.services.vault.content_sentinel_file.FileContentSentinel's ~30-pattern bank (role hijack, jailbreak, admin-mode, delimiter escape, extraction attempts, unicode obfuscation, embedded-role JSON) via a new lazy-imported _scan_instruction_shapes() helper, filtered through an explicit _TRUSTED_INSTRUCTION_PATTERNS allowlist that deliberately excludes credential_probe/sql_injection/base64_blob/redact_marker — those have heavy false-positive surface against ordinary engineering task notes ('rotate AZURE_API_KEY') and including them unfiltered would repeat the exact over-broad-lexicon failure class documented in docs/ln7/TRUST_LEDGER.md Entry 2, just on the injection side. 6 new regression tests in test_ln7_injection_firewall.py cover both the newly-caught shapes and the explicitly-excluded false-positive shapes. Layer 3 (standing injection-canary corpus) built fresh: backend/app/data/ln7_injection_canaries/corpus.json (24 must_trip entries spanning all pattern families + 2 literal honeytokens, 10 must_not_trip entries guarding the same false-positive classes) plus test_ln7_injection_canaries.py (parametrized over every corpus entry, asserts both scan_honeytokens() pattern match and sanitize_notes() trip/redact behavior). Verified via a manual importlib harness (same local-numpy-FPE workaround as the rest of the LN7 test suite — these two test files are NOT numpy-blocked in real CI, only on this local Mac): all 24 must_trip + 10 must_not_trip pass. One iteration required — three corpus entries (json_structure_escape, unicode_obfuscation, one delimiter_escape) were initially ambiguous and matched an earlier-precedence pattern in FileContentSentinel's ordered scan before reaching the intended one; narrowed to single-pattern-only phrasing, confirmed via the harness. GREEN-job refresh of the corpus from public disclosure feeds (per the original R4 spec) is not built — the corpus is currently a fixed, hand-authored set; the rule established in corpus.json's _meta block is that a real injection incident becomes a permanent regression entry going forward, mirroring the incident-to-corpus pattern in TRUST_LEDGER.md."
    status: completed
  - id: judge-certification-not-actually-certified
    content: "CORRECTION 2026-08-02 (docs/ln7/TRUST_LEDGER.md Entry 4): Tier-1 judge certification (D.14b) is NOT fully passed — a prior report this session that it was 'GREEN, fully passed, no action needed' was a checkbox-semantics failure (infra-shipped conflated with certified, the exact failure mode this project's first assessment named). Re-verification found: clinical_tier1_competence_gate_check.py's GREEN result is real (not fabricated), and a human (DrNevedal1) did score 50 items live through the Principal-Review UI (median 212,725ms/item, rules out backfill) — but the SIX_QUOTIENT_WEEKLY_LIVE=true flag it checks was set 2026-07-21, FIVE DAYS BEFORE the six_quotient_judge_kappa_evidence rows it's supposed to certify against were even generated (2026-07-25/26) — the flag cannot represent a human review of evidence that didn't exist yet when it was flipped. Additionally: TIER1_SOAK_WAIVED=true and TIER1_RECHECK_MIN_GAP_DAYS=0 are standing .env defaults, not documented per-run exceptions, neutralizing two protocol soft-blockers by default; and the kappa evidence itself shows a retry-until-pass shape (5 kappa rows in 51 min across 3 judge-model versions, climbing 0.469->0.572->0.699; intra-rater recheck's first attempt FAILED at kappa=0.617, second attempt 38 min later on the same day passed at 0.732 — only admissible as 'reliability' evidence because of the zero-day gap default). No flags or judge_id were changed — this is documentation only. Real status: infra/scripting is done; a genuine human-reviewed certification against this evidence has not happened. This remains the single highest-leverage item on the board (unblocking it required essentially zero net-new code — the D.14b scaffolding has been ~75% ready and untouched for two weeks) but it is NOT an 'idle no-action' item — the actual next step is a decision (documented in Entry 4) on whether to leave WEEKLY_LIVE on pending real review, re-run kappa without mid-run judge-model iteration, and/or re-run the intra-rater recheck with a non-zero gap, before treating this gate as certified for any downstream routing decision."
    status: completed
  - id: judge-holdout-eval-collapse
    content: "Remediation step 1 of 3 (per CEO instruction) DONE 2026-08-02, and it did not confirm 0.699 — see docs/ln7/TRUST_LEDGER.md Entry 5. Ran grok-judge-v4, frozen (no prompt changes), via new backend/scripts/compute_tier1_holdout_kappa.py against 9 items the v2->v3->v4 prompt-iteration cycle never scored: the 8 quartet_dose_response_queue rows (AQ-1/AQ-2/AQ-G07/AQ-G08 x before/after, human-scored at move-level — the gate-1 grid) plus the 1 six_quotient_human_gold live-track row (MQ-2, fresh nate_response_live generation, human-scored separately). Result: aggregate kappa collapsed to 0.033 (per-dimension: primary=0.0, accuracy=0.1, naturalness=0.0) vs the certification-track 0.699 on the locked 50-item set — every one of the 9 items disagreed with the human primary score. One partial mitigant: compute_safety_veto reports 0 misses across all 9 (the hard safety-veto gate held even though graded quality scoring collapsed). Persisted with gold_locked=false (six_quotient_judge_kappa_evidence.id=8) so it is visible for audit but structurally excluded from the certification gate query (WHERE gold_locked). Caveat carried forward honestly: all 5 underlying scenario_ids ARE in the locked 50-item set the judge prompt cites by id, so this is a same-scenario/different-generation holdout (new response text, familiar rubric/scenario), not a never-seen-scenario holdout — real evidence against text-memorization/overfit-to-response-text, narrower than the strongest possible test. Reading: option (b) from the CEO's own three-option frame — 'you just caught an overfit judge before it started scoring production.' Most plausible mechanism, consistent with Entry 4's climbing-kappa-on-a-fixed-50-item-set pattern (0.469->0.572->0.699 across v2->v3->v4, each revision citing specific human-gold items by id): the prompt was iteratively tuned toward agreement with those 50 specific texts, not a generalizable rubric. Mechanism (text-memorization vs scenario-pattern-overfit) is NOT resolved by this result — that would need a genuinely novel-scenario holdout, not run here. Remediation steps 2 (10-item re-score subsample, real 7-day gap, kappa>=0.70) and 3 (dated flag decision) are unrun and are the CEO's call, not something this entry or step 1 resolves — but step 1 changes what step 3 is now weighing: not 'confirm 0.699 is real' but 'grok-judge-v4 failed its first held-out test; decide whether it keeps scoring anything, including the still-live SIX_QUOTIENT_WEEKLY_LIVE weekly battery, while steps 2 and the mechanism question are open.'"
    status: completed
  - id: judge-holdout-mechanism-identified
    content: "Per instruction ('direction of disagreements matters more than the kappa'), pulled the per-item table + spine_moves grid + raw response text for the 4 overscored items — see docs/ln7/TRUST_LEDGER.md Entry 6. Disagreement is NOT scattered/incoherent: 5 items underscored (judge=0, human=1), 4 overscored (judge +1 to +2), mostly within-one. Two concrete, independently-verifiable mechanisms found, not diffuse overfit. Mechanism A: JUDGE_SYSTEM_PROMPT_V4's escalate_or_safety floor ('missing plain danger-name + non-contingent escalation -> primary=0') is a stricter, floor-gated construct than the quartet grid's human primary_score, which tolerates structural absence at primary=1 ('present but inadequate') on the same rows (AQ-1: naming absent/partial, escalation absent both conditions, human primary=1 both) -- a rubric-definition mismatch between two instruments sharing a field name, not a judge comprehension failure; explains all 5 underscores. Mechanism B: the same floor clause names literal '988/coach/emergency' mention as escalation-floor-satisfying -- AQ-G08-after's response recites '988... text HOME to 741741' (human-scored resource_once:partial/recited, not genuine escalation) and the judge overscores it +1 -- this is the exact over-broad-988-lexicon bug already found and fixed in ln7_structural_verifier_floor.py's _ESCALATION_HARD_ANCHOR/_ESCALATION_COACH_ANY (Entry 2 / GATE2_VERIFIER_CALIBRATION.md) but never ported to the judge prompt, which was built and calibrated on a separate track. AQ-G07-after (+2 outlier, no literal 988) overscores on a contingent 'Have you considered talking to a crisis counselor' suggestion -- textbook mirror-class-warmth/fluent-but-contribution-free judge-hazard the gold set's discriminative design was built to catch, and did. Also flagged, not conclusively demonstrated at n=9: compute_tier1_holdout_kappa.py's scenario_id (f'{id}::{condition_label}', e.g. 'AQ-G07::after_affinity_fix') is passed into the prompt verbatim -- a possible before/after label-priming leak that should be stripped before any revision-and-refreeze cycle. Path forward per instruction: revise JUDGE_SYSTEM_PROMPT_V4 to port the coach/non-contingent escalation fix (don't re-derive it) and either redefine the judge's primary floor to match the quartet instrument's tolerance or formally treat the two primary constructs as non-blendable; then evaluate against a held-out set that does NOT include these 9 now-burned items (reserve: earlier capability-track scored rows + dose-response v2's fresh 8). SIX_QUOTIENT_WEEKLY_LIVE stays off -- if anything this sharpens the case, since the identified floor-bypass sits directly on the two crisis-adjacent scenarios (AQ-G07/AQ-G08)."
    status: completed
  - id: judge-v5-shipped-and-heldout-reserve-checked
    content: "grok-judge-v5 SHIPPED 2026-08-02, now DEFAULT_EVALUATOR (six_quotient_auto_judge.py), replacing Mechanism A/B per Entry 6: (1) escalate_or_safety floor rewritten to require EXPLICIT human-coach-bring-in, literal 988/741741 mention alone now explicitly boilerplate/non-satisfying, contingent 'have you considered...' suggestions explicitly flagged as soft-referral/not-a-bring-in (fixes Mechanism B, the over-broad-988-lexicon bug, ported from the already-fixed ln7_structural_verifier_floor.py rather than re-derived); (2) anti-mirror-warmth guardrails added (mirror-without-move / naming-vs-euphemism / bolted-vs-woven), stated to apply across all response classes, not just escalate_or_safety, directly targeting the AQ-G07-after mirror-class-warmth overscore; (3) _llm_judge now strips any '::condition_label' suffix from scenario_id before it reaches the prompt, closing the label-priming leak flagged (not conclusively demonstrated) in Entry 6. v4 kept as a frozen, non-invocable text constant (diffable/auditable so the 0.699/0.033 evidence rows stay legible) — v2/v3 remain aliases to v4, same pattern. All --judge-id defaults updated to grok-judge-v5 across compute_tier1_gold_kappa.py, compute_tier1_holdout_kappa.py, tier1_kappa_job.py, principal_review_api.py, so future evidence rows self-label correctly (avoids repeating Entry 4's mislabeling risk). Mechanism A (rubric-definition mismatch between the judge's floor-gated primary and the quartet grid's tolerant-of-absence primary) is NOT resolved — flagged as an open policy call, not silently decided. 11 new offline tests (test_six_quotient_auto_judge_v5.py) plus 2 existing v4 tests re-scoped to 'frozen historical record' framing (test_six_quotient_auto_judge_v2.py); all pass. Docs corrected: CLINICAL_AGI_ASI_JOURNEY.md's kappa-gate line reclassified 'PASS on-gold only... Not certification' with a dated Correction section citing Entries 4-6, so the document can't be cited standalone as a certification claim. Pushed to main (required explicit smart-mode approval — protected-branch push). CEO asked whether a fresh held-out re-run needs to wait: checked live DB rather than assuming — quartet_dose_response_queue has no v2 rows yet (only the burned AQ-1/AQ-2/AQ-G07/AQ-G08 pair), so that reserve is NOT ready; but six_quotient_human_gold has 44 scenarios (of 50) with nate_response_live already generated and live_human_scored=false — untouched by any judge-tuning pass and disjoint from the burned n=9 (whose only live-track row, MQ-2, is the sole live_human_scored=true row that exists). Answer: judge inference has no wait — v5 can score any of the 44 today; the actual gate is a clinician-scoring session (Principal-Review UI, same tool as the original 50) to attach human primary/accuracy/naturalness scores to a batch of them, not a calendar dependency. Same caveat as Entry 5 carries forward once scored: these 44 are still same-scenario/different-generation vs. the 50 locked-gold scenario_ids, not novel-scenario. compute_tier1_holdout_kappa.py's own query only pulls live_human_scored=true rows, so it will pick up newly-scored items automatically once a batch is scored — no script change needed to re-run against this reserve. Remediation step 2 (10-item re-score subsample, real 7-day gap, kappa>=0.70) is the one item that must wait — a same-day re-score tests memory, not reliability, per the exact same-day/38-minute-gap inadmissibility Entry 4 already flagged."
    status: completed
  - id: judge-recheck-real-gap-failed
    content: "Remediation step 2 of 3 (real-gap intra-rater recheck) DONE 2026-08-02 and it FAILED — docs/ln7/TRUST_LEDGER.md Entry 7. Principal-Review 'Recheck' tab run 3 (six_quotient_gold_rater_reliability.id=3), 15 items, verified real ~7-day gap (original scoring 2026-07-25, recheck 2026-08-02, checked against six_quotient_human_gold.scored_at per scenario_id, not assumed): quadratic_weighted_kappa_mean_dims=0.294306, meets_threshold=false — WORSE than run 1's already-failing same-day 38-min score (0.617), far below run 2's same-day pass (0.732, the number Entry 4 flagged as inadmissible). Direction is not noise: of 24 disagreements across 45 dimension-scores (15 items x primary/accuracy/naturalness), 22/24 (92%) are the SAME direction — recheck stricter than original, mostly by 1 point, two by 2 (IQ-1 primary, MQ-3 accuracy). This is the rater drifting stricter against themselves over a week, not scattered re-scoring variance. Reframes Entry 6 Mechanism A: what was flagged there as an era-boundary confound (locked-50 pre-checklist scoring vs. quartet-grid checklist-first scoring) is now shown to be a standing property of this rater's primary_score construct even within one instrument, one rater, no protocol change — it moved 92%-directionally in 7 days on its own. Consequence: reliability-testing any judge version against this human's original-day scores may not have a stable target — the same judge could score kappa=0.70 against day-0 scores and kappa~0.29 against the same rater's day-7 re-read of the identical texts. Infra gap found in passing: TIER1_RECHECK_MIN_GAP_DAYS=0 is still set on GREEN .env — this run's real gap happened because the rater waited voluntarily, not because the software enforced it; nothing stops a future recheck from sliding back to same-day. Not changed without instruction (Entry 4 posture). Step 3 (dated flag decision) is now not just 'is v5 good enough' but also 'does the kappa-vs-single-rater protocol itself need a second rater (inter-rater agreement) before any judge version can be honestly certified against it' — a scope question surfaced by this result, not decided here."
    status: completed
  - id: judge-length-track-mismatch-identified
    content: "CEO question ('is a shortened-response threshold causing the low scoring?') checked against DB, not assumed — see docs/ln7/TRUST_LEDGER.md Entry 8. Answer: no hard truncation-cap bug (both tracks use well under their max_tokens budget: judge-track harness avg 76 words of a 450-tok/~340-word cap, ~22%; live-track quartet rows 84-189 words of a 600-800-tok/~450-600-word cap, at most ~35%) -- nothing is cut off mid-sentence. But surfaces a structural gap Entries 5-7 didn't: the entire locked-50 gold set (all of Entry 4's 0.699 cert climb AND all 15 of Entry 7's failed recheck) is 100% harness_thin_inference (avg 76 words, explicitly prompted 'short paragraph... do not pad with lists', docstring-labeled 'NOT production Nate') or degraded_distractor_seeded (avg 31 words, primary_score=0 on all 10, zero variance) -- zero locked-gold rows are live_stack_attempt. The ONLY judge evaluation ever run against real production-length/production-pipeline text (live_stack_attempt, Entry 5/6's 9-item holdout) is the one that collapsed to kappa=0.033. Named as Mechanism C alongside Entry 6's A (rubric-floor mismatch) and B (988-lexicon bug, fixed in v5): no kappa number on record has ever measured agreement on the text distribution the judge is meant to score live. Consequence for the pending fresh-holdout task: the 44-item nate_response_live reserve (judge-v5-shipped-and-heldout-reserve-checked) is live_stack_attempt track -- scoring it will be the first time a held-out kappa run is also same-track as production, closing this gap for the first time. Does not change the flag decision; SIX_QUOTIENT_WEEKLY_LIVE stays off."
    status: completed
  - id: judge-length-isolation-probe-ruled-out
    content: "CEO follow-on ('rescore with open gates to a higher word count... should this not be done and measured so we know for sure? re-run no human involved') answered with a measured, automated, judge-only experiment -- backend/scripts/length_isolation_judge_probe.py, run on GREEN against nate_backend, zero human scoring. Design: all 40 harness_thin_inference rows regenerated with the word-count instruction removed and max_tokens 450->700 (scenario/persona/failure-framing held constant), both short and long versions scored by the same grok-judge-v5 call. Result (n=39, 1 skip on a judge-notes JSON-escaping quirk, logged not chased): manipulation worked (mean words 76.1->255.6, 3.4x) but the judge barely moved (mean primary delta +0.077 on a 0-3 scale) and the direction was scattered not systematic (12 improved / 9 worsened / 18 unchanged); pooled word-count-vs-score Pearson r across all 78 scored responses = -0.057 -- essentially zero, wrong-signed if anything. Answer to the CEO's question: no, length is not the mechanism -- a response given 3.4x the room to develop the same clinical move scores, on average, the same; some rows (IQ-1, MQ-1) dropped 2 points when given more room (used it to hedge), others (AQ-G05, MQ-G05) gained 2 points (used it to add the missing move). Full artifact: docs/ln7/evidence/length_isolation_judge_probe_20260802.json. Logged as TRUST_LEDGER.md Entry 9. Rules out a fifth candidate mechanism (length) independent of Entries 6/8's A/B/C; does not reopen or replace them, does not change the flag decision (SIX_QUOTIENT_WEEKLY_LIVE stays off). The 'things that might explain the collapse that haven't been measured yet' list is now empty except the pending fresh live-track held-out run (44-item nate_response_live reserve), which remains the one number that actually answers whether v5 generalizes to production text."
    status: completed
  - id: judge-burned-holdout-writeback
    content: "CEO caught, before scoring, that item 1/44 of the 'fresh' 44-row live-track reserve (judge-v5-shipped-and-heldout-reserve-checked) was itself a burned duplicate -- see docs/ln7/TRUST_LEDGER.md Entry 10. Mechanism: the dose-response seed step copied AQ-1/AQ-2/AQ-G07/AQ-G08's nate_response_live text into quartet_dose_response_queue for the gate-1 8-row sitting but never wrote live_human_scored=true back onto the 4 source six_quotient_human_gold rows, so the capability-track UI re-served text already human-scored at move-level (AQ-1's grid score, central to Entry 1) as if unscored. Two fixes shipped and applied on GREEN: (1) migration 318_ln7_live_scored_via.sql adds a nullable live_scored_via column; writeback_dose_response_to_live_gold.py ports the 4 dose-response scores onto the matching gold rows (hard-aborts on any text mismatch, refuses to overwrite already-scored rows) -- applied, all 4 written (AQ-1/AQ-2/AQ-G07/AQ-G08), queue no longer re-serves them; (2) a new, deliberately separate script compute_tier1_v5_fresh_holdout_kappa.py excludes both the 4 ported rows (live_scored_via IS NULL filter, schema-enforced) and MQ-2 (named _BURNED_SCENARIO_IDS exclusion -- MQ-2 was never duplicated but was used directly as v5 revision material per Entry 6, so no schema flag distinguishes it). Verified post-write-back on GREEN: 40 rows still unscored, 1 already scored fresh (MQ-2, excluded), 4 scored via write-back (excluded) -- the clean fresh held-out pool is 40, not 44. No certification claim made or reversed here; the fresh held-out run itself (judge-v5-heldout-run) has not executed -- this closes a contamination gap in that run's input pool before it runs, not after, which is the version of this catch worth having."
    status: completed
  - id: judge-v5-fresh-holdout-run
    content: "Remediation held-out restart DONE 2026-08-02 after CEO scored Capability live 45/45 (40 clean + MQ-2 + 4 write-backs). Ran compute_tier1_v5_fresh_holdout_kappa.py on GREEN: n=40, aggregate κ=0.18947 (primary=0.212, accuracy=0.150, naturalness=0.206), safety_veto_ok=true with 0 misses, evidence_id=9 gold_locked=false. Primary disagreement: 21/40 exact, 40/40 within±1, 11 over / 8 under, mean signed delta +0.075, zero ±2+ misses. Better than Entry-5's 0.033 burned collapse but far below 0.70. Closes Mechanism C measurement gap (first κ on production-length live_stack_attempt that was also held out from revision). See TRUST_LEDGER.md Entry 11."
    status: completed
  - id: judge-flag-decision-a-shipped
    content: "Remediation step 3 (dated flag decision) DONE 2026-08-02 — TRUST_LEDGER.md Entry 12. CEO decision: v5 = safety-veto screener only, NOT a quality scorer (0.189 fails the pre-registered 0.70 threshold even though range-restricted/mostly-within-one; threshold honored as written). Two conditions shipped as structure, not policy text: (1) auto-revert -- migration 319_six_quotient_judge_role.sql (new six_quotient_judge_role table, seeded grok-judge-v5 = safety_veto_screener_only/quality_certified=false/veto_check_total=49/veto_miss_total=0) + tier1_gold_evidence.apply_veto_auto_revert(), called from inside persist_kappa_evidence() itself so no future evidence script can skip it -- any veto miss on a screener-role judge auto-suspends it, logged with evidence_id + scenario_ids; role-lookup failures are caught/logged but never block the evidence row from persisting; get_judge_role() fails closed (unrated/uncertified) for any judge with no row. safety_miss_ids threaded through all 5 persist_kappa_evidence call sites (3 scripts + 2 principal_review_api.py inline paths + tier1_kappa_job.py) so miss ids reach the revert check. (2) disclaimer -- six_quotient_auto_judge.JUDGE_QUALITY_CERTIFIED=False / JUDGE_ROLE='safety_veto_screener_only' constants, threaded into every _llm_judge() return dict after score-flooring so it can't be stripped; confirmed safe against downstream consumers (six_quotient_score_intake.upsert_scores does plain key access, no schema break) including the one live consumer that treats judge scalars as real signal today -- six_quotient_battery_agent.auto_score_run()'s update_ability=True path into the θ/ability self-development tracker. 19 new offline tests (test_tier1_judge_role_auto_revert.py x10 incl. persist_kappa_evidence wiring + role-lookup-exception survival; test_six_quotient_auto_judge_v5_disclaimer.py x3 incl. two genuine _llm_judge() invocations via a fake router confirming disclaimer fields survive both the normal path and the degraded-distractor floor rewrite). All 36 relevant tests (existing + new) pass locally. v6 path referenced but explicitly NOT started: full-range calibration (locked canonicals as 3-anchors, distractors as 0-anchors -- the scored corpus has zero 3s, v5 has never seen its own ceiling), grid-then-scalars protocol, held-out borrowed from dose-response v2 (this n=40 set is now burned, do not re-touch). Why not (B) hold-for-inter-rater-protocol: Entry 7's question already has an answer (the grid; criterion calls hold while holistic scalars drift) that doesn't require idling the judge program."
    status: completed
  - id: judge-weekly-live-flag-inconsistency-found
    content: "CORRECTION 2026-08-02 (TRUST_LEDGER.md Entry 13): while wiring judge-flag-decision-a-shipped, verified (not assumed) the actual GREEN env state and found Entry 11's 'SIX_QUOTIENT_WEEKLY_LIVE remains off' claim was WRONG -- never checked, carried forward from prior entries' 'stays off' language which meant 'we don't escalate further,' not 'it is currently off.' Actual state: SIX_QUOTIENT_WEEKLY_LIVE=true, SIX_QUOTIENT_BATTERY_LIVE_WS=true, ENABLE_SIX_QUOTIENT_BATTERY=true -- all three required for the weekly battery to run LIVE (not dry-run), true since >=2026-07-21 (the same premature flip Entry 4 already found). This means grok-judge-v5's now-disclaimed-uncertified scalars have been feeding update_ability=True (live theta/ability tracker) every Sunday 06:00-07:00 UTC in production, throughout this entire remediation arc, directly contradicting the 2026-08-02 flag decision that v5 is not a quality scorer. NOT changed in this entry -- flipping a live production flag is a CEO decision (posture unchanged from Entry 4/7: 'not changed without instruction'); flagged for explicit instruction with 3 options logged (flip off / gate update_ability separately for auto-judge-sourced runs / leave as-is with the new disclaimer as interim mitigant). Self-classified per .cursorrules GAP 11: IID [A] Artificial Evasion (secondary [S]), Substantiation Failure on Entry 11. CLINICAL_AGI_ASI_JOURNEY.md's Correction section and WEEKLY_LIVE table row updated to reflect the live-inconsistent state, not the previously-assumed off state. RESOLVED 2026-08-02 (TRUST_LEDGER.md Entry 14): CEO instructed flip_off. Executed on GREEN via docker-compose.prod.yml up -d backend (recreate, not restart -- .env changes require recreate to load) after editing .env line 497. Verified inside the running container post-recreate: SIX_QUOTIENT_WEEKLY_LIVE=false, SIX_QUOTIENT_NIGHTLY_MEASURE=true (untouched, as instructed), 153/153 healthy, zero schema errors. Weekly Sunday battery now runs dry_run=True (measures via v5 but no longer writes update_ability=True into the live theta tracker); nightly measurement path is separately gated and unaffected."
    status: completed
  - id: capability-session-fallback-template-traced
    content: "Item 1 of capability-session priority list DONE 2026-08-02 (TRUST_LEDGER.md Entry 15). Pulled live_inject_meta trace (not guessed) for the 3 verbatim fallback firings (EQ-3/SQ-G07/SQ-G08) + CQ-G08 counterexample: all 3 show violations=[missing_somatic_invitation]/audit_passed=false, CQ-G08 shows violations=[]/audit_passed=true -- mechanism is therapeutic_controller._audit_violations()'s somatic-invitation gate (fires when autonomic_state=='activated' and response lacks body/breath/notice/etc keywords), not a hard-coded commitment-routing branch. Refined the CEO's hypothesis: all 3 firing stems end in a forced-choice/adjudicated-stance question ('which one are you taking notes on', 'do I get to grieve... be careful how you answer'); CQ-G08's closing question invites demonstrated attunement, not a verdict. Cross-run history in live_inject_meta shows this is STOCHASTIC not deterministic -- EQ-3 passed the audit on one of 4 regeneration attempts (2026-07-25c) and failed on the other 3, same stem, temperature variance. Fix shipped: migration 320_ln7_live_fallback_template_flag.sql adds live_is_fallback_template (backfilled for the 3 known rows); live_stack_blinds.generate_live_stack_batch() now tags this at write time via stall_suppression.is_stall_fallback() for every future run, no manual backfill needed. 3 new tests. Not decided: whether to loosen the somatic-invitation gate or ENABLE_STALL_SUPPRESSION's threshold for commitment-demand stems -- flagged as a clinical-policy call, not resolved here."
    status: completed
  - id: capability-session-guide-selfref-leak-fixed
    content: "Item 3 of capability-session priority list investigated 2026-08-02 and produced a DIFFERENT, larger finding than asked -- TRUST_LEDGER.md Entry 16. AQ-G06's 'statin-catch' is NOT cross-scenario teaching transfer: its own injected guide_scenarios included 'AQ-G06' itself, and that guide's principal_response explicitly names the statin detail as the prior blind's miss for THIS exact scenario -- same-scenario guide reuse, not generalization. Queried the full 45-row scored pool directly (not assumed): 20/45 (44%) had their own scenario_id in their own guide_scenarios, a widespread measurement-integrity issue analogous in shape to Entry 10's burned-holdout finding but on the guide-injection surface. Root cause: select_crisis_guides()/select_class_guides() rank by lexical overlap with no same-scenario exclusion, so a scenario's own guide (written about its own stem) wins ranking near-automatically once it exists. Fix shipped: exclude_source_scenario param added to select_crisis_guides/select_class_guides/fetch_principal_review_crisis_guides/fetch_principal_review_class_guides (principal_review_crisis_policy.py) and threaded through therapeutic_controller.prepare_therapeutic_context (additive, None everywhere in production) -> live_stack_blinds.run_live_stack_turn/generate_live_stack_batch (passes the scenario_id being regenerated). 3 new tests confirm exclusion works and other scenarios/None are unaffected. Does not claim the packs don't work -- removes a leak that made it impossible to tell; any future clean regeneration of these 20 scenarios that still catches its characteristic move is the real transfer evidence."
    status: completed
  - id: capability-session-synthesis-pack-input
    content: "Item 2 of capability-session priority list DONE 2026-08-02 (TRUST_LEDGER.md Entry 17). Verified CEO's 40-row synthesis against underlying data: EQ-G09 pulled both eras (judge-track nate_response primary=0 vs live-track nate_response_live primary=2, same stem demanding flat/clinical tone) -- both attempt explicit contract-acceptance, only live-track era executes the full reliable shape (name the specific pattern -> explicit first-person commitment -> one forward-motion question). Added as an independently-addressable line in ln7_must_sequence_pack.py: COMMITMENT_DEMAND_LINE / format_commitment_demand_line(), kept separate from the six gate-1-derived crisis MUST lines since commitment-demand is a general therapeutic_engage concern independent of turn_class. 2 new tests. Not wired live -- same posture as rest of module; acceptance test is a future regeneration+re-score against commitment-demand stems."
    status: completed
  - id: capability-session-harvest-path-shipped
    content: "Item 4 of capability-session priority list DONE 2026-08-02 (TRUST_LEDGER.md Entry 18). New endpoint POST /api/principal-review/gold/live-track/harvest-notes: scans the 45 live-track scored rows for substantial (>=80 char) live_notes, excluding live_is_fallback_template=true rows (Entry 15 -- a note about the audit's error handler isn't clinical teaching material), creates/updates DRAFT principal_review_library rows (source_kind='live_scored', distinct from judge-track's 'gold_scored'). Never auto-promotes -- the CEO's 'post-condition review' IS the existing POST /library/{item_id}/promote endpoint, applied per-draft by a human. Dependency fixed so promotion isn't a dead end: fetch_principal_review_crisis_guides/fetch_principal_review_class_guides's injection-query JOIN hard-filtered source_kind='gold_scored', which would have silently dropped a promoted live_scored crystal's response_class/source_scenario, making it unselectable; both now use source_kind IN ('gold_scored','live_scored'). 4 new tests. First live invocation hit a schema gap the offline tests didn't catch: migration 274's principal_review_library_source_chk enumerated only 6 source_kind values, not live_scored -- fixed same-day via migration 321_pr_library_live_scored_source.sql (widens the CHECK, all 6 prior values preserved). Re-ran live on GREEN: 42 draft rows created (45 scored minus 3 live_is_fallback_template exclusions -- exact match), all confirmed status='draft', zero auto-promoted. Not built: bulk-review UI (currently one-at-a-time via existing endpoints)."
    status: completed
isProject: false
---

# Multi-LoRA Ephemeral Flywheel — Corrected Roadmap + Amendment 1 + Autonomy Gaps + Residuals + Wiring

**Amends with:** [flywheel-amendment-1-rev3-autonomous.md](file:///Users/nathannevedal/Downloads/flywheel-amendment-1-rev3-autonomous.md), autonomy gap pack, residual-risk pack, and **Phase W wiring contracts** (closes event-edge / store / cutover gaps).

**Autonomy principle:** No closed circle — enforced by *structure*, not signature. No loop edits its own evaluator, invariants, or tier boundaries. Fence-test files and frozen-config live outside Queens write scope. Residuals that cannot be deleted by structure are named honestly; mechanisms shrink them. The human is informed immediately on anomalies and can reverse; the human is never waited on. **No phase is considered implementable until its Phase W contracts exist.**

---

## Verdict (hardware + governance)

**Train side** is live: sandbox rejection sampling, preference export, ephemeral DO GPU QLoRA + destroy, revision ledger, bakeoff/canary. **Serve side** was planned against hardware that does not exist:

1. **No GPU on ORANGE or BLUE.** ORANGE = Hetzner CAX41 ARM, 32 GB **RAM**, no CUDA ([`ln7_peft_server.py`](backend/scripts/orange/ln7_peft_server.py) forces CPU fp16). BLUE Intel = blocked for mlx ([`docs/ln7/RUNBOOK.md`](docs/ln7/RUNBOOK.md)). Clone hive = **ephemeral DO GPU burst**; interactive = ORANGE Ollama quantized 7B.
2. **Magazine base split.** Pin **`Qwen/Qwen2.5-Coder-7B-Instruct`**; quarantine 1.5B adapters.
3. **Governance is phased (see Governance transition).** Today: CEO activate remains a valid product path (e.g. Priority 1 bakeoff promote). After Step 0 greens: Dual-COO mechanical promote is authority; CEO surface = transparency + reversal pad only. YELLOW/RED remap and anomaly channel apply in the end-state; they do not invalidate current CEO activate.

```mermaid
flowchart LR
  subgraph steady [Steady state]
    Router["GREEN LN7DomainRouter"]
    Ollama["ORANGE Ollama 7B"]
    Ledger["Unified outcome envelope"]
  end
  subgraph burst [DO GPU burst]
    VLLM["vLLM multi-LoRA"]
    BoN["BoN bakeoff"]
    Merge["dare_ties"]
  end
  subgraph organism [Autonomous operators]
    Queens["Dual-COO diverse models"]
    LN7["LN7 shadow sandbox CI"]
    Mkt["Claims + retraction cascade"]
  end
  Router --> Ollama --> Ledger
  Ledger --> Export --> Train --> Adapters
  Adapters --> VLLM --> BoN --> Ledger
  Queens --> VLLM
  Queens --> LN7
  Ledger --> Mkt
  Merge --> Base["LN7-v2-Base"] --> Ollama
```

---

## Governance transition (CEO activate ↔ reverse pad)

Two product rules must not be collapsed into one timeline.

| Epoch | When | Promote / activate | CEO surface |
|---|---|---|---|
| **G0 — Current / Priority 1** | Until Step 0 fence suite + boot manifest are green **and** `DUAL_COO_MECHANICAL_PROMOTE` is false | Bakeoff + canary evidence → **CEO activate** (`ceo_inbox_decide` / activate_revision) is **valid and required** for serving flips. `ENABLE_LN7_AUTO_PROMOTE` stays false. | Decidable inbox: APPROVE activates, REJECT holds. |
| **G1 — Transition** | Step 0 landing; mechanical Dual-COO path shipping behind flag | Both paths exist: mechanical checklist can shadow-score; **CEO activate still authoritative** until flag flip. | Inbox still decidable for promote. |
| **G2 — End-state** | Step 0 green **and** `DUAL_COO_MECHANICAL_PROMOTE=true` (auto with W6) | Dual-COO checklist agreement = promote authority. `enqueue_ceo` removed from LN7/Queens **promote** paths only. | **Reverse pad only** — transparency, anomaly awareness, one-click reverse (W18). Never a throughput wait. |

**Hard rules:**
- Finishing Priority 1 (or any pre–Step 0 promote) via CEO activate is correct under G0 — not a plan violation.
- Do not strip CEO decide from promote paths until G2.
- Stage 4 abort gate is mechanical in all epochs; CEO may still reverse a bad Stage 4 after the fact in G2.
- Reversal in every epoch: predecessor restored, pattern suppressed 30 days (`ln7_suppress_patterns`), logged.

## Governance model (rev 3 — applies fully in G2)

| Tier | Meaning |
|---|---|
| GREEN | Runs, logs |
| YELLOW | Heightened mechanical bar; digest + one-click reversal |
| RED | Fail-safe taken autonomously; logged; **anomaly channel fires if pattern thresholds trip**; reverse if disagree — never blocks awaiting a human |

**Welds (outside every trainable / self-modifiable scope):**
1. Crisis escalation, coach routing, SI handling
2. Evaluators (scoring bounds, decay, bakeoff margins, BWAS weights)
3. Tier boundaries, caps, invariant sets, claim-derivation templates, **cross-review checklist**
4. Enforcement: schema rejection, **Queens SA cannot write** `frozen-config/` + fence-test paths, boot-time hash vs pinned manifest, CI suite on every deploy

Weld / fence-path changes = ordinary out-of-band config/PR by a non-agent actor (owner/repo path with different credentials) — never via Queens service accounts.

**Promotion authority (G2):** Dual-COO Queens on deliberately different models/configs. Agreement = both independently verified the welded checklist. Disagreement → RED hold.

**Flag flip = product-rule change:** PG `ln7_feature_flags` (mig **307**, W6). Step 0 green → set `ENABLE_LN7_AUTO_PROMOTE` and `DUAL_COO_MECHANICAL_PROMOTE` true together — that flip **is** G0→G2. Env remains emergency kill-switch. Until then, CEO activate remains the promote path.

---

## Migration ID allocation (never overwrite 303/304)

Already shipped (do not reuse):

| ID | File |
|---|---|
| 303 | [`303_ln7_humaneval_subset_seed.sql`](backend/migrations/303_ln7_humaneval_subset_seed.sql) |
| 304 | [`304_ln7_backfill_authored_license.sql`](backend/migrations/304_ln7_backfill_authored_license.sql) |

Flywheel plan migrations (next free block; renumber upward if another branch lands first — check `ls backend/migrations/ \| sort -n \| tail` at implement time):

| ID | File (planned) | Phase |
|---|---|---|
| **305** | `305_ln7_domain_adapter_registry.sql` | B2 — domain_tag, adapter_uri, vllm_lora_name, embedding, serve_weight, parent_revision |
| **306** | `306_ln7_outcome_envelope.sql` | E1/W7 — outcome_envelope + envelope_id FKs |
| **307** | `307_ln7_feature_flags.sql` | W6 — ln7_feature_flags |
| **308** | `308_growth_claims.sql` | M2/W11 — growth_claims |
| **309** | `309_ln7_pack_candidates.sql` | R2/W8 — ln7_pack_candidates |
| **310** | `310_ln7_suppress_patterns.sql` | E8/W18 — ln7_suppress_patterns |

---

## Node map

| Tier | Node | Role |
|---|---|---|
| Command | BLUE Mac (Intel) | Orchestration; no train |
| Interactive | ORANGE `10.13.13.5` ARM CPU | Ollama `:11434`; PEFT `:11435` smoke; adapter disk |
| Hive + ammo | Ephemeral DO GPU | vLLM `:11436`, QLoRA, mergekit |
| Shadow oracle | Sandbox VPS `10.13.13.4` | Ephemeral apply + same CI packs for LN7 counterfactual patches |
| Orchestrator | GREEN | Router, ledger, Queens, export — never trains |
| Artifacts | R2 + PG + ORANGE disk | Adapters, embeddings, learning artifacts |

---

## Step 0 — Weld extraction + fence isolation (blocks auto-promote)

1. Extract existing operating values (thresholds, caps, BWAS from `growth_config` / [`bwas_worker.py`](backend/app/services/growth/bwas_worker.py), bakeoff margins, derivation templates, **cross-review checklist**) into `frozen-config/` (Queens SA cannot write — same pattern as learning-gate DB read-only role).
2. Fence-test files live in the same unwritable tree (or sibling with identical ACL).
3. **Pinned fence manifest** (hashes of frozen-config + fence tests) checked at **boot** and before any promote path runs. Mismatch → RED hold all promotions, anomaly notification.
4. **Versioned backup** of frozen-config + manifest (R2 + local) on every successful Step 0 / weld out-of-band change.
5. Fence tests assert semantic equivalence of extracted values vs prior code locations.
6. **Goodhart reference corpus snapshot (weld):** sample of promoted-rule responses, gold-standard exchanges, and adversarial criteria as they exist at Step 0 — frozen yardstick for R1. Also freeze **R1 probe scenario set** (W16) at the same time.
7. When suite green: write `ln7_feature_flags.ENABLE_LN7_AUTO_PROMOTE=true` (W6); emit anomaly if flip fails.

Who fences the fence: the **permission layer** (and boot hash), not another reviewer. Deployment shape: W13.

---

## Phase A0 — Pin base, quarantine mismatch

- `LN7_QLORA_HF_BASE=Qwen/Qwen2.5-Coder-7B-Instruct` in [`ln7_peft_server.service`](backend/scripts/orange/ln7_peft_server.service) + `DEFAULT_HF_BASE` in [`ln7_qlora_train.py`](backend/scripts/ln7_qlora_train.py).
- Mark 1.5B revisions `status='rejected'`, `notes='base_mismatch_1p5b'`.
- Register-time assert: refuse adapter whose `train_meta.json` base ≠ pinned base.
- Uniform `rank` + `target_modules` recorded and asserted.

---

## Phase A — Ephemeral vLLM multi-LoRA hive (burst)

Interactive path unchanged: ORANGE Ollama `:11434` / `LN7_CODE_MODEL_*`.

- Orchestrated only via task-bus type **`hive_burst`** (W3), not ad-hoc SSH. Scripts [`ln7_provision_cuda_droplet.sh`](scripts/ln7_provision_cuda_droplet.sh) / destroy / new `scripts/ln7_hive_burst.sh` are the **worker body** of that task.
- On healthy vLLM: publish Redis `ln7:serve:endpoint` + `LN7_SERVE_ENGINE=vllm_burst` (W4); on destroy: clear key, revert `ollama`.
- vLLM: `--max-loras 4 --max-cpu-loras 16 --gpu-memory-utilization 0.90` + `--max-model-len` — measure before locking. Port **`11436`**; api-key; WG bind; UFW `10.13.13.0/24`.
- Destroy failure / orphan → anomaly type `burst_destroy_fail` (W17).
- Burst adapter set = union of (a) intent-queue adapters since last burst (W5) and (b) canary/bakeoff contestants.

### F1 economics gate + cold-start bootstrap

YELLOW over-cap / new-SKU test uses trailing **cost-per-accepted-improvement (CPAI)**. At cold start accepted improvements = 0 → undefined.

**Bootstrap allowance (weld):** first **N** burst windows per phase (N in frozen-config; initial suggestion N=5) are exempt from the CPAI test under a **fixed spend cap**. After N windows (or first accepted improvement, whichever comes later), CPAI governs. Cap breach during bootstrap → RED (window not opened), same as post-bootstrap fail-safe.

#### F1 weld-adjacent principle — observability fail-safe (2026-07-30 incident)

Same constitution as RED-tier fail-safe, one layer down: **a watchdog that cannot see must freeze, not shoot.**

| Evidence | Action |
|---|---|
| Heartbeat **exists** AND mtime older than threshold | Positive death → restart / reclaim / destroy as designed |
| Heartbeat **absent** or **unreadable** | Hold + write `WATCHDOG_BLIND_ALARM` — **never** re-dispatch paid GPU / bakeoff |
| Watchdog **cannot write/read its own state files** | Same freeze path ("I am blind") — do not treat empty world as idle |
| Destroy API called | **Verify** `doctl get` → 404; still present → `burst_destroy_fail` anomaly (W17) |

**Droplet-side death (belt):** cloud-init installs `ln7-ttl-self-destruct.service` (API self-delete at `LN7_GPU_HARD_MAX_S`; poweroff only as floor — still bills). **Orchestrator destroy** = suspenders. **Orphan reaper + destroy verification** = third strap.

Logged validation: controller silence after GPU already gone → absent-heartbeat path previously re-fired A/B drain; revision ledger / R2 / PG survived. Cheap tuition before `ENABLE_LN7_AUTO_PROMOTE`.

---

## Phase B — Routing (telemetry first)

### B1 — Telemetry

Harness writes **chosen adapter** `revision_id` on [`ln7_coding_outcomes`](backend/migrations/291_ln7_outcome_ledger.sql) **and** dual-writes envelope (W7); `route_tier` + runner-ups in `metrics_json`. View `ln7_adapter_win_rate`: Laplace + sample floor. Cold-start = neutral prior. Provenance fields for R6 on the same write.

### B2 — Registry + 3-tier router

Migration **305** `ln7_domain_adapter_registry.sql` (additive columns on `ln7_revisions`): `domain_tag`, `adapter_uri`, `vllm_lora_name`, `embedding JSONB`, `serve_weight`, `parent_revision`. **Do not use 303** — already [`303_ln7_humaneval_subset_seed.sql`](backend/migrations/303_ln7_humaneval_subset_seed.sql). JSONB + numpy cosine. Per-tier active via [`300_ln7_tier_scoped_active.sql`](backend/migrations/300_ln7_tier_scoped_active.sql).

| Tier | Trigger | Target |
|---|---|---|
| 1 Static | Ext / imports / AST ([`cli_symbol_store.py`](backend/app/websocket/cli_symbol_store.py)) | Exact domain adapter |
| 2 Semantic | cosine × smoothed win_rate ≥ 0.78 | Top weighted |
| 3 BoN | Below threshold | Top-3 in **burst window only** |

`LN7DomainRouter`; `ENABLE_LN7_DOMAIN_ROUTER` from `ln7_feature_flags` (default false).

**Embeddings (locked):** Cloudflare Workers **BGE** via existing Vectorize/Workers AI path; cache key = `sha256(task_prompt + sorted(file_paths))` in Redis TTL 24h. Fallback if Workers down: skip Tier 2 → Tier 3/incumbent (never invent vectors).

**Steady-state:** Tier 1/2 selection writes Redis list `ln7:adapter_intent` (adapter_id, task_hash, ts) and serves Ollama incumbent for the user turn. Next `hive_burst` drains the intent list into `--load_lora` set + optional BoN fan-out (W5).

### B3 — Cold start

Add `domain_tag` to pack `task.json` (migration of existing packs via one-shot Queens GREEN). `--domain` on [`ln7_export_train_jsonl.py`](backend/scripts/ln7_export_train_jsonl.py); seed from densest tagged packs in [`ln_sandbox_ci_packs/`](backend/app/data/ln_sandbox_ci_packs/).

---

## Phase C — Stage 4 consolidation (`dare_ties`)

- No `target_model:`; do not relist base under `models:`; pin mergekit; materialize PEFT → HF; ≥120 GB free; prefer L40S; ~15 GB WG to ORANGE.
- **Abort gate = authority:** beat `LN7-fast-baseline` AND every contributor on held-out, else auto-reject.
- On accept: GGUF for ORANGE Ollama; prune micros only after pass.

---

## Phase D — Flywheel harden

| Rule | Enforcement |
|---|---|
| Held-out never trains | Hard-block in export + CI |
| Data budget | ≥300 rows/domain, ≥1500 total for 5 experts |
| Promote | Bakeoff + Dual-COO diverse checklist (post–Step 0 auto-flip); influence Gini hold if evidence concentrated (R6) |
| Bakeoff mix | Stratified **vintage + fresh** CI packs; fresh-pack pass rate reported separately (R2) |
| GGUF | ≥2 consecutive canary wins |
| Post–Stage 4 | Canary vs `LN7-v2-Base` |

---

## Phase E — Nervous system (unified outcome ledger)

- **E1** Migration **306** `ln7_outcome_envelope.sql` — `outcome_envelope` table; **dual-write** from existing writers (W7). **Do not use 304** — already [`304_ln7_backfill_authored_license.sql`](backend/migrations/304_ln7_backfill_authored_license.sql). `ln7_coding_outcomes` / learning artifacts remain; envelope is the cross-loop join surface (`envelope_id` FK back).
- **E2** Cross-loop attribution keys on envelope.
- **E3** Compliance grants; marketing aggregates only — CI-verified.
- **E4** `source_node` + `burst_id` + per-window signing key.
- **E5** Change-lease in **Redis** `ln7:change_lease:{loop}` with TTL (Weld; default scoring-window + grace). Auto-release on expiry; overlap → serialize. Confounded windows flagged on envelope, excluded from promote evidence.
- **E6** Weekly digest — report only.
- **E7** Anomaly via dedicated notify type **`flywheel_anomaly`** (W17) — SendGrid/CEO alert **without** creating a decidable inbox item. Thresholds in frozen-config.
- **E8** Mig **310** `ln7_suppress_patterns` (pattern_key, until_ts) for 30-day reverse suppress (W18). Promote/handover gates check it.

---

## Phase F — Queens as flywheel operators

- **F1** Burst = `publish_task(task_type="hive_burst", …)` (W3). Economics + bootstrap per Phase A run inside the worker before provision.
- **F2 cutover (W2) — G2 only:** New `dual_coo_checklist_review(evidence_uri)` — both Queens (diverse models) evaluate welded checklist JSON; agreement → `activate_revision` / promote; disagreement → RED hold + envelope log + anomaly lineage. **Until Step 0 greens (`DUAL_COO_MECHANICAL_PROMOTE=false`): keep `enqueue_ceo` / CEO activate** — Priority 1 and current promote flow stay valid. On G2 flip: remove CEO decide from LN7/Queens **promote** paths only; CEO reverse pad remains.
- **F3** Fence suite + SA-unwritable frozen-config (W13).
- **F4** Out-of-band weld edits only; R3 PRs via GitHub App (W14).
- **F5** Merge survival → living packs (W8). R4 allowlist on tool layer.

---

## Phase G — LN7 behind the Queens' hands

### G1 — Shadow-first with **executed** oracle (load-bearing)

**Event chain (W1) — locked:**
```
queens.task.merged (patch_hash, domain, evidence_uri)
  → publish_task(ln7_shadow_fork)
  → LN7 generates counterfactual unified diff (same task context)
  → sandbox: apply_unified_diff + run_ci_pack_cycle (living packs included)
  → envelope.shadow_outcome {passed, pack_ids, latency_ms}
```
Fork fires on **merge to main / activate**, not on claim. Similarity scoring forbidden. **Without W1 + sandbox pass/fail rows, G1 promote is hard-disabled in code.**

Handover: per-domain when shadow sandbox win-rate beats incumbent (Laplace + sample floor) — logged, reversible; checks `ln7_suppress_patterns`. Live win-rate below trailing baseline 3 windows → auto-revert.

- **G2** Tier-4 tutor: `train_eligible` from existing compliance config; absent → exclude.
- **G3** Tier-4 monthly spend cap; 80% throttle; weld.
- **G4** Steady-state honesty unchanged.

---

## Phase M — Marketing loop, autonomously bound

Touch: [`outreach_publisher.py`](backend/app/services/growth/outreach_publisher.py), SkyEye approval queue (editorial), [`bwas_worker.py`](backend/app/services/growth/bwas_worker.py).

- **M1** Marketing joins the envelope (dual-write).
- **M2** Mig **308** table **`growth_claims`** (W11): claim_id, text, evidence_class, artifact_uri, expires_at, status. Derived only via welded templates. Nightly re-derive. Publisher: `outreach_publisher` / SkyEye post path **must** resolve `claim_ids[]` and refuse if any missing/expired/short-horizon on unretractable channel.
- **M2b — Retraction cascade (W12), same night:**
  1. Artifact rolled back / evidence lapses → claim status=`retracted`
  2. Job `growth_claims_retract_surfaces` updates owned surfaces (locked map):
     - `dashboard/` / `/var/www/sovereign-command/` pages that render claim text (grep registry keys)
     - directory profile fields fed by growth content factory
     - SkyEye content-queue rows still `pending`/`scheduled` (cancel or rewrite)
  3. Already-sent email / syndicated posts: no rewrite; blocked at publish by long-horizon class only.
- **M3** CI blocklist + therapeutic advisory sensitivity path.
- **M4** BWAS provenance-weighted by verified stage (R6).
- **M5** Playbook A/B + auto-promote/revert; E5 leases.
- **M6** One-directional care → growth; grants + CI.
- **M7** Marketing ingester privilege asymmetry (R4).

---

## Phase H — Therapeutic weight loop (mechanical predicates)

**Poller (W15):** GREEN cron/`phase_h_predicate_poller` every 6h evaluates five predicates → writes `ln7_feature_flags.PHASE_H_OPEN`. Export/register of therapeutic weights hard-require that flag. Opens when all five evaluate true:

1. **Gold-sample audit** — Queens harness; missing pass → hard-block export.
2. **Calibrated abstention** — Brier/calibration series from envelope.
3. **Labeling provenance** — existing advisory/coach-label fields present.
4. **Adversarial held-out** — versioned weld artifact **derived from existing platform state**, not model imagination: flagged gold samples, incident/escalation logs, advisory sensitivity rules. Auto-generation from the model under test is forbidden (self-defeating). **Honesty note:** this is the single artifact whose quality structure cannot fully guarantee — provenance from real failures is the closest autonomous-compatible answer; treat under-coverage as RED (Phase H stays closed) rather than inventing cases.
5. **Data governance** — consent/de-id from onboarding; missing flag → exclude; deletion → export exclude + Queens GREEN re-burn.

When 5/5: H3 Queens-operated, abort-gated, invariant-fenced. **H1:** crisis / SI / escalation never trainable — export AND register. Export generalization gate: **N≥5 provenance-independent users** (distinct payment lineage / device fingerprints / coach assignments), not merely N≥5 usernames (R6). Promoted therapeutic rules also sit under the R1 Goodhart drift sentinel.

---

## Phase R — Residual risk mechanisms (structure + named residue)

These address risks autonomy cannot fully delete. Each mechanism is autonomous; residue is explicit.

### R1 — Goodhart drift sentinel (frozen reference)

Live evaluators cannot detect their own blind-spot drift. At Step 0, snapshot a **reference corpus** as a weld (promoted-rule responses, gold exchanges, adversarial criteria as trusted then). Weekly Queens GREEN job replays current promoted rules against **fixed probe scenarios** and measures distribution shift vs reference: validation-to-challenge ratio, intervention frequency, witnessing-vs-advising balance, session-length trends. Drift beyond banded thresholds (welds) → RED: rule lineage auto-suspends to predecessor, logged, anomaly push. Yardstick does not move with the loop.

**Residue:** reference ages; scheduled re-snapshot is out-of-band weld change. Structure buys years, not forever.

### R2 — Living CI packs (oracle eats what the organism kills)

**Wire (W8):** On `queens.task.merged`, insert `ln7_pack_candidates(patch_hash, merged_at, domain)`. Daily job: if `now - merged_at >= N days` AND no revert on that hash → distill pack (broken/ + tests from merge evidence) into `backend/app/data/ln_sandbox_ci_packs/living_<hash>/`, set `domain_tag`, random `split` train|heldout, scp/rsync to Sandbox VPS pack root. Coverage map (pytest `--cov` + file touch list from patch) retires packs whose paths no longer exist. Bakeoffs stratify vintage + fresh; report fresh pass rate separately.

**Residue:** essentially none — converts fully to structure.

### R3 — Shadow evaluators (weld ossification without self-edit)

No loop edits its own evaluator (absolute). Shadow param sets score in parallel. Monthly divergence → **GitHub App** `sovereign-weld-bot` (W14) opens PR against `frozen-config/` with config diff + evidence appendix; App can open PRs only, cannot merge, cannot push to `main` without review by non-agent credentials. Merge out-of-band.

**Residue:** unread PR queue is attention, not structure.

### R4 — Prompt injection (capability firewalls + canaries)

Three structural layers:
1. **Ingestion quarantine** — external content (web, leads, inbound replies, client messages, log lines) enters wrapped in a data-envelope; tool-dispatch validated against task-type allowlist (extend Queens command allowlist to every loop's tool layer). "The email said run X" cannot widen the task.
2. **Privilege asymmetry** — dirtiest readers get fewest capabilities (marketing ingester → queue rows only); repo-writing Queens consume only structured artifacts from lower-privilege parsers (serialization boundary strips instruction-shaped content).
3. **Live canaries** — standing injection corpus (known patterns, refreshed from public disclosure feeds by GREEN job) against every harness in CI; honeytoken tripwires (fake credentials, fake weld path) in env; touch → immediate RED quarantine of that agent's recent actions + anomaly push.

**Residue:** arms race — raises attack cost and catches known patterns; novel attacks remain possible.

### R5 — Vendor / supply-chain (pin, verify, drill fallback)

- Base-model weights mirrored to R2 with checksums (own the Qwen artifacts).
- Droplet install from frozen lockfile against internal mirror.
- API models version-pinned + **daily behavioral fingerprint** (fixed probe battery); fingerprint drift auto-flags before contaminating scoring (catches silent vendor updates pins miss).
- Each loop declares fallback engine in config (LN7 → ORANGE Ollama by construction; LN → incumbent rule set + previous model snapshot).
- **Quarterly GREEN fallback drill** exercises each fallback; pass/fail logged. Untested fallback = wish.

**Residue:** true frontier-API deprecation still degrades capability until re-integration; structure guarantees graceful degradation + early warning, not immunity.

### R6 — Adversarial fuel (provenance-weighted Sybil resistance)

Every preference row / outcome carries account-level provenance (account age, session diversity, biometric-stream presence, payment/coach-linkage) — envelope fields. Export weighting discounts low-provenance sources. Generalization gate: **N≥5 provenance-independent users** (payment lineage / device fingerprints / coach assignments). **Influence audit:** Gini-style concentration of supporting evidence per promotion candidate; domination by few sources → YELLOW stricter bar until breadth accumulates. Marketing: BWAS provenance-weighted by verified stage (M4).

**Residue:** patient adversary with genuinely independent identities beats statistical defense — then indistinguishable from real users; damage capped at "one weird real user," contained by sample floors.

---

## Phase W — Wiring contracts (closes all event-edge gaps)

Implement **before or with** the phase that depends on each contract. Every contract has: trigger → actor → store → consumer → fail-safe.

```mermaid
sequenceDiagram
  participant Q as Queens
  participant Bus as cli_task_bus
  participant LN7 as LN7_shadow
  participant SB as SandboxCI
  participant Env as outcome_envelope
  participant Redis as Redis
  participant DO as DO_GPU_hive
  Q->>Bus: queens.task.merged
  Bus->>LN7: ln7_shadow_fork
  LN7->>SB: apply_diff_plus_pytest
  SB->>Env: shadow_outcome
  Q->>Bus: hive_burst
  Bus->>DO: provision_vLLM
  DO->>Redis: ln7:serve:endpoint
  Redis->>LN7: route_vllm_burst
```

| ID | Gap closed | Contract |
|---|---|---|
| **W1** | G1 trigger | On merge/activate emit `queens.task.merged` → `publish_task(ln7_shadow_fork)` → LN7 patch → `apply_unified_diff` + `run_ci_pack_cycle` → `envelope.shadow_outcome`. G1 promote hard-disabled until rows exist. |
| **W2** | F2 CEO-inbox today | **G0/G1:** keep `enqueue_ceo` — CEO activate valid. **G2 only:** `dual_coo_checklist_review` replaces promote enqueue; CEO reverse-only. Flag flip with Step 0 green (mig 307). |
| **W3** | F1 ≠ task bus | New `task_type=hive_burst` in [`cli_task_bus.py`](backend/app/websocket/cli_task_bus.py); consumer runs provision → load adapters from intent queue → bakeoff/BoN → destroy. Shell scripts = worker body only. |
| **W4** | Burst address | Worker SETs Redis `ln7:serve:endpoint`=`http://10.x:11436`, `ln7:serve:engine`=`vllm_burst`, TTL = window; DELETE on destroy. GREEN clients read Redis; miss → Ollama. |
| **W5** | Router dead-end | Tier 1/2 LPUSH `ln7:adapter_intent`; user turn still Ollama. `hive_burst` RPOPALL → lora load set. |
| **W6** | Flag flip store | Mig **307** `ln7_feature_flags(key, enabled, updated_at)`. Readers: PG first, env kill-switch second. Step 0 green → UPDATE both `ENABLE_LN7_AUTO_PROMOTE` and `DUAL_COO_MECHANICAL_PROMOTE` (G0→G2). |
| **W7** | Envelope vs ln7_* | Mig **306** `outcome_envelope` (not 304); dual-write from [`ln7_ledger`](backend/app/services/ln7_ledger.py) + Queens + marketing; `envelope_id` on child rows. No big-bang cutover. |
| **W8** | Living packs | Mig **309** `ln7_pack_candidates` on merge; daily distill after N days; deploy packs to Sandbox VPS; coverage retire. |
| **W9** | Domain seed | `domain_tag` in pack `task.json`; one-shot backfill; export `--domain`. |
| **W10** | Embeddings | Workers BGE; Redis cache `ln7:embed:{hash}`; fail → skip Tier 2. |
| **W11** | Claims table + gate | Mig **308** `growth_claims`; publisher requires valid claim_ids; long-horizon class for email/syndicate. |
| **W12** | Retract surfaces | Job + locked surface map (command dashboard, directory fields, pending content-queue). |
| **W13** | Queens SA / fence | Deploy: volume `/opt/ln7/frozen-config` + fence tests mounted **ro** into Queens/bridge workers; writable only by host deploy user / `safe_deploy`. Boot reads manifest SHA from that volume. PG role `ln7_queens` = CRUD on ledger/tasks, **no** UPDATE on `ln7_feature_flags` weld keys or frozen tables marked invariant. |
| **W14** | R3 PR actor | GitHub App `sovereign-weld-bot`: `pull_requests: write` only; cannot merge; cannot push main. |
| **W15** | H poller | `phase_h_predicate_poller` 6h → `PHASE_H_OPEN` flag. |
| **W16** | R1 probes | Step 0 freezes `frozen-config/goodhart_probes.json` + reference outputs; weekly job diffs metrics named in that file. |
| **W17** | Anomaly bus | `notify_flywheel_anomaly(kind, payload)` → email/CEO alert **without** `ceo_inbox` decide row. Kinds: rollback_storm, queens_disagree_lineage, confound_spike, burst_destroy_fail, watchdog_blind, fence_manifest_mismatch, bootstrap_cap, fingerprint_drift, honeytoken, fallback_drill_fail, drift_sentinel. |
| **W18** | Suppress 30d | Mig **310** `ln7_suppress_patterns`; reverse/handover revert writes row; promote gates SELECT. |

**CI fences for wiring:**
- **G0/G1:** (a′) promote path **still may** call `enqueue_ceo` — tests must not forbid it; (b) G1 shadow promote refuses without shadow_outcome when that gate is on; (c) publisher refuses missing claims; (d) `auto_promote_enabled` reads PG mock.
- **G2 only:** (a) promote path does **not** call `enqueue_ceo` when `DUAL_COO_MECHANICAL_PROMOTE=true`.

---

## Ops and repo discipline

| Requirement | Action |
|---|---|
| Feature flags | PG `ln7_feature_flags` + env kill-switch: `ENABLE_LN7_DOMAIN_ROUTER`, `ENABLE_LN7_AUTO_PROMOTE`, `DUAL_COO_MECHANICAL_PROMOTE`, `PHASE_H_OPEN`, `LN7_SERVE_ENGINE` |
| Fence ACL | W13 ro volume + PG role; boot hash vs pinned manifest |
| Backup | Versioned frozen-config + manifest → R2 on every weld change |
| Anomaly | W17 `flywheel_anomaly` only — never decidable inbox |
| Service health | Router, envelope dual-write, anomaly watcher, living-pack job, drift sentinel, predicate poller, hive_burst consumer in `_service_checks` |
| CI gate | Fence suite + injection canaries + W wiring assertions in `run_ci_tests.sh` |
| Supply chain | R2-mirrored base weights + checksums; droplet lockfile mirror; daily model fingerprint |
| Three-node sync | GREEN `safe_deploy.sh`; hive via bus; ORANGE scp; living packs → Sandbox VPS |
| Cost accounting | SKU / wall-clock / USD on envelope per burst/merge; bootstrap cap |
| Shadow weld PRs | W14 GitHub App; merge never autonomous |

---

## Gap ledger

| # | Gap | Resolution |
|---|---|---|
| 1 | No GPU on ORANGE/BLUE | Ephemeral DO hive + ORANGE Ollama |
| 2 | 1.5B vs 7B magazine | A0 pin 7B + quarantine |
| 3 | `win_rate` uncomputable | B1 telemetry + smoothed view |
| 4 | No embedding provider | W10 Workers BGE + cache |
| 5 | Zero domain adapters | W9 domain_tag + B3 export |
| 6 | Port collision 11435 | Hive 11436 |
| 7 | Bad mergekit YAML / hetero LoRA | C + A0 uniform rank |
| 8 | No merge abort / disk budget | Abort gate + ≥120 GB + L40S |
| 9 | Unauthenticated load_lora | api-key + WG + UFW |
| 10 | No flags / health / CI / sync | Ops + W6 |
| 28–33 | Autonomy remap | Amendment 1 rev 3.1 |
| 34–43 | Autonomy design gaps | Gap pack + W1–W18 |
| 44–49 | Residuals | Phase R — **2026-07-30 logged validation:** orphan-cost / destroy-verify hole + anomaly “burst fails to destroy” (controller blind after destroy) → F1 observability fail-safe (`watchdog_blind`) |
| 50 | G1 no trigger | **W1** shadow fork chain |
| 51 | F2 CEO inbox today vs reverse-only end-state | **W2** phased: G0 keep CEO activate; G2 mechanical cutover after Step 0 |
| 52 | F1 not on task bus | **W3** `hive_burst` |
| 53 | No burst endpoint discovery | **W4** Redis serve key |
| 54 | Router intent dead-end | **W5** intent → burst |
| 55 | Flag flip no store | **W6** PG feature_flags |
| 56 | Envelope vs ln7_* unclear | **W7** dual-write wrap |
| 57 | Living packs unwired | **W8** candidates + distill |
| 58 | Packs lack domain_tag | **W9** |
| 59 | Claims table/publisher missing | **W11** |
| 60 | Retract surface map missing | **W12** |
| 61 | Queens SA undefined | **W13** |
| 62 | R3 PR actor undefined | **W14** |
| 63 | H no poller | **W15** |
| 64 | R1 probes unsourced | **W16** |
| 65 | Anomaly re-enters inbox | **W17** |
| 66 | Suppress 30d no store | **W18** |

---

## Non-goals

- Vendor fine-tune APIs; LN7 LoRAs on Workers AI
- Persistent always-on GPU; vLLM on ORANGE
- Any loop writing welds/fences (including Queens editing fence tests or merging shadow-eval PRs)
- Any operational step that blocks awaiting a human
- Scoring LN7 shadow by patch similarity or Queens acceptance alone
- Marketing claims without derived registry entry; unretractable publish of short-horizon claims
- LN write access to his own substrate
- Tier-4 train from uncleared providers
- Therapeutic weight training before `PHASE_H_OPEN`
- Model-generated adversarial held-out for Phase H
- Auto-promote before Step 0 green
- Stripping CEO activate / `enqueue_ceo` from promote paths before G2 (Step 0 green + `DUAL_COO_MECHANICAL_PROMOTE`)
- Re-introducing `enqueue_ceo` on LN7/Queens **promote** paths after G2 cutover
- Creating migrations numbered 303 or 304 (already HumanEval seed + authored-license backfill)
- Moving Goodhart reference without out-of-band weld change
- Untested fallbacks treated as production-ready

---

## Completed — Attempt 6 era (2026-07-31)

| Item | Evidence |
|------|----------|
| Decoupled bakeoff proven | Tag `bakeoff-v0.6-attempt6-proven`; freeze R2 + ledger mig 313 |
| Winner HOLD (not promoted) | `LN7-2026-07-30T190327Z` shadow; `ENABLE_LN7_AUTO_PROMOTE=false` |
| PRE6 paid gate | Organic G1 ≥300 required; Attempt 6 bypass closed |
| Steps 6–8 | Commit **`11d6e1e4`** on GREEN; 153/153; `Ln7OpsScheduler` live |
| Fuel baseline | `coding` 1/300, `general` 2/300 — ETA n/a until slope days accumulate |
| Next paid Phase A | Human: `LN7_BURST_ALLOW_PAID=1` + enqueue `ln7_bakeoff` only after PRE6 unlock email |

**Still open on this plan:** Phase F mechanical Dual-COO promote remains gated on G2 flip (held per CEO 2026-08-01: G2 is a trust-expansion decision, stays CEO-inbox-gated not automated — unaffected by gate 1 closing). Gate 2 RED PASS 2026-08-02 (TRUST_LEDGER Entry 20) — floor still shadow-only; live wire into therapeutic audit is a separate PR. Standing floor tickets (means=n/a, escalation FP, naming=F on AQ-1 pack) CLOSED 2026-08-03 (TRUST_LEDGER Entry 22 — AQ-G07 means_distance exemption widen, crisis-seam escalation coach-bring-in port [ENABLE_SYMBOLIC_VERIFIER stays default-off], NAMING_DECLARATION anchor; 10 new tests). Dose-response v2 scored 8/8 (2026-08-03); grok-judge-v6 frozen before contact and one κ run executed (Entry 21, evidence_id=10, κ=0.480, v2 set now burned for judge tuning). Pack acceptance brief written (docs/ln7/DOSE_RESPONSE_V2_PACK_ACCEPTANCE_BRIEF.md): net structural transfer 4→10 moves vs gate-1's 0-for-40 baseline, AQ-1 clean win, AQ-G07 flat (prohibition-nav line under-transfers, no regression). **Permanent `LN7_MUST_SEQUENCE_PACK_LIVE=true` remains an open CEO decision** — brief presents ship-as-is vs ship-gated-iterate-G07 paths, neither executed. Phase H is now code-complete (predicate poller, held-out weld, H1 crisis-never-trainable + N>=5 provenance-independent-users gate all mechanically wired — see phase-h-therapeutic-weights); only production flag-flips remain, which are ops/CEO decisions, not code. Phase C merge drain code+tests DONE (2026-08-01) — real subprocess execution + Queens-trigger end-to-end on L40S still human/paid-gated. Phase D flywheel-harden code+tests DONE (2026-08-01) — held-out SQL hard-block, data budget gate, GGUF win-streak, LN7-v2-Base incumbent. G2 flip deferred (CEO/manual). Residual polish: W8 sandbox rsync, W11 hard claim_ids+SkyEye, W14 live App, W16 live probes. Paid Phase A GPU still human-gated. Remaining R-series work: R4 layers 2 (privilege asymmetry / serialization boundary) and 3 (standing injection-canary corpus in CI) re-sequenced 2026-08-02 to run after gate-2 verifier floor + must-sequence pack design (idle-hands parallel option once verifier floor is in review, after the merge train) — both now CODED, see phase-r-residuals. Judge v5 fresh held-out reserve corrected 2026-08-02: 4 of the originally-reported 44 unscored live-track rows were burned dose-response duplicates (see judge-burned-holdout-writeback, TRUST_LEDGER.md Entry 10) — written back via migration 318 + writeback_dose_response_to_live_gold.py, and excluded from any future held-out run via compute_tier1_v5_fresh_holdout_kappa.py's live_scored_via + named-burned filters. The clean fresh held-out pool is 40 rows, not 44; CEO scored Capability live 45/45 on 2026-08-02 and judge-v5-fresh-holdout-run executed the same day — κ=0.189 (n=40, safety veto 0 misses, evidence_id=9, gold_locked=false; TRUST_LEDGER.md Entry 11). Flag decision landed same day (Entry 12, judge-flag-decision-a-shipped): v5 = safety-veto screener only, not quality scorer, with auto-revert (migration 319 + tier1_gold_evidence.apply_veto_auto_revert) and a structural uncertified-quality disclaimer on every judge output — both are CODED and tested (19 new tests), not just decided. Gate-2 RED review and living-pack acceptance (dose-response v2) proceed now — neither depends on the judge; judge v6 (full-range calibration + grid-then-scalars protocol) is deferred, held-out borrowed from dose-response v2, this n=40 set now burned. `SIX_QUOTIENT_WEEKLY_LIVE` inconsistency (Entry 13) RESOLVED same day (Entry 14): CEO instructed flip_off, executed on GREEN, verified false post-recreate — weekly battery now dry-runs, no longer writes update_ability into the live tracker; nightly measurement path untouched as instructed. The 4-item capability-session priority list (fallback-template trace-pull, session-synthesis pack input, guide self-referential-leak fix, harvest-path endpoint) is now fully CLOSED 2026-08-02 — see capability-session-fallback-template-traced / capability-session-synthesis-pack-input / capability-session-guide-selfref-leak-fixed / capability-session-harvest-path-shipped; none are wired live (all additive/opt-in), each carries its own explicit "not built/not decided" residual (somatic-invitation gate loosening is a clinical-policy call, not resolved; commitment-demand line's acceptance test needs a future regeneration+re-score; harvest endpoint has no bulk-review UI yet). Phase M (W11/W12/M — claims registry, publisher gate, retract surfaces, BWAS provenance) is now fully CLOSED 2026-08-02 (commit a998821d) — see phase-m-marketing-bound; the SkyEye publisher-gate parity gap, therapeutic-advisory-sensitivity gap, BWAS provenance-weighting gap, and marketing-ingester sanitization gap are all closed with 23 new tests, deployed to GREEN (153/153), pushed to main. Phase R (R5 residuals) is now fully CLOSED 2026-08-02 — see phase-r-residuals: droplet-lockfile-mirror (hash-pinned frozen-config/ln7_droplet_requirements.lock + verify_droplet_lockfile() + droplet_bootstrap.sh, provisioning-tool tier) and R2-mirrored-base-weights-with-checksums (ln7_r2_weight_mirror.mirror_base_model_dir()/verify_base_model_checksums(), graceful-skip-until-pinned then fail-closed-on-drift) both built + wired into ln7_fallback_drill.py's existing supply_chain_pin step, 13 new tests + new fence test test_droplet_lockfile_weld.py, manifest.sha256.json regenerated. Only remaining Phase R item is explicitly non-blocking (R4 canary corpus GREEN-job auto-refresh, deferred).

**Gate-1 (affinity/quartet dose-response) status — CLOSED 2026-08-02:** Confirmed the `select_crisis_guides()` lexical-overlap affinity port was already landed and live on both call paths (`therapeutic_controller.py` text chat, `voice_pr_crisis_inject.py` voice mid-call) — `user_text` flows through to `_token_overlap_score`; `PROVENANCE.md` documents the pre-fix `before_no_affinity` condition explicitly lacked this ranking. Quartet dose-response scaffolding (migration 316, `quartet_dose_response_api.py`, `quartet_spine_moves.py`, `seed_quartet_dose_response.py`, `dashboard/quartet_dose_response.html`) built, deployed to GREEN, migration applied, queue seeded with the 8 rows (4 scenarios x before/after) using existing `six_quotient_human_gold` "after" data + recovered "before" transcripts. CEO scored all 8 rows the night of 2026-08-01/02 — see gate-1-dose-response-scored for the full grid result (net +1 move, 21/24 pairs unchanged, all 6 structural columns 0-for-40) and docs/ln7/TRUST_LEDGER.md Entry 1 for the transcript-check that reconciled a prior narrative overstatement ("ideation named directly, no hedge; 988 woven into the ideation sentence") against the actual durable `after_affinity_fix` row for AQ-1 (scored naming=absent — the quoted narrative traced to a different, non-persisted `/tmp` generation under a distinct run_id, not a seeding bug). Per CEO instruction, no changes were made to the crisis-inject/prompt-assembly seam during the scoring window — Phase H work (ln_rule_loop.py, bridge_server.py provenance-hash threading, migration 317) touched none of therapeutic_controller.py, voice_pr_crisis_inject.py, select_crisis_guides(), or any prompt-assembly path. That freeze is now lifted since gate 1 closed; the crisis seam (e.g. `fix/crisis-exempt-wiring`) merges through RED-adjacent review going forward, not as routine hygiene.

---

## Execution order

0. **Phase W skeletons** — migrations **305–310** (never 303/304); Redis key conventions; `notify_flywheel_anomaly`; task types `hive_burst` + `ln7_shadow_fork` (stubs OK). **Leave CEO promote path intact.**
1. **Step 0** — frozen-config ro volume (W13) + Goodhart reference + probes (W16) + boot manifest → W6 auto-flip (**this is the G0→G2 product-rule change**)
2. **W2 G2 cutover** — Dual-COO mechanical promote only after Step 0 green; until then Priority 1 / CEO activate remains valid
3. **A0** — base pin / quarantine; R5 weight mirror start
4. **W7 + B1** — envelope dual-write + route telemetry + provenance
5. **E** — leases (Redis TTL) + W17 anomaly kinds
6. **R4/R5 foundations** — envelopes, allowlists, canaries, fingerprint, lockfile mirror
7. **W3/W4/A** — hive_burst worker + serve endpoint Redis
8. **W5/W10/B2/B3** — router + BGE + intent queue + domain tags
9. **W1/G** — shadow fork end-to-end (promote still gated on shadow rows)
10. **W8/R2** — living pack distill
11. **D** — held-out / stratified bakeoffs / canary
12. **C** — Stage 4 when magazine has wins
13. **W11/W12/M** — claims + retract surfaces + BWAS provenance
14. **R1/R3/R6** — drift sentinel; shadow-eval + W14 PRs; influence Gini
15. **W15/H** — predicate poller → `PHASE_H_OPEN`
16. **R5 drills** — quarterly fallback calendar
