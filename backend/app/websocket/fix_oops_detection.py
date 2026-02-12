#!/usr/bin/env python3
"""
Fix 1: Add "Oops" Detection to Private Coaching
Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_oops_detection.py
"""

import re

FILE_PATH = "bridge_server.py"

# The code to insert BEFORE "# Store user's message"
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

def apply_fix():
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    # Check if already applied
    if "OOPS DETECTION" in content:
        print("⚠️  Fix already applied! Skipping.")
        return False
    
    # Find the target line
    target = "                # Store user's message"
    if target not in content:
        print("❌ Could not find target line: '# Store user's message'")
        print("   Please apply manually.")
        return False
    
    # Insert the code before the target
    new_content = content.replace(target, OOPS_DETECTION_CODE + target)
    
    # Write back
    with open(FILE_PATH, 'w') as f:
        f.write(new_content)
    
    print("✅ Fix 1 Applied: Oops Detection added to bridge_server.py")
    print("   Location: Before '# Store user's message' in sanctuary_coaching_message handler")
    return True

if __name__ == "__main__":
    apply_fix()
