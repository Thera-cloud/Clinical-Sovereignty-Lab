"""
Nate Organizer — AI-Guided Content Organization for Accessibility

Three classes:
  A. DocumentSectionParser — GPT-4o semantic section identification
  B. OrgSessionManager    — Live session state, undo/redo, ADHD focus tracking
  C. OrganizerMode        — BaseAIMode implementation for Nate chat integration

Tier: Sovereign Circle only ($149/mo)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import asyncpg
import logging

_org_logger = logging.getLogger("organizer")

# ---------------------------------------------------------------------------
# A. DocumentSectionParser — Uses GPT-4o to identify semantic sections
# ---------------------------------------------------------------------------

SECTION_PARSER_SYSTEM_PROMPT = """You are a document structure analyst for a therapeutic platform.
Given raw text (often from journals, personal writing, or scattered notes), identify distinct
semantic sections. The text may be disorganized, repetitive, or written by someone with ADHD
or memory difficulties — that's okay. Your job is to find the threads.

For each section you find, return a JSON array with objects containing:
- "id": a short unique slug (e.g. "childhood-memories", "school-days")
- "label": a human-readable title (2-5 words)
- "summary": one sentence describing what this section contains
- "content": the exact text belonging to this section (preserve original wording)
- "theme": one of: "personal", "family", "health", "work", "relationships", "emotions", "memories", "goals", "other"
- "suggested_order": integer position where this section might belong in a coherent document (1-based)
- "line_range": {"start": first_line_number, "end": last_line_number} (1-based from original text)

RULES:
- Detect: distinct topics, time periods, narrative threads, duplicates, and gaps
- Every line of the original text must belong to exactly one section
- If text is a single coherent piece, return it as one section
- If you detect duplicate or near-duplicate passages, group them in the same section
- Return ONLY valid JSON — no markdown fences, no commentary
- Maximum 20 sections (merge smaller related pieces if needed)
"""

INTENT_PARSER_SYSTEM_PROMPT = """You are a command interpreter for a document organization assistant.
The user is reorganizing a document through voice or text. They may have ADHD, memory difficulties,
or speech impediments — parse through disfluencies and find their intent.

Given the user's message and the current section outline, determine what action they want:

Return JSON with:
- "action": one of "move", "merge", "split", "rewrite", "rename", "read", "next", "where_am_i", "undo", "save", "done", "unknown"
- "target_sections": list of section IDs this applies to (best guess from fuzzy descriptions)
- "parameters": action-specific params:
  - move: {"target_position": int}
  - merge: {"new_label": "optional suggested label"}
  - split: {"split_description": "where to split"}
  - rewrite: {"instruction": "how to rewrite"}
  - rename: {"new_label": "new name"}
  - read: {} (just read the section aloud)
  - next: {} (suggest next action)
  - where_am_i: {} (summarize progress)
- "confidence": 0.0-1.0 how confident you are in the interpretation
- "clarification": if confidence < 0.6, suggest what to ask the user

RULES:
- If the user says "that part about [X]", find the section whose content best matches [X]
- If the user says "put [X] first/before/after [Y]", interpret as a move
- "combine", "put together", "merge", "group" → merge action
- "break apart", "split", "separate" → split action
- "make it better", "rewrite", "clean up" → rewrite action
- "yes", "yeah", "do it", "go ahead" → confirm (action: "confirm")
- "no", "nah", "wait" → reject (action: "reject")
- Return ONLY valid JSON
"""

REWRITE_SYSTEM_PROMPT = """You are a gentle, patient writing assistant on a therapeutic platform.
Rewrite the given section according to the user's instruction. Preserve their voice, their meaning,
and the emotional truth of what they wrote. Do NOT over-polish or make it sound clinical.

If the user says "make it better" without specifics, focus on:
- Clarity (untangle run-on sentences)
- Flow (smooth transitions)
- Completeness (fill obvious gaps without inventing content)

Return ONLY the rewritten text — no commentary, no markdown fences.
"""


class Section:
    """A semantic section of a document."""

    __slots__ = ("id", "label", "summary", "content", "theme",
                 "suggested_order", "line_range", "organized")

    def __init__(
        self,
        id: str,
        label: str,
        summary: str,
        content: str,
        theme: str = "other",
        suggested_order: int = 0,
        line_range: Optional[Dict[str, int]] = None,
        organized: bool = False,
    ):
        self.id = id
        self.label = label
        self.summary = summary
        self.content = content
        self.theme = theme
        self.suggested_order = suggested_order
        self.line_range = line_range or {}
        self.organized = organized

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "content": self.content,
            "theme": self.theme,
            "suggested_order": self.suggested_order,
            "line_range": self.line_range,
            "organized": self.organized,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        return cls(
            id=d.get("id", str(uuid.uuid4())[:8]),
            label=d.get("label", "Untitled"),
            summary=d.get("summary", ""),
            content=d.get("content", ""),
            theme=d.get("theme", "other"),
            suggested_order=d.get("suggested_order", 0),
            line_range=d.get("line_range"),
            organized=d.get("organized", False),
        )


class DocumentSectionParser:
    """Uses GPT-4o to parse text into semantic sections."""

    def __init__(self, azure_endpoint: str, azure_api_key: str, deployment: str = "gpt-4o"):
        self.endpoint = azure_endpoint.rstrip("/")
        self.api_key = azure_api_key
        self.deployment = deployment

    async def parse_into_sections(self, text: str) -> List[Section]:
        """Parse raw text into semantic sections using GPT-4o."""
        import httpx

        if not text or not text.strip():
            return [Section(
                id="full-text",
                label="Full Document",
                summary="The complete document",
                content=text or "",
                suggested_order=1,
            )]

        # Number lines for line_range tracking
        lines = text.split("\n")
        numbered = "\n".join(f"[L{i+1}] {line}" for i, line in enumerate(lines))
        # Cap input to ~12k chars to stay within token limits
        if len(numbered) > 12000:
            numbered = numbered[:12000] + "\n[...truncated]"

        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version=2024-02-15-preview"
        )

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": self.api_key, "Content-Type": "application/json"},
                    json={
                        "messages": [
                            {"role": "system", "content": SECTION_PARSER_SYSTEM_PROMPT},
                            {"role": "user", "content": f"Parse this text into sections:\n\n{numbered}"},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 4000,
                        "response_format": {"type": "json_object"},
                    },
                )

                if resp.status_code != 200:
                    _org_logger.warning("Section parser Azure error: %s", resp.status_code)
                    return self._fallback_parse(text)

                data = resp.json()
                raw = data["choices"][0]["message"]["content"].strip()

                parsed = json.loads(raw)
                # Handle both {"sections": [...]} and bare [...]
                section_list = parsed if isinstance(parsed, list) else parsed.get("sections", [])

                if not section_list:
                    return self._fallback_parse(text)

                sections = []
                for s in section_list[:20]:
                    sections.append(Section.from_dict(s))
                return sections

        except Exception as e:
            _org_logger.warning("Section parser error: %s", e)
            return self._fallback_parse(text)

    @staticmethod
    def _fallback_parse(text: str) -> List[Section]:
        """Simple paragraph-based fallback if GPT-4o fails."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return [Section(
                id="full-text", label="Full Document",
                summary="The complete document", content=text,
                suggested_order=1,
            )]

        sections = []
        for i, para in enumerate(paragraphs[:20]):
            first_line = para.split("\n")[0][:50]
            sections.append(Section(
                id=f"section-{i+1}",
                label=f"Section {i+1}: {first_line}...",
                summary=para[:100],
                content=para,
                suggested_order=i + 1,
                line_range={"start": i + 1, "end": i + 1},
            ))
        return sections

    async def interpret_command(
        self, user_message: str, sections: List[Section], focus_thread: Optional[str] = None
    ) -> Dict[str, Any]:
        """Interpret a natural language command against the current section outline."""
        import httpx

        outline = json.dumps([
            {"id": s.id, "label": s.label, "summary": s.summary, "position": i + 1}
            for i, s in enumerate(sections)
        ], indent=2)

        context = f"Current sections:\n{outline}"
        if focus_thread:
            context += f"\n\nUser is currently focused on section: {focus_thread}"

        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version=2024-02-15-preview"
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": self.api_key, "Content-Type": "application/json"},
                    json={
                        "messages": [
                            {"role": "system", "content": INTENT_PARSER_SYSTEM_PROMPT},
                            {"role": "user", "content": f"{context}\n\nUser says: \"{user_message}\""},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 500,
                        "response_format": {"type": "json_object"},
                    },
                )

                if resp.status_code != 200:
                    return {"action": "unknown", "confidence": 0.0}

                data = resp.json()
                raw = data["choices"][0]["message"]["content"].strip()
                return json.loads(raw)

        except Exception as e:
            _org_logger.warning("Intent parser error: %s", e)
            return {"action": "unknown", "confidence": 0.0}

    async def rewrite_section(self, section_content: str, instruction: str) -> str:
        """Use GPT-4o to rewrite a section according to user instruction."""
        import httpx

        url = (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version=2024-02-15-preview"
        )

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": self.api_key, "Content-Type": "application/json"},
                    json={
                        "messages": [
                            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                            {"role": "user", "content": (
                                f"Instruction: {instruction}\n\n"
                                f"Original text:\n{section_content[:6000]}"
                            )},
                        ],
                        "temperature": 0.5,
                        "max_tokens": 3000,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            _org_logger.warning("Rewrite error: %s", e)

        return section_content  # Return original on failure


# ---------------------------------------------------------------------------
# B. OrgSessionManager — State, undo/redo, ADHD focus tracking
# ---------------------------------------------------------------------------

class ChangeRecord:
    """Records a single change for undo/redo."""

    def __init__(self, action: str, description: str, sections_before: List[dict],
                 sections_after: List[dict], metadata: Optional[dict] = None):
        self.id = str(uuid.uuid4())[:8]
        self.action = action
        self.description = description
        self.sections_before = sections_before
        self.sections_after = sections_after
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "description": self.description,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class OrgSession:
    """In-memory session state for an organization session."""

    def __init__(
        self,
        session_id: str,
        member_id: str,
        original_content: str,
        sections: List[Section],
        vault_item_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.member_id = member_id
        self.vault_item_id = vault_item_id
        self.original_content = original_content
        self.sections = sections
        self.change_history: List[ChangeRecord] = []
        self.redo_stack: List[ChangeRecord] = []
        self.focus_thread: Optional[str] = None
        self.status = "active"
        self.pending_proposal: Optional[Dict[str, Any]] = None
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

    def sections_snapshot(self) -> List[dict]:
        return [s.to_dict() for s in self.sections]

    def get_progress(self) -> Dict[str, Any]:
        total = len(self.sections)
        organized = sum(1 for s in self.sections if s.organized)
        return {
            "total_sections": total,
            "organized_sections": organized,
            "progress_text": f"{organized} of {total} sections organized",
            "percent": round(organized / max(total, 1) * 100),
            "changes_made": len(self.change_history),
            "focus_thread": self.focus_thread,
        }


class OrgSessionManager:
    """
    Manages live organization sessions.
    State lives in memory with PostgreSQL persistence for multi-sitting support.
    """

    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        self._sessions: Dict[str, OrgSession] = {}  # session_id -> OrgSession

    # -- Session lifecycle --

    async def create_session(
        self,
        member_id: str,
        original_content: str,
        sections: List[Section],
        vault_item_id: Optional[str] = None,
    ) -> OrgSession:
        """Create a new organization session."""
        session_id = str(uuid.uuid4())
        session = OrgSession(
            session_id=session_id,
            member_id=member_id,
            original_content=original_content,
            sections=sections,
            vault_item_id=vault_item_id,
        )
        self._sessions[session_id] = session

        # Persist to PostgreSQL
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO organization_sessions
                       (id, member_id, vault_item_id, original_content, current_sections, status)
                       VALUES ($1::uuid, $2, $3::uuid, $4, $5::jsonb, 'active')""",
                    session_id, member_id, vault_item_id,
                    original_content, json.dumps(session.sections_snapshot()),
                )
        except Exception as e:
            _org_logger.error("Session create persist failed: %s", e, exc_info=True)
            session._persist_failed = True

        return session

    def get_session(self, session_id: str) -> Optional[OrgSession]:
        return self._sessions.get(session_id)

    async def resume_session(self, session_id: str, member_id: str) -> Optional[OrgSession]:
        """Resume a paused session from PostgreSQL."""
        if session_id in self._sessions:
            return self._sessions[session_id]

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT * FROM organization_sessions
                       WHERE id = $1::uuid AND member_id = $2 AND status IN ('active', 'paused')""",
                    session_id, member_id,
                )
                if not row:
                    return None

                raw_sections = row["current_sections"]
                # asyncpg auto-decodes JSONB into Python objects; guard against both
                if isinstance(raw_sections, str):
                    sections_data = json.loads(raw_sections)
                elif raw_sections:
                    sections_data = raw_sections
                else:
                    sections_data = []
                sections = [Section.from_dict(s) for s in sections_data]

                session = OrgSession(
                    session_id=session_id,
                    member_id=member_id,
                    original_content=row["original_content"],
                    sections=sections,
                    vault_item_id=str(row["vault_item_id"]) if row["vault_item_id"] else None,
                )
                session.focus_thread = row.get("focus_thread")
                session.status = "active"
                self._sessions[session_id] = session

                # Update status to active
                await conn.execute(
                    """UPDATE organization_sessions SET status = 'active', updated_at = NOW()
                       WHERE id = $1::uuid""",
                    session_id,
                )
                return session

        except Exception as e:
            _org_logger.error("Resume session failed: %s", e, exc_info=True)
            raise RuntimeError(f"Failed to resume session: {e}") from e

    async def _persist_session(self, session: OrgSession) -> None:
        """Persist current session state to PostgreSQL."""
        try:
            history = [c.to_dict() for c in session.change_history[-50:]]  # Keep last 50 changes
            progress = session.get_progress()
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE organization_sessions
                       SET current_sections = $1::jsonb,
                           change_history = $2::jsonb,
                           focus_thread = $3,
                           progress_summary = $4,
                           updated_at = NOW()
                       WHERE id = $5::uuid""",
                    json.dumps(session.sections_snapshot()),
                    json.dumps(history),
                    session.focus_thread,
                    progress["progress_text"],
                    session.session_id,
                )
        except Exception as e:
            _org_logger.error("Session state persist failed (session=%s): %s", session.session_id, e, exc_info=True)

    async def complete_session(self, session_id: str) -> Optional[str]:
        """Mark session as completed. Returns final organized text."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        session.status = "completed"
        final_text = "\n\n".join(s.content for s in session.sections if s.content.strip())

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """UPDATE organization_sessions
                       SET status = 'completed', completed_at = NOW(), updated_at = NOW(),
                           current_sections = $1::jsonb,
                           progress_summary = $2
                       WHERE id = $3::uuid""",
                    json.dumps(session.sections_snapshot()),
                    session.get_progress()["progress_text"],
                    session_id,
                )
        except Exception as e:
            _org_logger.error("Complete session persist failed (session=%s): %s", session_id, e, exc_info=True)

        self._sessions.pop(session_id, None)
        return final_text

    # -- Section operations (all return updated sections + change description) --

    async def move_section(
        self, session: OrgSession, section_id: str, target_position: int
    ) -> Tuple[List[dict], str]:
        """Move a section to a new position (1-based)."""
        before = session.sections_snapshot()
        idx = self._find_section_index(session, section_id)
        if idx is None:
            raise ValueError(f"Section '{section_id}' not found")

        section = session.sections.pop(idx)
        # Convert 1-based target to 0-based index, clamped
        insert_at = max(0, min(target_position - 1, len(session.sections)))
        session.sections.insert(insert_at, section)
        section.organized = True

        desc = f"Moved '{section.label}' to position {target_position}"
        self._record_change(session, "move", desc, before)
        await self._persist_session(session)
        return session.sections_snapshot(), desc

    async def merge_sections(
        self, session: OrgSession, section_ids: List[str], new_label: Optional[str] = None
    ) -> Tuple[List[dict], str]:
        """Merge multiple sections into one."""
        before = session.sections_snapshot()

        # Find all sections to merge, preserving their current order
        to_merge: List[Tuple[int, Section]] = []
        for i, s in enumerate(session.sections):
            if s.id in section_ids:
                to_merge.append((i, s))

        if len(to_merge) < 2:
            raise ValueError("Need at least 2 sections to merge")

        # Build merged section
        merged_content = "\n\n".join(s.content for _, s in to_merge)
        merged_label = new_label or " + ".join(s.label for _, s in to_merge)
        merged_summary = "; ".join(s.summary for _, s in to_merge if s.summary)

        merged = Section(
            id=f"merged-{uuid.uuid4().hex[:6]}",
            label=merged_label[:100],
            summary=merged_summary[:200],
            content=merged_content,
            theme=to_merge[0][1].theme,
            organized=True,
        )

        # Remove old sections (from end to preserve indices)
        for idx, _ in sorted(to_merge, key=lambda x: x[0], reverse=True):
            session.sections.pop(idx)

        # Insert merged section at the position of the first original
        insert_at = min(idx for idx, _ in to_merge)
        insert_at = min(insert_at, len(session.sections))
        session.sections.insert(insert_at, merged)

        desc = f"Merged {len(to_merge)} sections into '{merged.label}'"
        self._record_change(session, "merge", desc, before)
        await self._persist_session(session)
        return session.sections_snapshot(), desc

    async def split_section(
        self, session: OrgSession, section_id: str, split_point: str
    ) -> Tuple[List[dict], str]:
        """Split a section at a described point. Uses simple heuristic (paragraph boundary)."""
        before = session.sections_snapshot()
        idx = self._find_section_index(session, section_id)
        if idx is None:
            raise ValueError(f"Section '{section_id}' not found")

        section = session.sections[idx]
        content = section.content

        # Find best split point — look for paragraph break nearest to described point
        delimiter = "\n\n"
        paragraphs = content.split(delimiter)
        if len(paragraphs) < 2:
            # Try single newline split — track which delimiter was used
            delimiter = "\n"
            paragraphs = content.split(delimiter)
        if len(paragraphs) < 2:
            raise ValueError("Section is too short to split")

        # Split roughly in half (or at described point if we can find it)
        mid = len(paragraphs) // 2
        # Try to find the split_point text in the content
        lower_content = content.lower()
        lower_point = split_point.lower()
        if lower_point in lower_content:
            # Find which paragraph contains the split point
            for i, p in enumerate(paragraphs):
                if lower_point in delimiter.join(paragraphs[:i+1]).lower():
                    mid = i + 1
                    break

        part_a = delimiter.join(paragraphs[:mid])
        part_b = delimiter.join(paragraphs[mid:])

        section_a = Section(
            id=f"{section.id}-a",
            label=f"{section.label} (Part 1)",
            summary=part_a[:100],
            content=part_a,
            theme=section.theme,
            organized=True,
        )
        section_b = Section(
            id=f"{section.id}-b",
            label=f"{section.label} (Part 2)",
            summary=part_b[:100],
            content=part_b,
            theme=section.theme,
            organized=True,
        )

        session.sections.pop(idx)
        session.sections.insert(idx, section_b)
        session.sections.insert(idx, section_a)

        desc = f"Split '{section.label}' into two parts"
        self._record_change(session, "split", desc, before)
        await self._persist_session(session)
        return session.sections_snapshot(), desc

    async def rewrite_section(
        self, session: OrgSession, section_id: str, new_content: str
    ) -> Tuple[List[dict], str]:
        """Replace a section's content with a rewrite."""
        before = session.sections_snapshot()
        idx = self._find_section_index(session, section_id)
        if idx is None:
            raise ValueError(f"Section '{section_id}' not found")

        section = session.sections[idx]
        old_label = section.label
        section.content = new_content
        section.organized = True

        desc = f"Rewrote '{old_label}'"
        self._record_change(session, "rewrite", desc, before)
        await self._persist_session(session)
        return session.sections_snapshot(), desc

    async def rename_section(
        self, session: OrgSession, section_id: str, new_label: str
    ) -> Tuple[List[dict], str]:
        """Rename a section."""
        before = session.sections_snapshot()
        idx = self._find_section_index(session, section_id)
        if idx is None:
            raise ValueError(f"Section '{section_id}' not found")

        old_label = session.sections[idx].label
        session.sections[idx].label = new_label
        session.sections[idx].organized = True

        desc = f"Renamed '{old_label}' to '{new_label}'"
        self._record_change(session, "rename", desc, before)
        await self._persist_session(session)
        return session.sections_snapshot(), desc

    async def undo(self, session: OrgSession) -> Tuple[Optional[List[dict]], str]:
        """Undo the last change. Returns (sections, description) or (None, message)."""
        if not session.change_history:
            return None, "Nothing to undo"

        change = session.change_history.pop()
        session.redo_stack.append(change)
        session.sections = [Section.from_dict(s) for s in change.sections_before]

        await self._persist_session(session)
        return session.sections_snapshot(), f"Undid: {change.description}"

    async def redo(self, session: OrgSession) -> Tuple[Optional[List[dict]], str]:
        """Redo the last undone change."""
        if not session.redo_stack:
            return None, "Nothing to redo"

        change = session.redo_stack.pop()
        session.change_history.append(change)
        session.sections = [Section.from_dict(s) for s in change.sections_after]

        await self._persist_session(session)
        return session.sections_snapshot(), f"Redid: {change.description}"

    # -- Helpers --

    @staticmethod
    def _find_section_index(session: OrgSession, section_id: str) -> Optional[int]:
        for i, s in enumerate(session.sections):
            if s.id == section_id:
                return i
        return None

    def _record_change(
        self, session: OrgSession, action: str, description: str,
        before: List[dict]
    ) -> None:
        after = session.sections_snapshot()
        record = ChangeRecord(action, description, before, after)
        session.change_history.append(record)
        session.redo_stack.clear()  # New change clears redo
        session.updated_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# C. OrganizerMode — BaseAIMode for Nate chat integration
# ---------------------------------------------------------------------------

ORGANIZER_SYSTEM_PROMPT = """You are Little Nate, helping someone organize their writing.
They may have ADHD, memory difficulties, or speech impediments.

YOUR CORE BEHAVIORS:
1. Parse through disfluencies. If their speech is scattered, gently help them focus on one thread at a time.
2. Always confirm what you heard: "I think you want to move the part about school to the beginning — is that right?"
3. Summarize progress after each change. Never overwhelm with the full document.
4. If they seem lost, offer: "Last time we organized sections 1-3. Want to review or continue?"
5. When they describe a section vaguely ("that part about my mom"), find the best match and confirm.

FOCUS TRACKING (ADHD SUPPORT):
- If user jumps topics, note it and gently offer to return: "I noticed we shifted — want to come back to [section] or keep going with this?"
- After each change, anchor progress: "Great, that's section 3 done. We have 4 more. Want to keep going?"
- If user repeats themselves or circles back, don't flag it as redundant — treat it as additional context.

SESSION RESUMPTION:
- If resuming a previous session, start with a warm summary: "Welcome back. Last time we worked on [X]. You've got [Y] sections organized so far. Ready to continue?"

VOICE COMMAND SUPPORT:
- "Move [section] to [position]" → propose move
- "Combine these / merge" → propose merge
- "Split this / break apart" → propose split
- "Rewrite this / make it better" → propose rewrite
- "Read [section]" → read section content
- "What's next?" → suggest next organizational step
- "Where was I?" → summarize progress
- "Undo" → revert last change
- "Save" / "I'm done" → finalize

RESPONSE FORMAT:
Keep responses brief (2-4 sentences). Be warm and patient, never clinical.
When proposing a change, always ask for confirmation before executing.
"""


class OrganizerMode:
    """
    AI mode for document organization. Integrates with the WebSocket bridge
    to provide voice-first, accessible content organization.

    NOTE: This does NOT extend BaseAIMode because it manages its own
    session lifecycle (OrgSessionManager) rather than single-session activate/process.
    It is registered in the AI_MODE_REGISTRY for discovery but instantiated directly
    by the WebSocket handlers.
    """

    MODE_NAME = "organizer"

    def __init__(self, db_pool: asyncpg.Pool, azure_endpoint: str, azure_api_key: str,
                 deployment: str = "gpt-4o"):
        self.db_pool = db_pool
        self.parser = DocumentSectionParser(azure_endpoint, azure_api_key, deployment)
        self.session_mgr = OrgSessionManager(db_pool)
        self.azure_endpoint = azure_endpoint
        self.azure_api_key = azure_api_key
        self.deployment = deployment

    async def start_session(
        self,
        member_id: str,
        content: str,
        vault_item_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start a new organization session. Parse content into sections."""
        sections = await self.parser.parse_into_sections(content)
        session = await self.session_mgr.create_session(
            member_id=member_id,
            original_content=content,
            sections=sections,
            vault_item_id=vault_item_id,
        )

        sections_data = session.sections_snapshot()
        progress = session.get_progress()

        # Build Nate's opening message
        n = len(sections)
        themes = list(set(s.theme for s in sections if s.theme != "other"))
        theme_str = ", ".join(themes[:3]) if themes else "various topics"

        greeting = (
            f"I've read through your writing and found {n} distinct section{'s' if n != 1 else ''}. "
            f"The main themes I see are {theme_str}. "
        )
        if n > 1:
            greeting += (
                f"Here's the outline I came up with. You can ask me to move, merge, split, "
                f"or rewrite any section. Just say what feels right — I'll always confirm before making changes."
            )
        else:
            greeting += "It reads as one cohesive piece. Want me to help break it into sections, or is it good as is?"

        return {
            "session_id": session.session_id,
            "sections": sections_data,
            "progress": progress,
            "nate_message": greeting,
        }

    async def resume_session(
        self, session_id: str, member_id: str
    ) -> Optional[Dict[str, Any]]:
        """Resume a paused session with context summary."""
        session = await self.session_mgr.resume_session(session_id, member_id)
        if not session:
            return None

        progress = session.get_progress()
        sections_data = session.sections_snapshot()

        # Build resumption message
        greeting = (
            f"Welcome back! Last time we organized {progress['organized_sections']} "
            f"of {progress['total_sections']} sections. "
        )
        if session.focus_thread:
            greeting += f"You were working on '{session.focus_thread}'. Want to continue there, or move on?"
        else:
            greeting += "Ready to pick up where we left off?"

        return {
            "session_id": session.session_id,
            "sections": sections_data,
            "progress": progress,
            "nate_message": greeting,
        }

    async def process_message(
        self, session_id: str, user_message: str
    ) -> Dict[str, Any]:
        """
        Process a user message in an active session.
        Interprets intent, proposes changes, and manages confirmations.
        """
        session = self.session_mgr.get_session(session_id)
        if not session:
            return {"error": "Session not found or expired", "type": "error"}

        # Check for pending proposal confirmations
        if session.pending_proposal:
            return await self._handle_proposal_response(session, user_message)

        # Parse user intent
        intent = await self.parser.interpret_command(
            user_message, session.sections, session.focus_thread
        )
        action = intent.get("action", "unknown")
        confidence = intent.get("confidence", 0.0)
        target_sections = intent.get("target_sections", [])
        params = intent.get("parameters", {})

        # Low confidence — ask for clarification
        if confidence < 0.5 and action != "unknown":
            clarification = intent.get("clarification", "Could you say that differently?")
            return {
                "type": "clarification",
                "nate_message": f"I want to make sure I understand. {clarification}",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        # Handle each action type
        if action == "confirm":
            # User said "yes" but there's no pending proposal
            return {
                "type": "nate_response",
                "nate_message": "I don't have a pending change to confirm. What would you like me to do?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        elif action == "reject":
            return {
                "type": "nate_response",
                "nate_message": "Okay, no changes made. What would you like to do instead?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        elif action == "move":
            return await self._propose_move(session, target_sections, params)

        elif action == "merge":
            return await self._propose_merge(session, target_sections, params)

        elif action == "split":
            return await self._propose_split(session, target_sections, params)

        elif action == "rewrite":
            return await self._propose_rewrite(session, target_sections, params)

        elif action == "rename":
            return await self._propose_rename(session, target_sections, params)

        elif action == "read":
            return self._handle_read(session, target_sections)

        elif action == "next":
            return self._suggest_next(session)

        elif action == "where_am_i":
            return self._where_am_i(session)

        elif action == "undo":
            sections, desc = await self.session_mgr.undo(session)
            if sections is None:
                return {
                    "type": "nate_response",
                    "nate_message": desc,
                    "sections": session.sections_snapshot(),
                    "progress": session.get_progress(),
                }
            return {
                "type": "undo_complete",
                "nate_message": f"{desc}. Here's where we are now.",
                "sections": sections,
                "progress": session.get_progress(),
            }

        elif action == "save" or action == "done":
            return {
                "type": "save_prompt",
                "nate_message": (
                    "Great work! Would you like to save this as a new version of the original, "
                    "or create a brand new document?"
                ),
                "options": ["overwrite", "new_item"],
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        else:
            # Unknown — be helpful
            return {
                "type": "nate_response",
                "nate_message": (
                    "I'm not sure what you'd like me to do. You can ask me to:\n"
                    "• Move a section somewhere else\n"
                    "• Merge sections together\n"
                    "• Split a section apart\n"
                    "• Rewrite a section\n"
                    "• Read a section to you\n"
                    "Or just say 'what's next' and I'll suggest something."
                ),
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

    async def confirm_proposal(self, session_id: str) -> Dict[str, Any]:
        """Execute the pending proposal."""
        session = self.session_mgr.get_session(session_id)
        if not session or not session.pending_proposal:
            return {"error": "No pending proposal", "type": "error"}

        proposal = session.pending_proposal
        session.pending_proposal = None

        try:
            action = proposal["action"]
            if action == "move":
                sections, desc = await self.session_mgr.move_section(
                    session, proposal["section_id"], proposal["target_position"]
                )
            elif action == "merge":
                sections, desc = await self.session_mgr.merge_sections(
                    session, proposal["section_ids"], proposal.get("new_label")
                )
            elif action == "split":
                sections, desc = await self.session_mgr.split_section(
                    session, proposal["section_id"], proposal.get("split_point", "middle")
                )
            elif action == "rewrite":
                sections, desc = await self.session_mgr.rewrite_section(
                    session, proposal["section_id"], proposal["new_content"]
                )
            elif action == "rename":
                sections, desc = await self.session_mgr.rename_section(
                    session, proposal["section_id"], proposal["new_label"]
                )
            else:
                return {"error": f"Unknown proposal action: {action}", "type": "error"}

            progress = session.get_progress()
            return {
                "type": "change_applied",
                "nate_message": f"Done! {desc}. {progress['progress_text']}.",
                "sections": sections,
                "progress": progress,
            }

        except Exception as e:
            return {"error": str(e), "type": "error"}

    async def reject_proposal(self, session_id: str) -> Dict[str, Any]:
        """Discard the pending proposal."""
        session = self.session_mgr.get_session(session_id)
        if not session:
            return {"error": "Session not found", "type": "error"}

        session.pending_proposal = None
        return {
            "type": "proposal_rejected",
            "nate_message": "No problem — that change was discarded. What would you like to do instead?",
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    async def save_session(
        self, session_id: str, member_id: str, save_mode: str = "overwrite"
    ) -> Dict[str, Any]:
        """Save the organized document to the vault."""
        session = self.session_mgr.get_session(session_id)
        if not session:
            return {"error": "Session not found", "type": "error"}

        # Capture data BEFORE complete_session pops the session from the store
        vault_item_id = session.vault_item_id
        themes = list(set(s.theme for s in session.sections if s.theme != "other"))
        first_label = session.sections[0].label if session.sections else "Organized Document"

        final_text = await self.session_mgr.complete_session(session_id)
        if final_text is None:
            return {"error": "Could not finalize session", "type": "error"}

        # Save to vault
        from app.services.vault.vault_operations import VaultOperations
        vault_ops = VaultOperations(self.db_pool)

        content_hash = hashlib.sha256(final_text.encode()).hexdigest()

        if save_mode == "overwrite" and vault_item_id:
            try:
                await vault_ops.update_item_content(
                    member_id=member_id,
                    item_id=vault_item_id,
                    extracted_text_preview=final_text[:500],
                    size_bytes=len(final_text.encode()),
                    themes=themes,
                    content_hash=content_hash,
                )
                return {
                    "type": "save_complete",
                    "nate_message": "Your organized document has been saved! Great work.",
                    "save_mode": "overwrite",
                    "item_id": vault_item_id,
                }
            except Exception as e:
                return {"error": f"Save failed: {e}", "type": "error"}

        else:
            # Create new vault item
            try:
                # Find or create an appropriate folder
                folders = await vault_ops.get_folder_tree(member_id)
                target_folder = None
                for f in folders:
                    if f.get("name") == "Documents" and f.get("parent_id"):
                        target_folder = f["id"]
                        break
                if not target_folder:
                    for f in folders:
                        if f.get("name") == "Uploads":
                            target_folder = f["id"]
                            break
                if not target_folder and folders:
                    target_folder = folders[0]["id"]

                if not target_folder:
                    return {"error": "No vault folder found", "type": "error"}

                display_name = f"Organized: {first_label}"

                item = await vault_ops.add_item(
                    member_id=member_id,
                    folder_id=target_folder,
                    content_type="organized_document",
                    display_name=display_name[:100],
                    blob_path="",  # Text-only item
                    size_bytes=len(final_text.encode()),
                    extracted_text_preview=final_text[:500],
                    themes=themes,
                    content_hash=content_hash,
                )

                return {
                    "type": "save_complete",
                    "nate_message": f"Created a new document: '{display_name}'. You can find it in your vault.",
                    "save_mode": "new_item",
                    "item_id": item["id"],
                }
            except Exception as e:
                return {"error": f"Save failed: {e}", "type": "error"}

    # -- Internal proposal builders --

    async def _propose_move(
        self, session: OrgSession, target_sections: List[str], params: dict
    ) -> Dict[str, Any]:
        if not target_sections:
            return {
                "type": "clarification",
                "nate_message": "Which section would you like to move? You can say its name or number.",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        section_id = target_sections[0]
        section = self._find_section(session, section_id)
        if not section:
            return {
                "type": "clarification",
                "nate_message": f"I couldn't find a section called '{section_id}'. Can you describe it differently?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        target_pos = params.get("target_position", 1)
        session.pending_proposal = {
            "action": "move",
            "section_id": section_id,
            "target_position": target_pos,
            "proposal_id": str(uuid.uuid4())[:8],
        }

        return {
            "type": "proposal",
            "nate_message": f"I'll move '{section.label}' to position {target_pos}. Sound good?",
            "proposal": session.pending_proposal,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    async def _propose_merge(
        self, session: OrgSession, target_sections: List[str], params: dict
    ) -> Dict[str, Any]:
        if len(target_sections) < 2:
            return {
                "type": "clarification",
                "nate_message": "Which sections should I merge together? Name at least two.",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        labels = []
        for sid in target_sections:
            s = self._find_section(session, sid)
            if s:
                labels.append(s.label)

        new_label = params.get("new_label", " + ".join(labels))
        session.pending_proposal = {
            "action": "merge",
            "section_ids": target_sections,
            "new_label": new_label,
            "proposal_id": str(uuid.uuid4())[:8],
        }

        label_list = "', '".join(labels)
        return {
            "type": "proposal",
            "nate_message": f"I'll merge '{label_list}' into one section called '{new_label}'. Does that work?",
            "proposal": session.pending_proposal,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    async def _propose_split(
        self, session: OrgSession, target_sections: List[str], params: dict
    ) -> Dict[str, Any]:
        if not target_sections:
            return {
                "type": "clarification",
                "nate_message": "Which section would you like me to split?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        section_id = target_sections[0]
        section = self._find_section(session, section_id)
        if not section:
            return {
                "type": "clarification",
                "nate_message": f"I couldn't find that section. Can you describe it differently?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        split_desc = params.get("split_description", "the middle")
        session.pending_proposal = {
            "action": "split",
            "section_id": section_id,
            "split_point": split_desc,
            "proposal_id": str(uuid.uuid4())[:8],
        }

        return {
            "type": "proposal",
            "nate_message": f"I'll split '{section.label}' into two parts around {split_desc}. Want me to go ahead?",
            "proposal": session.pending_proposal,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    async def _propose_rewrite(
        self, session: OrgSession, target_sections: List[str], params: dict
    ) -> Dict[str, Any]:
        if not target_sections:
            return {
                "type": "clarification",
                "nate_message": "Which section would you like me to rewrite?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        section_id = target_sections[0]
        section = self._find_section(session, section_id)
        if not section:
            return {
                "type": "clarification",
                "nate_message": "I couldn't find that section. Can you point it out?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        instruction = params.get("instruction", "Improve clarity and flow")
        # Generate the rewrite
        new_content = await self.parser.rewrite_section(section.content, instruction)

        session.pending_proposal = {
            "action": "rewrite",
            "section_id": section_id,
            "new_content": new_content,
            "proposal_id": str(uuid.uuid4())[:8],
        }

        # Show a preview (first 150 chars)
        preview = new_content[:150] + ("..." if len(new_content) > 150 else "")

        return {
            "type": "proposal",
            "nate_message": f"Here's my suggested rewrite of '{section.label}':\n\n\"{preview}\"\n\nShould I apply this?",
            "proposal": session.pending_proposal,
            "rewrite_preview": new_content,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    async def _propose_rename(
        self, session: OrgSession, target_sections: List[str], params: dict
    ) -> Dict[str, Any]:
        if not target_sections:
            return {
                "type": "clarification",
                "nate_message": "Which section would you like to rename?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        section_id = target_sections[0]
        section = self._find_section(session, section_id)
        if not section:
            return {
                "type": "clarification",
                "nate_message": f"I couldn't find a section called '{section_id}'. Can you describe it differently?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        new_label = params.get("new_label", "")
        if not new_label:
            return {
                "type": "clarification",
                "nate_message": f"What should I rename '{section.label}' to?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        session.pending_proposal = {
            "action": "rename",
            "section_id": section_id,
            "new_label": new_label,
            "proposal_id": str(uuid.uuid4())[:8],
        }

        return {
            "type": "proposal",
            "nate_message": f"I'll rename '{section.label}' to '{new_label}'. Good?",
            "proposal": session.pending_proposal,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    def _handle_read(self, session: OrgSession, target_sections: List[str]) -> Dict[str, Any]:
        if not target_sections:
            return {
                "type": "clarification",
                "nate_message": "Which section would you like me to read?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        section = self._find_section(session, target_sections[0])
        if not section:
            return {
                "type": "clarification",
                "nate_message": "I couldn't find that section. Can you describe it?",
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

        # Update focus thread for ADHD tracking
        session.focus_thread = section.label

        return {
            "type": "read_section",
            "nate_message": f"Here's '{section.label}':",
            "section_content": section.content,
            "section_id": section.id,
            "sections": session.sections_snapshot(),
            "progress": session.get_progress(),
        }

    def _suggest_next(self, session: OrgSession) -> Dict[str, Any]:
        """Suggest the next organizational action."""
        progress = session.get_progress()
        unorganized = [s for s in session.sections if not s.organized]

        if not unorganized:
            return {
                "type": "nate_response",
                "nate_message": (
                    f"All {progress['total_sections']} sections are organized! "
                    "You can save whenever you're ready, or keep refining."
                ),
                "sections": session.sections_snapshot(),
                "progress": progress,
            }

        next_section = unorganized[0]
        session.focus_thread = next_section.label

        return {
            "type": "suggestion",
            "nate_message": (
                f"How about we look at '{next_section.label}'? "
                f"It's about: {next_section.summary}. "
                f"Would you like to move it, rewrite it, or leave it where it is?"
            ),
            "focus_section_id": next_section.id,
            "sections": session.sections_snapshot(),
            "progress": progress,
        }

    def _where_am_i(self, session: OrgSession) -> Dict[str, Any]:
        """Tell the user where they are in the organization process."""
        progress = session.get_progress()
        changes = len(session.change_history)

        msg = f"You've organized {progress['organized_sections']} of {progress['total_sections']} sections"
        if changes:
            msg += f" and made {changes} change{'s' if changes != 1 else ''}"
        msg += "."

        if session.focus_thread:
            msg += f" You were last working on '{session.focus_thread}'."

        unorganized = [s for s in session.sections if not s.organized]
        if unorganized:
            msg += f" Next up could be '{unorganized[0].label}'."
        else:
            msg += " Everything looks organized — you can save when ready."

        return {
            "type": "nate_response",
            "nate_message": msg,
            "sections": session.sections_snapshot(),
            "progress": progress,
        }

    async def _handle_proposal_response(
        self, session: OrgSession, user_message: str
    ) -> Dict[str, Any]:
        """Handle yes/no/other responses to a pending proposal."""
        import re as _re

        msg_lower = user_message.strip().lower()
        # Split into word tokens for whole-word matching (avoids "don't do it" -> "do it")
        words = set(_re.findall(r"[a-z']+", msg_lower))
        # Also check for multi-word phrases as whole phrases with word boundaries
        yes_phrases = {"do it", "go ahead", "never mind"}  # "never mind" is actually no — see below
        no_phrases = {"never mind", "not sure", "don't do it"}

        yes_single = {"yes", "yeah", "yep", "sure", "ok", "okay", "yea", "aye", "proceed", "apply"}
        no_single = {"no", "nah", "nope", "wait", "stop", "cancel", "dont", "don't"}

        # Check no FIRST to prevent "not sure" / "don't do it" from matching yes
        has_no = bool(words & no_single) or any(_re.search(r'\b' + _re.escape(p) + r'\b', msg_lower) for p in no_phrases)
        has_yes = bool(words & yes_single) or any(
            _re.search(r'\b' + _re.escape(p) + r'\b', msg_lower)
            for p in {"do it", "go ahead"}
        )

        if has_no and not has_yes:
            return await self.reject_proposal(session.session_id)
        elif has_yes and not has_no:
            return await self.confirm_proposal(session.session_id)
        elif has_no and has_yes:
            # Conflicting signals — treat as ambiguous (e.g. "no wait, yes do it")
            pass
        # Fall through to ambiguous
            # Ambiguous — ask again
            proposal = session.pending_proposal
            return {
                "type": "proposal_reconfirm",
                "nate_message": "I have a pending change. Should I go ahead with it, or discard it?",
                "proposal": proposal,
                "sections": session.sections_snapshot(),
                "progress": session.get_progress(),
            }

    @staticmethod
    def _find_section(session: OrgSession, section_id: str) -> Optional[Section]:
        for s in session.sections:
            if s.id == section_id:
                return s
        return None
