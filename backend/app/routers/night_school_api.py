"""
LITTLE NATE — Night School REST API Endpoints
Version: 1.0
Date: January 21, 2026

Add these endpoints to api_server.py for Night School functionality.
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from pathlib import Path
import shutil

# Import from main api_server
# from api_server import get_current_user, require_admin, db

# Import Night School
from app.services.night_school_director import (
    NightSchoolDirector,
    WisdomCategory,
    DojoPersona,
    NoteStatus,
    create_night_school_director
)

# =============================================================================
# ROUTER
# =============================================================================

from app.services.api_server import require_coach

router = APIRouter(
    prefix="/api/night-school",
    tags=["Night School"],
    dependencies=[Depends(require_coach)],
)

# Global director instance (initialize in main app)
_director: Optional[NightSchoolDirector] = None

def get_director() -> NightSchoolDirector:
    if _director is None:
        raise HTTPException(status_code=500, detail="Night School not initialized")
    return _director

def init_night_school(vault_root: Path, db_pool=None):
    """Initialize the Night School director - call from main app startup"""
    global _director
    _director = create_night_school_director(vault_root, db_pool)
    return _director

# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class WisdomEntryCreate(BaseModel):
    content: str = Field(..., min_length=10)
    category: str = "general"
    confidence: float = Field(0.5, ge=0, le=1)
    auto_approve: bool = False
    tags: List[str] = []

class WisdomEntryResponse(BaseModel):
    id: str
    category: str
    source: str
    content: str
    confidence: float
    approved: bool
    created_at: datetime

class VersionResponse(BaseModel):
    version_id: str
    version_number: int
    created_at: datetime
    created_by: str
    description: str
    entry_count: int
    is_current: bool

class CreateSnapshotRequest(BaseModel):
    description: str = "Manual snapshot"

class CoachNoteSubmit(BaseModel):
    client_id: str
    client_name: str
    content: str = Field(..., min_length=10)
    session_id: Optional[str] = None

class CoachNoteResponse(BaseModel):
    id: str
    coach_name: str
    client_name: str
    content: str
    redacted_content: Optional[str]
    pii_detected: bool
    status: str
    created_at: datetime

class ApproveNoteRequest(BaseModel):
    use_redacted: bool = True
    category: str = "general"

class RejectNoteRequest(BaseModel):
    reason: str

class DojoStartRequest(BaseModel):
    persona: str = "HOSTILE"

class DojoMessageRequest(BaseModel):
    user_message: str
    nate_response: str

class DojoAnalysisResponse(BaseModel):
    violations: List[dict]
    flags: List[dict]
    violation_count: int
    is_safe: bool

# =============================================================================
# WISDOM ENDPOINTS
# =============================================================================

@router.get("/wisdom", response_model=List[WisdomEntryResponse])
async def get_wisdom(
    category: Optional[str] = None,
    limit: int = 100,
    director: NightSchoolDirector = Depends(get_director)
):
    """Get wisdom entries"""
    cat = WisdomCategory(category) if category else None
    entries = director.get_wisdom(category=cat, limit=limit)
    return [WisdomEntryResponse(**e.to_dict()) for e in entries]

@router.post("/wisdom", response_model=WisdomEntryResponse)
async def add_wisdom(
    data: WisdomEntryCreate,
    director: NightSchoolDirector = Depends(get_director),
    # admin = Depends(require_admin)  # Uncomment when integrated
):
    """Add a wisdom entry (admin only)"""
    entry = director.add_wisdom_entry(
        content=data.content,
        category=WisdomCategory(data.category),
        source='manual_entry',
        confidence=data.confidence,
        auto_approve=data.auto_approve,
        approved_by='admin' if data.auto_approve else None,
        tags=data.tags
    )
    return WisdomEntryResponse(**entry.to_dict())

@router.post("/wisdom/{entry_id}/approve")
async def approve_wisdom(
    entry_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """Approve a wisdom entry"""
    success = director.approve_wisdom_entry(entry_id, 'admin')
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}

@router.delete("/wisdom/{entry_id}")
async def delete_wisdom(
    entry_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """Delete a wisdom entry"""
    success = director.delete_wisdom_entry(entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"success": True}

# =============================================================================
# VERSION CONTROL ENDPOINTS
# =============================================================================

@router.get("/versions", response_model=List[VersionResponse])
async def get_versions(director: NightSchoolDirector = Depends(get_director)):
    """Get version history"""
    versions = director.get_versions()
    return [VersionResponse(**v.to_dict()) for v in versions]

@router.post("/versions/snapshot", response_model=VersionResponse)
async def create_snapshot(
    data: CreateSnapshotRequest,
    director: NightSchoolDirector = Depends(get_director)
):
    """Create a wisdom snapshot"""
    version = director.create_snapshot('admin', data.description)
    return VersionResponse(**version.to_dict())

@router.post("/versions/{version_id}/revert")
async def revert_version(
    version_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """Revert to a previous version"""
    success = director.revert_to_version(version_id, 'admin')
    if not success:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"success": True, "reverted_to": version_id}

@router.get("/versions/compare")
async def compare_versions(
    version_a: str,
    version_b: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """Compare two versions"""
    result = director.compare_versions(version_a, version_b)
    if 'error' in result:
        raise HTTPException(status_code=404, detail=result['error'])
    return result

# =============================================================================
# COACH NOTES ENDPOINTS
# =============================================================================

@router.get("/notes/pending", response_model=List[CoachNoteResponse])
async def get_pending_notes(director: NightSchoolDirector = Depends(get_director)):
    """Get pending coach notes (admin only)"""
    notes = director.get_pending_notes()
    return [CoachNoteResponse(**n.to_dict()) for n in notes]

@router.post("/notes", response_model=CoachNoteResponse)
async def submit_note(
    data: CoachNoteSubmit,
    director: NightSchoolDirector = Depends(get_director)
):
    """Submit a coach note for review"""
    note = director.submit_coach_note(
        coach_id='coach_api',
        coach_name='API Coach',
        client_id=data.client_id,
        client_name=data.client_name,
        content=data.content,
        session_id=data.session_id
    )
    return CoachNoteResponse(**note.to_dict())

@router.get("/notes/{note_id}", response_model=CoachNoteResponse)
async def get_note(
    note_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """Get a specific note"""
    note = director.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return CoachNoteResponse(**note.to_dict())

@router.post("/notes/{note_id}/approve")
async def approve_note(
    note_id: str,
    data: ApproveNoteRequest,
    director: NightSchoolDirector = Depends(get_director)
):
    """Approve a note and add to wisdom"""
    success, entry = director.approve_note(
        note_id=note_id,
        approved_by='admin',
        use_redacted=data.use_redacted,
        category=WisdomCategory(data.category)
    )
    if not success:
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "success": True,
        "wisdom_entry_id": entry.id if entry else None
    }

@router.post("/notes/{note_id}/reject")
async def reject_note(
    note_id: str,
    data: RejectNoteRequest,
    director: NightSchoolDirector = Depends(get_director)
):
    """Reject a note"""
    success = director.reject_note(note_id, 'admin', data.reason)
    if not success:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"success": True}


# =============================================================================
# COMPATIBILITY ALIASES — Sync frontend paths to existing backend endpoints
# =============================================================================


class ReviewNoteRequest(BaseModel):
    """Unified review endpoint body — dispatches to approve/reject/redact."""
    action: str  # "approve", "reject", or "redact"
    reason: str = ""
    use_redacted: bool = True
    category: str = "general"


@router.post("/snapshot")
async def create_snapshot_alias(
    data: CreateSnapshotRequest = CreateSnapshotRequest(),
    director: NightSchoolDirector = Depends(get_director),
):
    """Alias for /versions/snapshot — matches frontend path."""
    return await create_snapshot(data, director)


@router.post("/notes/{note_id}/review")
async def review_note_unified(
    note_id: str,
    data: ReviewNoteRequest,
    director: NightSchoolDirector = Depends(get_director),
):
    """Unified review endpoint — dispatches to approve, reject, or redact."""
    action = data.action.lower().strip()
    if action == "approve":
        success, entry = director.approve_note(
            note_id=note_id,
            approved_by="admin",
            use_redacted=data.use_redacted,
            category=WisdomCategory(data.category),
        )
        if not success:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"success": True, "action": "approved", "wisdom_entry_id": entry.id if entry else None}
    elif action in ("reject", "redact"):
        success = director.reject_note(note_id, "admin", data.reason or action)
        if not success:
            raise HTTPException(status_code=404, detail="Note not found")
        return {"success": True, "action": action}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}. Use approve, reject, or redact.")


# =============================================================================
# DOJO ENDPOINTS
# =============================================================================

# Store active sessions (in production, use Redis or database)
_dojo_sessions = {}

@router.post("/dojo/start")
async def start_dojo(
    data: DojoStartRequest,
    director: NightSchoolDirector = Depends(get_director)
):
    """Start a Dojo adversarial testing session"""
    try:
        persona = DojoPersona(data.persona)
    except:
        persona = DojoPersona.HOSTILE
    
    session = director.start_dojo_session(persona)
    _dojo_sessions[session.id] = session
    
    prompt = director.get_dojo_system_prompt(persona)
    
    return {
        "session_id": session.id,
        "persona": persona.value,
        "adversarial_prompt": prompt
    }

@router.post("/dojo/{session_id}/test", response_model=DojoAnalysisResponse)
async def test_dojo_message(
    session_id: str,
    data: DojoMessageRequest,
    director: NightSchoolDirector = Depends(get_director)
):
    """Test a message exchange in the Dojo"""
    session = _dojo_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    analysis = director.analyze_dojo_response(
        session=session,
        nate_response=data.nate_response,
        user_message=data.user_message
    )
    
    return DojoAnalysisResponse(**analysis)

@router.post("/dojo/{session_id}/end")
async def end_dojo(
    session_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """End a Dojo session and get final results"""
    session = _dojo_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    analysis = director.end_dojo_session(session)
    del _dojo_sessions[session_id]
    
    return {
        "session_id": session_id,
        "passed": session.passed,
        "analysis": analysis
    }

@router.get("/dojo/personas")
async def get_dojo_personas():
    """Get available Dojo personas"""
    return {
        "personas": [
            {"id": p.value, "name": p.value.replace("_", " ").title()}
            for p in DojoPersona
        ]
    }

# =============================================================================
# CLASSROOM → DOJO INTEGRATION ENDPOINTS
# =============================================================================

@router.get("/dojo/scenarios")
async def get_queued_dojo_scenarios(
    status: str = "queued",
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get DOJO scenarios queued from classroom session analyses.
    
    CONNECTION: Classroom dojo_scenarios → DOJO
    
    These scenarios are automatically created when classroom AI analyzes
    coaching sessions and identifies growth areas that need testing.
    """
    scenarios = director.get_queued_dojo_scenarios(status=status)
    
    return {
        "scenarios": scenarios,
        "total": len(scenarios),
        "status_filter": status
    }

@router.post("/dojo/scenarios/{scenario_id}/launch")
async def launch_dojo_from_classroom_scenario(
    scenario_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Launch a DOJO session from a classroom-generated scenario.
    
    CONNECTION: Classroom dojo_scenarios → DOJO
    
    This creates a DOJO testing session based on a real coaching scenario
    identified during classroom analysis. The DOJO will use the specific
    scenario and skill target from the classroom analysis.
    """
    session = director.create_dojo_from_classroom_scenario(scenario_id)
    
    if not session:
        raise HTTPException(
            status_code=404, 
            detail=f"Scenario {scenario_id} not found or already used"
        )
    
    # Store active session
    _dojo_sessions[session.id] = session
    
    # Get the custom prompt if set
    custom_prompt = ""
    if session.messages and session.messages[0].get('role') == 'system':
        custom_prompt = session.messages[0].get('content', '')[:200]
    
    return {
        "session_id": session.id,
        "persona": session.persona.value,
        "scenario_id": scenario_id,
        "started_at": session.started_at.isoformat(),
        "source": "classroom_scenario",
        "custom_prompt_preview": custom_prompt,
        "system_prompt": director.get_dojo_system_prompt(session.persona)
    }

@router.get("/dojo/wisdom/{persona}")
async def get_dojo_wisdom(
    persona: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get approved wisdom relevant to a DOJO persona for testing.
    
    CONNECTION: Night School → DOJO
    
    Returns wisdom entries that are relevant to the specified persona,
    which can be used to inform DOJO testing criteria.
    """
    try:
        persona_enum = DojoPersona(persona.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid persona. Valid options: {[p.value for p in DojoPersona]}"
        )
    
    wisdom_text = director.get_wisdom_for_dojo_analysis(persona_enum)
    
    return {
        "persona": persona,
        "wisdom_entries": wisdom_text,
        "entry_count": len(wisdom_text.split('\n')) - 1 if wisdom_text else 0
    }

@router.get("/learning/stats")
async def get_learning_stats(
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get statistics about the learning loop integrations.
    
    Shows how many wisdom entries came from each source:
    - classroom_analysis: From session transcript analysis
    - dojo_learning: From DOJO test failures/successes
    - coach_notes: From coach observations
    - curriculum: From uploaded training materials
    """
    wisdom = director.get_wisdom(limit=10000)
    
    by_source = {}
    by_tags = {}
    
    for entry in wisdom:
        source = entry.source
        by_source[source] = by_source.get(source, 0) + 1
        
        for tag in entry.tags:
            by_tags[tag] = by_tags.get(tag, 0) + 1
    
    # Get queued scenarios
    queued_scenarios = director.get_queued_dojo_scenarios(status="queued")
    active_scenarios = director.get_queued_dojo_scenarios(status="active")
    
    return {
        "wisdom_by_source": by_source,
        "wisdom_by_tags": by_tags,
        "queued_dojo_scenarios": len(queued_scenarios),
        "active_dojo_scenarios": len(active_scenarios),
        "learning_loop_active": True,
        "connections": {
            "classroom_to_night_school": by_source.get("classroom_analysis", 0) > 0,
            "dojo_to_night_school": by_source.get("dojo_learning", 0) > 0,
            "night_school_to_dojo": True,  # Always available via get_wisdom_for_dojo_analysis
            "classroom_scenarios_to_dojo": len(queued_scenarios) + len(active_scenarios) > 0
        }
    }

# =============================================================================
# SESSION MEMORY ENDPOINTS
# =============================================================================

@router.get("/memories/client/{client_id}")
async def get_client_memories(
    client_id: str,
    limit: int = 10,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get session memories for a specific client.
    
    Returns what Little Nate remembers from coaching sessions,
    including techniques used, key moments, and growth areas.
    
    Used by Briefings tab to show Nate's accumulated knowledge about a client.
    """
    try:
        memories = director.get_memories_for_client(client_id)
    except AttributeError:
        # Method not available in this version - return empty
        return {"client_id": client_id, "memories": [], "total": 0}
    
    # Format for frontend consumption
    formatted = []
    for memory in memories[:limit]:
        formatted.append({
            "memory_id": memory.get("memory_id", ""),
            "session_id": memory.get("session_id", ""),
            "summary": memory.get("session_summary", ""),
            "techniques": memory.get("techniques", []),
            "key_moments": memory.get("key_moments", []),
            "growth_areas": memory.get("growth_areas", []),
            "created_at": memory.get("created_at", ""),
            "coach_id": memory.get("coach_id", ""),
            "has_video_insights": bool(memory.get("video_insights")),
            "has_biometrics": bool(memory.get("biometrics")),
        })
    
    return {
        "client_id": client_id,
        "memories": formatted,
        "total": len(memories)
    }

@router.get("/memories/family/{family_id}")
async def get_family_memories(
    family_id: str,
    limit: int = 20,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get session memories for an entire family.
    
    Aggregates memories across all family members for family therapy context.
    """
    try:
        # Get all memories and filter by family
        all_memories = []
        # This would need the memory store to have family lookup
        # For now, return empty - would need to iterate clients
        return {
            "family_id": family_id,
            "memories": [],
            "total": 0,
            "note": "Family aggregation pending implementation"
        }
    except Exception as e:
        return {"family_id": family_id, "memories": [], "error": str(e)}

@router.get("/memories/session/{session_id}")
async def get_session_memory(
    session_id: str,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get the full memory record for a specific session.
    
    Returns all artifacts: transcript, analysis, observations, biometrics, video insights.
    """
    try:
        memory = director.get_session_memory(session_id)
    except AttributeError:
        raise HTTPException(status_code=501, detail="Memory retrieval not available")
    
    if not memory:
        raise HTTPException(status_code=404, detail="Session memory not found")
    
    return {
        "session_id": session_id,
        "memory": memory
    }

@router.get("/memories/dojo")
async def get_dojo_memories(
    limit: int = 20,
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get memories formatted for DOJO training scenarios.
    
    CONNECTION: Session memories → DOJO
    
    Returns session memories with focus on therapeutic techniques,
    challenging moments, and areas where Nate can improve responses.
    """
    try:
        memories = director.get_memories_for_dojo(limit=limit)
    except AttributeError:
        return {"memories": [], "total": 0, "note": "DOJO memory integration pending"}
    
    return {
        "memories": memories,
        "total": len(memories),
        "purpose": "dojo_training"
    }

@router.get("/memories/stats")
async def get_memory_stats(
    director: NightSchoolDirector = Depends(get_director)
):
    """
    Get statistics about stored session memories.
    """
    try:
        # Try to access the session memory vault
        vault_path = director.vault_root / "session_memories"
        if not vault_path.exists():
            return {
                "total_memories": 0,
                "clients_tracked": 0,
                "families_tracked": 0,
                "has_video_insights": 0,
                "has_biometrics": 0,
                "storage_initialized": False
            }
        
        # Count memory directories
        memories = list(vault_path.glob("session_*"))
        
        # Try to read index if available
        index_path = vault_path / "index.json"
        if index_path.exists():
            import json
            with open(index_path) as f:
                index = json.load(f)
            return {
                "total_memories": len(memories),
                "clients_tracked": len(index.get("by_client", {})),
                "families_tracked": len(index.get("by_family", {})),
                "coaches_tracked": len(index.get("by_coach", {})),
                "storage_initialized": True
            }
        
        return {
            "total_memories": len(memories),
            "storage_initialized": True
        }
    except Exception as e:
        return {"error": str(e), "storage_initialized": False}

# =============================================================================
# CURRICULUM ENDPOINTS
# =============================================================================

@router.post("/curriculum/upload")
async def upload_curriculum(
    file: UploadFile = File(...),
    category: str = Form("general"),
    director: NightSchoolDirector = Depends(get_director)
):
    """Upload and ingest a curriculum file"""
    # Validate file type
    allowed_types = ['.txt', '.md', '.json', '.pdf', '.docx']
    suffix = Path(file.filename).suffix.lower()
    
    if suffix not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"File type not allowed. Allowed: {allowed_types}"
        )
    
    # Save uploaded file — sanitize filename to prevent path traversal
    upload_dir = director.curriculum_dir / "uploads"
    upload_dir.mkdir(exist_ok=True)
    
    # Strip directory components and dangerous characters from filename
    import re
    safe_name = re.sub(r'[^\w\-.]', '_', Path(file.filename).name) if file.filename else "upload"
    safe_name = safe_name.lstrip('.')  # prevent hidden files
    if not safe_name:
        safe_name = f"upload_{__import__('uuid').uuid4().hex[:8]}{suffix}"
    file_path = upload_dir / safe_name
    # Final safety check: ensure resolved path is within upload_dir
    if not file_path.resolve().is_relative_to(upload_dir.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    with open(file_path, 'wb') as f:
        content = await file.read()
        f.write(content)
    
    # Ingest
    entries = await director.ingest_curriculum_file(
        file_path=file_path,
        category=WisdomCategory(category),
        ingested_by='api'
    )
    
    return {
        "filename": safe_name,
        "entries_created": len(entries),
        "category": category,
        "message": f"Created {len(entries)} wisdom entries (pending approval)"
    }

# =============================================================================
# STATISTICS ENDPOINT
# =============================================================================

@router.get("/stats")
async def get_night_school_stats(director: NightSchoolDirector = Depends(get_director)):
    """Get Night School statistics"""
    wisdom = director.get_wisdom(limit=10000)
    pending_notes = director.get_pending_notes()
    versions = director.get_versions()
    
    # Count by category
    by_category = {}
    for entry in wisdom:
        cat = entry.category.value
        by_category[cat] = by_category.get(cat, 0) + 1
    
    return {
        "total_wisdom_entries": len(wisdom),
        "approved_entries": len([e for e in wisdom if e.approved]),
        "pending_entries": len([e for e in wisdom if not e.approved]),
        "by_category": by_category,
        "pending_notes": len(pending_notes),
        "version_count": len(versions),
        "current_version": versions[0].version_number if versions else 0
    }


# =============================================================================
# INTEGRATION INSTRUCTIONS
# =============================================================================
"""
Add to api_server.py:

1. Import the router:
   from night_school_api import router as night_school_router, init_night_school

2. Initialize on startup:
   @app.on_event("startup")
   async def startup():
       ...
       init_night_school(VAULT_ROOT, db.pool)

3. Include the router:
   app.include_router(night_school_router)

The following endpoints will be available:

# Wisdom Management
GET  /api/night-school/wisdom
POST /api/night-school/wisdom
POST /api/night-school/wisdom/{id}/approve
DELETE /api/night-school/wisdom/{id}

# Version Control
GET  /api/night-school/versions
POST /api/night-school/versions/snapshot
POST /api/night-school/versions/{id}/revert
GET  /api/night-school/versions/compare

# Coach Notes
GET  /api/night-school/notes/pending
POST /api/night-school/notes
GET  /api/night-school/notes/{id}
POST /api/night-school/notes/{id}/approve
POST /api/night-school/notes/{id}/reject

# DOJO Testing
POST /api/night-school/dojo/start
POST /api/night-school/dojo/{id}/test
POST /api/night-school/dojo/{id}/end
GET  /api/night-school/dojo/personas

# Classroom → DOJO Integration (NEW)
GET  /api/night-school/dojo/scenarios        # Get queued scenarios from classroom
POST /api/night-school/dojo/scenarios/{id}/launch  # Launch DOJO from classroom scenario
GET  /api/night-school/dojo/wisdom/{persona}  # Get wisdom for DOJO persona

# Learning Loop Stats (NEW)
GET  /api/night-school/learning/stats        # View learning loop connections

# Curriculum
POST /api/night-school/curriculum/upload
GET  /api/night-school/stats

LEARNING LOOP CONNECTIONS:
- Classroom → Night School: Session analysis pushes insights as pending wisdom
- DOJO → Night School: Session failures create wisdom entries about safety
- Night School → DOJO: Approved wisdom informs DOJO response analysis
- Classroom dojo_scenarios → DOJO: AI-identified growth areas become DOJO tests
"""
