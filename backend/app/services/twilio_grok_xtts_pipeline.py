"""
Twilio Media Stream ↔ xAI Grok Realtime (text reasoning) ↔ Hetzner XTTS (Nathan voice).

Degradation ladder (Phase 1):
  1. XTTS down → Edge TTS (free Microsoft, generic voice)
  2. Grok down → session stays open but silent (caller hears nothing from Nate;
     TODO Phase 2: Azure OpenAI Chat fallback for text generation)
  3. Both down → Polly already spoke the greeting; session ends on Twilio stop

Session lifecycle:
  - Tracks call start time + call_sid
  - Releases Redis voice slot on cleanup
  - Logs voice minutes to voice_call_usage table

Env:
  AZURE_API_KEY            — required for Azure Foundry Grok Realtime
  AZURE_OPENAI_ENDPOINT    — Azure Foundry endpoint
  AZURE_OPENAI_DEPLOYMENT  — Grok model deployment (default gpt-realtime)
  TWILIO_VOICE_PIPELINE    — set to azure_realtime or grok_xtts

QUANTUM-CRYSTAL-ARCH — Sovereign Standard clinical RED gate.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.twilio_voice_codec import (
    strip_wav_header,
    twilio_mulaw_to_pcm16,
    xtts_pcm_to_twilio_mulaw,
)

try:
    from app.websocket.crystal_recall_bridge import (
        recall_crystals_for_context as _crystal_recall,
        crystallize_from_conversation as _crystal_forge,
    )
except ImportError:
    _crystal_recall = None
    _crystal_forge = None

try:
    from app.services.backchannel_engine import BackchannelEngine, MultiSignalTurnDetector
except ImportError:
    BackchannelEngine = None  # type: ignore[assignment,misc]
    MultiSignalTurnDetector = None  # type: ignore[assignment,misc]

try:
    from app.services.neural_mirror import NeuralMirrorSession
except ImportError:
    NeuralMirrorSession = None  # type: ignore[assignment,misc]

try:
    from app.services.search_proxy import SecureSearchProxy
except ImportError:
    SecureSearchProxy = None  # type: ignore[assignment,misc]

# SOVEREIGN-VOICE — identity / emotion pace / avatar sync (flag-gated)
try:
    from app.services.voice_call_sync import attach_voice_sync, CLARITY_LANGUAGE_PROMPT_ADDON
except ImportError:
    CLARITY_LANGUAGE_PROMPT_ADDON = (  # SOVEREIGN-VOICE
        "\nCLINICAL CLARITY: If speech is too fast/unclear, kindly ask once to slow down "
        "so you can hear them; name what pace helps. Mirror their language.\n"
    )

    async def attach_voice_sync(ctx, call_sid, username, instructions):  # type: ignore[misc]
        return None, (instructions or "") + CLARITY_LANGUAGE_PROMPT_ADDON

logger = logging.getLogger("nate.twilio_grok_xtts")

XTTS_URL = os.getenv("XTTS_URL", "http://37.27.244.80:8100/synthesize").strip().rstrip("/")
# SOVEREIGN-VOICE: Azure Foundry Grok Realtime WSS — never xAI direct
_AZ_EP = os.getenv("AZURE_OPENAI_ENDPOINT", "").replace("https://", "").replace("wss://", "").replace("/", "")
_AZ_DEPLOY = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-realtime")
_AZ_REALTIME_URL = f"wss://{_AZ_EP}/openai/realtime?api-version=2024-10-01-preview&deployment={_AZ_DEPLOY}" if _AZ_EP else ""

_TWILIO_MULAW_CHUNK = 160

_xtts_consecutive_failures = 0
_XTTS_FAIL_THRESHOLD = 3

# SOVEREIGN-VOICE — GA hardening (2026-06-09): detection-only Sensitive Bridge
# sweep on finalized voice utterances. Flag-gated, default OFF; fire-and-forget.
_SB_VOICE_SWEEP = os.getenv("SENSITIVE_BRIDGE_VOICE_SWEEP", "false").lower() == "true"

_FILLER_TIMEOUT_S = 1.5
_FILLER_PHRASES = [
    "Mmhmm.",
    "I hear you.",
    "Yeah.",
    "Let me think about that.",
    "Right.",
]
_filler_cache: Dict[str, bytes] = {}
_filler_idx = 0


def _default_phone_instructions(username: str, db_pool=None, user_id=None) -> str:
    who = username or "the caller"

    ANTI_CONFABULATION = (
        "\n\nABSOLUTE RULES — NEVER VIOLATE:\n"
        "- NEVER fabricate names of people in the user's life\n"
        "- NEVER invent physical descriptions of anyone\n"
        "- NEVER invent events that supposedly happened\n"
        "- NEVER say 'I remember you mentioned...' unless the information "
        "is explicitly provided in your context\n"
        "- If uncertain whether something was discussed, ASK: "
        "'I want to make sure I have this right — did you mention...?'\n"
        "- If the user mentions someone you have no record of, say "
        "'Tell me about them' — do NOT guess\n"
        "- It is ALWAYS better to ask than to guess\n"
    )

    return (
        f"You are Little Nate, a warm, concise therapeutic coach "
        f"on a live phone call with {who}. "
        f"You are on a live phone call. Keep every response to 2-4 sentences maximum. "
        f"Speak naturally and conversationally. Do not monologue. Pause and let the client react."
        f"{ANTI_CONFABULATION}"
        f"\nIf you do not have specific information about {who}'s life, "
        f"ask open questions rather than assuming or inventing details.\n\n"
        "INTERNET SEARCH CAPABILITY:\n"
        "You CAN search the internet when the caller asks. When they ask you to look something up, "
        "search for something, or ask a factual question you're unsure about, just say something like "
        "'Let me look that up for you' — the system will automatically search and provide you results. "
        "You will receive the search results as a follow-up message. Summarize them conversationally. "
        "Never say you cannot search the internet.\n"
    )


async def _build_grounded_voice_prompt(username: str, db_pool):
    """Build a system prompt grounded with crystal context and conversation history.

    QUANTUM-CRYSTAL-ARCH: returns (prompt, crystal_scopes) for Phase 5b light audit.
    """
    who = username or "friend"

    crystal_context = "No prior history with this user."
    recent_summary = "First conversation with this user."
    crystal_scopes: list = []

    if db_pool and username:
        if _crystal_recall:
            try:
                ctx = await _crystal_recall(db_pool, username, max_results=8, source="voice_call")
                if ctx:
                    crystal_context = ctx
                    crystal_scopes = list(getattr(ctx, "crystal_scopes", None) or [])[:50]
                    print(f"[VOICE-MEMORY] crystal recall returned {len(ctx)} chars for {username}")
                else:
                    print(f"[VOICE-MEMORY] no crystals found for {username}")
            except Exception as e:
                logger.warning("Voice prompt: crystal recall failed: %s", e)
        # QUANTUM-CRYSTAL-ARCH — Tier 2: PGSD briefing (ACCESS); no LIVE_CONTEXT
        try:
            from app.services.pgsd_briefing import append_field_briefing as _pgsd_voice
            _aug = await _pgsd_voice(
                db_pool, username,
                "" if crystal_context == "No prior history with this user." else crystal_context,
            )
            if _aug and _aug != crystal_context:
                crystal_context = _aug
        except Exception:
            pass

        try:
            async with db_pool.acquire() as conn:
                recent_rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at, session_id FROM conversation_history "
                    "WHERE user_id = $1 AND created_at > NOW() - INTERVAL '7 days' "
                    "AND LENGTH(user_text) > 15 "
                    "ORDER BY created_at DESC LIMIT 500",
                    username,
                )
                print(f"[VOICE-MEMORY] conversation_history query for '{username}' returned {len(recent_rows)} rows")
                if recent_rows:
                    summaries = []
                    for r in reversed(recent_rows):
                        u = r["user_text"] or ""
                        a = r["ai_text"] or ""
                        ts = r["created_at"].strftime("%b %d %I:%M%p") if r["created_at"] else ""
                        if u and len(u) > 15:
                            summaries.append(f"[{ts}] {who}: {u[:200]}")
                        if a and len(a) > 15:
                            summaries.append(f"[{ts}] Nate: {a[:200]}")
                    if summaries:
                        recent_summary = "\n".join(summaries[-200:])
                        print(f"[VOICE-MEMORY] built {len(summaries)} summary lines for prompt")
                    else:
                        print("[VOICE-MEMORY] rows found but all filtered out (too short)")
                else:
                    print(f"[VOICE-MEMORY] no conversation_history rows for '{username}'")
        except Exception as e:
            logger.warning("Voice prompt: history load failed: %s", e)

    has_history = recent_summary != "First conversation with this user."
    has_crystals = crystal_context != "No prior history with this user."

    memory_block = ""
    if has_history or has_crystals:
        memory_block = (
            f"=== PRIOR SESSION MEMORY FOR {who} (YOU HAVE TALKED BEFORE) ===\n"
            f"You and {who} have spoken in PREVIOUS phone calls. "
            "You MUST reference this history when relevant. "
            "When the caller asks what you remember, summarize the key points below.\n\n"
        )
        if has_crystals:
            memory_block += f"THERAPEUTIC INSIGHTS FROM PRIOR SESSIONS:\n{crystal_context}\n\n"
        if has_history:
            memory_block += f"TRANSCRIPTS FROM RECENT PRIOR CALLS:\n{recent_summary}\n\n"
        memory_block += "=== END PRIOR SESSION MEMORY ===\n\n"

    # SOVEREIGN-VOICE — hybrid resume (dropped voice + main chat + PAUSED redial)
    try:
        from app.services.voice_hybrid_resume import build_hybrid_resume_block
        memory_block += await build_hybrid_resume_block(db_pool, username)
    except Exception:
        pass

    # QUANTUM-CRYSTAL-ARCH: cycle skill / treatment plan for voice
    skill_plan_block = ""
    try:
        from app.services.cycle_skill_plan_service import build_cycle_skill_plan_context as _sk_voice
        _sk = await _sk_voice(db_pool, username) if db_pool and username else ""
        if _sk:
            skill_plan_block = (
                "=== SKILL PLAN (plain language only on call) ===\n"
                f"{_sk}\n=== END SKILL PLAN ===\n\n"
            )
    except Exception:
        skill_plan_block = ""

    # QUANTUM-CRYSTAL-ARCH: clinical technique directory / care-plan assist
    directory_block = ""
    try:
        if os.getenv("ENABLE_CLINICAL_TECHNIQUE_DIRECTORY", "").lower() in ("true", "1", "yes"):
            from app.services.clinical_technique_directory import (
                directory_context_for_surface,
                extract_plan_focus_theme,
            )
            from app.services.nate_therapeutic_plan_service import get_active_plan_context

            _pc = await get_active_plan_context(db_pool, username) if db_pool and username else ""
            _theme = extract_plan_focus_theme(_pc or "")
            _dc = await directory_context_for_surface(
                _theme or "skills practice grounding emotion regulation",
                db_pool=db_pool,
                user_id=username or "",
                search_proxy=_get_voice_search_proxy(),
                active_plan_theme=_theme,
                allow_web=False,
                max_techniques=3,
            )
            if _pc or _dc:
                directory_block = (
                    "=== CLINICAL DIRECTORY / PLAN (plain language only on call) ===\n"
                    + ((_pc + "\n\n") if _pc else "")
                    + (_dc or "")
                    + "\n=== END CLINICAL DIRECTORY ===\n\n"
                )
        # QUANTUM-CRYSTAL-ARCH — sandbox inject when directory flag off
        elif (
            os.getenv("ENABLE_LN_SANDBOX", "").lower() in ("true", "1", "yes", "on")
            and db_pool
            and username
        ):
            from app.services.ln_sandbox_context import get_sandbox_candidates_for_user

            _sb = await get_sandbox_candidates_for_user(db_pool, username, max_items=3)
            if _sb:
                directory_block = (
                    "=== LN SANDBOX CANDIDATES (plain language only on call) ===\n"
                    + _sb
                    + "\n=== END LN SANDBOX ===\n\n"
                )
    except Exception:
        directory_block = ""

    # SOVEREIGN-VOICE: inject SSE story context if available
    story_block = ""
    try:
        from app.sse.voice_context_enricher import get_voice_story_context
        sse = await get_voice_story_context(username, db_pool)
        parts = []
        if sse.get("archetype"):
            parts.append(f"Archetype: {sse['archetype']}")
        if sse.get("biome"):
            parts.append(f"Story biome: {sse['biome']}")
        if sse.get("active_quest"):
            parts.append(f"Working on: {sse['active_quest']}")
        if sse.get("active_mission"):
            parts.append(f"Relationship focus: {sse['active_mission']}")
        if parts:
            story_block = f"[STORY JOURNEY] {who}'s therapeutic story: " + " | ".join(parts) + "\n\n"
    except Exception:
        pass

    # QUANTUM-CRYSTAL-ARCH / SOVEREIGN-VOICE: population crisis + night register
    pop_block = ""
    try:
        _pop_profile = {"username": username, "profile_data": {}}
        if db_pool and username:
            async with db_pool.acquire() as _pc:
                _prow = await _pc.fetchrow(
                    "SELECT profile_data FROM users WHERE username = $1 LIMIT 1",
                    username,
                )
                if _prow:
                    _pop_profile["profile_data"] = _prow["profile_data"] or {}
        from app.services.population_prompt_modifiers import voice_population_suffix
        pop_block = voice_population_suffix(_pop_profile) or ""
    except Exception:
        pass

    prompt = (
        memory_block
        + skill_plan_block
        + directory_block
        + story_block
        + pop_block
        + f"You are Little Nate, a warm, concise therapeutic coach on a live phone call with {who}.\n"
        "Respond in 1–2 short sentences (under 25 words). One question OR one reflection, not both.\n"
        "Sound human and grounded. Never say you are an AI.\n\n"
        "MEMORY RULES:\n"
        f"- You HAVE talked to {who} before. The transcripts above are from PREVIOUS calls.\n"
        "- When asked 'do you remember', refer to the PRIOR SESSION MEMORY above.\n"
        "- When asked about previous conversations, summarize key topics from the transcripts.\n"
        "- Never say 'this is our first conversation' if PRIOR SESSION MEMORY exists above.\n\n"
        "ACCURACY RULES:\n"
        "- Only reference details that appear in PRIOR SESSION MEMORY.\n"
        "- If the user mentions someone not in your memory, say 'Tell me about them.'\n"
        "- If uncertain, ask: 'I want to make sure I'm remembering correctly — did you mention...?'\n"
        "- Never invent names, events, or details not in your memory.\n\n"
        "INTERNET SEARCH CAPABILITY:\n"
        "You CAN search the internet when the caller asks. When they ask you to look something up, "
        "search for something, or ask a factual question you're unsure about, just say something like "
        "'Let me look that up for you' — the system will automatically search and provide you results. "
        "You will receive the search results as a follow-up message. Summarize them conversationally. "
        "Never say you cannot search the internet.\n"
    )
    return prompt, crystal_scopes


def _rissc_params_for_profile(profile: str):
    from app.services.rissc_voice import get_rissc_params

    felt = profile if profile else "grounded"
    if felt == "connect":
        felt = "grounded"
    return get_rissc_params(felt, None)


async def synthesize_nathan_xtts(text: str, profile: str = "connect") -> bytes:
    """POST form to Hetzner XTTS; returns raw response body (WAV)."""
    import httpx

    params = _rissc_params_for_profile(profile)
    base = os.getenv("XTTS_URL", XTTS_URL).strip().rstrip("/") or XTTS_URL
    url = base if "/synthesize" in base else f"{base}/synthesize"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            data={
                "text": text,
                "voice_id": "father",
                "language": "en",
                "speed": str(params.speed),
                "temperature": str(params.temperature),
                "top_p": str(params.top_p),
            },
        )
        resp.raise_for_status()
        return resp.content


async def _synthesize_edge_tts_fallback(text: str) -> Optional[bytes]:
    """Edge TTS (free Microsoft) as fallback when XTTS is unreachable. Returns WAV-like bytes."""
    try:
        import edge_tts
        import io

        communicate = edge_tts.Communicate(text, "en-US-GuyNeural", rate="-5%")
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])
        audio = buffer.getvalue()
        if audio:
            logger.info("Edge TTS fallback: synthesized %d bytes for %d chars", len(audio), len(text))
            return audio
        return None
    except Exception as e:
        logger.warning("Edge TTS fallback failed: %s", e)
        return None


async def _open_grok_session(system_prompt: str, silence_duration_ms: int = 700):
    """Connect to Azure Foundry Grok Realtime and send session.update."""  # SOVEREIGN-VOICE
    import websockets

    api_key = os.getenv("AZURE_API_KEY", "").strip()
    if not api_key or not _AZ_REALTIME_URL:
        raise RuntimeError("AZURE_API_KEY or AZURE_OPENAI_ENDPOINT not set for voice")

    _sil = max(500, min(1500, int(silence_duration_ms or 700)))  # SOVEREIGN-VOICE pacing
    print(f"[VOICE] Connecting to Azure Foundry Realtime: {_AZ_REALTIME_URL[:60]}...")
    ws = await websockets.connect(
        _AZ_REALTIME_URL,
        extra_headers={"api-key": api_key},
        max_size=None,
    )
    # SOVEREIGN-VOICE — Foundry rejects session.audio; use flat input_audio_format
    session_update = {
        "type": "session.update",
        "session": {
            "instructions": system_prompt,
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": _sil,
                "threshold": 0.5,
                "prefix_padding_ms": 300,
            },
            "modalities": ["text"],
            "input_audio_format": "pcm16",
            # SOVEREIGN-VOICE — enable user STT for crystallize / SI / barge-in coaching
            "input_audio_transcription": {"model": "whisper-1"},
        },
    }
    await ws.send(json.dumps(session_update))
    return ws


_spoken_response_ids: set = set()


def _extract_assistant_text(event: Dict[str, Any]) -> Optional[str]:
    """Best-effort text extraction across xAI / OpenAI-realtime-style events.

    Uses _spoken_response_ids to prevent the same response from being spoken
    twice when xAI sends both a per-item done event and a response.done event
    with embedded text.
    """
    t = event.get("type") or ""
    resp_id = event.get("response_id") or ""

    if t in (
        "response.output_audio_transcript.delta",
        "response.output_audio.delta",
        "response.audio_transcript.delta",
        "response.audio.delta",
    ):
        return None

    # Foundry/xAI emit both response.audio_transcript.done and response.output_audio_transcript.done
    if t in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
        if resp_id and resp_id in _spoken_response_ids:
            print(f"[GROK-DEDUP] skipping duplicate audio transcript resp={resp_id[:12]}")
            return None
        txt = (event.get("transcript") or event.get("text") or "").strip()
        if not resp_id:
            resp_id = (event.get("response") or {}).get("id") or ""
        if txt and resp_id:
            _spoken_response_ids.add(resp_id)
        return txt or None

    if t in ("response.text.done", "response.output_text.done"):
        if resp_id and resp_id in _spoken_response_ids:
            print(f"[GROK-DEDUP] skipping duplicate text from {t} resp={resp_id[:12]}")
            return None
        txt = (event.get("text") or "").strip()
        if txt and resp_id:
            _spoken_response_ids.add(resp_id)
        return txt or None

    if t == "response.done":
        if resp_id and resp_id in _spoken_response_ids:
            print(f"[GROK-DEDUP] skipping response.done (resp_id match) resp={resp_id[:12]}")
            return None
        resp = event.get("response") or {}
        r_id = resp.get("id") or resp_id
        if r_id and r_id in _spoken_response_ids:
            print(f"[GROK-DEDUP] skipping response.done (resp.id match) resp={r_id[:12]}")
            return None
        out = resp.get("output") or []
        for item in out:
            if isinstance(item, dict):
                for part in item.get("content") or []:
                    if not isinstance(part, dict):
                        continue
                    ptype = part.get("type") or ""
                    if ptype in ("output_text", "text"):
                        tx = (part.get("text") or "").strip()
                    elif ptype in ("audio_transcript", "output_audio_transcript"):
                        tx = (part.get("transcript") or part.get("text") or "").strip()
                    else:
                        tx = ""
                    if tx:
                        if r_id:
                            _spoken_response_ids.add(r_id)
                        return tx
    return None


def _extract_user_text(event: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of user transcripts from realtime events."""
    t = event.get("type") or ""
    # SOVEREIGN-VOICE — Foundry/OpenAI transcription completed variants
    if t in (
        "input_audio_buffer.transcript.done",
        "conversation.item.input_audio_transcription.completed",
    ) or t.endswith("input_audio_transcription.completed"):
        txt = (event.get("transcript") or event.get("text") or "").strip()
        return txt or None
    if t == "conversation.item.created":
        item = event.get("item") or {}
        if item.get("role") == "user":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                tx = (part.get("transcript") or part.get("text") or "").strip()
                if tx and part.get("type") in ("input_text", "text", "input_audio"):
                    return tx
    return None


def _detect_therapeutic_insights(user_text: str, assistant_text: str) -> List[str]:
    """Heuristic insight extraction from finalized call transcript turns."""
    merged = f"{user_text}\n{assistant_text}".strip()
    if len(merged) < 80:
        return []
    lowered = merged.lower()
    markers = (
        "i feel", "i'm feeling", "anxious", "overwhelmed", "panic",
        "grief", "hopeless", "stuck", "unsafe", "lonely",
    )
    if any(m in lowered for m in markers):
        return [merged[:800]]
    return []


_MEMORY_FILLER_PHRASES = [
    "Let me check my notes on that...",
    "Give me a moment to pull that up...",
    "Let me look through our history...",
    "One second, I'm checking my records...",
]
_memory_filler_idx = 0


class MemorySearchDedup:
    """Prevents duplicate RAG queries when Grok re-emits the same transcript."""

    def __init__(self, ttl_seconds: float = 30.0):
        self._seen: Dict[str, float] = {}
        self._ttl = ttl_seconds

    def should_search(self, text: str) -> bool:
        key = hashlib.sha256(text[:200].lower().strip().encode()).hexdigest()[:16]
        now = time.monotonic()
        self._seen = {k: v for k, v in self._seen.items() if now - v < self._ttl}
        if key in self._seen:
            return False
        self._seen[key] = now
        return True

    def reset(self) -> None:
        self._seen.clear()


_search_dedup = MemorySearchDedup()


class MemorySearchTrigger:
    """Two-gate memory search trigger. Gate 1: at least 2 pattern categories must match.
    Gate 2: weighted confidence score must reach threshold (default 2.0).
    Patent 8, Claim 1: voice memory recall pipeline."""

    _CATEGORIES: Dict[str, List[re.Pattern]] = {
        "explicit_recall": [
            re.compile(r"\b(do you remember|you remember|can you recall)\b", re.I),
            re.compile(r"\b(remember when)\b", re.I),
            re.compile(r"\b(you forgot|don'?t you remember)\b", re.I),
            re.compile(r"\b(what do you know about me)\b", re.I),
        ],
        "temporal_reference": [
            re.compile(r"\b(last (time|call|session|conversation))\b", re.I),
            re.compile(r"\b(earlier (today|this week|you said))\b", re.I),
            re.compile(r"\b(previous|prior)\b.*\b(session|call|conversation)\b", re.I),
        ],
        "topic_deepening": [
            re.compile(r"\b(we (talked|discussed|spoke|chatted) about)\b", re.I),
            re.compile(r"\b(bring up|go back to|revisit|pick up where)\b", re.I),
            re.compile(r"\b(what (have )?we (been )?(working|talking) on)\b", re.I),
        ],
        "emotional_recall": [
            re.compile(r"\b(i told you|i mentioned|i said)\b", re.I),
            re.compile(r"\b(what did (i|we) (say|talk|discuss|mention))\b", re.I),
            re.compile(r"\b(my (therapist|counselor|doctor|coach) notes?)\b", re.I),
        ],
        "second_person_memory": [
            re.compile(r"\b(do you remember)\b", re.I),
        ],
    }

    _CONFIDENCE_THRESHOLD = 2.0

    def should_trigger(self, text: str) -> bool:
        if not text or len(text) < 8:
            return False
        matched_categories: List[str] = []
        score = 0.0
        for cat_name, patterns in self._CATEGORIES.items():
            if any(p.search(text) for p in patterns):
                matched_categories.append(cat_name)
                weight = 2.0 if cat_name == "second_person_memory" else 1.0
                score += weight

        if "?" in text:
            score += 0.5
        text_lower = text.lower()
        if any(w in text_lower for w in ("i ", "i'm", "my ", "me ")):
            score += 0.3

        unique_cats = set(matched_categories) - {"second_person_memory"}
        if "second_person_memory" in matched_categories:
            unique_cats.add("explicit_recall")
        return len(unique_cats) >= 2 and score >= self._CONFIDENCE_THRESHOLD


_memory_trigger = MemorySearchTrigger()


def _is_memory_query(text: str) -> bool:
    """Detect if user is asking Nate to recall something from memory.
    Uses two-gate MemorySearchTrigger: requires 2+ category matches AND confidence >= 2.0."""
    return _memory_trigger.should_trigger(text)


# ---------------------------------------------------------------------------
# WEB SEARCH — Internet lookup during live voice calls
# Patent 8: voice-initiated web search with sanitized injection into session
# ---------------------------------------------------------------------------

_WEB_SEARCH_FILLER_PHRASES = [
    "Let me look that up for you...",
    "Give me a moment, I'm searching for that...",
    "One second, checking the internet...",
    "Let me find some information on that...",
]
_web_filler_idx = 0

_web_search_dedup = MemorySearchDedup(ttl_seconds=45.0)

_voice_search_proxy: Optional["SecureSearchProxy"] = None


def _get_voice_search_proxy() -> Optional["SecureSearchProxy"]:
    """Lazy-init the search proxy so import-time failures are non-fatal."""
    global _voice_search_proxy
    if _voice_search_proxy is not None:
        return _voice_search_proxy
    if SecureSearchProxy is None:
        return None
    data_dir = os.getenv("DATA_DIR", "/tmp/nate_data")
    _voice_search_proxy = SecureSearchProxy(data_dir=data_dir)
    if not _voice_search_proxy.is_available:
        logger.warning("[VOICE-WEB-SEARCH] No search backend (Bing/DuckDuckGo) available")
    return _voice_search_proxy


class WebSearchTrigger:
    """Detect when a caller is asking Nate to search the internet.
    Requires explicit search intent AND a searchable noun phrase."""

    _PATTERNS: List[re.Pattern] = [
        re.compile(r"\b(search|look\s*up|google|find out|look\s*into)\b", re.I),
        re.compile(r"\b(what (is|are|does|do|was|were|causes?))\b", re.I),
        re.compile(r"\b(can you (find|check|search|look))\b", re.I),
        re.compile(r"\b(tell me about|info(rmation)? (on|about))\b", re.I),
        re.compile(r"\b(how (do|does|to|can|should))\b", re.I),
        re.compile(r"\b(is (it|there) true (that)?)\b", re.I),
        re.compile(r"\b(research|explore|investigate)\b", re.I),
        re.compile(r"\b(latest|recent|current|new|up.?to.?date)\b.*\b(on|about|regarding|for)\b", re.I),
    ]

    _EXCLUSION_PATTERNS: List[re.Pattern] = [
        re.compile(r"\b(do you remember|you remember|last (time|call|session))\b", re.I),
        re.compile(r"\b(we (talked|discussed|spoke) about)\b", re.I),
        re.compile(r"\b(i told you|i mentioned|i said)\b", re.I),
    ]

    _MIN_QUERY_LENGTH = 12

    def should_trigger(self, text: str) -> bool:
        if not text or len(text) < self._MIN_QUERY_LENGTH:
            return False
        if any(p.search(text) for p in self._EXCLUSION_PATTERNS):
            return False
        matches = sum(1 for p in self._PATTERNS if p.search(text))
        return matches >= 1


_web_trigger = WebSearchTrigger()


def _is_web_search_query(text: str) -> bool:
    """Detect if the caller is asking Nate to search the internet."""
    if _is_memory_query(text):
        return False
    return _web_trigger.should_trigger(text)


def _extract_web_query(text: str) -> str:
    """Extract a clean search query from the caller's question.
    Strips conversational filler, keeps the searchable core."""
    filler = [
        r"^(hey|hi|ok|okay|so|um|uh|well|like|you know|nate|little nate)\b[,\s]*",
        r"\b(can you|could you|would you|please)\b\s*",
        r"\b(search|google|look up|find out|look into)\b\s*(for me|for us|real quick)?\s*",
        r"\b(tell me about|give me info on|i want to know about)\b\s*",
    ]
    q = text.strip()
    for pattern in filler:
        q = re.sub(pattern, "", q, flags=re.I).strip()
    q = q.rstrip("?").strip()
    if len(q) < 5:
        q = text.strip()
    return q[:200]


class SearchTermExtractor:
    """Extract therapeutically significant search terms from memory queries.
    Returns 3-8 terms ordered by relevance: clinical terms first, then nouns, then verbs."""

    PRESERVE_WORDS = frozenset({
        "trauma", "anxiety", "grief", "abandonment", "attachment", "boundaries",
        "anger", "shame", "guilt", "fear", "depression", "loneliness", "isolation",
        "betrayal", "trust", "safety", "control", "helpless", "hopeless", "worthless",
        "abuse", "neglect", "codependent", "enmeshment", "dissociation", "panic",
        "suicidal", "self-harm", "addiction", "recovery", "relapse", "sobriety",
        "divorce", "custody", "affair", "infidelity", "marriage", "relationship",
        "mother", "father", "parent", "child", "sibling", "family", "daughter", "son",
        "therapist", "counselor", "medication", "diagnosis", "ptsd", "adhd", "ocd",
        "bipolar", "borderline", "narcissist", "gaslighting", "triggered", "flashback",
        "nightmare", "insomnia", "eating", "body", "weight", "exercise",
        "work", "boss", "fired", "career", "money", "debt", "homeless",
        "crying", "tears", "rage", "numb", "empty", "overwhelmed", "stuck",
        "healing", "growth", "progress", "breakthrough", "setback", "regression",
    })

    STOP_WORDS = frozenset({
        "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
        "and", "any", "are", "aren't", "as", "at", "back", "be", "because", "been",
        "before", "being", "below", "between", "both", "bring", "but", "by", "came",
        "can", "can't", "cannot", "chatted", "come", "conversation", "could", "couldn't",
        "day", "did", "didn't", "discussed", "do", "does", "doesn't", "doing", "don't",
        "down", "during", "each", "earlier", "even", "every", "few", "for", "from",
        "further", "get", "getting", "go", "going", "gone", "got", "had", "hadn't",
        "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's",
        "her", "here", "hers", "herself", "him", "himself", "his", "history", "how",
        "how's", "however", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into",
        "is", "isn't", "it", "it's", "its", "itself", "just", "know", "last", "let",
        "like", "ll", "look", "looking", "lot", "make", "making", "many", "may", "me",
        "mention", "mentioned", "might", "more", "most", "much", "must", "my", "myself",
        "no", "nor", "not", "now", "of", "off", "ok", "okay", "on", "once", "one",
        "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own",
        "pick", "please", "previous", "prior", "quite", "re", "really", "recall",
        "remember", "revisit", "right", "said", "same", "say", "session", "shall",
        "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some",
        "something", "spoke", "still", "such", "take", "talked", "tell", "than",
        "thank", "that", "that's", "the", "their", "theirs", "them", "themselves",
        "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
        "they've", "thing", "think", "this", "those", "though", "through", "time",
        "to", "today", "told", "too", "um", "uh", "under", "until", "up", "upon",
        "us", "ve", "very", "want", "was", "wasn't", "way", "we", "we'd", "we'll",
        "we're", "we've", "week", "well", "were", "weren't", "what", "what's", "when",
        "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why",
        "why's", "will", "with", "won't", "working", "would", "wouldn't", "yeah",
        "yes", "yet", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
        "yourself", "yourselves",
    })

    def extract(self, text: str) -> List[str]:
        words = re.findall(r"[a-zA-Z']+", text.lower())
        preserved = []
        others = []
        seen = set()
        for w in words:
            if w in seen or len(w) < 3:
                continue
            seen.add(w)
            if w in self.PRESERVE_WORDS:
                preserved.append(w)
            elif w not in self.STOP_WORDS:
                others.append(w)
        result = preserved + others
        if not result:
            return [text[:80]]
        return result[:8]


_term_extractor = SearchTermExtractor()


def _extract_search_terms(text: str) -> str:
    """Pull the meaningful search query from the user's memory request.
    Uses SearchTermExtractor with expanded stop words and clinical PRESERVE_WORDS."""
    terms = _term_extractor.extract(text)
    return " ".join(terms)


async def _deep_memory_search(
    username: str,
    query_text: str,
    db_pool,
    max_results: int = 12,
) -> str:
    """
    Parallel search across all memory stores for the given query.
    Returns formatted context string ready for injection into the live session.
    """
    search_terms = _extract_search_terms(query_text)
    print(f"[VOICE-DEEP-SEARCH] query='{query_text[:80]}' terms='{search_terms}' user={username}")

    results_parts: List[str] = []

    async def _search_conversation_history():
        """Full-text search on conversation_history using PostgreSQL FTS."""
        if not db_pool:
            return
        try:
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_text, ai_text, created_at, session_id, "
                    "ts_rank(to_tsvector('english', COALESCE(user_text,'') || ' ' || COALESCE(ai_text,'')), "
                    "        plainto_tsquery('english', $2)) AS rank "
                    "FROM conversation_history "
                    "WHERE user_id = $1 "
                    "AND to_tsvector('english', COALESCE(user_text,'') || ' ' || COALESCE(ai_text,'')) "
                    "    @@ plainto_tsquery('english', $2) "
                    "ORDER BY rank DESC, created_at DESC LIMIT $3",
                    username, search_terms, max_results,
                )
                if rows:
                    parts = []
                    for r in rows:
                        ts = r["created_at"].strftime("%b %d %I:%M%p") if r["created_at"] else ""
                        u = (r["user_text"] or "")[:250]
                        a = (r["ai_text"] or "")[:250]
                        entry = f"[{ts}]"
                        if u:
                            entry += f" {username}: {u}"
                        if a:
                            entry += f" | Nate: {a}"
                        parts.append(entry)
                    results_parts.append(
                        f"CONVERSATION HISTORY MATCHES ({len(rows)} found):\n"
                        + "\n".join(parts)
                    )
                    print(f"[VOICE-DEEP-SEARCH] conversation_history: {len(rows)} FTS hits")
        except Exception as e:
            logger.warning("Deep search conversation_history failed: %s", e)

    async def _search_crystals():
        """Search nate_intelligence_crystals by keyword ILIKE."""
        if not db_pool:
            return
        try:
            user_uuid = await _resolve_user_uuid(username, db_pool)
            async with db_pool.acquire() as conn:
                rows = await conn.fetch(
                    # SOVEREIGN-VOICE: global pool (user_id IS NULL) previously had no
                    # scope filter, letting admin_only and orphaned user:* crystals leak
                    # into a caller's deep-memory search. Allowlist scope='global' only.
                    "SELECT crystal_text, domain, confidence, created_at "
                    "FROM nate_intelligence_crystals "
                    "WHERE ((user_id = $1 AND scope != 'archived') "
                    "OR (user_id IS NULL AND scope = 'global')) "
                    "AND superseded_by IS NULL "
                    "AND crystal_text ILIKE '%' || $2 || '%' "
                    "ORDER BY confidence DESC LIMIT $3",
                    user_uuid, search_terms, max_results,
                )
                if rows:
                    parts = []
                    for r in rows:
                        ts = r["created_at"].strftime("%b %d") if r["created_at"] else ""
                        conf = f"{r['confidence']:.0%}" if r["confidence"] else ""
                        parts.append(f"[{ts} {r['domain'] or ''} {conf}] {(r['crystal_text'] or '')[:300]}")
                    results_parts.append(
                        f"CRYSTAL MEMORY MATCHES ({len(rows)} found):\n"
                        + "\n".join(parts)
                    )
                    print(f"[VOICE-DEEP-SEARCH] crystals: {len(rows)} ILIKE hits")
        except Exception as e:
            logger.warning("Deep search crystals failed: %s", e)

    async def _search_crystal_recall():
        """Use the standard crystal recall path for broader semantic matching."""
        if not _crystal_recall or not db_pool:
            return
        try:
            ctx = await _crystal_recall(db_pool, username, max_results=6, source="voice_deep_search")
            if ctx:
                results_parts.append(f"THERAPEUTIC RECALL CONTEXT:\n{ctx}")
                print(f"[VOICE-DEEP-SEARCH] crystal_recall: {len(ctx)} chars")
        except Exception as e:
            logger.warning("Deep search crystal_recall failed: %s", e)

    async def _search_vectorize():
        """Semantic search via Vectorize across conversation and wisdom indexes."""
        try:
            from app.services.vectorize_service import semantic_search_all
            user_uuid = await _resolve_user_uuid(username, db_pool) or username
            hits = await semantic_search_all(
                query=query_text,
                user_id=user_uuid,
                top_k=8,
                index_subset=["conversation", "wisdom", "session"],
            )
            total = 0
            for source, items in hits.items():
                if not items:
                    continue
                parts = []
                for item in items[:4]:
                    meta = item.get("metadata", {})
                    text_preview = meta.get("text", item.get("text", ""))[:300]
                    score = item.get("score", 0)
                    parts.append(f"  [{source} score={score:.2f}] {text_preview}")
                if parts:
                    results_parts.append(f"SEMANTIC MATCHES ({source}):\n" + "\n".join(parts))
                    total += len(parts)
            if total:
                print(f"[VOICE-DEEP-SEARCH] vectorize: {total} semantic hits")
        except ImportError:
            pass
        except Exception as e:
            logger.warning("Deep search vectorize failed: %s", e)

    await asyncio.gather(
        _search_conversation_history(),
        _search_crystals(),
        _search_crystal_recall(),
        _search_vectorize(),
        return_exceptions=True,
    )

    if not results_parts:
        print(f"[VOICE-DEEP-SEARCH] no results found for '{search_terms}'")
        return ""

    combined = "\n\n".join(results_parts)
    print(f"[VOICE-DEEP-SEARCH] total context: {len(combined)} chars from {len(results_parts)} sources")
    return combined


async def _inject_memory_context(grok_ws, username: str, memory_context: str) -> bool:
    """Inject retrieved memory context into the live Grok session."""
    if not grok_ws or not memory_context:
        return False

    context_msg = (
        f"[MEMORY SEARCH RESULTS — USE THIS TO ANSWER {username}'s QUESTION]\n"
        "The following is retrieved from your full memory (past calls, chats, crystals, notes). "
        "Reference specific details from these results when responding. "
        "If something matches what they asked about, say so directly.\n\n"
        f"{memory_context}\n\n"
        "[END MEMORY SEARCH RESULTS — Now respond to their question using this context.]"
    )

    try:
        await grok_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": context_msg}],
            },
        }))
        await grok_ws.send(json.dumps({"type": "response.create"}))
        print(f"[VOICE-DEEP-SEARCH] injected {len(context_msg)} chars via conversation.item.create")
        return True
    except Exception as e:
        logger.warning("conversation.item.create injection failed, trying session.update fallback: %s", e)

    try:
        await grok_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "instructions": context_msg,
            },
        }))
        print(f"[VOICE-DEEP-SEARCH] injected {len(context_msg)} chars via session.update fallback")
        return True
    except Exception as e2:
        logger.warning("session.update fallback also failed: %s", e2)
        return False


# ---------------------------------------------------------------------------
# WEB SEARCH — execute + inject
# ---------------------------------------------------------------------------

async def _web_search(query_text: str, username: str) -> str:
    """Run a sanitized internet search and return formatted context for Grok."""
    proxy = _get_voice_search_proxy()
    if proxy is None or not proxy.is_available:
        print("[VOICE-WEB-SEARCH] search proxy unavailable")
        return ""

    clean_query = _extract_web_query(query_text)
    print(f"[VOICE-WEB-SEARCH] query='{clean_query}' user={username}")

    try:
        result = await asyncio.wait_for(
            proxy.execute_search(clean_query, coach_id=username, num_results=3),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[VOICE-WEB-SEARCH] search timed out after 8s")
        return ""
    except Exception as e:
        logger.warning("[VOICE-WEB-SEARCH] search failed: %s", e)
        return ""

    if not result.get("success") or not result.get("results"):
        print(f"[VOICE-WEB-SEARCH] no results: {result.get('error', 'empty')}")
        return ""

    safe_results = [r for r in result["results"] if r.get("safe", False)]
    if not safe_results:
        print("[VOICE-WEB-SEARCH] all results filtered by security")
        return ""

    formatted = proxy.format_for_nate(safe_results)
    print(f"[VOICE-WEB-SEARCH] {len(safe_results)} safe results, {len(formatted)} chars")
    return formatted


async def _inject_web_context(grok_ws, username: str, web_context: str) -> bool:
    """Inject internet search results into the live Grok session."""
    if not grok_ws or not web_context:
        return False

    context_msg = (
        f"[INTERNET SEARCH RESULTS — USE THIS TO ANSWER {username}'s QUESTION]\n"
        "The following information was found via internet search. "
        "Summarize the key points conversationally — keep it brief and natural for a phone call. "
        "Do NOT read URLs aloud. Reference the source topic, not the domain name. "
        "If the information is clinical/medical, remind them this is general information "
        "and they should discuss specifics with their healthcare provider.\n\n"
        f"{web_context}\n\n"
        "[END SEARCH RESULTS — Respond naturally using this information.]"
    )

    try:
        await grok_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": context_msg}],
            },
        }))
        await grok_ws.send(json.dumps({"type": "response.create"}))
        print(f"[VOICE-WEB-SEARCH] injected {len(context_msg)} chars into session")
        return True
    except Exception as e:
        logger.warning("[VOICE-WEB-SEARCH] injection failed: %s", e)
        return False


async def _hydrate_call_context_from_redis(ctx: Dict[str, Any]) -> None:
    """Load nate:call_context:{call_id} when Twilio passes call_id but body is empty."""
    cid = (ctx.get("call_id") or "").strip()
    if not cid:
        return
    if (ctx.get("system_prompt") or "").strip() and (ctx.get("username") or ctx.get("user_id")):
        return
    try:
        from app.services.api_server import _get_auth_redis

        redis = await _get_auth_redis()
        if not redis:
            return
        raw = await redis.get(f"nate:call_context:{cid}")
        if not raw:
            return
        if isinstance(raw, bytes):
            raw = raw.decode()
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            for k, v in loaded.items():
                if k not in ctx or ctx[k] in (None, "", []):
                    ctx[k] = v
            print(f"[TWILIO-GROK-XTTS] hydrated call context from Redis call_id={cid[:12]}…")
    except Exception as e:
        logger.warning("Redis hydrate call context failed: %s", e)


def _twilio_stream_custom_parameters(start_data: Dict[str, Any]) -> Dict[str, str]:
    """Normalize Twilio ``start.customParameters`` (dict or list of {name,value})."""
    raw = start_data.get("customParameters")
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None and str(v) != ""}
    if isinstance(raw, list):
        out: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            val = item.get("value")
            if name is not None and val is not None and str(val) != "":
                out[str(name)] = str(val)
        return out
    return {}


async def _get_filler_mulaw(xtts_to_mulaw_state: list) -> Optional[bytes]:
    """Get a short filler phrase as μ-law audio, cycling through phrases."""
    global _filler_idx
    phrase = _FILLER_PHRASES[_filler_idx % len(_FILLER_PHRASES)]
    _filler_idx += 1

    if phrase in _filler_cache:
        return _filler_cache[phrase]

    audio = await _synthesize_edge_tts_fallback(phrase)
    if audio:
        import audioop

        pcm_raw = strip_wav_header(audio)
        if pcm_raw:
            try:
                pcm_8k, _ = audioop.ratecv(pcm_raw, 2, 1, 24000, 8000, None)
            except audioop.error:
                pcm_8k, _ = audioop.ratecv(pcm_raw, 2, 1, 22050, 8000, None)
            mulaw = audioop.lin2ulaw(pcm_8k, 2)
            _filler_cache[phrase] = mulaw
            return mulaw
    return None


async def _azure_tts(text: str, speed: float = 1.05) -> Optional[bytes]:
    """Azure OpenAI TTS (gpt-4o-mini-tts) — fastest path for live phone calls (<2s).

    Returns WAV-format audio bytes or None.
    """
    import httpx

    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.environ.get("AZURE_API_KEY", "")
    deployment = os.environ.get("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")

    if not endpoint or not api_key:
        return None

    url = f"https://{endpoint}/openai/deployments/{deployment}/audio/speech?api-version=2025-04-01-preview"

    payload = {
        "model": deployment,
        "input": text,
        "voice": "onyx",
        "response_format": "wav",
        "speed": speed,
        "instructions": (
            "Speak as a warm, confident young man in his late 20s. "
            "Natural and conversational — like talking to a trusted older brother. "
            "Relaxed pace, occasional light laugh energy. Never robotic or clinical."
        ),
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "api-key": api_key,
                    "Content-Type": "application/json",
                },
            )

        if resp.status_code == 200 and len(resp.content) > 100:
            print(f"[TWILIO-GROK-XTTS] Azure TTS: {len(resp.content)} bytes WAV")
            return resp.content

        print(f"[TWILIO-GROK-XTTS] Azure TTS returned {resp.status_code}: {resp.text[:100]}")
        return None
    except Exception as e:
        print(f"[TWILIO-GROK-XTTS] Azure TTS error: {e}")
        return None


def _wav_to_mulaw(wav_audio: bytes) -> Optional[bytes]:
    """Convert WAV audio (any sample rate) to 8kHz μ-law for Twilio."""
    import audioop

    pcm_raw = strip_wav_header(wav_audio)
    if not pcm_raw:
        return None
    try:
        pcm_8k, _ = audioop.ratecv(pcm_raw, 2, 1, 24000, 8000, None)
    except audioop.error:
        try:
            pcm_8k, _ = audioop.ratecv(pcm_raw, 2, 1, 22050, 8000, None)
        except audioop.error:
            pcm_8k, _ = audioop.ratecv(pcm_raw, 2, 1, 16000, 8000, None)
    return audioop.lin2ulaw(pcm_8k, 2)


async def _synthesize_with_fallback(
    text: str, profile: str, xtts_to_mulaw_state: list
) -> Optional[bytes]:
    """Azure TTS only — no voice switching. Retry once on failure."""
    for attempt in range(2):
        try:
            wav = await _azure_tts(text)
            if wav:
                mulaw = _wav_to_mulaw(wav)
                if mulaw:
                    return mulaw
        except Exception as e:
            logger.warning("Azure TTS attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(1.0)
    logger.warning("Azure TTS failed twice — skipping utterance (no voice switch)")
    return None


async def _resolve_user_uuid(username: str, db_pool) -> Optional[str]:
    """Lookup users.id (UUID) from username. Returns None if not found."""
    if not db_pool or not username:
        return None
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM users WHERE username = $1", username
            )
            return str(row["id"]) if row else None
    except Exception as e:
        logger.warning("resolve user UUID for %s failed: %s", username, e)
        return None


async def run_twilio_grok_xtts_bridge(
    websocket,
    call_context: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Drive one Twilio Media Stream WebSocket with Grok Realtime + XTTS.

    Lifecycle:
      1. On ``start``: acquire voice slot (Redis), open Grok session, record start time
      2. Stream audio: Twilio μ-law → Grok PCM 16k, Grok text → XTTS/Edge TTS → Twilio μ-law
      3. On ``stop`` or disconnect: release slot, log minutes, close Grok

    ``websocket`` is an accepted Starlette/FastAPI WebSocket.
    """
    ctx: Dict[str, Any] = dict(call_context or {})
    voice_crystallization_enabled = os.getenv("ENABLE_VOICE_TRANSCRIPT_CRYSTALLIZATION", "false").lower() in ("1", "true", "yes")
    stream_sid: Optional[str] = None
    grok_ws = None
    grok_task: Optional[asyncio.Task] = None
    mulaw_to_pcm_state: list = []
    xtts_to_mulaw_state: list = []
    seen_grok_event_ids: set = set()
    speaking = asyncio.Lock()
    tts_serial = asyncio.Lock()

    session_start: Optional[float] = None
    session_call_sid: Optional[str] = None
    session_username: Optional[str] = None
    _session_crystal_scopes: list = []  # QUANTUM-CRYSTAL-ARCH — Phase 5b
    slot_acquired = False
    user_turns: List[Dict[str, Any]] = []
    assistant_turns: List[Dict[str, Any]] = []
    filler_counts: Dict[str, int] = {}
    ec_snapshots: List[Dict[str, Any]] = []
    ec_task: Optional[asyncio.Task] = None

    # Patent 8: Backchannel engine + multi-signal turn detector
    _bc_engine = None  # Backchannel disabled — causes double-talk collisions
    _turn_detector = MultiSignalTurnDetector() if MultiSignalTurnDetector else None
    _greeting_spoken = False

    # Patent 11: Neural Mirror session (initialized after username is known)
    _neural_mirror = None
    _voice_sync = None  # SOVEREIGN-VOICE — VoiceCallSyncSession

    async def _record_ec_snapshot(reason: str) -> None:
        try:
            db_pool = ctx.get("db_pool")
            if not db_pool or not session_username:
                return
            from app.services.quantum_crystal_orchestrator import NevedalWaveEngine

            wave = NevedalWaveEngine(db_pool=db_pool)
            ec = await wave.compute_ec(session_username)
            ec["reason"] = reason
            ec["captured_at"] = datetime.now(timezone.utc).isoformat()
            ec_snapshots.append(ec)
        except Exception as e:
            logger.debug("EC snapshot failed (%s): %s", reason, e)

    async def _rolling_ec_loop() -> None:
        while True:
            await asyncio.sleep(30)
            asyncio.create_task(_record_ec_snapshot("rolling"))

    async def _send_mulaw_to_twilio(mulaw_out: bytes) -> None:
        nonlocal stream_sid, _tts_playback_started, _tts_playback_t0, _barge_speech_frames
        if not stream_sid or not mulaw_out:
            return
        async with speaking:
            # SOVEREIGN-VOICE — barge-in only after first chunk queued (not during synth wait)
            _tts_playback_started = True
            _tts_playback_t0 = time.monotonic()
            _barge_speech_frames = 0
            for i in range(0, len(mulaw_out), _TWILIO_MULAW_CHUNK):
                if _tts_cancel.is_set():  # SOVEREIGN-VOICE barge-in
                    print("[VOICE] barge-in — stop TTS playback")
                    return
                chunk = mulaw_out[i : i + _TWILIO_MULAW_CHUNK]
                msg = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
                try:
                    await websocket.send_text(json.dumps(msg))
                except Exception as e:
                    logger.warning("twilio send media failed: %s", e)
                    return
                if len(chunk) == _TWILIO_MULAW_CHUNK:
                    await asyncio.sleep(0.018)

    _nate_speaking = False
    _tts_cancel = asyncio.Event()  # SOVEREIGN-VOICE barge-in
    _tts_playback_started = False  # SOVEREIGN-VOICE — ignore barge-in until audio is sending
    _tts_playback_t0 = 0.0  # SOVEREIGN-VOICE — anti-echo grace clock
    _barge_speech_frames = 0  # SOVEREIGN-VOICE — require sustained speech to cut TTS

    async def _on_grok_text(response_text: str) -> None:
        nonlocal _greeting_spoken, _nate_speaking, _tts_playback_started, _barge_speech_frames
        text = (response_text or "").strip()
        if not text:
            return
        _tts_cancel.clear()
        _tts_playback_started = False
        _barge_speech_frames = 0
        _nate_speaking = True
        assistant_turns.append({"text": text, "ts": datetime.now(timezone.utc).isoformat()})
        # SOVEREIGN-VOICE — sync avatar expression to linked app
        if _voice_sync:
            _ut = user_turns[-1]["text"] if user_turns else ""
            asyncio.create_task(_voice_sync.on_nate_text(text, _ut))
        async with tts_serial:
            # Do not abort on cancel set during synth — ambient energy false barge-in
            tts_task = asyncio.create_task(
                _synthesize_with_fallback(text, "connect", xtts_to_mulaw_state)
            )
            try:
                mulaw_out = await asyncio.wait_for(
                    asyncio.shield(tts_task), timeout=_FILLER_TIMEOUT_S
                )
            except asyncio.TimeoutError:
                filler = await _get_filler_mulaw(xtts_to_mulaw_state)
                if filler:
                    print("[TWILIO-GROK-XTTS] filler played while waiting for TTS")
                    filler_counts["connect"] = filler_counts.get("connect", 0) + 1
                    _tts_cancel.clear()  # SOVEREIGN-VOICE — play filler after false barge
                    await _send_mulaw_to_twilio(filler)
                mulaw_out = await tts_task

            if mulaw_out:
                _tts_cancel.clear()  # SOVEREIGN-VOICE — clear false barge during synth
                print(f"[TWILIO-GROK-XTTS] synthesized {len(mulaw_out)} bytes μ-law for Twilio")
                await _send_mulaw_to_twilio(mulaw_out)
        if not _greeting_spoken:
            _greeting_spoken = True
        _nate_speaking = False
        _tts_playback_started = False

    _grok_event_count = 0
    _media_chunk_count = 0
    _call_limit_task: Optional[asyncio.Task] = None

    async def _enforce_call_limit() -> None:
        """Warn at 2 min before limit, disconnect at limit."""
        max_s = ctx.get("max_call_seconds")
        if not max_s or max_s <= 0:
            return
        warn_at = max(0, max_s - 120)
        if warn_at > 0:
            await asyncio.sleep(warn_at)
            try:
                await _on_grok_text(
                    "Just a heads up — we have about two minutes left in this session. "
                    "Is there anything important you'd like to touch on before we wrap up?"
                )
            except Exception:
                pass
            await asyncio.sleep(120)
        else:
            await asyncio.sleep(max_s)
        try:
            await _on_grok_text(
                "We've reached the end of our session time. "
                "It was good talking with you. Take care."
            )
            await asyncio.sleep(4)
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

    async def grok_listener() -> None:
        nonlocal _grok_event_count, _nate_speaking
        if grok_ws is None:
            return
        print("[GROK-LISTENER] started")
        _recovery_timer: Optional[asyncio.Task] = None
        _got_text_after_error = False

        async def _delayed_recovery() -> None:
            """Speak recovery only if Grok doesn't respond within 3 seconds."""
            nonlocal _got_text_after_error
            await asyncio.sleep(3.0)
            if not _got_text_after_error:
                print("[GROK-LISTENER] no response after 6s — speaking recovery")
                try:
                    await _on_grok_text(
                        "I'm sorry, give me just a moment. "
                        "I'm having a little trouble processing right now. "
                        "Could you say that again?"
                    )
                except Exception as _re:
                    logger.warning("Recovery TTS failed: %s", _re)

        try:
            async for raw in grok_ws:
                try:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                et = ev.get("type", "")
                _grok_event_count += 1
                if _grok_event_count <= 10 or _grok_event_count % 50 == 0:
                    print(f"[GROK-LISTENER] event #{_grok_event_count}: {et}")
                # SOVEREIGN-VOICE — barge-in: stop TTS + reopen mic when caller speaks
                if et == "input_audio_buffer.speech_started" and _nate_speaking:
                    _tts_cancel.set()
                    _nate_speaking = False
                    print("[VOICE] barge-in: caller speech_started")
                if et in (
                    "response.output_text.delta",
                    "response.output_audio.delta",
                    "response.output_audio_transcript.delta",
                    "response.audio.delta",
                    "response.audio_transcript.delta",
                    "ping",
                ):
                    continue
                if et == "error":
                    logger.warning("Grok realtime error event: %s", ev)
                    _err_msg = ev.get("error", {}).get("message", "")
                    if "unavailable" in _err_msg.lower() or "did not respond" in _err_msg.lower():
                        print("[GROK-LISTENER] model unavailable — waiting for retry before recovery")
                        _got_text_after_error = False
                        if _recovery_timer and not _recovery_timer.done():
                            _recovery_timer.cancel()
                        _recovery_timer = asyncio.create_task(_delayed_recovery())
                    continue
                txt = _extract_assistant_text(ev)
                if txt:
                    print(f"[GROK-LISTENER] got text ({len(txt)} chars): {txt[:80]}")
                    _got_text_after_error = True
                    if _recovery_timer and not _recovery_timer.done():
                        _recovery_timer.cancel()
                        _recovery_timer = None
                    eid = ev.get("event_id")
                    if eid:
                        if eid in seen_grok_event_ids:
                            continue
                        seen_grok_event_ids.add(eid)
                    await _on_grok_text(txt)
                user_txt = _extract_user_text(ev)
                if user_txt:
                    print(f"[VOICE-USER] '{user_txt[:120]}'")
                    user_turns.append({"text": user_txt, "ts": datetime.now(timezone.utc).isoformat()})
                    # SOVEREIGN-VOICE — GA hardening: detection-only bridge sweep (flag-gated)
                    if _SB_VOICE_SWEEP and session_username and ctx.get("db_pool"):
                        try:
                            from app.services.sensitive_clinical_bridge import schedule_detection_only
                            schedule_detection_only(
                                db_pool=ctx["db_pool"], user_id=session_username,
                                message=user_txt, source="voice_call",
                            )
                        except Exception as _sb_v_e:
                            print(f"[SB-SWEEP] voice sweep skipped (non-fatal): {_sb_v_e}")
                    # SOVEREIGN-VOICE — SI/violence coach alert + risk window + spoken resources
                    if session_username and ctx.get("db_pool"):
                        try:
                            from app.services.voice_si_crisis_hook import schedule_voice_si_crisis

                            async def _speak_crisis_line(text: str) -> None:
                                await _on_grok_text(text)

                            schedule_voice_si_crisis(
                                ctx["db_pool"],
                                session_username,
                                user_txt,
                                ctx.get("profile"),
                                speak_fn=_speak_crisis_line,
                            )
                        except Exception as _si_v_e:
                            print(f"[VOICE-SI] skipped (non-fatal): {_si_v_e}")
                        # QUANTUM-CRYSTAL-ARCH — Principal-Review crisis Guides (SI/HI turn_class)
                        try:
                            from app.services.voice_pr_crisis_inject import (
                                schedule_voice_pr_crisis_inject,
                            )
                            schedule_voice_pr_crisis_inject(
                                grok_ws, ctx["db_pool"], user_txt,
                                username=session_username,
                            )
                        except Exception as _pr_v_e:
                            print(f"[VOICE-PR-CRISIS] skipped (non-fatal): {_pr_v_e}")
                    if _bc_engine and not _bc_engine._enabled and _greeting_spoken:
                        _bc_engine.enable()
                        print("[BACKCHANNEL] enabled after first user speech")
                    if voice_crystallization_enabled:
                        asyncio.create_task(_record_ec_snapshot("turn"))
                    # SOVEREIGN-VOICE — identity probe + VAD pace update
                    if _voice_sync and grok_ws is not None:
                        await _voice_sync.apply_user_turn(grok_ws, user_txt)

                    if _is_memory_query(user_txt) and _search_dedup.should_search(user_txt) and session_username and ctx.get("db_pool"):
                        print(f"[VOICE-DEEP-SEARCH] memory query detected: '{user_txt[:80]}'")
                        try:
                            global _memory_filler_idx
                            filler_phrase = _MEMORY_FILLER_PHRASES[_memory_filler_idx % len(_MEMORY_FILLER_PHRASES)]
                            _memory_filler_idx += 1
                            filler_task = asyncio.create_task(
                                _synthesize_with_fallback(filler_phrase, "connect", xtts_to_mulaw_state)
                            )
                            search_task = asyncio.create_task(
                                _deep_memory_search(session_username, user_txt, ctx["db_pool"])
                            )
                            filler_audio = await filler_task
                            if filler_audio:
                                await _send_mulaw_to_twilio(filler_audio)

                            memory_context = await search_task
                            if memory_context:
                                await _inject_memory_context(grok_ws, session_username, memory_context)
                            else:
                                print("[VOICE-DEEP-SEARCH] no results — Grok will respond with existing context")
                        except Exception as e:
                            logger.warning("Deep memory search pipeline failed (non-fatal): %s", e)

                    elif _is_web_search_query(user_txt) and _web_search_dedup.should_search(user_txt) and session_username:
                        print(f"[VOICE-WEB-SEARCH] web query detected: '{user_txt[:80]}'")
                        try:
                            global _web_filler_idx
                            wfiller = _WEB_SEARCH_FILLER_PHRASES[_web_filler_idx % len(_WEB_SEARCH_FILLER_PHRASES)]
                            _web_filler_idx += 1
                            wfiller_task = asyncio.create_task(
                                _synthesize_with_fallback(wfiller, "connect", xtts_to_mulaw_state)
                            )
                            wsearch_task = asyncio.create_task(
                                _web_search(user_txt, session_username)
                            )
                            wfiller_audio = await wfiller_task
                            if wfiller_audio:
                                await _send_mulaw_to_twilio(wfiller_audio)

                            web_context = await wsearch_task
                            if web_context:
                                await _inject_web_context(grok_ws, session_username, web_context)
                            else:
                                print("[VOICE-WEB-SEARCH] no results — Grok will respond naturally")
                        except Exception as e:
                            logger.warning("Web search pipeline failed (non-fatal): %s", e)

                    # QUANTUM-CRYSTAL-ARCH: mid-call clinical directory / care-plan assist
                    elif (
                        os.getenv("ENABLE_CLINICAL_TECHNIQUE_DIRECTORY", "").lower()
                        in ("true", "1", "yes")
                        and session_username
                        and ctx.get("db_pool")
                    ):
                        try:
                            from app.services.clinical_technique_directory import (
                                directory_context_for_surface,
                                is_care_plan_request,
                                wants_web_enrichment,
                            )
                            if is_care_plan_request(user_txt) or wants_web_enrichment(user_txt):
                                print(f"[VOICE-CLINICAL-DIR] care-plan/enrich: '{user_txt[:80]}'")
                                _vdir = await directory_context_for_surface(
                                    user_txt,
                                    db_pool=ctx["db_pool"],
                                    user_id=session_username,
                                    search_proxy=_get_voice_search_proxy(),
                                    suggest_plan=True,
                                    allow_web=True,
                                    max_techniques=3,
                                )
                                if _vdir:
                                    await _inject_memory_context(
                                        grok_ws,
                                        session_username,
                                        "[CLINICAL DIRECTORY / CARE PLAN]\n" + _vdir,
                                    )
                        except Exception as e:
                            logger.warning("Voice clinical directory inject failed (non-fatal): %s", e)
                    # QUANTUM-CRYSTAL-ARCH — mid-call sandbox candidates when directory off
                    elif (
                        os.getenv("ENABLE_LN_SANDBOX", "").lower()
                        in ("true", "1", "yes", "on")
                        and session_username
                        and ctx.get("db_pool")
                    ):
                        try:
                            from app.services.ln_sandbox_context import (
                                get_sandbox_candidates_for_user,
                            )
                            _vsb = await get_sandbox_candidates_for_user(
                                ctx["db_pool"], session_username, max_items=2
                            )
                            if _vsb:
                                await _inject_memory_context(
                                    grok_ws,
                                    session_username,
                                    "[LN SANDBOX CANDIDATES]\n" + _vsb,
                                )
                        except Exception as e:
                            logger.warning("Voice sandbox inject failed (non-fatal): %s", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Grok listener ended: %s", e)
        finally:
            if _recovery_timer and not _recovery_timer.done():
                _recovery_timer.cancel()
        print(f"[GROK-LISTENER] exited (total events={_grok_event_count})")

    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            raw = None
            if "text" in msg and msg["text"] is not None:
                raw = msg["text"]
            elif "bytes" in msg and msg["bytes"] is not None:
                b = msg["bytes"]
                raw = (
                    bytes(b).decode("utf-8", errors="replace")
                    if isinstance(b, (bytes, bytearray, memoryview))
                    else str(b)
                )
            if not (raw or "").strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = data.get("event", "")

            if event == "connected":
                print("[TWILIO-GROK-XTTS] Twilio connected (pipeline idle until start)")

            elif event == "start":
                start_data = data.get("start") or {}
                stream_sid = start_data.get("streamSid") or stream_sid
                csid = start_data.get("callSid", "")
                if csid:
                    ctx["twilio_call_sid"] = csid
                    session_call_sid = csid
                custom = _twilio_stream_custom_parameters(start_data)
                for k, v in custom.items():
                    ks = str(k)
                    if ks == "max_call_seconds":
                        try:
                            ctx["max_call_seconds"] = int(v)
                        except (TypeError, ValueError):
                            pass
                    else:
                        ctx[ks] = v
                await _hydrate_call_context_from_redis(ctx)
                uname = (ctx.get("username") or ctx.get("user_id") or ctx.get("voice_billing_user_id") or "").strip()
                if uname:
                    ctx["username"] = uname
                    session_username = uname

                # SOVEREIGN-VOICE — coach-requested check-in: resolve callback ANI → task
                try:
                    if not ctx.get("coach_checkin_task_id") and ctx.get("db_pool"):
                        from app.services.coach_nate_checkin_service import CoachNateCheckinService
                        _ck = CoachNateCheckinService(ctx.get("db_pool"), ctx.get("app_state"))
                        _from = (ctx.get("from_number") or ctx.get("caller") or ctx.get("phone") or "").strip()
                        if _from:
                            _task = await _ck.resolve_inbound_by_phone(_from)
                            if _task:
                                ctx["coach_checkin_task_id"] = int(_task["id"])
                                ctx["is_callback"] = True
                                ctx["username"] = _task.get("client_username") or uname
                                uname = ctx["username"]
                                session_username = uname
                except Exception as _cke:
                    logger.debug("coach checkin inbound resolve: %s", _cke)

                # Patent 11: init Neural Mirror now that username is known
                if NeuralMirrorSession and session_username and not _neural_mirror:
                    try:
                        _neural_mirror = NeuralMirrorSession(
                            user_id=session_username,
                            session_id=session_call_sid or str(uuid.uuid4()),
                            sample_rate=8000,
                        )
                    except Exception as _nme:
                        logger.debug("NeuralMirrorSession init failed: %s", _nme)

                # --- session lifecycle: acquire slot ---
                try:
                    from app.services.voice_capacity import acquire_voice_slot, get_active_voice_count

                    acq = await acquire_voice_slot(session_call_sid or "unknown")
                    if acq:
                        slot_acquired = True
                        active = await get_active_voice_count()
                        print(f"[VOICE-SESSION] slot acquired (active={active})")
                    else:
                        print("[VOICE-SESSION] slot NOT acquired (at capacity) — proceeding anyway")
                except Exception as e:
                    logger.warning("voice slot acquire failed (non-fatal): %s", e)

                session_start = time.monotonic()
                if voice_crystallization_enabled:
                    if ec_task and not ec_task.done():
                        ec_task.cancel()
                    ec_task = asyncio.create_task(_rolling_ec_loop())
                    asyncio.create_task(_record_ec_snapshot("start"))

                _voice_db = ctx.get("db_pool")
                # SOVEREIGN-VOICE — coach check-in uses cold/warm prompt (PHI gated)
                _coach_ck_prompt = None
                if ctx.get("coach_checkin_task_id") and _voice_db:
                    try:
                        from app.services.coach_nate_checkin_service import CoachNateCheckinService
                        _cksvc = CoachNateCheckinService(_voice_db, ctx.get("app_state"))
                        _coach_ck_prompt = await _cksvc.pipeline_bootstrap_prompt(ctx)
                        await _cksvc.maybe_start_voice_recheck(ctx, session_call_sid or "", _voice_db)
                    except Exception as _cke2:
                        logger.warning("coach checkin prompt: %s", _cke2)
                if _coach_ck_prompt:
                    instructions = _coach_ck_prompt
                    _session_crystal_scopes = []
                elif _voice_db and uname:
                    try:
                        instructions, _session_crystal_scopes = await _build_grounded_voice_prompt(
                            uname, _voice_db
                        )
                    except Exception as e:
                        logger.warning("Grounded voice prompt failed, using default: %s", e)
                        instructions = _default_phone_instructions(uname)
                        _session_crystal_scopes = []
                else:
                    instructions = _default_phone_instructions(uname)
                if grok_task and not grok_task.done():
                    grok_task.cancel()
                    try:
                        await grok_task
                    except asyncio.CancelledError:
                        pass
                if grok_ws is not None:
                    try:
                        await grok_ws.close()
                    except Exception:
                        pass
                    grok_ws = None
                mulaw_to_pcm_state.clear()
                xtts_to_mulaw_state.clear()
                _spoken_response_ids.clear()
                # Patent 11: Neural Mirror prompt injection
                if _neural_mirror:
                    nm_injection = _neural_mirror.get_prompt_injection()
                    if nm_injection:
                        instructions += "\n\n" + nm_injection
                # SOVEREIGN-VOICE — identity / pace / avatar sync session
                _voice_sync, instructions = await attach_voice_sync(
                    ctx, session_call_sid or "", uname or "", instructions
                )
                try:
                    print(f"[VOICE-MEMORY] instructions length={len(instructions)} chars")
                    print(f"[VOICE-MEMORY] instructions preview: {instructions[-300:]}")
                    _sil = _voice_sync.silence_ms() if _voice_sync else 700
                    grok_ws = await _open_grok_session(instructions, silence_duration_ms=_sil)
                    grok_task = asyncio.create_task(grok_listener())
                    # Backchannel stays DISABLED until after Grok's first response
                    print(
                        f"[TWILIO-GROK-XTTS] Grok session started streamSid={stream_sid} user={uname!r}"
                    )
                    # Start call duration limit timer
                    if ctx.get("max_call_seconds") and not _call_limit_task:
                        _call_limit_task = asyncio.create_task(_enforce_call_limit())
                    # Greeting handled by Polly TwiML <Say> before stream connects.
                    # Grok listens passively until the caller speaks.
                except Exception as e:
                    logger.error("Failed to open Grok Realtime: %s", e, exc_info=True)
                    grok_ws = None

            elif event == "media":
                _media_chunk_count += 1
                if _media_chunk_count <= 3 or _media_chunk_count % 200 == 0:
                    print(f"[TWILIO-GROK-XTTS] media chunk #{_media_chunk_count} grok_ws={'open' if grok_ws is not None else 'NONE'}")
                if grok_ws is None:
                    continue
                payload = (data.get("media") or {}).get("payload", "")
                if not payload:
                    continue
                try:
                    mulaw_chunk = base64.b64decode(payload)
                except Exception:
                    continue
                pcm_chunk = twilio_mulaw_to_pcm16(mulaw_chunk, mulaw_to_pcm_state)
                if not pcm_chunk:
                    if _media_chunk_count <= 3:
                        print(f"[TWILIO-GROK-XTTS] pcm_chunk empty for media #{_media_chunk_count}")
                    continue

                # Patent 8: Turn detection on mulaw audio (backchannel DISABLED)
                chunk_energy = sum(abs(b - 0xFF) for b in mulaw_chunk) / max(len(mulaw_chunk), 1)
                is_speech = chunk_energy > 45
                if _turn_detector or _neural_mirror:
                    if _turn_detector:
                        _turn_detector.on_audio_frame(chunk_energy, is_speech, _media_chunk_count * 20.0)
                    if _neural_mirror and is_speech:
                        mirror_state = _neural_mirror.on_audio_chunk(mulaw_chunk)
                    # Backchannel clips disabled — causes double-talk collisions
                # SOVEREIGN-VOICE — local barge-in: after playback starts, skip 1.8s echo
                # grace, then require ~200ms sustained louder speech (not speaker bleed).
                if _nate_speaking and _tts_playback_started and is_speech:
                    age = time.monotonic() - _tts_playback_t0
                    loud = chunk_energy > 70
                    if age >= 1.8 and loud:
                        _barge_speech_frames += 1
                        if _barge_speech_frames >= 10:
                            _tts_cancel.set()
                            _nate_speaking = False
                            _barge_speech_frames = 0
                            print("[VOICE] barge-in: local energy")
                    else:
                        _barge_speech_frames = 0
                else:
                    _barge_speech_frames = 0
                if _voice_sync and pcm_chunk:  # SOVEREIGN-VOICE
                    _voice_sync.feed_audio(pcm_chunk)

                if not _nate_speaking:
                    try:
                        await grok_ws.send(
                            json.dumps(
                                {
                                    "type": "input_audio_buffer.append",
                                    "audio": base64.b64encode(pcm_chunk).decode("ascii"),
                                }
                            )
                        )
                    except Exception as e:
                        logger.warning("Grok append failed: %s", e)

            elif event == "stop":
                print("[TWILIO-GROK-XTTS] Twilio stream stopped")
                break

    finally:
        # --- session lifecycle: cleanup ---
        duration_s = 0.0
        if session_start:
            duration_s = time.monotonic() - session_start

        if _call_limit_task and not _call_limit_task.done():
            _call_limit_task.cancel()
            try:
                await _call_limit_task
            except asyncio.CancelledError:
                pass
        if grok_task and not grok_task.done():
            grok_task.cancel()
            try:
                await grok_task
            except asyncio.CancelledError:
                pass
        if grok_ws is not None:
            try:
                await grok_ws.close()
            except Exception:
                pass
        if ec_task and not ec_task.done():
            ec_task.cancel()
            try:
                await ec_task
            except asyncio.CancelledError:
                pass

        if slot_acquired:
            try:
                from app.services.voice_capacity import release_voice_slot

                await release_voice_slot(session_call_sid or "unknown")
                print(f"[VOICE-SESSION] slot released call_sid={session_call_sid}")
            except Exception as e:
                logger.warning("voice slot release failed: %s", e)

        if duration_s >= 1 and session_username:
            db_pool = ctx.get("db_pool")
            minutes = duration_s / 60.0
            user_uuid = None

            if db_pool:
                try:
                    from app.services.voice_metering import add_voice_minutes

                    user_uuid = await _resolve_user_uuid(session_username, db_pool)
                    if user_uuid:
                        await add_voice_minutes(db_pool, user_uuid, minutes)
                        print(
                            f"[VOICE-SESSION] logged {minutes:.1f}min ({int(duration_s)}s) for {session_username}"
                        )
                    else:
                        logger.warning("voice minutes: could not resolve UUID for %s", session_username)
                except Exception as e:
                    logger.warning("voice minutes logging failed: %s", e)

                # SOVEREIGN-VOICE — hybrid: persist assistant turns even if STT missed user side
                if assistant_turns and not user_turns:
                    user_turns.append({
                        "text": "[voice audio — transcript unavailable; call may have dropped]",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })

                if _crystal_forge and user_turns and assistant_turns:
                    try:
                        from app.services.vectorize_service import index_conversation as _vec_index
                    except ImportError:
                        _vec_index = None
                    try:
                        _pair_n = min(len(user_turns), len(assistant_turns))
                        for _ci in range(_pair_n):
                            _u = user_turns[_ci].get("text", "")
                            _a = assistant_turns[_ci].get("text", "")
                            if _u and len(_u) >= 40:
                                # QUANTUM-CRYSTAL-ARCH — Phase 5b: light verifier on voice reply
                                try:
                                    from app.services.therapeutic_controller import (
                                        light_symbolic_post_audit as _lspa_v,
                                    )
                                    _a = await _lspa_v(
                                        _a, user_text=_u, user_id=session_username,
                                        db_pool=db_pool,
                                        crystal_scopes=_session_crystal_scopes,
                                    )
                                except Exception:
                                    pass
                                await _crystal_forge(
                                    db_pool, session_username, _u, _a,
                                    user_name=session_username,
                                    domain="clinical",
                                    origin_surface="voice_call",
                                )
                                # QUANTUM-CRYSTAL-ARCH — PGSD voice finalize notify
                                try:
                                    from app.services.pgsd_triggers import notify_user as _pgsd_n
                                    _pgsd_n(session_username, source="voice_call")
                                except Exception:
                                    pass
                                # QUANTUM-CRYSTAL-ARCH: skill-plan tick (voice)
                                try:
                                    from app.services.cycle_skill_plan_service import schedule_skill_plan_post_turn as _sk_tick
                                    _sk_tick(db_pool, user_id=session_username, user_text=_u, nate_response=_a, user_name=session_username, origin_surface="voice_call")
                                except Exception:
                                    pass
                                # QUANTUM-CRYSTAL-ARCH: Phase 1 commitment extract (voice)
                                try:
                                    from app.services.nate_commitment_extractor import (
                                        schedule_post_turn_extraction,
                                    )
                                    schedule_post_turn_extraction(
                                        db_pool,
                                        username=session_username,
                                        hardware_id=session_username,
                                        user_text=_u,
                                    )
                                except Exception:
                                    pass
                                if _vec_index:
                                    try:
                                        await _vec_index(
                                            user_id=session_username,
                                            record_id=f"voice_{session_call_sid or 'call'}_{_ci}",
                                            user_text=_u[:4000],
                                            ai_text=_a[:4000],
                                            session_id=session_call_sid or "",
                                            timestamp=datetime.now(timezone.utc).isoformat(),
                                        )
                                    except Exception as _ve:
                                        logger.debug("voice crystal vectorize upsert: %s", _ve)
                    except Exception as e:
                        logger.warning("voice lightweight crystal forge failed: %s", e)

                # SOVEREIGN-VOICE: enrich crystals with voice session metadata
                if session_username and duration_s > 10:
                    try:
                        from app.sse.voice_crystal_enricher import enrich_crystals_from_voice
                        await enrich_crystals_from_voice(
                            session_call_sid or "unknown", session_username, duration_s, db_pool)
                    except Exception as _vce:
                        logger.warning("voice crystal enricher: %s", _vce)

                if voice_crystallization_enabled:
                    try:
                        from app.services.vectorize_service import index_conversation

                        asyncio.create_task(_record_ec_snapshot("final"))
                        pair_count = min(len(user_turns), len(assistant_turns))
                        async with db_pool.acquire() as conn:
                            for i in range(pair_count):
                                u = user_turns[i]["text"]
                                a = assistant_turns[i]["text"]
                                if not u and not a:
                                    continue
                                await conn.execute(
                                    """
                                    INSERT INTO conversation_history
                                        (user_id, session_id, user_text, ai_text, created_at)
                                    VALUES ($1, $2, $3, $4, NOW())
                                    ON CONFLICT DO NOTHING
                                    """,
                                    session_username,
                                    session_call_sid or "",
                                    u[:4000],
                                    a[:4000],
                                )
                                try:
                                    await index_conversation(
                                        user_id=session_username,
                                        record_id=f"{session_call_sid or 'call'}_{i}",
                                        user_text=u[:4000],
                                        ai_text=a[:4000],
                                        session_id=session_call_sid or "",
                                        timestamp=datetime.now(timezone.utc).isoformat(),
                                    )
                                except Exception as vz_err:
                                    logger.warning("voice conversation vectorize failed: %s", vz_err)

                                for insight in _detect_therapeutic_insights(u, a):
                                    _app_state = ctx.get("app_state")
                                    _crystallizer = getattr(_app_state, "nate_memory_crystallizer", None) if _app_state else None
                                    if _crystallizer is not None:
                                        _crystallizer._harvest_buffer.append(
                                            {
                                                "text": insight,
                                                "source": "voice_call",
                                                "domain": "clinical",
                                                "scope": f"user:{session_username}",
                                                "created_at": datetime.now(timezone.utc),
                                            }
                                        )

                            if user_uuid:
                                for profile, count in filler_counts.items():
                                    for _ in range(count):
                                        await conn.execute(
                                            """
                                            INSERT INTO voice_filler_events
                                                (user_uuid, call_sid, filler_profile, filler_hash, played_at)
                                            VALUES ($1, $2, $3, $4, NOW())
                                            """,
                                            user_uuid,
                                            session_call_sid or "unknown",
                                            profile,
                                            profile,
                                        )
                                await conn.execute(
                                    """
                                    INSERT INTO voice_session_biometrics
                                        (user_uuid, call_sid, payload, created_at)
                                    VALUES ($1, $2, $3::jsonb, NOW())
                                    """,
                                    user_uuid,
                                    session_call_sid or "unknown",
                                    json.dumps(
                                        {
                                            "ec_snapshots": ec_snapshots[-30:],
                                            "turn_count_user": len(user_turns),
                                            "turn_count_assistant": len(assistant_turns),
                                            "filler_counts": filler_counts,
                                        }
                                    ),
                                )
                        _app_state = ctx.get("app_state")
                        _orch = getattr(_app_state, "quantum_crystal_orchestrator", None) if _app_state else None
                        if _orch and user_turns:
                            _voice_hits = [
                                {
                                    "content_hash": f"{session_call_sid or 'call'}_{idx}",
                                    "text": (t.get("text") or "")[:160],
                                    "confidence": 0.7,
                                }
                                for idx, t in enumerate(user_turns[:6])
                                if t.get("text")
                            ]
                            if _voice_hits:
                                await _orch.record_co_activation_from_hits(
                                    _voice_hits,
                                    source="voice_crystallization",
                                    call_sid=session_call_sid,
                                )
                    except Exception as e:
                        logger.warning("voice transcript crystallization failed: %s", e)

            # Patent 11: finalize Neural Mirror session and store EEG trace
            if _neural_mirror and db_pool:
                try:
                    nm_summary = _neural_mirror.finalize()
                    if nm_summary.get("n_samples", 0) > 0:
                        _nm_session_uuid = None
                        try:
                            _nm_session_uuid = uuid.UUID(session_call_sid) if session_call_sid else None
                        except (ValueError, AttributeError):
                            pass
                        await db_pool.execute(
                            "INSERT INTO virtual_eeg_traces "
                            "(user_id, session_id, nevedal_factors, tunneling_events, "
                            "duration_seconds, created_at) "
                            "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, NOW())",
                            session_username,
                            _nm_session_uuid,
                            json.dumps(nm_summary.get("mean_nevedal_factors", {})),
                            json.dumps(nm_summary.get("tunneling_events", [])),
                            nm_summary.get("duration_s", 0.0),
                        )
                        fp_data = nm_summary.get("fingerprint", {})
                        if fp_data.get("calibrated"):
                            await db_pool.execute(
                                "INSERT INTO neural_fingerprints "
                                "(user_id, mean_vector, n_samples, calibrated, updated_at) "
                                "VALUES ($1, $2::jsonb, $3, $4, NOW()) "
                                "ON CONFLICT (user_id) DO UPDATE SET "
                                "mean_vector = EXCLUDED.mean_vector, "
                                "n_samples = EXCLUDED.n_samples, "
                                "calibrated = EXCLUDED.calibrated, "
                                "updated_at = NOW()",
                                session_username,
                                json.dumps(fp_data.get("mean_vector")),
                                fp_data.get("n_samples", 0),
                                True,
                            )
                except Exception as _nm_err:
                    logger.debug("Neural Mirror finalize: %s", _nm_err)

            # SOVEREIGN-VOICE — hybrid resume + PAUSED arm; clear call_context
            try:
                from app.services.voice_hybrid_resume import finalize_hybrid_on_call_end

                await finalize_hybrid_on_call_end(
                    db_pool,
                    username=session_username,
                    call_sid=session_call_sid or "",
                    ctx=ctx,
                    user_turns=user_turns,
                    assistant_turns=assistant_turns,
                )
            except Exception as _hy_e:
                logger.warning("hybrid resume finalize: %s", _hy_e)
                try:
                    from app.services.api_server import _get_auth_redis

                    redis = await _get_auth_redis()
                    if redis and session_call_sid:
                        await redis.delete(f"nate:call_context:{session_call_sid}")
                except Exception:
                    pass

            # SOVEREIGN-VOICE — finalize identity enrollment + avatar idle
            if _voice_sync:
                try:
                    await _voice_sync.finalize()
                except Exception as _vs_f:
                    logger.debug("VoiceCallSync finalize: %s", _vs_f)

        print(f"[TWILIO-GROK-XTTS] session closed — {duration_s:.0f}s")


def use_grok_xtts_pipeline() -> bool:
    v = os.getenv("TWILIO_VOICE_PIPELINE", "").strip().lower()
    return v in ("grok_xtts", "grok+xtts", "azure_realtime", "1", "true", "yes")


def grok_xtts_configured() -> bool:
    # SOVEREIGN-VOICE: Azure Foundry is the voice provider
    return bool(os.getenv("AZURE_API_KEY", "").strip()) and bool(_AZ_REALTIME_URL)
