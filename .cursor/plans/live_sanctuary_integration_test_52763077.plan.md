---
name: Live Sanctuary Integration Test
overview: Write and run a Python WebSocket test script against production (68.183.168.75) that simulates John D. (HoH) and Jane D. (member) in two Family Sanctuary sessions, exercising billing charges, coaching, group coaching approve/decline, and HoH observation capture.
todos:
  - id: write-test-script
    content: Write the Python test script (backend/tests/test_live_sanctuary.py) with both scenarios and colored output
    status: completed
  - id: pre-check-server
    content: Verify production server health (containers, bridge, DB) before running test
    status: completed
  - id: run-scenario-a
    content: "Run Scenario A: Jane creates sanctuary, coaching + group coaching approved"
    status: completed
  - id: run-scenario-b
    content: "Run Scenario B: John creates sanctuary, group coaching declined with HoH explanation"
    status: completed
  - id: verify-db-observations
    content: Query hoh_decision_observations table to confirm observation + classification captured
    status: completed
isProject: false
---

# Live Family Sanctuary Integration Test

## Test Accounts


| Account | Username   | Password  | Hardware ID   | Family         | Role   |
| ------- | ---------- | --------- | ------------- | -------------- | ------ |
| John D. | `client1`  | `test123` | `CLIENT_001`  | `FAM_1834DACF` | HEAD   |
| Jane D. | `client1b` | `test123` | `CLIENT_001B` | `FAM_1834DACF` | MEMBER |


## Connection

- Endpoint: `wss://api.sovereignsanctuary.net/ws`
- Auth: `login_request` with username/password/expected_role

## Test Script

Write a single Python script (`backend/tests/test_live_sanctuary.py`) using the `websockets` library that runs two concurrent WebSocket clients (John + Jane) through the following scenarios.

### Scenario A: Jane Creates Sanctuary, Coaching + Group Coaching Approved

1. **Connect both users** -- login John and Jane via `login_request`
2. **Jane sends `sanctuary_create**` -- verify `sanctuary_created` response with `sanctuary_id`
3. **John sends `sanctuary_join**` with the sanctuary_id -- verify `sanctuary_onboarding` / `sanctuary_entry_ready`
4. **Exchange messages** -- Jane sends a message about a family issue; John responds
5. **Trigger coaching offer** -- Jane sends a message containing distress keywords (e.g., "I feel stuck, little nate help me")
6. **Accept coaching** -- when `sanctuary_coaching_offer` arrives, accept it via `sanctuary_coaching_accept` -- verify `sanctuary_coaching_started` with charge info
7. **Trigger group coaching** -- John sends "we need group coaching, little nate help us all"
8. **John approves group coaching** -- send `sanctuary_group_coaching_approve` -- verify $20 charge broadcast
9. **Both receive `sanctuary_suggested_response**` -- send them back via `sanctuary_send_suggested_response`
10. **State sync** -- send `sanctuary_state_sync` and verify `total_charges` reflects base fee ($20) + coaching ($5) + group coaching ($20) = $45+

### Scenario B: John Creates Sanctuary, Group Coaching Declined with Explanation

1. **John sends `sanctuary_create**` -- new sanctuary
2. **Jane joins**
3. **Exchange messages** -- discuss an issue
4. **Trigger group coaching** -- Jane sends "what should we do? little nate help us"
5. **John declines with explanation** -- send `sanctuary_group_coaching_decline` with `decline_reason: "budget_tight"` and `decline_note: "We already spent a lot this month"`
6. **Verify decline response** -- `sanctuary_group_coaching_status` with `state: "IDLE"`
7. **Verify Little Nate message** -- acknowledgment message appears

### Verification: HoH Observation Captured

After Scenario B, SSH to production and query the database:

```sql
SELECT id, family_id, hoh_user_id, sanctuary_id, charge_type,
       charge_amount, decision, decline_reason, decline_note,
       nate_classification, created_at
FROM hoh_decision_observations
ORDER BY created_at DESC LIMIT 5;
```

Check that:

- `decision = 'declined'`
- `decline_reason = 'budget_tight'`
- `decline_note` contains the explanation text
- `nate_classification` JSONB is populated (may take a few seconds for async classification)

## Script Design

- Use `asyncio` + `websockets` library
- Two async tasks running in parallel (one per user)
- `asyncio.Queue` for cross-user coordination (e.g., passing sanctuary_id from creator to joiner)
- Colored console output for readability (John = blue, Jane = green, System = yellow)
- Each step prints PASS/FAIL with the message details
- Timeout of 30s per expected message
- Final summary of all charges and observations

## Execution

```bash
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d littlenate -c \"SELECT COUNT(*) FROM hoh_decision_observations\""
# Note the count before testing

pip install websockets  # if not already installed
python backend/tests/test_live_sanctuary.py

# After test, verify DB
ssh root@68.183.168.75 "docker exec nate_postgres psql -U nate_admin -d littlenate -c \"SELECT id, decline_reason, decline_note, nate_classification FROM hoh_decision_observations ORDER BY created_at DESC LIMIT 3\""
```

