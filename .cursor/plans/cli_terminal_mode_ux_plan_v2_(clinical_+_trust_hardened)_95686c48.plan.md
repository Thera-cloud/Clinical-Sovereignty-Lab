---
name: CLI Terminal Mode UX Plan v2 (Clinical + Trust Hardened)
overview: Harden the CLI Terminal Mode UX into a clinically safe, mode-governed execution system with explicit approval locking, strict state transitions, idempotency, artifact integrity, and graded authority expansion for LN-fab.
todos:
  - id: mode-ux-contract
    content: Implement mode selector + previewer with visible NO-DEPLOY/NO-EDIT/LIVE EXECUTION tags
    status: pending
  - id: approval-schema-hashlock
    content: Add ApprovalRecord contract with scope_hash lock, TTL, and clinical_sign_off requirements
    status: pending
  - id: state-machine-guards
    content: Implement formal run state machine with blocked transitions, conflict states, and audit suspension path
    status: pending
  - id: idempotency-concurrency
    content: Add idempotency key + duplicate suppression + one-active-run execution guard
    status: pending
  - id: corrective-validation
    content: Validate parent_build_id existence/completed-state before corrective request creation
    status: pending
  - id: artifact-canonicalization-storage
    content: Add canonical ArtifactRecord wrapping and size-tiered DB/R2 storage policy
    status: pending
  - id: clinical-gates
    content: Add session_protection_check and mandatory rollback_procedure for production-impacting executions
    status: pending
  - id: learning-memory-review
    content: Implement forbidden field redaction plus automated and Big Nate clinical review gates
    status: pending
  - id: grading-reproducibility
    content: Add rubric_version, scorer_identity, evaluation_context, and model_version to scoring records
    status: pending
  - id: tests-trust-coverage
    content: Add transition/idempotency/hashlock tests and update CLI auditor/trust baseline counts
    status: pending
isProject: false
---

# CLI Terminal Mode UX Plan v2 (Clinical + Trust Hardened)

## Objective

Evolve Command Terminal into a Cursor-like mode system (`Plan`, `Ask`, `Debug`, `LN-fab`) with explicit visual behavior contracts and backend-enforced clinical/trust controls before any production execution.

## Core Changes

### 1) Mode UX + Visual Contract (UI)

- Update [dashboard/skyeye.html](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/dashboard/skyeye.html) to add:
  - `Pick mode` selector and previewer workflow.
  - Mandatory mode capability tags visible pre-approval:
    - `Plan`/`Ask` -> `NO-DEPLOY`
    - `Debug` -> `NO-EDIT`
    - `LN-fab` -> `LIVE EXECUTION` (red)
  - Actions: `Generate Preview`, `Approve`, `Revise`, `Promote to LN-fab`.
  - Promotion behavior: auto-switch to `LN-fab`, require explicit re-execute.

### 2) Explicit Approval Contract + Scope Lock

- Extend [backend/app/routers/nate_agent_api.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/routers/nate_agent_api.py) with a strict approval record model:
  - `run_id`, `approved_by` (must be `big_nate`), `approved_at`, `approval_reason`, `mode_transition`, `scope_hash`, `expires_at`, `clinical_sign_off`.
- Enforce execution only when artifact hash equals approved `scope_hash`.
- Approval TTL: 4 hours; if expired before start -> `requires_reapproval`.

### 3) Formal State Machine + Transition Guards

- Implement run-state transitions in API/service layer:
  - `draft -> preview_generating -> preview_ready -> approved -> executing -> completed`
  - failure branch: `execution_failed -> rollback_pending -> rolled_back`
  - rejection/expiry: `rejected -> archived`, `approved -> expired -> requires_reapproval`
  - corrective path: `completed -> corrective_requested -> draft(new,parent_build_id)`
  - audit suspension: `approved -> suspended_audit_failure`
  - conflict branch: `conflict_detected -> pending_admin_resolution -> resolved_*`
- Block invalid transitions:
  - `executing -> executing`
  - duplicate `approved -> approved`

```mermaid
flowchart TD
  draft[Draft] --> previewGenerating[PreviewGenerating]
  previewGenerating --> previewReady[PreviewReady]
  previewReady --> approved[Approved]
  previewReady --> rejected[Rejected]
  approved --> executing[Executing]
  approved --> expired[Expired]
  approved --> suspendedAuditFailure[SuspendedAuditFailure]
  executing --> completed[Completed]
  executing --> executionFailed[ExecutionFailed]
  executionFailed --> rollbackPending[RollbackPending]
  rollbackPending --> rolledBack[RolledBack]
  completed --> correctiveRequested[CorrectiveRequested]
  correctiveRequested --> draft
  previewReady --> conflictDetected[ConflictDetected]
  conflictDetected --> pendingAdminResolution[PendingAdminResolution]
  pendingAdminResolution --> resolvedApproveOne[ResolvedApproveOne]
  pendingAdminResolution --> resolvedApproveSequential[ResolvedApproveSequential]
  pendingAdminResolution --> resolvedRejectBoth[ResolvedRejectBoth]
```



### 4) Idempotency + Concurrency Safety

- Add deterministic idempotency key computation in API path:
  - `SHA256(cli_agent + mode + request_text + parent_build_id + approved_by)`.
- TTL window: 300s; repeated submissions return existing run.
- Enforce one active execution per `(cli_agent, mode, parent_build_id)`.

### 5) Corrective Request Validation

- For corrective requests in [backend/app/routers/nate_agent_api.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/routers/nate_agent_api.py):
  - Validate `parent_build_id` exists.
  - Parent run must be `completed` and correction-eligible.
  - Reject parent runs in `executing` or terminal-invalid states.

### 6) Artifact Ownership + Storage Rules

- Contract:
  - CLI produces raw output.
  - API/bridge wrapper canonicalizes and versions artifact record.
  - Dashboard renders only canonical artifact records.
- Storage policy:
  - `<4KB` content in PostgreSQL artifact table.
  - `>=4KB` content in R2 with DB pointer.
  - All LN-fab execution logs in R2.
  - Retention: active/audit evidence indefinite; archived 365 days.

### 7) Clinical Safety Gates Before Execution

- Add pre-execution gates:
  - `session_protection_check`: block session-adjacent infra actions when escalation-level protections are active.
  - `rollback_procedure` required (non-empty) for production-impact runs.
- If approval expires mid-execution:
  - continue to completion, mark `approval_expired_mid_execution`, require post-hoc review.

### 8) Learning Memory Safety + Clinical Review Gate

- Add memory persistence with forbidden field policy:
  - no identifiers, session text, credentials, diagnosis/clinical specifics, family identifiers.
- Two-stage review:
  - automated redaction gate
  - Big Nate clinical sign-off for session-context touching patterns
- Failed patterns go to quarantine table, never auto-promoted.

### 9) Grading Reproducibility + Authority Expansion

- Persist scoring with reproducibility metadata:
  - `rubric_version`, `scorer_identity`, `evaluation_context`, `model_version`, `evaluation_date`.
- Add authority gates based on demonstrated competence (not generic feature flags):
  - e.g., infra repairs, LN-fab execution, fine-tune proposals, compliance updates.

### 10) Testing + Trust Integration

- Add tests for:
  - transition validity matrix
  - hash-lock execution matching
  - idempotency duplicate suppression
  - corrective validation paths
  - expiry/suspension/conflict branches
- Extend CLI auditor/trust baseline to include new mode workflow endpoints and counts.

## Target Files

- [dashboard/skyeye.html](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/dashboard/skyeye.html)
- [backend/app/routers/nate_agent_api.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/routers/nate_agent_api.py)
- [backend/app/websocket/bridge_server.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py) (or dedicated artifact canonicalization service)
- [backend/migrations](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/migrations) (new schema + indexes)
- CLI/trust auditor service files in [backend/app/services](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/services)

## Acceptance Criteria

- Visual behavior contract always visible and mode-accurate in UI.
- No execution without valid approval record, matching `scope_hash`, non-expired TTL, and required clinical sign-off.
- Invalid transitions, duplicate approvals, and duplicate execute actions are rejected deterministically.
- Corrective requests fail fast for invalid/non-completed parent build IDs.
- Artifact storage follows size-tier policy with verifiable pointers.
- Learning memory writes pass redaction + clinical review gates.
- Grading records are reproducible across rubric/model/evaluation contexts.
- Trust/auditor coverage includes all new mode endpoints and reports baseline-consistent counts.

