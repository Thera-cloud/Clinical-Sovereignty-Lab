#!/usr/bin/env python3
"""
Fix: Enforce 5-Step Coaching Limit with $5 Continuation Option
===============================================================
After 5 coaching messages:
1. User CANNOT send more messages without paying $5
2. Backend sends "coaching_limit_reached" with options:
   - Pay $5 to continue (5 more steps)
   - Get assisted response ($3) and return
   - Return to sanctuary without assisted response

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_coaching_5_step_limit.py
"""

FILE_PATH = "bridge_server.py"

# Find the current coaching message handler and add limit check
OLD_COACHING_MESSAGE = '''                # Increment attempt
                coaching_session["attempt_number"] = coaching_session.get("attempt_number", 0) + 1
                attempt_number = coaching_session["attempt_number"]
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate Little Nate's response
                result = await cortex.process_private_coaching('''

NEW_COACHING_MESSAGE = '''                # Increment attempt
                coaching_session["attempt_number"] = coaching_session.get("attempt_number", 0) + 1
                attempt_number = coaching_session["attempt_number"]
                
                # Get max steps (default 5, can be extended with $5 payment)
                max_steps = coaching_session.get("max_steps", 5)
                
                # CHECK IF LIMIT REACHED (step 6+ without extension)
                if attempt_number > max_steps:
                    # User has exceeded their allowed steps - send limit reached message
                    is_deescalated = coaching_session.get("is_deescalated", False)
                    
                    await websocket.send(json.dumps({
                        "type": "sanctuary_coaching_limit_reached",
                        "sanctuary_id": sanctuary_id,
                        "attempt_number": attempt_number,
                        "max_steps": max_steps,
                        "is_deescalated": is_deescalated,
                        "options": {
                            "continue_cost": 5.00,
                            "assisted_response_cost": 3.00
                        },
                        "message": f"You've completed {max_steps} coaching exchanges. Would you like to continue or return to your family?"
                    }))
                    
                    # Decrement the attempt since we're not processing this message
                    coaching_session["attempt_number"] = max_steps
                    sanctuary_engine.update_coaching_session(
                        sanctuary_id=sanctuary_id,
                        member_id=member_id,
                        updates={"attempt_number": max_steps}
                    )
                    continue
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate Little Nate's response
                result = await cortex.process_private_coaching('''

# Add handler for extending coaching session
EXTEND_HANDLER = '''
            elif t == "sanctuary_coaching_extend":
                """
                Member pays $5 to continue coaching for 5 more steps
                """
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                if not coaching_session or coaching_session.get('status') != 'ACTIVE':
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Charge $5 for extension
                charge_result = await sanctuary_engine.charge_coaching(
                    sanctuary_id=sanctuary_id,
                    intervention_id=coaching_session.get("intervention_id", ""),
                    member_id=member_id,
                    amount=5.00
                )
                
                if not charge_result[0]:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Payment failed. Please try again."
                    }))
                    continue
                
                # Extend the session by 5 more steps
                current_max = coaching_session.get("max_steps", 5)
                new_max = current_max + 5
                
                sanctuary_engine.update_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    updates={"max_steps": new_max}
                )
                
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_extended",
                    "sanctuary_id": sanctuary_id,
                    "new_max_steps": new_max,
                    "charge_amount": 5.00,
                    "message": f"Your coaching session has been extended! You now have {new_max - coaching_session.get('attempt_number', 0)} more exchanges available. 💙"
                }))
                
                print(f">>> [COACHING] Extended session for {member_name} to {new_max} steps (+$5)")

'''

# Insert marker for extend handler
EXTEND_INSERT_MARKER = '''            elif t == "sanctuary_coaching_complete":'''

def apply_fix():
    print("=" * 60)
    print("Fix: 5-Step Coaching Limit with $5 Continuation")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # Fix 1: Add limit check in coaching_message handler
    if "sanctuary_coaching_limit_reached" not in content:
        if OLD_COACHING_MESSAGE in content:
            content = content.replace(OLD_COACHING_MESSAGE, NEW_COACHING_MESSAGE)
            fixes_applied.append("1. Added 5-step limit check in coaching_message")
        else:
            print("   ⚠️  Could not find coaching_message handler to update")
    else:
        print("   ℹ️  Limit check already exists")
    
    # Fix 2: Add extend handler
    if "sanctuary_coaching_extend" not in content:
        if EXTEND_INSERT_MARKER in content:
            content = content.replace(EXTEND_INSERT_MARKER, EXTEND_HANDLER + EXTEND_INSERT_MARKER)
            fixes_applied.append("2. Added sanctuary_coaching_extend handler")
        else:
            print("   ⚠️  Could not find insertion point for extend handler")
    else:
        print("   ℹ️  Extend handler already exists")
    
    if fixes_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        
        print("")
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"   • {fix}")
        
        print("")
        print("BACKEND FLOW NOW:")
        print("  Step 1-5: Normal coaching exchanges")
        print("  Step 6+: Backend sends 'sanctuary_coaching_limit_reached'")
        print("           with options to continue ($5) or return")
        print("")
        print("NEW WEBSOCKET MESSAGE TYPES:")
        print("  • sanctuary_coaching_limit_reached (server → client)")
        print("  • sanctuary_coaching_extend (client → server)")
        print("  • sanctuary_coaching_extended (server → client)")
        print("")
        print("NEXT: Apply Flutter fix for handling these new message types")
    else:
        print("⚠️  No fixes applied")
    
    return True

if __name__ == "__main__":
    apply_fix()
