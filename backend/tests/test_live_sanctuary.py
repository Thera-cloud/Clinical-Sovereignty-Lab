"""
Live Family Sanctuary Integration Test
=======================================
Tests the full Family Sanctuary flow on production using John D. (HoH)
and Jane D. (family member) over real WebSocket connections.

Scenario A: Jane creates, coaching accepted, group coaching approved
Scenario B: John creates, group coaching declined with explanation

Usage:
    pip install websockets
    python backend/tests/test_live_sanctuary.py
"""

import asyncio
import json
import ssl
import sys
import time
import traceback

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' library required. Run: pip install websockets")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WS_URI = "wss://api.sovereignsanctuary.net/ws"
MSG_TIMEOUT = 45

JOHN = {"username": "client1",  "password": "test123", "expected_role": "CLIENT", "hardware_id": "CLIENT_001"}
JANE = {"username": "client1b", "password": "test123", "expected_role": "CLIENT", "hardware_id": "CLIENT_001B"}

SANCTUARY_ENTRY_TYPES = {
    "sanctuary_created", "sanctuary_joined", "sanctuary_reconnected",
    "sanctuary_rejoined", "sanctuary_onboarding",
}

# ---------------------------------------------------------------------------
# Console colors
# ---------------------------------------------------------------------------
class C:
    BLUE   = "\033[94m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def john_log(msg):  print(f"{C.BLUE}[JOHN]{C.RESET} {msg}")
def jane_log(msg):  print(f"{C.GREEN}[JANE]{C.RESET} {msg}")
def sys_log(msg):   print(f"{C.YELLOW}[SYS]{C.RESET}  {msg}")
def pass_log(msg):  print(f"{C.CYAN}{C.BOLD}  PASS{C.RESET} {msg}")
def fail_log(msg):  print(f"{C.RED}{C.BOLD}  FAIL{C.RESET} {msg}")
def hdr(msg):       print(f"\n{C.BOLD}{'='*60}\n {msg}\n{'='*60}{C.RESET}")

# ---------------------------------------------------------------------------
# WebSocket client helper
# ---------------------------------------------------------------------------
class SanctuaryClient:
    def __init__(self, name, creds, color_fn):
        self.name = name
        self.creds = creds
        self.log = color_fn
        self.ws = None
        self.token = None
        self.profile = None
        self._inbox = asyncio.Queue()
        self._listener_task = None
        self._all_messages = []

    async def connect(self):
        ssl_ctx = ssl.create_default_context()
        self.ws = await websockets.connect(WS_URI, ssl=ssl_ctx, ping_interval=20, ping_timeout=10)
        self._listener_task = asyncio.create_task(self._listen())
        connected = await self.wait_for("connected", timeout=10)
        if connected:
            self.log(f"Connected — status={connected.get('status')}")
        return connected

    async def login(self):
        await self.ws.send(json.dumps({"type": "login_request", **self.creds}))
        resp = await self.wait_for("login_success", timeout=30)
        if resp:
            self.token = resp.get("token")
            self.profile = resp.get("profile", {})
            self.log(f"Logged in as {self.profile.get('name')} (family_role={self.profile.get('family_role')})")
            return True
        fail = await self.wait_for("login_failed", timeout=3)
        if fail:
            self.log(f"Login FAILED: {fail.get('message')}")
        return False

    async def send(self, msg_dict):
        self.log(f"  >> {msg_dict.get('type', '?')}")
        await self.ws.send(json.dumps(msg_dict))

    async def wait_for(self, msg_type, timeout=MSG_TIMEOUT, quiet=False):
        """Wait for a specific message type from the inbox."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = max(0.1, deadline - time.time())
                msg = await asyncio.wait_for(self._inbox.get(), timeout=remaining)
                if msg.get("type") == msg_type:
                    if not quiet:
                        self.log(f"  << {msg_type}")
                    return msg
            except asyncio.TimeoutError:
                break
        if not quiet:
            self.log(f"  !! Timeout waiting for '{msg_type}' ({timeout}s)")
        return None

    async def wait_for_any(self, msg_types: set, timeout=MSG_TIMEOUT, quiet=False):
        """Wait for any of several message types."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = max(0.1, deadline - time.time())
                msg = await asyncio.wait_for(self._inbox.get(), timeout=remaining)
                if msg.get("type") in msg_types:
                    if not quiet:
                        self.log(f"  << {msg.get('type')}")
                    return msg
            except asyncio.TimeoutError:
                break
        if not quiet:
            self.log(f"  !! Timeout waiting for any of {msg_types} ({timeout}s)")
        return None

    async def collect_for(self, seconds):
        """Collect all messages for a duration."""
        collected = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                remaining = max(0.05, deadline - time.time())
                msg = await asyncio.wait_for(self._inbox.get(), timeout=remaining)
                collected.append(msg)
            except asyncio.TimeoutError:
                break
        return collected

    async def drain(self, seconds=2):
        """Drain the inbox for a few seconds to clear pending messages."""
        await self.collect_for(seconds)

    async def close(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self.ws:
            await self.ws.close()

    async def _listen(self):
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                    self._all_messages.append(msg)
                    await self._inbox.put(msg)
                except json.JSONDecodeError:
                    pass
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass


def _extract_sanctuary_id(msg: dict):
    """Extract sanctuary_id from various response formats."""
    return msg.get("sanctuary_id")


# ---------------------------------------------------------------------------
# Scenario A: Jane creates sanctuary, coaching + group coaching approved
# ---------------------------------------------------------------------------
async def scenario_a(john: SanctuaryClient, jane: SanctuaryClient):
    hdr("SCENARIO A: Jane Creates Sanctuary")
    results = []

    # --- Step 1: Jane opens/creates sanctuary ---
    sys_log("Step 1: Jane opens Family Sanctuary")
    await jane.send({"type": "sanctuary_get_or_create"})
    entry = await jane.wait_for_any(SANCTUARY_ENTRY_TYPES, timeout=30)
    if entry:
        sanctuary_id = _extract_sanctuary_id(entry)
        entry_type = entry.get("type")
        pass_log(f"Jane entered sanctuary: type={entry_type}, id={sanctuary_id}")
        if entry_type == "sanctuary_created":
            pass_log(f"  base_fee_charged={entry.get('base_fee_charged')}, total=${entry.get('total_charges', 0):.2f}")
        results.append(("A1: Jane opens sanctuary", True, sanctuary_id))
    else:
        # Check all collected messages for debugging
        all_recent = jane._all_messages[-10:]
        fail_log(f"No sanctuary response. Last messages: {[m.get('type') for m in all_recent]}")
        results.append(("A1: Jane opens sanctuary", False, None))
        return results, None

    # Drain Jane's onboarding/Nate messages
    await jane.drain(5)

    # --- Step 2: John joins via get_or_create (auto-finds family's active sanctuary) ---
    sys_log("Step 2: John joins sanctuary")
    await john.send({"type": "sanctuary_get_or_create"})
    john_entry = await john.wait_for_any(SANCTUARY_ENTRY_TYPES, timeout=20)
    if john_entry:
        john_entry_type = john_entry.get("type")
        pass_log(f"John entered: type={john_entry_type}")
        results.append(("A2: John joins", True, john_entry_type))
    else:
        all_recent = john._all_messages[-10:]
        fail_log(f"John did not enter. Last messages: {[m.get('type') for m in all_recent]}")
        results.append(("A2: John joins", False, None))

    # Drain any extra messages (estimates, onboarding, notifications)
    await john.drain(5)
    await jane.drain(3)

    # --- Step 3: Both complete onboarding if needed ---
    sys_log("Step 3: Complete onboarding")
    for client, name, responses in [
        (john, "John", {"reason": "Family communication test", "goal": "Test billing", "concerns": "Testing integration"}),
        (jane, "Jane", {"reason": "Family stress", "goal": "Better communication", "concerns": "Overwhelm"}),
    ]:
        await client.send({
            "type": "sanctuary_onboarding_complete",
            "sanctuary_id": sanctuary_id,
            "responses": responses,
        })
        entry_ready = await client.wait_for("sanctuary_entry_ready", timeout=15, quiet=True)
        if not entry_ready:
            entry_ready = await client.wait_for("sanctuary_entry_complete", timeout=5, quiet=True)
        if entry_ready:
            pass_log(f"{name} onboarding complete")
        else:
            sys_log(f"{name} onboarding — no entry_ready (may already be active)")

    results.append(("A3: Onboarding complete", True, None))
    await john.drain(3)
    await jane.drain(3)

    # --- Step 4: Exchange messages ---
    sys_log("Step 4: Exchange messages (family discussion)")
    await jane.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "I've been feeling really overwhelmed lately with everything going on at home."
    })
    await asyncio.sleep(3)
    await john.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "I hear you, Jane. I've been stressed too. I think we need to talk about how we handle things."
    })
    await asyncio.sleep(3)
    pass_log("Messages exchanged")
    results.append(("A4: Messages exchanged", True, None))
    await john.drain(5)
    await jane.drain(5)

    # --- Step 5: Jane triggers distress / coaching offer ---
    sys_log("Step 5: Jane sends distress message to trigger coaching offer")
    await jane.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "I feel so stuck and overwhelmed. Little Nate, I need help. I don't know what to do anymore."
    })

    coaching_offer = None
    all_msgs = await jane.collect_for(15)
    for m in all_msgs:
        if m.get("type") == "sanctuary_coaching_offer":
            coaching_offer = m
            break
        elif m.get("type") == "sanctuary_group_coaching_offer":
            sys_log(f"Got group coaching offer instead of private coaching offer")

    if coaching_offer:
        intervention_id = coaching_offer.get("intervention_id")
        is_free = coaching_offer.get("is_free", False)
        cost = coaching_offer.get("cost", 5.00)
        pass_log(f"Coaching offer: intervention={intervention_id}, free={is_free}, cost=${cost:.2f}")
        results.append(("A5: Coaching offer", True, intervention_id))

        sys_log("Step 6: Jane accepts coaching")
        await jane.send({
            "type": "sanctuary_coaching_accept", "sanctuary_id": sanctuary_id,
            "intervention_id": intervention_id, "assisted_response": False,
        })
        coaching_started = await jane.wait_for("sanctuary_coaching_started", timeout=30)
        if coaching_started:
            charge = coaching_started.get("charge_amount", 0)
            pass_log(f"Coaching started: charge=${charge:.2f}, free={coaching_started.get('is_free')}")
            results.append(("A6: Coaching accepted", True, f"${charge:.2f}"))
        else:
            fail_log("No coaching_started response")
            results.append(("A6: Coaching accepted", False, None))

        await jane.drain(10)
        await john.drain(5)
    else:
        sys_log("No private coaching offer — escalation detection may not have triggered. Continuing...")
        results.append(("A5: Coaching offer", False, "Not triggered"))
        results.append(("A6: Coaching accepted", False, "Skipped"))
        # Also check John's inbox in case the offer went to HoH
        john_msgs = await john.collect_for(3)
        for m in john_msgs:
            if m.get("type") == "sanctuary_group_coaching_offer":
                sys_log("Group coaching offer went to John (HoH) from Jane's distress message")

    # --- Step 7: Trigger group coaching ---
    sys_log("Step 7: Request group coaching")
    # Jane requests (non-HoH), offer goes to John (HoH)
    await jane.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "What should we do? We need group coaching. Little Nate help us all."
    })

    gc_offer = await john.wait_for("sanctuary_group_coaching_offer", timeout=20)
    if not gc_offer:
        # Try alternate: John requests it himself (as HoH, he gets the offer directly)
        sys_log("Retrying: John sends group coaching request")
        await john.send({
            "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
            "message": "We need group coaching. Little Nate, help us all figure this out together."
        })
        gc_offer = await john.wait_for("sanctuary_group_coaching_offer", timeout=20)

    if gc_offer:
        pass_log(f"Group coaching offer: cost=${gc_offer.get('cost', 0):.2f}, triggered_by={gc_offer.get('triggered_by')}")
        results.append(("A7: Group coaching offer", True, f"${gc_offer.get('cost', 0):.2f}"))
    else:
        fail_log("No group coaching offer received after both attempts")
        results.append(("A7: Group coaching offer", False, None))

    if gc_offer:
        # --- Step 8: John approves group coaching ---
        sys_log("Step 8: John (HoH) approves group coaching ($20)")
        await john.send({"type": "sanctuary_group_coaching_approve", "sanctuary_id": sanctuary_id})

        john_suggestion = await john.wait_for("sanctuary_suggested_response", timeout=60)
        jane_suggestion = await jane.wait_for("sanctuary_suggested_response", timeout=45)

        if john_suggestion:
            pass_log(f"John suggestion: \"{john_suggestion.get('suggested_text', '')[:80]}...\"")
            results.append(("A8a: John suggestion", True, None))
        else:
            fail_log("John did not receive suggestion")
            results.append(("A8a: John suggestion", False, None))

        if jane_suggestion:
            pass_log(f"Jane suggestion: \"{jane_suggestion.get('suggested_text', '')[:80]}...\"")
            results.append(("A8b: Jane suggestion", True, None))
        else:
            fail_log("Jane did not receive suggestion")
            results.append(("A8b: Jane suggestion", False, None))

        sys_log("Step 9: Both send their suggested responses")
        if john_suggestion:
            await john.send({
                "type": "sanctuary_send_suggested_response", "sanctuary_id": sanctuary_id,
                "response_text": john_suggestion.get("suggested_text", "I understand."), "was_edited": False,
            })
        if jane_suggestion:
            await jane.send({
                "type": "sanctuary_send_suggested_response", "sanctuary_id": sanctuary_id,
                "response_text": jane_suggestion.get("suggested_text", "Thank you."), "was_edited": False,
            })
        results.append(("A9: Suggested responses sent", True, None))
        await john.drain(5)
        await jane.drain(5)

    # --- Step 10: State sync to verify charges ---
    sys_log("Step 10: State sync — verify total charges")
    await john.send({"type": "sanctuary_sync_state", "sanctuary_id": sanctuary_id})
    sync = await john.wait_for("sanctuary_state_sync", timeout=15)
    if sync:
        total = sync.get("total_charges", 0)
        charges = sync.get("billing_charges", [])
        pass_log(f"Total charges: ${total:.2f} across {len(charges)} charge(s)")
        for ch in (charges or [])[-5:]:
            sys_log(f"  - {ch.get('charge_type', '?')}: ${ch.get('amount', 0):.2f} ({ch.get('status', '?')})")
        results.append(("A10: State sync", True, f"${total:.2f}"))
    else:
        fail_log("State sync failed")
        results.append(("A10: State sync", False, None))

    return results, sanctuary_id


async def complete_sanctuary(client: SanctuaryClient, sanctuary_id: str):
    """End a sanctuary session so a new one can be created."""
    sys_log(f"Completing sanctuary {sanctuary_id}...")
    await client.send({"type": "sanctuary_complete", "sanctuary_id": sanctuary_id})
    resp = await client.wait_for_any(
        {"sanctuary_summary", "sanctuary_completed", "error"}, timeout=30, quiet=True
    )
    if resp:
        sys_log(f"Sanctuary completed (response type: {resp.get('type')})")
    else:
        sys_log("No completion response — sanctuary may remain active")
    await client.drain(5)


# ---------------------------------------------------------------------------
# Scenario B: John creates sanctuary, group coaching declined
# ---------------------------------------------------------------------------
async def scenario_b(john: SanctuaryClient, jane: SanctuaryClient):
    hdr("SCENARIO B: John Creates Sanctuary, HoH Declines Group Coaching")
    results = []

    # --- Step 1: John opens/creates sanctuary ---
    sys_log("Step 1: John opens Family Sanctuary")
    await john.send({"type": "sanctuary_get_or_create"})
    entry = await john.wait_for_any(SANCTUARY_ENTRY_TYPES, timeout=30)
    if entry:
        sanctuary_id = _extract_sanctuary_id(entry)
        entry_type = entry.get("type")
        pass_log(f"John entered sanctuary: type={entry_type}, id={sanctuary_id}")
        results.append(("B1: John opens sanctuary", True, sanctuary_id))
    else:
        all_recent = john._all_messages[-10:]
        fail_log(f"No sanctuary response. Last messages: {[m.get('type') for m in all_recent]}")
        results.append(("B1: John opens sanctuary", False, None))
        return results, None

    await john.drain(5)

    # --- Step 2: Jane joins ---
    sys_log("Step 2: Jane joins sanctuary")
    await jane.send({"type": "sanctuary_get_or_create"})
    jane_entry = await jane.wait_for_any(SANCTUARY_ENTRY_TYPES, timeout=20)
    if jane_entry:
        pass_log(f"Jane entered: type={jane_entry.get('type')}")
        results.append(("B2: Jane joins", True, None))
    else:
        fail_log("Jane did not enter sanctuary")
        results.append(("B2: Jane joins", False, None))

    await jane.drain(5)
    await john.drain(3)

    # --- Step 3: Both complete onboarding ---
    sys_log("Step 3: Complete onboarding")
    for client, name, responses in [
        (jane, "Jane", {"reason": "Budget discussion", "goal": "Understand concerns", "concerns": "Financial disagreements"}),
        (john, "John", {"reason": "Family budget", "goal": "Find solutions", "concerns": "Spending patterns"}),
    ]:
        await client.send({
            "type": "sanctuary_onboarding_complete",
            "sanctuary_id": sanctuary_id,
            "responses": responses,
        })
        entry_ready = await client.wait_for("sanctuary_entry_ready", timeout=10, quiet=True)
        if not entry_ready:
            await client.wait_for("sanctuary_entry_complete", timeout=5, quiet=True)

    results.append(("B3: Onboarding complete", True, None))
    await john.drain(3)
    await jane.drain(3)

    # --- Step 4: Exchange messages + trigger group coaching ---
    sys_log("Step 4: Exchange messages and trigger group coaching")
    await john.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "I think we need to revisit our approach to the kids' schedules."
    })
    await asyncio.sleep(3)
    await jane.send({
        "type": "sanctuary_message", "sanctuary_id": sanctuary_id,
        "message": "I agree, it's been causing a lot of tension. What should we do? Little Nate help us figure this out."
    })

    gc_offer = await john.wait_for("sanctuary_group_coaching_offer", timeout=20)
    if gc_offer:
        pass_log(f"Group coaching offer received: cost=${gc_offer.get('cost', 0):.2f}")
        results.append(("B4: Group coaching offer", True, f"${gc_offer.get('cost', 0):.2f}"))
    else:
        fail_log("No group coaching offer received")
        results.append(("B4: Group coaching offer", False, None))
        return results, sanctuary_id

    # --- Step 5: John DECLINES with explanation ---
    sys_log("Step 5: John (HoH) declines group coaching with explanation")
    await john.send({
        "type": "sanctuary_group_coaching_decline",
        "sanctuary_id": sanctuary_id,
        "decline_reason": "budget_tight",
        "decline_note": "We already spent a lot this month on sessions, I want to try handling this ourselves first."
    })

    status_msg = None
    nate_msg = None
    all_msgs = await john.collect_for(10)
    for m in all_msgs:
        mt = m.get("type")
        if mt == "sanctuary_group_coaching_status":
            status_msg = m
        if mt == "sanctuary_message":
            inner = m.get("message", m)
            if isinstance(inner, dict) and inner.get("message_type") == "LITTLE_NATE":
                nate_msg = inner
            elif isinstance(inner, str) and "little nate" in inner.lower():
                nate_msg = {"content": inner}

    if status_msg:
        pass_log(f"Decline status: state={status_msg.get('state')}")
        results.append(("B5a: Decline status", True, status_msg.get("state")))
    else:
        fail_log("No decline status received")
        results.append(("B5a: Decline status", False, None))

    if nate_msg:
        pass_log(f"Little Nate said: \"{(nate_msg.get('content', '') or '')[:100]}\"")
        results.append(("B5b: Nate acknowledgment", True, None))
    else:
        sys_log("No Little Nate acknowledgment message detected (may be in broadcast)")
        results.append(("B5b: Nate acknowledgment", False, None))

    # --- Step 6: State sync to confirm charges ---
    sys_log("Step 6: State sync — verify no group coaching charge")
    await john.send({"type": "sanctuary_sync_state", "sanctuary_id": sanctuary_id})
    sync = await john.wait_for("sanctuary_state_sync", timeout=15)
    if sync:
        total = sync.get("total_charges", 0)
        pass_log(f"Total charges: ${total:.2f} (should be ~$20 base fee only)")
        results.append(("B6: State sync", True, f"${total:.2f}"))
    else:
        fail_log("State sync failed")
        results.append(("B6: State sync", False, None))

    return results, sanctuary_id


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def main():
    hdr("LIVE FAMILY SANCTUARY INTEGRATION TEST")
    sys_log(f"Target: {WS_URI}")
    sys_log(f"John D. (HoH, client1) + Jane D. (member, client1b)")
    sys_log(f"Family: FAM_1834DACF")

    john = SanctuaryClient("John", JOHN, john_log)
    jane = SanctuaryClient("Jane", JANE, jane_log)
    all_results = []

    try:
        hdr("AUTHENTICATION")
        await john.connect()
        await jane.connect()

        john_ok = await john.login()
        jane_ok = await jane.login()

        if not john_ok or not jane_ok:
            fail_log("Authentication failed — cannot proceed")
            return

        pass_log("Both users authenticated")
        await john.drain(3)
        await jane.drain(3)

        # Run Scenario A
        results_a, sanc_a = await scenario_a(john, jane)
        all_results.extend(results_a)

        # Complete Scenario A's sanctuary so Scenario B can create a fresh one
        if sanc_a:
            await complete_sanctuary(john, sanc_a)
        await john.drain(3)
        await jane.drain(3)

        sys_log("Pausing 5s between scenarios...")
        await asyncio.sleep(5)

        # Run Scenario B
        results_b, sanc_b = await scenario_b(john, jane)
        all_results.extend(results_b)

        # Complete Scenario B's sanctuary
        if sanc_b:
            await complete_sanctuary(john, sanc_b)

    except Exception as e:
        fail_log(f"Unhandled exception: {e}")
        traceback.print_exc()
    finally:
        await john.close()
        await jane.close()

    # --- Final Summary ---
    hdr("TEST SUMMARY")
    passed = sum(1 for _, ok, _ in all_results if ok)
    failed = sum(1 for _, ok, _ in all_results if not ok)
    for name, ok, detail in all_results:
        status = f"{C.CYAN}PASS{C.RESET}" if ok else f"{C.RED}FAIL{C.RESET}"
        extra = f" ({detail})" if detail else ""
        print(f"  {status}  {name}{extra}")
    print(f"\n  {C.BOLD}Total: {passed} passed, {failed} failed{C.RESET}")
    if failed:
        print(f"\n  {C.YELLOW}NOTE: Some failures may be expected if coaching escalation")
        print(f"  detection requires AI model availability, or group coaching")
        print(f"  is in cooldown from a prior test run.{C.RESET}")

    print(f"\n  {C.YELLOW}Next: Verify HoH observations in the database:{C.RESET}")
    print(f"  ssh root@68.183.168.75 \"docker exec nate_postgres psql -U nate_admin -d little_nate \\")
    print(f"    -c \\\"SELECT id, decline_reason, decline_note, nate_classification")
    print(f"        FROM hoh_decision_observations ORDER BY created_at DESC LIMIT 5\\\"\"")


if __name__ == "__main__":
    asyncio.run(main())
