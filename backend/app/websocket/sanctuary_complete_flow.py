#!/usr/bin/env python3
"""
Complete Session Flow - Ties all Phase 2 features together

Entry Questions → Session → Complete → Summary → Coach History
"""

import re

def main():
    print("="*60)
    print("SANCTUARY COMPLETE SESSION FLOW")
    print("="*60)
    
    with open('bridge_server.py', 'r') as f:
        content = f.read()
    
    # Step 1: Remove any broken sanctuary_complete handler
    pattern = r'elif t == "sanctuary_complete":.*?(?=\n            elif t == ")'
    if re.search(pattern, content, flags=re.DOTALL):
        content = re.sub(pattern, '', content, flags=re.DOTALL)
        print("✓ Removed broken handler")
    
    # Step 2: Build the complete handler
    complete_handler = '''elif t == "sanctuary_complete":
                """
                COMPLETE SESSION WITH SUMMARY
                
                Uses entry_responses + messages + coaching to generate:
                1. AI summary with personalized insights
                2. Coach history with auto-flagging
      3. Sends summary to each member
                """
                sanctuary_id = d.get('sanctuary_id')
                print(f">>> [SANCTUARY] Starting session completion for {sanctuary_id}")
                
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                if not sanctuary_data:
                    await websocket.send(json.dumps({"type": "error", "message": "Sanctuary not found"}))
                    continue
                
                members = sanctuary_data.get("members", [])
                
                # Notify all: generating summary
                for mid, ws in list(sanctuary_websockets.get(sanctuary_id, {}).items()):
                    try:
                        await ws.send(json.dumps({
                            "type": "sanctuary_generating_summary",
                            "sanctuary_id": sanctuary_id,
                            "message": "Little Nate is preparing your session summary... 💙"
                        }))
                    except:
                        pass
                
              # ============================================
                # GATHER ALL DATA FOR AI SUMMARY
                # ============================================
                
                # Entry questions context (WHY they came, GOALS)
                entry_responses = sanctuary_data.get("entry_responses", {})
                entry_context = ""
                for mid, resp in entry_responses.items():
                    name = resp.get("member_name", mid)
                    entry_context += f"""
{name}:
  - Why entering: {resp.get('why_entering', 'Not provided')}
  - What's happening: {resp.get('whats_happening', 'Not provided')}
  - Goals: {resp.get('goals', 'Not provided')}
  - Feeling at start: {resp.get('feeling_scale', '?')}/10
"""
                
                # Conversation messages
                messages = sanctuary_data.get("messages", [])
                conv_text = "\\n".join([
                    f"{m.get('sender_name', '?')}: {m.get('content', '')}"
                    for m in messages[-100:]
                ])
                
                # Coaching sessions
                coaching_sessions = sanctuary_data.get("coaching_sessions", {})
                coaching_summary = f"{len(coaching_sessions)} private coaching session(s)"
                
                # Duration
                created_at = sanctuary_data.get("created_at", datetime.datetime.now().isoformat())
                try:
                    start = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    duration_mins = int((datetime.datetime.now(datetime.timezone.utc) - start).total_seconds() / 60)
                except:
                    duration_mins = 0
                
                member_names = [m.get("name", "Member") for m in members]
                
                # ============================================
                # GENERATE AI SUMMARY
                # ============================================
                
                summary_prompt = f"""You are Little Nate, a compassionate therapeutic AI facilitator for the Family Sanctuary.

Analyze this family session and provide insights that will help each member grow.

FAMILY MEMBERS: {', '.join(member_names)}

ENTRY CONTEXT (what each member shared before starting):
{entry_context if entry_context.strip() else 'No entry responses collected'}

CONVERSATION ({len(messages)} messages over {duration_mins} minutes):
{conv_text if conv_text.strip() else 'No messages recorded'}

COACHING: {coaching_summary}

Generate a therapeutic summary as JSON:
{{
    "key_conflicts": [
        "Brief description of main conflict/tension 1",
        "Brief description of main conflict/tension 2"
    ],
    "points_of_agreement": [
        "Area where family found common ground"
    ],
    "corrective_experiences": [
        "A moment of healing, understanding, or emotional connection"
    ],
    "individual_insights": {{
        "{member_names[0] if member_names else 'Member1'}": {{
            "patterns_observed": "Communication or behavioral patterns you noticed",
            "growth_areas": "Areas for personal development",
            "strengths_shown": "Positive contributions they made",
            "suggested_focus": "What they should focus on moving forward"
        }},
        "{member_names[1] if len(member_names) > 1 else 'Member2'}": {{
            "patterns_observed": "...",
            "growth_areas": "...",
            "strengths_shown": "...",
            "suggested_focus": "..."
        }}
    }},
    "overall_progress": 6,
    "recommended_next_steps": [
        "Specific actionable suggestion 1",
        "Specific actionable suggestion 2",
        "Specific actionable suggestion 3"
    ],
    "coach_notes": "Summary notes for a human coach if they review this session"
}}

IMPORTANT: 
- Include individual_insights for EACH family member by name
- Be warm, encouraging, and growth-focused
- Reference their entry goals in suggested_focus
- Progress score: 1-10 based on how well they met their stated goals"""

                try:
                    summary_response = await call_azure_openai(
                        summary_prompt,
                        system_message="You are a compassionate therapeutic AI. Respond ONLY with valid JSON, no other text.",
                        max_tokens=2500
                    )
                    
                    # Extract JSON from response
                    json_match = re.search(r'\\{[\\s\\S]*\\}', summary_response)
                    if json_match:
                        summary_data = json.loads(json_match.group())
                    else:
                        raise ValueError("No valid JSON in AI response")
                    
                    print(f">>> [SANCTUARY] AI summary generated successfully")
                    
                except Exception as e:
                    print(f">>> [SANCTUARY] Summary generation error: {e}")
                    summary_data = {
                        "key_conflicts": ["Please review session manually"],
                        "points_of_agreement": ["Unable to analyze automatically"],
                        "corrective_experiences": [],
                        "individual_insights": {name: {
                            "patterns_observed": "Review needed",
                            "growth_areas": "Discuss with coach",
                            "strengths_shown": "Participated in session",
                            "suggested_focus": "Schedule follow-up"
                        } for name in member_names},
                        "overall_progress": 5,
                        "recommended_next_steps": ["Schedule a follow-up family discussion", "Consider live coaching session"],
                        "coach_notes": f"AI summary failed: {str(e)}. Manual review recommended."
                    }
                
                # ============================================
                # STORE FOR COACH HISTORY
                # ============================================
                
                sanctuary_data["session_summary"] = {
                    "generated_at": datetime.datetime.now().isoformat(),
                    "summary": summary_data,
                    "duration_minutes": duration_mins,
                    "total_messages": len(messages),
                    "coaching_sessions": len(coaching_sessions)
                }
                
                sanctuary_data["completed_at"] = datetime.datetime.now().isoformat()
                sanctuary_data["status"] = "COMPLETED"
                
                # Auto-flag for coach review
                needs_review = False
                review_reasons = []
                
                if duration_mins >= 10080:  # 7+ days
                    needs_review = True
                    review_reasons.append(f"Long session: {duration_mins // 1440} days")
                
                if summary_data.get("overall_progress", 10) <= 4:
                    needs_review = True
                    review_reasons.append(f"Low progress: {summary_data.get('overall_progress')}/10")
                
                # Check for concerning content
                danger_words = ["hurt myself", "suicide", "kill", "abuse", "hit me", "scared", "unsafe"]
                for msg in messages:
                    content_lower = msg.get("content", "").lower()
                    for word in danger_words:
                        if word in content_lower:
                            needs_review = True
                            review_reasons.append(f"Concerning content detected")
                            break
                    if needs_review:
                        break
                
                sanctuary_data["needs_coach_review"] = needs_review
                sanctuary_data["review_reasons"] = review_reasons
                
                # Save to history
                import os as os2
                history_dir = os2.path.join(DATA_DIR, "sanctuary_history")
                os2.makedirs(history_dir, exist_ok=True)
                
                history_path = os2.path.join(history_dir, f"{sanctuary_id}.json")
                with open(history_path, "w") as hf:
                    json.dump(sanctuary_data, hf, indent=2, default=str)
                
                print(f">>> [SANCTUARY] Saved to history: {history_path}")
                print(f">>> [SANCTUARY] Needs coach review: {needs_review} {review_reasons}")
                
                # ============================================
                # SEND PERSONALIZED SUMMARY TO EACH MEMBER
                # ============================================
                
                for member in members:
                    m_id = member.get("user_id")
                    m_name = member.get("name", "Member")
                    
                    # Get their personalized insights
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
                                    "duration_minutes": duration_mins,
                                    "total_messages": len(messages),
                                    "coaching_sessions": len(coaching_sessions)
                                },
                                "message": f"Here's your session summary, {m_name}. Take time to reflect. 💙"
                            }))
                            print(f">>> [SANCTUARY] Sent summary to {m_name}")
                        except Exception as e:
                            print(f">>> [SANCTUARY] Failed to send summary to {m_name}: {e}")
                
                # ============================================
                # CLOSE SANCTUARY
                # ============================================
                
                # Reve from active
                del sanctuary_engine.data["active_sanctuaries"][sanctuary_id]
                sanctuary_engine._save_data()
                
                # Clear websocket registry
                if sanctuary_id in sanctuary_websockets:
                    del sanctuary_websockets[sanctuary_id]
                
                print(f">>> [SANCTUARY] ✓ Session {sanctuary_id} completed successfully")

            '''
    
    # Insert before sanctuary_entry_responses
    marker = 'elif t == "sanctuary_entry_responses":'
    if marker in content:
        idx = content.find(marker)
        content = content[:idx] + complete_handler + content[idx:]
        print("✓ Added complete session handler")
    else:
        t("✗ Could not find insertion point")
        return
    
    with open('bridge_server.py', 'w') as f:
        f.write(content)
    
    print("")
    print("✓ COMPLETE SESSION FLOW IMPLEMENTED")
    print("")
    print("Flow:")
    print("  1. User clicks 'Complete Session'")
    print("  2. sanctuary_complete sent to backend")
    print("  3. sanctuary_generating_summary sent to all members")
    print("  4. AI analyzes: entry_responses + messages + coaching")
    print("  5. sanctuary_summary sent with personalized insights")
    print("  6. Session archived to data/sanctuary_history/")
    print("  7. Auto-flagged if: >7 days, low score, concerning content")
    print("  8. Sanctuary closed")
    print("")
    print("Restart backend to test!")

if __name__ == "__main__":
    main()
