---
name: Fix Registration WebSocket Crash
overview: The "Head of Household" field is NOT triggering any action that could cause the crash. The registration WebSocket closes because the server crashes processing the `register_request` with no error handling, and the error is swallowed silently. Changes to fix this have already been made but need to be deployed.
todos:
  - id: deploy-changes
    content: Build Flutter web and deploy both main.dart (Flutter) and bridge_server.py to the production server
    status: in_progress
  - id: test-registration
    content: Hard refresh and test new client registration -- check console for [REG] debug output and any red SnackBar error messages
    status: completed
  - id: check-registry
    content: If errors persist, SSH into server and inspect user_registry.json for malformed entries (missing 'credentials' key)
    status: cancelled
isProject: false
---

# Fix Registration WebSocket Crash

## Investigation Result: Head of Household Field

The `_parentCtrl` TextField at [mobile/lib/main.dart](mobile/lib/main.dart) line 4950 has **no `onChanged` callback, no listener, and no WebSocket trigger**. Typing in it does nothing except update a local controller. The `_isDependent` toggle only calls `setState()`. The field value is included in the registration payload as `parent_username`, but `register_new_user()` in the server **completely ignores this field** -- it never reads `data.get("parent_username")`.

**Verdict: The Head of Household field is not causing the crash.**

## Root Cause Analysis

The console output tells the story:

```
>>> [REG] SERVER SAYS: {type: connected, status: ready}
>>> [REG] WebSocket closed
```

The server sends `connected`, client sends `register_request`, and the server **crashes during processing**. The crash propagates to the outer exception handler at line ~11366 which only prints a one-line error (no traceback) and closes the connection. The client never receives any response.

### Most Likely Crash Point

In [bridge_server.py](backend/app/websocket/bridge_server.py) line 957, `register_new_user` iterates the registry:

```python
for k, v in registry.items():
    if v["credentials"]["username"] == username:  # KeyError if malformed entry
```

If **any** entry in `user_registry.json` is missing the `credentials` key or has a non-dict value, this crashes with a `KeyError`. The merged registry pulls from two sources (`REGISTRY_FILE` + `BACKEND_REGISTRY_FILE`), and any corruption in either will crash every registration attempt.

Other possible crash points (less likely):

- `MetricsEngine.initialize_metrics()` -- file system permission errors in Docker
- `save_registry()` -- disk write failures
- Directory creation at line 1062 -- `mkdir` permissions

## Changes Already Made (Pending Deployment)

### Server: [bridge_server.py](backend/app/websocket/bridge_server.py)

1. **Try/except around `register_request` handler** -- catches any crash, logs full traceback, and sends `registration_failed` with the error message back to the client instead of silently dying
2. **Defensive registry iteration** -- changed `v["credentials"]["username"]` to `v.get("credentials", {}).get("username")` to prevent `KeyError` on malformed entries
3. **Added `[REG]` debug prints** throughout the handler for visibility

### Client: [main.dart](mobile/lib/main.dart)

1. **Moved `regSocket` to instance variable `_regSocket**` -- prevents garbage collection from closing the connection mid-registration
2. **Deferred payload send** -- registration payload now sent inside the `connected` handler, not immediately after connect (eliminates race condition)
3. **Added `regSent` tracking** -- `onDone` handler reports whether the payload was actually sent before the connection dropped
4. **Added `dispose()` cleanup** -- properly closes socket if user navigates away
5. **Unknown responses show SnackBar** -- any unexpected server response is now visible on screen

## Deployment Steps

```bash
# 1. Build Flutter web
cd ~/Desktop/Clinical-Sovereignty-Lab-2/mobile && flutter build web --release

# 2. Deploy Flutter web assets
rsync -avz build/web/ root@68.183.168.75:/var/www/sovereignsanctuary-web/

# 3. Deploy bridge_server.py
scp ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/bridge_server.py \
    root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/app/websocket/bridge_server.py

# 4. Restart bridge service
ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && docker compose restart bridge"

# 5. Hard refresh browser (Cmd+Shift+R) then test registration
```

## What To Expect After Deployment

- If the server crashes during registration, the actual Python error message will now appear in a **red SnackBar** on screen AND in the browser console as `>>> [REG] SERVER SAYS: {type: registration_failed, message: SERVER_ERROR: ...}`
- If the registry iteration was the crash point, the defensive `.get()` fix should resolve it entirely
- Console will show `>>> [REG] Connection confirmed -- sending register_request NOW` confirming the payload was sent after the connection was confirmed ready

