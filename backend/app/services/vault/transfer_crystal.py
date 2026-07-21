"""
Sovereign Vault — Transfer Crystal (B3).

Builds therapeutic summary crystals from imported AI chat exports
(ChatGPT, Claude, Gemini, Replika). Parses platform-specific formats,
runs content sentinel scan, batch-analyzes with GPT-4o, and synthesizes
a 9-section clinical crystal for first-session continuity.
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.services.vault.content_sentinel_file import FileContentSentinel

logger = logging.getLogger("vault.transfer_crystal")

IMPORT_SOURCES = {
    "chatgpt": {
        "name": "ChatGPT (OpenAI)",
        "file_format": "zip containing conversations.json",
        "parser": "chatgpt_parser",
    },
    "claude": {
        "name": "Claude (Anthropic)",
        "file_format": "json conversations export",
        "parser": "claude_parser",
    },
    "gemini": {
        "name": "Gemini (Google)",
        "file_format": "Google Takeout export",
        "parser": "gemini_parser",
    },
    "replika": {
        "name": "Replika",
        "file_format": "data export (JSON or CSV)",
        "parser": "replika_parser",
    },
}

IMPORT_TRIGGER_PHRASES = [
    "import my chatgpt",
    "transfer from chatgpt",
    "bring my history",
    "import my conversations",
    "i have a chatgpt export",
    "transfer crystal",
    "bring my data from",
    "import from claude",
    "switch from chatgpt",
    "migrate from",
    "bring over my",
]

# =============================================================================
# IMPORT SAFETY LIMITS (Section 9b)
# =============================================================================
MAX_CONVERSATIONS = 10_000
MAX_MESSAGES_PER_CONV = 5_000
MAX_MESSAGE_TEXT_CHARS = 100_000
MAX_JSON_BYTES = 200 * 1024 * 1024  # 200MB
MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024  # 500MB
MAX_ZIP_ENTRIES = 100
MAX_ZIP_ENTRY_SIZE = 200 * 1024 * 1024  # 200MB per entry
MAX_JSON_DEPTH = 50
MAX_VAULT_ITEMS_PER_USER = 10_000

# Import-specific injection patterns (Section 9c)
IMPORT_INJECTION_PATTERNS = [
    (r'"role"\s*:\s*"system"', "embedded_role_override"),
    (r'"role"\s*:\s*"(admin|developer)"', "embedded_admin_role"),
    (r'}\s*,\s*\{[^}]*"role"\s*:', "json_structure_escape"),
    (r'(?:eyJ|YTo)[A-Za-z0-9+/]{20,}={0,2}', "base64_payload"),
]

BATCH_ANALYSIS_PROMPT = """You are a clinical analyst preparing a therapeutic transfer summary for Sovereign Sanctuary (Little Nate), an AI therapy platform.

Analyze this batch of user messages from a prior AI chat platform export. Extract therapeutic-relevant patterns.

For each batch, provide a JSON object with these keys (use empty arrays/objects if none found):
- key_relationships: list of people, roles, or entities the user mentions (e.g., partner, parent, boss)
- recurring_emotional_themes: list of emotional patterns (e.g., anxiety about work, grief, loneliness)
- significant_life_events: list of notable events mentioned (e.g., divorce, job loss, birth)
- communication_style: brief description of how they express themselves (e.g., analytical, emotional, avoidant)
- therapeutic_patterns: list of themes from prior therapeutic work (e.g., CBT techniques, attachment work)
- unresolved_threads: list of issues raised but not resolved
- values_and_beliefs: list of stated or implied values
- self_perception: how they see themselves (e.g., "failure", "survivor", "people-pleaser")

Be concise. Preserve clinical nuance. Do not diagnose."""

SYNTHESIS_PROMPT = """You are synthesizing a Transfer Crystal for Sovereign Sanctuary (Little Nate), an AI therapy platform. The member is switching from another AI chat platform. This crystal guides the first session and continuity of care.

Given the batch analyses from their prior conversation history, produce a single JSON object with exactly 9 sections:

{
  "core_identity_summary": "2-4 sentence distillation of who this person is, their life context, and presenting self",
  "relationship_map": "Key relationships (family, work, significant others) and their emotional weight",
  "active_therapeutic_themes": "Current themes actively being worked on",
  "historical_themes": "Past themes, resolved or dormant",
  "communication_profile": "How they communicate: style, defenses, strengths",
  "unresolved_work": "Threads left dangling, questions unanswered, goals not met",
  "strengths_and_resources": "Internal and external resources, coping patterns that help",
  "clinical_considerations": "Cautions, sensitivities, contraindications for the therapist",
  "first_session_guidance": "2-4 sentences: how to open, what to acknowledge, what to invite"
}

Write in warm, clinical, third-person. Preserve the person's voice. No diagnoses."""


class TransferCrystalBuilder:
    """
    Builds therapeutic summary crystals from imported AI chat exports.
    """

    BATCH_TOKEN_LIMIT = 30_000
    TOKENS_PER_CHAR = 0.25

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    # -------------------------------------------------------------------------
    # HOSTILE TRANSFER DEFENSES (Section 9a)
    # -------------------------------------------------------------------------

    @staticmethod
    def validate_zip_safety(raw_data: bytes) -> None:
        """Validate ZIP file for bombs, path traversal, and excessive entries."""
        if not raw_data or raw_data[:4] != b"PK\x03\x04":
            return  # Not a ZIP — skip validation

        try:
            with zipfile.ZipFile(io.BytesIO(raw_data), "r") as zf:
                entries = zf.infolist()

                # Entry count check
                if len(entries) > MAX_ZIP_ENTRIES:
                    raise ValueError(
                        f"ZIP has too many entries ({len(entries)}). Max: {MAX_ZIP_ENTRIES}"
                    )

                total_uncompressed = 0
                for info in entries:
                    # Path traversal check
                    if '..' in info.filename or info.filename.startswith('/') or '\\' in info.filename:
                        raise ValueError(
                            f"ZIP entry has suspicious path: {info.filename}"
                        )

                    # Per-entry size check
                    if info.file_size > MAX_ZIP_ENTRY_SIZE:
                        raise ValueError(
                            f"ZIP entry too large: {info.filename} "
                            f"({info.file_size} bytes, max {MAX_ZIP_ENTRY_SIZE})"
                        )

                    total_uncompressed += info.file_size

                # ZIP bomb check (total uncompressed)
                if total_uncompressed > MAX_ZIP_UNCOMPRESSED:
                    raise ValueError(
                        f"ZIP total uncompressed size too large: "
                        f"{total_uncompressed} bytes (max {MAX_ZIP_UNCOMPRESSED})"
                    )
        except zipfile.BadZipFile as e:
            raise ValueError(f"Invalid ZIP file: {e}") from e

    @staticmethod
    def _safe_json_loads(raw: bytes) -> Any:
        """Parse JSON with size limit. Raises ValueError if too large."""
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError(
                f"JSON data too large: {len(raw)} bytes (max {MAX_JSON_BYTES})"
            )
        return json.loads(raw.decode("utf-8", errors="replace"))

    @staticmethod
    def _check_json_depth(obj: Any, max_depth: int = MAX_JSON_DEPTH, current: int = 0) -> None:
        """Check JSON nesting depth to prevent stack overflow."""
        if current > max_depth:
            raise ValueError(f"JSON nesting exceeds {max_depth} levels")
        if isinstance(obj, dict):
            for v in obj.values():
                TransferCrystalBuilder._check_json_depth(v, max_depth, current + 1)
        elif isinstance(obj, list):
            for item in obj[:100]:  # Only check first 100 items to avoid O(n) on large arrays
                TransferCrystalBuilder._check_json_depth(item, max_depth, current + 1)

    @staticmethod
    def scan_conversation_text(text: str) -> tuple:
        """Scan text for import-specific + standard injection patterns. Returns (sanitized, patterns, risk)."""
        import re as _re
        from app.services.vault.content_sentinel_file import FileContentSentinel

        # Standard content sentinel scan
        result = FileContentSentinel.scan(text)
        patterns = list(result.patterns_found)
        sanitized = result.sanitized_text

        # Import-specific patterns
        for pattern_str, name in IMPORT_INJECTION_PATTERNS:
            pat = _re.compile(pattern_str, _re.IGNORECASE)
            if pat.search(sanitized):
                if name not in patterns:
                    patterns.append(name)
                sanitized = pat.sub("[import content removed]", sanitized)

        risk = "low"
        if any(p in ("embedded_role_override", "embedded_admin_role", "json_structure_escape") for p in patterns):
            risk = "critical"
        elif any(p in ("base64_payload",) for p in patterns):
            risk = "high"
        elif result.risk_level in ("critical", "high"):
            risk = result.risk_level
        elif patterns:
            risk = "medium"

        return sanitized, patterns, risk

    # -------------------------------------------------------------------------
    # MAIN BUILD PIPELINE
    # -------------------------------------------------------------------------

    async def build(
        self,
        member_id: str,
        source: str,
        raw_data: bytes,
        content_sentinel_scan: bool = True,
        tier: str = "STANDARD",
    ) -> dict:
        """
        Parse, scan, batch-analyze, synthesize, and store a transfer crystal.

        Args:
            member_id: Sanctuary member ID
            source: Platform key (chatgpt, claude, gemini, replika)
            raw_data: Raw file bytes (ZIP or JSON)
            content_sentinel_scan: Whether to run injection-pattern scan (default True)

        Returns:
            Crystal dict with id, crystal, stats, etc.
        """
        start_time = datetime.utcnow()
        stats: Dict[str, Any] = {
            "conversation_count": 0,
            "message_count": 0,
            "date_range_start": None,
            "date_range_end": None,
            "batch_count": 0,
            "errors": [],
        }

        # 1. Parse platform-specific format
        parser = getattr(self, f"parse_{source}", None)
        if not parser:
            raise ValueError(f"Unknown source: {source}")

        try:
            messages = parser(raw_data)
        except Exception as e:
            logger.exception("Parse failed for source=%s", source)
            stats["errors"].append(f"Parse error: {e}")
            raise ValueError(f"Failed to parse {source} export: {e}") from e

        if not messages:
            raise ValueError("No user messages found in export")

        # Conversation-shaped parsers (ChatGPT, Claude) return vault-importable threads.
        # Flat parsers (Gemini, Replika) are wrapped so full history still lands in vault.
        conversations = None
        if messages and isinstance(messages[0], dict) and "messages" in messages[0]:
            conversations = messages
            messages = []
            for conv in conversations:
                for m in conv.get("messages", []):
                    if m.get("role") == "user":
                        messages.append({
                            "text": m.get("text", ""),
                            "timestamp": m.get("timestamp"),
                            "_conv_title": conv.get("title", ""),
                            "_folder_name": conv.get("folder_name", ""),
                        })
            stats["conversation_count"] = len(conversations)
        else:
            conversations = self._flat_messages_to_conversations(messages, source)
            stats["conversation_count"] = len(conversations)

        stats["message_count"] = len(messages)
        if not messages and conversations:
            for conv in conversations:
                for m in conv.get("messages", []):
                    if m.get("role") == "user":
                        messages.append({
                            "text": m.get("text", ""),
                            "timestamp": m.get("timestamp"),
                            "_conv_title": conv.get("title", ""),
                        })
            stats["message_count"] = len(messages)

        # 2. Sort chronologically
        def _ts(m: dict) -> float:
            ts = m.get("timestamp") or m.get("created_at") or ""
            if isinstance(ts, (int, float)):
                return float(ts)
            if isinstance(ts, str):
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except (ValueError, OSError, TypeError):
                    return 0.0
            return 0.0

        messages.sort(key=_ts)

        # 3. Content sentinel scan
        if content_sentinel_scan:
            combined = "\n".join(
                (m.get("text") or m.get("content") or "")[:50000] for m in messages
            )
            result = FileContentSentinel.scan(combined)
            if result.injection_detected:
                logger.warning(
                    "Transfer crystal content sentinel flagged: %s (risk=%s)",
                    result.patterns_found,
                    result.risk_level,
                )
                stats["errors"].append(
                    f"Content sentinel: {result.patterns_found} (risk={result.risk_level})"
                )
                # Continue with partial data per spec (log and continue)

        # 4. Date range
        if messages:
            first_ts = _ts(messages[0])
            last_ts = _ts(messages[-1])
            if first_ts:
                stats["date_range_start"] = datetime.utcfromtimestamp(first_ts).isoformat()
            if last_ts:
                stats["date_range_end"] = datetime.utcfromtimestamp(last_ts).isoformat()

        # 5. Vault import FIRST — full history must persist even if Azure synthesis fails
        vault_import_stats = None
        if conversations:
            try:
                vault_import_stats = await self.import_to_vault(
                    member_id=member_id,
                    conversations=conversations,
                    tier=tier,
                    source_platform=source,
                )
            except Exception as e:
                logger.warning("Vault import failed: %s", e)
                stats["errors"].append(f"Vault import: {e}")

        # 6. Batch analysis + crystal (best-effort; vault capture is the hard guarantee)
        batches = self.create_batches(messages, self.BATCH_TOKEN_LIMIT) if messages else []
        stats["batch_count"] = len(batches)
        batch_analyses: List[dict] = []

        for i, batch in enumerate(batches):
            try:
                analysis = await self.analyze_batch(batch, i + 1, len(batches))
                if analysis:
                    batch_analyses.append(analysis)
            except Exception as e:
                logger.exception("Batch %d analysis failed", i + 1)
                stats["errors"].append(f"Batch {i + 1}: {e}")

        crystal: Optional[dict] = None
        if batch_analyses:
            crystal = await self.synthesize_crystal(member_id, batch_analyses, source)

        if not crystal:
            # Minimal continuity profile so chat can still inject import awareness
            crystal = self._stub_crystal(source, stats)
            stats["errors"].append("Azure synthesis unavailable; stored vault-backed stub crystal")

        # 7. Store crystal (full or stub)
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        stats["processing_time_seconds"] = elapsed
        try:
            await self.store_crystal(
                member_id=member_id,
                crystal=crystal,
                source=source,
                stats=stats,
            )
        except Exception as e:
            logger.warning("Crystal store failed (vault may still have history): %s", e)
            stats["errors"].append(f"Crystal store: {e}")

        _vault_ok = bool(
            vault_import_stats and (vault_import_stats.get("conversations_imported") or 0) > 0
        )
        if not _vault_ok and not crystal.get("id"):
            raise ValueError("Import failed: neither vault history nor crystal was saved")

        return {
            "id": crystal.get("id"),
            "crystal": crystal,
            "stats": stats,
            "vault_import": vault_import_stats,
        }

    @staticmethod
    def _flat_messages_to_conversations(
        messages: List[dict], source: str,
    ) -> List[dict]:
        """Wrap flat user-message lists (Gemini/Replika) into vault conversation shape."""
        conv_msgs: List[dict] = []
        for m in messages or []:
            if not isinstance(m, dict):
                continue
            if "messages" in m:
                continue
            text = (m.get("text") or m.get("content") or "").strip()
            if not text:
                continue
            conv_msgs.append({
                "role": m.get("role") or "user",
                "text": text[:MAX_MESSAGE_TEXT_CHARS],
                "timestamp": m.get("timestamp") or m.get("created_at"),
            })
        if not conv_msgs:
            return []
        return [{
            "title": f"{source.title()} import",
            "create_time": conv_msgs[0].get("timestamp") or 0,
            "messages": conv_msgs[:MAX_MESSAGES_PER_CONV],
            "folder_id": "",
            "folder_name": "",
        }]

    @staticmethod
    def _stub_crystal(source: str, stats: Dict[str, Any]) -> dict:
        """Vault-backed continuity profile when Azure batch/synthesis is unavailable."""
        n_msg = stats.get("message_count") or 0
        n_conv = stats.get("conversation_count") or 0
        return {
            "core_identity_summary": (
                f"Member imported prior AI history from {source} "
                f"({n_conv} conversations, {n_msg} user messages). "
                "Full threads are stored in Transfer History vault for recall."
            ),
            "relationship_map": "",
            "active_therapeutic_themes": "",
            "historical_themes": "",
            "communication_profile": "",
            "unresolved_work": "Explore topics from their imported history when they ask.",
            "strengths_and_resources": "",
            "clinical_considerations": "Imported content is pre-Sanctuary; verify with the member.",
            "first_session_guidance": (
                "Acknowledge their imported history is available. Invite them to name "
                "what matters most from that prior work."
            ),
            "_stub": True,
        }

    # -------------------------------------------------------------------------
    # SOURCE DETECTION
    # -------------------------------------------------------------------------

    def detect_source(self, filename: str, raw_data: bytes) -> str:
        """
        Auto-detect platform from file content.

        Returns:
            Source key: chatgpt, claude, gemini, replika, or "unknown"
        """
        filename_lower = (filename or "").lower()

        # ZIP with conversations.json -> ChatGPT
        if filename_lower.endswith(".zip") or raw_data[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(raw_data), "r") as zf:
                    names = zf.namelist()
                    if "conversations.json" in names:
                        return "chatgpt"
                    if any("conversations" in n for n in names):
                        return "chatgpt"
            except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
                logger.debug("Source detection (zip) failed: %s", e)

        # JSON
        try:
            text = raw_data.decode("utf-8", errors="replace")
            data = json.loads(text)

            if isinstance(data, dict):
                # ChatGPT conversations.json (inside zip, but also standalone)
                if "conversations" in data or "items" in data:
                    items = data.get("conversations") or data.get("items") or []
                    if items and isinstance(items, list):
                        first = items[0] if items else {}
                        if isinstance(first, dict):
                            if "mapping" in first or "current_node" in first:
                                return "chatgpt"
                            if "id" in first and "create_time" in first:
                                return "chatgpt"

                # Claude export
                if "chats" in data:
                    return "claude"
                if "meta" in data and "chats" in data:
                    return "claude"

                # Replika
                if "conversations" in data or "messages" in data:
                    conv = data.get("conversations") or data.get("messages") or []
                    if conv:
                        return "replika"

                # Google Takeout Gemini
                if "Gemini" in str(data) or "gemini" in filename_lower:
                    return "gemini"

            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    first = data[0]
                    if "mapping" in first or "conversation_id" in first:
                        return "chatgpt"
                    if "type" in first and first.get("type") in ("prompt", "response"):
                        return "claude"
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        # CSV -> Replika sometimes
        if filename_lower.endswith(".csv"):
            return "replika"

        return "unknown"

    # -------------------------------------------------------------------------
    # PARSERS
    # -------------------------------------------------------------------------

    def parse_chatgpt(self, raw_data: bytes) -> List[dict]:
        """
        Parse ChatGPT ZIP/JSON export. Returns list of conversation dicts, each containing:
        - conversation_id, title, folder_id, create_time, update_time
        - messages: list of {role, text, timestamp}
        - custom_instructions, attachment_refs, message_count
        """
        # ZIP safety checks (Section 9a)
        self.validate_zip_safety(raw_data)

        conversations: List[dict] = []
        folder_names: Dict[str, str] = {}  # folder_id -> folder_name

        def _traverse_thread(mapping: dict, current_node: str) -> List[dict]:
            """Walk the tree backwards from current_node via parent links, then reverse."""
            visited = set()
            thread: List[dict] = []
            node_id = current_node

            while node_id and node_id not in visited and len(thread) < MAX_MESSAGES_PER_CONV:
                visited.add(node_id)
                node = mapping.get(node_id)
                if not node or not isinstance(node, dict):
                    break

                msg = node.get("message")
                if msg and isinstance(msg, dict):
                    author = msg.get("author") or {}
                    role = author.get("role") if isinstance(author, dict) else None
                    if role in ("user", "assistant"):
                        content = msg.get("content") or {}
                        parts = content.get("parts") if isinstance(content, dict) else content
                        if not isinstance(parts, list):
                            parts = [parts] if parts else []

                        text_parts = []
                        attachment_refs = []
                        for p in parts:
                            if isinstance(p, str):
                                text_parts.append(p[:MAX_MESSAGE_TEXT_CHARS])
                            elif isinstance(p, dict):
                                if "text" in p:
                                    text_parts.append(str(p["text"])[:MAX_MESSAGE_TEXT_CHARS])
                                elif p.get("content_type") in ("image_asset_pointer", "image"):
                                    ref = p.get("asset_pointer") or p.get("name") or "image"
                                    attachment_refs.append(str(ref)[:255])
                                elif "name" in p:
                                    attachment_refs.append(str(p["name"])[:255])

                        text = "\n".join(text_parts).strip()
                        if text:
                            ts = msg.get("create_time") or 0
                            entry = {"role": role, "text": text, "timestamp": ts}
                            if attachment_refs:
                                entry["attachments"] = attachment_refs
                            thread.append(entry)

                    # Capture custom instructions from system messages
                    elif role == "system":
                        meta = msg.get("metadata") or {}
                        if meta.get("is_user_system_message"):
                            content = msg.get("content") or {}
                            parts = content.get("parts") if isinstance(content, dict) else content
                            if isinstance(parts, list):
                                text = "\n".join(str(p) for p in parts if isinstance(p, str))
                                if text.strip():
                                    thread.append({
                                        "role": "custom_instructions",
                                        "text": text[:MAX_MESSAGE_TEXT_CHARS],
                                        "timestamp": msg.get("create_time") or 0,
                                    })

                node_id = node.get("parent")

            thread.reverse()
            return thread

        def _extract_conversation(conv: dict) -> None:
            if not isinstance(conv, dict):
                return
            mapping = conv.get("mapping") or {}
            current_node = conv.get("current_node")

            # Get messages via tree traversal (preferred) or flat iteration (fallback)
            if current_node and current_node in mapping:
                messages = _traverse_thread(mapping, current_node)
            else:
                # Fallback: iterate all nodes, sort by timestamp
                messages = []
                for node_id, node in mapping.items():
                    if not isinstance(node, dict):
                        continue
                    msg = node.get("message")
                    if not msg or not isinstance(msg, dict):
                        continue
                    author = msg.get("author") or {}
                    role = author.get("role") if isinstance(author, dict) else None
                    if role not in ("user", "assistant"):
                        continue
                    content = msg.get("content") or {}
                    parts = content.get("parts") if isinstance(content, dict) else content
                    if not isinstance(parts, list):
                        parts = [parts] if parts else []
                    text_parts = [
                        (str(p)[:MAX_MESSAGE_TEXT_CHARS] if isinstance(p, str) else
                         str(p.get("text", ""))[:MAX_MESSAGE_TEXT_CHARS] if isinstance(p, dict) and "text" in p else "")
                        for p in parts
                    ]
                    text = "\n".join(t for t in text_parts if t).strip()
                    if text:
                        messages.append({
                            "role": role,
                            "text": text,
                            "timestamp": msg.get("create_time") or 0,
                        })
                messages.sort(key=lambda m: m.get("timestamp") or 0)

            if not messages:
                return

            # Extract attachment refs from all messages
            all_attachments = []
            for m in messages:
                all_attachments.extend(m.pop("attachments", []))

            # Extract custom instructions
            custom_instructions = ""
            for m in messages:
                if m.get("role") == "custom_instructions":
                    custom_instructions = m.get("text", "")
            messages = [m for m in messages if m.get("role") in ("user", "assistant")]

            conv_entry = {
                "conversation_id": str(conv.get("id") or ""),
                "title": str(conv.get("title") or "Untitled")[:255],
                "folder_id": str(conv.get("folder_id") or ""),
                "folder_name": "",  # resolved later from folder_names
                "create_time": conv.get("create_time") or 0,
                "update_time": conv.get("update_time") or 0,
                "messages": messages,
                "custom_instructions": custom_instructions[:MAX_MESSAGE_TEXT_CHARS],
                "attachment_refs": all_attachments[:100],
                "message_count": len(messages),
            }

            # Resolve folder name
            fid = conv_entry["folder_id"]
            if fid and fid in folder_names:
                conv_entry["folder_name"] = folder_names[fid]

            conversations.append(conv_entry)

        try:
            if raw_data[:4] == b"PK\x03\x04":
                with zipfile.ZipFile(io.BytesIO(raw_data), "r") as zf:
                    # Look for folders.json first
                    for name in zf.namelist():
                        if "folder" in name.lower() and name.endswith(".json"):
                            try:
                                fdata = self._safe_json_loads(zf.read(name))
                                if isinstance(fdata, list):
                                    for f in fdata:
                                        if isinstance(f, dict) and f.get("id") and f.get("name"):
                                            folder_names[str(f["id"])] = str(f["name"])[:64]
                                elif isinstance(fdata, dict):
                                    for fid, fobj in fdata.items():
                                        if isinstance(fobj, dict) and fobj.get("name"):
                                            folder_names[str(fid)] = str(fobj["name"])[:64]
                            except Exception as e:
                                logger.debug("Folder metadata parse: %s", e)

                    # Parse conversations
                    for name in zf.namelist():
                        if "conversations" in name.lower() and name.endswith(".json"):
                            try:
                                data = self._safe_json_loads(zf.read(name))
                                self._check_json_depth(data)
                                if isinstance(data, list):
                                    for c in data[:MAX_CONVERSATIONS]:
                                        _extract_conversation(c)
                                elif isinstance(data, dict):
                                    items = data.get("conversations") or data.get("items") or []
                                    for c in items[:MAX_CONVERSATIONS]:
                                        _extract_conversation(c)
                            except ValueError:
                                raise  # Re-raise safety violations
                            except Exception as e:
                                logger.warning("ChatGPT zip member %s: %s", name, e)
            else:
                # Direct JSON (not in ZIP)
                data = self._safe_json_loads(raw_data)
                self._check_json_depth(data)
                if isinstance(data, list):
                    for c in data[:MAX_CONVERSATIONS]:
                        _extract_conversation(c)
                else:
                    items = data.get("conversations") or data.get("items") or []
                    for c in items[:MAX_CONVERSATIONS]:
                        _extract_conversation(c)
        except ValueError:
            raise  # Re-raise safety violations
        except Exception as e:
            logger.exception("ChatGPT parse error")
            raise ValueError(f"ChatGPT parse failed: {e}") from e

        # Log if conversations were capped
        if len(conversations) >= MAX_CONVERSATIONS:
            logger.warning("ChatGPT import capped at %d conversations", MAX_CONVERSATIONS)

        return conversations

    @staticmethod
    def _extract_claude_text(item: dict) -> str:
        """Extract plain text from a Claude export message object."""
        if not isinstance(item, dict):
            return ""

        for key in ("text", "content"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:MAX_MESSAGE_TEXT_CHARS]
            if isinstance(val, list):
                parts = []
                for m in val:
                    if isinstance(m, dict):
                        if m.get("type") == "p" and m.get("data"):
                            parts.append(str(m["data"]))
                        elif m.get("text"):
                            parts.append(str(m["text"]))
                    elif isinstance(m, str):
                        parts.append(m)
                joined = "\n".join(p for p in parts if p).strip()
                if joined:
                    return joined[:MAX_MESSAGE_TEXT_CHARS]

        msg_data = item.get("message")
        if isinstance(msg_data, dict):
            return TransferCrystalBuilder._extract_claude_text(msg_data)
        if isinstance(msg_data, list):
            return TransferCrystalBuilder._extract_claude_text({"content": msg_data})
        if isinstance(msg_data, str) and msg_data.strip():
            return msg_data.strip()[:MAX_MESSAGE_TEXT_CHARS]
        return ""

    @staticmethod
    def _claude_item_role(item: dict) -> Optional[str]:
        """Map Claude export fields to user/assistant roles."""
        sender = str(item.get("sender") or item.get("role") or "").lower()
        if sender in ("human", "user"):
            return "user"
        if sender in ("assistant", "claude"):
            return "assistant"

        msg_type = str(item.get("type") or "").lower()
        if msg_type == "prompt":
            return "user"
        if msg_type in ("completion", "assistant", "response"):
            return "assistant"
        return None

    def parse_claude(self, raw_data: bytes) -> List[dict]:
        """Parse Claude JSON export into conversation objects (user + assistant turns)."""
        conversations: List[dict] = []

        try:
            data = json.loads(raw_data.decode("utf-8", errors="replace"))
            chats = data.get("chats") or data.get("conversations") or []
            if isinstance(data, list):
                chats = data

            for chat in chats[:MAX_CONVERSATIONS]:
                if not isinstance(chat, dict):
                    continue

                raw_items = (
                    chat.get("chat_messages")
                    or chat.get("messages")
                    or chat.get("items")
                    or chat.get("chats")
                    or []
                )
                if not raw_items and chat.get("type") == "prompt":
                    raw_items = [chat]

                messages: List[dict] = []
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    role = self._claude_item_role(item)
                    if not role:
                        continue
                    text = self._extract_claude_text(item)
                    if not text:
                        continue
                    ts = (
                        item.get("created_at")
                        or item.get("create_time")
                        or item.get("timestamp")
                        or chat.get("created_at")
                        or chat.get("create_time")
                    )
                    messages.append({
                        "role": role,
                        "text": text,
                        "timestamp": ts,
                    })

                if not messages:
                    continue
                if not any(m.get("role") == "user" for m in messages):
                    continue

                messages.sort(key=lambda m: m.get("timestamp") or 0)
                title = (
                    chat.get("name")
                    or chat.get("title")
                    or (messages[0].get("text", "")[:80] or "Untitled")
                )
                create_time = chat.get("created_at") or chat.get("create_time")
                if isinstance(create_time, str):
                    try:
                        create_time = datetime.fromisoformat(
                            create_time.replace("Z", "+00:00")
                        ).timestamp()
                    except (ValueError, OSError, TypeError):
                        create_time = messages[0].get("timestamp") or 0
                elif not create_time:
                    create_time = messages[0].get("timestamp") or 0

                conversations.append({
                    "title": str(title)[:255],
                    "create_time": create_time,
                    "messages": messages[:MAX_MESSAGES_PER_CONV],
                    "folder_id": "",
                    "folder_name": "",
                })

        except Exception as e:
            logger.exception("Claude parse error")
            raise ValueError(f"Claude parse failed: {e}") from e

        return conversations

    def parse_gemini(self, raw_data: bytes) -> List[dict]:
        """Parse Google Takeout Gemini export."""
        messages: List[dict] = []

        try:
            text = raw_data.decode("utf-8", errors="replace")
            data = json.loads(text) if text.strip().startswith("{") else None
            if not data:
                # Try line-by-line JSON
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            role = obj.get("role") or obj.get("actor") or ""
                            content = obj.get("text") or obj.get("content") or obj.get("parts", [])
                            if isinstance(content, list):
                                content = " ".join(
                                    p.get("text", p) if isinstance(p, dict) else str(p)
                                    for p in content
                                )
                            if str(role).lower() in ("user", "human", "0"):
                                messages.append({
                                    "text": str(content),
                                    "timestamp": obj.get("timestamp") or obj.get("created_at"),
                                })
                    except json.JSONDecodeError:
                        continue
                return messages

            # Nested Takeout structure
            def _walk(obj: Any, path: str = "") -> None:
                if isinstance(obj, dict):
                    if "text" in obj and ("user" in path.lower() or "human" in str(obj.get("role", "")).lower()):
                        messages.append({
                            "text": obj.get("text", ""),
                            "timestamp": obj.get("timestamp") or obj.get("created_at"),
                        })
                    for k, v in obj.items():
                        _walk(v, f"{path}.{k}")
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        _walk(v, f"{path}[{i}]")

            _walk(data)
        except Exception as e:
            logger.exception("Gemini parse error")
            raise ValueError(f"Gemini parse failed: {e}") from e

        return messages

    def parse_replika(self, raw_data: bytes) -> List[dict]:
        """Parse Replika JSON or CSV export."""
        messages: List[dict] = []

        try:
            text = raw_data.decode("utf-8", errors="replace")

            # CSV
            if "\t" in text[:500] or "," in text[:500]:
                lines = text.strip().splitlines()
                if lines:
                    header = lines[0].lower()
                    sep = "\t" if "\t" in lines[0] else ","
                    cols = [c.strip().lower() for c in lines[0].split(sep)]
                    idx_text = idx_ts = -1
                    for i, c in enumerate(cols):
                        if "text" in c or "message" in c or "content" in c:
                            idx_text = i
                        if "timestamp" in c or "date" in c or "time" in c:
                            idx_ts = i
                    for line in lines[1:]:
                        parts = line.split(sep)
                        if idx_text >= 0 and idx_text < len(parts):
                            msg_text = parts[idx_text].strip()
                            if msg_text:
                                ts = parts[idx_ts] if idx_ts >= 0 and idx_ts < len(parts) else None
                                messages.append({"text": msg_text, "timestamp": ts})
                return messages

            # JSON
            data = json.loads(text)
            items = data.get("conversations") or data.get("messages") or data.get("chats") or []
            if isinstance(data, list):
                items = data

            for item in items:
                if not isinstance(item, dict):
                    continue
                msg = item.get("message") or item.get("text") or item.get("content") or ""
                role = item.get("role") or item.get("sender") or ""
                if str(role).lower() in ("user", "human", "you") or not role:
                    if msg:
                        messages.append({
                            "text": str(msg),
                            "timestamp": item.get("timestamp") or item.get("created_at"),
                        })
        except Exception as e:
            logger.exception("Replika parse error")
            raise ValueError(f"Replika parse failed: {e}") from e

        return messages

    # -------------------------------------------------------------------------
    # BATCHING & ANALYSIS
    # -------------------------------------------------------------------------

    def create_batches(
        self,
        messages: List[dict],
        token_limit: Optional[int] = None,
    ) -> List[List[dict]]:
        """Group messages into batches that fit within token_limit."""
        limit = token_limit or self.BATCH_TOKEN_LIMIT
        batches: List[List[dict]] = []
        current: List[dict] = []
        current_tokens = 0

        for m in messages:
            text = m.get("text") or m.get("content") or ""
            tokens = int(len(text) * self.TOKENS_PER_CHAR)
            if current_tokens + tokens > limit and current:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(m)
            current_tokens += tokens

        if current:
            batches.append(current)

        return batches

    async def analyze_batch(
        self,
        batch: List[dict],
        batch_num: int,
        total_batches: int,
    ) -> Optional[dict]:
        """
        Send batch to GPT-4o for therapeutic analysis.
        Returns parsed JSON or None on failure.
        """
        api_key = os.getenv("AZURE_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

        if not api_key or not endpoint:
            logger.warning("Azure OpenAI not configured; skipping batch analysis")
            return None

        # Build batch text with conversation context when available
        text_parts = []
        for m in batch:
            header_parts = []
            ts = m.get('timestamp', '')
            if ts:
                header_parts.append(f"[{ts}]")
            conv_title = m.get('_conv_title', '')
            folder_name = m.get('_folder_name', '')
            if conv_title:
                header_parts.append(f"(Conversation: {conv_title})")
            if folder_name:
                header_parts.append(f"(Folder: {folder_name})")
            header = " ".join(header_parts)
            text = m.get('text', '') or m.get('content', '')
            text_parts.append(f"{header}\n{text}" if header else text)
        text_content = "\n\n---\n\n".join(text_parts)

        endpoint_base = endpoint.replace("https://", "").replace("wss://", "").rstrip("/")
        if not endpoint_base.startswith("http"):
            endpoint_base = f"https://{endpoint_base}"
        url = f"{endpoint_base}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"

        payload = {
            "messages": [
                {"role": "system", "content": BATCH_ANALYSIS_PROMPT},
                {"role": "user", "content": f"Batch {batch_num}/{total_batches}:\n\n{text_content}"},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.error("Azure batch analysis %s: %s", resp.status_code, resp.text[:500])
                    return None
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    return json.loads(content)
        except Exception as e:
            logger.exception("Batch analysis failed: %s", e)

        return None

    async def synthesize_crystal(
        self,
        member_id: str,
        batch_analyses: List[dict],
        source: str,
    ) -> dict:
        """
        Send all batch analyses to GPT-4o for synthesis into 9-section crystal.
        """
        api_key = os.getenv("AZURE_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

        if not api_key or not endpoint:
            logger.warning("Azure OpenAI not configured; returning placeholder crystal")
            return {
                "core_identity_summary": "Transfer crystal synthesis skipped (Azure not configured).",
                "relationship_map": "",
                "active_therapeutic_themes": "",
                "historical_themes": "",
                "communication_profile": "",
                "unresolved_work": "",
                "strengths_and_resources": "",
                "clinical_considerations": "",
                "first_session_guidance": "Acknowledge the member's history and invite them to share what matters most.",
            }

        combined = json.dumps(batch_analyses, indent=2)
        endpoint_base = endpoint.replace("https://", "").replace("wss://", "").rstrip("/")
        if not endpoint_base.startswith("http"):
            endpoint_base = f"https://{endpoint_base}"
        url = f"{endpoint_base}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"

        payload = {
            "messages": [
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": f"Batch analyses from {source}:\n\n{combined}"},
            ],
            "temperature": 0.4,
            "max_tokens": 3000,
            "response_format": {"type": "json_object"},
        }

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.error("Azure synthesis %s: %s", resp.status_code, resp.text[:500])
                    return {}
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content")
                if content:
                    return json.loads(content)
        except Exception as e:
            logger.exception("Crystal synthesis failed: %s", e)

        return {}

    # -------------------------------------------------------------------------
    # STORAGE
    # -------------------------------------------------------------------------

    async def store_crystal(
        self,
        member_id: str,
        crystal: dict,
        source: str,
        stats: dict,
    ) -> None:
        """INSERT into transfer_crystals table."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO transfer_crystals (
                    member_id, source_platform, conversation_count, message_count,
                    date_range_start, date_range_end, crystal, version,
                    processing_time_seconds, token_cost
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                member_id,
                source,
                stats.get("conversation_count", 0),
                stats.get("message_count", 0),
                stats.get("date_range_start"),
                stats.get("date_range_end"),
                json.dumps(crystal),
                "1.0",
                stats.get("processing_time_seconds"),
                stats.get("token_cost", 0.0),
            )
            if row:
                crystal["id"] = str(row["id"])

    # -------------------------------------------------------------------------
    # VAULT IMPORT PIPELINE
    # -------------------------------------------------------------------------

    async def import_to_vault(
        self,
        member_id: str,
        conversations: List[dict],
        tier: str = "STANDARD",
        source_platform: str = "chatgpt",
    ) -> dict:
        """
        Import parsed conversations into the Vault as browseable items.

        Returns:
            dict with keys: conversations_imported, folders_created,
            conversations_quarantined, transfer_folder_id
        """
        from app.services.vault.vault_operations import VaultOperations

        vault_ops = VaultOperations(self.db_pool)
        stats = {
            "conversations_imported": 0,
            "conversations_quarantined": 0,
            "conversations_skipped_duplicate": 0,
            "folders_created": 0,
            "transfer_folder_id": None,
        }

        # Check vault item count cap
        existing_count = await self.db_pool.fetchval(
            "SELECT COUNT(*) FROM vault_items WHERE member_id = $1",
            member_id,
        ) or 0
        if existing_count >= MAX_VAULT_ITEMS_PER_USER:
            raise ValueError(
                f"Vault item limit reached ({MAX_VAULT_ITEMS_PER_USER}). "
                "Delete some items before importing."
            )
        remaining_slots = MAX_VAULT_ITEMS_PER_USER - existing_count

        # Ensure default folders exist
        folders = await vault_ops.get_folder_tree(member_id)
        if not folders:
            await vault_ops.create_default_folders(member_id, tier)
            folders = await vault_ops.get_folder_tree(member_id)

        # Find or create "Transfer History" folder under "Uploads"
        uploads_root = None
        transfer_history = None
        for f in folders:
            if f["name"] == "Uploads" and f.get("parent_id") is None:
                uploads_root = f["id"]
            if f["name"] == "Transfer History":
                transfer_history = f["id"]

        if not uploads_root:
            # Create Uploads folder
            result = await vault_ops.create_folder(
                member_id, "Uploads", parent_id=None, icon="📤", tier=tier
            )
            uploads_root = result["id"]

        if not transfer_history:
            result = await vault_ops.create_folder(
                member_id, "Transfer History", parent_id=uploads_root, icon="🔄", tier=tier
            )
            transfer_history = result["id"]
            stats["folders_created"] += 1

        stats["transfer_folder_id"] = str(transfer_history)

        # Create sub-folders for each ChatGPT folder
        chatgpt_folder_map: Dict[str, str] = {}  # chatgpt_folder_id -> vault_folder_id
        folder_names_seen: set = set()

        for conv in conversations:
            fid = conv.get("folder_id") or ""
            fname = conv.get("folder_name") or ""
            if fid and fname and fid not in chatgpt_folder_map and fname not in folder_names_seen:
                try:
                    safe_name = fname[:60]
                    result = await vault_ops.create_folder(
                        member_id, safe_name, parent_id=transfer_history, icon="💬", tier=tier
                    )
                    chatgpt_folder_map[fid] = result["id"]
                    folder_names_seen.add(fname)
                    stats["folders_created"] += 1
                except (ValueError, Exception) as e:
                    logger.debug("Folder creation skipped: %s", e)

        # Import each conversation as a vault item
        imported = 0
        for conv in conversations:
            if imported >= remaining_slots:
                logger.warning("Vault item cap reached during import")
                break

            # Determine target folder
            fid = conv.get("folder_id") or ""
            target_folder = chatgpt_folder_map.get(fid, transfer_history)

            # Build conversation JSON for storage
            conv_json = json.dumps({
                "source": source_platform,
                "title": conv.get("title", "Untitled"),
                "create_time": conv.get("create_time"),
                "messages": conv.get("messages", []),
                "custom_instructions": conv.get("custom_instructions", ""),
                "attachment_refs": conv.get("attachment_refs", []),
            }, default=str)

            # Deduplication by content hash
            import hashlib
            content_hash = hashlib.sha256(conv_json.encode()).hexdigest()

            existing = await self.db_pool.fetchval(
                "SELECT 1 FROM vault_items WHERE member_id = $1 AND content_hash = $2",
                member_id, content_hash,
            )
            if existing:
                stats["conversations_skipped_duplicate"] += 1
                continue

            # Per-conversation Content Sentinel scan (Section 9c)
            user_text = "\n".join(
                m.get("text", "") for m in conv.get("messages", [])
                if m.get("role") == "user"
            )
            _, patterns, risk = self.scan_conversation_text(user_text)
            is_quarantined = risk in ("critical", "high")

            if is_quarantined:
                stats["conversations_quarantined"] += 1

            # Build display name and preview
            title = conv.get("title") or "Untitled"
            create_time = conv.get("create_time")
            if create_time and isinstance(create_time, (int, float)) and create_time > 0:
                try:
                    date_str = datetime.utcfromtimestamp(create_time).strftime("%Y-%m-%d")
                    display_name = f"{title} ({date_str})"
                except (OSError, ValueError):
                    display_name = title
            else:
                display_name = title

            # Truncate for display
            display_name = display_name[:250]

            # Build full conversation text for chat context + FTS  # QUANTUM-CRYSTAL-ARCH
            _conv_parts = []
            for m in conv.get("messages", []):
                _role = m.get("role", "unknown")
                _txt = (m.get("text") or "").strip()
                if _txt:
                    _label = "User" if _role == "user" else "AI"
                    _conv_parts.append(f"{_label}: {_txt}")
            preview = "\n\n".join(_conv_parts)[:50000]

            # Themes
            themes = ["imported", source_platform]
            folder_name = conv.get("folder_name")
            if folder_name:
                themes.append(folder_name)
            if is_quarantined:
                themes.append("quarantined")
            if patterns:
                themes.append(f"sentinel:{','.join(patterns[:3])}")

            # Store
            try:
                await vault_ops.add_item(
                    member_id=member_id,
                    folder_id=target_folder,
                    content_type="transfer_conversation",
                    display_name=display_name,
                    blob_path=None,  # QUANTUM-CRYSTAL-ARCH: full text in extracted_text_preview
                    size_bytes=len(conv_json.encode()),
                    mime_type="application/json",
                    extracted_text_preview=preview,
                    themes=themes,
                    content_hash=content_hash,
                )
                imported += 1
                stats["conversations_imported"] += 1
            except Exception as e:
                logger.warning("Failed to import conversation '%s': %s", title, e)

        return stats
