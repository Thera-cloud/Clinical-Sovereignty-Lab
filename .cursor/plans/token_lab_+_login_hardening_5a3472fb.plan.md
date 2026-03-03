---
name: Token Lab + Login Hardening
overview: "Three-part hardening: (1) Token Lab safety -- add user existence validation, idempotency, and race condition fixes to prevent tokens from being deleted/moved to the wrong user; (2) Unified password-failure UX -- shake the password field on wrong password, never navigate away, and enforce 5 attempts / 3-minute cooldown that persists across refresh; (3) Ensure coaches and clients are both tracked in Token Lab."
todos:
  - id: token-existence
    content: Add user existence validation to Token Lab /adjust, /reward, /mass-drop endpoints
    status: completed
  - id: token-idempotency
    content: Add idempotency key (batch_id reuse) to prevent duplicate token adjustments
    status: completed
  - id: token-atomic
    content: Replace read-modify-write in bridge use_tokens/add_token_usage with atomic SQL UPDATE
    status: completed
  - id: token-logging
    content: Improve _log_token_transaction reliability (logger.warning, retry)
    status: completed
  - id: token-coach-tracking
    content: Add role breakdown to usage-by-source endpoint, verify coach token tracking
    status: completed
  - id: login-guardian-3min
    content: Change LoginGuardian lockout from 30min to 3min, return remaining_attempts/cooldown_seconds
    status: completed
  - id: bridge-login-metadata
    content: Pass remaining_attempts and cooldown_seconds in login_failed and passphrase responses
    status: completed
  - id: flutter-shake
    content: Add shake animation to password fields on wrong password (main.dart, coach_portal_v2)
    status: completed
  - id: flutter-no-navigate
    content: Remove Navigator.pop in coach portal and Navigator.push in ReConsent on login failure
    status: completed
  - id: flutter-cooldown-persist
    content: Store cooldown expiry in SharedPreferences, show countdown timer, disable login button
    status: completed
  - id: web-shake-cooldown
    content: Add shake animation + localStorage cooldown to dashboard login and admin passphrase
    status: completed
  - id: deploy-verify
    content: Deploy all changes, verify shake/cooldown on every portal, verify Token Lab safety
    status: completed
isProject: false
---

# Token Lab + Login Hardening Plan

## Part 1: Token Lab Safety (Prevent Wrong-User Token Edits)

### Problem

The Token Lab `/adjust` endpoint has three issues:

- No validation that the target user exists (adjusting a non-existent username silently returns `{"before": 0, "after": amount}`)
- No idempotency key (double-click on "Adjust Balance" creates duplicate transactions)
- Race conditions in bridge `use_tokens()` / `add_token_usage()` (concurrent calls read the same balance, both deduct, last write wins)

### Fixes

**A. User existence validation** in [backend/app/routers/token_lab_api.py](backend/app/routers/token_lab_api.py) `adjust_balance()`:

- Before adjusting, query `SELECT username FROM users WHERE username = $1` -- if no row, raise `HTTPException(404, "User not found")`
- Apply same check to `/reward` and `/mass-drop` individual scope

**B. Idempotency key** to prevent duplicate adjustments:

- Add optional `idempotency_key: Optional[str]` to the `TokenAdjust` Pydantic model
- In the frontend (`token_lab.html`), generate a UUID per button click and send it with the POST
- In the backend, before inserting the transaction, check `SELECT 1 FROM token_transactions WHERE batch_id = $1` -- if exists, return the cached result instead of re-adjusting
- Reuse the existing `batch_id` column on `token_transactions` for this purpose

**C. Atomic balance updates** to fix race conditions in [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py):

- In `use_tokens()`: replace the read-modify-write pattern with a single atomic SQL `UPDATE users SET token_balance = GREATEST(token_balance - $1, 0) WHERE username = $2 AND token_balance >= $1 RETURNING token_balance`
- In `add_token_usage()`: same atomic pattern
- Fall back to the current in-memory pattern only if `db_pool` is None

**D. Transaction logging reliability** in `_log_token_transaction()`:

- Replace `print()` with `logger.warning()` on failure
- Add a 1-retry with 500ms delay before giving up

### Files Changed

- `backend/app/routers/token_lab_api.py` -- existence check, idempotency
- `backend/app/websocket/bridge_server.py` -- atomic balance updates, logging reliability
- `dashboard/token_lab.html` -- idempotency key generation on Adjust button

---

## Part 2: Client + Coach Token Tracking in Token Lab

### Current State

Token Lab already returns all roles (CLIENT, COACH, ADMIN) from the `/balances` endpoint and the frontend has a role filter dropdown. However, coaches may not be generating `token_transactions` rows because coach-side AI interactions may not pass the `source` tag.

### Fixes

- Verify that all 4 consumption points in `bridge_server.py` correctly attribute coach usage (they operate on `hoh_id` which could be a coach's own ID)
- In the Token Lab dashboard (`token_lab.html`), ensure the role filter is visible and defaults to "All" so coaches are always shown
- In the Usage Map (`/api/token-lab/usage-by-source`), add a role breakdown so admin can see coach vs client consumption

### Files Changed

- `backend/app/routers/token_lab_api.py` -- add role grouping to usage-by-source
- `dashboard/token_lab.html` -- verify role filter UI

---

## Part 3: Password Failure UX -- Shake, Don't Navigate (All Endpoints)

### Current Behavior


| Entry Point          | On Wrong Password                | Attempt Limit           | Cooldown Persists? |
| -------------------- | -------------------------------- | ----------------------- | ------------------ |
| Flutter Mobile Login | SnackBar error, stays            | LoginGuardian: 5/30min  | Yes (DB)           |
| Coach Portal Login   | SnackBar, **pops dialog**        | LoginGuardian: 5/30min  | Yes (DB)           |
| ReConsent Screen     | **Navigates to LobbyScreen**     | LoginGuardian: 5/30min  | Yes (DB)           |
| Web Admin Login      | Error text, stays                | LoginGuardian: 5/30min  | Yes (DB)           |
| Admin Passphrase     | Shows remaining, lockout overlay | 3/5min (sessionStorage) | Partially          |


### Target Behavior (ALL login screens)

- On wrong password: **shake the password field**, show inline error text, **never navigate away**
- 5 failed attempts triggers a 3-minute cooldown
- Cooldown tracked server-side (LoginGuardian in PostgreSQL) so refresh cannot reset it
- Client-side: store cooldown expiry in `localStorage` (not `sessionStorage`) so closing/reopening the tab still shows the countdown
- Show remaining attempts after the 3rd failure (e.g., "2 attempts remaining")
- Show countdown timer during cooldown (e.g., "Try again in 2:47")

### Changes

**A. Server-side** -- [backend/app/services/login_guardian.py](backend/app/services/login_guardian.py):

- Change `MAX_FAILED_ATTEMPTS` from 5 to 5 (no change)
- Change `LOCKOUT_DURATION_MINUTES` from 30 to 3
- Return `remaining_attempts` and `lockout_seconds` in the response so clients can display them
- Keep escalation logic (repeated lockouts still double the duration)

**B. Bridge server** -- [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py):

- On `login_failed`, include `remaining_attempts` and `cooldown_seconds` in the response payload
- Change fallback in-memory limiter to match: 5 attempts, 3-minute cooldown
- Pass LoginGuardian's `remaining_attempts` through to the client

**C. Flutter Mobile Login** -- [mobile/lib/main.dart](mobile/lib/main.dart):

- Add shake animation on wrong password (use `AnimationController` with `Offset` transform)
- Show remaining attempts text after 3rd failure
- Store cooldown expiry in device `SharedPreferences` (persists across app restart)
- Show countdown timer during cooldown, disable login button
- Never navigate away on login failure

**D. Coach Portal Login** -- [mobile/lib/screens/coach_portal_v2_complete.dart](mobile/lib/screens/coach_portal_v2_complete.dart):

- Remove `Navigator.of(context).pop()` on login failure
- Add shake animation to password field
- Show remaining attempts and cooldown timer (same pattern as mobile login)

**E. ReConsent Screen** -- [mobile/lib/main.dart](mobile/lib/main.dart) (ReConsentScreen):

- Remove `Navigator.pushAndRemoveUntil(... LobbyScreen ...)` on login failure
- Add shake animation, remaining attempts, cooldown timer
- Stay on the re-consent screen and let the user retry

**F. Web Admin Login** -- [dashboard/index.html](dashboard/index.html):

- Add CSS shake animation on password field
- Store cooldown expiry in `localStorage` (persists across refresh)
- Show remaining attempts and countdown timer
- Align admin passphrase to use 5 attempts / 3 minutes (currently 3 attempts / 5 minutes)

**G. Admin Passphrase** -- [dashboard/index.html](dashboard/index.html):

- Change `MAX_PASSPHRASE_ATTEMPTS` from 3 to 5
- Change `LOCKOUT_SECONDS` from 300 to 180
- Switch from `sessionStorage` to `localStorage` for lockout persistence
- Add shake animation to passphrase input

**H. Bridge passphrase handler** -- [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py):

- Change server-side passphrase limit from 5/15min to 5/3min
- Return `remaining_attempts` and `cooldown_seconds` in passphrase response

### Shake Animation Pattern

Flutter (reusable across all screens):

```dart
class _ShakeWidget extends StatelessWidget {
  final AnimationController controller;
  final Widget child;
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, child) {
        final sineValue = sin(controller.value * pi * 4);
        return Transform.translate(
          offset: Offset(sineValue * 10, 0),
          child: child,
        );
      },
      child: child,
    );
  }
}
```

Web (CSS):

```css
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
  20%, 40%, 60%, 80% { transform: translateX(5px); }
}
.shake { animation: shake 0.5s ease-in-out; }
```

### Files Changed

- `backend/app/services/login_guardian.py` -- 3min cooldown, return metadata
- `backend/app/websocket/bridge_server.py` -- pass remaining attempts/cooldown to client
- `mobile/lib/main.dart` -- shake animation, cooldown persistence, ReConsent fix
- `mobile/lib/screens/coach_portal_v2_complete.dart` -- remove pop, add shake
- `dashboard/index.html` -- shake, localStorage cooldown, unified 5/3min limits
- `mobile/pubspec.yaml` -- add `shared_preferences` if not already present

---

## Deployment Sequence

1. Backend changes (login_guardian, bridge, token_lab_api) -- deploy via `scp`, restart `nate_backend` + `nate_bridge`
2. Dashboard changes (token_lab.html, index.html) -- deploy to all 3 server directories
3. Flutter changes -- `flutter build web --release`, deploy to web directories
4. Verify: wrong password shakes on all portals, cooldown persists across refresh, Token Lab adjustments validate user existence

