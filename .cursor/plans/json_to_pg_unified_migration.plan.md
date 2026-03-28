---
name: JSON to PG Unified Migration
overview: "Unified plan consolidating both JSON-to-PG migration approaches: (1) Fix profile_data overwrite risk in upsert_user(), (2) Eliminate dual-storage desync for sessions/billing/wisdom, (3) Migrate 100+ JSON reads across 8 routers to PG-first, (4) Create PG tables for clinically critical JSON-only files, (5) Enterprise bulk import. Supersedes: json_to_pg_migration_8e122964 and json_to_postgresql_migration_8443b291."
todos:
  - id: phase0-upsert-fix
    content: "URGENT: Fix upsert_user() in user_store.py to protect all 17 DB-owned profile_data keys from bridge cache overwrite (MFA, sentinel, usage counters)"
    status: pending
  - id: phase0-deploy-verify
    content: Deploy user_store.py fix, restart bridge, verify MFA/sentinel fields survive a bridge save cycle
    status: pending
  - id: phase1-sessions-pg
    content: "Migrate sessions.json: 10 remaining JSON-only endpoints in sessions.py to PG-first, fix Pool.execute bug"
    status: pending
  - id: phase1-billing-pg
    content: "Retire billing.json reads in billing.py (~20 sites), read from PG subscriptions/token_transactions, add Request param"
    status: pending
  - id: phase1-wisdom-pg
    content: "Make Night School wisdom writes go to PG first (wisdom_extractions table), JSON becomes backup"
    status: pending
  - id: phase2-admin-pg
    content: "Convert admin.py: ~16 user_registry.json reads + billing/sessions/analytics/crisis/audit/metrics JSON reads to PG-first"
    status: pending
  - id: phase2-coach-pg
    content: "Convert coach.py: user_registry, sessions, coach_notes, memory JSON reads to PG-first"
    status: pending
  - id: phase2-other-routers
    content: "Convert client_data_api.py, me2me.py, sanctuary_engine.py, drip_scheduler.py JSON reads to PG-first"
    status: pending
  - id: phase3-memory-pg
    content: "Create user_memories PG table (migration) and migrate memory.json reads/writes — clinically critical"
    status: pending
  - id: phase3-story-pg
    content: "Create client_narratives PG table (migration) and migrate story.json reads/writes — irreplaceable data"
    status: pending
  - id: phase3-coach-notes-pg
    content: "Create coach_session_notes PG table (migration) and migrate coach_notes.json reads/writes"
    status: pending
  - id: phase4-bulk-import
    content: "Build POST /api/admin/bulk-import/users endpoint with CSV upload, parallel password hashing (20 workers), batch PG insert, Redis cache sync — 5,000 users in ~1 minute"
    status: pending
  - id: phase5-pmb-deploy
    content: "Deploy pmb_reports.html to all 3 dashboard directories (/var/www/sovereign-command/, /opt/clinical-sovereignty-lab/dashboard/, /var/www/sovereignsanctuary-web/)"
    status: pending
  - id: deploy-verify
    content: "Deploy all changes, restart backend+bridge, verify service health + trust maintained"
    status: pending
isProject: false
---

# JSON to PostgreSQL Unified Migration Plan

> **Execution Order:** 3 of 4 — AFTER hallucination defense
> **Priority:** TIER 3 (data sovereignty)
> **Supersedes:** `json_to_pg_migration_8e122964.plan.md`, `json_to_postgresql_migration_8443b291.plan.md`
> **Deploy order:** Phase 0 (bridge upsert fix) first, then phases 1-3 (backend routers), then phase 4 (bulk import)

See the archived original plans for full architectural diagrams and detailed file-by-file analysis.

## Phase Summary

| Phase | Scope | Risk Level | Key Files |
|-------|-------|-----------|-----------|
| 0 | Fix `upsert_user()` profile_data overwrite (17 keys) | URGENT | `user_store.py` |
| 1 | Eliminate dual-storage desync (sessions, billing, wisdom) | HIGH | `sessions.py`, `billing.py`, `night_school_director.py` |
| 2 | Convert 100+ JSON reads across 8 routers to PG-first | MEDIUM | `admin.py`, `coach.py`, `client_data_api.py`, `me2me.py` |
| 3 | Create PG tables for clinically critical JSON-only files | MEDIUM | New migrations + service changes |
| 4 | Enterprise bulk import endpoint (5,000+ users from CSV) | LOW | `admin.py` |
| 5 | Deploy PMB tab | LOW | Dashboard HTML deploy only |

## Reusable PG-First Pattern

```python
pool = getattr(request.app.state, "db_pool", None)
if pool:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT ... FROM table WHERE ...", *params)
            return response_from_rows(rows)
    except Exception as e:
        logger.warning("endpoint_name: PG read failed: %s", e)

# JSON fallback (legacy)
data = load_json(PATH / "file.json", default)
```

## What Should Stay as JSON (No Migration)

- `google-service-account.json` — external credential
- `admin_settings.json` — small config, single writer
- `zoom_meeting_map.json` — ephemeral mapping
- Report files (`report_*.json`) — generated artifacts
- Search audit JSONL — append-only log
