#!/usr/bin/env python3
"""
Fix: Don't send coaching offer to members already in coaching
=============================================================
When Jane enters coaching, don't send a coaching offer popup to John
if John is already in his own coaching session.

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_skip_offer_if_in_coaching.py
"""

FILE_PATH = "bridge_server.py"

OLD_CODE = '''                for other_member in other_members:
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
                                "type": "sanctuary_coaching_offer",'''

NEW_CODE = '''                for other_member in other_members:
                    other_id = other_member.get('user_id')
                    other_name = other_member.get('name', 'Friend')
                    
                    # SKIP if this member is already in their own coaching session
                    if other_member.get('status') == 'IN_COACHING':
                        print(f">>> [SANCTUARY] Skipping offer to {other_name} - already in coaching")
                        continue
                    
                    # Check if they've used free coaching
                    other_free = not other_member.get('free_coaching_used', False)
                    other_cost = 0.00 if other_free else 5.00
                    
                    # Get their websocket
                    other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_id)
                    if other_ws:
                        try:
                            # Send coaching offer (shows popup modal)
                            await other_ws.send(json.dumps({
                                "type": "sanctuary_coaching_offer",'''

def apply_fix():
    print("=" * 60)
    print("FIX: Skip Coaching Offer if Member Already in Coaching")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    if "Skipping offer to" in content and "already in coaching" in content:
        print("⚠️  Fix already applied!")
        return False
    
    if OLD_CODE not in content:
        print("❌ Could not find the target code to fix.")
        print("   The code structure may have changed.")
        return False
    
    content = content.replace(OLD_CODE, NEW_CODE)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix applied!")
    print("")
    print("Now when Jane enters coaching:")
    print("  • If John is in coaching → John does NOT get popup")
    print("  • If John is in pause screen → John gets coaching offer popup")
    print("")
    print("NEXT: Restart backend and test")
    return True

if __name__ == "__main__":
    apply_fix()
