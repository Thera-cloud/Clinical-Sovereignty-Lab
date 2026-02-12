"""
PRIVATE COACHING IMPLEMENTATION - BRIDGE_SERVER.PY ADDITIONS
============================================================
Copy these sections into bridge_server.py at the indicated locations.

Implementation Date: January 27, 2026
"""

# =============================================================================
# PART 1: ADD TO AzureCortex CLASS (after process_sanctuary_message method)
# Location: Around line 1565, after the closing of process_sanctuary_message
# =============================================================================

    async def process_private_coaching(
        self,
        member_profile: dict,
        sanctuary_data: dict,
        coaching_session: dict,
        trigger: str = "coaching_start"
    ) -> dict:
        """
        Process private 1-on-1 coaching session with Little Nate
        
        Triggers:
        - coaching_start: Initial reframe and first question
        - coaching_response: Respond to user's message (up to 5 attempts)
        - coaching_deescalated: User is calm, prepare to return
        - generate_assisted_response: Create $3 assisted response
        """
        print(f">>> [PRIVATE COACHING] Processing: {trigger} for {member_profile.get('name')}")
        
        member_name = member_profile.get("name", "Friend")
        member_id = member_profile.get("hardware_id")
        
        # Get member's history and metrics
        memory = self.mem.recall(member_profile, limit=5)
        metrics = self.metrics.load_metrics(member_profile)
        
        # Get coaching session context
        attempt_number = coaching_session.get("attempt_number", 1)
        coaching_messages = coaching_session.get("messages", [])
        triggering_message = coaching_session.get("triggering_message", "")
        
        # Format private conversation so far
        private_convo = ""
        for msg in coaching_messages[-6:]:
            role = "You" if msg.get("role") == "assistant" else member_name
            private_convo += f"{role}: {msg.get('content', '')}\n"
        
        # Get recent sanctuary messages for context (what led to this)
        sanctuary_messages = sanctuary_data.get("messages", [])[-10:]
        sanctuary_convo = ""
        for msg in sanctuary_messages:
            sanctuary_convo += f"{msg.get('sender_name', 'Unknown')}: {msg.get('content', '')}\n"
        
        # Build trigger-specific prompts
        if trigger == "coaching_start":
            user_prompt = f"""This is your FIRST message to {member_name} in private coaching.

WHAT HAPPENED (sanctuary conversation that triggered this):
{sanctuary_convo}

{member_name}'s triggering message: "{triggering_message}"

YOUR TASK:
1. Acknowledge their strong feelings with warmth
2. Provide an initial REFRAME - help them see what might be underneath their anger
3. Ask your FIRST curiosity question to understand what triggered this reaction

Keep it conversational and warm. 2-3 short paragraphs max."""

        elif trigger == "coaching_response":
            user_prompt = f"""Continue your private coaching with {member_name}.

ATTEMPT: {attempt_number} of 5

PRIVATE CONVERSATION SO FAR:
{private_convo}

{member_name}'s latest message: "{coaching_messages[-1].get('content', '') if coaching_messages else ''}"

YOUR TASK (based on attempt number):
- Attempt 1-2: Ask curiosity questions - what happened? what did it mean to them?
- Attempt 3: Validate their feelings, ask what they need the other person to understand
- Attempt 4: Offer a de-escalation technique (breathing, grounding, reframe)
- Attempt 5: Check if they're ready to return, or offer assisted response

ASSESS their emotional state:
- If they seem calmer, acknowledge progress and ask if ready to return
- If still escalated, continue with compassionate questions
- If stuck after 5 attempts, gently offer the assisted response option

Keep responses warm and brief (2-3 sentences per thought)."""

        elif trigger == "coaching_deescalated":
            user_prompt = f"""Great news - {member_name} seems calmer now.

PRIVATE CONVERSATION:
{private_convo}

YOUR TASK:
1. Acknowledge their progress warmly
2. Ask if they're ready to return to the Family Sanctuary
3. Offer to help them craft an opening message if they'd like

Be encouraging but not pushy. They can take their time."""

        elif trigger == "generate_assisted_response":
            # Get other family members' context (without revealing private details)
            other_members = [m for m in sanctuary_data.get("members", []) if m.get("user_id") != member_id]
            other_context = ""
            for other in other_members:
                other_context += f"- {other.get('name', 'Family member')}: Participant in sanctuary\n"
            
            user_prompt = f"""Generate an ASSISTED RESPONSE for {member_name} to send to the Family Sanctuary.

WHAT {member_name.upper()} SHARED IN PRIVATE (CONFIDENTIAL - use themes only):
{private_convo}

OTHER FAMILY MEMBERS:
{other_context}

SANCTUARY CONTEXT:
{sanctuary_convo}

YOUR TASK:
Create a response that {member_name} can send to the sanctuary that:
1. Expresses their TRUE feelings (from private coaching) in a way others can hear
2. Uses "I feel" statements instead of "You did"
3. Shares their underlying need without attacking
4. Opens door for connection

CRITICAL: Do NOT reveal specific details from private coaching. Use themes and feelings only.

Format your response as:
SUGGESTED_RESPONSE: [the message they can send]
EXPLANATION: [brief note about why this approach helps]"""

        else:
            user_prompt = f"Continue supporting {member_name} in their private coaching session."

        # Build system prompt
        system_prompt = f"""You are Little Nate, providing PRIVATE 1-on-1 coaching to {member_name}.

THIS IS CONFIDENTIAL - nothing shared here goes back to other family members.

ABOUT {member_name.upper()}:
- Current mood: {metrics.get('current_mood', 'distressed')}
- Risk level: {metrics.get('risk_level', 'LOW')}
- History context: {memory[:300] if memory else 'New user'}

YOUR APPROACH:
1. CURIOSITY over judgment - ask "what happened?" not "why did you do that?"
2. COMPASSION - validate their feelings even if their behavior was problematic
3. REFRAME - help them see the other person's perspective gently
4. DE-ESCALATE - breathing, grounding, or perspective shifts
5. EMPOWER - help them find their own words, don't lecture

CONFIDENTIALITY RULES:
- What they share here stays here
- If generating assisted response, use THEMES not specific details
- Never quote their private words to other family members

Keep responses warm, brief, and conversational. You're a supportive friend, not a lecturer."""

        try:
            import aiohttp
            response_text = ""
            
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    AZURE_ENDPOINT,
                    headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}
                ) as azure_ws:
                    await azure_ws.send_str(json.dumps({
                        "type": "session.update",
                        "session": {"modalities": ["text"], "instructions": system_prompt}
                    }))
                    await azure_ws.send_str(json.dumps({
                        "type": "conversation.item.create",
                        "item": {"type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": user_prompt}]}
                    }))
                    await azure_ws.send_str(json.dumps({"type": "response.create"}))
                    
                    async for msg in azure_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("type") == "response.text.delta":
                                response_text += data.get("delta", "")
                            elif data.get("type") in ["response.done", "error"]:
                                break
            
            # Determine if user seems de-escalated (simple heuristic)
            is_deescalated = False
            if coaching_messages:
                last_user_msg = coaching_messages[-1].get("content", "").lower() if coaching_messages[-1].get("role") == "user" else ""
                calm_indicators = ["okay", "i understand", "you're right", "thank you", "i see", "that helps", "i feel better", "ready"]
                is_deescalated = any(indicator in last_user_msg for indicator in calm_indicators)
            
            # Check if we should offer assisted response
            should_offer_assisted = attempt_number >= 5 and not is_deescalated
            
            self.analytics.record_event("private_coaching_response", member_id, {
                "trigger": trigger,
                "attempt": attempt_number,
                "is_deescalated": is_deescalated
            })
            
            return {
                "success": True,
                "response": response_text,
                "attempt_number": attempt_number,
                "is_deescalated": is_deescalated,
                "should_offer_assisted": should_offer_assisted
            }
            
        except Exception as e:
            print(f">>> [PRIVATE COACHING ERROR] {e}")
            return {
                "success": False,
                "response": f"I'm here with you, {member_name}. Let's take a breath together. What's on your mind?",
                "attempt_number": attempt_number,
                "is_deescalated": False,
                "should_offer_assisted": False
            }


# =============================================================================
# PART 2: REPLACE sanctuary_coaching_accept HANDLER
# Location: Around line 3346, replace the entire elif block
# =============================================================================

            elif t == "sanctuary_coaching_accept":
                """
                Member accepts coaching offer - START private 1-on-1 session
                """
                sanctuary_id = d.get('sanctuary_id')
                intervention_id = d.get('intervention_id')
                wants_assisted_response = d.get('assisted_response', False)
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Check if this is member's first coaching
                member_coaching_count = sanctuary_engine.get_member_coaching_count(
                    sanctuary_id, member_id
                )
                
                # Determine charge
                if member_coaching_count == 0:
                    charge_amount = 0.00
                    is_free = True
                else:
                    charge_amount = 5.00
                    is_free = False
                
                # Charge if not free
                if not is_free:
                    sanctuary = sanctuary_engine.get_session(sanctuary_id)
                    charge_result = await sanctuary_engine.charge_coaching(
                        sanctuary_id=sanctuary_id,
                        intervention_id=intervention_id,
                        member_id=member_id,
                        amount=charge_amount
                    )
                    
                    if not charge_result[0]:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Payment failed. Please try again."
                        }))
                        continue
                
                # Start private coaching session
                coaching_session = sanctuary_engine.start_private_coaching(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    intervention_id=intervention_id
                )
                
                # Get sanctuary data for context
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate initial coaching message
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="coaching_start"
                )
                
                # Store Little Nate's opening message
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="assistant",
                    content=result["response"]
                )
                
                # Increment coaching count
                sanctuary_engine.increment_coaching_count(sanctuary_id, member_id)
                
                # Notify member that coaching started
                free_msg = "🎁 Your first coaching is FREE!" if is_free else f"💰 Coaching: ${charge_amount:.2f}"
                
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_started",
                    "sanctuary_id": sanctuary_id,
                    "intervention_id": intervention_id,
                    "is_free": is_free,
                    "charge_amount": charge_amount,
                    "message": free_msg,
                    "coaching_message": {
                        "role": "assistant",
                        "content": result["response"],
                        "attempt_number": 1
                    }
                }))
                
                # Notify other members that this person is in coaching
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_member_coaching",
                        "member_id": member_id,
                        "member_name": member_name,
                        "message": f"{member_name} is receiving private support from Little Nate. The sanctuary is paused."
                    },
                    exclude_user_id=member_id
                )


# =============================================================================
# PART 3: ADD NEW HANDLER - sanctuary_coaching_message
# Location: Add after sanctuary_coaching_accept handler (around line 3416)
# =============================================================================

            elif t == "sanctuary_coaching_message":
                """
                Member sends message in private coaching session
                """
                sanctuary_id = d.get('sanctuary_id')
                message_content = d.get('message', '')
                
                if not message_content.strip():
                    continue
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Store user's message
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="user",
                    content=message_content
                )
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Increment attempt
                coaching_session["attempt_number"] = coaching_session.get("attempt_number", 0) + 1
                attempt_number = coaching_session["attempt_number"]
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate Little Nate's response
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="coaching_response"
                )
                
                # Store Little Nate's response
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="assistant",
                    content=result["response"]
                )
                
                # Update coaching session
                sanctuary_engine.update_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    updates={
                        "attempt_number": attempt_number,
                        "is_deescalated": result.get("is_deescalated", False)
                    }
                )
                
                # Build response
                response_data = {
                    "type": "sanctuary_coaching_response",
                    "sanctuary_id": sanctuary_id,
                    "coaching_message": {
                        "role": "assistant",
                        "content": result["response"],
                        "attempt_number": attempt_number
                    },
                    "is_deescalated": result.get("is_deescalated", False),
                    "attempts_remaining": max(0, 5 - attempt_number)
                }
                
                # Check if should offer assisted response
                if result.get("should_offer_assisted"):
                    response_data["offer_assisted_response"] = True
                    response_data["assisted_response_cost"] = 3.00
                    response_data["assisted_response_message"] = "Would you like me to help craft a response for you? For $3, I can express your feelings in a way your family can hear."
                
                await websocket.send(json.dumps(response_data))


# =============================================================================
# PART 4: ADD NEW HANDLER - sanctuary_coaching_complete
# Location: Add after sanctuary_coaching_message handler
# =============================================================================

            elif t == "sanctuary_coaching_complete":
                """
                Member ends private coaching and returns to sanctuary
                """
                sanctuary_id = d.get('sanctuary_id')
                request_assisted_response = d.get('request_assisted_response', False)
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                assisted_response = None
                
                # Generate assisted response if requested
                if request_assisted_response:
                    # Charge $3 for assisted response
                    charge_result = await sanctuary_engine.charge_coaching(
                        sanctuary_id=sanctuary_id,
                        intervention_id=coaching_session.get("intervention_id", ""),
                        member_id=member_id,
                        amount=3.00
                    )
                    
                    if charge_result[0]:
                        sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                        
                        result = await cortex.process_private_coaching(
                            member_profile=current_profile,
                            sanctuary_data=sanctuary_data,
                            coaching_session=coaching_session,
                            trigger="generate_assisted_response"
                        )
                        
                        # Parse the assisted response
                        response_text = result.get("response", "")
                        if "SUGGESTED_RESPONSE:" in response_text:
                            parts = response_text.split("SUGGESTED_RESPONSE:")
                            if len(parts) > 1:
                                assisted_part = parts[1]
                                if "EXPLANATION:" in assisted_part:
                                    assisted_response = assisted_part.split("EXPLANATION:")[0].strip()
                                else:
                                    assisted_response = assisted_part.strip()
                        else:
                            assisted_response = response_text
                
                # End the coaching session
                sanctuary_engine.end_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                # Send completion to member
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_completed",
                    "sanctuary_id": sanctuary_id,
                    "message": f"Welcome back, {member_name}. You're ready to reconnect with your family.",
                    "assisted_response": assisted_response
                }))
                
                # Notify sanctuary that member is back
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_member_returned",
                        "member_id": member_id,
                        "member_name": member_name,
                        "message": f"{member_name} has returned to the sanctuary."
                    }
                )
                
                # Check if all coaching sessions are complete
                active_coaching = sanctuary_engine.get_active_coaching_sessions(sanctuary_id)
                if not active_coaching:
                    # All coaching done - sanctuary resumes
                    await sanctuary_engine.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_resumed",
                            "message": "Everyone is back. The sanctuary conversation can continue. 💙"
                        }
                    )


# =============================================================================
# PART 5: ADD NEW HANDLER - sanctuary_request_assisted_response
# Location: Add after sanctuary_coaching_complete handler
# =============================================================================

            elif t == "sanctuary_request_assisted_response":
                """
                Member requests assisted response during coaching (the $3 add-on)
                """
                sanctuary_id = d.get('sanctuary_id')
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Charge $3 for assisted response
                charge_result = await sanctuary_engine.charge_coaching(
                    sanctuary_id=sanctuary_id,
                    intervention_id=coaching_session.get("intervention_id", ""),
                    member_id=member_id,
                    amount=3.00
                )
                
                if not charge_result[0]:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Payment failed. Please try again."
                    }))
                    continue
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate assisted response
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="generate_assisted_response"
                )
                
                # Parse the assisted response
                response_text = result.get("response", "")
                assisted_response = ""
                explanation = ""
                
                if "SUGGESTED_RESPONSE:" in response_text:
                    parts = response_text.split("SUGGESTED_RESPONSE:")
                    if len(parts) > 1:
                        assisted_part = parts[1]
                        if "EXPLANATION:" in assisted_part:
                            split_parts = assisted_part.split("EXPLANATION:")
                            assisted_response = split_parts[0].strip()
                            explanation = split_parts[1].strip() if len(split_parts) > 1 else ""
                        else:
                            assisted_response = assisted_part.strip()
                else:
                    assisted_response = response_text
                
                # Send to member
                await websocket.send(json.dumps({
                    "type": "sanctuary_assisted_response_generated",
                    "sanctuary_id": sanctuary_id,
                    "assisted_response": assisted_response,
                    "explanation": explanation,
                    "charge_amount": 3.00,
                    "message": "Here's a suggested response. You can edit it before sending, or use it as-is."
                }))
