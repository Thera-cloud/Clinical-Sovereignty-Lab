# Autonomous Trust Verification Agents

These agents can be invoked by Cursor background agents to maintain 100% trust (493/493 checks, 26 auditors, 5 pre-flight).

---

## Agent 1: Pre-Deploy Trust Gate

**Trigger**: Before any deployment to production (68.183.168.75)
**Purpose**: Catch trust-breaking patterns before they reach the server

### Steps

1. **Schema Verification** — For every SQL query in changed files, verify column names exist:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c '\d TABLE_NAME'"
   ```

2. **Silent Exception Scan** — Grep changed files for `except Exception: pass` or `except Exception: return`:
   ```bash
   rg "except Exception.*:$" --glob "*.py" -A1 | rg "pass|return \[\]|return \{\}|return None"
   ```

3. **Catch-All Route Check** — If any router has `/{param}` routes, verify specific routes are defined first.

4. **Service Health Sync** — If `main.py` changed, count `_service_checks` entries and verify it matches the `service-health-49-49.mdc` denominator.

5. **Auditor 5-Location Sync** — If any `*_auditor.py` changed, verify TAB_ENDPOINTS count matches the corresponding `trust_baseline` row:
   ```bash
   python3 -c "exec(open('backend/app/services/AUDITOR.py').read()); print(sum(len(t['endpoints']) for t in TAB_ENDPOINTS))"
   ```

6. **load_dotenv Check** — Grep for `load_dotenv(override=True)` in changed files:
   ```bash
   rg "load_dotenv\(override=True\)" backend/
   ```

---

## Agent 2: Post-Deploy Trust Verifier

**Trigger**: After every deployment and backend restart
**Purpose**: Confirm 100% trust was maintained

### Steps

1. **Container Health** — All 5 containers running:
   ```bash
   ssh root@68.183.168.75 "docker ps --format '{{.Names}}\t{{.Status}}'"
   ```

2. **Service Health** — 85/85 healthy:
   ```bash
   ssh root@68.183.168.75 "docker logs nate_backend --since 2m 2>&1 | grep 'STARTUP COMPLETE'"
   ```

3. **Schema Error Scan** — No "does not exist" errors:
   ```bash
   ssh root@68.183.168.75 "docker logs nate_backend --since 2m 2>&1 | grep 'does not exist' | grep -v 'me2me\|metered_billing\|hive_forensic\|sha256_hash\|file_size\|scan_number\|audit_number\|fibre_type\|trigger_reason'"
   ```
   (The excluded patterns are pre-existing known issues)

4. **API Health**:
   ```bash
   ssh root@68.183.168.75 "curl -s http://localhost:8000/health"
   ```

5. **Bridge PostgreSQL** — Not degraded:
   ```bash
   ssh root@68.183.168.75 "docker logs nate_bridge 2>&1 | grep -E 'Database pool|UserStore|PostgreSQL Registry'"
   ```

6. **Trigger Audit Cascade** (if time permits):
   ```bash
   ssh root@68.183.168.75 'TOKEN=$(grep SKYEYE_AUDIT_TOKEN /opt/clinical-sovereignty-lab/.env | cut -d= -f2); curl -s -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/admin/skyeye-audit/send'
   ```

7. **Wait 5 minutes**, then verify 490/490:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT content FROM skyeye_activity WHERE type = 'trust_enforcer_sent' ORDER BY created_at DESC LIMIT 1\""
   ```

---

## Agent 3: SQL Column Auditor

**Trigger**: When editing any file in `backend/app/routers/` or `backend/app/services/`
**Purpose**: Prevent column name mismatches before they cause 500 errors

### Steps

1. Extract all SQL table references from the changed file:
   ```bash
   rg "FROM\s+(\w+)|INTO\s+(\w+)|UPDATE\s+(\w+)|JOIN\s+(\w+)" --only-matching FILE.py
   ```

2. For each referenced table, verify schema:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c '\d TABLE_NAME'"
   ```

3. Cross-reference every column name in the query against the actual schema.

4. Flag any mismatches with the correct column name.

### Known Mismatches to Fix

| File | Line | Wrong | Correct |
|---|---|---|---|
| `twilio_voice.py` | 44 | `users.user_id` | `users.id::text` or `users.username` |
| `twilio_voice.py` | 153 | `users.user_id` | `users.id::text` or `users.username` |
| `twilio_voice.py` | 157 | `skyeye_activity (action, details, timestamp)` | `(type, content, created_at)` |

---

## Agent 4: Auditor Endpoint Counter

**Trigger**: When editing any `*_auditor.py` file
**Purpose**: Keep TAB_ENDPOINTS count in sync with trust_baseline

### Steps

1. Count endpoints programmatically:
   ```bash
   python3 -c "
   exec(open('backend/app/services/AUDITOR_FILE.py').read())
   total = sum(len(t['endpoints']) for t in TAB_ENDPOINTS)
   print(f'{total} endpoints')
   for t in TAB_ENDPOINTS:
       print(f'  {t[\"tab\"]}: {len(t[\"endpoints\"])}')
   "
   ```

2. Check trust_baseline expected count:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT parameter_key, parameter_value->>'expected' FROM trust_baseline WHERE parameter_key LIKE '%KEYWORD%'\""
   ```

3. If counts differ, update the baseline:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"UPDATE trust_baseline SET parameter_value = jsonb_set(parameter_value, '{expected}', 'NEW_COUNT') WHERE parameter_key = 'KEY'\""
   ```

4. Verify the auditor's activity type exists in `AUDITOR_ACTIVITY_TYPES`, `AUDITOR_LABELS`, and `_baseline_key_for()` in `trust_enforcer.py`.

---

## Agent 5: Silent Exception Hunter

**Trigger**: Periodic or when editing router files
**Purpose**: Find and flag exception handlers that swallow errors without logging

### Steps

1. Scan for silent handlers:
   ```bash
   rg "except Exception" backend/app/routers/ -A2 | rg -B1 "pass$|return \[\]$|return \{\}$|return None$|body = |row = None"
   ```

2. For each finding, check if there's a `logger.warning` or `logger.error` call within the except block.

3. If no logging exists, flag it with the recommended fix:
   ```python
   except Exception as e:
       logger.warning("ENDPOINT_NAME: DESCRIPTION: %s", e)
       return []  # or appropriate fallback
   ```

4. Priority: Fix handlers in files that are actively audited first (skyeye_api.py, sessions.py, coherence_api.py).

---

## Agent 6: Environment Variable Guardian

**Trigger**: When editing `.env`, `.env.template`, `docker-compose.prod.yml`, or `main.py`
**Purpose**: Prevent env var drift that breaks trust pre-flight checks

### Required Variables for 100% Trust

| Variable | Pre-flight Check | Used By |
|---|---|---|
| `SKYEYE_AUDIT_TOKEN` | Audit Token | All 23 auditors |
| `AZURE_API_KEY` | Azure Env | AI Pipeline auditor |
| `AZURE_OPENAI_ENDPOINT` | Azure Env | AI Pipeline auditor |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Azure Env | AI Pipeline auditor |
| `AZURE_OPENAI_DEPLOYMENT` | Azure Env | AI Pipeline auditor |
| `AZURE_OPENAI_MINI_TTS_DEPLOYMENT` | Azure Env | AI Pipeline auditor |
| `REDIS_PASSWORD` | Redis | Trust Enforcer Redis check |
| `POSTGRES_PASSWORD` | (indirect) | All DB queries |

### Docker Compose Override Variables

These MUST exist in `docker-compose.prod.yml` `environment:` block:

| Variable | Docker Value | Why |
|---|---|---|
| `DATABASE_URL` | `postgresql://...@postgres:5432/...` | `.env` has `localhost` |
| `REDIS_URL` | `redis://:${REDIS_PASSWORD}@redis:6379` | `.env` has `10.0.0.81` |
| `REDIS_HOST` | `redis` | `.env` has `10.0.0.81` |
| `POSTGRES_HOST` | `postgres` | `.env` has `localhost` |

### Verification

```bash
ssh root@68.183.168.75 "docker exec nate_backend printenv | grep -E 'REDIS_HOST|DATABASE_URL|POSTGRES_HOST|AZURE|SKYEYE_AUDIT'"
```

---

## Agent 7: Token Economy Verifier

**Trigger**: After any change to token-related files (`token_lab_api.py`, `token_usage_agent.py`, `billing.py`, `stripe_integration.py`, `bridge_server.py`)
**Purpose**: Verify token consumption, purchase, and sharing pipelines are intact

### Steps

1. **Source Tag Completeness** — Verify all 4 consumption points in `bridge_server.py` pass a `source` parameter:
   ```bash
   rg "use_tokens\(|add_token_usage\(" backend/app/websocket/bridge_server.py | rg "source="
   ```
   Expected: 4 matches (ai_chat, sanctuary_ai, group_coaching, private_coaching).

2. **Token Transaction Schema** — Verify the `source` column exists on `token_transactions`:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c '\d token_transactions' | grep source"
   ```

3. **Token Pack Definitions** — Verify `TOKEN_PACKS` in `stripe_integration.py` has 4 entries with correct prices:
   ```bash
   python3 -c "
   import re
   content = open('backend/app/services/stripe_integration.py').read()
   packs = re.findall(r'\"(light|standard|power|ultimate)\".*?\"price_cents\":\s*(\d+)', content)
   for name, price in packs:
       print(f'  {name}: {int(price)/100:.2f}')
   assert len(packs) == 4, f'Expected 4 packs, found {len(packs)}'
   print('OK: 4 packs defined')
   "
   ```

4. **Usage Map Endpoint** — Verify `/api/token-lab/usage-by-source` returns data:
   ```bash
   ssh root@68.183.168.75 'curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/token-lab/usage-by-source?days=30 | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{len(d)} sources\")"'
   ```

5. **Token Usage Agent Running** — Verify agent is in `_service_checks` and started:
   ```bash
   ssh root@68.183.168.75 "docker logs nate_backend --since 5m 2>&1 | grep TokenUsageAgent"
   ```

6. **Webhook Handler** — Verify `_handle_checkout_completed` checks for `metadata.type == "token_pack"`:
   ```bash
   rg "token_pack" backend/app/services/stripe_integration.py
   ```

---

## Agent 8: GKM Donation Auditor

**Trigger**: After any change to `gkm_api.py`, `gkm.html`, `token_usage_agent.py`, or token sharing flow
**Purpose**: Verify GKM donation tracking, receipt generation, and Stripe integration

### Steps

1. **GKM Tables Exist** — Verify all 4 GKM tables were created by migration 076:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
     SELECT table_name FROM information_schema.tables
     WHERE table_name IN ('token_shares','gkm_donations','gkm_annual_receipts','gkm_discounts')
     ORDER BY table_name;
   \""
   ```
   Expected: 4 rows.

2. **GKM API Health** — Verify the health endpoint responds:
   ```bash
   ssh root@68.183.168.75 'curl -s http://localhost:8000/api/gkm/health'
   ```
   Expected: `{"status": "ok"}`

3. **GKM Router Registered** — Verify no import error on startup:
   ```bash
   ssh root@68.183.168.75 "docker logs nate_backend --since 2m 2>&1 | grep -i gkm"
   ```
   Should NOT contain `⚠️ GKM router failed`.

4. **Tax-Exempt ID Consistency** — Verify the tax ID in `gkm_api.py` matches the rule:
   ```bash
   rg "84-3879515" backend/app/routers/gkm_api.py
   ```
   Expected: at least 1 match.

5. **Share Fee Calculation** — Verify $5 per 10k tokens (500 cents per 10000 tokens):
   ```bash
   rg "SHARE_FEE_PER_10K|share_fee" backend/app/routers/gkm_api.py | head -5
   ```

6. **Cumulative Total Logic** — Verify `gkm_donations` INSERT updates `cumulative_total_cents`:
   ```bash
   rg "cumulative_total_cents" backend/app/routers/gkm_api.py
   ```

7. **Annual Receipt Automation** — Verify Token Usage Agent checks Jan 2nd:
   ```bash
   rg "annual_receipts\|month.*==.*1\|day.*==.*2" backend/app/services/token_usage_agent.py
   ```

8. **GKM Dashboard Deployed** — Verify `gkm.html` exists on server:
   ```bash
   ssh root@68.183.168.75 "ls -la /var/www/sovereign-command/gkm.html 2>/dev/null && echo 'EXISTS' || echo 'MISSING'"
   ```

9. **Navigation Tab** — Verify `command.html` includes the GKM nav tab:
   ```bash
   rg "gkm" dashboard/command.html
   ```

10. **Little Nate Gifting Response** — Verify `generate_gifting_response` exists in `skyeye_chat.py`:
    ```bash
    rg "generate_gifting_response" backend/app/services/skyeye_chat.py
    ```

---

## Agent 9: Token Balance Sovereignty Verifier

**Trigger**: After any change to `user_store.py`, `bridge_server.py`, or `token_lab_api.py`
**Purpose**: Ensure bridge cache does not overwrite direct DB token adjustments

### Steps

1. **Bridge Cache Merge Strategy** — Verify `user_store.py` uses `GREATEST` for `token_balance`:
   ```bash
   rg "GREATEST" backend/app/websocket/user_store.py
   ```
   Expected: `GREATEST(EXCLUDED.token_balance, u.token_balance)` or equivalent.

2. **Token Lab Quick Adjust Typing** — Verify `to_jsonb($1::int)` is used (not bare `to_jsonb($1)`):
   ```bash
   rg "to_jsonb" backend/app/routers/token_lab_api.py
   ```
   Expected: explicit `::int` cast.

3. **Token Transaction Async Logging** — Verify `_async_log_token_tx` uses `db_pool`:
   ```bash
   rg "_async_log_token_tx" backend/app/websocket/bridge_server.py
   ```

4. **Profile Data JSONB Merge** — Verify token resets use `jsonb_set`, not full profile replacement:
   ```bash
   rg "jsonb_set" backend/app/services/token_usage_agent.py | head -5
   ```
   Expected: multiple matches for `token_usage_today` and `token_usage_month` resets.

5. **No Full Profile Overwrite** — Verify `token_usage_agent.py` does NOT contain `SET profile_data =` without `jsonb_set`:
   ```bash
   rg "SET profile_data = \\\$" backend/app/services/token_usage_agent.py
   ```
   Expected: 0 matches (all updates should be `jsonb_set` based).

---

## Agent 10: QuickBooks Multi-Tenant Verifier

**Trigger**: After any change to `quickbooks_api.py`, `corp_quickbooks_api.py`, `coach_quickbooks_api.py`, `quickbooks_sync_agent.py`, `corporate_command.html`, or `coach_portal_v2_complete.dart`
**Purpose**: Verify all 3 QB tenants (admin, corp, coach) are wired correctly with security hardening intact

### Steps

1. **Migration 086 Applied** — Verify all 6 QB tables exist:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
     SELECT table_name FROM information_schema.tables
     WHERE table_name IN ('qb_corp_connection','qb_corp_sync_log','qb_corp_account_mapping',
                          'qb_coach_connection','qb_coach_sync_log','qb_coach_account_mapping')
     ORDER BY table_name;
   \""
   ```
   Expected: 6 rows.

2. **Tracking Columns Exist** — Verify `synced_to_corp_qb` and `synced_to_coach_qb` columns:
   ```bash
   ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
     SELECT table_name, column_name FROM information_schema.columns
     WHERE column_name IN ('synced_to_corp_qb','synced_to_coach_qb')
     ORDER BY table_name;
   \""
   ```
   Expected: 3 rows (payment_history, token_transactions, signup_sharing_ledger).

3. **Router Registration** — Verify all 6 routers loaded (3 auth-gated + 3 oauth):
   ```bash
   ssh root@68.183.168.75 "docker logs nate_backend --since 2m 2>&1 | grep -i 'quickbooks\|corp.*qb\|coach.*qb'"
   ```
   Must NOT contain `⚠️ ... router failed`.

4. **Admin QB Endpoints** — Verify health + callback:
   ```bash
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/admin/quickbooks/health'
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/admin/quickbooks/callback'
   ```
   Expected: 200 (health), 422 (callback — missing required params).

5. **Corp QB Endpoints** — Verify health + callback:
   ```bash
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/corp/quickbooks/health'
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/corp/quickbooks/callback'
   ```
   Expected: 200 (health), 422 (callback).

6. **Coach QB Endpoints** — Verify health + callback:
   ```bash
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/coach/quickbooks/health'
   ssh root@68.183.168.75 'curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/coach/quickbooks/callback'
   ```
   Expected: 200 (health), 422 (callback).

7. **CSRF State Token** — Verify Redis state storage pattern exists in all 3 callback handlers:
   ```bash
   rg "redis.*setex.*qb_oauth_state\|redis.*get.*qb_oauth_state" backend/app/routers/quickbooks_api.py backend/app/routers/corp_quickbooks_api.py backend/app/routers/coach_quickbooks_api.py
   ```
   Expected: 6 matches (setex + get per router).

8. **Token Encryption** — Verify `TokenCipher` is used in all 4 QB files:
   ```bash
   rg "TokenCipher|_cipher\.(encrypt|decrypt)" backend/app/routers/quickbooks_api.py backend/app/routers/corp_quickbooks_api.py backend/app/routers/coach_quickbooks_api.py backend/app/services/quickbooks_sync_agent.py
   ```
   Expected: matches in all 4 files.

9. **Secure Logger** — Verify no raw `logging.getLogger` in QB files:
   ```bash
   rg "logging\.getLogger" backend/app/routers/quickbooks_api.py backend/app/routers/corp_quickbooks_api.py backend/app/routers/coach_quickbooks_api.py backend/app/services/quickbooks_sync_agent.py
   ```
   Expected: 0 matches (all should use `get_secure_logger`).

10. **Rate Limiting** — Verify `_check_rate` exists in corp + coach routers:
    ```bash
    rg "_check_rate" backend/app/routers/corp_quickbooks_api.py backend/app/routers/coach_quickbooks_api.py
    ```
    Expected: matches in both files.

11. **Auditor Endpoint Counts** — Verify corporate_command and coach_dojo auditors match baselines:
    ```bash
    python3 -c "
    exec(open('backend/app/services/corporate_command_auditor.py').read())
    total = sum(len(t['endpoints']) for t in TAB_ENDPOINTS)
    assert total == 21, f'Corporate Command: expected 21, got {total}'
    print(f'Corporate Command: {total} ✅')
    "
    python3 -c "
    exec(open('backend/app/services/coach_dojo_auditor.py').read())
    total = sum(len(t['endpoints']) for t in TAB_ENDPOINTS)
    assert total == 55, f'Coach DOJO: expected 55, got {total}'
    print(f'Coach DOJO: {total} ✅')
    "
    ```

12. **Trust Baseline Updated** — Verify DB baseline matches code:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
      SELECT parameter_key, parameter_value->>'expected'
      FROM trust_baseline
      WHERE parameter_key IN ('corporate_command_check_count','coach_dojo_endpoint_count')
    \""
    ```
    Expected: `corporate_command_check_count` = 21, `coach_dojo_endpoint_count` = 55.

13. **Env Vars** — Verify all QB env vars are set:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_backend printenv | grep QB_"
    ```
    Expected: `QB_CLIENT_ID`, `QB_CLIENT_SECRET`, `QB_ENVIRONMENT`, `QB_REDIRECT_URI`, `QB_CORP_REDIRECT_URI`, `QB_COACH_REDIRECT_URI`.

14. **Intuit App Config** — Verify all 3 redirect URIs are registered in the Intuit Developer Portal. Cannot be automated — manual check required:
    - `https://api.sovereignsanctuary.net/api/admin/quickbooks/callback`
    - `https://api.sovereignsanctuary.net/api/corp/quickbooks/callback`
    - `https://api.sovereignsanctuary.net/api/coach/quickbooks/callback`

---

## Agent 11: Counterfactual Engine Verifier

**Trigger**: After any change to `bridge_server.py` (admin_member_removal_scenario handler) or `nevedal_lab_family.html`
**Purpose**: Verify the Member Removal Counterfactual Engine is deployed and functional

### Steps

1. **Bridge Handler Registered** — Verify the handler exists in the deployed bridge:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_bridge grep -c 'admin_member_removal_scenario' /app/app/websocket/bridge_server.py"
    ```
    Expected: >= 3 (handler definition + sentinel skip + response type).

2. **Sentinel Skip Entry** — Verify the handler is in `_SENTINEL_SKIP`:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_bridge grep 'admin_member_removal_scenario' /app/app/websocket/bridge_server.py | head -1"
    ```
    Expected: line containing `_SENTINEL_SKIP`.

3. **Dashboard Functions Present** — Verify counterfactual rendering functions exist:
    ```bash
    ssh root@68.183.168.75 "grep -c 'renderRemovalScenario\|renderSeparationDecoherence\|renderNateAssessmentPanel\|hideNateAssessmentPanel' /var/www/sovereign-command/nevedal_lab_family.html"
    ```
    Expected: >= 4.

4. **Ghost Node Rendering** — Verify ghost node support in draw2DNetwork:
    ```bash
    ssh root@68.183.168.75 "grep -c 'isGhost\|ghostIds\|ghostData' /var/www/sovereign-command/nevedal_lab_family.html"
    ```
    Expected: >= 3.

5. **Emotional Weather Snapshots Table** — Verify table exists and has required schema:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT column_name FROM information_schema.columns WHERE table_name = 'emotional_weather_snapshots' ORDER BY ordinal_position\""
    ```
    Expected: columns include `user_id`, `weather_type`, `intensity`, `recorded_at`.

6. **Nevedal Lab Auditor Updated** — Verify auditor has 30 checks (24 REST + 6 DB):
    ```bash
    python3 -c "
    exec(open('backend/app/services/nevedal_lab_auditor.py').read())
    rest = sum(len(t['endpoints']) for t in TAB_ENDPOINTS)
    db = len(DB_PIPELINE_CHECKS)
    total = rest + db
    assert total == 30, f'Expected 30, got {total} ({rest} REST + {db} DB)'
    print(f'Nevedal Lab: {total} ✅ ({rest} REST + {db} DB)')
    "
    ```

7. **Trust Baseline Updated** — Verify DB baseline matches:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT parameter_value->>'expected' FROM trust_baseline WHERE parameter_key = 'nevedal_lab_endpoint_count'\""
    ```
    Expected: `30`.

---

## Agent 12: Session Scheduling & Group/Corporate Verifier

**Trigger**: After any change to session scheduling, group/corporate assignment, or `updated_screens.dart`
**Purpose**: Verify dynamic session dropdowns and group/corporate data integrity

### Steps

1. **coach_get_clients Returns group_id** — Verify the bridge includes `group_id` in client data:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_bridge grep 'group_id' /app/app/websocket/bridge_server.py | grep -c 'coach_get_clients\|\"group_id\"'"
    ```
    Expected: >= 1.

2. **Flutter Build Compiles** — Verify the dynamic dropdown code compiles:
    ```bash
    cd mobile && flutter build web --release 2>&1 | grep -E "^lib/|Error:|error:" | head -10
    ```
    Expected: 0 errors.

3. **Session REST Endpoints** — Verify session scheduling endpoints respond:
    ```bash
    ssh root@68.183.168.75 'TOKEN=$(grep SKYEYE_AUDIT_TOKEN /opt/clinical-sovereignty-lab/.env | cut -d= -f2); curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/sessions/availability/COACH_COACHN_ID'
    ```
    Expected: 200.

4. **Corporate Field Sync** — Verify company_id column matches JSONB:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
      SELECT username, company_id::text, profile_data->>'company_id' AS json_cid
      FROM users
      WHERE company_id IS NOT NULL
        AND company_id::text != COALESCE(profile_data->>'company_id', '')
    \""
    ```
    Expected: 0 rows (no mismatches).

5. **Group Assignments Exist** — Verify clients have group_id assigned:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"
      SELECT username, profile_data->>'group_id' AS group_id
      FROM users
      WHERE profile_data->>'group_id' IS NOT NULL AND profile_data->>'group_id' != ''
    \""
    ```

6. **Data Uniformity Check Count** — Verify 21 checks:
    ```bash
    ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d little_nate -c \"SELECT parameter_value->>'expected' FROM trust_baseline WHERE parameter_key = 'data_uniformity_check_count'\""
    ```
    Expected: `21`.
