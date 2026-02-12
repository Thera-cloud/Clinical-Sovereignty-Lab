#!/usr/bin/env python3
"""
Fix: Send Coaching Offer to Other Members When One Enters Coaching
===================================================================
When John enters private coaching, Jane should see a popup offering her
coaching too (not just the pause screen).

The flow should be:
1. John accepts coaching → enters private coaching
2. Backend sends to Jane: "sanctuary_coaching_offer" (shows modal popup)
3. Jane can Accept (enter coaching) or Decline (see pause screen)

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_send_coaching_offer_to_others.py
"""

FILE_PATH = "bridge_server.py"

# Find the current broadcast that just sends pause notification
OLD_BROADCAST = '''                # Notify other members that this person is in coaching
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_member_coaching",
                        "member_id": member_id,
                        "member_name": member_name,
                        "message": f"{member_name} is receiving private support from Little Nate. The sanctuary is paused."
                    },
                    exclude_user_id=member_id
                )'''

# Replace with code that sends coaching OFFER to each member (with their pricing)
NEW_BROADCAST = '''                # Notify other members and OFFER them coaching too
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                other_members = [m for m in sanctuary_data.get('members', []) if m.get('user_id') != member_id]
                
                for other_member in other_members:
                    other_id = other_member.get('user_id')
                    other_name = other_member.get('name', 'Friend')
                    
                    # Check if they've used free coaching
                    other_free = not other_member.get('free_coaching_used', False)
                    other_cost = 0.00 if other_free else 5.00
                    
                    # Get their websocket
                    other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_id)
                    if other_ws:
                        try:
                            # Send coaching offer (shows popup modal)
                            await other_ws.send(json.dumps({
                                "type": "sanctuary_coaching_offer",
                                "sanctuary_id": sanctuary_id,
                                "intervention_id": f"COACH_OFFER_{other_id}_{int(datetime.now().timestamp())}",
                                "is_free": other_free,
                                "cost": other_cost,
                                "trigger_member": member_name,
                                "message": f"{member_name} is receiving private coaching. Would you also like coaching support?"
                            }))
                            print(f">>> [SANCTUARY] Sent coaching offer to {other_name} (free={other_free})")
                        except Exception as e:
                            print(f">>> [SANCTUARY] Failed to send offer to {other_name}: {e}")
                            # Fall back to just pause notification
                            try:
                                await other_ws.send(json.dumps({
                                    "type": "sanctuary_member_coaching",
                                    "member_id": member_id,
                                    "member_name": member_name,
                                    "message": f"{member_name} is receiving private support from Little Nate. The sanctuary is paused."
                                }))
                            except:
                                pass'''

# Also need to add a handler for when someone DECLINES the coaching offer
DECLINE_HANDLER = '''
            elif t == "sanctuary_coaching_decline":
                """
                Member declines coaching offer - show them the pause screen instead
                """
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                
                # Find who IS in coaching to show in the pause message
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                in_coaching = []
                for cs in coaching_sessions.values():
                    if cs.get('status') == 'ACTIVE':
                        in_coaching.append(cs.get('member_name', 'A family member'))
                
                coaching_member = in_coaching[0] if in_coaching else 'A family member'
                
                # Send the pause notification
                await websocket.send(json.dumps({
                    "type": "sanctuary_member_coaching",
                    "member_name": coaching_member,
                    "message": f"{coaching_member} is receiving private support from Little Nate. The sanctuary is paused."
                }))
                
                print(f">>> [SANCTUARY] {current_profile.get('name')} declined coaching, showing pause screen")

'''

# Search marker for where to insert decline handler
DECLINE_INSERT_MARKER = '''            elif t == "sanctuary_request_coach":'''

def apply_fix():
    print("=" * 60)
    print("FIX: Send Coaching Offer to Other Members")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    # Check if already applied
    if "sanctuary_coaching_offer" in content and "COACH_OFFER_" in content:
        print("⚠️  Fix already applied! Skipping.")
        return False
    
    if OLD_BROADCAST not in content:
        print("❌ Could not find the broadcast code to replace.")
        print("   Looking for: 'Notify other members that this person is in coaching'")
        print("")
        print("   Trying alternative search...")
        
        # Try alternative
        alt_search = 'exclude_user_id=member_id\n                )'
        if alt_search in content:
            print("   Found alternative pattern, but manual review recommended.")
        return False
    
    content = content.replace(OLD_BROADCAST, NEW_BROADCAST)
    
    # Also add the decline handler if not present
    if "sanctuary_coaching_decline" not in content:
        if DECLINE_INSERT_MARKER in content:
            content = content.replace(DECLINE_INSERT_MARKER, DECLINE_HANDLER + DECLINE_INSERT_MARKER)
            print("   Also added 'sanctuary_coaching_decline' handler")
        else:
            print("   ⚠️  Could not add decline handler - add manually")
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Backend fix applied!")
    print("")
    print("Now when John enters coaching:")
    print("  → Jane sees popup: 'Would you also like coaching?' with Accept/Decline")
    print("  → If Jane declines, she sees the pause screen")
    print("  → If Jane accepts, she enters her own coaching session")
    print("")
    print("NEXT: Restart backend and test")
    return True

if __name__ == "__main__":
    apply_fix()
