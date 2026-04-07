---
name: Stripe Payment UX Rebuild
overview: "Rebuild the payment UX for Stripe-only across all surfaces: unify return URLs, add in-app payment confirmation, wire webhook-to-WebSocket push, add payment history, fix dead code/navigation, and harden webhook processing. Phased to prioritize cleanup before new features."
todos:
  - id: a1-unify-urls
    content: Unify all Stripe success/cancel URLs to payment-success / payment-cancel across 4 files
    status: completed
  - id: a3-dead-code
    content: Delete _processUpgradeViaIAP (settings_screen.dart) and _canUseRealtimeVoice (updated_screens.dart)
    status: completed
  - id: a4-fix-nav
    content: Fix broken pushNamed('/settings') in vault_attachment_button.dart
    status: completed
  - id: a2-static-pages
    content: Create payment-success.html and payment-cancel.html + nginx config
    status: completed
  - id: b1-lifecycle
    content: Add AppLifecycleState.resumed profile refresh with _pendingCheckout flag
    status: completed
  - id: b2-confirm-screen
    content: Create PaymentConfirmationScreen with polling, 10s/30s timeout states
    status: completed
  - id: b3-ws-push
    content: "Add Redis nate:payment_confirmed channel: backend publish + bridge subscribe + Flutter handler"
    status: completed
  - id: c1-cancel-sub
    content: Add Manage Subscription button in Settings opening Stripe Billing Portal
    status: completed
  - id: c2-payment-history
    content: Add Payment History section in Settings using GET /api/billing/invoices/{user_id}
    status: completed
  - id: c3-webhook-harden
    content: Fix voice webhook idempotency check (session ID vs payment intent mismatch) + verify Stripe Dashboard endpoint config
    status: completed
isProject: false
---

# Stripe Payment UX Rebuild Plan (Updated)

## Phase Order

A1 (unify URLs) -> A3 (dead code) -> A4 (fix nav) -> A2 (static pages) -> B1 (lifecycle refresh) -> B2 (in-app confirmation screen) -> B3 (webhook -> WebSocket push) -> C1 (cancel subscription) -> C2 (payment history) -> C3 (webhook hardening) -> C4 (promo code audit)

---

## Phase A: Fix Critical Gaps

### A1 — Unify All Stripe Success/Cancel URLs

Currently 6 different URL patterns exist across 4 files. Consolidate to one pair:

- **Success:** `https://app.sovereignsanctuary.net/payment-success?session_id={CHECKOUT_SESSION_ID}`
- **Cancel:** `https://app.sovereignsanctuary.net/payment-cancel`

Files to edit (4):

- [mobile/lib/services/payment_service.dart](mobile/lib/services/payment_service.dart) — lines 92-93: change `billing/success` and `billing/cancel`
- [mobile/lib/screens/billing_screens.dart](mobile/lib/screens/billing_screens.dart) — lines 356-357, 1501-1504, 2806-2807: change `payment-success`/`payment-cancel` (already correct) and `coaching/success`/`coaching/cancel` (needs change)
- [mobile/lib/screens/settings_screen.dart](mobile/lib/screens/settings_screen.dart) — lines 727-728: already uses `payment-success`/`payment-cancel`, keep as-is
- [backend/app/routers/billing.py](backend/app/routers/billing.py) — lines 1624-1625 (family member defaults), 2125-2126 (payment method setup), 2186-2187 (DOJO): update defaults to match

Backend `stripe_integration.py` appends `?session_id={CHECKOUT_SESSION_ID}` to success URLs automatically (line 612), so Flutter should NOT include the template variable.

### A3 — Delete Dead Code

- [mobile/lib/screens/settings_screen.dart](mobile/lib/screens/settings_screen.dart) lines 760-771: delete `_processUpgradeViaIAP` (defined, never called)
- [mobile/lib/updated_screens.dart](mobile/lib/updated_screens.dart): delete `_canUseRealtimeVoice()` (defined, never called)

### A4 — Fix Broken Navigation

- [mobile/lib/widgets/vault_attachment_button.dart](mobile/lib/widgets/vault_attachment_button.dart) line 103: `Navigator.pushNamed(context, '/settings')` — the `/settings` route is not registered in `main.dart`. Replace with the actual navigation pattern used elsewhere in the app (likely pushing `SettingsScreen` directly with required constructor args, or show a dialog instructing the user to go to Settings)

### A2 — Static Return Pages

Create two minimal HTML pages deployed to `/var/www/sovereignsanctuary-web/`:

- `payment-success.html` — "Payment confirmed! Returning to your app..." with auto-redirect logic (`window.close()` or `location.href = 'sovereignsanctuary://payment-success'`)
- `payment-cancel.html` — "Payment cancelled. You can close this tab."

These are the **fallback** for users who don't return to the app automatically. The primary UX is the in-app confirmation (Phase B2).

Nginx config: add `location = /payment-success` and `location = /payment-cancel` blocks that serve these files instead of the Flutter SPA `index.html`.

---

## Phase B: Post-Checkout Return Handling

### B1 — AppLifecycleState Profile Refresh

When the app returns from background (user was in Stripe checkout browser), re-fetch the user profile to detect tier/token changes.

Add to the main chat screen or app shell (wherever `WidgetsBindingObserver` is most appropriate):

```dart
@override
void didChangeAppLifecycleState(AppLifecycleState state) {
  if (state == AppLifecycleState.resumed && _pendingCheckout) {
    _refreshProfileAfterCheckout();
  }
}
```

`_pendingCheckout` is set `true` before `launchUrl()` and cleared after refresh. The refresh calls `GET /api/billing/subscription/{user_id}` and compares tier/tokens to pre-checkout snapshot.

### B2 — In-App PaymentConfirmationScreen (NEW)

New file: `mobile/lib/screens/payment_confirmation_screen.dart` (max 40 lines)

Shown when `_refreshProfileAfterCheckout()` detects a change, OR navigated to from `AppLifecycleState.resumed` when `_pendingCheckout` is true.

Logic:
1. On entry, snapshot the user's current tier and token balance
2. Poll `GET /api/billing/subscription/{user_id}` every 2 seconds
3. **If tier or token balance changed within 10s:** show success icon + "Payment confirmed! You now have [plan name / N tokens]" + "Continue" button
4. **If no change after 10s:** show "Still processing... This usually takes a moment" + manual "Check Again" button
5. **If no change after 30s:** show "Something may have gone wrong. Check your email for confirmation or contact support." + "Return to App" button

Design tokens: success icon uses `_D.green`, text uses `_D.textPrimary`, background `_D.bgChamber`.

### B3 — Webhook -> WebSocket Push Notification (NEW)

**Architecture constraint:** The bridge and backend run in separate Docker containers. The bridge owns all WebSocket connections (`connected_clients`, `connected_coaches`). The backend cannot push directly.

**Existing mechanism:** The backend publishes to Redis channel `nate:user_reload` (in `stripe_integration.py` line 467-475 via `_notify_bridge_reload`). The bridge subscribes and reloads the user from PostgreSQL.

**Implementation (2 touch points, ~15 lines total):**

1. **Backend** ([backend/app/services/stripe_integration.py](backend/app/services/stripe_integration.py)): After `_handle_checkout_completed` processes a payment, publish a Redis message on a new channel `nate:payment_confirmed`:

```python
await r.publish("nate:payment_confirmed", json.dumps({
    "username": username,
    "type": "plan_upgrade" or "token_pack",
    "plan": tier_name,
    "tokens_added": amount
}))
```

2. **Bridge** ([backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py)): In the existing `_cache_sync_blocking_listener`, subscribe to `nate:payment_confirmed`. On message, look up `connected_clients.get(hw_id)` or `connected_coaches.get(hw_id)` and `await ws.send(json.dumps({"type": "payment_confirmed", ...}))`.

**Note:** This touches `bridge_server.py` (protected file, 50-line limit). The bridge-side listener addition is ~8 lines (subscribe + lookup + send). This is additive only — no existing code modified.

3. **Flutter**: In the WebSocket message handler, listen for `type: "payment_confirmed"` and show a `SnackBar`:

```dart
case 'payment_confirmed':
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text('Payment confirmed! ${data['plan'] ?? 'Tokens added'}')),
  );
  _refreshProfile(); // reload user data
  break;
```

---

## Phase C: Additional Features

### C1 — Cancel Subscription Flow

Add to Settings screen: "Cancel Plan" button that opens the Stripe Billing Portal.

Backend endpoint already exists: `POST /api/billing/billing-portal` (in `stripe_integration.py` `create_billing_portal_session`). The portal handles cancellation, plan changes, and payment method updates.

Flutter: add a "Manage Subscription" button in the billing section of [mobile/lib/screens/settings_screen.dart](mobile/lib/screens/settings_screen.dart) that calls the portal endpoint and opens the returned URL.

### C2 — Payment History in Settings (NEW)

Backend endpoint exists: `GET /api/billing/invoices/{user_id}` ([backend/app/routers/billing.py](backend/app/routers/billing.py) line 703).

Add ~15 lines to [mobile/lib/screens/settings_screen.dart](mobile/lib/screens/settings_screen.dart):

- "Payment History" section header
- `FutureBuilder` calling `GET /api/billing/invoices/{userId}?limit=10`
- `ListView` showing each invoice: date, amount formatted as currency, status badge (paid/pending/failed)
- "View in Browser" link opening Stripe-hosted invoice URL if available

### C3 — Webhook Double-Processing Hardening (NEW)

**Risk assessment:** The main webhook (`/api/billing/webhook`) and voice webhook (`/api/voice/webhook/stripe`) both handle `checkout.session.completed`. The main handler already includes `_handle_voice_block` for `metadata.type == voice_block`. If both Stripe endpoints are registered for the same events, voice purchases could be credited twice.

**Additionally:** The voice webhook's idempotency check queries `voice_transactions.stripe_payment_id` by session ID, but stores payment intent ID — these are different values, making the dedup check unreliable.

**Fix (3 lines per handler):**

1. **Voice webhook** ([backend/app/routers/voice_billing_api.py](backend/app/routers/voice_billing_api.py)): Already filters `metadata.type == voice_block` (line 377-379). Fix the idempotency check to query by payment intent ID instead of session ID, matching what `credit_seconds` stores.

2. **Main webhook** ([backend/app/services/stripe_integration.py](backend/app/services/stripe_integration.py)): In `_handle_checkout_completed`, the voice block branch already exists and uses `webhook_events` / `webhook_events_v2` for dedup. No change needed unless both endpoints are registered in Stripe Dashboard — **verify in Stripe Dashboard** which endpoint URLs are active. If both are active for `checkout.session.completed`, disable voice events on the voice endpoint (preferred) or add a cross-handler dedup using `webhook_events_v2`.

### C4 — Promo Code Audit (ALREADY EXISTS)

Research shows promo code UI **already exists** in [mobile/lib/screens/billing_screens.dart](mobile/lib/screens/billing_screens.dart):

- `_promoCtrl` TextEditingController (line 74)
- "Have a promo code?" expandable field (line 134)
- Verification via `GET /api/billing/verify-promo/{code}?tier={plan}` (line 201)
- Passes `promo_code` in checkout request body (line 360)

**No work needed.** Remove from task list.

---

## Family Billing Model (Documentation Note)

Research confirms the billing model:

- **Head of household (HoH) pays for all family members** via their Stripe customer/subscription
- **Spouse:** always free
- **First child under 12:** free
- **Paid slots** (tiered): $75 / $60 / $45 / $30 per month for 1st / 2nd / 3rd / 4th+ paid add-ons
- **Requires Sovereign Circle (TOP_TIER)** for family features
- **Family member subscription items** are added to the HoH's existing Stripe subscription, not separate customers

The Flutter UI uses a WebSocket `family_invite` flow, not the `checkout_family_member` REST endpoint. The checkout endpoint exists as a fallback/alternative path but is currently unused by the mobile app.

**No code changes needed** — the model is clear and consistent. The rebuild plan does not need to alter family billing routing. The only action item is ensuring the unified success/cancel URLs (Phase A1) cover the family member checkout defaults in `billing.py` lines 1624-1625.

---

## Files Changed (Summary)

| Phase | File | Lines Changed (est.) |
|---|---|---|
| A1 | `payment_service.dart` | 2 |
| A1 | `billing_screens.dart` | 4 |
| A1 | `billing.py` | 6 |
| A3 | `settings_screen.dart` | -12 (delete) |
| A3 | `updated_screens.dart` | -8 (delete) |
| A4 | `vault_attachment_button.dart` | 3 |
| A2 | New: `payment-success.html` | ~20 |
| A2 | New: `payment-cancel.html` | ~15 |
| B1 | App shell / chat screen | ~15 |
| B2 | New: `payment_confirmation_screen.dart` | ~40 |
| B3 | `stripe_integration.py` | ~5 |
| B3 | `bridge_server.py` | ~8 (additive) |
| B3 | Flutter WS handler | ~6 |
| C1 | `settings_screen.dart` | ~10 |
| C2 | `settings_screen.dart` | ~15 |
| C3 | `voice_billing_api.py` | ~3 |

**Total: ~160 lines across 11 files + 2 new HTML files + 1 new Dart file**
