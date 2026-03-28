"""
Session Memory Store - Unified memory management for Little Nate

This module provides a centralized interface for all session memory operations:
- Storing session data (transcripts, analysis, biometrics, observations)
- Retrieving memories for DOJO training context
- Providing client context for Little Nate responses
- Managing memory lifecycle and cleanup

The store integrates with:
- Night School Director (wisdom and learning)
- Classroom Analyzer (session analysis)
- Live Session handlers (observations and biometrics)
- Nevedal Engine (biometric processing)
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("session_memory_store")


def _r2_upload(key: str, content: bytes, content_type: str = "application/octet-stream"):
    """Fire-and-forget R2 upload for redundancy. Local disk is the hot path."""
    try:
        from app.services.blob_storage import upload_bytes
        kind, loc = upload_bytes(rel_path=key, content=content, content_type=content_type)
        logger.debug("[MemoryStore] R2 backup: %s → %s", key, kind)
    except Exception as e:
        logger.debug("[MemoryStore] R2 backup skipped for %s: %s", key, e)


def _r2_download(key: str) -> Optional[bytes]:
    """Try downloading from R2 when local file is missing."""
    try:
        from app.services.blob_storage import download_bytes
        return download_bytes(location=key, storage_kind="r2")
    except Exception:
        return None


class SessionMemoryStore:
    """
    Unified memory store for all session-related data.
    
    Provides:
    - Session storage (transcripts, analysis, observations, biometrics)
    - Memory retrieval for DOJO and Classroom
    - Client context for Little Nate responses
    - Memory search and filtering
    """
    
    def __init__(self, storage_root: Path):
        """
        Initialize the session memory store.
        
        Args:
            storage_root: Root directory for memory storage
        """
        self.storage_root = storage_root
        self.memories_dir = storage_root / "session_memories"
        self.memories_dir.mkdir(parents=True, exist_ok=True)
        
        self.clients_dir = self.memories_dir / "clients"
        self.clients_dir.mkdir(parents=True, exist_ok=True)
        
        self.index_path = self.memories_dir / "index.json"
        
        # Initialize or load index
        self._index = self._load_index()
    
    def _load_index(self) -> Dict:
        """Load or initialize the memory index."""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"Load memory index: {e}")
                pass
        
        return {
            "memories": [],
            "by_coach": {},
            "by_client": {},
            "by_family": {},
            "last_updated": datetime.now().isoformat()
        }
    
    def _save_index(self):
        """Save the memory index."""
        self._index["last_updated"] = datetime.now().isoformat()
        with open(self.index_path, 'w') as f:
            json.dump(self._index, f, indent=2)
    
    def store_session(
        self,
        session_id: str,
        coach_id: str,
        client_id: str,
        transcript: Optional[str] = None,
        analysis: Optional[Dict] = None,
        observations: Optional[List[Dict]] = None,
        biometrics: Optional[List[Dict]] = None,
        video_insights: Optional[Dict] = None,
        live_session_data: Optional[Dict] = None,
        family_id: Optional[str] = None
    ) -> Dict:
        """
        Store complete session data to memory.
        
        Args:
            session_id: Unique session identifier
            coach_id: Coach's identifier
            client_id: Client's identifier
            transcript: VTT transcript text
            analysis: ClassroomAnalyzer results
            observations: Live session observations
            biometrics: Nevedal biometric readings
            video_insights: Visual analysis results
            live_session_data: Raw live session data
            family_id: Optional family group ID
            
        Returns:
            Dict with memory_id and storage info
        """
        # Create session directory
        session_dir = self.memories_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        memory_id = f"MEM_{session_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Build summary from analysis
        summary = ""
        techniques = []
        key_moments = []
        growth_areas = []
        duration_minutes = 0
        
        if analysis:
            ai_analysis = analysis.get("ai_analysis", {})
            if isinstance(ai_analysis, dict):
                summary = ai_analysis.get("overall_summary", "")
                techniques = [s.get("technique", "") for s in ai_analysis.get("strengths", [])[:5]]
                key_moments = [m.get("description", "") for m in ai_analysis.get("key_moments", [])[:3]]
                growth_areas = [g.get("area", "") for g in ai_analysis.get("growth_areas", [])[:3]]
            
            metrics = analysis.get("metrics", {})
            duration_minutes = metrics.get("total_duration_minutes", 0)
        
        # Build memory record
        memory_record = {
            "memory_id": memory_id,
            "session_id": session_id,
            "coach_id": coach_id,
            "client_id": client_id,
            "family_id": family_id or "",
            "created_at": datetime.now().isoformat(),
            
            # Summary for quick access
            "summary": summary,
            "techniques_used": techniques,
            "key_moments": key_moments,
            "growth_areas": growth_areas,
            "duration_minutes": duration_minutes,
            
            # Data flags
            "has_transcript": bool(transcript),
            "has_analysis": bool(analysis),
            "has_observations": bool(observations),
            "has_biometrics": bool(biometrics),
            "has_video_insights": bool(video_insights),
            "has_live_session": bool(live_session_data),
            
            # Counts
            "observation_count": len(observations) if observations else 0,
            "biometric_count": len(biometrics) if biometrics else 0,
        }
        
        # Save memory index (local + R2)
        index_bytes = json.dumps(memory_record, indent=2).encode()
        with open(session_dir / "memory_index.json", 'w') as f:
            f.write(index_bytes.decode())
        _r2_upload(f"session_memories/{session_id}/memory_index.json", index_bytes, "application/json")

        # Save individual components (local + R2 for redundancy)
        if transcript:
            with open(session_dir / "transcript.vtt", 'w') as f:
                f.write(transcript)
            _r2_upload(f"session_memories/{session_id}/transcript.vtt", transcript.encode(), "text/vtt")

        if analysis:
            analysis_bytes = json.dumps(analysis, indent=2, default=str).encode()
            with open(session_dir / "analysis.json", 'w') as f:
                f.write(analysis_bytes.decode())
            _r2_upload(f"session_memories/{session_id}/analysis.json", analysis_bytes, "application/json")

        if observations:
            obs_bytes = json.dumps(observations, indent=2, default=str).encode()
            with open(session_dir / "observations.json", 'w') as f:
                f.write(obs_bytes.decode())
            _r2_upload(f"session_memories/{session_id}/observations.json", obs_bytes, "application/json")

        if biometrics:
            bio_bytes = json.dumps(biometrics, indent=2, default=str).encode()
            with open(session_dir / "biometrics.json", 'w') as f:
                f.write(bio_bytes.decode())
            _r2_upload(f"session_memories/{session_id}/biometrics.json", bio_bytes, "application/json")

        if video_insights:
            vi_bytes = json.dumps(video_insights, indent=2, default=str).encode()
            with open(session_dir / "video_insights.json", 'w') as f:
                f.write(vi_bytes.decode())
            _r2_upload(f"session_memories/{session_id}/video_insights.json", vi_bytes, "application/json")

        if live_session_data:
            ls_bytes = json.dumps(live_session_data, indent=2, default=str).encode()
            with open(session_dir / "live_session.json", 'w') as f:
                f.write(ls_bytes.decode())
            _r2_upload(f"session_memories/{session_id}/live_session.json", ls_bytes, "application/json")
        
        # Update indexes
        self._update_index(memory_id, session_id, coach_id, client_id, family_id)
        self._update_client_references(client_id, memory_id, session_id, memory_record)

        try:
            from app.services.vectorize_service import index_session, is_vectorize_configured
            if is_vectorize_configured():
                import asyncio as _aio
                _aio.create_task(index_session(
                    session_id=session_id, coach_id=coach_id, client_id=client_id,
                    transcript=transcript or "", analysis_summary=summary,
                    family_id=family_id or "",
                    timestamp=datetime.now().isoformat(),
                ))
        except Exception:
            pass
        
        print(f"[MemoryStore] Stored session {session_id} as {memory_id}")
        
        return {
            "memory_id": memory_id,
            "session_id": session_id,
            "storage_path": str(session_dir),
            "summary": summary[:200] if summary else "No summary",
        }
    
    def _update_index(
        self,
        memory_id: str,
        session_id: str,
        coach_id: str,
        client_id: str,
        family_id: Optional[str]
    ):
        """Update the global memory index."""
        # Add to main list
        self._index["memories"].append({
            "memory_id": memory_id,
            "session_id": session_id,
            "coach_id": coach_id,
            "client_id": client_id,
            "family_id": family_id or "",
            "created_at": datetime.now().isoformat(),
        })
        
        # Keep last 1000
        self._index["memories"] = self._index["memories"][-1000:]
        
        # Update by-coach index
        if coach_id:
            if coach_id not in self._index["by_coach"]:
                self._index["by_coach"][coach_id] = []
            self._index["by_coach"][coach_id].append(session_id)
            self._index["by_coach"][coach_id] = self._index["by_coach"][coach_id][-100:]
        
        # Update by-client index
        if client_id:
            if client_id not in self._index["by_client"]:
                self._index["by_client"][client_id] = []
            self._index["by_client"][client_id].append(session_id)
            self._index["by_client"][client_id] = self._index["by_client"][client_id][-100:]
        
        # Update by-family index
        if family_id:
            if family_id not in self._index["by_family"]:
                self._index["by_family"][family_id] = []
            self._index["by_family"][family_id].append(session_id)
            self._index["by_family"][family_id] = self._index["by_family"][family_id][-100:]
        
        self._save_index()
    
    def _update_client_references(
        self,
        client_id: str,
        memory_id: str,
        session_id: str,
        memory_record: Dict
    ):
        """Update client-specific memory references."""
        if not client_id:
            return
        
        client_dir = self.clients_dir / client_id
        client_dir.mkdir(parents=True, exist_ok=True)
        
        refs_path = client_dir / "memory_references.json"
        
        refs = []
        if refs_path.exists():
            try:
                with open(refs_path, 'r') as f:
                    refs = json.load(f)
            except Exception as e:
                logger.debug(f"Load memory references: {e}")
                refs = []
        
        refs.append({
            "memory_id": memory_id,
            "session_id": session_id,
            "created_at": memory_record.get("created_at"),
            "summary": memory_record.get("summary", "")[:100],
            "techniques": memory_record.get("techniques_used", []),
            "growth_areas": memory_record.get("growth_areas", []),
        })
        
        # Keep last 100
        refs = refs[-100:]
        
        with open(refs_path, 'w') as f:
            json.dump(refs, f, indent=2)
    
    def _read_local_or_r2(self, local_path: Path, r2_key: str) -> Optional[bytes]:
        """Read from local disk first, then R2 fallback."""
        if local_path.exists():
            try:
                return local_path.read_bytes()
            except Exception as e:
                logger.debug("Local read failed for %s: %s", local_path, e)

        data = _r2_download(r2_key)
        if data is not None:
            try:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(data)
            except Exception:
                pass
        return data

    def get_session(self, session_id: str) -> Optional[Dict]:
        """
        Retrieve a session's memory record.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Memory record dict or None if not found
        """
        local_path = self.memories_dir / session_id / "memory_index.json"
        r2_key = f"session_memories/{session_id}/memory_index.json"
        data = self._read_local_or_r2(local_path, r2_key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except Exception as e:
            logger.debug("Parse session memory record: %s", e)
            return None

    def get_session_transcript(self, session_id: str) -> Optional[str]:
        """Get transcript for a session."""
        local_path = self.memories_dir / session_id / "transcript.vtt"
        r2_key = f"session_memories/{session_id}/transcript.vtt"
        data = self._read_local_or_r2(local_path, r2_key)
        if data is None:
            return None
        try:
            return data.decode()
        except Exception as e:
            logger.debug("Decode session transcript: %s", e)
            return None

    def get_session_analysis(self, session_id: str) -> Optional[Dict]:
        """Get analysis for a session."""
        local_path = self.memories_dir / session_id / "analysis.json"
        r2_key = f"session_memories/{session_id}/analysis.json"
        data = self._read_local_or_r2(local_path, r2_key)
        if data is None:
            return None
        try:
            return json.loads(data)
        except Exception as e:
            logger.debug("Parse session analysis: %s", e)
            return None

    def get_for_dojo(
        self,
        coach_id: str,
        persona: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get relevant memories for DOJO training context.
        
        Args:
            coach_id: Coach's identifier
            persona: Optional DOJO persona to filter for
            limit: Maximum memories to return
            
        Returns:
            List of memory summaries relevant to DOJO training
        """
        # Get coach's sessions
        session_ids = self._index.get("by_coach", {}).get(coach_id, [])
        
        memories = []
        for sid in reversed(session_ids[-limit:]):
            memory = self.get_session(sid)
            if memory:
                memories.append({
                    "session_id": sid,
                    "summary": memory.get("summary", ""),
                    "techniques": memory.get("techniques_used", []),
                    "growth_areas": memory.get("growth_areas", []),
                    "duration_minutes": memory.get("duration_minutes", 0),
                    "has_observations": memory.get("has_observations", False),
                })
        
        return memories
    
    def get_for_classroom(self, session_id: str) -> Dict:
        """
        Get all data for Classroom display.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Complete session data for Classroom tab
        """
        result = {
            "session_id": session_id,
            "memory": self.get_session(session_id),
            "analysis": self.get_session_analysis(session_id),
            "transcript": None,  # Don't load full transcript by default
            "observations": [],
            "biometrics_summary": None,
        }
        
        obs_data = self._read_local_or_r2(
            self.memories_dir / session_id / "observations.json",
            f"session_memories/{session_id}/observations.json",
        )
        if obs_data:
            try:
                result["observations"] = json.loads(obs_data)
            except Exception as e:
                logger.debug("Load observations for classroom: %s", e)

        bio_data = self._read_local_or_r2(
            self.memories_dir / session_id / "biometrics.json",
            f"session_memories/{session_id}/biometrics.json",
        )
        if bio_data:
            try:
                biometrics = json.loads(bio_data)
                if biometrics:
                    c_emo_values = [b.get("c_emo", 0.5) for b in biometrics if "c_emo" in b]
                    result["biometrics_summary"] = {
                        "count": len(biometrics),
                        "avg_c_emo": sum(c_emo_values) / len(c_emo_values) if c_emo_values else 0.5,
                        "max_c_emo": max(c_emo_values) if c_emo_values else 0.5,
                        "min_c_emo": min(c_emo_values) if c_emo_values else 0.5,
                    }
            except Exception as e:
                logger.debug("Load biometrics for classroom: %s", e)

        return result

    def get_for_client_context(
        self,
        client_id: str,
        limit: int = 10
    ) -> List[Dict]:
        """
        Get session memories for building client context in Little Nate responses.
        
        Args:
            client_id: Client's identifier
            limit: Maximum memories to return
            
        Returns:
            List of memory references for client context
        """
        refs_path = self.clients_dir / client_id / "memory_references.json"
        
        if not refs_path.exists():
            return []
        
        try:
            with open(refs_path, 'r') as f:
                refs = json.load(f)
            return refs[-limit:]
        except Exception as e:
            logger.debug(f"Get client context memory refs: {e}")
            return []

    def get_for_family_context(
        self,
        family_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        Get session memories for a family group.
        
        Args:
            family_id: Family group identifier
            limit: Maximum memories to return
            
        Returns:
            List of memory summaries for the family
        """
        session_ids = self._index.get("by_family", {}).get(family_id, [])
        
        memories = []
        for sid in reversed(session_ids[-limit:]):
            memory = self.get_session(sid)
            if memory:
                memories.append({
                    "session_id": sid,
                    "client_id": memory.get("client_id", ""),
                    "summary": memory.get("summary", ""),
                    "created_at": memory.get("created_at"),
                })
        
        return memories
    
    def search_memories(
        self,
        query: str,
        coach_id: Optional[str] = None,
        client_id: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """
        Search memories by content.
        
        Args:
            query: Search query
            coach_id: Optional filter by coach
            client_id: Optional filter by client
            limit: Maximum results
            
        Returns:
            List of matching memory summaries
        """
        query_lower = query.lower()
        results = []
        
        # SECURITY: Require at least one of coach_id or client_id to prevent
        # cross-user data exposure. Global searches are no longer permitted.
        if not client_id and not coach_id:
            return []
        
        # Get candidate sessions scoped to the specified user
        if client_id:
            session_ids = self._index.get("by_client", {}).get(client_id, [])
        else:
            session_ids = self._index.get("by_coach", {}).get(coach_id, [])
        
        for sid in reversed(session_ids):
            memory = self.get_session(sid)
            if not memory:
                continue
            
            # Search in summary, techniques, and growth areas
            searchable = " ".join([
                memory.get("summary", ""),
                " ".join(memory.get("techniques_used", [])),
                " ".join(memory.get("growth_areas", [])),
            ]).lower()
            
            if query_lower in searchable:
                results.append({
                    "session_id": sid,
                    "memory_id": memory.get("memory_id"),
                    "summary": memory.get("summary", "")[:200],
                    "match_context": "summary/techniques/growth_areas",
                })
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_stats(self) -> Dict:
        """Get memory store statistics."""
        return {
            "total_memories": len(self._index.get("memories", [])),
            "total_coaches": len(self._index.get("by_coach", {})),
            "total_clients": len(self._index.get("by_client", {})),
            "total_families": len(self._index.get("by_family", {})),
            "last_updated": self._index.get("last_updated"),
        }


def create_session_memory_store(storage_root: Path) -> SessionMemoryStore:
    """Factory function to create a SessionMemoryStore instance."""
    return SessionMemoryStore(storage_root)
