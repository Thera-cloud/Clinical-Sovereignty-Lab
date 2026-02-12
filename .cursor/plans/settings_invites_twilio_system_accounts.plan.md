---
name: Settings Invites — Twilio & System Accounts
overview: Ensure all settings features work for coach and client, fix Invite Family Member, add coach-to-client invite for tier signup. Uses Twilio (SMS), SendGrid (email), and WebSocket bridge.
todos:
  - id: fix-family-invite-client
    content: Fix Invite Family Member — resilient WebSocket + wait for token before share
    status: completed
  - id: wire-family-invite-backend-sms-email
    content: Wire backend to send family invite via Twilio (phone) or SendGrid (email) when token generated
    status: completed
  - id: coach-invite-client-feature
    content: Add Coach Settings "Invite Client" — form + backend handler + Twilio/SendGrid delivery
    status: completed
  - id: settings-websocket-resilience
    content: Wrap _sendWs in try-catch across client and coach settings to handle closed sockets
    status: completed
isProject: false
---

# Settings Invites — Twilio & System Accounts

## Current System Accounts

| Service | Purpose | Location |
|---------|---------|----------|
| **Twilio** | SMS (password reset, invites) | `notification_system.py` — send_sms, send_password_reset_sms |
| **SendGrid** | Email (password reset, notifications) | `notification_system.py` — _send_email |
| **Stripe** | Payments | stripe_billing, stripe_integration |
| **Zoom** | Live sessions | zoom_client |

## 1. Invite Family Member (Client — Sovereign Circle)

**Current issues:**
- `_sendWs` throws "Cannot add event after closing" when parent socket is closed
- Client never waits for `family_invite_token_generated` — share message has no token
- Backend generates token but does not send SMS/email to invitee

**Fix:**
1. Use dedicated short-lived WebSocket for invite flow (avoids closed-socket crash)
2. Wait for `family_invite_token_generated` before including token in share message
3. Optional: backend sends SMS (Twilio) or email (SendGrid) to invitee with link + token

## 2. Coach Invite Client to Sign Up

**New feature:**
- Coach Settings → "Invite Client" (name, email or phone, suggested tier: STANDARD / COACH_ONLY / SOVEREIGN_CIRCLE)
- Backend: `coach_invite_client` handler
  - Create invite token tied to coach_id, tier
  - Send via Twilio (phone) or SendGrid (email)
  - Store in registry for accept flow
- Invitee receives link; when they register, they’re pre-linked to coach and tier

## 3. Settings WebSocket Resilience

- Wrap `_sendWs` in try-catch; on "Cannot add event after closing", show snackbar
- Consider: Settings could open a fresh socket when passed socket is closed (requires auth context)

## Files to Modify

- `mobile/lib/screens/settings_screen.dart` — Invite Family Member flow, _sendWs try-catch
- `backend/app/websocket/bridge_server.py` — wire notification_system for family invite; add coach_invite_client
- `backend/app/websocket/notification_system.py` — add send_family_invitation (email + SMS)
