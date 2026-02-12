#!/usr/bin/env python3
"""
Fix 2: Send Pause Status on Reconnect
Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_pause_on_reconnect.py
"""

FILE_PATH = "bridge_server.py"

# The code to insert AFTER the sanctuary_reconnected send (after the closing }))
PAUSE_CHECK_CODE = '''
                        
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
                                }))
'''

def apply_fix():
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    # Check if already applied
    if "CHECK IF SANCTUARY IS PAUSED DUE TO COACHING" in content:
        print("⚠️  Fix already applied! Skipping.")
        return False
    
    # Find the target - the line after "Welcome back, {member_name}!"
    # We need to find this specific pattern in the RECONNECTED block
    target = '''                            "message": f"Welcome back, {member_name}!"
                        }))'''
    
    if target not in content:
        print("❌ Could not find target pattern.")
        print("   Looking for: 'Welcome back, {member_name}!' followed by '}))'")
        print("   Please apply manually.")
        return False
    
    # Insert after the target (but we need to be careful - there are multiple similar patterns)
    # We specifically want the one in the RECONNECTED/REFRESHED block
    
    # Find the section with "elif action in ["RECONNECTED", "REFRESHED"]:"
    reconnect_section_start = content.find('elif action in ["RECONNECTED", "REFRESHED"]:')
    if reconnect_section_start == -1:
        print("❌ Could not find RECONNECTED/REFRESHED section")
        return False
    
    # Find the target AFTER this section start
    target_pos = content.find(target, reconnect_section_start)
    if target_pos == -1:
        print("❌ Could not find 'Welcome back' message in RECONNECTED section")
        return False
    
    # Insert after the target
    insert_pos = target_pos + len(target)
    new_content = content[:insert_pos] + PAUSE_CHECK_CODE + content[insert_pos:]
    
    # Write back
    with open(FILE_PATH, 'w') as f:
        f.write(new_content)
    
    print("✅ Fix 2 Applied: Pause status check added on reconnect")
    print("   Location: After 'Welcome back' message in RECONNECTED handler")
    return True

if __name__ == "__main__":
    apply_fix()
