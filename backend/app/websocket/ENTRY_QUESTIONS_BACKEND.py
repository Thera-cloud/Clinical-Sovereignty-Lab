"""
===============================================================================
ENTRY QUESTIONS & SESSION GOALS - BACKEND IMPLEMENTATION
===============================================================================
Add these handlers to bridge_server.py and methods to sanctuary_engine.py
Implementation Date: January 27, 2026
===============================================================================
"""

# =============================================================================
# PART 1: ADD TO sanctuary_engine.py - Session Goals Methods
# Add these methods to FamilySanctuaryEngine class
# =============================================================================

    # =========================================================================
    # SESSION GOALS & ONBOARDING
    # =========================================================================
    
    def needs_onboarding(self, sanctuary_id: str, member_id: str) -> bool:
        """Check if member needs to complete entry questions"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return True
        
        session_goals = sanctuary.get("session_goals", {})
        member_goals = session_goals.get(member_id, {})
        
        return not member_goals.get("completed_onboarding", False)
    
    def store_member_goals(
        self,
        sanctuary_id: str,
        member_id: str,
        what_happened: str,
        personal_goal: str,
        what_other_needs_to_know: str
    ) -> bool:
        """Store member's entry question responses (CONFIDENTIAL)"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        if "session_goals" not in sanctuary:
            sanctuary["session_goals"] = {}
        
        sanctuary["session_goals"][member_id] = {
            "completed_onboarding": True,
            "what_happened": what_happened,
            "personal_goal": personal_goal,
            "what_other_needs_to_know": what_other_needs_to_know,
            "submitted_at": datetime.now().isoformat()
        }
        
        # Update member status
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if member:
            member["onboarding_complete"] = True
        
        self._save()
        print(f">>> [SANCTUARY] Stored goals for {member_id}")
        return True
    
    def get_member_goals(self, sanctuary_id: str, member_id: str) -> dict:
        """Get a member's session goals (for reconnect)"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {}
        
        return sanctuary.get("session_goals", {}).get(member_id, {})
    
    def all_members_onboarded(self, sanctuary_id: str) -> bool:
        """Check if all members have completed entry questions"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        session_goals = sanctuary.get("session_goals", {})
        
        for member in sanctuary.get("members", []):
            member_id = member.get("user_id")
            if not session_goals.get(member_id, {}).get("completed_onboarding", False):
                return False
        
        return len(sanctuary.get("members", [])) > 0
    
    async def start_session_after_onboarding(self, sanctuary_id: str):
        """Called when all members complete onboarding - Little Nate opens session"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return
        
        sanctuary["status"] = "ACTIVE"
        sanctuary["session_started_at"] = datetime.now().isoformat()
        self._save()
        
        # Generate Little Nate's opening message using goals (without revealing specifics)
        if self.azure_cortex:
            try:
                # Build context from goals (themes only, not specifics)
                goal_themes = []
                for member_id, goals in sanctuary.get("session_goals", {}).items():
                    member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
                    if member:
                        goal_themes.append(f"{member.get('name', 'Member')} wants: {goals.get('personal_goal', 'to communicate better')[:50]}")
                
                profiles = self._get_family_profiles_from_registry(sanctuary)
                
                result = await self.azure_cortex.process_sanctuary_message(
                    sanctuary_data=sanctuary,
                    family_profiles=profiles,
                    recent_messages=[],
                    trigger="session_start"
                )
                
                if result.get("success"):
                    opening_msg = {
                        "message_id": f"LN_OPEN_{sanctuary_id}",
                        "message_type": "LITTLE_NATE",
                        "sender_id": "LITTLE_NATE",
                        "sender_name": "Little Nate",
                        "content": result.get("response", "Welcome to Family Sanctuary. This is a safe space. Who would like to start? 💙"),
                        "timestamp": datetime.now().isoformat()
                    }
                    sanctuary["messages"].append(opening_msg)
                    self._save()
                    
                    # Broadcast session started
                    await self.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_session_started",
                            "message": "Session has begun. 💙"
                        }
                    )
                    
                    # Broadcast Little Nate's opening
                    await self.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_message",
                            "message_type": "LITTLE_NATE",
                            "sender_id": "LITTLE_NATE",
                            "sender_name": "Little Nate",
                            "content": opening_msg["content"],
                            "timestamp": opening_msg["timestamp"]
                        }
                    )
            except Exception as e:
                print(f">>> [SANCTUARY] Opening message error: {e}")
                # Send basic opening
                await self.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_session_started",
                        "message": "Session has begun. 💙"
                    }
                )
    
    def clear_session_goals(self, sanctuary_id: str):
        """Clear goals when session is marked complete (for new session next time)"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return
        
        sanctuary["session_goals"] = {}
        for member in sanctuary.get("members", []):
            member["onboarding_complete"] = False
        
        self._save()


# =============================================================================
# PART 2: ADD TO bridge_server.py - WebSocket Handlers
# Add these handler cases in handle_client() after sanctuary_get_or_create
# =============================================================================

            elif t == "sanctuary_submit_onboarding":
                """Member submits entry question responses"""
                sanctuary_id = d.get('sanctuary_id')
                responses = d.get('responses', {})
                member_id = current_profile['hardware_id']
                
                # Store goals (confidential)
                sanctuary_engine.store_member_goals(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    what_happened=responses.get('what_happened', ''),
                    personal_goal=responses.get('personal_goal', ''),
                    what_other_needs_to_know=responses.get('what_other_needs_to_know', '')
                )
                
                # Confirm to member
                await websocket.send(json.dumps({
                    "type": "sanctuary_onboarding_complete",
                    "message": "Thank you for sharing. Your goals are saved. 💙"
                }))
                
                # Notify other members that this person is ready
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_member_ready",
                        "member_id": member_id,
                        "member_name": current_profile.get('name', 'Member')
                    },
                    exclude_user_id=member_id
                )
                
                # Check if all members are ready
                if sanctuary_engine.all_members_onboarded(sanctuary_id):
                    # Start the session!
                    await sanctuary_engine.start_session_after_onboarding(sanctuary_id)


# =============================================================================
# PART 3: UPDATE sanctuary_get_or_create handler
# Modify the existing handler to check for onboarding
# =============================================================================

            elif t == "sanctuary_get_or_create":
                """Get existing sanctuary or create new one"""
                family_id = d.get('family_id')
                member_id = d.get('member_id')
                member_name = d.get('member_name')
                
                print(f">>> [SANCTUARY] Processing get_or_create for {member_name} ({member_id}) in family {family_id}")
                
                result = await sanctuary_engine.get_or_create_session(
                    family_id=family_id,
                    head_of_household_id=member_id if d.get('is_hoh', False) else None
                )
                
                sanctuary_id = result.get("sanctuary_id")
                action = result.get("action")
                
                # Add/reconnect member
                member_result = await sanctuary_engine.add_or_reconnect_member(
                    sanctuary_id=sanctuary_id,
                    user_id=member_id,
                    name=member_name,
                    websocket=websocket
                )
                
                action = member_result.get("action", action)
                print(f">>> [SANCTUARY] Member {member_name} {action} to {sanctuary_id}")
                
                # Register websocket
                sanctuary_engine.register_websocket(sanctuary_id, member_id, websocket)
                
                # Get current state
                sanctuary = sanctuary_engine.get_session(sanctuary_id)
                members = sanctuary.get("members", [])
                messages = sanctuary.get("messages", [])[-50:]  # Last 50 messages
                
                # Check if member needs onboarding
                needs_onboarding = sanctuary_engine.needs_onboarding(sanctuary_id, member_id)
                existing_goals = sanctuary_engine.get_member_goals(sanctuary_id, member_id)
                
                # Check if session has started (all onboarded)
                session_started = sanctuary.get("status") == "ACTIVE" and sanctuary.get("session_started_at")
                
                if action in ["RECONNECTED", "REFRESHED", "RETURNED"]:
                    await websocket.send(json.dumps({
                        "type": "sanctuary_reconnected",
                        "sanctuary_id": sanctuary_id,
                        "status": sanctuary.get("status", "ACTIVE"),
                        "members": members,
                        "messages": messages,
                        "needs_onboarding": needs_onboarding,
                        "existing_goals": existing_goals,
                        "session_started": session_started,
                        "total_charges": sanctuary.get("billing", {}).get("total_charges", 0),
                        "message": f"Welcome back, {member_name}!"
                    }))
                else:
                    await websocket.send(json.dumps({
                        "type": "sanctuary_joined",
                        "sanctuary_id": sanctuary_id,
                        "status": sanctuary.get("status", "WAITING"),
                        "members": members,
                        "needs_onboarding": True,  # New members always need onboarding
                        "total_charges": sanctuary.get("billing", {}).get("total_charges", 0),
                        "message": f"Welcome to Family Sanctuary, {member_name}!"
                    }))
                
                # Notify others of join/return
                if action in ["JOINED", "RETURNED"]:
                    await sanctuary_engine.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_member_joined" if action == "JOINED" else "sanctuary_member_returned",
                            "member_id": member_id,
                            "member_name": member_name,
                            "members": members
                        },
                        exclude_user_id=member_id
                    )


# =============================================================================
# PART 4: UPDATE process_sanctuary_message for session_start trigger
# Add this case to the trigger handling in AzureCortex.process_sanctuary_message
# =============================================================================

# In the system_prompt building section, add handling for session_start:

        if trigger == "session_start":
            system_prompt = f"""You are Little Nate, the Quantum Observer - an empathetic AI family therapist.

FAMILY SANCTUARY SESSION BEGINNING
Topic: {topic}

FAMILY MEMBERS:
{family_context}

WISDOM:
{wisdom_text}

YOUR ROLE FOR SESSION_START:
- Welcome everyone warmly
- Acknowledge this takes courage
- Set a safe, non-judgmental tone
- Gently invite someone to share first
- Do NOT reveal anyone's private goals
- Keep it brief (2-3 sentences)

Remember: You have insight from their entry questions but must NOT reveal specifics.
You can reference THEMES without quoting anyone."""
