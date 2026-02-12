#!/usr/bin/env python3
"""
Fix: Include Message History in ALL Reconnect Scenarios
========================================================
Messages are stored in sanctuary but not sent to Flutter on:
- RECONNECTED (page refresh)
- REFRESHED (same as reconnected)
- RETURNED (after exit)
- REJOINED (after exit)

This fix updates ALL these handlers to include message history.

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
Usage: python3 fix_message_history_all.py
"""

FILE_PATH = "bridge_server.py"

def apply_fix():
    print("=" * 60)
    print("Fix: Message History on ALL Reconnect Scenarios")
    print("=" * 60)
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add message history to RECONNECTED/REFRESHED response
    # =========================================================================
    
    # Find the sanctuary_reconnected send that doesn't include messages
    old_reconnected = '''"type": "sanctuary_reconnected",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back, {member_name}!"'''
    
    new_reconnected = '''"type": "sanctuary_reconnected",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": sanctuary_data.get("messages", [])[-50:],
                            "message": f"Welcome back, {member_name}!"'''
    
    if old_reconnected in content and '"messages": sanctuary_data.get("messages"' not in content:
        content = content.replace(old_reconnected, new_reconnected)
        fixes_applied.append("1. Added message history to RECONNECTED/REFRESHED")
    
    # =========================================================================
    # FIX 2: Add message history to RETURNED (sanctuary_rejoined) response
    # =========================================================================
    
    # Pattern 1: sanctuary_rejoined without messages
    old_rejoined1 = '''"type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "message": f"Welcome back to the sanctuary, {member_name}!"'''
    
    new_rejoined1 = '''"type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {}).get("messages", [])[-50:],
                            "message": f"Welcome back to the sanctuary, {member_name}!"'''
    
    if old_rejoined1 in content:
        content = content.replace(old_rejoined1, new_rejoined1)
        fixes_applied.append("2. Added message history to RETURNED (sanctuary_rejoined)")
    
    # =========================================================================
    # FIX 3: Add message history to JOINED response (new member sees history)
    # =========================================================================
    
    old_joined = '''"type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members'''
    
    new_joined = '''"type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": sanctuary_data.get("messages", [])[-50:]'''
    
    if old_joined in content and 'sanctuary_joined' in content:
        # Only replace if it doesn't already have messages
        if '"messages": sanctuary_data.get("messages"' not in content.split('"sanctuary_joined"')[1][:500]:
            content = content.replace(old_joined, new_joined)
            fixes_applied.append("3. Added message history to JOINED")
    
    # =========================================================================
    # WRITE CHANGES
    # =========================================================================
    
    if fixes_applied:
        with open(FILE_PATH, 'w') as f:
            f.write(content)
        
        print("")
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"   • {fix}")
        
        print("")
        print("Backend now sends 'messages' array in:")
        print("  • sanctuary_reconnected")
        print("  • sanctuary_rejoined")
        print("  • sanctuary_joined")
        print("")
        print("NEXT: Restart backend, then test")
    else:
        print("⚠️  No fixes applied - patterns may have changed")
        print("")
        print("Let me check what's there...")
        
        # Debug: show what patterns exist
        if "sanctuary_reconnected" in content:
            idx = content.find('"sanctuary_reconnected"')
            print(f"Found sanctuary_reconnected at position {idx}")
            print(content[idx:idx+500])
    
    return True

if __name__ == "__main__":
    apply_fix()
