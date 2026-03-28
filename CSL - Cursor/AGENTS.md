# Autonomous Trust Verification Agents

These agents can be invoked by Cursor background agents to maintain 100% trust (344/344 checks, 19 auditors, 5 pre-flight).

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

2. **Service Health** — 80/80 healthy:
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

7. **Wait 5 minutes**, then verify 344/344:
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
| `SKYEYE_AUDIT_TOKEN` | Audit Token | All 19 auditors |
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
