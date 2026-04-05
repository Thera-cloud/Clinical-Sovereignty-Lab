# Backend Tests

## Running Unit/Integration Tests

```bash
cd backend
pytest tests/ -v
```

Only files matching `test_*.py` are collected (configured in `pytest.ini`).

## Test File Conventions

| Pattern | Collected by pytest | Purpose |
|---|---|---|
| `test_*.py` | Yes | Unit and integration tests |
| `load_test*.py` | No | Manual load/stress tests (see below) |
| `_live_*.py` | No | Manual live-environment probes |
| `_ws_probe.py` | No | Manual WebSocket connectivity check |

## Running Load Tests

Load tests are excluded from pytest and must be run manually:

```bash
cd backend/tests
python3 load_test_graduated.py --levels 10,25,50 --per-user --duration 30 --recovery 60
```

See `load-test-performance-baseline.mdc` for the March 21, 2026 baseline methodology and tuned parameters.

### Load test accounts

Tests use pre-created accounts `loadtest_001` through `loadtest_300` with password `LoadTest2026!Nate`.

## Environment

Tests require a `.env` at the project root with database and API credentials. The `Settings` model in `backend/app/config/_settings.py` uses `extra = "ignore"` so undeclared env vars won't cause collection failures.
