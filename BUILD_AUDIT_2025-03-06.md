# Build Audit — 6 Mar 2025

## Executive Summary

| Category | Status | Action |
|----------|--------|--------|
| Trust / Memory Plan | ✅ Implemented | Verify migrations 112/113 applied on server |
| Check-in Reply Pipeline | ⚠️ Gaps | Twilio RLS bypass missing; parameter type fix needed |
| Nevedal Reports | ⚠️ Gap | User resolution fails for hardware_id-only lookups |
| Memory Search / Backfill | ✅ Present | Ensure backfill run for Lisa/Bill/LetsGoBill etc. |
| Family Sanctuary | ❌ Not built | HoH approval, member visibility, Nate interaction |
| Push in BRIEFINGS | ❌ Not built | Per-client push button |

---

## 1. Check-in Reply Pipeline — Critical Fixes

### 1.1 Twilio Webhook Missing `set_rls_admin()` (RLS Failure)

**Symptom**: "new row violates row-level security policy for table checkin_wisdom"

**Root cause**: The Twilio webhook (`backend/app/routers/twilio_webhook.py`) inserts into `checkin_wisdom` **without** calling `set_rls_admin()`. SendGrid inbound does call it (line 115). The Twilio path uses an unauthenticated connection, so RLS context is empty → INSERT fails.

**Fix**:
```python
# In twilio_webhook.py, before the async with db_pool.acquire() block
# that handles check-in reply (around line 230), add:
from app.services.rls_context import set_rls_admin
set_rls_admin()
```

**Location**: Before the `await conn.execute(... INSERT INTO checkin_wisdom ...)` in the free-text reply handler.

---

### 1.2 CheckInReplyProcessor "inconsistent types deduced for parameter $1"

**Symptom**: `CheckInReplyProcessor: DB store failed for DrNevedal1: ... inconsistent types deduced for parameter $1`

**Root cause**: The UPDATE and client INSERT use `$3::uuid` with `checkin_uuid` that can be `None`. asyncpg/PostgreSQL can infer conflicting types when the same parameter is used in `$3::uuid IS NULL` and `checkin_id = $3::uuid`.

**Fix**: Split logic by `checkin_uuid` or use explicit casts:
- When `checkin_uuid` is None: use a subquery that only filters by `created_at > NOW() - INTERVAL '5 minutes'`
- When `checkin_uuid` is set: use `checkin_id = $3::uuid`

Or use two separate queries to avoid polymorphic parameter typing.

---

## 2. Nevedal Reports — User Resolution 400

**Symptom**: "Could not resolve user: CLIENT_JAIMECARPENTER_ID"

**Root cause**: `nevedal_reports_api.py` resolves `subject_ids` by:
1. Trying `UUID(sid)` — fails for hardware_ids like `CLIENT_JAIMECARPENTER_ID`
2. Then `SELECT id FROM users WHERE hardware_id = $1 OR username = $1`

If the DB has `CLIENT_JAIMECARPENTER2_ID` or `jaimecarpenter` (username) but not `CLIENT_JAIMECARPENTER_ID`, resolution fails.

**Fixes**:
1. **Expand lookup**: Also match `profile_data->>'name'` (ILIKE) or `hardware_id ILIKE '%jaime%carpenter%'` for fuzzy resolution when exact match fails.
2. **Frontend**: Ensure the report UI sends the correct `hardware_id` from the users table (user picker should use `hardware_id` from API response, not display name).
3. **API response**: Return a clear error: "User X not found. Valid identifiers: hardware_id or username."

---

## 3. Trust / Memory Plan — Deployment Verification

### Implemented

- Admin backfill: `POST /api/admin/memory/backfill?dry_run=true` (optional `?hw_id=X`)
- Client App Auditor: Client Data Sync tab + `GET /api/client/health-check?hw_id=audit_client_hw`
- Memory Nesting Auditor: 1/1 TRUSTED format
- Trust Enforcer: `memory_nesting_audit_sent` + baseline
- Migrations: 112, 113

### Server Checks (run on 68.183.168.75)

```bash
# 1. Migrations applied
docker exec nate_postgres psql -U nate_admin -d little_nate -c \
  "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 5"

# 2. Trust baseline
docker exec nate_postgres psql -U nate_admin -d little_nate -c \
  "SELECT parameter_key, parameter_value FROM trust_baseline WHERE parameter_key IN ('client_app_endpoint_count','memory_nesting_check_count')"

# 3. conversation_history gaps (users with no rows)
docker exec nate_postgres psql -U nate_admin -d little_nate -c \
  "SELECT u.username, u.hardware_id FROM users u LEFT JOIN conversation_history c ON c.user_id = u.hardware_id WHERE u.role = 'CLIENT' AND c.user_id IS NULL"
```

### Backfill for Blank Memory Search

```bash
# Dry run first
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/admin/memory/backfill?dry_run=true"

# Full backfill (or with ?hw_id=CLIENT_LETSGOBILL_ID)
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/admin/memory/backfill"
```

---

## 4. Memory Search / conversation_history

| User | conversation_history | Notes |
|------|----------------------|-------|
| CLIENT_LETSGOLISA_ID | 22 rows | Has data |
| CLIENT_LETSGOBILL_ID | 0 | Likely no backfill; bridge may not have written |
| N3WdayBill, N3WdayLisa, HOLLISA | 0 | Same |

**Action**: Run backfill for all clients; verify bridge `db_pool` is healthy (logs: "Database pool created", "UserStore ready").

---

## 5. Gaps Not Yet Implemented

| Feature | Status |
|---------|--------|
| Family Sanctuary — HoH approval, member visibility, Nate interaction | Not built |
| Push button in BRIEFINGS (per-client) | Not built |
| Little Nate INSIGHTS cyan VIEW banner when coach opens app after reply | Check coach INSIGHTS fetch + `client_nate_messages` / `coach_nate_chat_history` wiring |
| Duplicate "I got your response" emails | Investigate dedup in `_send_follow_up` / notification flow |

---

## 6. Recommended Fix Order

1. **Twilio RLS** — Add `set_rls_admin()` to Twilio check-in reply handler (high impact, 2-line change)
2. **CheckInReplyProcessor parameter types** — Split NULL vs non-NULL `checkin_id` logic (fixes DrNevedal1)
3. **Nevedal Reports resolution** — Extend lookup to `profile_data->>'name'` or document correct ID format
4. **Run migrations 112/113** on server and verify trust/health
5. **Backfill conversation_history** for clients with blank Memory Search
