# PGSD Wiring Guide

The Planetary Galactic Scale Detector (PGSD) ships in three pieces:

| Piece | Path |
|---|---|
| Computation engine | `backend/app/services/pgsd_engine.py` |
| WebSocket router | `backend/app/websocket/pgsd_handlers.py` |
| Schema | `backend/migrations/191_pgsd_tables.sql` |

The bridge integration is **gated behind the `PGSD_ENABLED` env var**
(off by default, per protected-file rule). When enabled, `bridge_server.py`
constructs a `PGSDWebSocketRouter` and dispatches any message whose `type`
starts with `pgsd_` to it.

## 1. Turn it on

Apply the migration, then export the env var before starting the bridge:

```bash
psql "$DATABASE_URL" -f backend/migrations/191_pgsd_tables.sql
export PGSD_ENABLED=true
```

The bridge log line `[*] PGSD router initialized (PGSD_ENABLED)`
confirms the router is live. With the flag off, behavior is identical to
pre-PGSD.

## 2. Message types (all COACH/ADMIN gated)

| Request type | Required fields | Reply type |
|---|---|---|
| `pgsd_compute_snapshot` | `client_id` | `pgsd_snapshot` |
| `pgsd_get_history` | `client_id`, `limit` (default 20) | `pgsd_history` |
| `pgsd_get_trajectory` | `client_id` | `pgsd_trajectory` |
| `pgsd_get_family_entanglement` | `family_id` | `pgsd_family_entanglement` |
| `pgsd_get_zero_time_route` | `client_id`, `origin_snapshot_id`, `destination_snapshot_id` | `pgsd_zero_time_route` |

Any reply with `ok: false` carries `code` (`forbidden` / `error`) and
`error` describing the cause. The router never raises into the bridge.

## 3. Auto-trigger producers

The router exposes a debounced background trigger:

```python
PGSDWebSocketRouter.schedule_for_user(user_id: str, source: str = "auto") -> bool
```

- Fire-and-forget; safe to call from sync or async code.
- Debounced to **at most one snapshot per hour per user**.
- Returns `True` if a task was scheduled, `False` if debounced or disabled.
- Errors inside the background compute are swallowed — auto-triggers
  must NEVER surface to the user-facing flow.

The bridge holds the live router as `bridge_server._pgsd_router`. Producer
code calls it like this **after the producer's own success path completes**:

```python
# After crystallize_from_conversation succeeds
try:
    from app.websocket import bridge_server as _bs
    if _bs._pgsd_router is not None:
        _bs._pgsd_router.schedule_for_user(user_hardware_id, source="crystallizer")
except Exception:
    pass  # PGSD must never break the producer path
```

Recommended `source` values (free-form, surfaced in the snapshot's
`full_pgsd._trigger_source` field for telemetry):

| Producer | Suggested `source` value | Where to add the call |
|---|---|---|
| `nate_memory_crystallizer.crystallize_from_conversation` | `"crystallizer"` | After successful crystal promotion |
| Multi-modal fusion (Phase 4) | `"multimodal_fusion"` | After fusion result is persisted |
| Wisdom absorption | `"wisdom_absorbed"` | After `admin_absorb_wisdom` succeeds |

> **Note on protected files**: `nate_memory_crystallizer.py` is on the
> `.cursorrules` protected list (50-line cap, marker required). Adding
> the `schedule_for_user` call there is a separate small, additive,
> feature-flagged change — not bundled with the bridge edit.

## 4. Persistence

| Table | Written by |
|---|---|
| `pgsd_snapshots` | `pgsd_compute_snapshot` handler + `schedule_for_user` background task |
| `pgsd_trajectories` | `pgsd_get_zero_time_route` handler |
| `pgsd_family_entanglement` | `pgsd_get_family_entanglement` handler (per pair) |

All `INSERT`s are wrapped in try/except and silently skipped when
`db_pool` is unavailable. The handler still returns the computed PGSD
to the caller — only the persistence side-effect is best-effort.

## 5. Sentinel exclusions

All five PGSD message types are added to `_SENTINEL_SKIP` so they don't
trigger admin-action anomaly scoring (they're read-only / telemetry).

## 6. Disable

```bash
unset PGSD_ENABLED  # or set PGSD_ENABLED=false
```

The bridge resumes pre-PGSD behavior. Existing `pgsd_*` rows in the
database remain untouched.
