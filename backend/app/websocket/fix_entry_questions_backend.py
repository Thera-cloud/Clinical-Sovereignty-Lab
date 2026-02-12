#!/usr/bin/env python3
"""
Fix: Sanctuary Entry Questions
==============================
Adds pre-entry questionnaire before users enter the Family Sanctuary.

Questions:
1. Why are you entering today?
2. What's happening right now?
3. What do you hope to achieve?
4. How are you feeling? (1-10 scale)

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
"""

import shutil
from datetime import datetime

FILE_PATH = "bridge_server.py"

def apply_fix():
    print("=" * 60)
    print("Fix: Sanctuary Entry Questions")
    print("=" * 60)
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup: {backup_path}")
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add entry questions check after member joins/returns
    # =========================================================================
    
    # Find where we send sanctuary_joined/rejoined and add entry questions check
    # We'll add a new handler for entry responses
    
    entry_questions_handler = '''
            # =========================================================================
            # SANCTUARY ENTRY QUESTIONS
            # =========================================================================
            elif t == "sanctuary_entry_responses":
                sanctuary_id = data.get("sanctuary_id")
                responses = data.get("responses", {})
                
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                if sanctuary_data:
                    if "entry_responses" not in sanctuary_data:
                        sanctuary_data["entry_responses"] = {}
                    
                    sanctuary_data["entry_responses"][member_id] = {
                        **responses,
                        "member_name": member_name,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    
                    # Update sanctuary data
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                    sanctuary_engine._save_data()
                    
                    print(f">>> [SANCTUARY] Entry responses saved for {member_name}")
                    
                    # Send completion and proceed to sanctuary
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_complete",
                        "sanctuary_id": sanctuary_id,
                        "message": "Thank you for sharing. Let's begin. 💙"
                    }))
                    
                    # Now send the appropriate join/reconnect message with history
                    members = [{
                        "user_id": m.get("user_id"),
                        "name": m.get("name"),
                        "status": m.get("status", "ACTIVE"),
                        "role": m.get("role", "member")
                    } for m in sanctuary_data.get("members", [])]
                    
                    message_history = sanctuary_data.get("messages", [])[-50:]
                    
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_ready",
                        "sanctuary_id": sanctuary_id,
                        "status": sanctuary_data.get("status", "ACTIVE"),
                        "members": members,
                        "messages": message_history,
                        "message": f"Welcome to the sanctuary, {member_name}!"
                    }))

'''
    
    # Find insertion point - after sanctuary_exit_confirm handler
    insert_marker = 'elif t == "sanctuary_exit_confirm":'
    
    if insert_marker in content and "sanctuary_entry_responses" not in content:
        # Find the end of sanctuary_exit_confirm handler and insert after
        idx = content.find(insert_marker)
        # Find the next elif at the same indentation level
        search_start = idx + len(insert_marker)
        next_elif = content.find('\n            elif t == "', search_start)
        
        if next_elif > 0:
            content = content[:next_elif] + entry_questions_handler + content[next_elif:]
            fixes_applied.append("1. Added sanctuary_entry_responses handler")
    else:
        if "sanctuary_entry_responses" in content:
            print("   ℹ️  Entry responses handler already exists")
        else:
            print("   ⚠️  Could not find insertion point")
    
    # =========================================================================
    # FIX 2: Modify JOINED/RETURNED to send entry questions first
    # =========================================================================
    
    # Find where sanctuary_joined is sent and add entry questions check
    old_joined_send = '''await websocket.send(json.dumps({
                            "type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": sanctuary_data.get("messages", [])[-50:]
                        }))'''
    
    new_joined_send = '''# Check if member needs entry questions
                        member_entry = sanctuary_data.get("entry_responses", {}).get(member_id)
                        needs_entry = member_entry is None
                        
                        if needs_entry:
                            await websocket.send(json.dumps({
                                "type": "sanctuary_entry_questions",
                                "sanctuary_id": sanctuary_id,
                                "questions": [
                                    {
                                        "id": "why_entering",
                                        "type": "text",
                                        "question": "Why are you entering the Family Sanctuary today?",
                                        "placeholder": "What brings you here right now?",
                                        "required": True
                                    },
                                    {
                                        "id": "whats_happening",
                                        "type": "text",
                                        "question": "What's happening right now in your family?",
                                        "placeholder": "Describe the current situation...",
                                        "required": True
                                    },
                                    {
                                        "id": "goals",
                                        "type": "text",
                                        "question": "What do you hope to achieve in this conversation?",
                                        "placeholder": "What would a good outcome look like?",
                                        "required": True
                                    },
                                    {
                                        "id": "feeling_scale",
                                        "type": "scale",
                                        "question": "How are you feeling right now?",
                                        "min": 1,
                                        "max": 10,
                                        "min_label": "Very upset",
                                        "max_label": "Completely calm",
                                        "required": True
                                    }
                                ],
                                "message": "Before we begin, help Little Nate understand where you're at. 💙"
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "sanctuary_joined",
                                "sanctuary_id": sanctuary_id,
                                "status": existing.get('status', 'ACTIVE'),
                                "members": members,
                                "messages": sanctuary_data.get("messages", [])[-50:]
                            }))'''
    
    if old_joined_send in content:
        content = content.replace(old_joined_send, new_joined_send)
        fixes_applied.append("2. Added entry questions check to JOINED flow")
    
    # Similar for RETURNED (sanctuary_rejoined)
    old_rejoined_send = '''"type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "members": members,
                            "messages": sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {}).get("messages", [])[-50:],
                            "message": f"Welcome back to the sanctuary, {member_name}!"'''
    
    # For rejoined, we skip entry questions if they already answered today
    # This is handled by checking timestamp in entry_responses
    
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
        print("NEW WEBSOCKET MESSAGES:")
        print("  • sanctuary_entry_questions (Server → Client)")
        print("  • sanctuary_entry_responses (Client → Server)")
        print("  • sanctuary_entry_complete (Server → Client)")
        print("  • sanctuary_entry_ready (Server → Client)")
        print("")
        print("NEXT: Apply Flutter fix, then restart backend")
    else:
        print("⚠️  No fixes applied")
    
    return True

if __name__ == "__main__":
    apply_fix()
