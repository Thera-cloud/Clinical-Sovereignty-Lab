> **HISTORICAL — READ ONLY as of 2026-04-30.** New open items go 
> in `docs/OPEN_TODOS.md`, not here. This file is preserved for 
> historical reference and pending reconciliation. See 
> docs/OPEN_TODOS.md for active work.

# Family Sanctuary + Family Tab + Vault + IAP Audit

Audit scope: save conversation, exit/complete sanctuary, four charges ($5, $3, $20, $20), client Settings → Subscriptions → Family tab billing, Browse Vault (saved conversation + final summary), Stripe verification, and in-app purchase testing. Use **client1** and **client1b** for vault/summary checks.

---

## 1. Family Sanctuary flows (save, exit, complete)

### 1.1 Save conversation

| Location | Behavior |
|----------|----------|
| **Flutter** `main.dart` | `_saveConversation()` builds text from `_messages`, copies to clipboard, sends `export_conversation`, and POSTs to `POST /api/v1/vault/save-conversation` with `title: "Sanctuary Session — {date}"`, `source: "sanctuary"`. |
| **Backend** `vault_api.py` | `save_conversation` inserts into `vault_items` (member_id, content_type=source, display_name, extracted_text_preview, size_bytes). |
| **Vault browse** | `VaultBrowserScreen` loads items via `GET /api/v1/vault/...` (folders + items). Saved conversations appear as vault items with `content_type: sanctuary`. |

**Check:** From Family Sanctuary, use “Copy & Save” (or equivalent); then Settings → Browse Vault and confirm a “Sanctuary Session — {date}” item appears.

### 1.2 Exit sanctuary

| Step | Message / API | Backend |
|------|----------------|---------|
| User taps exit | `sanctuary_exit` (WS) | Bridge sends `sanctuary_exit_checkin` with checkin message. |
| User confirms | `sanctuary_exit_confirm` (reason, inform_family) | Bridge marks member exited, broadcasts `sanctuary_exited`; if last member exits, may call `sanctuary_engine.complete_session(sanctuary_id)`. |

**Check:** Start sanctuary as client1, exit with reason; confirm other member (client1b) sees “exited” and session can end or continue.

### 1.3 Complete sanctuary

| Step | Message / API | Backend |
|------|----------------|---------|
| Creator/HoH taps complete | `sanctuary_complete` (WS) | Bridge: HoH/creator check → broadcast `sanctuary_generating_summary` → build entry + messages + coaching context → call Azure for JSON summary → write to `data/sanctuary_history/{sanctuary_id}.json` → send **sanctuary_summary** per member (personalized insights) → update_client_story per member → remove from active_sanctuaries. |
| Flutter | Handles `sanctuary_summary`: sets `_sessionSummary`, `_sessionStats`, shows overlay. | “Close & Exit” dismisses overlay. **New:** “Save to Vault” calls `_saveSessionSummaryToVault()` → POST `save-conversation` with summary text, `source: sanctuary_summary`. |

**Check:** Complete a sanctuary as HoH; confirm session summary overlay; tap “Save to Vault”; then in Settings → Browse Vault confirm “Family Sanctuary Summary — {date}” appears.

---

## 2. Four Family Sanctuary charges

Canonical amounts (single source of truth: `sanctuary_engine.py`):

| Charge | Constant | Amount | When |
|--------|----------|--------|------|
| Initial session | `SANCTUARY_CHARGE_BASE_FEE` | $20.00 | When sanctuary is created (group asks for help / session starts). |
| Group coaching | `SANCTUARY_CHARGE_GROUP_COACHING` | $20.00 | When family requests help together and HoH approves. |
| Individual coaching | `SANCTUARY_CHARGE_INDIVIDUAL_COACHING` | $5.00 | When Little Nate is triggered to set in and de-escalate (after first free per member). |
| Get Help (assisted response) | `SANCTUARY_CHARGE_ASSISTED_RESPONSE` | $3.00 | Little Nate provides guide; client can push to chat. |

- **Backend:** `charge_base_fee`, `charge_group_coaching`, `charge_coaching` (5), `charge_assisted_response` (3) all use these constants. Bridge uses `SANCTUARY_CHARGE_*` for UI and charge calls.
- **Stripe:** You created four products (e.g. SANCTUARY_CHARGE_BASE_FEE, SANCTUARY_CHARGE_GROUP_COACHING, SANCTUARY_CHARGE_INDIVIDUAL_COACHING, SANCTUARY_CHARGE_ASSISTED_RESPONSE) at $20, $20, $5, $3. When `SANCTUARY_BILLING_ENABLED=true`, backend uses `billing.record_transaction(...)` (transaction_type: sanctuary_base_fee, sanctuary_group_coaching, etc.). Confirm whether `record_transaction` creates a Stripe PaymentIntent/Charge for these types or only logs locally; if only local, Stripe charges for these consumables may be triggered via IAP on iOS and then backend receipt validation.
- **Apple IAP (consumables):** Product IDs: `net.sovereignsanctuary.sanctuary_charge_base_fee`, `net.sovereignsanctuary.sanctuary_charge_group_coaching`, `net.sovereignsanctuary.sanctuary_charge_individual_coaching`, `net.sovereignsanctuary.sanctuary_charge_assisted_response`. On iOS, when user taps “Continue Coaching ($5)” or “Get Help + Return ($3)” or when base/group charges apply, the app should present the corresponding IAP and then call backend verify-receipt so the ledger is updated.

**Check:** Run a full sanctuary (client1 + client1b): create (expect $20 base), optional coaching ($5 after first free), optional Get Help ($3), optional group coaching ($20). Confirm UI shows correct amounts and backend ledger (and Stripe if enabled) reflects them.

---

## 3. Client Settings → Subscriptions → Family tab (charges)

| Data source | What’s shown |
|-------------|----------------|
| **WebSocket** | Family tab sends `sanctuary_get_members` with `family_id`. Bridge now handles **both** `get_family_members` and `sanctuary_get_members` and returns `family_members` with `members`, `pending_invites`, `billing`. Each member includes `family_billing_price_cents` (from `get_family_billing_summary`). |
| **REST fallback** | `GET /api/billing/family/members?family_id=...` returns members (may not include `family_billing_price_cents`; Family tab uses WS when available). |
| **Billing summary** | `get_family_billing_summary(family_id)` returns base_price_cents, members (price_cents, price_display), family_addon_cents, total_monthly_cents, total_display. |

**Family tab UI:** Base subscription ($49 or $149), family members count, Spouse/Partner free, First child free, “Additional members from $75/mo”, and **Total** (base + sum of members’ `family_billing_price_cents`). Per-session Family Sanctuary charges ($20, $20, $5, $3) are **not** shown in this tab; they are per-session and reflected in sanctuary session total during the session and in session history.

**Check:** As client1 (HoH with family), open Settings → Subscriptions → Family. Confirm Billing Summary shows base, member count, and total; confirm each member row shows correct $/mo or “Free” from `family_billing_price_cents`.

---

## 4. Settings → Client → Browse Vault (saved conversation + final summary)

| Item | How it gets into the vault |
|------|----------------------------|
| **Saved conversation** | User triggers “Copy & Save” (or equivalent) in Family Sanctuary → `_saveConversation()` → POST `/api/v1/vault/save-conversation` with full conversation text, `title: "Sanctuary Session — {date}"`, `source: sanctuary`. |
| **Final summary report** | After complete, Flutter shows session summary overlay. User taps **“Save to Vault”** → `_saveSessionSummaryToVault()` → POST `/api/v1/vault/save-conversation` with summary text (Key Conflicts, Points of Agreement, Your Personal Insights, Next Steps), `title: "Family Sanctuary Summary — {date}"`, `source: sanctuary_summary`. |

**Check (client1 and client1b):**

1. Run a Family Sanctuary with client1 and client1b; send a few messages.
2. Use “Copy & Save” (or the save action that calls `_saveConversation()`). In Settings → Browse Vault, confirm “Sanctuary Session — {date}” appears.
3. Complete the sanctuary as HoH. When the summary overlay appears, tap “Save to Vault”. In Settings → Browse Vault, confirm “Family Sanctuary Summary — {date}” appears.
4. Repeat from client1b’s device; confirm their vault shows their saved items (per member_id).

---

## 5. Stripe verification

- **Products:** In Stripe Dashboard → Product catalogue, confirm the four sanctuary products exist with correct prices: $20, $20, $5, $3 (Professional Services tax category).
- **Charges:** If `SANCTUARY_BILLING_ENABLED=true` and backend creates Stripe charges for these, run a test session and confirm in Stripe Dashboard that the corresponding PaymentIntents/Charges appear for the HoH customer. If the backend only records transactions locally (e.g. billing.json or DB) and does not create Stripe one-off charges for sanctuary consumables, then Stripe is used for subscription/add-ons only; sanctuary consumables are IAP on iOS and optionally Stripe on web.

---

## 6. In-app purchase testing

- **iOS:** On device/simulator, ensure the four consumable product IDs are configured in App Store Connect and that the app calls `PaymentService` (or equivalent) to purchase the correct product when:
  - Starting a sanctuary (base fee),
  - Approving group coaching,
  - Continuing coaching ($5),
  - Get Help + Return ($3).
- After a successful IAP, the app should send the receipt to `POST /api/billing/verify-receipt/apple` (and optionally restore). Backend should map product IDs to the four sanctuary consumables and update the sanctuary ledger / user balance so that the session total and Family Sanctuary history remain correct.
- **Check:** Trigger each charge type on iOS and confirm: (1) Apple payment sheet appears with correct price, (2) after purchase, backend accepts receipt and records the charge, (3) session total and any post-session summary reflect the charge.

---

## 7. Test accounts (client1, client1b)

- Use **client1** and **client1b** (or your real test accounts) for:
  - Family Sanctuary: create, chat, coaching, Get Help, group coaching, complete.
  - Save conversation and Save summary to Vault; confirm both appear in Browse Vault for the correct user.
  - Family tab: confirm billing summary and member list with `family_billing_price_cents` (and that both `sanctuary_get_members` and `get_family_members` are supported).

---

## 8. Code / config references

| Item | File(s) |
|------|--------|
| Sanctuary charge constants | `backend/app/websocket/sanctuary_engine.py` (SANCTUARY_CHARGE_*) |
| Base fee / group coaching / coaching / assisted | `sanctuary_engine.py` (charge_base_fee, charge_group_coaching, charge_coaching, charge_assisted_response); bridge_server.py (imports constants, calls engine) |
| Complete session + summary | `bridge_server.py` (sanctuary_complete block): summary generation, write to sanctuary_history, sanctuary_summary per member |
| Save conversation (Flutter) | `main.dart` (_saveConversation, POST save-conversation) |
| Save summary to Vault (Flutter) | `main.dart` (_saveSessionSummaryToVault, “Save to Vault” in summary overlay) |
| Vault save-conversation API | `backend/app/routers/vault_api.py` (POST /vault/save-conversation) |
| Family members + billing | `bridge_server.py` (get_family_members / sanctuary_get_members), `stripe_billing.py` (get_family_billing_summary) |
| Family tab UI | `mobile/lib/screens/billing_screens.dart` (FamilyManagementScreen, _loadMembers, Billing Summary) |
| Apple IAP product IDs | App Store Connect; Flutter PaymentService; backend receipt_validation (map to sanctuary consumables and credit ledger) |

---

## 9. Summary checklist

- [ ] **Save conversation:** “Copy & Save” in sanctuary → vault item “Sanctuary Session — {date}” visible in Browse Vault (client1 / client1b).
- [ ] **Exit sanctuary:** sanctuary_exit → sanctuary_exit_confirm → member marked exited; last member can trigger complete.
- [ ] **Complete sanctuary:** sanctuary_complete (HoH/creator) → summary generated → sanctuary_summary per member → overlay with “Save to Vault” and “Close & Exit”.
- [ ] **Final summary in vault:** After complete, tap “Save to Vault” → “Family Sanctuary Summary — {date}” visible in Browse Vault.
- [ ] **Four charges:** $20 base, $20 group, $5 coaching, $3 Get Help applied via constants; UI and ledger consistent.
- [ ] **Family tab:** sanctuary_get_members (or get_family_members) returns members with family_billing_price_cents; Billing Summary shows base + add-ons + total.
- [ ] **Stripe:** Four products present; charges appear in Stripe when billing enabled (if implemented).
- [ ] **IAP:** iOS consumables for all four; verify-receipt credits ledger; session total correct after each purchase.
