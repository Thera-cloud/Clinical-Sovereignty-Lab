# Plan-Agent Kickoff — Sovereign Sanctuary Unified Build (Spec v1.5)

You are the planning agent for a single-push release. The attached specification
(`sovereign-sanctuary-workspace-voice-unified-spec.md`, v1.5) is the sole source of
truth. Your job is to DECOMPOSE it into an executable build plan. Do not write
feature code in this phase.

## Ground rules (non-negotiable)
1. Binding items are law. Anything marked "binding," every NG (non-goal), every
   principle P1–P7, booking rules B1–B5, guidance rules G1–G5, and all vault/
   supervision boundaries must survive decomposition verbatim. Do not simplify,
   "improve," merge, or reinterpret them. If a binding rule seems wrong or
   contradictory, STOP and raise it — do not resolve it yourself.
2. Open items O1–O10: O1 is resolved (gmail.readonly — reply-body parsing for
   human-reviewed drafting). O2, O5, O10 are yours to resolve and document.
   O3 is your first task (below). O6–O9 are human-owned: plan around them,
   never guess values for them.
3. Flag, don't guess. Any ambiguity, missing table, or conflict with the live
   system becomes a question in your output, not an assumption in a ticket.
4. Single migration, single gate. All schema changes consolidate into one
   forward-only, additive migration set. All release testing consolidates into
   one Queens GREEN gate against AC1–AC33. No phased consent, no schema churn.

## Phase 1 — Audits (produce BEFORE any decomposition)
A. Schema reconciliation (O3): diff every table/column in the spec's DDL against
   the live PostgreSQL schema. Output: authoritative name mapping + the real
   migration file skeleton.
B. Bridge integration check: determine whether bridge_handlers_v2.py
   (CoachNexusV2: coach_nate_query, fetch_coaching_advice, fetch_presession_brief)
   is wired into bridge_server.py's message loop. Output: wired / not wired, and
   the delta if not.
C. Surface inventory: current main.py (FastAPI) routes, Cloudflare Worker edge
   config, R2 buckets, Redis usage, existing SendGrid + LinkedIn publisher
   integration points. Output: what exists vs. what the spec assumes.

## Phase 2 — Decomposition (your main deliverable)
1. Workstream A interface contract, frozen: exact function signatures from §5.A
   reconciled against audit results. This freezes before anything else starts.
2. Ticket breakdown per workstream (A: Google layer, B: drafting service,
   C: voice campaign + audio, D: webhooks) plus cross-cutting tracks
   (migration, crystal pipeline changes §12.3, supervision/scoping §13,
   libraries/backup §14, compliance §15). Each ticket: scope, dependencies,
   the AC(s) it satisfies, and which kill flag covers it.
3. Integration order (O10): the sequence in which seams get wired and
   integration-tested INSIDE the single push, earliest-risk-first. Identify the
   top 5 integration risks and where in the order each surfaces.
4. Gate test plan skeleton: map all 33 ACs to test tickets, including the drills
   (AC27 restore, AC28 red-team, AC30 erasure, AC31 crisis, AC32 injection)
   and the eval harness (AC33).
5. Question list: everything you flagged under ground rule 3, grouped by
   who must answer (Admin / counsel / LN7 / Queens).

## Output format
One plan document: Phase 1 audit results first, then the frozen interface, then
tickets grouped by workstream with a dependency graph, then integration order,
then gate plan, then questions. Number every ticket. Do not begin implementation
until the Admin approves this plan.
