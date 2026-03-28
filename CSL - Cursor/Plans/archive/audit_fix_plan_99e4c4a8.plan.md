---
name: Audit Fix Plan
overview: Comprehensive audit of the HoH Decline Explanation Box and Family Sanctuary Billing implementations, identifying 14 bugs across severity levels with concrete fixes for each.
todos:
  - id: fix-c1
    content: Fix family_id lookup in HoH decline INSERT (bridge_server.py) — use head_id to look up family UUID
    status: completed
  - id: fix-c2
    content: Fix list_payment_methods to return both cards and us_bank_account types (billing.py)
    status: completed
  - id: fix-h1
    content: Fix SovereignMind wisdom feed — either inject app reference or access SovereignMind directly (bridge_server.py)
    status: completed
  - id: fix-h2
    content: Initialize total=0 before async with block in _classify_hoh_decision (bridge_server.py)
    status: completed
  - id: fix-h3
    content: Fix or remove speculative generational flag query logic (bridge_server.py)
    status: completed
  - id: fix-h4
    content: Fix UNION query in analyze_hoh_decision_patterns to resolve family_id properly (pattern_engine.py)
    status: completed
  - id: fix-m1
    content: Dispose noteController in _showDeclineExplanationDialog (main.dart)
    status: completed
  - id: fix-m2
    content: Move discount code TextEditingControllers to state variables with proper disposal (billing_screens.dart)
    status: completed
  - id: fix-m3
    content: Add obs_id null check at start of _classify_hoh_decision (bridge_server.py)
    status: completed
  - id: fix-m4
    content: Handle non-UUID input in HoH observations admin endpoint (admin.py)
    status: completed
  - id: fix-m5
    content: Validate fund_id as UUID in scholarship API models (scholarship_api.py)
    status: completed
  - id: fix-l1
    content: Wire up get_pre_session_estimate call site in bridge_server.py or remove dead code
    status: completed
  - id: fix-l2
    content: Add logging to silent except blocks in _classify_hoh_decision (bridge_server.py)
    status: completed
  - id: fix-l3
    content: Fix pre-existing total_themes undefined variable in pattern_engine.py
    status: completed
isProject: false
---

# Audit: HoH Decline + Family Sanctuary Billing

## Severity Key

- **CRITICAL** — Data corruption or feature completely broken
- **HIGH** — Logic error, feature silently fails
- **MEDIUM** — Memory leak, missing validation, partial failure
- **LOW** — Dead code, style, minor resilience

---

## CRITICAL (2 issues)

### C1. Wrong `family_id` lookup in HoH decline INSERT

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (decline handler, ~line 19050)

The INSERT uses `sanctuary_data.get("family_id", head_id)` as `$1` in a `SELECT id FROM users WHERE hardware_id = $1` subquery. But `family_id` from sanctuary data is a UUID (not a hardware_id), so the lookup finds nothing. The fallback `head_id` is a hardware_id, but it would store the **user's** UUID as `family_id`, not the **family's** UUID.

**Fix:** Look up the family UUID from the HoH's user record:

```python
_obs_row = await _obs_conn.fetchrow("""
    INSERT INTO hoh_decision_observations
        (family_id, hoh_user_id, sanctuary_id, charge_type,
         charge_amount, decision, decline_reason, decline_note)
    VALUES (
        (SELECT family_id FROM users WHERE hardware_id = $1 LIMIT 1),
        (SELECT id FROM users WHERE hardware_id = $1 LIMIT 1),
        $2, 'group_coaching', 20.00, 'declined', $3, $4
    )
    RETURNING id
""", head_id, sanctuary_id, decline_reason, decline_note)
```

### C2. Payment methods endpoint only returns cards — bank accounts invisible

**File:** [backend/app/routers/billing.py](backend/app/routers/billing.py) (line 441)

`list_payment_methods()` calls `stripe.PaymentMethod.list(customer=..., type="card")`. Bank accounts added via ACH setup never appear. The Flutter `PaymentMethodsScreen` checks `m['type'] == 'us_bank_account'` but this data never arrives.

**Fix:** Query both types and merge results:

```python
cards = stripe.PaymentMethod.list(customer=stripe_customer, type="card")
banks = stripe.PaymentMethod.list(customer=stripe_customer, type="us_bank_account")
# Build combined list with type field, bank_name, last4 for banks
```

---

## HIGH (4 issues)

### H1. `_fastapi_app` global never set — SovereignMind wisdom feed is dead

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (~line 7295)

`globals().get("_fastapi_app")` always returns `None`. No code in bridge_server.py ever sets this variable. The `absorb_fibre_wisdom()` call never executes.

**Fix:** Import and use the SovereignMind instance directly, or add a setter function called from `main.py` during startup (matching the pattern used for `set_hive_defense` etc. if such exists). Alternatively, use the `db_pool` to write wisdom directly to the database.

### H2. `total` variable used outside its scope in `_classify_hoh_decision`

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (~line 7293)

`total` is computed inside the `async with db_pool.acquire()` block. If that block throws before `total` is set, the line `if total >= 3` raises `NameError`.

**Fix:** Initialize `total = 0` before the `async with` block.

### H3. Generational flag query logic is incorrect

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (~line 7252)

The query finds observations where `u.family_id != current family`, then counts control-reason declines. This flags observations from *any other family* as "generational", which is semantically wrong. It should check for parent-child relationships.

**Fix:** Since the system may not track explicit parent-child links across families, this should be simplified to check if the HoH has repeated control patterns within their *own* family history, or the generational flag should be deferred until a parent-link table exists. For now, set `generational = False` by default and only flag if a known parent record is found (or remove the speculative logic entirely).

### H4. `analyze_hoh_decision_patterns` UNION query is fragile

**File:** [backend/app/services/pattern_engine.py](backend/app/services/pattern_engine.py) (~line 424)

```sql
WHERE family_id = (
    SELECT family_id FROM users WHERE id = $1
    UNION
    SELECT $1::uuid
    LIMIT 1
)
```

The UNION is ambiguous — if `$1` is a hardware_id string, `$1::uuid` fails. If `$1` is a UUID, the first branch may return NULL (no user with that `id`), and the second branch treats the UUID as a family_id which may be wrong.

**Fix:** Resolve family_id explicitly first, then query observations:

```python
family_uuid = await conn.fetchval(
    "SELECT family_id FROM users WHERE id = $1 "
    "UNION SELECT id FROM users WHERE id = $1 "
    "LIMIT 1", family_id
)
```

Or split into two sequential queries for clarity.

---

## MEDIUM (5 issues)

### M1. Memory leak: `TextEditingController` in dialog (main.dart)

**File:** [mobile/lib/main.dart](mobile/lib/main.dart) (~line 3114)

`noteController` in `_showDeclineExplanationDialog()` is created but never disposed when the dialog closes.

**Fix:** Chain `.then((_) => noteController.dispose())` on the `showDialog()` call.

### M2. Memory leak: `TextEditingController` in `_discountCodeSection` (billing_screens.dart)

**File:** [mobile/lib/screens/billing_screens.dart](mobile/lib/screens/billing_screens.dart) (~line 2268)

`final ctrl = TextEditingController()` is created inside a builder method. A new controller is created every rebuild and never disposed.

**Fix:** Move the school code and corporate code controllers to `_PaymentMethodsScreenState` instance variables, dispose them in `dispose()`.

### M3. Missing `obs_id` null check in `_classify_hoh_decision`

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (~line 7187)

If `obs_id` is None (INSERT returned no row), the function proceeds to UPDATE with `WHERE id = NULL`, which silently updates nothing.

**Fix:** Add `if not obs_id: return` at the top of `_classify_hoh_decision`.

### M4. HoH observations admin endpoint may crash on non-UUID input

**File:** [backend/app/routers/admin.py](backend/app/routers/admin.py) (~line 2150)

`WHERE o.family_id = $1::uuid` will throw a PostgreSQL error if `family_id` is a hardware_id string (not a valid UUID).

**Fix:** Wrap in a try/except or validate the input format first, or restructure the query to try hardware_id lookup first.

### M5. Scholarship API `fund_id` passed as string, used as UUID

**File:** [backend/app/routers/scholarship_api.py](backend/app/routers/scholarship_api.py) (lines 98, 184, 254)

`fund_id` is typed as `str` in Pydantic models but used in queries against a UUID column. asyncpg will auto-cast valid UUID strings, but invalid strings cause unhandled errors.

**Fix:** Use `uuid.UUID(req.fund_id)` to validate before querying, or change the Pydantic model field to `uuid.UUID`.

---

## LOW (3 issues)

### L1. `get_pre_session_estimate` is dead code

**File:** [backend/app/websocket/sanctuary_engine.py](backend/app/websocket/sanctuary_engine.py) (~line 673)

The method exists and `sanctuary_pre_session_estimate` is handled in main.dart, but nothing in bridge_server.py ever calls `get_pre_session_estimate()` or sends that message type to clients.

**Fix:** Add a call site in bridge_server.py (e.g., when a non-HoH member starts a session, send the estimate to the HoH), or remove both the method and the Flutter handler.

### L2. Silent exception swallowing in `_classify_hoh_decision`

**File:** [backend/app/websocket/bridge_server.py](backend/app/websocket/bridge_server.py) (~lines 7246, 7260)

C_emo and generational queries catch all exceptions with bare `except: pass`. Failures are completely invisible.

**Fix:** Add `except Exception as e: print(f">>> [HOH_OBS] query failed: {e}")` for debuggability.

### L3. Pre-existing: `total_themes` undefined in `analyze_emotional_themes`

**File:** [backend/app/services/pattern_engine.py](backend/app/services/pattern_engine.py) (line 149)

`total_themes_analyzed: total_themes` references a variable that was never defined. This is a pre-existing bug (not introduced by our changes) but will crash if `analyze_emotional_themes` is ever called.

**Fix:** Replace with the correct variable, likely `len(union_themes)` or sum of per-member theme counts.

---

## Summary


| Severity | Count | Key Risk                                                                  |
| -------- | ----- | ------------------------------------------------------------------------- |
| Critical | 2     | Data corruption (wrong family_id), invisible bank accounts                |
| High     | 4     | Dead wisdom feed, NameError risk, wrong generational logic, fragile query |
| Medium   | 5     | Memory leaks (x2), null check, UUID validation (x2)                       |
| Low      | 3     | Dead code, silent errors, pre-existing bug                                |


