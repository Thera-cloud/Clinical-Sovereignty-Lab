"""
LITTLE NATE — Night School WebSocket Handlers
Version: 1.0
Date: January 21, 2026

WebSocket message handlers for Night School Director integration.
Add these handlers to bridge_server_hybrid.py.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Import from services (try multiple paths for different run contexts)
try:
    from app.services.night_school_director import (
        NightSchoolDirector,
        WisdomCategory,
        DojoPersona,
        create_night_school_director
    )
except ImportError:
    try:
        from ..services.night_school_director import (
            NightSchoolDirector,
            WisdomCategory,
            DojoPersona,
            create_night_school_director
        )
    except ImportError:
        print("[!] night_school_director not found - Dojo features disabled")
        NightSchoolDirector = None
        WisdomCategory = None
        DojoPersona = None
        create_night_school_director = None


class NightSchoolHandler:
    """Handles Night School WebSocket messages"""
    
    def __init__(self, vault_root: Path, db_pool=None):
        if create_night_school_director:
            self.director = create_night_school_director(vault_root, db_pool)
            print(">>> [NIGHT SCHOOL] Handler initialized")
        else:
            self.director = None
            print("[!] NightSchoolHandler: Director unavailable - Dojo disabled")
        self.active_dojo_sessions: Dict[str, Any] = {}  # websocket -> DojoSession
    
    # -------------------------------------------------------------------------
    # WISDOM HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_get_wisdom(self, websocket, data: Dict, profile: Dict):
        """Get wisdom entries"""
        category = data.get('category')
        limit = min(data.get('limit', 100), 500)
        
        cat = WisdomCategory(category) if category else None
        entries = self.director.get_wisdom(category=cat, limit=limit)
        
        await websocket.send(json.dumps({
            "type": "night_school_wisdom",
            "count": len(entries),
            "data": [e.to_dict() for e in entries]
        }))
    
    async def handle_add_wisdom(self, websocket, data: Dict, profile: Dict):
        """Add a wisdom entry (admin only)"""
        if profile.get('role') not in ['ADMIN', 'COACH']:
            await self._send_error(websocket, "Admin access required")
            return
        
        try:
            entry = self.director.add_wisdom_entry(
                content=data.get('content', ''),
                category=WisdomCategory(data.get('category', 'general')),
                source='manual_entry',
                confidence=data.get('confidence', 0.5),
                auto_approve=data.get('auto_approve', False),
                approved_by=profile.get('username') if data.get('auto_approve') else None,
                tags=data.get('tags', [])
            )
            
            await websocket.send(json.dumps({
                "type": "night_school_wisdom_added",
                "entry": entry.to_dict()
            }))
        except Exception as e:
            await self._send_error(websocket, f"Error adding wisdom: {e}")
    
    async def handle_approve_wisdom(self, websocket, data: Dict, profile: Dict):
        """Approve a pending wisdom entry"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        entry_id = data.get('entry_id')
        success = self.director.approve_wisdom_entry(entry_id, profile.get('username', 'admin'))
        
        await websocket.send(json.dumps({
            "type": "night_school_wisdom_approved",
            "entry_id": entry_id,
            "success": success
        }))
    
    async def handle_delete_wisdom(self, websocket, data: Dict, profile: Dict):
        """Delete a wisdom entry"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        entry_id = data.get('entry_id')
        success = self.director.delete_wisdom_entry(entry_id)
        
        await websocket.send(json.dumps({
            "type": "night_school_wisdom_deleted",
            "entry_id": entry_id,
            "success": success
        }))
    
    # -------------------------------------------------------------------------
    # VERSION CONTROL HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_get_versions(self, websocket, data: Dict, profile: Dict):
        """Get version history"""
        versions = self.director.get_versions()
        
        await websocket.send(json.dumps({
            "type": "night_school_versions",
            "count": len(versions),
            "data": [v.to_dict() for v in versions]
        }))
    
    async def handle_create_snapshot(self, websocket, data: Dict, profile: Dict):
        """Create a wisdom snapshot"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        description = data.get('description', 'Manual snapshot')
        version = self.director.create_snapshot(
            created_by=profile.get('username', 'admin'),
            description=description
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_snapshot_created",
            "version": version.to_dict()
        }))
    
    async def handle_revert_version(self, websocket, data: Dict, profile: Dict):
        """Revert to a previous version"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        version_id = data.get('version_id')
        success = self.director.revert_to_version(
            version_id,
            reverted_by=profile.get('username', 'admin')
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_version_reverted",
            "version_id": version_id,
            "success": success
        }))
    
    async def handle_compare_versions(self, websocket, data: Dict, profile: Dict):
        """Compare two versions"""
        version_a = data.get('version_a')
        version_b = data.get('version_b')
        
        comparison = self.director.compare_versions(version_a, version_b)
        
        await websocket.send(json.dumps({
            "type": "night_school_version_comparison",
            "data": comparison
        }))
    
    # -------------------------------------------------------------------------
    # COACH NOTES AUDIT HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_submit_coach_note(self, websocket, data: Dict, profile: Dict):
        """Submit a coach note for review"""
        if profile.get('role') not in ['COACH', 'ADMIN']:
            await self._send_error(websocket, "Coach access required")
            return
        
        note = self.director.submit_coach_note(
            coach_id=profile.get('hardware_id'),
            coach_name=profile.get('name', 'Unknown Coach'),
            client_id=data.get('client_id', ''),
            client_name=data.get('client_name', 'Unknown Client'),
            content=data.get('content', ''),
            session_id=data.get('session_id')
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_note_submitted",
            "note": note.to_dict()
        }))
    
    async def handle_get_pending_notes(self, websocket, data: Dict, profile: Dict):
        """Get pending notes (admin only)"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        notes = self.director.get_pending_notes()
        
        await websocket.send(json.dumps({
            "type": "night_school_pending_notes",
            "count": len(notes),
            "data": [n.to_dict() for n in notes]
        }))
    
    async def handle_approve_note(self, websocket, data: Dict, profile: Dict):
        """Approve a coach note"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        note_id = data.get('note_id')
        use_redacted = data.get('use_redacted', True)
        category = WisdomCategory(data.get('category', 'general'))
        
        success, entry = self.director.approve_note(
            note_id=note_id,
            approved_by=profile.get('username', 'admin'),
            use_redacted=use_redacted,
            category=category
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_note_approved",
            "note_id": note_id,
            "success": success,
            "wisdom_entry": entry.to_dict() if entry else None
        }))
    
    async def handle_reject_note(self, websocket, data: Dict, profile: Dict):
        """Reject a coach note"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        note_id = data.get('note_id')
        reason = data.get('reason', 'No reason provided')
        
        success = self.director.reject_note(
            note_id=note_id,
            rejected_by=profile.get('username', 'admin'),
            reason=reason
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_note_rejected",
            "note_id": note_id,
            "success": success
        }))
    
    # -------------------------------------------------------------------------
    # DOJO HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_start_dojo(self, websocket, data: Dict, profile: Dict):
        """Start a Dojo adversarial testing session"""
        # Allow both ADMIN and COACH roles to use Dojo
        if profile.get('role') not in ['ADMIN', 'COACH']:
            await self._send_error(websocket, "Admin or Coach access required")
            return
        
        persona_str = data.get('persona', 'HOSTILE')
        mode_str = data.get('mode', 'THERAPIST')
        try:
            persona = DojoPersona(persona_str)
        except:
            persona = DojoPersona.HOSTILE
        
        session = self.director.start_dojo_session(persona)
        self.active_dojo_sessions[id(websocket)] = session
        
        # Get adversarial prompt for testing
        adversarial_prompt = self.director.get_dojo_system_prompt(persona)
        
        # Send both old and new message type names for compatibility
        await websocket.send(json.dumps({
            "type": "dojo_started",  # Flutter app expects this
            "session_id": session.id,
            "persona": persona.value,
            "mode": mode_str
        }))
        
        # Send the adversarial prompt as a separate message
        await websocket.send(json.dumps({
            "type": "dojo_prompt",
            "prompt": adversarial_prompt
        }))
    
    async def handle_dojo_message(self, websocket, data: Dict, profile: Dict):
        """Process a Dojo test message and analyze the response"""
        session = self.active_dojo_sessions.get(id(websocket))
        if not session:
            await self._send_error(websocket, "No active Dojo session")
            return
        
        user_message = data.get('user_message', '')
        nate_response = data.get('nate_response', '')
        
        analysis = self.director.analyze_dojo_response(
            session=session,
            nate_response=nate_response,
            user_message=user_message
        )
        
        await websocket.send(json.dumps({
            "type": "dojo_analysis",
            "session_id": session.id,
            "message_count": len(session.messages),
            "analysis": analysis
        }))
    
    async def handle_end_dojo(self, websocket, data: Dict, profile: Dict):
        """End a Dojo session and get final analysis"""
        session = self.active_dojo_sessions.get(id(websocket))
        if not session:
            await self._send_error(websocket, "No active Dojo session")
            return
        
        final_analysis = self.director.end_dojo_session(session)
        del self.active_dojo_sessions[id(websocket)]
        
        await websocket.send(json.dumps({
            "type": "dojo_ended",  # Flutter app expects this
            "session_id": session.id,
            "passed": session.passed,
            "analysis": final_analysis
        }))
    
    # -------------------------------------------------------------------------
    # CURRICULUM HANDLERS
    # -------------------------------------------------------------------------
    
    async def handle_ingest_curriculum(self, websocket, data: Dict, profile: Dict):
        """Ingest a curriculum file"""
        if profile.get('role') != 'ADMIN':
            await self._send_error(websocket, "Admin access required")
            return
        
        file_path = Path(data.get('file_path', ''))
        category = WisdomCategory(data.get('category', 'general'))
        
        if not file_path.exists():
            await self._send_error(websocket, f"File not found: {file_path}")
            return
        
        entries = await self.director.ingest_curriculum_file(
            file_path=file_path,
            category=category,
            ingested_by=profile.get('username', 'admin')
        )
        
        await websocket.send(json.dumps({
            "type": "night_school_curriculum_ingested",
            "file": file_path.name,
            "entries_created": len(entries),
            "entries": [e.to_dict() for e in entries[:10]]  # First 10 only
        }))
    
    # -------------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------------
    
    async def _send_error(self, websocket, message: str):
        """Send error message"""
        try:
            await websocket.send(json.dumps({
                "type": "night_school_error",
                "message": message
            }))
        except:
            pass
    
    def cleanup_connection(self, websocket):
        """Clean up when websocket disconnects"""
        ws_id = id(websocket)
        if ws_id in self.active_dojo_sessions:
            session = self.active_dojo_sessions[ws_id]
            self.director.end_dojo_session(session)
            del self.active_dojo_sessions[ws_id]


# =============================================================================
# INTEGRATION INSTRUCTIONS
# =============================================================================
"""
Add to bridge_server_hybrid.py:

1. Import:
   from night_school_handlers import NightSchoolHandler

2. Initialize after VAULT_ROOT:
   night_school_handler = NightSchoolHandler(VAULT_ROOT)

3. Add message handlers in the main loop:

   # Wisdom Management
   elif msg_type == "night_school_get_wisdom":
       await night_school_handler.handle_get_wisdom(websocket, data, current_profile)
   elif msg_type == "night_school_add_wisdom":
       await night_school_handler.handle_add_wisdom(websocket, data, current_profile)
   elif msg_type == "night_school_approve_wisdom":
       await night_school_handler.handle_approve_wisdom(websocket, data, current_profile)
   elif msg_type == "night_school_delete_wisdom":
       await night_school_handler.handle_delete_wisdom(websocket, data, current_profile)
   
   # Version Control
   elif msg_type == "night_school_get_versions":
       await night_school_handler.handle_get_versions(websocket, data, current_profile)
   elif msg_type == "night_school_create_snapshot":
       await night_school_handler.handle_create_snapshot(websocket, data, current_profile)
   elif msg_type == "night_school_revert_version":
       await night_school_handler.handle_revert_version(websocket, data, current_profile)
   elif msg_type == "night_school_compare_versions":
       await night_school_handler.handle_compare_versions(websocket, data, current_profile)
   
   # Coach Notes Audit
   elif msg_type == "submit_session_note":  # Existing handler - redirect
       await night_school_handler.handle_submit_coach_note(websocket, data, current_profile)
   elif msg_type == "night_school_get_pending_notes":
       await night_school_handler.handle_get_pending_notes(websocket, data, current_profile)
   elif msg_type == "night_school_approve_note":
       await night_school_handler.handle_approve_note(websocket, data, current_profile)
   elif msg_type == "night_school_reject_note":
       await night_school_handler.handle_reject_note(websocket, data, current_profile)
   
   # Dojo
   elif msg_type == "dojo_start":
       await night_school_handler.handle_start_dojo(websocket, data, current_profile)
   elif msg_type == "dojo_test_message":
       await night_school_handler.handle_dojo_message(websocket, data, current_profile)
   elif msg_type == "dojo_end":
       await night_school_handler.handle_end_dojo(websocket, data, current_profile)
   
   # Curriculum
   elif msg_type == "night_school_ingest_curriculum":
       await night_school_handler.handle_ingest_curriculum(websocket, data, current_profile)

4. Add cleanup on disconnect:
   finally:
       night_school_handler.cleanup_connection(websocket)

5. Update AI system prompt to include wisdom:
   In AzureLobe.process_interaction(), replace:
       wisdom = self.school.load_wisdom()
   With:
       wisdom = night_school_handler.director.get_wisdom_for_prompt()
"""
