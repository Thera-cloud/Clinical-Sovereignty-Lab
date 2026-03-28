# CLI Program Production Close Runbook (Steps 1-5)

This runbook closes the current CLI/D1/nightly-audit build in production with explicit pass/fail and rollback criteria.

## Step 1 — Backend + Migration + Env (Production VPS)

1. Apply migration:
   - `docker exec nate_postgres psql -U nate_admin -d little_nate -f /opt/clinical-sovereignty-lab/backend/migrations/139_nightly_audit_and_extensions.sql`
2. Confirm required env vars in `/opt/clinical-sovereignty-lab/.env`:
   - `CLI_CLOUD_TOKEN`
   - `CLI_MAC_TOKEN`
   - `CLI_AUDIT_TOKEN`
   - `NIGHTLY_AUDIT_ENABLED=true`
   - `NIGHTLY_AUDIT_HOUR=4`
   - `NIGHTLY_AUDIT_RERUN_ON_CLI_REPAIR=true`
   - `D1_SANDBOX_DATABASE_ID`
3. Recreate services to load env (not restart-only):
   - `docker compose -f docker-compose.prod.yml up -d backend bridge`

Pass criteria:
- Backend logs show `STARTUP COMPLETE` with no import/schema errors.
- `nightly_audit_runner`, `d1_sandbox_executor`, `formula_registry`, `nate_webhook_dispatcher`, `cli_auditor` initialize.

Rollback criteria:
- If backend fails health or imports, restore prior backend image/container and re-run with previous env.

## Step 2 — Workers + D1 Schema

1. Apply sandbox schema to `cli-chamberofsecrets`:
   - `cd cloudflare/workers`
   - `npx wrangler d1 execute cli-chamberofsecrets --file ../d1/sandbox_schema.sql`
2. Deploy workers:
   - `cd nate-summon-worker && npx wrangler deploy`
   - `cd ../nate-cron-worker && npx wrangler deploy`
   - `cd ../nate-auth-edge && npx wrangler deploy`
   - `cd .. && npx wrangler deploy -c nate-edge-cache-wrangler.toml`
   - `cd nate-analytics-edge && npx wrangler deploy`

Pass criteria:
- Worker deploys succeed.
- D1 tables exist in `nate-hot` and `cli-chamberofsecrets`.

Rollback criteria:
- If a worker deploy fails, redeploy previous worker revision immediately before continuing.

## Step 3 — Smoke Tests (Functional)

1. Nightly audit endpoints:
   - `GET /api/admin/nightly-audit/status`
   - `POST /api/admin/nightly-audit/rerun`
2. CLI endpoints:
   - `/api/nate-agent/cli/health`
   - `/api/nate-agent/cli/read-access/allowlist`
   - `/api/nate-agent/cli/search/pending`
   - `/api/nate-agent/cli/backup/restore-request` (expect validation or queued behavior)
3. Gate behavior:
   - Set gate to blocked via override endpoint.
   - Verify CLIENT login blocked.
   - Verify live CLIENT `chat_message`/`nate_query`/`voice_query` blocked mid-session.
   - Set gate cleared and verify paths restore.

Pass criteria:
- All listed endpoints return expected status codes.
- Gate enforcement works at both login and mid-session interaction boundaries.

Rollback criteria:
- If gate blocks incorrectly for non-client roles or does not block client interaction paths, revert backend change and re-test.

## Step 4 — Trust and Auditor Verification

1. Trigger auditor cascade:
   - `POST /api/admin/skyeye-audit/send`
2. Verify CLI auditor:
   - Latest `skyeye_activity` contains `cli_audit_sent`.
3. Trigger trust enforcer:
   - `POST /api/trust-enforcer/trigger`
4. Verify trust output:
   - No new WARNING/FAILED related to CLI/nightly-audit surfaces.

Pass criteria:
- `cli_audit_sent` present.
- Trust report remains GREEN/expected.

Rollback criteria:
- If trust regresses due to new changes, revert only the failing component (backend or worker) and rerun steps 3-4.

## Step 5 — Close and Handoff

1. Mark production-close completion in ops notes:
   - migration applied
   - workers deployed
   - smoke tests passed
   - trust checks passed
2. Open next implementation stream:
   - `cli-littlenate-eval-system_5e6051a6.plan.md` (still pending by design).

Pass criteria:
- All prior steps are green.
- Team has a clear next build target (evaluation system).

## Required Verification Commands (Quick Bundle)

- `curl -s http://localhost:8000/health`
- `docker logs nate_backend --since 3m | rg "STARTUP COMPLETE|NightlyAudit|CliAuditor|D1SandboxExecutor|FormulaRegistry|WebhookDispatcher"`
- `docker logs nate_bridge --since 3m | rg "platform:audit:status|login_failed|PLATFORM_AUDIT_GATE_BLOCKED"`
- `docker exec nate_postgres psql -U nate_admin -d little_nate -c "SELECT COUNT(*) FROM nightly_audit_results;"`
- `docker exec nate_postgres psql -U nate_admin -d little_nate -c "SELECT COUNT(*) FROM innovation_proposals;"`

