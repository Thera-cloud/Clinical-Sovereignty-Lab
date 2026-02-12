#!/usr/bin/env python3
"""
Fix: Coaching Offer on RECONNECTED + Message History on RETURNED
=================================================================
Issues:
1. When Jane RECONNECTS while John is in coaching, she only gets pause screen
   (should get coaching OFFER popup first)
2. When Jane RETURNS after exit, she doesn't get message history
3. sanctuary_member_returned sometimes has null member data

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_reconnect_coaching_offer.py
"""

FILE_PATH = "bridge_server.py"

# =============================================================================
# FIX 1: Update RECONNECTED to send coaching OFFER (not just pause)
# =============================================================================

OLD_RECONNECT_PAUSE = '''                        # CHECK IF SANCTUARY IS PAUSED DUE TO COACHING
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                            
                            # Check if THIS member is the one in coaching
                            my_coaching = coaching_sessions.get(member_id, {})
                            if my_coaching.get('status') == 'ACTIVE':
                                # Resume their coaching session!
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_resumed",
                                    "sanctuary_id": sanctuary_id,
                                    "coaching_session": my_coaching,
                                    "message": "Welcome back to your coaching session."
                                }))
                            else:
                                # Someone ELSE is in coaching - show pause
                                in_coaching_names = []
                                for cs in coaching_sessions.values():
                                    if cs.get('status') == 'ACTIVE':
                                        in_coaching_names.append(cs.get('member_name', 'A family member'))
                                
                                if in_coaching_names:
                                    await websocket.send(json.dumps({
                                        "type": "sanctuary_member_coaching",
                                        "member_name": in_coaching_names[0],
                                        "message": f"{in_coaching_names[0]} is receiving private support from Little Nate. The sanctuary is paused."
                                    }))'''

NEW_RECONNECT_OFFER = '''                        # CHECK IF SANCTUARY IS PAUSED DUE TO COACHING
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                            
                            # Check if THIS member is the one in coaching
                            my_coaching = coaching_sessions.get(member_id, {})
                            if my_coaching.get('status') == 'ACTIVE':
                                # Resume their coaching session!
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_resumed",
                                    "sanctuary_id": sanctuary_id,
                                    "coaching_session": my_coaching,
                                    "message": "Welcome back to your coaching session."
                                }))
                            else:
                                # Someone ELSE is in coaching - send coaching OFFER (not just pause)
                                in_coaching_names = []
                                for cs in coaching_sessions.values():
                                    if cs.get('status') == 'ACTIVE':
                                        in_coaching_names.append(cs.get('member_name', 'A family member'))
                                
                                if in_coaching_names:
                                    # Check if this member has used free coaching
                                    member_data = next((m for m in sanctuary_data.get('members', []) if m.get('user_id') == member_id), {})
                                    is_free = not member_data.get('free_coaching_used', False)
                                    cost = 0.00 if is_free else 5.00
                                    
                                    # Send coaching OFFER popup (not just pause)
                                    await websocket.send(json.dumps({
                                        "type": "sanctuary_coaching_offer",
                                        "sanctuary_id": sanctuary_id,
                                        "intervention_id": f"COACH_RECONNECT_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                        "is_free": is_free,
                                        "cost": cost,
                                        "trigger_member": in_coaching_names[0],
                                        "message": f"{in_coaching_names[0]} is receiving private coaching. Would you also like coaching support?"
                                    }))
                                    print(f">>> [SANCTUARY] Sent coaching offer to reconnecting member {member_name}")'''

# =============================================================================
# FIX 2: Update RETURNED to include message history
# =============================================================================

OLD_RETURNED_REJOINED = '''                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))'''

NEW_RETURNED_REJOINED = '''                        # Get message history for returning member
                        sanctuary_data_ret = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        message_history = sanctuary_data_ret.get("messages", [])[-50:]  # Last 50 messages
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": message_history,
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))'''

# =============================================================================
# FIX 3: Update sanctuary_member_returned broadcast to include member data properly
# =============================================================================

OLD_MEMBER_RETURNED_BROADCAST = '''                            "type": "sanctuary_member_returned",
                            "member": {"id": member_id, "name": member_name}'''

NEW_MEMBER_RETURNED_BROADCAST = '''                            "type": "sanctuary_member_returned",
                            "member": {"id": member_id, "name": member_name},
                            "member_id": member_id,
                            "member_name": member_name,
                            "message": f"{member_name} has returned to the sanctuary."'''


def apply_fix():
    print("=" * 60)
    print("Fix: Coaching Offer on RECONNECT + History on RETURNED")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # Fix 1: Update RECONNECTED to send coaching offer
    if "COACH_RECONNECT_" not in content:
        if OLD_RECONNECT_PAUSE in content:
            content = content.replace(OLD_RECONNECT_PAUSE, NEW_RECONNECT_OFFER)
            fixes_applied.append("1. RECONNECTED now sends coaching OFFER (not just pause)")
        else:
            print("   ⚠️  Could not find RECONNECTED pause handler")
    else:
        print("   ℹ️  RECONNECTED coaching offer already exists")
    
    # Fix 2: Update RETURNED to include message history
    if OLD_RETURNED_REJOINED in content and '"messages": message_history' not in content:
        content = content.replace(OLD_RETURNED_REJOINED, NEW_RETURNED_REJOINED)
        fixes_applied.append("2. RETURNED now includes message history")
    else:
        print("   ℹ️  RETURNED message history may already exist or pattern not found")
    
    # Fix 3: Update member_returned broadcast
    old_count = content.count(OLD_MEMBER_RETURNED_BROADCAST)
    if old_count > 0 and '"member_name": member_name,' not in content:
        content = content.replace(OLD_MEMBER_RETURNED_BROADCAST, NEW_MEMBER_RETURNED_BROADCAST)
        fixes_applied.append(f"3. Fixed sanctuary_member_returned broadcast ({old_count} occurrences)")
    
    if fixes_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        
        print("")
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"   • {fix}")
        
        print("")
        print("FLOW NOW:")
        print("  Jane RECONNECTS while John in coaching:")
        print("    → sanctuary_reconnected (with history)")
        print("    → sanctuary_coaching_offer (popup!)")
        print("    → If decline → sanctuary_member_coaching (pause)")
        print("")
        print("  Jane RETURNS after exit:")
        print("    → sanctuary_rejoined (WITH message history)")
        print("    → sanctuary_coaching_offer (if someone in coaching)")
        print("")
        print("NEXT: Restart backend")
    else:
        print("⚠️  No fixes applied - patterns may have changed")
    
    return True

if __name__ == "__main__":
    apply_fix()
