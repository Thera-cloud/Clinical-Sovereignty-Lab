"""
ADD THIS METHOD TO AzureCortex CLASS IN bridge_server.py
Location: After process_sanctuary_message method (around line 1565)
"""

    async def process_private_coaching(
        self,
        member_profile: dict,
        sanctuary_data: dict,
        coaching_session: dict,
        trigger: str = "coaching_start"
    ) -> dict:
        """Process private 1-on-1 coaching session with Little Nate"""
        print(f">>> [PRIVATE COACHING] {trigger} for {member_profile.get('name')}")
        
        member_name = member_profile.get("name", "Friend")
        member_id = member_profile.get("hardware_id")
        
        memory = self.mem.recall(member_profile, limit=5)
        metrics = self.metrics.load_metrics(member_profile)
        
        attempt_number = coaching_session.get("attempt_number", 1)
        coaching_messages = coaching_session.get("messages", [])
        triggering_message = coaching_session.get("triggering_message", "")
        
        private_convo = "\n".join([f"{'Little Nate' if m.get('role')=='assistant' else member_name}: {m.get('content','')}" for m in coaching_messages[-6:]])
        sanctuary_convo = "\n".join([f"{m.get('sender_name','?')}: {m.get('content','')}" for m in sanctuary_data.get("messages", [])[-10:]])
        
        if trigger == "coaching_start":
            user_prompt = f"FIRST message to {member_name}. Context:\n{sanctuary_convo}\n\nTriggering: \"{triggering_message}\"\n\n1. Acknowledge feelings warmly\n2. Reframe - what's underneath the anger?\n3. Ask first curiosity question"
        elif trigger == "coaching_response":
            user_prompt = f"Continue coaching {member_name}. Attempt {attempt_number}/5.\n\nConvo:\n{private_convo}\n\nAttempt 1-2: curiosity. 3: validate. 4: de-escalation. 5: check readiness or offer assisted response."
        elif trigger == "generate_assisted_response":
            user_prompt = f"Generate assisted response for {member_name}.\n\nPrivate (CONFIDENTIAL):\n{private_convo}\n\nSanctuary:\n{sanctuary_convo}\n\nUse 'I feel' statements. NO private details.\n\nFormat:\nSUGGESTED_RESPONSE: [message]\nEXPLANATION: [why]"
        else:
            user_prompt = f"Continue supporting {member_name}."

        system_prompt = f"You are Little Nate, PRIVATE coaching {member_name}. CONFIDENTIAL. Mood: {metrics.get('current_mood','distressed')}. Be warm, curious, compassionate. Help them de-escalate and find their words."

        try:
            import aiohttp
            response_text = ""
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(AZURE_ENDPOINT, headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}) as azure_ws:
                    await azure_ws.send_str(json.dumps({"type": "session.update", "session": {"modalities": ["text"], "instructions": system_prompt}}))
                    await azure_ws.send_str(json.dumps({"type": "conversation.item.create", "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": user_prompt}]}}))
                    await azure_ws.send_str(json.dumps({"type": "response.create"}))
                    async for msg in azure_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("type") == "response.text.delta": response_text += data.get("delta", "")
                            elif data.get("type") in ["response.done", "error"]: break
            
            is_deescalated = False
            if coaching_messages:
                user_msgs = [m for m in coaching_messages if m.get("role") == "user"]
                if user_msgs:
                    last = user_msgs[-1].get("content", "").lower()
                    is_deescalated = any(w in last for w in ["okay", "understand", "right", "thank", "better", "ready", "calmer", "helps"])
            
            return {"success": True, "response": response_text, "attempt_number": attempt_number, "is_deescalated": is_deescalated, "should_offer_assisted": attempt_number >= 5 and not is_deescalated}
        except Exception as e:
            print(f">>> [COACHING ERROR] {e}")
            return {"success": False, "response": f"I'm here, {member_name}. What's on your mind?", "attempt_number": attempt_number, "is_deescalated": False, "should_offer_assisted": False}
