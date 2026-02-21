---
name: Dependency Guardian Agent
overview: Build an internal background worker ("Dependency Guardian") that runs daily on the production server, audits all dependency versions and API key health across the stack, and pushes a structured report to the admin notification system.
todos:
  - id: guardian-worker
    content: Create `dependency_guardian.py` worker with all 6 checkers (pip, npm, flutter, docker, api-keys, playwright)
    status: completed
  - id: schedule-worker
    content: Wire guardian into `main.py` background task scheduler (daily 3am UTC) + manual trigger endpoint in `admin.py`
    status: completed
  - id: admin-endpoint
    content: Add GET /api/admin/dependency-report endpoint to serve latest report
    status: completed
  - id: dashboard-card
    content: Add Dependency Health card to Sovereign Command dashboard
    status: completed
  - id: deploy-verify
    content: Deploy to production and run first audit to verify
    status: completed
isProject: false
---

# Dependency Guardian Agent

## Architecture

A single Python worker file that runs as a daily cron task inside the `nate_backend` container. It checks every dependency surface, generates a health report, saves it to disk, and pushes critical findings through the existing notification system to Sovereign Command.

```mermaid
flowchart TD
    Cron["Cron Schedule (daily 3am UTC)"] --> Guardian["dependency_guardian.py"]
    Guardian --> PipCheck["Python Packages\n(PyPI JSON API)"]
    Guardian --> NpmCheck["Node Packages\n(npm registry API)"]
    Guardian --> FlutterCheck["Flutter Packages\n(pub.dev API)"]
    Guardian --> DockerCheck["Docker Images\n(Docker Hub API)"]
    Guardian --> ApiKeyCheck["API Key Health\n(test endpoints)"]
    Guardian --> PlaywrightCheck["Playwright/Chromium\n(GitHub releases API)"]
    PipCheck --> Report["JSON Report"]
    NpmCheck --> Report
    FlutterCheck --> Report
    DockerCheck --> Report
    ApiKeyCheck --> Report
    PlaywrightCheck --> Report
    Report --> DiskLog["data/guardian/report_YYYY-MM-DD.json"]
    Report --> Notify["Notification System\n(push to Sovereign Command)"]
```



## What Gets Checked

Each checker is a self-contained async function. All use public APIs (no auth needed except for API key health checks):

- **Python packages** -- Parse `backend/requirements.txt`, query `https://pypi.org/pypi/{pkg}/json` for latest version, compare against installed/pinned. Flag deprecated packages (like the `duckduckgo_search` incident).
- **Node packages** -- Parse `admin/package.json`, query `https://registry.npmjs.org/{pkg}/latest` for latest version, compare.
- **Flutter packages** -- Parse `mobile/pubspec.yaml`, query `https://pub.dev/api/packages/{pkg}` for latest version, compare.
- **Docker base images** -- Check `python:3.11-slim`, `node:22-alpine`, `postgres:15.10-alpine`, `redis:7.4-alpine` against Docker Hub API for newer minor/patch tags.
- **API key health** -- Test each configured key with a minimal API call:
  - Bing Search: `GET /v7.0/search?q=test` (check for 401)
  - Azure OpenAI: Connection test to the endpoint
  - Stripe: `GET /v1/balance` (check for auth error)
  - SendGrid: `GET /v3/user/profile` (check for auth error)
- **Playwright/Chromium** -- Query GitHub releases API for `microsoft/playwright-python`, compare against installed `1.49.x`.

## Severity Levels

Each finding gets a severity:

- **CRITICAL** -- API key expired/invalid (service is broken NOW, like the Bing 401)
- **WARNING** -- Major version behind, deprecated package, security advisory
- **INFO** -- Minor/patch update available

## Files to Create/Modify

### New file: `[backend/app/workers/dependency_guardian.py](backend/app/workers/dependency_guardian.py)`

The main worker. Contains:

- `DependencyGuardian` class with individual checker methods
- `run_audit()` entry point that runs all checks, builds report
- Report saved to `/app/data/guardian/report_YYYY-MM-DD.json`
- Critical findings pushed via existing `notification_system.py`

### Modify: `[backend/app/main.py](backend/app/main.py)`

Add a daily background task using the existing worker scheduling pattern (same as `briefing_worker.py`). Schedule at 3:00 AM UTC daily.

### Modify: `[backend/app/routers/admin.py](backend/app/routers/admin.py)`

Add `GET /api/admin/dependency-report` endpoint that returns the latest guardian report so Sovereign Command can display it.

### Modify: `[admin/src/SovereignCommand.jsx](admin/src/SovereignCommand.jsx)`

Add a "Dependency Health" card/section that shows the latest report -- color-coded by severity (red/yellow/green), with package name, current version, latest version, and status.

## Key Design Decisions

- **Runs inside `nate_backend**` -- has network access, Python environment, and access to config/settings for API keys. No new container needed.
- **No auto-updates** -- report only. All updates require manual action.
- **Rate-limited** -- Each checker uses `asyncio.sleep()` between API calls to avoid hammering registries. Total audit takes ~30-60 seconds.
- **Idempotent** -- Can be triggered manually via admin API endpoint (`POST /api/admin/run-dependency-audit`) in addition to the daily cron.
- **Reports persist** -- JSON reports saved to `data/guardian/` with date-stamped filenames. Last 30 days retained, older auto-cleaned.

