# Identity Surface Inventory — Clinical Sovereignty Lab

**Generated:** 2026-05-12  
**Scope:** Read/write surfaces that bind behavior to a user or household identifier (`username`, `hardware_id`, UUID `users.id`, `family_id`, `company_id` / corporate, `group_id`, `device_id`, `session_id`, email-as-key).  
**Purpose:** Retroactive foundational spec so identity-era changes (e.g. Sensitive Bridge canonicalization 2026-03-22, `conversation_history` username merge 2026-05-12) can be traced and planned.

---

## Executive summary

| Metric | Approximate value |
|--------|-------------------|
| **PostgreSQL identifier-bearing columns** (public schema, pattern-filtered) | **229** rows in column inventory — see Appendix A |
| **Vault directory key** | **`hardware_id`** (folder name under `Clients` / `Coaches` / `Admin` / `Guests`) |
| **Bridge WebSocket** | **`~100`** top-level `elif t == "<message_type>"` branches in `bridge_server.py` (plus nested handlers); runtime identity from **`current_profile`** (`hardware_id`, `username`, role) |
| **REST surface** | **`backend/app/routers/*.py`** — **~85** router modules (canonical API layer); only **2** files match `backend/app/services/*_api.py` (`enterprise_api.py`, `security/sandbox_api.py`) — **do not** limit audits to `services/*_api.py` |
| **Redis** | Dominant pattern **`nate:{ENVIRONMENT}:auth:{token}`** — token maps to profile containing **`hardware_id`** + **`username`** in JSON payload |
| **Scheduled agents** | **`backend/app/main.py`** `lifespan()` → **`_service_checks`** — dozens of auditors/agents iterate users/tables by mixed identifiers |

**Identifier distribution (conceptual):**

- **`users` row:** canonical **`username`** (unique), **`hardware_id`** (stable device/account key), **`id`** (UUID PK). **`company_id`**, **`family_id`** on row + mirrored in `profile_data` JSONB for many flows.
- **`conversation_history.user_id`:** **TEXT — canonicalized to `username`** as of one-way PG migration **2026-05-12** (731 legacy hardware-keyed rows rewritten); **`partner_user_ids`**, **`family_id`** columns exist for multi-party rows.
- **`coaching_sessions`:** **`client_id` / `coach_id`** documented in migrations as **hardware_id-shaped TEXT**.
- **Crystals / legacy analytics:** mix **`user_id` UUID** (FK to `users.id`) vs **TEXT** username/hardware — **parallel split risk**.

**Known split risks (high level):**

1. **RLS policy vs column semantics drift** on `conversation_history` — see Critical findings.
2. **Vault / hippocampus** paths keyed by **`hardware_id`** while PG chat keyed by **`username`** — rebuild scripts must map username ↔ hardware_id (see `scripts/rebuild_memory_from_pg.py`).
3. **`family_id` / `company_id` / `group_id`** — household and org surfaces duplicate assignment fields (`coach_id`, `assigned_coach`, JSON vs column); corporate roster uses UUID company FK.

---

## Per-surface inventory (consolidated)

Columns are **Surface** (logical component), **Type**, **Identifier used**, **Source of truth**, **Migration story** (if canonical id changes), **Notes**.

| Surface | Type | Identifier used | Source of truth | Migration story | Notes |
|---------|------|-----------------|-----------------|-----------------|-------|
| **`users` / `users_secure`** | PG table | `username`, `hardware_id`, UUID `id`, `family_id`, `company_id` | **`users.username`** + **`users.hardware_id`** assigned at registration | Username rename = update all TEXT-keyed tables + vault folder rename + Redis profile payloads; hardware_id change = rare (device migration product gap) | `users_secure` mirrors sensitive columns; check both when adding columns |
| **`conversation_history`** | PG table | **`user_id` TEXT** (now **username** post–2026-05-12), `family_id`, `partner_user_ids` | **`username`** for new writes (`_persist_chat_to_conversation_history`); legacy rows were hardware_id until merged | One-way UPDATE migration applied 2026-05-12; backup `conversation_history_pre_migration_*.sql` | **Encryption:** `105_pgcrypto_sql_encryption.sql` — triggers/ciphertext columns; do not drop encrypted blobs |
| **`sessions`** | PG table | UUID `user_id`, UUID `coach_id` | **`users.id`** | UUID stable; username rename does not break FK | RLS uses **`app.acting_username`** → subselect `users.id` |
| **`coaching_sessions`** | PG table | TEXT `client_id`, TEXT `coach_id`, TEXT `family_id` | **hardware_id** per migration 107 comments | If coaching moves to username-keyed TEXT, bulk UPDATE + app changes | RLS uses **`app.acting_hardware_id`** |
| **`client_metrics` / `coach_metrics`** | PG table | UUID `user_id` + TEXT **`hardware_id`** | Dual — UUID FK + legacy TEXT | Risk: metrics writer uses one key and reader another | Audit writers |
| **`nate_intelligence_crystals`** | PG table | UUID `user_id`, TEXT `family_id`, scope fields | Primarily **UUID** `users.id`; recall bridges accept username OR hardware_id | Crystal recall must remap if user merge | Validator / Vectorize side indexes |
| **`token_transactions` / `token_usage_snapshots`** | PG table | **`username`** VARCHAR | **`username`** | Username rename = migrate rows | RLS `token_tx_app_own` uses acting identity |
| **`sensitive_bridge_log` / `sensitive_bridge_enrollment`** | PG table | **`user_id` TEXT** | Bridge/API writes — verify per handler | Align with coach/client username vs hw | Telemetry / audit |
| **`device_reputation` / `hive_devices` / BLE mesh** | PG + Redis-adjacent | **`device_id`**, sometimes `user_id` TEXT/VARCHAR | Device fingerprint | Device merge / ban lists | Parallel to human user ids |
| **Vault `data/bridge/Vaults/{Role}/{hardware_id}/`** | Filesystem | **`hardware_id`** folder name | **`users.hardware_id`** | Folder rename + update any hardcoded paths; **`memory.json`** rebuilt from PG via script | Sample: `Clients/CLIENT_LETSGOLISA_ID/memory.json`, `metrics.json`, backups `memory.json.pre_rebuild_*` |
| **`bridge_server.py` WebSocket dispatch** | WebSocket | **`t` message type** + **`current_profile`** | Login binds **`hardware_id`**, **`username`**, **`role`** to socket | All downstream handlers use profile dict | **~100** `elif t ==` branches — coaching, admin, vault, ** `get_presession_brief`**, **`admin_get_client_history`**, **`sensitive_profile_screen_opened`**, etc. |
| **`_persist_chat_to_conversation_history`** | Bridge fn → PG | **`username`** | `users.username` | Matches post–Mar-2026 canonical write path | INSERT uses username as `user_id` column value |
| **`_fetch_pg_history_for_chat`** | Bridge fn → PG | **username + hardware_id** | Dual query `WHERE user_id = ANY([username, hardware_id])` | Defensive alias read until all surfaces unified | May simplify after full PG backfill confidence |
| **`hippocampus` / MemorySystem** | Vault + Python | Path = **`hardware_id`** | Vault layout | memory.json content keyed by folder only | Coach briefings read **`memory.json`**, not PG directly |
| **`backend/app/services/api_server.py`** + routers | REST API | Bearer token → **`get_current_user`** profile | Redis **`nate:{env}:auth:{token}`** JSON | Token invalidation on identity change | **`set_rls_context(username, hardware_id, role)`** per `rls_context.py` |
| **`rls_context.py` / `RLSPoolWrapper`** | Middleware | Session GUCs **`app.acting_username`**, **`app.acting_hardware_id`**, **`app.acting_role`** | Authenticated request | Policies must match column semantics | See Critical findings |
| **Redis auth keys** | Redis | Key = token hex; **value** embeds profile | Bridge login | Re-login after profile mutation | Pattern **`nate:{ENVIRONMENT}:auth:{token}`** |
| **`nate:call_context:{call_sid}`** | Redis | Call SID | Voice pipeline | Session-scoped | Optional username inside JSON payload |
| **Flutter `mobile/lib/screens/*.dart`** | Client UI | **`widget.profile`** / **`currentUserProfile`** — `username`, `hardware_id`, `token` | Login / bridge success payload | Field names **not interchangeable** across widgets | Prefer **`Authorization: Bearer ${profile['token']}`** |
| **Dashboard HTML (`dashboard/*.html`)** | Admin UI | Session token + REST | Same Redis JWT/bridge token bridge | `_authHeaders()` pattern | SkyEye / Command client history |
| **Logs / telemetry** | PG / files | **`user_id` TEXT**, **`username`** in various tables | Emitter-dependent | **`sensitive_bridge_log.user_id`** — confirm alignment | Audit tables: `audit_log.admin_username`, `security_events.username`, etc. |

---

## Critical findings

### 1. `conversation_history` RLS vs username canonicalization (P0 — verify immediately)

- **Migration 107** defines **`convhist_app_own`** as:
  - `user_id = COALESCE(current_setting('app.acting_hardware_id', true), '')`
- **Documentation in 107** states `conversation_history.user_id` was **hardware_id-shaped TEXT**.
- **2026-05-12 data migration** rewrote legacy rows so **`user_id` holds `username`** (e.g. `LetsGoLisa`, `client1`) for merged accounts.
- **Bridge INSERT** (`_persist_chat_to_conversation_history`) inserts **`username`** into `user_id`.
- **Conflict:** For connections using role **`nate_app`** with RLS enforced, **`USING` / `WITH CHECK`** compare **`user_id`** to **`acting_hardware_id`**, not **`acting_username`**. Unless the DB role bypasses RLS or hardware_id equals username (false for typical clients), **policy semantics are stale**.
- **Action:** Run **`EXPLAIN`** / integration test as `nate_app`, or confirm bridge pool role (**`nate_admin`** / superuser bypass). If `nate_app` is used for client-scoped REST reads of `conversation_history`, **update policy** to:
  - `user_id IN (SELECT username FROM users WHERE hardware_id = current_setting('app.acting_hardware_id'))` OR equivalent dual match,
  - or compare `user_id = app.acting_username`.

### 2. Split identifier families (read ≠ write)

| Area | Write tends to use | Read tends to use |
|------|-------------------|-------------------|
| Coach scheduling PG | hardware_id TEXT (`coaching_sessions`) | Same if consistent |
| Nevedal / sessions PG | UUID `users.id` | Username via join |
| Vault memory | hardware_id path | PG fetch may use username |
| Token economics | username | — |

### 3. Sensitive Bridge era

- **2026-03-22** deploy (referenced commit **a7c03b7**): `_persist_chat_to_conversation_history` keyed by **`username`** going forward; legacy **`conversation_history`** rows remained **`hardware_id`** until **2026-05-12** merge migration (**731** rows across **8** hardware IDs).

### 4. Encryption boundaries

- **`105_pgcrypto_sql_encryption.sql`**: `convhist_encrypt_trigger()` and related — plaintext vs ciphertext columns for **`conversation_history`**. Identifiers in triggers keyed by row **`user_id`** column value — **after username migration, encryption metadata remains tied to row**.
- **Vault / disk:** client-side or bridge-side JSON encryption layers documented elsewhere — not duplicated here.

### 5. Corporate / family / group parallel risks

- **`users.company_id`** vs **`profile_data->>'company_id'`** — both must stay aligned per workspace rules.
- **`family_id`** on **`users`** + **`family_members`** + sanctuary/coherence tables — merging families requires coordinated FK updates.
- **`group_id`** — profile_json field for cohort scheduling; coach **`coach_get_clients`** merges assignment keys **`coach_id`**, **`assigned_coach_id`**, **`assigned_coach`**.

---

## Recommended actions

1. **RLS reconciliation:** Confirm runtime DB role for bridge/backend pools on **`conversation_history`**; patch **`convhist_app_own`** if **`nate_app`** must see username-keyed rows (priority **P0**).
2. **Single inventory query:** Re-run Appendix A SQL monthly after migrations.
3. **Automated check:** Add CI or admin script: “orphan `conversation_history.user_id` not in (`users.username` ∪ `users.hardware_id`)”.
4. **Vault tooling:** Keep **`scripts/rebuild_memory_from_pg.py`** **`--verify-only`** after PG identity changes.
5. **Router audit:** Expand endpoint enumeration from **`backend/app/routers/`** (not only `services/*_api.py`).
6. **Flutter contract:** Document canonical **`CoachDashboardScreenV2.currentUserProfile`** vs **`CommunityMeshScreen.profile`** to prevent wrong constructor keys.

---

## Appendix A — PostgreSQL column inventory (pattern-filtered)

**Query (executed 2026-05-12 against production-shaped schema):**

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (column_name LIKE '%user_id%'
       OR column_name LIKE '%hardware_id%'
       OR column_name LIKE '%username%'
       OR column_name LIKE '%corporate_id%'
       OR column_name LIKE '%family_id%'
       OR column_name LIKE '%group_id%'
       OR column_name LIKE '%device_id%'
       OR column_name LIKE '%client_id%')
ORDER BY table_name, column_name;
```

**Row count:** **229** (tabular rows below).

> **Coverage gap:** this filter uses `%corporate_id%` but not `%company_id%`. Tables such as **`users.company_id`** require a separate column grep when auditing corporate FK surfaces.

| table_name | column_name | data_type |
|------------|-------------|-----------|
| active_tokens | user_id | uuid |
| api_audit_log | client_id | uuid |
| api_clients | client_id | uuid |
| api_usage | client_id | uuid |
| assessment_results | user_id | character varying |
| audit_log | admin_username | character varying |
| backup_access_log | user_id | character varying |
| behavioral_access_log | user_id | character varying |
| call_metrics | user_id | character varying |
| canary_crystals | device_id | text |
| character_lora_models | user_id | text |
| checkin_wisdom | user_id | character varying |
| classroom_session_analyses | client_id | character varying |
| classroom_session_analyses | family_id | character varying |
| client_data_export_requests | user_id | text |
| client_fcodes | client_id | text |
| client_metrics | hardware_id | text |
| client_metrics | user_id | uuid |
| client_nate_messages | user_id | character varying |
| clinical_records | user_id | text |
| coach_client_overrides | client_user_id | character varying |
| coach_client_overrides | coach_user_id | character varying |
| coach_consultations | assistant_username | text |
| coach_consultations | master_username | text |
| coach_escalation_notifications | coach_username | text |
| coach_metrics | hardware_id | text |
| coach_metrics | user_id | uuid |
| coach_nate_chat_history | coach_username | character varying |
| coach_nate_progress | coach_username | character varying |
| coach_notes | client_id | uuid |
| coach_override_audit | client_user_id | character varying |
| coach_override_audit | coach_user_id | character varying |
| coach_profiles | coach_user_id | character varying |
| coach_profiles | username | character varying |
| coach_requests | client_id | character varying |
| coach_requests | client_username | character varying |
| coach_requests | coach_user_id | character varying |
| coaching_assessments | user_id | uuid |
| coaching_mesh_participants | ble_device_id | character varying |
| coaching_mesh_participants | user_id | character varying |
| coaching_sessions | client_id | text |
| coaching_sessions | family_id | text |
| coherence_measurements | family_id | uuid |
| coherence_measurements | user_id | uuid |
| coherence_time_crystals | user_id | text |
| community_attendance_records | user_id | character varying |
| community_check_ins | user_id | character varying |
| community_sessions | manager_user_id | character varying |
| consent_records | parent_user_id | text |
| consent_records | user_id | text |
| consent_requests | user_id | text |
| conversation_history | family_id | character varying |
| conversation_history | partner_user_ids | ARRAY |
| conversation_history | user_id | text |
| corporate_enrollments | user_id | uuid |
| crisis_events | family_id | text |
| crisis_events | hardware_id | text |
| crisis_events | user_id | uuid |
| crisis_watchlist | user_id | uuid |
| crystal_recall_log | user_id | text |
| crystal_replication | device_id | text |
| custody_dispute_records | family_id | text |
| cycle_detections | user_id | character varying |
| cycle_observations | user_id | character varying |
| cycle_predictions | user_id | character varying |
| data_deletion_queue | user_id | text |
| detector_telemetry | user_id | text |
| device_imprints | user_id | text |
| device_reputation | device_id | character varying |
| device_reputation | user_id | character varying |
| device_verification_codes | user_id | text |
| dojo_mentor_sessions | client_user_id | character varying |
| dojo_mentor_sessions | coach_user_id | character varying |
| drift_baselines | user_id | text |
| dynamic_assessments | user_id | uuid |
| emotional_weather_snapshots | family_id | text |
| engagement_requests | target_user_id | text |
| family_members | family_id | text |
| family_members | user_id | text |
| family_sanctuary_sessions | family_id | uuid |
| family_shared_events | family_id | text |
| gkm_annual_receipts | username | character varying |
| gkm_discounts | username | character varying |
| gkm_donations | username | character varying |
| google_calendar_connection | google_user_id | character varying |
| google_calendar_connection | user_id | character varying |
| google_calendar_sync_log | user_id | character varying |
| google_external_busy | user_id | character varying |
| grief_signals | user_id | text |
| group_entity_members | client_id | uuid |
| guardian_fibre_events | user_id | text |
| guardian_fibres | user_id | text |
| guardian_heartbeat_log | user_id | text |
| guardian_snapshots | user_id | text |
| heritage_vault_records | user_id | text |
| hive_backup_access_log | user_id | character varying |
| hive_devices | device_id | character varying |
| hive_wipe_operations | device_id | character varying |
| hoh_decision_observations | family_id | uuid |
| hoh_decision_observations | hoh_user_id | uuid |
| identity_drift_flags | user_id | text |
| identity_refinement_log | user_id | text |
| intensity_ledger | user_id | text |
| legacy_vault_consent | family_id | uuid |
| legacy_vault_consent | user_id | uuid |
| legacy_vault_entries | family_id | uuid |
| legacy_wishes | user_id | text |
| liminal_resolve_states | user_id | text |
| liminal_sessions | user_id | character varying |
| linguistic_fingerprints | user_id | text |
| livestream_wisdom | matched_client_id | text |
| mandatory_reporting_protocols | user_id | text |
| me2me_avatars | user_id | text |
| me2me_consent_records | user_id | text |
| me2me_family_fabrics | family_id | text |
| me2me_identity_crystals | user_id | text |
| me2me_imprint_entries | user_id | text |
| me2me_migrations | user_id | text |
| me2me_sovereign_trusts | user_id | text |
| memory_ledger | user_id | uuid |
| metered_billing_state | user_id | text |
| narrative_identity_profiles | user_id | text |
| narrative_state_objects | user_id | text |
| nate_checkins | user_id | character varying |
| nate_insights | user_id | uuid |
| nate_intelligence_crystals | family_id | character varying |
| nate_intelligence_crystals | user_id | uuid |
| nate_nudges | user_id | uuid |
| neural_fingerprints | user_id | text |
| nevedal_coherence_metrics | user_id | uuid |
| nevedal_metrics | user_id | uuid |
| nso_history | user_id | text |
| oauth_clients | client_id | character varying |
| onboarding_initiations | user_id | text |
| payment_history | user_id | uuid |
| pending_signups | username | character varying |
| pgsd_family_entanglement | family_id | character varying |
| pgsd_snapshots | user_id | character varying |
| pgsd_trajectories | user_id | character varying |
| pmb_report_requests | client_hardware_id | character varying |
| pmb_report_requests | client_username | character varying |
| prospect_story_store | user_id | uuid |
| prospects | converted_to_client_id | uuid |
| public_summon_usage | converted_username | character varying |
| qb_coach_account_mapping | coach_username | character varying |
| qb_coach_connection | coach_username | character varying |
| qb_coach_sync_log | coach_username | character varying |
| quiz_client_submissions | user_id | text |
| quiz_responses | user_id | uuid |
| safe_silence_mode_active_users | username | character varying |
| safe_silence_mode_state | user_id | text |
| safe_silence_state_v | user_id | text |
| sanctuary_members | user_id | uuid |
| scholarship_allocations | beneficiary_user_id | uuid |
| scholarship_funds | sponsor_user_id | uuid |
| scope_violation_logs | user_id | text |
| security_events | username | character varying |
| sensitive_bridge_enrollment | user_id | text |
| sensitive_bridge_log | user_id | text |
| sentinel_records | user_id | text |
| session_packs | user_id | uuid |
| session_summaries | client_id | text |
| sessions | user_id | uuid |
| six_quotient_growth | user_id | character varying |
| skyeye_social_memory | matched_user_id | uuid |
| slf_export_requests | user_id | text |
| slf_import_requests | user_id | text |
| sse_admin_alerts | user_id | text |
| sse_biome_state | user_id | text |
| sse_delivery_gap_log | user_id | text |
| sse_delivery_generation_log | user_id | text |
| sse_delivery_outcomes | user_id | text |
| sse_enrolled_users | user_id | text |
| sse_identity_forge | user_id | text |
| sse_missions | user_id | text |
| sse_panel_log | user_id | text |
| sse_parts_registry | user_id | text |
| sse_quests | user_id | text |
| sse_therapeutic_audit_log | user_id | text |
| sse_user_journeys | user_id | text |
| sse_user_locale | user_id | text |
| sse_workbook_progress | user_id | text |
| staged_deletions | user_id | text |
| student_verifications | user_id | uuid |
| subscription_items | user_id | uuid |
| subscriptions | user_id | uuid |
| summon_interactions | username | character varying |
| summon_tokens | username | character varying |
| therapeutic_habit_tracking | user_id | character varying |
| therapeutic_predictions | family_id | character varying |
| therapeutic_predictions | user_id | character varying |
| tmc_training_data | user_id | text |
| token_economics | user_id | uuid |
| token_shares | receiver_username | character varying |
| token_shares | sharer_username | character varying |
| token_transactions | username | character varying |
| token_usage_snapshots | username | character varying |
| trial_fingerprints | user_id | text |
| ucd_creative_directives | user_id | text |
| usage_meters | user_id | text |
| usage_records | user_id | text |
| user_legal_status | user_id | text |
| user_linguistic_baseline | user_id | text |
| user_polyvictimization_layers | user_id | text |
| user_prospect_journey | user_id | uuid |
| user_prospect_journey | username | character varying |
| user_safety_codewords | user_id | text |
| user_trigger_dates | user_id | text |
| users | family_id | uuid |
| users | hardware_id | character varying |
| users | username | character varying |
| users_secure | family_id | uuid |
| users_secure | hardware_id | character varying |
| users_secure | username | character varying |
| v_clinician_authorization_mode | coach_user_id | character varying |
| v_clinician_authorization_mode | username | character varying |
| v_user_nevedal_state | user_id | uuid |
| vault_item_annotations | user_id | character varying |
| virtual_eeg_traces | user_id | text |
| voice_accounts | user_id | text |
| voice_crystals | user_id | text |
| voice_emotional_baselines | user_id | text |
| voice_enrollment_profiles | user_id | text |
| voice_mandatory_reporting_events | user_id | text |
| voice_sessions | user_id | text |
| voice_transactions | user_id | text |
| wisdom_extractions | family_id | uuid |
| wisdom_extractions | user_id | uuid |
| zefcp_endpoints | device_id | character varying |

---

## Appendix B — Raw command fragments (reference)

**Vault sample (GREEN host):**

```text
/opt/clinical-sovereignty-lab/data/bridge/Vaults/{Clients,Coaches,Admin,Guests}/
Clients/<hardware_id>/memory.json | metrics.json | memory.json.pre_rebuild_*
```

**Redis sample keys (`SCAN` prefix `nate:*`):**

```text
nate:production:auth:<64-char-hex-token>
```

**WebSocket dispatch grep:**

```bash
grep -n 'elif t ==' backend/app/websocket/bridge_server.py
# ~100 primary branches (auth, chat_message, coach_get_clients, get_presession_brief, …)
```

**Migrations touching RLS / identity:**

- `backend/migrations/104_security_hardening.sql` — users, vault, token_transactions policies  
- `backend/migrations/107_rls_phase2_clinical_tables.sql` — sessions, coaching_sessions, **conversation_history**, nevedal_metrics, crisis_watchlist  
- `backend/migrations/105_pgcrypto_sql_encryption.sql` — conversation_history encryption triggers  

**ALTER TABLE … user_id / hardware_id** (non-exhaustive grep): `011_prospect_to_user_linking.sql` + broader identity ALTER history lives across `backend/migrations/*.sql` — treat migrations directory as authoritative changelog.

---

*End of inventory — update when adding tables, new Redis namespaces, or changing RLS GUC contract.*
