#!/usr/bin/env python3
"""
FAMILY SANCTUARY FIXES
======================
Applies both fixes for:
1. "Oops" detection - early exit from private coaching
2. Pause status on reconnect - show pause screen when joining while someone is in coaching

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 apply_sanctuary_fixes.py
"""

import os
import shutil
from datetime import datetime

FILE_PATH = "bridge_server.py"
BACKUP_PATH = f"bridge_server.py.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# ============================================================================
# FIX 1: OOPS DETECTION
# ============================================================================
OOPS_DETECTION_CODE = '''
                # ===== OOPS DETECTION (First message only) =====
                coaching_session_check = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                is_first_message = len(coaching_session_check.get("messages", [])) <= 1
                
                oops_keywords = ["oops", "wrong", "mistake", "didn't mean", "accident", "back", "exit", "leave", "return", "go back"]
                is_oops = is_first_message and any(kw in message_content.lower() for kw in oops_keywords)
                
                if is_oops:
                    sanctuary_engine.end_coaching_session(sanctuary_id, member_id)
                    
                    await websocket.send(json.dumps({
                        "type": "sanctuary_coaching_completed",
                        "sanctuary_id": sanctuary_id,
                        "message": "No problem! Heading back to the sanctuary.",
                        "was_early_exit": True
                    }))
                    
                    await sanctuary_engine.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_member_returned",
                            "member_id": member_id,
                            "member_name": member_name,
                            "message": f"{member_name} has returned to the sanctuary."
                        }
                    )
                    
                    active_coaching = sanctuary_engine.get_active_coaching_sessions(sanctuary_id)
                    if not active_coaching:
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_resumed",
                                "message": "Everyone is back. The sanctuary conversation can continue. 💙"
                            }
                        )
                    continue
                # ===== END OOPS DETECTION =====

'''

# ============================================================================
# FIX 2: PAUSE STATUS ON RECONNECT
# ============================================================================
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

def apply_fix_1(content):
    """Add Oops Detection"""
    if "OOPS DETECTION" in content:
        print("   ⚠️  Fix 1 already applied, skipping")
        return content, False
    
    target = "                # Store user's message"
    if target not in content:
        print("   ❌ Fix 1 FAILED: Could not find '# Store user's message'")
        return content, False
    
    content = content.replace(target, OOPS_DETECTION_CODE + target)
    print("   ✅ Fix 1 Applied: Oops Detection")
    return content, True

def apply_fix_2(content):
    """Add Pause Status on Reconnect"""
    if "CHECK IF SANCTUARY IS PAUSED DUE TO COACHING" in content:
        print("   ⚠️  Fix 2 already applied, skipping")
        return content, False
    
    # Find RECONNECTED section
    reconnect_start = content.find('elif action in ["RECONNECTED", "REFRESHED"]:')
    if reconnect_start == -1:
        print("   ❌ Fix 2 FAILED: Could not find RECONNECTED section")
        return content, False
    
    target = '''                            "message": f"Welcome back, {member_name}!"
                        }))'''
    
    target_pos = content.find(target, reconnect_start)
    if target_pos == -1:
        print("   ❌ Fix 2 FAILED: Could not find 'Welcome back' in RECONNECTED section")
        return content, False
    
    insert_pos = target_pos + len(target)
    content = content[:insert_pos] + PAUSE_CHECK_CODE + content[insert_pos:]
    print("   ✅ Fix 2 Applied: Pause Status on Reconnect")
    return content, True

def main():
    print("=" * 60)
    print("FAMILY SANCTUARY FIXES")
    print("=" * 60)
    
    if not os.path.exists(FILE_PATH):
        print(f"❌ File not found: {FILE_PATH}")
        print("   Make sure you're running from backend/app/websocket/")
        return
    
    # Backup
    shutil.copy(FILE_PATH, BACKUP_PATH)
    print(f"📦 Backup created: {BACKUP_PATH}")
    
    # Read file
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    print("\nApplying fixes...")
    
    # Apply fixes
    content, fix1_applied = apply_fix_1(content)
    content, fix2_applied = apply_fix_2(content)
    
    if fix1_applied or fix2_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        print("\n✅ Changes written to bridge_server.py")
    else:
        print("\n⚠️  No changes made (fixes already applied or failed)")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    print("1. Restart backend:")
    print("   cd ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket")
    print("   DATA_DIR=./data python3 bridge_server.py")
    print("")
    print("2. Test Fix 1 (Oops Detection):")
    print("   - Enter private coaching")
    print("   - Type 'oops' or 'wrong place' as first message")
    print("   - Should immediately return to sanctuary")
    print("")
    print("3. Test Fix 2 (Pause on Reconnect):")
    print("   - Have User 1 (John) enter private coaching")
    print("   - Have User 2 (phone) open/refresh the sanctuary")
    print("   - Should see pause overlay with message")
    print("=" * 60)

if __name__ == "__main__":
    main()
