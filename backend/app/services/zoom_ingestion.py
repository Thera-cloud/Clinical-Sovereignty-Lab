"""
Zoom Transcript Ingestion Service (Patent 2, Section 16)

Downloads and parses Zoom meeting/phone transcripts, matches participants
to Sovereign Sanctuary clients, and feeds conversation turns through the
MetricsEngine pipeline to compute Crisis Perception, Shame, PMB, Legacy,
and Observer Protocol metrics from external coaching sessions.

Design:
- Stateless service: instantiate per-ingestion or reuse.
- VTT parsing handles Zoom's standard WebVTT format.
- Client matching uses email + name fuzzy lookup against user_registry.
- MetricsEngine is imported from bridge_server at runtime to avoid
  circular import issues.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("zoom_ingestion")

DATA_DIR = Path(os.getenv("DATA_DIR", "./data"))
REGISTRY_FILE = DATA_DIR / "user_registry.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
BACKEND_DATA_DIR = Path("/app/backend_data")
BACKEND_REGISTRY_FILE = BACKEND_DATA_DIR / "user_registry.json"


def _load_json(path: Path, default: Any = None):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


class ZoomIngestionService:
    """
    Ingests Zoom meeting/phone transcripts into the Nevedal metrics pipeline.
    """

    # =========================================================================
    # PARSE TRANSCRIPT (VTT → structured turns)
    # =========================================================================
    def parse_transcript(self, vtt_text: str) -> List[Dict[str, Any]]:
        """
        Parse a WebVTT transcript into structured conversation turns.

        Returns a list of dicts:
        [
            {
                "speaker": "John Doe",
                "text": "Hello, how are you today?",
                "start_time": "00:00:05.000",
                "end_time": "00:00:08.500",
            },
            ...
        ]
        """
        if not vtt_text or not vtt_text.strip():
            return []

        turns: List[Dict[str, Any]] = []
        lines = vtt_text.strip().split("\n")

        # VTT format:
        # WEBVTT
        #
        # 1
        # 00:00:05.000 --> 00:00:08.500
        # John Doe: Hello, how are you today?
        #
        # 2
        # 00:00:09.000 --> 00:00:12.000
        # Jane Smith: I'm doing well, thanks.

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Look for timestamp lines: HH:MM:SS.mmm --> HH:MM:SS.mmm
            timestamp_match = re.match(
                r"(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})",
                line,
            )
            if timestamp_match:
                start_time = timestamp_match.group(1)
                end_time = timestamp_match.group(2)

                # Collect all text lines until blank line or next cue
                text_lines = []
                i += 1
                while i < len(lines) and lines[i].strip():
                    text_lines.append(lines[i].strip())
                    i += 1

                full_text = " ".join(text_lines)

                # Extract speaker if present ("Speaker Name: text")
                speaker = ""
                text = full_text
                speaker_match = re.match(r"^([^:]{1,60}):\s*(.+)$", full_text)
                if speaker_match:
                    speaker = speaker_match.group(1).strip()
                    text = speaker_match.group(2).strip()

                if text:
                    turns.append({
                        "speaker": speaker,
                        "text": text,
                        "start_time": start_time,
                        "end_time": end_time,
                    })
            else:
                i += 1

        return turns

    # =========================================================================
    # MATCH CLIENT (participant emails/names → client ID)
    # =========================================================================
    async def match_client(
        self,
        meeting_topic: str = "",
        participant_emails: Optional[List[str]] = None,
    ) -> str:
        """
        Match Zoom meeting participants to a Sovereign Sanctuary client.
        Returns the client_id (hardware_id) or empty string if no match.

        Matching strategy:
        1. Email exact match against user_registry email fields
        2. Name fuzzy match against user_registry display names
        3. Meeting topic match (if topic contains a client name)
        """
        registry = self._load_registry()
        if not registry:
            return ""

        participant_emails = participant_emails or []

        # Build lookup maps
        email_to_id: Dict[str, str] = {}
        name_to_id: Dict[str, str] = {}

        for user_key, user_data in registry.items():
            if not isinstance(user_data, dict):
                continue
            role = (user_data.get("role") or "").upper()
            # Skip coaches/admins — we want to match clients
            if role in ("COACH", "ADMIN"):
                continue

            hw_id = user_data.get("hardware_id") or user_key
            email = (user_data.get("email") or "").lower().strip()
            name = (user_data.get("name") or user_data.get("display_name") or "").lower().strip()

            if email:
                email_to_id[email] = hw_id
            if name and len(name) > 2:
                name_to_id[name] = hw_id

        # Strategy 1: Email match (highest confidence)
        for pemail in participant_emails:
            pemail_lower = pemail.lower().strip()
            if pemail_lower in email_to_id:
                logger.info(f"[Zoom Match] Email match: {pemail_lower} → {email_to_id[pemail_lower]}")
                return email_to_id[pemail_lower]

        # Strategy 2: Meeting topic contains a client name
        if meeting_topic:
            topic_lower = meeting_topic.lower().strip()
            for name, hw_id in name_to_id.items():
                if name in topic_lower:
                    logger.info(f"[Zoom Match] Topic match: '{name}' in '{meeting_topic}' → {hw_id}")
                    return hw_id

        return ""

    # =========================================================================
    # INGEST SESSION (transcript turns → MetricsEngine pipeline)
    # =========================================================================
    async def ingest_session(
        self,
        client_id: str,
        transcript_turns: List[Dict[str, Any]],
        session_source: str = "zoom_meeting",
        meeting_id: str = "",
        topic: str = "",
        start_time: str = "",
        duration: int = 0,
    ) -> Dict[str, Any]:
        """
        Feed client utterances from a parsed Zoom transcript through the
        MetricsEngine.analyze_and_update() pipeline.

        Only processes turns attributed to the CLIENT (not the coach).
        The coach's utterances are used as the "ai_text" context.

        Returns summary of what was processed.
        """
        # Import MetricsEngine at runtime to avoid circular imports
        # The MetricsEngine lives in bridge_server.py
        from app.websocket.bridge_server import MetricsEngine, DATA_DIR as BRIDGE_DATA_DIR

        metrics_engine = MetricsEngine(BRIDGE_DATA_DIR / "Vaults")

        # Build a client profile dict that MetricsEngine expects
        registry = self._load_registry()
        client_profile = None
        for user_key, user_data in registry.items():
            if not isinstance(user_data, dict):
                continue
            hw_id = user_data.get("hardware_id") or user_key
            if hw_id == client_id:
                client_profile = user_data
                break

        if not client_profile:
            logger.warning(f"[Zoom Ingest] Client {client_id} not found in registry")
            return {"error": "client_not_found", "client_turns_processed": 0}

        # Ensure metrics exist
        try:
            metrics_engine.load_metrics(client_profile)
        except Exception:
            metrics_engine.initialize_metrics(client_profile)

        # Identify coach vs client turns
        # Strategy: identify the coach by checking if any speaker name matches
        # a COACH/ADMIN in the registry, then treat remaining speakers as client
        coach_names = set()
        for user_key, user_data in registry.items():
            if not isinstance(user_data, dict):
                continue
            role = (user_data.get("role") or "").upper()
            if role in ("COACH", "ADMIN"):
                name = (user_data.get("name") or user_data.get("display_name") or "").lower().strip()
                if name:
                    coach_names.add(name)

        # Group consecutive client turns and pair with previous/next coach turns
        client_turns_processed = 0
        pending_client_text = []
        last_coach_text = ""

        for turn in transcript_turns:
            speaker = (turn.get("speaker") or "").lower().strip()
            text = turn.get("text") or ""

            is_coach = any(cn in speaker for cn in coach_names) if coach_names else False

            if is_coach:
                # If we have pending client text, flush it with this coach response
                if pending_client_text:
                    user_text = " ".join(pending_client_text)
                    try:
                        metrics_engine.analyze_and_update(
                            client_profile, user_text, last_coach_text
                        )
                        client_turns_processed += 1
                    except Exception as e:
                        logger.error(f"[Zoom Ingest] analyze_and_update failed: {e}")
                    pending_client_text = []
                last_coach_text = text
            else:
                # Client turn
                pending_client_text.append(text)

        # Flush any remaining client text
        if pending_client_text:
            user_text = " ".join(pending_client_text)
            try:
                metrics_engine.analyze_and_update(
                    client_profile, user_text, last_coach_text
                )
                client_turns_processed += 1
            except Exception as e:
                logger.error(f"[Zoom Ingest] analyze_and_update failed: {e}")

        # Tag the session source in the client's metrics
        try:
            current_metrics = metrics_engine.load_metrics(client_profile)
            zoom_sessions = current_metrics.get("zoom_sessions", [])
            zoom_sessions.append({
                "meeting_id": meeting_id,
                "topic": topic,
                "source": session_source,
                "start_time": start_time,
                "duration": duration,
                "turns_total": len(transcript_turns),
                "client_turns_processed": client_turns_processed,
                "ingested_at": dt.datetime.utcnow().isoformat(),
            })
            # Cap to 500 most recent
            current_metrics["zoom_sessions"] = zoom_sessions[-500:]
            # Save
            path = metrics_engine._path(client_profile)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(current_metrics, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"[Zoom Ingest] Failed to save zoom_sessions: {e}")

        # Log to global sessions file
        try:
            sessions = _load_json(SESSIONS_FILE, []) or []
            if not isinstance(sessions, list):
                sessions = []
            sessions.append({
                "client_id": client_id,
                "meeting_id": meeting_id,
                "topic": topic,
                "session_source": session_source,
                "start_time": start_time,
                "duration": duration,
                "client_turns_processed": client_turns_processed,
                "ingested_at": dt.datetime.utcnow().isoformat(),
                "type": "zoom_ingested",
            })
            _save_json(SESSIONS_FILE, sessions[-5000:])
        except Exception as e:
            logger.error(f"[Zoom Ingest] Failed to log session: {e}")

        logger.info(
            f"[Zoom Ingest] Completed: client={client_id}, "
            f"meeting={meeting_id}, turns_processed={client_turns_processed}"
        )

        return {
            "client_id": client_id,
            "meeting_id": meeting_id,
            "session_source": session_source,
            "client_turns_processed": client_turns_processed,
            "total_turns": len(transcript_turns),
        }

    # =========================================================================
    # HELPERS
    # =========================================================================
    def _load_registry(self) -> Dict[str, Any]:
        """Load user registry (merge local + backend like bridge_server does)."""
        local = _load_json(REGISTRY_FILE, {}) or {}
        if not isinstance(local, dict):
            local = {}
        backend = _load_json(BACKEND_REGISTRY_FILE, {}) or {}
        if not isinstance(backend, dict):
            backend = {}
        if not backend:
            return local
        if not local:
            return backend
        merged = dict(backend)
        merged.update(local)
        return merged
