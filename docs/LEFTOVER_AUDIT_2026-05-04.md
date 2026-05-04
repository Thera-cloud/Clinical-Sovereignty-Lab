# LEFTOVER_AUDIT_2026-05-04

Format: `path | line | marker | context` (one line each). Sorted: severity-style markers, then TODO, then DEFERRED/checklist/plan/schema notes. Truncated to ~500 tokens; full repo has hundreds of `- [ ]` and 278 `*.plan.md`.

## Markers (code / docs) — sorted FIXME → XXX → TODO → DEFERRED

- _(grep `*.py`/`*.dart`/admin)_ | — | FIXME | _(0 matches)_
- _(grep `*.py`/`*.dart`)_ | — | XXX | _(0 backlog markers; masks/URN placeholders excluded)_
- `backend/app/websocket/bridge_server.py` | 19646 | TODO | `# TODO(FOLLOW-UP SECURITY): Gate still treats any non-empty family_id as eligible;`
- `backend/app/services/identity_chain.py` | 37 | TODO | `# TODO(L4): Implement key rotation for Sovereign Mind master key. Current design`
- `backend/app/sse/layer0_orchestrator.py` | 151 | TODO | `# TODO Phase 5: Select best 3 journey panels from week → Grok Video Extend from`
- `backend/app/sse/thera_world_engine.py` | 7 | TODO | `# TODO: Couples — shared relational story space. Partner NPCs appear as`
- `backend/app/sse/thera_world_engine.py` | 9 | TODO | `# TODO: Dependents — age-gated biomes (brighter, gentler imagery).`
- `backend/app/sse/thera_world_engine.py` | 11 | TODO | `# TODO: Family coherence — family-level story thread when multiple members`
- `backend/app/sse/thera_world_engine.py` | 13 | TODO | `# TODO: Relational crystal linking — crystals from family therapy sessions`
- `backend/app/sse/quest_mission_engine.py` | 6 | TODO | `# TODO Phase 3: Crystal confidence levels affecting narrative intensity`
- `backend/app/sse/quest_mission_engine.py` | 7 | TODO | `# TODO Phase 3: Cross-domain crystal co-occurrence for complex NPCs`
- `backend/app/sse/quest_mission_engine.py` | 8 | TODO | `# TODO Phase 3: Quest/mission history endpoints`
- `backend/app/sse/quest_mission_engine.py` | 253 | TODO | `return fallback  # TODO Phase 3: LLM-composed quest panels with arc awareness`
- `backend/app/sse/quest_mission_engine.py` | 268 | TODO | `return fallback  # TODO Phase 3: LLM-composed mission panels`
- `backend/app/sse/quest_mission_engine.py` | 273 | TODO | `# TODO Phase 2B: Wire into crystal pipeline when new crystals are created in quest domain`
- `backend/app/services/counter_intelligence/counter_emitter.py` | 114 | TODO | `# TODO: When RSSI triangulation data is available from multiple`
- `backend/app/services/stripe_integration.py` | 2549 | TODO | `# TODO(scale): trial notifications will outnumber paid signups by 5–10× in any healthy funnel.`
- `backend/app/services/stripe_integration.py` | 2839 | TODO | `# TODO(scale): once paid-signup volume exceeds ~20/day, route this notification`
- `backend/app/services/twilio_grok_xtts_pipeline.py` | 7 | TODO | `TODO Phase 2: Azure OpenAI Chat fallback for text generation)`
- `backend/app/websocket/vault_bridge.py` | 420 | TODO | `preview["source"] = "chatgpt"  # TODO: store source in themes`
- `backend/migrations/migrate_to_postgres.py` | 305 | TODO | `# TODO: Map to sessions table when format is defined`
- `mobile/lib/counter_intelligence/ble_counter_emitter.dart` | 155 | TODO | `// TODO: Use platform channel to set BLE advertising data`
- `docs/OPEN_TODOS.md` | 13 | checklist | `| Coach Classroom WebSocket error leaves UI stuck (analyzing flag never resets) | UX | HIGH | mobile/lib/updated_screens.dart:6725 | 2026-04-30 |`
- `docs/OPEN_TODOS.md` | 14 | checklist | `| Sovereign Mind master key rotation procedure unimplemented | SECURITY | MEDIUM | backend/app/services/identity_chain.py:37 | 2026-04-30 |`
- `docs/OPEN_TODOS.md` | 15 | checklist | `| Wire lived wisdom extraction on sanctuary_complete to Night School | FEATURE | MEDIUM | backend/app/websocket/bridge_server.py:26814 + lived_wisdom.py | 2026-04-30 |`
- `docs/OPEN_TODOS.md` | 16 | checklist | `| Exit feeling_scale capture + Nevedal C_emo delta | FEATURE | MEDIUM | backend/app/websocket/bridge_server.py + sanctuary_engine | 2026-04-30 |`
- `docs/OPEN_TODOS.md` | 17 | checklist | `| Coach notification when sanctuary needs_review (beyond flag) | UX | MEDIUM | backend/app/websocket/bridge_server.py:27017 | 2026-04-30 |`
- `docs/OPEN_TODOS.md` | 21 | DEFERRED | `| The Eye sanctuary effectiveness dashboard + wisdom analytics | FEATURE | LOW | dashboard/the_eye.html | Product scoping needed |`
- `docs/OPEN_TODOS.md` | 22 | DEFERRED | `| Edge firmware scaffolding (fragment reassembly, mesh routing, OTA) | INFRA | LOW | edge/ | Pending ZEFCP ship |`
- `docs/OPEN_TODOS.md` | 23 | DEFERRED | `| SSE / Sovereign Command remaining media pipeline | FEATURE | LOW | backend/app/sse/ + studio | Large product scope |`
- `docs/OPEN_TODOS.md` | 24 | DEFERRED | `| Manual UX/QA verification of feature checklist items | QA | LOW | UX_AUDIT_FEATURE_CHECKLIST.md | Needs device QA session |`
- `docs/LITTLE_NATE_PROGRESS_CHECKLIST_UPDATED.md` | 86 | checklist | `| 6.1 Create \`extract_sanctuary_wisdom()\` function | ⬜ TODO | bridge_server.py | Medium |`
- `docs/LITTLE_NATE_LIVED_WISDOM_CHECKLIST.md` | 87 | checklist | `| 1.1 | Find existing Azure AI function name in codebase | ⬜ TODO | \`bridge_server.py\` | Low |`

## HACK

- _(0 matches in `*.py`/`*.dart`/admin `*.{ts,tsx,js,jsx}`)_

## Unchecked `- [ ]` (first 30 paths, count)

- `UX_AUDIT_REPORT.md` | — | checklist | 113 unchecked
- `.cursor/plans/SSE_Build_Status_Definitive.md` | — | checklist | 20 unchecked
- `.cursor/plans/SSE_Story_Creation_Generator_Spec_v1.3.1.md` | — | checklist | 76 unchecked
- `UX_AUDIT_FEATURE_CHECKLIST.md` | — | checklist | 37 unchecked
- `AUDIT_ACCOUNT_STATUS.md` | — | checklist | 16 unchecked
- `admin/node_modules/eslint-plugin-import/docs/rules/no-deprecated.md` | — | checklist | 2 unchecked
- `admin/node_modules/fast-uri/README.md` | — | checklist | 2 unchecked
- `UX_AUDIT_PACKAGE_SUMMARY.md` | — | checklist | 13 unchecked
- `docs/DATA_SOURCE_MAPPING_V2.md` | — | checklist | 16 unchecked
- `docs/ANALYTICS_AND_CRISIS_PROTOCOL.md` | — | checklist | 8 unchecked
- `docs/FAMILY_SANCTUARY_SPEC.md` | — | checklist | 82 unchecked
- `docs/SOVEREIGN_COMMAND_README.md` | — | checklist | 22 unchecked
- `docs/LOGIN_REQUIREMENTS_GUIDE.md` | — | checklist | 10 unchecked
- `docs/CURSOR_PROJECT_STRUCTURE.md` | — | checklist | 17 unchecked
- `docs/MOBILE_APP_UX_FLOW_TREE_V1.md` | — | checklist | 7 unchecked
- `docs/FAMILY_SANCTUARY_UX_FLOW_TREE_V4.md` | — | checklist | 5 unchecked
- `docs/DEPLOYMENT_GUIDE.md` | — | checklist | 8 unchecked
- `docs/FULL_STACK_CHECKLIST_V4.md` | — | checklist | 124 unchecked
- `docs/CLINICAL_SOVEREIGNTY_LAB_PROJECT_TREE.md` | — | checklist | 9 unchecked
- `docs/PROJECT_MASTER_DOCUMENTATION.md` | — | checklist | 34 unchecked
- `docs/DEVELOPMENT_PROTOCOL.md` | — | checklist | 13 unchecked
- `docs/MVVM_INTEGRATION_GUIDE.md` | — | checklist | 61 unchecked
- `docs/INTEGRATION_GUIDE.md` | — | checklist | 12 unchecked
- `docs/AUDIT_CLIENT_PORTAL_SETTINGS.md` | — | checklist | 7 unchecked
- `docs/FAMILY_SANCTUARY_AUDIT_CHARGES_VAULT_IAP.md` | — | checklist | 8 unchecked
- `edge/README.md` | — | checklist | 8 unchecked
- `mobile/ios/WIDGET_SETUP_INSTRUCTIONS.md` | — | checklist | 8 unchecked
- `UX_AUDIT_TECHNICAL_GUIDE.md` | — | checklist | 68 unchecked
- `BROWSER_DEBUGGING_GUIDE.md` | — | checklist | 7 unchecked
- `UX_AUDIT_README.md` | — | checklist | 21 unchecked

## `*.plan.md` (278 total; unfinished cues = Phase/Status/TODO/emoji — sample)

- `.cursor/plans/skyeye_live_data_overhaul_1b7e6f8d.plan.md` | 72 | plan | `## Phase 1: Fix Platform Connectivity (unblock all data flow)`
- `.cursor/plans/stripe_payment_ux_rebuild_a0f67933.plan.md` | 46 | plan | `## Phase A: Fix Critical Gaps`
- `.cursor/plans/sse_uniformity_build_plan_5459effc.plan.md` | 116 | plan | `## Item 3: Phase 4 -- Flutter Chat Integration`
- `.cursor/plans/sovereign_inference_alignment_6b373956.plan.md` | 6 | plan | `content: "Phase 1: Configure DO GPU droplet -- install Ollama, pull Qwen2.5-14B, WireGuard tunnel, verify GPU inference"`
- `docs/OPEN_TODOS.md` | 69 | plan | `- .cursor/plans/ (entire directory — historical planning)`

## `client_nate_messages` / `last_nate_message_at` (not abandoned — live references)

- `backend/migrations/110_client_nate_messages.sql` | 4 | schema-ref | `CREATE TABLE IF NOT EXISTS client_nate_messages (`
- `backend/migrations/046_deadman_activity_tracking.sql` | 9 | schema-ref | `ALTER TABLE users ADD COLUMN IF NOT EXISTS last_nate_message_at TIMESTAMPTZ;`
- `backend/app/services/checkin_reply_processor.py` | 148 | schema-ref | `"""INSERT INTO client_nate_messages (user_id, message, source, checkin_wisdom_id)`
- `backend/app/services/deadman_switch.py` | 68 | schema-ref | `u.last_nate_message_at,`
- `backend/app/websocket/bridge_server.py` | 9309 | schema-ref | `"UPDATE users SET last_nate_message_at = NOW() WHERE hardware_id = $1",`
