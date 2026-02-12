"""
FAMILY SANCTUARY ENGINE
Handles multi-member therapeutic group sessions with Little Nate

PROPERLY INTEGRATED WITH:
- BillingSystem (billing.json, transactions.json)
- AnalyticsEngine (analytics.json)
- MetricsEngine (Vaults/Clients/{id}/metrics.json)
- User Registry (user_registry.json)

Per DATA_SOURCE_MAPPING_V2.md architecture
"""

import json
import asyncio
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
try:
    from transformers import pipeline
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    print(">>> [SANCTUARY] AI detection unavailable: No module named 'transformers'")

# Note: BillingSystem, AnalyticsEngine passed in from bridge_server.py
# No direct Stripe imports - use BillingSystem instead


class FamilySanctuaryEngine:
    def __init__(self, data_dir: Path, azure_cortex, nevedal_handler, billing_system, analytics_engine=None):
        """
        Initialize with proper system integrations
        
        Args:
            data_dir: Path to data directory
            azure_cortex: AzureCortex instance for AI
            nevedal_handler: NevedalHandler for C_emo tracking
            billing_system: BillingSystem instance for charges
            analytics_engine: AnalyticsEngine instance for event tracking
        """
        self.data_dir = data_dir
        self.sanctuary_file = data_dir / "family_sanctuaries.json"
        self.azure_cortex = azure_cortex
        self.nevedal_handler = nevedal_handler
        self.billing = billing_system  # Use existing BillingSystem
        self.analytics = analytics_engine  # Use existing AnalyticsEngine
        
        # WebSocket registry: {sanctuary_id: {user_id: websocket}}
        # Separate from member data because websockets can't be serialized
        self._websocket_registry: Dict[str, Dict[str, any]] = {}
        
        # Legacy connections set (for backward compatibility)
        self.sanctuary_connections: Dict[str, Set] = {}
        
        # Load or create sanctuary data
        self._load_sanctuaries()
    
    def _load_sanctuaries(self):
        """Load sanctuary data from disk"""
        if self.sanctuary_file.exists():
            with open(self.sanctuary_file, 'r') as f:
                self.data = json.load(f)
        else:
            self.data = {
                "active_sanctuaries": {},
                "completed_sanctuaries": {}
            }
            self._save()
    
    def _save(self):
        """Save sanctuary data to disk"""
        with open(self.sanctuary_file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def _record_analytics(self, event_type: str, user_id: str = None, data: dict = None):
        """Record analytics event if analytics engine is available"""
        if self.analytics:
            try:
                self.analytics.record_event(event_type, user_id, data)
            except Exception as e:
                print(f">>> [SANCTUARY] Analytics recording failed: {e}")

    # =========================================================================
    # WEBSOCKET REGISTRY - Proper connection tracking
    # =========================================================================
    
    def _register_websocket(self, sanctuary_id: str, user_id: str, websocket):
        """Register a websocket connection for a member"""
        if sanctuary_id not in self._websocket_registry:
            self._websocket_registry[sanctuary_id] = {}
        self._websocket_registry[sanctuary_id][user_id] = websocket
        
        # Also add to legacy connections set
        if sanctuary_id not in self.sanctuary_connections:
            self.sanctuary_connections[sanctuary_id] = set()
        self.sanctuary_connections[sanctuary_id].add(websocket)
        
        print(f">>> [SANCTUARY] Registered websocket for {user_id} in {sanctuary_id}")

    def _unregister_websocket(self, sanctuary_id: str, user_id: str):
        """Unregister a websocket when member disconnects"""
        if sanctuary_id in self._websocket_registry:
            ws = self._websocket_registry[sanctuary_id].pop(user_id, None)
            if ws and sanctuary_id in self.sanctuary_connections:
                self.sanctuary_connections[sanctuary_id].discard(ws)
        print(f">>> [SANCTUARY] Unregistered websocket for {user_id} in {sanctuary_id}")

    def get_member_websocket(self, sanctuary_id: str, user_id: str):
        """Get websocket for a specific member"""
        return self._websocket_registry.get(sanctuary_id, {}).get(user_id)

    def get_active_websockets(self, sanctuary_id: str) -> list:
        """Get all active websockets for a sanctuary"""
        return list(self._websocket_registry.get(sanctuary_id, {}).values())

    # =========================================================================
    # SANCTUARY LOOKUP
    # =========================================================================

    def get_active_sanctuary_for_family(self, family_id: str) -> Optional[Dict]:
        """Get active sanctuary for a family if one exists"""
        for sanctuary_id, sanctuary in self.data.get('active_sanctuaries', {}).items():
            if (sanctuary.get('family_id') == family_id and 
                sanctuary.get('status') not in ['COMPLETED', 'CANCELLED']):
                return sanctuary
        return None
    
    # =========================================================================
    # SANCTUARY LIFECYCLE
    # =========================================================================
    
    async def create_sanctuary(
        self,
        family_id: str,
        head_of_household_id: str,
        invited_members: List[str],
        initial_topic: str,
        consent_data: Dict
    ) -> str:
        """Create new Family Sanctuary session"""
        
        # Generate sanctuary ID
        sanctuary_id = f"SANC_{datetime.now().strftime('%Y%m%d')}_{len(self.data['active_sanctuaries']) + 1:03d}"
        
        # Create sanctuary record
        sanctuary = {
            "sanctuary_id": sanctuary_id,
            "family_id": family_id,
            "head_of_household_id": head_of_household_id,
            "created_by": head_of_household_id,  # Default creator (bridge may override with actual initiator)
            "legal_consent": {
                "version": "v1.0_2026",
                "agreed_at": datetime.now().isoformat(),
                "ip_address": consent_data.get("ip_address"),
                "signature": consent_data.get("signature"),
                "terms_acknowledged": True,
                "no_refund_acknowledged": True
            },
            "status": "WAITING_FOR_MEMBERS",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "last_activity_at": datetime.now().isoformat(),
            "current_cycle_start": datetime.now().isoformat(),
            "current_cycle_end": (datetime.now() + timedelta(hours=24)).isoformat(),
            "members": [],
            "invited_member_ids": invited_members,
            "messages": [],
            "billing": {
                "base_fee_charged": False,
                "total_charges": 0.00,
                "charges": [],
                "free_coaching_summary": {
                    "total_free_given": 0,
                    "members_used_free": []
                },
                "thresholds_notified": [],
                "next_threshold": 50
            },
            "metrics": {
                "total_messages": 0,
                "intervention_count": 0,
                "free_interventions": 0,
                "paid_interventions": 0,
                "breakthrough_moments": 0,
                "escalation_events": 0,
                "de_escalation_success_rate": 1.0,
                "family_c_emo_avg": 0.0,
                "individual_c_emo": {}
            },
            "initial_topic": initial_topic,
            "therapeutic_approach": "FAMILY_SYSTEMS_EFT_LEGACY",
            "current_focus": "",
            "coach_escalation": {
                "recommended": False,
                "reason": None,
                "coach_notified": False,
                "coach_assigned": None
            }
        }
        
        self.data["active_sanctuaries"][sanctuary_id] = sanctuary
        self._websocket_registry[sanctuary_id] = {}
        self.sanctuary_connections[sanctuary_id] = set()
        self._save()
        
        # Record analytics event
        self._record_analytics("sanctuary_created", head_of_household_id, {
            "sanctuary_id": sanctuary_id,
            "family_id": family_id
        })
        
        print(f">>> [SANCTUARY] Created sanctuary {sanctuary_id} for family {family_id}")
        return sanctuary_id
    
    async def charge_base_fee(self, sanctuary_id: str, head_of_household_id: str) -> Tuple[bool, str]:
        """
        Charge $20 base fee using BillingSystem
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        amount = 20.00
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False, "Sanctuary not found"

        billing = (sanctuary.get("billing") or {}) if isinstance(sanctuary, dict) else {}
        if billing.get("base_fee_charged") is True:
            return True, "Base fee already charged"

        # Check if billing is enabled (for testing)
        BILLING_ENABLED = os.getenv("SANCTUARY_BILLING_ENABLED", "false").lower() == "true"

        # We always record an auditable ledger entry. If billing is disabled (or provider missing),
        # record as test/record-only so UIs and flow charts remain authoritative.
        transaction_id = None
        charge_status = "PAID"
        try:
            if not BILLING_ENABLED:
                charge_status = "TEST_MODE"
                print(f">>> [SANCTUARY] Billing disabled - recording base fee (test mode) for {sanctuary_id}")
                if self.billing:
                    txn = self.billing.record_transaction(
                        user_id=head_of_household_id,
                        amount=amount,
                        description=f"Family Sanctuary Base Fee - {sanctuary_id}",
                        transaction_type="sanctuary_base_fee",
                        status="test_mode",
                        metadata={
                            "mode": "test_mode",
                            "sanctuary_id": sanctuary_id,
                            "family_id": sanctuary.get("family_id"),
                            "charge_type": "BASE_FEE",
                        },
                    )
                    transaction_id = (txn or {}).get("transaction_id")
            else:
                # Billing is enabled; if no provider is configured, still record ledger locally.
                if not self.billing:
                    charge_status = "RECORDED"
                    print(f">>> [SANCTUARY] Billing enabled but no provider; recording base fee for {sanctuary_id}")
                else:
                    txn = self.billing.record_transaction(
                        user_id=head_of_household_id,
                        amount=amount,
                        description=f"Family Sanctuary Base Fee - {sanctuary_id}",
                        transaction_type="sanctuary_base_fee",
                        metadata={
                            "sanctuary_id": sanctuary_id,
                            "family_id": sanctuary.get("family_id"),
                            "charge_type": "BASE_FEE",
                        },
                    )
                    transaction_id = (txn or {}).get("transaction_id")
        except Exception as e:
            # Never block the sanctuary from having an authoritative ledger entry
            charge_status = "RECORDED"
            print(f">>> [SANCTUARY] Base fee txn record failed; recording locally instead: {e}")

        prev_total = float(billing.get("total_charges", 0.0) or 0.0)
        billing["base_fee_charged"] = True
        billing["total_charges"] = prev_total + amount
        charges = billing.get("charges") if isinstance(billing.get("charges"), list) else []
        charges.append({
            "timestamp": datetime.now().isoformat(),
            "type": "BASE_FEE",
            "amount": amount,
            "status": charge_status,
            "billed_to": head_of_household_id,
            "transaction_id": transaction_id,
        })
        billing["charges"] = charges
        sanctuary["billing"] = billing
        self._save()

        try:
            self._record_analytics("sanctuary_base_fee", head_of_household_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": amount,
                "status": charge_status,
                "transaction_id": transaction_id,
            })
        except Exception:
            pass

        if charge_status == "TEST_MODE":
            return True, "Base fee recorded (test mode)"
        if charge_status == "RECORDED":
            return True, "Base fee recorded"
        return True, "Base fee charged successfully"
    
    def verify_invitation(self, sanctuary_id: str, user_id: str) -> bool:
        """Verify user is invited to sanctuary"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        return user_id in sanctuary["invited_member_ids"]
    
    # =========================================================================
    # MEMBER MANAGEMENT - With proper reconnection handling
    # =========================================================================

    async def add_or_reconnect_member(
        self, 
        sanctuary_id: str, 
        user_id: str, 
        user_name: str, 
        websocket
    ) -> dict:
        """
        Add a new member or reconnect an existing one.
        Returns action taken: CREATED, JOINED, RECONNECTED, RETURNED, REFRESHED
        """
        sanctuary = self.data['active_sanctuaries'].get(sanctuary_id)
        if not sanctuary:
            return {"success": False, "error": "Sanctuary not found"}
        
        # Check if member already exists
        existing_member = None
        for member in sanctuary.get('members', []):
            if member['user_id'] == user_id:
                existing_member = member
                break
        
        if existing_member:
            # RECONNECTION - Update connection and status
            old_status = existing_member.get('status', 'ACTIVE')
            existing_member['last_seen'] = datetime.now().isoformat()
            
            if old_status == 'EXITED':
                # Returning after exit - member is rejoining
                existing_member['status'] = 'ACTIVE'
                existing_member['exited_at'] = None
                action = "RETURNED"
                print(f">>> [SANCTUARY] Member {user_name} RETURNED to {sanctuary_id}")
                self._record_analytics("sanctuary_member_returned", user_id, {"sanctuary_id": sanctuary_id})
            elif old_status == 'PAUSED':
                # Reconnecting after disconnect
                existing_member['status'] = 'ACTIVE'
                action = "RECONNECTED"
                print(f">>> [SANCTUARY] Member {user_name} RECONNECTED to {sanctuary_id}")
                self._record_analytics("sanctuary_member_reconnected", user_id, {"sanctuary_id": sanctuary_id})
            else:
                # Already active, just updating websocket (page refresh)
                action = "REFRESHED"
                print(f">>> [SANCTUARY] Member {user_name} REFRESHED connection to {sanctuary_id}")
                self._record_analytics("sanctuary_member_refreshed", user_id, {"sanctuary_id": sanctuary_id})
            
            # Register websocket
            self._register_websocket(sanctuary_id, user_id, websocket)
            self._save()
            
            return {
                "success": True,
                "action": action,
                "member": existing_member,
                "is_new": False
            }
        else:
            # NEW MEMBER
            # Load user profile for additional info
            user_profile = self._get_user_profile(user_id)
            
            new_member = {
                "user_id": user_id,
                "name": user_name or user_profile.get("name", "Unknown"),
                "role": user_profile.get("family_role", "member"),
                "age": user_profile.get("age"),
                "status": "ACTIVE",
                "member_consent_agreed": False,
                "member_consent_agreed_at": None,
                "joined_at": datetime.now().isoformat(),
                "last_seen": datetime.now().isoformat(),
                "exited_at": None,
                "initial_reason": None,
                "personal_goal": None,
                "family_concerns": None,
                "message_count": 0,
                "coaching_received": 0,
                "free_coaching_used": False,
                "coaching_charges_incurred": 0.00
            }
            
            sanctuary['members'].append(new_member)
            sanctuary['last_activity_at'] = datetime.now().isoformat()
            
            # Register websocket
            self._register_websocket(sanctuary_id, user_id, websocket)
            self._save()
            
            # Record analytics
            self._record_analytics("sanctuary_member_joined", user_id, {
                "sanctuary_id": sanctuary_id,
                "member_count": len(sanctuary['members'])
            })
            
            print(f">>> [SANCTUARY] Member {user_name} JOINED {sanctuary_id}")
            
            return {
                "success": True,
                "action": "JOINED",
                "member": new_member,
                "is_new": True
            }

    async def add_member(self, sanctuary_id: str, user_id: str, websocket):
        """
        Legacy method - redirects to add_or_reconnect_member
        Kept for backward compatibility
        """
        # Get user name from profile
        user_profile = self._get_user_profile(user_id)
        user_name = user_profile.get("name", "Unknown")
        
        result = await self.add_or_reconnect_member(sanctuary_id, user_id, user_name, websocket)
        
        # For backward compatibility, broadcast if truly new
        if result.get('success') and result.get('is_new'):
            await self.broadcast_to_sanctuary(
                sanctuary_id,
                {
                    "type": "sanctuary_member_joined",
                    "member": result['member']
                },
                exclude_user_id=user_id  # Don't send to the joining member
            )

    def member_disconnect(self, sanctuary_id: str, user_id: str):
        """Handle member disconnecting (not exiting, just lost connection)"""
        sanctuary = self.data['active_sanctuaries'].get(sanctuary_id)
        if not sanctuary:
            return
        
        for member in sanctuary.get('members', []):
            if member['user_id'] == user_id:
                member['status'] = 'PAUSED'
                member['last_seen'] = datetime.now().isoformat()
                print(f">>> [SANCTUARY] Member {member['name']} PAUSED (disconnected) from {sanctuary_id}")
                break
        
        self._unregister_websocket(sanctuary_id, user_id)
        self._save()
        self._record_analytics("sanctuary_member_disconnected", user_id, {"sanctuary_id": sanctuary_id})
    
    async def store_member_input(
        self,
        sanctuary_id: str,
        user_id: str,
        initial_reason: str,
        personal_goal: str,
        family_concerns: str
    ):
        """Store member's confidential onboarding responses"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        member = next((m for m in sanctuary["members"] if m["user_id"] == user_id), None)
        if member:
            member["initial_reason"] = initial_reason
            member["personal_goal"] = personal_goal
            member["family_concerns"] = family_concerns
            member["member_consent_agreed"] = True
            member["member_consent_agreed_at"] = datetime.now().isoformat()
            member["status"] = "ACTIVE"
            
            sanctuary["last_activity_at"] = datetime.now().isoformat()
            self._save()
    
    def all_members_joined(self, sanctuary_id: str) -> bool:
        """Check if all invited members have joined"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        joined_ids = {m["user_id"] for m in sanctuary["members"] if m["member_consent_agreed"]}
        invited_ids = set(sanctuary["invited_member_ids"])
        
        # All invited members have completed onboarding
        return joined_ids == invited_ids
    
    async def start_session(self, sanctuary_id: str):
        """Start the sanctuary session (all members ready)"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        sanctuary["status"] = "ACTIVE"
        sanctuary["started_at"] = datetime.now().isoformat()
        self._save()
        
        # Record analytics
        self._record_analytics("sanctuary_session_started", sanctuary["head_of_household_id"], {
            "sanctuary_id": sanctuary_id,
            "member_count": len(sanctuary["members"])
        })
        
        # Generate opening message from Little Nate
        opening_message = await self._generate_opening_message(sanctuary)
        
        # Broadcast to all members
        await self.broadcast_to_sanctuary(sanctuary_id, {
            "type": "sanctuary_started",
            "members": sanctuary["members"],
            "opening_message": opening_message
        })
    
    # =========================================================================
    # MESSAGE HANDLING
    # =========================================================================
    
    async def add_message(
        self,
        sanctuary_id: str,
        sender_id: str,
        content: str,
        message_type: str = "MEMBER_MESSAGE",
    ) -> str:
        """Add message to sanctuary and return message ID"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        # Get sender info
        member = next((m for m in sanctuary["members"] if m["user_id"] == sender_id), None)
        if not member:
            return None
        
        message_id = f"MSG_{len(sanctuary['messages']) + 1}"
        
        message = {
            "message_id": message_id,
            "message_type": message_type,
            "sender_id": sender_id,
            "sender_name": member["name"],
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "is_private": False,
            "emotional_tone": None,
            "escalation_detected": False,
            "intervention_triggered": False
        }
        
        sanctuary["messages"].append(message)
        sanctuary["metrics"]["total_messages"] += 1
        member["message_count"] += 1
        sanctuary["last_activity_at"] = datetime.now().isoformat()
        
        self._save()
        
        # Record analytics
        self._record_analytics("sanctuary_message", sender_id, {
            "sanctuary_id": sanctuary_id
        })
        
        return message_id
    
    async def broadcast_to_sanctuary(
        self,
        sanctuary_id: str,
        message_data: Dict,
        exclude: Optional[List] = None,
        exclude_user_id: Optional[str] = None
    ):
        """Broadcast message to all sanctuary members"""
        exclude = exclude or []
        message_json = json.dumps(message_data)
        
        # Use the websocket registry for more reliable delivery
        for user_id, ws in list(self._websocket_registry.get(sanctuary_id, {}).items()):
            # Skip if this user should be excluded
            if exclude_user_id and user_id == exclude_user_id:
                continue
            if ws in exclude:
                continue
                
            try:
                await ws.send(message_json)
            except Exception as e:
                print(f">>> [SANCTUARY] Broadcast failed to {user_id}: {e}")
                # Mark as disconnected but don't remove - they might reconnect
                self.member_disconnect(sanctuary_id, user_id)
    
    # =========================================================================
    # VENTRILOQUISM DETECTION (Patent 3)
    # =========================================================================
    
    # Proxy speech patterns: when a family member speaks for another
    VENTRILOQUISM_PATTERNS = [
        r"\bhe\s+feels?\b", r"\bshe\s+feels?\b", r"\bthey\s+feel\b",
        r"\bhe\s+thinks?\b", r"\bshe\s+thinks?\b", r"\bthey\s+think\b",
        r"\bhe\s+wants?\b", r"\bshe\s+wants?\b", r"\bthey\s+want\b",
        r"\bhe\s+needs?\b", r"\bshe\s+needs?\b", r"\bthey\s+need\b",
        r"\bhe\s+always\b", r"\bshe\s+always\b", r"\bthey\s+always\b",
        r"\bhe\s+never\b", r"\bshe\s+never\b", r"\bthey\s+never\b",
        r"\bmy\s+husband\s+(is|feels?|thinks?|wants?|needs?|always|never)\b",
        r"\bmy\s+wife\s+(is|feels?|thinks?|wants?|needs?|always|never)\b",
        r"\bmy\s+(son|daughter|child|kid|mom|dad|father|mother)\s+(is|feels?|thinks?|wants?|needs?|always|never)\b",
        r"\bhe\s+doesn'?t\s+(care|listen|understand|try)\b",
        r"\bshe\s+doesn'?t\s+(care|listen|understand|try)\b",
    ]
    
    def detect_ventriloquism(
        self,
        sanctuary_id: str,
        message_content: str,
        sender_id: str,
        sender_name: str = ""
    ) -> bool:
        """
        Detect when a family member speaks for another member (ventriloquism).
        Returns True if proxy speech is detected.
        """
        import re
        
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        content_lower = message_content.lower().strip()
        if len(content_lower) < 10:
            return False
        
        detected_phrases = []
        for pattern in self.VENTRILOQUISM_PATTERNS:
            matches = re.findall(pattern, content_lower)
            if matches:
                # Find the actual matched substring for context
                for m in re.finditer(pattern, content_lower):
                    detected_phrases.append(m.group(0))
        
        if not detected_phrases:
            return False
        
        # Record the ventriloquism event
        if "ventriloquism_events" not in sanctuary:
            sanctuary["ventriloquism_events"] = []
        
        event = {
            "speaker_id": sender_id,
            "speaker_name": sender_name or sender_id,
            "phrase": detected_phrases[0],
            "full_patterns": detected_phrases[:3],
            "description": f"Proxy speech detected: '{detected_phrases[0]}' — speaking for another family member",
            "timestamp": datetime.now().isoformat(),
            "message_excerpt": content_lower[:100],
        }
        sanctuary["ventriloquism_events"].append(event)
        
        # Track per-member frequency
        if "ventriloquism_counts" not in sanctuary:
            sanctuary["ventriloquism_counts"] = {}
        sanctuary["ventriloquism_counts"][sender_id] = sanctuary["ventriloquism_counts"].get(sender_id, 0) + 1
        
        self._save()
        return True
    
    # =========================================================================
    # ESCALATION DETECTION & INTERVENTION
    # =========================================================================
    
    async def detect_escalation(
        self,
        sanctuary_id: str,
        message_id: str,
        message_content: str,
        sender_id: str
    ) -> bool:
        """Detect escalation and get Little Nate response"""
        
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False
        
        # Quick keyword check
        keywords = ["angry", "furious", "hate", "frustrated", "upset", "scared",
                    "hopeless", "worthless", "hurt", "kill", "die", "suicide"]
        
        if not any(kw in message_content.lower() for kw in keywords):
            return False
        
        # Get Little Nate's response
        if self.azure_cortex:
            try:
                profiles = self._get_family_profiles_from_registry(sanctuary)
                result = await self.azure_cortex.process_sanctuary_message(
                    sanctuary_data=sanctuary,
                    family_profiles=profiles,
                    recent_messages=sanctuary["messages"][-10:],
                    trigger="escalation"
                )
                
                if result.get("success") and result.get("should_intervene"):
                    nate_msg = {
                        "message_id": f"LN_{len(sanctuary['messages']) + 1}",
                        "message_type": "LITTLE_NATE",
                        "sender_id": "LITTLE_NATE",
                        "sender_name": "Little Nate",
                        "content": result.get("response"),
                        "timestamp": datetime.now().isoformat(),
                        "crisis_level": result.get("crisis_level", "NONE")
                    }
                    sanctuary["messages"].append(nate_msg)
                    self._save()
                    
                    await self.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_message",
                            "message_type": "LITTLE_NATE",
                            "sender_id": "LITTLE_NATE",
                            "sender_name": "Little Nate",
                            "content": result.get("response"),
                            "timestamp": nate_msg["timestamp"]
                        }
                    )
                    return True
            except Exception as e:
                print(f">>> [SANCTUARY] Error: {e}")
        
        return False
    
    def _get_family_profiles_from_registry(self, sanctuary: dict) -> list:
        """Get profiles for all sanctuary members"""
        profiles = []
        try:
            registry_path = Path(self.data_dir) / "user_registry.json"
            if registry_path.exists():
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                for member in sanctuary.get("members", []):
                    user_id = member.get("user_id")
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == user_id:
                            profiles.append(v["profile"])
                            break
        except Exception as e:
            print(f">>> [SANCTUARY] Profile error: {e}")
        return profiles
    
    async def trigger_intervention(
        self,
        sanctuary_id: str,
        triggered_by_message_id: str
    ):
        """Trigger coaching intervention for appropriate family member"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        # Determine who needs coaching (usually the person who escalated)
        message = next((m for m in sanctuary["messages"] if m["message_id"] == triggered_by_message_id), None)
        if not message:
            return
        
        recipient_id = message["sender_id"]
        member = next((m for m in sanctuary["members"] if m["user_id"] == recipient_id), None)
        
        if not member:
            return
        
        # Check if this is their first coaching (FREE)
        is_free = not member["free_coaching_used"]
        coaching_number = member["coaching_received"] + 1
        
        # Create intervention offer
        intervention_id = f"INT_{len(sanctuary['messages']) + 1}"
        
        # Send coaching offer to member
        await self._send_coaching_offer(
            sanctuary_id,
            recipient_id,
            intervention_id,
            is_free,
            coaching_number
        )
        
        sanctuary["metrics"]["intervention_count"] += 1
        message["intervention_triggered"] = True
        self._save()
    
    async def _send_coaching_offer(
        self,
        sanctuary_id: str,
        recipient_id: str,
        intervention_id: str,
        is_free: bool,
        coaching_number: int
    ):
        """Send private coaching offer to specific member"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == recipient_id), None)
        
        # Find recipient's WebSocket using registry
        recipient_ws = self.get_member_websocket(sanctuary_id, recipient_id)
        if not recipient_ws:
            print(f">>> [SANCTUARY] No websocket found for {recipient_id}")
            return
        
        offer_message = {
            "type": "sanctuary_coaching_offer",
            "sanctuary_id": sanctuary_id,
            "intervention_id": intervention_id,
            "is_free": is_free,
            "coaching_number": coaching_number,
            "charge_amount": 0.00 if is_free else 5.00,
            "message": f"Hi {member['name']},\n\nI notice an opportunity to provide support. Would you like coaching on this moment?\n\n{'🎁 Your First Coaching: FREE!' if is_free else '💰 Coaching: $5.00'}\n\n(You can also request an assisted response for +$3.00)"
        }
        
        try:
            await recipient_ws.send(json.dumps(offer_message))
        except Exception as e:
            print(f">>> [SANCTUARY] Failed to send coaching offer: {e}")
    
    # =========================================================================
    # COACHING & BILLING
    # =========================================================================
    
    async def generate_coaching(
        self,
        sanctuary_id: str,
        intervention_id: str,
        member_id: str,
        include_drafted_response: bool = False
    ) -> str:
        """Generate AI coaching content for member"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        
        # Build coaching prompt with context
        coaching_prompt = self._build_coaching_prompt(
            sanctuary,
            member,
            include_drafted_response
        )
        
        # Generate via Azure OpenAI
        coaching_content = await self.azure_cortex.generate_coaching(coaching_prompt)
        
        return coaching_content
    
    async def charge_coaching(
        self,
        sanctuary_id: str,
        intervention_id: str,
        member_id: str,
        amount: float
    ) -> Tuple[bool, str]:
        """
        Charge for coaching intervention using BillingSystem
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if amount == 0:
            return True, "Free coaching"  # Free coaching
        
        # Check if billing is enabled
        BILLING_ENABLED = os.getenv("SANCTUARY_BILLING_ENABLED", "false").lower() == "true"
        
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        head_of_household_id = sanctuary["head_of_household_id"]
        
        if not BILLING_ENABLED:
            # Test mode - record but don't charge
            transaction_id = None
            try:
                if self.billing:
                    txn = self.billing.record_transaction(
                        user_id=head_of_household_id,  # Bill to head of household
                        amount=amount,
                        description=f"Family Sanctuary Coaching - {sanctuary_id}",
                        transaction_type="sanctuary_coaching",
                        status="test_mode",
                        metadata={
                            "mode": "test_mode",
                            "sanctuary_id": sanctuary_id,
                            "family_id": sanctuary.get("family_id"),
                            "charge_type": "COACHING",
                            "recipient": member_id,
                            "coaching_number": (member.get("coaching_received", 0) + 1) if member else None,
                        },
                    )
                    transaction_id = (txn or {}).get("transaction_id")
            except Exception as e:
                print(f">>> [SANCTUARY] Coaching txn (test mode) record failed: {e}")

            sanctuary["billing"]["total_charges"] += amount
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "COACHING",
                "recipient": member_id,
                "coaching_number": member["coaching_received"] + 1,
                "amount": amount,
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })
            member["coaching_charges_incurred"] += amount
            sanctuary["metrics"]["paid_interventions"] += 1
            self._save()
            self._record_analytics("sanctuary_coaching_charged", member_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": amount,
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })
            return True, "Coaching charged (test mode)"
        
        try:
            # Use BillingSystem to record transaction
            transaction = self.billing.record_transaction(
                user_id=head_of_household_id,  # Bill to head of household
                amount=amount,
                description=f"Family Sanctuary Coaching - {sanctuary_id}",
                transaction_type="sanctuary_coaching",
                metadata={
                    "sanctuary_id": sanctuary_id,
                    "family_id": sanctuary.get("family_id"),
                    "charge_type": "COACHING",
                    "recipient": member_id,
                    "coaching_number": (member.get("coaching_received", 0) + 1) if member else None,
                },
            )
            
            # Record in sanctuary billing
            sanctuary["billing"]["total_charges"] += amount
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "COACHING",
                "recipient": member_id,
                "coaching_number": member["coaching_received"] + 1,
                "amount": amount,
                "transaction_id": transaction.get("transaction_id")
            })
            
            member["coaching_charges_incurred"] += amount
            sanctuary["metrics"]["paid_interventions"] += 1
            
            self._save()
            
            # Check thresholds
            await self._check_billing_thresholds(sanctuary_id)
            
            # Record analytics
            self._record_analytics("sanctuary_coaching_charged", member_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": amount
            })
            
            return True, "Coaching charged successfully"
            
        except Exception as e:
            print(f">>> [SANCTUARY] Coaching charge error: {e}")
            return False, str(e)

    async def charge_assisted_response(
        self,
        sanctuary_id: str,
        member_id: str,
        amount: float = 3.00,
    ) -> Tuple[bool, str]:
        """
        Charge for the $3 Assisted Response add-on (billed to head of household).

        This is separate from COACHING so ledgers, dashboards, and flow charts can be precise.
        In test mode (SANCTUARY_BILLING_ENABLED=false), records the charge without charging real money.
        """
        if amount == 0:
            return True, "Free assisted response"

        BILLING_ENABLED = os.getenv("SANCTUARY_BILLING_ENABLED", "false").lower() == "true"

        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        head_of_household_id = sanctuary["head_of_household_id"]

        if not BILLING_ENABLED:
            transaction_id = None
            try:
                if self.billing:
                    txn = self.billing.record_transaction(
                        user_id=head_of_household_id,
                        amount=float(amount),
                        description=f"Family Sanctuary Assisted Response - {sanctuary_id}",
                        transaction_type="sanctuary_assisted_response",
                        status="test_mode",
                        metadata={
                            "mode": "test_mode",
                            "sanctuary_id": sanctuary_id,
                            "family_id": sanctuary.get("family_id"),
                            "charge_type": "ASSISTED_RESPONSE",
                            "recipient": member_id,
                        },
                    )
                    transaction_id = (txn or {}).get("transaction_id")
            except Exception as e:
                print(f">>> [SANCTUARY] Assisted response txn (test mode) record failed: {e}")

            sanctuary["billing"]["total_charges"] += float(amount)
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "ASSISTED_RESPONSE",
                "recipient": member_id,
                "amount": float(amount),
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })
            if member:
                member["coaching_charges_incurred"] = float(member.get("coaching_charges_incurred", 0.0) or 0.0) + float(amount)
            sanctuary["metrics"]["paid_interventions"] = int(sanctuary["metrics"].get("paid_interventions", 0) or 0) + 1
            self._save()

            self._record_analytics("sanctuary_assisted_response_charged", member_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": float(amount),
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })

            return True, "Assisted response charged (test mode)"

        try:
            transaction = self.billing.record_transaction(
                user_id=head_of_household_id,
                amount=float(amount),
                description=f"Family Sanctuary Assisted Response - {sanctuary_id}",
                transaction_type="sanctuary_assisted_response",
                metadata={
                    "sanctuary_id": sanctuary_id,
                    "family_id": sanctuary.get("family_id"),
                    "charge_type": "ASSISTED_RESPONSE",
                    "recipient": member_id,
                },
            )

            sanctuary["billing"]["total_charges"] += float(amount)
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "ASSISTED_RESPONSE",
                "recipient": member_id,
                "amount": float(amount),
                "transaction_id": (transaction or {}).get("transaction_id"),
            })
            if member:
                member["coaching_charges_incurred"] = float(member.get("coaching_charges_incurred", 0.0) or 0.0) + float(amount)
            sanctuary["metrics"]["paid_interventions"] = int(sanctuary["metrics"].get("paid_interventions", 0) or 0) + 1
            self._save()

            await self._check_billing_thresholds(sanctuary_id)

            self._record_analytics("sanctuary_assisted_response_charged", member_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": float(amount),
                "transaction_id": (transaction or {}).get("transaction_id"),
            })

            return True, "Assisted response charged successfully"
        except Exception as e:
            print(f">>> [SANCTUARY] Assisted response charge error: {e}")
            return False, str(e)

    async def charge_group_coaching(
        self,
        sanctuary_id: str,
        amount: float = 20.00,
        description: str = "Group Coaching Session"
    ) -> Tuple[bool, str]:
        """
        Charge for group coaching (billed to head of household).

        In test mode (SANCTUARY_BILLING_ENABLED=false), records the charge without charging real money.
        """
        if amount == 0:
            return True, "Free group coaching"

        BILLING_ENABLED = os.getenv("SANCTUARY_BILLING_ENABLED", "false").lower() == "true"

        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        hoh_id = sanctuary["head_of_household_id"]

        if not BILLING_ENABLED:
            transaction_id = None
            try:
                if self.billing:
                    txn = self.billing.record_transaction(
                        user_id=hoh_id,
                        amount=amount,
                        description=description,
                        transaction_type="sanctuary_group_coaching",
                        status="test_mode",
                        metadata={
                            "mode": "test_mode",
                            "sanctuary_id": sanctuary_id,
                            "family_id": sanctuary.get("family_id"),
                            "charge_type": "GROUP_COACHING",
                        },
                    )
                    transaction_id = (txn or {}).get("transaction_id")
            except Exception as e:
                print(f">>> [SANCTUARY] Group coaching txn (test mode) record failed: {e}")

            sanctuary["billing"]["total_charges"] += amount
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "GROUP_COACHING",
                "amount": amount,
                "description": description,
                "billed_to": hoh_id,
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })
            sanctuary["metrics"]["paid_interventions"] += 1
            self._save()
            await self._check_billing_thresholds(sanctuary_id)
            self._record_analytics("sanctuary_group_coaching_charged", hoh_id, {
                "sanctuary_id": sanctuary_id,
                "family_id": sanctuary.get("family_id"),
                "amount": amount,
                "status": "TEST_MODE",
                "transaction_id": transaction_id,
            })
            return True, "Group coaching recorded (test mode)"

        try:
            transaction = self.billing.record_transaction(
                user_id=hoh_id,
                amount=amount,
                description=description,
                transaction_type="sanctuary_group_coaching",
                metadata={
                    "sanctuary_id": sanctuary_id,
                    "family_id": sanctuary.get("family_id"),
                    "charge_type": "GROUP_COACHING",
                },
            )

            sanctuary["billing"]["total_charges"] += amount
            sanctuary["billing"]["charges"].append({
                "timestamp": datetime.now().isoformat(),
                "type": "GROUP_COACHING",
                "amount": amount,
                "description": description,
                "billed_to": hoh_id,
                "transaction_id": transaction.get("transaction_id"),
            })
            sanctuary["metrics"]["paid_interventions"] += 1
            self._save()

            await self._check_billing_thresholds(sanctuary_id)
            self._record_analytics("sanctuary_group_coaching_charged", hoh_id, {
                "sanctuary_id": sanctuary_id,
                "amount": amount,
            })

            return True, "Group coaching charged successfully"
        except Exception as e:
            print(f">>> [SANCTUARY] Group coaching charge error: {e}")
            return False, str(e)
    
    async def increment_coaching_count(self, sanctuary_id: str, member_id: str):
        """Increment coaching count for member"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        
        if member:
            member["coaching_received"] += 1
            
            if not member["free_coaching_used"]:
                member["free_coaching_used"] = True
                sanctuary["billing"]["free_coaching_summary"]["total_free_given"] += 1
                sanctuary["billing"]["free_coaching_summary"]["members_used_free"].append(member_id)
                sanctuary["metrics"]["free_interventions"] += 1
            
            self._save()
    
    def get_member_coaching_count(self, sanctuary_id: str, member_id: str) -> int:
        """Get coaching count for specific member"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        
        return member["coaching_received"] if member else 0
    
    async def _check_billing_thresholds(self, sanctuary_id: str):
        """Check if billing thresholds reached ($50, $100)"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        total = sanctuary["billing"]["total_charges"]
        notified = sanctuary["billing"]["thresholds_notified"]
        
        if total >= 100 and "$100" not in notified:
            await self._notify_threshold(sanctuary_id, 100, offer_coach=True)
            sanctuary["billing"]["thresholds_notified"].append("$100")
            sanctuary["billing"]["next_threshold"] = 200
            self._save()
            
        elif total >= 50 and "$50" not in notified:
            await self._notify_threshold(sanctuary_id, 50, offer_coach=False)
            sanctuary["billing"]["thresholds_notified"].append("$50")
            sanctuary["billing"]["next_threshold"] = 100
            self._save()
    
    async def _notify_threshold(self, sanctuary_id: str, threshold: int, offer_coach: bool):
        """Notify Head of Household about billing threshold"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        hoh_id = sanctuary["head_of_household_id"]
        
        # Find HoH WebSocket using registry
        hoh_ws = self.get_member_websocket(sanctuary_id, hoh_id)
        if not hoh_ws:
            return
        
        message = {
            "type": "sanctuary_threshold_notification",
            "sanctuary_id": sanctuary_id,
            "threshold": threshold,
            "total_charges": sanctuary["billing"]["total_charges"],
            "offer_coach": offer_coach,
            "message": f"Your family has reached ${threshold} in sanctuary charges. " + ("Would you like to schedule a live coach session?" if offer_coach else "You're making good progress.")
        }
        
        try:
            await hoh_ws.send(json.dumps(message))
        except:
            pass
    
    # =========================================================================
    # MEMBER ACTIONS
    # =========================================================================
    
    async def member_exit(self, sanctuary_id: str, member_id: str, reason: str):
        """Member exits sanctuary"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        
        if member:
            member["status"] = "EXITED"
            member["exited_at"] = datetime.now().isoformat()
            member["exit_reason"] = reason
            sanctuary["last_activity_at"] = datetime.now().isoformat()
            
            # Unregister websocket
            self._unregister_websocket(sanctuary_id, member_id)
            
            self._save()
            
            # Record analytics
            self._record_analytics("sanctuary_member_exited", member_id, {
                "sanctuary_id": sanctuary_id,
                "reason": reason
            })
            
            print(f">>> [SANCTUARY] Member {member['name']} EXITED from {sanctuary_id}")
    
    async def complete_session(self, sanctuary_id: str):
        """Complete sanctuary session"""
        sanctuary = self.data["active_sanctuaries"][sanctuary_id]
        
        sanctuary["status"] = "COMPLETED"
        sanctuary["completed_at"] = datetime.now().isoformat()
        
        # Record analytics before moving
        self._record_analytics("sanctuary_completed", sanctuary["head_of_household_id"], {
            "sanctuary_id": sanctuary_id,
            "total_charges": sanctuary["billing"]["total_charges"],
            "total_messages": sanctuary["metrics"]["total_messages"],
            "member_count": len(sanctuary["members"])
        })
        
        # Move to completed
        self.data["completed_sanctuaries"][sanctuary_id] = sanctuary
        del self.data["active_sanctuaries"][sanctuary_id]
        
        # Clean up websocket registry
        if sanctuary_id in self._websocket_registry:
            del self._websocket_registry[sanctuary_id]
        if sanctuary_id in self.sanctuary_connections:
            del self.sanctuary_connections[sanctuary_id]
        
        self._save()
        
        print(f">>> [SANCTUARY] Session {sanctuary_id} COMPLETED")
        # TODO: Archive to Azure Blob
        # await self._archive_to_azure(sanctuary_id)
    
    # =========================================================================
    # GETTER METHODS
    # =========================================================================
    
    def get_member_list(self, sanctuary_id: str) -> List[dict]:
        """Get list of members with their status (for API responses)"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return []
        
        return [
            {
                "user_id": m["user_id"],
                "name": m["name"],
                "status": m.get("status", "ACTIVE"),
                "role": m.get("role", "member")
            }
            for m in sanctuary.get("members", [])
            if m.get("status") not in ["EXITED"]  # Don't show exited members
        ]

    def get_active_member_names(self, sanctuary_id: str) -> List[str]:
        """Get just the names of active members (for display)"""
        members = self.get_member_list(sanctuary_id)
        # Return unique names only
        return list(set([m['name'] for m in members if m.get('status') == 'ACTIVE']))
    
    def get_total_charges(self, sanctuary_id: str) -> float:
        """Get total charges for sanctuary"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return 0.0
        billing = sanctuary.get("billing", {}) or {}
        if not isinstance(billing, dict):
            billing = {}

        # Stored total is used for legacy sanctuaries that predate the itemized ledger.
        try:
            stored = float(billing.get("total_charges", 0.0) or 0.0)
        except Exception:
            stored = 0.0

        charges = billing.get("charges", None)
        base_fee_charged = bool(billing.get("base_fee_charged") is True)

        # Backward-compat:
        # If charges ledger is missing/empty but stored total is non-zero, do NOT "downgrade" to $0.
        # Instead, return stored and (best-effort) backfill a minimal ledger entry so future reads are consistent.
        if not isinstance(charges, list) or len(charges) == 0:
            if stored > 0.0:
                try:
                    if not isinstance(charges, list):
                        charges = []
                    # Prefer a base-fee-looking entry when it matches, otherwise record a legacy total snapshot.
                    if base_fee_charged and abs(stored - 20.0) < 0.01:
                        charges.append({
                            "timestamp": datetime.now().isoformat(),
                            "type": "BASE_FEE",
                            "amount": 20.0,
                            "status": "LEGACY_BACKFILL",
                            "billed_to": sanctuary.get("head_of_household_id") or "",
                            "transaction_id": None,
                        })
                    else:
                        charges.append({
                            "timestamp": datetime.now().isoformat(),
                            "type": "LEGACY_TOTAL",
                            "amount": round(stored, 2),
                            "status": "LEGACY_BACKFILL",
                            "billed_to": sanctuary.get("head_of_household_id") or "",
                            "transaction_id": None,
                        })

                    sanctuary.setdefault("billing", {})
                    if isinstance(sanctuary["billing"], dict):
                        sanctuary["billing"]["charges"] = charges
                        sanctuary["billing"]["total_charges"] = round(stored, 2)
                    self._save()
                except Exception:
                    # Even if backfill fails, returning stored prevents UI regressions.
                    pass
                return round(stored, 2)
            return 0.0

        # Ledger-derived total is authoritative when ledger is present.
        total = 0.0
        for c in charges:
            if not isinstance(c, dict):
                continue
            try:
                total += float(c.get("amount", 0.0) or 0.0)
            except Exception:
                continue

        # Keep stored total in sync (best-effort)
        if abs(stored - total) > 0.001:
            try:
                sanctuary.setdefault("billing", {})
                if isinstance(sanctuary["billing"], dict):
                    sanctuary["billing"]["total_charges"] = round(total, 2)
                self._save()
            except Exception:
                pass
        return round(total, 2)
    
    def get_session(self, sanctuary_id: str) -> Optional[Dict]:
        """Get sanctuary session data"""
        return self.data["active_sanctuaries"].get(sanctuary_id)
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _get_user_profile(self, user_id: str) -> Dict:
        """Load user profile from registry"""
        registry_file = self.data_dir / "user_registry.json"
        try:
            with open(registry_file, 'r') as f:
                registry = json.load(f)
            
            # Find user by hardware_id
            for key, user_data in registry.items():
                profile = user_data.get("profile", {})
                if profile.get("hardware_id") == user_id:
                    return profile
                # Also check nested credentials structure
                if user_data.get("credentials"):
                    profile = user_data.get("profile", {})
                    if profile.get("hardware_id") == user_id:
                        return profile
        except Exception as e:
            print(f">>> [SANCTUARY] Error loading user profile: {e}")
        
        return {}
    
    def _find_member_websocket(self, sanctuary_id: str, user_id: str):
        """Find WebSocket for specific member - uses the registry"""
        return self.get_member_websocket(sanctuary_id, user_id)
    
    def _build_escalation_analysis_prompt(self, message: str, recent_msgs: List, sanctuary: Dict) -> str:
        """Build prompt for escalation analysis"""
        return f"""
Analyze this family sanctuary message for escalation:

MESSAGE: "{message}"

RECENT CONVERSATION:
{self._format_recent_messages(recent_msgs)}

RESPONSE FORMAT (JSON only):
{{
    "escalation_level": "HIGH" | "MEDIUM" | "LOW" | "NONE",
    "primary_emotion": "anger" | "hurt" | "fear" | "sadness",
    "intervention_recommended": true | false,
    "reasoning": "brief explanation"
}}
"""
    
    def _build_coaching_prompt(self, sanctuary: Dict, member: Dict, include_response: bool) -> str:
        """Build prompt for generating coaching"""
        return f"""
You're providing private coaching to {member['name']} in a Family Sanctuary session.

MEMBER CONTEXT:
- Why they came: {member.get('initial_reason', 'Not specified')}
- Their goal: {member.get('personal_goal', 'Not specified')}
- Concerns: {member.get('family_concerns', 'Not specified')}

Generate compassionate coaching (3-4 sentences) that:
1. Validates their emotions
2. Helps them see others' perspectives
3. Suggests a response that expresses needs while staying connected

{'Include a drafted response they can use.' if include_response else ''}
"""
    
    def _format_recent_messages(self, messages: List) -> str:
        """Format recent messages for prompt"""
        return "\n".join([
            f"{m.get('sender_name', 'Unknown')}: {m.get('content', '')}"
            for m in messages[-5:]
        ])
    
    async def _generate_opening_message(self, sanctuary: Dict) -> str:
        """Generate opening message from Little Nate"""
        members_list = "\n".join([f"• {m['name']} ({m.get('role', 'member')})" for m in sanctuary["members"]])
        
        return f"""Welcome everyone to Family Sanctuary. I'm Little Nate, and I'm honored to hold space for this important conversation.

Currently present:
{members_list}

I've heard each of your individual perspectives on why you're here. Let's begin with a moment to acknowledge the courage it takes to have difficult conversations.

Remember: I'm here to help guide the conversation toward connection and understanding. I may pause at times to offer individual coaching or reflection.

Who would like to share first about what brought the family together today?"""

    # =========================================================================
    # PRIVATE COACHING SESSION MANAGEMENT
    # =========================================================================
    
    def start_private_coaching(self, sanctuary_id: str, member_id: str, intervention_id: str) -> dict:
        """Start a private 1-on-1 coaching session"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return {}
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if not member: return {}
        
        triggering_message = ""
        for msg in reversed(sanctuary.get("messages", [])):
            if msg.get("sender_id") == member_id:
                triggering_message = msg.get("content", "")
                break
        
        coaching_session = {
            "session_id": f"COACH_{sanctuary_id}_{member_id}",
            "sanctuary_id": sanctuary_id, "member_id": member_id,
            "member_name": member.get("name", "Member"), "intervention_id": intervention_id,
            "started_at": datetime.now().isoformat(), "triggering_message": triggering_message,
            "messages": [], "attempt_number": 0, "is_deescalated": False, "status": "ACTIVE"
        }
        
        if "coaching_sessions" not in sanctuary: sanctuary["coaching_sessions"] = {}
        sanctuary["coaching_sessions"][member_id] = coaching_session
        member["status"] = "IN_COACHING"
        sanctuary["status"] = "COACHING_ACTIVE"
        self._save()
        print(f">>> [COACHING] Started session for {member.get('name')}")
        return coaching_session
    
    def add_coaching_message(self, sanctuary_id: str, member_id: str, role: str, content: str) -> bool:
        """Add message to private coaching conversation"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return False
        session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not session: return False
        session["messages"].append({"role": role, "content": content, "timestamp": datetime.now().isoformat()})
        self._save()
        return True
    
    def get_coaching_session(self, sanctuary_id: str, member_id: str) -> dict:
        """Get active coaching session for a member"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return {}
        return sanctuary.get("coaching_sessions", {}).get(member_id, {})
    
    def update_coaching_session(self, sanctuary_id: str, member_id: str, updates: dict) -> bool:
        """Update coaching session data"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return False
        session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not session: return False
        session.update(updates)
        self._save()
        return True
    
    def end_coaching_session(self, sanctuary_id: str, member_id: str) -> bool:
        """End coaching session, return member to sanctuary"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return False
        session = sanctuary.get("coaching_sessions", {}).get(member_id)
        if not session: return False
        session["status"] = "COMPLETED"
        session["ended_at"] = datetime.now().isoformat()
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        if member:
            member["status"] = "ACTIVE"
            member["coaching_received"] = member.get("coaching_received", 0) + 1
        if not self.get_active_coaching_sessions(sanctuary_id):
            sanctuary["status"] = "ACTIVE"
        self._save()
        print(f">>> [COACHING] Ended session for {member_id}")
        return True
    
    def get_active_coaching_sessions(self, sanctuary_id: str) -> list:
        """Get all active coaching sessions in sanctuary"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return []
        return [s for s in sanctuary.get("coaching_sessions", {}).values() if s.get("status") == "ACTIVE"]
    
    def get_member_coaching_count(self, sanctuary_id: str, member_id: str) -> int:
        """Get coaching count for member"""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary: return 0
        member = next((m for m in sanctuary["members"] if m["user_id"] == member_id), None)
        return member.get("coaching_received", 0) if member else 0
    
    def increment_coaching_count(self, sanctuary_id: str, member_id: str) -> bool:
        """Increment coaching count (called when session starts)"""
        return True

    # =========================================================================
    # EFT LONGING TRACKER (EFT-informed deepening)
    # =========================================================================

    def initialize_longing_tracker(self, sanctuary_id: str):
        """Ensure EFT tracker exists on a sanctuary session."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        if "eft_tracker" not in sanctuary:
            sanctuary["eft_tracker"] = {
                "member_longings": {},      # {member_id: [longing objects]}
                "negative_cycle": None,     # {pattern, description, roles, identified_at}
                "corrective_moments": [],   # list of corrective moments
                "current_focus": None,      # {type, data, set_at, stay_count}
                "session_stage": "CYCLE_IDENTIFICATION",
            }
            self._save()

    def record_longing(
        self,
        sanctuary_id: str,
        member_id: str,
        longing_type: str,
        expressed_as: str,
        underlying_need: str,
        wound_indicated: str = None,
        affect_when_met: str = None,
        detected_at: str = None,
    ) -> Optional[str]:
        """Record an attachment longing expressed by a member."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_longing_tracker(sanctuary_id)
        tracker = sanctuary["eft_tracker"]

        if member_id not in tracker["member_longings"]:
            tracker["member_longings"][member_id] = []

        import uuid
        longing_id = f"LONG_{uuid.uuid4().hex[:8]}"

        longing = {
            "id": longing_id,
            "type": longing_type,
            "expressed_as": expressed_as,
            "underlying_need": underlying_need,
            "wound_indicated": wound_indicated,
            "affect_when_met": affect_when_met,
            "detected_at": detected_at or datetime.now().isoformat(),
            "acknowledged_by_other": False,
            "corrective_offered": False,
            "corrective_received": False,
        }

        tracker["member_longings"][member_id].append(longing)
        self._save()
        return longing_id

    def record_negative_cycle_marker(
        self,
        sanctuary_id: str,
        pattern: str,
        description: str,
        roles: str = None,
    ):
        """Record a named negative cycle (lightweight marker-based version)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        self.initialize_longing_tracker(sanctuary_id)
        sanctuary["eft_tracker"]["negative_cycle"] = {
            "pattern": pattern,
            "description": description,
            "roles": roles,
            "identified_at": datetime.now().isoformat(),
        }
        self._save()

    def record_corrective_moment(
        self,
        sanctuary_id: str,
        speaker_id: str,
        receiver_id: str,
        longing_addressed: str = None,
        what_was_said: str = None,
        emotional_impact: str = None,
        needs_deepening: bool = True,
    ) -> Optional[str]:
        """Record a corrective emotional moment. IDs may be unknown; store what we have."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_longing_tracker(sanctuary_id)

        import uuid
        moment_id = f"CEM_{uuid.uuid4().hex[:8]}"

        moment = {
            "id": moment_id,
            "speaker_id": speaker_id or "",
            "receiver_id": receiver_id or "",
            "longing_addressed": longing_addressed,
            "what_was_said": what_was_said,
            "emotional_impact": emotional_impact,
            "needs_deepening": bool(needs_deepening),
            "deepened": False,
            "acknowledged": False,
            "timestamp": datetime.now().isoformat(),
        }

        sanctuary["eft_tracker"]["corrective_moments"].append(moment)
        sanctuary["eft_tracker"]["current_focus"] = {
            "type": "CORRECTIVE_MOMENT",
            "data": {"moment_id": moment_id, "description": what_was_said or emotional_impact or ""},
            "set_at": datetime.now().isoformat(),
            "stay_count": 0,
        }
        self._save()
        return moment_id

    def set_current_focus(self, sanctuary_id: str, focus_type: str, focus_data: dict):
        """Set what Little Nate should stay with (do not move on)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        self.initialize_longing_tracker(sanctuary_id)
        sanctuary["eft_tracker"]["current_focus"] = {
            "type": focus_type,
            "data": focus_data or {},
            "set_at": datetime.now().isoformat(),
            "stay_count": int((sanctuary["eft_tracker"].get("current_focus") or {}).get("stay_count", 0) or 0),
        }
        self._save()

    def bump_focus_stay_count(self, sanctuary_id: str):
        """Increment stay_count to help Nate 'slow down' on tender moments."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        tracker = sanctuary.get("eft_tracker")
        if not tracker or not tracker.get("current_focus"):
            return

        tracker["current_focus"]["stay_count"] = int(tracker["current_focus"].get("stay_count", 0) or 0) + 1
        self._save()

    def get_eft_context(self, sanctuary_id: str) -> dict:
        """Get EFT tracker context for AI prompt building."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {}

        tracker = sanctuary.get("eft_tracker", {})
        member_names = {m["user_id"]: m.get("name", "Member") for m in sanctuary.get("members", [])}

        unacknowledged = []
        for member_id, longings in (tracker.get("member_longings", {}) or {}).items():
            for longing in longings or []:
                if not longing.get("acknowledged_by_other"):
                    unacknowledged.append({
                        "member_id": member_id,
                        "member_name": member_names.get(member_id, "Unknown"),
                        **longing,
                    })

        undeepened = [
            m for m in (tracker.get("corrective_moments", []) or [])
            if m.get("needs_deepening") and not m.get("deepened")
        ]

        return {
            "unacknowledged_longings": unacknowledged,
            "negative_cycle": tracker.get("negative_cycle"),
            "corrective_moments": tracker.get("corrective_moments", []),
            "undeepened_moments": undeepened,
            "current_focus": tracker.get("current_focus"),
            "session_stage": tracker.get("session_stage", "CYCLE_IDENTIFICATION"),
            "member_names": member_names,
        }

    def mark_longing_acknowledged(self, sanctuary_id: str, member_id: str, longing_id: str):
        """Mark a longing as acknowledged by another member."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        tracker = sanctuary.get("eft_tracker", {})
        longings = (tracker.get("member_longings", {}) or {}).get(member_id, []) or []
        for longing in longings:
            if longing.get("id") == longing_id:
                longing["acknowledged_by_other"] = True
                longing["acknowledged_at"] = datetime.now().isoformat()
                self._save()
                return

    def mark_moment_deepened(self, sanctuary_id: str, moment_id: str):
        """Mark a corrective moment as deepened."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        tracker = sanctuary.get("eft_tracker", {})
        for moment in (tracker.get("corrective_moments", []) or []):
            if moment.get("id") == moment_id:
                moment["deepened"] = True
                moment["deepened_at"] = datetime.now().isoformat()
                self._save()
                return

    # =========================================================================
    # MEMORY RECONSOLIDATION TRACKER (Ecker/Ticic/Hulley + evocative imagery)
    # =========================================================================

    def initialize_reconsolidation_tracker(self, sanctuary_id: str):
        """Ensure reconsolidation tracker exists on a sanctuary session."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        if "reconsolidation_tracker" not in sanctuary:
            sanctuary["reconsolidation_tracker"] = {
                "schemas": {},                 # schema_id -> schema record
                "activations": [],             # activation records
                "imagery_events": [],          # imagery used events
                "activation_deepenings": [],   # deepen events
                "mismatches": [],              # mismatch records
                "consolidations": [],          # consolidation records
                "reconsolidations": [],        # recon completion records
                "active_windows": [],          # [{schema_id, member_id, activated_at, window_expires, mismatch_delivered, needs_consolidation}]
            }
            self._save()

    def record_schema(
        self,
        sanctuary_id: str,
        member_id: str,
        member_name: str,
        core_belief: str,
        emotional_charge: str = "moderate",
        origin_hint: str = None,
        related_longing: str = None,
    ) -> Optional[str]:
        """Record or reuse a schema (core wound/belief)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]

        # Reuse schema if same member + belief already exists
        for sid, s in (tr.get("schemas") or {}).items():
            if s.get("member_id") == member_id and (s.get("core_belief") or "").strip().lower() == (core_belief or "").strip().lower():
                s["activation_count"] = int(s.get("activation_count", 0) or 0)
                self._save()
                return sid

        import uuid
        schema_id = f"SCHEMA_{uuid.uuid4().hex[:8]}"
        tr["schemas"][schema_id] = {
            "id": schema_id,
            "member_id": member_id,
            "member_name": member_name,
            "core_belief": core_belief,
            "emotional_charge": emotional_charge,
            "origin_hint": origin_hint,
            "related_longing": related_longing,
            "activation_count": 0,
            "last_activated": None,
            "mismatch_offered": False,
            "reconsolidation_complete": False,
        }
        self._save()
        return schema_id

    def record_imagery_used(
        self,
        sanctuary_id: str,
        member_id: str,
        member_name: str,
        imagery_type: str,
        prompt: str,
    ) -> None:
        """Record an evocative imagery prompt used to activate limbic experience."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        tr["imagery_events"].append({
            "timestamp": datetime.now().isoformat(),
            "member_id": member_id,
            "member_name": member_name,
            "type": imagery_type,
            "prompt": (prompt or "")[:240],
        })
        tr["imagery_events"] = tr["imagery_events"][-50:]
        self._save()

    def record_schema_activation(
        self,
        sanctuary_id: str,
        member_id: str,
        schema_id: str,
        activation_method: str,
        activation_prompt: str,
        member_response: str = None,
        limbic_engagement: str = "moderate",
    ) -> Optional[str]:
        """Record a schema activation and start a ~5 hour reconsolidation window."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        schema = (tr.get("schemas") or {}).get(schema_id)
        if not schema:
            return None

        import uuid
        activation_id = f"ACT_{uuid.uuid4().hex[:8]}"
        now = datetime.now()
        window_expires = (now + timedelta(hours=5)).isoformat()
        tr["activations"].append({
            "id": activation_id,
            "schema_id": schema_id,
            "member_id": member_id,
            "activated_at": now.isoformat(),
            "activation_method": activation_method,
            "activation_prompt": (activation_prompt or "")[:240],
            "member_response": (member_response or "")[:240] if member_response else None,
            "limbic_engagement": limbic_engagement,
            "window_expires": window_expires,
        })
        tr["activations"] = tr["activations"][-100:]

        schema["activation_count"] = int(schema.get("activation_count", 0) or 0) + 1
        schema["last_activated"] = now.isoformat()

        tr["active_windows"].append({
            "schema_id": schema_id,
            "member_id": member_id,
            "activated_at": now.isoformat(),
            "window_expires": window_expires,
            "mismatch_delivered": False,
            "needs_consolidation": True,
        })
        tr["active_windows"] = tr["active_windows"][-20:]

        self._save()
        return activation_id

    def record_activation_deepened(
        self,
        sanctuary_id: str,
        member_id: str,
        member_name: str,
        what_emerged: str,
    ) -> None:
        """Record deepening of activation (parts/age/somatic detail)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        tr["activation_deepenings"].append({
            "timestamp": datetime.now().isoformat(),
            "member_id": member_id,
            "member_name": member_name,
            "what_emerged": (what_emerged or "")[:260],
        })
        tr["activation_deepenings"] = tr["activation_deepenings"][-50:]
        self._save()

    def record_mismatch(
        self,
        sanctuary_id: str,
        schema_id: str,
        activation_id: str,
        mismatch_type: str,
        what_happened: str,
        old_expectation: str,
        new_experience: str,
        emotional_impact: str = None,
    ) -> Optional[str]:
        """Record prediction error / mismatch while schema is active."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        import uuid
        mismatch_id = f"MISMATCH_{uuid.uuid4().hex[:8]}"
        tr["mismatches"].append({
            "id": mismatch_id,
            "schema_id": schema_id,
            "activation_id": activation_id,
            "mismatch_type": mismatch_type,
            "what_happened": (what_happened or "")[:240],
            "old_expectation": (old_expectation or "")[:120],
            "new_experience": (new_experience or "")[:120],
            "emotional_impact": (emotional_impact or "")[:240] if emotional_impact else None,
            "created_at": datetime.now().isoformat(),
        })
        tr["mismatches"] = tr["mismatches"][-80:]

        schema = (tr.get("schemas") or {}).get(schema_id)
        if schema:
            schema["mismatch_offered"] = True

        # Update the most recent active window for this schema
        for w in reversed(tr.get("active_windows", []) or []):
            if w.get("schema_id") == schema_id:
                w["mismatch_delivered"] = True
                w["needs_consolidation"] = True
                break

        self._save()
        return mismatch_id

    def record_consolidation(
        self,
        sanctuary_id: str,
        schema_id: str,
        response: str,
        depth: str = "moderate",
    ) -> None:
        """Record consolidation in progress (helping the new learning land)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        tr["consolidations"].append({
            "timestamp": datetime.now().isoformat(),
            "schema_id": schema_id,
            "response": (response or "")[:240],
            "depth": depth,
        })
        tr["consolidations"] = tr["consolidations"][-60:]

        # Mark window as having consolidation evidence
        for w in reversed(tr.get("active_windows", []) or []):
            if w.get("schema_id") == schema_id:
                w["needs_consolidation"] = False
                break

        self._save()

    def record_reconsolidation_complete(
        self,
        sanctuary_id: str,
        schema_id: str,
        old_belief: str,
        new_belief: str,
        verification_response: str,
        confidence: str = "emerging",
    ) -> Optional[str]:
        """Record a verified belief shift (reconsolidation)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return None

        self.initialize_reconsolidation_tracker(sanctuary_id)
        tr = sanctuary["reconsolidation_tracker"]
        import uuid
        recon_id = f"RECON_{uuid.uuid4().hex[:8]}"
        tr["reconsolidations"].append({
            "id": recon_id,
            "schema_id": schema_id,
            "old_belief": (old_belief or "")[:200],
            "new_belief": (new_belief or "")[:200],
            "verification_response": (verification_response or "")[:240],
            "confidence": confidence,
            "completed_at": datetime.now().isoformat(),
        })
        tr["reconsolidations"] = tr["reconsolidations"][-50:]

        schema = (tr.get("schemas") or {}).get(schema_id)
        if schema:
            schema["reconsolidation_complete"] = True

        # Clear windows for this schema (keep list bounded)
        tr["active_windows"] = [w for w in (tr.get("active_windows", []) or []) if w.get("schema_id") != schema_id][-20:]
        self._save()
        return recon_id

    def get_reconsolidation_context(self, sanctuary_id: str) -> dict:
        """Get reconsolidation context for AI prompt building."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {}

        tr = sanctuary.get("reconsolidation_tracker", {}) or {}
        schemas = tr.get("schemas", {}) or {}

        # Active windows that haven't expired yet
        now = datetime.now()
        active_windows = []
        for w in (tr.get("active_windows", []) or []):
            try:
                exp = datetime.fromisoformat(w.get("window_expires"))
                if exp > now:
                    active_windows.append(w)
            except Exception:
                continue

        # Most recent mismatches + reconsolidations
        recent_mismatches = (tr.get("mismatches", []) or [])[-5:]
        recent_recons = (tr.get("reconsolidations", []) or [])[-5:]

        return {
            "active_windows": active_windows[-8:],
            "schemas": list(schemas.values())[-12:],
            "recent_mismatches": recent_mismatches,
            "recent_reconsolidations": recent_recons,
        }

    # =========================================================================
    # BIOMETRIC HEALTH INTEGRATION (Sanctuary-scoped)
    # =========================================================================

    def store_member_biometrics(self, sanctuary_id: str, member_id: str, biometric_data: dict) -> bool:
        """Store a biometric snapshot for a member (persisted)."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return False

        if "member_biometrics" not in sanctuary:
            sanctuary["member_biometrics"] = {}

        # Minimal normalization + bounds
        safe = dict(biometric_data or {})
        safe["received_at"] = datetime.now().isoformat()
        sanctuary["member_biometrics"][member_id] = safe
        self._save()
        return True

    def update_realtime_heart_rate(self, sanctuary_id: str, member_id: str, bpm: int, timestamp: str = None) -> dict:
        """
        Update real-time HR for a member (in-memory ring buffer).
        NOTE: We do NOT call _save() here to avoid excessive disk writes.
        """
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"stored": False}

        if "realtime_biometrics" not in sanctuary:
            sanctuary["realtime_biometrics"] = {}

        if member_id not in sanctuary["realtime_biometrics"]:
            sanctuary["realtime_biometrics"][member_id] = {
                "heart_rate_history": [],
                "baseline_hr": None,
                "current_hr": None,
                "elevated_since": None,
                "peak_hr": None,
                "peak_hr_at": None,
                "support_last_sent_at": None,  # throttle support prompts
            }

        rt = sanctuary["realtime_biometrics"][member_id]
        reading = {"bpm": int(bpm), "timestamp": timestamp or datetime.now().isoformat()}
        rt["heart_rate_history"].append(reading)
        rt["heart_rate_history"] = rt["heart_rate_history"][-60:]

        rt["current_hr"] = int(bpm)
        if rt["peak_hr"] is None or int(bpm) > int(rt["peak_hr"]):
            rt["peak_hr"] = int(bpm)
            rt["peak_hr_at"] = reading["timestamp"]

        if rt["baseline_hr"] is None and len(rt["heart_rate_history"]) >= 5:
            first_five = [r["bpm"] for r in rt["heart_rate_history"][:5]]
            rt["baseline_hr"] = sum(first_five) / 5.0

        escalation = {"elevated": False, "duration_seconds": 0}
        if rt["baseline_hr"] and int(bpm) > float(rt["baseline_hr"]) * 1.2:
            if rt["elevated_since"] is None:
                rt["elevated_since"] = datetime.now().isoformat()
            escalation["elevated"] = True
            try:
                elevated_start = datetime.fromisoformat(rt["elevated_since"])
                escalation["duration_seconds"] = (datetime.now() - elevated_start).total_seconds()
            except Exception:
                escalation["duration_seconds"] = 0
        else:
            rt["elevated_since"] = None

        return {
            "stored": True,
            "current_hr": int(bpm),
            "baseline_hr": rt["baseline_hr"],
            "escalation": escalation,
        }

    def get_member_biometric_context(self, sanctuary_id: str, member_id: str) -> dict:
        """Get a normalized biometric context for AI prompts."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return {"has_biometrics": False}

        static = sanctuary.get("member_biometrics", {}).get(member_id, {}) or {}
        realtime = sanctuary.get("realtime_biometrics", {}).get(member_id, {}) or {}

        context = {"has_biometrics": bool(static) or bool(realtime), "source": static.get("source", "unknown")}
        if not context["has_biometrics"]:
            return context

        # Sleep
        sleep = static.get("sleep", {}) or {}
        if sleep.get("total_hours") is not None:
            hours = float(sleep.get("total_hours") or 0)
            context["sleep"] = {
                "hours": hours,
                "quality": sleep.get("quality", "unknown"),
                "deprived": bool(sleep.get("sleep_deprived", False) or hours < 5),
                "deep_hours": sleep.get("deep_hours"),
                "rem_hours": sleep.get("rem_hours"),
            }

        # HRV
        hrv = static.get("hrv", {}) or {}
        if hrv.get("average_ms") is not None:
            avg_ms = float(hrv.get("average_ms") or 0)
            context["hrv"] = {
                "average_ms": avg_ms,
                "regulation": hrv.get("regulation_level", hrv.get("regulation", "unknown")),
                "stress_indicator": bool(hrv.get("stress_indicator", False) or avg_ms < 30),
            }

        # Activity
        activity = static.get("activity", {}) or {}
        if activity.get("daily_average") is not None:
            daily_avg = float(activity.get("daily_average") or 0)
            context["activity"] = {
                "level": activity.get("activity_level", "unknown"),
                "daily_average": daily_avg,
                "today": activity.get("today"),
                "sedentary": bool(activity.get("sedentary_pattern", False) or daily_avg < 3000),
            }

        # Real-time HR
        if realtime.get("current_hr") is not None:
            rt = {
                "current": realtime.get("current_hr"),
                "baseline": realtime.get("baseline_hr"),
                "peak": realtime.get("peak_hr"),
                "elevated": realtime.get("elevated_since") is not None,
                "elevated_duration_seconds": 0,
            }
            if realtime.get("elevated_since"):
                try:
                    elevated_time = datetime.fromisoformat(realtime["elevated_since"])
                    rt["elevated_duration_seconds"] = (datetime.now() - elevated_time).total_seconds()
                except Exception:
                    rt["elevated_duration_seconds"] = 0
            context["realtime_hr"] = rt

        return context

    def detect_physiological_escalation(self, sanctuary_id: str, member_id: str) -> dict:
        """Detect whether member looks physiologically escalated (best-effort)."""
        context = self.get_member_biometric_context(sanctuary_id, member_id)
        result = {"escalated": False, "signals": [], "severity": "none", "recommendations": []}
        if not context.get("has_biometrics"):
            return result

        severity_score = 0

        rt = context.get("realtime_hr", {}) or {}
        if rt.get("elevated"):
            dur = float(rt.get("elevated_duration_seconds") or 0)
            if dur > 30:
                result["signals"].append({
                    "type": "elevated_hr",
                    "message": f"Elevated HR for {int(dur)}s",
                    "value": rt.get("current"),
                    "baseline": rt.get("baseline"),
                })
                severity_score += 1
            if dur > 60:
                severity_score += 1
                result["recommendations"].append("pause_and_breathe")
            if dur > 180:
                severity_score += 1
                result["recommendations"].append("grounding_exercise")

        hrv = context.get("hrv", {}) or {}
        if hrv.get("stress_indicator"):
            result["signals"].append({
                "type": "low_hrv",
                "message": "Low HRV indicates stress",
                "value": hrv.get("average_ms"),
            })
            severity_score += 1

        sleep = context.get("sleep", {}) or {}
        if sleep.get("deprived"):
            result["signals"].append({
                "type": "sleep_deprived",
                "message": f"Sleep deprived ({float(sleep.get('hours') or 0):.1f}h)",
                "value": sleep.get("hours"),
            })
            severity_score += 1
            result["recommendations"].append("acknowledge_fatigue")

        activity = context.get("activity", {}) or {}
        if activity.get("sedentary"):
            result["signals"].append({
                "type": "sedentary",
                "message": "Low activity pattern",
                "value": activity.get("daily_average"),
            })

        if severity_score == 0:
            result["severity"] = "none"
        elif severity_score == 1:
            result["severity"] = "mild"
        elif severity_score == 2:
            result["severity"] = "moderate"
            result["escalated"] = True
        else:
            result["severity"] = "high"
            result["escalated"] = True

        return result

    def format_biometric_context_for_ai(self, sanctuary_id: str) -> str:
        """Format all member biometrics into a prompt-safe section."""
        sanctuary = self.data["active_sanctuaries"].get(sanctuary_id)
        if not sanctuary:
            return ""

        sections = []
        for member in sanctuary.get("members", []):
            if member.get("status") == "EXITED":
                continue
            mid = member.get("user_id")
            name = member.get("name", "Member")
            bio = self.get_member_biometric_context(sanctuary_id, mid)
            if not bio.get("has_biometrics"):
                continue

            lines = [f"{name}:"]
            sleep = bio.get("sleep")
            if sleep:
                if sleep.get("deprived"):
                    lines.append("  - Sleep: deprived")
                else:
                    lines.append(f"  - Sleep: {sleep.get('quality', 'unknown')}")

            hrv = bio.get("hrv")
            if hrv:
                if hrv.get("stress_indicator"):
                    lines.append("  - HRV: low (stress indicator)")
                else:
                    lines.append(f"  - HRV: {hrv.get('regulation', 'unknown')} regulation")

            rt = bio.get("realtime_hr")
            if rt:
                if rt.get("elevated"):
                    lines.append("  - HR: elevated (fight/flight likely)")
                else:
                    lines.append("  - HR: stable")

            activity = bio.get("activity")
            if activity and activity.get("sedentary"):
                lines.append("  - Activity: low pattern")

            sections.append("\n".join(lines))

        if not sections:
            return ""

        return (
            "PHYSIOLOGICAL AWARENESS (session-scoped):\n"
            + "\n\n".join(sections)
            + "\n\nGUIDELINES:\n"
            + "- If HR is elevated or HRV indicates stress, prioritize regulation over deepening/reconsolidation.\n"
            + "- Do not reveal exact numbers to the group; speak in general terms (\"your body seems activated\").\n"
            + "- If sleep deprived, go gentler/slower.\n"
        )

    def get_breathing_exercise(self, exercise_type: str = "box") -> dict:
        """Get a breathing exercise payload for UI."""
        exercises = {
            "box": {"type": "box_breathing", "inhale": 4, "hold": 4, "exhale": 4, "cycles": 4},
            "4-7-8": {"type": "4-7-8", "inhale": 4, "hold": 7, "exhale": 8, "cycles": 4},
            "physiological_sigh": {"type": "physiological_sigh", "inhale_1": 2, "inhale_2": 1, "exhale": 6, "cycles": 5},
            "coherent": {"type": "coherent_breathing", "inhale": 5, "exhale": 5, "cycles": 6},
        }
        return exercises.get(exercise_type, exercises["box"])

    # =========================================================================
    # LIVE COACH BRIEFING SYSTEM (Add-on)
    # =========================================================================

    def generate_coach_briefing(
        self,
        sanctuary_id: str,
        member_profiles: dict,  # {member_id: profile_dict}
        metrics_engine=None,
        memory_system=None,
        include_transcripts: bool = True,
        max_transcript_messages: int = 60,
    ) -> dict:
        """
        Generate a comprehensive briefing document for a live human coach.

        Add-on only: reads existing sanctuary state + trackers; does not alter
        any sanctuary mechanics, billing, or AI behavior.
        """
        sanctuary = self.data.get("active_sanctuaries", {}).get(sanctuary_id)
        if not sanctuary:
            return {"error": "Sanctuary not found"}

        members = [m for m in (sanctuary.get("members", []) or []) if m.get("status") != "EXITED"]
        family_id = sanctuary.get("family_id") or ""

        eft = sanctuary.get("eft_tracker", {}) or {}
        recon = sanctuary.get("reconsolidation_tracker", {}) or {}

        # Build convenience lookups
        member_names = {m.get("user_id"): (m.get("name") or member_profiles.get(m.get("user_id"), {}).get("name") or "Member") for m in members}

        def risk_bucket(risk: str) -> str:
            r = (risk or "").upper()
            if r in ("CRITICAL", "RED", "P0", "P1", "HIGH"):
                return "RED"
            if r in ("MEDIUM", "MODERATE", "YELLOW", "P2"):
                return "YELLOW"
            return "GREEN"

        def worst_bucket(buckets: List[str]) -> str:
            if "RED" in buckets:
                return "RED"
            if "YELLOW" in buckets:
                return "YELLOW"
            return "GREEN"

        # Pull per-member metrics
        per_member_metrics = {}
        risk_notes = []
        buckets = []
        for mid, prof in (member_profiles or {}).items():
            try:
                m = metrics_engine.load_metrics(prof) if metrics_engine else {}
                ns = (m.get("nevedal_state") or {})
            except Exception:
                ns = {}
            per_member_metrics[mid] = ns
            bucket = risk_bucket(ns.get("risk_level"))
            buckets.append(bucket)
            if bucket != "GREEN":
                risk_notes.append(f"{prof.get('name', mid)}: {ns.get('risk_level', 'UNKNOWN')}")

        # Stuckness indicators (best-effort)
        stuckness = []
        member_longings = (eft.get("member_longings") or {})
        unack_count = 0
        for mid, longings in member_longings.items():
            for l in (longings or []):
                if not l.get("acknowledged_by_other") and not l.get("corrective_received"):
                    unack_count += 1
        if unack_count >= 2:
            stuckness.append(f"{unack_count} unacknowledged longings still unmet")

        focus = eft.get("current_focus") or None
        if focus and focus.get("type"):
            stuckness.append(f"Current focus: {focus.get('type')}")

        recon_ctx = self.get_reconsolidation_context(sanctuary_id) or {}
        if (recon_ctx.get("active_windows") or []):
            stuckness.append("Active reconsolidation window(s) present")

        # Primary focus
        primary_focus = "Stabilize and re-enter the family cycle with attunement."
        if focus and focus.get("data"):
            desc = (focus.get("data") or {}).get("description") or ""
            if desc:
                primary_focus = desc[:220]
        else:
            # use most recent longing, if any
            recent_longing = None
            for mid, longings in member_longings.items():
                if longings:
                    recent_longing = longings[-1]
            if recent_longing:
                primary_focus = f"Help {member_names.get(recent_longing.get('member_id'), 'member')} stay with longing: {recent_longing.get('type', 'CONNECTION')}"

        # Key transcripts (best-effort)
        transcripts = []
        if include_transcripts:
            msgs = (sanctuary.get("messages", []) or [])[-max_transcript_messages:]
            for m in msgs:
                transcripts.append({
                    "timestamp": m.get("timestamp"),
                    "sender_id": m.get("sender_id"),
                    "sender_name": m.get("sender_name") or member_names.get(m.get("sender_id")) or "Unknown",
                    "message_type": m.get("message_type") or m.get("type") or "message",
                    "content": (m.get("content") or "")[:1200],
                })

        # Individual profiles
        individual = {}
        for m in members:
            mid = m.get("user_id")
            prof = member_profiles.get(mid, {}) if member_profiles else {}
            ns = per_member_metrics.get(mid, {}) or {}

            longings = (member_longings.get(mid) or [])[-8:]
            longing_rows = [{
                "type": l.get("type"),
                "expressed_as": (l.get("expressed_as") or "")[:220],
                "need": (l.get("underlying_need") or "")[:220],
                "acknowledged": bool(l.get("acknowledged_by_other")),
                "received": bool(l.get("corrective_received")),
                "detected_at": l.get("detected_at"),
            } for l in longings]

            member_schemas = []
            try:
                schemas = (recon_ctx.get("schemas") or [])
                member_schemas = [s for s in schemas if (s.get("member_id") == mid or s.get("member_name") == prof.get("name"))][-6:]
            except Exception:
                member_schemas = []

            bio = self.get_member_biometric_context(sanctuary_id, mid)
            escalation = self.detect_physiological_escalation(sanctuary_id, mid)

            mem = ""
            try:
                if memory_system and prof:
                    mem = memory_system.recall(prof, limit=5) or ""
            except Exception:
                mem = ""

            individual[mid] = {
                "name": prof.get("name") or m.get("name") or "Unknown",
                "role": m.get("role") or prof.get("family_role") or "MEMBER",
                "risk_level": ns.get("risk_level", "LOW"),
                "metrics": {
                    "C_emo": ns.get("C_emo"),
                    "GAP": ns.get("GAP"),
                    "Quantum": ns.get("Quantum"),
                    "engagement": ns.get("engagement"),
                    "stress_level": ns.get("stress_level"),
                    "anxiety_level": ns.get("anxiety_level"),
                    "session_count": ns.get("session_count"),
                },
                "longings": longing_rows,
                "schemas": [{
                    "schema": (s.get("core_belief") or s.get("belief") or s.get("schema") or "")[:240],
                    "emotional_charge": s.get("emotional_charge"),
                    "origin_hint": s.get("origin_hint"),
                    "reconsolidation_complete": bool(s.get("reconsolidation_complete")),
                } for s in member_schemas],
                "biometrics": {
                    "has_biometrics": bool(bio.get("has_biometrics")),
                    "sleep": bio.get("sleep"),
                    "hrv": bio.get("hrv"),
                    "activity": bio.get("activity"),
                    "realtime_hr": bio.get("realtime_hr"),
                    "escalation": escalation,
                },
                "recent_memory": mem[:1800] if mem else "",
            }

        # Relationship dynamics (EFT negative cycle if available)
        negative_cycle = eft.get("negative_cycle") or {}
        relationship_dynamics = {
            "pattern": negative_cycle.get("pattern") or "Unknown",
            "description": negative_cycle.get("description") or "",
            "roles": negative_cycle.get("roles") or "",
            "identified_at": negative_cycle.get("identified_at") or "",
        }

        # Therapeutic work summary
        corrective = (eft.get("corrective_moments") or [])[-12:]
        therapeutic_work = {
            "corrective_moments": [{
                "timestamp": c.get("timestamp"),
                "speaker": member_names.get(c.get("speaker_id"), c.get("speaker_id") or ""),
                "receiver": member_names.get(c.get("receiver_id"), c.get("receiver_id") or ""),
                "longing_addressed": c.get("longing_addressed"),
                "what_was_said": (c.get("what_was_said") or "")[:240],
                "needs_deepening": bool(c.get("needs_deepening")),
                "deepened": bool(c.get("deepened")),
                "acknowledged": bool(c.get("acknowledged")),
            } for c in corrective],
            "reconsolidation": {
                "active_windows": (recon_ctx.get("active_windows") or [])[-8:],
                "recent_mismatches": (recon_ctx.get("recent_mismatches") or [])[-6:],
                "recent_reconsolidations": (recon_ctx.get("recent_reconsolidations") or [])[-6:],
            }
        }

        # Coaching recommendations (best-effort + safety)
        recommendations = {
            "primary_focus": primary_focus,
            "what_to_avoid": [
                "Rushing tender moments (slow down after longing emerges).",
                "Over-reassuring pursuer anxiety (increase tolerance for uncertainty).",
                "Direct 'how do you feel' questions when a withdrawer is activated.",
            ],
            "questions_to_ask": [
                "What happens inside right before you shut down / pursue harder?",
                "What do you need (longing) that you’re afraid to ask for?",
                "Can you stay with that feeling for 10 seconds and let it land?",
            ],
            "watch_for": [
                "Escalation signals: elevated HR / low HRV / sleep deprivation.",
                "Cycle cues: repeated questions → silence → pursuit → shutdown.",
            ],
        }

        briefing = {
            "briefing_id": f"BRIEF_{uuid.uuid4().hex[:8]}",
            "generated_at": datetime.now().isoformat(),
            "sanctuary_id": sanctuary_id,
            "family_id": family_id,
            "executive_summary": {
                "status": sanctuary.get("status"),
                "members_present": [member_names.get(m.get("user_id"), "Member") for m in members],
                "referral_reason": "; ".join(stuckness[:2]) if stuckness else "Live coach briefing requested",
                "risk_level": worst_bucket(buckets),
                "risk_notes": risk_notes[:6],
                "primary_focus": primary_focus,
                "stuckness_indicators": stuckness[:6],
            },
            "individual_profiles": individual,
            "relationship_dynamics": relationship_dynamics,
            "therapeutic_work": therapeutic_work,
            "clinical_considerations": {
                "risk_level": worst_bucket(buckets),
                "risk_notes": risk_notes[:10],
                "biometric_patterns": self.format_biometric_context_for_ai(sanctuary_id)[:1800],
            },
            "recommendations": recommendations,
            "key_transcripts": transcripts,
            "metrics": {
                "by_member": {mid: {
                    "name": (member_profiles.get(mid, {}) or {}).get("name") or member_names.get(mid) or mid,
                    "C_emo": (per_member_metrics.get(mid, {}) or {}).get("C_emo"),
                    "GAP": (per_member_metrics.get(mid, {}) or {}).get("GAP"),
                    "Quantum": (per_member_metrics.get(mid, {}) or {}).get("Quantum"),
                    "engagement": (per_member_metrics.get(mid, {}) or {}).get("engagement"),
                    "risk_level": (per_member_metrics.get(mid, {}) or {}).get("risk_level"),
                    "mood_current": (per_member_metrics.get(mid, {}) or {}).get("mood_current"),
                } for mid in (member_profiles or {}).keys()}
            }
        }

        return briefing
