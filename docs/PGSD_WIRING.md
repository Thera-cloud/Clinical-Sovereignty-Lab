# PGSD Wiring Guide

The Planetary Galactic Scale Detector (PGSD) ships in layers:

| Piece | Path |
|---|---|
| Computation engine | `backend/app/services/pgsd_engine.py` |
| WebSocket router | `backend/app/websocket/pgsd_handlers.py` |
| Safe trigger facade | `backend/app/services/pgsd_triggers.py` |
| Heartbeat agent | `backend/app/services/pgsd_heartbeat_agent.py` |
| Core schema | `backend/migrations/191_pgsd_tables.sql` |
| Access + field schema | `backend/migrations/283_pgsd_access_field.sql` |

Bridge integration is **gated behind `PGSD_ENABLED`** (off by default). Sub-flags
layer on top — see **Flag order** below.

## Identity contract

- **Canonical `user_id` in all PGSD tables = `users.hardware_id`.**
- Callers may pass `users.id` (UUID), `hardware_id`, or `username`; resolve via
  `PGSDEngine.resolve_pgsd_subject()` before persistence or debounce keys.
- **`username` is additive** (migration 283) for joins to `conversation_history`
  (`conversation_history.user_id` stores username strings).
- Never query PGSD tables by hardware_id while passing a UUID without resolution.

## Flag order (enable in sequence)

| Order | Env var | Unlocks |
|---|---|---|
| 1 | `PGSD_ENABLED` | Master gate — router, triggers, engine |
| 2 | `ENABLE_PGSD_HEARTBEAT` | `PGSDHeartbeatAgent` nightly baselines (primary-only) |
| 3 | `ENABLE_PGSD_ACCESS` | Chat correlation, discernment scores, briefing, crisis regions |
| 4 | `ENABLE_PGSD_FIELD` | Trauma wells, TFIM spectrum, ground state, Hamiltonian track |

Optional: `ENABLE_PGSD_BACKFILL`, `ENABLE_PGSD_HELIX_HINT` (see plan doc).

Never enable `ENABLE_PGSD_FIELD` before `ENABLE_PGSD_ACCESS` in production smoke.

## 1. Turn it on

Apply migrations, then export flags before starting the bridge/backend:

```bash
psql "$DATABASE_URL" -f backend/migrations/191_pgsd_tables.sql
psql "$DATABASE_URL" -f backend/migrations/283_pgsd_access_field.sql
export PGSD_ENABLED=true
export ENABLE_PGSD_HEARTBEAT=true   # optional
export ENABLE_PGSD_ACCESS=true      # Phase B/B2
export ENABLE_PGSD_FIELD=true       # Phase C/D — after ACCESS validated
```

Bridge log `[*] PGSD router initialized (PGSD_ENABLED)` confirms the router is live.

## 2. Message types (all COACH/ADMIN gated)

| Request type | Required fields | Reply type |
|---|---|---|
| `pgsd_compute_snapshot` | `client_id` | `pgsd_snapshot` |
| `pgsd_get_history` | `client_id`, `limit` (default 20) | `pgsd_history` |
| `pgsd_get_trajectory` | `client_id` | `pgsd_trajectory` |
| `pgsd_get_family_entanglement` | `family_id` | `pgsd_family_entanglement` |
| `pgsd_get_zero_time_route` | `client_id`, `origin_snapshot_id`, `destination_snapshot_id` | `pgsd_zero_time_route` |
| `pgsd_get_chat_timeline` | `client_id`, `limit` | `pgsd_chat_timeline` (ACCESS) |
| `pgsd_get_discernment` | `client_id` | `pgsd_discernment` (ACCESS) |
| `pgsd_get_cross_domain_series` | `client_id`, `days` | `pgsd_cross_domain_series` (ACCESS) |
| `pgsd_get_trauma_wells` | `client_id` | `pgsd_trauma_wells` (FIELD) |
| `pgsd_get_ground_state` | `client_id` | `pgsd_ground_state` (FIELD) |

Replies with `ok: false` carry `code` and `error`. The router never raises into the bridge.

Admin UI: `dashboard/pgsd.html` §VIII renders timeline / discernment / cross-domain / wells / ground state.

## 3. Auto-trigger producers (use `pgsd_triggers`, not the router directly)

All producers call **`notify_user(raw_id, source=...)`** or
**`notify_user_async(db_pool, raw_id, source=...)`** — never
`schedule_for_user` directly.

```python
from app.services.pgsd_triggers import notify_user

# After producer success path:
notify_user(user_hardware_id_or_username, source="crystallizer")
```

Behavior:

- Resolves to `hardware_id` when async + `db_pool` available.
- **Quarantine:** skips `audit_*` accounts, six_quotient/battery surfaces, and
  `six_quotient_battery_quarantine.should_block_crystallize` hits.
- Debounced to **at most one snapshot per hour per user** (10-minute floor for
  `live_activation`, `sensitive_bridge_enroll`).
- Returns `True` if scheduled; never raises.

Recommended `source` values (stored in `pgsd_snapshots.trigger_source`):

| Producer | `source` |
|---|---|
| `nate_memory_crystallizer` | `crystallizer` |
| Heartbeat agent | `heartbeat` |
| Sensitive bridge enroll | `sensitive_bridge_enroll` |
| Live activation | `live_activation` |
| Multimodal fusion | `multimodal_fusion` |

## 4. Heartbeat agent

`PGSDHeartbeatAgent` (`backend/app/services/pgsd_heartbeat_agent.py`):

- Requires `PGSD_ENABLED` + `ENABLE_PGSD_HEARTBEAT`.
- Primary-only Redis leader lock (`pgsd:heartbeat:leader`).
- Once per UTC day: schedules snapshots for active clients via `notify_user`.
- Skips quarantined / audit accounts.

Registered in `main.py` when flags are on.

## 5. Phase B/B2/C/D services (ACCESS + FIELD)

| Module | Role | Flag |
|---|---|---|
| `pgsd_correlation.py` | Redacted chat ↔ snapshot rows | ACCESS |
| `pgsd_discernment_scorer.py` | Past/present/future discernment | ACCESS |
| `pgsd_pmb_bridge.py` | Crisis precursors → PMB | ACCESS (regions) |
| `pgsd_briefing.py` | Coach briefing string | ACCESS and/or FIELD |
| `pgsd_trauma_wells.py` | Temporal trauma wells | FIELD |
| `pgsd_field_engine.py` | TFIM spectrum + ground state + H(t) track | FIELD |

After each successful auto-trigger snapshot save, `_bg_compute` fires
**`correlate_recent_chat`** (fire-and-forget) when `ENABLE_PGSD_ACCESS` is on.

## 6. Persistence tables

### Core (191)

| Table | Written by |
|---|---|
| `pgsd_snapshots` | WS handlers + `schedule_for_user` / heartbeat |
| `pgsd_trajectories` | `pgsd_get_zero_time_route` |
| `pgsd_family_entanglement` | `pgsd_get_family_entanglement` |

### ACCESS / FIELD (283)

| Table | Written by |
|---|---|
| `pgsd_crisis_regions` | `pgsd_pmb_bridge.seed_region_from_crisis_event` |
| `pgsd_chat_correlation` | `pgsd_correlation.correlate_recent_chat` |
| `pgsd_discernment_scores` | `PGSDDiscernmentScorer.score_user` |
| `pgsd_cross_domain_agreement` | (future — cross-surface agreement) |
| `pgsd_trauma_wells` | `TraumaWellEngine.refresh_wells` / `collapse_well` |
| `pgsd_forecasts` | (future — forecast + Brier) |
| `pgsd_field_couplings` | (future — pairwise J, h) |
| `pgsd_field_spectrum` | `PGSDFieldEngine.compute_spectrum` |
| `pgsd_ground_states` | `PGSDFieldEngine.compute_spectrum` |
| `pgsd_hamiltonian_track` | `PGSDFieldEngine.track_hamiltonian` |
| `pgsd_legacy_string` | (future — inherited well lineage) |

All INSERT paths are try/except guarded; missing `db_pool` skips persistence only.

## 7. Sentinel exclusions

All five PGSD WS message types are in `_SENTINEL_SKIP` (read-only / telemetry).

## 8. Disable

```bash
unset PGSD_ENABLED
unset ENABLE_PGSD_ACCESS
unset ENABLE_PGSD_FIELD
```

Existing rows remain; producers no-op when master flag is off.
