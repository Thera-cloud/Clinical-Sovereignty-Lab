# Follow-up Ticket: Family Sanctuary Token-Resume on Reconnect

**Filed**: 2026-05-09
**Status**: Deferred (non-blocking)
**Estimate**: ~30 minutes
**Owner**: TBD
**Priority**: Low (architecture cleanup; no current user impact after the
4-item fix landed 2026-05-09)

## Context

The 2026-05-09 Family Sanctuary reconnect fix replaced fixed-2s reconnect
with exponential backoff + jitter, wired `_reconnectIfNeeded()` into the
lifecycle, and switched the post-auth path to `sanctuary_join` (so the
backend emits `sanctuary_reconnected` with last-50 history).

That fix kept the existing **full re-authentication on every reconnect**
(`login_request` with username + password). Today, with the new backoff,
the re-auth rate is bounded enough that Sentinel scoring stays well below
the freeze threshold. However, this is a behavioral guarantee, not an
architectural one — if reconnect frequency rises later (e.g., flaky
networks, mobile background-restore, or future feature interactions),
re-auth pressure could re-emerge.

## Proposal

When a valid bridge token is already in storage, the Family Sanctuary
client should resume that session via `bridge_token_resume` (or equivalent
existing handler) instead of re-running `login_request`.

### Why this is clean

1. **Sentinel surface area drops to zero.** Token-resume bypasses the
   credential-scoring path entirely. Even if reconnect frequency spikes,
   no anomaly points accumulate.
2. **One bridge token per device, not one per reconnect.** Avoids
   filling Redis with stale `nate:{env}:auth:*` keys until TTL.
3. **Faster reconnect.** Skips PBKDF2 verification + Sentinel scoring on
   the bridge side.
4. **Backend already handles it.** `add_or_reconnect_member()` in
   `backend/app/websocket/sanctuary_engine.py:355-423` already classifies
   the WS as RECONNECTED/REFRESHED/RETURNED based on member state — it
   does not care whether auth happened via password or token.

## Scope

### Client (`mobile/lib/main.dart` → `_FamilySanctuaryScreenState`)

- `_connectToServer()`: read `widget.profile['token']` (or current
  storage location for the bridge token); if non-empty, send a
  `bridge_token_resume`-style message instead of `login_request`.
- Fall back to `login_request` only when the token is missing/expired
  (e.g., bridge responds with token-rejection event).
- Keep the existing `case 'login_success'` handler — token-resume should
  emit the same success event so the rest of the flow (sanctuary_join /
  sanctuary_get_or_create) is unchanged.

### Bridge (`backend/app/websocket/bridge_server.py`)

- Verify a token-resume handler exists; if not, add a thin handler that
  validates the token against Redis (`nate:{env}:auth:{token}`) and emits
  `login_success` with the same payload shape as the password path.
- Reuse existing token validation — do not duplicate logic.

## Out of scope

- Coach portal or admin portal token resume (separate audit).
- Any change to backend `add_or_reconnect_member()` semantics.
- Changes to other screens with reconnect logic (lobby is correct
  already; `NeuralInterface` has its own pattern).

## Verification (when implemented)

1. Login fresh → confirm `login_request` path.
2. Trigger synthetic disconnect during active sanctuary → confirm next
   reconnect uses token-resume (no Sentinel scoring, no new Redis token
   key created).
3. Force token expiry → confirm graceful fallback to `login_request`.
4. Confirm `sanctuary_reconnected` still fires with last-50 messages.

## Why deferred (not blocking)

The 4-item fix already eliminates the user-visible symptoms (constant
"Reconnecting..." banner, lost message history, thundering herd, Sentinel
freeze risk). Token-resume is a hardening layer, not a regression fix.
Safe to schedule.
