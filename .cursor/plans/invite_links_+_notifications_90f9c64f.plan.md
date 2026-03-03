---
name: Invite Links + Notifications
overview: "Fix the \"Invite a Friend\" link, add SMS/email options to Family Invite in billing, and add four missing notification triggers: new client signup email to support, new coach registration email to admin, coach approval SMS+email to the coach, and proper download/signup links in all invite flows."
todos:
  - id: fix-invite-link
    content: Change Invite a Friend URL in settings_screen.dart from sovereignsanctuary.net/download to app.sovereignsanctuary.net
    status: pending
  - id: billing-invite-sms-email
    content: Add SMS/email toggle to Family Invite dialog in billing_screens.dart, send via chosen channel with proper download link
    status: pending
  - id: client-signup-email
    content: Add email to support@sovereignsanctuary.net on new CLIENT registration in bridge_server.py
    status: pending
  - id: coach-registration-email
    content: Add email to admin_nevedalnj@sovereignsanctuary.net on new COACH registration in bridge_server.py
    status: pending
  - id: coach-approval-notify
    content: Add SMS + email to coach on admin approval in bridge_server.py (and admin.py REST endpoint if applicable)
    status: pending
  - id: deploy-verify
    content: Deploy all changes, verify notifications fire correctly
    status: pending
isProject: false
---

# Invite Links + Notification Triggers

## 1. Fix "Invite a Friend" Link (Settings Screen)

### Current

In [mobile/lib/screens/settings_screen.dart](mobile/lib/screens/settings_screen.dart) line 774, the link is:

```
https://sovereignsanctuary.net/download
```

This domain does not host the app. The correct gateway is `https://app.sovereignsanctuary.net`.

### Change

- Update the URL in `_inviteFriend()` (line 774) to `https://app.sovereignsanctuary.net`
- Update the copyable link box below the button (around line 1390) to match
- Keep the share message text as-is but with the corrected URL

### File

- `mobile/lib/screens/settings_screen.dart` -- 2 string replacements

---

## 2. Family Invite in Billing -- Add SMS / Email Option

### Current

The "Invite Family Member" button in [mobile/lib/screens/billing_screens.dart](mobile/lib/screens/billing_screens.dart) line 758 opens a dialog with Name, Email, and Relationship fields. It sends a `family_invite` WebSocket message. There is no explicit choice between SMS and email, and no proper download link is sent.

### Change

- Add a **contact method toggle** (SMS or Email) to the `_showInviteDialog` dialog
- If SMS is selected, show a phone number field instead of email
- The WebSocket message `family_invite` already accepts these fields; the backend handler in `bridge_server.py` already calls `notification_system` for sending
- Ensure the invite message body includes: the inviter's name, a personal message, and the download/signup link `https://app.sovereignsanctuary.net/family-invite?code=TOKEN`
- If no token is generated (backend issue), fall back to `https://app.sovereignsanctuary.net` as the download link

### Backend

In [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py), the `family_invite` handler needs to:

- Accept either `email` or `phone` (or both)
- Call `notification_system._send_email()` for email invites with a formatted HTML message
- Call `notification_system.send_sms()` for SMS invites with a concise text message
- Both messages include the invite link and download instructions

### Files

- `mobile/lib/screens/billing_screens.dart` -- add SMS/email toggle to invite dialog
- `backend/app/websocket/bridge_server.py` -- ensure family_invite handler sends via the chosen method with proper link

---

## 3. New Client Signup -- Email to [support@sovereignsanctuary.net](mailto:support@sovereignsanctuary.net)

### Current

In [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py), `register_new_user()` (line 2230) creates the account and returns success, but sends no notification to anyone.

### Change

After a successful CLIENT registration (after `save_registry_async` confirms PostgreSQL write), fire an async notification:

```python
if role == "CLIENT":
    asyncio.create_task(notification_system._send_email(
        to_email="support@sovereignsanctuary.net",
        subject=f"New Client Signup: {name or username}",
        content=f"A new client has registered.\n\nUsername: {username}\nName: {name}\nEmail: {email}\nRegistered: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        notification_type="admin_alert"
    ))
```

This is fire-and-forget -- registration success is not gated on the email sending.

### File

- `backend/app/websocket/bridge_server.py` -- add ~5 lines after successful CLIENT registration

---

## 4. New Coach Registration -- Email to [admin_nevedalnj@sovereignsanctuary.net](mailto:admin_nevedalnj@sovereignsanctuary.net)

### Current

When a COACH registers, `subscription_status` is set to `"PENDING_VERIFICATION"` and `certification_status` to `"PENDING"`. No notification is sent to the admin.

### Change

After a successful COACH registration (after `save_registry_async` confirms PostgreSQL write), fire an async notification:

```python
if role == "COACH":
    asyncio.create_task(notification_system._send_email(
        to_email="admin_nevedalnj@sovereignsanctuary.net",
        subject=f"New Coach Awaiting Approval: {name or username}",
        content=f"A new coach has registered and requires your approval.\n\nUsername: {username}\nName: {name}\nEmail: {email}\nSpecializations: {', '.join(data.get('specializations', []))}\n\nLog in to Sovereign Command to approve: https://command.sovereignsanctuary.net",
        notification_type="admin_alert"
    ))
```

### File

- `backend/app/websocket/bridge_server.py` -- add ~8 lines after successful COACH registration

---

## 5. Coach Approval -- SMS + Email to the Coach

### Current

In [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py), `admin_approve_coach` handler (line 9993) sets `subscription_status = "ACTIVE"` and `certification_status = "APPROVED"` but sends no notification to the coach.

### Change

After successful approval, send both SMS and email to the coach:

```python
coach_email = v["profile"].get("email") or v.get("credentials", {}).get("email")
coach_phone = v["profile"].get("phone")
coach_name = v["profile"].get("name", username)

if coach_email:
    asyncio.create_task(notification_system._send_email(
        to_email=coach_email,
        subject="Your Coach Account Has Been Approved!",
        content=f"Congratulations {coach_name}!\n\nYour coach account on Sovereign Sanctuary has been verified and approved. You can now sign in to the Coach Portal.\n\nSign in at: https://coach.sovereignsanctuary.net\n\nWelcome to the team.",
        notification_type="coach_approval"
    ))

if coach_phone:
    asyncio.create_task(notification_system.send_sms(
        to_phone=coach_phone,
        body=f"Sovereign Sanctuary: Your coach account has been approved! Sign in at https://coach.sovereignsanctuary.net"
    ))
```

### Sovereign Command UI

Also check if there is a REST endpoint for coach approval in [backend/app/routers/admin.py](backend/app/routers/admin.py) (line 892) -- if so, add the same notification logic there to cover both WebSocket and REST approval paths.

### File

- `backend/app/websocket/bridge_server.py` -- add ~15 lines after successful coach approval
- `backend/app/routers/admin.py` -- add same notification to REST approval endpoint (if used)

---

## Summary of All Changes


| Feature                      | File(s)                                    | What Changes                                                                    |
| ---------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------- |
| Invite a Friend link         | `settings_screen.dart`                     | URL from `sovereignsanctuary.net/download` to `app.sovereignsanctuary.net`      |
| Family Invite SMS/email      | `billing_screens.dart`, `bridge_server.py` | Add contact method toggle, send via chosen channel with proper link             |
| New client signup email      | `bridge_server.py`                         | Send email to `support@sovereignsanctuary.net` after CLIENT registration        |
| New coach registration email | `bridge_server.py`                         | Send email to `admin_nevedalnj@sovereignsanctuary.net` after COACH registration |
| Coach approval SMS+email     | `bridge_server.py`, possibly `admin.py`    | Send SMS + email to coach after admin approval                                  |


## Deployment

1. Deploy `bridge_server.py` changes -- `scp` to server, restart `nate_bridge`
2. Deploy `admin.py` if changed -- `scp` to server, restart `nate_backend`
3. Flutter changes require `flutter build web --release` then rsync (no `--delete`) to web directories
4. No database migration needed -- all changes are code-level notification triggers using existing `notification_system` infrastructure

