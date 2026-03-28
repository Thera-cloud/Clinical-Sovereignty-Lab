# Monetization Overhaul Risk Audit

## Scope

This audit tracks implementation progress against the `moat_pricing_overhaul_32d85e56` plan and evaluates risk posture by week.

## Implemented in this build

### Week 1: Predictability Foundation

- Implemented entitlement drift detection endpoint:
  - `GET /api/monetization-control/predictability`
  - File: `backend/app/routers/monetization_control_api.py`
- Aligned enforcement limits toward displayed plan values:
  - File: `backend/app/services/billing/tier_enforcement.py`

### Week 2: SkyEye Monitor-Only V1

- Implemented monitor API router with first 5 contract endpoints (+ health):
  - `GET /api/monetization-control/health`
  - `GET /api/monetization-control/overview`
  - `GET /api/monetization-control/predictability`
  - `GET /api/monetization-control/credits/depth-mix`
  - `GET /api/monetization-control/rails/reconciliation`
  - `GET /api/monetization-control/api-dojo/performance`
- Mounted router in app startup:
  - File: `backend/app/main.py`
- Added SkyEye tab + read-only loading panel:
  - File: `dashboard/skyeye.html`

### Week 3: Depth Classification

- Added depth classification logic in monetization endpoints (`core` vs `deep_noetic`).
- Added shadow ingestion of usage events from stripe usage reporting path:
  - File: `backend/app/services/stripe_integration.py`

### Week 4: Ledger Shadow Schema

- Added migration with core schema:
  - `backend/migrations/133_monetization_control_credit_ledger.sql`
  - Tables:
    - `usage_events`
    - `usage_ratings`
    - `credit_wallets`
    - `pricing_rule_versions`
    - `entitlement_snapshots`
    - `entitlement_reconciliation_conflicts`
    - `pricing_change_proposals`

### Week 5: Dual-Rail Reconciliation (Read + Resolve)

- Implemented reconciliation endpoints:
  - `GET /api/monetization-control/entitlements/{account_id}`
  - `POST /api/monetization-control/reconcile/{account_id}`
  - `GET /api/monetization-control/reconcile/conflicts`
  - `POST /api/monetization-control/reconcile/conflicts/{conflict_id}/resolve`

### Week 6: Governed Edit Workflow

- Implemented proposal workflow endpoints:
  - `POST /api/monetization-control/pricing/proposals`
  - `POST /api/monetization-control/pricing/proposals/{proposal_id}/approve`
  - `POST /api/monetization-control/pricing/proposals/{proposal_id}/apply`

### Commercial Layer (API Moat Overlay)

- Added moat catalog overlay without breaking legacy tiers:
  - `GET /api/enterprise/tiers/moat-catalog`
  - Legacy tier response now includes `moat_catalog_tier`
  - File: `backend/app/services/enterprise_api.py`

### SkyEye Auditor Coverage

- Added Monetization Control tab checks in SkyEye auditor:
  - File: `backend/app/services/skyeye_tab_auditor.py`
  - Total endpoint count now: `63`
- Added baseline migration:
  - `backend/migrations/134_skyeye_monetization_control_baseline.sql`

## Verification performed

- Python syntax compile:
  - `backend/app/routers/monetization_control_api.py`
  - `backend/app/services/enterprise_api.py`
  - `backend/app/services/billing/tier_enforcement.py`
- SkyEye auditor endpoint count check:
  - Confirmed `63` endpoints.
- Lint diagnostics check:
  - No linter errors in edited files.

## Gaps fixed (Mar 13 2026 audit pass)

### HIGH-1: Reconciliation summary fabricated matched=1 when zero conflicts existed
- **File:** `monetization_control_api.py` — `rails_reconciliation()`
- **Fix:** Removed the `checked=1; matched=1` fabrication block. Summary now accurately reports `checked=0, matched=0` when no conflicts exist, reflecting the true unaudited state.

### HIGH-2: Duplicate conflict rows on repeated reconcile calls
- **File:** `monetization_control_api.py` — `reconcile_account()`
- **Fix:** Added a `SELECT id ... WHERE account_id AND stripe_state AND apple_state AND status IN ('open','pending')` guard before insert. A new conflict is only created when no matching open/pending conflict exists for that account+state combination.

### HIGH-3: Multiple concurrently active pricing rule versions
- **File:** `monetization_control_api.py` — `apply_pricing_proposal()`
- **Fix:** Added `UPDATE pricing_rule_versions SET status = 'superseded' WHERE status = 'active'` before inserting the new active rule. The single-active invariant is now enforced transactionally.

### MEDIUM-1: Baseline migration silently no-ops when row missing
- **File:** `backend/migrations/134_skyeye_monetization_control_baseline.sql`
- **Fix:** Replaced bare `UPDATE` with `INSERT ... ON CONFLICT (parameter_key) DO UPDATE` so both fresh installs and existing deployments are handled.

### MEDIUM-2: Depth-mix endpoint missed token data when usage_events existed but was empty
- **File:** `monetization_control_api.py` — `credits_depth_mix()`
- **Fix:** Changed from `if ... elif` logic to a `used_usage_events` flag. If `usage_events` exists but returns zero rows, the endpoint now falls through to `token_transactions` for data.

### MEDIUM-3: Predictability mapping incomplete
- **File:** `monetization_control_api.py` — `DISPLAY_TO_ENFORCED_KEY`
- **Fix:** Added `COACH_ONLY` tier mapping. Extended `TRIAL` and `STANDARD` tiers to include `nevedal_per_month`, `foresight_per_month`, and `me2me_avatar_hours`. Added `coach_only` as a first-class entry in `TIER_LIMITS` (`tier_enforcement.py`) with `ai_session_minutes=0, coach_sessions=-1` matching `PLAN_DETAILS`.

## Residual risks (post-fix)

### Risk A: Runtime contract risk (Medium)

- Endpoints are implemented, but runtime behavior depends on migrations being applied.
- If migration `133` is not applied, some endpoints gracefully degrade but will not show full data.

Mitigation:
- Apply migrations in order (`133`, `134`) before audit run.

### Risk B: Baseline/trust sync risk (Low — was Medium)

- Auditor count changed from historical `58` to `63`.
- Baseline migration now uses UPSERT; works on both fresh and existing installs.

Mitigation:
- Verify `skyeye_endpoint_count.expected = 63` after migration.

### Risk C: Predictability semantics risk (Low — was Medium)

- All numerically comparable fields are now mapped across all 4 tiers (COACH_ONLY, TRIAL, STANDARD, TOP_TIER).
- Boolean/string features (`family_sanctuary`, `vault_search`, `realtime_voice`) are not drift-checked since they have no numeric counterpart in enforcement.

Mitigation:
- Consider adding boolean entitlement checks in a future pass if business requirements warrant it.

### Risk D: Reconciliation policy risk (Medium — was High)

- Conflict deduplication and single-active rule invariant are now enforced.
- Full automatic refund/grace policy for edge cases should still be expanded before hard cutover.

Mitigation:
- Keep reconciliation in controlled mode; require manual review for mismatches during canary.

### Risk E: UI integration risk (Low)

- SkyEye tab is integrated and read-only.
- Additional UX hardening (empty-state semantics, sorting, paging) can be done post-audit.

Mitigation:
- Run UI smoke tests for all new cards and endpoint failures.

## Audit runbook (post-deploy)

1. Apply migrations:
   - `133_monetization_control_credit_ledger.sql`
   - `134_skyeye_monetization_control_baseline.sql`
2. Restart backend.
3. Verify router health:
   - `GET /api/monetization-control/health`
4. Verify predictability:
   - `GET /api/monetization-control/predictability`
5. Verify SkyEye auditor count and trust baseline:
   - Ensure auditor total is `63`
   - Ensure baseline expected is `63`
6. Trigger SkyEye audit and inspect Monetization Control endpoints.
7. Reconciliation smoke:
   - run `POST /api/monetization-control/reconcile/{account_id}` on test account
   - check `GET /api/monetization-control/reconcile/conflicts`

## Go / No-Go summary

- **Go (staging):** Yes, for monitor/read-only + governed proposal flow.
- **Go (production canary):** Yes, after migrations + baseline sync + smoke pass.
- **Full cutover:** Keep in shadow mode until parity and reconciliation confidence are stable.
