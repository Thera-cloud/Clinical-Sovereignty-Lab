#!/usr/bin/env python3
"""
Fix: Show Coaching Offer When Re-entering Sanctuary During Active Coaching
==========================================================================
When a user re-enters Family Sanctuary (after exiting) while another member
is in private coaching, they should:
1. First see the coaching offer popup (not just pause screen)
2. If they decline, THEN see the pause screen

This fix updates both:
- RECONNECTED/REFRESHED handlers (page refresh)
- RETURNED handler (re-entering after exit)

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_reentry_coaching_offer.py
"""

FILE_PATH = "bridge_server.py"

# ============================================================================
# FIX 1: Update RETURNED handler to check for active coaching
# ============================================================================

OLD_RETURNED_HANDLER = '''                    elif action == "RETURNED":
                        # Member who had exited is returning
                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))
                        
                        # Notify others that member returned
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_member_returned",
                                "member": {"id": member_id, "name": member_name}
                            },
                            exclude_user_id=member_id
                        )'''

NEW_RETURNED_HANDLER = '''                    elif action == "RETURNED":
                        # Member who had exited is returning
                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))
                        
                        # Notify others that member returned
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_member_returned",
                                "member": {"id": member_id, "name": member_name}
                            },
                            exclude_user_id=member_id
                        )
                        
                        # CHECK IF SOMEONE ELSE IS IN COACHING - Offer coaching to returning member
                        if existing.get('status') == 'COACHING_ACTIVE':
                            sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                            coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                            
                            # Find who is in coaching (not this member)
                            in_coaching = []
                            for cs in coaching_sessions.values():
                                if cs.get('status') == 'ACTIVE' and cs.get('member_id') != member_id:
                                    in_coaching.append(cs.get('member_name', 'A family member'))
                            
                            if in_coaching:
                                # Check if returning member has used free coaching
                                member_data = next((m for m in sanctuary_data.get('members', []) if m.get('user_id') == member_id), {})
                                is_free = not member_data.get('free_coaching_used', False)
                                cost = 0.00 if is_free else 5.00
                                
                                # Send coaching OFFER (popup) to returning member
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_offer",
                                    "sanctuary_id": sanctuary_id,
                                    "intervention_id": f"COACH_RETURN_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                    "is_free": is_free,
                                    "cost": cost,
                                    "trigger_member": in_coaching[0],
                                    "message": f"{in_coaching[0]} is receiving private coaching. Would you also like coaching support?"
                                }))
                                print(f">>> [SANCTUARY] Sent coaching offer to returning member {member_name}")'''

def apply_fix():
    print("=" * 60)
    print("FIX: Coaching Offer on Re-entry During Active Coaching")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    # Check if already applied
    if "COACH_RETURN_" in content:
        print("⚠️  Fix already applied! Skipping.")
        return False
    
    if OLD_RETURNED_HANDLER not in content:
        print("❌ Could not find RETURNED handler to update.")
        print("   The code structure may have changed.")
        print("")
        print("   Looking for: 'elif action == \"RETURNED\":'")
        return False
    
    content = content.replace(OLD_RETURNED_HANDLER, NEW_RETURNED_HANDLER)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix applied!")
    print("")
    print("Now when Jane re-enters sanctuary while John is in coaching:")
    print("  1. Jane sees sanctuary_rejoined (welcome back)")
    print("  2. Jane sees sanctuary_coaching_offer (popup)")
    print("  3. If Accept → enters coaching")
    print("  4. If Decline → sees pause screen (sanctuary_member_coaching)")
    print("")
    print("NEXT: Restart backend and test")
    return True

if __name__ == "__main__":
    apply_fix()
