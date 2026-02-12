---
name: Fix coach approval flow
overview: "Fix the coach approval flow end-to-end: the frontend key mismatch fix was deployed but may be browser-cached, add debug logging, implement REJECT handler, and add a manual approval option on the Users tab as a fallback."
todos:
  - id: backend-approve-logging
    content: Add debug logging to admin_approve_coach handler showing received coach_id vs registry hardware_ids
    status: completed
  - id: backend-reject-handler
    content: Add admin_reject_coach WebSocket handler
    status: completed
  - id: frontend-error-display
    content: Add generic error message display in _handleSocketMessage
    status: completed
  - id: frontend-reject-wire
    content: Wire REJECT button to _rejectCoach() method + handle coach_rejected response
    status: completed
  - id: frontend-users-approve
    content: Add inline APPROVE/REJECT buttons on Users tab for PENDING_VERIFICATION users
    status: completed
  - id: rebuild-deploy-approval
    content: Rebuild Flutter web (skip index.html) + deploy bridge_server.py and web build
    status: completed
isProject: false
---

# Fix Coach Approval Flow

## Current Issues

There are several gaps in the approval pipeline:

### Issue 1: Browser cache may still serve old code

The `coach['id']` -> `coach['hardware_id']` fix was deployed, but the browser may be caching the old `main.dart.js`. The server needs cache-busting headers, or the user needs a hard refresh (Cmd+Shift+R).

### Issue 2: No error feedback when approval fails

When the backend can't find the coach (line 5034-5035 in [bridge_server.py](backend/app/websocket/bridge_server.py)), it sends `{"type": "error", "message": "Coach not found"}`. But the frontend's `_handleSocketMessage` doesn't display generic `error` messages -- they get silently dropped. The admin sees nothing happen.

### Issue 3: REJECT button is a no-op

The REJECT button has `// TODO: Reject coach` (line 9855 in [updated_screens.dart](mobile/lib/updated_screens.dart)). No backend handler exists either.

### Issue 4: No fallback approval path

If the approval card has any issue, there's no way to manually approve a coach from the USERS tab.

---

## Fixes

### A. Backend: Add logging + error response to approve handler

**File**: [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (line ~5017)

Add `print()` logging showing the `coach_id` received and each `hardware_id` compared. This will help debug mismatches in server logs.

### B. Backend: Add `admin_reject_coach` handler

**File**: [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (after approve handler, ~line 5036)

Sets `subscription_status` to `REJECTED`, `certification_status` to `REJECTED`. Returns `{"type": "coach_rejected", "coach_id": ...}`.

### C. Frontend: Show error messages from backend

**File**: [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) (~line 9012 in `_handleSocketMessage`)

Add handler for `data['type'] == 'error'` to show a red SnackBar with the error message, so the admin sees "Coach not found" if approval fails.

### D. Frontend: Wire up REJECT button

**File**: [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) (line ~9855)

Replace the TODO with a call to `_rejectCoach(coach['hardware_id'])`. Add the `_rejectCoach` method. Handle `coach_rejected` response to show snackbar + refresh.

### E. Frontend: Add approve/reject actions on Users tab entries

**File**: [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart) (`_buildUsersTab`, line ~9507)

For users with `subscription_status == PENDING_VERIFICATION`, show small APPROVE/REJECT buttons inline on the user card. This provides a fallback approval path.

### F. Immediate fix for Thomas Signguy

Add a temporary `print` in the backend approve handler that logs what `coach_id` was received and what hardware IDs exist. After deploy, the admin tries approval again (after hard refresh), and we can see the exact mismatch in server logs.

---

## Deployment

- Backend: `scp bridge_server.py` only
- Frontend: Flutter rebuild + rsync (skip index.html)
- User must hard-refresh browser (Cmd+Shift+R) after deploy to bypass cache

