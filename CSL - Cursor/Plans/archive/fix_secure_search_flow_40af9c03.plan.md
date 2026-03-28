---
name: Fix Secure Search Flow
overview: "Fix two bugs preventing Secure Internet Search from working: (1) a critical registry iteration bug that prevents admin notifications from ever being delivered, and (2) the pyotp installation issue on the server."
todos:
  - id: fix-registry-iteration
    content: Fix registry iteration bug in admin notification at lines 9220-9232 and 9261-9273 of bridge_server.py - change 'for u in registry' to 'for rk, rv in registry.items()' with proper profile access
    status: completed
  - id: install-pyotp
    content: Install pyotp in running Docker container and optionally rebuild image for permanence
    status: completed
  - id: deploy-and-test-search
    content: Deploy fixed bridge_server.py, restart containers, test full search flow end-to-end
    status: completed
isProject: false
---

# Fix Secure Internet Search Approval Flow

## Bug 1: Admin Never Receives Search Requests (CRITICAL)

The admin notification code in [bridge_server.py](backend/app/websocket/bridge_server.py) iterates over the registry **incorrectly**. This means the admin portal **never** receives real-time `search_pending_admin` messages.

**The bug** (lines 9220-9223 and 9261-9264):

```python
registry = load_registry()
for u in registry:                    # <-- iterates over dict KEYS (strings)
    if u.get("role") == "ADMIN":      # <-- strings don't have .get() -> AttributeError
        admin_uid = u.get("hardware_id")
```

The registry is a `dict` with structure `{ key: { "profile": { "role": ..., "hardware_id": ... } } }`. Iterating `for u in registry` yields string keys, and calling `.get("role")` on a string throws `AttributeError`. This silently crashes the notification because the error propagates up to the main handler's try/except.

**Correct pattern** used everywhere else in the file (e.g., lines 4828, 4972, 5011, 5039):

```python
for rk, rv in registry.items():
    p = rv.get("profile", {})
    if p.get("role") == "ADMIN":
        admin_uid = p.get("hardware_id")
```

**Fix**: Update both admin notification loops (after coach_approve at line 9220 and after 2fa_verify at line 9261) to use the correct `registry.items()` pattern.

## Bug 2: pyotp Not Installed in Docker Container

The `pyotp` package is in [requirements.txt](backend/requirements.txt) (line 53) but the Docker container was built before it was added. The deploy script's `pip install` doesn't persist across container restarts.

**Fix**: Install pyotp in the running container, then rebuild the Docker image for permanence:

- Immediate: `docker exec ... pip install pyotp==2.9.0 qrcode==7.4.2`
- Permanent: Rebuild container image so pyotp is baked in

## Flow Verification

The complete Secure Internet Search flow, once these bugs are fixed:

```mermaid
sequenceDiagram
    participant Coach as Coach DOJO
    participant Backend as bridge_server.py
    participant Admin as command.html

    Coach->>Backend: search_request
    Backend->>Coach: search_query_proposed
    Coach->>Backend: search_coach_approve
    Note over Backend: 2FA check
    alt 2FA enabled
        Backend->>Coach: search_2fa_required
        Coach->>Backend: search_2fa_verify
    end
    Backend->>Coach: search_awaiting_admin
    Backend->>Admin: search_pending_admin (FIX HERE)
    Note over Admin: Shows in Pending Search Approvals card
    Admin->>Backend: search_admin_decision
    alt Approved
        Backend->>Backend: execute_search via Bing API
        Backend->>Coach: search_results_review
        Coach->>Backend: search_results_confirmed
        Backend->>Backend: Send to Nate via cortex
        Backend->>Coach: search_complete
    else Denied
        Backend->>Coach: search_denied
    end
```



The admin portal in [command.html](dashboard/command.html) already has the full UI (lines 1375-1812):

- "Pending Search Approvals" card with badge counter
- `renderPendingSearches()` renders approve/deny buttons
- `approveSearch()` / `denySearch()` send `search_admin_decision`
- Loads pending requests on connect via `admin_get_pending_searches`

All admin-side code is correct. The **only** issue is the backend never delivers the `search_pending_admin` notification due to the registry iteration bug.