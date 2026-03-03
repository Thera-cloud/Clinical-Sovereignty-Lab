# =============================================================================
# FAMILY SANCTUARY - ENHANCED COACHING FLOW v2.0
# =============================================================================
#
# COMPLIANT WITH:
# - FAMILY_SANCTUARY_SPEC.md (billing, intervention types, modalities)
# - LITTLE_NATE_INTEGRATION_GUIDE.md (The Eye, Nevedal, Night School)
# - DATA_SOURCE_MAPPING_V2.md (data flows, storage)
# - ANALYTICS_AND_CRISIS_PROTOCOL.md (P0/P1/P2 crisis levels)
# - CURSOR_PROJECT_STRUCTURE.md (service-based architecture)
#
# BILLING STRUCTURE (per FAMILY_SANCTUARY_SPEC lines 583-588):
# - $20.00 base fee at session creation
# - First coaching per member: FREE
# - Subsequent coaching: $5.00
# - Assisted response add-on: +$3.00
# - All charges billed to HEAD OF HOUSEHOLD's Stripe account
#
# =============================================================================

from datetime import datetime
from typing import Optional, Dict, List, Any
from pathlib import Path
import json

# =============================================================================
# PART 1: COACHING STATE DATA STRUCTURE
# Add this to sanctuary data in create_sanctuary()
# =============================================================================

COACHING_STATE_TEMPLATE = {
    "status": "NORMAL",  # NORMAL, COACHING_ACTIVE, RESUMING
    "active_sessions": {},  # user_id -> CoachingSession
    "pending_offers": {},   # user_id -> CoachingOffer
    "completed_sessions": [],  # List of completed sessions for synthesis
    "synthesis_ready": False,
    "last_escalation_at": None
}

# Per FAMILY_SANCTUARY_SPEC lines 1421-1429
INTERVENTION_TYPES = [
    "PERSPECTIVE_TAKING",
    "GROUNDING", 
    "EMOTION_REGULATION",
    "RESPONSE_GUIDANCE",
    "ASSISTED_RESPONSE",
    "CONFLICT_MEDIATION",
    "GRIEF_SUPPORT"
]

# Per FAMILY_SANCTUARY_SPEC lines 1432-1438
MODALITIES = [
    "FAMILY_SYSTEMS",
    "EFT",
    "IFS", 
    "LEGACY_WORK",
    "GENERAL"
]


# =============================================================================
# PART 2: SANCTUARY ENGINE METHODS
# Add these methods to FamilySanctuaryEngine class in sanctuary_engine.py
# =============================================================================

class FamilySanctuaryCoachingMixin:
    """
    Mixin class for coaching functionality.
    Add these methods to FamilySanctuaryEngine.
    """
    
    async def offer_coaching_to_all(
        self,
        sanctuary_id: str,
        trigger_message_id: str,
        trigger_user_id: str,
        detected_emotion: str = "distress",
        intervention_type: str = "EMOTION_REGULATION",
        modality: str = "FAMILY_SYSTEMS"
    ) -> dict:
        """
        Offer coaching to ALL family members when escalation detected.
        
        Per FAMILY_SANCTUARY_SPEC:
        - First coaching per member is FREE
        - Subsequent coaching is $5.00
        - Assisted response adds $3.00
        
        Integration points (per LITTLE_NATE_INTEGRATION_GUIDE):
        - Records to analytics.json via AnalyticsEngine
        - Loads Nevedal metrics for each member
        - Uses Night School wisdom for intervention type selection
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        # Generate intervention ID
        interventions = sanctuary.get("interventions", [])
        intervention_id = f"INT_{len(interventions) + 1:03d}"
        
        # Initialize coaching_state if not present
        if "coaching_state" not in sanctuary:
            sanctuary["coaching_state"] = COACHING_STATE_TEMPLATE.copy()
            sanctuary["coaching_state"]["active_sessions"] = {}
            sanctuary["coaching_state"]["pending_offers"] = {}
            sanctuary["coaching_state"]["completed_sessions"] = []
        
        members_offered = []
        
        for member in sanctuary["members"]:
            user_id = member["user_id"]
            user_name = member["name"]
            
            # Check if first coaching (per spec: free_coaching_used field)
            is_first_coaching = not member.get("free_coaching_used", False)
            
            # Build offer per FAMILY_SANCTUARY_SPEC lines 1446-1450
            offer = {
                "intervention_id": intervention_id,
                "user_id": user_id,
                "user_name": user_name,
                "is_free": is_first_coaching,
                "base_cost": 0.00 if is_first_coaching else 5.00,
                "assisted_cost": 3.00,  # Additional if they want assisted response
                "offered_at": datetime.now().isoformat(),
                "status": "PENDING",  # PENDING, ACCEPTED, DECLINED, EXPIRED
                "is_trigger_member": user_id == trigger_user_id,
                "intervention_type": intervention_type,
                "modality": modality,
                "detected_emotion": detected_emotion
            }
            
            sanctuary["coaching_state"]["pending_offers"][user_id] = offer
            members_offered.append(offer)
        
        # Record intervention per FAMILY_SANCTUARY_SPEC lines 1414-1460
        sanctuary["interventions"] = interventions
        sanctuary["interventions"].append({
            "intervention_id": intervention_id,
            "triggered_by_message_id": trigger_message_id,
            "triggered_by_user_id": trigger_user_id,
            "intervention_type": intervention_type,
            "modality": modality,
            "offered_to_all": True,
            "created_at": datetime.now().isoformat(),
            "member_responses": {}  # Will track who accepted/declined
        })
        
        sanctuary["coaching_state"]["last_escalation_at"] = datetime.now().isoformat()
        
        self._save()
        
        # Record analytics per LITTLE_NATE_INTEGRATION_GUIDE
        # The Eye: Track coaching offer event
        self._record_analytics("sanctuary_coaching_offered", trigger_user_id, {
            "sanctuary_id": sanctuary_id,
            "intervention_id": intervention_id,
            "members_offered": len(members_offered),
            "intervention_type": intervention_type
        })
        
        return {
            "success": True,
            "intervention_id": intervention_id,
            "offers": members_offered
        }
    
    
    async def accept_coaching(
        self,
        sanctuary_id: str,
        user_id: str,
        intervention_id: str,
        wants_assisted_response: bool = False
    ) -> dict:
        """
        Member accepts coaching offer. Enters private 1-on-1 with Little Nate.
        
        BILLING (per FAMILY_SANCTUARY_SPEC lines 583-588):
        - Charges go to HEAD OF HOUSEHOLD's Stripe account
        - First coaching: FREE
        - Subsequent: $5.00 base + $3.00 if assisted
        
        INTEGRATION:
        - The Eye: Record transaction
        - Nevedal: Load member's emotional metrics for personalized coaching
        - Night School: Load relevant wisdom for intervention type
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        pending = coaching_state.get("pending_offers", {}).get(user_id)
        
        if not pending:
            return {"success": False, "error": "No pending coaching offer for this user"}
        
        if pending["status"] != "PENDING":
            return {"success": False, "error": f"Offer already {pending['status'].lower()}"}
        
        # Calculate costs
        base_cost = pending["base_cost"]
        assisted_cost = pending["assisted_cost"] if wants_assisted_response else 0.00
        total_cost = base_cost + assisted_cost
        is_free = pending["is_free"]
        
        # BILLING: Charge HEAD OF HOUSEHOLD (per spec line 588)
        hoh_id = sanctuary.get("head_of_household_id")
        
        if total_cost > 0 and self.billing:
            charge_result = await self._charge_coaching_to_hoh(
                sanctuary_id=sanctuary_id,
                hoh_id=hoh_id,
                member_id=user_id,
                amount=total_cost,
                intervention_id=intervention_id,
                is_assisted=wants_assisted_response
            )
            
            if not charge_result.get("success"):
                return {"success": False, "error": "Payment failed - please check billing details"}
        
        # Update offer status
        pending["status"] = "ACCEPTED"
        pending["accepted_at"] = datetime.now().isoformat()
        pending["wants_assisted_response"] = wants_assisted_response
        pending["total_charged"] = total_cost
        
        # Create active coaching session
        session = {
            "user_id": user_id,
            "user_name": pending["user_name"],
            "intervention_id": intervention_id,
            "intervention_type": pending["intervention_type"],
            "modality": pending["modality"],
            "started_at": datetime.now().isoformat(),
            "messages": [],
            "wants_assisted_response": wants_assisted_response,
            "assisted_response_draft": None,
            "cost_charged": total_cost,
            "is_free": is_free,
            "status": "ACTIVE",
            "nevedal_at_start": None,  # Will be populated by Nevedal integration
            "nevedal_at_end": None
        }
        
        # Load Nevedal metrics for this member (per LITTLE_NATE_INTEGRATION_GUIDE)
        if self.nevedal_handler:
            try:
                member_profile = self._get_member_profile(sanctuary, user_id)
                if member_profile:
                    nevedal_metrics = self.nevedal_handler.get_metrics(member_profile)
                    session["nevedal_at_start"] = {
                        "c_emo": nevedal_metrics.get("coherence"),
                        "anxiety": nevedal_metrics.get("anxiety_level"),
                        "risk_level": nevedal_metrics.get("risk_level"),
                        "mood": nevedal_metrics.get("current_mood")
                    }
            except Exception as e:
                print(f">>> [SANCTUARY] Nevedal load error: {e}")
        
        coaching_state["active_sessions"][user_id] = session
        coaching_state["status"] = "COACHING_ACTIVE"
        
        # Update member record
        member = next((m for m in sanctuary["members"] if m["user_id"] == user_id), None)
        if member:
            # Track free coaching used (per spec line 1369)
            if is_free:
                member["free_coaching_used"] = True
            
            # Increment coaching count (per spec line 1368)
            member["coaching_received_count"] = member.get("coaching_received_count", 0) + 1
            
            # Track charges for this member (per spec line 1370)
            member["total_charges_incurred"] = member.get("total_charges_incurred", 0.0) + total_cost
            
            # Add to coaching history
            if "coaching_history" not in member:
                member["coaching_history"] = []
            member["coaching_history"].append({
                "intervention_id": intervention_id,
                "started_at": session["started_at"],
                "cost": total_cost,
                "is_free": is_free
            })
        
        # Update sanctuary totals
        sanctuary["metrics"]["coaching_interventions"] = sanctuary["metrics"].get("coaching_interventions", 0) + 1
        sanctuary["total_charges"] = sanctuary.get("total_charges", 20.0) + total_cost
        
        # Update intervention record
        intervention = next((i for i in sanctuary["interventions"] if i["intervention_id"] == intervention_id), None)
        if intervention:
            intervention["member_responses"][user_id] = {
                "action": "ACCEPTED",
                "timestamp": datetime.now().isoformat(),
                "cost": total_cost
            }
        
        self._save()
        
        # Record analytics (The Eye)
        self._record_analytics("sanctuary_coaching_accepted", user_id, {
            "sanctuary_id": sanctuary_id,
            "intervention_id": intervention_id,
            "cost": total_cost,
            "is_free": is_free,
            "wants_assisted": wants_assisted_response,
            "intervention_type": pending["intervention_type"]
        })
        
        return {
            "success": True,
            "session": session,
            "total_cost": total_cost,
            "is_free": is_free,
            "intervention_type": pending["intervention_type"],
            "modality": pending["modality"]
        }
    
    
    async def decline_coaching(
        self,
        sanctuary_id: str,
        user_id: str
    ) -> dict:
        """Member declines coaching offer"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        pending = coaching_state.get("pending_offers", {}).get(user_id)
        
        if pending and pending["status"] == "PENDING":
            pending["status"] = "DECLINED"
            pending["declined_at"] = datetime.now().isoformat()
            
            # Update intervention record
            intervention_id = pending["intervention_id"]
            intervention = next((i for i in sanctuary.get("interventions", []) 
                               if i["intervention_id"] == intervention_id), None)
            if intervention:
                intervention["member_responses"][user_id] = {
                    "action": "DECLINED",
                    "timestamp": datetime.now().isoformat()
                }
            
            self._save()
            
            # Check if all members have responded
            await self._check_all_responded(sanctuary_id)
        
        return {"success": True}
    
    
    async def add_coaching_message(
        self,
        sanctuary_id: str,
        user_id: str,
        content: str,
        is_from_nate: bool = False
    ) -> dict:
        """
        Add message to private coaching session.
        
        INTEGRATION:
        - Messages stored per session
        - If from member, triggers Little Nate response
        - Night School wisdom used for responses
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        session = coaching_state.get("active_sessions", {}).get(user_id)
        
        if not session:
            return {"success": False, "error": "No active coaching session"}
        
        message = {
            "message_id": f"COACH_{len(session['messages']) + 1:03d}",
            "sender": "LITTLE_NATE" if is_from_nate else user_id,
            "sender_name": "Little Nate" if is_from_nate else session["user_name"],
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "is_private": True
        }
        
        session["messages"].append(message)
        self._save()
        
        return {"success": True, "message": message}
    
    
    async def complete_coaching_session(
        self,
        sanctuary_id: str,
        user_id: str,
        summary: str = None,
        assisted_response_draft: str = None
    ) -> dict:
        """
        Complete a coaching session.
        
        POST-COACHING:
        - Record Nevedal metrics at end
        - Generate synthesis if all sessions complete
        - Store assisted response if requested
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        session = coaching_state.get("active_sessions", {}).get(user_id)
        
        if not session:
            return {"success": False, "error": "No active coaching session"}
        
        # Record Nevedal at end (per LITTLE_NATE_INTEGRATION_GUIDE)
        if self.nevedal_handler:
            try:
                member_profile = self._get_member_profile(sanctuary, user_id)
                if member_profile:
                    nevedal_metrics = self.nevedal_handler.get_metrics(member_profile)
                    session["nevedal_at_end"] = {
                        "c_emo": nevedal_metrics.get("coherence"),
                        "anxiety": nevedal_metrics.get("anxiety_level"),
                        "risk_level": nevedal_metrics.get("risk_level"),
                        "mood": nevedal_metrics.get("current_mood")
                    }
            except Exception as e:
                print(f">>> [SANCTUARY] Nevedal end error: {e}")
        
        # Complete the session
        session["status"] = "COMPLETED"
        session["completed_at"] = datetime.now().isoformat()
        session["summary"] = summary
        session["assisted_response_draft"] = assisted_response_draft
        session["message_count"] = len(session["messages"])
        
        # Calculate effectiveness (C_emo improvement)
        if session.get("nevedal_at_start") and session.get("nevedal_at_end"):
            start_cemo = self._parse_cemo(session["nevedal_at_start"].get("c_emo"))
            end_cemo = self._parse_cemo(session["nevedal_at_end"].get("c_emo"))
            if start_cemo and end_cemo:
                session["effectiveness_rating"] = round(end_cemo - start_cemo, 2)
        
        # Move to completed
        coaching_state["completed_sessions"].append(session)
        del coaching_state["active_sessions"][user_id]
        
        # Check if all coaching complete
        all_complete = len(coaching_state["active_sessions"]) == 0
        pending_count = sum(1 for o in coaching_state.get("pending_offers", {}).values() 
                          if o["status"] == "PENDING")
        
        if all_complete and pending_count == 0:
            coaching_state["status"] = "RESUMING"
            coaching_state["synthesis_ready"] = True
        
        self._save()
        
        # Record analytics
        self._record_analytics("sanctuary_coaching_completed", user_id, {
            "sanctuary_id": sanctuary_id,
            "intervention_id": session["intervention_id"],
            "message_count": session["message_count"],
            "effectiveness": session.get("effectiveness_rating")
        })
        
        return {
            "success": True,
            "all_complete": all_complete,
            "pending_offers": pending_count,
            "ready_to_resume": coaching_state["status"] == "RESUMING",
            "assisted_response": assisted_response_draft
        }
    
    
    async def get_coaching_synthesis(
        self,
        sanctuary_id: str
    ) -> dict:
        """
        Generate synthesis of all coaching sessions for family reunion.
        
        Little Nate uses insights from each private conversation to:
        - Find common ground
        - Identify shared concerns
        - Suggest path forward
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        completed = coaching_state.get("completed_sessions", [])
        
        if not completed:
            return {"success": False, "error": "No completed coaching sessions"}
        
        # Build synthesis data
        synthesis = {
            "member_count": len(completed),
            "total_messages": sum(s.get("message_count", 0) for s in completed),
            "modalities_used": list(set(s.get("modality", "GENERAL") for s in completed)),
            "intervention_types": list(set(s.get("intervention_type", "GENERAL") for s in completed)),
            "sessions": [],
            "overall_effectiveness": None
        }
        
        effectiveness_scores = []
        
        for session in completed:
            session_summary = {
                "user_name": session["user_name"],
                "started_at": session["started_at"],
                "completed_at": session.get("completed_at"),
                "message_count": session.get("message_count", 0),
                "effectiveness": session.get("effectiveness_rating"),
                "summary": session.get("summary"),
                "nevedal_improvement": None
            }
            
            # Calculate Nevedal improvement
            if session.get("nevedal_at_start") and session.get("nevedal_at_end"):
                start = self._parse_cemo(session["nevedal_at_start"].get("c_emo"))
                end = self._parse_cemo(session["nevedal_at_end"].get("c_emo"))
                if start and end:
                    session_summary["nevedal_improvement"] = round((end - start) * 100, 1)
            
            if session.get("effectiveness_rating"):
                effectiveness_scores.append(session["effectiveness_rating"])
            
            synthesis["sessions"].append(session_summary)
        
        if effectiveness_scores:
            synthesis["overall_effectiveness"] = round(sum(effectiveness_scores) / len(effectiveness_scores), 2)
        
        return {
            "success": True,
            "synthesis": synthesis
        }
    
    
    async def resume_sanctuary(
        self,
        sanctuary_id: str
    ) -> dict:
        """Resume sanctuary after all coaching is complete"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        coaching_state = sanctuary.get("coaching_state", {})
        
        # Reset for next potential escalation
        coaching_state["status"] = "NORMAL"
        coaching_state["pending_offers"] = {}
        coaching_state["synthesis_ready"] = False
        # Keep completed_sessions for history
        
        self._save()
        
        return {"success": True}
    
    
    def can_send_message(self, sanctuary_id: str, user_id: str) -> tuple:
        """
        Check if a user can send a message in the sanctuary.
        
        Returns: (can_send: bool, reason: str or None)
        - If in COACHING_ACTIVE, only users in coaching sessions can message
        - Others see "sanctuary paused" message
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return (False, "Sanctuary not found")
        
        coaching_state = sanctuary.get("coaching_state", {})
        status = coaching_state.get("status", "NORMAL")
        
        if status == "NORMAL":
            return (True, None)
        
        if status == "COACHING_ACTIVE":
            # Check if user is in active coaching
            if user_id in coaching_state.get("active_sessions", {}):
                return (True, "coaching")  # Route to coaching handler
            
            # Check if user has pending offer
            pending = coaching_state.get("pending_offers", {}).get(user_id)
            if pending and pending["status"] == "PENDING":
                return (False, "Please accept or decline the coaching offer to continue")
            
            return (False, "Sanctuary paused while family members receive coaching. You can accept coaching or wait.")
        
        if status == "RESUMING":
            return (False, "Sanctuary resuming shortly...")
        
        return (True, None)
    
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    async def _charge_coaching_to_hoh(
        self,
        sanctuary_id: str,
        hoh_id: str,
        member_id: str,
        amount: float,
        intervention_id: str,
        is_assisted: bool
    ) -> dict:
        """
        Charge coaching fee to Head of Household's Stripe account.
        Per FAMILY_SANCTUARY_SPEC line 588.
        """
        if not self.billing:
            print(f">>> [SANCTUARY BILLING] No billing system - skipping ${amount:.2f} charge")
            return {"success": True, "charged": False}
        
        try:
            description = f"Family Sanctuary coaching - {intervention_id}"
            if is_assisted:
                description += " (with assisted response)"
            
            result = self.billing.record_transaction(
                user_id=hoh_id,  # Charge to HOH, not individual member
                transaction_type="sanctuary_coaching",
                amount=amount,
                description=description,
                metadata={
                    "sanctuary_id": sanctuary_id,
                    "intervention_id": intervention_id,
                    "member_id": member_id,
                    "is_assisted": is_assisted
                }
            )
            
            # Record in sanctuary billing events (per spec line 1466-1480)
            sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
            if sanctuary:
                if "billing_events" not in sanctuary:
                    sanctuary["billing_events"] = []
                sanctuary["billing_events"].append({
                    "event_type": "COACHING" if not is_assisted else "ASSISTED_RESPONSE",
                    "amount_usd": amount,
                    "hoh_id": hoh_id,
                    "member_id": member_id,
                    "intervention_id": intervention_id,
                    "timestamp": datetime.now().isoformat()
                })
                self._save()
            
            print(f">>> [SANCTUARY BILLING] Charged ${amount:.2f} to HOH {hoh_id}")
            return {"success": True, "charged": True, "transaction": result}
            
        except Exception as e:
            print(f">>> [SANCTUARY BILLING ERROR] {e}")
            return {"success": False, "error": str(e)}
    
    
    async def _check_all_responded(self, sanctuary_id: str):
        """Check if all members have responded to coaching offers"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return
        
        coaching_state = sanctuary.get("coaching_state", {})
        pending = coaching_state.get("pending_offers", {})
        
        # Check if anyone is still pending
        still_pending = any(o["status"] == "PENDING" for o in pending.values())
        
        if not still_pending:
            # All responded - check if anyone is in active coaching
            active = coaching_state.get("active_sessions", {})
            if not active:
                # No one is coaching - resume sanctuary
                coaching_state["status"] = "NORMAL"
                self._save()
    
    
    def _get_member_profile(self, sanctuary: dict, user_id: str) -> Optional[dict]:
        """Get full profile for a sanctuary member from registry"""
        try:
            registry_path = Path(self.data_dir) / "user_registry.json"
            if registry_path.exists():
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                for k, v in registry.items():
                    if v.get("profile", {}).get("hardware_id") == user_id:
                        return v["profile"]
        except Exception as e:
            print(f">>> [SANCTUARY] Profile lookup error: {e}")
        return None
    
    
    def _parse_cemo(self, value) -> Optional[float]:
        """Parse C_emo value from various formats"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Handle "73%" format
            if "%" in value:
                try:
                    return float(value.replace("%", "")) / 100
                except:
                    return None
            try:
                return float(value)
            except:
                return None
        return None


# =============================================================================
# PART 3: BRIDGE_SERVER HANDLER UPDATES
# Replace/add these handlers in bridge_server.py
# =============================================================================

"""
# In the message handling loop, add these handlers:

elif t == "sanctuary_coaching_accept":
    '''
    Member accepts coaching offer - enters private session with Little Nate
    '''
    sanctuary_id = d.get('sanctuary_id')
    intervention_id = d.get('intervention_id')
    wants_assisted = d.get('assisted_response', False)
    
    result = await sanctuary_engine.accept_coaching(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        intervention_id=intervention_id,
        wants_assisted_response=wants_assisted
    )
    
    if result["success"]:
        # Notify accepting member
        await websocket.send(json.dumps({
            "type": "sanctuary_coaching_started",
            "intervention_id": intervention_id,
            "is_free": result["is_free"],
            "total_cost": result["total_cost"],
            "intervention_type": result["intervention_type"],
            "modality": result["modality"],
            "message": "You're now in a private coaching session with Little Nate."
        }))
        
        # Notify other members
        await sanctuary_engine.broadcast_to_sanctuary(
            sanctuary_id=sanctuary_id,
            message_data={
                "type": "sanctuary_member_in_coaching",
                "member_name": current_profile['name'],
                "message": f"{current_profile['name']} is receiving 1-on-1 coaching from Little Nate. The sanctuary is paused."
            },
            exclude_user_id=current_profile['hardware_id']
        )
        
        # Get Little Nate's opening for private coaching
        # Uses full integration: Memory + Nevedal + Night School
        sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
        
        nate_result = await cortex.process_sanctuary_message(
            sanctuary_data=sanctuary_data,
            family_profiles=[current_profile],
            recent_messages=sanctuary_data.get("messages", [])[-10:],
            trigger="private_coaching_start"
        )
        
        if nate_result.get("response"):
            # Save to coaching session
            await sanctuary_engine.add_coaching_message(
                sanctuary_id=sanctuary_id,
                user_id=current_profile['hardware_id'],
                content=nate_result["response"],
                is_from_nate=True
            )
            
            # Send to member
            await websocket.send(json.dumps({
                "type": "sanctuary_coaching_message",
                "sender": "Little Nate",
                "content": nate_result["response"],
                "is_private": True
            }))
    else:
        await websocket.send(json.dumps({
            "type": "error",
            "message": result.get("error", "Could not start coaching session")
        }))


elif t == "sanctuary_coaching_decline":
    '''
    Member declines coaching offer
    '''
    sanctuary_id = d.get('sanctuary_id')
    
    result = await sanctuary_engine.decline_coaching(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id']
    )
    
    await websocket.send(json.dumps({
        "type": "sanctuary_coaching_declined",
        "message": "You can continue observing. Coaching will be available again if needed."
    }))


elif t == "sanctuary_coaching_message":
    '''
    Message in private coaching session
    '''
    sanctuary_id = d.get('sanctuary_id')
    content = d.get('message', '').strip()
    
    if not content:
        continue
    
    # Save member's message
    await sanctuary_engine.add_coaching_message(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        content=content,
        is_from_nate=False
    )
    
    # Get coaching session for context
    sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
    coaching_state = sanctuary_data.get("coaching_state", {})
    session = coaching_state.get("active_sessions", {}).get(current_profile['hardware_id'])
    
    if session:
        # Get Little Nate's response
        nate_result = await cortex.process_sanctuary_message(
            sanctuary_data=sanctuary_data,
            family_profiles=[current_profile],
            recent_messages=session.get("messages", [])[-10:],
            trigger="private_coaching"
        )
        
        if nate_result.get("response"):
            # Save Nate's response
            await sanctuary_engine.add_coaching_message(
                sanctuary_id=sanctuary_id,
                user_id=current_profile['hardware_id'],
                content=nate_result["response"],
                is_from_nate=True
            )
            
            # Send to member
            await websocket.send(json.dumps({
                "type": "sanctuary_coaching_message",
                "sender": "Little Nate",
                "content": nate_result["response"],
                "is_private": True
            }))


elif t == "sanctuary_coaching_complete":
    '''
    Member ends their coaching session
    '''
    sanctuary_id = d.get('sanctuary_id')
    
    # Get assisted response if they requested it
    sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
    coaching_state = sanctuary_data.get("coaching_state", {})
    session = coaching_state.get("active_sessions", {}).get(current_profile['hardware_id'])
    
    assisted_response = None
    if session and session.get("wants_assisted_response"):
        # Generate assisted response using Little Nate
        nate_result = await cortex.process_sanctuary_message(
            sanctuary_data=sanctuary_data,
            family_profiles=[current_profile],
            recent_messages=session.get("messages", []),
            trigger="generate_assisted_response"
        )
        assisted_response = nate_result.get("response")
    
    result = await sanctuary_engine.complete_coaching_session(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id'],
        assisted_response_draft=assisted_response
    )
    
    if result["success"]:
        # Notify member
        response_data = {
            "type": "sanctuary_coaching_ended",
            "message": "Your coaching session is complete. Thank you for sharing."
        }
        if assisted_response:
            response_data["assisted_response"] = assisted_response
        
        await websocket.send(json.dumps(response_data))
        
        # Notify others that member returned
        await sanctuary_engine.broadcast_to_sanctuary(
            sanctuary_id=sanctuary_id,
            message_data={
                "type": "sanctuary_member_returned",
                "member_name": current_profile['name'],
                "message": f"{current_profile['name']} has completed their coaching session."
            },
            exclude_user_id=current_profile['hardware_id']
        )
        
        # If all coaching complete, do reunion
        if result["ready_to_resume"]:
            # Get synthesis and reunion message
            synthesis = await sanctuary_engine.get_coaching_synthesis(sanctuary_id)
            
            # Get family profiles for reunion message
            family_profiles = []
            for member in sanctuary_data.get("members", []):
                profile = sanctuary_engine._get_member_profile(sanctuary_data, member["user_id"])
                if profile:
                    family_profiles.append(profile)
            
            nate_result = await cortex.process_sanctuary_message(
                sanctuary_data=sanctuary_data,
                family_profiles=family_profiles,
                recent_messages=[],
                trigger="reunion"
            )
            
            # Resume sanctuary
            await sanctuary_engine.resume_sanctuary(sanctuary_id)
            
            # Broadcast reunion to all
            reunion_message = nate_result.get("response", 
                "Welcome back everyone. I've had meaningful conversations with each of you. "
                "Let's continue with fresh understanding and compassion.")
            
            await sanctuary_engine.broadcast_to_sanctuary(
                sanctuary_id=sanctuary_id,
                message_data={
                    "type": "sanctuary_resumed",
                    "message": reunion_message,
                    "synthesis": synthesis.get("synthesis") if synthesis.get("success") else None
                }
            )


# Update sanctuary_message handler to check if messaging is allowed:

elif t == "sanctuary_message":
    sanctuary_id = d.get('sanctuary_id')
    message = d.get('message', '').strip()
    
    if not message:
        continue
    
    # Check if user can send messages (may be paused for coaching)
    can_send, reason = sanctuary_engine.can_send_message(
        sanctuary_id=sanctuary_id,
        user_id=current_profile['hardware_id']
    )
    
    if not can_send:
        await websocket.send(json.dumps({
            "type": "sanctuary_message_blocked",
            "reason": reason
        }))
        continue
    
    if reason == "coaching":
        # Redirect to coaching message handler
        # (This means user is in active coaching session)
        await sanctuary_engine.add_coaching_message(
            sanctuary_id=sanctuary_id,
            user_id=current_profile['hardware_id'],
            content=message,
            is_from_nate=False
        )
        # ... get Little Nate response (same as sanctuary_coaching_message handler)
        continue
    
    # Normal message flow continues...
    # ... existing message handling code ...
"""


# =============================================================================
# PART 4: PROCESS_SANCTUARY_MESSAGE TRIGGER UPDATES
# Add these trigger cases to the process_sanctuary_message method in AzureCortex
# =============================================================================

"""
Add these trigger cases to the system prompt builder:

trigger_instructions = {
    "observation": "You are OBSERVING. Speak only if you notice disconnection or opportunity for growth.",
    "escalation": "ESCALATION DETECTED. Gently pause and offer coaching to help process emotions.",
    "private_coaching_start": '''PRIVATE COACHING SESSION STARTING.
        You are now in a 1-on-1 session with this family member.
        - Be warm and validating
        - Ask about their feelings regarding the family conflict
        - Help them process their emotions
        - Do NOT reveal what other family members have said
        - Focus on their experience and perspective''',
    "private_coaching": '''PRIVATE COACHING IN PROGRESS.
        Continue supporting this family member.
        - Validate their feelings
        - Help them see other perspectives (without revealing private info)
        - Guide them toward understanding and regulation
        - If they're ready, help prepare them to re-enter the sanctuary''',
    "generate_assisted_response": '''GENERATE ASSISTED RESPONSE.
        Based on the coaching session, help draft a response this member 
        could share with their family when they return to the sanctuary.
        - Keep it authentic to their voice
        - Focus on "I feel" statements
        - Avoid blame
        - Express needs and desires for connection''',
    "reunion": '''REUNION - ALL COACHING COMPLETE.
        Welcome everyone back to the sanctuary.
        - Acknowledge the work each person did privately
        - Highlight common ground you observed (without revealing private details)
        - Set intention for continued connection
        - Invite them to share if comfortable'''
}
"""
