---
name: neural_tract_migration_first
overview: Integrate the neural tract pipeline into the bridge first (before Command Terminal UI swap), migrate all `cortex.process_interaction(...)` call sites to tract routing, and wire tract metrics + sleep cycle with graceful v5 fallbacks.
todos:
  - id: add-tract-module
    content: Add `neural_tract_pipeline.py` under websocket module path and align imports/utilities with repo conventions.
    status: completed
  - id: wire-bridge-init
    content: Initialize `tract_pipeline` in `bridge_server.py` with optional v5 dependency guards and logging.
    status: completed
  - id: migrate-all-callsites
    content: Replace all current `cortex.process_interaction(...)` call sites with `tract_pipeline.process(...)` while preserving context/session intent.
    status: completed
  - id: add-tract-ws-handlers
    content: Add `get_tract_metrics` and admin-only `trigger_sleep_cycle` websocket handlers and include read-only skip protection.
    status: completed
  - id: add-nightly-script
    content: Add `backend/scripts/nightly_sleep_cycle.py` and validate standalone execution/output behavior.
    status: completed
  - id: run-bridge-verification
    content: Validate startup, websocket response flow, admin gating, sentinel behavior, and non-v5 graceful fallback.
    status: completed
  - id: sequence-ui-swap-after
    content: Mark Command Terminal UI swap as dependent on successful tract migration verification.
    status: completed
isProject: false
---

# Neural Tract Migration First

## Goal and sequencing

Implement the tract-system migration first, then proceed to Command Terminal UI swap. This phase adds the neural tract runtime, routes all chat inference paths through it, and introduces tract observability + nightly consolidation.

## Source and target files

- Source references:
  - `[/Users/nathannevedal/Downloads/neural_tract_pipeline.py](/Users/nathannevedal/Downloads/neural_tract_pipeline.py)`
  - `[/Users/nathannevedal/Downloads/bridge_integration_guide.py](/Users/nathannevedal/Downloads/bridge_integration_guide.py)`
  - `[/Users/nathannevedal/Downloads/nightly_sleep_cycle.py](/Users/nathannevedal/Downloads/nightly_sleep_cycle.py)`
- Primary integration target:
  - `[/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py)`
- New runtime/module targets:
  - `[/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/neural_tract_pipeline.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/neural_tract_pipeline.py)`
  - `[/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/scripts/nightly_sleep_cycle.py](/Users/nathannevedal/Desktop/Clinical-Sovereignty-Lab-2/backend/scripts/nightly_sleep_cycle.py)`

## Migration plan

1. Add `NeuralTractPipeline` as a new websocket-side module and keep it wrapper-only around existing nuclei (`cortex`, `parietal`, `analytics_engine`, `night_school`, `billing_system_internal`, `sanctuary_engine`).
2. Initialize `tract_pipeline` after current bridge nucleus instantiation, with optional v5 dependencies (`CodeCycleDetector`, `CodeForesightEngine`, `CrystalQualityAuditor`) loaded via guarded imports and `None` fallback.
3. Migrate **all current** `cortex.process_interaction(...)` call sites to `tract_pipeline.process(...)` (scope confirmed), preserving each call’s contextual prompt/session behavior.
4. Add websocket handlers:
  - `get_tract_metrics` -> returns `tract_pipeline.get_tract_metrics()`
  - `trigger_sleep_cycle` -> admin-only manual trigger calling `tract_pipeline.enter_sleep_cycle()`
5. Register new read-only messages in `_SENTINEL_SKIP` to prevent false-positive Sentinel scoring from dashboard polling.
6. Add `backend/scripts/nightly_sleep_cycle.py` cron-compatible runner with graceful ImportError behavior for not-yet-built v5 services and JSON output to `data/sleep_cycle_results.json`.
7. Keep Command Terminal UI plan deferred until this tract migration is merged and runtime-verified.

## Compatibility and risk controls

- Preserve existing response contract (`nate_response`) and websocket protocol for Flutter compatibility.
- Maintain graceful degradation when v5 modules are absent.
- Avoid direct behavior changes to existing core classes (`AzureCortex`, `MetricsEngine`, `NightSchool`, `BillingSystem`) beyond wrapper invocation.
- Ensure billing behavior is not double-counted when moving through ascending stage checks.

## Verification checklist

- Bridge starts without import errors when v5 modules are missing.
- All migrated chat/coaching routes return expected responses via websocket.
- `get_tract_metrics` returns stable payload and can be polled safely.
- `trigger_sleep_cycle` rejects non-admin users and succeeds for admin.
- Nightly script runs standalone and writes `data/sleep_cycle_results.json`.
- No Sentinel regressions from new read-only message types.

## Hand-off to next phase

After this plan is complete and stable, resume the existing Command Terminal UI swap plan (`command_terminal_ui_swap_9b8ae38d.plan.md`) using the new tract metrics endpoint for live terminal visibility.