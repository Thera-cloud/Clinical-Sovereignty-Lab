#!/usr/bin/env python3
"""
Fix 3: Proper Reconnect Logic for Coaching
==========================================
When someone reconnects:
- If THEY are the one in coaching → resume their coaching session
- If SOMEONE ELSE is in coaching → show them the pause screen

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_coaching_reconnect.py
"""

FILE_PATH = "bridge_server.py"

# We need to REPLACE the pause check we added with a smarter version
OLD_PAUSE_CHECK = '''
                        # CHECK IF SANCTUARY IS PAUSED DUE TO COACHING
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data.get('coaching_sessions', {})
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

NEW_PAUSE_CHECK = '''
                        # CHECK IF SANCTUARY IS PAUSED DUE TO COACHING
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

def apply_fix():
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    # Check if old version exists
    if OLD_PAUSE_CHECK not in content:
        if "sanctuary_coaching_resumed" in content:
            print("⚠️  Fix 3 already applied! Skipping.")
            return False
        else:
            print("❌ Could not find the pause check code to replace.")
            print("   You may need to apply Fix 2 first, or apply manually.")
            return False
    
    # Replace
    content = content.replace(OLD_PAUSE_CHECK, NEW_PAUSE_CHECK)
    
    with open(FILE_PATH, 'w') as f:
        f.write(content)
    
    print("✅ Fix 3 Applied: Smart coaching reconnect logic")
    print("   - If YOU are in coaching → resume your session")
    print("   - If SOMEONE ELSE is in coaching → see pause screen")
    return True

if __name__ == "__main__":
    apply_fix()
