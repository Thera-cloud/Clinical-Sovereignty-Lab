#!/usr/bin/env python3
"""
Fix: Sanctuary Session Summary
==============================
Generates AI summary when sanctuary session ends, including:
- Key arguments/conflicts
- Points of agreement
- Corrective relational experiences
- Individual insights for each member
- Recommended next steps

Run from: ~/Desktop/Clinical-Sovereignty-Lab-2/backend/app/websocket/
"""

import shutil
from datetime import datetime

FILE_PATH = "bridge_server.py"
ENGINE_PATH = "sanctuary_engine.py"

def apply_fix():
    print("=" * 60)
    print("Fix: Sanctuary Session Summary")
    print("=" * 60)
    
    # Backup
    backup_path = FILE_PATH + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(FILE_PATH, backup_path)
    print(f"📦 Backup: {backup_path}")
    
    with open(FILE_PATH, 'r') as f:
        content = f.read()
    
    fixes_applied = []
    
    # =========================================================================
    # FIX 1: Add sanctuary_end_session handler
    # =========================================================================
    
    end_session_handler = '''
            # =========================================================================
            # SANCTUARY END SESSION WITH SUMMARY
            # =========================================================================
            elif t == "sanctuary_end_session":
                sanctuary_id = data.get("sanctuary_id")
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                
                if not sanctuary_data:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Sanctuary not found"
                    }))
                    continue
                
                print(f">>> [SANCTUARY] Generating session summary for {sanctuary_id}")
                
                # Notify all members summary is being generated
                for mid, ws in sanctuary_websockets.get(sanctuary_id, {}).items():
                    try:
                        await ws.send(json.dumps({
                            "type": "sanctuary_generating_summary",
                            "sanctuary_id": sanctuary_id,
                            "message": "Little Nate is preparing your session summary... 💙"
                        }))
                    except:
                        pass
                
                # Gather conversation data
                messages = sanctuary_data.get("messages", [])
                entry_responses = sanctuary_data.get("entry_responses", {})
                coaching_sessions = sanctuary_data.get("coaching_sessions", {})
                members = sanctuary_data.get("members", [])
                
                # Calculate session duration
                created_at = sanctuary_data.get("created_at", datetime.datetime.now().isoformat())
                try:
                    start_time = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    duration_minutes = int((datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() / 60)
                except:
                    duration_minutes = 0
                
                # Build conversation text for AI
                conversation_text = "\\n".join([
                    f"{m.get('sender_name', 'Unknown')}: {m.get('content', '')}"
                    for m in messages[-100:]  # Last 100 messages
                ])
                
                # Build entry context
                entry_context = "\\n".join([
                    f"{entry_responses.get(mid, {}).get('member_name', mid)}: " +
                    f"Why: {resp.get('why_entering', 'N/A')}, " +
                    f"Goals: {resp.get('goals', 'N/A')}, " +
                    f"Feeling: {resp.get('feeling_scale', 'N/A')}/10"
                    for mid, resp in entry_responses.items()
                ])
                
                member_names = [m.get("name", "Unknown") for m in members]
                
                # Generate summary with AI
                summary_prompt = f"""You are Little Nate, a therapeutic AI facilitator for the Family Sanctuary.
                
Analyze this family conversation session and provide a comprehensive, compassionate summary.

FAMILY MEMBERS: {', '.join(member_names)}

ENTRY CONTEXT (what each member shared before entering):
{entry_context if entry_context else "No entry responses recorded"}

CONVERSATION ({len(messages)} messages):
{conversation_text if conversation_text else "No messages recorded"}

NUMBER OF PRIVATE COACHING SESSIONS: {len(coaching_sessions)}

Generate a therapeutic summary in the following JSON format:
{{
    "key_conflicts": [
        "Brief description of main conflict/argument 1",
        "Brief description of main conflict/argument 2"
    ],
    "points_of_agreement": [
        "Area where family found common ground",
        "Shared value or understanding discovered"
    ],
    "corrective_experiences": [
        "Moment of healing or understanding",
        "Instance of emotional connection"
    ],
    "individual_insights": {{
        "{member_names[0] if member_names else 'Member'}": {{
            "patterns_observed": "Communication or behavioral patterns noticed",
            "growth_areas": "Areas for personal development",
            "strengths_shown": "Positive contributions to the conversation",
            "suggested_focus": "What to focus on moving forward"
        }}
    }},
    "overall_progress": 7,
    "recommended_next_steps": [
        "Specific actionable suggestion 1",
        "Specific actionable suggestion 2",
        "Specific actionable suggestion 3"
    ],
    "coach_notes": "Summary notes for a human coach reviewing this session"
}}

Be warm, encouraging, and focus on growth opportunities. Include insights for EACH family member in individual_insights."""

                try:
                    # Use existing AI generation
                    summary_response = await call_azure_openai(
                        summary_prompt,
                        system_message="You are a compassionate therapeutic AI. Respond only with valid JSON.",
                        max_tokens=2000
                    )
                    
                    # Parse JSON from response
                    import re
                    json_match = re.search(r'\\{[\\s\\S]*\\}', summary_response)
                    if json_match:
                        summary_data = json.loads(json_match.group())
                    else:
                        raise ValueError("No JSON found in response")
                        
                except Exception as e:
                    print(f">>> [SANCTUARY] Summary generation error: {e}")
                    summary_data = {
                        "key_conflicts": ["Unable to analyze - please review conversation manually"],
                        "points_of_agreement": [],
                        "corrective_experiences": [],
                        "individual_insights": {},
                        "overall_progress": 5,
                        "recommended_next_steps": ["Schedule a follow-up family discussion"],
                        "coach_notes": f"AI summary failed: {str(e)}"
                    }
                
                # Store summary in sanctuary data
                sanctuary_data["session_summary"] = {
                    "generated_at": datetime.datetime.now().isoformat(),
                    "summary": summary_data,
                    "session_duration_minutes": duration_minutes,
                    "total_messages": len(messages),
                    "coaching_sessions_count": len(coaching_sessions)
                }
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                sanctuary_engine._save_data()
                
                # Store for coach access
                await store_session_for_coach_review(sanctuary_id, sanctuary_data)
                
                # Send personalized summaries to each member
                for member in members:
                    m_id = member.get("user_id")
                    m_name = member.get("name", "Unknown")
                    
                    personal_insights = summary_data.get("individual_insights", {}).get(m_name, {})
                    
                    ws = sanctuary_websockets.get(sanctuary_id, {}).get(m_id)
                    if ws:
                        try:
                            await ws.send(json.dumps({
                                "type": "sanctuary_summary",
                                "sanctuary_id": sanctuary_id,
                                "summary": {
                                    "key_conflicts": summary_data.get("key_conflicts", []),
                                    "points_of_agreement": summary_data.get("points_of_agreement", []),
                                    "corrective_experiences": summary_data.get("corrective_experiences", []),
                                    "your_insights": personal_insights,
                                    "overall_progress": summary_data.get("overall_progress", 5),
                                    "next_steps": summary_data.get("recommended_next_steps", [])
                                },
                                "session_stats": {
                                    "duration_minutes": duration_minutes,
                                    "total_messages": len(messages),
                                    "coaching_sessions": len(coaching_sessions)
                                },
                                "message": f"Here's your session summary, {m_name}. Take time to reflect. 💙"
                            }))
                        except Exception as e:
                            print(f">>> [SANCTUARY] Failed to send summary to {m_name}: {e}")
                
                print(f">>> [SANCTUARY] Session summary sent for {sanctuary_id}")

'''
    
    # Insert handler
    insert_marker = 'elif t == "sanctuary_entry_responses":'
    if insert_marker in content and "sanctuary_end_session" not in content:
        idx = content.find(insert_marker)
        content = content[:idx] + end_session_handler + "\n            " + content[idx:]
        fixes_applied.append("1. Added sanctuary_end_session handler")
    elif "sanctuary_end_session" not in content:
        # Try alternate insertion point
        alt_marker = 'elif t == "sanctuary_exit":'
        if alt_marker in content:
            idx = content.find(alt_marker)
            content = content[:idx] + end_session_handler + "\n            " + content[idx:]
            fixes_applied.append("1. Added sanctuary_end_session handler")
    
    # =========================================================================
    # FIX 2: Add store_session_for_coach_review function
    # =========================================================================
    
    coach_storage_func = '''
async def store_session_for_coach_review(sanctuary_id: str, sanctuary_data: dict):
    """Store completed session for coach review"""
    import os
    
    HISTORY_DIR = os.path.join(DATA_DIR, "sanctuary_history")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    
    family_id = sanctuary_data.get("family_id", "UNKNOWN")
    
    # Calculate if needs coach review
    messages = sanctuary_data.get("messages", [])
    summary = sanctuary_data.get("session_summary", {}).get("summary", {})
    
    needs_review = False
    review_reasons = []
    
    # Check duration
    created_at = sanctuary_data.get("created_at")
    if created_at:
        try:
            start = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            days_active = (datetime.datetime.now(datetime.timezone.utc) - start).days
            if days_active >= 7:
                needs_review = True
                review_reasons.append(f"Session lasted {days_active} days")
        except:
            pass
    
    # Check progress score
    if summary.get("overall_progress", 10) <= 4:
        needs_review = True
        review_reasons.append("Low progress score")
    
    # Check for concerning content
    danger_keywords = ["hurt myself", "suicide", "kill", "weapon", "abuse", "hit me", "scared"]
    for msg in messages:
        content_lower = msg.get("content", "").lower()
        for kw in danger_keywords:
            if kw in content_lower:
                needs_review = True
                review_reasons.append(f"Concerning content detected: '{kw}'")
                break
    
    history_record = {
        "sanctuary_id": sanctuary_id,
        "family_id": family_id,
        "created_at": sanctuary_data.get("created_at"),
        "completed_at": datetime.datetime.now().isoformat(),
        "members": sanctuary_data.get("members", []),
        "messages": messages,
        "entry_responses": sanctuary_data.get("entry_responses", {}),
        "coaching_sessions": sanctuary_data.get("coaching_sessions", {}),
        "session_summary": sanctuary_data.get("session_summary", {}),
        "coach_notes": [],
        "needs_review": needs_review,
        "review_reasons": review_reasons,
        "status": "needs_review" if needs_review else "completed"
    }
    
    # Save session file
    filepath = os.path.join(HISTORY_DIR, f"{sanctuary_id}.json")
    with open(filepath, 'w') as f:
        json.dump(history_record, f, indent=2, default=str)
    
    # Update family history index
    family_index_path = os.path.join(HISTORY_DIR, f"family_{family_id}_index.json")
    family_index = []
    if os.path.exists(family_index_path):
        with open(family_index_path, 'r') as f:
            family_index = json.load(f)
    
    family_index.append({
        "sanctuary_id": sanctuary_id,
        "completed_at": history_record["completed_at"],
        "needs_review": needs_review,
        "message_count": len(messages)
    })
    
    with open(family_index_path, 'w') as f:
        json.dump(family_index, f, indent=2)
    
    print(f">>> [SANCTUARY] Session stored for coach review: {sanctuary_id} (needs_review={needs_review})")
    
    # If needs review, notify coach
    if needs_review:
        # Find assigned coach
        for member in sanctuary_data.get("members", []):
            user_id = member.get("user_id")
            # Look up user's assigned coach
            user_path = os.path.join(DATA_DIR, "Users", f"{user_id}.json")
            if os.path.exists(user_path):
                with open(user_path, 'r') as f:
                    user_data = json.load(f)
                coach_id = user_data.get("assigned_coach")
                if coach_id:
                    # Create notification for coach
                    await create_coach_notification(
                        coach_id,
                        f"Family session needs review",
                        f"Session {sanctuary_id} flagged: {', '.join(review_reasons)}",
                        {"sanctuary_id": sanctuary_id, "type": "session_review"}
                    )
                    break

async def create_coach_notification(coach_id: str, title: str, body: str, data: dict):
    """Create in-app notification for coach"""
    import os
    
    notif_dir = os.path.join(DATA_DIR, "Notifications", coach_id)
    os.makedirs(notif_dir, exist_ok=True)
    
    notif_id = f"NOTIF_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    notif = {
        "id": notif_id,
        "title": title,
        "body": body,
        "data": data,
        "created_at": datetime.datetime.now().isoformat(),
        "read": False
    }
    
    filepath = os.path.join(notif_dir, f"{notif_id}.json")
    with open(filepath, 'w') as f:
        json.dump(notif, f, indent=2)
    
    print(f">>> [NOTIFY] Created notification for coach {coach_id}: {title}")

'''
    
    # Add function before main websocket handler
    if "store_session_for_coach_review" not in content:
        # Find a good insertion point
        insert_before = "async def handle_websocket"
        if insert_before in content:
            idx = content.find(insert_before)
            content = content[:idx] + coach_storage_func + "\n\n" + content[idx:]
            fixes_applied.append("2. Added store_session_for_coach_review function")
            fixes_applied.append("3. Added create_coach_notification function")
    
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
        print("NEW FEATURES:")
        print("  • AI-generated session summary with:")
        print("    - Key conflicts identified")
        print("    - Points of agreement")
        print("    - Corrective experiences")
        print("    - Individual insights per member")
        print("    - Progress score (1-10)")
        print("    - Recommended next steps")
        print("  • Sessions stored in data/sanctuary_history/")
        print("  • Auto-flag for coach review if:")
        print("    - Session > 7 days")
        print("    - Low progress score")
        print("    - Concerning content detected")
        print("")
        print("NEXT: Apply Flutter fix, then restart backend")
    else:
        print("⚠️  No fixes applied - may need manual intervention")
    
    return True

if __name__ == "__main__":
    apply_fix()
