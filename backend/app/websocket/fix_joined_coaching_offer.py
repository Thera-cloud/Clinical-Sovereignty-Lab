#!/usr/bin/env python3
"""
Fix: Send Coaching Offer When New Member JOINS During Active Coaching
======================================================================
When John joins Family Sanctuary for the FIRST time while Jane is in
private coaching, John should get a coaching offer popup (not just 
go straight to main chat).

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_joined_coaching_offer.py
"""

FILE_PATH = "bridge_server.py"

OLD_JOINED = '''                    if action == "JOINED":
                        # Truly new member
                        await websocket.send(json.dumps({
                            "type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members
                        }))
                        
                        # Notify others
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_member_joined",
                                "member": {"id": member_id, "name": member_name}
                            },
                            exclude_user_id=member_id
                        )
                        
                    elif action in ["RECONNECTED", "REFRESHED"]:'''

NEW_JOINED = '''                    if action == "JOINED":
                        # Truly new member
                        await websocket.send(json.dumps({
                            "type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members
                        }))
                        
                        # Notify others (but skip members in coaching - don't interrupt them)
                        sanctuary_data_joined = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        for other_m in sanctuary_data_joined.get('members', []):
                            if other_m.get('user_id') != member_id and other_m.get('status') != 'IN_COACHING':
                                other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_m.get('user_id'))
                                if other_ws:
                                    try:
                                        await other_ws.send(json.dumps({
                                            "type": "sanctuary_member_joined",
                                            "member": {"id": member_id, "name": member_name}
                                        }))
                                    except:
                                        pass
                        
                        # CHECK IF SOMEONE IS IN COACHING - Offer coaching to new member
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data_joined.get('coaching_sessions', {})
                            
                            # Find who is in coaching
                            in_coaching = []
                            for cs in coaching_sessions.values():
                                if cs.get('status') == 'ACTIVE':
                                    in_coaching.append(cs.get('member_name', 'A family member'))
                            
                            if in_coaching:
                                # Check if new member gets free coaching (yes, first time!)
                                is_free = True  # New member always gets first free
                                cost = 0.00
                                
                                # Send coaching OFFER (popup) to new member
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_offer",
                                    "sanctuary_id": sanctuary_id,
                                    "intervention_id": f"COACH_NEWJOIN_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                    "is_free": is_free,
                                    "cost": cost,
                                    "trigger_member": in_coaching[0],
                                    "message": f"{in_coaching[0]} is receiving private coaching. Would you also like coaching support?"
                                }))
                                print(f">>> [SANCTUARY] Sent coaching offer to new member {member_name}")
                        
                    elif action in ["RECONNECTED", "REFRESHED"]:'''

def apply_fix():
    print("=" * 60)
    print("Fix: Coaching Offer When New Member JOINS During Coaching")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    if "COACH_NEWJOIN_" in content:
        print("⚠️  Fix already applied!")
        return False
    
    if OLD_JOINED not in content:
        print("❌ Could not find the JOINED handler to update.")
        print("   The code structure may have changed.")
        return False
    
    content = content.replace(OLD_JOINED, NEW_JOINED)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix applied!")
    print("")
    print("Now when John JOINS for first time while Jane is in coaching:")
    print("  1. John sees: sanctuary_joined")
    print("  2. John sees: sanctuary_coaching_offer (popup)")
    print("  3. If Accept → John enters coaching")
    print("  4. If Decline → John sees pause screen")
    print("")
    print("ALSO: Members in coaching won't get 'member_joined' notification")
    print("      (no interruption during their session)")
    print("")
    print("NEXT: Restart backend and test")
    return True

if __name__ == "__main__":
    apply_fix()
