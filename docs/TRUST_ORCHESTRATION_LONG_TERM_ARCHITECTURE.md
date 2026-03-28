# Trust Orchestration Long-Term Architecture

This document captures the production-safe target architecture for trust execution and reporting.

## Goals

- Keep API multi-worker throughput.
- Remove duplicate trust sends and race conditions.
- Ensure deterministic trust-window execution.
- Maintain full auditability of scheduled/manual runs.

## Target Pattern

1. **API tier (multi-worker)**
   - Handles user/API traffic.
   - Does not own background scheduling long-term.

2. **Single-runner tier (1 replica)**
   - Owns all background agents including Trust Enforcer.
   - One process/container for all scheduled loops.

3. **Distributed lock**
   - Redis window claim using `SET key value NX EX`.
   - Window key example: `YYYY-MM-DD_HH`.
   - Manual and scheduled runs share the same lock key.

4. **DB idempotency ledger**
   - `trust_enforcer_run_records` with unique key `(window_key, run_type)`.
   - Status progression: `running -> sent|failed|skipped`.
   - Preserves history for compliance and incident review.

5. **Manual trigger safety**
   - `/api/trust-enforcer/trigger` calls same execution path and lock.
   - If lock/idempotency already claimed, response is `duplicate_skipped`.

## What Is Implemented Now

- Redis lock claim in Trust Enforcer window execution.
- Manual trigger now uses same hour window key as scheduled flow.
- DB idempotency ledger model added:
  - table: `trust_enforcer_run_records`
  - unique key: `(window_key, run_type)`
- API trigger endpoint returns:
  - `status: triggered|duplicate_skipped`
  - `email_sent: true|false`

## Remaining Work for Full Single-Runner Cutover

1. Add runtime role toggle in backend startup:
   - `NATE_RUNTIME_ROLE=api|runner|all`
2. Guard background agent startup behind role check.
3. Deploy dedicated `backend-runner` service (1 replica) in compose.
4. Keep API service scaled with workers for throughput.
5. Add health endpoint for runner liveness and lock freshness.

## Rollout Steps (recommended)

1. Apply DB migration for run ledger.
2. Deploy Trust Enforcer code with lock + DB guard.
3. Verify lock logs (`lock_acquired`, `lock_skipped`) in `skyeye_activity`.
4. Trigger twice within same minute window:
   - first => `triggered`
   - second => `duplicate_skipped`
5. Introduce `backend-runner` service with role gating.
6. Disable background starts on API tier.

