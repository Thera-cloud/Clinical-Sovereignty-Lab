"""
PRIVATE COACHING IMPLEMENTATION - SANCTUARY_ENGINE.PY ADDITIONS
===============================================================
Copy these methods into the FamilySanctuaryEngine class in sanctuary_engine.py

Implementation Date: January 27, 2026
"""

# =============================================================================
# ADD THESE METHODS TO FamilySanctuaryEngine CLASS
# Location: Add after the existing coaching methods (around line 800)
# =============================================================================

    # =========================================================================
    # PRIVATE COACHING SESSION MANAGEMENT
    # =========================================================================
    
    def start_private_coaching(
        self,
        sanctuary_id: str,
        member_id: str,
        intervention_id: str
    ) -> dict:
        """
        Start a private 1-on-1 coaching session for a member
        
        Returns:
            dict: The coaching session data
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {}
        
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if not member:
            return {}
        
        # Find the triggering message (last message from this member before intervention)
        triggering_message = ""
        for msg in reversed(sanctuary.get("messages", [])):
            if msg.get("sender_id") == member_id:
                triggering_message = msg.get("content", "")
                break
        
        # Create coaching session
        coaching_session = {
            "session_id": f"COACH_{sanctuary_id}_{member_id}_{datetime.now().strftime('%H%M%S')}",
            "sanctuary_id": sanctuary_id,
            "member_id": member_id,
            "member_name": member.get("name", "Member"),
            "intervention_id": intervention_id,
            "started_at": datetime.now().isoformat(),
            "triggering_message": triggering_message,
            "messages": [],  # Private conversation with Little Nate
            "attempt_number": 0,
            "is_deescalated": False,
            "assisted_response_generated": False,
            "status": "ACTIVE"
        }
        
        # Store in sanctuary data
        if "coaching_sessions" not in sanctuary:
            sanctuary["coaching_sessions"] = {}
        sanctuary["coaching_sessions"][member_id] = coaching_session
        
        # Update member status
        member["status"] = "IN_COACHING"
        member["current_coaching_session"] = coaching_session["session_id"]
        
        # Update sanctuary status
        sanctuary["status"] = "COACHING_ACTIVE"
        
        self._save()
        
        print(f">>> [COACHING] Started private session for {member.get('name')} in {sanctuary_id}")
        
        return coaching_session
    
    def add_coaching_message(
        self,
        sanctuary_id: str,
        member_id: str,
        role: str,  # "user" or "assistant"
        content: str
    ) -> bool:
        """
        Add a message to the private coaching conversation
        
        Args:
            sanctuary_id: The sanctuary ID
            member_id: The member in coaching
            role: "user" for member, "assistant" for Little Nate
            content: The message content
            
        Returns:
            bool: Success
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        coaching_session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not coaching_session:
            return False
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        coaching_session["messages"].append(message)
        self._save()
        
        return True
    
    def get_coaching_session(
        self,
        sanctuary_id: str,
        member_id: str
    ) -> dict:
        """
        Get the active coaching session for a member
        
        Returns:
            dict: The coaching session data or empty dict
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {}
        
        return sanctuary.get("coaching_sessions", {}).get(member_id, {})
    
    def update_coaching_session(
        self,
        sanctuary_id: str,
        member_id: str,
        updates: dict
    ) -> bool:
        """
        Update coaching session data
        
        Args:
            sanctuary_id: The sanctuary ID
            member_id: The member in coaching
            updates: Dict of fields to update
            
        Returns:
            bool: Success
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        coaching_session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not coaching_session:
            return False
        
        coaching_session.update(updates)
        self._save()
        
        return True
    
    def end_coaching_session(
        self,
        sanctuary_id: str,
        member_id: str
    ) -> bool:
        """
        End a private coaching session and return member to sanctuary
        
        Returns:
            bool: Success
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        coaching_session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not coaching_session:
            return False
        
        # Mark session as complete
        coaching_session["status"] = "COMPLETED"
        coaching_session["ended_at"] = datetime.now().isoformat()
        coaching_session["total_attempts"] = coaching_session.get("attempt_number", 0)
        
        # Update member status
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if member:
            member["status"] = "ACTIVE"
            member["current_coaching_session"] = None
            member["coaching_received"] = member.get("coaching_received", 0) + 1
        
        # Check if any other members are still in coaching
        active_coaching = self.get_active_coaching_sessions(sanctuary_id)
        if not active_coaching:
            sanctuary["status"] = "ACTIVE"
        
        # Record analytics
        self._record_analytics("coaching_session_completed", member_id, {
            "sanctuary_id": sanctuary_id,
            "total_attempts": coaching_session["total_attempts"],
            "is_deescalated": coaching_session.get("is_deescalated", False),
            "assisted_response_generated": coaching_session.get("assisted_response_generated", False)
        })
        
        self._save()
        
        print(f">>> [COACHING] Ended session for member {member_id} in {sanctuary_id}")
        
        return True
    
    def get_active_coaching_sessions(self, sanctuary_id: str) -> list:
        """
        Get all active coaching sessions in a sanctuary
        
        Returns:
            list: List of active coaching session dicts
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return []
        
        active = []
        for member_id, session in sanctuary.get("coaching_sessions", {}).items():
            if session.get("status") == "ACTIVE":
                active.append(session)
        
        return active
    
    def can_send_sanctuary_message(self, sanctuary_id: str, member_id: str) -> tuple:
        """
        Check if a member can send messages to the sanctuary
        
        Returns:
            tuple: (can_send: bool, reason: str)
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False, "Sanctuary not found"
        
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if not member:
            return False, "Not a member of this sanctuary"
        
        # Check if member is in coaching
        if member.get("status") == "IN_COACHING":
            return False, "You are in private coaching. Complete coaching to return."
        
        # Check if sanctuary is paused for coaching
        if sanctuary.get("status") == "COACHING_ACTIVE":
            # Only block if THIS member is not the one in coaching
            active_sessions = self.get_active_coaching_sessions(sanctuary_id)
            for session in active_sessions:
                if session.get("member_id") == member_id:
                    return False, "Complete your coaching session first."
            
            # Other members can still see messages but sanctuary is technically paused
            # We'll allow messages but show a notice
            return True, "Sanctuary is paused - some members are in coaching."
        
        return True, "OK"
    
    def get_member_coaching_count(self, sanctuary_id: str, member_id: str) -> int:
        """
        Get how many coaching sessions a member has received in this sanctuary
        
        Returns:
            int: Number of coaching sessions
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return 0
        
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if not member:
            return 0
        
        return member.get("coaching_received", 0)
    
    def increment_coaching_count(self, sanctuary_id: str, member_id: str) -> bool:
        """
        Increment the coaching count for a member
        Note: This is now called when coaching STARTS, not ends
        
        Returns:
            bool: Success
        """
        # This is handled in end_coaching_session now
        # But keep for backwards compatibility
        return True


# =============================================================================
# UPDATE THE EXISTING add_message METHOD
# Replace the existing add_message method to check coaching status
# =============================================================================

    async def add_message(
        self,
        sanctuary_id: str,
        sender_id: str,
        content: str,
        message_type: str = "MEMBER_MESSAGE"
    ) -> str:
        """
        Add a message to the sanctuary - WITH COACHING CHECK
        
        Returns:
            str: message_id or empty string if blocked
        """
        # Check if member can send
        can_send, reason = self.can_send_sanctuary_message(sanctuary_id, sender_id)
        
        if not can_send:
            print(f">>> [SANCTUARY] Message blocked for {sender_id}: {reason}")
            return ""
        
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return ""
        
        member = next((m for m in sanctuary["members"] if m["user_id"] == sender_id), None)
        sender_name = member.get("name", "Unknown") if member else "Little Nate"
        
        message_id = f"MSG_{len(sanctuary.get('messages', [])) + 1}"
        
        message = {
            "message_id": message_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "content": content,
            "message_type": message_type,
            "timestamp": datetime.now().isoformat()
        }
        
        if "messages" not in sanctuary:
            sanctuary["messages"] = []
        sanctuary["messages"].append(message)
        
        # Update metrics
        sanctuary["metrics"]["total_messages"] = sanctuary["metrics"].get("total_messages", 0) + 1
        
        self._save()
        
        return message_id
