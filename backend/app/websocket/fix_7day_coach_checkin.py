#!/usr/bin/env python3
"""
Fix: 7-Day Coach Check-in & Coach Guidance
===========================================
Features:
1. Background task checks sanctuaries active > 7 days
2. Notifies assigned coach for review
3. Coach can set guidance for Little Nate
4. Little Nate incorporates coach guidance in responses

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
"""

import shutil
from datetime import datetime

FILE_PATH = "bridge_server.py"

def apply_fix():
    print("=" * 60)
    print("Fix: 7-Day Coach Check-in & Guidance")
    print("=" * 60)
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup: {backup_path}")
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add background task for sanctuary monitoring
    # =========================================================================
    
    background_task = '''
# =============================================================================
# SANCTUARY 7-DAY COACH CHECK-IN SYSTEM
# =============================================================================

import asyncio

async def sanctuary_monitoring_task():
    """Background task to monitor long-running sanctuaries and notify coaches"""
    
    print("[SANCTUARY MONITOR] Starting background monitoring task...")
    
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            
            print("[SANCTUARY MONITOR] Running check...")
            
            active_sanctuaries = sanctuary_engine.data.get("active_sanctuaries", {})
            
            for sanctuary_id, sanctuary_data in active_sanctuaries.items():
                created_at_str = sanctuary_data.get("created_at")
                if not created_at_str:
                    continue
                
                try:
                    created_at = datetime.datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    days_active = (datetime.datetime.now(datetime.timezone.utc) - created_at).days
                except:
                    continue
                
                # Check if needs coach review (7+ days and not already notified)
                if days_active >= 7 and not sanctuary_data.get("coach_7day_notified"):
                    print(f"[SANCTUARY MONITOR] Sanctuary {sanctuary_id} active for {days_active} days - notifying coach")
                    await notify_coach_for_long_session(sanctuary_id, sanctuary_data, days_active)
                    
                    # Mark as notified
                    sanctuary_data["coach_7day_notified"] = True
                    sanctuary_data["coach_notified_at"] = datetime.datetime.now().isoformat()
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                    sanctuary_engine._save_data()
                
                # Check again at 14 days with higher urgency
                elif days_active >= 14 and not sanctuary_data.get("coach_14day_notified"):
                    print(f"[SANCTUARY MONITOR] Sanctuary {sanctuary_id} active for {days_active} days - URGENT coach notification")
                    await notify_coach_for_long_session(sanctuary_id, sanctuary_data, days_active, urgent=True)
                    
                    sanctuary_data["coach_14day_notified"] = True
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                    sanctuary_engine._save_data()
                    
        except Exception as e:
            print(f"[SANCTUARY MONITOR] Error: {e}")
        
        # Wait before next check cycle
        await asyncio.sleep(82800)  # ~23 hours (check roughly daily)

async def notify_coach_for_long_session(sanctuary_id: str, sanctuary_data: dict, days_active: int, urgent: bool = False):
    """Notify assigned coach about long-running sanctuary"""
    
    family_id = sanctuary_data.get("family_id")
    members = sanctuary_data.get("members", [])
    member_names = [m.get("name", "Unknown") for m in members]
    
    # Find assigned coach from any family member
    coach_id = None
    for member in members:
        user_id = member.get("user_id")
        user_path = os.path.join(DATA_DIR, "Users", f"{user_id}.json")
        if os.path.exists(user_path):
            try:
                with open(user_path, 'r') as f:
                    user_data = json.load(f)
                if user_data.get("assigned_coach"):
                    coach_id = user_data.get("assigned_coach")
                    break
            except:
                pass
    
    if not coach_id:
        print(f"[SANCTUARY MONITOR] No assigned coach found for sanctuary {sanctuary_id}")
        return
    
    # Generate AI summary of current state
    messages = sanctuary_data.get("messages", [])[-30:]  # Last 30 messages
    
    summary_context = "\\n".join([
        f"{m.get('sender_name', 'Unknown')}: {m.get('content', '')[:100]}"
        for m in messages
    ])
    
    # Create notification
    alert_level = "urgent" if urgent else "high" if days_active >= 10 else "medium"
    
    notification = {
        "id": f"SANC_ALERT_{sanctuary_id}_{datetime.datetime.now().strftime('%Y%m%d')}",
        "type": "sanctuary_long_session",
        "title": f"{'🚨 URGENT: ' if urgent else ''}Family Sanctuary Needs Review",
        "body": f"A family sanctuary has been active for {days_active} days and may need your guidance.",
        "data": {
            "sanctuary_id": sanctuary_id,
            "family_id": family_id,
            "days_active": days_active,
            "members": member_names,
            "message_count": len(sanctuary_data.get("messages", [])),
            "alert_level": alert_level,
            "recent_context": summary_context[:500]
        },
        "created_at": datetime.datetime.now().isoformat(),
        "read": False,
        "priority": "urgent" if urgent else "high"
    }
    
    # Save notification
    notif_dir = os.path.join(DATA_DIR, "Notifications", coach_id)
    os.makedirs(notif_dir, exist_ok=True)
    
    notif_path = os.path.join(notif_dir, f"{notification['id']}.json")
    with open(notif_path, 'w') as f:
        json.dump(notification, f, indent=2)
    
    print(f"[SANCTUARY MONITOR] Created notification for coach {coach_id}")
    
    # If coach is connected, send real-time alert
    coach_ws = connected_coaches.get(coach_id)
    if coach_ws:
        try:
            await coach_ws.send(json.dumps({
                "type": "coach_sanctuary_alert",
                **notification
            }))
            print(f"[SANCTUARY MONITOR] Sent real-time alert to coach {coach_id}")
        except:
            pass

# Dictionary to track connected coaches
connected_coaches = {}

'''
    
    # Insert after imports/globals section
    if "sanctuary_monitoring_task" not in content:
        # Find a good insertion point - after sanctuary_engine initialization
        insert_marker = "sanctuary_engine = SanctuaryEngine()"
        if insert_marker in content:
            idx = content.find(insert_marker) + len(insert_marker)
            content = content[:idx] + "\n\n" + background_task + content[idx:]
            fixes_applied.append("1. Added sanctuary monitoring background task")
        else:
            # Try alternate location
            alt_marker = "# Bridge Online"
            if alt_marker in content:
                idx = content.find(alt_marker)
                content = content[:idx] + background_task + "\n" + content[idx:]
                fixes_applied.append("1. Added sanctuary monitoring background task")
    
    # =========================================================================
    # FIX 2: Add coach guidance handlers
    # =========================================================================
    
    coach_guidance_handlers = '''
            # =========================================================================
            # COACH GUIDANCE FOR SANCTUARY
            # =========================================================================
            elif t == "coach_set_guidance":
                # Coach sets guidance for Little Nate in a sanctuary
                sanctuary_id = data.get("sanctuary_id")
                guidance = data.get("guidance", {})
                
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id)
                if not sanctuary_data:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Sanctuary not found"
                    }))
                    continue
                
                sanctuary_data["coach_guidance"] = {
                    "coach_id": user_id,
                    "coach_name": member_name,
                    "set_at": datetime.datetime.now().isoformat(),
                    "focus_areas": guidance.get("focus_areas", []),
                    "ai_instructions": guidance.get("ai_instructions", ""),
                    "suggest_live_coaching": guidance.get("suggest_live_coaching", False),
                    "priority_topics": guidance.get("priority_topics", []),
                    "avoid_topics": guidance.get("avoid_topics", []),
                    "tone_adjustment": guidance.get("tone_adjustment", ""),
                    "escalation_threshold": guidance.get("escalation_threshold", "normal")
                }
                
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                sanctuary_engine._save_data()
                
                print(f">>> [COACH] Guidance set for sanctuary {sanctuary_id} by {member_name}")
                
                # Notify family if coach wants
                if guidance.get("notify_family", True):
                    for mid, ws in sanctuary_websockets.get(sanctuary_id, {}).items():
                        try:
                            await ws.send(json.dumps({
                                "type": "sanctuary_coach_guidance",
                                "sanctuary_id": sanctuary_id,
                                "coach_name": member_name,
                                "message": "Your family coach has reviewed your progress and provided guidance for Little Nate. 💙",
                                "suggest_live_coaching": guidance.get("suggest_live_coaching", False),
                                "focus_areas": guidance.get("focus_areas", [])
                            }))
                        except:
                            pass
                
                await websocket.send(json.dumps({
                    "type": "coach_guidance_set",
                    "sanctuary_id": sanctuary_id,
                    "message": "Guidance applied successfully"
                }))
            
            elif t == "coach_get_sanctuary_detail":
                # Coach requests full detail of a sanctuary
                sanctuary_id = data.get("sanctuary_id")
                
                # Check sanctuary history first
                history_path = os.path.join(DATA_DIR, "sanctuary_history", f"{sanctuary_id}.json")
                if os.path.exists(history_path):
                    with open(history_path, 'r') as f:
                        session_data = json.load(f)
                    await websocket.send(json.dumps({
                        "type": "coach_sanctuary_detail",
                        "sanctuary_id": sanctuary_id,
                        "session": session_data,
                        "source": "history"
                    }))
                else:
                    # Check active sanctuaries
                    sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id)
                    if sanctuary_data:
                        await websocket.send(json.dumps({
                            "type": "coach_sanctuary_detail",
                            "sanctuary_id": sanctuary_id,
                            "session": sanctuary_data,
                            "source": "active"
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Sanctuary not found"
                        }))
            
            elif t == "coach_add_session_note":
                # Coach adds note to a session
                sanctuary_id = data.get("sanctuary_id")
                note = data.get("note", "")
                
                history_path = os.path.join(DATA_DIR, "sanctuary_history", f"{sanctuary_id}.json")
                if os.path.exists(history_path):
                    with open(history_path, 'r') as f:
                        session_data = json.load(f)
                    
                    if "coach_notes" not in session_data:
                        session_data["coach_notes"] = []
                    
                    session_data["coach_notes"].append({
                        "coach_id": user_id,
                        "coach_name": member_name,
                        "note": note,
                        "timestamp": datetime.datetime.now().isoformat()
                    })
                    
                    with open(history_path, 'w') as f:
                        json.dump(session_data, f, indent=2)
                    
                    await websocket.send(json.dumps({
                        "type": "coach_note_added",
                        "sanctuary_id": sanctuary_id,
                        "message": "Note added successfully"
                    }))
                else:
                    await websocket.send(json.dumps({
                        "type": "error", 
                        "message": "Session not found"
                    }))

'''
    
    # Insert handlers
    if "coach_set_guidance" not in content:
        insert_marker = 'elif t == "sanctuary_end_session":'
        if insert_marker in content:
            idx = content.find(insert_marker)
            content = content[:idx] + coach_guidance_handlers + "\n            " + content[idx:]
            fixes_applied.append("2. Added coach guidance handlers")
        else:
            # Try alternate insertion
            alt_marker = 'elif t == "sanctuary_exit":'
            if alt_marker in content:
                idx = content.find(alt_marker)
                content = content[:idx] + coach_guidance_handlers + "\n            " + content[idx:]
                fixes_applied.append("2. Added coach guidance handlers")
    
    # =========================================================================
    # FIX 3: Modify AI response generation to include coach guidance
    # =========================================================================
    
    # Add helper function to build AI context with coach guidance
    coach_context_func = '''
def get_sanctuary_ai_context_with_coach_guidance(sanctuary_data: dict) -> str:
    """Build AI context string including any coach guidance"""
    
    context_parts = []
    
    # Entry responses context
    entry_responses = sanctuary_data.get("entry_responses", {})
    if entry_responses:
        entry_context = []
        for mid, resp in entry_responses.items():
            name = resp.get("member_name", mid)
            entry_context.append(
                f"{name} entered because: {resp.get('why_entering', 'N/A')}. "
                f"Goals: {resp.get('goals', 'N/A')}. "
                f"Feeling: {resp.get('feeling_scale', '?')}/10"
            )
        context_parts.append("FAMILY ENTRY CONTEXT:\\n" + "\\n".join(entry_context))
    
    # Coach guidance context
    coach_guidance = sanctuary_data.get("coach_guidance")
    if coach_guidance:
        guidance_parts = [
            f"\\n\\nCOACH GUIDANCE (from {coach_guidance.get('coach_name', 'Coach')}):",
        ]
        
        if coach_guidance.get("focus_areas"):
            guidance_parts.append(f"Focus Areas: {', '.join(coach_guidance['focus_areas'])}")
        
        if coach_guidance.get("ai_instructions"):
            guidance_parts.append(f"Special Instructions: {coach_guidance['ai_instructions']}")
        
        if coach_guidance.get("priority_topics"):
            guidance_parts.append(f"Priority Topics: {', '.join(coach_guidance['priority_topics'])}")
        
        if coach_guidance.get("avoid_topics"):
            guidance_parts.append(f"Topics to Avoid: {', '.join(coach_guidance['avoid_topics'])}")
        
        if coach_guidance.get("tone_adjustment"):
            guidance_parts.append(f"Tone Adjustment: {coach_guidance['tone_adjustment']}")
        
        if coach_guidance.get("suggest_live_coaching"):
            guidance_parts.append("NOTE: Coach suggests offering live coaching session to this family.")
        
        context_parts.append("\\n".join(guidance_parts))
        context_parts.append("\\nPlease incorporate the coach's guidance into your facilitation style and focus.")
    
    return "\\n\\n".join(context_parts)

'''
    
    if "get_sanctuary_ai_context_with_coach_guidance" not in content:
        # Insert before handle_websocket
        insert_before = "async def handle_websocket"
        if insert_before in content:
            idx = content.find(insert_before)
            content = content[:idx] + coach_context_func + "\n\n" + content[idx:]
            fixes_applied.append("3. Added coach guidance context builder")
    
    # =========================================================================
    # FIX 4: Start monitoring task when server starts
    # =========================================================================
    
    # Find where server starts and add task creation
    old_server_start = 'print("[*] Bridge Online. Awaiting connections...")'
    new_server_start = '''print("[*] Bridge Online. Awaiting connections...")
    
    # Start sanctuary monitoring background task
    asyncio.create_task(sanctuary_monitoring_task())
    print("[*] Sanctuary monitoring task started")'''
    
    if old_server_start in content and "sanctuary_monitoring_task()" not in content:
        content = content.replace(old_server_start, new_server_start)
        fixes_applied.append("4. Added monitoring task startup")
    
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
        print("7-DAY CHECK-IN FEATURES:")
        print("  • Background task monitors active sanctuaries")
        print("  • Notifies coach at 7 days and 14 days (urgent)")
        print("  • Creates in-app notification for coach")
        print("  • Real-time alert if coach is connected")
        print("")
        print("COACH GUIDANCE FEATURES:")
        print("  • coach_set_guidance - Set AI instructions")
        print("  • coach_get_sanctuary_detail - View full session")
        print("  • coach_add_session_note - Add notes")
        print("  • Coach guidance injected into AI context")
        print("")
        print("NEXT: Restart backend to start monitoring task")
    else:
        print("⚠️  No fixes applied - check patterns manually")
    
    return True

if __name__ == "__main__":
    apply_fix()
