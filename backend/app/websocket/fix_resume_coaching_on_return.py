#!/usr/bin/env python3
"""
Fix: Preserve and Resume Coaching Session on Exit/Return
=========================================================
Problem: 
- Client1 is in private coaching, presses "Exit Sanctuary"
- Client1 re-enters Family Sanctuary
- Instead of resuming coaching, Client1 goes to main chat
- Client2 is stuck on pause screen

Solution:
- When Client1 RETURNS, check if they have an active coaching session
- If yes, send sanctuary_coaching_resumed (not coaching_offer)
- This resumes their session instead of starting fresh

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_resume_coaching_on_return.py
"""

FILE_PATH = "bridge_server.py"

# Current RETURNED handler sends coaching OFFER to returning member
# We need to check if they were IN coaching and resume that instead

OLD_RETURNED = '''                    elif action == "RETURNED":
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

NEW_RETURNED = '''                    elif action == "RETURNED":
                        # Member who had exited is returning
                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))
                        
                        # Notify others that member returned (skip those in coaching)
                        sanctuary_data_ret = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        for other_m in sanctuary_data_ret.get('members', []):
                            if other_m.get('user_id') != member_id and other_m.get('status') != 'IN_COACHING':
                                other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_m.get('user_id'))
                                if other_ws:
                                    try:
                                        await other_ws.send(json.dumps({
                                            "type": "sanctuary_member_returned",
                                            "member": {"id": member_id, "name": member_name}
                                        }))
                                    except:
                                        pass
                        
                        # CHECK IF THIS MEMBER HAS AN ACTIVE COACHING SESSION TO RESUME
                        coaching_sessions = sanctuary_data_ret.get('coaching_sessions', {})
                        my_coaching = coaching_sessions.get(member_id, {})
                        
                        if my_coaching.get('status') == 'ACTIVE':
                            # RESUME their coaching session!
                            print(f">>> [SANCTUARY] Resuming coaching session for returning member {member_name}")
                            
                            # Restore member status to IN_COACHING
                            member_obj = next((m for m in sanctuary_data_ret.get('members', []) if m.get('user_id') == member_id), None)
                            if member_obj:
                                member_obj['status'] = 'IN_COACHING'
                                sanctuary_engine._save()
                            
                            await websocket.send(json.dumps({
                                "type": "sanctuary_coaching_resumed",
                                "sanctuary_id": sanctuary_id,
                                "coaching_session": my_coaching,
                                "message": "Welcome back! Let's continue our coaching conversation."
                            }))
                        
                        # ELSE CHECK IF SOMEONE ELSE IS IN COACHING - Offer coaching to returning member
                        elif existing.get('status') == 'COACHING_ACTIVE':
                            # Find who is in coaching (not this member)
                            in_coaching = []
                            for cs in coaching_sessions.values():
                                if cs.get('status') == 'ACTIVE' and cs.get('member_id') != member_id:
                                    in_coaching.append(cs.get('member_name', 'A family member'))
                            
                            if in_coaching:
                                # Check if returning member has used free coaching
                                member_data = next((m for m in sanctuary_data_ret.get('members', []) if m.get('user_id') == member_id), {})
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
    print("Fix: Resume Coaching Session on Return (not just offer)")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    if "RESUME their coaching session!" in content:
        print("⚠️  Fix already applied!")
        return False
    
    if OLD_RETURNED not in content:
        print("❌ Could not find the RETURNED handler to update.")
        print("   The code structure may have changed.")
        return False
    
    content = content.replace(OLD_RETURNED, NEW_RETURNED)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix applied!")
    print("")
    print("Now when Client1 returns after exiting while in coaching:")
    print("  1. Check: Does Client1 have active coaching session?")
    print("  2. YES → sanctuary_coaching_resumed (resume session)")
    print("  3. NO, but someone else in coaching → sanctuary_coaching_offer")
    print("  4. NO coaching at all → normal sanctuary")
    print("")
    print("NEXT: Restart backend and test")
    return True

if __name__ == "__main__":
    apply_fix()
