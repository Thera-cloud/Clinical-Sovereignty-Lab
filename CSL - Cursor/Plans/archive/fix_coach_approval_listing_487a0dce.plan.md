---
name: Fix coach approval listing
overview: Add the missing `admin_get_pending_coaches` WebSocket handler so pending coaches appear in the Admin Command approval tab.
todos:
  - id: add-pending-coaches-handler
    content: Add admin_get_pending_coaches WebSocket handler in bridge_server.py that scans registry for COACH profiles with PENDING_VERIFICATION status
    status: completed
  - id: deploy-bridge
    content: Deploy updated bridge_server.py to server and restart containers
    status: completed
isProject: false
---

# Fix Coach Approval Listing

## Problem

The admin dashboard sends `admin_get_pending_coaches` via WebSocket, but the backend has **no handler** for this message type. The `admin_approve_coach` handler exists (line ~4990 in bridge_server.py), but there's no corresponding handler to fetch the list of pending coaches. This is why the APPROVALS tab shows "No pending coach approvals."

## Fix

Add a handler for `admin_get_pending_coaches` in [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py), right before the existing `admin_approve_coach` handler (line ~4988).

The handler will:

1. Verify the requester is an ADMIN
2. Scan the registry for profiles where `role == "COACH"` and `subscription_status == "PENDING_VERIFICATION"`
3. Return them as `{"type": "pending_coaches", "coaches": [...]}` -- matching what the Flutter admin dashboard expects at line ~9031 of [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart)

Each coach entry will include: `hardware_id`, `name`, `email`, `joined_date`, `specializations`, `selected_dojos`, `dojo_monthly_price`, `w9_submitted`, and `certification_status`.

## Deployment

After the change, only `bridge_server.py` needs to be redeployed:

```
scp backend/app/websocket/bridge_server.py root@68.183.168.75:/opt/clinical-sovereignty-lab/backend/app/websocket/
ssh root@68.183.168.75 "cd /opt/clinical-sovereignty-lab && docker compose -f docker-compose.prod.yml restart backend bridge 2>/dev/null || docker compose -f docker-compose.prod.yml restart nate_backend nate_bridge"
```

No Flutter rebuild needed -- the admin dashboard already sends the right message and handles the response.