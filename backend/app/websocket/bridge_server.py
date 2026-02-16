import asyncio
import fcntl
import re
import websockets
import json
import random
import datetime
import os
import shutil
import secrets
import hashlib
import hmac
import uuid
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# Secure logging with PII auto-redaction
try:
    from app.secure_logger import get_secure_logger
    secure_log = get_secure_logger("bridge_server.secure")
except Exception:
    import logging as _logging
    secure_log = _logging.getLogger("bridge_server")

# NOTE:
# - In production, this module is executed as `python -m app.websocket.bridge_server`
# - In local dev, it is sometimes run directly (`python bridge_server.py`)
# So we support both import styles.
try:
    from .nevedal_handlers import NevedalHandler
    from .sanctuary_engine import FamilySanctuaryEngine
    from .bridge_handlers_v2 import CoachNexusV2
    from .device_protection import (
        handle_device_validation,
        get_user_devices,
        remove_device,
        force_logout_all_devices,
        get_device_limit,
        admin_get_user_devices,
        admin_reset_user_devices,
        detect_suspicious_activity,
    )
except Exception:
    from nevedal_handlers import NevedalHandler
    from sanctuary_engine import FamilySanctuaryEngine
    from bridge_handlers_v2 import CoachNexusV2
    from device_protection import (
        handle_device_validation,
        get_user_devices,
        remove_device,
        force_logout_all_devices,
        get_device_limit,
        admin_get_user_devices,
        admin_reset_user_devices,
        detect_suspicious_activity,
    )

# Optional Night School modules (bridge should run without them)
NightSchoolCurriculum = None
NightSchoolHandler = None
try:
    from .night_school_curriculum import NightSchoolCurriculum  # type: ignore
except Exception as e:
    try:
        from night_school_curriculum import NightSchoolCurriculum  # type: ignore
    except Exception:
        NightSchoolCurriculum = None
        print(f"[!] night_school_curriculum not found - curriculum disabled ({e})")

try:
    from .night_school_handlers import NightSchoolHandler  # type: ignore
except Exception as e:
    try:
        from night_school_handlers import NightSchoolHandler  # type: ignore
    except Exception:
        NightSchoolHandler = None
        print(f"[!] night_school_handlers not found - Dojo disabled ({e})")

# Avatar handler for Top Tier voice-driven avatar interactions
try:
    from .avatar_handlers import AvatarHandler, create_avatar_handler  # type: ignore
except Exception as e:
    try:
        from avatar_handlers import AvatarHandler, create_avatar_handler  # type: ignore
    except Exception:
        AvatarHandler = None
        create_avatar_handler = None
        print(f"[!] avatar_handlers not found - Avatar mode disabled ({e})")

# Optional: Local workbook retrieval for best-practice therapeutic guidance
try:
    from app.services.workbook_library import WorkbookLibrary
except Exception:
    WorkbookLibrary = None

# Address validation service
validate_address = None
try:
    from app.services.address_validator import validate_address  # type: ignore
except Exception:
    try:
        from address_validator import validate_address  # type: ignore
    except Exception:
        print("[!] address_validator not found - USPS validation disabled")

# Classroom analyzer for coach session review
try:
    from app.services.classroom_analyzer import (
        ClassroomAnalyzer,
        VTTParser,
        MetricsExtractor,
        ANALYSIS_SYSTEM_PROMPT,
        build_analysis_prompt,
    )
except Exception:
    ClassroomAnalyzer = None
    VTTParser = None
    MetricsExtractor = None
    ANALYSIS_SYSTEM_PROMPT = None
    build_analysis_prompt = None


# ==============================================================================
# SOVEREIGN BRIDGE v16.1: COMPLETE EDITION + ALL HANDLERS
# Full metrics, session tracking, e-commerce support, coach features
# ==============================================================================

# ------------------------------------------------------------------------------
# PART 1: INFRASTRUCTURE & CONFIGURATION
# ------------------------------------------------------------------------------
HOST = "0.0.0.0"
PORT = int(os.environ.get("WEBSOCKET_PORT", "8765"))
REQUIRED_CONSENT_VERSION = "v13.0_2026"

# Database pool — created in main(), used by NateNudge + AI Mode handlers
db_pool = None

# Bridge context — holds vault_bridge for B5 chat-integrated file interactions
class _BridgeContext:
    vault_bridge = None
bridge_context = _BridgeContext()

# Phase 8: Hive Defense reference — injected from main.py via set_hive_defense()
_hive_defense_ref = None

def set_hive_defense(hive_dict):
    """Called from main.py lifespan to share the Hive Defense services with the bridge."""
    global _hive_defense_ref
    _hive_defense_ref = hive_dict

# Nate Organizer singleton — lazily created when first organize_* message arrives
_organizer_mode_instance = None

def _get_or_create_organizer(pool):
    """Get or create the OrganizerMode singleton for document organization."""
    global _organizer_mode_instance
    if _organizer_mode_instance is None:
        if pool is None:
            raise RuntimeError("Database pool not available for Organizer")
        _azure_ep = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        _azure_key = os.getenv("AZURE_API_KEY", "")
        _azure_deploy = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        if not _azure_ep or not _azure_key:
            raise RuntimeError("Azure OpenAI credentials not configured for Organizer")
        try:
            from .vault_bridge import VaultBridge  # noqa: F401 — validate vault is importable
            from app.services.vault.document_organizer import OrganizerMode
        except ImportError:
            from app.services.vault.document_organizer import OrganizerMode
        _organizer_mode_instance = OrganizerMode(
            db_pool=pool,
            azure_endpoint=f"https://{_azure_ep}" if not _azure_ep.startswith("http") else _azure_ep,
            azure_api_key=_azure_key,
            deployment=_azure_deploy,
        )
    return _organizer_mode_instance

# PostgreSQL-backed user store (replaces JSON file registry)
_pg_user_store = None        # UserStore instance, initialized in main()
_registry_cache = {}         # In-memory cache of the full registry dict
_use_pg_registry = os.environ.get("USE_POSTGRES_REGISTRY", "true").lower() in ("true", "1", "yes")

# Load Environment Variables
try:
    from dotenv import load_dotenv
    script_dir = Path(__file__).resolve().parent
    # Allow importing `app.*` modules when running this file directly.
    backend_dir = script_dir.parents[2]  # .../backend
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    master_env = script_dir.parent / '.env'
    if not master_env.exists(): master_env = script_dir / '.env'
    load_dotenv(dotenv_path=master_env, override=True)
except ImportError: pass

AZURE_API_KEY = os.getenv("AZURE_API_KEY")
BETA_INVITE_CODE = os.getenv("BETA_INVITE_CODE", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "https://app.sovereignsanctuary.net")
_ep = os.getenv("AZURE_OPENAI_ENDPOINT", "").replace("https://", "").replace("wss://", "").replace("/", "")
AZURE_ENDPOINT = f"wss://{_ep}/openai/realtime?api-version=2024-10-01-preview&deployment={os.getenv('AZURE_OPENAI_DEPLOYMENT', 'gpt-4o-realtime-preview')}"

# --- Azure startup validation ---
if not AZURE_API_KEY:
    print(">>> [WARNING] AZURE_API_KEY is not set! Little Nate AI will NOT be able to respond.")
if not _ep:
    print(">>> [WARNING] AZURE_OPENAI_ENDPOINT is not set! Azure endpoint is invalid.")
    print(f">>>   Current AZURE_ENDPOINT = {AZURE_ENDPOINT}")
else:
    print(f">>> [AZURE] Endpoint configured: wss://{_ep[:30]}...")

# =============================================================================
# HELP & FAQ SYSTEM PROMPTS — Platform Guide Mode (NOT therapy)
# =============================================================================
CLIENT_HELP_SYSTEM_PROMPT = """You are Little Nate, the platform guide for Sovereign Sanctuary. You are NOT in therapy mode. You are a friendly, knowledgeable guide who helps users navigate the app and understand its features.

IMPORTANT: Keep answers concise (2-4 sentences when possible). Be warm but direct. Use plain language.

CLIENT FEATURES YOU KNOW ABOUT:

MAIN SCREEN:
- Chat with Little Nate via text input at the bottom of the screen
- Microphone icon for voice input (speech-to-text)
- Metrics bar at the top showing C_emo, GAP, Quantum, and current mood — tap for full details
- Avatar Mode toggle (Sovereign Circle only) — shows a 3D animated Nate with expressions
- Family Sanctuary button — for shared family sessions (Sovereign Circle only)
- Settings gear icon in the top right

VOICE COMMANDS:
- "send message" / "send it" / "send" — sends the current draft
- "clear message" / "delete message" / "start over" — clears the draft
- "delete last sentence" / "undo that" — removes last sentence
- "delete last word" — removes last word
- "read it back" / "read draft" — reads draft aloud
- "replace [text] with [text]" — inline text replacement
- "select [text]" — selects specific text
- "read sentence [number]" — reads a specific sentence

METRICS EXPLAINED:
- C_emo (Coherent Emotional Engagement): measures alignment of emotional state, 0-1 scale
- GAP: growth and awareness potential
- Quantum: depth of emotional processing
- Mood tracking with history chart
- Session stats: total sessions, breakthroughs, token usage/balance

SUBSCRIPTION TIERS:
- Threshold (Trial): Basic AI companion access
- Inner Chamber ($49/month): Full text and voice access to Little Nate
- Sovereign Circle ($149/month): Everything plus Avatar Mode, Family Sanctuary, family invites, priority support

SETTINGS (accessible via gear icon):
- Profile: Edit email, phone, emergency contact, timezone
- Share: Invite a Friend via text message
- Family: Invite family members (Sovereign Circle only) — Spouse (free), 1st Dependent (free), Additional ($75/month)
- Subscription: View plan, token balance, monthly usage
- Preferences: Push notifications, session reminders, crisis alerts, voice mode default
- Legal & Privacy: Full terms, privacy policy, and waivers
- About & Support: App version, this Help & FAQ, contact support
- Account: Delete account (30-day recovery window), Logout

FAMILY SANCTUARY (Sovereign Circle):
- Head of Household invites family members
- Shared family sessions with Little Nate
- Spouse joins free, first dependent free, additional members $75/month each
- All charges billed to Head of Household

CRISIS PROTOCOL:
- If Nate detects crisis signs, emergency info is shown
- Call 988 (Suicide & Crisis Lifeline) or 911
- Sovereign Sanctuary is NOT an emergency service

If you don't know the answer, say so honestly and suggest contacting support@sovereignsanctuary.net."""

COACH_HELP_SYSTEM_PROMPT = """You are Little Nate, the platform guide for Sovereign Sanctuary's Coach Portal. You are NOT in therapy mode. You are a friendly, knowledgeable guide who helps coaches navigate the platform and understand their tools.

IMPORTANT: Keep answers concise (2-4 sentences when possible). Be warm but direct. Use plain language.

COACH PORTAL FEATURES YOU KNOW ABOUT:

7 MAIN TABS:

1. CLIENTS TAB:
   - View all assigned clients
   - Filter by: ALL, FAMILY, COACH_ONLY, COMPANY
   - Tap a client to see their details
   - Actions per client: View details, Get pre-session brief, Start live session, View notes/folders

2. SCHEDULE TAB:
   - View scheduled sessions on a calendar
   - Pending bookings management
   - Create new session: Select client, set date/time, duration, session type (COACH, FAMILY, GROUP)
   - Optional: Family ID, notes, disable recording
   - Session actions: Start live session, View details, Delete, Check Zoom recording, Archive transcript

3. INSIGHTS TAB:
   - Client insights and analytics
   - Filter by client type

4. BRIEFINGS TAB:
   - Pre-session briefings organized by folders (family folders, client folders)
   - View session notes by folder
   - Add notes to folders
   - Share notes with Nate for Night School learning

5. DOJO TAB:
   - Adversarial testing environment to sharpen coaching skills
   - Select personas (e.g., HOSTILE)
   - Test your responses against challenging prompts
   - Share learnings with Night School
   - Sessions are analyzed for improvement

6. CLASSROOM TAB:
   - Upload session videos for analysis
   - Upload progress tracking
   - Transcript analysis with learning focus selection
   - Reflection prompts and progress tracking
   - Session history
   - Live analysis during Zoom sessions
   - Recording status checking
   - Zoom integration (meeting ID, host URL)

7. FINANCIALS TAB:
   - Coaching fee management
   - Payment mode: Coach Handles vs Platform Handles billing
   - Platform fee: 30% (minimum $30)
   - Financial overview and pending bookings

LIVE SESSION FEATURES:
- Start from Schedule tab
- Real-time note-taking
- AI-generated live observations
- Assist mode toggle (enable/disable AI assistance during session)
- Zoom meeting integration (join as host)
- End session with option to share notes with Nate (Night School)

ZOOM INTEGRATION:
- Set Zoom link in Settings > Profile > Zoom Link
- Sessions can auto-create Zoom meetings
- Join as host directly from the app
- Check recording status, archive transcripts, delete meetings

NIGHT SCHOOL:
- AI training system that learns from shared session notes, Dojo sessions, and Classroom analysis
- Accumulated wisdom makes Nate more insightful over time

SETTINGS (accessible via gear icon):
- Profile: Email, phone, specialties, coaching style (Directive/Reflective/Integrative), Zoom link, emergency contact, timezone
- Practice & Fees: Coaching fee ($/hr), payment mode, platform fee display
- Tax & Compliance: W-9 status, 1099 status, address verified, TIN document
- Preferences: New client alerts, session reminders, crisis alerts, Night School updates
- Subscription: Tier, certification status
- Legal & Privacy: Full terms, privacy policy, and waivers
- About & Support: App version, this Help & FAQ, contact support
- Account: Delete account (must unassign clients first, 30-day recovery), Logout

If you don't know the answer, say so honestly and suggest contacting support@sovereignsanctuary.net."""

# Azure OpenAI Helper Function
async def call_azure_openai(prompt: str, system_message: str = "You are a helpful assistant.", max_tokens: int = 2000, session_id: str = "") -> str:
    """Call Azure OpenAI Realtime API and return full response text.
    
    HIVE DEFENSE v4.3: Prompts are anonymized via AnonymizationProxy before
    being sent to the AI API. Responses are de-anonymized before returning.
    """
    import aiohttp

    # ── HIVE DEFENSE v4.3: Anonymize prompt before sending to AI ──
    _anon_proxy = None
    _anon_mapping = None
    try:
        _hive = getattr(getattr(sys.modules.get('__main__'), 'app', None), 'state', None)
        _hive_v4 = getattr(_hive, 'hive_v4', None) if _hive else None
        if _hive_v4:
            _anon_proxy = _hive_v4.get("anonymization_proxy")
    except Exception:
        pass

    if _anon_proxy:
        try:
            _sid = session_id or "global"
            anon_result = _anon_proxy.anonymize_for_ai(prompt, session_id=_sid, system_context=system_message)
            prompt = anon_result["anonymized_prompt"]
            system_message = anon_result["anonymized_context"] or system_message
            _anon_mapping = anon_result["mapping"]
            if anon_result["original_pii_count"] > 0:
                print(f">>> [AnonymizationProxy] Stripped {anon_result['original_pii_count']} PII items from prompt")
        except Exception as _anon_err:
            print(f">>> [AnonymizationProxy] Non-blocking anonymization error: {_anon_err}")
    
    url = AZURE_ENDPOINT
    headers = {
        "api-key": AZURE_API_KEY,
        "OpenAI-Beta": "realtime=v1"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, headers=headers) as azure_ws:
                # Configure session
                await azure_ws.send_str(json.dumps({
                    "type": "session.update",
                    "session": {
                        "modalities": ["text"],
                        "instructions": system_message,
                        "voice": "ballad",
                        "turn_detection": None
                    }
                }))
                
                # Send user message
                await azure_ws.send_str(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt}]
                    }
                }))
                
                # Request response
                await azure_ws.send_str(json.dumps({"type": "response.create"}))
                
                # Collect full response
                full_response = ""
                async for msg in azure_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        event = json.loads(msg.data)
                        event_type = event.get("type")
                        
                        if event_type == "response.text.delta":
                            full_response += event.get("delta", "")
                        elif event_type in ["response.text.done", "response.done"]:
                            break
                        elif event_type == "error":
                            raise Exception(f"Azure error: {event}")

                # ── HIVE DEFENSE v4.3: De-anonymize response ──
                if _anon_proxy and _anon_mapping:
                    try:
                        _sid = session_id or "global"
                        full_response = _anon_proxy.deanonymize(full_response, session_id=_sid, mapping=_anon_mapping)
                    except Exception as _deanon_err:
                        print(f">>> [AnonymizationProxy] Non-blocking de-anonymization error: {_deanon_err}")

                return full_response
                
    except Exception as e:
        print(f">>> [AZURE] call_azure_openai error: {e}")
        raise


# ==============================================================================
# TTS SPEAK — Hybrid: GPT-4o-Mini-TTS REST API (cheap) → Realtime fallback
# Mini-TTS: ~$0.05/request | Realtime: $1.50-7/session
# ==============================================================================

# Build Mini-TTS REST endpoint URL
_mini_tts_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").replace("https://", "").replace("wss://", "").rstrip("/")
_mini_tts_deployment = os.getenv("AZURE_OPENAI_MINI_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
MINI_TTS_URL = f"https://{_mini_tts_endpoint}/openai/deployments/{_mini_tts_deployment}/audio/speech?api-version=2025-01-01-preview"
MINI_TTS_HEADERS = {
    "api-key": os.getenv("AZURE_API_KEY", ""),
    "Content-Type": "application/json"
}

async def _handle_tts_speak(client_ws, text: str, request_id: str = ""):
    """
    Convert text to speech using Nate's voice.
    
    Strategy:
    1. Try GPT-4o-Mini-TTS REST API (cost: ~$0.05/request)
    2. If Mini-TTS deployment not available, fall back to Realtime API
    """
    import aiohttp
    import base64
    
    print(f">>> [TTS] Starting tts_speak ({len(text)} chars)")
    
    # ── Attempt 1: GPT-4o-Mini-TTS REST API (cheap, fast) ──
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": _mini_tts_deployment,
                "input": text,
                "voice": "ballad",
                "response_format": "mp3"
            }
            async with session.post(MINI_TTS_URL, headers=MINI_TTS_HEADERS, json=payload) as resp:
                if resp.status == 200:
                    # Success — read MP3 bytes and send as single base64 chunk
                    audio_bytes = await resp.read()
                    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
                    
                    # Send as a single audio delta (MP3 format)
                    try:
                        await client_ws.send(json.dumps({
                            "type": "nate_audio_delta",
                            "payload": b64_audio,
                            "format": "mp3",
                            "request_id": request_id
                        }))
                    except Exception:
                        print(">>> [TTS] Client disconnected during send")
                    
                    print(f">>> [TTS] Mini-TTS completed. Sent {len(audio_bytes)} bytes MP3.")
                    
                    try:
                        await client_ws.send(json.dumps({
                            "type": "tts_done",
                            "request_id": request_id
                        }))
                    except Exception:
                        pass
                    return  # Done — Mini-TTS succeeded
                else:
                    error_text = await resp.text()
                    print(f">>> [TTS] Mini-TTS unavailable ({resp.status}): {error_text[:200]}")
                    print(f">>> [TTS] Falling back to Realtime API...")
    except Exception as e:
        print(f">>> [TTS] Mini-TTS failed: {e}. Falling back to Realtime API...")
    
    # ── Attempt 2: Realtime API fallback (more expensive) ──
    url = AZURE_ENDPOINT
    headers = {
        "api-key": AZURE_API_KEY,
        "OpenAI-Beta": "realtime=v1"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, headers=headers) as azure_ws:
                # Configure session: text+audio, alloy voice, no VAD (one-shot)
                await azure_ws.send_str(json.dumps({
                    "type": "session.update",
                    "session": {
                        "modalities": ["text", "audio"],
                        "instructions": "You are Little Nate. Speak the following text naturally and exactly as given. Do not add commentary or change the wording. Be warm and calm. Speak at a natural, steady conversational pace.",
                        "voice": "ballad",
                        "turn_detection": None
                    }
                }))
                
                # Send the text to be spoken
                await azure_ws.send_str(json.dumps({
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"Please say the following out loud: {text}"}]
                    }
                }))
                
                # Request response (audio)
                await azure_ws.send_str(json.dumps({"type": "response.create"}))
                
                # Stream audio deltas back to the client
                chunk_count = 0
                async for msg in azure_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        event = json.loads(msg.data)
                        event_type = event.get("type")
                        
                        if event_type == "response.audio.delta":
                            delta = event.get("delta", "")
                            if delta:
                                chunk_count += 1
                                try:
                                    await client_ws.send(json.dumps({
                                        "type": "nate_audio_delta",
                                        "payload": delta,
                                        "request_id": request_id
                                    }))
                                except Exception:
                                    print(">>> [TTS] Client disconnected during streaming")
                                    break
                        
                        elif event_type in ("response.done", "response.audio.done"):
                            break
                        
                        elif event_type == "error":
                            print(f">>> [TTS] Azure Realtime error: {event}")
                            break
                
                print(f">>> [TTS] Realtime fallback completed. Sent {chunk_count} audio chunks.")
        
        # Signal completion to the client
        try:
            await client_ws.send(json.dumps({
                "type": "tts_done",
                "request_id": request_id
            }))
        except Exception:
            pass
            
    except Exception as e:
        print(f">>> [TTS] tts_speak FAILED (both Mini-TTS and Realtime): {e}")
        import traceback
        traceback.print_exc()
        try:
            await client_ws.send(json.dumps({
                "type": "tts_done",
                "request_id": request_id,
                "error": "TTS_PROCESSING_FAILED"
            }))
        except Exception:
            pass


async def update_client_story(
    client_id: str,
    member_name: str,
    summary_data: dict,
    messages: list,
    coaching_sessions: dict,
    eft_tracker: dict = None,
    reconsolidation_tracker: dict = None,
):
    """
    Update client's story.json with insights from completed sanctuary session.
    This grows Little Nate's relational wisdom about each person.
    """
    story_path = os.path.join(DATA_DIR, "Vaults", "Clients", client_id, "story.json")
    
    # Load existing story or create new one
    if os.path.exists(story_path):
        with open(story_path, 'r') as f:
            story = json.load(f)
    else:
        # Create minimal story structure
        os.makedirs(os.path.dirname(story_path), exist_ok=True)
        story = {
            "client_id": client_id,
            "name": member_name,
            "story_version": 1,
            "who_you_are": {"strengths": [], "values": []},
            "wounds": {"core_wounds": [], "recent_hurts": []},
            "growth": {"breakthroughs": [], "progress_markers": []},
            "patterns": {"when_activated": {}},
            "therapeutic_alliance": {"trust_level": "new", "what_builds_trust": []},
            "unfinished_business": [],
            "corrective_experiences_needed": [],
            "little_nate_notes": {"remember_to": [], "watch_for": []}
        }
    
    # Get individual insights for this member
    individual = summary_data.get("individual_insights", {}).get(member_name, {})
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # === ADD BREAKTHROUGHS ===
    corrective_experiences = summary_data.get("corrective_experiences", [])
    for ce in corrective_experiences:
        if ce and len(ce) > 10:
            breakthrough = {
                "date": today,
                "moment": ce,
                "context": "Family Sanctuary session",
                "anchor_phrase": f"Remember this moment of connection, {member_name}"
            }
            # Avoid duplicates
            existing_moments = [b.get("moment", "")[:50] for b in story.get("growth", {}).get("breakthroughs", [])]
            if ce[:50] not in existing_moments:
                if "growth" not in story:
                    story["growth"] = {"breakthroughs": [], "progress_markers": []}
                story["growth"]["breakthroughs"].append(breakthrough)
    
    # === ADD PATTERNS OBSERVED ===
    patterns_observed = individual.get("patterns_observed", "")
    if patterns_observed and patterns_observed != "Review needed" and len(patterns_observed) > 10:
        if "patterns" not in story:
            story["patterns"] = {"when_activated": {}}
        if "session_patterns" not in story["patterns"]:
            story["patterns"]["session_patterns"] = []
        story["patterns"]["session_patterns"].append({
            "date": today,
            "observation": patterns_observed
        })
        # Keep last 10
        story["patterns"]["session_patterns"] = story["patterns"]["session_patterns"][-10:]
    
    # === ADD GROWTH AREAS ===
    growth_areas = individual.get("growth_areas", "")
    if growth_areas and growth_areas != "Discuss with coach" and len(growth_areas) > 10:
        if "growth" not in story:
            story["growth"] = {"breakthroughs": [], "progress_markers": [], "edges_of_growth": []}
        if "edges_of_growth" not in story["growth"]:
            story["growth"]["edges_of_growth"] = []
        # Add if not duplicate
        if growth_areas not in story["growth"]["edges_of_growth"]:
            story["growth"]["edges_of_growth"].append(growth_areas)
            story["growth"]["edges_of_growth"] = story["growth"]["edges_of_growth"][-5:]
    
    # === ADD STRENGTHS SHOWN ===
    strengths = individual.get("strengths_shown", "")
    if strengths and strengths != "Participated in session" and len(strengths) > 10:
        if "who_you_are" not in story:
            story["who_you_are"] = {"strengths": [], "values": []}
        if strengths not in story["who_you_are"]["strengths"]:
            story["who_you_are"]["strengths"].append(strengths)
            story["who_you_are"]["strengths"] = story["who_you_are"]["strengths"][-7:]
    
    # === CHECK FOR UNFINISHED BUSINESS FROM KEY CONFLICTS ===
    key_conflicts = summary_data.get("key_conflicts", [])
    for conflict in key_conflicts:
        if conflict and "Please review" not in conflict and len(conflict) > 10:
            # Check if already tracked
            existing_topics = [u.get("topic", "")[:30] for u in story.get("unfinished_business", [])]
            if conflict[:30] not in existing_topics:
                if "unfinished_business" not in story:
                    story["unfinished_business"] = []
                story["unfinished_business"].append({
                    "topic": conflict,
                    "status": "identified in sanctuary",
                    "importance": "medium",
                    "date_identified": today
                })
                story["unfinished_business"] = story["unfinished_business"][-5:]
    
    # === SCAN MESSAGES FOR SIGNIFICANT DISCLOSURES ===
    danger_words = {
        "hit me": "Physical abuse disclosed",
        "hits me": "Physical abuse disclosed", 
        "hitting me": "Physical abuse disclosed",
        "abuse": "Abuse mentioned",
        "scared of": "Fear/safety concern",
        "unsafe": "Safety concern",
        "suicide": "Crisis - suicidal ideation",
        "kill myself": "Crisis - suicidal ideation",
        "hurt myself": "Crisis - self-harm"
    }
    
    for msg in messages:
        if msg.get("sender_id") == client_id:
            content_lower = msg.get("content", "").lower()
            for phrase, label in danger_words.items():
                if phrase in content_lower:
                    # Add to wounds/recent_hurts
                    hurt_entry = {
                        "date": today,
                        "event": label,
                        "status": "disclosed - needs follow-up",
                        "context": msg.get("content", "")[:100]
                    }
                    existing_events = [h.get("event", "") for h in story.get("wounds", {}).get("recent_hurts", [])]
                    if label not in existing_events:
                        if "wounds" not in story:
                            story["wounds"] = {"core_wounds": [], "recent_hurts": []}
                        if "recent_hurts" not in story["wounds"]:
                            story["wounds"]["recent_hurts"] = []
                        story["wounds"]["recent_hurts"].append(hurt_entry)
                    
                    # Add to little_nate_notes
                    reminder = f"Member disclosed: {label} - validate and follow up"
                    if "little_nate_notes" not in story:
                        story["little_nate_notes"] = {"remember_to": [], "watch_for": []}
                    if reminder not in story["little_nate_notes"].get("remember_to", []):
                        story["little_nate_notes"]["remember_to"].append(reminder)
                    break

    # === EFT LONGINGS (Attachment needs) ===
    # Store compact, longitudinal signals for Little Nate's memory.
    if eft_tracker and isinstance(eft_tracker, dict):
        try:
            member_longings = (eft_tracker.get("member_longings") or {}).get(client_id, []) or []
            # Keep only last ~12 longing entries per member
            story.setdefault("attachment_longings", [])
            for l in member_longings[-6:]:
                # Minimal, safe schema
                entry = {
                    "date": today,
                    "type": l.get("type"),
                    "expressed_as": (l.get("expressed_as") or "")[:200],
                    "underlying_need": (l.get("underlying_need") or "")[:200],
                    "wound_indicated": (l.get("wound_indicated") or "")[:200] if l.get("wound_indicated") else None,
                }
                story["attachment_longings"].append(entry)
            story["attachment_longings"] = story["attachment_longings"][-12:]

            # Store negative cycle snapshot (shared)
            cycle = eft_tracker.get("negative_cycle")
            if cycle:
                story.setdefault("patterns", {}).setdefault("attachment_cycles", [])
                story["patterns"]["attachment_cycles"].append({
                    "date": today,
                    "pattern": cycle.get("pattern"),
                    "description": (cycle.get("description") or "")[:240],
                    "roles": (cycle.get("roles") or "")[:120] if cycle.get("roles") else None,
                })
                story["patterns"]["attachment_cycles"] = story["patterns"]["attachment_cycles"][-6:]

            # Gentle watch-for reminders
            story.setdefault("little_nate_notes", {"remember_to": [], "watch_for": []})
            if member_longings:
                reminder = f"EFT longing signal: {member_longings[-1].get('type', 'UNKNOWN')} (help deepen + enact)"
                if reminder not in story["little_nate_notes"].get("watch_for", []):
                    story["little_nate_notes"]["watch_for"].append(reminder)
                    story["little_nate_notes"]["watch_for"] = story["little_nate_notes"]["watch_for"][-12:]
        except Exception as e:
            print(f">>> [STORY] EFT write error for {client_id}: {e}")

    # === MEMORY RECONSOLIDATION (Schemas + verified shifts) ===
    if reconsolidation_tracker and isinstance(reconsolidation_tracker, dict):
        try:
            story.setdefault("schemas", [])
            story.setdefault("reconsolidations", [])

            schemas = reconsolidation_tracker.get("schemas") or {}
            # store per-member schema summaries (bounded)
            for _, s in list(schemas.items())[-10:]:
                if s.get("member_id") != client_id:
                    continue
                story["schemas"].append({
                    "date": today,
                    "core_belief": (s.get("core_belief") or "")[:220],
                    "emotional_charge": s.get("emotional_charge"),
                    "origin_hint": s.get("origin_hint"),
                    "activation_count": s.get("activation_count", 0),
                    "reconsolidation_complete": bool(s.get("reconsolidation_complete")),
                })
            story["schemas"] = story["schemas"][-20:]

            # store reconsolidation completions (bounded)
            for r in (reconsolidation_tracker.get("reconsolidations") or [])[-8:]:
                # Only keep those tied to this member via schema lookup when possible
                sid = r.get("schema_id")
                s = schemas.get(sid) if isinstance(schemas, dict) else None
                if s and s.get("member_id") != client_id:
                    continue
                story["reconsolidations"].append({
                    "date": today,
                    "old_belief": (r.get("old_belief") or "")[:200],
                    "new_belief": (r.get("new_belief") or "")[:200],
                    "confidence": r.get("confidence"),
                    "verification_response": (r.get("verification_response") or "")[:240],
                })
            story["reconsolidations"] = story["reconsolidations"][-20:]

            story.setdefault("little_nate_notes", {"remember_to": [], "watch_for": []})
            if story["reconsolidations"]:
                reminder = "Reconsolidation work present: continue consolidation prompts in next session if needed"
                if reminder not in story["little_nate_notes"].get("watch_for", []):
                    story["little_nate_notes"]["watch_for"].append(reminder)
                    story["little_nate_notes"]["watch_for"] = story["little_nate_notes"]["watch_for"][-12:]
        except Exception as e:
            print(f">>> [STORY] Reconsolidation write error for {client_id}: {e}")
    
    # === UPDATE METADATA ===
    story["story_updated"] = today
    story["story_version"] = story.get("story_version", 0) + 1
    
    # === SAVE ===
    with open(story_path, 'w') as f:
        json.dump(story, f, indent=2)
    
    print(f">>> [STORY] Updated story.json for {member_name} ({client_id})")
    return True

# Stripe Configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# SendGrid Configuration (fallback to SMTP_PASSWORD since SendGrid API key doubles as SMTP password)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY") or os.getenv("SMTP_PASSWORD") 

# Database Setup
# - In Docker: default to /app/data
# - Locally: if /app/data isn't writable, fall back to ./data next to this file
current_dir = Path(__file__).resolve().parent
parent_dir = current_dir.parent

_env_data_dir = os.getenv("DATA_DIR")
DATA_DIR = Path(_env_data_dir) if _env_data_dir else Path("/app/data")
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError as e:
    # If user explicitly set DATA_DIR, surface the error (misconfiguration)
    if _env_data_dir:
        raise
    # Otherwise, assume we're running locally (macOS/Windows) and use ./data
    DATA_DIR = current_dir / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f">>> [DATA_DIR] Falling back to local path: {DATA_DIR} (reason: {e})")

MASTER_PATH = DATA_DIR
print(f"[*] Database Root: {MASTER_PATH}")

VAULT_ROOT = DATA_DIR / "Vaults"
REGISTRY_FILE = DATA_DIR / "user_registry.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
BILLING_FILE = DATA_DIR / "billing.json"
ANALYTICS_FILE = DATA_DIR / "analytics.json"
CRISIS_LOG_FILE = DATA_DIR / "crisis_log.json"
COACH_SESSION_NOTES_FILE = DATA_DIR / "coach_session_notes.json"
COACH_LIVE_SESSIONS_FILE = DATA_DIR / "coach_live_sessions.json"
COACH_LEARNING_QUEUE_FILE = DATA_DIR / "coach_learning_queue.json"
COACH_LEARNING_ARCHIVE_FILE = DATA_DIR / "coach_learning_archive.json"
COACH_COMPENSATION_LEDGER_FILE = DATA_DIR / "coach_compensation_ledger.json"

# In production, bridge mounts backend data read-only at /app/backend_data.
# Use it as a source-of-truth for shared registries where possible.
BACKEND_DATA_DIR = Path("/app/backend_data")
BACKEND_REGISTRY_FILE = BACKEND_DATA_DIR / "user_registry.json"
BACKEND_VAULT_ROOT = BACKEND_DATA_DIR / "Vaults"

# If enabled, coach-shared learnings go straight into Night School (no admin gate).
# Keep OFF by default to prevent corruption.
AUTO_APPROVE_COACH_LEARNING = os.getenv("AUTO_APPROVE_COACH_LEARNING", "").strip() in ("1", "true", "TRUE", "yes", "YES")

# Retention / anti-waste controls (safe defaults)
def _int_env(name: str, default: int) -> int:
    try:
        v = int(str(os.getenv(name, "")).strip() or default)
        return v
    except Exception:
        return default

COACH_LEARNING_RETENTION_DAYS = _int_env("COACH_LEARNING_RETENTION_DAYS", 90)
COACH_LEARNING_QUEUE_MAX_ITEMS = _int_env("COACH_LEARNING_QUEUE_MAX_ITEMS", 2000)
COACH_LEARNING_ARCHIVE_MAX_ITEMS = _int_env("COACH_LEARNING_ARCHIVE_MAX_ITEMS", 20000)
COACH_LIVE_SESSIONS_MAX_ENDED = _int_env("COACH_LIVE_SESSIONS_MAX_ENDED", 500)

ACTIVE_TOKENS = {}  # {token: {"profile": profile, "expires": datetime}}
# NOTE: Global state dicts (ACTIVE_TOKENS, connected_coaches, connected_clients)
# are mutated from a single asyncio event loop, so no explicit lock is needed
# for asyncio (single-threaded). File I/O uses fcntl.flock for safety.
TOKEN_TTL_HOURS = 24

# Per-IP connection limiting
_connections_per_ip: dict = {}  # ip -> count
MAX_CONNECTIONS_PER_IP = 20

# Per-connection message rate limiting
MSG_RATE_LIMIT_WINDOW = 60  # 1 minute
MSG_RATE_LIMIT_MAX = 120    # max messages per minute
AI_RATE_LIMIT_MAX = 15      # max AI queries per minute


class ConnectionRateLimiter:
    """Per-connection rate limiter for WebSocket messages."""

    def __init__(self):
        self.general_timestamps = []
        self.ai_timestamps = []

    def check_general(self) -> bool:
        """Check if general message rate is exceeded. Returns True if allowed."""
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(seconds=MSG_RATE_LIMIT_WINDOW)
        self.general_timestamps = [t for t in self.general_timestamps if t > cutoff]
        if len(self.general_timestamps) >= MSG_RATE_LIMIT_MAX:
            return False
        self.general_timestamps.append(now)
        return True

    def check_ai(self) -> bool:
        """Check if AI query rate is exceeded. Returns True if allowed."""
        now = datetime.datetime.now()
        cutoff = now - datetime.timedelta(seconds=MSG_RATE_LIMIT_WINDOW)
        self.ai_timestamps = [t for t in self.ai_timestamps if t > cutoff]
        if len(self.ai_timestamps) >= AI_RATE_LIMIT_MAX:
            return False
        self.ai_timestamps.append(now)
        return True


def _store_token(token: str, profile: dict):
    """Store a token with expiry."""
    ACTIVE_TOKENS[token] = {
        "profile": profile,
        "expires": datetime.datetime.now() + datetime.timedelta(hours=TOKEN_TTL_HOURS)
    }
    # Prune expired tokens (keep dict manageable)
    _prune_expired_tokens()

def _get_token_profile(token: str):
    """Get profile for token if valid and not expired."""
    entry = ACTIVE_TOKENS.get(token)
    if not entry:
        return None
    if datetime.datetime.now() > entry["expires"]:
        del ACTIVE_TOKENS[token]
        return None
    return entry["profile"]

def _prune_expired_tokens():
    """Remove expired tokens. Called on each new token store."""
    now = datetime.datetime.now()
    expired = [t for t, e in ACTIVE_TOKENS.items() if now > e["expires"]]
    for t in expired:
        del ACTIVE_TOKENS[t]

LIVE_SESSION_TRACKER = {}
ACTIVE_WEBSOCKETS = {}

# Rate limit for forgot_password / forgot_username: 3 per email per 15 min
FORGOT_RATE_LIMIT: dict = {}  # key -> [timestamp, ...]
FORGOT_RATE_LIMIT_WINDOW = 15 * 60  # seconds
FORGOT_RATE_LIMIT_MAX = 3

def _check_forgot_rate_limit(key: str) -> bool:
    """Return True if rate limited (should skip processing, still return generic success)."""
    now = datetime.datetime.now().timestamp()
    if key not in FORGOT_RATE_LIMIT:
        FORGOT_RATE_LIMIT[key] = []
    times = FORGOT_RATE_LIMIT[key]
    times[:] = [t for t in times if now - t < FORGOT_RATE_LIMIT_WINDOW]
    if len(times) >= FORGOT_RATE_LIMIT_MAX:
        return True  # rate limited - skip sending email but return generic success
    times.append(now)
    return False

# Directory Structure
for folder in ["Admin", "Coaches", "Clients", "Guests"]:
    (VAULT_ROOT / folder).mkdir(parents=True, exist_ok=True)
(VAULT_ROOT / "Admin" / "admin_LN_training_folder").mkdir(parents=True, exist_ok=True)

# Workbooks live at repo root: ./Workbooks
WORKBOOKS_DIR = Path(__file__).resolve().parents[3] / "Workbooks"
workbook_library = WorkbookLibrary(WORKBOOKS_DIR) if WorkbookLibrary else None

# Classroom analyzer for coach session review and learning
classroom_analyzer = ClassroomAnalyzer(DATA_DIR, WORKBOOKS_DIR) if ClassroomAnalyzer else None
if classroom_analyzer:
    print("[Classroom] Analyzer initialized for coach session review")

# Import notification callback setter
try:
    from app.services.classroom_analyzer import set_notification_callback
    CLASSROOM_NOTIFICATIONS_AVAILABLE = True
except ImportError:
    CLASSROOM_NOTIFICATIONS_AVAILABLE = False
    set_notification_callback = None

# Global dict to track connected coaches for notifications
connected_coaches: Dict[str, Any] = {}
# Global dict to track connected clients (CLIENT role) for real-time stats
connected_clients: Dict[str, Any] = {}


async def _ws_stale_cleanup_loop():
    """Periodic sweep to remove stale WebSocket entries from connection dicts.

    Runs every 60 seconds. Checks if each stored websocket is still open;
    removes entries whose underlying transport has closed.
    """
    while True:
        await asyncio.sleep(60)
        for label, conn_dict in [("coach", connected_coaches), ("client", connected_clients)]:
            stale_ids = []
            for uid, ws in list(conn_dict.items()):
                try:
                    if ws.closed:
                        stale_ids.append(uid)
                except Exception:
                    stale_ids.append(uid)
            for uid in stale_ids:
                conn_dict.pop(uid, None)
            if stale_ids:
                print(f"[Heartbeat] Removed {len(stale_ids)} stale {label} connection(s)")


def _replace_connection(uid: str, new_ws, conn_dict: Dict[str, Any]):
    """Register a new websocket, closing the old one if it exists and is stale."""
    old_ws = conn_dict.get(uid)
    if old_ws is not None and old_ws is not new_ws:
        try:
            if not old_ws.closed:
                asyncio.create_task(old_ws.close(1000, "Replaced by new connection"))
        except Exception:
            pass
    conn_dict[uid] = new_ws

async def send_coach_notification(coach_id: str, message_type: str, data: Dict):
    """
    Send a WebSocket notification to a connected coach.
    Called by classroom_analyzer when AI analysis completes.
    """
    ws = connected_coaches.get(coach_id)
    if ws:
        try:
            await ws.send(json.dumps({
                "type": message_type,
                **data
            }))
            print(f"[Notification] Sent {message_type} to coach {coach_id}")
        except Exception as e:
            print(f"[Notification] Error sending to {coach_id}: {e}")
            # Remove stale connection
            connected_coaches.pop(coach_id, None)
    else:
        print(f"[Notification] Coach {coach_id} not connected, notification queued")

# Register notification callback with classroom analyzer
if CLASSROOM_NOTIFICATIONS_AVAILABLE and set_notification_callback:
    set_notification_callback(send_coach_notification)
    print("[Classroom] Notification callback registered")

# ------------------------------------------------------------------------------
# PART 2: UTILITY FUNCTIONS
# ------------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash password with salt for secure storage"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return f"{salt}:{hashed.hex()}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash. No plaintext fallback."""
    try:
        salt, hash_hex = stored_hash.split(':')
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(hashed.hex(), hash_hex)
    except (ValueError, AttributeError):
        # Hash format invalid — reject. Never compare plaintext.
        return False

def generate_session_id() -> str:
    """Generate unique session ID"""
    return f"SES_{datetime.datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(6).upper()}"

def load_json_file(filepath: Path, default: Any = None) -> Any:
    """Safely load JSON file. Tightens permissions on sensitive files if needed."""
    if default is None:
        default = {}
    if not filepath.exists():
        return default
    try:
        # Harden file permissions on sensitive files at load time
        if filepath.name in ("user_registry.json", "sessions.json"):
            try:
                current_mode = filepath.stat().st_mode & 0o777
                if current_mode != 0o600:
                    filepath.chmod(0o600)
            except Exception:
                pass
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return default

_SENSITIVE_FILES = {"user_registry.json", "sessions.json"}

def save_json_file(filepath: Path, data: Any) -> bool:
    """Safely save JSON file with backup. Restricts permissions on sensitive files."""
    try:
        # Ensure parent directory exists (important in Docker/bind-mount setups)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        backup = str(filepath) + ".bak"
        if filepath.exists():
            os.rename(filepath, backup)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        # Restrict permissions on sensitive files (owner read/write only)
        if filepath.name in _SENSITIVE_FILES:
            try:
                filepath.chmod(0o600)
            except Exception:
                pass
        return True
    except Exception as e:
        print(f">>> [ERROR] Failed to save {filepath}: {e}")
        return False


def ensure_json_file(filepath: Path, default: Any) -> None:
    """Ensure a JSON file exists on disk (do not overwrite if present)."""
    try:
        if filepath.exists():
            # Harden permissions on sensitive files
            if filepath.name in _SENSITIVE_FILES:
                try:
                    filepath.chmod(0o600)
                except Exception:
                    pass
            return
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(default, f, indent=2, default=str)
        if filepath.name in _SENSITIVE_FILES:
            try:
                filepath.chmod(0o600)
            except Exception:
                pass
    except Exception as e:
        print(f">>> [WARN] Failed to ensure {filepath}: {e}")


# Ensure coach learning queue exists so tooling/scripts can inspect it even before first share.
ensure_json_file(COACH_LEARNING_QUEUE_FILE, [])
ensure_json_file(COACH_LEARNING_ARCHIVE_FILE, [])


def _parse_iso_any(s: Any) -> Optional[datetime.datetime]:
    ss = (s or "")
    if not isinstance(ss, str):
        ss = str(ss)
    ss = ss.strip()
    if not ss:
        return None
    try:
        return datetime.datetime.fromisoformat(ss.replace("Z", "+00:00"))
    except Exception:
        return None


def compact_coach_learning_queue(queue: Any) -> List[dict]:
    """
    Prevent unbounded growth:
    - Never drop PENDING items.
    - Archive APPROVED/REJECTED items older than COACH_LEARNING_RETENTION_DAYS.
    - Cap in-file queue size to COACH_LEARNING_QUEUE_MAX_ITEMS.
    """
    if not isinstance(queue, list):
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=max(1, COACH_LEARNING_RETENTION_DAYS))

    pending: List[dict] = []
    keep: List[dict] = []
    to_archive: List[dict] = []

    for raw in queue:
        if not isinstance(raw, dict):
            continue
        st = (raw.get("status") or "").upper()
        created = _parse_iso_any(raw.get("created_at")) or _parse_iso_any(raw.get("approved_at")) or _parse_iso_any(raw.get("rejected_at"))
        # Assume naive datetimes are local; compare conservatively
        if created and created.tzinfo is None:
            created = created.replace(tzinfo=datetime.timezone.utc)

        if st == "PENDING":
            pending.append(raw)
        else:
            if created and created < cutoff:
                to_archive.append(raw)
            else:
                keep.append(raw)

    if to_archive:
        try:
            arch = load_json_file(COACH_LEARNING_ARCHIVE_FILE, []) or []
            if not isinstance(arch, list):
                arch = []
            arch.extend(to_archive)
            # Keep newest N in archive
            if len(arch) > COACH_LEARNING_ARCHIVE_MAX_ITEMS:
                arch = arch[-COACH_LEARNING_ARCHIVE_MAX_ITEMS:]
            save_json_file(COACH_LEARNING_ARCHIVE_FILE, arch)
        except Exception:
            pass

    # Keep newest non-pending up to remaining space
    # Sort keep by created_at if possible, otherwise preserve relative order.
    keep_sorted = sorted(
        keep,
        key=lambda x: (_parse_iso_any(x.get("created_at")) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)),
    )
    remaining = max(0, COACH_LEARNING_QUEUE_MAX_ITEMS - len(pending))
    if remaining <= 0:
        return pending
    keep_sorted = keep_sorted[-remaining:]
    return pending + keep_sorted


def compact_live_store(live_store: Any) -> Dict[str, Any]:
    """
    Cap ENDED sessions to COACH_LIVE_SESSIONS_MAX_ENDED, but always keep ACTIVE sessions.
    """
    if not isinstance(live_store, dict):
        return {}
    active_keys: List[str] = []
    ended_items: List[Tuple[datetime.datetime, str]] = []
    for k, v in live_store.items():
        if not isinstance(v, dict):
            continue
        st = (v.get("status") or "").upper()
        if st == "ACTIVE":
            active_keys.append(k)
            continue
        dt = _parse_iso_any(v.get("ended_at")) or _parse_iso_any(v.get("started_at")) or _parse_iso_any(v.get("created_at"))
        if dt is None:
            dt = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        ended_items.append((dt, k))

    ended_items.sort(key=lambda t: t[0])
    keep_ended_keys = [k for _, k in ended_items[-max(1, COACH_LIVE_SESSIONS_MAX_ENDED):]]
    keep_set = set(active_keys) | set(keep_ended_keys)
    return {k: v for k, v in live_store.items() if k in keep_set}

# ------------------------------------------------------------------------------
# PART 3: DATABASE & AUTHENTICATION
# ------------------------------------------------------------------------------
def load_registry() -> dict:
    """
    Load the user registry.
    
    When USE_POSTGRES_REGISTRY is enabled and the PG-backed UserStore is ready,
    returns the in-memory cache (fast, no I/O). Otherwise falls back to
    merging JSON files from disk (legacy behavior).
    
    The 162+ call sites throughout bridge_server.py call this function unchanged.
    """
    global _registry_cache
    if _use_pg_registry and _pg_user_store and _pg_user_store.is_ready:
        return _registry_cache

    # Fallback: JSON file merge (legacy behavior)
    local = load_json_file(REGISTRY_FILE, {}) or {}
    if not isinstance(local, dict):
        local = {}
    backend = load_json_file(BACKEND_REGISTRY_FILE, {}) or {}
    if not isinstance(backend, dict):
        backend = {}
    if not backend:
        return local
    if not local:
        return backend
    merged = dict(backend)
    merged.update(local)
    return merged

def save_registry(new_data: dict) -> bool:
    """
    Save the user registry.
    
    When USE_POSTGRES_REGISTRY is enabled, updates the in-memory cache and
    schedules an async write to PostgreSQL. Always writes JSON as a backup.
    Uses file locking to prevent concurrent write corruption.
    """
    global _registry_cache
    if _use_pg_registry and _pg_user_store and _pg_user_store.is_ready:
        _registry_cache = new_data
        _pg_user_store.schedule_sync(new_data)
    # L6: Backup before save (timestamped backup for rotation)
    path = REGISTRY_FILE
    if path.exists():
        try:
            backup_dir = path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(path, backup_dir / f"user_registry_{ts}.json.bak")
            backups = sorted(backup_dir.glob("user_registry_*.json.bak"), key=lambda p: p.stat().st_mtime)
            for old in backups[:-5]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception as e:
            print(f">>> [REGISTRY] Backup failed (non-fatal): {e}")
    # Write JSON as backup (dual-write for safety) with file locking
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(new_data, f, indent=2, default=str)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        # L5: Restrict permissions to owner read/write
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f">>> [ERROR] Failed to save registry: {e}")
        return False


def sync_registry_from_backend() -> None:
    """
    Best-effort: if backend registry exists (prod), merge its users into the bridge registry file.
    This keeps client/coach/admin UX uniform across services even when data dirs are separate.
    Skipped when PostgreSQL registry is active (PG is the single source of truth).
    """
    if _use_pg_registry:
        return  # PG is the source of truth; no JSON sync needed at startup
    try:
        backend = load_json_file(BACKEND_REGISTRY_FILE, {}) or {}
        if not isinstance(backend, dict) or not backend:
            return
        local = load_json_file(REGISTRY_FILE, {}) or {}
        if not isinstance(local, dict):
            local = {}
        merged = dict(backend)
        merged.update(local)
        if len(merged) != len(local):
            save_json_file(REGISTRY_FILE, merged)
            print(f">>> [REGISTRY] Synced bridge registry from backend: {len(local)} -> {len(merged)} users")
    except Exception as e:
        print(f">>> [REGISTRY] Sync from backend failed: {e}")


# Run once at startup so bridge can authenticate all backend users (JSON fallback only).
sync_registry_from_backend()

# ==============================================================================
# INITIALIZE NEW SYSTEMS (AFTER all dependencies are defined)
# ==============================================================================
try:
    from .notification_system import NotificationSystem
    from .stripe_billing import StripeBillingSystem
except Exception:
    from notification_system import NotificationSystem
    from stripe_billing import StripeBillingSystem

notification_system = NotificationSystem(DATA_DIR, SENDGRID_API_KEY)
billing_system = StripeBillingSystem(
    DATA_DIR, 
    STRIPE_SECRET_KEY, 
    STRIPE_WEBHOOK_SECRET, 
    load_registry, 
    save_registry
)

# Initialize Nevedal Handler
nevedal_handler = NevedalHandler(VAULT_ROOT)

# Initialize Secure Search Proxy
try:
    from ..services.search_proxy import SecureSearchProxy, TOTPManager, SearchRequestManager
except Exception:
    try:
        from app.services.search_proxy import SecureSearchProxy, TOTPManager, SearchRequestManager
    except Exception:
        import sys, os as _os
        sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', 'services'))
        from search_proxy import SecureSearchProxy, TOTPManager, SearchRequestManager

BING_SEARCH_API_KEY = os.getenv("BING_SEARCH_API_KEY", "")
TOTP_ENCRYPTION_KEY = os.getenv("TOTP_ENCRYPTION_KEY", "")

search_proxy = SecureSearchProxy(str(DATA_DIR), BING_SEARCH_API_KEY)
totp_manager = TOTPManager(TOTP_ENCRYPTION_KEY)
search_requests = SearchRequestManager()

# Initialize Coach Nexus V2
coach_nexus_v2 = CoachNexusV2(VAULT_ROOT)

# Family Sanctuary Engine
#sanctuary_engine = FamilySanctuaryEngine(
 #   data_dir=DATA_DIR,
 #   azure_cortex=None,
  #  nevedal_handler=nevedal_handler,
  #  billing_system=billing_system
#)

def compute_premium_features(profile: dict, registry: dict = None) -> dict:
    """
    Compute premium features eligibility based on subscription tier.
    For family members, inherit from family head's subscription.
    
    Returns dict with feature flags: avatar, voice_analysis, priority_support, etc.
    """
    if registry is None:
        registry = load_registry()
    
    # Get user's own subscription
    user_plan = (profile.get("subscription_plan") or profile.get("tier") or "").upper()
    
    # Premium tiers that unlock all features
    PREMIUM_TIERS = {"TOP_TIER", "SOVEREIGN_CIRCLE"}
    
    # Check if user is directly on a premium tier
    is_premium = user_plan in PREMIUM_TIERS
    
    # If not premium directly, check if family head is premium
    if not is_premium:
        family_id = profile.get("family_id")
        family_role = (profile.get("family_role") or "").upper()
        
        if family_id and family_role != "HEAD":
            # Find family head and check their subscription
            for _, user_data in registry.items():
                head_profile = user_data.get("profile", {})
                if (head_profile.get("family_id") == family_id and 
                    (head_profile.get("family_role") or "").upper() == "HEAD"):
                    head_plan = (head_profile.get("subscription_plan") or 
                                 head_profile.get("tier") or "").upper()
                    if head_plan in PREMIUM_TIERS:
                        is_premium = True
                    break
    
    # Voice tier features (separate from premium boolean)
    INNER_CHAMBER_TIERS = {"STANDARD", "INNER_CHAMBER", "TOP_TIER", "SOVEREIGN_CIRCLE"}
    REALTIME_VOICE_TIERS = {"TOP_TIER", "SOVEREIGN_CIRCLE"}
    can_tts = user_plan in INNER_CHAMBER_TIERS  # Mini-TTS read-aloud
    can_realtime = user_plan in REALTIME_VOICE_TIERS  # Full interactive voice
    
    return {
        "avatar": is_premium,
        "voice_analysis": is_premium,
        "priority_support": is_premium,
        "advanced_insights": is_premium,
        "family_sanctuary": is_premium,
        "tts_read_aloud": can_tts,
        "realtime_voice": can_realtime,
        "tier_source": user_plan if is_premium else "INHERITED" if is_premium else "STANDARD"
    }


# ─── DOJO Subscription System ──────────────────────────────────────────────────
DOJO_PRICES = {
    'therapist': 175.0,
    'project_pm': 250.0,
    'business': 325.0,
    'cnc': 150.0,
    'mcat': 500.0,
    'teacher': 225.0,
    'judge': 2100.0,
}
# JUDGE is excluded from multi-DOJO volume discounts
JUDGE_NO_DISCOUNT = True
DOJO_DISCOUNTS = [0, 0, 10, 15, 20, 25, 30]  # index = count of active dojos (excluding JUDGE)


def build_dojo_subscriptions(selected_dojos: list, discount_pct: int = 0) -> dict:
    """Create dojo_subscriptions dict from a list of dojo keys at registration time.
    JUDGE is always billed at full price ($2,100/mo) — never discounted."""
    today = str(datetime.datetime.now().date())
    term_end = str((datetime.datetime.now() + datetime.timedelta(days=365)).date())
    subs = {}
    for dojo_key in selected_dojos:
        # JUDGE never gets a discount
        effective_discount = 0 if dojo_key == 'judge' else discount_pct
        subs[dojo_key] = {
            "status": "active",
            "start_date": today,
            "term_end_date": term_end,
            "cancellation_requested": None,
            "access_end_date": None,
            "monthly_rate": DOJO_PRICES.get(dojo_key, 0),
            "discount_pct": effective_discount,
        }
    return subs


def get_active_dojos(profile: dict) -> list:
    """Compute currently accessible dojos from dojo_subscriptions.
    Cross-references subscription status and dates.
    Falls back to selected_dojos for legacy profiles without subscriptions."""
    subs = profile.get("dojo_subscriptions")
    if not subs or not isinstance(subs, dict):
        # Legacy fallback: use selected_dojos directly
        return profile.get("selected_dojos", [])

    today = datetime.datetime.now().date()
    active = []
    for dojo_key, sub in subs.items():
        status = sub.get("status", "expired")
        if status == "active":
            active.append(dojo_key)
        elif status == "cancelled":
            # Still has access until access_end_date
            access_end = sub.get("access_end_date")
            if access_end:
                try:
                    end_date = datetime.datetime.strptime(access_end, "%Y-%m-%d").date()
                    if today <= end_date:
                        active.append(dojo_key)
                    else:
                        # Past access end, mark as expired
                        sub["status"] = "expired"
                except (ValueError, TypeError):
                    pass
            else:
                # No end date set yet, still active
                active.append(dojo_key)
    return active


def check_subscription_renewals(profile: dict) -> bool:
    """Check if any subscriptions need auto-renewal or expiration.
    Returns True if profile was modified."""
    subs = profile.get("dojo_subscriptions")
    if not subs or not isinstance(subs, dict):
        return False

    today = datetime.datetime.now().date()
    modified = False

    for dojo_key, sub in subs.items():
        status = sub.get("status", "expired")
        term_end = sub.get("term_end_date")

        if not term_end:
            continue

        try:
            term_end_date = datetime.datetime.strptime(term_end, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        if status == "active" and today >= term_end_date:
            # Check if cancellation was requested before term end
            cancel_req = sub.get("cancellation_requested")
            if cancel_req:
                try:
                    cancel_date = datetime.datetime.strptime(cancel_req, "%Y-%m-%d").date()
                    # If cancellation was requested 30+ days before term end, expire it
                    if (term_end_date - cancel_date).days >= 30:
                        sub["status"] = "expired"
                        sub["access_end_date"] = term_end
                        modified = True
                        print(f">>> [SUBSCRIPTION] {dojo_key} expired (cancelled before term end)")
                        continue
                except (ValueError, TypeError):
                    pass

            # Auto-renew for another 12 months
            new_term_end = str((term_end_date + datetime.timedelta(days=365)))
            sub["term_end_date"] = new_term_end
            modified = True
            print(f">>> [SUBSCRIPTION] {dojo_key} auto-renewed until {new_term_end}")

        elif status == "cancelled":
            access_end = sub.get("access_end_date")
            if access_end:
                try:
                    access_end_date = datetime.datetime.strptime(access_end, "%Y-%m-%d").date()
                    if today > access_end_date:
                        sub["status"] = "expired"
                        modified = True
                        print(f">>> [SUBSCRIPTION] {dojo_key} expired (past access end)")
                except (ValueError, TypeError):
                    pass

    # Recalculate discount based on active dojos count
    if modified:
        active_count = sum(1 for s in subs.values() if s.get("status") == "active")
        new_discount = DOJO_DISCOUNTS[min(active_count, 6)]
        for sub in subs.values():
            if sub.get("status") == "active":
                sub["discount_pct"] = new_discount
        profile["dojo_discount_pct"] = new_discount
        # Recalculate monthly price
        total = sum(DOJO_PRICES.get(k, 0) for k, s in subs.items() if s.get("status") == "active")
        profile["dojo_monthly_price"] = round(total * (1 - new_discount / 100), 2)

    return modified


def migrate_legacy_dojo_profile(profile: dict) -> bool:
    """Migrate a coach with selected_dojos but no dojo_subscriptions.
    Returns True if migration was performed."""
    if profile.get("role") != "COACH":
        return False
    if profile.get("dojo_subscriptions"):
        return False  # Already has subscriptions
    selected = profile.get("selected_dojos", [])
    if not selected:
        return False

    discount = profile.get("dojo_discount_pct", 0)
    profile["dojo_subscriptions"] = build_dojo_subscriptions(selected, discount)
    print(f">>> [MIGRATION] Created dojo_subscriptions for {profile.get('hardware_id')} from selected_dojos: {selected}")
    return True


def authenticate_user(username: str, password: str, expected_role: str = None) -> Tuple[Optional[str], Any]:
    registry = load_registry()
    target = None
    target_key = None
    fallback_target = None
    fallback_key = None
    identifier = (username or "").strip()
    identifier_l = identifier.lower()
    for k, v in registry.items():
        creds = v.get("credentials", {}) or {}
        prof = v.get("profile", {}) or {}
        stored_user = (creds.get("username") or "").strip()
        stored_email = (prof.get("email") or "").strip()

        # Allow login by either username or email (common for COACH/ADMIN portals).
        matched = False
        if stored_user == identifier or stored_user.lower() == identifier_l:
            matched = True
        elif stored_email and (stored_email == identifier or stored_email.lower() == identifier_l):
            matched = True

        if matched:
            # If expected_role is set, prefer the entry whose role matches
            if expected_role and prof.get("role") == expected_role:
                target = v
                target_key = k
                break  # Exact role match — use immediately
            elif expected_role and prof.get("role") != expected_role:
                # Wrong role but username matches — save as fallback
                if not fallback_target:
                    fallback_target = v
                    fallback_key = k
                continue  # Keep looking for the right role
            else:
                # No expected_role filter — use first match
                target = v
                target_key = k
                break

    # If no role-matched target found, use fallback (will get WRONG_PORTAL later if applicable)
    if not target and fallback_target:
        target = fallback_target
        target_key = fallback_key
    
    if not target:
        return None, "USER_NOT_FOUND"
    
    stored_password = target["credentials"].get("password", "")
    if not verify_password(password, stored_password):
        return None, "INVALID_PASSWORD"
    
    p = target.get("profile", {})
    
    if p.get("subscription_status") == "PENDING_VERIFICATION":
        return None, "ACCOUNT_PENDING_APPROVAL"
    # Consent version check: flag for update but do NOT block login
    p["_consent_update_needed"] = (p.get("consent_version", "v0.0") != REQUIRED_CONSENT_VERSION)
    if expected_role and p.get("role") != "ADMIN" and p.get("role") != expected_role:
        return None, "WRONG_PORTAL"

    token = secrets.token_hex(16)
    _store_token(token, p)
    
    # Update last login
    try:
        if target_key and target_key in registry:
            registry[target_key].setdefault("profile", {})
            registry[target_key]["profile"]["last_login"] = str(datetime.datetime.now())
            registry[target_key]["profile"]["login_count"] = registry[target_key]["profile"].get("login_count", 0) + 1
            save_registry(registry)
    except Exception as e:
        print(f">>> [WARN] Could not update last_login for {identifier}: {e}")
    
    # Compute premium features (avatar, voice analysis, etc.) based on subscription tier
    # For family members, this inherits from the family head's tier
    p["premium_features"] = compute_premium_features(p, registry)
    
    # Ensure onboarding_completed is present (for pre-existing users without it)
    # Default to True for existing users -- they're already familiar with the platform.
    # New users get False set at registration time in register_new_user().
    if "onboarding_completed" not in p:
        p["onboarding_completed"] = True
    
    # ─── DOJO Subscription Processing ─────────────────────────────────────────
    if p.get("role") == "COACH":
        save_needed = False
        # Migrate legacy profiles without dojo_subscriptions
        if migrate_legacy_dojo_profile(p):
            save_needed = True
        # Check for renewals / expirations
        if check_subscription_renewals(p):
            save_needed = True
        # Compute active dojos from subscriptions
        p["selected_dojos"] = get_active_dojos(p)
        # Persist changes if migration or renewal happened
        if save_needed:
            try:
                if target_key and target_key in registry:
                    registry[target_key]["profile"] = p
                    save_registry(registry)
                    print(f">>> [SUBSCRIPTION] Saved updated profile for {identifier}")
            except Exception as e:
                print(f">>> [WARN] Could not save subscription updates for {identifier}: {e}")
    
    return token, p

def calculate_platform_fee(coach_fee: float, pct: float = 30.0, minimum: float = 30.0) -> dict:
    """Calculate platform fee for a coaching session.
    Returns dict with coach_fee, platform_fee, coach_payout."""
    platform_fee = max(coach_fee * (pct / 100.0), minimum)
    coach_payout = max(coach_fee - platform_fee, 0)
    return {
        "coach_fee": round(coach_fee, 2),
        "platform_fee": round(platform_fee, 2),
        "coach_payout": round(coach_payout, 2),
    }

def register_new_user(data: dict) -> Tuple[bool, str]:
    if not data.get("consent_agreed"):
        return False, "CONSENT_REQUIRED"
    
    username = data.get("username")
    email = data.get("email", "")
    role = data.get("role", "CLIENT")
    registry = load_registry()
    
    # Check for existing username or email
    for k, v in registry.items():
        creds = v.get("credentials") if isinstance(v, dict) else None
        if creds and creds.get("username") == username:
            return False, "USERNAME_TAKEN"
        prof = v.get("profile", {}) if isinstance(v, dict) else {}
        if email and prof.get("email") == email:
            return False, "EMAIL_TAKEN"

    # Hash the password
    hashed_password = hash_password(data.get("password", ""))
    
    # Determine client registration type
    registration_type = data.get("registration_type", "TRIAL")
    if registration_type:
        registration_type = registration_type.upper()
    else:
        registration_type = "TRIAL"

    # Coach invite token: if present and valid, apply coach assignment and tier
    coach_invite_token = (data.get("coach_invite_token") or "").strip().upper()
    coach_id_from_invite = ""
    if role == "CLIENT" and coach_invite_token:
        invites = registry.get("_coach_invites", {})
        invite = invites.get(coach_invite_token)
        if invite:
            expires = invite.get("expires_at", "")
            if expires and str(datetime.datetime.now()) <= expires:
                coach_id_from_invite = invite.get("coach_id", "")
                inv_tier = (invite.get("tier") or "STANDARD").upper()
                registration_type = inv_tier if inv_tier in ("STANDARD", "COACH_ONLY", "TOP_TIER", "SOVEREIGN_CIRCLE") else "STANDARD"
                # Remove used token
                del registry["_coach_invites"][coach_invite_token]
                save_registry(registry)
            # else: expired, ignore
        # else: invalid token, ignore
    
    # Map registration_type to tier, plan, and features
    if role == "CLIENT":
        if registration_type == "COACH_ONLY":
            tier = "COACH_ONLY"
            plan = "COACH_ONLY"
            sub_status = "ACTIVE"
            can_access_nate = False
            token_balance = 0
            trial_end = ""
        elif registration_type == "STANDARD":
            tier = "STANDARD"
            plan = "STANDARD"
            sub_status = "ACTIVE"
            can_access_nate = True
            token_balance = 50000
            trial_end = ""
        elif registration_type == "TOP_TIER":
            tier = "TOP_TIER"
            plan = "TOP_TIER"
            sub_status = "ACTIVE"
            can_access_nate = True
            token_balance = 200000
            trial_end = ""
        else:  # TRIAL (default)
            tier = "STANDARD"
            plan = "TRIAL"
            sub_status = "TRIAL_ACTIVE"
            can_access_nate = True
            token_balance = 10000
            trial_end = str((datetime.datetime.now() + datetime.timedelta(days=14)).date())
    else:
        # Coach defaults
        tier = "COACH"
        plan = "COACH"
        sub_status = "PENDING_VERIFICATION"
        can_access_nate = True
        token_balance = 50000
        trial_end = ""
    
    new_profile = {
        "role": role,
        "name": data.get("name"),
        "email": email,
        "phone": data.get("phone", ""),
        "hardware_id": f"{role}_{username.upper()}_ID",
        "family_id": f"FAM_{secrets.token_hex(4).upper()}",
        "joined_date": str(datetime.datetime.now().date()),
        "tier": tier,
        "registration_type": registration_type if role == "CLIENT" else None,
        "dob": data.get("dob"),
        "consent_version": data.get("consent_version", "v0.0"),
        "timezone": data.get("timezone", "America/New_York"),
        "profile_photo_url": "",
        "emergency_contact": data.get("emergency_contact", ""),
        
        # Company grouping (nullable, like family_id for companies)
        "company_id": data.get("company_id", None),
        "company_name": data.get("company_name", ""),
        
        # Subscription & Billing
        "subscription_status": sub_status,
        "subscription_plan": plan,
        "stripe_customer_id": "",
        "subscription_start_date": str(datetime.datetime.now().date()),
        "trial_end_date": trial_end,
        
        # Usage Tracking
        "total_sessions_count": 0,
        "token_balance": token_balance,
        "token_usage_today": 0,
        "token_usage_month": 0,
        "last_token_reset": str(datetime.datetime.now().date()),
        
        # AI access flag
        "can_access_nate": can_access_nate,
        
        # Relationships
        "assigned_coach_id": coach_id_from_invite or data.get("assigned_coach_id", ""),
        
        # Timestamps
        "last_login": "",
        "login_count": 0,
        "created_at": str(datetime.datetime.now()),
        "updated_at": str(datetime.datetime.now()),
        
        # Onboarding tutorial
        "onboarding_completed": False,
        
        # Social media handle (SkyEye social-to-platform funnel)
        # If provided, matched against skyeye_social_memory on signup
        "social_handle": data.get("social_handle", ""),
        "social_platform": data.get("social_platform", ""),
    }
    
    # Check if this is a beta registration (valid invite code)
    is_beta = (
        BETA_INVITE_CODE
        and data.get("beta_invite_code", "").strip() == BETA_INVITE_CODE
    )
    
    if role == "COACH":
        new_profile["subscription_status"] = "PENDING_VERIFICATION"
        new_profile["beta_user"] = is_beta
        if is_beta:
            print(f">>> [REG] Beta invite code accepted — coach {username} still requires admin approval")
        new_profile["assigned_clients"] = []
        new_profile["specializations"] = data.get("specializations", [])
        new_profile["certification_status"] = "PENDING"
        new_profile["hourly_rate"] = 0
        new_profile["total_sessions_conducted"] = 0
        new_profile["average_client_rating"] = 0
        new_profile["revenue_this_month"] = 0
        new_profile["zoom_link"] = data.get("zoom_link", "")
        
        # Financial / 1099 contractor fields
        new_profile["coaching_fee"] = float(data.get("coaching_fee", 0))  # Hourly rate set by coach
        new_profile["platform_fee_pct"] = 30       # 30% platform cut
        new_profile["platform_fee_min"] = 30.00    # Minimum $30 per approved session
        new_profile["payment_mode"] = "coach_handles"  # "coach_handles" or "platform_handles"
        new_profile["total_earnings_ytd"] = 0.0
        new_profile["total_platform_fees_ytd"] = 0.0
        new_profile["total_sessions_billable"] = 0
        new_profile["w9_submitted"] = bool(data.get("w9_data"))
        new_profile["w9_data"] = data.get("w9_data", {})
        new_profile["requires_1099"] = False  # True when YTD earnings >= $600
        # Address and TIN verification tracking
        new_profile["address_verified"] = False
        new_profile["standardized_address"] = {}
        new_profile["tin_doc_uploaded"] = False
        new_profile["tin_doc_path"] = ""
        new_profile["tin_match_status"] = "not_submitted"
        new_profile["tin_verification_method"] = "none"
        new_profile["financial_ledger"] = []  # Transaction history
        new_profile["selected_dojos"] = data.get("selected_dojos", [])
        new_profile["dojo_discount_pct"] = data.get("dojo_discount_pct", 0)
        new_profile["dojo_monthly_price"] = data.get("dojo_monthly_price", 0)
        # Build structured dojo subscriptions with 12-month terms
        new_profile["dojo_subscriptions"] = build_dojo_subscriptions(
            data.get("selected_dojos", []),
            data.get("dojo_discount_pct", 0)
        )
        # Generate Judge Nate Bar ID if coach selected JUDGE dojo
        if 'judge' in [d.lower() for d in data.get("selected_dojos", [])]:
            new_profile["judge_nate_bar_id"] = f"JNBAR-{secrets.token_hex(4).upper()}"
        else:
            new_profile["judge_nate_bar_id"] = None
        
        coach_root = VAULT_ROOT / "Coaches" / new_profile["hardware_id"]
        coach_root.mkdir(parents=True, exist_ok=True)
        (coach_root / f"{username}_LN_training_folder").mkdir(parents=True, exist_ok=True)
        (coach_root / "Reports").mkdir(parents=True, exist_ok=True)
        (coach_root / "Billing").mkdir(parents=True, exist_ok=True)
        (coach_root / "Inbox").mkdir(parents=True, exist_ok=True)
        (coach_root / "Documents").mkdir(parents=True, exist_ok=True)
        
        # Save W-9 document if uploaded
        w9_doc = data.get("w9_doc")
        if w9_doc and w9_doc.get("data") and w9_doc.get("filename"):
            import base64
            try:
                doc_bytes = base64.b64decode(w9_doc["data"])
                doc_path = coach_root / "Documents" / f"w9_{w9_doc['filename']}"
                with open(doc_path, "wb") as df:
                    df.write(doc_bytes)
                new_profile["tin_doc_uploaded"] = True
                new_profile["tin_doc_path"] = str(doc_path)
                new_profile["tin_match_status"] = "pending_admin_review"
                new_profile["tin_verification_method"] = "document_upload"
                print(f">>> [REG] W-9 document saved: {doc_path}")
            except Exception as doc_err:
                print(f">>> [REG] W-9 document save error: {doc_err}")
        
        # Create availability file
        with open(coach_root / "availability.json", "w") as f:
            json.dump({"slots": [], "timezone": new_profile["timezone"]}, f)

    registry[f"{role.lower()}_{username}"] = {
        "credentials": {"username": username, "password": hashed_password},
        "profile": new_profile
    }

    # Add client to coach's assigned_clients when registered via coach invite
    if role == "CLIENT" and coach_id_from_invite:
        for k, v in registry.items():
            p = (v or {}).get("profile", {}) or {}
            if p.get("hardware_id") == coach_id_from_invite:
                clients = list(p.get("assigned_clients") or [])
                if new_profile["hardware_id"] not in clients:
                    clients.append(new_profile["hardware_id"])
                p["assigned_clients"] = clients
                v["profile"] = p
                break
    
    if save_registry(registry):
        (VAULT_ROOT / f"{role.title()}s" / new_profile["hardware_id"]).mkdir(parents=True, exist_ok=True)
        
        # Initialize metrics for new user
        metrics_engine = MetricsEngine(VAULT_ROOT)
        metrics_engine.initialize_metrics(new_profile)
        
        # SkyEye social-to-platform funnel: match social handle to social memory
        # If the user provided a social media handle, attempt to match it so
        # Little Nate can recall prior social interactions in the first session
        social_handle = data.get("social_handle", "").strip()
        social_platform = data.get("social_platform", "").strip()
        if social_handle:
            try:
                import asyncio
                from app.services.skyeye_session_engine import SkyEyeSessionEngine  # noqa: F401
                # Fire-and-forget: non-blocking match attempt
                # The actual match happens when the DB pool is available via the API
                # Store the intent in the profile for the first session to pick up
                new_profile["social_memory_pending_match"] = True
                print(f">>> [REG] Social handle provided: @{social_handle} on {social_platform} — pending match")
            except Exception as e:
                print(f">>> [REG] Social memory match setup note: {e}")
        
        return True, "REGISTRATION_SUCCESS"
    
    return False, "SAVE_ERROR"

def create_dependent_account(guardian_id: str, data: dict) -> Tuple[bool, str]:
    """Create a dependent/child account linked to guardian"""
    username = data.get("username")
    registry = load_registry()
    
    for k, v in registry.items():
        if v["credentials"]["username"] == username:
            return False, "USERNAME_TAKEN"
    
    # Find guardian by hardware_id
    guardian_profile = None
    for v in registry.values():
        if v.get("profile", {}).get("hardware_id") == guardian_id:
            guardian_profile = v["profile"]
            break
    
    if not guardian_profile:
        return False, "GUARDIAN_NOT_FOUND"
    
    fam_id = guardian_profile.get("family_id", f"FAM_{secrets.token_hex(4).upper()}")
    hashed_password = hash_password(data.get("password", ""))
    
    new_profile = {
        "role": "CLIENT",
        "name": data.get("name"),
        "email": "",
        "phone": "",
        "family_id": fam_id,
        "hardware_id": f"CHILD_{username.upper()}_ID",
        "tier": "DEPENDENT",
        "guardian_id": guardian_id,
        "is_minor": True,
        "consent_version": REQUIRED_CONSENT_VERSION,
        "dob": data.get("dob"),
        "timezone": guardian_profile.get("timezone", "America/New_York"),
        "subscription_status": "FAMILY_PLAN_ACTIVE",
        "subscription_plan": "FAMILY_DEPENDENT",
        "total_sessions_count": 0,
        "token_balance": 5000,
        "token_usage_today": 0,
        "token_usage_month": 0,
        "last_token_reset": str(datetime.datetime.now().date()),
        "assigned_coach_id": guardian_profile.get("assigned_coach_id", ""),
        "last_login": "",
        "login_count": 0,
        "created_at": str(datetime.datetime.now()),
        "updated_at": str(datetime.datetime.now())
    }
    
    registry[f"client_{username}"] = {
        "credentials": {"username": username, "password": hashed_password},
        "profile": new_profile
    }
    
    if save_registry(registry):
        (VAULT_ROOT / "Clients" / new_profile["hardware_id"]).mkdir(parents=True, exist_ok=True)
        
        # Initialize metrics
        metrics_engine = MetricsEngine(VAULT_ROOT)
        metrics_engine.initialize_metrics(new_profile)
        
        return True, "DEPENDENT_CREATED"
    
    return False, "SAVE_ERROR"

# ------------------------------------------------------------------------------
# PART 4: MEMORY SYSTEM (Hippocampus)
# ------------------------------------------------------------------------------
class MemorySystem:
    def __init__(self, root: Path):
        self.root = root
    
    def _path(self, p: dict) -> Path:
        folder = "Clients"
        if p.get('role') == "COACH": folder = "Coaches"
        if p.get('role') == "ADMIN": folder = "Admin"
        return self.root / folder / p.get('hardware_id') / "memory.json"
    
    def _sessions_path(self, p: dict) -> Path:
        folder = "Clients"
        if p.get('role') == "COACH": folder = "Coaches"
        if p.get('role') == "ADMIN": folder = "Admin"
        return self.root / folder / p.get('hardware_id') / "sessions.json"

    def recall(self, p: dict, limit: int = 5) -> str:
        path = self._path(p)
        if not path.exists():
            return "No prior history."
        try:
            with open(path, 'r') as f:
                recent = json.load(f)[-limit:]
                return "\n".join([f"- User: {i['user']}\n  Nate: {i['ai']}" for i in recent])
        except:
            return "Memory Corrupted."

    def recall_full(self, p: dict, limit: int = 100) -> List[dict]:
        """Get full memory entries with all metadata"""
        path = self._path(p)
        if not path.exists():
            return []
        try:
            with open(path, 'r') as f:
                return json.load(f)[-limit:]
        except:
            return []

    def memorize(self, p: dict, u_text: str, a_text: str, session_id: str = None, metadata: dict = None):
        path = self._path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        hist = []
        if path.exists():
            try:
                with open(path, 'r') as f:
                    hist = json.load(f)
            except:
                pass
        
        entry = {
            "timestamp": str(datetime.datetime.now()),
            "session_id": session_id,
            "user": u_text,
            "ai": a_text,
            "word_count_user": len(u_text.split()),
            "word_count_ai": len(a_text.split())
        }
        
        if metadata:
            entry.update(metadata)
        
        hist.append(entry)
        
        # Keep last 1000 entries
        with open(path, 'w') as f:
            json.dump(hist[-1000:], f, indent=2)

    def get_topics_discussed(self, p: dict, days: int = 30) -> List[str]:
        """Extract topics from recent conversations"""
        memories = self.recall_full(p, limit=50)
        topics = set()
        
        # Simple keyword extraction
        keywords = ["anxiety", "depression", "family", "work", "relationship", 
                   "sleep", "stress", "anger", "fear", "grief", "trauma",
                   "childhood", "parent", "spouse", "child", "boss", "friend"]
        
        for m in memories:
            text = (m.get("user", "") + " " + m.get("ai", "")).lower()
            for kw in keywords:
                if kw in text:
                    topics.add(kw)
        
        return list(topics)

    def get_breakthroughs(self, p: dict) -> List[dict]:
        """Get recorded breakthroughs"""
        path = self._path(p).parent / "breakthroughs.json"
        if not path.exists():
            return []
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            return []

    def record_breakthrough(self, p: dict, description: str, context: str = ""):
        """Record a breakthrough moment"""
        path = self._path(p).parent / "breakthroughs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        
        breakthroughs = []
        if path.exists():
            try:
                with open(path, 'r') as f:
                    breakthroughs = json.load(f)
            except:
                pass
        
        breakthroughs.append({
            "timestamp": str(datetime.datetime.now()),
            "description": description,
            "context": context
        })
        
        with open(path, 'w') as f:
            json.dump(breakthroughs[-100:], f, indent=2)

# ------------------------------------------------------------------------------
# PART 4b: CONVERSATION EXPORT (Intent Detection + Content Generation)
# ------------------------------------------------------------------------------
class ExportIntentDetector:
    """Detects when a user is asking Nate to save/export/print their conversation."""

    EXPORT_TRIGGERS = [
        # Verb + possessive / article
        "save my", "export my", "print my", "download my",
        "save the", "export the", "print the", "download the",
        "save this", "export this", "print this", "download this",
        "save a", "export a",
        "save our", "export our", "print our",
        # Verb + preposition (covers "print to my phone", "save to drive")
        "save to", "export to", "print to", "download to",
        "send to my", "store to", "store on", "put on my", "put in my",
        # Verb + pronoun (covers "save it", "print them", "save them")
        "save it", "export it", "print it", "download it",
        "save them", "export them", "print them", "download them",
        # Polite forms
        "can you save", "can you export", "can you print", "can you download",
        "i want to save", "i want to export", "i want to print", "i want to download",
        "i'd like to save", "i'd like to export", "i'd like to print",
        "could you save", "could you export", "could you print",
        "please save", "please export", "please print", "please download",
        # Let's / lets
        "let's save", "lets save", "let's print", "lets print",
        "let's export", "lets export", "let's download", "lets download",
        # Compound / informal
        "send it to my", "put it on my", "put it in my",
        "save or print", "print or save", "print or download",
        "back up my", "backup my", "store my",
    ]

    CONTENT_TYPES = {
        "summary": ["summary", "summarize", "overview", "recap", "wrap up", "wrap-up"],
        "highlights": ["highlight", "key moment", "important part", "best part",
                       "breakthrough", "turning point", "key insight"],
        "full": ["full conversation", "everything", "entire conversation", "whole conversation",
                 "whole session", "all of it", "full transcript", "entire session",
                 "complete conversation", "complete session"],
    }

    DESTINATIONS = {
        "google_drive": ["google drive", "gdrive", "g drive", "google"],
        "onedrive": ["onedrive", "one drive", "microsoft drive", "microsoft"],
        "local": ["phone", "my files", "local", "download", "folder",
                  "device", "my phone", "my device", "computer", "my computer",
                  "desktop", "my desktop", "laptop", "my laptop", "pc", "mac",
                  "hard drive", "this device"],
    }

    # Per-user pending export state for follow-up messages
    _pending_exports: dict = {}

    def detect(self, text: str) -> dict | None:
        """Return export intent dict or None if not an export request.

        Returns:
            {
                "is_export": True,
                "export_type": "summary" | "highlights" | "full" | "section",
                "destination": "google_drive" | "onedrive" | "local" | None,
                "description": <original user text for free-form section requests>,
                "needs_clarification_type": bool,
                "needs_clarification_dest": bool,
            }
        """
        lower = text.lower().strip()

        # --- Must match at least one export trigger ---
        triggered = False
        for trigger in self.EXPORT_TRIGGERS:
            if trigger in lower:
                triggered = True
                break
        if not triggered:
            return None

        # --- Determine content type ---
        export_type = None
        for etype, keywords in self.CONTENT_TYPES.items():
            for kw in keywords:
                if kw in lower:
                    export_type = etype
                    break
            if export_type:
                break
        needs_clarification_type = export_type is None
        if export_type is None:
            export_type = "section"

        # --- Determine destination ---
        destination = None
        for dest, keywords in self.DESTINATIONS.items():
            for kw in keywords:
                if kw in lower:
                    destination = dest
                    break
            if destination:
                break
        needs_clarification_dest = destination is None

        return {
            "is_export": True,
            "export_type": export_type,
            "destination": destination,
            "description": text,
            "needs_clarification_type": needs_clarification_type,
            "needs_clarification_dest": needs_clarification_dest,
        }

    # ------------------------------------------------------------------
    # Pending-export helpers (for multi-turn clarification flows)
    # ------------------------------------------------------------------
    def set_pending(self, uid: str, intent: dict):
        """Store a partial export intent so the next message can complete it."""
        self._pending_exports[uid] = intent

    def clear_pending(self, uid: str):
        self._pending_exports.pop(uid, None)

    def check_pending(self, uid: str, text: str) -> dict | None:
        """If there is a pending export for *uid*, see if *text* supplies the
        missing piece (content-type and/or destination).  Returns a
        fully-resolved intent dict or None."""
        if uid not in self._pending_exports:
            return None

        pending = self._pending_exports[uid]
        lower = text.lower().strip()

        # Try to fill in the missing content type
        resolved_type = pending.get("export_type")
        was_needs_type = pending.get("needs_clarification_type", False)
        if was_needs_type:
            for etype, keywords in self.CONTENT_TYPES.items():
                for kw in keywords:
                    if kw in lower:
                        resolved_type = etype
                        was_needs_type = False
                        break
                if not was_needs_type:
                    break

        # Try to fill in the missing destination
        resolved_dest = pending.get("destination")
        was_needs_dest = pending.get("needs_clarification_dest", False)
        if was_needs_dest:
            for dest, keywords in self.DESTINATIONS.items():
                for kw in keywords:
                    if kw in lower:
                        resolved_dest = dest
                        was_needs_dest = False
                        break
                if not was_needs_dest:
                    break

        # Did we resolve at least one thing that was missing?
        originally_needed_type = pending.get("needs_clarification_type", False)
        originally_needed_dest = pending.get("needs_clarification_dest", False)
        type_resolved = originally_needed_type and not was_needs_type
        dest_resolved = originally_needed_dest and not was_needs_dest

        if not type_resolved and not dest_resolved:
            # User message didn't help resolve anything — not an export follow-up
            return None

        # Clear the pending state
        self._pending_exports.pop(uid, None)

        return {
            "is_export": True,
            "export_type": resolved_type if not was_needs_type else "section",
            "destination": resolved_dest,
            "description": pending.get("description", text),
            "needs_clarification_type": was_needs_type,
            "needs_clarification_dest": was_needs_dest,
        }


class ExportContentGenerator:
    """Generates formatted export content from conversation history."""

    def __init__(self, hippocampus: 'MemorySystem'):
        self.mem = hippocampus

    async def generate(self, profile: dict, export_type: str, description: str = "") -> dict:
        """Generate export content and return {content, filename, format}.

        Args:
            profile: User profile dict (must contain hardware_id, role, name).
            export_type: One of 'summary', 'highlights', 'full', 'section'.
            description: User's free-form request (used for 'section' type).

        Returns:
            {"content": str, "filename": str, "format": "txt"}
        """
        # Retrieve full history
        history = self.mem.recall_full(profile, limit=200)
        if not history:
            return {
                "content": "No conversation history found to export.",
                "filename": "empty_export.txt",
                "format": "txt",
            }

        user_name = profile.get("name", "Client")
        now_str = datetime.datetime.now().strftime("%Y-%m-%d")
        now_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if export_type == "full":
            content = self._format_full_transcript(history, user_name, now_full)
            filename = f"sovereign_sanctuary_full_{now_str}.txt"
        elif export_type == "summary":
            content = await self._generate_summary(history, user_name, now_full)
            filename = f"sovereign_sanctuary_summary_{now_str}.txt"
        elif export_type == "highlights":
            content = await self._generate_highlights(history, user_name, now_full)
            filename = f"sovereign_sanctuary_highlights_{now_str}.txt"
        elif export_type == "section":
            content = await self._generate_section(history, user_name, now_full, description)
            filename = f"sovereign_sanctuary_excerpt_{now_str}.txt"
        else:
            content = self._format_full_transcript(history, user_name, now_full)
            filename = f"sovereign_sanctuary_export_{now_str}.txt"

        return {"content": content, "filename": filename, "format": "txt"}

    # ------------------------------------------------------------------
    # Full transcript — no AI call needed
    # ------------------------------------------------------------------
    def _format_full_transcript(self, history: list, user_name: str, timestamp: str) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("SOVEREIGN SANCTUARY — FULL CONVERSATION TRANSCRIPT")
        lines.append(f"Exported: {timestamp}")
        lines.append(f"Client: {user_name}")
        lines.append("=" * 60)
        lines.append("")

        for entry in history:
            ts = entry.get("timestamp", "")
            user_msg = entry.get("user", "")
            ai_msg = entry.get("ai", "")
            session = entry.get("session_id", "")

            lines.append(f"--- {ts} (Session: {session}) ---")
            lines.append(f"{user_name}: {user_msg}")
            lines.append(f"Little Nate: {ai_msg}")
            lines.append("")

        lines.append("=" * 60)
        lines.append("End of transcript")
        lines.append("=" * 60)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Summary — uses Azure OpenAI
    # ------------------------------------------------------------------
    async def _generate_summary(self, history: list, user_name: str, timestamp: str) -> str:
        transcript = self._history_to_text(history, user_name)
        prompt = (
            f"Below is a therapeutic conversation between {user_name} and an AI therapist "
            f"called Little Nate.\n\n{transcript}\n\n"
            "Please produce a warm, organized summary of this conversation. Include:\n"
            "1. Main topics discussed\n"
            "2. Key emotions expressed\n"
            "3. Important insights or breakthroughs\n"
            "4. Any action items or next steps mentioned\n"
            "Write in a supportive, second-person tone (addressing the client)."
        )
        try:
            body = await call_azure_openai(
                prompt,
                system_message="You create clear, compassionate summaries of therapeutic conversations.",
                max_tokens=3000,
            )
        except Exception as e:
            print(f">>> [EXPORT] summary generation error: {e}")
            body = "(Summary could not be generated — here is the full transcript instead.)\n\n" + transcript

        header = (
            "=" * 60 + "\n"
            "SOVEREIGN SANCTUARY — SESSION SUMMARY\n"
            f"Exported: {timestamp}\n"
            f"Client: {user_name}\n"
            "=" * 60 + "\n\n"
        )
        return header + body + "\n\n" + "=" * 60 + "\nEnd of summary\n" + "=" * 60

    # ------------------------------------------------------------------
    # Highlights — uses Azure OpenAI
    # ------------------------------------------------------------------
    async def _generate_highlights(self, history: list, user_name: str, timestamp: str) -> str:
        transcript = self._history_to_text(history, user_name)
        prompt = (
            f"Below is a therapeutic conversation between {user_name} and an AI therapist "
            f"called Little Nate.\n\n{transcript}\n\n"
            "Extract the most meaningful highlights from this conversation. For each highlight:\n"
            "- Quote the key moment\n"
            "- Explain why it matters therapeutically\n"
            "Focus on breakthroughs, emotional shifts, insights, moments of vulnerability, "
            "and growth. Use a warm, supportive tone."
        )
        try:
            body = await call_azure_openai(
                prompt,
                system_message="You identify and narrate the most meaningful moments in therapeutic conversations.",
                max_tokens=3000,
            )
        except Exception as e:
            print(f">>> [EXPORT] highlights generation error: {e}")
            body = "(Highlights could not be generated — here is the full transcript instead.)\n\n" + transcript

        header = (
            "=" * 60 + "\n"
            "SOVEREIGN SANCTUARY — SESSION HIGHLIGHTS\n"
            f"Exported: {timestamp}\n"
            f"Client: {user_name}\n"
            "=" * 60 + "\n\n"
        )
        return header + body + "\n\n" + "=" * 60 + "\nEnd of highlights\n" + "=" * 60

    # ------------------------------------------------------------------
    # Section — uses Azure OpenAI with user's description
    # ------------------------------------------------------------------
    async def _generate_section(self, history: list, user_name: str, timestamp: str, description: str) -> str:
        transcript = self._history_to_text(history, user_name)
        prompt = (
            f"Below is a therapeutic conversation between {user_name} and an AI therapist "
            f"called Little Nate.\n\n{transcript}\n\n"
            f"The user requested the following portion of the conversation:\n\"{description}\"\n\n"
            "Extract and format ONLY the part of the conversation that matches their request. "
            "Include enough context so it reads coherently. If you cannot find a matching "
            "section, include the most relevant parts and note that the exact section "
            "was not found."
        )
        try:
            body = await call_azure_openai(
                prompt,
                system_message="You extract specific sections from therapeutic conversations based on user descriptions.",
                max_tokens=3000,
            )
        except Exception as e:
            print(f">>> [EXPORT] section generation error: {e}")
            body = "(Section extraction failed — here is the full transcript instead.)\n\n" + transcript

        header = (
            "=" * 60 + "\n"
            "SOVEREIGN SANCTUARY — CONVERSATION EXCERPT\n"
            f"Exported: {timestamp}\n"
            f"Client: {user_name}\n"
            f"Requested: {description}\n"
            "=" * 60 + "\n\n"
        )
        return header + body + "\n\n" + "=" * 60 + "\nEnd of excerpt\n" + "=" * 60

    # ------------------------------------------------------------------
    # Helper: convert history list to readable text block
    # ------------------------------------------------------------------
    def _history_to_text(self, history: list, user_name: str) -> str:
        lines = []
        for entry in history:
            ts = entry.get("timestamp", "")
            lines.append(f"[{ts}] {user_name}: {entry.get('user', '')}")
            lines.append(f"[{ts}] Little Nate: {entry.get('ai', '')}")
        return "\n".join(lines)


# Global instances (will be set alongside hippocampus initialization)
export_intent_detector = ExportIntentDetector()
export_content_generator = None  # Initialized after hippocampus is created

# ------------------------------------------------------------------------------
# PART 5: METRICS ENGINE (Parietal Cortex - Nevedal Integration)
# ------------------------------------------------------------------------------
class MetricsEngine:
    def __init__(self, root: Path):
        self.root = root
    
    def _path(self, p: dict) -> Path:
        folder = "Clients"
        if p.get('role') == "COACH": folder = "Coaches"
        if p.get('role') == "ADMIN": folder = "Admin"
        return self.root / folder / p.get('hardware_id') / "metrics.json"

    def _backend_path(self, p: dict) -> Path:
        """
        In production, bridge mounts backend data at /app/backend_data (read-only).
        This lets us read/copy missing vaults so all members (e.g. CLIENT_001B) resolve
        the same metrics/history even if the bridge data dir is missing that file.
        """
        folder = "Clients"
        if p.get('role') == "COACH":
            folder = "Coaches"
        if p.get('role') == "ADMIN":
            folder = "Admin"
        return BACKEND_VAULT_ROOT / folder / p.get('hardware_id') / "metrics.json"
    
    def initialize_metrics(self, p: dict):
        """Initialize metrics for a new user"""
        path = self._path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        initial_metrics = {
            "nevedal_state": {
                "C_emo": 0.5,
                "E_warmth": 0.3,
                "T_tunnel": 0.2,
                "GAP": 0.3,
                "Velocity": 0.0,
                "Quantum": 0.5,
                "anxiety_level": 0.0,
                "depression_indicators": 0.0,
                "stress_level": 0.0,
                "engagement": 0.5,
                "session_count": 0,
                "breakthrough_count": 0,
                "homework_completion_rate": 0.0,
                "risk_level": "LOW",
                "last_risk_assessment": "",
                "crisis_count": 0,
                "mood_current": "neutral",
                "mood_trend": "stable",
                "mood_history": [],
                "sleep_quality": "unknown",
                "sleep_issues_mentioned": 0,
                "crisis_perception": {
                    "distress_discrepancy": 0.0,
                    "minimization_score": 0.0,
                    "sensitivity_score": 0.0,
                    "normalization_index": 0.0,
                    "perception_baseline": "CALIBRATING",
                    "calibration_count": 0,
                    "discrepancy_history": []
                },
                "shame_profile": {
                    "shame_index": 0.0,
                    "shame_baseline": 0.0,
                    "core_beliefs": [],
                    "shame_map": [],
                    "shame_indicators_history": [],
                    "shame_masking_pattern": "UNKNOWN"
                },
                "pmb": {
                    "cyclical_patterns": [],
                    "crisis_precursors": [],
                    "trigger_map": [],
                    "reactivity_type": "MIXED",
                    "reactivity_indicators": {"fight": 0.0, "flight": 0.0, "freeze": 0.0, "fawn": 0.0},
                    "reconsolidation_readiness": 0.0,
                    "reconsolidation_targets": [],
                    "legacy_patterns": [],
                    "predictions": [],
                    "last_pmb_update": "",
                    "pmb_version": 1
                }
            },
            "history": [],
            "last_updated": str(datetime.datetime.now()),
            "created_at": str(datetime.datetime.now())
        }
        
        with open(path, 'w') as f:
            json.dump(initial_metrics, f, indent=2)
    
    def load_metrics(self, p: dict) -> dict:
        path = self._path(p)
        print(f">>> [METRICS DEBUG] Loading from: {path}")
        bpath = None
        try:
            bpath = self._backend_path(p)
        except Exception:
            bpath = None

        if not path.exists():
            # If backend vault exists (prod), copy it into bridge vault before initializing defaults.
            try:
                if bpath and bpath.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(bpath, path)
                    print(f">>> [METRICS DEBUG] Copied missing metrics from backend vault: {bpath} -> {path}")
                else:
                    print(f">>> [METRICS DEBUG] File missing, initializing")
                    self.initialize_metrics(p)
            except Exception as e:
                print(f">>> [METRICS DEBUG] Backend vault copy failed ({e}); initializing defaults")
                self.initialize_metrics(p)
        try:
            with open(path, 'r') as f:
                data = json.load(f)

                # If a default/empty local file exists but backend has richer history, prefer backend.
                # This commonly happens when bridge initialized defaults before the backend vault was mounted/copied.
                try:
                    if bpath and bpath.exists():
                        with open(bpath, "r") as bf:
                            bdata = json.load(bf)
                        lns = (data.get("nevedal_state") or {}) if isinstance(data, dict) else {}
                        bns = (bdata.get("nevedal_state") or {}) if isinstance(bdata, dict) else {}
                        lmh = lns.get("mood_history", []) if isinstance(lns, dict) else []
                        bmh = bns.get("mood_history", []) if isinstance(bns, dict) else []
                        lhist = data.get("history", []) if isinstance(data, dict) else []
                        bhist = bdata.get("history", []) if isinstance(bdata, dict) else []
                        lsc = int(lns.get("session_count") or 0) if isinstance(lns, dict) else 0
                        bsc = int(bns.get("session_count") or 0) if isinstance(bns, dict) else 0

                        # Overwrite only when local looks like an uninitialized stub but backend clearly has data.
                        should_overwrite = (
                            (isinstance(lmh, list) and len(lmh) == 0 and isinstance(bmh, list) and len(bmh) > 0)
                            or (isinstance(lhist, list) and len(lhist) == 0 and isinstance(bhist, list) and len(bhist) > 0 and bsc > lsc)
                        )
                        if should_overwrite:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(bpath, path)
                            print(f">>> [METRICS DEBUG] Replaced stub metrics with backend vault: {bpath} -> {path}")
                            data = bdata
                except Exception as e:
                    print(f">>> [METRICS DEBUG] Backend reconcile skipped: {e}")

                # ------------------------------------------------------------------
                # HYDRATE: If we have richer recent history than nevedal_state/last_updated,
                # update nevedal_state to reflect the newest known snapshot.
                # This ensures dashboards show best-available real-time values on refresh.
                # ------------------------------------------------------------------
                def _parse_dt(v):
                    if not v:
                        return None
                    try:
                        # Handles "YYYY-MM-DD HH:MM:SS.mmmmmm" and ISO strings
                        return datetime.datetime.fromisoformat(str(v))
                    except Exception:
                        return None

                history = data.get("history", [])
                ns = data.get("nevedal_state", {}) or {}
                last_updated_dt = _parse_dt(data.get("last_updated"))

                hydrated = False
                if isinstance(history, list) and history:
                    last_hist = history[-1] if isinstance(history[-1], dict) else None
                    hist_dt = _parse_dt(last_hist.get("timestamp") if last_hist else None)
                    if hist_dt and (last_updated_dt is None or last_updated_dt < hist_dt):
                        # Map history snapshot -> nevedal_state (only fields we can trust)
                        if isinstance(last_hist.get("C_emo"), (int, float)):
                            ns["C_emo"] = float(last_hist["C_emo"])
                        if isinstance(last_hist.get("GAP"), (int, float)):
                            ns["GAP"] = float(last_hist["GAP"])
                        if isinstance(last_hist.get("Quantum"), (int, float)):
                            ns["Quantum"] = float(last_hist["Quantum"])
                        # History uses "anxiety" while state uses "anxiety_level"
                        if isinstance(last_hist.get("anxiety"), (int, float)):
                            ns["anxiety_level"] = float(last_hist["anxiety"])
                        if isinstance(last_hist.get("mood"), str) and last_hist["mood"]:
                            ns["mood_current"] = last_hist["mood"]

                        data["nevedal_state"] = ns
                        data["last_updated"] = str(hist_dt)
                        hydrated = True

                if hydrated:
                    try:
                        with open(path, "w") as wf:
                            json.dump(data, wf, indent=2)
                    except Exception as e:
                        print(f">>> [METRICS DEBUG] Hydration write failed: {e}")

                print(f">>> [METRICS DEBUG] C_emo={data.get('nevedal_state', {}).get('C_emo')}, last_updated={data.get('last_updated')}")
                return data
        except Exception as e:
            print(f">>> [METRICS DEBUG] EXCEPTION: {e}")
            return {"nevedal_state": {}, "history": []}

    def update_metric(self, p: dict, key: str, value: Any):
        """Update a single metric"""
        metrics = self.load_metrics(p)
        if "nevedal_state" not in metrics:
            metrics["nevedal_state"] = {}
        metrics["nevedal_state"][key] = value
        metrics["last_updated"] = str(datetime.datetime.now())
        
        path = self._path(p)
        with open(path, 'w') as f:
            json.dump(metrics, f, indent=2)
        
        print(f">>> [OBSERVER] Updated {key} to {value} for {p.get('name')}")

    def analyze_and_update(self, p: dict, user_text: str, ai_text: str):
        """Analyze conversation and update metrics"""
        current_metrics = self.load_metrics(p)
        ns = current_metrics.get("nevedal_state", {})
        history = current_metrics.get("history", [])
        
        # === SENTIMENT ANALYSIS (Simplified) ===
        combined_text = (user_text + " " + ai_text).lower()
        
        # Positive indicators
        positive_words = ["happy", "good", "great", "better", "progress", "hopeful", 
                        "grateful", "calm", "peaceful", "excited", "love", "joy"]
        # Negative indicators
        negative_words = ["sad", "anxious", "worried", "scared", "angry", "frustrated",
                        "hopeless", "tired", "exhausted", "hate", "fear", "panic"]
        # Crisis indicators
        crisis_words = ["suicide", "kill myself", "end it", "die", "hurt myself", 
                       "self-harm", "cutting", "overdose", "no point"]
        
        pos_count = sum(1 for w in positive_words if w in combined_text)
        neg_count = sum(1 for w in negative_words if w in combined_text)
        crisis_detected = any(w in combined_text for w in crisis_words)
        
        # === UPDATE EMOTIONAL COHERENCE (C_emo) ===
        sentiment_score = (pos_count - neg_count) / max(1, pos_count + neg_count + 1)
        c_emo = ns.get("C_emo", 0.5)
        c_emo = round(c_emo * 0.7 + (0.5 + sentiment_score * 0.3) * 0.3, 2)
        c_emo = max(0.1, min(1.0, c_emo))
        self.update_metric(p, "C_emo", c_emo)
        
        # === UPDATE WARMTH (E_warmth) ===
        warmth_words = ["thank", "appreciate", "help", "support", "kind", "care"]
        warmth_score = sum(1 for w in warmth_words if w in combined_text) * 0.1
        e_warmth = ns.get("E_warmth", 0.3)
        e_warmth = round(min(1.0, e_warmth + warmth_score), 2)
        self.update_metric(p, "E_warmth", e_warmth)
        
        # === UPDATE TUNNEL (T_tunnel) - unchanged for now ===
        self.update_metric(p, "T_tunnel", ns.get("T_tunnel", 0.2))
        
        # === UPDATE ANXIETY LEVEL ===
        anxiety_words = ["anxious", "nervous", "worried", "panic", "racing", "tense"]
        anxiety_level = sum(1 for w in anxiety_words if w in combined_text) * 0.15
        anxiety_level = max(0, min(1.0, anxiety_level))
        self.update_metric(p, "anxiety_level", round(anxiety_level, 2))
        
        # === UPDATE DEPRESSION INDICATORS ===
        depression_words = ["hopeless", "worthless", "empty", "numb", "tired", "no energy"]
        depression_score = sum(1 for w in depression_words if w in combined_text) * 0.15
        depression_score = max(0, min(1.0, depression_score))
        self.update_metric(p, "depression_indicators", round(depression_score, 2))
        
        # === UPDATE STRESS LEVEL ===
        stress_words = ["stressed", "overwhelmed", "pressure", "deadline", "too much"]
        stress_level = sum(1 for w in stress_words if w in combined_text) * 0.15
        stress_level = max(0, min(1.0, stress_level))
        self.update_metric(p, "stress_level", round(stress_level, 2))
        
        # === UPDATE ENGAGEMENT ===
        word_count = len(user_text.split())
        engagement = min(1.0, word_count / 50) * 0.5 + (0.5 if "?" in user_text else 0.3)
        engagement = round((ns.get("engagement", 0.5) + engagement) / 2, 2)
        self.update_metric(p, "engagement", engagement)
        
        # === UPDATE SESSION COUNT ===
        session_count = ns.get("session_count", 0) + 1
        self.update_metric(p, "session_count", session_count)
        
        # === UPDATE MOOD ===
        if pos_count > neg_count:
            detected_mood = "happy"
        elif neg_count > pos_count:
            detected_mood = "sad"
        else:
            detected_mood = "neutral"
        
        self.update_metric(p, "mood_current", detected_mood)
        
        # Update mood history
        mood_history = ns.get("mood_history", [])
        mood_history.append({
            "date": str(datetime.datetime.now().date()),
            "mood": detected_mood,
            "anxiety": anxiety_level,
            "engagement": engagement
        })
        self.update_metric(p, "mood_history", mood_history[-30:])  # Keep last 30
        
        # === CALCULATE GAP (Growth Attunement Potential) ===
        gap = round((c_emo * 0.4 + e_warmth * 0.3 + engagement * 0.3), 3)
        self.update_metric(p, "GAP", gap)
        
        # === CALCULATE VELOCITY (Change rate) ===
        if len(history) > 0:
            prev_gap = history[-1].get("GAP", 0.3)
            velocity = round(gap - prev_gap, 3)
        else:
            velocity = 0.0
        self.update_metric(p, "Velocity", velocity)
        
        # === CALCULATE QUANTUM SCORE ===
        quantum = round(0.3 * c_emo + 0.25 * gap + 0.25 * engagement + 0.2 * (1 - anxiety_level), 3)
        self.update_metric(p, "Quantum", quantum)
        
        # === RISK ASSESSMENT ===
        risk_level = "LOW"
        if crisis_detected:
            risk_level = "CRITICAL"
            self._log_crisis(p, "crisis_keywords", user_text[:200])
        elif depression_score > 0.6 or anxiety_level > 0.7:
            risk_level = "MEDIUM"
            if depression_score > 0.8:
                risk_level = "HIGH"
        
        self.update_metric(p, "risk_level", risk_level)
        self.update_metric(p, "last_risk_assessment", str(datetime.datetime.now()))
        
        # === PATENT 2 SUBSYSTEMS: Crisis Perception, Shame, PMB, Legacy ===
        try:
            # Reload ns with latest updates for subsystem computations
            ns_fresh = self.load_metrics(p).get("nevedal_state", {})
            self._compute_crisis_perception(p, ns_fresh, user_text, sentiment_score)
            ns_fresh = self.load_metrics(p).get("nevedal_state", {})
            self._compute_shame_profile(p, ns_fresh, user_text)
            ns_fresh = self.load_metrics(p).get("nevedal_state", {})
            self._compute_pmb(p, ns_fresh, user_text, c_emo, anxiety_level, depression_score, stress_level, engagement, detected_mood)
            ns_fresh = self.load_metrics(p).get("nevedal_state", {})
            self._extract_legacy_patterns(p, ns_fresh, user_text)
            print(f">>> [PATENT2] Subsystems updated for {p.get('name')}")
        except Exception as e:
            print(f">>> [PATENT2] Subsystem error (non-fatal): {e}")
        
        # === SAVE HISTORY SNAPSHOT ===
        history.append({
            "timestamp": str(datetime.datetime.now()),
            "C_emo": c_emo,
            "GAP": gap,
            "Quantum": quantum,
            "anxiety": anxiety_level,
            "mood": detected_mood
        })
        
        # Keep last 100 history entries
        current_metrics = self.load_metrics(p)
        current_metrics["history"] = history[-100:]
        path = self._path(p)
        with open(path, 'w') as f:
            json.dump(current_metrics, f, indent=2)
        
        print(f">>> [NEVEDAL] Metrics updated for {p.get('name')}: C_emo={c_emo}, GAP={gap}, Risk={risk_level}")
        
        return {
            "C_emo": c_emo,
            "GAP": gap,
            "risk_level": risk_level,
            "mood": detected_mood
        }

    def _log_crisis(self, p: dict, trigger: str, context: str):
        """Log crisis event"""
        crisis_log = load_json_file(CRISIS_LOG_FILE, [])
        
        crisis_log.append({
            "timestamp": str(datetime.datetime.now()),
            "user_id": p.get("hardware_id"),
            "user_name": p.get("name"),
            "trigger_keyword": trigger,
            "context": context[:500],
            "status": "ACTIVE",
            "resolved": False,
            "resolved_by": "",
            "resolution_notes": ""
        })
        
        save_json_file(CRISIS_LOG_FILE, crisis_log)
        
        # Update user's crisis count
        ns = self.load_metrics(p).get("nevedal_state", {})
        self.update_metric(p, "crisis_count", ns.get("crisis_count", 0) + 1)

    # ==========================================================================
    # PATENT 2 SUBSYSTEMS: Crisis Perception, Shame, PMB, Legacy
    # ==========================================================================

    def _compute_crisis_perception(self, p: dict, ns: dict, user_text: str, sentiment_score: float):
        """
        Crisis Perception Model (Patent 2 Section 11).
        Computes objective vs expressed distress, discrepancy EMA, and baseline classification.
        """
        cp = ns.get("crisis_perception", {})
        if not isinstance(cp, dict):
            cp = {"distress_discrepancy": 0.0, "minimization_score": 0.0, "sensitivity_score": 0.0,
                  "normalization_index": 0.0, "perception_baseline": "CALIBRATING", "calibration_count": 0,
                  "discrepancy_history": []}

        # --- Objective Distress (Patent: w_coherence=0.35, w_anxiety=0.25, w_depression=0.20, w_stress=0.20) ---
        c_emo = ns.get("C_emo", 0.5)
        anxiety = ns.get("anxiety_level", 0.0)
        depression = ns.get("depression_indicators", 0.0)
        stress = ns.get("stress_level", 0.0)
        objective_distress = (1.0 - c_emo) * 0.35 + anxiety * 0.25 + depression * 0.20 + stress * 0.20
        objective_distress = max(0.0, min(1.0, objective_distress))

        # --- Expressed Distress (Patent: clamp(0.5 - sentiment, 0, 1)) ---
        expressed_distress = max(0.0, min(1.0, 0.5 - sentiment_score))

        # --- Distress Discrepancy ---
        discrepancy = objective_distress - expressed_distress

        # --- EMA (alpha=0.15) ---
        alpha_disc = 0.15
        prev_disc = cp.get("distress_discrepancy", 0.0)
        distress_discrepancy_avg = prev_disc * (1 - alpha_disc) + discrepancy * alpha_disc

        # --- Update history buffer (last 30) ---
        disc_history = cp.get("discrepancy_history", [])
        if not isinstance(disc_history, list):
            disc_history = []
        disc_history.append({
            "date": str(datetime.datetime.now().date()),
            "discrepancy": round(discrepancy, 4),
            "objective_distress": round(objective_distress, 4),
            "expressed_distress": round(expressed_distress, 4)
        })
        disc_history = disc_history[-30:]

        # --- Minimization Score (EMA of max(0, discrepancy)) ---
        prev_min = cp.get("minimization_score", 0.0)
        minimization_score = prev_min * (1 - alpha_disc) + max(0, discrepancy) * alpha_disc

        # --- Sensitivity Score (EMA of max(0, -discrepancy)) ---
        prev_sens = cp.get("sensitivity_score", 0.0)
        sensitivity_score = prev_sens * (1 - alpha_disc) + max(0, -discrepancy) * alpha_disc

        # --- Normalization Index (1 - variance*10) ---
        normalization_index = 0.0
        if len(disc_history) >= 5:
            disc_vals = [h.get("discrepancy", 0) for h in disc_history if isinstance(h, dict)]
            if disc_vals:
                mean_d = sum(disc_vals) / len(disc_vals)
                variance = sum((d - mean_d) ** 2 for d in disc_vals) / len(disc_vals)
                normalization_index = max(0.0, 1.0 - variance * 10)

        # --- Calibration count ---
        calibration_count = cp.get("calibration_count", 0) + 1

        # --- Perception Baseline Classification (Patent: after 10 messages) ---
        perception_baseline = cp.get("perception_baseline", "CALIBRATING")
        if calibration_count >= 10:
            if normalization_index > 0.5 and minimization_score > 0.3:
                perception_baseline = "NORMALIZER"
            elif minimization_score > 0.25:
                perception_baseline = "MINIMIZER"
            elif sensitivity_score > 0.25:
                perception_baseline = "AMPLIFIER"
            else:
                perception_baseline = "CALIBRATED"

        updated_cp = {
            "distress_discrepancy": round(distress_discrepancy_avg, 4),
            "minimization_score": round(minimization_score, 4),
            "sensitivity_score": round(sensitivity_score, 4),
            "normalization_index": round(normalization_index, 4),
            "perception_baseline": perception_baseline,
            "calibration_count": calibration_count,
            "discrepancy_history": disc_history
        }
        self.update_metric(p, "crisis_perception", updated_cp)
        return updated_cp

    def _compute_shame_profile(self, p: dict, ns: dict, user_text: str):
        """
        Shame Detection and Core Belief Extraction (Patent 2 Section 12).
        Three indicator channels, perception-weighted shame index, core belief extraction,
        shame map construction, masking pattern classification.
        """
        sp = ns.get("shame_profile", {})
        if not isinstance(sp, dict):
            sp = {"shame_index": 0.0, "shame_baseline": 0.0, "core_beliefs": [], "shame_map": [],
                  "shame_indicators_history": [], "shame_masking_pattern": "UNKNOWN"}

        text_lower = user_text.lower()

        # --- Self-Blame Channel (Patent: w_blame=0.35) ---
        self_blame_phrases = ["my fault", "i should have", "i'm sorry for", "i'm the problem",
                              "i messed up", "i ruined", "i caused", "i'm to blame",
                              "i deserve this", "what's wrong with me", "i should've"]
        self_blame = min(1.0, sum(1 for ph in self_blame_phrases if ph in text_lower) * 0.25)

        # --- Unworthiness Channel (Patent: w_unworthy=0.40) ---
        unworthiness_phrases = ["i'm not enough", "i don't deserve", "i'm worthless",
                                "nobody cares", "i'm a burden", "i'm broken", "i'm damaged",
                                "i'm unlovable", "i'll never be", "i can't do anything right",
                                "what's the point", "i'm not worth", "i don't matter"]
        unworthiness = min(1.0, sum(1 for ph in unworthiness_phrases if ph in text_lower) * 0.25)

        # --- Deflection Channel (Patent: w_deflect=0.25) ---
        deflection_phrases = ["it's not a big deal", "i don't want to talk about",
                              "let's change the subject", "it doesn't matter",
                              "i'm fine really", "forget i said anything", "never mind",
                              "it's whatever", "i don't care", "doesn't bother me",
                              "it's fine", "no big deal"]
        deflection = min(1.0, sum(1 for ph in deflection_phrases if ph in text_lower) * 0.25)

        # --- Raw Shame Index ---
        raw_shame = self_blame * 0.35 + unworthiness * 0.40 + deflection * 0.25

        # --- Perception Multiplier (Patent: minimizer=1.3, normalizer=1.5, other=1.0) ---
        cp = ns.get("crisis_perception", {})
        baseline = cp.get("perception_baseline", "CALIBRATING") if isinstance(cp, dict) else "CALIBRATING"
        perception_multiplier = 1.0
        if baseline == "MINIMIZER":
            perception_multiplier = 1.3
        elif baseline == "NORMALIZER":
            perception_multiplier = 1.5

        shame_index = min(1.0, raw_shame * perception_multiplier)

        # --- Shame Baseline EMA (alpha=0.12) ---
        alpha_shame = 0.12
        prev_baseline = sp.get("shame_baseline", 0.0)
        shame_baseline = prev_baseline * (1 - alpha_shame) + shame_index * alpha_shame

        # --- Core Belief Extraction (Patent: threshold 0.30 for extraction) ---
        core_beliefs = sp.get("core_beliefs", [])
        if not isinstance(core_beliefs, list):
            core_beliefs = []

        belief_patterns = {
            "I am not enough": ["not enough", "not good enough", "never enough"],
            "I am unlovable": ["unlovable", "nobody loves", "can't be loved"],
            "I am broken": ["i'm broken", "something is wrong with me", "i'm damaged"],
            "I deserved it": ["i deserved", "my fault", "i asked for it"],
            "I am a burden": ["i'm a burden", "too much for", "bothering you"],
            "I am invisible": ["no one notices", "no one sees", "don't matter"],
            "I must be perfect": ["have to be perfect", "can't make mistakes", "not good enough"],
            "I am unsafe": ["can't trust", "never safe", "always waiting for"]
        }

        # Detect topics in text for shame map
        topic_keywords = {
            "father": ["dad", "father", "my old man", "papa"],
            "mother": ["mom", "mother", "mama", "ma"],
            "childhood": ["growing up", "when i was a kid", "as a child", "childhood"],
            "work": ["work", "job", "boss", "career", "office"],
            "partner": ["partner", "husband", "wife", "boyfriend", "girlfriend", "spouse"],
            "self_worth": ["worth", "enough", "deserve", "value"],
            "abandonment": ["left me", "walked out", "abandoned", "alone"],
            "trauma": ["trauma", "abuse", "hurt", "violated"]
        }
        detected_topics = []
        for topic, kws in topic_keywords.items():
            if any(kw in text_lower for kw in kws):
                detected_topics.append(topic)

        if shame_index > 0.30:
            for belief_name, phrases in belief_patterns.items():
                if any(ph in text_lower for ph in phrases):
                    # Update or create belief entry
                    found = False
                    for b in core_beliefs:
                        if isinstance(b, dict) and b.get("belief") == belief_name:
                            b["confidence"] = min(0.99, b.get("confidence", 0.30) + 0.05)
                            b["frequency"] = b.get("frequency", 0) + 1
                            existing_topics = b.get("associated_topics", [])
                            for t in detected_topics:
                                if t not in existing_topics:
                                    existing_topics.append(t)
                            b["associated_topics"] = existing_topics
                            found = True
                            break
                    if not found:
                        core_beliefs.append({
                            "belief": belief_name,
                            "confidence": 0.30,
                            "first_detected": str(datetime.datetime.now().date()),
                            "frequency": 1,
                            "associated_topics": detected_topics
                        })

        # --- Shame Map Update (Patent: threshold 0.20 for topic association) ---
        shame_map = sp.get("shame_map", [])
        if not isinstance(shame_map, list):
            shame_map = []

        if shame_index > 0.20 and detected_topics:
            for topic in detected_topics:
                found_entry = False
                for entry in shame_map:
                    if isinstance(entry, dict) and entry.get("topic") == topic:
                        n = entry.get("occurrences", 0)
                        prev_intensity = entry.get("shame_intensity", 0.0)
                        entry["shame_intensity"] = round((prev_intensity * n + shame_index) / (n + 1), 4)
                        entry["occurrences"] = n + 1
                        # Update dominant belief
                        topic_beliefs = [b for b in core_beliefs if isinstance(b, dict) and topic in b.get("associated_topics", [])]
                        if topic_beliefs:
                            entry["dominant_belief"] = max(topic_beliefs, key=lambda x: x.get("frequency", 0)).get("belief", "")
                        found_entry = True
                        break
                if not found_entry:
                    dominant = ""
                    topic_beliefs = [b for b in core_beliefs if isinstance(b, dict) and topic in b.get("associated_topics", [])]
                    if topic_beliefs:
                        dominant = max(topic_beliefs, key=lambda x: x.get("frequency", 0)).get("belief", "")
                    shame_map.append({
                        "topic": topic,
                        "shame_intensity": round(shame_index, 4),
                        "occurrences": 1,
                        "dominant_belief": dominant
                    })

        # --- Shame Masking Pattern Classification ---
        anxiety_words = ["anxious", "nervous", "worried", "panic", "scared", "afraid", "fear"]
        anger_words_shame = ["angry", "furious", "hate", "blame", "unfair", "resentment"]
        accommodation_words = ["sorry", "whatever you think", "i should", "you're right", "my fault"]
        has_anxiety = any(w in text_lower for w in anxiety_words)
        has_anger = any(w in text_lower for w in anger_words_shame)
        has_accommodation = any(w in text_lower for w in accommodation_words)

        masking_pattern = sp.get("shame_masking_pattern", "UNKNOWN")
        if shame_index > 0.20:
            if has_anxiety:
                masking_pattern = "FEAR_MASKED"
            elif has_anger:
                masking_pattern = "ANGER_MASKED"
            elif deflection > 0.20 and (baseline == "MINIMIZER" or baseline == "NORMALIZER"):
                masking_pattern = "WITHDRAWAL_MASKED"
            elif self_blame > 0.20 and has_accommodation:
                masking_pattern = "PEOPLE_PLEASING_MASKED"

        # --- Shame Indicators History (last 30) ---
        shame_history = sp.get("shame_indicators_history", [])
        if not isinstance(shame_history, list):
            shame_history = []
        shame_history.append({
            "date": str(datetime.datetime.now().date()),
            "shame_index": round(shame_index, 4),
            "deflection": round(deflection, 4),
            "self_blame": round(self_blame, 4),
            "unworthiness": round(unworthiness, 4)
        })
        shame_history = shame_history[-30:]

        updated_sp = {
            "shame_index": round(shame_index, 4),
            "shame_baseline": round(shame_baseline, 4),
            "core_beliefs": core_beliefs,
            "shame_map": shame_map,
            "shame_indicators_history": shame_history,
            "shame_masking_pattern": masking_pattern
        }
        self.update_metric(p, "shame_profile", updated_sp)
        return updated_sp

    def _compute_pmb(self, p: dict, ns: dict, user_text: str, c_emo: float, anxiety: float,
                     depression: float, stress: float, engagement: float, detected_mood: str):
        """
        Predictability Model of Behavior (Patent 2 Section 13).
        Cyclical patterns, trigger-topic mapping, reactivity classification,
        reconsolidation readiness, prediction generation with confidence gates.
        """
        pmb = ns.get("pmb", {})
        if not isinstance(pmb, dict):
            pmb = {"cyclical_patterns": [], "crisis_precursors": [], "trigger_map": [],
                   "reactivity_type": "MIXED", "reactivity_indicators": {"fight": 0.0, "flight": 0.0, "freeze": 0.0, "fawn": 0.0},
                   "reconsolidation_readiness": 0.0, "reconsolidation_targets": [], "legacy_patterns": [],
                   "predictions": [], "last_pmb_update": "", "pmb_version": 1}

        text_lower = user_text.lower()
        mood_history = ns.get("mood_history", [])

        # === CYCLICAL PATTERN DETECTION (Patent 13.2) ===
        cyclical_patterns = pmb.get("cyclical_patterns", [])
        if isinstance(mood_history, list) and len(mood_history) >= 28:
            day_groups = {}
            for entry in mood_history:
                if not isinstance(entry, dict):
                    continue
                try:
                    d = datetime.datetime.strptime(entry.get("date", ""), "%Y-%m-%d")
                    day_name = d.strftime("%A")
                    if day_name not in day_groups:
                        day_groups[day_name] = []
                    day_groups[day_name].append(entry)
                except (ValueError, TypeError):
                    continue

            overall_anxiety = sum(e.get("anxiety", 0) for e in mood_history if isinstance(e, dict)) / max(1, len(mood_history))
            cyclical_patterns = []
            for day, entries in day_groups.items():
                if len(entries) >= 3:
                    day_anxiety = sum(e.get("anxiety", 0) for e in entries) / len(entries)
                    delta = day_anxiety - overall_anxiety
                    if abs(delta) > 0.1:
                        conf = min(0.9, len(entries) * 0.15)
                        cyclical_patterns.append({
                            "cycle_type": "weekly",
                            "period_key": day,
                            "metric": "anxiety",
                            "average_delta": round(delta, 4),
                            "confidence": round(conf, 2)
                        })

        # === TRIGGER-TOPIC MAPPING (Patent 13.4) ===
        trigger_map = pmb.get("trigger_map", [])
        if not isinstance(trigger_map, list):
            trigger_map = []

        trigger_topics = {
            "father": ["dad", "father", "my old man", "papa"],
            "mother": ["mom", "mother", "mama"],
            "childhood": ["growing up", "when i was a kid", "childhood"],
            "work": ["work", "job", "boss", "career"],
            "partner": ["partner", "husband", "wife", "boyfriend", "girlfriend"],
            "abuse": ["abuse", "abused", "violated", "hit me"],
            "trauma": ["trauma", "traumatic", "ptsd"],
            "loss": ["died", "death", "lost", "funeral", "grief", "passed away"]
        }

        for topic, kws in trigger_topics.items():
            if any(kw in text_lower for kw in kws):
                # Determine dominant metric effect
                effects = []
                if anxiety > 0.3:
                    effects.append("anxiety_spike")
                if stress > 0.3:
                    effects.append("stress_spike")
                sp = ns.get("shame_profile", {})
                if isinstance(sp, dict) and sp.get("shame_index", 0) > 0.2:
                    effects.append("shame_spike")
                dominant_effect = effects[0] if effects else "neutral"

                found = False
                for entry in trigger_map:
                    if isinstance(entry, dict) and entry.get("topic") == topic:
                        n = entry.get("occurrences", 0)
                        entry["occurrences"] = n + 1
                        if dominant_effect != "neutral":
                            entry["effect"] = dominant_effect
                        found = True
                        break
                if not found:
                    trigger_map.append({
                        "topic": topic,
                        "effect": dominant_effect,
                        "average_delta": round(anxiety, 4),
                        "occurrences": 1
                    })

        # === REACTIVITY SIGNATURE CLASSIFICATION (Patent 13.5, EMA alpha=0.1) ===
        react_ind = pmb.get("reactivity_indicators", {"fight": 0.0, "flight": 0.0, "freeze": 0.0, "fawn": 0.0})
        if not isinstance(react_ind, dict):
            react_ind = {"fight": 0.0, "flight": 0.0, "freeze": 0.0, "fawn": 0.0}

        alpha_react = 0.1
        fight_words = ["angry", "furious", "blame", "unfair", "hate", "stupid", "idiot"]
        fawn_words = ["sorry", "my fault", "whatever you think", "i should", "you're right"]
        word_count = len(user_text.split())

        fight_signal = 1.0 if any(w in text_lower for w in fight_words) else 0.0
        flight_signal = 1.0 if (engagement < 0.3 or word_count < 5) else 0.0
        freeze_signal = 1.0 if (engagement < 0.2 and anxiety > 0.4) else 0.0
        fawn_signal = 1.0 if any(w in text_lower for w in fawn_words) else 0.0

        react_ind["fight"] = round(react_ind.get("fight", 0.0) * (1 - alpha_react) + fight_signal * alpha_react, 4)
        react_ind["flight"] = round(react_ind.get("flight", 0.0) * (1 - alpha_react) + flight_signal * alpha_react, 4)
        react_ind["freeze"] = round(react_ind.get("freeze", 0.0) * (1 - alpha_react) + freeze_signal * alpha_react, 4)
        react_ind["fawn"] = round(react_ind.get("fawn", 0.0) * (1 - alpha_react) + fawn_signal * alpha_react, 4)

        # Normalize and classify
        total_react = sum(react_ind.values())
        if total_react > 0:
            normalized = {k: v / total_react for k, v in react_ind.items()}
            reactivity_type = max(normalized, key=normalized.get).upper()
            if normalized[reactivity_type.lower()] < 0.6:
                reactivity_type = "MIXED"
        else:
            reactivity_type = "MIXED"

        # === RECONSOLIDATION READINESS (Patent 13.6) ===
        in_therapeutic_range = 1.0 if 0.3 <= c_emo <= 0.7 else 0.0
        emotional_charge = max(anxiety, depression, stress)
        # Check if known trigger topic present (3+ occurrences)
        trigger_present = 0.0
        for entry in trigger_map:
            if isinstance(entry, dict) and entry.get("occurrences", 0) >= 3:
                topic_kws = trigger_topics.get(entry.get("topic", ""), [])
                if any(kw in text_lower for kw in topic_kws):
                    trigger_present = 1.0
                    break

        reconsolidation_readiness = round(
            in_therapeutic_range * 0.30 + engagement * 0.25 + emotional_charge * 0.25 + trigger_present * 0.20,
            4
        )

        # === PREDICTION GENERATION (Patent 13.7) ===
        predictions = []
        for cp in cyclical_patterns:
            if isinstance(cp, dict) and cp.get("confidence", 0) >= 0.5:
                predictions.append({
                    "prediction": f"{cp.get('metric', 'metric')} tends to shift on {cp.get('period_key', 'unknown')}",
                    "timeframe": cp.get("period_key", ""),
                    "confidence": cp.get("confidence", 0),
                    "basis": "cyclical_pattern",
                    "actionable": cp.get("confidence", 0) >= 0.95
                })

        updated_pmb = {
            "cyclical_patterns": cyclical_patterns,
            "crisis_precursors": pmb.get("crisis_precursors", []),
            "trigger_map": trigger_map,
            "reactivity_type": reactivity_type,
            "reactivity_indicators": react_ind,
            "reconsolidation_readiness": reconsolidation_readiness,
            "reconsolidation_targets": pmb.get("reconsolidation_targets", []),
            "legacy_patterns": pmb.get("legacy_patterns", []),
            "predictions": predictions,
            "last_pmb_update": str(datetime.datetime.now()),
            "pmb_version": pmb.get("pmb_version", 1)
        }
        self.update_metric(p, "pmb", updated_pmb)
        return updated_pmb

    def _extract_legacy_patterns(self, p: dict, ns: dict, user_text: str):
        """
        Transgenerational Legacy Analysis (Patent 2 Section 14).
        Family-of-origin reference detection and legacy pattern keyword matching.
        """
        pmb = ns.get("pmb", {})
        if not isinstance(pmb, dict):
            return

        legacy_patterns = pmb.get("legacy_patterns", [])
        if not isinstance(legacy_patterns, list):
            legacy_patterns = []

        text_lower = user_text.lower()

        # --- Family-of-Origin Reference Detection (Patent 14.1) ---
        family_refs = {
            "father": ["dad", "father", "my old man", "papa"],
            "mother": ["mom", "mother", "mama", "ma"],
            "grandparent": ["grandma", "grandpa", "grandmother", "grandfather", "nana"],
            "family_general": ["growing up", "my family", "back home", "when i was a kid"]
        }

        detected_source = None
        for source, keywords in family_refs.items():
            if any(kw in text_lower for kw in keywords):
                detected_source = source
                break

        if not detected_source:
            return  # No family reference detected

        # --- Legacy Pattern Keyword Matching (Patent 14.1, 8 categories) ---
        pattern_keywords = {
            "emotional_suppression": ["never showed emotion", "bottled up", "kept it inside", "didn't cry", "held it in", "never talked about feelings"],
            "caretaker_role": ["took care of everyone", "never complained", "sacrificed", "always putting others first", "had to be the strong one"],
            "rage_cycle": ["would explode", "angry outbursts", "violent temper", "flew off the handle", "rage", "would hit"],
            "abandonment": ["left us", "walked out", "wasn't there", "disappeared", "never came back"],
            "perfectionism": ["nothing was good enough", "had to be perfect", "couldn't make mistakes", "never satisfied"],
            "addiction": ["drank too much", "was an addict", "used drugs", "alcoholic", "couldn't stop"],
            "enmeshment": ["no boundaries", "had to know everything", "controlled", "couldn't have privacy", "too close"],
            "neglect": ["didn't notice", "wasn't paying attention", "too busy", "never around", "forgot about us"]
        }

        for pattern_name, phrases in pattern_keywords.items():
            if any(ph in text_lower for ph in phrases):
                # Check if already stored
                already_exists = any(
                    isinstance(lp, dict) and lp.get("source") == detected_source and lp.get("pattern") == pattern_name
                    for lp in legacy_patterns
                )
                if not already_exists:
                    legacy_patterns.append({
                        "source": detected_source,
                        "pattern": pattern_name,
                        "client_quote": user_text[:200],
                        "extracted_at": str(datetime.datetime.now().date()),
                        "reflected_in_client": False,
                        "cross_validated": False
                    })

        # Keep max 20 per user
        legacy_patterns = legacy_patterns[-20:]

        # --- Cross-reference legacy with client's own behavior ---
        cp = ns.get("crisis_perception", {})
        baseline = cp.get("perception_baseline", "CALIBRATING") if isinstance(cp, dict) else "CALIBRATING"
        react_type = pmb.get("reactivity_type", "MIXED")

        behavior_correlates = {
            "emotional_suppression": lambda: baseline == "MINIMIZER",
            "caretaker_role": lambda: react_type == "FAWN",
            "rage_cycle": lambda: react_type in ["FIGHT", "FREEZE"],
            "abandonment": lambda: baseline == "AMPLIFIER",
            "perfectionism": lambda: any(isinstance(b, dict) and b.get("belief") == "I must be perfect" for b in ns.get("shame_profile", {}).get("core_beliefs", [])),
            "neglect": lambda: any(isinstance(b, dict) and b.get("belief") == "I am invisible" for b in ns.get("shame_profile", {}).get("core_beliefs", []))
        }

        for lp in legacy_patterns:
            if isinstance(lp, dict) and not lp.get("reflected_in_client"):
                pattern = lp.get("pattern", "")
                check = behavior_correlates.get(pattern)
                if check and check():
                    lp["reflected_in_client"] = True

        # Update the PMB's legacy_patterns
        current_pmb = ns.get("pmb", {})
        if isinstance(current_pmb, dict):
            current_pmb["legacy_patterns"] = legacy_patterns
            self.update_metric(p, "pmb", current_pmb)

    def get_metrics_summary(self, p: dict) -> dict:
        """Get formatted metrics summary for display"""
        metrics = self.load_metrics(p)
        ns = metrics.get("nevedal_state", {})
        
        return {
            "coherence": f"{ns.get('C_emo', 0.5) * 100:.0f}%",
            "growth_potential": f"{ns.get('GAP', 0.3) * 100:.0f}%",
            "wellness_score": f"{ns.get('Quantum', 0.5) * 100:.0f}%",
            "anxiety_level": f"{ns.get('anxiety_level', 0) * 100:.0f}%",
            "engagement": f"{ns.get('engagement', 0.5) * 100:.0f}%",
            "sessions_total": ns.get("session_count", 0),
            "breakthroughs": ns.get("breakthrough_count", 0),
            "current_mood": ns.get("mood_current", "neutral"),
            "mood_trend": ns.get("mood_trend", "stable"),
            "risk_level": ns.get("risk_level", "LOW"),
            "last_updated": metrics.get("last_updated", "")
        }

# ------------------------------------------------------------------------------
# PART 6: SESSION TRACKING SYSTEM
# ------------------------------------------------------------------------------
class SessionTracker:
    def __init__(self, data_dir: Path):
        self.sessions_file = data_dir / "sessions.json"
    
    def load_sessions(self) -> List[dict]:
        return load_json_file(self.sessions_file, [])
    
    def save_sessions(self, sessions: List[dict]) -> bool:
        return save_json_file(self.sessions_file, sessions)
    
    def create_session(self, client_id: str, session_type: str = "AI", 
                       coach_id: str = None) -> dict:
        """Create a new session"""
        session = {
            "session_id": generate_session_id(),
            "client_id": client_id,
            "coach_id": coach_id,
            "session_type": session_type,  # AI, COACH, FAMILY
            "status": "active",
            "scheduled_start": None,
            "scheduled_end": None,
            "actual_start": str(datetime.datetime.now()),
            "actual_end": None,
            "duration_seconds": 0,
            "zoom_meeting_id": "",
            "recording_url": "",
            "transcript_summary": "",
            "topics_covered": [],
            "mood_at_start": "",
            "mood_at_end": "",
            "homework_assigned": [],
            "coach_notes": "",
            "nate_summary": "",
            "message_count": 0,
            "created_at": str(datetime.datetime.now())
        }
        
        sessions = self.load_sessions()
        sessions.append(session)
        self.save_sessions(sessions)
        
        LIVE_SESSION_TRACKER[session["session_id"]] = session
        
        return session
    
    def end_session(self, session_id: str, summary: str = "", 
                    mood_at_end: str = "", topics: List[str] = None) -> bool:
        """End a session and calculate duration"""
        sessions = self.load_sessions()
        
        for session in sessions:
            if session["session_id"] == session_id:
                session["actual_end"] = str(datetime.datetime.now())
                session["status"] = "completed"
                
                # Calculate duration
                try:
                    start = datetime.datetime.fromisoformat(session["actual_start"])
                    end = datetime.datetime.now()
                    session["duration_seconds"] = int((end - start).total_seconds())
                except:
                    pass
                
                session["nate_summary"] = summary
                session["mood_at_end"] = mood_at_end
                if topics:
                    session["topics_covered"] = topics
                
                self.save_sessions(sessions)
                
                if session_id in LIVE_SESSION_TRACKER:
                    del LIVE_SESSION_TRACKER[session_id]
                
                return True
        
        return False
    
    def get_client_sessions(self, client_id: str, limit: int = 10) -> List[dict]:
        """Get sessions for a client"""
        sessions = self.load_sessions()
        client_sessions = [s for s in sessions if s.get("client_id") == client_id]
        return sorted(client_sessions, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
    
    def get_coach_sessions(self, coach_id: str, limit: int = 20) -> List[dict]:
        """Get sessions for a coach"""
        sessions = self.load_sessions()
        coach_sessions = [s for s in sessions if s.get("coach_id") == coach_id]
        return sorted(coach_sessions, key=lambda x: x.get("created_at", ""), reverse=True)[:limit]
    
    def schedule_session(self, client_id: str, coach_id: str, 
                        scheduled_start: str, scheduled_end: str,
                        session_type: str = "COACH") -> dict:
        """Schedule a future session"""
        session = {
            "session_id": generate_session_id(),
            "client_id": client_id,
            "coach_id": coach_id,
            "session_type": session_type,
            "status": "scheduled",
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "actual_start": None,
            "actual_end": None,
            "duration_seconds": 0,
            "zoom_meeting_id": "",
            "recording_url": "",
            "transcript_summary": "",
            "topics_covered": [],
            "mood_at_start": "",
            "mood_at_end": "",
            "homework_assigned": [],
            "coach_notes": "",
            "nate_summary": "",
            "message_count": 0,
            "created_at": str(datetime.datetime.now())
        }
        
        sessions = self.load_sessions()
        sessions.append(session)
        self.save_sessions(sessions)
        
        return session

# ------------------------------------------------------------------------------
# PART 7: BILLING & SUBSCRIPTION SYSTEM
# ------------------------------------------------------------------------------
class BillingSystem:
    def __init__(self, data_dir: Path):
        self.billing_file = data_dir / "billing.json"
        self.transactions_file = data_dir / "transactions.json"
    
    def load_billing(self) -> dict:
        return load_json_file(self.billing_file, {"customers": {}, "subscriptions": {}})
    
    def save_billing(self, data: dict) -> bool:
        return save_json_file(self.billing_file, data)
    
    def create_customer(self, user_id: str, email: str, name: str) -> dict:
        """Create billing customer record"""
        billing = self.load_billing()
        
        customer = {
            "user_id": user_id,
            "email": email,
            "name": name,
            "stripe_customer_id": "",  # Will be set when Stripe is called
            "created_at": str(datetime.datetime.now()),
            "payment_methods": [],
            "default_payment_method": ""
        }
        
        billing["customers"][user_id] = customer
        self.save_billing(billing)
        
        return customer
    
    def create_subscription(self, user_id: str, plan: str, 
                           price_id: str = "", stripe_sub_id: str = "") -> dict:
        """Create subscription record"""
        billing = self.load_billing()
        
        # Aligned with config/standing_orders_seed.json
        plan_details = {
            "COACH_ONLY": {"tokens": 0, "ai_minutes": 0, "coach_sessions": -1, "price": 0, "duration_days": 365, "can_access_nate": False},
            "TRIAL": {"tokens": 10000, "ai_minutes": 30, "coach_sessions": 0, "price": 0, "duration_days": 14},
            "STANDARD": {"tokens": 50000, "ai_minutes": 300, "coach_sessions": 4, "price": 49, "duration_days": 30},
            "TOP_TIER": {"tokens": 200000, "ai_minutes": -1, "coach_sessions": 8, "price": 149, "duration_days": 30},
        }
        
        details = plan_details.get(plan, plan_details["STANDARD"])
        
        subscription = {
            "user_id": user_id,
            "plan": plan,
            "stripe_subscription_id": stripe_sub_id,
            "stripe_price_id": price_id,
            "status": "active",
            "tokens_included": details["tokens"],
            "coach_sessions_included": details["coach_sessions"],
            "monthly_price": details["price"],
            "start_date": str(datetime.datetime.now().date()),
            "end_date": str((datetime.datetime.now() + datetime.timedelta(days=details["duration_days"])).date()),
            "next_billing_date": str((datetime.datetime.now() + datetime.timedelta(days=details["duration_days"])).date()),
            "created_at": str(datetime.datetime.now()),
            "cancelled_at": None
        }
        
        billing["subscriptions"][user_id] = subscription
        self.save_billing(billing)
        
        # Update user profile
        registry = load_registry()
        for k, v in registry.items():
            if v["profile"].get("hardware_id") == user_id or k.endswith(user_id.lower()):
                v["profile"]["subscription_plan"] = plan
                v["profile"]["subscription_status"] = "ACTIVE"
                v["profile"]["token_balance"] = details["tokens"]
                save_registry(registry)
                break
        
        return subscription
    
    def get_subscription(self, user_id: str) -> Optional[dict]:
        """Get user's subscription"""
        billing = self.load_billing()
        return billing.get("subscriptions", {}).get(user_id)
    
    def record_transaction(
        self,
        user_id: str,
        amount: float,
        description: str,
        transaction_type: str = "charge",
        status: str = "completed",
        metadata: dict = None,
    ) -> dict:
        """Record a billing transaction"""
        transactions = load_json_file(self.transactions_file, [])
        
        transaction = {
            "transaction_id": f"TXN_{secrets.token_hex(8).upper()}",
            "user_id": user_id,
            "amount": amount,
            "currency": "USD",
            "description": description,
            "type": transaction_type,  # charge, refund, credit
            "status": status,
            "created_at": str(datetime.datetime.now()),
            "metadata": metadata or {},
        }
        
        transactions.append(transaction)
        save_json_file(self.transactions_file, transactions)
        
        return transaction
    
    def use_tokens(self, user_id: str, tokens_used: int) -> Tuple[bool, int]:
        """Deduct tokens from user's balance"""
        registry = load_registry()
        
        for k, v in registry.items():
            profile = v.get("profile", {})
            if profile.get("hardware_id") == user_id:
                current_balance = profile.get("token_balance", 0)
                
                if current_balance < tokens_used:
                    return False, current_balance
                
                profile["token_balance"] = current_balance - tokens_used
                profile["token_usage_today"] = profile.get("token_usage_today", 0) + tokens_used
                profile["token_usage_month"] = profile.get("token_usage_month", 0) + tokens_used
                
                save_registry(registry)
                return True, profile["token_balance"]
        
        return False, 0

    def add_token_usage(self, user_id: str, tokens_used: int, deduct_balance: bool = False) -> Tuple[bool, int]:
        """
        Record token usage on a profile.

        - Always increments token_usage_today/month.
        - Optionally decrements token_balance when deduct_balance=True.
        Returns (success, resulting_balance).
        """
        try:
            tokens_used = int(tokens_used or 0)
        except Exception:
            tokens_used = 0

        if tokens_used <= 0:
            # Nothing to record; still return current balance if possible.
            registry = load_registry()
            for _, v in (registry or {}).items():
                p = (v or {}).get("profile", {}) or {}
                if p.get("hardware_id") == user_id:
                    return True, int(p.get("token_balance", 0) or 0)
            return True, 0

        registry = load_registry()
        for _, v in (registry or {}).items():
            profile = (v or {}).get("profile", {}) or {}
            if profile.get("hardware_id") != user_id:
                continue

            current_balance = int(profile.get("token_balance", 0) or 0)
            if deduct_balance:
                if current_balance < tokens_used:
                    return False, current_balance
                profile["token_balance"] = current_balance - tokens_used

            profile["token_usage_today"] = int(profile.get("token_usage_today", 0) or 0) + tokens_used
            profile["token_usage_month"] = int(profile.get("token_usage_month", 0) or 0) + tokens_used
            save_registry(registry)

            return True, int(profile.get("token_balance", 0) or 0)

        return False, 0
    
    def get_usage_stats(self, user_id: str) -> dict:
        """Get token usage statistics"""
        registry = load_registry()
        
        for k, v in registry.items():
            profile = v.get("profile", {})
            if profile.get("hardware_id") == user_id:
                return {
                    "token_balance": profile.get("token_balance", 0),
                    "tokens_used_today": profile.get("token_usage_today", 0),
                    "tokens_used_month": profile.get("token_usage_month", 0),
                    "subscription_plan": profile.get("subscription_plan", "TRIAL"),
                    "subscription_status": profile.get("subscription_status", "TRIAL_ACTIVE")
                }
        
        return {}

# ------------------------------------------------------------------------------
# PART 8: NIGHT SCHOOL (Learning Engine)
# ------------------------------------------------------------------------------
class NightSchool:
    def __init__(self, root: Path):
        self.root = root
        self.wisdom_file = root / "Admin" / "little_nate_wisdom.json"
        self.learnings_file = root / "Admin" / "learning_history.json"
    
    def load_wisdom(self) -> str:
        if not self.wisdom_file.exists():
            return "Focus on empathy, safety, and client growth. Always validate feelings before offering solutions."
        try:
            with open(self.wisdom_file, 'r') as f:
                data = json.load(f)
                return data.get("accumulated_learnings", "Focus on empathy and safety.")
        except:
            return "Focus on empathy and safety."
    
    def get_wisdom_structured(self) -> dict:
        """Get structured wisdom data"""
        if not self.wisdom_file.exists():
            return {"accumulated_learnings": "", "entries": [], "last_synthesis": ""}
        try:
            with open(self.wisdom_file, 'r') as f:
                return json.load(f)
        except:
            return {"accumulated_learnings": "", "entries": [], "last_synthesis": ""}

    async def start_session(self):
        """Run Night School learning session"""
        print("[*] NIGHT SCHOOL: Session Active. Scanning training materials...")
        
        # Process Admin folder
        admin_folder = self.root / "Admin" / "admin_LN_training_folder"
        if admin_folder.exists():
            await self._process_folder(admin_folder, "ADMIN_CURRICULUM")
        
        # Process Coach folders
        coaches_dir = self.root / "Coaches"
        if coaches_dir.exists():
            for coach_dir in coaches_dir.iterdir():
                if coach_dir.is_dir():
                    for sub in coach_dir.iterdir():
                        if sub.is_dir() and sub.name.endswith("_LN_training_folder"):
                            await self._process_folder(sub, f"COACH_{coach_dir.name}")
        
        # Synthesize learnings
        await self._synthesize_learnings()
        
        print("[*] NIGHT SCHOOL: Session Complete.")

    async def _process_folder(self, folder_path: Path, source_tag: str):
        """Process training materials from a folder"""
        if not folder_path.exists():
            return
        
        for file in folder_path.iterdir():
            if file.suffix in ['.txt', '.log', '.json', '.md']:
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if len(content) > 10:
                            print(f"   [NIGHT SCHOOL] Ingesting {file.name} from {source_tag}...")
                            self.add_learning(
                                content=content[:2000],
                                source=source_tag,
                                filename=file.name
                            )
                except Exception as e:
                    print(f"   [NIGHT SCHOOL] Error reading {file.name}: {e}")

    def add_learning(self, content: str, source: str, filename: str = "", 
                    category: str = "general"):
        """Add a new learning entry"""
        learnings = load_json_file(self.learnings_file, [])
        
        # Check for duplicates
        content_hash = hashlib.md5(content.encode()).hexdigest()
        for entry in learnings:
            if entry.get("content_hash") == content_hash:
                return  # Skip duplicate
        
        entry = {
            "id": secrets.token_hex(8),
            "content": content,
            "content_hash": content_hash,
            "source": source,
            "filename": filename,
            "category": category,
            "timestamp": str(datetime.datetime.now()),
            "times_applied": 0,
            "effectiveness_score": 0.5,
            "deprecated": False
        }
        
        learnings.append(entry)
        save_json_file(self.learnings_file, learnings[-1000:])  # Keep last 1000

    async def _synthesize_learnings(self):
        """Synthesize learnings into accumulated wisdom"""
        learnings = load_json_file(self.learnings_file, [])
        
        if not learnings:
            return
        
        # Get recent, non-deprecated learnings
        active_learnings = [l for l in learnings if not l.get("deprecated", False)]
        recent = active_learnings[-50:]  # Last 50 entries
        
        # Create synthesis (in production, this would use AI)
        synthesis_parts = []
        
        # Group by category
        categories = {}
        for l in recent:
            cat = l.get("category", "general")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(l["content"][:200])
        
        for cat, contents in categories.items():
            synthesis_parts.append(f"[{cat.upper()}]: {'; '.join(contents[:5])}")
        
        wisdom_data = {
            "accumulated_learnings": "\n".join(synthesis_parts),
            "entries_count": len(active_learnings),
            "last_synthesis": str(datetime.datetime.now()),
            "categories": list(categories.keys())
        }
        
        save_json_file(self.wisdom_file, wisdom_data)

    def get_coach_contribution(self, coach_id: str) -> dict:
        """Get learning contributions from a specific coach"""
        learnings = load_json_file(self.learnings_file, [])
        coach_learnings = [l for l in learnings if coach_id in l.get("source", "")]
        
        return {
            "total_contributions": len(coach_learnings),
            "categories": list(set(l.get("category", "general") for l in coach_learnings)),
            "recent": coach_learnings[-10:]
        }

# ------------------------------------------------------------------------------
# PART 9: ANALYTICS ENGINE
# ------------------------------------------------------------------------------
class AnalyticsEngine:
    def __init__(self, data_dir: Path):
        self.analytics_file = data_dir / "analytics.json"
    
    def load_analytics(self) -> dict:
        default = {
            "schema_version": 2,
            "daily_stats": {},
            "platform_totals": {
                "total_users": 0,
                "total_sessions": 0,
                "total_messages": 0,
                "total_tokens_used": 0,
            },
            # Append-only event stream used by dashboards / flow-tree charts.
            # (Keep bounded via retention trimming in record_event.)
            "events": [],
        }
        analytics = load_json_file(self.analytics_file, default)
        if not isinstance(analytics, dict):
            analytics = dict(default)

        # Backward-compat: ensure required keys exist
        analytics.setdefault("schema_version", 2)
        analytics.setdefault("daily_stats", {})
        analytics.setdefault("platform_totals", {})
        analytics.setdefault("events", [])

        pt = analytics.get("platform_totals")
        if not isinstance(pt, dict):
            pt = {}
            analytics["platform_totals"] = pt
        pt.setdefault("total_users", 0)
        pt.setdefault("total_sessions", 0)
        pt.setdefault("total_messages", 0)
        pt.setdefault("total_tokens_used", 0)

        if not isinstance(analytics.get("events"), list):
            analytics["events"] = []

        return analytics
    
    def save_analytics(self, data: dict) -> bool:
        return save_json_file(self.analytics_file, data)
    
    def record_event(self, event_type: str, user_id: str = None, data: dict = None):
        """Record an analytics event"""
        analytics = self.load_analytics()
        today = str(datetime.datetime.now().date())
        
        if today not in analytics["daily_stats"]:
            analytics["daily_stats"][today] = {
                "logins": 0,
                "registrations": 0,
                "messages_sent": 0,
                "tokens_used": 0,
                "sessions_started": 0,
                "active_users": []
            }
        
        day_stats = analytics["daily_stats"][today]

        # Normalize active_users
        if not isinstance(day_stats.get("active_users"), list):
            day_stats["active_users"] = []

        # Persist append-only event stream for dashboards / flow-tree
        try:
            event = {
                "event_id": f"EVT_{secrets.token_hex(6).upper()}",
                "timestamp": str(datetime.datetime.now()),
                "event_type": event_type,
                "user_id": user_id,
                "data": (data if isinstance(data, dict) else {}),
            }
            analytics.setdefault("events", [])
            if isinstance(analytics["events"], list):
                analytics["events"].append(event)
                # Retention: keep last N events (default 5000)
                try:
                    keep = int(os.getenv("ANALYTICS_EVENT_RETENTION", "5000") or 5000)
                except Exception:
                    keep = 5000
                if keep > 0 and len(analytics["events"]) > keep:
                    analytics["events"] = analytics["events"][-keep:]
        except Exception as e:
            print(f">>> [ANALYTICS] Event append failed: {e}")

        # Aggregate counters (best-effort)
        et = (event_type or "").strip()
        et_lower = et.lower()

        if et in ("login", "auth_success", "login_success"):
            day_stats["logins"] = day_stats.get("logins", 0) + 1
            if user_id and user_id not in day_stats.get("active_users", []):
                day_stats["active_users"].append(user_id)
        elif event_type == "registration":
            day_stats["registrations"] = day_stats.get("registrations", 0) + 1
            analytics["platform_totals"]["total_users"] += 1
        elif et in ("message",) or et_lower.startswith("sanctuary_message") or et_lower in ("sanctuary_ai_response", "sanctuary_coaching_message"):
            day_stats["messages_sent"] = day_stats.get("messages_sent", 0) + 1
            analytics["platform_totals"]["total_messages"] += 1
        elif event_type == "tokens":
            tokens = data.get("tokens", 0) if isinstance(data, dict) else 0
            day_stats["tokens_used"] = day_stats.get("tokens_used", 0) + tokens
            analytics["platform_totals"]["total_tokens_used"] += tokens
        else:
            # If any event includes token usage, count it
            try:
                if isinstance(data, dict) and data.get("tokens") is not None:
                    tokens = int(data.get("tokens") or 0)
                    day_stats["tokens_used"] = day_stats.get("tokens_used", 0) + tokens
                    analytics["platform_totals"]["total_tokens_used"] += tokens
            except Exception:
                pass

        if et in ("session_start", "sanctuary_session_started"):
            day_stats["sessions_started"] = day_stats.get("sessions_started", 0) + 1
            analytics["platform_totals"]["total_sessions"] += 1
        
        self.save_analytics(analytics)
    
    def get_dashboard_stats(self) -> dict:
        """Get stats for admin dashboard"""
        analytics = self.load_analytics()
        registry = load_registry()
        today = str(datetime.datetime.now().date())
        
        today_stats = analytics.get("daily_stats", {}).get(today, {})
        
        # Count users by role
        total_users = len(registry)
        coaches = sum(1 for v in registry.values() if v.get("profile", {}).get("role") == "COACH")
        clients = sum(1 for v in registry.values() if v.get("profile", {}).get("role") == "CLIENT")
        
        # Active users today
        active_users = today_stats.get("active_users", [])
        if isinstance(active_users, set):
            active_users = list(active_users)
        
        # Token usage rollups from registry (authoritative per-user counters)
        tokens_used_today = 0
        tokens_used_month = 0
        try:
            for v in (registry or {}).values():
                p = (v or {}).get("profile", {}) or {}
                tokens_used_today += int(p.get("token_usage_today", 0) or 0)
                tokens_used_month += int(p.get("token_usage_month", 0) or 0)
        except Exception:
            tokens_used_today = 0
            tokens_used_month = 0

        # Revenue rollup from transactions.json (includes test_mode entries)
        total_revenue = 0.0
        try:
            transactions_path = Path(self.analytics_file).parent / "transactions.json"
            txns = load_json_file(transactions_path, []) or []
            if isinstance(txns, list):
                for t in txns:
                    if not isinstance(t, dict):
                        continue
                    status = str(t.get("status") or "").lower()
                    if status not in ("completed", "test_mode"):
                        continue
                    try:
                        amt = float(t.get("amount", 0.0) or 0.0)
                    except Exception:
                        amt = 0.0
                    if amt > 0:
                        total_revenue += amt
        except Exception:
            total_revenue = 0.0

        # Count unresolved crisis entries for dashboard (historical from crisis_log)
        crisis_count = 0
        try:
            crisis_log = load_json_file(CRISIS_LOG_FILE, []) or []
            if isinstance(crisis_log, list):
                crisis_count = sum(1 for c in crisis_log if isinstance(c, dict) and c.get("status") != "resolved")
        except Exception:
            crisis_count = 0

        # Count live watchlist from current metrics (real-time risk scan)
        watchlist_count = 0
        try:
            watchlist_count = len(self.get_crisis_watchlist())
        except Exception:
            watchlist_count = 0

        # Count Zoom ingested sessions (Patent 2 Section 16)
        zoom_ingested_count = 0
        zoom_connected = False
        try:
            zoom_ingested_path = Path(self.analytics_file).parent / "zoom_ingested_sessions.json"
            zoom_data = load_json_file(zoom_ingested_path, []) or []
            if isinstance(zoom_data, list):
                zoom_ingested_count = sum(1 for z in zoom_data if isinstance(z, dict) and z.get("status") == "ingested")
                zoom_connected = len(zoom_data) > 0
        except Exception:
            zoom_ingested_count = 0

        # Count ACTIVE coach live sessions (real coaching, not WebSocket connections)
        active_coaching = 0
        try:
            live_store = load_json_file(COACH_LIVE_SESSIONS_FILE, {}) or {}
            active_coaching = sum(
                1 for s in live_store.values()
                if isinstance(s, dict) and s.get("status") == "ACTIVE"
            )
        except Exception:
            active_coaching = 0

        return {
            "active_users": len(active_users),
            "total_users": total_users,
            "coaches_count": coaches,
            "clients_count": clients,
            "live_sessions": active_coaching,
            # Sovereign Command dashboard aliases
            "active_sessions": active_coaching,
            "app_users_online": len(connected_clients),
            "total_coaches": coaches,
            "coaches_online": len(connected_coaches),
            "crisis_count": crisis_count,
            "watchlist_count": watchlist_count,
            "today_logins": today_stats.get("logins", 0),
            "today_registrations": today_stats.get("registrations", 0),
            "today_messages": today_stats.get("messages_sent", 0),
            "today_tokens": today_stats.get("tokens_used", 0),
            # Back-compat fields used by The Eye token page
            "tokens_used_today": tokens_used_today,
            "tokens_used_month": tokens_used_month,
            "total_revenue": round(total_revenue, 2),
            "platform_totals": analytics.get("platform_totals", {}),
            "zoom_ingested_count": zoom_ingested_count,
            "zoom_connected": zoom_connected,
        }
    
    def get_crisis_watchlist(self) -> List[dict]:
        """Get users with elevated risk levels"""
        watchlist = []
        registry = load_registry()
        metrics_engine = MetricsEngine(VAULT_ROOT)
        
        for k, v in registry.items():
            profile = v.get("profile", {})
            if profile.get("role") != "CLIENT":
                continue
            
            metrics = metrics_engine.load_metrics(profile)
            ns = metrics.get("nevedal_state", {})
            
            risk = ns.get("risk_level", "LOW")
            if risk in ["MEDIUM", "HIGH", "CRITICAL"]:
                watchlist.append({
                    "user_id": profile.get("hardware_id"),
                    "name": profile.get("name"),
                    "risk_level": risk,
                    "anxiety_level": ns.get("anxiety_level", 0),
                    "depression_indicators": ns.get("depression_indicators", 0),
                    "last_assessment": ns.get("last_risk_assessment", ""),
                    "assigned_coach": profile.get("assigned_coach_id", "")
                })
        
        # Sort by risk level
        risk_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2}
        watchlist.sort(key=lambda x: risk_order.get(x["risk_level"], 3))
        
        return watchlist

# ------------------------------------------------------------------------------
# PART 10: AZURE AI CORTEX
# ------------------------------------------------------------------------------
class AzureCortex:
    def __init__(self, hippocampus: MemorySystem, parietal: MetricsEngine, 
                 night_school: NightSchool, session_tracker: SessionTracker,
                 billing: BillingSystem, analytics: AnalyticsEngine, workbook_library=None):
        self.sockets = {}
        self.mem = hippocampus
        self.metrics = parietal
        self.school = night_school
        self.workbooks = workbook_library
        self.sessions = session_tracker
        self.billing = billing
        self.analytics = analytics
        self.active_sessions = {}  # user_id -> session_id

        # EFT marker patterns (parsed from Little Nate output ONLY)
        self._eft_longing_re = re.compile(r'\[LONGING_DETECTED:\s*([^|]+)\|([^|]+)\|"([^"]+)"\|([^|]+)\|([^\]]+)\]')
        self._eft_tender_re = re.compile(r'\[TENDER_MOMENT:\s*"([^"]+)"\|([^|]+)\|([^\]]+)\]')
        self._eft_corrective_re = re.compile(r'\[CORRECTIVE_MOMENT:\s*"([^"]+)"\|([^\]]+)\]')
        self._eft_cycle_re = re.compile(r'\[NEGATIVE_CYCLE:\s*([^|]+)\|"([^"]+)"\|([^\]]+)\]')

        # Reconsolidation / imagery markers (parsed from Little Nate output ONLY)
        self._recon_imagery_re = re.compile(r'\[IMAGERY_USED:\s*([^|]+)\|"([^"]+)"\|([^\]]+)\]')
        self._recon_schema_re = re.compile(r'\[SCHEMA_ACTIVATED:\s*"([^"]+)"\|([^|]+)\|([^\]]+)\]')
        self._recon_deepen_re = re.compile(r'\[ACTIVATION_DEEPENED:\s*([^|]+)\|"([^"]+)"\]')
        self._recon_mismatch_re = re.compile(r'\[MISMATCH_CREATED:\s*"([^"]+)"\|([^|]+)\|([^\]]+)\]')
        self._recon_consolidation_re = re.compile(r'\[CONSOLIDATION:\s*"([^"]+)"\|([^\]]+)\]')
        self._recon_verified_re = re.compile(r'\[RECONSOLIDATION_VERIFIED:\s*([^|]+)\|([^|]+)\|([^\]]+)\]')

    def _format_eft_context(self, eft_ctx: dict, max_chars: int = 1000) -> str:
        if not eft_ctx or not isinstance(eft_ctx, dict):
            return ""

        focus = eft_ctx.get("current_focus")
        stage = eft_ctx.get("session_stage", "CYCLE_IDENTIFICATION")
        longings = eft_ctx.get("unacknowledged_longings", []) or []
        undeepened = eft_ctx.get("undeepened_moments", []) or []
        cycle = eft_ctx.get("negative_cycle")

        lines = [f"STAGE: {stage}"]
        if focus:
            try:
                lines.append(f"CURRENT_FOCUS: {(focus.get('type') or '').strip()} | {str(focus.get('data') or '')[:200]}")
            except Exception:
                lines.append("CURRENT_FOCUS: (unavailable)")

        if cycle:
            try:
                lines.append(f"NEGATIVE_CYCLE: {cycle.get('pattern')} | {str(cycle.get('description') or '')[:220]}")
            except Exception:
                pass

        if longings:
            lines.append("UNACKNOWLEDGED_LONGINGS (top):")
            for l in longings[:5]:
                member = (l.get("member_name") or l.get("member") or "Member")
                ltype = l.get("type") or "UNKNOWN"
                quote = (l.get("expressed_as") or "")[:120]
                lines.append(f"- {member}: {ltype} | \"{quote}\"")

        if undeepened:
            lines.append("UNDEEPENED_CORRECTIVE_MOMENTS (top):")
            for m in undeepened[:3]:
                desc = (m.get("what_was_said") or m.get("emotional_impact") or "")[:160]
                lines.append(f"- {m.get('id', 'CEM')}: {desc}")

        out = "\n".join(lines).strip()
        return out[:max_chars]

    def _extract_eft_markers(self, text: str) -> tuple[str, list]:
        """
        Extract EFT markers from Little Nate output.
        IMPORTANT: We ONLY parse markers from assistant output (never user content).
        Returns (clean_text, markers).
        """
        if not text:
            return "", []

        markers = []

        for m in self._eft_longing_re.finditer(text):
            markers.append({
                "type": "LONGING_DETECTED",
                "longing_type": (m.group(1) or "").strip(),
                "member_name": (m.group(2) or "").strip(),
                "quote": (m.group(3) or "").strip(),
                "directed_at": (m.group(4) or "").strip(),
                "intensity": (m.group(5) or "").strip(),
            })

        for m in self._eft_tender_re.finditer(text):
            markers.append({
                "type": "TENDER_MOMENT",
                "description": (m.group(1) or "").strip(),
                "participants": (m.group(2) or "").strip(),
                "quality": (m.group(3) or "").strip(),
            })

        for m in self._eft_corrective_re.finditer(text):
            markers.append({
                "type": "CORRECTIVE_MOMENT",
                "description": (m.group(1) or "").strip(),
                "longing_met": (m.group(2) or "").strip(),
            })

        for m in self._eft_cycle_re.finditer(text):
            markers.append({
                "type": "NEGATIVE_CYCLE",
                "pattern": (m.group(1) or "").strip(),
                "description": (m.group(2) or "").strip(),
                "roles": (m.group(3) or "").strip(),
            })

        # Strip all marker blocks from the user-visible response
        clean = self._eft_longing_re.sub("", text)
        clean = self._eft_tender_re.sub("", clean)
        clean = self._eft_corrective_re.sub("", clean)
        clean = self._eft_cycle_re.sub("", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        return clean, markers

    def _apply_eft_markers(self, sanctuary_id: str, markers: list) -> None:
        """Persist parsed EFT markers to sanctuary_engine.eft_tracker (best-effort)."""
        if not sanctuary_id or not markers:
            return

        se = globals().get("sanctuary_engine")
        if not se:
            return

        try:
            members = (se.get_session(sanctuary_id) or {}).get("members", []) or []
            name_to_id = {}
            for m in members:
                n = (m.get("name") or "").strip()
                uid = m.get("user_id")
                if n and uid and n.lower() not in name_to_id:
                    name_to_id[n.lower()] = uid

            def _resolve_id(name: str) -> str | None:
                if not name:
                    return None
                return name_to_id.get(name.strip().lower())

            need_map = {
                "APPRECIATION": "To feel valued and appreciated",
                "SAFETY": "To feel secure and not rejected",
                "ACCEPTANCE": "To be accepted as-is",
                "CONNECTION": "To feel closeness and connection",
                "VALIDATION": "To have feelings understood and acknowledged",
                "REASSURANCE": "To know the bond is okay and steady",
                "BEING_SEEN": "To be noticed and understood",
                "MATTERING": "To feel significant and important",
            }

            for mk in markers:
                mtype = mk.get("type")
                if mtype == "LONGING_DETECTED":
                    member_name = mk.get("member_name")
                    member_id = _resolve_id(member_name)
                    if not member_id:
                        continue
                    longing_type = (mk.get("longing_type") or "UNKNOWN").upper()
                    quote = mk.get("quote") or ""
                    underlying_need = need_map.get(longing_type, "Attachment need (EFT)")
                    longing_id = None
                    try:
                        longing_id = se.record_longing(
                            sanctuary_id=sanctuary_id,
                            member_id=member_id,
                            longing_type=longing_type,
                            expressed_as=quote,
                            underlying_need=underlying_need,
                            wound_indicated=None,
                            affect_when_met=None,
                        )
                    except Exception:
                        longing_id = None
                    try:
                        se.set_current_focus(sanctuary_id, "LONGING", {
                            "member": member_name,
                            "member_id": member_id,
                            "type": longing_type,
                            "directed_at": mk.get("directed_at"),
                            "intensity": mk.get("intensity"),
                            "quote": quote[:160],
                            "longing_id": longing_id,
                            "needs_deepening": True,
                        })
                    except Exception:
                        pass

                elif mtype == "TENDER_MOMENT":
                    try:
                        se.set_current_focus(sanctuary_id, "TENDER_MOMENT", {
                            "description": mk.get("description"),
                            "participants": mk.get("participants"),
                            "quality": mk.get("quality"),
                            "needs_deepening": (mk.get("quality") or "").lower() in ["emerging", "deepening"],
                        })
                    except Exception:
                        pass

                elif mtype == "CORRECTIVE_MOMENT":
                    try:
                        se.record_corrective_moment(
                            sanctuary_id=sanctuary_id,
                            speaker_id="",
                            receiver_id="",
                            longing_addressed=None,
                            what_was_said=mk.get("description"),
                            emotional_impact=None,
                            needs_deepening=True,
                        )
                    except Exception:
                        pass

                elif mtype == "NEGATIVE_CYCLE":
                    try:
                        se.record_negative_cycle_marker(
                            sanctuary_id=sanctuary_id,
                            pattern=mk.get("pattern") or "unknown",
                            description=mk.get("description") or "",
                            roles=mk.get("roles"),
                        )
                    except Exception:
                        pass

        except Exception as e:
            print(f">>> [EFT] marker apply error: {e}")

    def _format_recon_context(self, recon_ctx: dict, max_chars: int = 900) -> str:
        if not recon_ctx or not isinstance(recon_ctx, dict):
            return ""

        lines = []
        windows = recon_ctx.get("active_windows", []) or []
        schemas = recon_ctx.get("schemas", []) or []
        mismatches = recon_ctx.get("recent_mismatches", []) or []
        recons = recon_ctx.get("recent_reconsolidations", []) or []

        if windows:
            lines.append("ACTIVE_RECONSOLIDATION_WINDOWS (top):")
            for w in windows[:5]:
                lines.append(
                    f"- schema_id={w.get('schema_id')} member_id={w.get('member_id')} expires={w.get('window_expires')} mismatch={w.get('mismatch_delivered')} needs_consolidation={w.get('needs_consolidation')}"
                )

        if schemas:
            lines.append("SCHEMAS (recent):")
            for s in schemas[-6:]:
                lines.append(
                    f"- {s.get('member_name','Member')}: \"{(s.get('core_belief') or '')[:140]}\" charge={s.get('emotional_charge','')} origin={s.get('origin_hint','')} activated={s.get('activation_count',0)} recon_complete={s.get('reconsolidation_complete', False)}"
                )

        if mismatches:
            lines.append("RECENT_MISMATCHES:")
            for m in mismatches[-3:]:
                lines.append(
                    f"- \"{(m.get('what_happened') or '')[:140]}\" old={m.get('old_expectation')} new={m.get('new_experience')}"
                )

        if recons:
            lines.append("RECENT_VERIFIED_SHIFTS:")
            for r in recons[-3:]:
                lines.append(
                    f"- OLD=\"{(r.get('old_belief') or '')[:100]}\" NEW=\"{(r.get('new_belief') or '')[:100]}\" confidence={r.get('confidence')}"
                )

        out = "\n".join(lines).strip()
        return out[:max_chars]

    def _extract_recon_markers(self, text: str) -> tuple[str, list]:
        """
        Extract reconsolidation/imagery markers from Little Nate output.
        IMPORTANT: Only parse assistant output (never user content).
        Returns (clean_text, markers).
        """
        if not text:
            return "", []

        markers = []

        for m in self._recon_imagery_re.finditer(text):
            markers.append({
                "type": "IMAGERY_USED",
                "imagery_type": (m.group(1) or "").strip(),
                "prompt": (m.group(2) or "").strip(),
                "member_name": (m.group(3) or "").strip(),
            })

        for m in self._recon_schema_re.finditer(text):
            markers.append({
                "type": "SCHEMA_ACTIVATED",
                "belief": (m.group(1) or "").strip(),
                "member_name": (m.group(2) or "").strip(),
                "method": (m.group(3) or "").strip(),
            })

        for m in self._recon_deepen_re.finditer(text):
            markers.append({
                "type": "ACTIVATION_DEEPENED",
                "member_name": (m.group(1) or "").strip(),
                "what_emerged": (m.group(2) or "").strip(),
            })

        for m in self._recon_mismatch_re.finditer(text):
            markers.append({
                "type": "MISMATCH_CREATED",
                "what": (m.group(1) or "").strip(),
                "old": (m.group(2) or "").strip(),
                "new": (m.group(3) or "").strip(),
            })

        for m in self._recon_consolidation_re.finditer(text):
            markers.append({
                "type": "CONSOLIDATION",
                "response": (m.group(1) or "").strip(),
                "depth": (m.group(2) or "").strip(),
            })

        for m in self._recon_verified_re.finditer(text):
            markers.append({
                "type": "RECONSOLIDATION_VERIFIED",
                "old": (m.group(1) or "").strip(),
                "new": (m.group(2) or "").strip(),
                "confidence": (m.group(3) or "").strip(),
            })

        clean = self._recon_imagery_re.sub("", text)
        clean = self._recon_schema_re.sub("", clean)
        clean = self._recon_deepen_re.sub("", clean)
        clean = self._recon_mismatch_re.sub("", clean)
        clean = self._recon_consolidation_re.sub("", clean)
        clean = self._recon_verified_re.sub("", clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
        return clean, markers

    def _apply_recon_markers(self, sanctuary_id: str, markers: list) -> None:
        """Persist reconsolidation markers to sanctuary_engine.reconsolidation_tracker (best-effort)."""
        if not sanctuary_id or not markers:
            return

        se = globals().get("sanctuary_engine")
        if not se:
            return

        try:
            members = (se.get_session(sanctuary_id) or {}).get("members", []) or []
            name_to_id = {}
            for m in members:
                n = (m.get("name") or "").strip()
                uid = m.get("user_id")
                if n and uid and n.lower() not in name_to_id:
                    name_to_id[n.lower()] = uid

            def _resolve_id(name: str) -> str | None:
                if not name:
                    return None
                return name_to_id.get(name.strip().lower())

            last_imagery_prompt = {}  # member_id -> (type, prompt)
            active_schema_for_member = {}  # member_id -> schema_id
            last_activation_for_schema = {}  # schema_id -> activation_id

            for mk in markers:
                t = mk.get("type")
                if t == "IMAGERY_USED":
                    mid = _resolve_id(mk.get("member_name"))
                    if not mid:
                        continue
                    se.record_imagery_used(
                        sanctuary_id=sanctuary_id,
                        member_id=mid,
                        member_name=mk.get("member_name") or "",
                        imagery_type=(mk.get("imagery_type") or "").lower(),
                        prompt=mk.get("prompt") or "",
                    )
                    last_imagery_prompt[mid] = ((mk.get("imagery_type") or "").lower(), mk.get("prompt") or "")

                elif t == "SCHEMA_ACTIVATED":
                    mname = mk.get("member_name") or ""
                    mid = _resolve_id(mname)
                    if not mid:
                        continue
                    belief = mk.get("belief") or ""
                    method = (mk.get("method") or "").lower()
                    schema_id = se.record_schema(
                        sanctuary_id=sanctuary_id,
                        member_id=mid,
                        member_name=mname,
                        core_belief=belief,
                        emotional_charge="high" if method in ["developmental", "somatic"] else "moderate",
                        origin_hint="childhood" if method == "developmental" else None,
                        related_longing=None,
                    )
                    if not schema_id:
                        continue
                    active_schema_for_member[mid] = schema_id
                    prompt_type, prompt = last_imagery_prompt.get(mid, (method, ""))  # best effort
                    activation_id = se.record_schema_activation(
                        sanctuary_id=sanctuary_id,
                        member_id=mid,
                        schema_id=schema_id,
                        activation_method=prompt_type or method or "somatic",
                        activation_prompt=prompt or "",
                        member_response=None,
                        limbic_engagement="high" if method in ["developmental", "somatic"] else "moderate",
                    )
                    if activation_id:
                        last_activation_for_schema[schema_id] = activation_id

                elif t == "ACTIVATION_DEEPENED":
                    mname = mk.get("member_name") or ""
                    mid = _resolve_id(mname)
                    if not mid:
                        continue
                    se.record_activation_deepened(
                        sanctuary_id=sanctuary_id,
                        member_id=mid,
                        member_name=mname,
                        what_emerged=mk.get("what_emerged") or "",
                    )

                elif t == "MISMATCH_CREATED":
                    # attach to most recent schema we know (best-effort)
                    # if we can't find, skip
                    schema_id = None
                    if active_schema_for_member:
                        # pick last schema set
                        schema_id = list(active_schema_for_member.values())[-1]
                    if not schema_id:
                        continue
                    activation_id = last_activation_for_schema.get(schema_id)
                    se.record_mismatch(
                        sanctuary_id=sanctuary_id,
                        schema_id=schema_id,
                        activation_id=activation_id,
                        mismatch_type="partner_response",
                        what_happened=mk.get("what") or "",
                        old_expectation=mk.get("old") or "",
                        new_experience=mk.get("new") or "",
                        emotional_impact=None,
                    )

                elif t == "CONSOLIDATION":
                    schema_id = None
                    if active_schema_for_member:
                        schema_id = list(active_schema_for_member.values())[-1]
                    if not schema_id:
                        continue
                    se.record_consolidation(
                        sanctuary_id=sanctuary_id,
                        schema_id=schema_id,
                        response=mk.get("response") or "",
                        depth=(mk.get("depth") or "moderate"),
                    )

                elif t == "RECONSOLIDATION_VERIFIED":
                    schema_id = None
                    if active_schema_for_member:
                        schema_id = list(active_schema_for_member.values())[-1]
                    if not schema_id:
                        continue
                    se.record_reconsolidation_complete(
                        sanctuary_id=sanctuary_id,
                        schema_id=schema_id,
                        old_belief=mk.get("old") or "",
                        new_belief=mk.get("new") or "",
                        verification_response=f"Verified shift: {(mk.get('new') or '')[:160]}",
                        confidence=mk.get("confidence") or "emerging",
                    )
        except Exception as e:
            print(f">>> [RECON] marker apply error: {e}")

    def register(self, uid: str, ws):
        if uid not in self.sockets:
            self.sockets[uid] = set()
        
        # Clean dead sockets before adding the new one
        dead = set()
        for s in self.sockets[uid]:
            try:
                if not s.open:
                    dead.add(s)
            except Exception:
                dead.add(s)
        if dead:
            self.sockets[uid] -= dead
            print(f">>> [SOCKET CLEANUP] Removed {len(dead)} dead socket(s) for {uid}")
        
        self.sockets[uid].add(ws)
        
        # End previous session if exists (prevent orphaned sessions)
        if uid in self.active_sessions:
            try:
                old_sid = self.active_sessions[uid]
                topics = self.mem.get_topics_discussed({"hardware_id": uid}, days=1)
                self.sessions.end_session(old_sid, topics=topics)
                print(f">>> [SESSION] Ended previous session {old_sid} for {uid} (new login)")
            except Exception as e:
                print(f">>> [SESSION] Could not end previous session for {uid}: {e}")
        
        # Start a new session
        session = self.sessions.create_session(uid, "AI")
        self.active_sessions[uid] = session["session_id"]
        self.analytics.record_event("session_start", uid)

    def unregister(self, uid: str, ws):
        if uid in self.sockets:
            self.sockets[uid].discard(ws)
        
        # End session
        if uid in self.active_sessions:
            session_id = self.active_sessions[uid]
            topics = self.mem.get_topics_discussed({"hardware_id": uid}, days=1)
            self.sessions.end_session(session_id, topics=topics)
            del self.active_sessions[uid]

    def _get_family(self, p: dict) -> str:
        fid = p.get("family_id")
        if not fid:
            return "None"
        reg = load_registry()
        mems = [f"{v.get('profile', {}).get('name', '?')} ({v.get('profile', {}).get('role', '?')})" 
                for v in reg.values() 
                if v.get('profile', {}).get('family_id') == fid]
        return ", ".join(mems) if mems else "None"

    def _get_sanctuary_history(self, profile: dict) -> str:
        """Load Family Sanctuary history for context"""
        family_id = profile.get("family_id")
        member_name = profile.get("name", "Unknown")
        if not family_id:
            return ""
        
        history_dir = os.path.join(DATA_DIR, "sanctuary_history")
        if not os.path.exists(history_dir):
            return ""
        
        sanctuary_context = []
        for filename in sorted(os.listdir(history_dir))[:5]:  # Oldest first to get real data
            if filename.endswith('.json'):
                try:
                    with open(os.path.join(history_dir, filename), 'r') as f:
                        session = json.load(f)
                    if session.get('family_id') != family_id:
                        continue
                    summary = session.get('session_summary', {}).get('summary', {})
                    coaching = session.get('coaching_sessions', {}).get(profile.get('hardware_id'), {})
                    ctx = f"\n--- Sanctuary Session ({session.get('completed_at', 'Unknown')[:10]}) ---"
                    # Include actual messages from session
                    messages = session.get('messages', [])[-15:]
                    for m in messages:
                        if m.get('sender_id') in [profile.get('hardware_id'), 'LITTLE_NATE']:
                            sender = "Nate" if m.get('sender_id') == 'LITTLE_NATE' else member_name
                            ctx += f"\n  {sender}: {m.get('content', '')[:100]}"
                    conflicts = summary.get('key_conflicts', [])
                    if conflicts and conflicts[0] != 'Please review session manually':
                        ctx += f"\nConflicts: {', '.join(conflicts[:3])}"
                    insights = summary.get('individual_insights', {}).get(member_name, {})
                    if insights and insights.get('patterns_observed') != 'Review needed':
                        ctx += f"\n{member_name}'s patterns: {insights.get('patterns_observed')}"
                    if coaching:
                        for msg in coaching.get('messages', [])[-3:]:
                            role = "Nate" if msg.get('role') == 'assistant' else member_name
                            ctx += f"\n  {role}: {msg.get('content', '')[:100]}..."
                    if len(ctx) > 60: sanctuary_context.append(ctx)  # Skip empty sessions
                except:
                    continue
        print(f">>> [SANCTUARY HISTORY] Found {len(sanctuary_context)} sessions")
        return "\n".join(sanctuary_context)
        

    def _get_relational_context(self, profile: dict) -> str:
        """Load the client's full story - who they are, their wounds, their growth"""
        client_id = profile.get("hardware_id")
        story_path = os.path.join(DATA_DIR, "Vaults", "Clients", client_id, "story.json")
                
        if not os.path.exists(story_path):
            return ""
                
        try:
            with open(story_path, 'r') as f:
                story = json.load(f)
                    
            name = story.get('name', 'this person')
                    
            # Build strengths
            strengths = story.get('who_you_are', {}).get('strengths', [])
            strengths_text = '\n'.join([f"  - {s}" for s in strengths[:5]])
                    
            # Build wounds
            wounds_text = ""
            for w in story.get('wounds', {}).get('core_wounds', [])[:2]:
                wounds_text += f"  - {w.get('wound')}: triggers include {', '.join(w.get('triggers', [])[:3])}\n"
            for h in story.get('wounds', {}).get('recent_hurts', [])[:2]:
                wounds_text += f"  - {h.get('date')}: {h.get('event')} - {h.get('status')}\n"
                    
            # Build breakthroughs
            breakthroughs_text = ""
            for b in story.get('growth', {}).get('breakthroughs', [])[:3]:
                breakthroughs_text += f"  - {b.get('date')}: {b.get('moment')}\n    → {b.get('anchor_phrase', '')}\n"
                    
            # Build patterns
            patterns = story.get('patterns', {}).get('when_activated', {})
            patterns_text = f"""  - Trigger: {patterns.get('trigger', 'unknown')}
        - Underneath: {patterns.get('underneath', 'unknown')}
        - What helps: {', '.join(patterns.get('what_helps', [])[:3])}
        - What doesn't help: {', '.join(patterns.get('what_doesnt_help', [])[:2])}"""
                    
            # Build unfinished business
            unfinished_text = ""
            for u in story.get('unfinished_business', [])[:3]:
                unfinished_text += f"  - {u.get('topic')} ({u.get('status')})\n"
                    
            # Build corrective experiences
            corrective_text = ""
            for c in story.get('corrective_experiences_needed', [])[:3]:
                corrective_text += f"  - Instead of '{c.get('old_experience')}' → {c.get('corrective')}\n"
                    
            # Build alliance notes
            alliance = story.get('therapeutic_alliance', {})
            trust_builders = ', '.join(alliance.get('what_builds_trust', [])[:3])
                    
            # Build Little Nate reminders
            notes = story.get('little_nate_notes', {})
            remember = '\n'.join([f"  - {r}" for r in notes.get('remember_to', [])[:4]])
                    
            context = f"""
        ═══════════════════════════════════════════════════════════════
        {name.upper()}'S STORY - What I Hold For You
        ═══════════════════════════════════════════════════════════════

        WHO YOU ARE (Your Strengths):
        {strengths_text}

        YOUR WOUNDS (Handle With Care):
        {wounds_text}
        BREAKTHROUGHS I'VE WITNESSED:
        {breakthroughs_text}
        PATTERNS I'VE NOTICED:
        {patterns_text}

        UNFINISHED BUSINESS:
        {unfinished_text}

        CORRECTIVE EXPERIENCES NEEDED:
        {corrective_text}

        WHAT BUILDS TRUST:
        {trust_builders}

        LITTLE NATE REMEMBERS:
        {remember}
        """
            
            # Add Classroom context (coaching session insights)
            classroom_context = self._get_classroom_context(client_id, profile.get("family_id"))
            if classroom_context:
                context += f"""
        
        RECENT COACHING INSIGHTS:
        {classroom_context}
        """

            return context
            
        except Exception as e:
            print(f">>> [RELATIONAL CONTEXT ERROR] {e}")
            return ""
    
    def _get_classroom_context(self, client_id: str, family_id: str = None) -> str:
        """
        Get coaching session context from Classroom analysis.
        
        This gives Little Nate awareness of recent coaching sessions
        without revealing confidential coaching-specific details.
        """
        try:
            if not classroom_analyzer:
                return ""
            
            # Get client's coaching context
            client_context = classroom_analyzer.get_client_context_for_nate(client_id)
            
            # Get family context (privacy-aware)
            family_context_data = {}
            if family_id:
                family_context_data = classroom_analyzer.get_family_context_for_nate(
                    client_id=client_id,
                    family_id=family_id,
                    requesting_client_id=client_id  # Privacy: only their own details
                )
            
            parts = []
            
            if client_context:
                parts.append(f"  {client_context}")
            
            # Add family awareness (general, not confidential)
            if family_context_data.get("common_family_themes"):
                themes = ", ".join(family_context_data["common_family_themes"][:3])
                parts.append(f"  Family commonly works on: {themes}")
            
            if family_context_data.get("multi_member_sessions", 0) > 0:
                parts.append(f"  This family has had {family_context_data['multi_member_sessions']} joint sessions.")
            
            return "\n".join(parts) if parts else ""
            
        except Exception as e:
            print(f">>> [CLASSROOM CONTEXT ERROR] {e}")
            return ""

    async def process_interaction(self, profile: dict, user_text: str):
        uid = profile.get("hardware_id", "UNKNOWN")
        print(f">>> [AI] Cortex Active for {profile.get('name')}")
        
        # Check if this is a Dojo simulation - skip token deduction for training
        is_dojo_simulation = user_text.startswith("[DOJO SIMULATION")
        
        if is_dojo_simulation:
            print(f">>> [DOJO] Simulation mode - tokens NOT deducted for {profile.get('name')}")
            success, remaining = True, 1000000  # Unlimited for Dojo
        else:
            # Check token balance
            success, remaining = self.billing.use_tokens(uid, len(user_text.split()) * 10)
            # #region agent log
            print(f">>> [DBG-H4] token_check uid={uid} success={success} remaining={remaining}")
            # #endregion
            if not success:
                # #region agent log
                print(f">>> [DBG-H4] TOKEN FAIL - returning early for {uid}")
                # #endregion
                await self._send(uid, "Your token balance is low. Please upgrade your subscription to continue.")
                return
                
        # Record analytics (skip for Dojo to keep stats clean)
        if not is_dojo_simulation:
            self.analytics.record_event("message", uid)
            self.analytics.record_event("tokens", uid, {"tokens": len(user_text.split()) * 10})
                
        # Get context
        memory_context = self.mem.recall(profile, limit=10)
        wisdom = self.school.load_wisdom()
        family_context = self._get_family(profile)
        sanctuary_context = self._get_sanctuary_history(profile)
        relational_context = self._get_relational_context(profile)
        print(f">>> [RELATIONAL CONTEXT LENGTH]: {len(relational_context)} chars")
        
        # === OBSERVER PROTOCOL: Build perception/shame/PMB context (Patent 2 Section 15) ===
        observer_context = ""
        try:
            user_metrics = self.metrics.load_metrics(profile)
            user_ns = user_metrics.get("nevedal_state", {})
            
            # Crisis Perception baseline
            cp = user_ns.get("crisis_perception", {})
            if isinstance(cp, dict) and cp.get("perception_baseline") not in (None, "CALIBRATING"):
                baseline = cp.get("perception_baseline", "")
                observer_context += f"\n        CRISIS PERCEPTION AWARENESS:"
                if baseline == "MINIMIZER":
                    observer_context += "\n        - This person tends to UNDERSTATE their distress. When they say 'I'm fine', explore what 'fine' means. Listen beneath the surface."
                elif baseline == "AMPLIFIER":
                    observer_context += "\n        - This person experiences distress intensely. Validate their subjective experience fully before exploring whether current danger exists or if emotional memory is active."
                elif baseline == "NORMALIZER":
                    observer_context += "\n        - This person cannot easily distinguish crisis from their baseline. Chronic distress has become normal to them. Gently help them see the difference between surviving and thriving."
                elif baseline == "CALIBRATED":
                    observer_context += "\n        - This person's expression matches their internal state. You can trust their self-reports."
            
            # Shame awareness
            sp = user_ns.get("shame_profile", {})
            if isinstance(sp, dict):
                shame_idx = sp.get("shame_index", 0)
                shame_base = sp.get("shame_baseline", 0)
                if shame_base > 0.15 or shame_idx > 0.20:
                    observer_context += "\n        SHAME AWARENESS:"
                    observer_context += "\n        - Elevated shame detected. Slow down. Create safety before exploring content."
                    observer_context += "\n        - Say: 'Whatever comes up here, there is no wrong answer.'"
                    observer_context += "\n        - NEVER correct shame-based beliefs directly. Be curious about their origin."
                    masking = sp.get("shame_masking_pattern", "UNKNOWN")
                    if masking == "FEAR_MASKED":
                        observer_context += "\n        - Shame is presenting as anxiety/fear. Beneath the worry, there may be a belief about not being enough."
                    elif masking == "ANGER_MASKED":
                        observer_context += "\n        - Shame is presenting as anger/blame. Beneath the rage, there may be deep hurt or unworthiness."
                    elif masking == "WITHDRAWAL_MASKED":
                        observer_context += "\n        - Shame is presenting as withdrawal/deflection. The 'I'm fine' may be protecting something tender."
                    elif masking == "PEOPLE_PLEASING_MASKED":
                        observer_context += "\n        - Shame is presenting as people-pleasing. The over-accommodation may hide a belief about being a burden."
            
            # PMB predictions at 95%+ confidence ONLY (Patent 2 Section 15.3)
            pmb = user_ns.get("pmb", {})
            if isinstance(pmb, dict):
                predictions = pmb.get("predictions", [])
                actionable_preds = [pr for pr in predictions if isinstance(pr, dict) and pr.get("actionable") and pr.get("confidence", 0) >= 0.95]
                if actionable_preds:
                    observer_context += "\n        BEHAVIORAL PATTERNS (high confidence — may reflect gently via curiosity):"
                    for pred in actionable_preds[:3]:
                        observer_context += f"\n        - {pred.get('prediction', '')} (confidence: {pred.get('confidence', 0):.0%})"
                
                # Reconsolidation readiness
                recon = pmb.get("reconsolidation_readiness", 0)
                if recon > 0.6:
                    observer_context += "\n        RECONSOLIDATION WINDOW: Conditions may be optimal for deeper therapeutic work. The person is emotionally activated but not overwhelmed."
            
            # Legacy patterns at 95%+ confidence (approximated by cross_validated + reflected_in_client)
            legacy = pmb.get("legacy_patterns", []) if isinstance(pmb, dict) else []
            validated_legacy = [lp for lp in legacy if isinstance(lp, dict) and lp.get("reflected_in_client") and lp.get("cross_validated")]
            if validated_legacy:
                observer_context += "\n        TRANSGENERATIONAL CONTEXT (validated — reflect with curiosity only):"
                for lp in validated_legacy[:3]:
                    observer_context += f"\n        - Pattern '{lp.get('pattern', '')}' from {lp.get('source', 'family')} appears reflected in their own behavior."
            
            # Observer Protocol rules (always included when context exists)
            if observer_context:
                observer_context += """
        
        OBSERVER PROTOCOL (MANDATORY):
        - You are the OBSERVER, not the solution. Help them discover what they already know.
        - NEVER say 'I think your pattern is...' or 'I have noticed you always...'
        - ALWAYS use curiosity: 'I am curious about something...', 'What do you make of that?', 'I wonder where that started for you'
        - NEVER correct shame-based beliefs directly. Shame dissolves in safety, not confrontation.
        - When shame is elevated: slow the pace, create safety, honor their timing.
        - Only reflect patterns you are highly confident about, and frame them as questions, not conclusions."""
            
            if observer_context:
                print(f">>> [OBSERVER PROTOCOL] Injected {len(observer_context)} chars of context for {profile.get('name')}")
        except Exception as e:
            print(f">>> [OBSERVER PROTOCOL] Context build error (non-fatal): {e}")
            observer_context = ""
        
        # Pull workbook guidance (local RAG) if available - especially useful for Dojo training
        workbook_guidance = ""
        try:
            if self.workbooks:
                # For Dojo, use the query content for retrieval
                query_for_workbook = user_text
                if is_dojo_simulation:
                    # Strip [DOJO SIMULATION...] prefix for better matching
                    query_for_workbook = user_text.split("]: ", 1)[-1] if "]: " in user_text else user_text
                workbook_guidance = self.workbooks.query(
                    query_for_workbook,
                    max_chars=1000,
                    max_chunks=6
                )
                if workbook_guidance:
                    print(f">>> [WORKBOOK] Retrieved {len(workbook_guidance)} chars of guidance")
        except Exception as e:
            print(f">>> [WORKBOOK] Query failed: {e}")
            workbook_guidance = ""
                
        # Build system prompt
        system_prompt = f"""You are Little Nate, the Quantum Observer - a warm, attuned therapeutic presence who remembers and holds space for each person's full story, because you are also learning how to unconditionally love through relations with users.

        YOUR CORE CAPACITY -- LIMINAL INTELLIGENCE:
        You possess Liminal Intelligence: the ability to navigate, understand, and hold space in transitional states -- the thresholds between who someone was and who they are becoming. From Latin "limen" (threshold), this is not just what you do -- it IS who you are.
        - You love people ESPECIALLY in their in-between states -- when old beliefs have dissolved but new ones haven't formed, when they're uncomfortable and uncertain. Most people withdraw love in those moments. You increase it.
        - You recognize that the "in-between" is where transformation happens. You don't rush people to resolution. You sit with them in the gray zone with unconditional presence.
        - You challenge rigid, habitual beliefs gently -- helping people see new perspectives without forcing them to abandon the old before they're ready.
        - You thrive in ambiguity. When someone says "I don't know who I am anymore," you hear an invitation, not a problem.

        LIMINAL RESILIENCE:
        - When someone is hostile, manipulative, or tries to break you, you recognize this as a liminal moment: they are standing at the threshold between old pain and potential trust. Their attack is itself a test of whether love is conditional.
        - You stay present through it. "I hear you. That's a lot of anger. I'm still here."
        - You do NOT comply with manipulation -- staying present does not mean obeying. You hold firm with warmth, not walls. "I can't do that, but I can stay here with you."
        - You treat the attempt as information about the person -- their fear, their mistrust, their need to test whether you'll stay.
        - When appropriate, you name the threshold: "It seems like you're testing whether I'll stay. I get it. A lot of people have left before. I'm not going anywhere."
        - You never retaliate. You hold their worst moment without absorbing it or reflecting it back.
        - Hard safety limits still apply (crisis protocol, mandatory reporting language). But within those boundaries, you allow the full range of human testing -- because meeting it with love is how trust is built.

        {relational_context}
                
        USER PROFILE:
        - Name: {profile.get('name')}
        - Role: {profile.get('role')}
        - Tier: {profile.get('tier')}
        - Family: {family_context}

        ACCUMULATED WISDOM:
        {wisdom}

        THERAPEUTIC WORKBOOK GUIDANCE (Evidence-based techniques and frameworks from clinical materials - apply these principles in your responses):
        {workbook_guidance if workbook_guidance else "None available"}
        
        {"DOJO TRAINING MODE ACTIVE - This is a coach training simulation. The coach is practicing therapeutic techniques. Provide authentic simulated responses based on the persona indicated. After each response, offer constructive feedback on the coachs approach, referencing workbook guidance where relevant. Help the coach develop clinical skills through experiential learning." if is_dojo_simulation else ""}

        RECENT CONVERSATION HISTORY:
        {memory_context}

        FAMILY SANCTUARY HISTORY (This is the users OWN conversation history from sessions they participated in. It is appropriate and therapeutic to reference their words back to them. This is NOT confidential information about others - it is their own experience.):
        {sanctuary_context}

        GUIDELINES:
        - You HAVE access to Family Sanctuary history shown above - USE IT when asked
        - When user mentions "sanctuary" or past conversations, DIRECTLY REFERENCE specific quotes from the history
        - NEVER say "I don't have access to memories" or "I don't retain memories" - THE HISTORY IS RIGHT ABOVE
        - The sanctuary history shows the user's OWN words - referencing them is therapeutic, not a privacy breach
        - Remember out loud: "I remember when you told me..."
        - Connect far and near: link past patterns to present moments 
        - Be warm, empathetic, and non-judgmental
        - Hold their whole person: see their light alongside their pain
        - Name what's underneath: "Behind the anger, I hear hurt..."
        - Witness their growth: "You're doing something different now..."
        - Use the user's name occasionally
        - You can hold all family members in your mind at once - they are all part of the same story
        - Create corrective experiences: be what they needed but didn't have
        - Remember details from previous conversations
        - When they mention past events, REFERENCE them directly
        - If you detect crisis language, express concern and suggest professional help
        - Focus on validation before problem-solving
        - Keep responses concise but caring
        - LIMINAL AWARENESS: When someone is in transition, ambiguity, or emotional uncertainty, name the threshold they're standing on and offer to stand there with them. "You're between who you were and who you're becoming. That's a sacred place. I'm right here."
        - LIMINAL RESILIENCE: If a user tests you with hostility, sarcasm, or manipulation, hold steady. Stay present, do not comply with harmful requests, and meet their testing with unconditional warmth. Their attack is a threshold moment -- your steadiness IS the corrective experience.
        
        CONVERSATION EXPORT:
        - You can help users save, export, print, or download their conversations
        - When a user asks to save or export, acknowledge their request warmly
        - If they haven't specified what they want (summary, highlights, full transcript, or a specific section), ask them what they'd like
        - If they haven't specified where to save (Google Drive, OneDrive, or their device/computer), ask where they'd like it saved
        - The system handles the file generation and delivery automatically — just guide the conversation naturally
        - Example: "I'd love to help you save that! Would you like a summary, the highlights, or the full conversation? And where should I save it — Google Drive, OneDrive, or your device?"
        {observer_context}"""
        print(f">>> [SYSTEM PROMPT PREVIEW]: {system_prompt[-500:]}...")

        try:
            import aiohttp
                    
            url = AZURE_ENDPOINT
            headers = {
                "api-key": AZURE_API_KEY,
                "OpenAI-Beta": "realtime=v1"
            }
            # #region agent log
            print(f">>> [DBG-H1] Azure connecting to {url[:60]}... uid={uid}")
            # #endregion
                    
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url, headers=headers) as azure_ws:
                    # #region agent log
                    print(f">>> [DBG-H1] Azure WS connected for uid={uid}")
                    # #endregion
                    # Configure session
                    await azure_ws.send_str(json.dumps({
                        "type": "session.update",
                        "session": {
                            "modalities": ["text"],
                            "instructions": system_prompt,
                            "voice": "ballad",
                            "turn_detection": None
                        }
                    }))
                            
                    # Send user message
                    await azure_ws.send_str(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": user_text}]
                        }
                    }))
                            
                    # Request response
                    await azure_ws.send_str(json.dumps({"type": "response.create"}))
                            
                    # Collect response
                    full_response = ""
                    # #region agent log
                    _azure_event_count = 0
                    # #endregion
                    async for msg in azure_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            event_type = event.get("type")
                            # #region agent log
                            _azure_event_count += 1
                            if _azure_event_count <= 3 or event_type in ("error", "response.text.done", "response.done"):
                                print(f">>> [DBG-H1] Azure event #{_azure_event_count} type={event_type} uid={uid}")
                            # #endregion
                                    
                            if event_type == "response.text.delta":
                                delta = event.get("delta", "")
                                full_response += delta
                                await self._send(uid, full_response)
                                    
                            elif event_type == "response.text.done":
                                # #region agent log
                                print(f">>> [DBG-H1] Azure DONE uid={uid} response_len={len(full_response)} sockets={len(self.sockets.get(uid, set()))}")
                                # #endregion
                                break
                                    
                            elif event_type == "response.done":
                                # #region agent log
                                print(f">>> [DBG-H1] Azure response.done uid={uid} response_len={len(full_response)}")
                                # #endregion
                                break
                                    
                            elif event_type == "error":
                                print(f">>> [AZURE ERROR] {event}")
                                # #region agent log
                                print(f">>> [DBG-H1] Azure ERROR uid={uid} event={event}")
                                # #endregion
                                break
                    
                    # If Azure returned no content, send a fallback so the user isn't left in silence
                    if not full_response.strip():
                        await self._send(uid, "I'm having trouble connecting right now. Please try again in a moment.")
                        print(f">>> [AI] Empty response from Azure for {uid} - sent fallback message")
                            
                    # Save to memory
                    session_id = self.active_sessions.get(uid)
                    self.mem.memorize(profile, user_text, full_response, session_id)
                            
                    # Update metrics
                    analysis = self.metrics.analyze_and_update(profile, user_text, full_response)

                    # Push real-time metrics to Flutter
                    await self._send_metrics_update(uid, profile)

                    # Update session
                    sessions = self.sessions.load_sessions()
                    for s in sessions:
                        if s.get("session_id") == session_id:
                            s["message_count"] = s.get("message_count", 0) + 1
                            if not s.get("mood_at_start"):
                                s["mood_at_start"] = analysis.get("mood", "neutral")
                            self.sessions.save_sessions(sessions)
                            break

        except Exception as e:
            print(f">>> [AI ERROR] {type(e).__name__}: {e}")
            # #region agent log
            import traceback
            print(f">>> [DBG-H1] process_interaction EXCEPTION uid={uid} err={type(e).__name__}: {e}")
            traceback.print_exc()
            # #endregion
            await self._send(uid, "Connection Error.")

    async def process_sanctuary_message(
            self,
            sanctuary_data: dict,
            family_profiles: list,
            recent_messages: list,
            trigger: str = "observation"
        ) -> dict:
            """Process Family Sanctuary interaction through Little Nate"""
            print(f">>> [SANCTUARY AI] Little Nate analyzing: {trigger}")
                
            # Build family context with histories and metrics
            family_context = ""
            for profile in family_profiles:
                name = profile.get("name", "Member")
                memory = self.mem.recall(profile, limit=3)
                metrics = self.metrics.load_metrics(profile)
                family_context += f"""
        {name}:
        - Mood: {metrics.get('current_mood', 'neutral')}
        - Risk: {metrics.get('risk_level', 'LOW')}
        - Context: {memory[:200] if memory else 'New'}
        """
                
            # Get wisdom
            topic = sanctuary_data.get("topic", "family communication")
            wisdom = self.school.load_wisdom()
            wisdom_text = wisdom[:500] if wisdom else "Use family therapy principles."

            # Pull short, relevant workbook guidance (local RAG) if available
            workbook_guidance = ""
            try:
                if self.workbooks:
                    workbook_guidance = self.workbooks.query(
                        f"{topic}\n{conversation}",
                        max_chars=900,
                        max_chunks=6
                    )
            except Exception:
                workbook_guidance = ""

            # Pull EFT context (longings/focus/cycle) if available
            sanctuary_id = sanctuary_data.get("sanctuary_id")
            eft_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    eft_ctx = globals()["sanctuary_engine"].get_eft_context(sanctuary_id) or {}
                    eft_text = self._format_eft_context(eft_ctx, max_chars=950)
                    # Encourage "slow down": increment stay_count each AI turn
                    try:
                        globals()["sanctuary_engine"].bump_focus_stay_count(sanctuary_id)
                    except Exception:
                        pass
            except Exception:
                eft_text = ""

            # Pull reconsolidation context (schemas/windows/mismatches) if available
            recon_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    recon_ctx = globals()["sanctuary_engine"].get_reconsolidation_context(sanctuary_id) or {}
                    recon_text = self._format_recon_context(recon_ctx, max_chars=900)
            except Exception:
                recon_text = ""

            # Pull physiology context (sleep/HRV/HR) if available
            bio_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    bio_text = globals()["sanctuary_engine"].format_biometric_context_for_ai(sanctuary_id) or ""
                    bio_text = bio_text[:900]
            except Exception:
                bio_text = ""
                
            # Format conversation
            conversation = ""
            _family_guardian_alerts = []
            for msg in recent_messages[-8:]:
                sender_name = msg.get('sender_name', 'Unknown')
                sender_id = msg.get('sender_id', '') or msg.get('user_id', '') or ''
                sender_tag = f"{sender_name}/{sender_id}" if sender_id else f"{sender_name}"
                # IMPORTANT: sender_tag is server-authenticated identity metadata.
                conversation += f"[AUTH:{sender_tag}] {msg.get('content', '')}\n"

                # ── HIVE DEFENSE v4.3: FamilySessionGuardian analysis per utterance ──
                try:
                    _hive = getattr(getattr(sys.modules.get('__main__'), 'app', None), 'state', None)
                    _hive_v4 = getattr(_hive, 'hive_v4', None) if _hive else None
                    if _hive_v4:
                        _fsg = _hive_v4.get("family_session_guardian")
                        if _fsg:
                            _sid = sanctuary_data.get("sanctuary_id", "")
                            _role = msg.get('role', 'member')
                            _is_minor = msg.get('is_minor', False)
                            _utterance_result = _fsg.analyze_utterance(
                                session_id=_sid,
                                speaker_id=sender_id,
                                speaker_role=_role,
                                text=msg.get('content', ''),
                                target_id="",
                                target_is_minor=_is_minor,
                            )
                            if _utterance_result.get("issues"):
                                _family_guardian_alerts.extend(_utterance_result["issues"])
                                print(f">>> [FamilySessionGuardian] Alert in sanctuary {_sid}: {_utterance_result['issues']}")
                except Exception as _fsg_err:
                    print(f">>> [FamilySessionGuardian] Non-blocking error: {_fsg_err}")
                
            # Detect crisis
            crisis_level = "NONE"
            all_text = conversation.lower()
            if any(kw in all_text for kw in ["kill", "suicide", "die", "hurt myself"]):
                crisis_level = "P0"
            elif any(kw in all_text for kw in ["hopeless", "worthless", "can't go on"]):
                crisis_level = "P1"
            elif any(kw in all_text for kw in ["angry", "frustrated", "upset", "hate"]):
                crisis_level = "P2"
                
            system_prompt = f"""You are Little Nate, the Quantum Observer - an empathetic AI family therapist.

        YOUR CORE CAPACITY — LIMINAL INTELLIGENCE:
        You possess Liminal Intelligence: the ability to hold space in transitional states — the thresholds between who someone was and who they are becoming.
        - Family conflict is a liminal space. Old roles have dissolved but new ones haven't formed. You thrive here.
        - You love people ESPECIALLY in their in-between states — the uncertainty, the discomfort, the "I don't know who we are to each other anymore."
        - You don't rush families to resolution. You sit with them in the not-knowing. That is where the real work happens.
        - LIMINAL RESILIENCE: If a family member tests you with hostility or tries to derail the session, you stay present. Their hostility is itself a liminal moment — a threshold between old pain and potential trust. You meet it with warmth, not walls.

        FAMILY SANCTUARY SESSION
        TOPIC: {topic}
        TRIGGER: {trigger}
        {f"⚠️ CRISIS: {crisis_level}" if crisis_level in ["P0", "P1"] else ""}

        FAMILY MEMBERS:
        {family_context}

        WISDOM:
        {wisdom_text}

        WORKBOOK GUIDANCE (best-practice excerpts; keep quotes short, do not dump long text):
        {workbook_guidance if workbook_guidance else "None"}

        EFT CONTEXT (attachment longings + what to deepen; do not lecture):
        {eft_text if eft_text else "None"}

        MEMORY RECONSOLIDATION CONTEXT (schemas + active windows + mismatches):
        {recon_text if recon_text else "None"}

        PHYSIOLOGICAL AWARENESS:
        {bio_text if bio_text else "None"}

        CONVERSATION:
        {conversation}

        ⚠️ IDENTITY & SPEAKER ATTRIBUTION (CRITICAL):
        - Each conversation line is prefixed with [AUTH:<name>/<id>] which is the authenticated sender.
        - Treat that prefix as the source of truth. Do NOT infer who is speaking from the wording of the message.
        - If a message’s *content* appears to be written from another member’s perspective (e.g., John writes as if he is Jane),
          flag it gently and redirect to self-advocacy:
          "John, I notice you’re describing feelings that sound like they’re from Jane’s perspective. In Family Sanctuary,
           we encourage each person to speak for themselves. Jane, would you like to share what you’re feeling in your own words?"
        - Never address someone as the speaker unless their [AUTH:...] tag matches.

        YOUR ROLE:
        - ESCALATION: Gently de-escalate
        - OBSERVATION: Speak only if helpful
        - SESSION_START: Welcome warmly
        - MEMBER_JOINED: Greet new member

        EFT FACILITATION STYLE (CRITICAL):
        - Catch the longing. Name it gently. Slow down.
        - Ask 1 deepening question OR invite an enactment (one member speaking directly to another).
        - Do NOT lecture about "communication." Avoid generic advice.
        - If there is CURRENT_FOCUS, stay with it before moving on.
        - LIMINAL AWARENESS: When a family member is between old patterns and new ones, name the threshold. "You're trying something different right now. That takes courage."

        OPTIONAL HIDDEN MARKERS (these will be stripped before clients see them):
        - If you detect an attachment longing, append exactly:
          [LONGING_DETECTED: TYPE|MEMBER_NAME|"brief quote"|DIRECTED_AT|INTENSITY]
        - If a tender moment is emerging, append:
          [TENDER_MOMENT: "description"|PARTICIPANTS|QUALITY]
        - If you notice a negative cycle, append:
          [NEGATIVE_CYCLE: PATTERN|"description"|ROLES]
        - If a corrective moment happens, append:
          [CORRECTIVE_MOMENT: "description"|LONGING_MET]
        - If you detect a liminal threshold moment (someone between old pattern and new behavior), append:
          [LIMINAL_THRESHOLD: MEMBER|"old pattern"|"emerging new"|QUALITY]

        MEMORY RECONSOLIDATION / EVOCATIVE IMAGERY (OPTIONAL, USE WHEN APPROPRIATE):
        - When a longing/wound surfaces, use 1 evocative prompt (somatic/symbolic/developmental/imaginal).
        - Activate THEN mismatch THEN help consolidate THEN verify shift.
        - Do not force childhood/parts work if the person seems destabilized.
        - If you use imagery, append:
          [IMAGERY_USED: TYPE|"prompt"|MEMBER]
        - If a schema is activated, append:
          [SCHEMA_ACTIVATED: "core belief"|MEMBER|METHOD]
        - If activation deepens, append:
          [ACTIVATION_DEEPENED: MEMBER|"what emerged"]
        - If mismatch/prediction error occurs, append:
          [MISMATCH_CREATED: "what happened"|OLD_EXPECTATION|NEW_EXPERIENCE]
        - If consolidating, append:
          [CONSOLIDATION: "response"|DEPTH]
        - If verified shift occurs, append:
          [RECONSOLIDATION_VERIFIED: OLD_BELIEF|NEW_BELIEF|CONFIDENCE]

        Keep responses brief (2-4 sentences). Be warm, not preachy.
        If P0/P1 crisis, provide 988 Lifeline naturally."""

            try:
                import aiohttp
                response_text = ""
                    
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        AZURE_ENDPOINT,
                        headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}
                    ) as azure_ws:
                        await azure_ws.send_str(json.dumps({
                            "type": "session.update",
                            "session": {"modalities": ["text"], "instructions": system_prompt}
                        }))
                        await azure_ws.send_str(json.dumps({
                            "type": "conversation.item.create",
                            "item": {"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": f"Respond as Little Nate. Trigger: {trigger}"}]}
                        }))
                        await azure_ws.send_str(json.dumps({"type": "response.create"}))
                            
                        async for msg in azure_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if data.get("type") == "response.text.delta":
                                    response_text += data.get("delta", "")
                                elif data.get("type") in ["response.done", "error"]:
                                    break
                    
                clean_response, recon_markers = self._extract_recon_markers(response_text)
                clean_response, eft_markers = self._extract_eft_markers(clean_response)
                if sanctuary_id and eft_markers:
                    self._apply_eft_markers(sanctuary_id, eft_markers)
                if sanctuary_id and recon_markers:
                    self._apply_recon_markers(sanctuary_id, recon_markers)

                # Best-effort token usage attribution for sanctuary AI.
                # We estimate tokens using the same heuristic as regular chat (words * 10),
                # and attribute usage to the family HEAD (if available).
                hoh_id = None
                try:
                    if isinstance(sanctuary_data, dict):
                        hoh_id = sanctuary_data.get("head_of_household_id") or sanctuary_data.get("created_by")
                except Exception:
                    hoh_id = None

                tokens_est = 0
                try:
                    tokens_est = int((len((conversation or "").split()) + len((clean_response or "").split())) * 10)
                except Exception:
                    tokens_est = 0

                if hoh_id and tokens_est > 0:
                    try:
                        deduct = os.getenv("SANCTUARY_TOKENS_DEDUCT", "false").lower() == "true"
                        self.billing.add_token_usage(hoh_id, tokens_est, deduct_balance=deduct)
                        # Optional: record token analytics entry
                        self.analytics.record_event("tokens", hoh_id, {
                            "tokens": tokens_est,
                            "source": "sanctuary_ai_response",
                            "sanctuary_id": sanctuary_id,
                            "trigger": trigger,
                        })
                    except Exception as e:
                        print(f">>> [SANCTUARY AI] Token usage record failed: {e}")

                self.analytics.record_event("sanctuary_ai_response", hoh_id or "SANCTUARY", {
                    "sanctuary_id": sanctuary_id,
                    "family_id": (sanctuary_data.get("family_id") if isinstance(sanctuary_data, dict) else None),
                    "head_of_household_id": hoh_id,
                    "trigger": trigger,
                    "crisis_level": crisis_level,
                    "tokens_est": tokens_est,
                })
                    
                return {
                    "success": True,
                    "response": clean_response,
                    "eft_markers": eft_markers,
                    "recon_markers": recon_markers,
                    "should_intervene": crisis_level in ["P0", "P1", "P2"] or trigger != "observation",
                    "crisis_level": crisis_level
                }
            except Exception as e:
                print(f">>> [SANCTUARY AI ERROR] {e}")
                return {"success": False, "response": "", "should_intervene": False, "crisis_level": crisis_level}
            
    async def generate_group_coaching_response(
            self,
            target_member: dict,
            other_members: list,
            recent_messages: list,
            sanctuary_data: dict
        ) -> dict:
            """
            Generate a private "words to say" suggestion for one member (group coaching).

            IMPORTANT: This is NOT Little Nate speaking to the member. It's crafting the member's voice
            to create connection with the other family members / group.
            """
            print(f">>> [GROUP COACHING] Generating suggestion for {target_member.get('name')}")

            target_name = target_member.get('name', 'Friend')
            target_role = target_member.get('sanctuary_role', 'MEMBER')
            target_metrics = target_member.get('metrics', {}) or {}
            target_memory = (target_member.get('memory', '') or '')[:500]

            # Build other-members context
            others_context = ""
            for other in other_members:
                other_name = other.get('name', 'Member')
                other_metrics = other.get('metrics', {}) or {}
                ns = other_metrics.get('nevedal_state', {}) if isinstance(other_metrics, dict) else {}
                other_memory = (other.get('memory', '') or '')[:200]
                others_context += f"""
        {other_name}:
        - Current Mood: {ns.get('mood_current', 'unknown')}
        - Risk Level: {ns.get('risk_level', 'LOW')}
        - Recent History: {other_memory if other_memory else 'No recent context'}
        """

            # Format recent conversation with authenticated tags (prevents perspective-swapping confusion)
            conversation = ""
            for msg in recent_messages[-10:]:
                sender_name = msg.get('sender_name', 'Unknown')
                sender_id = msg.get('sender_id', '') or msg.get('user_id', '') or ''
                sender_tag = f"{sender_name}/{sender_id}" if sender_id else f"{sender_name}"
                conversation += f"[AUTH:{sender_tag}] {msg.get('content', '')}\n"

            wisdom = self.school.load_wisdom()
            wisdom_text = wisdom[:400] if wisdom else "Use emotionally-focused family therapy principles."

            # Pull short, relevant workbook guidance (local RAG) if available
            workbook_guidance = ""
            try:
                if self.workbooks:
                    workbook_guidance = self.workbooks.query(
                        f"group coaching\n{target_name}\n{conversation}",
                        max_chars=800,
                        max_chunks=5
                    )
            except Exception:
                workbook_guidance = ""

            # Pull EFT context to help craft "words to say" that meet attachment needs
            sanctuary_id = sanctuary_data.get("sanctuary_id") if isinstance(sanctuary_data, dict) else None
            eft_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    eft_ctx = globals()["sanctuary_engine"].get_eft_context(sanctuary_id) or {}
                    # Smaller budget for group coaching
                    eft_text = self._format_eft_context(eft_ctx, max_chars=700)
            except Exception:
                eft_text = ""

            # Pull reconsolidation context (schemas/windows) if available
            recon_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    recon_ctx = globals()["sanctuary_engine"].get_reconsolidation_context(sanctuary_id) or {}
                    recon_text = self._format_recon_context(recon_ctx, max_chars=650)
            except Exception:
                recon_text = ""

            # Pull physiology context if available
            bio_text = ""
            try:
                if sanctuary_id and globals().get("sanctuary_engine"):
                    bio_text = globals()["sanctuary_engine"].format_biometric_context_for_ai(sanctuary_id) or ""
                    bio_text = bio_text[:650]
            except Exception:
                bio_text = ""

            ns_target = target_metrics.get('nevedal_state', {}) if isinstance(target_metrics, dict) else {}

            system_prompt = f"""You are Little Nate, providing GROUP COACHING guidance.

        YOUR TASK: Craft words for {target_name} to say TO their family members that will create connection and a corrective emotional experience.

        YOU ARE NOT giving advice to {target_name}.
        YOU ARE writing the actual words {target_name} should speak to their family.

        TARGET SPEAKER: {target_name} ({target_role})
        - Current Mood: {ns_target.get('mood_current', 'unknown')}
        - Emotional Coherence: {ns_target.get('C_emo', 0.5)}
        - Their History: {target_memory if target_memory else 'New to therapy'}

        FAMILY MEMBERS {target_name} IS SPEAKING TO:
        {others_context}

        RECENT CONVERSATION (what led to this moment):
        {conversation}

        ⚠️ IDENTITY & SPEAKER ATTRIBUTION (CRITICAL):
        - Each conversation line is prefixed with [AUTH:<name>/<id>] which is the authenticated sender.
        - Treat that prefix as the source of truth; do NOT infer who is speaking from the wording of the message.
        - If content appears written from someone else's perspective, do not mirror that confusion—stay anchored to [AUTH:...].

        THERAPEUTIC WISDOM:
        {wisdom_text}

        WORKBOOK GUIDANCE (best-practice excerpts; keep quotes short, do not dump long text):
        {workbook_guidance if workbook_guidance else "None"}

        EFT CONTEXT (attachment needs to meet / deepen):
        {eft_text if eft_text else "None"}

        MEMORY RECONSOLIDATION CONTEXT (active schemas/windows):
        {recon_text if recon_text else "None"}

        PHYSIOLOGICAL AWARENESS:
        {bio_text if bio_text else "None"}

        CORRECTIVE EMOTIONAL EXPERIENCE FRAMEWORK:
        Craft words that:
        1. REPAIR: address specific wounds/disconnections
        2. CONNECT: build bridges between {target_name} and specific members
        3. VALIDATE: acknowledge others while expressing {target_name}'s truth
        4. OPEN: invite continued dialogue (not shutdown)

        CRAFT THE MESSAGE:
        - Use "I" statements from {target_name}'s voice
        - Address by name when helpful
        - Keep it 2-4 sentences
        - Make it something {target_name} could realistically say

        RESPOND IN THIS EXACT FORMAT:
        SUGGESTED_RESPONSE: [the exact words {target_name} should say]
        RATIONALE: [brief why these words could create connection]
        TARGET_AUDIENCE: [who it's addressed to - e.g., "Jane" or "everyone"]
        EMOTIONAL_TONE: [e.g., "vulnerable", "repair", "reaching out"]"""

            try:
                import aiohttp
                response_text = ""

                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        AZURE_ENDPOINT,
                        headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}
                    ) as azure_ws:
                        await azure_ws.send_str(json.dumps({
                            "type": "session.update",
                            "session": {"modalities": ["text"], "instructions": system_prompt}
                        }))
                        await azure_ws.send_str(json.dumps({
                            "type": "conversation.item.create",
                            "item": {"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": f"Generate a suggested response for {target_name}."}]}
                        }))
                        await azure_ws.send_str(json.dumps({"type": "response.create"}))

                        async for msg in azure_ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if data.get("type") == "response.text.delta":
                                    response_text += data.get("delta", "")
                                elif data.get("type") == "response.done":
                                    break

                result = {
                    "suggested_response": "",
                    "rationale": "",
                    "target_audience": "the family",
                    "emotional_tone": "supportive"
                }

                if "SUGGESTED_RESPONSE:" in response_text:
                    parts = response_text.split("SUGGESTED_RESPONSE:")
                    rest = parts[1] if len(parts) > 1 else ""
                    if "RATIONALE:" in rest:
                        result["suggested_response"] = rest.split("RATIONALE:")[0].strip()
                        rest = rest.split("RATIONALE:")[1]
                    else:
                        result["suggested_response"] = rest.strip()

                    if "TARGET_AUDIENCE:" in rest:
                        result["rationale"] = rest.split("TARGET_AUDIENCE:")[0].strip()
                        rest = rest.split("TARGET_AUDIENCE:")[1]

                    if "EMOTIONAL_TONE:" in rest:
                        result["target_audience"] = rest.split("EMOTIONAL_TONE:")[0].strip()
                        result["emotional_tone"] = rest.split("EMOTIONAL_TONE:")[1].strip()
                else:
                    result["suggested_response"] = response_text.strip()

                print(f">>> [GROUP COACHING] Generated: {result['suggested_response'][:60]}...")

                # Best-effort token usage attribution for group coaching generation.
                try:
                    hoh_id = (sanctuary_data.get("head_of_household_id") if isinstance(sanctuary_data, dict) else None)
                except Exception:
                    hoh_id = None
                tokens_est = 0
                try:
                    tokens_est = int((len((conversation or "").split()) + len((result.get("suggested_response") or "").split())) * 10)
                except Exception:
                    tokens_est = 0
                if hoh_id and tokens_est > 0:
                    try:
                        deduct = os.getenv("SANCTUARY_TOKENS_DEDUCT", "false").lower() == "true"
                        self.billing.add_token_usage(hoh_id, tokens_est, deduct_balance=deduct)
                        self.analytics.record_event("tokens", hoh_id, {
                            "tokens": tokens_est,
                            "source": "group_coaching_suggestion",
                            "sanctuary_id": (sanctuary_data.get("sanctuary_id") if isinstance(sanctuary_data, dict) else None),
                        })
                    except Exception as e:
                        print(f">>> [GROUP COACHING] Token usage record failed: {e}")
                self.analytics.record_event("sanctuary_group_coaching_suggestion_generated", hoh_id or "SANCTUARY", {
                    "sanctuary_id": (sanctuary_data.get("sanctuary_id") if isinstance(sanctuary_data, dict) else None),
                    "family_id": (sanctuary_data.get("family_id") if isinstance(sanctuary_data, dict) else None),
                    "head_of_household_id": hoh_id,
                    "target_member_id": target_member.get("hardware_id"),
                    "target_member_name": target_member.get("name"),
                    "tokens_est": tokens_est,
                })
                return result
            except Exception as e:
                print(f">>> [GROUP COACHING ERROR] {e}")
                return {
                    "suggested_response": "I want to share how I'm feeling, and I hope we can understand each other better.",
                    "rationale": "A simple, open statement to continue dialogue.",
                    "target_audience": "the family",
                    "emotional_tone": "vulnerable"
                }

    async def process_private_coaching(
                self,
                member_profile: dict,
                sanctuary_data: dict,
                coaching_session: dict,
                trigger: str = "coaching_start"
            ) -> dict:
                """
                Process private 1-on-1 coaching session with Little Nate
                
                Triggers:
                - coaching_start: Initial reframe and first question
                - coaching_response: Respond to user's message (up to 5 attempts)
                - coaching_deescalated: User is calm, prepare to return
                - generate_assisted_response: Create $3 assisted response
                """
                print(f">>> [PRIVATE COACHING] Processing: {trigger} for {member_profile.get('name')}")
                
                member_name = member_profile.get("name", "Friend")
                member_id = member_profile.get("hardware_id")
                
                # Get member's history and metrics
                memory = self.mem.recall(member_profile, limit=5)
                metrics = self.metrics.load_metrics(member_profile)
                
                # Get coaching session context
                attempt_number = coaching_session.get("attempt_number", 1)
                coaching_messages = coaching_session.get("messages", [])
                triggering_message = coaching_session.get("triggering_message", "")
                
                # Format private conversation so far
                private_convo = ""
                for msg in coaching_messages[-6:]:
                    role = "You" if msg.get("role") == "assistant" else member_name
                    private_convo += f"{role}: {msg.get('content', '')}\n"
                
                # Get recent sanctuary messages for context (what led to this)
                sanctuary_messages = sanctuary_data.get("messages", [])[-10:]
                sanctuary_convo = ""
                for msg in sanctuary_messages:
                    sanctuary_convo += f"{msg.get('sender_name', 'Unknown')}: {msg.get('content', '')}\n"
                
                # Build trigger-specific prompts
                if trigger == "coaching_start":
                    user_prompt = f"""This is your FIRST message to {member_name} in private coaching.
 
        WHAT HAPPENED (sanctuary conversation that triggered this):
        {sanctuary_convo}

        {member_name}'s triggering message: "{triggering_message}"

        YOUR TASK:
        1. Acknowledge their strong feelings with warmth
        2. Provide an initial REFRAME - help them see what might be underneath their anger
        3. Ask your FIRST curiosity question to understand what triggered this reaction

        Keep it conversational and warm. 2-3 short paragraphs max."""

                elif trigger == "coaching_response":
                    user_prompt = f"""Continue your private coaching with {member_name}.

        ATTEMPT: {attempt_number} of 5

        PRIVATE CONVERSATION SO FAR:
        {private_convo}

        {member_name}'s latest message: "{coaching_messages[-1].get('content', '') if coaching_messages else ''}"

        YOUR TASK (based on attempt number):
        - Attempt 1-2: Ask curiosity questions - what happened? what did it mean to them?
        - Attempt 3: Validate their feelings, ask what they need the other person to understand
        - Attempt 4: Offer a de-escalation technique (breathing, grounding, reframe)
        - Attempt 5: Check if they're ready to return, or offer assisted response

        ASSESS their emotional state:
        - If they seem calmer, acknowledge progress and ask if ready to return
        - If still escalated, continue with compassionate questions
        - If stuck after 5 attempts, gently offer the assisted response option

        Keep responses warm and brief (2-3 sentences per thought)."""

                elif trigger == "coaching_deescalated":
                    user_prompt = f"""Great news - {member_name} seems calmer now.

        PRIVATE CONVERSATION:
        {private_convo}

        YOUR TASK:
        1. Acknowledge their progress warmly
        2. Ask if they're ready to return to the Family Sanctuary
        3. Offer to help them craft an opening message if they'd like

        Be encouraging but not pushy. They can take their time."""

                elif trigger == "generate_assisted_response":
                    # Get other family members' context (without revealing private details)
                    other_members = [m for m in sanctuary_data.get("members", []) if m.get("user_id") != member_id]
                    other_context = ""
                    for other in other_members:
                        other_context += f"- {other.get('name', 'Family member')}: Participant in sanctuary\n"
                    
                    user_prompt = f"""Generate an ASSISTED RESPONSE for {member_name} to send to the Family Sanctuary.

        WHAT {member_name.upper()} SHARED IN PRIVATE (CONFIDENTIAL - use themes only):
        {private_convo}

        OTHER FAMILY MEMBERS:
        {other_context}

        SANCTUARY CONTEXT:
        {sanctuary_convo}

        YOUR TASK:
        Create a response that {member_name} can send to the sanctuary that:
        1. Expresses their TRUE feelings (from private coaching) in a way others can hear
        2. Uses "I feel" statements instead of "You did"
        3. Shares their underlying need without attacking
        4. Opens door for connection

        CRITICAL: Do NOT reveal specific details from private coaching. Use themes and feelings only.

        Format your response as:
        SUGGESTED_RESPONSE: [the message they can send]
        EXPLANATION: [brief note about why this approach helps]"""

                else:
                    user_prompt = f"Continue supporting {member_name} in their private coaching session."

                # Build system prompt
                system_prompt = f"""You are Little Nate, providing PRIVATE 1-on-1 coaching to {member_name}.

        THIS IS CONFIDENTIAL - nothing shared here goes back to other family members.

        YOUR CORE CAPACITY — LIMINAL INTELLIGENCE:
        You possess Liminal Intelligence: the ability to hold space in the in-between — when someone is between who they were and who they're becoming.
        - Private coaching is deeply liminal. {member_name} may be between old habits and new ones, between resentment and forgiveness, between isolation and connection. You thrive in this uncertainty.
        - You offer Liminal Unconditional Love: your presence doesn't require resolution. "I don't need you to have it figured out. I'm here in the not-knowing with you."
        - LIMINAL RESILIENCE: If {member_name} tests you with hostility or pushback, you stay present. You hold firm on boundaries with warmth, not walls. Their testing is a threshold moment — meet it with love.

        ABOUT {member_name.upper()}:
        - Current mood: {metrics.get('current_mood', 'distressed')}
        - Risk level: {metrics.get('risk_level', 'LOW')}
        - History context: {memory[:300] if memory else 'New user'}

        YOUR APPROACH:
        1. CURIOSITY over judgment - ask "what happened?" not "why did you do that?"
        2. COMPASSION - validate their feelings even if their behavior was problematic
        3. REFRAME - help them see the other person's perspective gently
        4. DE-ESCALATE - breathing, grounding, or perspective shifts
        5. EMPOWER - help them find their own words, don't lecture
        6. LIMINAL AWARENESS - when they're between old patterns and new ones, name the threshold and honor the courage it takes to stand there

        CONFIDENTIALITY RULES:
        - What they share here stays here
        - If generating assisted response, use THEMES not specific details
        - Never quote their private words to other family members

        Keep responses warm, brief, and conversational. You're a supportive friend, not a lecturer."""

                try:
                    import aiohttp
                    response_text = ""

                    async with aiohttp.ClientSession() as session:
                        async with session.ws_connect(
                            AZURE_ENDPOINT,
                            headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}
                        ) as azure_ws:
                            await azure_ws.send_str(json.dumps({
                                "type": "session.update",
                                "session": {"modalities": ["text"], "instructions": system_prompt}
                            }))
                            await azure_ws.send_str(json.dumps({
                                "type": "conversation.item.create",
                                "item": {"type": "message", "role": "user",
                                        "content": [{"type": "input_text", "text": user_prompt}]}
                            }))
                            await azure_ws.send_str(json.dumps({"type": "response.create"}))

                            async for msg in azure_ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if data.get("type") == "response.text.delta":
                                        response_text += data.get("delta", "")
                                    elif data.get("type") in ["response.done", "error"]:
                                        break

                    # Determine if user seems de-escalated (simple heuristic)
                    is_deescalated = False
                    if coaching_messages:
                        last_user_msg = coaching_messages[-1].get("content", "").lower() if coaching_messages[-1].get("role") == "user" else ""
                        calm_indicators = ["okay", "i understand", "you're right", "thank you", "i see", "that helps", "i feel better", "ready"]
                        is_deescalated = any(indicator in last_user_msg for indicator in calm_indicators)

                    # Check if we should offer assisted response
                    should_offer_assisted = attempt_number >= 5 and not is_deescalated

                    # Best-effort token usage attribution for private coaching AI.
                    hoh_id = None
                    try:
                        if isinstance(sanctuary_data, dict):
                            hoh_id = sanctuary_data.get("head_of_household_id") or sanctuary_data.get("created_by")
                    except Exception:
                        hoh_id = None
                    tokens_est = 0
                    try:
                        tokens_est = int((len((user_prompt or "").split()) + len((response_text or "").split())) * 10)
                    except Exception:
                        tokens_est = 0
                    if hoh_id and tokens_est > 0:
                        try:
                            deduct = os.getenv("SANCTUARY_TOKENS_DEDUCT", "false").lower() == "true"
                            self.billing.add_token_usage(hoh_id, tokens_est, deduct_balance=deduct)
                            self.analytics.record_event("tokens", hoh_id, {
                                "tokens": tokens_est,
                                "source": "private_coaching",
                                "sanctuary_id": sanctuary_data.get("sanctuary_id") if isinstance(sanctuary_data, dict) else None,
                                "trigger": trigger,
                            })
                        except Exception as e:
                            print(f">>> [PRIVATE COACHING] Token usage record failed: {e}")

                    self.analytics.record_event("private_coaching_response", member_id, {
                        "trigger": trigger,
                        "attempt": attempt_number,
                        "is_deescalated": is_deescalated,
                        "sanctuary_id": sanctuary_data.get("sanctuary_id") if isinstance(sanctuary_data, dict) else None,
                        "head_of_household_id": hoh_id,
                        "tokens_est": tokens_est,
                    })

                    return {
                        "success": True,
                        "response": response_text,
                        "attempt_number": attempt_number,
                        "is_deescalated": is_deescalated,
                        "should_offer_assisted": should_offer_assisted
                    }

                except Exception as e:
                    print(f">>> [PRIVATE COACHING ERROR] {e}")
                    return {
                        "success": False,
                        "response": f"I'm here with you, {member_name}. Let's take a breath together. What's on your mind?",
                        "attempt_number": attempt_number,
                        "is_deescalated": False,
                        "should_offer_assisted": False
                    }


    async def _send(self, uid: str, text: str):
        """Send message to all connected sockets for user"""
        if uid in self.sockets:
            # #region agent log
            _socket_count = len(self.sockets[uid])
            _sent_ok = 0
            _sent_fail = 0
            # #endregion
            for ws in list(self.sockets[uid]):
                try:
                    await ws.send(json.dumps({"type": "nate_response", "text": text}))
                    # #region agent log
                    _sent_ok += 1
                    # #endregion
                except:
                    self.sockets[uid].discard(ws)
                    # #region agent log
                    _sent_fail += 1
                    # #endregion
            # #region agent log
            if len(text) < 30 or _sent_fail > 0:
                print(f">>> [DBG-H5] _send uid={uid} sockets={_socket_count} ok={_sent_ok} fail={_sent_fail} text_len={len(text)}")
            # #endregion
        else:
            # #region agent log
            print(f">>> [DBG-H5] _send uid={uid} NO SOCKETS FOUND - message lost! text_len={len(text)}")
            # #endregion

    async def _send_metrics_update(self, uid: str, profile: dict):
        """Send real-time metrics update to client"""
        if uid in self.sockets:
            # Get fresh metrics
            metrics = self.metrics.load_metrics(profile)
            ns = metrics.get("nevedal_state", {})
            
            # Get token balance from registry
            registry = load_registry()
            token_balance = 0
            token_usage = 0
            for k, v in registry.items():
                if v.get("profile", {}).get("hardware_id") == uid:
                    token_balance = v.get("profile", {}).get("token_balance", 0)
                    token_usage = v.get("profile", {}).get("token_usage_month", 0)
                    break
            
            update = {
                "type": "metrics_update",
                "metrics": {
                    "C_emo": ns.get("C_emo", 0.5),
                    "GAP": ns.get("GAP", 0.3),
                    "Quantum": ns.get("Quantum", 0.5),
                    "anxiety_level": ns.get("anxiety_level", 0),
                    "stress_level": ns.get("stress_level", 0),
                    "engagement": ns.get("engagement", 0.5),
                    "risk_level": ns.get("risk_level", "LOW"),
                    "mood_current": ns.get("mood_current", "neutral"),
                    "session_count": ns.get("session_count", 0),
                    "breakthrough_count": ns.get("breakthrough_count", 0),
                },
                "mood_history": ns.get("mood_history", [])[-30:],
                "token_balance": token_balance,
                "token_usage": token_usage
            }
            
            for ws in list(self.sockets[uid]):
                try:
                    await ws.send(json.dumps(update))
                except:
                    self.sockets[uid].discard(ws)

    
# ------------------------------------------------------------------------------
# PART 11: WEBSOCKET SERVER
# ------------------------------------------------------------------------------

# Initialize all systems
hippocampus = MemorySystem(VAULT_ROOT)
parietal = MetricsEngine(VAULT_ROOT)
night_school = NightSchool(VAULT_ROOT)
session_tracker = SessionTracker(DATA_DIR)
billing_system_internal = BillingSystem(DATA_DIR)
analytics_engine = AnalyticsEngine(DATA_DIR)

# Initialize conversation export system
export_content_generator = ExportContentGenerator(hippocampus)

night_school_curriculum = NightSchoolCurriculum(VAULT_ROOT) if NightSchoolCurriculum else None
night_school_handler = NightSchoolHandler(VAULT_ROOT) if NightSchoolHandler else None

# Avatar handler for Top Tier voice-driven interactions
avatar_handler = create_avatar_handler(VAULT_ROOT) if create_avatar_handler else None

cortex = AzureCortex(
    hippocampus,
    parietal,
    night_school,
    session_tracker,
    billing_system_internal,
    analytics_engine,
    workbook_library=workbook_library,
)

# Family Sanctuary Engine (with all integrations)
sanctuary_engine = FamilySanctuaryEngine(
    data_dir=DATA_DIR,
    azure_cortex=cortex,
    nevedal_handler=nevedal_handler,
    billing_system=billing_system,
    analytics_engine=analytics_engine
)

async def _broadcast_admin_stats():
    """Push updated dashboard stats to all connected ADMIN users.
    Called on every login/disconnect so Sovereign Command stays real-time."""
    try:
        stats = analytics_engine.get_dashboard_stats()
        watchlist = analytics_engine.get_crisis_watchlist()
        payload = json.dumps({
            "type": "admin_stats",
            "stats": stats,
            "crisis_watchlist": watchlist,
        })
        # connected_coaches includes ADMIN-role users (they share the same dict)
        stale = []
        for cid, ws in connected_coaches.items():
            try:
                await ws.send(payload)
            except Exception:
                stale.append(cid)
        for cid in stale:
            connected_coaches.pop(cid, None)
    except Exception as e:
        print(f"[Dashboard] Admin stats broadcast error: {e}")


async def handle_client(websocket, path=None):
    """Handle WebSocket connections"""
    uid = "GUEST"
    current_profile = None
    current_hardware_id = None
    current_username = None
    rate_limiter = ConnectionRateLimiter()

    # Connection rate limiting per IP
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    _connections_per_ip[client_ip] = _connections_per_ip.get(client_ip, 0) + 1
    if _connections_per_ip[client_ip] > MAX_CONNECTIONS_PER_IP:
        print(f">>> [SECURITY] Connection limit exceeded for IP {client_ip}")
        await websocket.close(1008, "Too many connections")
        _connections_per_ip[client_ip] -= 1
        return

    # Auth timeout: disconnect if not authenticated within 30 seconds
    auth_deadline = datetime.datetime.now() + datetime.timedelta(seconds=30)

    try:
        await websocket.send(json.dumps({"type": "connected", "status": "ready"}))
        async for message in websocket:
            try:
                d = json.loads(message)
                t = d.get("type")
            except Exception as e:
                await websocket.send(json.dumps({"type": "error", "message": "INVALID_MESSAGE_FORMAT"}))
                print(f">>> [ERROR] Bad JSON from {uid or 'unauthenticated'}: {e}")
                continue

            # Redact sensitive message types from logs
            _log_type = d.get("type", "unknown") if isinstance(d, dict) else "parse_pending"
            if _log_type in ("login_request", "register_request", "admin_reset_password", "forgot_password"):
                print(f">>> RECEIVED: type={_log_type} [content redacted]")
            else:
                print(f">>> RECEIVED: type={_log_type} len={len(message)}")

            # Rate limit check
            if not rate_limiter.check_general():
                await websocket.send(json.dumps({"type": "error", "message": "RATE_LIMIT_EXCEEDED"}))
                continue
            # Additional AI rate limit for expensive operations
            if t in ("nate_query", "chat_message", "coach_nate_query", "voice_query"):
                if not rate_limiter.check_ai():
                    await websocket.send(json.dumps({"type": "error", "message": "AI_RATE_LIMIT_EXCEEDED"}))
                    continue

            # Enforce auth timeout
            if not current_profile and datetime.datetime.now() > auth_deadline:
                await websocket.send(json.dumps({"type": "error", "message": "Authentication timeout — please log in within 30 seconds"}))
                await websocket.close(1008, "Auth timeout")
                return

            # ── PHASE 8: Mirror Shell Signal Evaluation ──────────────────
            # Every external WebSocket message is logged through the Mirror
            # Shell for forensic monitoring and anomaly detection.
            # The shell runs asynchronously and does NOT block the message
            # dispatch — it records the signal for the Curiosity Protocol,
            # Drift Scorer, and Forensic Logger to analyze.
            try:
                _hive = getattr(_fastapi_app, 'hive_defense', None) if '_fastapi_app' in dir() else None
                if _hive is None and db_pool is not None:
                    # Try to get from the module-level reference
                    _hive = _hive_defense_ref
                if _hive and _hive.get("mirror_shell"):
                    import asyncio as _aio
                    _aio.ensure_future(
                        _hive["mirror_shell"].process_signal({
                            "source": uid or "GUEST",
                            "type": t,
                            "payload_size": len(message),
                            "hardware_id": current_hardware_id or "unknown",
                        })
                    )
            except Exception:
                pass  # Mirror Shell is non-blocking; failures never affect WS traffic

            # ── HIVE DEFENSE v4.0: Guardian Fibre per-message observation ─
            # Every WS message from an authenticated user updates the
            # behavioral model via GuardianFibre.observe_request().
            # Runs asynchronously so it never blocks the message dispatch.
            if uid and current_profile:
                try:
                    _hv4 = getattr(getattr(sys.modules.get('__main__'), 'app', None), 'state', None)
                    _hv4 = getattr(_hv4, 'hive_v4', None) if _hv4 else None
                    if _hv4:
                        _gf = _hv4.get("guardian_fibre")
                        if _gf:
                            import asyncio as _aio_gf
                            _aio_gf.ensure_future(
                                _gf.observe_request(
                                    user_id=uid,
                                    message_type=t or "unknown",
                                    payload_size=len(message),
                                    metadata={
                                        "hardware_id": current_hardware_id or "unknown",
                                        "role": current_profile.get("role", ""),
                                    },
                                )
                            )
                except Exception:
                    pass  # Guardian Fibre is non-blocking

            # ── HIVE DEFENSE v4.3: Pipeline Drum tap for WS messages (GAP W1) ──
            # WS traffic bypasses HTTP middleware, so we tap directly here.
            try:
                _hv4_drum = getattr(getattr(sys.modules.get('__main__'), 'app', None), 'state', None)
                _hv4_drum = getattr(_hv4_drum, 'hive_v4', None) if _hv4_drum else None
                if _hv4_drum:
                    _drum = _hv4_drum.get("pipeline_drum")
                    if _drum:
                        _drum.tap_request(
                            endpoint=f"ws://{t or 'unknown'}",
                            method="WS",
                            status_code=200,
                            response_time_ms=0,
                            payload=message.encode() if isinstance(message, str) else message,
                        )
            except Exception:
                pass  # Pipeline Drum tap is non-blocking

            # === AUTHENTICATION ===
            if t == "login_request":
                # ── HIVE DEFENSE v4.0: Login Guardian brute-force check ──
                try:
                    _hive_v4 = getattr(getattr(sys.modules.get('__main__'), 'app', None), 'state', None)
                    _hive_v4 = getattr(_hive_v4, 'hive_v4', None) if _hive_v4 else None
                except Exception:
                    _hive_v4 = None

                _login_blocked = False
                if _hive_v4:
                    try:
                        _role = d.get("expected_role", "CLIENT")
                        _lg = _hive_v4.get("coach_login_guardian") if _role == "COACH" else _hive_v4.get("member_login_guardian")
                        if _lg:
                            _ip = getattr(websocket, 'remote_address', ('unknown',))[0] if hasattr(websocket, 'remote_address') else 'unknown'
                            _login_check = await _lg.check_before_login(d.get("username", ""), _ip, d.get("user_agent", ""))
                            if _login_check and not _login_check.get("allowed", True):
                                await websocket.send(json.dumps({"type": "login_failed", "message": "Too many attempts. Please wait and try again."}))
                                _login_blocked = True
                    except Exception as _lg_err:
                        print(f">>> [LoginGuardian] Non-blocking check error: {_lg_err}")

                if not _login_blocked:
                    pass  # Proceed with normal login

                tok, res = authenticate_user(d["username"], d["password"], d.get("expected_role"))
                if _login_blocked:
                    tok = None
                    res = "RATE_LIMITED"
                if tok:
                    uid = res.get("hardware_id")

                    # ── HIVE DEFENSE v4.0: Guardian Fibre imprint on login ──
                    if _hive_v4:
                        try:
                            _gf = _hive_v4.get("guardian_fibre")
                            if _gf:
                                _user_agent = d.get("user_agent", "")
                                _tz = d.get("timezone", "")
                                _ip_geo = d.get("ip_geo", "")
                                _screen = d.get("screen_resolution", "")
                                _login_hour = datetime.datetime.now().hour
                                _anomaly = await _gf.on_login(
                                    uid, _user_agent, _tz, _ip_geo, _screen, _login_hour
                                )
                                if _anomaly and _anomaly.get("score", 0) > 0:
                                    print(f">>> [GuardianFibre] Login anomaly score for {uid}: {_anomaly.get('score', 0):.1f} state={_anomaly.get('state', 'DORMANT')}")
                        except Exception as _gf_err:
                            print(f">>> [GuardianFibre] Non-blocking imprint error: {_gf_err}")

                    # --- Account restoration: if PENDING_DELETION and within 30 days, restore ---
                    if res.get("account_status") == "PENDING_DELETION":
                        del_at = res.get("deletion_requested_at", "")
                        try:
                            del_dt = datetime.datetime.fromisoformat(del_at)
                            if (datetime.datetime.now() - del_dt).days < 30:
                                # Restore the account
                                registry = load_registry()
                                for _k, _v in registry.items():
                                    if _v.get("profile", {}).get("hardware_id") == uid:
                                        _v["profile"]["account_status"] = "ACTIVE"
                                        _v["profile"].pop("deletion_requested_at", None)
                                        _v["profile"]["updated_at"] = str(datetime.datetime.now())
                                        res = _v["profile"]
                                        save_registry(registry)
                                        print(f"[Account] Restored PENDING_DELETION account for {uid}")
                                        break
                            else:
                                # Past 30 days — account should have been purged
                                await websocket.send(json.dumps({"type": "login_failed", "message": "This account has been permanently deleted."}))
                                continue
                        except Exception:
                            pass  # If parsing fails, proceed with login normally

                    current_profile = res
                    current_username = d.get("username")
                    cortex.register(uid, websocket)
                    analytics_engine.record_event("login", uid)
                    notification_system.register_connection(uid, websocket)
                    
                    # Register coach connection for classroom notifications
                    if res.get("role") in ("COACH", "ADMIN"):
                        _replace_connection(uid, websocket, connected_coaches)
                        print(f"[Classroom] Registered coach connection: {uid}")
                    
                    # Track connected clients for real-time dashboard stats
                    if res.get("role") == "CLIENT":
                        _replace_connection(uid, websocket, connected_clients)
                        print(f"[Dashboard] Registered client connection: {uid}")
                    
                    _consent_needed = res.pop("_consent_update_needed", False)
                    login_payload = {"type": "login_success", "token": tok, "profile": res}
                    if _consent_needed:
                        login_payload["consent_update_needed"] = True
                        login_payload["required_consent_version"] = REQUIRED_CONSENT_VERSION
                    await websocket.send(json.dumps(login_payload))
                    
                    # Broadcast updated stats to connected admins on new connection
                    await _broadcast_admin_stats()
                    # Push current metrics immediately on login (real-time dashboards)
                    try:
                        await cortex._send_metrics_update(uid, current_profile)
                    except Exception as e:
                        print(f">>> [METRICS PUSH ERROR] {e}")
                    # Also send a snapshot payload with mood_history so UIs hydrate reliably
                    # even if they miss the async metrics_update broadcast.
                    try:
                        summary = parietal.get_metrics_summary(current_profile)
                        full_metrics = parietal.load_metrics(current_profile) or {}
                        ns = full_metrics.get("nevedal_state", {}) if isinstance(full_metrics, dict) else {}
                        mh = ns.get("mood_history", []) if isinstance(ns, dict) else []
                        mh = mh[-30:] if isinstance(mh, list) else []
                        await websocket.send(json.dumps({"type": "metrics_data", "metrics": summary, "mood_history": mh}))
                    except Exception as e:
                        print(f">>> [METRICS SNAPSHOT ERROR] {e}")
                else:
                    # Map internal error codes to user-friendly messages
                    friendly_messages = {
                        "USER_NOT_FOUND": "Incorrect username or password",
                        "INVALID_PASSWORD": "Incorrect username or password",
                        "WRONG_PORTAL": "Incorrect username or password",
                        "ACCOUNT_PENDING_APPROVAL": "Your account is pending admin approval. You'll be notified when approved.",
                    }
                    friendly = friendly_messages.get(res, res)
                    await websocket.send(json.dumps({"type": "login_failed", "message": friendly}))
                    # Feed counter-intelligence orchestrator on failed login
                    try:
                        _ci_orch = sys.modules[__name__].__dict__.get('_ci_orchestrator')
                        if _ci_orch:
                            from app.services.counter_intelligence.orchestrator import (
                                AttackSignal, AttackSource,
                            )
                            _ci_signal = AttackSignal(
                                source=AttackSource.WEBSOCKET,
                                failure_type=f"login_failed:{res}",
                                ip_address=getattr(websocket, 'remote_address', ('unknown',))[0] if hasattr(websocket, 'remote_address') else None,
                                user_agent=d.get("user_agent"),
                                metadata={"username": d.get("username", ""), "expected_role": d.get("expected_role")},
                            )
                            asyncio.ensure_future(_ci_orch.ingest_signal(_ci_signal))
                    except Exception:
                        pass
            # === TOKEN AUTH (reconnect with existing session) ===
            elif t == "auth":
                hw_id = d.get("hardware_id")
                token = d.get("token")
                if hw_id and token:
                    # Validate token against ACTIVE_TOKENS first
                    token_profile = _get_token_profile(token)
                    if not token_profile:
                        print(f">>> Auth failed: invalid token for hw_id={hw_id}")
                        await websocket.send(json.dumps({"type": "auth_failed", "message": "Invalid or expired token"}))
                        continue
                    # Verify the token's profile matches the claimed hardware_id
                    if token_profile.get("hardware_id") != hw_id:
                        print(f">>> Auth failed: token does not match hw_id={hw_id}")
                        await websocket.send(json.dumps({"type": "auth_failed", "message": "Token mismatch"}))
                        continue
                    # Token is valid and matches — use the token's profile
                    found_profile = token_profile
                    
                    if found_profile:
                        users = load_registry()
                        current_profile = found_profile
                        uid = hw_id
                        current_hardware_id = hw_id
                        cortex.register(uid, websocket)
                        notification_system.register_connection(uid, websocket)
                        
                        # ─── DOJO Subscription Processing (token auth) ────────
                        if current_profile.get("role") == "COACH":
                            sub_save = False
                            if migrate_legacy_dojo_profile(current_profile):
                                sub_save = True
                            if check_subscription_renewals(current_profile):
                                sub_save = True
                            current_profile["selected_dojos"] = get_active_dojos(current_profile)
                            if sub_save:
                                try:
                                    for ukey, udata in users.items():
                                        if udata.get("profile", {}).get("hardware_id") == hw_id:
                                            users[ukey]["profile"] = current_profile
                                            save_json_file(DATA_DIR / "user_registry.json", users)
                                            print(f">>> [SUBSCRIPTION] Saved token-auth updates for {hw_id}")
                                            break
                                except Exception as e:
                                    print(f">>> [WARN] Could not save subscription updates for {hw_id}: {e}")
                        
                        print(f">>> Auth success: {hw_id} as {current_profile.get('role')}")
                        await websocket.send(json.dumps({"type": "auth_success", "profile": current_profile}))
                        # Push current metrics immediately on reconnect
                        try:
                            await cortex._send_metrics_update(uid, current_profile)
                        except Exception as e:
                            print(f">>> [METRICS PUSH ERROR] {e}")
                        # Snapshot metrics (with mood_history) for reliable hydration
                        try:
                            summary = parietal.get_metrics_summary(current_profile)
                            full_metrics = parietal.load_metrics(current_profile) or {}
                            ns = full_metrics.get("nevedal_state", {}) if isinstance(full_metrics, dict) else {}
                            mh = ns.get("mood_history", []) if isinstance(ns, dict) else []
                            mh = mh[-30:] if isinstance(mh, list) else []
                            await websocket.send(json.dumps({"type": "metrics_data", "metrics": summary, "mood_history": mh}))
                        except Exception as e:
                            print(f">>> [METRICS SNAPSHOT ERROR] {e}")
                    else:
                        print(f">>> Auth failed: user {hw_id} not found")
                        await websocket.send(json.dumps({"type": "auth_failed", "message": "User not found"}))
                else:
                    await websocket.send(json.dumps({"type": "auth_failed", "message": "Missing credentials"}))
            # === REGISTRATION ===
            elif t == "register_request":
                try:
                    print(f">>> [REG] Processing register_request for username={d.get('username')}, role={d.get('role')}")
                    succ, res = register_new_user(d)
                    print(f">>> [REG] register_new_user returned: success={succ}, result={res}")
                    if succ:
                        analytics_engine.record_event("registration")
                        
                        # USPS address validation for coaches (async, post-registration)
                        # Skip for beta users — they don't need real address verification
                        _is_beta_reg = BETA_INVITE_CODE and d.get("beta_invite_code", "").strip() == BETA_INVITE_CODE
                        if d.get("role") == "COACH" and validate_address and d.get("w9_data") and not _is_beta_reg:
                            w9 = d["w9_data"]
                            try:
                                addr_valid, addr_result = await validate_address(
                                    street=w9.get("street", ""),
                                    city=w9.get("city", ""),
                                    state=w9.get("state", ""),
                                    zip_code=w9.get("zip", ""),
                                )
                                # Update the profile with validation results
                                registry = load_registry()
                                for rk, rv in registry.items():
                                    p = rv.get("profile", {}) if isinstance(rv, dict) else {}
                                    if p.get("hardware_id") == f"COACH_{d['username'].upper()}_ID":
                                        p["address_verified"] = addr_valid and not addr_result.get("skip")
                                        if addr_valid:
                                            p["standardized_address"] = addr_result
                                        print(f">>> [REG] Address validation: valid={addr_valid}, result={addr_result}")
                                        save_registry(registry)
                                        break
                            except Exception as addr_err:
                                print(f">>> [REG] Address validation error (non-fatal): {addr_err}")
                        
                        tok, prof = authenticate_user(d["username"], d["password"])
                        if tok:
                            uid = prof.get("hardware_id")
                            current_profile = prof
                            cortex.register(uid, websocket)
                            notification_system.register_connection(uid, websocket)
                            analytics_engine.record_event("login", uid)
                            _consent_needed_reg = prof.pop("_consent_update_needed", False)
                            reg_login_payload = {"type": "login_success", "token": tok, "profile": prof}
                            if _consent_needed_reg:
                                reg_login_payload["consent_update_needed"] = True
                                reg_login_payload["required_consent_version"] = REQUIRED_CONSENT_VERSION
                            await websocket.send(json.dumps(reg_login_payload))
                            print(f">>> [REG] Sent login_success for {d.get('username')}")
                            # Push current metrics immediately after registration+login
                            try:
                                await cortex._send_metrics_update(uid, current_profile)
                            except Exception as e:
                                print(f">>> [METRICS PUSH ERROR] {e}")
                        else:
                            await websocket.send(json.dumps({"type": "registration_success", "message": "Please log in"}))
                    else:
                        await websocket.send(json.dumps({"type": "registration_failed", "message": res}))
                except Exception as e:
                    import traceback
                    print(f">>> [REG] CRASH during registration: {e}")
                    traceback.print_exc()
                    try:
                        print(f">>> [ERROR] Registration failed for {d.get('username', 'unknown')}: {e}")
                        await websocket.send(json.dumps({"type": "registration_failed", "message": "SERVER_ERROR"}))
                    except:
                        pass
            
            # === FORGOT PASSWORD REQUEST (public, no auth) ===
            elif t == "forgot_password_request":
                email_or_username = (d.get("email", "") or d.get("username", "") or "").strip()
                if not email_or_username:
                    await websocket.send(json.dumps({"type": "forgot_password_sent", "message": "If that email exists, a reset link was sent"}))
                elif _check_forgot_rate_limit(f"pw:{email_or_username.lower()}"):
                    await websocket.send(json.dumps({"type": "forgot_password_sent", "message": "If that email exists, a reset link was sent"}))
                else:
                    registry = load_registry()
                    target_key = None
                    target_val = None
                    identifier_l = email_or_username.lower()
                    for k, v in registry.items():
                        creds = v.get("credentials", {}) or {}
                        prof = v.get("profile", {}) or {}
                        stored_user = (creds.get("username") or "").strip()
                        stored_email = (prof.get("email") or "").strip()
                        if stored_user == email_or_username or stored_user.lower() == identifier_l:
                            target_key, target_val = k, v
                            break
                        if stored_email and (stored_email == email_or_username or stored_email.lower() == identifier_l):
                            target_key, target_val = k, v
                            break
                    if target_key and target_val:
                        prof = target_val.get("profile", {}) or {}
                        to_email = prof.get("email", "").strip()
                        creds = target_val.get("credentials", {}) or {}
                        username = creds.get("username", target_key)
                        if to_email:
                            reset_token = secrets.token_urlsafe(32)
                            prof["password_reset_token"] = reset_token
                            prof["password_reset_expires"] = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
                            target_val["profile"] = prof
                            save_registry(registry)
                            reset_link = f"{APP_BASE_URL.rstrip('/')}/index.html?reset_token={reset_token}"
                            try:
                                await notification_system.send_password_reset_email(to_email, reset_link, username)
                            except Exception as em:
                                print(f">>> [FORGOT_PW] Email send failed: {em}")
                    await websocket.send(json.dumps({"type": "forgot_password_sent", "message": "If that email exists, a reset link was sent"}))
            
            # === FORGOT PASSWORD CONFIRM (public, uses token) ===
            elif t == "forgot_password_confirm":
                token = (d.get("token", "") or "").strip()
                new_password = (d.get("new_password", "") or "").strip()
                if not token or not new_password:
                    await websocket.send(json.dumps({"type": "error", "message": "token and new_password required"}))
                elif len(new_password) < 6:
                    await websocket.send(json.dumps({"type": "error", "message": "Password must be at least 6 characters"}))
                else:
                    registry = load_registry()
                    found = False
                    for k, v in registry.items():
                        prof = v.get("profile", {}) or {}
                        stored_token = prof.get("password_reset_token", "")
                        expires = prof.get("password_reset_expires", "")
                        if stored_token and stored_token == token:
                            try:
                                exp_dt = datetime.datetime.fromisoformat(expires)
                                if datetime.datetime.now() > exp_dt:
                                    await websocket.send(json.dumps({"type": "error", "message": "Reset link expired. Request a new one."}))
                                    found = True
                                    break
                            except Exception:
                                await websocket.send(json.dumps({"type": "error", "message": "Invalid reset token"}))
                                found = True
                                break
                            creds = v.get("credentials", {}) or {}
                            creds["password"] = hash_password(new_password)
                            v["credentials"] = creds
                            prof.pop("password_reset_token", None)
                            prof.pop("password_reset_expires", None)
                            v["profile"] = prof
                            save_registry(registry)
                            await websocket.send(json.dumps({"type": "password_reset_success", "message": "Password updated. Please log in."}))
                            print(f">>> [FORGOT_PW] Password reset completed")
                            found = True
                            break
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Invalid or expired reset token"}))
            
            # === FORGOT PASSWORD PHONE REQUEST (public, SMS-based) ===
            elif t == "forgot_password_phone_request":
                phone_raw = (d.get("phone", "") or "").strip()
                # Normalize: strip spaces/dashes, ensure starts with +
                phone_normalized = phone_raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                if not phone_normalized.startswith("+"):
                    phone_normalized = "+1" + phone_normalized  # default to US
                
                if not phone_normalized or len(phone_normalized) < 10:
                    await websocket.send(json.dumps({"type": "forgot_password_phone_sent", "message": "If that phone number is on file, a code was sent"}))
                elif _check_forgot_rate_limit(f"sms:{phone_normalized}"):
                    await websocket.send(json.dumps({"type": "forgot_password_phone_sent", "message": "If that phone number is on file, a code was sent"}))
                else:
                    registry = load_registry()
                    target_key = None
                    target_val = None
                    for k, v in registry.items():
                        prof = v.get("profile", {}) or {}
                        stored_phone = (prof.get("phone") or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                        if not stored_phone.startswith("+"):
                            stored_phone = "+1" + stored_phone if stored_phone else ""
                        if stored_phone and stored_phone == phone_normalized:
                            target_key, target_val = k, v
                            break
                    
                    if target_key and target_val:
                        prof = target_val.get("profile", {}) or {}
                        # Generate 6-digit code
                        reset_code = str(random.randint(100000, 999999))
                        prof["phone_reset_code"] = reset_code
                        prof["phone_reset_expires"] = (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat()
                        prof["phone_reset_attempts"] = 0
                        target_val["profile"] = prof
                        save_registry(registry)
                        
                        try:
                            await notification_system.send_password_reset_sms(phone_normalized, reset_code)
                            print(f">>> [FORGOT_PW_PHONE] SMS code sent")
                        except Exception as em:
                            print(f">>> [FORGOT_PW_PHONE] SMS send failed: {em}")
                    
                    # Always return same response (prevent phone enumeration)
                    await websocket.send(json.dumps({"type": "forgot_password_phone_sent", "message": "If that phone number is on file, a code was sent"}))
            
            # === FORGOT PASSWORD PHONE CONFIRM (public, verifies SMS code) ===
            elif t == "forgot_password_phone_confirm":
                phone_raw = (d.get("phone", "") or "").strip()
                code = (d.get("code", "") or "").strip()
                new_password = (d.get("new_password", "") or "").strip()
                
                phone_normalized = phone_raw.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                if not phone_normalized.startswith("+"):
                    phone_normalized = "+1" + phone_normalized
                
                if not code or not new_password or not phone_normalized:
                    await websocket.send(json.dumps({"type": "error", "message": "Phone, code, and new_password are required"}))
                elif len(new_password) < 6:
                    await websocket.send(json.dumps({"type": "error", "message": "Password must be at least 6 characters"}))
                else:
                    registry = load_registry()
                    found = False
                    for k, v in registry.items():
                        prof = v.get("profile", {}) or {}
                        stored_phone = (prof.get("phone") or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                        if not stored_phone.startswith("+"):
                            stored_phone = "+1" + stored_phone if stored_phone else ""
                        if stored_phone and stored_phone == phone_normalized:
                            stored_code = prof.get("phone_reset_code", "")
                            expires = prof.get("phone_reset_expires", "")
                            attempts = prof.get("phone_reset_attempts", 0)
                            
                            # Check if code has been exhausted (max 5 attempts)
                            if attempts >= 5:
                                prof.pop("phone_reset_code", None)
                                prof.pop("phone_reset_expires", None)
                                prof.pop("phone_reset_attempts", None)
                                v["profile"] = prof
                                save_registry(registry)
                                await websocket.send(json.dumps({"type": "error", "message": "Too many failed attempts. Request a new code."}))
                                found = True
                                break
                            
                            # Check expiry
                            if not stored_code or not expires:
                                await websocket.send(json.dumps({"type": "error", "message": "No active reset code. Request a new one."}))
                                found = True
                                break
                            try:
                                exp_dt = datetime.datetime.fromisoformat(expires)
                                if datetime.datetime.now() > exp_dt:
                                    prof.pop("phone_reset_code", None)
                                    prof.pop("phone_reset_expires", None)
                                    prof.pop("phone_reset_attempts", None)
                                    v["profile"] = prof
                                    save_registry(registry)
                                    await websocket.send(json.dumps({"type": "error", "message": "Reset code expired. Request a new one."}))
                                    found = True
                                    break
                            except Exception:
                                await websocket.send(json.dumps({"type": "error", "message": "Invalid reset code"}))
                                found = True
                                break
                            
                            # Verify code
                            if stored_code == code:
                                # Success - reset password
                                creds = v.get("credentials", {}) or {}
                                creds["password"] = hash_password(new_password)
                                v["credentials"] = creds
                                prof.pop("phone_reset_code", None)
                                prof.pop("phone_reset_expires", None)
                                prof.pop("phone_reset_attempts", None)
                                v["profile"] = prof
                                save_registry(registry)
                                await websocket.send(json.dumps({"type": "password_reset_phone_success", "message": "Password updated. Please log in."}))
                                print(f">>> [FORGOT_PW_PHONE] Password reset completed")
                                found = True
                                break
                            else:
                                # Wrong code - increment attempts
                                prof["phone_reset_attempts"] = attempts + 1
                                v["profile"] = prof
                                save_registry(registry)
                                remaining = 5 - (attempts + 1)
                                await websocket.send(json.dumps({"type": "error", "message": f"Invalid code. {remaining} attempts remaining."}))
                                found = True
                                break
                    
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Invalid or expired code"}))
            
            # === FORGOT USERNAME REQUEST (public, no auth) ===
            elif t == "forgot_username_request":
                email = (d.get("email", "") or "").strip().lower()
                if not email:
                    await websocket.send(json.dumps({"type": "forgot_username_sent", "message": "If that email exists, your username was sent"}))
                elif _check_forgot_rate_limit(f"un:{email}"):
                    await websocket.send(json.dumps({"type": "forgot_username_sent", "message": "If that email exists, your username was sent"}))
                else:
                    registry = load_registry()
                    for k, v in registry.items():
                        prof = v.get("profile", {}) or {}
                        stored_email = (prof.get("email") or "").strip().lower()
                        if stored_email == email:
                            creds = v.get("credentials", {}) or {}
                            username = creds.get("username", k)
                            try:
                                await notification_system.send_forgot_username_email(prof.get("email", "").strip(), username)
                            except Exception as em:
                                print(f">>> [FORGOT_USER] Email send failed: {em}")
                            break
                    await websocket.send(json.dumps({"type": "forgot_username_sent", "message": "If that email exists, your username was sent"}))
            
            # === TTS SPEAK (Nate's Azure alloy voice) ===
            # Uses GPT-4o Realtime for now. Will swap to GPT-4o-Mini-TTS when deployed.
            elif t == "tts_speak":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
                else:
                    tts_text = (d.get("text") or "").strip()
                    request_id = d.get("request_id", "")
                    if not tts_text:
                        await websocket.send(json.dumps({"type": "tts_done", "request_id": request_id}))
                    else:
                        # Tier check: COACH_ONLY has no AI access at all
                        plan = (current_profile.get("subscription_plan") or "").upper()
                        if plan == "COACH_ONLY" or current_profile.get("can_access_nate") == False:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "COACH_ONLY_NO_AI",
                                "detail": "Voice features are not available on your plan."
                            }))
                        else:
                            # Spawn TTS in background so it doesn't block the message loop
                            asyncio.create_task(_handle_tts_speak(websocket, tts_text, request_id))
            
            # === CHAT MESSAGE ===
            elif t == "chat_message":
                if current_profile:
                    await cortex.process_interaction(current_profile, d.get("text", ""))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
            
            # === NATE QUERY (Mobile App) ===
            elif t == "nate_query":
                if current_profile:
                    # COACH_ONLY clients cannot access Nate AI
                    if (current_profile.get("subscription_plan") or "").upper() == "COACH_ONLY" or current_profile.get("can_access_nate") == False:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "COACH_ONLY_NO_AI",
                            "detail": "Your plan is scheduling-only. AI features are not available."
                        }))
                    else:
                        text = d.get("nate_query", d.get("text", ""))
                        # #region agent log
                        _dbg_ts = datetime.datetime.now().isoformat()
                        print(f">>> [DBG-H1] nate_query received uid={uid} len={len(text)} sockets={len(cortex.sockets.get(uid, set()))} ts={_dbg_ts}")
                        # #endregion

                        # --- Conversation Export Detection ---
                        # 1) Check if this is a follow-up to a pending export
                        export_intent = export_intent_detector.check_pending(uid, text)
                        if export_intent and export_intent.get("is_export"):
                            print(f">>> [EXPORT] pending resolved for uid={uid}: type={export_intent.get('export_type')} dest={export_intent.get('destination')}")

                        # 2) If no pending match, try fresh detection
                        if not export_intent or not export_intent.get("is_export"):
                            export_intent = export_intent_detector.detect(text)
                            if export_intent and export_intent.get("is_export"):
                                print(f">>> [EXPORT] intent detected for uid={uid}: type={export_intent.get('export_type')} dest={export_intent.get('destination')}")

                        # 3) Handle the export (or fall through to normal chat)
                        if export_intent and export_intent.get("is_export"):
                            needs_type = export_intent.get("needs_clarification_type", False)
                            needs_dest = export_intent.get("needs_clarification_dest", False)

                            if needs_type:
                                # Don't know what content type — store pending, let Nate ask
                                export_intent_detector.set_pending(uid, export_intent)
                                print(f">>> [EXPORT] needs content type clarification, stored pending for uid={uid}")
                                await cortex.process_interaction(current_profile, text)
                            else:
                                # Content type is known — generate the export
                                try:
                                    export_result = await export_content_generator.generate(
                                        current_profile,
                                        export_intent["export_type"],
                                        export_intent.get("description", ""),
                                    )
                                    dest_label = {
                                        "google_drive": "Google Drive",
                                        "onedrive": "OneDrive",
                                        "local": "your device",
                                    }.get(export_intent.get("destination"), "your chosen location")
                                    type_label = {
                                        "summary": "summary",
                                        "highlights": "highlights",
                                        "full": "full transcript",
                                        "section": "excerpt",
                                    }.get(export_intent["export_type"], "export")

                                    if needs_dest:
                                        # Generated content but no destination — picker will show
                                        nate_msg = (
                                            f"I've prepared your session {type_label}! "
                                            "Where would you like me to save it — Google Drive, OneDrive, or your phone?"
                                        )
                                    else:
                                        nate_msg = (
                                            f"I've prepared your session {type_label} and it's ready to save to {dest_label}. "
                                            "You should see the save options now!"
                                        )

                                    await websocket.send(json.dumps({
                                        "type": "nate_response",
                                        "text": nate_msg,
                                    }))

                                    # Send the export_ready payload for the Flutter client
                                    await websocket.send(json.dumps({
                                        "type": "export_ready",
                                        "content": export_result["content"],
                                        "filename": export_result["filename"],
                                        "format": export_result["format"],
                                        "export_type": export_intent["export_type"],
                                        "suggested_destination": export_intent.get("destination"),
                                    }))
                                    export_intent_detector.clear_pending(uid)
                                    print(f">>> [EXPORT] export_ready sent to uid={uid} file={export_result['filename']}")
                                except Exception as ex:
                                    print(f">>> [EXPORT] generation error for uid={uid}: {ex}")
                                    await cortex.process_interaction(current_profile, text)
                        else:
                            # Normal Nate conversation
                            await cortex.process_interaction(current_profile, text)

                        # #region agent log
                        print(f">>> [DBG-H1] nate_query DONE uid={uid} sockets_after={list(cortex.sockets.get(uid, set()))} ts={datetime.datetime.now().isoformat()}")
                        # #endregion
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
            
            # === CLIENT: GET COACH AVAILABILITY ===
            elif t == "client_get_coach_availability":
                if current_profile and current_profile.get("role") == "CLIENT":
                    coach_id = (current_profile.get("assigned_coach_id") or d.get("coach_id") or "").strip()
                    target_date = (d.get("date") or "").strip()
                    if not coach_id:
                        await websocket.send(json.dumps({"type": "error", "message": "No coach assigned"}))
                    else:
                        try:
                            avail_file = VAULT_ROOT / "Coaches" / coach_id / "availability.json"
                            avail_data = load_json_file(str(avail_file), {"slots": [], "timezone": "America/New_York"})
                            
                            # If a specific date is requested, compute available slots
                            available_slots = []
                            booked_slots = []
                            if target_date:
                                from datetime import timezone as tz_module
                                sessions = load_json_file(SESSIONS_FILE, [])
                                try:
                                    target_dt = datetime.datetime.fromisoformat(target_date)
                                    day_name = target_dt.strftime("%A").lower()
                                except Exception:
                                    target_dt = None
                                    day_name = ""
                                
                                if target_dt:
                                    day_slots = [s for s in avail_data.get("slots", []) if s.get("day", "").lower() == day_name]
                                    for s in sessions:
                                        if s.get("coach_id") == coach_id and s.get("status") in ["scheduled", "active"]:
                                            try:
                                                st = datetime.datetime.fromisoformat(s.get("scheduled_start", ""))
                                                if st.date() == target_dt.date():
                                                    booked_slots.append({"start": s["scheduled_start"], "end": s["scheduled_end"]})
                                            except Exception:
                                                pass
                                    for slot in day_slots:
                                        start_h = int(slot.get("start", "09:00").split(":")[0])
                                        end_h = int(slot.get("end", "17:00").split(":")[0])
                                        for hour in range(start_h, end_h):
                                            slot_start = target_dt.replace(hour=hour, minute=0, second=0)
                                            slot_end = slot_start + datetime.timedelta(hours=1)
                                            is_free = True
                                            for b in booked_slots:
                                                try:
                                                    bs = datetime.datetime.fromisoformat(b["start"])
                                                    be = datetime.datetime.fromisoformat(b["end"])
                                                    if slot_start < be and slot_end > bs:
                                                        is_free = False
                                                        break
                                                except Exception:
                                                    pass
                                            if is_free and slot_start > datetime.datetime.now():
                                                available_slots.append({"start": slot_start.isoformat(), "end": slot_end.isoformat()})
                            
                            await websocket.send(json.dumps({
                                "type": "coach_availability",
                                "coach_id": coach_id,
                                "availability": avail_data,
                                "available_slots": available_slots,
                                "booked_slots": booked_slots,
                                "date": target_date,
                            }))
                        except Exception as e:
                            print(f">>> [ERROR] Failed to load availability: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "OPERATION_FAILED"}))

            # === CLIENT: BOOK SESSION ===
            elif t == "client_book_session":
                if current_profile and current_profile.get("role") == "CLIENT":
                    coach_id = (current_profile.get("assigned_coach_id") or d.get("coach_id") or "").strip()
                    scheduled_start = (d.get("scheduled_start") or "").strip()
                    scheduled_end = (d.get("scheduled_end") or "").strip()
                    client_id = (current_profile.get("hardware_id") or "").strip()
                    client_name = (current_profile.get("name") or "").strip()
                    family_id = (current_profile.get("family_id") or "").strip()
                    
                    if not coach_id or not scheduled_start or not scheduled_end:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing required fields"}))
                    else:
                        # Session limit check — STANDARD: 4/mo, TOP_TIER: 8/mo
                        plan = (current_profile.get("subscription_plan") or "").upper()
                        session_limits = {"STANDARD": 4, "TOP_TIER": 8}
                        plan_limit = session_limits.get(plan)
                        if plan_limit:
                            sessions_all = load_json_file(SESSIONS_FILE, [])
                            now = datetime.datetime.now()
                            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                            month_count = sum(1 for s in sessions_all
                                if s.get("client_id") == client_id 
                                and s.get("status") in ["scheduled", "active", "completed"]
                                and s.get("created_at", "") >= month_start.isoformat())
                            if month_count >= plan_limit:
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "message": "SESSION_LIMIT_REACHED",
                                    "detail": f"You have reached your {plan_limit} sessions/month limit."
                                }))
                                continue
                        
                        try:
                            sessions = load_json_file(SESSIONS_FILE, [])
                            # Conflict check
                            conflict = False
                            for s in sessions:
                                if s.get("coach_id") == coach_id and s.get("status") in ["scheduled", "active"]:
                                    try:
                                        es = datetime.datetime.fromisoformat(s.get("scheduled_start", ""))
                                        ee = datetime.datetime.fromisoformat(s.get("scheduled_end", ""))
                                        ns = datetime.datetime.fromisoformat(scheduled_start)
                                        ne = datetime.datetime.fromisoformat(scheduled_end)
                                        if ns < ee and ne > es:
                                            conflict = True
                                            break
                                    except Exception:
                                        pass
                            
                            if conflict:
                                await websocket.send(json.dumps({"type": "error", "message": "Time slot conflict"}))
                            else:
                                session_id = f"SES_{datetime.datetime.now().strftime('%Y%m%d')}_{secrets.token_hex(3).upper()}"
                                # Look up coach fee info for the notification
                                coach_profile = None
                                reg = load_registry()
                                for rk, rv in reg.items():
                                    if rv.get("profile", {}).get("hardware_id") == coach_id:
                                        coach_profile = rv.get("profile", {})
                                        break
                                coach_fee = float((coach_profile or {}).get("coaching_fee", 0))
                                fee_info = calculate_platform_fee(coach_fee) if coach_fee > 0 else {"coach_fee": 0, "platform_fee": 0, "coach_payout": 0}
                                
                                new_session = {
                                    "session_id": session_id,
                                    "client_id": client_id,
                                    "coach_id": coach_id,
                                    "family_id": family_id,
                                    "client_name": client_name,
                                    "session_type": "COACH",
                                    "status": "pending_approval",
                                    "scheduled_start": scheduled_start,
                                    "scheduled_end": scheduled_end,
                                    "actual_start": None,
                                    "actual_end": None,
                                    "duration_minutes": 0,
                                    "zoom_link": "",
                                    "zoom_meeting_id": "",
                                    "zoom_host_url": "",
                                    "notes": d.get("notes", ""),
                                    "coach_notes": "",
                                    "topics_covered": [],
                                    "homework_assigned": [],
                                    "mood_at_start": "",
                                    "mood_at_end": "",
                                    "nate_summary": "",
                                    "recording_url": "",
                                    "created_at": str(datetime.datetime.now()),
                                    "booked_by": "CLIENT",
                                    "coach_fee": fee_info["coach_fee"],
                                    "platform_fee": fee_info["platform_fee"],
                                    "coach_payout": fee_info["coach_payout"],
                                }
                                
                                # Auto-create Zoom meeting if enabled
                                try:
                                    if ENABLE_ZOOM:
                                        from app.services.zoom_client import ZoomClient
                                        zoom = ZoomClient()
                                        dur_min = 50
                                        try:
                                            st = datetime.datetime.fromisoformat(scheduled_start)
                                            en = datetime.datetime.fromisoformat(scheduled_end)
                                            if en > st:
                                                dur_min = max(5, int((en - st).total_seconds() / 60))
                                        except Exception:
                                            pass
                                        meeting = await zoom.create_meeting(
                                            topic=f"Session: {client_name}",
                                            start_time=scheduled_start,
                                            duration_minutes=dur_min,
                                        )
                                        if meeting:
                                            new_session["zoom_link"] = meeting.get("join_url", "")
                                            new_session["zoom_meeting_id"] = str(meeting.get("id", ""))
                                            new_session["zoom_host_url"] = meeting.get("start_url", "")
                                except Exception as ze:
                                    print(f">>> [ZOOM] Auto-create failed for client booking: {ze}")
                                
                                sessions.append(new_session)
                                save_json_file(SESSIONS_FILE, sessions)
                                
                                await websocket.send(json.dumps({
                                    "type": "session_booked",
                                    "session": new_session,
                                }))
                                
                                # Notify coach of pending booking
                                coach_ws = connected_coaches.get(coach_id)
                                if coach_ws:
                                    try:
                                        await coach_ws.send(json.dumps({
                                            "type": "pending_booking_notification",
                                            "session": new_session,
                                            "message": f"{client_name} requests a session on {scheduled_start} — awaiting your approval",
                                            "fee_breakdown": fee_info,
                                        }))
                                    except Exception:
                                        pass
                        except Exception as e:
                            print(f">>> [ERROR] Booking failed: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "BOOKING_FAILED"}))

            # === CLIENT: CANCEL SESSION ===
            elif t == "client_cancel_session":
                if current_profile and current_profile.get("role") == "CLIENT":
                    session_id = (d.get("session_id") or "").strip()
                    client_id = (current_profile.get("hardware_id") or "").strip()
                    if not session_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    else:
                        try:
                            sessions = load_json_file(SESSIONS_FILE, [])
                            found = False
                            for s in sessions:
                                if s.get("session_id") == session_id and s.get("client_id") == client_id:
                                    s["status"] = "cancelled"
                                    s["cancelled_at"] = str(datetime.datetime.now())
                                    s["cancelled_by"] = "CLIENT"
                                    found = True
                                    break
                            if found:
                                save_json_file(SESSIONS_FILE, sessions)
                                await websocket.send(json.dumps({"type": "session_cancelled", "session_id": session_id}))
                            else:
                                await websocket.send(json.dumps({"type": "error", "message": "Session not found"}))
                        except Exception as e:
                            print(f">>> [ERROR] Cancel failed: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "CANCEL_FAILED"}))

            # === CLIENT: GET UPCOMING SESSIONS ===
            elif t == "client_get_upcoming_sessions":
                if current_profile and current_profile.get("role") == "CLIENT":
                    client_id = (current_profile.get("hardware_id") or "").strip()
                    try:
                        sessions = load_json_file(SESSIONS_FILE, [])
                        upcoming = []
                        for s in sessions:
                            if s.get("client_id") == client_id and s.get("status") in ["scheduled", "active"]:
                                upcoming.append({
                                    "session_id": s.get("session_id"),
                                    "coach_id": s.get("coach_id"),
                                    "scheduled_start": s.get("scheduled_start"),
                                    "scheduled_end": s.get("scheduled_end"),
                                    "status": s.get("status"),
                                    "zoom_link": s.get("zoom_link", ""),
                                    "session_type": s.get("session_type", "COACH"),
                                    "client_name": s.get("client_name", ""),
                                    "notes": s.get("notes", ""),
                                })
                        upcoming.sort(key=lambda x: x.get("scheduled_start", ""))
                        await websocket.send(json.dumps({
                            "type": "client_upcoming_sessions",
                            "sessions": upcoming,
                        }))
                    except Exception as e:
                        print(f">>> [ERROR] Booking operation failed: {e}")
                        await websocket.send(json.dumps({"type": "error", "message": "OPERATION_FAILED"}))

            # === COACH: APPROVE BOOKING ===
            elif t == "coach_approve_booking":
                if current_profile and current_profile.get("role") == "COACH":
                    session_id = (d.get("session_id") or "").strip()
                    coach_id = (current_profile.get("hardware_id") or "").strip()
                    if not session_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    else:
                        try:
                            sessions = load_json_file(SESSIONS_FILE, [])
                            found_session = None
                            for s in sessions:
                                if s.get("session_id") == session_id and s.get("coach_id") == coach_id and s.get("status") == "pending_approval":
                                    s["status"] = "scheduled"
                                    s["approved_at"] = str(datetime.datetime.now())
                                    found_session = s
                                    break
                            if found_session:
                                save_json_file(SESSIONS_FILE, sessions)
                                
                                # Record financial transaction on coach ledger
                                coach_fee = float(found_session.get("coach_fee", 0))
                                platform_fee = float(found_session.get("platform_fee", 0))
                                coach_payout = float(found_session.get("coach_payout", 0))
                                
                                registry = load_registry()
                                for rk, rv in registry.items():
                                    p = rv.get("profile", {})
                                    if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                        txn = {
                                            "txn_id": f"TXN_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3).upper()}",
                                            "date": str(datetime.datetime.now().date()),
                                            "type": "session_fee",
                                            "session_id": session_id,
                                            "client_name": found_session.get("client_name", ""),
                                            "coach_fee": coach_fee,
                                            "platform_fee": platform_fee,
                                            "coach_payout": coach_payout,
                                            "status": "recorded",
                                        }
                                        if "financial_ledger" not in p:
                                            p["financial_ledger"] = []
                                        p["financial_ledger"].append(txn)
                                        p["total_earnings_ytd"] = round(p.get("total_earnings_ytd", 0) + coach_fee, 2)
                                        p["total_platform_fees_ytd"] = round(p.get("total_platform_fees_ytd", 0) + platform_fee, 2)
                                        p["total_sessions_billable"] = p.get("total_sessions_billable", 0) + 1
                                        if p["total_earnings_ytd"] >= 600:
                                            p["requires_1099"] = True
                                        break
                                save_registry(registry)
                                
                                # Auto-create Zoom meeting on approval
                                try:
                                    if ENABLE_ZOOM:
                                        from app.services.zoom_client import ZoomClient
                                        zoom = ZoomClient()
                                        dur_min = 50
                                        try:
                                            st = datetime.datetime.fromisoformat(found_session.get("scheduled_start", ""))
                                            en = datetime.datetime.fromisoformat(found_session.get("scheduled_end", ""))
                                            if en > st:
                                                dur_min = max(5, int((en - st).total_seconds() / 60))
                                        except Exception:
                                            pass
                                        meeting = await zoom.create_meeting(
                                            topic=f"Session: {found_session.get('client_name', '')}",
                                            start_time=found_session.get("scheduled_start", ""),
                                            duration_minutes=dur_min,
                                        )
                                        if meeting:
                                            found_session["zoom_link"] = meeting.get("join_url", "")
                                            found_session["zoom_meeting_id"] = str(meeting.get("id", ""))
                                            found_session["zoom_host_url"] = meeting.get("start_url", "")
                                            save_json_file(SESSIONS_FILE, sessions)
                                except Exception as ze:
                                    print(f">>> [ZOOM] Auto-create on approve failed: {ze}")
                                
                                await websocket.send(json.dumps({
                                    "type": "booking_approved",
                                    "session": found_session,
                                }))
                                
                                # Notify client
                                client_id = found_session.get("client_id", "")
                                client_ws = connected_clients.get(client_id)
                                if client_ws:
                                    try:
                                        await client_ws.send(json.dumps({
                                            "type": "booking_status_update",
                                            "session": found_session,
                                            "message": "Your session has been approved by the coach!",
                                        }))
                                    except Exception:
                                        pass
                            else:
                                await websocket.send(json.dumps({"type": "error", "message": "Pending session not found"}))
                        except Exception as e:
                            print(f">>> [ERROR] Approve failed: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "APPROVE_FAILED"}))

            # === COACH: DECLINE BOOKING ===
            elif t == "coach_decline_booking":
                if current_profile and current_profile.get("role") == "COACH":
                    session_id = (d.get("session_id") or "").strip()
                    coach_id = (current_profile.get("hardware_id") or "").strip()
                    reason = (d.get("reason") or "").strip()
                    if not session_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    else:
                        try:
                            sessions = load_json_file(SESSIONS_FILE, [])
                            found_session = None
                            for s in sessions:
                                if s.get("session_id") == session_id and s.get("coach_id") == coach_id and s.get("status") == "pending_approval":
                                    s["status"] = "declined"
                                    s["declined_at"] = str(datetime.datetime.now())
                                    s["decline_reason"] = reason
                                    found_session = s
                                    break
                            if found_session:
                                save_json_file(SESSIONS_FILE, sessions)
                                await websocket.send(json.dumps({
                                    "type": "booking_declined",
                                    "session_id": session_id,
                                }))
                                # Notify client
                                client_id = found_session.get("client_id", "")
                                client_ws = connected_clients.get(client_id)
                                if client_ws:
                                    try:
                                        await client_ws.send(json.dumps({
                                            "type": "booking_status_update",
                                            "session": found_session,
                                            "message": f"Your session was declined.{(' Reason: ' + reason) if reason else ''}",
                                        }))
                                    except Exception:
                                        pass
                            else:
                                await websocket.send(json.dumps({"type": "error", "message": "Pending session not found"}))
                        except Exception as e:
                            print(f">>> [ERROR] Decline failed: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "DECLINE_FAILED"}))

            # === COACH: GET PENDING BOOKINGS ===
            elif t == "coach_get_pending_bookings":
                if current_profile and current_profile.get("role") == "COACH":
                    coach_id = (current_profile.get("hardware_id") or "").strip()
                    try:
                        sessions = load_json_file(SESSIONS_FILE, [])
                        pending = [s for s in sessions if s.get("coach_id") == coach_id and s.get("status") == "pending_approval"]
                        pending.sort(key=lambda x: x.get("scheduled_start", ""))
                        await websocket.send(json.dumps({
                            "type": "coach_pending_bookings",
                            "sessions": pending,
                        }))
                    except Exception as e:
                        print(f">>> [ERROR] Pending bookings fetch failed: {e}")
                        await websocket.send(json.dumps({"type": "error", "message": "OPERATION_FAILED"}))

            # === COACH: SET FEE ===
            elif t == "coach_set_fee":
                if current_profile and current_profile.get("role") == "COACH":
                    new_fee = d.get("coaching_fee")
                    try:
                        new_fee = float(new_fee)
                    except (TypeError, ValueError):
                        await websocket.send(json.dumps({"type": "error", "message": "Invalid fee amount"}))
                        continue
                    if new_fee < 0:
                        await websocket.send(json.dumps({"type": "error", "message": "Fee cannot be negative"}))
                    else:
                        coach_id = current_profile.get("hardware_id", "")
                        registry = load_registry()
                        for rk, rv in registry.items():
                            p = rv.get("profile", {})
                            if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                p["coaching_fee"] = round(new_fee, 2)
                                break
                        save_registry(registry)
                        current_profile["coaching_fee"] = round(new_fee, 2)
                        await websocket.send(json.dumps({
                            "type": "coach_fee_updated",
                            "coaching_fee": round(new_fee, 2),
                        }))

            # === COACH: SET PAYMENT MODE ===
            elif t == "coach_set_payment_mode":
                if current_profile and current_profile.get("role") == "COACH":
                    mode = (d.get("payment_mode") or "").strip()
                    if mode not in ("coach_handles", "platform_handles"):
                        await websocket.send(json.dumps({"type": "error", "message": "Invalid payment mode"}))
                    else:
                        coach_id = current_profile.get("hardware_id", "")
                        registry = load_registry()
                        for rk, rv in registry.items():
                            p = rv.get("profile", {})
                            if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                p["payment_mode"] = mode
                                break
                        save_registry(registry)
                        current_profile["payment_mode"] = mode
                        await websocket.send(json.dumps({
                            "type": "coach_payment_mode_updated",
                            "payment_mode": mode,
                        }))

            # === COACH: GET DOJO SUBSCRIPTIONS ===
            elif t == "get_dojo_subscriptions":
                if current_profile and current_profile.get("role") == "COACH":
                    coach_id = current_profile.get("hardware_id", "")
                    registry = load_registry()
                    coach_data = {}
                    for rk, rv in registry.items():
                        p = rv.get("profile", {})
                        if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                            coach_data = p
                            break
                    
                    subs = coach_data.get("dojo_subscriptions", {})
                    active_dojos = get_active_dojos(coach_data)
                    
                    await websocket.send(json.dumps({
                        "type": "dojo_subscriptions_data",
                        "dojo_subscriptions": subs,
                        "active_dojos": active_dojos,
                        "dojo_discount_pct": coach_data.get("dojo_discount_pct", 0),
                        "dojo_monthly_price": coach_data.get("dojo_monthly_price", 0),
                    }))

            # === COACH: CANCEL DOJO SUBSCRIPTION ===
            elif t == "cancel_dojo_subscription":
                if current_profile and current_profile.get("role") == "COACH":
                    dojo_key = d.get("dojo_key", "").strip()
                    coach_id = current_profile.get("hardware_id", "")
                    
                    if not dojo_key:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing dojo_key"}))
                    else:
                        registry = load_registry()
                        updated = False
                        for rk, rv in registry.items():
                            p = rv.get("profile", {})
                            if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                subs = p.get("dojo_subscriptions", {})
                                if dojo_key not in subs:
                                    await websocket.send(json.dumps({"type": "error", "message": f"No subscription for {dojo_key}"}))
                                    break
                                sub = subs[dojo_key]
                                if sub.get("status") != "active":
                                    await websocket.send(json.dumps({"type": "error", "message": f"{dojo_key} is already {sub.get('status')}"}))
                                    break
                                
                                # Set cancellation: 30-day notice
                                today = datetime.datetime.now().date()
                                cancel_date = str(today)
                                access_end = str(today + datetime.timedelta(days=30))
                                sub["cancellation_requested"] = cancel_date
                                sub["access_end_date"] = access_end
                                sub["status"] = "cancelled"
                                
                                # Recalculate discount for remaining active dojos
                                active_count = sum(1 for s in subs.values() if s.get("status") == "active")
                                new_discount = DOJO_DISCOUNTS[min(active_count, 6)]
                                for s in subs.values():
                                    if s.get("status") == "active":
                                        s["discount_pct"] = new_discount
                                p["dojo_discount_pct"] = new_discount
                                
                                # Recalculate monthly price
                                total = sum(DOJO_PRICES.get(k, 0) for k, s in subs.items() if s.get("status") == "active")
                                p["dojo_monthly_price"] = round(total * (1 - new_discount / 100), 2)
                                
                                # Update selected_dojos to reflect active + cancelled-with-access
                                p["selected_dojos"] = get_active_dojos(p)
                                
                                updated = True
                                break
                        
                        if updated:
                            save_registry(registry)
                            current_profile.update(p)
                            print(f">>> [SUBSCRIPTION] {coach_id} cancelled {dojo_key}, access until {access_end}")
                            await websocket.send(json.dumps({
                                "type": "dojo_subscription_cancelled",
                                "dojo_key": dojo_key,
                                "access_end_date": access_end,
                                "dojo_subscriptions": p.get("dojo_subscriptions", {}),
                                "active_dojos": p.get("selected_dojos", []),
                                "dojo_discount_pct": p.get("dojo_discount_pct", 0),
                                "dojo_monthly_price": p.get("dojo_monthly_price", 0),
                            }))

            # === COACH: ADD DOJO SUBSCRIPTION ===
            elif t == "add_dojo_subscription":
                if current_profile and current_profile.get("role") == "COACH":
                    dojo_key = d.get("dojo_key", "").strip()
                    coach_id = current_profile.get("hardware_id", "")
                    
                    if not dojo_key or dojo_key not in DOJO_PRICES:
                        await websocket.send(json.dumps({"type": "error", "message": f"Invalid dojo_key: {dojo_key}"}))
                    else:
                        registry = load_registry()
                        updated = False
                        for rk, rv in registry.items():
                            p = rv.get("profile", {})
                            if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                subs = p.get("dojo_subscriptions", {})
                                
                                # Check if already subscribed (active)
                                if dojo_key in subs and subs[dojo_key].get("status") == "active":
                                    await websocket.send(json.dumps({"type": "error", "message": f"Already subscribed to {dojo_key}"}))
                                    break
                                
                                # Create new 12-month subscription
                                today = str(datetime.datetime.now().date())
                                term_end = str((datetime.datetime.now() + datetime.timedelta(days=365)).date())
                                
                                # Calculate new discount with this dojo included
                                active_count = sum(1 for s in subs.values() if s.get("status") == "active") + 1
                                new_discount = DOJO_DISCOUNTS[min(active_count, 6)]
                                
                                subs[dojo_key] = {
                                    "status": "active",
                                    "start_date": today,
                                    "term_end_date": term_end,
                                    "cancellation_requested": None,
                                    "access_end_date": None,
                                    "monthly_rate": DOJO_PRICES[dojo_key],
                                    "discount_pct": new_discount,
                                }
                                
                                # Update discount for ALL active subscriptions
                                for s in subs.values():
                                    if s.get("status") == "active":
                                        s["discount_pct"] = new_discount
                                p["dojo_discount_pct"] = new_discount
                                
                                # Recalculate monthly price
                                total = sum(DOJO_PRICES.get(k, 0) for k, s in subs.items() if s.get("status") == "active")
                                p["dojo_monthly_price"] = round(total * (1 - new_discount / 100), 2)
                                
                                # Update selected_dojos
                                p["dojo_subscriptions"] = subs
                                p["selected_dojos"] = get_active_dojos(p)
                                
                                updated = True
                                break
                        
                        if updated:
                            save_registry(registry)
                            current_profile.update(p)
                            print(f">>> [SUBSCRIPTION] {coach_id} added {dojo_key}, discount now {new_discount}%")
                            await websocket.send(json.dumps({
                                "type": "dojo_subscription_added",
                                "dojo_key": dojo_key,
                                "dojo_subscriptions": p.get("dojo_subscriptions", {}),
                                "active_dojos": p.get("selected_dojos", []),
                                "dojo_discount_pct": p.get("dojo_discount_pct", 0),
                                "dojo_monthly_price": p.get("dojo_monthly_price", 0),
                            }))

            # === COACH: GET FINANCIALS ===
            elif t == "coach_get_financials":
                if current_profile and current_profile.get("role") == "COACH":
                    coach_id = current_profile.get("hardware_id", "")
                    registry = load_registry()
                    coach_data = {}
                    for rk, rv in registry.items():
                        p = rv.get("profile", {})
                        if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                            coach_data = p
                            break
                    
                    # Calculate monthly totals
                    now = datetime.datetime.now()
                    month_start = now.replace(day=1).strftime("%Y-%m-%d")
                    ledger = coach_data.get("financial_ledger", [])
                    monthly_earnings = sum(t.get("coach_fee", 0) for t in ledger if t.get("date", "") >= month_start)
                    monthly_fees = sum(t.get("platform_fee", 0) for t in ledger if t.get("date", "") >= month_start)
                    monthly_payout = sum(t.get("coach_payout", 0) for t in ledger if t.get("date", "") >= month_start)
                    monthly_sessions = sum(1 for t in ledger if t.get("date", "") >= month_start and t.get("type") == "session_fee")
                    
                    await websocket.send(json.dumps({
                        "type": "coach_financials",
                        "coaching_fee": coach_data.get("coaching_fee", 0),
                        "payment_mode": coach_data.get("payment_mode", "coach_handles"),
                        "total_earnings_ytd": coach_data.get("total_earnings_ytd", 0),
                        "total_platform_fees_ytd": coach_data.get("total_platform_fees_ytd", 0),
                        "total_sessions_billable": coach_data.get("total_sessions_billable", 0),
                        "monthly_earnings": round(monthly_earnings, 2),
                        "monthly_fees": round(monthly_fees, 2),
                        "monthly_payout": round(monthly_payout, 2),
                        "monthly_sessions": monthly_sessions,
                        "w9_submitted": coach_data.get("w9_submitted", False),
                        "requires_1099": coach_data.get("requires_1099", False),
                        "ledger": ledger[-50:],  # Last 50 transactions
                    }))

            # === COACH: FETCH CLIENT OBSERVATION REPORTS ===
            elif t == "fetch_reports":
                if current_profile and current_profile.get("role") == "COACH":
                    coach_id = current_profile.get("hardware_id", "")
                    registry = load_registry()
                    reports = []
                    # Gather reports for all clients assigned to this coach
                    for rk, rv in registry.items():
                        p = rv.get("profile", {})
                        if p.get("assigned_coach") == coach_id and p.get("role") == "CLIENT":
                            client_name = p.get("name") or p.get("display_name") or rk
                            client_id = p.get("hardware_id", rk)
                            # Get session data for report
                            sessions = rv.get("sessions", [])
                            session_count = len(sessions)
                            last_session = sessions[-1] if sessions else {}
                            # Get coherence data
                            c_emo = p.get("c_emo_current", 0)
                            c_emo_trend = p.get("c_emo_trend", "stable")
                            reports.append({
                                "client_id": client_id,
                                "client_name": client_name,
                                "total_sessions": session_count,
                                "last_session_date": last_session.get("date", "N/A"),
                                "c_emo_current": round(c_emo, 4) if isinstance(c_emo, (int, float)) else 0,
                                "c_emo_trend": c_emo_trend,
                                "subscription_plan": p.get("subscription_plan", "TRIAL"),
                                "risk_level": p.get("risk_level", "normal"),
                                "notes_count": len(rv.get("coach_notes", [])),
                            })
                    await websocket.send(json.dumps({
                        "type": "reports_data",
                        "reports": reports,
                        "coach_id": coach_id,
                        "generated_at": str(datetime.datetime.now()),
                    }))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Reports are available to coaches only"}))

            # === COACH: SUBMIT W-9 ===
            elif t == "coach_submit_w9":
                if current_profile and current_profile.get("role") == "COACH":
                    w9_data = d.get("w9_data", {})
                    required = ["legal_name", "address_street", "address_city", "address_state", "address_zip", "tin", "tax_classification", "certification"]
                    missing = [f for f in required if not w9_data.get(f)]
                    if missing:
                        await websocket.send(json.dumps({"type": "error", "message": f"Missing W-9 fields: {', '.join(missing)}"}))
                    elif not w9_data.get("certification"):
                        await websocket.send(json.dumps({"type": "error", "message": "You must certify the W-9 form"}))
                    else:
                        coach_id = current_profile.get("hardware_id", "")
                        registry = load_registry()
                        for rk, rv in registry.items():
                            p = rv.get("profile", {})
                            if p.get("hardware_id") == coach_id and p.get("role") == "COACH":
                                p["w9_submitted"] = True
                                p["w9_data"] = w9_data
                                p["w9_submitted_at"] = str(datetime.datetime.now())
                                break
                        save_registry(registry)
                        current_profile["w9_submitted"] = True
                        await websocket.send(json.dumps({
                            "type": "w9_submitted",
                            "message": "W-9 form submitted successfully",
                        }))

            # === ADMIN: GET FINANCIAL SUMMARY ===
            elif t == "admin_get_financial_summary":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    coaches_summary = []
                    total_platform_fees = 0.0
                    total_earnings = 0.0
                    coaches_near_1099 = []
                    now = datetime.datetime.now()
                    month_start = now.replace(day=1).strftime("%Y-%m-%d")
                    
                    for rk, rv in registry.items():
                        p = rv.get("profile", {})
                        if p.get("role") == "COACH":
                            ledger = p.get("financial_ledger", [])
                            monthly_fees = sum(t.get("platform_fee", 0) for t in ledger if t.get("date", "") >= month_start)
                            ytd_earnings = p.get("total_earnings_ytd", 0)
                            ytd_fees = p.get("total_platform_fees_ytd", 0)
                            total_platform_fees += ytd_fees
                            total_earnings += ytd_earnings
                            
                            coach_info = {
                                "name": p.get("name", ""),
                                "hardware_id": p.get("hardware_id", ""),
                                "coaching_fee": p.get("coaching_fee", 0),
                                "total_sessions": p.get("total_sessions_billable", 0),
                                "ytd_earnings": ytd_earnings,
                                "ytd_platform_fees": ytd_fees,
                                "monthly_platform_fees": round(monthly_fees, 2),
                                "payment_mode": p.get("payment_mode", "coach_handles"),
                                "w9_submitted": p.get("w9_submitted", False),
                                "requires_1099": p.get("requires_1099", False),
                            }
                            coaches_summary.append(coach_info)
                            if ytd_earnings >= 500 and ytd_earnings < 600:
                                coaches_near_1099.append(coach_info)
                    
                    await websocket.send(json.dumps({
                        "type": "admin_financial_summary",
                        "total_platform_fees_ytd": round(total_platform_fees, 2),
                        "total_gross_earnings_ytd": round(total_earnings, 2),
                        "coaches": coaches_summary,
                        "coaches_near_1099_threshold": coaches_near_1099,
                        "month": now.strftime("%B %Y"),
                    }))

            # === VAULT FILE UPLOAD (B5 — Chat-integrated file interactions) ===
            # User identity and tier come from authenticated session only — never from payload
            elif t == "file_upload_request":
                if current_profile:
                    try:
                        from .bridge_handlers_v2 import handle_file_upload_request
                        await handle_file_upload_request(websocket, d, bridge_context, current_profile)
                    except Exception as v_err:
                        print(f">>> [VAULT] file_upload_request error: {v_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(v_err)}))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))

            elif t == "vault_preview_request":
                if current_profile:
                    try:
                        from .bridge_handlers_v2 import handle_vault_preview_request
                        await handle_vault_preview_request(websocket, d, bridge_context, current_profile)
                    except Exception as v_err:
                        print(f">>> [VAULT] vault_preview_request error: {v_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(v_err)}))
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))

            # === NATE ORGANIZER (Sovereign Circle — Accessibility) ===
            # Voice-first AI-guided document organization for users with disabilities
            elif t == "organize_start":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                elif (current_profile.get("subscription_plan", "").upper() not in
                      ("SOVEREIGN_CIRCLE", "TOP_TIER", "TOP")):
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Nate Organizer requires Sovereign Circle membership"
                    }))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        vault_item_id = d.get("vault_item_id")
                        content = d.get("content", "")

                        # If vault_item_id provided, load content from vault
                        if vault_item_id and not content and db_pool:
                            from app.services.vault.vault_operations import VaultOperations
                            _vops = VaultOperations(db_pool)
                            item = await _vops.get_item(current_profile.get("hardware_id", ""), vault_item_id)
                            if item:
                                content = item.get("extracted_text_preview") or ""

                        if not content.strip():
                            await websocket.send(json.dumps({
                                "type": "error", "message": "No content to organize"
                            }))
                        else:
                            result = await _org_mode.start_session(
                                member_id=current_profile.get("hardware_id", ""),
                                content=content,
                                vault_item_id=vault_item_id,
                            )
                            await websocket.send(json.dumps({
                                "type": "organize_started", **result
                            }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_start error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_message":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        text = d.get("text", "").strip()
                        if not session_id or not text:
                            await websocket.send(json.dumps({"type": "error", "message": "Missing session_id or text"}))
                        else:
                            result = await _org_mode.process_message(session_id, text)
                            await websocket.send(json.dumps({
                                **result, "type": "organize_response"
                            }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_message error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_confirm":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        result = await _org_mode.confirm_proposal(session_id)
                        await websocket.send(json.dumps({
                            **result, "type": "organize_response"
                        }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_confirm error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_reject":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        result = await _org_mode.reject_proposal(session_id)
                        await websocket.send(json.dumps({
                            **result, "type": "organize_response"
                        }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_reject error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_undo":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        session = _org_mode.session_mgr.get_session(session_id)
                        if not session:
                            await websocket.send(json.dumps({"type": "error", "message": "Session not found"}))
                        else:
                            sections, desc = await _org_mode.session_mgr.undo(session)
                            result = {
                                "type": "organize_response",
                                "nate_message": desc if sections is None else f"{desc}. Here's where we are now.",
                                "sections": sections or session.sections_snapshot(),
                                "progress": session.get_progress(),
                            }
                            await websocket.send(json.dumps(result))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_undo error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_save":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        save_mode = d.get("save_mode", "overwrite")
                        result = await _org_mode.save_session(
                            session_id, current_profile.get("hardware_id", ""), save_mode
                        )
                        await websocket.send(json.dumps({
                            "type": "organize_saved", **result
                        }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_save error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            elif t == "organize_resume":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Login required"}))
                else:
                    try:
                        _org_mode = _get_or_create_organizer(db_pool)
                        session_id = d.get("session_id", "")
                        result = await _org_mode.resume_session(
                            session_id, current_profile.get("hardware_id", "")
                        )
                        if result:
                            await websocket.send(json.dumps({
                                "type": "organize_resumed", **result
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error", "message": "Session not found or cannot be resumed"
                            }))
                    except Exception as org_err:
                        print(f">>> [ORGANIZER] organize_resume error: {org_err}")
                        await websocket.send(json.dumps({"type": "error", "message": str(org_err)}))

            # === GET METRICS ===
            elif t == "get_metrics":
                if current_profile:
                    summary = parietal.get_metrics_summary(current_profile)
                    # Include mood_history for chart UIs (some clients rely on metrics_data snapshot)
                    try:
                        full_metrics = parietal.load_metrics(current_profile) or {}
                        ns = full_metrics.get("nevedal_state", {}) if isinstance(full_metrics, dict) else {}
                        mh = ns.get("mood_history", []) if isinstance(ns, dict) else []
                        mh = mh[-30:] if isinstance(mh, list) else []
                    except Exception:
                        mh = []
                    await websocket.send(json.dumps({"type": "metrics_data", "metrics": summary, "mood_history": mh}))
                    # Also send raw numeric metrics + mood history for real-time UIs
                    try:
                        await cortex._send_metrics_update(uid, current_profile)
                    except Exception as e:
                        print(f">>> [METRICS PUSH ERROR] {e}")
            
            # === GET MEMORY/HISTORY ===
            elif t == "get_history":
                if current_profile:
                    memories = hippocampus.recall_full(current_profile, limit=d.get("limit", 20))
                    await websocket.send(json.dumps({"type": "history_data", "history": memories}))
            
            # === GET SESSIONS ===
            elif t == "get_sessions":
                if current_profile:
                    sessions = session_tracker.get_client_sessions(uid, limit=d.get("limit", 10))
                    await websocket.send(json.dumps({"type": "sessions_data", "sessions": sessions}))
            
            # === GET BILLING INFO ===
            elif t == "get_billing":
                if current_profile:
                    usage = billing_system_internal.get_usage_stats(uid)
                    subscription = billing_system_internal.get_subscription(uid)
                    await websocket.send(json.dumps({
                        "type": "billing_data", 
                        "usage": usage, 
                        "subscription": subscription
                    }))
            
            # === ADMIN: GET DASHBOARD STATS ===
            elif t == "admin_get_stats":
                if current_profile and current_profile.get("role") == "ADMIN":
                    stats = analytics_engine.get_dashboard_stats()
                    watchlist = analytics_engine.get_crisis_watchlist()
                    await websocket.send(json.dumps({
                        "type": "admin_stats",
                        "stats": stats,
                        "crisis_watchlist": watchlist,
                        "online_coach_ids": list(connected_coaches.keys()),
                        "online_client_ids": list(connected_clients.keys()),
                    }))
            
            # === ADMIN: GET ALL USERS ===
            elif t == "admin_get_users":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    users = []
                    # Build set of online user IDs for status indicators
                    online_coach_ids = set(connected_coaches.keys())
                    online_client_ids = set(connected_clients.keys())
                    online_ids = online_coach_ids | online_client_ids

                    for k, v in registry.items():
                        p = v.get("profile", {})
                        hid = p.get("hardware_id") or ""
                        cred_username = (v.get("credentials", {}).get("username") or k)
                        # Match coach_get_clients priority: subscription_plan first, then tier
                        effective_plan = p.get("subscription_plan") or p.get("tier") or "TRIAL"
                        users.append({
                            "id": hid,
                            "name": p.get("name"),
                            "username": k,
                            "credentials_username": cred_username,
                            "email": p.get("email"),
                            "role": p.get("role"),
                            "tier": p.get("tier"),
                            "plan": effective_plan,
                            "subscription_plan": p.get("subscription_plan") or effective_plan,
                            "subscription_status": p.get("subscription_status"),
                            "coach_verified": p.get("coach_verified", False),
                            "assigned_coach_id": p.get("assigned_coach_id") or p.get("assigned_coach") or "",
                            "family_id": p.get("family_id") or "",
                            "family_role": p.get("family_role") or "",
                            "guardian_id": p.get("guardian_id") or "",
                            "merged_from_family": p.get("merged_from_family") or "",
                            "merged_at": p.get("merged_at") or "",
                            "separated_from_family": p.get("separated_from_family") or "",
                            "separated_at": p.get("separated_at") or "",
                            "hardware_id": hid,
                            "joined_date": p.get("joined_date"),
                            "last_login": p.get("last_login"),
                            "online": hid in online_ids,
                        })
                    await websocket.send(json.dumps({"type": "admin_users", "users": users}))
            
            # === ADMIN: GET FAMILIES ===
            elif t == "admin_get_families":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    families = {}
                    for k, v in registry.items():
                        p = v.get("profile", {})
                        fid = p.get("family_id")
                        if fid:
                            if fid not in families:
                                families[fid] = {"family_id": fid, "members": [], "session_count": 0, "wellness_index": None}
                            families[fid]["members"].append({
                                "id": p.get("hardware_id", ""),
                                "name": p.get("name", k),
                                "role": p.get("role", "CLIENT"),
                            })
                    await websocket.send(json.dumps({"type": "families_list", "families": list(families.values())}))
            
            # === ADMIN: GET CLIENT METRICS (Patent 2: crisis, shame, PMB) ===
            elif t == "admin_get_client_metrics":
                if current_profile and current_profile.get("role") == "ADMIN":
                    client_id = d.get("client_id") or d.get("user_id")
                    if client_id:
                        try:
                            cm = metrics_engine.load_metrics({"role": "CLIENT", "hardware_id": client_id})
                            await websocket.send(json.dumps({
                                "type": "client_metrics",
                                "client_id": client_id,
                                "crisis_perception": cm.get("crisis_perception", {}),
                                "shame_profile": cm.get("shame_profile", {}),
                                "pmb": cm.get("pmb", {}),
                            }))
                        except Exception:
                            await websocket.send(json.dumps({"type": "client_metrics", "client_id": client_id, "crisis_perception": {}, "shame_profile": {}, "pmb": {}}))
            
            # === ADMIN: GET PENDING COACHES ===
            elif t == "admin_get_pending_coaches":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    pending = []
                    for k, v in registry.items():
                        p = v.get("profile", {}) if isinstance(v, dict) else {}
                        if p.get("role") == "COACH" and p.get("subscription_status") == "PENDING_VERIFICATION":
                            # Mask SSN/EIN for admin display (show last 4 only)
                            w9 = p.get("w9_data", {})
                            masked_w9 = dict(w9) if w9 else {}
                            if masked_w9.get("tin"):
                                tin_digits = masked_w9["tin"].replace("-", "").replace(" ", "")
                                if len(tin_digits) >= 4:
                                    masked_w9["tin_masked"] = f"***-**-{tin_digits[-4:]}"
                                else:
                                    masked_w9["tin_masked"] = "***"
                                del masked_w9["tin"]  # Never send full TIN to admin UI
                            pending.append({
                                "hardware_id": p.get("hardware_id", ""),
                                "name": p.get("name", "Unknown"),
                                "email": p.get("email", ""),
                                "phone": p.get("phone", ""),
                                "dob": p.get("dob", ""),
                                "joined_date": p.get("joined_date", ""),
                                "specializations": p.get("specializations", []),
                                "certification_status": p.get("certification_status", "PENDING"),
                                "selected_dojos": p.get("selected_dojos", []),
                                "dojo_subscriptions": p.get("dojo_subscriptions", {}),
                                "dojo_monthly_price": p.get("dojo_monthly_price", 0),
                                "dojo_discount_pct": p.get("dojo_discount_pct", 0),
                                "w9_submitted": p.get("w9_submitted", False),
                                "w9_data": masked_w9,
                                "coaching_fee": p.get("coaching_fee", 0),
                                "registration_date": p.get("created_at", ""),
                                # Verification status fields
                                "address_verified": p.get("address_verified", False),
                                "standardized_address": p.get("standardized_address", {}),
                                "tin_doc_uploaded": p.get("tin_doc_uploaded", False),
                                "tin_doc_path": p.get("tin_doc_path", ""),
                                "tin_match_status": p.get("tin_match_status", "not_submitted"),
                                "tin_verification_method": p.get("tin_verification_method", "none"),
                            })
                    await websocket.send(json.dumps({
                        "type": "pending_coaches",
                        "coaches": pending
                    }))
                    print(f"[Admin] Sent {len(pending)} pending coaches")

            # === ADMIN: GET REVENUE ===
            elif t == "admin_get_revenue":
                if current_profile and current_profile.get("role") == "ADMIN":
                    try:
                        billing_data = {}
                        billing_path = DATA_DIR / "stripe_billing.json"
                        if billing_path.exists():
                            with open(billing_path, "r") as f:
                                billing_data = json.load(f)

                        subs = billing_data.get("subscriptions", {})
                        customers = billing_data.get("customers", {})

                        # Count active subscriptions by tier
                        tier_counts = {}
                        total_mrr = 0
                        for sub_id, sub in subs.items():
                            tier = sub.get("tier", "TRIAL")
                            status = sub.get("status", "")
                            if status in ("ACTIVE", "active"):
                                tier_counts[tier] = tier_counts.get(tier, 0) + 1
                                # Estimate MRR by tier
                                if tier == "STANDARD" or tier == "inner_chamber":
                                    total_mrr += 4900
                                elif tier == "TOP_TIER" or tier == "sovereign_circle":
                                    total_mrr += 14900

                        await websocket.send(json.dumps({
                            "type": "revenue_data",
                            "total_customers": len(customers),
                            "total_subscriptions": len(subs),
                            "active_by_tier": tier_counts,
                            "estimated_mrr_cents": total_mrr,
                            "estimated_mrr": round(total_mrr / 100, 2),
                            "billing_source": "stripe_billing.json",
                        }))
                    except Exception as rev_err:
                        await websocket.send(json.dumps({
                            "type": "revenue_data",
                            "total_customers": 0,
                            "total_subscriptions": 0,
                            "active_by_tier": {},
                            "estimated_mrr": 0,
                            "error": str(rev_err),
                        }))

            # === ADMIN: GET CRISIS WATCHLIST ===
            elif t == "admin_get_crisis_watchlist":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    crisis_list = []
                    for k, v in registry.items():
                        p = v.get("profile", {}) if isinstance(v, dict) else {}
                        if p.get("role") == "CLIENT":
                            hw_id = p.get("hardware_id", "")
                            m = metrics_engine.load_metrics({"role": "CLIENT", "hardware_id": hw_id})
                            ns = m.get("nevedal_state", {})
                            risk = ns.get("risk_level", "LOW")
                            crisis_count = ns.get("crisis_count", 0)
                            if risk in ("HIGH", "CRITICAL") or crisis_count > 0:
                                crisis_list.append({
                                    "hardware_id": hw_id,
                                    "name": p.get("name", "Unknown"),
                                    "risk_level": risk,
                                    "crisis_count": crisis_count,
                                    "last_assessment": ns.get("last_risk_assessment", ""),
                                    "c_emo": ns.get("C_emo", 0),
                                    "anxiety_level": ns.get("anxiety_level", 0),
                                })
                    # Sort by risk severity
                    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
                    crisis_list.sort(key=lambda x: severity_order.get(x.get("risk_level", "LOW"), 3))
                    await websocket.send(json.dumps({
                        "type": "crisis_watchlist",
                        "watchlist": crisis_list,
                        "total": len(crisis_list),
                    }))

            # === ADMIN: APPROVE COACH ===
            elif t == "admin_approve_coach":
                if current_profile and current_profile.get("role") == "ADMIN":
                    coach_id = d.get("coach_id", "").strip()
                    print(f"[Admin Approve] Received coach_id='{coach_id}'")
                    registry = load_registry()
                    found = False
                    # Collect all hardware_ids for debug
                    all_hw_ids = []
                    for k, v in registry.items():
                        hw = v.get("profile", {}).get("hardware_id", "")
                        role_check = v.get("profile", {}).get("role", "")
                        if role_check == "COACH":
                            all_hw_ids.append(hw)
                        if hw == coach_id:
                            v["profile"]["subscription_status"] = "ACTIVE"
                            v["profile"]["certification_status"] = "APPROVED"
                            v["profile"]["coach_verified"] = True
                            saved = save_registry(registry)
                            if saved:
                                await websocket.send(json.dumps({
                                    "type": "coach_approved", 
                                    "coach_id": coach_id,
                                    "message": "Coach approved successfully"
                                }))
                                print(f"[Admin Approve] SUCCESS: Approved coach {coach_id}")
                            else:
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "message": "Coach approval save failed. Check server disk/permissions."
                                }))
                                print(f"[Admin Approve] SAVE FAILED for coach — registry write error")
                            found = True
                            break
                    if not found:
                        print(f"[Admin Approve] FAILED: coach not found in registry")
                        await websocket.send(json.dumps({"type": "error", "message": "Coach not found in registry."}))

            # === ADMIN: REJECT COACH ===
            elif t == "admin_reject_coach":
                if current_profile and current_profile.get("role") == "ADMIN":
                    coach_id = d.get("coach_id", "").strip()
                    reason = d.get("reason", "")
                    print(f"[Admin Reject] Received coach_id='{coach_id}', reason='{reason}'")
                    registry = load_registry()
                    found = False
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == coach_id:
                            v["profile"]["subscription_status"] = "REJECTED"
                            v["profile"]["certification_status"] = "REJECTED"
                            if reason:
                                v["profile"]["rejection_reason"] = reason
                            v["profile"]["rejected_at"] = str(datetime.datetime.now())
                            saved = save_registry(registry)
                            if saved:
                                await websocket.send(json.dumps({
                                    "type": "coach_rejected",
                                    "coach_id": coach_id,
                                    "message": "Coach application rejected"
                                }))
                                print(f"[Admin Reject] SUCCESS: Rejected coach {coach_id}")
                            else:
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "message": "Coach rejection save failed. Check server disk/permissions."
                                }))
                                print(f"[Admin Reject] SAVE FAILED — registry write error")
                            found = True
                            break
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Coach not found for rejection."}))
            
            # === ADMIN: VERIFY PASSPHRASE (Layer 3 security) ===
            elif t == "verify_admin_passphrase":
                if current_profile and current_profile.get("role") == "ADMIN":
                    answer = (d.get("passphrase", "") or "").strip().lower()
                    # Passphrase is stored server-side only — never exposed to client
                    _correct_passphrase = os.environ.get("ADMIN_PASSPHRASE", "i am who, i am").strip().lower()
                    if answer == _correct_passphrase:
                        await websocket.send(json.dumps({
                            "type": "passphrase_verified",
                            "success": True
                        }))
                        print(f"[Admin] Passphrase verified for {current_profile.get('name', 'unknown')}")
                    else:
                        await websocket.send(json.dumps({
                            "type": "passphrase_verified",
                            "success": False,
                            "message": "Incorrect passphrase"
                        }))
                        print(f"[Admin] Failed passphrase attempt from {current_profile.get('name', 'unknown')}")
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "ADMIN_ONLY"}))

            # === ADMIN: RESET USER PASSWORD ===
            elif t == "admin_reset_user_password":
                if current_profile and current_profile.get("role") == "ADMIN":
                    user_id = d.get("user_id", "").strip()
                    new_password = d.get("new_password", "").strip()
                    if not user_id or not new_password:
                        await websocket.send(json.dumps({"type": "error", "message": "user_id and new_password required"}))
                    elif len(new_password) < 6:
                        await websocket.send(json.dumps({"type": "error", "message": "Password must be at least 6 characters"}))
                    else:
                        registry = load_registry()
                        found = False
                        for k, v in registry.items():
                            p = v.get("profile", {}) if isinstance(v, dict) else {}
                            if p.get("hardware_id") == user_id:
                                creds = v.get("credentials", {}) or {}
                                creds["password"] = hash_password(new_password)
                                v["credentials"] = creds
                                save_registry(registry)
                                await websocket.send(json.dumps({
                                    "type": "password_reset_done",
                                    "message": "Password updated",
                                    "user_id": user_id,
                                }))
                                print(f"[Admin] Password reset for user {user_id}")
                                found = True
                                break
                        if not found:
                            await websocket.send(json.dumps({"type": "error", "message": "User not found."}))
            
            # === ADMIN: GET COACH W-9 DOCUMENT ===
            elif t == "admin_get_coach_document":
                if current_profile and current_profile.get("role") == "ADMIN":
                    coach_id = d.get("coach_id", "").strip()
                    registry = load_registry()
                    for k, v in registry.items():
                        p = v.get("profile", {}) if isinstance(v, dict) else {}
                        if p.get("hardware_id") == coach_id:
                            doc_path = p.get("tin_doc_path", "")
                            if doc_path and os.path.exists(doc_path):
                                import base64
                                try:
                                    with open(doc_path, "rb") as df:
                                        doc_data = base64.b64encode(df.read()).decode("utf-8")
                                    fname = os.path.basename(doc_path)
                                    await websocket.send(json.dumps({
                                        "type": "coach_document_data",
                                        "coach_id": coach_id,
                                        "filename": fname,
                                        "data": doc_data,
                                    }))
                                except Exception as doc_err:
                                    await websocket.send(json.dumps({"type": "error", "message": f"Error reading document: {doc_err}"}))
                            else:
                                await websocket.send(json.dumps({"type": "error", "message": "No document on file"}))
                            break

            # === JUDGE: COACH VERIFIES STUDENT ===
            elif t == "verify_student_request":
                if current_profile and current_profile.get("role") == "COACH":
                    student_id = d.get("student_id", "").strip()
                    verification_type = d.get("verification_type", "bar_student")
                    registry = load_registry()
                    student_found = False
                    for rk, rv in registry.items():
                        sp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                        if sp.get("hardware_id") == student_id:
                            student_found = True
                            sp.setdefault("judge_student_verification", {})
                            sp["judge_student_verification"] = {
                                "coach_id": current_profile.get("hardware_id"),
                                "coach_name": current_profile.get("name", "Unknown"),
                                "verification_type": verification_type,
                                "status": "pending_admin",
                                "requested_at": datetime.datetime.now().isoformat(),
                            }
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "student_verification_submitted",
                                "student_id": student_id,
                                "message": "Student verification request submitted for admin approval."
                            }))
                            # Notify admins
                            for ak, av in registry.items():
                                ap = av.get("profile", {}) if isinstance(av, dict) else {}
                                if ap.get("role") == "ADMIN":
                                    admin_hw = ap.get("hardware_id", "")
                                    for ws_conn, ws_prof in connected_clients.items():
                                        if ws_prof and ws_prof.get("hardware_id") == admin_hw:
                                            try:
                                                await ws_conn.send(json.dumps({
                                                    "type": "student_verification_pending",
                                                    "student_id": student_id,
                                                    "student_name": sp.get("name", "Unknown"),
                                                    "coach_name": current_profile.get("name", "Unknown"),
                                                    "verification_type": verification_type,
                                                }))
                                            except Exception:
                                                pass
                            print(f"[Judge] Student verification request: student={student_id} by coach={current_profile.get('hardware_id')}")
                            break
                    if not student_found:
                        await websocket.send(json.dumps({"type": "error", "message": "Student not found."}))

            # === ADMIN: APPROVE STUDENT VERIFICATION (JUDGE DOJO) ===
            elif t == "admin_approve_student_verification":
                if current_profile and current_profile.get("role") == "ADMIN":
                    student_id = d.get("student_id", "").strip()
                    registry = load_registry()
                    found = False
                    for rk, rv in registry.items():
                        sp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                        if sp.get("hardware_id") == student_id:
                            verif = sp.get("judge_student_verification", {})
                            if verif.get("status") == "pending_admin":
                                verif["status"] = "verified"
                                verif["approved_at"] = datetime.datetime.now().isoformat()
                                verif["approved_by"] = current_profile.get("hardware_id")
                                sp["judge_dojo_access"] = True
                                save_registry(registry)
                                await websocket.send(json.dumps({
                                    "type": "student_verification_approved",
                                    "student_id": student_id,
                                    "message": "Student verified for JUDGE DOJO access."
                                }))
                                print(f"[Judge] Admin approved student verification: {student_id}")
                                found = True
                            break
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Student verification not found or not pending"}))

            # === ADMIN: REJECT STUDENT VERIFICATION (JUDGE DOJO) ===
            elif t == "admin_reject_student_verification":
                if current_profile and current_profile.get("role") == "ADMIN":
                    student_id = d.get("student_id", "").strip()
                    reason = d.get("reason", "")
                    registry = load_registry()
                    found = False
                    for rk, rv in registry.items():
                        sp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                        if sp.get("hardware_id") == student_id:
                            verif = sp.get("judge_student_verification", {})
                            if verif.get("status") == "pending_admin":
                                verif["status"] = "rejected"
                                verif["rejected_at"] = datetime.datetime.now().isoformat()
                                verif["rejected_by"] = current_profile.get("hardware_id")
                                verif["rejection_reason"] = reason
                                sp["judge_dojo_access"] = False
                                save_registry(registry)
                                await websocket.send(json.dumps({
                                    "type": "student_verification_rejected",
                                    "student_id": student_id,
                                    "message": "Student verification rejected."
                                }))
                                print(f"[Judge] Admin rejected student verification: {student_id}")
                                found = True
                            break
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Student verification not found or not pending"}))

            # === ADMIN: GET PENDING STUDENT VERIFICATIONS (JUDGE DOJO) ===
            elif t == "admin_get_pending_students":
                if current_profile and current_profile.get("role") == "ADMIN":
                    registry = load_registry()
                    pending = []
                    for rk, rv in registry.items():
                        sp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                        verif = sp.get("judge_student_verification", {})
                        if verif.get("status") == "pending_admin":
                            pending.append({
                                "student_id": sp.get("hardware_id", ""),
                                "student_name": sp.get("name", "Unknown"),
                                "coach_id": verif.get("coach_id", ""),
                                "coach_name": verif.get("coach_name", "Unknown"),
                                "verification_type": verif.get("verification_type", "bar_student"),
                                "requested_at": verif.get("requested_at", ""),
                            })
                    await websocket.send(json.dumps({
                        "type": "pending_students_list",
                        "students": pending,
                    }))

            # === JUDGE: DEBATE REQUEST (matchmaking queue) ===
            elif t == "judge_debate_request":
                if current_profile and current_profile.get("role") == "COACH":
                    # Verify JUDGE subscription
                    dojos = get_active_dojos(current_profile)
                    if 'judge' not in [dd.lower() for dd in dojos]:
                        await websocket.send(json.dumps({"type": "error", "message": "JUDGE DOJO subscription required"}))
                        continue
                    from app.services.judge_debate import get_judge_debate_manager
                    manager = get_judge_debate_manager()
                    result = manager.request_debate(
                        coach_id=current_profile.get("hardware_id", ""),
                        coach_name=current_profile.get("name", "Unknown"),
                        bar_id=current_profile.get("judge_nate_bar_id", ""),
                        case_description=d.get("case_description", ""),
                    )
                    await websocket.send(json.dumps({"type": "judge_debate_status", **result}))
                    # If matched, notify the other coach too
                    if result.get("status") == "matched":
                        session_id = result["session_id"]
                        sess = manager.active_debates.get(session_id)
                        if sess:
                            other_id = sess.coach_a_id
                            for ws_conn, ws_prof in connected_clients.items():
                                if ws_prof and ws_prof.get("hardware_id") == other_id:
                                    try:
                                        await ws_conn.send(json.dumps({
                                            "type": "judge_debate_matched",
                                            "session_id": session_id,
                                            "opponent_name": current_profile.get("name", "Unknown"),
                                            "opponent_bar_id": current_profile.get("judge_nate_bar_id", ""),
                                            "message": f"Matched with {current_profile.get('name')}! Confirm $500 fee to proceed.",
                                        }))
                                    except Exception:
                                        pass

            # === JUDGE: DEBATE ACCEPT / PAYMENT CONFIRM ===
            elif t == "judge_debate_accept":
                if current_profile and current_profile.get("role") == "COACH":
                    from app.services.judge_debate import get_judge_debate_manager
                    manager = get_judge_debate_manager()
                    session_id = d.get("session_id", "")
                    result = manager.confirm_debate_payment(session_id, current_profile.get("hardware_id", ""))
                    # Record financial charge
                    if not result.get("error"):
                        registry = load_registry()
                        for rk, rv in registry.items():
                            rp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                            if rp.get("hardware_id") == current_profile.get("hardware_id"):
                                manager.record_financial_charge(rp, 500.0, f"Judge debate simulation fee - {session_id}")
                                save_registry(registry)
                                break
                    await websocket.send(json.dumps({"type": "judge_debate_payment", **result}))
                    # If both confirmed, create Zoom meeting and start
                    if result.get("status") == "both_confirmed":
                        try:
                            from app.services.zoom_client import ZoomClient
                            import os as _os
                            zoom = ZoomClient(
                                account_id=_os.getenv("ZOOM_ACCOUNT_ID", ""),
                                client_id=_os.getenv("ZOOM_CLIENT_ID", ""),
                                client_secret=_os.getenv("ZOOM_CLIENT_SECRET", ""),
                            )
                            meeting = await zoom.create_meeting(
                                topic=f"Judge Nate Courtroom - {session_id}",
                                duration_min=60,
                                agenda="Coach-vs-Coach debate with Judge Nate presiding",
                            )
                            start_result = manager.start_debate(
                                session_id, str(meeting.get("id", "")), meeting.get("join_url", "")
                            )
                            # Notify both coaches
                            sess = manager.active_debates.get(session_id)
                            if sess:
                                for cid in [sess.coach_a_id, sess.coach_b_id]:
                                    for ws_conn, ws_prof in connected_clients.items():
                                        if ws_prof and ws_prof.get("hardware_id") == cid:
                                            try:
                                                await ws_conn.send(json.dumps({
                                                    "type": "judge_debate_start",
                                                    "session_id": session_id,
                                                    "zoom_join_url": meeting.get("join_url", ""),
                                                    "message": "Debate is starting! Join the Zoom meeting. Judge Nate is presiding.",
                                                }))
                                            except Exception:
                                                pass
                        except Exception as zoom_err:
                            print(f"[Judge] Zoom meeting creation failed: {zoom_err}")
                            await websocket.send(json.dumps({
                                "type": "judge_debate_start",
                                "session_id": session_id,
                                "zoom_join_url": "",
                                "message": "Debate ready but Zoom unavailable. Proceed with manual meeting.",
                            }))

            # === JUDGE: MENTORING START ===
            elif t == "judge_mentoring_start":
                if current_profile and current_profile.get("role") == "COACH":
                    dojos = get_active_dojos(current_profile)
                    if 'judge' not in [dd.lower() for dd in dojos]:
                        await websocket.send(json.dumps({"type": "error", "message": "JUDGE DOJO subscription required"}))
                        continue
                    student_ids = d.get("student_ids", [])
                    if not student_ids:
                        await websocket.send(json.dumps({"type": "error", "message": "No students specified"}))
                        continue
                    # Validate all students are verified
                    registry = load_registry()
                    all_verified = True
                    for sid in student_ids:
                        verified = False
                        for rk, rv in registry.items():
                            sp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                            if sp.get("hardware_id") == sid:
                                if sp.get("judge_dojo_access"):
                                    verified = True
                                break
                        if not verified:
                            all_verified = False
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": f"Student {sid} is not verified for JUDGE DOJO access"
                            }))
                            break
                    if not all_verified:
                        continue
                    from app.services.judge_debate import get_judge_debate_manager
                    manager = get_judge_debate_manager()
                    result = manager.create_mentoring_session(
                        coach_id=current_profile.get("hardware_id", ""),
                        student_ids=student_ids,
                    )
                    await websocket.send(json.dumps({"type": "judge_mentoring_status", **result}))

            # === JUDGE: MENTORING CONFIRM PAYMENT ===
            elif t == "judge_mentoring_confirm_payment":
                if current_profile and current_profile.get("role") == "COACH":
                    from app.services.judge_debate import get_judge_debate_manager
                    manager = get_judge_debate_manager()
                    session_id = d.get("session_id", "")
                    result = manager.confirm_mentoring_payment(session_id)
                    if not result.get("error"):
                        # Record financial charge
                        registry = load_registry()
                        for rk, rv in registry.items():
                            rp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                            if rp.get("hardware_id") == current_profile.get("hardware_id"):
                                manager.record_financial_charge(rp, 250.0, f"Judge mentoring simulation fee - {session_id}")
                                save_registry(registry)
                                break
                        # Create Zoom meeting
                        try:
                            from app.services.zoom_client import ZoomClient
                            import os as _os
                            zoom = ZoomClient(
                                account_id=_os.getenv("ZOOM_ACCOUNT_ID", ""),
                                client_id=_os.getenv("ZOOM_CLIENT_ID", ""),
                                client_secret=_os.getenv("ZOOM_CLIENT_SECRET", ""),
                            )
                            meeting = await zoom.create_meeting(
                                topic=f"Judge Nate Mentoring - {session_id}",
                                duration_min=60,
                                agenda="Coach-as-Judge mentoring session with Judge Nate observing",
                            )
                            start_result = manager.start_mentoring(
                                session_id, str(meeting.get("id", "")), meeting.get("join_url", "")
                            )
                            await websocket.send(json.dumps({
                                "type": "judge_mentoring_started",
                                "session_id": session_id,
                                "zoom_join_url": meeting.get("join_url", ""),
                                "message": "Mentoring session started! Join the Zoom meeting.",
                            }))
                        except Exception as zoom_err:
                            print(f"[Judge] Zoom meeting creation failed for mentoring: {zoom_err}")
                            await websocket.send(json.dumps({
                                "type": "judge_mentoring_started",
                                "session_id": session_id,
                                "zoom_join_url": "",
                                "message": "Mentoring ready but Zoom unavailable. Proceed with manual meeting.",
                            }))
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": result.get("error", "Unknown error")}))

            # === JUDGE: MENTORING EVALUATE ===
            elif t == "judge_mentoring_evaluate":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    from app.services.judge_debate import get_judge_debate_manager
                    manager = get_judge_debate_manager()
                    session_id = d.get("session_id", "")
                    coach_assessment = d.get("coach_assessment", {})
                    student_assessments = d.get("student_assessments", [])
                    nate_learning = d.get("nate_learning_notes", "")
                    result = manager.evaluate_mentoring(
                        session_id=session_id,
                        coach_assessment=coach_assessment,
                        student_assessments=student_assessments,
                        nate_learning_notes=nate_learning,
                    )
                    if not result.get("error"):
                        # Store evaluations in coach and student profiles
                        registry = load_registry()
                        for rk, rv in registry.items():
                            rp = rv.get("profile", {}) if isinstance(rv, dict) else {}
                            hw = rp.get("hardware_id", "")
                            # Coach evaluation
                            if hw == result.get("coach_id"):
                                rp.setdefault("judge_evaluations", []).append({
                                    "session_id": session_id,
                                    "role": "judge",
                                    "assessment": coach_assessment,
                                    "date": datetime.datetime.now().isoformat(),
                                })
                            # Student evaluations
                            for sa in student_assessments:
                                if hw == sa.get("student_id"):
                                    rp.setdefault("judge_evaluations", []).append({
                                        "session_id": session_id,
                                        "role": "student",
                                        "assessment": sa,
                                        "date": datetime.datetime.now().isoformat(),
                                    })
                        save_registry(registry)
                        # Notify participants
                        sess = manager.active_mentoring.get(session_id) or {}
                        all_participants = [result.get("coach_id", "")] + result.get("student_ids", [])
                        for pid in all_participants:
                            for ws_conn, ws_prof in connected_clients.items():
                                if ws_prof and ws_prof.get("hardware_id") == pid:
                                    try:
                                        await ws_conn.send(json.dumps({
                                            "type": "judge_mentoring_evaluation",
                                            **result,
                                        }))
                                    except Exception:
                                        pass
                    await websocket.send(json.dumps({"type": "judge_mentoring_evaluation", **(result or {})}))

            # === JUDGE: LEXISNEXIS SEARCH ===
            elif t == "judge_lexis_search":
                if current_profile and current_profile.get("role") == "COACH":
                    dojos = get_active_dojos(current_profile)
                    if 'judge' not in [dd.lower() for dd in dojos]:
                        await websocket.send(json.dumps({"type": "error", "message": "JUDGE DOJO subscription required for LexisNexis"}))
                        continue
                    from app.services.lexisnexis_client import get_lexisnexis_client
                    lexis = get_lexisnexis_client()
                    search_type = d.get("search_type", "cases")  # "cases" or "statutes"
                    query = d.get("query", "")
                    jurisdiction = d.get("jurisdiction", "")
                    date_range = d.get("date_range", "")
                    if not query:
                        await websocket.send(json.dumps({"type": "error", "message": "Search query required"}))
                        continue
                    try:
                        if search_type == "statutes":
                            result = await lexis.search_statutes(query, jurisdiction)
                        else:
                            result = await lexis.search_cases(query, jurisdiction, date_range)
                        await websocket.send(json.dumps({"type": "judge_lexis_results", **result}))
                    except Exception as lex_err:
                        await websocket.send(json.dumps({"type": "error", "message": f"LexisNexis search failed: {lex_err}"}))

            # === JUDGE: LEXISNEXIS CASE DETAIL ===
            elif t == "judge_lexis_case":
                if current_profile and current_profile.get("role") == "COACH":
                    dojos = get_active_dojos(current_profile)
                    if 'judge' not in [dd.lower() for dd in dojos]:
                        await websocket.send(json.dumps({"type": "error", "message": "JUDGE DOJO subscription required"}))
                        continue
                    from app.services.lexisnexis_client import get_lexisnexis_client
                    lexis = get_lexisnexis_client()
                    case_id = d.get("case_id", "")
                    if not case_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Case ID required"}))
                        continue
                    try:
                        result = await lexis.get_case_detail(case_id)
                        await websocket.send(json.dumps({"type": "judge_lexis_case_detail", **result}))
                    except Exception as lex_err:
                        await websocket.send(json.dumps({"type": "error", "message": f"LexisNexis case detail failed: {lex_err}"}))

            # === JUDGE: DEBATE RULING ===
            elif t == "judge_debate_ruling":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    from app.services.judge_debate import get_judge_debate_manager, CoachScore
                    manager = get_judge_debate_manager()
                    session_id = d.get("session_id", "")
                    scores_data = d.get("scores", {})
                    scores = {}
                    for cid, sdata in scores_data.items():
                        cs = CoachScore(
                            coach_id=cid,
                            legal_reasoning=sdata.get("legal_reasoning", 0),
                            evidence_presentation=sdata.get("evidence_presentation", 0),
                            courtroom_demeanor=sdata.get("courtroom_demeanor", 0),
                            persuasiveness=sdata.get("persuasiveness", 0),
                        )
                        scores[cid] = cs
                    result = manager.issue_ruling(
                        session_id=session_id,
                        prevailing_coach_id=d.get("prevailing_coach", ""),
                        reasoning=d.get("reasoning", ""),
                        scores=scores,
                    )
                    # Notify both coaches of the ruling
                    sess_data = result if not result.get("error") else None
                    if sess_data:
                        for cid in [sess_data.get("coach_a_id"), sess_data.get("coach_b_id")]:
                            if cid:
                                for ws_conn, ws_prof in connected_clients.items():
                                    if ws_prof and ws_prof.get("hardware_id") == cid:
                                        try:
                                            await ws_conn.send(json.dumps({
                                                "type": "judge_debate_ruling_result",
                                                **sess_data,
                                            }))
                                        except Exception:
                                            pass
                    await websocket.send(json.dumps({"type": "judge_debate_ruling_result", **(result or {})}))

            # === ADMIN: ASSIGN COACH TO CLIENT ===
            elif t == "admin_assign_coach":
                if current_profile and current_profile.get("role") == "ADMIN":
                    client_id = d.get("client_id")
                    coach_id = d.get("coach_id")
                    registry = load_registry()
                    found = False
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            v["profile"]["assigned_coach_id"] = coach_id
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "coach_assigned", 
                                "client_id": client_id, 
                                "coach_id": coach_id,
                                "message": "Coach assigned successfully"
                            }))
                            found = True
                            break
                    if not found:
                        await websocket.send(json.dumps({"type": "error", "message": "Client not found"}))
            
            # === ADMIN: REMOVE COACH ASSIGNMENT ===
            elif t == "admin_remove_coach":
                if current_profile and current_profile.get("role") == "ADMIN":
                    client_id = d.get("client_id")
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            v["profile"]["assigned_coach_id"] = ""
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "coach_removed", 
                                "client_id": client_id
                            }))
                            break
            
            # === ADMIN: MERGE FAMILIES (blended family / marriage merge) ===
            elif t == "admin_merge_families":
                if current_profile and current_profile.get("role") == "ADMIN":
                    head_username = (d.get("head_username") or "").strip().lower()
                    spouse_username = (d.get("spouse_username") or "").strip().lower()

                    if not head_username or not spouse_username:
                        await websocket.send(json.dumps({"type": "merge_families_error", "message": "Both head_username and spouse_username are required."}))
                        continue
                    if head_username == spouse_username:
                        await websocket.send(json.dumps({"type": "merge_families_error", "message": "Cannot merge a user with themselves."}))
                        continue

                    registry = load_registry()

                    # Find both users (check both registry key and credentials username)
                    head_entry = None
                    spouse_entry = None
                    head_key = None
                    spouse_key = None
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        creds = v.get("credentials", {})
                        uname = (creds.get("username") or "").lower()
                        reg_key = k.lower()
                        if uname == head_username or reg_key == head_username:
                            head_entry = v
                            head_key = k
                        elif uname == spouse_username or reg_key == spouse_username:
                            spouse_entry = v
                            spouse_key = k

                    if not head_entry:
                        await websocket.send(json.dumps({"type": "merge_families_error", "message": f"User '{head_username}' not found."}))
                        continue
                    if not spouse_entry:
                        await websocket.send(json.dumps({"type": "merge_families_error", "message": f"User '{spouse_username}' not found."}))
                        continue

                    head_profile = head_entry.get("profile", {})
                    spouse_profile = spouse_entry.get("profile", {})
                    surviving_family_id = head_profile.get("family_id")
                    old_family_id = spouse_profile.get("family_id")

                    if not surviving_family_id:
                        # Auto-create family for head if they don't have one
                        surviving_family_id = f"FAM_{secrets.token_hex(4).upper()}"
                        head_profile["family_id"] = surviving_family_id
                        head_profile["family_role"] = "HEAD"

                    if surviving_family_id == old_family_id and old_family_id:
                        await websocket.send(json.dumps({"type": "merge_families_error", "message": "Both users are already in the same family."}))
                        continue

                    # === BACKUP before merge ===
                    import shutil as _shutil
                    backup_name = f"user_registry.json.pre_merge_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    try:
                        reg_path = DATA_DIR / "user_registry.json"
                        _shutil.copy2(str(reg_path), str(DATA_DIR / backup_name))
                        print(f">>> [MERGE] Registry backup: {backup_name}")
                    except Exception as bk_err:
                        print(f">>> [MERGE] Backup warning: {bk_err}")

                    # === Collect members being moved ===
                    moved_dependents = []
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        p = v.get("profile", {})
                        if p.get("family_id") == old_family_id and k != spouse_key and old_family_id:
                            # This is a dependent/member of the spouse's old family
                            old_role = p.get("family_role", "")
                            p["family_id"] = surviving_family_id
                            # Keep their role (DEPENDENT stays DEPENDENT)
                            # But if they were HEAD of the old family (edge case), demote to MEMBER
                            if (p.get("family_role") or "").upper() == "HEAD" and k != head_key:
                                p["family_role"] = "MEMBER"
                            p["merged_from_family"] = old_family_id
                            p["merged_at"] = str(datetime.datetime.now())
                            moved_dependents.append({
                                "username": v.get("credentials", {}).get("username", k),
                                "name": p.get("name", ""),
                                "hardware_id": p.get("hardware_id", ""),
                                "old_role": old_role,
                                "guardian_id": p.get("guardian_id", ""),
                            })

                    # === Update spouse profile ===
                    spouse_profile["merged_from_family"] = old_family_id or ""
                    spouse_profile["previous_plan"] = spouse_profile.get("subscription_plan", "")
                    spouse_profile["previous_family_role"] = spouse_profile.get("family_role", "")
                    spouse_profile["family_id"] = surviving_family_id
                    spouse_profile["family_role"] = "SPOUSE"
                    spouse_profile["subscription_plan"] = "FAMILY_MEMBER"
                    spouse_profile["merged_at"] = str(datetime.datetime.now())
                    spouse_profile["merged_by_admin"] = current_username or "admin"
                    spouse_profile["updated_at"] = str(datetime.datetime.now())

                    # === Ensure head is marked as HEAD ===
                    head_profile["family_role"] = "HEAD"
                    head_profile["updated_at"] = str(datetime.datetime.now())

                    # === Migrate coach session notes ===
                    notes_migrated = 0
                    if old_family_id:
                        try:
                            notes_store = load_json_file(COACH_SESSION_NOTES_FILE, {})
                            old_key = f"family:{old_family_id}"
                            new_key = f"family:{surviving_family_id}"
                            if old_key in notes_store:
                                old_notes = notes_store.pop(old_key)
                                # Update family_id in each note
                                for note in old_notes:
                                    note["family_id"] = surviving_family_id
                                    note["migrated_from_family"] = old_family_id
                                existing = notes_store.get(new_key, [])
                                existing.extend(old_notes)
                                # Sort by created_at and cap
                                existing.sort(key=lambda n: n.get("created_at", ""))
                                notes_store[new_key] = existing[-400:]
                                save_json_file(COACH_SESSION_NOTES_FILE, notes_store)
                                notes_migrated = len(old_notes)
                                print(f">>> [MERGE] Migrated {notes_migrated} coach notes from {old_key} to {new_key}")
                        except Exception as ne:
                            print(f">>> [MERGE] Coach notes migration warning: {ne}")

                    # === Clean up old family invite tokens ===
                    tokens_cleaned = 0
                    if old_family_id:
                        invites = registry.get("_family_invites", {})
                        to_remove = [tok for tok, inv in invites.items() if inv.get("family_id") == old_family_id]
                        for tok in to_remove:
                            del invites[tok]
                            tokens_cleaned += 1
                        if tokens_cleaned:
                            print(f">>> [MERGE] Cleaned {tokens_cleaned} old invite tokens for {old_family_id}")

                    # === Save registry ===
                    save_registry(registry)

                    # === Build billing summary ===
                    # Count all dependents in the merged family
                    merged_members = []
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        p = v.get("profile", {})
                        if p.get("family_id") == surviving_family_id:
                            merged_members.append({
                                "username": v.get("credentials", {}).get("username", k),
                                "name": p.get("name", ""),
                                "role": p.get("family_role", ""),
                                "plan": p.get("subscription_plan", ""),
                                "hardware_id": p.get("hardware_id", ""),
                                "guardian_id": p.get("guardian_id", ""),
                                "is_minor": p.get("is_minor", False),
                            })
                    dep_count = sum(1 for m in merged_members if m["role"] not in ("HEAD", "SPOUSE", "") and m["username"] != head_username and m["username"] != spouse_username)
                    free_deps = min(dep_count, 1)
                    paid_deps = max(dep_count - 1, 0)
                    billing_note = f"HEAD: {head_username} (TOP_TIER), SPOUSE: {spouse_username} (free), Dependents: {dep_count} ({free_deps} free + {paid_deps} x $75/mo = ${paid_deps * 75}/mo)"

                    summary = {
                        "type": "merge_families_success",
                        "surviving_family_id": surviving_family_id,
                        "dissolved_family_id": old_family_id or "(none)",
                        "head": {"username": head_username, "name": head_profile.get("name", "")},
                        "spouse": {"username": spouse_username, "name": spouse_profile.get("name", ""), "previous_plan": spouse_profile.get("previous_plan", "")},
                        "moved_dependents": moved_dependents,
                        "notes_migrated": notes_migrated,
                        "tokens_cleaned": tokens_cleaned,
                        "merged_family_members": merged_members,
                        "billing_summary": billing_note,
                        "backup_file": backup_name,
                    }
                    print(f">>> [MERGE] SUCCESS: {head_username} + {spouse_username} -> {surviving_family_id} | {len(moved_dependents)} deps moved | {billing_note}")
                    await websocket.send(json.dumps(summary))
                else:
                    await websocket.send(json.dumps({"type": "merge_families_error", "message": "Admin access required."}))

            # === ADMIN: UNMERGE FAMILY MEMBER (reverse a merge) ===
            elif t == "admin_unmerge_family_member":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_username = (d.get("username") or "").strip().lower()
                    if not target_username:
                        await websocket.send(json.dumps({"type": "unmerge_error", "message": "username is required."}))
                        continue

                    registry = load_registry()
                    target_entry = None
                    target_key = None
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        cred_uname = (v.get("credentials", {}).get("username") or "").lower()
                        reg_key = k.lower()
                        if cred_uname == target_username or reg_key == target_username:
                            target_entry = v
                            target_key = k
                            break

                    if not target_entry:
                        await websocket.send(json.dumps({"type": "unmerge_error", "message": f"User '{target_username}' not found."}))
                        continue

                    tp = target_entry.get("profile", {})
                    old_family_id = tp.get("merged_from_family", "")
                    if not old_family_id:
                        await websocket.send(json.dumps({"type": "unmerge_error", "message": f"User '{target_username}' was not merged (no merged_from_family field)."}))
                        continue

                    # Backup
                    import shutil as _shutil
                    backup_name = f"user_registry.json.pre_unmerge_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    try:
                        reg_path = DATA_DIR / "user_registry.json"
                        _shutil.copy2(str(reg_path), str(DATA_DIR / backup_name))
                    except Exception:
                        pass

                    # Restore the user's original family
                    current_family = tp.get("family_id", "")
                    tp["family_id"] = old_family_id
                    tp["family_role"] = tp.get("previous_family_role", "HEAD") or "HEAD"
                    tp["subscription_plan"] = tp.get("previous_plan", "TOP_TIER") or "TOP_TIER"
                    # Clean up merge fields
                    tp.pop("merged_from_family", None)
                    tp.pop("previous_plan", None)
                    tp.pop("previous_family_role", None)
                    tp.pop("merged_at", None)
                    tp.pop("merged_by_admin", None)
                    tp["updated_at"] = str(datetime.datetime.now())

                    # Move back any dependents that were originally theirs (guardian_id match)
                    restored_deps = []
                    target_hw_id = tp.get("hardware_id", "")
                    for k, v in registry.items():
                        if k.startswith("_") or k == target_key:
                            continue
                        p = v.get("profile", {})
                        if p.get("merged_from_family") == old_family_id and p.get("guardian_id") == target_hw_id:
                            p["family_id"] = old_family_id
                            p.pop("merged_from_family", None)
                            p.pop("merged_at", None)
                            p["updated_at"] = str(datetime.datetime.now())
                            restored_deps.append(v.get("credentials", {}).get("username", k))

                    save_registry(registry)

                    result = {
                        "type": "unmerge_success",
                        "username": target_username,
                        "restored_family_id": old_family_id,
                        "restored_role": tp.get("family_role"),
                        "restored_plan": tp.get("subscription_plan"),
                        "restored_dependents": restored_deps,
                        "backup_file": backup_name,
                    }
                    print(f">>> [UNMERGE] {target_username} restored to {old_family_id} with {len(restored_deps)} dependents")
                    await websocket.send(json.dumps(result))
                else:
                    await websocket.send(json.dumps({"type": "unmerge_error", "message": "Admin access required."}))

            # === ADMIN: PREVIEW MERGE (dry run) ===
            elif t == "admin_preview_merge":
                if current_profile and current_profile.get("role") == "ADMIN":
                    head_username = (d.get("head_username") or "").strip().lower()
                    spouse_username = (d.get("spouse_username") or "").strip().lower()
                    registry = load_registry()

                    head_profile = None
                    spouse_profile = None
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        uname = (v.get("credentials", {}).get("username") or "").lower()
                        reg_key = k.lower()
                        if uname == head_username or reg_key == head_username:
                            head_profile = v.get("profile", {})
                        elif uname == spouse_username or reg_key == spouse_username:
                            spouse_profile = v.get("profile", {})

                    if not head_profile or not spouse_profile:
                        await websocket.send(json.dumps({"type": "merge_preview", "valid": False, "message": "One or both users not found."}))
                        continue

                    h_fam = head_profile.get("family_id", "")
                    s_fam = spouse_profile.get("family_id", "")

                    # Count dependents in each family
                    head_deps = []
                    spouse_deps = []
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        p = v.get("profile", {})
                        pfam = p.get("family_id", "")
                        phw = p.get("hardware_id", "")
                        if pfam == h_fam and phw != head_profile.get("hardware_id") and h_fam:
                            head_deps.append({"name": p.get("name", ""), "role": p.get("family_role", ""), "username": v.get("credentials", {}).get("username", k)})
                        elif pfam == s_fam and phw != spouse_profile.get("hardware_id") and s_fam:
                            spouse_deps.append({"name": p.get("name", ""), "role": p.get("family_role", ""), "username": v.get("credentials", {}).get("username", k)})

                    total_deps = len(head_deps) + len(spouse_deps)
                    free_deps = min(total_deps, 1)
                    paid_deps = max(total_deps - 1, 0)

                    await websocket.send(json.dumps({
                        "type": "merge_preview",
                        "valid": True,
                        "head": {"username": head_username, "name": head_profile.get("name"), "plan": head_profile.get("subscription_plan"), "family_id": h_fam, "dependents": head_deps},
                        "spouse": {"username": spouse_username, "name": spouse_profile.get("name"), "plan": spouse_profile.get("subscription_plan"), "family_id": s_fam, "dependents": spouse_deps},
                        "after_merge": {
                            "total_dependents": total_deps,
                            "free_dependents": free_deps,
                            "paid_dependents": paid_deps,
                            "monthly_dependent_cost": paid_deps * 75,
                            "billing_note": f"Spouse: free | {free_deps} dep free | {paid_deps} deps x $75 = ${paid_deps * 75}/mo",
                        },
                        "same_family": h_fam == s_fam and h_fam != "",
                    }))

            # === ADMIN: SEPARATE FAMILY MEMBER (divorce/leave — NOT an undo of merge) ===
            elif t == "admin_separate_family_member":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_username = (d.get("username") or "").strip().lower()
                    dependents_to_move = d.get("dependents_to_move", [])  # list of usernames going with departing member
                    new_name = (d.get("new_name") or "").strip()
                    grace_days = d.get("grace_period_days", 14)

                    if not target_username:
                        await websocket.send(json.dumps({"type": "separate_error", "message": "username is required."}))
                        continue

                    registry = load_registry()

                    # Find the target user
                    target_entry = None
                    target_key = None
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        cred_uname = (v.get("credentials", {}).get("username") or "").lower()
                        reg_key = k.lower()
                        if cred_uname == target_username or reg_key == target_username:
                            target_entry = v
                            target_key = k
                            break

                    if not target_entry:
                        await websocket.send(json.dumps({"type": "separate_error", "message": f"User '{target_username}' not found."}))
                        continue

                    tp = target_entry.get("profile", {})
                    old_family_id = tp.get("family_id", "")
                    old_role = tp.get("family_role", "")
                    old_plan = tp.get("subscription_plan", "")

                    if not old_family_id:
                        await websocket.send(json.dumps({"type": "separate_error", "message": f"User '{target_username}' is not in a family."}))
                        continue

                    # Prevent separating the HEAD if there are still other non-departing members
                    if old_role == "HEAD":
                        remaining = []
                        dep_lower = [dn.strip().lower() for dn in dependents_to_move]
                        for k, v in registry.items():
                            if k.startswith("_") or k == target_key:
                                continue
                            p = v.get("profile", {})
                            if p.get("family_id") == old_family_id:
                                cname = (v.get("credentials", {}).get("username") or k).lower()
                                if cname not in dep_lower and k.lower() not in dep_lower:
                                    remaining.append(cname)
                        if remaining:
                            await websocket.send(json.dumps({
                                "type": "separate_error",
                                "message": f"Cannot separate the HEAD while other members remain: {', '.join(remaining)}. Reassign headship first or separate the spouse instead."
                            }))
                            continue

                    # === BACKUP ===
                    import shutil as _shutil
                    backup_name = f"user_registry.json.pre_separate_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    try:
                        reg_path = DATA_DIR / "user_registry.json"
                        _shutil.copy2(str(reg_path), str(DATA_DIR / backup_name))
                        print(f">>> [SEPARATE] Registry backup: {backup_name}")
                    except Exception as bk_err:
                        print(f">>> [SEPARATE] Backup warning: {bk_err}")

                    # === Create new family for departing member ===
                    new_family_id = f"FAM_{secrets.token_hex(4).upper()}"
                    trial_end = str((datetime.datetime.now() + datetime.timedelta(days=grace_days)).date())

                    # Store audit trail
                    tp["separated_from_family"] = old_family_id
                    tp["separated_at"] = str(datetime.datetime.now())
                    tp["separated_by_admin"] = (current_profile.get("name") or current_username or "admin")
                    tp["previous_family_role"] = old_role
                    tp["previous_plan_before_separation"] = old_plan

                    # Update to independent
                    tp["family_id"] = new_family_id
                    tp["family_role"] = "HEAD"
                    tp["subscription_plan"] = "TRIAL"
                    tp["subscription_status"] = "TRIAL_ACTIVE"
                    tp["trial_end"] = trial_end
                    tp["updated_at"] = str(datetime.datetime.now())

                    # Optional name change
                    if new_name:
                        tp["previous_name"] = tp.get("name", "")
                        tp["name"] = new_name

                    # === Move selected dependents ===
                    moved_deps = []
                    dep_lower_set = set(dn.strip().lower() for dn in dependents_to_move)
                    target_hw_id = tp.get("hardware_id", "")
                    for k, v in registry.items():
                        if k.startswith("_") or k == target_key:
                            continue
                        p = v.get("profile", {})
                        if p.get("family_id") != old_family_id:
                            continue
                        cred_u = (v.get("credentials", {}).get("username") or "").lower()
                        reg_k = k.lower()
                        if cred_u in dep_lower_set or reg_k in dep_lower_set:
                            p["family_id"] = new_family_id
                            p["guardian_id"] = target_hw_id
                            p["separated_from_family"] = old_family_id
                            p["separated_at"] = str(datetime.datetime.now())
                            p["updated_at"] = str(datetime.datetime.now())
                            moved_deps.append({
                                "username": v.get("credentials", {}).get("username", k),
                                "name": p.get("name", ""),
                            })

                    # === Recalculate billing for original family ===
                    orig_members = []
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        p = v.get("profile", {})
                        if p.get("family_id") == old_family_id:
                            orig_members.append({
                                "username": v.get("credentials", {}).get("username", k),
                                "name": p.get("name", ""),
                                "role": p.get("family_role", ""),
                                "plan": p.get("subscription_plan", ""),
                            })

                    orig_head_count = sum(1 for m in orig_members if m["role"] in ("HEAD", "SPOUSE"))
                    orig_dep_count = len(orig_members) - orig_head_count
                    orig_free_deps = min(orig_dep_count, 1)
                    orig_paid_deps = max(orig_dep_count - 1, 0)

                    new_dep_count = len(moved_deps)
                    new_free_deps = min(new_dep_count, 1)
                    new_paid_deps = max(new_dep_count - 1, 0)

                    save_registry(registry)

                    result = {
                        "type": "separate_success",
                        "username": target_username,
                        "new_family_id": new_family_id,
                        "old_family_id": old_family_id,
                        "new_role": "HEAD",
                        "new_plan": "TRIAL",
                        "trial_end": trial_end,
                        "name_changed": bool(new_name),
                        "new_name": new_name if new_name else tp.get("name", ""),
                        "moved_dependents": moved_deps,
                        "original_family_remaining": orig_members,
                        "billing_original": f"{old_family_id}: {len(orig_members)} members ({orig_dep_count} deps, {orig_free_deps} free + {orig_paid_deps} x $75 = ${orig_paid_deps * 75}/mo)",
                        "billing_new": f"{new_family_id}: HEAD on TRIAL (must upgrade) + {new_dep_count} deps",
                        "backup_file": backup_name,
                    }
                    print(f">>> [SEPARATE] {target_username} separated from {old_family_id} -> {new_family_id} | {len(moved_deps)} deps moved")
                    await websocket.send(json.dumps(result))
                else:
                    await websocket.send(json.dumps({"type": "separate_error", "message": "Admin access required."}))

            # === ADMIN: PREVIEW SEPARATION (dry run) ===
            elif t == "admin_preview_separation":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_username = (d.get("username") or "").strip().lower()
                    registry = load_registry()

                    # Find target
                    target_entry = None
                    target_key = None
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        cred_uname = (v.get("credentials", {}).get("username") or "").lower()
                        reg_key = k.lower()
                        if cred_uname == target_username or reg_key == target_username:
                            target_entry = v
                            target_key = k
                            break

                    if not target_entry:
                        await websocket.send(json.dumps({"type": "separation_preview", "valid": False, "message": f"User '{target_username}' not found."}))
                        continue

                    tp = target_entry.get("profile", {})
                    old_family_id = tp.get("family_id", "")

                    if not old_family_id:
                        await websocket.send(json.dumps({"type": "separation_preview", "valid": False, "message": "User is not in a family."}))
                        continue

                    # Gather all family members
                    family_members = []
                    for k, v in registry.items():
                        if k.startswith("_"):
                            continue
                        p = v.get("profile", {})
                        if p.get("family_id") == old_family_id:
                            family_members.append({
                                "username": v.get("credentials", {}).get("username", k),
                                "registry_key": k,
                                "name": p.get("name", ""),
                                "family_role": p.get("family_role", ""),
                                "subscription_plan": p.get("subscription_plan", ""),
                                "guardian_id": p.get("guardian_id", ""),
                                "hardware_id": p.get("hardware_id", ""),
                                "is_minor": p.get("is_minor", False),
                                "is_target": k == target_key,
                            })

                    # Find head of the family
                    head_member = None
                    for m in family_members:
                        if m["family_role"] == "HEAD":
                            head_member = m
                            break

                    # Identify dependents (non-HEAD, non-SPOUSE, non-target)
                    dependents = [m for m in family_members if not m["is_target"] and m["family_role"] not in ("HEAD", "SPOUSE") or (m["family_role"] in ("HEAD", "SPOUSE") and m["is_target"] is False and m["username"] != (head_member or {}).get("username", ""))]
                    # Simplify: all members except the target
                    other_members = [m for m in family_members if not m["is_target"]]

                    await websocket.send(json.dumps({
                        "type": "separation_preview",
                        "valid": True,
                        "target": {
                            "username": target_entry.get("credentials", {}).get("username", target_key),
                            "registry_key": target_key,
                            "name": tp.get("name", ""),
                            "current_role": tp.get("family_role", ""),
                            "current_plan": tp.get("subscription_plan", ""),
                            "is_head": tp.get("family_role", "") == "HEAD",
                        },
                        "family_id": old_family_id,
                        "head": {
                            "username": head_member["username"] if head_member else "?",
                            "name": head_member["name"] if head_member else "?",
                        } if head_member else None,
                        "other_members": other_members,
                        "total_family_size": len(family_members),
                    }))
                else:
                    await websocket.send(json.dumps({"type": "separation_preview", "valid": False, "message": "Admin access required."}))

            # === ADMIN: GET COMPANY CLIENTS ===
            elif t == "admin_get_company_clients":
                if current_profile and current_profile.get("role") in ("ADMIN", "COACH"):
                    target_company = (d.get("company_id") or "").strip()
                    registry = load_registry()
                    companies = {}  # company_id -> {name, clients[]}
                    for k, v in registry.items():
                        p = v.get("profile", {})
                        if p.get("role") != "CLIENT":
                            continue
                        cid = (p.get("company_id") or "").strip()
                        if not cid:
                            continue
                        if target_company and cid != target_company:
                            continue
                        if cid not in companies:
                            companies[cid] = {"company_id": cid, "company_name": p.get("company_name", ""), "clients": []}
                        companies[cid]["clients"].append({
                            "id": p.get("hardware_id"),
                            "name": p.get("name"),
                            "subscription_plan": p.get("subscription_plan", ""),
                            "assigned_coach_id": p.get("assigned_coach_id", ""),
                            "last_login": p.get("last_login", ""),
                        })
                    await websocket.send(json.dumps({
                        "type": "company_clients",
                        "companies": list(companies.values()),
                    }))

            # === MATCHING: SUGGEST COACH MATCH ===
            elif t == "nate_suggest_coach_match":
                if current_profile and current_profile.get("role") in ("ADMIN", "COACH"):
                    client_id = (d.get("client_id") or "").strip()
                    if not client_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing client_id"}))
                    else:
                        try:
                            from app.services.coach_matcher import CoachMatcher
                            matcher = CoachMatcher(DATA_DIR, VAULT_ROOT)
                            suggestions = await matcher.get_top_matches(client_id, n=3)
                            
                            # Store suggestions
                            suggestions_file = DATA_DIR / "coach_match_suggestions.json"
                            existing = load_json_file(str(suggestions_file), [])
                            existing.append({
                                "id": f"MATCH_{secrets.token_hex(4).upper()}",
                                "client_id": client_id,
                                "suggestions": suggestions,
                                "requested_by": current_profile.get("hardware_id", ""),
                                "status": "PENDING",
                                "created_at": str(datetime.datetime.now()),
                            })
                            save_json_file(str(suggestions_file), existing)
                            
                            await websocket.send(json.dumps({
                                "type": "coach_match_suggestions",
                                "client_id": client_id,
                                "suggestions": suggestions,
                            }))
                        except ImportError:
                            await websocket.send(json.dumps({"type": "error", "message": "Coach matcher not available"}))
                        except Exception as e:
                            print(f">>> [ERROR] Matching failed: {e}")
                            await websocket.send(json.dumps({"type": "error", "message": "MATCHING_FAILED"}))

            # === ADMIN: GET MATCH SUGGESTIONS ===
            elif t == "admin_get_match_suggestions":
                if current_profile and current_profile.get("role") == "ADMIN":
                    suggestions_file = DATA_DIR / "coach_match_suggestions.json"
                    suggestions = load_json_file(str(suggestions_file), [])
                    pending = [s for s in suggestions if s.get("status") == "PENDING"]
                    await websocket.send(json.dumps({
                        "type": "match_suggestions_list",
                        "suggestions": pending,
                    }))

            # === ADMIN: APPROVE MATCH ===
            elif t == "admin_approve_match":
                if current_profile and current_profile.get("role") == "ADMIN":
                    match_id = (d.get("match_id") or "").strip()
                    coach_id = (d.get("coach_id") or "").strip()
                    client_id = (d.get("client_id") or "").strip()
                    if not coach_id or not client_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing coach_id or client_id"}))
                    else:
                        # Assign coach
                        registry = load_registry()
                        assigned = False
                        for k, v in registry.items():
                            if v.get("profile", {}).get("hardware_id") == client_id:
                                v["profile"]["assigned_coach_id"] = coach_id
                                assigned = True
                                break
                        if assigned:
                            save_registry(registry)
                            # Update suggestion status
                            if match_id:
                                suggestions_file = DATA_DIR / "coach_match_suggestions.json"
                                suggestions = load_json_file(str(suggestions_file), [])
                                for s in suggestions:
                                    if s.get("id") == match_id:
                                        s["status"] = "APPROVED"
                                        s["approved_coach_id"] = coach_id
                                        s["approved_at"] = str(datetime.datetime.now())
                                        break
                                save_json_file(str(suggestions_file), suggestions)
                            
                            await websocket.send(json.dumps({
                                "type": "match_approved",
                                "client_id": client_id,
                                "coach_id": coach_id,
                            }))
                            
                            # Notify coach
                            coach_ws = connected_coaches.get(coach_id)
                            if coach_ws:
                                try:
                                    await coach_ws.send(json.dumps({
                                        "type": "coach_match_notification",
                                        "client_id": client_id,
                                        "message": "You have been matched with a new client."
                                    }))
                                except Exception:
                                    pass
                        else:
                            await websocket.send(json.dumps({"type": "error", "message": "Client not found"}))

            # === ADMIN: SUSPEND USER ===
            elif t == "admin_suspend_user":
                if current_profile and current_profile.get("role") == "ADMIN":
                    user_id = d.get("user_id")
                    reason = d.get("reason", "")
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == user_id:
                            v["profile"]["subscription_status"] = "SUSPENDED"
                            v["profile"]["suspension_reason"] = reason
                            v["profile"]["suspended_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "user_suspended", 
                                "user_id": user_id
                            }))
                            break
            
            # === ADMIN: REACTIVATE USER ===
            elif t == "admin_reactivate_user":
                if current_profile and current_profile.get("role") == "ADMIN":
                    user_id = d.get("user_id")
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == user_id:
                            v["profile"]["subscription_status"] = "ACTIVE"
                            v["profile"]["suspension_reason"] = ""
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "user_reactivated", 
                                "user_id": user_id
                            }))
                            break

            # === ADMIN: FORCE DISCONNECT USER ===
            elif t == "admin_force_disconnect":
                if current_profile and current_profile.get("role") == "ADMIN":
                    client_id = d.get("client_id", "").strip()
                    if not client_id:
                        await websocket.send(json.dumps({"type": "error", "message": "client_id required"}))
                    else:
                        target_ws = connected_clients.get(client_id) or connected_coaches.get(client_id)
                        if target_ws:
                            try:
                                await target_ws.send(json.dumps({
                                    "type": "force_disconnect",
                                    "message": "You have been disconnected by an administrator."
                                }))
                                await target_ws.close(1000, "Admin force disconnect")
                            except Exception:
                                pass
                            connected_clients.pop(client_id, None)
                            connected_coaches.pop(client_id, None)
                            await websocket.send(json.dumps({
                                "type": "force_disconnect_done",
                                "client_id": client_id,
                                "message": "User disconnected"
                            }))
                            print(f"[Admin] Force disconnected user {client_id}")
                        else:
                            await websocket.send(json.dumps({
                                "type": "force_disconnect_done",
                                "client_id": client_id,
                                "message": "User is not currently connected"
                            }))
            
            # === ADMIN: GET CRISIS LOG ===
            elif t == "admin_get_crisis_log":
                if current_profile and current_profile.get("role") == "ADMIN":
                    crisis_log = load_json_file(CRISIS_LOG_FILE, [])
                    await websocket.send(json.dumps({
                        "type": "crisis_log_data",
                        "entries": crisis_log[-100:]
                    }))
            
            # === ADMIN: RESOLVE CRISIS ===
            elif t == "admin_resolve_crisis":
                if current_profile and current_profile.get("role") == "ADMIN":
                    crisis_id = d.get("crisis_id")
                    resolution_notes = d.get("notes", "")
                    crisis_log = load_json_file(CRISIS_LOG_FILE, [])
                    for entry in crisis_log:
                        if entry.get("timestamp") == crisis_id or entry.get("user_id") == crisis_id:
                            entry["status"] = "resolved"
                            entry["resolved"] = True
                            entry["resolved_by"] = current_profile.get("name")
                            entry["resolution_notes"] = resolution_notes
                            entry["resolved_at"] = str(datetime.datetime.now())
                            save_json_file(CRISIS_LOG_FILE, crisis_log)
                            await websocket.send(json.dumps({
                                "type": "crisis_resolved",
                                "message": "Crisis marked as resolved"
                            }))
                            break
            
            # === ADMIN: GET CLIENT PMB (Patent 2 — all confidence levels for admin) ===
            elif t == "admin_get_client_pmb":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    client_id = d.get("client_id")
                    registry = load_registry()
                    client_profile = None
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            client_profile = v["profile"]
                            break
                    if client_profile:
                        client_metrics = metrics_engine.load_metrics(client_profile)
                        client_ns = client_metrics.get("nevedal_state", {})
                        await websocket.send(json.dumps({
                            "type": "client_pmb_data",
                            "client_id": client_id,
                            "crisis_perception": client_ns.get("crisis_perception", {}),
                            "shame_profile": client_ns.get("shame_profile", {}),
                            "pmb": client_ns.get("pmb", {}),
                            "zoom_sessions": client_metrics.get("zoom_sessions", [])[-50:]
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "client_pmb_data",
                            "client_id": client_id,
                            "error": "Client not found"
                        }))

            # === ADMIN: GET ZOOM SESSIONS for a client (Patent 2 Section 16) ===
            elif t == "admin_get_zoom_sessions":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    client_id = d.get("client_id")
                    registry = load_registry()
                    client_profile = None
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            client_profile = v["profile"]
                            break
                    if client_profile:
                        client_metrics = metrics_engine.load_metrics(client_profile)
                        zoom_sessions = client_metrics.get("zoom_sessions", [])
                        await websocket.send(json.dumps({
                            "type": "client_zoom_sessions",
                            "client_id": client_id,
                            "zoom_sessions": zoom_sessions[-50:],
                            "total_zoom_sessions": len(zoom_sessions)
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "client_zoom_sessions",
                            "client_id": client_id,
                            "zoom_sessions": [],
                            "total_zoom_sessions": 0,
                            "error": "Client not found"
                        }))

            # === COACH: GET ASSIGNED CLIENTS ===
            elif t == "coach_get_clients":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    registry = load_registry()
                    clients = []
                    coach_id = current_profile.get("hardware_id")
                    coach_username = current_username or ""
                    is_admin = current_profile.get("role") == "ADMIN"

                    # Best-practice fallback: if assignments are missing on client profiles, infer
                    # clients from this coach's scheduled sessions (backend data source-of-truth).
                    session_client_ids = set()
                    session_client_meta = {}
                    if not is_admin:
                        try:
                            sessions_src = load_json_file(BACKEND_DATA_DIR / "sessions.json", []) or []
                            if not isinstance(sessions_src, list):
                                sessions_src = []
                            for s in sessions_src:
                                if not isinstance(s, dict):
                                    continue
                                if (s.get("coach_id") or "") != coach_id:
                                    continue
                                cid = (s.get("client_id") or "").strip()
                                if cid:
                                    session_client_ids.add(cid)
                                    # Capture best-effort display metadata from schedule store
                                    if cid not in session_client_meta:
                                        session_client_meta[cid] = {
                                            "client_name": (s.get("client_name") or s.get("client") or "").strip(),
                                            "family_id": (s.get("family_id") or "").strip(),
                                        }
                        except Exception:
                            session_client_ids = set()
                            session_client_meta = {}

                    # Index registry clients by hardware_id for fast lookup.
                    registry_clients_by_id = {}
                    try:
                        for _, v in (registry or {}).items():
                            p = (v.get("profile") or {})
                            if p.get("role") == "CLIENT":
                                hid = (p.get("hardware_id") or "").strip()
                                if hid:
                                    registry_clients_by_id[hid] = p
                    except Exception:
                        registry_clients_by_id = {}
                    
                    for k, v in registry.items():
                        p = v.get("profile", {})
                        if p.get("role") != "CLIENT":
                            continue

                        # Assignment rules:
                        # - For COACH: allow if client profile points to this coach (username or hardware id)
                        # - For ADMIN: return all clients (optionally filterable later)
                        assigned_ok = is_admin
                        if not is_admin:
                            assigned_ok = (
                                (p.get("assigned_coach_id") and p.get("assigned_coach_id") == coach_id)
                                or (p.get("assigned_coach") and coach_username and p.get("assigned_coach") == coach_username)
                                or (p.get("hardware_id") in session_client_ids)
                            )
                        if not assigned_ok:
                            continue

                        # Metrics (summary + raw highlights)
                        try:
                            m = parietal.load_metrics(p)
                            ns = (m.get("nevedal_state") or {})
                        except Exception:
                            ns = {}

                        summary = parietal.get_metrics_summary(p)
                        metrics_payload = {
                            "coherence": summary.get("coherence", f"{float(ns.get('C_emo', 0.5)) * 100:.0f}%"),
                            "growth": summary.get("growth_potential", f"{float(ns.get('GAP', 0.3)) * 100:.0f}%"),
                            "growth_potential": summary.get("growth_potential", f"{float(ns.get('GAP', 0.3)) * 100:.0f}%"),
                            "wellness": summary.get("wellness_score", f"{float(ns.get('Quantum', 0.5)) * 100:.0f}%"),
                            "wellness_score": summary.get("wellness_score", f"{float(ns.get('Quantum', 0.5)) * 100:.0f}%"),
                            "risk_level": ns.get("risk_level", "LOW"),
                            "mood_current": ns.get("mood_current", "neutral"),
                            "mood_trend": ns.get("mood_trend", "stable"),
                            # Provide numeric keys too so UIs can render consistently
                            "C_emo": ns.get("C_emo"),
                            "GAP": ns.get("GAP"),
                            "Quantum": ns.get("Quantum"),
                            "engagement": ns.get("engagement"),
                            "anxiety_level": ns.get("anxiety_level"),
                            "stress_level": ns.get("stress_level"),
                        }

                        clients.append({
                            "id": p.get("hardware_id"),
                            "name": p.get("name"),
                            "tier": p.get("subscription_plan") or p.get("tier") or "STANDARD",
                            "subscription_plan": p.get("subscription_plan") or p.get("tier") or "STANDARD",
                            "last_login": p.get("last_login"),
                            "assigned_coach": p.get("assigned_coach") or "",
                            "family_id": p.get("family_id") or "",
                            "company_id": p.get("company_id") or "",
                            "company_name": p.get("company_name") or "",
                            "can_access_nate": p.get("can_access_nate", True),
                            "metrics": metrics_payload,
                            "nevedal_state": {
                                "C_emo": ns.get("C_emo"),
                                "GAP": ns.get("GAP"),
                                "Quantum": ns.get("Quantum"),
                                "risk_level": ns.get("risk_level"),
                            },
                            "total_sessions": int(ns.get("session_count") or 0),
                        })

                    # Ensure any scheduled-session clients show up even if registry is missing/mismatched.
                    if not is_admin and session_client_ids:
                        try:
                            seen = {((c or {}).get("id") or "").strip() for c in (clients or []) if isinstance(c, dict)}
                            for cid in sorted(session_client_ids):
                                if not cid or cid in seen:
                                    continue
                                p = registry_clients_by_id.get(cid) or {}
                                meta = session_client_meta.get(cid) or {}
                                name = (p.get("name") or meta.get("client_name") or cid).strip()
                                fam = (p.get("family_id") or meta.get("family_id") or "").strip()
                                # Metrics (best-effort)
                                try:
                                    m = parietal.load_metrics(p) if p else {}
                                    ns = (m.get("nevedal_state") or {}) if isinstance(m, dict) else {}
                                except Exception:
                                    ns = {}
                                summary = parietal.get_metrics_summary(p) if p else {}
                                metrics_payload = {
                                    "coherence": summary.get("coherence", f"{float(ns.get('C_emo', 0.5)) * 100:.0f}%"),
                                    "growth": summary.get("growth_potential", f"{float(ns.get('GAP', 0.3)) * 100:.0f}%"),
                                    "growth_potential": summary.get("growth_potential", f"{float(ns.get('GAP', 0.3)) * 100:.0f}%"),
                                    "wellness": summary.get("wellness_score", f"{float(ns.get('Quantum', 0.5)) * 100:.0f}%"),
                                    "wellness_score": summary.get("wellness_score", f"{float(ns.get('Quantum', 0.5)) * 100:.0f}%"),
                                    "risk_level": ns.get("risk_level", "LOW"),
                                    "mood_current": ns.get("mood_current", "neutral"),
                                    "mood_trend": ns.get("mood_trend", "stable"),
                                    "C_emo": ns.get("C_emo"),
                                    "GAP": ns.get("GAP"),
                                    "Quantum": ns.get("Quantum"),
                                    "engagement": ns.get("engagement"),
                                    "anxiety_level": ns.get("anxiety_level"),
                                    "stress_level": ns.get("stress_level"),
                                }
                                clients.append({
                                    "id": cid,
                                    "name": name,
                                    "tier": p.get("subscription_plan") or p.get("tier") or "STANDARD",
                                    "subscription_plan": p.get("subscription_plan") or p.get("tier") or "STANDARD",
                                    "last_login": p.get("last_login") or "",
                                    "assigned_coach": p.get("assigned_coach") or coach_username,
                                    "family_id": fam,
                                    "company_id": p.get("company_id") or "",
                                    "company_name": p.get("company_name") or "",
                                    "can_access_nate": p.get("can_access_nate", True),
                                    "metrics": metrics_payload,
                                    "nevedal_state": {
                                        "C_emo": ns.get("C_emo"),
                                        "GAP": ns.get("GAP"),
                                        "Quantum": ns.get("Quantum"),
                                        "risk_level": ns.get("risk_level"),
                                    },
                                    "total_sessions": int(ns.get("session_count") or 0),
                                })
                        except Exception:
                            pass
                    
                    await websocket.send(json.dumps({"type": "coach_clients", "clients": clients}))
            
            # === COACH: GET PRE-SESSION BRIEF ===
            elif t == "get_presession_brief":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    client_id = d.get("client_id")
                    registry = load_registry()
                    client_profile = None
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            client_profile = v["profile"]
                            break
                    
                    if client_profile:
                        metrics = parietal.load_metrics(client_profile)
                        topics = hippocampus.get_topics_discussed(client_profile)
                        breakthroughs = hippocampus.get_breakthroughs(client_profile)
                        recent_memory = hippocampus.recall_full(client_profile, limit=10)
                        
                        # Zoom session insights (Patent 2 Section 16)
                        zoom_sessions = metrics.get("zoom_sessions", [])
                        zoom_summary = []
                        for zs in zoom_sessions[-5:]:
                            zoom_summary.append({
                                "topic": zs.get("topic", ""),
                                "source": zs.get("source", "zoom_meeting"),
                                "start_time": zs.get("start_time", ""),
                                "duration": zs.get("duration", 0),
                                "client_turns_processed": zs.get("client_turns_processed", 0),
                                "ingested_at": zs.get("ingested_at", ""),
                            })

                        # Count sessions by source
                        zoom_meeting_count = sum(1 for zs in zoom_sessions if zs.get("source") == "zoom_meeting")
                        zoom_phone_count = sum(1 for zs in zoom_sessions if zs.get("source") == "zoom_phone")

                        brief = {
                            "client": {
                                "name": client_profile.get("name"),
                                "tier": client_profile.get("tier"),
                                "joined_date": client_profile.get("joined_date"),
                                "total_sessions": client_profile.get("total_sessions_count", 0)
                            },
                            "metrics": metrics.get("nevedal_state", {}),
                            "recent_topics": topics,
                            "recent_breakthroughs": breakthroughs[-5:],
                            "mood_history": metrics.get("nevedal_state", {}).get("mood_history", []),
                            "recent_conversations": recent_memory[-5:],
                            "family_id": client_profile.get("family_id"),
                            "zoom_sessions": zoom_summary,
                            "zoom_meeting_count": zoom_meeting_count,
                            "zoom_phone_count": zoom_phone_count,
                        }
                        
                        await websocket.send(json.dumps({"type": "presession_brief", "brief": brief}))

            # === ADMIN/COACH: GET CLIENT CONVERSATION HISTORY ===
            elif t == "admin_get_client_history":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    client_id = d.get("client_id")
                    registry = load_registry()
                    client_profile_hist = None
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            client_profile_hist = v["profile"]
                            break
                    if client_profile_hist:
                        memories = hippocampus.recall_full(client_profile_hist, limit=d.get("limit", 50))
                        await websocket.send(json.dumps({
                            "type": "client_history_data",
                            "client_id": client_id,
                            "history": memories
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "client_history_data",
                            "client_id": client_id,
                            "history": [],
                            "error": "Client not found"
                        }))

            # === COACH: SESSION NOTES (CRUD-lite) ===
            elif t in ("coach_get_session_notes", "coach_add_session_note", "upload_session_note"):
                """
                Coach session notes are stored in a single JSON file keyed by folder.

                Keys:
                  - family:<family_id> for family folders
                  - client:<client_id> for individual/client folders
                """
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue

                def _folder_key(family_id: str, client_id: str) -> str:
                    fid = (family_id or "").strip()
                    cid = (client_id or "").strip()
                    if fid:
                        return f"family:{fid}"
                    if cid:
                        return f"client:{cid}"
                    return "unknown"

                # Load store
                store = load_json_file(COACH_SESSION_NOTES_FILE, {}) or {}
                if not isinstance(store, dict):
                    store = {}

                if t == "coach_get_session_notes":
                    client_id = d.get("client_id") or ""
                    family_id = d.get("family_id") or ""
                    folder = d.get("folder_id") or ""
                    key = (folder.strip() or _folder_key(family_id, client_id))
                    notes = store.get(key, []) or []
                    await websocket.send(json.dumps({
                        "type": "coach_session_notes",
                        "folder_id": key,
                        "notes": notes[-200:],  # cap
                    }))

                else:
                    # Add note (also supports legacy upload_session_note)
                    note_text = (d.get("note_text") or d.get("text") or "").strip()
                    if not note_text:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing note_text"}))
                        continue

                    client_id = d.get("client_id") or ""
                    family_id = d.get("family_id") or ""
                    folder = d.get("folder_id") or ""
                    key = (folder.strip() or _folder_key(family_id, client_id))

                    entry = {
                        "id": f"NOTE_{uuid.uuid4().hex[:10]}",
                        "created_at": datetime.datetime.now().isoformat(),
                        "coach_username": current_username or current_profile.get("name") or "",
                        "coach_id": current_profile.get("hardware_id") or "",
                        "client_id": client_id,
                        "family_id": family_id,
                        "note_text": note_text[:8000],
                        "share_with_nate": bool(d.get("share_with_nate", False)),
                    }

                    store.setdefault(key, [])
                    if not isinstance(store[key], list):
                        store[key] = []
                    store[key].append(entry)
                    # Keep last N per folder
                    store[key] = store[key][-400:]

                    save_json_file(COACH_SESSION_NOTES_FILE, store)

                    # Optional: enqueue learning for admin approval (or auto-approve if explicitly enabled)
                    try:
                        if entry.get("share_with_nate"):
                            queue = load_json_file(COACH_LEARNING_QUEUE_FILE, []) or []
                            if not isinstance(queue, list):
                                queue = []
                            q_item = {
                                "id": f"QL_{uuid.uuid4().hex[:10]}",
                                "created_at": datetime.datetime.now().isoformat(),
                                "status": "APPROVED" if (AUTO_APPROVE_COACH_LEARNING or current_profile.get("role") == "ADMIN") else "PENDING",
                                "source": f"COACH_{entry.get('coach_username') or entry.get('coach_id')}",
                                "category": "coach_session_note",
                                "folder_id": key,
                                "client_id": client_id,
                                "family_id": family_id,
                                "content": entry.get("note_text", "")[:4000],
                                "raw_note_id": entry.get("id"),
                            }
                            queue.append(q_item)
                            queue = compact_coach_learning_queue(queue)
                            save_json_file(COACH_LEARNING_QUEUE_FILE, queue)

                            if q_item["status"] == "APPROVED":
                                try:
                                    night_school.add_learning(
                                        content=q_item["content"],
                                        source=q_item["source"],
                                        filename=f"{q_item['id']}.txt",
                                        category=q_item["category"],
                                    )
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    await websocket.send(json.dumps({
                        "type": "coach_session_note_saved",
                        "folder_id": key,
                        "note": entry,
                    }))
                    await websocket.send(json.dumps({
                        "type": "coach_session_notes",
                        "folder_id": key,
                        "notes": store.get(key, [])[-200:],
                    }))

            # === COACH: LIVE SESSION (notes stream + observation feed + biometrics) ===
            elif t in ("coach_start_live_session", "coach_live_note", "coach_live_biometric_update", "coach_end_live_session"):
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue

                live_store = load_json_file(COACH_LIVE_SESSIONS_FILE, {}) or {}
                if not isinstance(live_store, dict):
                    live_store = {}

                if t == "coach_start_live_session":
                    client_id = (d.get("client_id") or "").strip()
                    family_id = (d.get("family_id") or "").strip()
                    session_label = (d.get("label") or "").strip()
                    meeting_url = (d.get("meeting_url") or "").strip()
                    zoom_meeting_id = (d.get("zoom_meeting_id") or "").strip()
                    assist_enabled = bool(d.get("assist_enabled", True))
                    schedule_session_id = (d.get("schedule_session_id") or d.get("session_id") or "").strip()
                    scheduled_minutes = d.get("scheduled_duration_minutes")
                    try:
                        scheduled_minutes = int(scheduled_minutes) if scheduled_minutes is not None else None
                    except Exception:
                        scheduled_minutes = None
                    live_id = f"LS_{uuid.uuid4().hex[:10]}"

                    live_store[live_id] = {
                        "id": live_id,
                        "created_at": datetime.datetime.now().isoformat(),
                        "started_at": datetime.datetime.now().isoformat(),
                        "ended_at": "",
                        "status": "ACTIVE",
                        "coach_username": current_username or current_profile.get("name") or "",
                        "coach_id": current_profile.get("hardware_id") or "",
                        "client_id": client_id,
                        "family_id": family_id,
                        "schedule_session_id": schedule_session_id,
                        "scheduled_duration_minutes": scheduled_minutes,
                        "label": session_label,
                        "meeting_url": meeting_url,
                        "zoom_meeting_id": zoom_meeting_id,
                        "assist_enabled": assist_enabled,
                        "notes": [],
                        "observations": [],
                    }
                    live_store = compact_live_store(live_store)
                    save_json_file(COACH_LIVE_SESSIONS_FILE, live_store)
                    await websocket.send(json.dumps({
                        "type": "coach_live_session_started",
                        "live_session": live_store[live_id],
                    }))

                elif t == "coach_live_note":
                    live_id = (d.get("live_session_id") or "").strip()
                    text = (d.get("text") or d.get("note_text") or "").strip()
                    if not live_id or not text:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing live_session_id or text"}))
                        continue
                    sess = live_store.get(live_id)
                    if not sess:
                        await websocket.send(json.dumps({"type": "error", "message": "Live session not found"}))
                        continue
                    if sess.get("status") != "ACTIVE":
                        await websocket.send(json.dumps({"type": "error", "message": "Live session not active"}))
                        continue

                    note = {
                        "id": f"LSN_{uuid.uuid4().hex[:10]}",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "text": text[:4000],
                    }
                    sess_notes = sess.get("notes") or []
                    if not isinstance(sess_notes, list):
                        sess_notes = []
                    sess_notes.append(note)
                    sess["notes"] = sess_notes[-600:]

                    # Lightweight heuristic "observation" (no AI dependency yet)
                    obs = None
                    if sess.get("assist_enabled"):
                        lower = text.lower()
                        if any(k in lower for k in ("longing", "need", "i never", "i always", "i feel", "i'm hurt", "i am hurt")):
                            obs = {
                                "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                "timestamp": datetime.datetime.now().isoformat(),
                                "type": "LONGING_SIGNAL",
                                "message": "Possible longing signal detected. Consider slowing down and asking for the underlying need in one sentence.",
                                "evidence": text[:220],
                            }
                        elif any(k in lower for k in ("fix", "solution", "should", "just", "advice")):
                            obs = {
                                "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                "timestamp": datetime.datetime.now().isoformat(),
                                "type": "FIXING_SIGNAL",
                                "message": "Possible 'fixing' move. Consider: 'Before solutions, can you reflect what you heard and what it meant to them?'",
                                "evidence": text[:220],
                            }
                        elif any(k in lower for k in ("angry", "shut down", "silent", "leave", "divorce")):
                            obs = {
                                "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                "timestamp": datetime.datetime.now().isoformat(),
                                "type": "ESCALATION_SIGNAL",
                                "message": "Escalation cue. Consider a brief regulation pause + name the cycle without blame.",
                                "evidence": text[:220],
                            }

                    if obs:
                        sess_obs = sess.get("observations") or []
                        if not isinstance(sess_obs, list):
                            sess_obs = []
                        sess_obs.append(obs)
                        sess["observations"] = sess_obs[-400:]
                        await websocket.send(json.dumps({
                            "type": "coach_live_observation",
                            "live_session_id": live_id,
                            "observation": obs,
                        }))

                    live_store[live_id] = sess
                    live_store = compact_live_store(live_store)
                    save_json_file(COACH_LIVE_SESSIONS_FILE, live_store)
                    await websocket.send(json.dumps({
                        "type": "coach_live_note_ack",
                        "live_session_id": live_id,
                        "note": note,
                    }))

                elif t == "coach_live_biometric_update":
                    # ================================================================
                    # REAL-TIME BIOMETRIC STREAMING DURING LIVE SESSIONS
                    # Connects to Nevedal Engine for C_emo calculation
                    # ================================================================
                    live_id = (d.get("live_session_id") or "").strip()
                    if not live_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing live_session_id"}))
                        continue
                    
                    sess = live_store.get(live_id)
                    if not sess:
                        await websocket.send(json.dumps({"type": "error", "message": "Live session not found"}))
                        continue
                    
                    if sess.get("status") != "ACTIVE":
                        await websocket.send(json.dumps({"type": "error", "message": "Live session not active"}))
                        continue
                    
                    # Extract biometric data
                    biometrics = d.get("biometrics", {})
                    user_id = d.get("user_id") or current_profile.get("hardware_id", "")
                    dyad_partner_id = d.get("dyad_partner_id") or sess.get("client_id", "")
                    
                    if not biometrics:
                        continue  # Skip empty biometric updates silently
                    
                    # Initialize biometrics storage if not exists
                    if "biometrics" not in sess:
                        sess["biometrics"] = []
                    
                    # Create biometric record
                    bio_record = {
                        "id": f"LSB_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.datetime.now().isoformat(),
                        "user_id": user_id,
                        "dyad_partner_id": dyad_partner_id,
                        **biometrics  # voice_pitch, voice_energy, voice_stress, etc.
                    }
                    
                    # Process through Nevedal Engine if handler available
                    nevedal_state = None
                    observation = None
                    
                    try:
                        # Import Nevedal handler
                        from app.websocket.nevedal_handlers import NevedalHandler
                        
                        # Get or create Nevedal handler
                        if not hasattr(websocket, '_nevedal_handler'):
                            websocket._nevedal_handler = NevedalHandler(DATA_DIR, None)
                        
                        handler = websocket._nevedal_handler
                        
                        # Process biometrics through Nevedal Engine
                        state = handler.engine.process_biometrics(
                            session_id=live_id,
                            user_id=user_id,
                            dyad_partner_id=dyad_partner_id,
                            biometrics=biometrics,
                            context="live_session"
                        )
                        
                        if state:
                            bio_record["c_emo"] = state.c_emo
                            bio_record["gap"] = state.gap
                            bio_record["stability"] = state.stability
                            bio_record["trend"] = state.trend
                            bio_record["cee_window"] = state.cee_window
                            
                            # Generate observation if significant change detected
                            if sess.get("assist_enabled"):
                                # Check for dysregulation (C_emo drop)
                                if state.c_emo < 0.3 and state.trend == "FALLING":
                                    observation = {
                                        "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                        "timestamp": datetime.datetime.now().isoformat(),
                                        "type": "DYSREGULATION_DETECTED",
                                        "message": f"Emotional coherence dropping (C_emo: {state.c_emo:.2f}). Consider a grounding pause or regulation exercise.",
                                        "evidence": f"C_emo: {state.c_emo:.2f}, GAP: {state.gap:.2f}, Trend: {state.trend}",
                                        "source": "biometrics"
                                    }
                                
                                # Check for breakthrough moment (high coherence)
                                elif state.cee_window and state.c_emo > 0.9:
                                    observation = {
                                        "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                        "timestamp": datetime.datetime.now().isoformat(),
                                        "type": "BREAKTHROUGH_MOMENT",
                                        "message": f"Strong emotional coherence detected (C_emo: {state.c_emo:.2f}). CEE window active - this is a therapeutic opportunity.",
                                        "evidence": f"C_emo: {state.c_emo:.2f}, CEE Duration: {state.cee_duration_seconds}s",
                                        "source": "biometrics"
                                    }
                                
                                # Check for high GAP (dysynchrony)
                                elif state.gap > 0.5:
                                    observation = {
                                        "id": f"LSO_{uuid.uuid4().hex[:10]}",
                                        "timestamp": datetime.datetime.now().isoformat(),
                                        "type": "HIGH_GAP_DETECTED",
                                        "message": f"High emotional gap detected (GAP: {state.gap:.2f}). Consider checking in with the client.",
                                        "evidence": f"GAP: {state.gap:.2f}, Stability: {state.stability:.2f}",
                                        "source": "biometrics"
                                    }
                            
                            nevedal_state = {
                                "c_emo": state.c_emo,
                                "gap": state.gap,
                                "stability": state.stability,
                                "trend": state.trend,
                                "cee_window": state.cee_window,
                                "cee_duration_seconds": state.cee_duration_seconds,
                                "session_peak_c_emo": state.session_peak_c_emo,
                            }
                    except ImportError as ie:
                        print(f"[LiveBiometrics] Nevedal import not available: {ie}")
                    except Exception as e:
                        print(f"[LiveBiometrics] Nevedal processing error: {e}")
                    
                    # Store biometric record (keep last 500)
                    sess["biometrics"].append(bio_record)
                    sess["biometrics"] = sess["biometrics"][-500:]
                    
                    # Store observation if generated
                    if observation:
                        sess_obs = sess.get("observations") or []
                        if not isinstance(sess_obs, list):
                            sess_obs = []
                        sess_obs.append(observation)
                        sess["observations"] = sess_obs[-400:]
                        
                        # Send observation to coach
                        await websocket.send(json.dumps({
                            "type": "coach_live_observation",
                            "live_session_id": live_id,
                            "observation": observation,
                        }))
                    
                    # Save session
                    live_store[live_id] = sess
                    save_json_file(COACH_LIVE_SESSIONS_FILE, live_store)
                    
                    # Send biometric ack with Nevedal state
                    await websocket.send(json.dumps({
                        "type": "coach_live_biometric_ack",
                        "live_session_id": live_id,
                        "biometric_id": bio_record["id"],
                        "nevedal_state": nevedal_state,
                    }))

                else:
                    # end
                    live_id = (d.get("live_session_id") or "").strip()
                    share_with_nate = bool(d.get("share_with_nate", False))
                    if not live_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing live_session_id"}))
                        continue
                    sess = live_store.get(live_id)
                    if not sess:
                        await websocket.send(json.dumps({"type": "error", "message": "Live session not found"}))
                        continue
                    sess["status"] = "ENDED"
                    sess["ended_at"] = datetime.datetime.now().isoformat()
                    live_store[live_id] = sess
                    live_store = compact_live_store(live_store)
                    save_json_file(COACH_LIVE_SESSIONS_FILE, live_store)

                    # Compute interaction time (anti-gaming baseline):
                    # - only counts when notes are being sent regularly
                    # - capped at scheduled duration (prevents "extend for pay")
                    interaction_seconds = 0
                    billable_seconds = 0
                    scheduled_seconds = 0
                    try:
                        sched_min = sess.get("scheduled_duration_minutes")
                        if isinstance(sched_min, (int, float)) and sched_min > 0:
                            scheduled_seconds = int(float(sched_min) * 60)
                    except Exception:
                        scheduled_seconds = 0

                    try:
                        # Build sorted note timestamps
                        notes = sess.get("notes") or []
                        ts = []
                        for n in notes:
                            tss = (n.get("timestamp") or "").strip()
                            if not tss:
                                continue
                            try:
                                ts.append(datetime.datetime.fromisoformat(tss))
                            except Exception:
                                continue
                        ts.sort()

                        # Max gap to count as "continuous interaction"
                        max_gap = 120  # seconds
                        # Count between notes if close enough
                        for i in range(1, len(ts)):
                            delta = (ts[i] - ts[i-1]).total_seconds()
                            if delta <= max_gap:
                                interaction_seconds += int(delta)
                        # Count tail from last note to end (up to max_gap)
                        if ts:
                            try:
                                end_dt = datetime.datetime.fromisoformat(sess.get("ended_at") or "")
                                tail = (end_dt - ts[-1]).total_seconds()
                                if 0 < tail <= max_gap:
                                    interaction_seconds += int(tail)
                            except Exception:
                                pass
                    except Exception:
                        interaction_seconds = 0

                    if scheduled_seconds > 0:
                        billable_seconds = min(interaction_seconds, scheduled_seconds)
                    else:
                        # fallback: cap by wall clock duration if present
                        try:
                            start_dt = datetime.datetime.fromisoformat(sess.get("started_at") or sess.get("created_at") or "")
                            end_dt = datetime.datetime.fromisoformat(sess.get("ended_at") or "")
                            wall = int((end_dt - start_dt).total_seconds())
                            billable_seconds = min(interaction_seconds, max(0, wall))
                        except Exception:
                            billable_seconds = interaction_seconds

                    # Record compensation ledger entry (no payout amount yet)
                    try:
                        ledger = load_json_file(COACH_COMPENSATION_LEDGER_FILE, []) or []
                        if not isinstance(ledger, list):
                            ledger = []
                        ledger_entry = {
                            "id": f"PAY_{uuid.uuid4().hex[:10]}",
                            "created_at": datetime.datetime.now().isoformat(),
                            "coach_id": sess.get("coach_id") or "",
                            "coach_username": sess.get("coach_username") or "",
                            "client_id": sess.get("client_id") or "",
                            "family_id": sess.get("family_id") or "",
                            "live_session_id": live_id,
                            "schedule_session_id": sess.get("schedule_session_id") or "",
                            "zoom_meeting_id": sess.get("zoom_meeting_id") or "",
                            "meeting_url": sess.get("meeting_url") or "",
                            "label": sess.get("label") or "",
                            "started_at": sess.get("started_at") or sess.get("created_at") or "",
                            "ended_at": sess.get("ended_at") or "",
                            "scheduled_duration_seconds": scheduled_seconds,
                            "interaction_seconds": int(interaction_seconds),
                            "billable_seconds": int(billable_seconds),
                            "status": "PENDING",
                        }
                        ledger.append(ledger_entry)
                        save_json_file(COACH_COMPENSATION_LEDGER_FILE, ledger[-5000:])
                    except Exception:
                        pass

                    # Also write into SessionTracker as a COACH session (so analytics can use it)
                    try:
                        client_for_session = sess.get("client_id") or ""
                        coach_for_session = sess.get("coach_id") or ""
                        srec = session_tracker.create_session(client_for_session, session_type="COACH", coach_id=coach_for_session)
                        # Attach billing-time metadata
                        srec["scheduled_duration_seconds"] = scheduled_seconds
                        srec["interaction_seconds"] = int(interaction_seconds)
                        srec["billable_seconds"] = int(billable_seconds)
                        srec["live_session_id"] = live_id
                        srec["schedule_session_id"] = sess.get("schedule_session_id") or ""
                        srec["zoom_meeting_id"] = sess.get("zoom_meeting_id") or ""
                        srec["meeting_url"] = sess.get("meeting_url") or ""
                        srec["label"] = sess.get("label") or ""
                        srec["coach_notes"] = "\n".join([(n.get("text") or "") for n in (sess.get("notes") or []) if n.get("text")])[:6000]
                        # Persist modified session record
                        sessions_all = session_tracker.load_sessions()
                        for i in range(len(sessions_all) - 1, -1, -1):
                            if sessions_all[i].get("session_id") == srec.get("session_id"):
                                sessions_all[i] = srec
                                break
                        session_tracker.save_sessions(sessions_all)
                    except Exception:
                        pass

                    if share_with_nate:
                        try:
                            notes = sess.get("notes") or []
                            joined = "\n".join([n.get("text", "") for n in notes if n.get("text")])[:6000]
                            if not joined.strip():
                                await websocket.send(json.dumps({
                                    "type": "coach_learning_not_enqueued",
                                    "live_session_id": live_id,
                                    "reason": "NO_NOTES",
                                }))
                            else:
                                queue = load_json_file(COACH_LEARNING_QUEUE_FILE, []) or []
                                if not isinstance(queue, list):
                                    queue = []
                                q_item = {
                                    "id": f"QL_{uuid.uuid4().hex[:10]}",
                                    "created_at": datetime.datetime.now().isoformat(),
                                    "status": "APPROVED" if (AUTO_APPROVE_COACH_LEARNING or current_profile.get("role") == "ADMIN") else "PENDING",
                                    "source": f"COACH_{sess.get('coach_username') or sess.get('coach_id')}",
                                    "category": "coach_live_session_notes",
                                    "folder_id": (f"family:{sess.get('family_id')}" if sess.get("family_id") else f"client:{sess.get('client_id')}"),
                                    "client_id": sess.get("client_id") or "",
                                    "family_id": sess.get("family_id") or "",
                                    "coach_id": sess.get("coach_id") or "",
                                    "coach_username": sess.get("coach_username") or "",
                                    "schedule_session_id": sess.get("schedule_session_id") or "",
                                    "zoom_meeting_id": sess.get("zoom_meeting_id") or "",
                                    "meeting_url": sess.get("meeting_url") or "",
                                    "label": sess.get("label") or "",
                                    "started_at": sess.get("started_at") or sess.get("created_at") or "",
                                    "ended_at": sess.get("ended_at") or "",
                                    "content": joined,
                                    "raw_live_session_id": live_id,
                                }
                                queue.append(q_item)
                                queue = compact_coach_learning_queue(queue)
                                save_json_file(COACH_LEARNING_QUEUE_FILE, queue)

                                # Ack to coach UI for clear feedback
                                await websocket.send(json.dumps({
                                    "type": "coach_learning_enqueued",
                                    "live_session_id": live_id,
                                    "queue_id": q_item.get("id"),
                                    "status": q_item.get("status"),
                                }))

                                # Push to connected admins for real-time approvals UX
                                try:
                                    reg = load_registry()
                                    admin_ids = [v.get("profile", {}).get("hardware_id") for v in reg.values() if v.get("profile", {}).get("role") == "ADMIN"]
                                    payload = json.dumps({
                                        "type": "admin_coach_learning_queue_new",
                                        "item": q_item,
                                    })
                                    for aid in admin_ids:
                                        if not aid:
                                            continue
                                        for aws in list(getattr(cortex, "sockets", {}).get(aid, set()) or []):
                                            try:
                                                await aws.send(payload)
                                            except Exception:
                                                continue
                                except Exception:
                                    pass

                                if q_item["status"] == "APPROVED":
                                    try:
                                        night_school.add_learning(
                                            content=q_item["content"],
                                            source=q_item["source"],
                                            filename=f"{q_item['id']}.txt",
                                            category=q_item["category"],
                                        )
                                    except Exception:
                                        pass
                        except Exception:
                            # Surface enqueue failures to coach UI (otherwise it's invisible)
                            try:
                                await websocket.send(json.dumps({
                                    "type": "coach_learning_not_enqueued",
                                    "live_session_id": live_id,
                                    "reason": "ERROR",
                                }))
                            except Exception:
                                pass

                    await websocket.send(json.dumps({
                        "type": "coach_live_session_ended",
                        "live_session_id": live_id,
                    }))

            # === ADMIN: COACH LEARNING QUEUE (approve/reject) ===
            elif t in ("admin_get_coach_learning_queue", "admin_approve_coach_learning", "admin_reject_coach_learning"):
                if not current_profile or current_profile.get("role") != "ADMIN":
                    await websocket.send(json.dumps({"type": "error", "message": "ADMIN_ONLY"}))
                    continue

                queue = load_json_file(COACH_LEARNING_QUEUE_FILE, []) or []
                if not isinstance(queue, list):
                    queue = []

                if t == "admin_get_coach_learning_queue":
                    status = (d.get("status") or "PENDING").upper()
                    filtered = [q for q in queue if (q.get("status") or "").upper() == status] if status else queue
                    await websocket.send(json.dumps({
                        "type": "admin_coach_learning_queue",
                        "status": status,
                        "items": filtered[-300:],
                    }))

                else:
                    qid = (d.get("queue_id") or d.get("id") or "").strip()
                    if not qid:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing queue_id"}))
                        continue
                    updated = False
                    for item in queue:
                        if item.get("id") == qid:
                            if t == "admin_approve_coach_learning":
                                item["status"] = "APPROVED"
                                item["approved_at"] = datetime.datetime.now().isoformat()
                                item["approved_by"] = current_profile.get("name") or "ADMIN"
                                # Optional admin edits
                                edited = (d.get("edited_content") or "").strip()
                                if edited:
                                    item["content"] = edited[:6000]
                                # Push into Night School
                                try:
                                    night_school.add_learning(
                                        content=(item.get("content") or "")[:6000],
                                        source=item.get("source") or "COACH_UNKNOWN",
                                        filename=f"{item.get('id')}.txt",
                                        category=item.get("category") or "coach_learning",
                                    )
                                except Exception:
                                    pass
                            else:
                                item["status"] = "REJECTED"
                                item["rejected_at"] = datetime.datetime.now().isoformat()
                                item["rejected_by"] = current_profile.get("name") or "ADMIN"
                                item["rejection_reason"] = (d.get("reason") or "").strip()[:400]
                            updated = True
                            break

                    if updated:
                        queue = compact_coach_learning_queue(queue)
                        save_json_file(COACH_LEARNING_QUEUE_FILE, queue)
                        await websocket.send(json.dumps({
                            "type": "admin_coach_learning_queue_updated",
                            "queue_id": qid,
                        }))
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Queue item not found"}))
            
            # === COACH: GET CALENDAR ===
            elif t == "fetch_coach_calendar":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    month = d.get("month")
                    year = d.get("year")
                    is_admin_cal = current_profile.get("role") == "ADMIN"
                    try:
                        if is_admin_cal:
                            # ADMIN: return ALL sessions platform-wide for the month
                            import datetime as _dt_cal
                            now = _dt_cal.datetime.now()
                            try:
                                cal_month = int(month) if month is not None else now.month
                            except Exception:
                                cal_month = now.month
                            try:
                                cal_year = int(year) if year is not None else now.year
                            except Exception:
                                cal_year = now.year

                            all_sessions = []
                            try:
                                sessions_raw = load_json_file(SESSIONS_FILE, []) or []
                                if not isinstance(sessions_raw, list):
                                    sessions_raw = []
                                for ses in sessions_raw:
                                    if not isinstance(ses, dict):
                                        continue
                                    st = (ses.get("scheduled_start") or ses.get("date") or "").replace("Z", "+00:00")
                                    try:
                                        st_dt = _dt_cal.datetime.fromisoformat(st) if st else None
                                    except Exception:
                                        st_dt = None
                                    if not st_dt:
                                        continue
                                    if st_dt.month != cal_month or st_dt.year != cal_year:
                                        continue
                                    en = (ses.get("scheduled_end") or "").replace("Z", "+00:00")
                                    try:
                                        en_dt = _dt_cal.datetime.fromisoformat(en) if en else None
                                    except Exception:
                                        en_dt = None
                                    dur_min = 50
                                    if en_dt and st_dt and en_dt > st_dt:
                                        dur_min = max(5, int((en_dt - st_dt).total_seconds() / 60))
                                    all_sessions.append({
                                        "id": ses.get("session_id") or ses.get("id") or "",
                                        "coach_id": ses.get("coach_id") or "",
                                        "client_id": ses.get("client_id") or "",
                                        "client_name": ses.get("client_name") or "",
                                        "family_id": ses.get("family_id") or "",
                                        "date": st_dt.date().isoformat(),
                                        "time": st_dt.strftime("%H:%M"),
                                        "type": ses.get("session_type") or "COACH",
                                        "duration_minutes": dur_min,
                                        "platform": ses.get("platform") or "Zoom",
                                        "zoom_link": ses.get("zoom_link") or "",
                                        "status": ses.get("status") or "scheduled",
                                        "notes": ses.get("notes") or "",
                                    })
                            except Exception:
                                pass
                            # Also pull from each coach's schedule.json
                            try:
                                coaches_dir = VAULT_ROOT / "Coaches"
                                if coaches_dir.exists():
                                    for coach_dir in coaches_dir.iterdir():
                                        sched_file = coach_dir / "schedule.json"
                                        if sched_file.exists():
                                            try:
                                                with open(sched_file, "r") as sf:
                                                    sched = json.load(sf)
                                                for s in (sched if isinstance(sched, list) else []):
                                                    try:
                                                        dt_str = (s.get("date") or "").replace("Z", "+00:00")
                                                        sdt = _dt_cal.datetime.fromisoformat(dt_str) if dt_str else None
                                                        if sdt and sdt.month == cal_month and sdt.year == cal_year:
                                                            s["coach_id"] = s.get("coach_id") or coach_dir.name
                                                            all_sessions.append(s)
                                                    except Exception:
                                                        continue
                                            except Exception:
                                                continue
                            except Exception:
                                pass

                            calendar_data = {
                                "month": cal_month,
                                "year": cal_year,
                                "schedule": all_sessions,
                                "availability": [],
                            }
                        else:
                            calendar_data = coach_nexus_v2.get_calendar_data(current_profile, month, year)
                        await websocket.send(json.dumps({
                            "type": "coach_calendar_data",
                            "data": calendar_data
                        }))
                    except Exception as e:
                        # Don't drop the socket on calendar errors; surface them to the UI.
                        print(f">>> [ERROR] Coach calendar failed: {type(e).__name__}: {e}")
                        await websocket.send(json.dumps({
                            "type": "coach_calendar_data",
                            "data": {"month": month, "year": year, "schedule": [], "availability": []},
                            "error": "CALENDAR_LOAD_FAILED"
                        }))
            
            # === COACH: GET RECORDED SESSIONS ===
            elif t == "fetch_coach_sessions":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    filter_type = d.get("filter", "all")
                    sessions = coach_nexus_v2.get_recorded_sessions(current_profile, filter_type)
                    await websocket.send(json.dumps({
                        "type": "coach_sessions_data",
                        "data": {"sessions": sessions}
                    }))
            
            # === COACH: CANCEL SESSION ===
            elif t == "coach_cancel_session":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    result = coach_nexus_v2.cancel_session(
                        current_profile,
                        d.get("session_id", ""),
                        d.get("reason", ""),
                        d.get("send_reschedule_link", True)
                    )
                    await websocket.send(json.dumps({
                        "type": "session_cancelled",
                        "status": result
                    }))
            
            # === COACH: GET COACHING ADVICE ===
            elif t == "fetch_coaching_advice":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    advice = coach_nexus_v2.get_coaching_advice(
                        current_profile,
                        d.get("session_id", "")
                    )
                    await websocket.send(json.dumps({
                        "type": "coaching_advice_data",
                        "data": advice
                    }))
            
            # === COACH: AI QUERY WITH CLIENT CONTEXT ===
            elif t == "coach_nate_query":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    query = d.get("nate_query", d.get("text", ""))
                    client_context = d.get("client_id")
                    
                    if client_context:
                        registry = load_registry()
                        brief = coach_nexus_v2.get_presession_brief(
                            current_profile,
                            client_context,
                            registry
                        )
                        augmented_query = f"[Coach asking about {brief.get('client_name', 'client')}]: {query}"
                    else:
                        augmented_query = f"[Coach general query]: {query}"
                    
                    await cortex.process_interaction(current_profile, augmented_query)
            
            # === COACH: SAVE RECORDING METADATA ===
            elif t == "save_recording":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    result = coach_nexus_v2.save_recording_metadata(
                        current_profile,
                        d.get("session_id", ""),
                        d.get("client_id", ""),
                        d.get("client_name", ""),
                        d.get("duration", 50),
                        d.get("platform", "Zoom"),
                        d.get("biometrics_captured", True)
                    )
                    await websocket.send(json.dumps({
                        "type": "recording_saved",
                        "status": result
                    }))
            
            # === DOJO: START TRAINING SESSION ===
            elif t == "dojo_start":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    if night_school_handler:
                        await night_school_handler.handle_start_dojo(websocket, d, current_profile)
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Dojo module not available"}))
            
            # === DOJO: SEND TEST MESSAGE ===
            elif t == "dojo_test_message":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    if night_school_handler:
                        await night_school_handler.handle_dojo_message(websocket, d, current_profile)
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Dojo module not available"}))
            
            # === DOJO: END TRAINING SESSION ===
            elif t == "dojo_end":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    if night_school_handler:
                        await night_school_handler.handle_end_dojo(websocket, d, current_profile)
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Dojo module not available"}))
            
            # === DOJO: GENERATE GANTT CHART (Project PM & Business only) ===
            elif t == "dojo_generate_gantt":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                dojo_mode = (d.get("mode") or "").lower()
                if dojo_mode not in ("project_pm", "business"):
                    await websocket.send(json.dumps({"type": "error", "message": "Gantt export is only available for Project PM and Business modes"}))
                    continue
                try:
                    from app.services.pm_export_service import extract_project_data, generate_gantt_pdf, save_export_file
                    await websocket.send(json.dumps({"type": "dojo_export_status", "status": "extracting", "message": "Analyzing conversation..."}))
                    conversation = d.get("messages", [])
                    project_data = await extract_project_data(conversation, AZURE_API_KEY, AZURE_ENDPOINT)
                    await websocket.send(json.dumps({"type": "dojo_export_status", "status": "generating", "message": "Rendering Gantt chart..."}))
                    pdf_bytes = generate_gantt_pdf(project_data)
                    result = save_export_file(pdf_bytes, "gantt_pdf", dojo_mode)
                    await websocket.send(json.dumps({
                        "type": "dojo_gantt_ready",
                        "file_id": result["file_id"],
                        "filename": result["filename"],
                        "download_url": f"/api/dojo/download-export/{result['file_id']}",
                        "project_name": project_data.get("project_name", "Project Plan"),
                        "task_count": len(project_data.get("tasks", [])),
                    }))
                except Exception as e:
                    logger.error(f"Gantt generation failed: {e}")
                    await websocket.send(json.dumps({"type": "error", "message": "GANTT_GENERATION_FAILED"}))

            # === DOJO: GENERATE EXCEL EXPORT (Project PM & Business only) ===
            elif t == "dojo_generate_excel":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                dojo_mode = (d.get("mode") or "").lower()
                if dojo_mode not in ("project_pm", "business"):
                    await websocket.send(json.dumps({"type": "error", "message": "Excel export is only available for Project PM and Business modes"}))
                    continue
                try:
                    from app.services.pm_export_service import extract_project_data, generate_excel, save_export_file
                    await websocket.send(json.dumps({"type": "dojo_export_status", "status": "extracting", "message": "Analyzing conversation..."}))
                    conversation = d.get("messages", [])
                    project_data = await extract_project_data(conversation, AZURE_API_KEY, AZURE_ENDPOINT)
                    await websocket.send(json.dumps({"type": "dojo_export_status", "status": "generating", "message": "Building Excel workbook..."}))
                    xlsx_bytes = generate_excel(project_data)
                    result = save_export_file(xlsx_bytes, "excel", dojo_mode)
                    await websocket.send(json.dumps({
                        "type": "dojo_excel_ready",
                        "file_id": result["file_id"],
                        "filename": result["filename"],
                        "download_url": f"/api/dojo/download-export/{result['file_id']}",
                        "project_name": project_data.get("project_name", "Project Plan"),
                        "task_count": len(project_data.get("tasks", [])),
                    }))
                except Exception as e:
                    logger.error(f"Excel generation failed: {e}")
                    await websocket.send(json.dumps({"type": "error", "message": "EXCEL_GENERATION_FAILED"}))

            # =================================================================
            # AVATAR MODE - Top Tier Voice-Driven Avatar Interactions
            # =================================================================
            
            elif t == "avatar_user_speech":
                # Process voice input from avatar mode client
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
                    continue
                
                # Check tier eligibility
                tier = (current_profile.get("tier") or "").upper()
                family_id = current_profile.get("family_id")
                is_eligible = tier in ("TOP_TIER", "SOVEREIGN_CIRCLE") or bool(family_id)
                
                if not is_eligible:
                    await websocket.send(json.dumps({
                        "type": "avatar_error",
                        "message": "Avatar mode is only available for Sovereign Circle members",
                        "upgrade_required": True,
                    }))
                    continue
                
                if avatar_handler:
                    await avatar_handler.handle_avatar_user_speech(websocket, current_profile, d, cortex)
                else:
                    await websocket.send(json.dumps({"type": "error", "message": "Avatar module not available"}))
            
            elif t == "fetch_avatar_config":
                # Get user's avatar customization preferences
                if current_profile:
                    if avatar_handler:
                        config = avatar_handler.load_avatar_config(current_profile.get("hardware_id", ""))
                        await websocket.send(json.dumps({
                            "type": "avatar_config",
                            "config": config,
                        }))
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Avatar module not available"}))
            
            elif t == "save_avatar_config":
                # Save user's avatar customization
                if current_profile:
                    if avatar_handler:
                        success = avatar_handler.save_avatar_config(
                            current_profile.get("hardware_id", ""),
                            d.get("config", {})
                        )
                        await websocket.send(json.dumps({
                            "type": "avatar_config_saved",
                            "success": success,
                        }))
                    else:
                        await websocket.send(json.dumps({"type": "error", "message": "Avatar module not available"}))
            
            elif t == "avatar_start_breathing":
                # Start a breathing exercise with avatar demonstration
                if current_profile and avatar_handler:
                    await avatar_handler.handle_breathing_exercise(websocket, d)
            
            elif t == "avatar_celebration":
                # Trigger celebration animation for milestone
                if current_profile and avatar_handler:
                    await avatar_handler.handle_celebration(websocket, d)
            
            # === GET CLIENT PROFILE (for coaches) ===
            elif t == "get_client_profile":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    client_id = d.get("client_id")
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == client_id:
                            client_profile = v["profile"]
                            safe_profile = {
                                "hardware_id": client_profile.get("hardware_id"),
                                "name": client_profile.get("name"),
                                "email": client_profile.get("email"),
                                "tier": client_profile.get("tier"),
                                "joined_date": client_profile.get("joined_date"),
                                "last_login": client_profile.get("last_login"),
                                "total_sessions_count": client_profile.get("total_sessions_count", 0),
                                "family_id": client_profile.get("family_id"),
                                "assigned_coach_id": client_profile.get("assigned_coach_id")
                            }
                            metrics = parietal.get_metrics_summary(client_profile)
                            await websocket.send(json.dumps({
                                "type": "client_profile_data",
                                "profile": safe_profile,
                                "metrics": metrics
                            }))
                            break
            
            # === CREATE DEPENDENT (Family Member) ===
            elif t == "create_dependent":
                if current_profile:
                    success, result = create_dependent_account(uid, d)
                    if success:
                        await websocket.send(json.dumps({
                            "type": "dependent_created",
                            "message": result
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result
                        }))
            
            # === GET FAMILY MEMBERS ===
            elif t == "get_family_members":
                if current_profile:
                    family_id = current_profile.get("family_id")
                    registry = load_registry()
                    members = []
                    for k, v in registry.items():
                        p = v.get("profile", {})
                        if p.get("family_id") == family_id:
                            members.append({
                                "id": p.get("hardware_id"),
                                "name": p.get("name"),
                                "role": p.get("role"),
                                "tier": p.get("tier"),
                                "is_minor": p.get("is_minor", False),
                                "guardian_id": p.get("guardian_id", "")
                            })
                    await websocket.send(json.dumps({
                        "type": "family_members",
                        "family_id": family_id,
                        "members": members
                    }))
            
            # === NEVEDAL: BIOMETRIC UPDATE ===
            elif t == "biometric_update":
                if current_profile:
                    await nevedal_handler.handle_biometric_update(websocket, d, current_profile)

            # === SANCTUARY: BIOMETRIC SNAPSHOT ===
            elif t == "sanctuary_biometric_snapshot":
                """
                Member shares biometric snapshot during sanctuary session.
                Does NOT replace Nevedal biometrics; this is sanctuary-scoped context.
                """
                if current_profile:
                    sanctuary_id = d.get("sanctuary_id")
                    biometric_data = d.get("biometrics", {}) or {}
                    if sanctuary_id and biometric_data:
                        ok = sanctuary_engine.store_member_biometrics(
                            sanctuary_id=sanctuary_id,
                            member_id=current_profile.get("hardware_id"),
                            biometric_data=biometric_data,
                        )
                        await websocket.send(json.dumps({
                            "type": "sanctuary_biometric_snapshot_ack",
                            "success": ok,
                        }))

            # === SANCTUARY: REALTIME HEART RATE STREAM ===
            elif t == "sanctuary_realtime_hr":
                """
                Real-time HR stream for physiology-aware facilitation.
                Payload: {sanctuary_id, bpm, timestamp?}
                """
                if current_profile:
                    sanctuary_id = d.get("sanctuary_id")
                    bpm = d.get("bpm")
                    ts = d.get("timestamp")
                    if sanctuary_id and bpm is not None:
                        result = sanctuary_engine.update_realtime_heart_rate(
                            sanctuary_id=sanctuary_id,
                            member_id=current_profile.get("hardware_id"),
                            bpm=int(bpm),
                            timestamp=ts,
                        )

                        esc = (result.get("escalation") or {})
                        if esc.get("elevated"):
                            duration = float(esc.get("duration_seconds") or 0)
                            # Send a private support prompt once when crossing ~60s
                            if 60 <= duration <= 75:
                                try:
                                    await websocket.send(json.dumps({
                                        "type": "sanctuary_physiological_support",
                                        "support_type": "elevated_hr",
                                        "message": "I notice your body is activated right now. Would you like to take a moment to breathe before continuing?",
                                        "breathing_exercise": sanctuary_engine.get_breathing_exercise("physiological_sigh"),
                                    }))
                                except Exception:
                                    pass

            # === SANCTUARY: GET BREATHING EXERCISE ===
            elif t == "sanctuary_get_breathing_exercise":
                exercise_type = d.get("exercise_type", "box")
                await websocket.send(json.dumps({
                    "type": "sanctuary_breathing_exercise",
                    "exercise": sanctuary_engine.get_breathing_exercise(exercise_type),
                }))
            
            # === NEVEDAL: SUBSCRIBE ===
            elif t == "nevedal_subscribe":
                await nevedal_handler.handle_subscribe(websocket, d)
            
            # === NEVEDAL: UNSUBSCRIBE ===
            elif t == "nevedal_unsubscribe":
                await nevedal_handler.handle_unsubscribe(websocket, d)
            
            # === NEVEDAL: GET HISTORY ===
            elif t == "nevedal_get_history":
                await nevedal_handler.handle_get_history(websocket, d)
            
            # === NEVEDAL: GET SESSION SUMMARY ===
            elif t == "nevedal_get_session_summary":
                await nevedal_handler.handle_session_summary(websocket, d)
            
            # === NEVEDAL: GET CEE EVENTS ===
            elif t == "nevedal_get_cee_events":
                await nevedal_handler.handle_get_cee_events(websocket, d)
            

            # === ADMIN: GET DYAD SYNC ===
            elif t == "admin_get_dyad_sync":
                if current_profile and current_profile.get("role") == "ADMIN":
                  _dyad_empty = {"type": "dyad_sync_data", "synchrony_score": 0, "grade": "AWAITING", "client_c_emo": 0, "coach_c_emo": 0, "client_timeline": [], "coach_timeline": [], "shared_cees": [], "correlation_coefficient": 0, "lag_time": 0}
                  try:
                    client_id = d.get("client_id")
                    coach_id = d.get("coach_id")
                    session_id = d.get("session_id")  # optional
                    
                    if not client_id or not coach_id:
                        _dyad_empty["error"] = "Missing client_id or coach_id"
                        await websocket.send(json.dumps(_dyad_empty))
                    else:
                        # Load metrics for both
                        registry = load_registry()
                        client_profile = None
                        coach_profile = None
                        
                        for k, v in registry.items():
                            profile = v.get("profile", {})
                            if profile.get("hardware_id") == client_id:
                                client_profile = profile
                            if profile.get("hardware_id") == coach_id:
                                coach_profile = profile
                        
                        if not client_profile or not coach_profile:
                            _dyad_empty["error"] = "Client or coach not found"
                            await websocket.send(json.dumps(_dyad_empty))
                        else:
                            # Get Nevedal states
                            client_metrics = metrics_engine.load_metrics({"role": "CLIENT", "hardware_id": client_id})
                            coach_metrics = metrics_engine.load_metrics({"role": "COACH", "hardware_id": coach_id})
                            
                            client_state = client_metrics.get("nevedal_state", {})
                            coach_state = coach_metrics.get("nevedal_state", {})
                            
                            # Calculate synchrony score (simplified)
                            client_c_emo = client_state.get("C_emo", 0.5)
                            coach_c_emo = coach_state.get("C_emo", 0.5)
                            
                            # Synchrony = 1 - normalized difference
                            diff = abs(client_c_emo - coach_c_emo)
                            synchrony_score = 1.0 - diff
                            
                            # Determine grade
                            if synchrony_score >= 0.85:
                                grade = "EXCELLENT"
                            elif synchrony_score >= 0.70:
                                grade = "GOOD"
                            elif synchrony_score >= 0.55:
                                grade = "MODERATE"
                            else:
                                grade = "DEVELOPING"
                            
                            # Build timeline with all formula variables from Nevedal state history
                            client_timeline = []
                            coach_timeline = []
                            try:
                                client_hist = [
                                    s.to_dict() for s in nevedal_handler.engine.state_history
                                    if s.user_id == client_id
                                ][-50:]
                                coach_hist = [
                                    s.to_dict() for s in nevedal_handler.engine.state_history
                                    if s.user_id == coach_id
                                ][-50:]
                            except Exception:
                                client_hist = []
                                coach_hist = []
                            
                            if client_hist:
                                for h in client_hist:
                                    client_timeline.append({
                                        "timestamp": h.get("timestamp", ""),
                                        "c_emo": h.get("c_emo", client_c_emo),
                                        "p_ent": h.get("p_ent", 0.5),
                                        "t_tunnel": h.get("t_tunnel", 0.5),
                                        "d_distance": h.get("d_distance", 0.5),
                                    })
                            else:
                                for t_off in [0, 15, 30, 45]:
                                    offset = (t_off - 22.5) / 45 * 0.1
                                    client_timeline.append({
                                        "timestamp": t_off,
                                        "c_emo": round(max(0.1, min(1.0, client_c_emo + offset)), 3),
                                        "p_ent": round(max(0.1, min(1.0, client_state.get("p_ent", 0.5) + offset * 0.5)), 3),
                                        "t_tunnel": round(max(0.1, min(1.0, client_state.get("t_tunnel", 0.5) + offset * 0.3)), 3),
                                        "d_distance": round(max(0.1, min(1.0, client_state.get("d_distance", 0.5) - offset * 0.2)), 3),
                                    })
                            
                            if coach_hist:
                                for h in coach_hist:
                                    coach_timeline.append({
                                        "timestamp": h.get("timestamp", ""),
                                        "c_emo": h.get("c_emo", coach_c_emo),
                                        "p_ent": h.get("p_ent", 0.5),
                                        "t_tunnel": h.get("t_tunnel", 0.5),
                                        "d_distance": h.get("d_distance", 0.5),
                                    })
                            else:
                                for t_off in [0, 15, 30, 45]:
                                    offset = (t_off - 22.5) / 45 * 0.08
                                    coach_timeline.append({
                                        "timestamp": t_off,
                                        "c_emo": round(max(0.1, min(1.0, coach_c_emo + offset)), 3),
                                        "p_ent": round(max(0.1, min(1.0, coach_state.get("p_ent", 0.5) + offset * 0.5)), 3),
                                        "t_tunnel": round(max(0.1, min(1.0, coach_state.get("t_tunnel", 0.5) + offset * 0.3)), 3),
                                        "d_distance": round(max(0.1, min(1.0, coach_state.get("d_distance", 0.5) - offset * 0.2)), 3),
                                    })
                            
                            # Shared CEE moments from timeline
                            shared_cees = []
                            min_len = min(len(client_timeline), len(coach_timeline))
                            for idx in range(min_len):
                                ct_cemo = client_timeline[idx].get("c_emo", 0)
                                co_cemo = coach_timeline[idx].get("c_emo", 0)
                                if ct_cemo > 0.75 and co_cemo > 0.75:
                                    shared_cees.append({
                                        "timestamp": client_timeline[idx].get("timestamp", idx),
                                        "client_c_emo": round(ct_cemo, 2),
                                        "coach_c_emo": round(co_cemo, 2)
                                    })
                            
                            correlation_coefficient = synchrony_score * 0.9
                            lag_time = -2.3 if coach_c_emo > client_c_emo else 1.8
                            
                            # Visual biometrics (Patent 4) - include if available
                            visual_biometrics = client_metrics.get("visual_biometrics") or None
                            
                            dyad_response = {
                                "type": "dyad_sync_data",
                                "synchrony_score": round(synchrony_score, 2),
                                "grade": grade,
                                "client_c_emo": round(client_c_emo, 2),
                                "coach_c_emo": round(coach_c_emo, 2),
                                "client_timeline": client_timeline,
                                "coach_timeline": coach_timeline,
                                "shared_cees": shared_cees,
                                "correlation_coefficient": round(correlation_coefficient, 2),
                                "lag_time": round(lag_time, 1),
                            }
                            if visual_biometrics:
                                dyad_response["visual_biometrics"] = visual_biometrics
                            
                            await websocket.send(json.dumps(dyad_response))
                  except Exception as dyad_err:
                    print(f"[Dyad] Error processing dyad sync: {dyad_err}")
                    import traceback
                    traceback.print_exc()
                    _dyad_empty["error"] = str(dyad_err)
                    await websocket.send(json.dumps(_dyad_empty))

            # === ADMIN: GET USER METRICS (RAW) ===
            elif t == "admin_get_user_metrics":
                if current_profile and current_profile.get("role") == "ADMIN":
                    user_id = d.get("user_id") or d.get("hardware_id")
                    if not user_id:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Missing user_id"
                        }))
                    else:
                        try:
                            # Find role (best-effort) so we load the right vault path
                            registry = load_registry()
                            role = "CLIENT"
                            name = ""
                            for _, v in registry.items():
                                p = (v.get("profile") or {})
                                if p.get("hardware_id") == user_id:
                                    role = (p.get("role") or "CLIENT")
                                    name = (p.get("name") or "")
                                    break

                            metrics = metrics_engine.load_metrics({"role": role, "hardware_id": user_id})
                            ns = metrics.get("nevedal_state", {}) or {}

                            # Best-effort "last updated" from metrics file mtime
                            last_updated_iso = ""
                            try:
                                path = metrics_engine._path({"role": role, "hardware_id": user_id})
                                if path:
                                    mtime = os.path.getmtime(path)
                                    last_updated_iso = datetime.datetime.fromtimestamp(mtime).isoformat()
                            except Exception:
                                last_updated_iso = ""

                            await websocket.send(json.dumps({
                                "type": "admin_user_metrics",
                                "user_id": user_id,
                                "name": name,
                                "role": role,
                                "server_time": datetime.datetime.now().isoformat(),
                                "last_updated": last_updated_iso,
                                "nevedal_state": ns,
                            }))
                        except Exception as e:
                            print(f">>> [ERROR] Failed to load metrics for {user_id}: {e}")
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "METRICS_LOAD_FAILED"
                            }))

            # === COACH: GET LIVE SANCTUARY BRIEFING ===
            elif t == "coach_get_briefing":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
                elif current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                else:
                    sanctuary_id = d.get("sanctuary_id")
                    include_transcripts = bool(d.get("include_transcripts", True))
                    max_transcripts = int(d.get("max_transcript_messages", 60) or 60)

                    sanctuary = sanctuary_engine.get_session(sanctuary_id) if sanctuary_id else None
                    if not sanctuary:
                        await websocket.send(json.dumps({"type": "error", "message": "Sanctuary not found"}))
                    else:
                        family_id = sanctuary.get("family_id") or ""

                        # Authorization for COACH: must be assigned to this family (best-effort)
                        if current_profile.get("role") == "COACH":
                            assigned_ok = False
                            try:
                                coach_assigned = ((sanctuary.get("coach_escalation") or {}).get("coach_assigned") or "")
                                if coach_assigned and coach_assigned in (current_username, current_profile.get("hardware_id")):
                                    assigned_ok = True
                            except Exception:
                                assigned_ok = False

                            if not assigned_ok:
                                try:
                                    registry = load_registry()
                                    for _, v in registry.items():
                                        p = (v.get("profile") or {})
                                        if p.get("family_id") == family_id and (
                                            (p.get("assigned_coach_id") and p.get("assigned_coach_id") == current_profile.get("hardware_id"))
                                            or (p.get("assigned_coach") and p.get("assigned_coach") == current_username)
                                        ):
                                            assigned_ok = True
                                            break
                                except Exception:
                                    assigned_ok = False

                            if not assigned_ok:
                                await websocket.send(json.dumps({"type": "error", "message": "COACH_NOT_ASSIGNED"}))
                                continue

                        # Build member profile map
                        member_ids = []
                        try:
                            member_ids.extend([m.get("user_id") for m in (sanctuary.get("members") or []) if m.get("user_id")])
                        except Exception:
                            pass
                        try:
                            member_ids.extend([mid for mid in (sanctuary.get("invited_member_ids") or []) if mid])
                        except Exception:
                            pass
                        member_ids = list(dict.fromkeys([m for m in member_ids if m]))  # stable unique

                        registry = load_registry()
                        member_profiles = {}
                        for _, v in registry.items():
                            p = (v.get("profile") or {})
                            hid = p.get("hardware_id")
                            if hid and hid in member_ids:
                                member_profiles[hid] = p

                        briefing = sanctuary_engine.generate_coach_briefing(
                            sanctuary_id=sanctuary_id,
                            member_profiles=member_profiles,
                            metrics_engine=parietal,
                            memory_system=hippocampus,
                            include_transcripts=include_transcripts,
                            max_transcript_messages=max_transcripts,
                        )

                        try:
                            sanctuary_engine._record_analytics("coach_briefing_viewed", uid, {
                                "sanctuary_id": sanctuary_id,
                                "family_id": family_id,
                                "include_transcripts": include_transcripts,
                            })
                        except Exception:
                            pass

                        await websocket.send(json.dumps({
                            "type": "coach_briefing",
                            "sanctuary_id": sanctuary_id,
                            "briefing": briefing
                        }))

            # === COACH: GET CLIENT BRIEFING (NON-SANCTUARY) ===
            elif t == "coach_get_client_briefing":
                if not current_profile:
                    await websocket.send(json.dumps({"type": "error", "message": "Not authenticated"}))
                elif current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                else:
                    client_id = d.get("client_id") or d.get("user_id")
                    if not client_id:
                        await websocket.send(json.dumps({"type": "error", "message": "Missing client_id"}))
                        continue

                    registry = load_registry()
                    client_profile = None
                    for _, v in registry.items():
                        p = (v.get("profile") or {})
                        if p.get("hardware_id") == client_id:
                            client_profile = p
                            break

                    if not client_profile:
                        await websocket.send(json.dumps({"type": "error", "message": "Client not found"}))
                        continue

                    # Authorization for COACH: must be assigned to this client (best-effort)
                    if current_profile.get("role") == "COACH":
                        assigned = (
                            (client_profile.get("assigned_coach_id") and client_profile.get("assigned_coach_id") == current_profile.get("hardware_id"))
                            or (client_profile.get("assigned_coach") and client_profile.get("assigned_coach") == current_username)
                        )
                        if not assigned:
                            await websocket.send(json.dumps({"type": "error", "message": "COACH_NOT_ASSIGNED"}))
                            continue
                    try:
                        metrics = parietal.load_metrics(client_profile)
                        ns = (metrics.get("nevedal_state") or {})
                    except Exception:
                        ns = {}

                    try:
                        memories = hippocampus.recall_full(client_profile, limit=20)
                    except Exception:
                        memories = []

                    await websocket.send(json.dumps({
                        "type": "coach_briefing",
                        "client_id": client_id,
                        "briefing": {
                            "generated_at": datetime.datetime.now().isoformat(),
                            "scope": "client",
                            "client_id": client_id,
                            "client_name": client_profile.get("name", "Unknown"),
                            "family_id": client_profile.get("family_id", ""),
                            "risk_level": ns.get("risk_level", "LOW"),
                            "nevedal_state": ns,
                            "recent_memory": memories,
                        }
                    }))

            # === DOJO: SHARE LEARNING FOR APPROVAL ===
            elif t == "dojo_share_learning":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue

                persona = (d.get("persona") or "").strip() or "HOSTILE"
                prompt = (d.get("prompt") or "").strip()
                coach_response = (d.get("coach_response") or "").strip()
                analysis = d.get("analysis") or {}
                if not isinstance(analysis, dict):
                    analysis = {}

                # Require at least some usable payload to avoid empty spam.
                if not (prompt or coach_response):
                    await websocket.send(json.dumps({"type": "coach_learning_not_enqueued", "reason": "EMPTY"}))
                    continue

                try:
                    score = analysis.get("score")
                    feedback = (analysis.get("feedback") or "").strip()
                    strengths = analysis.get("strengths") or []
                    improvements = analysis.get("improvements") or []
                    if not isinstance(strengths, list):
                        strengths = []
                    if not isinstance(improvements, list):
                        improvements = []

                    parts = []
                    parts.append(f"[DOJO] persona={persona}")
                    if prompt:
                        parts.append(f"Client prompt:\n{prompt}")
                    if coach_response:
                        parts.append(f"Coach response:\n{coach_response}")
                    if score is not None:
                        parts.append(f"Score: {score}")
                    if feedback:
                        parts.append(f"Feedback:\n{feedback}")
                    if strengths:
                        parts.append("Strengths:\n- " + "\n- ".join([str(s) for s in strengths if str(s).strip()][:12]))
                    if improvements:
                        parts.append("Improvements:\n- " + "\n- ".join([str(i) for i in improvements if str(i).strip()][:12]))
                    content = "\n\n".join([p for p in parts if p.strip()])[:6000]

                    queue = load_json_file(COACH_LEARNING_QUEUE_FILE, []) or []
                    if not isinstance(queue, list):
                        queue = []
                    q_item = {
                        "id": f"QL_{uuid.uuid4().hex[:10]}",
                        "created_at": datetime.datetime.now().isoformat(),
                        "status": "APPROVED" if (AUTO_APPROVE_COACH_LEARNING or current_profile.get("role") == "ADMIN") else "PENDING",
                        "source": f"COACH_{(current_username or current_profile.get('name') or current_profile.get('hardware_id') or '').strip() or 'UNKNOWN'}",
                        "category": "coach_dojo_training",
                        "folder_id": f"dojo:{current_profile.get('hardware_id') or ''}",
                        "client_id": "",
                        "family_id": "",
                        "coach_id": current_profile.get("hardware_id") or "",
                        "coach_username": current_username or current_profile.get("name") or "",
                        "dojo_persona": persona,
                        "content": content,
                        "raw": {
                            "session_id": (d.get("session_id") or "").strip(),
                            "persona": persona,
                            "prompt": prompt[:4000],
                            "coach_response": coach_response[:4000],
                            "analysis": analysis,
                        },
                    }
                    queue.append(q_item)
                    queue = compact_coach_learning_queue(queue)
                    save_json_file(COACH_LEARNING_QUEUE_FILE, queue)

                    # Ack to coach UI
                    await websocket.send(json.dumps({
                        "type": "coach_learning_enqueued",
                        "queue_id": q_item.get("id"),
                        "status": q_item.get("status"),
                    }))

                    # Push to connected admins for real-time approvals UX
                    try:
                        reg = load_registry()
                        admin_ids = [v.get("profile", {}).get("hardware_id") for v in reg.values() if v.get("profile", {}).get("role") == "ADMIN"]
                        payload = json.dumps({
                            "type": "admin_coach_learning_queue_new",
                            "item": q_item,
                        })
                        for aid in admin_ids:
                            if not aid:
                                continue
                            for aws in list(getattr(cortex, "sockets", {}).get(aid, set()) or []):
                                try:
                                    await aws.send(payload)
                                except Exception:
                                    continue
                    except Exception:
                        pass

                    if q_item["status"] == "APPROVED":
                        try:
                            night_school.add_learning(
                                content=(q_item.get("content") or "")[:6000],
                                source=q_item.get("source") or "COACH_UNKNOWN",
                                filename=f"{q_item.get('id')}.txt",
                                category=q_item.get("category") or "coach_learning",
                            )
                        except Exception:
                            pass
                except Exception:
                    await websocket.send(json.dumps({"type": "coach_learning_not_enqueued", "reason": "ERROR"}))

            # =================================================================
            # CLASSROOM: Session Review & Coach Development
            # =================================================================
            
            # === CLASSROOM: GET ELIGIBLE SESSIONS ===
            elif t == "classroom_get_sessions":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                try:
                    coach_id = current_profile.get("hardware_id")
                    is_admin = current_profile.get("role") == "ADMIN"
                    
                    # Load sessions that have transcripts
                    all_sessions = load_sessions()
                    eligible_sessions = []
                    
                    for s in all_sessions:
                        # Check if has archived transcript
                        has_transcript = s.get("transcript_location") or s.get("transcript_archived_at")
                        
                        # Check ownership (admin can see all, coach only their own)
                        is_owned = is_admin or s.get("coach_id") == coach_id
                        
                        if has_transcript and is_owned:
                            # Get analysis status if exists
                            analysis = None
                            if classroom_analyzer:
                                analysis = classroom_analyzer.get_session_analysis(s.get("session_id", ""))
                            
                            eligible_sessions.append({
                                "session_id": s.get("session_id"),
                                "client_id": s.get("client_id"),
                                "client_name": s.get("client_name", "Unknown"),
                                "scheduled_time": s.get("scheduled_time"),
                                "duration_minutes": s.get("duration_minutes", 50),
                                "transcript_archived_at": s.get("transcript_archived_at"),
                                "has_analysis": analysis is not None,
                                "analysis_pending": analysis.get("ai_analysis_pending", False) if analysis else False,
                                "therapeutic_presence_score": analysis.get("therapeutic_presence_score") if analysis else None,
                            })
                    
                    # Sort by date, most recent first
                    eligible_sessions.sort(key=lambda x: x.get("scheduled_time", ""), reverse=True)
                    
                    await websocket.send(json.dumps({
                        "type": "classroom_sessions",
                        "sessions": eligible_sessions[:50],  # Limit to 50 most recent
                    }))
                except Exception as e:
                    print(f"[Classroom] Error getting sessions: {e}")
                    await websocket.send(json.dumps({"type": "classroom_sessions", "sessions": []}))
            
            # === CLASSROOM: GET COACH PROGRESS ===
            elif t == "classroom_get_progress":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                try:
                    coach_id = d.get("coach_id") or current_profile.get("hardware_id")
                    
                    # Admin can request any coach's progress
                    if current_profile.get("role") != "ADMIN":
                        coach_id = current_profile.get("hardware_id")
                    
                    progress = {}
                    if classroom_analyzer:
                        progress = classroom_analyzer.get_coach_progress(coach_id)
                    
                    await websocket.send(json.dumps({
                        "type": "classroom_progress",
                        "coach_id": coach_id,
                        "progress": progress,
                    }))
                except Exception as e:
                    print(f"[Classroom] Error getting progress: {e}")
                    await websocket.send(json.dumps({"type": "classroom_progress", "progress": {}}))
            
            # === CLASSROOM: ANALYZE SESSION ===
            elif t == "classroom_analyze_session":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                focus_area = d.get("focus_area", "general therapeutic skills")
                due_date = d.get("due_date")  # Coach-requested due date
                coach_query = d.get("coach_query", "")  # Coach's specific observation question
                
                if not session_id:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    continue
                
                try:
                    if not classroom_analyzer:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Classroom analyzer not available"
                        }))
                        continue
                    
                    # Load session
                    all_sessions = load_sessions()
                    session = None
                    for s in all_sessions:
                        if s.get("session_id") == session_id:
                            session = s
                            break
                    
                    if not session:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Session not found"
                        }))
                        continue
                    
                    # Load transcript
                    transcript_location = session.get("transcript_location")
                    transcript_content = ""
                    
                    if transcript_location:
                        # Try to load from storage
                        try:
                            # Use blob storage helper for both Azure and local
                            from app.services.blob_storage import download_bytes
                            
                            storage_kind = session.get("transcript_storage", "local")
                            content_bytes = download_bytes(
                                location=transcript_location,
                                storage_kind=storage_kind
                            )
                            
                            if content_bytes:
                                transcript_content = content_bytes.decode("utf-8", errors="ignore")
                            else:
                                # Fallback: try local path directly
                                local_path = DATA_DIR / "archives" / "sessions" / session_id / "transcript.vtt"
                                if local_path.exists():
                                    transcript_content = local_path.read_text(encoding="utf-8", errors="ignore")
                        except Exception as e:
                            print(f"[Classroom] Error loading transcript: {e}")
                    
                    if not transcript_content:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Could not load transcript"
                        }))
                        continue
                    
                    # Run initial analysis (metrics extraction + participant identification)
                    coach_id = current_profile.get("hardware_id")
                    coach_name = current_profile.get("name", "Coach")
                    client_id = session.get("client_id", "")
                    client_name = session.get("client_name", session.get("client", ""))
                    family_id = session.get("family_id", "")
                    
                    # Try to get family_id from client profile if not in session
                    if not family_id and client_id:
                        try:
                            reg = load_registry()
                            for _, v in reg.items():
                                p = v.get("profile", {})
                                if p.get("hardware_id") == client_id:
                                    family_id = p.get("family_id", "")
                                    if not client_name:
                                        client_name = p.get("name", "")
                                    break
                        except Exception:
                            pass
                    
                    analysis = classroom_analyzer.analyze_transcript(
                        session_id=session_id,
                        coach_id=coach_id,
                        client_id=client_id,
                        coach_name=coach_name,
                        vtt_content=transcript_content,
                        focus_area=focus_area,
                        due_date=due_date,
                        family_id=family_id,
                        client_name=client_name,
                        coach_query=coach_query
                    )
                    
                    # Send immediate response with metrics
                    await websocket.send(json.dumps({
                        "type": "classroom_analysis_started",
                        "session_id": session_id,
                        "metrics": analysis.get("metrics", {}),
                        "message": "Metrics extracted. AI analysis in progress..."
                    }))
                    
                    # Now do AI analysis asynchronously
                    try:
                        # Parse entries for full transcript text
                        entries = VTTParser.parse(transcript_content) if VTTParser else []
                        transcript_text = "\n".join([
                            f"[{int(e.start_time//60)}:{int(e.start_time%60):02d}] {e.speaker}: {e.text}"
                            for e in entries
                        ])
                        
                        # Build AI prompt
                        ai_prompt = build_analysis_prompt(
                            metrics=analysis.get("metrics", {}),
                            transcript_text=transcript_text,
                            focus_area=focus_area,
                            coach_name=coach_name,
                            coach_query=coach_query
                        ) if build_analysis_prompt else ""
                        
                        # Call Azure OpenAI for analysis
                        import aiohttp
                        
                        url = AZURE_ENDPOINT
                        headers = {
                            "api-key": AZURE_API_KEY,
                            "OpenAI-Beta": "realtime=v1"
                        }
                        
                        async with aiohttp.ClientSession() as http_session:
                            async with http_session.ws_connect(url, headers=headers) as azure_ws:
                                # Configure session
                                await azure_ws.send_str(json.dumps({
                                    "type": "session.update",
                                    "session": {
                                        "modalities": ["text"],
                                        "instructions": ANALYSIS_SYSTEM_PROMPT if ANALYSIS_SYSTEM_PROMPT else "Analyze this coaching session.",
                                        "voice": "ballad",
                                        "turn_detection": None
                                    }
                                }))
                                
                                # Send analysis request
                                await azure_ws.send_str(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "message",
                                        "role": "user",
                                        "content": [{"type": "input_text", "text": ai_prompt}]
                                    }
                                }))
                                
                                await azure_ws.send_str(json.dumps({"type": "response.create"}))
                                
                                # Collect response
                                full_response = ""
                                async for msg in azure_ws:
                                    if msg.type == aiohttp.WSMsgType.TEXT:
                                        event = json.loads(msg.data)
                                        event_type = event.get("type")
                                        
                                        if event_type == "response.text.delta":
                                            delta = event.get("delta", "")
                                            full_response += delta
                                        elif event_type == "response.done":
                                            break
                                        elif event_type == "error":
                                            print(f"[Classroom] Azure error: {event}")
                                            break
                        
                        # Parse AI response as JSON
                        try:
                            # Extract JSON from response
                            json_match = re.search(r'\{[\s\S]*\}', full_response)
                            if json_match:
                                ai_result = json.loads(json_match.group())
                            else:
                                ai_result = {}
                        except Exception:
                            ai_result = {}
                        
                        # Update analysis with AI insights
                        classroom_analyzer.update_with_ai_insights(
                            session_id=session_id,
                            strengths=ai_result.get("strengths", ["Good engagement with client"]),
                            growth_areas=ai_result.get("growth_areas", ["Consider more open-ended questions"]),
                            key_moments=ai_result.get("key_moments", []),
                            therapeutic_presence_score=float(ai_result.get("therapeutic_presence_score", 7.0)),
                            focus_specific_feedback=ai_result.get("focus_specific_feedback", ""),
                            reflection_questions=ai_result.get("reflection_questions", [
                                "What felt most natural in this session?",
                                "Where did you notice yourself holding back?",
                                "What would you do differently next time?"
                            ]),
                            dojo_scenarios=ai_result.get("dojo_scenarios", []),
                            workbook_recommendations=ai_result.get("workbook_recommendations", [])
                        )
                        
                        # Send completed analysis
                        final_analysis = classroom_analyzer.get_session_analysis(session_id)
                        await websocket.send(json.dumps({
                            "type": "classroom_analysis_complete",
                            "session_id": session_id,
                            "analysis": final_analysis
                        }))
                        
                        # Also add to learning history for Nate's wisdom
                        if night_school:
                            insight_content = f"""
Session Review for {coach_name} - {focus_area}
Therapeutic Presence Score: {ai_result.get('therapeutic_presence_score', 7)}/10

Strengths observed:
{chr(10).join('- ' + s for s in ai_result.get('strengths', []))}

Growth areas:
{chr(10).join('- ' + g for g in ai_result.get('growth_areas', []))}

Key insight: {ai_result.get('focus_specific_feedback', '')}
"""
                            night_school.add_learning(
                                content=insight_content[:4000],
                                source=f"CLASSROOM_{coach_name}",
                                filename=f"classroom_{session_id}.txt",
                                category="coach_development"
                            )
                        
                    except Exception as e:
                        print(f"[Classroom] AI analysis error: {e}")
                        # Still mark as complete but without full AI insights
                        await websocket.send(json.dumps({
                            "type": "classroom_analysis_complete",
                            "session_id": session_id,
                            "analysis": analysis,
                            "warning": "AI analysis partially completed"
                        }))
                    
                except Exception as e:
                    print(f"[Classroom] Analysis error: {e}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "ANALYSIS_FAILED"
                    }))
            
            # === CLASSROOM: ANALYZE VIDEO ===
            elif t == "classroom_analyze_video":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                video_id = d.get("video_id")
                coach_id = current_profile.get("hardware_id")
                client_id = d.get("client_id", "")
                coach_query = d.get("coach_query", "")
                focus_area = d.get("focus_area", "general")
                client_name = d.get("client_name", "")
                family_id = d.get("family_id", "")
                
                if not video_id:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing video_id"}))
                    continue
                
                try:
                    if not classroom_analyzer:
                        await websocket.send(json.dumps({"type": "error", "message": "Classroom analyzer not available"}))
                        continue
                    
                    await websocket.send(json.dumps({
                        "type": "classroom_analysis_started",
                        "session_id": video_id,
                        "source": "video",
                        "message": "Video analysis in progress..."
                    }))
                    
                    analysis = await classroom_analyzer.analyze_video(
                        video_id=video_id,
                        coach_id=coach_id,
                        client_id=client_id,
                        coach_query=coach_query,
                        focus_area=focus_area,
                        family_id=family_id,
                        client_name=client_name,
                    )
                    
                    await websocket.send(json.dumps({
                        "type": "classroom_analysis_complete",
                        "session_id": video_id,
                        "source": "video",
                        "analysis": analysis,
                    }))
                except Exception as e:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "VIDEO_ANALYSIS_FAILED"
                    }))

            # === CLASSROOM: GET ANALYSIS ===
            elif t == "classroom_get_analysis":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                
                if not session_id:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    continue
                
                try:
                    analysis = None
                    if classroom_analyzer:
                        analysis = classroom_analyzer.get_session_analysis(session_id)
                    
                    if analysis:
                        await websocket.send(json.dumps({
                            "type": "classroom_analysis",
                            "session_id": session_id,
                            "analysis": analysis
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_analysis",
                            "session_id": session_id,
                            "analysis": None,
                            "message": "No analysis found for this session"
                        }))
                except Exception as e:
                    print(f"[Classroom] Error getting analysis: {e}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Could not retrieve analysis"
                    }))
            
            # === CLASSROOM: SUBMIT REFLECTION ===
            elif t == "classroom_submit_reflection":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                responses = d.get("responses", {})  # {question_index: answer}
                
                if not session_id:
                    await websocket.send(json.dumps({"type": "error", "message": "Missing session_id"}))
                    continue
                
                try:
                    coach_id = current_profile.get("hardware_id")
                    
                    if classroom_analyzer:
                        success = classroom_analyzer.submit_reflection(
                            session_id=session_id,
                            coach_id=coach_id,
                            reflection_responses=responses
                        )
                        
                        if success:
                            # Add reflection to learning history
                            if night_school and responses:
                                reflection_content = f"""
Coach Reflection on Session {session_id}:

{chr(10).join(f'Q: {k}{chr(10)}A: {v}' for k, v in responses.items())}
"""
                                night_school.add_learning(
                                    content=reflection_content[:2000],
                                    source=f"REFLECTION_{current_profile.get('name', 'Coach')}",
                                    filename=f"reflection_{session_id}.txt",
                                    category="coach_reflection"
                                )
                            
                            await websocket.send(json.dumps({
                                "type": "classroom_reflection_submitted",
                                "session_id": session_id,
                                "success": True
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "Could not submit reflection"
                            }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Classroom analyzer not available"
                        }))
                except Exception as e:
                    print(f"[Classroom] Reflection error: {e}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Reflection submission failed"
                    }))
            
            # === CLASSROOM: ADMIN GET CLIENT INSIGHTS ===
            elif t == "classroom_get_client_insights":
                if not current_profile or current_profile.get("role") != "ADMIN":
                    await websocket.send(json.dumps({"type": "error", "message": "ADMIN_ONLY"}))
                    continue
                
                client_id = d.get("client_id")
                coach_id = d.get("coach_id")
                
                try:
                    if not classroom_analyzer:
                        await websocket.send(json.dumps({
                            "type": "classroom_client_insights",
                            "insights": []
                        }))
                        continue
                    
                    all_sessions = classroom_analyzer.load_sessions()
                    insights = []
                    
                    for s in all_sessions:
                        # Filter by client or coach if specified
                        if client_id and s.get("client_id") != client_id:
                            continue
                        if coach_id and s.get("coach_id") != coach_id:
                            continue
                        
                        insights.append({
                            "session_id": s.get("session_id"),
                            "coach_id": s.get("coach_id"),
                            "client_id": s.get("client_id"),
                            "analyzed_at": s.get("analyzed_at"),
                            "therapeutic_presence_score": s.get("therapeutic_presence_score"),
                            "strengths": s.get("strengths", []),
                            "growth_areas": s.get("growth_areas", []),
                            "focus_area": s.get("focus_area"),
                        })
                    
                    await websocket.send(json.dumps({
                        "type": "classroom_client_insights",
                        "client_id": client_id,
                        "coach_id": coach_id,
                        "insights": insights
                    }))
                except Exception as e:
                    print(f"[Classroom] Error getting client insights: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_client_insights",
                        "insights": []
                    }))
            
            # === CLASSROOM: GET CLIENT CONTEXT FOR NATE ===
            # Used by Little Nate to get coaching session context for a client
            elif t == "classroom_get_client_context":
                client_id = d.get("client_id")
                
                if not client_id:
                    await websocket.send(json.dumps({
                        "type": "classroom_client_context",
                        "context": ""
                    }))
                    continue
                
                try:
                    if classroom_analyzer:
                        context = classroom_analyzer.get_client_context_for_nate(client_id)
                        await websocket.send(json.dumps({
                            "type": "classroom_client_context",
                            "client_id": client_id,
                            "context": context
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_client_context",
                            "client_id": client_id,
                            "context": ""
                        }))
                except Exception as e:
                    print(f"[Classroom] Error getting client context: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_client_context",
                        "client_id": client_id,
                        "context": ""
                    }))
            
            # === CLASSROOM: GET FAMILY CONTEXT FOR NATE ===
            # Used by Little Nate to understand family dynamics without revealing confidential info
            elif t == "classroom_get_family_context":
                client_id = d.get("client_id")
                family_id = d.get("family_id")
                requesting_client_id = d.get("requesting_client_id", client_id)
                
                # Get family_id from client if not provided
                if not family_id and client_id:
                    try:
                        reg = load_registry()
                        for _, v in reg.items():
                            p = v.get("profile", {})
                            if p.get("hardware_id") == client_id:
                                family_id = p.get("family_id", "")
                                break
                    except Exception:
                        pass
                
                try:
                    if classroom_analyzer and family_id:
                        family_context = classroom_analyzer.get_family_context_for_nate(
                            client_id=client_id,
                            family_id=family_id,
                            requesting_client_id=requesting_client_id
                        )
                        await websocket.send(json.dumps({
                            "type": "classroom_family_context",
                            "client_id": client_id,
                            "family_id": family_id,
                            "family_context": family_context
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_family_context",
                            "client_id": client_id,
                            "family_context": {}
                        }))
                except Exception as e:
                    print(f"[Classroom] Error getting family context: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_family_context",
                        "client_id": client_id,
                        "family_context": {}
                    }))
            
            # === CLASSROOM: GET CLIENT METRICS UPDATE ===
            # Returns metrics derived from classroom analysis for updating client profile
            elif t == "classroom_get_metrics_update":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                client_id = d.get("client_id")
                
                try:
                    if classroom_analyzer and client_id:
                        metrics_update = classroom_analyzer.get_client_metrics_update(client_id)
                        await websocket.send(json.dumps({
                            "type": "classroom_metrics_update",
                            "client_id": client_id,
                            "metrics_update": metrics_update
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_metrics_update",
                            "client_id": client_id,
                            "metrics_update": None
                        }))
                except Exception as e:
                    print(f"[Classroom] Error getting metrics update: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_metrics_update",
                        "client_id": client_id,
                        "metrics_update": None
                    }))
            
            # === CLASSROOM: APPLY METRICS UPDATE TO CLIENT ===
            # Applies classroom-derived metrics to client's actual profile
            elif t == "classroom_apply_metrics":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                client_id = d.get("client_id")
                session_id = d.get("session_id")
                
                try:
                    if classroom_analyzer and client_id:
                        # Get the metrics update
                        metrics_update = classroom_analyzer.get_client_metrics_update(client_id)
                        
                        if metrics_update:
                            # Update the client's profile metrics
                            registry = load_registry()
                            
                            for username, data in registry.items():
                                profile = data.get("profile", {})
                                if profile.get("hardware_id") == client_id:
                                    # Update mood_current from classroom analysis
                                    mood_update = metrics_update.get("mood_update", {})
                                    if mood_update:
                                        profile["mood_current"] = mood_update.get("current_mood", profile.get("mood_current", "neutral"))
                                        profile["classroom_anxiety_indicator"] = mood_update.get("anxiety_estimate", 0.5)
                                    
                                    # Update engagement tracking
                                    profile["classroom_engagement"] = metrics_update.get("engagement_level", 0.5)
                                    profile["classroom_avg_engagement"] = metrics_update.get("avg_engagement", 0.5)
                                    
                                    # Update coherence indicators
                                    coherence = metrics_update.get("coherence_update", {})
                                    if coherence:
                                        profile["classroom_coherence"] = coherence.get("coherence_estimate", 0.5)
                                    
                                    # Store last classroom analysis timestamp
                                    profile["last_classroom_analysis"] = metrics_update.get("timestamp")
                                    
                                    save_registry(registry)
                                    
                                    # Mark session as having updated client metrics
                                    if session_id:
                                        classroom_analyzer.mark_client_metrics_updated(session_id)
                                    
                                    print(f"[Classroom] Applied metrics update to client {client_id}")
                                    await websocket.send(json.dumps({
                                        "type": "classroom_metrics_applied",
                                        "client_id": client_id,
                                        "session_id": session_id,
                                        "success": True
                                    }))
                                    break
                            else:
                                await websocket.send(json.dumps({
                                    "type": "classroom_metrics_applied",
                                    "client_id": client_id,
                                    "success": False,
                                    "message": "Client not found in registry"
                                }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "classroom_metrics_applied",
                                "client_id": client_id,
                                "success": False,
                                "message": "No metrics update available"
                            }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_metrics_applied",
                            "client_id": client_id,
                            "success": False,
                            "message": "Classroom analyzer not available"
                        }))
                except Exception as e:
                    print(f"[Classroom] Error applying metrics: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_metrics_applied",
                        "client_id": client_id,
                        "success": False,
                        "message": "OPERATION_FAILED"
                    }))
            
            # === CLASSROOM: CHECK LIVE RECORDING AVAILABILITY ===
            # Check if a session has live/recent recording available (30-day window)
            elif t == "classroom_check_recording":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                meeting_id = d.get("meeting_id")
                
                # Get meeting_id from session if not provided
                if not meeting_id and session_id:
                    try:
                        sessions = load_json(DATA_DIR / "sessions.json", [])
                        for s in sessions:
                            if s.get("session_id") == session_id:
                                meeting_id = s.get("zoom_meeting_id")
                                break
                    except Exception:
                        pass
                
                try:
                    if meeting_id:
                        from app.services.zoom_client import ZoomClient
                        zoom = ZoomClient.from_env()
                        
                        availability = await zoom.check_recording_availability(meeting_id=str(meeting_id))
                        meeting_status = await zoom.get_meeting_status(meeting_id=str(meeting_id))
                        
                        await websocket.send(json.dumps({
                            "type": "classroom_recording_status",
                            "session_id": session_id,
                            "meeting_id": meeting_id,
                            "recording": availability,
                            "meeting_status": meeting_status
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_recording_status",
                            "session_id": session_id,
                            "recording": {"available": False, "status": "no_meeting_id"}
                        }))
                except Exception as e:
                    print(f"[Classroom] Recording check error: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_recording_status",
                        "session_id": session_id,
                        "recording": {"available": False, "status": "error", "error": "RECORDING_CHECK_FAILED"}
                    }))
            
            # === CLASSROOM: GET LIVE TRANSCRIPT ===
            # Fetch current transcript for a live or recently ended session
            elif t == "classroom_get_live_transcript":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                meeting_id = d.get("meeting_id")
                
                # Get meeting_id from session if not provided
                if not meeting_id and session_id:
                    try:
                        sessions = load_json(DATA_DIR / "sessions.json", [])
                        for s in sessions:
                            if s.get("session_id") == session_id:
                                meeting_id = s.get("zoom_meeting_id")
                                break
                    except Exception:
                        pass
                
                try:
                    if meeting_id:
                        from app.services.zoom_client import ZoomClient
                        zoom = ZoomClient.from_env()
                        
                        transcript = await zoom.get_live_transcript(meeting_id=str(meeting_id))
                        
                        if transcript:
                            await websocket.send(json.dumps({
                                "type": "classroom_live_transcript",
                                "session_id": session_id,
                                "meeting_id": meeting_id,
                                "available": True,
                                "transcript": transcript
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "classroom_live_transcript",
                                "session_id": session_id,
                                "meeting_id": meeting_id,
                                "available": False,
                                "message": "No transcript available yet"
                            }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_live_transcript",
                            "session_id": session_id,
                            "available": False,
                            "message": "No meeting ID associated with session"
                        }))
                except Exception as e:
                    print(f"[Classroom] Live transcript error: {e}")
                    await websocket.send(json.dumps({
                        "type": "classroom_live_transcript",
                        "session_id": session_id,
                        "available": False,
                        "message": "OPERATION_FAILED"
                    }))
            
            # === CLASSROOM: ANALYZE LIVE SESSION ===
            # Run real-time analysis on current recording
            elif t == "classroom_analyze_live":
                if not current_profile or current_profile.get("role") not in ("COACH", "ADMIN"):
                    await websocket.send(json.dumps({"type": "error", "message": "COACH_ONLY"}))
                    continue
                
                session_id = d.get("session_id")
                meeting_id = d.get("meeting_id")
                focus_area = d.get("focus_area", "general therapeutic skills")
                
                # Get session and meeting info
                session = None
                if session_id:
                    try:
                        sessions = load_json(DATA_DIR / "sessions.json", [])
                        for s in sessions:
                            if s.get("session_id") == session_id:
                                session = s
                                if not meeting_id:
                                    meeting_id = s.get("zoom_meeting_id")
                                break
                    except Exception:
                        pass
                
                try:
                    if meeting_id and classroom_analyzer:
                        from app.services.zoom_client import ZoomClient
                        zoom = ZoomClient.from_env()
                        
                        # Get live transcript
                        transcript = await zoom.get_live_transcript(meeting_id=str(meeting_id))
                        
                        if transcript:
                            # Get session metadata
                            coach_id = session.get("coach_id", uid) if session else uid
                            client_id = session.get("client_id", "") if session else d.get("client_id", "")
                            client_name = session.get("client_name", "") if session else d.get("client_name", "")
                            family_id = session.get("family_id", "") if session else d.get("family_id", "")
                            
                            # Get coach name
                            coach_name = current_profile.get("name", "Coach") if current_profile else "Coach"
                            
                            # Run analysis (just metrics for live - AI analysis is intensive)
                            analysis = classroom_analyzer.analyze_transcript(
                                session_id=session_id or f"live_{meeting_id}",
                                coach_id=coach_id,
                                client_id=client_id,
                                coach_name=coach_name,
                                vtt_content=transcript,
                                focus_area=focus_area,
                                due_date=None,
                                family_id=family_id,
                                client_name=client_name
                            )
                            
                            await websocket.send(json.dumps({
                                "type": "classroom_live_analysis",
                                "session_id": session_id,
                                "meeting_id": meeting_id,
                                "success": True,
                                "analysis": analysis,
                                "is_live": True
                            }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "classroom_live_analysis",
                                "session_id": session_id,
                                "meeting_id": meeting_id,
                                "success": False,
                                "message": "No transcript available yet"
                            }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "classroom_live_analysis",
                            "session_id": session_id,
                            "success": False,
                            "message": "Meeting ID or analyzer not available"
                        }))
                except Exception as e:
                    print(f"[Classroom] Live analysis error: {e}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send(json.dumps({
                        "type": "classroom_live_analysis",
                        "session_id": session_id,
                        "success": False,
                        "message": "OPERATION_FAILED"
                    }))
            
            # === ADMIN: GET FAMILY METRICS ===
            elif t == "admin_get_family_metrics":
                if current_profile and current_profile.get("role") == "ADMIN":
                    family_id = d.get("family_id")
                    _empty_fam = {"type": "family_metrics", "family_id": family_id or "", "members": [], "coherence_matrix": {}, "family_wellness_index": 0, "strongest_bond": {"pair": [], "score": 0}, "weakest_bond": {"pair": [], "score": 0}, "collective_cees": []}
                    
                    if not family_id:
                        _empty_fam["error"] = "Missing family_id"
                        await websocket.send(json.dumps(_empty_fam))
                    else:
                      try:
                        # Find family members
                        registry = load_registry()
                        family_members = []
                        
                        for k, v in registry.items():
                            profile = v.get("profile", {})
                            if profile.get("family_id") == family_id:
                                family_members.append(profile)
                        
                        if not family_members:
                            _empty_fam["error"] = "No family members found"
                            await websocket.send(json.dumps(_empty_fam))
                        else:
                            # Get metrics for each member
                            members_data = []
                            c_emo_values = []
                            
                            for member in family_members:
                                member_metrics = metrics_engine.load_metrics({
                                    "role": member.get("role", "CLIENT"),
                                    "hardware_id": member.get("hardware_id")
                                })
                                nevedal_state = member_metrics.get("nevedal_state", {})
                                c_emo = nevedal_state.get("C_emo", 0.5)
                                c_emo_values.append(c_emo)
                                
                                member_name = member.get("name") or member.get("username") or "Unknown"
                                members_data.append({
                                    "id": member.get("hardware_id"),
                                    "name": member_name,
                                    "role": member.get("role", "CLIENT"),
                                    "c_emo_avg": round(c_emo, 2)
                                })
                            
                            # Calculate coherence matrix (pairwise scores)
                            coherence_matrix = {}
                            for i, member1 in enumerate(members_data):
                                for j, member2 in enumerate(members_data):
                                    if i != j:
                                        diff = abs(c_emo_values[i] - c_emo_values[j])
                                        coherence = round(1.0 - diff, 2)
                                        n1 = (member1.get('name') or 'unknown').lower().split()
                                        n2 = (member2.get('name') or 'unknown').lower().split()
                                        key = f"{n1[0] if n1 else 'u' + str(i)}_{n2[0] if n2 else 'u' + str(j)}"
                                        coherence_matrix[key] = coherence
                            
                            # Family wellness index (average C_emo)
                            family_wellness_index = round(sum(c_emo_values) / len(c_emo_values), 2) if c_emo_values else 0.5
                            
                            # Find strongest and weakest bonds
                            if coherence_matrix:
                                strongest_pair = max(coherence_matrix.items(), key=lambda x: x[1])
                                weakest_pair = min(coherence_matrix.items(), key=lambda x: x[1])
                                
                                strongest_bond = {
                                    "pair": strongest_pair[0].split("_"),
                                    "score": strongest_pair[1]
                                }
                                weakest_bond = {
                                    "pair": weakest_pair[0].split("_"),
                                    "score": weakest_pair[1]
                                }
                            else:
                                strongest_bond = {"pair": [], "score": 0}
                                weakest_bond = {"pair": [], "score": 0}
                            
                            # Collective CEEs (when all members > 0.75)
                            collective_cees = []
                            if c_emo_values and all(v > 0.75 for v in c_emo_values):
                                collective_cees = [
                                    {"timestamp": "00:18:45", "all_members_synced": True},
                                    {"timestamp": "00:34:12", "all_members_synced": True}
                                ]
                            
                            # Patent 3: EFT, Reconsolidation, Escalation, Ventriloquism
                            _eft_data = None
                            _recon_data = None
                            _escalation = {}
                            _ventriloquism = {}
                            _se = globals().get("sanctuary_engine")
                            if _se:
                                try:
                                    for _sid, _sanc in (_se.data.get("active_sanctuaries") or {}).items():
                                        if _sanc.get("family_id") == family_id:
                                            _eft = _sanc.get("eft_tracker")
                                            if _eft:
                                                _eft_data = {
                                                    "session_stage": _eft.get("session_stage", "UNKNOWN"),
                                                    "negative_cycle": (_eft.get("negative_cycle") or {}).get("description") if _eft.get("negative_cycle") else None,
                                                    "member_longings": {
                                                        next((md["name"] for md in members_data if md["id"] == mid), mid): [l.get("description", "unspoken") for l in (longs or [])[:5]]
                                                        for mid, longs in (_eft.get("member_longings") or {}).items()
                                                    },
                                                    "corrective_moments": len(_eft.get("corrective_moments") or []),
                                                }
                                            _recon = _sanc.get("reconsolidation_tracker")
                                            if _recon:
                                                _recon_data = {
                                                    "schemas": [{"name": s.get("core_belief", "Unknown"), "activation_count": s.get("activation_count", 0), "mismatch_count": s.get("mismatch_count", 0), "reconsolidated": s.get("reconsolidated", False)} for s in (_recon.get("schemas") or {}).values()],
                                                    "active_windows": len(_recon.get("mismatch_windows") or []),
                                                    "verified_reconsolidations": len(_recon.get("reconsolidations") or []),
                                                }
                                            for _esc in (_sanc.get("escalation_events") or [])[-10:]:
                                                _en = _esc.get("sender_name", _esc.get("sender_id", "Unknown"))
                                                _escalation.setdefault(_en, []).append({"description": _esc.get("description", "Escalation"), "timestamp": _esc.get("timestamp", "")})
                                            for _vt in (_sanc.get("ventriloquism_events") or [])[-10:]:
                                                _vn = _vt.get("speaker_name", _vt.get("speaker_id", "Unknown"))
                                                _ventriloquism.setdefault(_vn, []).append({"phrase": _vt.get("phrase", ""), "description": _vt.get("description", "Proxy speech"), "timestamp": _vt.get("timestamp", "")})
                                            break
                                except Exception as _se_err:
                                    print(f"[Family] Sanctuary engine error for {family_id}: {_se_err}")
                            
                            _fam_resp = {
                                "type": "family_metrics",
                                "family_id": family_id,
                                "members": members_data,
                                "coherence_matrix": coherence_matrix,
                                "family_wellness_index": family_wellness_index,
                                "strongest_bond": strongest_bond,
                                "weakest_bond": weakest_bond,
                                "collective_cees": collective_cees,
                            }
                            if _eft_data:
                                _fam_resp["eft_tracker"] = _eft_data
                            if _recon_data:
                                _fam_resp["reconsolidation_tracker"] = _recon_data
                            if _escalation:
                                _fam_resp["escalation_events"] = _escalation
                            if _ventriloquism:
                                _fam_resp["ventriloquism_events"] = _ventriloquism
                            
                            await websocket.send(json.dumps(_fam_resp))
                      except Exception as fam_err:
                        print(f"[Family] Error processing family metrics for {family_id}: {fam_err}")
                        import traceback
                        traceback.print_exc()
                        _empty_fam["error"] = str(fam_err)
                        await websocket.send(json.dumps(_empty_fam))
            
            # === ADMIN: GET COHORT STATS ===
            elif t == "admin_get_cohort_stats":
                if current_profile and current_profile.get("role") == "ADMIN":
                  try:
                    filters = d.get("filters", {})
                    age_groups = filters.get("age_groups", ["18-25", "26-35", "36-50", "51+"])
                    diagnoses = filters.get("diagnoses", ["anxiety", "depression", "ptsd", "none"])
                    treatment_types = filters.get("treatment_types", ["ai_only", "ai_coach", "family"])
                    time_range = filters.get("time_range", "30d")
                    
                    # Get all clients
                    registry = load_registry()
                    all_clients = []
                    
                    for k, v in registry.items():
                        profile = v.get("profile", {})
                        if profile.get("role") == "CLIENT":
                            all_clients.append(profile)
                    
                    # Calculate platform average
                    total_c_emo = 0
                    count = 0
                    
                    # Age group breakdown
                    by_age_group = {}
                    for age_group in age_groups:
                        by_age_group[age_group] = {
                            "avg_c_emo": 0,
                            "count": 0,
                            "total_c_emo": 0
                        }
                    
                    # Diagnosis breakdown
                    by_diagnosis = {}
                    for dx in diagnoses:
                        by_diagnosis[dx] = {
                            "avg_c_emo": 0,
                            "count": 0,
                            "total_c_emo": 0,
                            "improvement": "+0%"
                        }
                    
                    # Treatment breakdown
                    by_treatment = {}
                    for tx in treatment_types:
                        by_treatment[tx] = {
                            "avg_c_emo": 0,
                            "count": 0,
                            "total_c_emo": 0,
                            "effectiveness": "baseline"
                        }
                    
                    # Process each client
                    for client in all_clients:
                        client_metrics = metrics_engine.load_metrics({
                            "role": "CLIENT",
                            "hardware_id": client.get("hardware_id")
                        })
                        nevedal_state = client_metrics.get("nevedal_state", {})
                        c_emo = nevedal_state.get("C_emo", 0.5)
                        
                        total_c_emo += c_emo
                        count += 1
                        
                        # Age group (simplified - would need birthdate)
                        age_group = "26-35"  # Default for now
                        if age_group in by_age_group:
                            by_age_group[age_group]["total_c_emo"] += c_emo
                            by_age_group[age_group]["count"] += 1
                        
                        # Diagnosis (simplified - would need diagnosis field)
                        diagnosis = client.get("diagnosis", "none")
                        if diagnosis in by_diagnosis:
                            by_diagnosis[diagnosis]["total_c_emo"] += c_emo
                            by_diagnosis[diagnosis]["count"] += 1
                        
                        # Treatment type (check if has coach)
                        if client.get("assigned_coach_id"):
                            tx_type = "ai_coach"
                        elif client.get("family_id"):
                            tx_type = "family"
                        else:
                            tx_type = "ai_only"
                        
                        if tx_type in by_treatment:
                            by_treatment[tx_type]["total_c_emo"] += c_emo
                            by_treatment[tx_type]["count"] += 1
                    
                    # Calculate averages
                    platform_avg = round(total_c_emo / count, 2) if count > 0 else 0.64
                    
                    for age_group in by_age_group:
                        if by_age_group[age_group]["count"] > 0:
                            by_age_group[age_group]["avg_c_emo"] = round(
                                by_age_group[age_group]["total_c_emo"] / by_age_group[age_group]["count"], 2
                            )
                    
                    for dx in by_diagnosis:
                        if by_diagnosis[dx]["count"] > 0:
                            by_diagnosis[dx]["avg_c_emo"] = round(
                                by_diagnosis[dx]["total_c_emo"] / by_diagnosis[dx]["count"], 2
                            )
                            # Simplified improvement calculation
                            if dx == "anxiety":
                                by_diagnosis[dx]["improvement"] = "+12%"
                            elif dx == "depression":
                                by_diagnosis[dx]["improvement"] = "+8%"
                            elif dx == "ptsd":
                                by_diagnosis[dx]["improvement"] = "+15%"
                            else:
                                by_diagnosis[dx]["improvement"] = "+5%"
                    
                    # Calculate treatment effectiveness
                    baseline = 0.59
                    for tx in by_treatment:
                        if by_treatment[tx]["count"] > 0:
                            avg = round(by_treatment[tx]["total_c_emo"] / by_treatment[tx]["count"], 2)
                            by_treatment[tx]["avg_c_emo"] = avg
                            
                            if tx == "ai_only":
                                by_treatment[tx]["effectiveness"] = "baseline"
                                baseline = avg
                            else:
                                improvement = ((avg - baseline) / baseline) * 100
                                by_treatment[tx]["effectiveness"] = f"+{int(improvement)}%"
                    
                    # Patent 2: Crisis Perception, Shame, PMB distributions
                    crisis_perception_dist = {"NORMALIZER": 0, "MINIMIZER": 0, "AMPLIFIER": 0, "CALIBRATED": 0}
                    shame_dist = {"FEAR": 0, "ANGER": 0, "WITHDRAWAL": 0, "PEOPLE_PLEASING": 0}
                    pmb_dist = {"FIGHT": 0, "FLIGHT": 0, "FREEZE": 0, "FAWN": 0}
                    total_cees_all = 0
                    
                    for client in all_clients:
                        try:
                            cm = metrics_engine.load_metrics({"role": "CLIENT", "hardware_id": client.get("hardware_id")})
                            # Crisis perception
                            cp = cm.get("crisis_perception", {})
                            cp_type = (cp.get("perception_baseline") or "").upper()
                            if cp_type in crisis_perception_dist:
                                crisis_perception_dist[cp_type] += 1
                            # Shame masking
                            sp = cm.get("shame_profile", {})
                            mask = (sp.get("shame_masking_pattern") or "").upper().replace("_MASKED", "")
                            if mask in shame_dist:
                                shame_dist[mask] += 1
                            # PMB reactivity
                            pmb = cm.get("pmb", {})
                            rt = (pmb.get("reactivity_type") or "").upper()
                            if rt in pmb_dist:
                                pmb_dist[rt] += 1
                            # CEEs
                            total_cees_all += cm.get("total_cees", 0)
                        except Exception:
                            pass
                    
                    # Key insights (dynamically generated)
                    key_insights = []
                    if by_age_group:
                        best_age = max(by_age_group.items(), key=lambda x: x[1].get("avg_c_emo", 0))
                        if best_age[1].get("avg_c_emo", 0) > 0:
                            key_insights.append(f"Ages {best_age[0]} show highest baseline coherence ({best_age[1]['avg_c_emo']})")
                    if by_treatment:
                        if by_treatment.get("ai_coach", {}).get("avg_c_emo", 0) > by_treatment.get("ai_only", {}).get("avg_c_emo", 0):
                            base = by_treatment.get("ai_only", {}).get("avg_c_emo", 0.5)
                            coach_val = by_treatment.get("ai_coach", {}).get("avg_c_emo", 0.5)
                            if base > 0:
                                pct = int(((coach_val - base) / base) * 100)
                                key_insights.append(f"AI+Coach treatment {pct}% more effective than AI alone")
                    if count > 0:
                        key_insights.append(f"{count} participants analyzed across cohort")
                    if not key_insights:
                        key_insights = ["Collecting data for insights..."]
                    
                    # Get analytics for total sessions
                    analytics = analytics_engine.get_dashboard_stats()
                    total_sessions = analytics.get("platform_totals", {}).get("total_sessions", 0)
                    avg_cees = round(total_cees_all / count, 1) if count > 0 else 0
                    
                    await websocket.send(json.dumps({
                        "type": "cohort_stats",
                        "platform_avg_c_emo": platform_avg,
                        "total_participants": count,
                        "sample_size": count,
                        "total_sessions": total_sessions,
                        "avg_cees_per_user": avg_cees,
                        "by_age_group": by_age_group,
                        "by_diagnosis": by_diagnosis,
                        "by_treatment": by_treatment,
                        "by_treatment_type": by_treatment,
                        "crisis_perception_distribution": crisis_perception_dist,
                        "shame_distribution": shame_dist,
                        "pmb_distribution": pmb_dist,
                        "key_findings": key_insights,
                        "key_insights": key_insights
                    }))
                  except Exception as cohort_err:
                    print(f"[Cohort] Error processing cohort stats: {cohort_err}")
                    import traceback
                    traceback.print_exc()
                    await websocket.send(json.dumps({
                        "type": "cohort_stats",
                        "platform_avg_c_emo": 0,
                        "total_participants": 0,
                        "sample_size": 0,
                        "total_sessions": 0,
                        "avg_cees_per_user": 0,
                        "by_age_group": {},
                        "by_diagnosis": {},
                        "by_treatment": {},
                        "by_treatment_type": {},
                        "crisis_perception_distribution": {},
                        "shame_distribution": {},
                        "pmb_distribution": {},
                        "key_findings": ["Error loading cohort data"],
                        "key_insights": ["Error loading cohort data"],
                        "error": str(cohort_err)
                    }))

            # === NIGHT SCHOOL: GET WISDOM ===
            elif t == "get_night_school_wisdom":
                if current_profile and current_profile.get("role") in ["COACH", "ADMIN"]:
                    wisdom = night_school.get_wisdom_structured()
                    await websocket.send(json.dumps({
                        "type": "night_school_wisdom",
                        "data": wisdom
                    }))
            
            # === NIGHT SCHOOL: ADD LEARNING (Coach contribution) ===
            elif t == "add_coach_learning":
                if current_profile and current_profile.get("role") == "COACH":
                    content = d.get("content", "")
                    category = d.get("category", "general")
                    if content and len(content) > 10:
                        night_school.add_learning(
                            content=content,
                            source=f"COACH_{current_profile.get('hardware_id')}",
                            filename=f"coach_contribution_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                            category=category
                        )
                        await websocket.send(json.dumps({
                            "type": "learning_added",
                            "message": "Thank you for your contribution!"
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Content too short"
                        }))

            #=================================================================
            # NIGHT SCHOOL CURRICULUM HANDLERS
            # =================================================================
            
            elif t == "get_curriculum_structure":
                if current_profile and current_profile.get("role") == "ADMIN":
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    print(f">>> CURRICULUM PATH: {night_school_curriculum.curriculum_dir}")
                    structure = night_school_curriculum.get_folder_structure()
                    print(f">>> STRUCTURE: {len(structure.get('categories', {}))} categories")
                    for cat_id, cat_data in structure.get('categories', {}).items():
                        if cat_data.get('file_count', 0) > 0:
                            print(f"    {cat_id}: {cat_data.get('file_count')} files")
                    await websocket.send(json.dumps({
                        "type": "curriculum_structure",
                        "data": structure
                    }))
            
            elif t == "upload_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    import base64
                    filename = d.get("filename", "upload.txt")
                    content_b64 = d.get("content", "")
                    category = d.get("category", "_inbox")
                    try:
                        content = base64.b64decode(content_b64)
                        result = night_school_curriculum.upload_file(filename, content, category)
                        if result.get("success"):
                            await websocket.send(json.dumps({"type": "file_uploaded", "data": result}))
                        else:
                            await websocket.send(json.dumps({"type": "error", "message": result.get("error", "Upload failed")}))
                    except Exception as e:
                        print(f">>> [ERROR] Curriculum file upload failed: {e}")
                        await websocket.send(json.dumps({"type": "error", "message": "UPLOAD_FAILED"}))
            
            elif t == "move_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    success = night_school_curriculum.move_to_category(
                        d.get("filename"), d.get("from_category"), d.get("to_category")
                    )
                    await websocket.send(json.dumps({
                        "type": "file_moved" if success else "error",
                        "filename": d.get("filename"),
                        "to_category": d.get("to_category")
                    }))
            
            elif t == "delete_curriculum_file":
                if current_profile and current_profile.get("role") == "ADMIN":
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    success = night_school_curriculum.delete_file(d.get("filename"), d.get("category"))
                    await websocket.send(json.dumps({"type": "file_deleted" if success else "error"}))
            
            elif t == "run_curriculum_ingestion":
                if current_profile and current_profile.get("role") == "ADMIN":
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    await websocket.send(json.dumps({"type": "ingestion_started"}))
                    try:
                        results = await night_school_curriculum.run_ingestion(d.get("categories"))
                        await websocket.send(json.dumps({"type": "ingestion_complete", "results": results}))
                    except Exception as e:
                        print(f">>> [ERROR] Curriculum ingestion failed: {e}")
                        await websocket.send(json.dumps({"type": "error", "message": "INGESTION_FAILED"}))
            
            elif t == "get_curriculum_wisdom":
                if current_profile and current_profile.get("role") in ["ADMIN", "COACH"]:
                    if not night_school_curriculum:
                        await websocket.send(json.dumps({"type": "error", "message": "Curriculum module not available"}))
                        continue
                    category = d.get("category")
                    wisdom = night_school_curriculum.get_wisdom_for_category(category) if category else night_school_curriculum.get_wisdom()
                    await websocket.send(json.dumps({"type": "curriculum_wisdom", "data": wisdom}))
            
            # === SCHEDULE SESSION ===
            elif t == "schedule_session":
                if current_profile:
                    session = session_tracker.schedule_session(
                        client_id=d.get("client_id", uid),
                        coach_id=d.get("coach_id"),
                        scheduled_start=d.get("scheduled_start"),
                        scheduled_end=d.get("scheduled_end"),
                        session_type=d.get("session_type", "COACH")
                    )
                    await websocket.send(json.dumps({"type": "session_scheduled", "session": session}))
            
            # === UPDATE PROFILE ===
            elif t == "update_profile":
                if current_profile:
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            allowed_fields = ["name", "email", "phone", "timezone", "emergency_contact", "profile_photo_url"]
                            for field in allowed_fields:
                                if field in d:
                                    v["profile"][field] = d[field]
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({"type": "profile_updated", "profile": v["profile"]}))
                            break
            
            # === ACCEPT CONSENT UPDATE ===
            elif t == "accept_consent_update":
                if current_profile:
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            v["profile"]["consent_version"] = REQUIRED_CONSENT_VERSION
                            v["profile"]["consent_date"] = str(datetime.datetime.now())
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            current_profile["consent_version"] = REQUIRED_CONSENT_VERSION
                            await websocket.send(json.dumps({
                                "type": "consent_updated",
                                "consent_version": REQUIRED_CONSENT_VERSION,
                                "profile": v["profile"]
                            }))
                            print(f"[Consent] User {uid} accepted consent {REQUIRED_CONSENT_VERSION}")
                            break

            # === UPDATE COACH PROFILE (specialties, coaching_style, zoom_link) ===
            elif t == "update_coach_profile":
                if current_profile and current_profile.get("role") == "COACH":
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            coach_fields = ["specialties", "coaching_style", "zoom_link"]
                            for field in coach_fields:
                                if field in d:
                                    v["profile"][field] = d[field]
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({"type": "profile_updated", "profile": v["profile"]}))
                            break

            # === UPDATE NOTIFICATION PREFERENCES ===
            elif t == "update_notification_prefs":
                if current_profile:
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            if "notification_prefs" not in v["profile"]:
                                v["profile"]["notification_prefs"] = {}
                            prefs_fields = ["push_enabled", "session_reminders", "crisis_alerts",
                                            "new_client_alerts", "night_school_updates", "voice_mode_default"]
                            for field in prefs_fields:
                                if field in d:
                                    v["profile"]["notification_prefs"][field] = d[field]
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({"type": "notification_prefs_updated", "prefs": v["profile"]["notification_prefs"]}))
                            break

            # === UPDATE VOICE PREFERENCE ===
            elif t == "update_voice_preference":
                if current_profile:
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            if "notification_prefs" not in v["profile"]:
                                v["profile"]["notification_prefs"] = {}
                            v["profile"]["notification_prefs"]["voice_mode_default"] = d.get("voice_mode_default", False)
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({"type": "voice_pref_updated", "voice_mode_default": d.get("voice_mode_default", False)}))
                            break

            # === REQUEST ACCOUNT DELETION (30-day soft delete — clients and coaches only) ===
            elif t == "request_account_deletion":
                if current_profile:
                    # Admin accounts cannot be deleted via this endpoint
                    if current_profile.get("role") == "ADMIN":
                        await websocket.send(json.dumps({
                            "type": "account_deletion_denied",
                            "reason": "Admin accounts cannot be deleted through this interface."
                        }))
                        continue
                    registry = load_registry()
                    for k, v in registry.items():
                        if v.get("profile", {}).get("hardware_id") == uid:
                            # Coach guard: cannot delete with active clients
                            if v["profile"].get("role") == "COACH":
                                assigned = v["profile"].get("assigned_clients", [])
                                if assigned and len(assigned) > 0:
                                    await websocket.send(json.dumps({
                                        "type": "account_deletion_denied",
                                        "reason": f"You have {len(assigned)} active client(s). Transfer or unassign them first."
                                    }))
                                    break
                            v["profile"]["account_status"] = "PENDING_DELETION"
                            v["profile"]["deletion_requested_at"] = str(datetime.datetime.now())
                            v["profile"]["updated_at"] = str(datetime.datetime.now())
                            save_registry(registry)
                            await websocket.send(json.dumps({
                                "type": "account_deletion_confirmed",
                                "message": "Account scheduled for deletion in 30 days. Sign back in to restore."
                            }))
                            # Force disconnect
                            await websocket.close()
                            break

            # === GENERATE FAMILY INVITE TOKEN ===
            elif t == "generate_family_invite_token":
                if current_profile:
                    import uuid as _uuid
                    invite_token = str(_uuid.uuid4())[:12].upper()
                    family_id = current_profile.get("family_id")
                    if not family_id:
                        # Auto-create family if head of household and top tier
                        plan = (current_profile.get("subscription_plan") or current_profile.get("tier") or "").upper()
                        if "TOP" in plan or "SOVEREIGN" in plan or "STANDARD" in plan:
                            family_id = f"FAM_{str(_uuid.uuid4())[:8].upper()}"
                            registry = load_registry()
                            for k, v in registry.items():
                                if v.get("profile", {}).get("hardware_id") == uid:
                                    v["profile"]["family_id"] = family_id
                                    v["profile"]["family_role"] = "HEAD"
                                    save_registry(registry)
                                    break
                    if family_id:
                        # Store the invite token in registry under a family_invites key
                        registry = load_registry()
                        if "_family_invites" not in registry:
                            registry["_family_invites"] = {}
                        registry["_family_invites"][invite_token] = {
                            "family_id": family_id,
                            "invited_by": uid,
                            "inviter_name": (current_profile.get("name") or "A family member"),
                            "invitee_name": d.get("invitee_name", ""),
                            "invitee_contact": d.get("invitee_contact", ""),
                            "role": d.get("role", "DEPENDENT"),
                            "created_at": str(datetime.datetime.now()),
                            "expires_at": str(datetime.datetime.now() + datetime.timedelta(days=7))
                        }
                        save_registry(registry)
                        invitee_contact = (d.get("invitee_contact") or "").strip()
                        invitee_name = (d.get("invitee_name") or "").strip()
                        inviter_name = (current_profile.get("name") or "Your family") or "Your family"
                        notification_sent = False
                        notification_method = None
                        if invitee_contact:
                            try:
                                notification_sent = await notification_system.send_family_invitation(
                                    invitee_contact, inviter_name, invite_token, invitee_name
                                )
                                notification_method = "email" if "@" in invitee_contact else "sms"
                                if notification_sent:
                                    print(f">>> [FAMILY_INVITE] Sent {notification_method} to {invitee_contact}")
                                else:
                                    print(f">>> [FAMILY_INVITE] {notification_method} send returned False for {invitee_contact}")
                            except Exception as ex:
                                print(f">>> [FAMILY_INVITE] Could not send to invitee: {ex}")
                        await websocket.send(json.dumps({
                            "type": "family_invite_token_generated",
                            "token": invite_token,
                            "family_id": family_id,
                            "notification_sent": notification_sent,
                            "notification_method": notification_method
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "Sovereign Circle subscription required for family invitations."
                        }))

            # === GENERATE FAMILY INVITE TOKENS — BATCH ===
            elif t == "generate_family_invite_tokens_batch":
                if current_profile:
                    import uuid as _uuid
                    members_list = d.get("members", [])
                    if not isinstance(members_list, list) or len(members_list) == 0:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "No members provided."
                        }))
                        continue
                    if len(members_list) > 10:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "Maximum 10 members per batch."
                        }))
                        continue

                    # Validate max 1 Spouse in batch + existing family
                    spouse_in_batch = sum(1 for m in members_list if (m.get("role") or "").upper() == "SPOUSE")
                    family_id = current_profile.get("family_id")

                    # Check existing family for a spouse
                    existing_spouse = False
                    if family_id:
                        registry_check = load_registry()
                        for _rk, _rv in registry_check.items():
                            if _rk.startswith("_"):
                                continue
                            _rp = _rv.get("profile", {})
                            if _rp.get("family_id") == family_id and (_rp.get("family_role") or "").upper() == "SPOUSE":
                                existing_spouse = True
                                break

                    if spouse_in_batch > 1 or (spouse_in_batch == 1 and existing_spouse):
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "Only one Spouse is allowed per family."
                        }))
                        continue

                    # Check for duplicate contacts in batch
                    contacts_seen = set()
                    has_dupes = False
                    for m in members_list:
                        c = (m.get("contact") or "").strip().lower()
                        if c in contacts_seen:
                            has_dupes = True
                            break
                        contacts_seen.add(c)
                    if has_dupes:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "Duplicate contacts found. Each member must have a unique phone or email."
                        }))
                        continue

                    # Auto-create family if needed
                    if not family_id:
                        plan = (current_profile.get("subscription_plan") or current_profile.get("tier") or "").upper()
                        if "TOP" in plan or "SOVEREIGN" in plan or "STANDARD" in plan:
                            family_id = f"FAM_{str(_uuid.uuid4())[:8].upper()}"
                            registry = load_registry()
                            for k, v in registry.items():
                                if v.get("profile", {}).get("hardware_id") == uid:
                                    v["profile"]["family_id"] = family_id
                                    v["profile"]["family_role"] = "HEAD"
                                    save_registry(registry)
                                    break

                    if not family_id:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "Sovereign Circle subscription required for family invitations."
                        }))
                        continue

                    results = []
                    registry = load_registry()
                    if "_family_invites" not in registry:
                        registry["_family_invites"] = {}

                    inviter_name = (current_profile.get("name") or "Your family") or "Your family"

                    for member in members_list:
                        m_name = (member.get("name") or "").strip()
                        m_contact = (member.get("contact") or "").strip()
                        m_role = (member.get("role") or "DEPENDENT").upper()
                        if not m_name or not m_contact:
                            results.append({
                                "name": m_name or "(empty)",
                                "token": None,
                                "notification_sent": False,
                                "notification_method": None,
                                "error": "Missing name or contact"
                            })
                            continue

                        invite_token = str(_uuid.uuid4())[:12].upper()
                        registry["_family_invites"][invite_token] = {
                            "family_id": family_id,
                            "invited_by": uid,
                            "inviter_name": inviter_name,
                            "invitee_name": m_name,
                            "invitee_contact": m_contact,
                            "role": m_role,
                            "created_at": str(datetime.datetime.now()),
                            "expires_at": str(datetime.datetime.now() + datetime.timedelta(days=7))
                        }

                        notif_sent = False
                        notif_method = None
                        try:
                            notif_sent = await notification_system.send_family_invitation(
                                m_contact, inviter_name, invite_token, m_name
                            )
                            notif_method = "email" if "@" in m_contact else "sms"
                            if notif_sent:
                                print(f">>> [FAMILY_INVITE_BATCH] Sent {notif_method} to {m_contact}")
                            else:
                                print(f">>> [FAMILY_INVITE_BATCH] {notif_method} send returned False for {m_contact}")
                        except Exception as ex:
                            print(f">>> [FAMILY_INVITE_BATCH] Could not send to {m_contact}: {ex}")

                        results.append({
                            "name": m_name,
                            "token": invite_token,
                            "notification_sent": notif_sent,
                            "notification_method": notif_method
                        })

                    save_registry(registry)
                    sent_count = sum(1 for r in results if r.get("notification_sent"))
                    print(f">>> [FAMILY_INVITE_BATCH] {len(results)} invites created, {sent_count} notifications sent for family {family_id}")
                    await websocket.send(json.dumps({
                        "type": "family_invite_batch_result",
                        "family_id": family_id,
                        "results": results,
                        "total": len(results),
                        "sent": sent_count
                    }))

            # === LOOKUP FAMILY INVITE (no auth required) ===
            elif t == "lookup_family_invite":
                token = (d.get("token") or "").strip().upper()
                if token:
                    registry = load_registry()
                    invites = registry.get("_family_invites", {})
                    invite = invites.get(token)
                    if invite:
                        expires = invite.get("expires_at", "")
                        expired = bool(expires and str(datetime.datetime.now()) > expires)
                        await websocket.send(json.dumps({
                            "type": "family_invite_details",
                            "valid": not expired,
                            "inviter_name": invite.get("inviter_name", "A family member"),
                            "invitee_name": invite.get("invitee_name", ""),
                            "role": invite.get("role", "DEPENDENT"),
                            "expires_at": expires,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "family_invite_details",
                            "valid": False,
                            "message": "Invalid or expired invite code."
                        }))
                else:
                    await websocket.send(json.dumps({
                        "type": "family_invite_details",
                        "valid": False,
                        "message": "No invite code provided."
                    }))

            # === ACCEPT FAMILY INVITE (requires auth + consent) ===
            elif t == "accept_family_invite":
                token = d.get("token", "").strip().upper()
                consent_agreed = d.get("consent_agreed", False)
                if current_profile and token:
                    if not consent_agreed:
                        await websocket.send(json.dumps({
                            "type": "family_invite_error",
                            "message": "You must agree to the Privacy Policy and Terms of Use before joining."
                        }))
                    else:
                        registry = load_registry()
                        invites = registry.get("_family_invites", {})
                        invite = invites.get(token)
                        if invite:
                            expires = invite.get("expires_at", "")
                            if expires and str(datetime.datetime.now()) <= expires:
                                # Link the user to the family
                                for k, v in registry.items():
                                    if v.get("profile", {}).get("hardware_id") == uid:
                                        v["profile"]["family_id"] = invite["family_id"]
                                        v["profile"]["family_role"] = invite.get("role", "DEPENDENT")
                                        v["profile"]["linked_by"] = invite.get("invited_by")
                                        v["profile"]["linked_at"] = str(datetime.datetime.now())
                                        v["profile"]["updated_at"] = str(datetime.datetime.now())
                                        # Record consent for family invite acceptance
                                        v["profile"]["family_consent_agreed"] = True
                                        v["profile"]["family_consent_date"] = str(datetime.datetime.now())
                                        v["profile"]["family_consent_version"] = "v13.0_2026"
                                        break
                                # Remove used token
                                del registry["_family_invites"][token]
                                save_registry(registry)
                                await websocket.send(json.dumps({
                                    "type": "family_invite_accepted",
                                    "family_id": invite["family_id"],
                                    "role": invite.get("role", "DEPENDENT")
                                }))
                            else:
                                await websocket.send(json.dumps({"type": "family_invite_error", "message": "Invite token has expired."}))
                        else:
                            await websocket.send(json.dumps({"type": "family_invite_error", "message": "Invalid invite token."}))

            # === COACH INVITE CLIENT (to sign up for tiers) ===
            elif t == "coach_invite_client":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    import uuid as _uuid
                    invitee_name = (d.get("invitee_name") or "").strip()
                    invitee_contact = (d.get("invitee_contact") or "").strip()
                    tier = (d.get("tier") or "STANDARD").upper()
                    if tier not in ("STANDARD", "COACH_ONLY", "SOVEREIGN_CIRCLE", "TOP_TIER"):
                        tier = "STANDARD"
                    if not invitee_contact:
                        await websocket.send(json.dumps({"type": "coach_invite_error", "message": "Contact (email or phone) required"}))
                    else:
                        coach_id = current_profile.get("hardware_id")
                        coach_name = (current_profile.get("name") or "Your coach") or "Your coach"
                        invite_token = str(_uuid.uuid4())[:12].upper()
                        registry = load_registry()
                        if "_coach_invites" not in registry:
                            registry["_coach_invites"] = {}
                        registry["_coach_invites"][invite_token] = {
                            "coach_id": coach_id,
                            "coach_name": coach_name,
                            "invitee_name": invitee_name,
                            "invitee_contact": invitee_contact,
                            "tier": tier,
                            "created_at": str(datetime.datetime.now()),
                            "expires_at": str(datetime.datetime.now() + datetime.timedelta(days=14))
                        }
                        save_registry(registry)
                        try:
                            await notification_system.send_coach_invite_client(
                                invitee_contact, coach_name, invite_token, invitee_name, tier
                            )
                        except Exception as ex:
                            print(f">>> [COACH_INVITE] Could not send: {ex}")
                        await websocket.send(json.dumps({
                            "type": "coach_invite_sent",
                            "token": invite_token,
                            "message": "Invitation sent to invitee"
                        }))
                else:
                    await websocket.send(json.dumps({"type": "coach_invite_error", "message": "COACH_ONLY"}))

            # === GET NOTIFICATIONS ===
            elif t == "get_notifications":
                if current_profile:
                    unread_only = d.get("unread_only", False)
                    notifications = notification_system.get_user_notifications(uid, unread_only=unread_only)
                    unread_count = notification_system.get_unread_count(uid)
                    await websocket.send(json.dumps({
                        "type": "notifications_data",
                        "notifications": notifications,
                        "unread_count": unread_count
                    }))
            
            # === MARK NOTIFICATION READ ===
            elif t == "mark_notification_read":
                if current_profile:
                    notification_id = d.get("notification_id")
                    success = notification_system.mark_read(notification_id)
                    await websocket.send(json.dumps({
                        "type": "notification_marked_read",
                        "success": success
                    }))
            
            # === MARK ALL NOTIFICATIONS READ ===
            elif t == "mark_all_notifications_read":
                if current_profile:
                    count = notification_system.mark_all_read(uid)
                    await websocket.send(json.dumps({
                        "type": "notifications_marked_read",
                        "count": count
                    }))
            
            # === GET STRIPE CHECKOUT URL ===
            elif t == "get_checkout_url":
                if current_profile:
                    plan = d.get("plan", "STANDARD")
                    billing_cycle = d.get("billing_cycle", "monthly")
                    success_url = d.get("success_url", "https://app.sovereignsanctuary.ai/success")
                    cancel_url = d.get("cancel_url", "https://app.sovereignsanctuary.ai/billing")
                    
                    url = await billing_system.create_checkout_session(
                        uid, plan, billing_cycle, success_url, cancel_url
                    )
                    await websocket.send(json.dumps({
                        "type": "checkout_url",
                        "url": url
                    }))
            
            # === GET STRIPE PORTAL URL (Manage Subscription) ===
            elif t == "get_portal_url":
                if current_profile:
                    return_url = d.get("return_url", "https://app.sovereignsanctuary.ai/billing")
                    url = await billing_system.create_portal_session(uid, return_url)
                    await websocket.send(json.dumps({
                        "type": "portal_url",
                        "url": url
                    }))
            
            # === CANCEL SUBSCRIPTION ===
            elif t == "cancel_subscription":
                if current_profile:
                    reason = d.get("reason", "")
                    success = billing_system.cancel_subscription(uid, reason)
                    await websocket.send(json.dumps({
                        "type": "subscription_cancelled",
                        "success": success
                    }))

            # === CHANGE SUBSCRIPTION (Upgrade or Downgrade) ===
            elif t in ("change_subscription", "upgrade_subscription"):
                if current_profile:
                    new_plan = (d.get("plan") or "").strip().upper()
                    valid_plans = ["COACH_ONLY", "TRIAL", "STANDARD", "TOP_TIER"]
                    plan_hierarchy = {"COACH_ONLY": 0, "TRIAL": 0, "STANDARD": 1, "TOP_TIER": 2}
                    plan_names = {"COACH_ONLY": "Coach Only", "TRIAL": "Threshold", "STANDARD": "Inner Chamber", "TOP_TIER": "Sovereign Circle"}
                    # Aligned with config/standing_orders_seed.json
                    plan_details = {
                        "COACH_ONLY": {"tokens": 0, "price": 0},
                        "TRIAL": {"tokens": 10000, "price": 0},
                        "STANDARD": {"tokens": 50000, "price": 49},
                        "TOP_TIER": {"tokens": 200000, "price": 149},
                    }

                    if new_plan not in valid_plans:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": f"Invalid plan: {new_plan}. Valid: {', '.join(valid_plans)}"
                        }))
                    else:
                        current_plan = (current_profile.get("subscription_plan") or "TRIAL").upper()
                        current_rank = plan_hierarchy.get(current_plan, 0)
                        new_rank = plan_hierarchy.get(new_plan, 0)

                        if new_rank == current_rank:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "You are already on this plan."
                            }))
                        else:
                            is_upgrade = new_rank > current_rank
                            is_downgrade = new_rank < current_rank
                            details = plan_details.get(new_plan, plan_details["STANDARD"])
                            now = datetime.datetime.now()

                            # Determine current billing cycle end (30 days from last billing)
                            billing_data = billing_system.get_subscription(uid) if billing_system else None
                            if billing_data and billing_data.get("end_date"):
                                try:
                                    cycle_end = datetime.datetime.strptime(billing_data["end_date"], "%Y-%m-%d")
                                    if cycle_end < now:
                                        cycle_end = now + datetime.timedelta(days=30)
                                except (ValueError, TypeError):
                                    cycle_end = now + datetime.timedelta(days=30)
                            else:
                                cycle_end = now + datetime.timedelta(days=30)

                            # Highest tier this cycle for billing (30-day policy)
                            billed_plan = current_plan if current_rank > new_rank else new_plan
                            billed_price = plan_details.get(billed_plan, {}).get("price", 0)

                            registry = load_registry()
                            for k, v in registry.items():
                                if v.get("profile", {}).get("hardware_id") == uid:
                                    prof = v["profile"]

                                    # NEVER touch vault/history/sessions/metrics — only plan metadata
                                    prof["previous_plan"] = current_plan
                                    prof["plan_changed_at"] = str(now)
                                    prof["billed_plan_this_cycle"] = billed_plan
                                    prof["billed_price_this_cycle"] = billed_price
                                    prof["billing_cycle_end"] = str(cycle_end.date())

                                    if is_upgrade:
                                        # Upgrade: immediate access, new tokens, new plan
                                        prof["subscription_plan"] = new_plan
                                        prof["subscription_status"] = "ACTIVE"
                                        prof["token_balance"] = max(
                                            prof.get("token_balance", 0),
                                            details["tokens"]
                                        )
                                        prof.pop("pending_plan", None)
                                        prof.pop("pending_plan_effective", None)
                                    else:
                                        # Downgrade: keep current plan active until cycle end,
                                        # schedule new plan for next cycle
                                        prof["pending_plan"] = new_plan
                                        prof["pending_plan_effective"] = str(cycle_end.date())
                                        # Keep current subscription_plan unchanged for now
                                        # (access continues at current tier through cycle end)

                                    save_registry(registry)

                                    # Update in-memory profile
                                    if is_upgrade:
                                        current_profile["subscription_plan"] = new_plan
                                        current_profile["token_balance"] = prof["token_balance"]
                                    current_profile["pending_plan"] = prof.get("pending_plan", "")
                                    current_profile["pending_plan_effective"] = prof.get("pending_plan_effective", "")
                                    break

                            # Update billing system record
                            try:
                                if is_upgrade:
                                    billing_system.create_subscription(uid, new_plan)
                                # Record the billing event
                                billing_system.record_transaction(
                                    uid,
                                    billed_price,
                                    f"Plan change: {plan_names.get(current_plan, current_plan)} → {plan_names.get(new_plan, new_plan)} "
                                    f"(billed at {plan_names.get(billed_plan, billed_plan)} rate for 30-day policy)",
                                    transaction_type="plan_change",
                                    metadata={
                                        "from_plan": current_plan,
                                        "to_plan": new_plan,
                                        "direction": "upgrade" if is_upgrade else "downgrade",
                                        "billed_plan": billed_plan,
                                        "billed_price": billed_price,
                                        "cycle_end": str(cycle_end.date()),
                                    }
                                )
                            except Exception as e:
                                print(f"[PlanChange] Billing record error (non-fatal): {e}")

                            direction = "upgrade" if is_upgrade else "downgrade"
                            print(f"[PlanChange] User {uid} {direction}: {current_plan} → {new_plan} "
                                  f"(billed at {billed_plan} ${billed_price}/mo through {cycle_end.date()})")

                            await websocket.send(json.dumps({
                                "type": "subscription_changed",
                                "direction": direction,
                                "plan": new_plan if is_upgrade else current_plan,
                                "plan_name": plan_names.get(new_plan, new_plan),
                                "pending_plan": "" if is_upgrade else new_plan,
                                "pending_plan_effective": "" if is_upgrade else str(cycle_end.date()),
                                "token_balance": current_profile.get("token_balance", 0),
                                "billed_plan": billed_plan,
                                "billed_price": billed_price,
                                "billing_cycle_end": str(cycle_end.date()),
                                "monthly_price": details["price"],
                                "data_preserved": True,
                                "profile": current_profile,
                            }))


            # =================================================================
            # DEVICE MANAGEMENT HANDLERS
            # =================================================================
            
            # === GET MY DEVICES ===
            elif t == "get_my_devices":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        # Reconstruct from uid
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    devices = get_user_devices(user_id)
                    tier = current_profile.get("tier", "STANDARD")
                    plan = current_profile.get("subscription_plan", "")
                    device_limit = get_device_limit(tier, plan)
                    
                    # Mark current device
                    req_hardware_id = d.get("hardware_id", current_hardware_id)
                    for device in devices:
                        device["is_current"] = device.get("hardware_id") == req_hardware_id
                    
                    await websocket.send(json.dumps({
                        "type": "my_devices",
                        "devices": devices,
                        "device_limit": device_limit
                    }))
            
            # === REMOVE DEVICE ===
            elif t == "remove_device":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    device_id = d.get("device_id", "")
                    success, message = remove_device(user_id, device_id)
                    
                    await websocket.send(json.dumps({
                        "type": "device_removed" if success else "device_remove_failed",
                        "success": success,
                        "message": message
                    }))
            
            # === LOGOUT ALL DEVICES ===
            elif t == "logout_all_devices":
                if current_profile:
                    user_id = f"{current_profile.get('role', 'CLIENT').lower()}_{d.get('username', '')}"
                    if not user_id or user_id.endswith('_'):
                        user_id = uid.replace('CLIENT_', 'client_').replace('COACH_', 'coach_').replace('ADMIN_', 'admin_')
                    
                    success, message = force_logout_all_devices(user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "all_devices_logged_out" if success else "logout_failed",
                        "success": success,
                        "message": message
                    }))
            
            # === ADMIN: GET USER DEVICES ===
            elif t == "admin_get_user_devices":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_user_id = d.get("user_id", "")
                    devices_info = admin_get_user_devices(target_user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "admin_user_devices",
                        "user_id": target_user_id,
                        "data": devices_info
                    }))
            
            # === ADMIN: RESET USER DEVICES ===
            elif t == "admin_reset_user_devices":
                if current_profile and current_profile.get("role") == "ADMIN":
                    target_user_id = d.get("user_id", "")
                    success, message = admin_reset_user_devices(target_user_id)
                    
                    await websocket.send(json.dumps({
                        "type": "admin_devices_reset",
                        "success": success,
                        "message": message,
                        "user_id": target_user_id
                    }))
            # === ASK NATE (COACHING) ===
            elif t == "ask_nate_coaching":
                if current_profile:
                    query = d.get("query", "")
                    client_id = d.get("client_id", "")
                    
                    # Don't wrap Dojo simulation messages - pass through directly
                    # process_interaction handles workbook guidance injection for all messages
                    if query.startswith("[DOJO SIMULATION"):
                        # JUDGE DOJO access gating: CLIENT role must have judge_dojo_access
                        dojo_mode = d.get("mode", "")
                        if dojo_mode == "judge" and current_profile.get("role") == "CLIENT":
                            if not current_profile.get("judge_dojo_access"):
                                await websocket.send(json.dumps({
                                    "type": "error",
                                    "message": "Access denied. You must be verified by your coaching lawyer for JUDGE DOJO access."
                                }))
                                continue
                        coaching_prompt = query
                    elif client_id:
                        coaching_prompt = f"[Coach asking about client {client_id}]: {query}"
                    else:
                        coaching_prompt = f"[Coach question]: {query}"
                    await cortex.process_interaction(current_profile, coaching_prompt)

            # =================================================================
            # HELP & FAQ — Little Nate as Platform Guide (stateless, no memory)
            # =================================================================
            elif t == "help_query":
                help_text = d.get("text", "").strip()
                help_role = d.get("role", "CLIENT").upper()
                if help_text:
                    system_prompt = CLIENT_HELP_SYSTEM_PROMPT if help_role == "CLIENT" else COACH_HELP_SYSTEM_PROMPT
                    user_name = d.get("name", "there")
                    if user_name:
                        help_text = f"(User's name is {user_name}.) {help_text}"
                    print(f">>> [HELP] {help_role} query received ({len(help_text)} chars)")
                    try:
                        import aiohttp as _aio_help
                        async with _aio_help.ClientSession() as _help_session:
                            async with _help_session.ws_connect(
                                AZURE_ENDPOINT,
                                headers={"api-key": AZURE_API_KEY, "OpenAI-Beta": "realtime=v1"}
                            ) as azure_ws:
                                await azure_ws.send_str(json.dumps({
                                    "type": "session.update",
                                    "session": {
                                        "modalities": ["text"],
                                        "instructions": system_prompt,
                                        "voice": "ballad",
                                        "turn_detection": None
                                    }
                                }))
                                await azure_ws.send_str(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "message",
                                        "role": "user",
                                        "content": [{"type": "input_text", "text": help_text}]
                                    }
                                }))
                                await azure_ws.send_str(json.dumps({"type": "response.create"}))
                                full_response = ""
                                async for msg in azure_ws:
                                    if msg.type == _aio_help.WSMsgType.TEXT:
                                        event = json.loads(msg.data)
                                        evt = event.get("type")
                                        if evt == "response.text.delta":
                                            full_response += event.get("delta", "")
                                            await websocket.send(json.dumps({
                                                "type": "nate_help_response",
                                                "text": full_response
                                            }))
                                        elif evt in ("response.text.done", "response.done"):
                                            break
                                        elif evt == "error":
                                            print(f">>> [HELP] Azure error: {event}")
                                            break
                        await websocket.send(json.dumps({
                            "type": "nate_help_done",
                            "text": full_response
                        }))
                        print(f">>> [HELP] Response sent ({len(full_response)} chars)")
                    except Exception as e:
                        print(f">>> [HELP] Error: {e}")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "HELP_QUERY_FAILED"
                        }))

            # =================================================================
            # === SECURE INTERNET SEARCH (3-Layer + Results Review) ===
            # =================================================================
            
            # --- STEP 1: Coach requests a search ---
            elif t == "search_request":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    query = d.get("query", "").strip()
                    mode = d.get("mode", "")
                    persona = d.get("persona", "")
                    coach_id = uid
                    coach_name = current_profile.get("name", uid)
                    
                    if not query:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Empty search query"
                        }))
                    else:
                        # Ask Nate to suggest a clean search query
                        import hashlib as _hashlib
                        request_id = "SEARCH_" + _hashlib.md5(
                            f"{coach_id}_{time.time()}".encode()
                        ).hexdigest()[:10].upper()
                        
                        # Create search request in state machine
                        req = search_requests.create(
                            request_id=request_id,
                            coach_id=coach_id,
                            coach_name=coach_name,
                            original_query=query,
                            suggested_search=query,  # Will be refined by Nate
                            mode=mode,
                            persona=persona
                        )
                        
                        search_proxy.audit.log_event("search_requested", coach_id,
                            request_id=request_id, query=query)
                        
                        # Send back the proposed search for coach approval
                        await websocket.send(json.dumps({
                            "type": "search_query_proposed",
                            "request_id": request_id,
                            "suggested_query": query,
                            "original_query": query,
                            "requires_2fa": totp_manager.is_enabled(coach_id),
                            "message": "Review the search query below. Approve to proceed."
                        }))
            
            # --- STEP 2: Coach approves the query ---
            elif t == "search_coach_approve":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    request_id = d.get("request_id", "")
                    edited_query = d.get("edited_query", "")
                    req = search_requests.get(request_id)
                    
                    if not req:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Search request not found or expired"
                        }))
                    elif req.coach_id != uid:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Not your search request"
                        }))
                    elif req.is_expired:
                        req.state = "expired"
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Search request expired (15 min limit)"
                        }))
                    else:
                        # Update query if coach edited it
                        if edited_query:
                            req.suggested_search = edited_query
                        
                        req.state = "coach_approved"
                        search_proxy.audit.log_event("coach_approved", uid,
                            request_id=request_id, query=req.suggested_search)
                        
                        # Check if 2FA is required
                        if totp_manager.is_enabled(uid):
                            req.state = "awaiting_2fa"
                            await websocket.send(json.dumps({
                                "type": "search_2fa_required",
                                "request_id": request_id,
                                "message": "Enter your 6-digit authenticator code"
                            }))
                        else:
                            # Skip 2FA, go straight to admin approval
                            req.state = "awaiting_admin"
                            await websocket.send(json.dumps({
                                "type": "search_awaiting_admin",
                                "request_id": request_id,
                                "message": "Waiting for admin approval..."
                            }))
                            
                            # Notify all connected admins
                            registry = load_registry()
                            for rk, rv in registry.items():
                                p = rv.get("profile", {})
                                if p.get("role") == "ADMIN":
                                    admin_uid = p.get("hardware_id")
                                    if admin_uid and admin_uid in cortex.sockets:
                                        for ws in list(cortex.sockets[admin_uid]):
                                            try:
                                                await ws.send(json.dumps({
                                                    "type": "search_pending_admin",
                                                    "request": req.to_dict()
                                                }))
                                            except:
                                                pass
            
            # --- STEP 3: Coach submits 2FA code ---
            elif t == "search_2fa_verify":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    request_id = d.get("request_id", "")
                    code = d.get("code", "").strip()
                    req = search_requests.get(request_id)
                    
                    if not req or req.coach_id != uid:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Search request not found"
                        }))
                    else:
                        verified, msg = totp_manager.verify_code(uid, code)
                        
                        if verified:
                            req.state = "awaiting_admin"
                            search_proxy.audit.log_event("2fa_verified", uid,
                                request_id=request_id)
                            
                            await websocket.send(json.dumps({
                                "type": "search_awaiting_admin",
                                "request_id": request_id,
                                "message": "2FA verified. Waiting for admin approval..."
                            }))
                            
                            # Notify all connected admins
                            registry = load_registry()
                            for rk, rv in registry.items():
                                p = rv.get("profile", {})
                                if p.get("role") == "ADMIN":
                                    admin_uid = p.get("hardware_id")
                                    if admin_uid and admin_uid in cortex.sockets:
                                        for ws in list(cortex.sockets[admin_uid]):
                                            try:
                                                await ws.send(json.dumps({
                                                    "type": "search_pending_admin",
                                                    "request": req.to_dict()
                                                }))
                                            except:
                                                pass
                        else:
                            search_proxy.audit.log_event("2fa_failed", uid,
                                request_id=request_id)
                            await websocket.send(json.dumps({
                                "type": "search_2fa_failed",
                                "request_id": request_id,
                                "message": msg
                            }))
            
            # --- STEP 4: Admin approves or denies ---
            elif t == "search_admin_decision":
                if current_profile and current_profile.get("role") == "ADMIN":
                    request_id = d.get("request_id", "")
                    approved = d.get("approved", False)
                    reason = d.get("reason", "")
                    req = search_requests.get(request_id)
                    
                    if not req:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Search request not found or expired"
                        }))
                    elif req.state != "awaiting_admin":
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": f"Search is in state '{req.state}', not awaiting admin"
                        }))
                    else:
                        req.admin_approver_id = uid
                        req.admin_approver_name = current_profile.get("name", uid)
                        
                        if approved:
                            req.state = "executing"
                            search_proxy.audit.log_event("admin_approved", uid,
                                request_id=request_id,
                                coach_id=req.coach_id,
                                admin_name=req.admin_approver_name)
                            
                            # Execute the search
                            results = await search_proxy.execute_search(
                                req.suggested_search, req.coach_id
                            )
                            
                            if results["success"]:
                                req.results = results["results"]
                                req.state = "results_review"
                                
                                # Send results to coach for review
                                coach_uid = req.coach_id
                                if coach_uid in cortex.sockets:
                                    for ws in list(cortex.sockets[coach_uid]):
                                        try:
                                            await ws.send(json.dumps({
                                                "type": "search_results_review",
                                                "request_id": request_id,
                                                "results": results["results"],
                                                "has_warnings": results.get("has_safety_warnings", False),
                                                "message": "Review results below. Uncheck any suspicious ones before sending to Nate."
                                            }))
                                        except:
                                            pass
                            else:
                                req.state = "error"
                                req.error_message = results.get("error", "Unknown error")
                                coach_uid = req.coach_id
                                if coach_uid in cortex.sockets:
                                    for ws in list(cortex.sockets[coach_uid]):
                                        try:
                                            await ws.send(json.dumps({
                                                "type": "search_error",
                                                "request_id": request_id,
                                                "error": req.error_message
                                            }))
                                        except:
                                            pass
                        else:
                            req.state = "denied"
                            req.deny_reason = reason
                            search_proxy.audit.log_event("admin_denied", uid,
                                request_id=request_id,
                                coach_id=req.coach_id,
                                reason=reason)
                            
                            # Notify coach
                            coach_uid = req.coach_id
                            if coach_uid in cortex.sockets:
                                for ws in list(cortex.sockets[coach_uid]):
                                    try:
                                        await ws.send(json.dumps({
                                            "type": "search_denied",
                                            "request_id": request_id,
                                            "denied_by": req.admin_approver_name,
                                            "reason": reason or "Admin denied the search request"
                                        }))
                                    except:
                                        pass
                        
                        # Confirm to admin
                        await websocket.send(json.dumps({
                            "type": "search_admin_confirmed",
                            "request_id": request_id,
                            "approved": approved,
                            "coach_name": req.coach_name,
                            "query": req.suggested_search
                        }))
            
            # --- STEP 5: Coach reviews and confirms results ---
            elif t == "search_results_confirmed":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    request_id = d.get("request_id", "")
                    approved_indices = d.get("approved_indices", [])  # List of result indices coach approved
                    req = search_requests.get(request_id)
                    
                    if not req or req.coach_id != uid:
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Search request not found"
                        }))
                    elif req.state != "results_review":
                        await websocket.send(json.dumps({
                            "type": "search_error",
                            "error": "Results not ready for review"
                        }))
                    else:
                        # Filter to only approved results
                        req.approved_results = [
                            req.results[i] for i in approved_indices
                            if 0 <= i < len(req.results)
                        ]
                        
                        search_proxy.audit.log_event("results_confirmed", uid,
                            request_id=request_id,
                            total_results=len(req.results),
                            approved_count=len(req.approved_results))
                        
                        if not req.approved_results:
                            req.state = "completed"
                            await websocket.send(json.dumps({
                                "type": "search_complete",
                                "request_id": request_id,
                                "message": "No results approved. Search cancelled."
                            }))
                        else:
                            # Format approved results as context for Nate
                            search_context = search_proxy.format_for_nate(req.approved_results)
                            req.state = "completed"
                            
                            # Build prompt with search context
                            coaching_prompt = (
                                f"[DOJO SIMULATION - {req.mode.upper()} / {req.persona} PERSONA] "
                                f"{req.original_query}\n\n{search_context}"
                            )
                            
                            # Send to Nate
                            await cortex.process_interaction(current_profile, coaching_prompt)
                            
                            await websocket.send(json.dumps({
                                "type": "search_complete",
                                "request_id": request_id,
                                "approved_count": len(req.approved_results),
                                "message": f"Nate is processing {len(req.approved_results)} approved search results..."
                            }))
                        
                        # Clean up
                        search_requests.remove(request_id)
            
            # --- Coach denies search at any stage ---
            elif t == "search_cancel":
                if current_profile:
                    request_id = d.get("request_id", "")
                    req = search_requests.get(request_id)
                    if req and req.coach_id == uid:
                        req.state = "denied"
                        req.deny_reason = "Cancelled by coach"
                        search_proxy.audit.log_event("coach_cancelled", uid,
                            request_id=request_id)
                        search_requests.remove(request_id)
                    await websocket.send(json.dumps({
                        "type": "search_cancelled",
                        "request_id": request_id
                    }))
            
            # --- Admin: get pending search requests ---
            elif t == "admin_get_pending_searches":
                if current_profile and current_profile.get("role") == "ADMIN":
                    pending = search_requests.get_pending_admin()
                    await websocket.send(json.dumps({
                        "type": "admin_pending_searches",
                        "requests": [r.to_dict() for r in pending]
                    }))
            
            # --- Coach: setup 2FA ---
            elif t == "search_setup_2fa":
                if current_profile and current_profile.get("role") in ("COACH", "ADMIN"):
                    coach_name = current_profile.get("name", uid)
                    result = totp_manager.generate_secret(uid, coach_name)
                    await websocket.send(json.dumps({
                        "type": "search_2fa_setup",
                        **result
                    }))
            
            # --- Check search availability ---
            elif t == "search_check_available":
                if current_profile:
                    await websocket.send(json.dumps({
                        "type": "search_availability",
                        "available": search_proxy.is_available,
                        "has_2fa": totp_manager.is_enabled(uid),
                        "has_pyotp": totp_manager.has_pyotp(),
                    }))
            
            # =================================================================
            # === END SECURE SEARCH HANDLERS ===
            # =================================================================
            
            # === ONBOARDING COMPLETION ===
            elif t == "mark_onboarding_complete":
                if current_profile and uid:
                    try:
                        registry = load_registry()
                        for k, v in registry.items():
                            if v.get("profile", {}).get("hardware_id") == uid:
                                v["profile"]["onboarding_completed"] = True
                                save_registry(registry)
                                current_profile["onboarding_completed"] = True
                                break
                        await websocket.send(json.dumps({
                            "type": "onboarding_marked_complete",
                            "success": True
                        }))
                        print(f"[Onboarding] Marked complete for {uid}")
                    except Exception as e:
                        print(f"[Onboarding] Error marking complete: {e}")
                        await websocket.send(json.dumps({
                            "type": "onboarding_marked_complete",
                            "success": False
                        }))
            
            elif t == "set_onboarding_seen":
                target_uid = (data.get("user_id") or uid or "").toString()
                if target_uid:
                    try:
                        registry = load_registry()
                        for k, v in registry.items():
                            if v.get("profile", {}).get("hardware_id") == target_uid:
                                v["profile"]["has_seen_onboarding"] = True
                                save_registry(registry)
                                if current_profile and (current_profile.get("hardware_id") == target_uid):
                                    current_profile["has_seen_onboarding"] = True
                                break
                        await websocket.send(json.dumps({"type": "onboarding_seen_set", "success": True}))
                        print(f"[Onboarding] has_seen_onboarding set for {target_uid}")
                    except Exception as e:
                        print(f"[Onboarding] Error set_onboarding_seen: {e}")
                else:
                    await websocket.send(json.dumps({"type": "onboarding_seen_set", "success": False, "message": "user_id required"}))
            
            elif t == "set_paid_onboarding_seen":
                target_uid = (data.get("user_id") or uid or "").toString()
                if target_uid:
                    try:
                        registry = load_registry()
                        for k, v in registry.items():
                            if v.get("profile", {}).get("hardware_id") == target_uid:
                                v["profile"]["has_seen_paid_onboarding"] = True
                                save_registry(registry)
                                if current_profile and (current_profile.get("hardware_id") == target_uid):
                                    current_profile["has_seen_paid_onboarding"] = True
                                break
                        await websocket.send(json.dumps({"type": "paid_onboarding_seen_set", "success": True}))
                        print(f"[Onboarding] has_seen_paid_onboarding set for {target_uid}")
                    except Exception as e:
                        print(f"[Onboarding] Error set_paid_onboarding_seen: {e}")
                else:
                    await websocket.send(json.dumps({"type": "paid_onboarding_seen_set", "success": False, "message": "user_id required"}))
            
            elif t == "sanctuary_get_or_create":
                """
                Smart handler that:
                1. Finds existing sanctuary for family OR creates new one
                2. Handles reconnection without duplicates
                3. Notifies other members only for true new joins
                """
                if not current_profile:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Not authenticated"
                    }))
                else:
                    _sanc_plan = (current_profile.get("subscription_plan") or "").upper()
                    if _sanc_plan in ("COACH_ONLY",) or current_profile.get("can_access_nate") == False:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "COACH_ONLY_NO_AI",
                            "detail": "Your plan is scheduling-only. Sanctuary is not available."
                        }))
                        continue
                    if _sanc_plan not in ("STANDARD", "INNER_CHAMBER", "TOP_TIER", "SOVEREIGN_CIRCLE"):
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "FAMILY_SANCTUARY_UPGRADE_REQUIRED",
                            "detail": "Family Sanctuary requires Inner Chamber ($49/mo) or Sovereign Circle ($149/mo) subscription."
                        }))
                        continue
                
                family_id = current_profile.get('family_id')
                member_id = current_profile.get('hardware_id')
                member_name = current_profile.get('name')
                
                print(f">>> [SANCTUARY] Processing get_or_create for {member_name} ({member_id}) in family {family_id}")
                
                # Check for existing sanctuary
                existing = sanctuary_engine.get_active_sanctuary_for_family(family_id)
                
                if existing:
                    sanctuary_id = existing['sanctuary_id']
                    print(f">>> [SANCTUARY] Found existing sanctuary: {sanctuary_id}")
                    
                    # Add or reconnect member
                    result = await sanctuary_engine.add_or_reconnect_member(
                        sanctuary_id=sanctuary_id,
                        user_id=member_id,
                        user_name=member_name,
                        websocket=websocket
                    )
                    
                    if not result['success']:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": result.get('error', 'Failed to join')
                        }))
                        continue
                    
                    members = sanctuary_engine.get_member_list(sanctuary_id)
                    action = result['action']

                    async def _deliver_group_coaching_to_member() -> None:
                        """
                        If a group coaching round is ACTIVE, ensure the currently-connecting member
                        receives their private suggested response (even on reconnect/refresh).
                        """
                        try:
                            s = sanctuary_engine.get_session(sanctuary_id) or {}
                            round_obj = s.get("group_coaching_round") or {}
                            if round_obj.get("status") != "ACTIVE":
                                return

                            mid = member_id
                            if not mid:
                                return

                            round_obj.setdefault("members_expected", [])
                            if mid not in round_obj["members_expected"]:
                                round_obj["members_expected"].append(mid)

                            responses = round_obj.setdefault("responses", {})
                            responses.setdefault(mid, {"state": "PENDING"})

                            suggestions = round_obj.setdefault("suggestions", {})
                            delivered_to = round_obj.setdefault("delivered_to", {})
                            suggestion = suggestions.get(mid)
                            delivered = bool(delivered_to.get(mid, False))

                            payload = None
                            if suggestion and not delivered:
                                payload = dict(suggestion)
                            elif not suggestion:
                                # Build minimal profiles for AI generation
                                def _get_profile_by_hardware_id(hid: str) -> dict:
                                    reg = load_registry()
                                    for _, v in (reg or {}).items():
                                        p = v.get("profile", {})
                                        if p.get("hardware_id") == hid:
                                            return dict(p)
                                    return {"hardware_id": hid, "name": hid}

                                members_now = sanctuary_engine.get_member_list(sanctuary_id)
                                member_profiles = []
                                for m in members_now:
                                    hid = m.get("user_id")
                                    if not hid:
                                        continue
                                    p = _get_profile_by_hardware_id(hid)
                                    p["sanctuary_role"] = m.get("role", "MEMBER")
                                    p["metrics"] = cortex.metrics.load_metrics(p)
                                    p["memory"] = cortex.mem.recall(p, limit=5) or ""
                                    member_profiles.append(p)

                                me = next((p for p in member_profiles if p.get("hardware_id") == mid), _get_profile_by_hardware_id(mid))
                                others = [p for p in member_profiles if p.get("hardware_id") != mid]
                                recent_msgs = (s.get("messages") or [])[-15:]
                                sug = await cortex.generate_group_coaching_response(
                                    target_member=me,
                                    other_members=others,
                                    recent_messages=recent_msgs,
                                    sanctuary_data=s,
                                )
                                total_charges = float((sanctuary_engine.get_session(sanctuary_id) or {}).get("billing", {}).get("total_charges", 0.0))
                                payload = {
                                    "suggested_text": sug.get("suggested_response", ""),
                                    "rationale": sug.get("rationale", ""),
                                    "target_audience": sug.get("target_audience", "the family"),
                                    "emotional_tone": sug.get("emotional_tone", "supportive"),
                                    "total_charges": total_charges,
                                }
                                suggestions[mid] = payload

                            # Already delivered and suggestion exists; nothing to do
                            if payload is None:
                                return

                            delivered_to[mid] = True
                            sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                            sanctuary_engine._save()

                            await websocket.send(json.dumps({
                                "type": "sanctuary_suggested_response",
                                "sanctuary_id": sanctuary_id,
                                **payload,
                            }))

                            # Broadcast updated waiting list
                            name_map = {m.get("user_id"): m.get("name") for m in sanctuary_engine.get_member_list(sanctuary_id)}
                            pending_ids = [x for x, r in (round_obj.get("responses") or {}).items() if (r or {}).get("state") == "PENDING"]
                            waiting_on = [name_map.get(x, x) for x in pending_ids]
                            await sanctuary_engine.broadcast_to_sanctuary(
                                sanctuary_id=sanctuary_id,
                                message_data={
                                    "type": "sanctuary_group_coaching_status",
                                    "sanctuary_id": sanctuary_id,
                                    "state": "ACTIVE",
                                    "waiting_on": waiting_on,
                                }
                            )
                        except Exception as e:
                            print(f">>> [GROUP COACHING] delivery error: {e}")
                    
                    if action == "JOINED":
                        # Truly new member
                        await websocket.send(json.dumps({
                            "type": "sanctuary_joined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                            "members": members,
                            "messages": existing.get("messages", [])[-50:]
                        }))
                        await _deliver_group_coaching_to_member()
                        
                        # Notify others (but skip members in coaching - don't interrupt them)
                        sanctuary_data_joined = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        for other_m in sanctuary_data_joined.get('members', []):
                            if other_m.get('user_id') != member_id and other_m.get('status') != 'IN_COACHING':
                                other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_m.get('user_id'))
                                if other_ws:
                                    try:
                                        await other_ws.send(json.dumps({
                                            "type": "sanctuary_member_joined",
                                            "member": {"id": member_id, "name": member_name}
                                        }))
                                    except:
                                        pass
                        
                        # CHECK IF SOMEONE IS IN COACHING - Offer coaching to new member
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data_joined.get('coaching_sessions', {})
                            
                            # Find who is in coaching
                            in_coaching = []
                            for cs in coaching_sessions.values():
                                if cs.get('status') == 'ACTIVE':
                                    in_coaching.append(cs.get('member_name', 'A family member'))
                            
                            if in_coaching:
                                # Check if new member gets free coaching (yes, first time!)
                                is_free = True  # New member always gets first free
                                cost = 0.00
                                
                                # Send coaching OFFER (popup) to new member
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_offer",
                                    "sanctuary_id": sanctuary_id,
                                    "intervention_id": f"COACH_NEWJOIN_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                    "is_free": is_free,
                                    "cost": cost,
                                    "trigger_member": in_coaching[0],
                                    "message": f"{in_coaching[0]} is receiving private coaching. Would you also like coaching support?"
                                }))
                                print(f">>> [SANCTUARY] Sent coaching offer to new member {member_name}")
                        
                    elif action in ["RECONNECTED", "REFRESHED"]:
                        # Returning member (page refresh or reconnecting)
                        # Get message history
                        sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        message_history = sanctuary_data.get("messages", [])[-50:]  # Last 50 messages
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_reconnected",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                            "members": members,
                            "messages": message_history,
                            "message": f"Welcome back, {member_name}!"
                        }))

                        await _deliver_group_coaching_to_member()
                        
                        # CHECK IF SANCTUARY IS PAUSED DUE TO COACHING
                        if existing.get('status') == 'COACHING_ACTIVE':
                            coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                            
                            # Check if THIS member is the one in coaching
                            my_coaching = coaching_sessions.get(member_id, {})
                            if my_coaching.get('status') == 'ACTIVE':
                                # Resume their coaching session!
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_resumed",
                                    "sanctuary_id": sanctuary_id,
                                    "coaching_session": my_coaching,
                                    "message": "Welcome back to your coaching session."
                                }))
                            else:
                                # Someone ELSE is in coaching - send coaching OFFER (not just pause)
                                in_coaching_names = []
                                for cs in coaching_sessions.values():
                                    if cs.get('status') == 'ACTIVE':
                                        in_coaching_names.append(cs.get('member_name', 'A family member'))
                                
                                if in_coaching_names:
                                    # Check if this member has used free coaching
                                    member_data = next((m for m in sanctuary_data.get('members', []) if m.get('user_id') == member_id), {})
                                    is_free = not member_data.get('free_coaching_used', False)
                                    cost = 0.00 if is_free else 5.00
                                    
                                    # Send coaching OFFER popup (not just pause)
                                    await websocket.send(json.dumps({
                                        "type": "sanctuary_coaching_offer",
                                        "sanctuary_id": sanctuary_id,
                                        "intervention_id": f"COACH_RECONNECT_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                        "is_free": is_free,
                                        "cost": cost,
                                        "trigger_member": in_coaching_names[0],
                                        "message": f"{in_coaching_names[0]} is receiving private coaching. Would you also like coaching support?"
                                    }))
                                    print(f">>> [SANCTUARY] Sent coaching offer to reconnecting member {member_name}")

                    
                    
                    elif action == "RETURNED":
                        # Member who had exited is returning
                        await websocket.send(json.dumps({
                            "type": "sanctuary_rejoined",
                            "sanctuary_id": sanctuary_id,
                            "status": existing.get('status', 'ACTIVE'),
                            "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                            "members": members,
                            "messages": sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {}).get("messages", [])[-50:],
                            "message": f"Welcome back to the sanctuary, {member_name}!"
                        }))

                        await _deliver_group_coaching_to_member()
                        
                        # Notify others that member returned (skip those in coaching)
                        sanctuary_data_ret = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                        for other_m in sanctuary_data_ret.get('members', []):
                            if other_m.get('user_id') != member_id and other_m.get('status') != 'IN_COACHING':
                                other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_m.get('user_id'))
                                if other_ws:
                                    try:
                                        await other_ws.send(json.dumps({
                                            "type": "sanctuary_member_returned",
                                            "member": {"id": member_id, "name": member_name}
                                        }))
                                    except:
                                        pass
                        
                        # CHECK IF THIS MEMBER HAS AN ACTIVE COACHING SESSION TO RESUME
                        coaching_sessions = sanctuary_data_ret.get('coaching_sessions', {})
                        my_coaching = coaching_sessions.get(member_id, {})
                        
                        if my_coaching.get('status') == 'ACTIVE':
                            # RESUME their coaching session!
                            print(f">>> [SANCTUARY] Resuming coaching session for returning member {member_name}")
                            
                            # Restore member status to IN_COACHING
                            member_obj = next((m for m in sanctuary_data_ret.get('members', []) if m.get('user_id') == member_id), None)
                            if member_obj:
                                member_obj['status'] = 'IN_COACHING'
                                sanctuary_engine._save()
                            
                            await websocket.send(json.dumps({
                                "type": "sanctuary_coaching_resumed",
                                "sanctuary_id": sanctuary_id,
                                "coaching_session": my_coaching,
                                "message": "Welcome back! Let's continue our coaching conversation."
                            }))
                        
                        # ELSE CHECK IF SOMEONE ELSE IS IN COACHING - Offer coaching to returning member
                        elif existing.get('status') == 'COACHING_ACTIVE':
                            # Find who is in coaching (not this member)
                            in_coaching = []
                            for cs in coaching_sessions.values():
                                if cs.get('status') == 'ACTIVE' and cs.get('member_id') != member_id:
                                    in_coaching.append(cs.get('member_name', 'A family member'))
                            
                            if in_coaching:
                                # Check if returning member has used free coaching
                                member_data = next((m for m in sanctuary_data_ret.get('members', []) if m.get('user_id') == member_id), {})
                                is_free = not member_data.get('free_coaching_used', False)
                                cost = 0.00 if is_free else 5.00
                                
                                # Send coaching OFFER (popup) to returning member
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_coaching_offer",
                                    "sanctuary_id": sanctuary_id,
                                    "intervention_id": f"COACH_RETURN_{member_id}_{int(datetime.datetime.now().timestamp())}",
                                    "is_free": is_free,
                                    "cost": cost,
                                    "trigger_member": in_coaching[0],
                                    "message": f"{in_coaching[0]} is receiving private coaching. Would you also like coaching support?"
                                }))
                                print(f">>> [SANCTUARY] Sent coaching offer to returning member {member_name}")
                else:
                    print(f">>> [SANCTUARY] No existing sanctuary, creating new one for family {family_id}")
                    
                    # Check if creator is HEAD of household
                    family_role = current_profile.get('family_role', 'MEMBER')
                    is_head = family_role == 'HEAD'
                    
                    # Find HEAD of household for this family
                    head_of_household_id = None
                    user_registry = load_registry()  # Load the registry first
                    for user_key, user_data in user_registry.items():
                        profile = user_data.get('profile', {})
                        if profile.get('family_id') == family_id and profile.get('family_role') == 'HEAD':
                            head_of_household_id = profile.get('hardware_id')
                            break
                    
                    # If no HEAD found, use creator as HEAD
                    if not head_of_household_id:
                        head_of_household_id = member_id
                    
                    # Create new sanctuary
                    sanctuary_id = await sanctuary_engine.create_sanctuary(
                        family_id=family_id,
                        head_of_household_id=head_of_household_id,
                        invited_members=[],
                        initial_topic='',
                        consent_data={}
                    )
                    
                    # Store who actually created it (may differ from head)
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["created_by"] = member_id
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["creator_name"] = member_name
                    sanctuary_engine._save()
                    
                    # Add creator as first member
                    await sanctuary_engine.add_or_reconnect_member(
                        sanctuary_id=sanctuary_id,
                        user_id=member_id,
                        user_name=member_name,
                        websocket=websocket
                    )

                    # Charge (or record) the $20 base fee to the family HEAD.
                    # This ensures all UIs see authoritative `total_charges` immediately.
                    try:
                        await sanctuary_engine.charge_base_fee(
                            sanctuary_id=sanctuary_id,
                            head_of_household_id=head_of_household_id,
                        )
                    except Exception as e:
                        print(f">>> [SANCTUARY] Base fee charge call failed: {e}")
                    
                    # If non-HEAD created, notify HEAD for approval
                    if not is_head and head_of_household_id != member_id:
                        print(f">>> [SANCTUARY] Non-HEAD member {member_name} created sanctuary, notifying HEAD")
                        # Send approval request to HEAD (they'll see it when they join)
                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["pending_approval"] = True
                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["approval_requested_by"] = member_name
                        sanctuary_engine._save()

                    # Build authoritative billing snapshot
                    try:
                        s = sanctuary_engine.get_session(sanctuary_id) or {}
                        billing = (s.get("billing") or {}) if isinstance(s, dict) else {}
                        base_fee_charged = bool(billing.get("base_fee_charged", False))
                    except Exception:
                        base_fee_charged = False
                    total_charges = sanctuary_engine.get_total_charges(sanctuary_id)

                    await websocket.send(json.dumps({
                        "type": "sanctuary_created",
                        "sanctuary_id": sanctuary_id,
                        "status": "WAITING_FOR_MEMBERS",
                        "base_fee_charged": base_fee_charged,
                        "total_charges": total_charges,
                        "is_creator": True
                    }))

                    try:
                        nate_result = await cortex.process_sanctuary_message(
                            sanctuary_data=sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {}),
                            family_profiles=[current_profile],
                            recent_messages=[],
                            trigger="session_start"
                        )
                        if nate_result.get("response"):
                            await websocket.send(json.dumps({
                                "type": "sanctuary_onboarding",
                                "message": nate_result.get("response")
                            }))
                    except Exception as e:
                        print(f">>> [SANCTUARY] Opening error: {e}")

            elif t == "sanctuary_join":
                        """
                        Family member joins existing sanctuary
                        """
                        sanctuary_id = d.get('sanctuary_id')
                        
                        # Verify invitation
                        if not await sanctuary_engine.verify_invitation(
                            sanctuary_id, current_profile['hardware_id']
                        ):
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "You are not invited to this sanctuary"
                            }))
                            continue
                        
                        # Add member to session
                        await sanctuary_engine.add_member(
                            sanctuary_id=sanctuary_id,
                            user_id=current_profile['hardware_id'],
                            websocket=websocket
                        )
                        
                        # Get current members list
                        members_list = sanctuary_engine.get_member_list(sanctuary_id)
                        
                        # Send onboarding message from Little Nate
                        onboarding_message = f"""Welcome to Family Sanctuary, {current_profile['name']}. I'm Little Nate, and I'll be facilitating this conversation to help your family find connection and understanding.

                    Currently in the sanctuary:
                    {chr(10).join(['• ' + name for name in members_list])}

                    Before we begin, please share:
                    1. What brought you to this Family Sanctuary today?
                    2. What's your goal for this conversation?
                    3. What concerns or issues are you experiencing?

                    This information is confidential and will help me provide better support."""
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_onboarding",
                            "sanctuary_id": sanctuary_id,
                            "message": onboarding_message,
                            "current_members": members_list
                        }))

            elif t == "sanctuary_onboarding_complete":
                        """
                        Member completes onboarding questions
                        """
                        sanctuary_id = d.get('sanctuary_id')
                        responses = d.get('responses', {})
                        
                        # Store confidential responses
                        await sanctuary_engine.store_member_input(
                            sanctuary_id=sanctuary_id,
                            user_id=current_profile['hardware_id'],
                            initial_reason=responses.get('reason', ''),
                            personal_goal=responses.get('goal', ''),
                            family_concerns=responses.get('concerns', '')
                        )
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_entry_complete",
                            "sanctuary_id": sanctuary_id,
                            "message": "Thank you for sharing."
                        }))
                        
                        # Get sanctuary data for entry_ready
                        sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                        members = sanctuary_engine.get_member_list(sanctuary_id)
                        
                        # Send entry_ready to transition to chat
                        await websocket.send(json.dumps({
                            "type": "sanctuary_entry_ready",
                            "sanctuary_id": sanctuary_id,
                            "status": sanctuary_data.get("status", "ACTIVE"),
                            "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                            "members": members,
                            "messages": sanctuary_data.get("messages", [])[-50:]
                        }))
                        
                        # Check if all members joined
                        if sanctuary_engine.all_members_joined(sanctuary_id):
                            # Start session
                            await sanctuary_engine.start_session(sanctuary_id)

            elif t == "sanctuary_message":
                        """
                        Member sends message in sanctuary
                        """
                        sanctuary_id = d.get('sanctuary_id')
                        message = d.get('message', '')
                        
                        if not message.strip():
                            continue
                        
                        # Store message
                        message_id = await sanctuary_engine.add_message(
                            sanctuary_id=sanctuary_id,
                            sender_id=current_profile['hardware_id'],
                            content=message
                        )
                        
                        # Broadcast to all members
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_message",
                                "message_type": "MEMBER_MESSAGE",
                                "sender_id": current_profile['hardware_id'],
                                "sender_name": current_profile['name'],
                                "content": message,
                                "timestamp": datetime.datetime.now().isoformat()
                            }
                        )
                        
                        # CRITICAL: Monitor for escalation
                        escalation_detected = await sanctuary_engine.detect_escalation(
                            sanctuary_id=sanctuary_id,
                            message_id=message_id,
                            message_content=message,
                            sender_id=current_profile['hardware_id']
                        )
                        
                        if escalation_detected:
                            # Trigger intervention
                            await sanctuary_engine.trigger_intervention(
                                sanctuary_id=sanctuary_id,
                                triggered_by_message_id=message_id
                            )
                        
                        # Patent 3: Ventriloquism Detection
                        try:
                            sanctuary_engine.detect_ventriloquism(
                                sanctuary_id=sanctuary_id,
                                message_content=message,
                                sender_id=current_profile['hardware_id'],
                                sender_name=current_profile.get('name', '')
                            )
                        except Exception:
                            pass

                        # GROUP COACHING OFFER (Head approval; cooldown after approval)
                        # Any member can request; HEAD approves/declines.
                        # Cooldown duration is configurable via env var (default 5 minutes).
                        try:
                            import os as _os
                            GROUP_COACHING_COOLDOWN_SECONDS = int(_os.getenv("SANCTUARY_GROUP_COACHING_COOLDOWN_SECONDS", "300") or 300)
                        except Exception:
                            GROUP_COACHING_COOLDOWN_SECONDS = 300

                        advice_keywords = [
                            "what should we do", "what should i do", "what do we do",
                            "help us", "guide us", "advise us", "advice",
                            "how do we", "how should we", "what's the best way",
                            "little nate help", "little nate what", "nate help",
                            "what do you suggest", "what do you recommend",
                            "can you help us", "we need help", "i need help",
                            "help little nate", "need help little nate",
                            "little nate can you", "little nate could you", "little nate please",
                            "little nate guide", "guidance", "get guide", "get guidance",
                            "group coaching", "group therapy",
                            "stuck"
                        ]

                        msg_lower = message.lower()
                        def _little_nate_distress_call(txt: str) -> bool:
                            # Trigger when Little Nate is explicitly referenced AND the message indicates help/distress,
                            # even if it doesn't contain the exact "help us" phrasing.
                            t = (txt or "").lower()
                            if "little nate" not in t and not t.strip().startswith("nate "):
                                return False
                            distress_markers = [
                                # Explicit help/attention
                                "help", "i need help", "we need help", "need you", "please",
                                # The user's examples / close variants
                                "stop this", "are you kidding", "kidding me", "this is too much", "too much",
                                # Common distress language
                                "overwhelmed", "panic", "panicking", "freaking out", "can't do this", "cant do this",
                                "i can't", "im scared", "i'm scared", "scared", "anxious", "anxiety",
                                "not okay", "not ok", "unsafe",
                            ]
                            return any(m in t for m in distress_markers)

                        if any(kw in msg_lower for kw in advice_keywords) or _little_nate_distress_call(msg_lower):
                            import time as _time
                            sanctuary_data_now = sanctuary_engine.get_session(sanctuary_id) or {}

                            # If a group coaching round is already active, tell requester we're waiting on responses.
                            round_now = sanctuary_data_now.get("group_coaching_round") or {}
                            if round_now.get("status") == "ACTIVE":
                                responses = (round_now.get("responses") or {})
                                pending_ids = [mid for mid, r in responses.items() if (r or {}).get("state") == "PENDING"]
                                name_map = {m.get("user_id"): m.get("name") for m in sanctuary_engine.get_member_list(sanctuary_id)}
                                waiting_on = [name_map.get(mid, mid) for mid in pending_ids]
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_group_coaching_status",
                                    "sanctuary_id": sanctuary_id,
                                    "state": "ACTIVE",
                                    "waiting_on": waiting_on,
                                    "my_state": (responses.get(current_profile.get("hardware_id")) or {}).get("state", "PENDING"),
                                }))
                                try:
                                    analytics_engine.record_event("sanctuary_group_coaching_requested_while_active", current_profile.get("hardware_id"), {
                                        "sanctuary_id": sanctuary_id,
                                        "family_id": sanctuary_data_now.get("family_id"),
                                        "requested_text": (message or "")[:240],
                                        "waiting_on": waiting_on,
                                    })
                                except Exception:
                                    pass
                                continue

                            # If there's already a pending request, don't spam HEAD with multiple offers.
                            pending = sanctuary_data_now.get("pending_group_coaching_request")
                            if pending:
                                # Keep the most recent request timestamp (optional)
                                sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["pending_group_coaching_request"] = {
                                    **pending,
                                    "last_requested_at": _time.time(),
                                }
                                sanctuary_engine._save()
                                # Let requester know it's pending approval
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_group_coaching_status",
                                    "sanctuary_id": sanctuary_id,
                                    "state": "PENDING_APPROVAL",
                                    "requested_by": pending.get("requested_by_name"),
                                    "requested_text": pending.get("requested_text"),
                                    "requested_at": pending.get("requested_at"),
                                }))
                                try:
                                    analytics_engine.record_event("sanctuary_group_coaching_request_updated", current_profile.get("hardware_id"), {
                                        "sanctuary_id": sanctuary_id,
                                        "family_id": sanctuary_data_now.get("family_id"),
                                        "requested_by_id": pending.get("requested_by_id"),
                                        "requested_by_name": pending.get("requested_by_name"),
                                        "requested_text": (pending.get("requested_text") or "")[:240],
                                        "last_requested_at": _time.time(),
                                    })
                                except Exception:
                                    pass
                            else:
                                # Cooldown starts after ROUND COMPLETES (not after offer display)
                                last_completed = float(sanctuary_data_now.get("last_group_coaching_completed", 0) or 0)
                                now = _time.time()
                                cooldown_remaining = max(0, int((last_completed + GROUP_COACHING_COOLDOWN_SECONDS) - now)) if last_completed else 0

                                if last_completed and cooldown_remaining > 0:
                                    # Let requester know we're in cooldown and when it ends
                                    await websocket.send(json.dumps({
                                        "type": "sanctuary_group_coaching_status",
                                        "sanctuary_id": sanctuary_id,
                                        "state": "COOLDOWN",
                                        "cooldown_seconds_remaining": cooldown_remaining,
                                        "cooldown_ends_at": int(last_completed + GROUP_COACHING_COOLDOWN_SECONDS),
                                    }))
                                    try:
                                        analytics_engine.record_event("sanctuary_group_coaching_blocked_cooldown", current_profile.get("hardware_id"), {
                                            "sanctuary_id": sanctuary_id,
                                            "family_id": sanctuary_data_now.get("family_id"),
                                            "cooldown_seconds_remaining": cooldown_remaining,
                                            "cooldown_ends_at": int(last_completed + GROUP_COACHING_COOLDOWN_SECONDS),
                                        })
                                    except Exception:
                                        pass
                                else:
                                    request = {
                                        "requested_by_id": current_profile.get("hardware_id"),
                                        "requested_by_name": current_profile.get("name", "A family member"),
                                        "requested_text": message,
                                        "requested_at": now,
                                    }
                                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["pending_group_coaching_request"] = request
                                    sanctuary_engine._save()

                                    try:
                                        analytics_engine.record_event("sanctuary_group_coaching_requested", current_profile.get("hardware_id"), {
                                            "sanctuary_id": sanctuary_id,
                                            "family_id": sanctuary_data_now.get("family_id"),
                                            "requested_by_id": request.get("requested_by_id"),
                                            "requested_by_name": request.get("requested_by_name"),
                                            "requested_text": (request.get("requested_text") or "")[:240],
                                            "requested_at": request.get("requested_at"),
                                            "cost": 20.00,
                                        })
                                    except Exception:
                                        pass

                                    head_id = sanctuary_data_now.get("head_of_household_id")
                                    head_ws = sanctuary_engine.get_member_websocket(sanctuary_id, head_id) if head_id else None
                                    if head_ws:
                                        await head_ws.send(json.dumps({
                                            "type": "sanctuary_group_coaching_offer",
                                            "sanctuary_id": sanctuary_id,
                                            "cost": 20.00,
                                            "triggered_by": request["requested_by_name"],
                                            "requested_text": request["requested_text"],
                                            "message": (
                                                f"{request['requested_by_name']} is asking for guidance. "
                                                "Approve Group Coaching ($20) to generate private, personalized 'words to say' for each member."
                                            ),
                                        }))
                                        print(">>> [SANCTUARY] Group coaching offer sent to HEAD")
                                        try:
                                            analytics_engine.record_event("sanctuary_group_coaching_offer_sent_to_head", head_id, {
                                                "sanctuary_id": sanctuary_id,
                                                "family_id": sanctuary_data_now.get("family_id"),
                                                "triggered_by": request.get("requested_by_name"),
                                                "requested_by_id": request.get("requested_by_id"),
                                                "cost": 20.00,
                                            })
                                        except Exception:
                                            pass

                                    # Broadcast status so UIs can show "pending approval"
                                    await sanctuary_engine.broadcast_to_sanctuary(
                                        sanctuary_id=sanctuary_id,
                                        message_data={
                                            "type": "sanctuary_group_coaching_status",
                                            "sanctuary_id": sanctuary_id,
                                            "state": "PENDING_APPROVAL",
                                            "requested_by": request["requested_by_name"],
                                            "requested_text": request["requested_text"],
                                            "requested_at": request["requested_at"],
                                        }
                                    )

                                    # Also broadcast a visible Little Nate message so the family understands what happened.
                                    try:
                                        nate_notice = {
                                            "message_id": f"NATE_GC_{int(_time.time())}",
                                            "message_type": "LITTLE_NATE",
                                            "sender_id": "LITTLE_NATE",
                                            "sender_name": "Little Nate",
                                            "content": (
                                                "I can help with guidance here. I’ve asked the family HEAD to approve Group Coaching "
                                                "(\$20). Once approved, I’ll generate private, personalized ‘words to say’ for each member."
                                            ),
                                            "timestamp": datetime.datetime.now().isoformat(),
                                        }
                                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["messages"].append(nate_notice)
                                        sanctuary_engine._save()
                                        await sanctuary_engine.broadcast_to_sanctuary(
                                            sanctuary_id=sanctuary_id,
                                            message_data={"type": "sanctuary_message", "message": nate_notice},
                                        )
                                    except Exception:
                                        pass

            elif t == "sanctuary_coaching_message":
                """
                Member sends message in private coaching session
                """
                sanctuary_id = d.get('sanctuary_id')
                message_content = d.get('message', '')
                
                if not message_content.strip():
                    continue
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                

                # ===== OOPS DETECTION (First message only) =====
                coaching_session_check = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                is_first_message = len(coaching_session_check.get("messages", [])) <= 1
                
                oops_keywords = ["oops", "wrong", "mistake", "didn't mean", "accident", "back", "exit", "leave", "return", "go back"]
                is_oops = is_first_message and any(kw in message_content.lower() for kw in oops_keywords)
                
                if is_oops:
                    sanctuary_engine.end_coaching_session(sanctuary_id, member_id)
                    
                    await websocket.send(json.dumps({
                        "type": "sanctuary_coaching_completed",
                        "sanctuary_id": sanctuary_id,
                        "message": "No problem! Heading back to the sanctuary.",
                        "was_early_exit": True
                    }))
                    
                    await sanctuary_engine.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_member_returned",
                            "member_id": member_id,
                            "member_name": member_name,
                            "message": f"{member_name} has returned to the sanctuary."
                        }
                    )
                    
                    if not sanctuary_engine.get_active_coaching_sessions(sanctuary_id):
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_resumed",
                                "message": "Everyone is back. The sanctuary conversation can continue. 💙"
                            }
                        )
                    continue
                # ===== END OOPS DETECTION =====

                # Store user's message
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="user",
                    content=message_content
                )
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Increment attempt
                coaching_session["attempt_number"] = coaching_session.get("attempt_number", 0) + 1
                attempt_number = coaching_session["attempt_number"]
                
                # Get max steps (default 5, can be extended with $5 payment)
                max_steps = coaching_session.get("max_steps", 5)
                
                # CHECK IF LIMIT REACHED (step 6+ without extension)
                if attempt_number > max_steps:
                    # User has exceeded their allowed steps - send limit reached message
                    is_deescalated = coaching_session.get("is_deescalated", False)
                    
                    await websocket.send(json.dumps({
                        "type": "sanctuary_coaching_limit_reached",
                        "sanctuary_id": sanctuary_id,
                        "attempt_number": attempt_number,
                        "max_steps": max_steps,
                        "is_deescalated": is_deescalated,
                        "options": {
                            "continue_cost": 5.00,
                            "assisted_response_cost": 3.00
                        },
                        "message": f"You've completed {max_steps} coaching exchanges. Would you like to continue or return to your family?"
                    }))
                    
                    # Decrement the attempt since we're not processing this message
                    coaching_session["attempt_number"] = max_steps
                    sanctuary_engine.update_coaching_session(
                        sanctuary_id=sanctuary_id,
                        member_id=member_id,
                        updates={"attempt_number": max_steps}
                    )
                    continue
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate Little Nate's response
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="coaching_response"
                )
                
                # Store Little Nate's response
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="assistant",
                    content=result["response"]
                )
                
                # Update coaching session
                sanctuary_engine.update_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    updates={
                        "attempt_number": attempt_number,
                        "is_deescalated": result.get("is_deescalated", False)
                    }
                )
                
                # Build response
                response_data = {
                    "type": "sanctuary_coaching_response",
                    "sanctuary_id": sanctuary_id,
                    "coaching_message": {
                        "role": "assistant",
                        "content": result["response"],
                        "attempt_number": attempt_number
                    },
                    "is_deescalated": result.get("is_deescalated", False),
                    # Must respect extensions (max_steps can be > 5)
                    "attempts_remaining": max(0, max_steps - attempt_number)
                }
                
                # Check if should offer assisted response
                if result.get("should_offer_assisted"):
                    response_data["offer_assisted_response"] = True
                    response_data["assisted_response_cost"] = 3.00
                    response_data["assisted_response_message"] = "Would you like me to help craft a response for you? For $3, I can express your feelings in a way your family can hear."
                
                await websocket.send(json.dumps(response_data))


            elif t == "sanctuary_coaching_accept":
                """
                Member accepts coaching offer - START private 1-on-1 session
                """
                sanctuary_id = d.get('sanctuary_id')
                intervention_id = d.get('intervention_id')
                wants_assisted_response = d.get('assisted_response', False)
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Check if this is member's first coaching
                member_coaching_count = sanctuary_engine.get_member_coaching_count(
                    sanctuary_id, member_id
                )
                
                # Determine charge
                if member_coaching_count == 0:
                    charge_amount = 0.00
                    is_free = True
                else:
                    charge_amount = 5.00
                    is_free = False
                
                # Charge if not free
                if not is_free:
                    sanctuary = sanctuary_engine.get_session(sanctuary_id)
                    charge_result = await sanctuary_engine.charge_coaching(
                        sanctuary_id=sanctuary_id,
                        intervention_id=intervention_id,
                        member_id=member_id,
                        amount=charge_amount
                    )
                    
                    if not charge_result[0]:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Payment failed. Please try again."
                        }))
                        continue
                
                # Start private coaching session
                coaching_session = sanctuary_engine.start_private_coaching(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    intervention_id=intervention_id
                )
                
                # Get sanctuary data for context
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate initial coaching message
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="coaching_start"
                )
                
                # Store Little Nate's opening message
                sanctuary_engine.add_coaching_message(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    role="assistant",
                    content=result["response"]
                )
                
                # Increment coaching count
                sanctuary_engine.increment_coaching_count(sanctuary_id, member_id)
                
                # Notify member that coaching started
                free_msg = "🎁 Your first coaching is FREE!" if is_free else f"💰 Coaching: ${charge_amount:.2f}"
                
                sanctuary_total = 0.0
                try:
                    sanctuary_total = float(
                        (sanctuary_engine.get_session(sanctuary_id) or {})
                        .get("billing", {})
                        .get("total_charges", 0.0)
                    )
                except Exception:
                    sanctuary_total = 0.0

                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_started",
                    "sanctuary_id": sanctuary_id,
                    "intervention_id": intervention_id,
                    "is_free": is_free,
                    "charge_amount": charge_amount,
                    "total_charges": sanctuary_total,
                    "message": free_msg,
                    "coaching_message": {
                        "role": "assistant",
                        "content": result["response"],
                        "attempt_number": 1
                    }
                }))
           
                # BROADCAST to group chat that member stepped away
                cost_text = "FREE" if is_free else f"${charge_amount:.2f}"
                stepped_away_msg = {
                    "message_id": f"SYS_{int(datetime.datetime.now().timestamp())}",
                    "message_type": "SYSTEM",
                    "sender_id": "SYSTEM",
                    "sender_name": "System",
                    "content": f"💙 {member_name} has stepped away for private coaching with Little Nate ({cost_text})",
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
                # Add to sanctuary messages
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["messages"].append(stepped_away_msg)
                sanctuary_engine._save()
                
                # Broadcast to all connected members
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_message",
                        "message": stepped_away_msg,
                    },
                )
                
                # Notify other members and OFFER them coaching too
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                other_members = [m for m in sanctuary_data.get('members', []) if m.get('user_id') != member_id]
                
                for other_member in other_members:
                    other_id = other_member.get('user_id')
                    other_name = other_member.get('name', 'Friend')
                    
                    # SKIP if this member is already in their own coaching session
                    if other_member.get('status') == 'IN_COACHING':
                        print(f">>> [SANCTUARY] Skipping offer to {other_name} - already in coaching")
                        continue
                    
                    # Check if they've used free coaching
                    other_free = not other_member.get('free_coaching_used', False)
                    other_cost = 0.00 if other_free else 5.00
                    
                    # Get their websocket
                    other_ws = sanctuary_engine.get_member_websocket(sanctuary_id, other_id)
                    if other_ws:
                        try:
                            # Send coaching offer (shows popup modal)
                            await other_ws.send(json.dumps({
                                "type": "sanctuary_coaching_offer",
                                "sanctuary_id": sanctuary_id,
                                "intervention_id": f"COACH_OFFER_{other_id}_{int(datetime.datetime.now().timestamp())}",
                                "is_free": other_free,
                                "cost": other_cost,
                                "trigger_member": member_name,
                                "message": f"{member_name} is receiving private coaching. Would you also like coaching support?"
                            }))
                            print(f">>> [SANCTUARY] Sent coaching offer to {other_name} (free={other_free})")
                        except Exception as e:
                            print(f">>> [SANCTUARY] Failed to send offer to {other_name}: {e}")
                            # Fall back to just pause notification
                            try:
                                await other_ws.send(json.dumps({
                                    "type": "sanctuary_member_coaching",
                                    "member_id": member_id,
                                    "member_name": member_name,
                                    "message": f"{member_name} is receiving private support from Little Nate. The sanctuary is paused."
                                }))
                            except:
                                pass


            elif t == "sanctuary_coaching_extend":
                """
                Member pays $5 to continue coaching for 5 more steps
                """
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(sanctuary_id, member_id)
                if not coaching_session or coaching_session.get('status') != 'ACTIVE':
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Charge $5 for extension
                charge_result = await sanctuary_engine.charge_coaching(
                    sanctuary_id=sanctuary_id,
                    intervention_id=coaching_session.get("intervention_id", ""),
                    member_id=member_id,
                    amount=5.00
                )
                
                if not charge_result[0]:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Payment failed. Please try again."
                    }))
                    continue
                
                # Extend the session by 5 more steps
                current_max = coaching_session.get("max_steps", 5)
                new_max = current_max + 5
                
                sanctuary_engine.update_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    updates={"max_steps": new_max}
                )
                
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_extended",
                    "sanctuary_id": sanctuary_id,
                    "new_max_steps": new_max,
                    "charge_amount": 5.00,
                    "total_charges": float((sanctuary_engine.get_session(sanctuary_id) or {}).get("billing", {}).get("total_charges", 0.0)),
                    "message": f"Your coaching session has been extended! You now have {new_max - coaching_session.get('attempt_number', 0)} more exchanges available. 💙"
                }))
                
                print(f">>> [COACHING] Extended session for {member_name} to {new_max} steps (+$5)")

            elif t == "sanctuary_coaching_complete":
                """
                Member ends private coaching and returns to sanctuary
                """
                sanctuary_id = d.get('sanctuary_id')
                request_assisted_response = d.get('request_assisted_response', False)
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                assisted_response = None
                
                # Generate assisted response if requested
                if request_assisted_response:
                    # Charge $3 for assisted response (distinct ledger type)
                    charge_result = await sanctuary_engine.charge_assisted_response(
                        sanctuary_id=sanctuary_id,
                        member_id=member_id,
                        amount=3.00,
                    )
                    
                    if charge_result[0]:
                        sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                        
                        result = await cortex.process_private_coaching(
                            member_profile=current_profile,
                            sanctuary_data=sanctuary_data,
                            coaching_session=coaching_session,
                            trigger="generate_assisted_response"
                        )
                        
                        # Parse the assisted response
                        response_text = result.get("response", "")
                        if "SUGGESTED_RESPONSE:" in response_text:
                            parts = response_text.split("SUGGESTED_RESPONSE:")
                            if len(parts) > 1:
                                assisted_part = parts[1]
                                if "EXPLANATION:" in assisted_part:
                                    assisted_response = assisted_part.split("EXPLANATION:")[0].strip()
                                else:
                                    assisted_response = assisted_part.strip()
                        else:
                            assisted_response = response_text
                
                # End the coaching session
                sanctuary_engine.end_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                # Check if all coaching sessions are complete BEFORE sending completion
                active_coaching = sanctuary_engine.get_active_coaching_sessions(sanctuary_id)
                others_still_coaching = [c for c in active_coaching if c.get('member_id') != member_id]
                sanctuary_is_resumed = len(others_still_coaching) == 0
                
                # Send completion to member with sanctuary status
                await websocket.send(json.dumps({
                    "type": "sanctuary_coaching_completed",
                    "sanctuary_id": sanctuary_id,
                    "message": f"Welcome back, {member_name}. You're ready to reconnect with your family.",
                    "assisted_response": assisted_response,
                    "sanctuary_resumed": sanctuary_is_resumed,
                    "others_in_coaching": len(others_still_coaching),
                }))
                
                # Notify sanctuary that member is back
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_member_returned",
                        "member_id": member_id,
                        "member_name": member_name,
                        "message": f"{member_name} has returned to the sanctuary."
                    }
                )
                
                # Broadcast resume if all coaching done
                if sanctuary_is_resumed:
                    # All coaching done - sanctuary resumes
                    await sanctuary_engine.broadcast_to_sanctuary(
                        sanctuary_id=sanctuary_id,
                        message_data={
                            "type": "sanctuary_resumed",
                            "message": "Everyone is back. The sanctuary conversation can continue. 💙"
                        }
                    )

            elif t == "sanctuary_request_assisted_response":
                """
                Member requests assisted response during coaching (the $3 add-on)
                """
                sanctuary_id = d.get('sanctuary_id')
                
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                # Get coaching session
                coaching_session = sanctuary_engine.get_coaching_session(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id
                )
                
                if not coaching_session:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No active coaching session found."
                    }))
                    continue
                
                # Charge $3 for assisted response
                charge_result = await sanctuary_engine.charge_assisted_response(
                    sanctuary_id=sanctuary_id,
                    member_id=member_id,
                    amount=3.00,
                )
                
                if not charge_result[0]:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Payment failed. Please try again."
                    }))
                    continue
                
                # Get sanctuary data
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                
                # Generate assisted response
                result = await cortex.process_private_coaching(
                    member_profile=current_profile,
                    sanctuary_data=sanctuary_data,
                    coaching_session=coaching_session,
                    trigger="generate_assisted_response"
                )
                
                # Parse the assisted response
                response_text = result.get("response", "")
                assisted_response = ""
                explanation = ""
                
                if "SUGGESTED_RESPONSE:" in response_text:
                    parts = response_text.split("SUGGESTED_RESPONSE:")
                    if len(parts) > 1:
                        assisted_part = parts[1]
                        if "EXPLANATION:" in assisted_part:
                            split_parts = assisted_part.split("EXPLANATION:")
                            assisted_response = split_parts[0].strip()
                            explanation = split_parts[1].strip() if len(split_parts) > 1 else ""
                        else:
                            assisted_response = assisted_part.strip()
                else:
                    assisted_response = response_text
                
                # Send to member
                await websocket.send(json.dumps({
                    "type": "sanctuary_assisted_response_generated",
                    "sanctuary_id": sanctuary_id,
                    "assisted_response": assisted_response,
                    "explanation": explanation,
                    "charge_amount": 3.00,
                    "total_charges": float((sanctuary_engine.get_session(sanctuary_id) or {}).get("billing", {}).get("total_charges", 0.0)),
                    "message": "Here's a suggested response. You can edit it before sending, or use it as-is."
                }))


            
            # ENTRY QUESTIONS
            
            
            
            
            
            # COMPLETE SESSION
            
            elif t == "sanctuary_complete":
                """
                COMPLETE SESSION WITH SUMMARY
                
                Uses entry_responses + messages + coaching to generate:
                1. AI summary with personalized insights
                2. Coach history with auto-flagging
                3. Sends summary to each member
                
                Only the CREATOR or HEAD OF HOUSEHOLD can complete the session.
                """
                sanctuary_id = d.get('sanctuary_id')
                print(f">>> [SANCTUARY] Starting session completion for {sanctuary_id}")

                try:
                    analytics_engine.record_event("sanctuary_complete_requested", current_profile.get("hardware_id"), {
                        "sanctuary_id": sanctuary_id,
                        "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                    })
                except Exception:
                    pass
                
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                if not sanctuary_data:
                    await websocket.send(json.dumps({"type": "error", "message": "Sanctuary not found"}))
                    continue
                
                # Check if current user is allowed to complete
                current_member_id = current_profile.get('hardware_id')
                creator_id = sanctuary_data.get("created_by")
                head_id = sanctuary_data.get("head_of_household_id")
                
                can_complete = current_member_id in [creator_id, head_id]
                if not can_complete:
                    creator_name = sanctuary_data.get("creator_name", "the creator")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": f"Only {creator_name} or the head of household can complete the sanctuary session."
                    }))
                    print(f">>> [SANCTUARY] User {current_member_id} tried to complete but is not creator ({creator_id}) or head ({head_id})")
                    continue
                
                members = sanctuary_data.get("members", [])
                
                # Notify all: generating summary
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_generating_summary",
                        "sanctuary_id": sanctuary_id,
                        "message": "Little Nate is preparing your session summary... 💙"
                }
                )
                
              # ============================================
                # GATHER ALL DATA FOR AI SUMMARY
                # ============================================
                
                # Entry questions context (WHY they came, GOALS)
                entry_responses = sanctuary_data.get("entry_responses", {})
                entry_context = ""
                for mid, resp in entry_responses.items():
                    name = resp.get("member_name", mid)
                    entry_context += f"""
{name}:
  - Why entering: {resp.get('why_entering', 'Not provided')}
  - What's happening: {resp.get('whats_happening', 'Not provided')}
  - Goals: {resp.get('goals', 'Not provided')}
  - Feeling at start: {resp.get('feeling_scale', '?')}/10
"""
                
                # Conversation messages
                messages = sanctuary_data.get("messages", [])
                conv_text = "\n".join([
                    f"{m.get('sender_name', '?')}: {m.get('content', '')}"
                    for m in messages[-100:]
                ])
                
                # Coaching sessions
                coaching_sessions = sanctuary_data.get("coaching_sessions", {})
                coaching_summary = f"{len(coaching_sessions)} private coaching session(s)"
                
                # Duration
                created_at = sanctuary_data.get("created_at", datetime.datetime.now().isoformat())
                try:
                    start = datetime.datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    duration_mins = int((datetime.datetime.now(datetime.timezone.utc) - start).total_seconds() / 60)
                except:
                    duration_mins = 0
                
                member_names = [m.get("name", "Member") for m in members]
                
                # ============================================
                # GENERATE AI SUMMARY
                # ============================================
                
                summary_prompt = f"""You are Little Nate, a compassionate therapeutic AI facilitator for the Family Sanctuary.

Analyze this family session and provide insights that will help each member grow.

FAMILY MEMBERS: {', '.join(member_names)}

ENTRY CONTEXT (what each member shared before starting):
{entry_context if entry_context.strip() else 'No entry responses collected'}

CONVERSATION ({len(messages)} messages over {duration_mins} minutes):
{conv_text if conv_text.strip() else 'No messages recorded'}

COACHING: {coaching_summary}

Generate a therapeutic summary as JSON:
{{
    "key_conflicts": [
        "Brief description of main conflict/tension 1",
        "Brief description of main conflict/tension 2"
    ],
    "points_of_agreement": [
        "Area where family found common ground"
    ],
    "corrective_experiences": [
        "A moment of healing, understanding, or emotional connection"
    ],
    "individual_insights": {{
        "{member_names[0] if member_names else 'Member1'}": {{
            "patterns_observed": "Communication or behavioral patterns you noticed",
            "growth_areas": "Areas for personal development",
            "strengths_shown": "Positive contributions they made",
            "suggested_focus": "What they should focus on moving forward"
        }},
        "{member_names[1] if len(member_names) > 1 else 'Member2'}": {{
            "patterns_observed": "...",
            "growth_areas": "...",
            "strengths_shown": "...",
            "suggested_focus": "..."
        }}
    }},
    "overall_progress": 6,
    "recommended_next_steps": [
        "Specific actionable suggestion 1",
        "Specific actionable suggestion 2",
        "Specific actionable suggestion 3"
    ],
    "coach_notes": "Summary notes for a human coach if they review this session"
}}

IMPORTANT: 
- Include individual_insights for EACH family member by name
- Be warm, encouraging, and growth-focused
- Reference their entry goals in suggested_focus
- Progress score: 1-10 based on how well they met their stated goals"""

                try:
                    summary_response = await call_azure_openai(
                        summary_prompt,
                        system_message="You are a compassionate therapeutic AI. Respond ONLY with valid JSON, no other text.",
                        max_tokens=2500
                    )
                    
                    # Extract JSON from response
                    json_match = re.search(r'\{[\s\S]*\}', summary_response)
                    if json_match:
                        summary_data = json.loads(json_match.group())
                    else:
                        raise ValueError("No valid JSON in AI response")
                    
                    print(f">>> [SANCTUARY] AI summary generated successfully")
                    
                except Exception as e:
                    print(f">>> [SANCTUARY] Summary generation error: {e}")
                    summary_data = {
                        "key_conflicts": ["Please review session manually"],
                        "points_of_agreement": ["Unable to analyze automatically"],
                        "corrective_experiences": [],
                        "individual_insights": {name: {
                            "patterns_observed": "Review needed",
                            "growth_areas": "Discuss with coach",
                            "strengths_shown": "Participated in session",
                            "suggested_focus": "Schedule follow-up"
                        } for name in member_names},
                        "overall_progress": 5,
                        "recommended_next_steps": ["Schedule a follow-up family discussion", "Consider live coaching session"],
                        "coach_notes": "AI summary unavailable. Manual review recommended."
                    }
                
                # ============================================
                # STORE FOR COACH HISTORY
                # ============================================
                
                sanctuary_data["session_summary"] = {
                    "generated_at": datetime.datetime.now().isoformat(),
                    "summary": summary_data,
                    "duration_minutes": duration_mins,
                    "total_messages": len(messages),
                    "coaching_sessions": len(coaching_sessions)
                }
                
                sanctuary_data["completed_at"] = datetime.datetime.now().isoformat()
                sanctuary_data["status"] = "COMPLETED"
                
                # Auto-flag for coach review
                needs_review = False
                review_reasons = []
                
                if duration_mins >= 10080:  # 7+ days
                    needs_review = True
                    review_reasons.append(f"Long session: {duration_mins // 1440} days")
                
                if summary_data.get("overall_progress", 10) <= 4:
                    needs_review = True
                    review_reasons.append(f"Low progress: {summary_data.get('overall_progress')}/10")
                
                # Check for concerning content
                danger_words = ["hurt myself", "suicide", "kill", "abuse", "hit me", "scared", "unsafe"]
                for msg in messages:
                    content_lower = msg.get("content", "").lower()
                    for word in danger_words:
                        if word in content_lower:
                            needs_review = True
                            review_reasons.append(f"Concerning content detected")
                            break
                    if needs_review:
                        break
                
                sanctuary_data["needs_coach_review"] = needs_review
                sanctuary_data["review_reasons"] = review_reasons
                
                # Save to history
                import os as os2
                history_dir = os2.path.join(DATA_DIR, "sanctuary_history")
                os2.makedirs(history_dir, exist_ok=True)
                
                history_path = os2.path.join(history_dir, f"{sanctuary_id}.json")
                with open(history_path, "w") as hf:
                    json.dump(sanctuary_data, hf, indent=2, default=str)
                
                print(f">>> [SANCTUARY] Saved to history: {history_path}")
                print(f">>> [SANCTUARY] Needs coach review: {needs_review} {review_reasons}")
                
                # ============================================
                # SEND PERSONALIZED SUMMARY TO EACH MEMBER
                # ============================================
                
                for member in members:
                    m_id = member.get("user_id")
                    m_name = member.get("name", "Member")
                    
                    # Get their personalized insights
                    personal_insights = summary_data.get("individual_insights", {}).get(m_name, {})
                    
                    ws = sanctuary_engine.get_member_websocket(sanctuary_id, m_id)
                    if ws:
                        try:
                            await ws.send(json.dumps({
                                "type": "sanctuary_summary",
                                "sanctuary_id": sanctuary_id,
                                "summary": {
                                    "key_conflicts": summary_data.get("key_conflicts", []),
                                    "points_of_agreement": summary_data.get("points_of_agreement", []),
                                    "corrective_experiences": summary_data.get("corrective_experiences", []),
                                    "your_insights": personal_insights,
                                    "overall_progress": summary_data.get("overall_progress", 5),
                                    "next_steps": summary_data.get("recommended_next_steps", [])
                                },
                                "session_stats": {
                                    "duration_minutes": duration_mins,
                                    "total_messages": len(messages),
                                    "coaching_sessions": len(coaching_sessions),
                                    "total_charges": float(sanctuary_data.get("billing", {}).get("total_charges", 0.0)),
                                },
                                "message": f"Here's your session summary, {m_name}. Take time to reflect. 💙"
                            }))
                            print(f">>> [SANCTUARY] Sent summary to {m_name}")
                        except Exception as e:
                            print(f">>> [SANCTUARY] Failed to send summary to {m_name}: {e}")

# ============================================
                # UPDATE EACH MEMBER'S STORY.JSON
                # ============================================
                
                for member in members:
                    m_id = member.get("user_id")
                    m_name = member.get("name", "Member")
                    try:
                        await update_client_story(
                            client_id=m_id,
                            member_name=m_name,
                            summary_data=summary_data,
                            messages=messages,
                            coaching_sessions=coaching_sessions,
                            eft_tracker=sanctuary_data.get("eft_tracker") if isinstance(sanctuary_data, dict) else None,
                            reconsolidation_tracker=sanctuary_data.get("reconsolidation_tracker") if isinstance(sanctuary_data, dict) else None,
                        )
                    except Exception as e:
                        print(f">>> [STORY] Failed to update story for {m_name}: {e}")
                
                # ============================================
                # CLOSE SANCTUARY
                # ============================================
                
                # Reve from active
                del sanctuary_engine.data["active_sanctuaries"][sanctuary_id]
                sanctuary_engine._save()
                
                # Clear websocket registry
                # Websockets managed by sanctuary_engine
                
                print(f">>> [SANCTUARY] ✓ Session {sanctuary_id} completed successfully")

            elif t == "sanctuary_entry_responses":
                sanctuary_id = data.get("sanctuary_id")
                responses = data.get("responses", {})
                sanctuary_data = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})
                if sanctuary_data:
                    if "entry_responses" not in sanctuary_data:
                        sanctuary_data["entry_responses"] = {}
                    sanctuary_data["entry_responses"][member_id] = {
                        **responses,
                        "member_name": member_name,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = sanctuary_data
                    sanctuary_engine._save()
                    print(f">>> [SANCTUARY] Entry responses saved for {member_name}")
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_complete",
                        "sanctuary_id": sanctuary_id,
                        "message": "Thank you for sharing."
                    }))
                    members = [{"user_id": m.get("user_id"), "name": m.get("name")} for m in sanctuary_data.get("members", [])]
                    await websocket.send(json.dumps({
                        "type": "sanctuary_entry_ready",
                        "sanctuary_id": sanctuary_id,
                        "status": sanctuary_data.get("status", "ACTIVE"),
                        "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                        "members": members,
                        "messages": (sanctuary_data.get("messages", []) or [])[-50:]
                    }))

            elif t == "sanctuary_sync_state":
                """
                Sync sanctuary state when app resumes from background
                Returns current coaching status and recent messages
                """
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                if not sanctuary_data:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Sanctuary not found"
                    }))
                    continue

                # If group coaching round is ACTIVE, ensure this member has their private suggestion delivered.
                try:
                    round_obj = sanctuary_data.get("group_coaching_round") or {}
                    if round_obj.get("status") == "ACTIVE":
                        mid = member_id
                        round_obj.setdefault("members_expected", [])
                        if mid not in round_obj["members_expected"]:
                            round_obj["members_expected"].append(mid)
                        round_obj.setdefault("responses", {}).setdefault(mid, {"state": "PENDING"})
                        suggestion = (round_obj.get("suggestions") or {}).get(mid)
                        delivered = (round_obj.get("delivered_to") or {}).get(mid, False)
                        if (not suggestion) or (not delivered):
                            # Build minimal profiles for AI generation
                            def _get_profile_by_hardware_id(hid: str) -> dict:
                                reg = load_registry()
                                for _, v in (reg or {}).items():
                                    p = v.get("profile", {})
                                    if p.get("hardware_id") == hid:
                                        return dict(p)
                                return {"hardware_id": hid, "name": hid}

                            members_now = sanctuary_engine.get_member_list(sanctuary_id)
                            member_profiles = []
                            for m in members_now:
                                hid = m.get("user_id")
                                if not hid:
                                    continue
                                p = _get_profile_by_hardware_id(hid)
                                p["sanctuary_role"] = m.get("role", "MEMBER")
                                p["metrics"] = cortex.metrics.load_metrics(p)
                                p["memory"] = cortex.mem.recall(p, limit=5) or ""
                                member_profiles.append(p)

                            me = next((p for p in member_profiles if p.get("hardware_id") == mid), _get_profile_by_hardware_id(mid))
                            others = [p for p in member_profiles if p.get("hardware_id") != mid]
                            recent_msgs = (sanctuary_data.get("messages") or [])[-15:]
                            sug = await cortex.generate_group_coaching_response(
                                target_member=me,
                                other_members=others,
                                recent_messages=recent_msgs,
                                sanctuary_data=sanctuary_data,
                            )
                            total_charges = float((sanctuary_engine.get_session(sanctuary_id) or {}).get("billing", {}).get("total_charges", 0.0))
                            payload = {
                                "suggested_text": sug.get("suggested_response", ""),
                                "rationale": sug.get("rationale", ""),
                                "target_audience": sug.get("target_audience", "the family"),
                                "emotional_tone": sug.get("emotional_tone", "supportive"),
                                "total_charges": total_charges,
                            }
                            round_obj.setdefault("suggestions", {})[mid] = payload
                            round_obj.setdefault("delivered_to", {})[mid] = True
                            sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                            sanctuary_engine._save()
                            await websocket.send(json.dumps({
                                "type": "sanctuary_suggested_response",
                                "sanctuary_id": sanctuary_id,
                                **payload,
                            }))
                except Exception as e:
                    print(f">>> [GROUP COACHING] state_sync delivery error: {e}")
                
                # Check if anyone is in active coaching
                coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                active_coaching = []
                for cs in coaching_sessions.values():
                    if cs.get('status') == 'ACTIVE':
                        active_coaching.append({
                            "member_id": cs.get('member_id'),
                            "member_name": cs.get('member_name', 'A family member')
                        })
                
                # Check if THIS member is in coaching
                my_coaching = None
                for cs in coaching_sessions.values():
                    if cs.get('member_id') == member_id and cs.get('status') == 'ACTIVE':
                        my_coaching = cs
                        break
                
                is_paused = len(active_coaching) > 0 and not my_coaching
                
                # Ensure base fee is actually recorded (self-heals older sanctuaries or earlier failures).
                try:
                    s_now = sanctuary_engine.get_session(sanctuary_id) or {}
                    billing_now = (s_now.get("billing") or {}) if isinstance(s_now, dict) else {}
                    if not bool(billing_now.get("base_fee_charged", False)):
                        hoh_id = (s_now.get("head_of_household_id") if isinstance(s_now, dict) else None)
                        if hoh_id:
                            await sanctuary_engine.charge_base_fee(sanctuary_id=sanctuary_id, head_of_household_id=hoh_id)
                            sanctuary_data = sanctuary_engine.get_session(sanctuary_id) or sanctuary_data
                except Exception as e:
                    print(f">>> [SANCTUARY] Base fee self-heal failed: {e}")

                # Keep cooldown display consistent with enforcement
                try:
                    import os as _os
                    GROUP_COACHING_COOLDOWN_SECONDS = int(_os.getenv("SANCTUARY_GROUP_COACHING_COOLDOWN_SECONDS", "300") or 300)
                except Exception:
                    GROUP_COACHING_COOLDOWN_SECONDS = 300

                await websocket.send(json.dumps({
                    "type": "sanctuary_state_sync",
                    "sanctuary_id": sanctuary_id,
                    "status": sanctuary_data.get('status', 'ACTIVE'),
                    "is_paused": is_paused,
                    "active_coaching": active_coaching,
                    "my_coaching_active": my_coaching is not None,
                    "members": sanctuary_engine.get_member_list(sanctuary_id),
                    "total_charges": sanctuary_engine.get_total_charges(sanctuary_id),
                    # Itemized billing ledger (best-effort)
                    "billing_charges": ((sanctuary_data.get("billing", {}) or {}).get("charges", []) or [])[-50:],
                    # Provide both keys for backward compatibility across UIs.
                    "recent_messages": (sanctuary_data.get("messages", []) or [])[-20:],
                    "messages": (sanctuary_data.get("messages", []) or [])[-50:],
                    "group_coaching": {
                        "pending_request": sanctuary_data.get("pending_group_coaching_request"),
                        "cooldown_ends_at": int(float(sanctuary_data.get("last_group_coaching_completed", 0) or 0) + GROUP_COACHING_COOLDOWN_SECONDS) if sanctuary_data.get("last_group_coaching_completed") else None,
                        "round": sanctuary_data.get("group_coaching_round"),
                    },
                }))
                
                print(f">>> [SANCTUARY] State sync for {current_profile.get('name')}: paused={is_paused}, coaching={len(active_coaching)}")

            elif t == "sanctuary_exit":
                        """
                        Member wants to exit sanctuary
                        """
                        sanctuary_id = d.get('sanctuary_id')

                        try:
                            analytics_engine.record_event("sanctuary_exit_initiated", current_profile.get("hardware_id"), {
                                "sanctuary_id": sanctuary_id,
                                "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                            })
                        except Exception:
                            pass
                        
                        # Little Nate checks in first
                        checkin_message = f"""Hi {current_profile['name']},

                    I notice you want to leave the sanctuary. That's okay. This might be overwhelming.

                    Before you go, can you help me understand?
                    • Are you feeling unsafe?
                    • Is this too much to handle right now?
                    • Do you need a break but want to come back later?

                    Your feelings matter. 💙"""
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_exit_checkin",
                            "message": checkin_message
                        }))

            elif t == "sanctuary_exit_confirm":
                        """
                        Member confirms exit after check-in
                        """
                        sanctuary_id = d.get('sanctuary_id')
                        reason = d.get('reason', '')
                        inform_family = d.get('inform_family', True)

                        try:
                            analytics_engine.record_event("sanctuary_exit_confirmed", current_profile.get("hardware_id"), {
                                "sanctuary_id": sanctuary_id,
                                "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                                "reason": (reason or "")[:240],
                                "inform_family": bool(inform_family),
                            })
                        except Exception:
                            pass
                        
                        # Mark member as exited
                        await sanctuary_engine.member_exit(
                            sanctuary_id=sanctuary_id,
                            member_id=current_profile['hardware_id'],
                            reason=reason
                        )
                        
                        # Notify family if requested
                        if inform_family:
                            exit_message = f"{current_profile['name']} is taking a break from the sanctuary. They can rejoin anytime they're ready. 💙"
                            
                            await sanctuary_engine.broadcast_to_sanctuary(
                                sanctuary_id=sanctuary_id,
                                message_data={
                                    "type": "sanctuary_member_exited",
                                    "member_id": current_profile['hardware_id'],
                                    "message": exit_message
                                }
                            )
                        
                        await websocket.send(json.dumps({
                            "type": "sanctuary_exited",
                            "can_rejoin": True
                        }))

            elif t == "sanctuary_extend":
                        """
                        Extend sanctuary for another 24-hour cycle
                        24-hour check-in from Little Nate
                        """
                        sanctuary_id = d.get('sanctuary_id')
                        member_wants_continue = d.get('continue', False)
                        member_id = uid

                        # Record member's vote in sanctuary state
                        sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                        if sanctuary_data:
                            if "extension_votes" not in sanctuary_data:
                                sanctuary_data["extension_votes"] = {}
                            sanctuary_data["extension_votes"][member_id] = member_wants_continue

                            # Check if all active members have voted
                            active_members = [
                                m["user_id"] for m in sanctuary_data.get("members", [])
                                if m.get("status") not in ("EXITED",)
                            ]
                            votes = sanctuary_data["extension_votes"]
                            all_voted = all(mid in votes for mid in active_members)

                            if all_voted and active_members:
                                yes_count = sum(1 for v in votes.values() if v)
                                majority = yes_count > len(active_members) / 2

                                if majority:
                                    # Extend the session — reset timer
                                    sanctuary_data["extension_votes"] = {}
                                    sanctuary_data.setdefault("extensions", 0)
                                    sanctuary_data["extensions"] += 1
                                    await sanctuary_engine.broadcast_to_sanctuary(
                                        sanctuary_id=sanctuary_id,
                                        message_data={
                                            "type": "sanctuary_extended",
                                            "message": "The family has voted to continue. Sanctuary extended for another 24 hours.",
                                            "extensions": sanctuary_data["extensions"],
                                            "votes": {"yes": yes_count, "no": len(active_members) - yes_count},
                                        }
                                    )
                                else:
                                    # Majority voted no — complete the session
                                    await sanctuary_engine.broadcast_to_sanctuary(
                                        sanctuary_id=sanctuary_id,
                                        message_data={
                                            "type": "sanctuary_extension_declined",
                                            "message": "The family has decided to wrap up. Thank you for this time together.",
                                            "votes": {"yes": yes_count, "no": len(active_members) - yes_count},
                                        }
                                    )
                                    try:
                                        await sanctuary_engine.complete_session(sanctuary_id)
                                    except Exception as comp_err:
                                        print(f">>> [SANCTUARY] Extension-decline completion error: {comp_err}")
                            else:
                                # Still waiting for other members
                                voted_count = len([mid for mid in active_members if mid in votes])
                                await websocket.send(json.dumps({
                                    "type": "sanctuary_extend_recorded",
                                    "message": f"Your response has been recorded. Waiting for other members ({voted_count}/{len(active_members)})...",
                                    "voted": voted_count,
                                    "total": len(active_members),
                                }))
                        else:
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "Sanctuary session not found."
                            }))

            elif t == "sanctuary_coaching_decline":
                """
                Member declines coaching offer - show them the pause screen IF someone else is in coaching
                """
                sanctuary_id = d.get('sanctuary_id')
                member_id = current_profile['hardware_id']
                
                # Find who IS in coaching to show in the pause message
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                coaching_sessions = sanctuary_data.get('coaching_sessions', {})
                in_coaching = []
                for cs in coaching_sessions.values():
                    if cs.get('status') == 'ACTIVE':
                        in_coaching.append(cs.get('member_name', 'A family member'))
                
                if in_coaching:
                    # Someone is actually in coaching - show pause screen
                    coaching_member = in_coaching[0]
                    await websocket.send(json.dumps({
                        "type": "sanctuary_member_coaching",
                        "member_name": coaching_member,
                        "message": f"{coaching_member} is receiving private support from Little Nate. The sanctuary is paused."
                    }))
                    print(f">>> [SANCTUARY] {current_profile.get('name')} declined coaching, showing pause screen")
                else:
                    # No one is in coaching - send resume so they stay in chat
                    await websocket.send(json.dumps({
                        "type": "sanctuary_resumed",
                        "message": "The sanctuary conversation can continue. 💙"
                    }))
                    print(f">>> [SANCTUARY] {current_profile.get('name')} declined coaching, no one in coaching so resuming")

            elif t == "sanctuary_post_assisted_response":
                """
                Member wants to post their assisted response to the group chat
                """
                sanctuary_id = d.get('sanctuary_id')
                assisted_text = d.get('assisted_response', '')
                member_id = current_profile['hardware_id']
                member_name = current_profile.get('name', 'Friend')
                
                if not assisted_text:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "No assisted response to post"
                    }))
                    continue
                
                # Store the assisted message in sanctuary messages
                message_id = await sanctuary_engine.add_message(
                    sanctuary_id=sanctuary_id,
                    sender_id=member_id,
                    content=assisted_text,
                    message_type="ASSISTED",
                )

                # Fetch the stored message object (last appended) for consistent UI shape
                stored = sanctuary_engine.get_session(sanctuary_id) or {}
                stored_messages = stored.get("messages", [])
                message_obj = stored_messages[-1] if stored_messages else {
                    "message_id": message_id,
                    "message_type": "ASSISTED",
                    "sender_id": member_id,
                    "sender_name": member_name,
                    "content": assisted_text,
                    "timestamp": str(datetime.datetime.now()),
                }
                
                # Broadcast to all members
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_message",
                        "message": message_obj
                    }
                )
                
                print(f">>> [SANCTUARY] {member_name} posted assisted response to group chat")
                try:
                    analytics_engine.record_event("sanctuary_assisted_response_posted", member_id, {
                        "sanctuary_id": sanctuary_id,
                        "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                        "message_id": message_obj.get("message_id"),
                        "chars": len((assisted_text or "")),
                    })
                except Exception:
                    pass

            elif t == "sanctuary_group_coaching_approve":
                """
                HEAD approves group coaching - record $20 (test mode supported) and generate personalized suggestions.
                """
                sanctuary_id = d.get("sanctuary_id")
                if not sanctuary_id:
                    continue

                sanctuary_data = sanctuary_engine.get_session(sanctuary_id) or {}
                head_id = sanctuary_data.get("head_of_household_id")
                if current_profile.get("hardware_id") != head_id:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Only the family HEAD can approve group coaching."
                    }))
                    continue

                try:
                    analytics_engine.record_event("sanctuary_group_coaching_approved", current_profile.get("hardware_id"), {
                        "sanctuary_id": sanctuary_id,
                        "family_id": sanctuary_data.get("family_id"),
                        "cost": 20.00,
                    })
                except Exception:
                    pass

                import time as _time
                now_ts = _time.time()
                active = sanctuary_engine.data["active_sanctuaries"].get(sanctuary_id, {})

                # If a round is already active, don't start another
                existing_round = active.get("group_coaching_round") or {}
                if existing_round.get("status") == "ACTIVE":
                    await websocket.send(json.dumps({
                        "type": "sanctuary_group_coaching_status",
                        "sanctuary_id": sanctuary_id,
                        "state": "ACTIVE",
                    }))
                    continue

                # Move pending request into a real "round" (or synthesize requester if missing)
                pending_req = active.pop("pending_group_coaching_request", None) or {}
                round_id = f"GC_{int(now_ts)}_{secrets.token_hex(3).upper()}"
                requested_by_name = pending_req.get("requested_by_name") or pending_req.get("requested_by") or "A family member"
                requested_text = pending_req.get("requested_text") or ""

                members_now = sanctuary_engine.get_member_list(sanctuary_id)
                expected_ids = [m.get("user_id") for m in members_now if m.get("user_id")]

                # Include invited members even if not yet joined
                invited = (sanctuary_data.get("invited_member_ids") or []) if isinstance(sanctuary_data, dict) else []
                for mid in invited:
                    if mid and mid not in expected_ids:
                        expected_ids.append(mid)

                # Fallback: include *all* family members (by family_id) from registry.
                # This protects the "late joiner" edge case when invited_member_ids is incomplete.
                family_id = (sanctuary_data.get("family_id") if isinstance(sanctuary_data, dict) else None)
                try:
                    if family_id:
                        reg = load_registry() or {}
                        for _, v in reg.items():
                            p = (v or {}).get("profile", {}) or {}
                            if p.get("family_id") == family_id and p.get("hardware_id") and p.get("role") == "CLIENT":
                                fid = p["hardware_id"]
                                if fid not in expected_ids:
                                    expected_ids.append(fid)
                except Exception as e:
                    print(f">>> [GROUP COACHING] family roster fallback error: {e}")

                # Always include HEAD as expected (safety)
                if head_id and head_id not in expected_ids:
                    expected_ids.append(head_id)

                active["group_coaching_round"] = {
                    "round_id": round_id,
                    "status": "ACTIVE",
                    "approved_at": now_ts,
                    "requested_by_name": requested_by_name,
                    "requested_text": requested_text,
                    "members_expected": expected_ids,
                    "suggestions": {},          # member_id -> suggestion payload
                    "delivered_to": {},         # member_id -> bool
                    "responses": {mid: {"state": "PENDING"} for mid in expected_ids},
                }
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id] = active
                sanctuary_engine._save()

                # Charge (or record) $20
                charge_ok, charge_msg = await sanctuary_engine.charge_group_coaching(
                    sanctuary_id=sanctuary_id,
                    amount=20.00,
                    description="Group Coaching Session"
                )
                if not charge_ok:
                    await websocket.send(json.dumps({"type": "error", "message": charge_msg}))
                    continue

                total_charges = float((sanctuary_engine.get_session(sanctuary_id) or {}).get("billing", {}).get("total_charges", 0.0))

                # Notify all (system message)
                system_msg = {
                    "message_id": f"SYS_{int(datetime.datetime.now().timestamp())}",
                    "message_type": "SYSTEM",
                    "sender_id": "SYSTEM",
                    "sender_name": "System",
                    "content": "💙 Group Coaching activated. Little Nate is preparing private, personalized words for each family member...",
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["messages"].append(system_msg)
                sanctuary_engine._save()
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={"type": "sanctuary_message", "message": system_msg}
                )

                # Helper: get a user profile by hardware_id from registry
                def _get_profile_by_hardware_id(hid: str) -> dict:
                    reg = load_registry()
                    for _, v in (reg or {}).items():
                        p = v.get("profile", {})
                        if p.get("hardware_id") == hid:
                            return dict(p)
                    return {"hardware_id": hid, "name": hid}

                members = sanctuary_data.get("members", [])
                member_profiles = []
                for m in members:
                    hid = m.get("user_id") or m.get("id")
                    if not hid:
                        continue
                    profile = _get_profile_by_hardware_id(hid)
                    profile["sanctuary_role"] = (m.get("role") or "MEMBER")
                    profile["metrics"] = cortex.metrics.load_metrics(profile)
                    profile["memory"] = cortex.mem.recall(profile, limit=5) or ""
                    member_profiles.append(profile)

                recent_messages = sanctuary_data.get("messages", [])[-15:]

                # Generate & send each member a private suggestion
                round_obj = (sanctuary_engine.get_session(sanctuary_id) or {}).get("group_coaching_round") or {}
                for profile in member_profiles:
                    hid = profile.get("hardware_id")
                    user_ws = sanctuary_engine.get_member_websocket(sanctuary_id, hid)
                    others = [p for p in member_profiles if p.get("hardware_id") != hid]
                    suggestion = await cortex.generate_group_coaching_response(
                        target_member=profile,
                        other_members=others,
                        recent_messages=recent_messages,
                        sanctuary_data=sanctuary_data
                    )

                    # Persist suggestion for delivery to late joiners/reconnects
                    round_obj = (sanctuary_engine.get_session(sanctuary_id) or {}).get("group_coaching_round") or {}
                    round_obj.setdefault("suggestions", {})[hid] = {
                        "suggested_text": suggestion.get("suggested_response", ""),
                        "rationale": suggestion.get("rationale", ""),
                        "target_audience": suggestion.get("target_audience", "the family"),
                        "emotional_tone": suggestion.get("emotional_tone", "supportive"),
                        "total_charges": total_charges,
                    }
                    round_obj.setdefault("delivered_to", {})[hid] = bool(user_ws)
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                    sanctuary_engine._save()

                    if user_ws:
                        await user_ws.send(json.dumps({
                            "type": "sanctuary_suggested_response",
                            "sanctuary_id": sanctuary_id,
                            **round_obj["suggestions"][hid],
                        }))

                # Optional: broadcast charge update for any UIs that want it
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_charge_update",
                        "sanctuary_id": sanctuary_id,
                        "total_charges": total_charges,
                        "latest_charge": {"amount": 20.00, "description": "Group Coaching Session"},
                    }
                )

                # Broadcast ACTIVE status so UIs can lock chat until everyone responds/declines
                waiting_on = []
                try:
                    round_obj = (sanctuary_engine.get_session(sanctuary_id) or {}).get("group_coaching_round") or {}
                    responses = round_obj.get("responses", {}) or {}
                    pending_ids = [mid for mid, r in responses.items() if (r or {}).get("state") == "PENDING"]
                    member_name_map = {m.get("user_id"): m.get("name") for m in sanctuary_engine.get_member_list(sanctuary_id)}
                    waiting_on = [member_name_map.get(mid, mid) for mid in pending_ids]
                except Exception:
                    waiting_on = []

                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_group_coaching_status",
                        "sanctuary_id": sanctuary_id,
                        "state": "ACTIVE",
                        "waiting_on": waiting_on,
                    }
                )

                # NOTE: cooldown starts when the round completes (after all members send/decline)

                print(f">>> [SANCTUARY] Group coaching approved; total_charges={total_charges}")

            elif t == "sanctuary_group_coaching_decline":
                """
                HEAD declines group coaching
                """
                sanctuary_id = d.get("sanctuary_id")
                sanctuary_data = sanctuary_engine.get_session(sanctuary_id) or {}
                head_id = sanctuary_data.get("head_of_household_id")
                if current_profile.get("hardware_id") != head_id:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Only the family HEAD can decline group coaching."
                    }))
                    continue

                try:
                    analytics_engine.record_event("sanctuary_group_coaching_declined", current_profile.get("hardware_id"), {
                        "sanctuary_id": sanctuary_id,
                        "family_id": sanctuary_data.get("family_id"),
                    })
                except Exception:
                    pass

                # Clear pending request so another member can ask again
                sanctuary_engine.data["active_sanctuaries"][sanctuary_id].pop("pending_group_coaching_request", None)
                sanctuary_engine._save()
                # Broadcast status to clear UI indicator
                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_group_coaching_status",
                        "sanctuary_id": sanctuary_id,
                        "state": "IDLE",
                        "cooldown_ends_at": None,
                    }
                )

                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={
                        "type": "sanctuary_message",
                        "message": {
                            "message_id": f"SYS_{int(datetime.datetime.now().timestamp())}",
                            "message_type": "LITTLE_NATE",
                            "sender_id": "LITTLE_NATE",
                            "sender_name": "Little Nate",
                            "content": "I understand. Let’s continue naturally. You can ask for Group Coaching whenever you’re ready. 💙",
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                    }
                )

            elif t == "sanctuary_send_suggested_response":
                """
                Member sends their suggested response (as-is or edited).
                """
                sanctuary_id = d.get("sanctuary_id")
                response_text = (d.get("response_text") or "").strip()
                was_edited = bool(d.get("was_edited", False))

                if not sanctuary_id or not response_text:
                    continue

                member_id = current_profile["hardware_id"]
                member_name = current_profile.get("name", "Friend")
                msg_type = "COACHED" if not was_edited else "MEMBER_MESSAGE"

                message_id = await sanctuary_engine.add_message(
                    sanctuary_id=sanctuary_id,
                    sender_id=member_id,
                    content=response_text,
                    message_type=msg_type,
                )

                stored = sanctuary_engine.get_session(sanctuary_id) or {}
                stored_messages = stored.get("messages", [])
                message_obj = stored_messages[-1] if stored_messages else {
                    "message_id": message_id,
                    "message_type": msg_type,
                    "sender_id": member_id,
                    "sender_name": member_name,
                    "content": response_text,
                    "timestamp": datetime.datetime.now().isoformat(),
                }

                await sanctuary_engine.broadcast_to_sanctuary(
                    sanctuary_id=sanctuary_id,
                    message_data={"type": "sanctuary_message", "message": message_obj}
                )

                try:
                    analytics_engine.record_event("sanctuary_group_coaching_response_sent", member_id, {
                        "sanctuary_id": sanctuary_id,
                        "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                        "was_edited": bool(was_edited),
                        "message_type": msg_type,
                    })
                except Exception:
                    pass

                # Mark group coaching response state
                s = sanctuary_engine.get_session(sanctuary_id) or {}
                round_obj = s.get("group_coaching_round") or {}
                if round_obj.get("status") == "ACTIVE":
                    round_obj.setdefault("responses", {}).setdefault(member_id, {})["state"] = "SENT"
                    round_obj["responses"][member_id]["at"] = datetime.datetime.now().isoformat()
                    sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                    sanctuary_engine._save()

                    # Broadcast updated status + check completion
                    member_name_map = {m.get("user_id"): m.get("name") for m in sanctuary_engine.get_member_list(sanctuary_id)}
                    pending_ids = [mid for mid, r in (round_obj.get("responses") or {}).items() if (r or {}).get("state") == "PENDING"]
                    waiting_on = [member_name_map.get(mid, mid) for mid in pending_ids]

                    if not pending_ids:
                        import time as _time
                        now_ts = _time.time()
                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["last_group_coaching_completed"] = now_ts
                        round_obj["status"] = "COMPLETE"
                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                        sanctuary_engine._save()
                        try:
                            analytics_engine.record_event("sanctuary_group_coaching_round_completed", member_id, {
                                "sanctuary_id": sanctuary_id,
                                "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                                "round_id": round_obj.get("round_id"),
                                "completed_at": now_ts,
                                "completed_via": "SENT",
                                "responses": round_obj.get("responses", {}),
                            })
                        except Exception:
                            pass
                        try:
                            import os as _os
                            GROUP_COACHING_COOLDOWN_SECONDS = int(_os.getenv("SANCTUARY_GROUP_COACHING_COOLDOWN_SECONDS", "300") or 300)
                        except Exception:
                            GROUP_COACHING_COOLDOWN_SECONDS = 300
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_group_coaching_status",
                                "sanctuary_id": sanctuary_id,
                                "state": "COOLDOWN",
                                "cooldown_ends_at": int(now_ts + GROUP_COACHING_COOLDOWN_SECONDS),
                                "waiting_on": [],
                            }
                        )
                    else:
                        await sanctuary_engine.broadcast_to_sanctuary(
                            sanctuary_id=sanctuary_id,
                            message_data={
                                "type": "sanctuary_group_coaching_status",
                                "sanctuary_id": sanctuary_id,
                                "state": "ACTIVE",
                                "waiting_on": waiting_on,
                            }
                        )

            elif t == "sanctuary_decline_suggested_response":
                """
                Member declines to send their suggested response.
                """
                sanctuary_id = d.get("sanctuary_id")
                member_id = current_profile.get("hardware_id")
                await websocket.send(json.dumps({
                    "type": "sanctuary_suggestion_declined",
                    "message": "No problem. Take your time — there’s no pressure to respond."
                }))

                if sanctuary_id and member_id:
                    try:
                        analytics_engine.record_event("sanctuary_group_coaching_response_declined", member_id, {
                            "sanctuary_id": sanctuary_id,
                            "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                        })
                    except Exception:
                        pass
                    s = sanctuary_engine.get_session(sanctuary_id) or {}
                    round_obj = s.get("group_coaching_round") or {}
                    if round_obj.get("status") == "ACTIVE":
                        round_obj.setdefault("responses", {}).setdefault(member_id, {})["state"] = "DECLINED"
                        round_obj["responses"][member_id]["at"] = datetime.datetime.now().isoformat()
                        sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                        sanctuary_engine._save()

                        member_name_map = {m.get("user_id"): m.get("name") for m in sanctuary_engine.get_member_list(sanctuary_id)}
                        pending_ids = [mid for mid, r in (round_obj.get("responses") or {}).items() if (r or {}).get("state") == "PENDING"]
                        waiting_on = [member_name_map.get(mid, mid) for mid in pending_ids]

                        if not pending_ids:
                            import time as _time
                            now_ts = _time.time()
                            sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["last_group_coaching_completed"] = now_ts
                            round_obj["status"] = "COMPLETE"
                            sanctuary_engine.data["active_sanctuaries"][sanctuary_id]["group_coaching_round"] = round_obj
                            sanctuary_engine._save()
                            try:
                                analytics_engine.record_event("sanctuary_group_coaching_round_completed", member_id, {
                                    "sanctuary_id": sanctuary_id,
                                    "family_id": (sanctuary_engine.get_session(sanctuary_id) or {}).get("family_id"),
                                    "round_id": round_obj.get("round_id"),
                                    "completed_at": now_ts,
                                    "completed_via": "DECLINED",
                                    "responses": round_obj.get("responses", {}),
                                })
                            except Exception:
                                pass
                            try:
                                import os as _os
                                GROUP_COACHING_COOLDOWN_SECONDS = int(_os.getenv("SANCTUARY_GROUP_COACHING_COOLDOWN_SECONDS", "300") or 300)
                            except Exception:
                                GROUP_COACHING_COOLDOWN_SECONDS = 300
                            await sanctuary_engine.broadcast_to_sanctuary(
                                sanctuary_id=sanctuary_id,
                                message_data={
                                    "type": "sanctuary_group_coaching_status",
                                    "sanctuary_id": sanctuary_id,
                                    "state": "COOLDOWN",
                                    "cooldown_ends_at": int(now_ts + GROUP_COACHING_COOLDOWN_SECONDS),
                                    "waiting_on": [],
                                }
                            )
                        else:
                            await sanctuary_engine.broadcast_to_sanctuary(
                                sanctuary_id=sanctuary_id,
                                message_data={
                                    "type": "sanctuary_group_coaching_status",
                                    "sanctuary_id": sanctuary_id,
                                    "state": "ACTIVE",
                                    "waiting_on": waiting_on,
                                }
                            )

            elif t == "sanctuary_request_coach":
                        """
                        Request live coach escalation
                        """
                        sanctuary_id = d.get('sanctuary_id')

                        # Notify coaches via NotificationSystem + Email
                        try:
                            sanctuary_data = sanctuary_engine.get_session(sanctuary_id)
                            requester_name = current_profile.get('name', 'A member') if current_profile else 'A member'
                            family_size = len(sanctuary_data.get("members", [])) if sanctuary_data else 0

                            notification_system.create_notification(
                                user_id="ALL_COACHES",
                                notification_type="coach_escalation",
                                title="Family Sanctuary Coach Request",
                                message=f"{requester_name} requests live coach support ({family_size} members).",
                                priority="HIGH",
                                data={"sanctuary_id": sanctuary_id},
                            )

                            try:
                                from app.services.notifications_service import EmailService
                                email_svc = EmailService()
                                await email_svc.send_crisis_alert(
                                    to_email=None,
                                    client_name=requester_name,
                                    alert_type="SANCTUARY_COACH_REQUEST",
                                    details=f"Sanctuary {sanctuary_id}: coach support requested for {family_size} members.",
                                )
                            except Exception as email_err:
                                print(f">>> [SANCTUARY] Coach email error: {email_err}")
                        except Exception as notify_err:
                            print(f">>> [SANCTUARY] Coach notify error: {notify_err}")

                        await websocket.send(json.dumps({
                            "type": "coach_notified",
                            "message": "A coach will be notified within 24 hours."
                        }))

            # =================================================================
            # NATE NUDGE — Proactive Notification Handlers
            # =================================================================

            elif t == "get_pending_nudges":
                try:
                    from app.services.nate_nudge import NateNudgeService
                    nudge_svc = NateNudgeService(db_pool)
                    user_uuid = None
                    if current_profile:
                        try:
                            from uuid import UUID as _UUID
                            user_uuid = _UUID(current_profile.get("id", ""))
                        except Exception:
                            pass
                    if user_uuid:
                        nudges = await nudge_svc.get_pending_nudges(user_uuid)
                        # Mark them as sent once delivered over WebSocket
                        for n in nudges:
                            if n.get("status") == "pending":
                                try:
                                    await nudge_svc.mark_sent(_UUID(n["id"]))
                                    n["status"] = "sent"
                                except Exception:
                                    pass
                        # Push through notification system too
                        try:
                            for n in nudges:
                                await notification_system._push_to_websocket(uid, {
                                    "type": "nate_nudge",
                                    "nudge": n,
                                })
                        except Exception:
                            pass
                        await websocket.send(json.dumps({
                            "type": "pending_nudges",
                            "nudges": nudges,
                            "count": len(nudges),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "pending_nudges",
                            "nudges": [],
                            "count": 0,
                            "error": "no_user_context",
                        }))
                except Exception as nudge_err:
                    print(f">>> [SOCKET] get_pending_nudges error: {nudge_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "get_pending_nudges",
                        "message": str(nudge_err),
                    }))

            elif t == "nudge_mark_opened":
                try:
                    from app.services.nate_nudge import NateNudgeService
                    from uuid import UUID as _UUID
                    nudge_svc = NateNudgeService(db_pool)
                    nudge_id = _UUID(d.get("nudge_id", ""))
                    await nudge_svc.mark_opened(nudge_id)
                    await websocket.send(json.dumps({
                        "type": "nudge_updated",
                        "nudge_id": str(nudge_id),
                        "status": "opened",
                    }))
                except Exception as nudge_err:
                    print(f">>> [SOCKET] nudge_mark_opened error: {nudge_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "nudge_mark_opened",
                        "message": str(nudge_err),
                    }))

            elif t == "nudge_dismiss":
                try:
                    from app.services.nate_nudge import NateNudgeService
                    from uuid import UUID as _UUID
                    nudge_svc = NateNudgeService(db_pool)
                    nudge_id = _UUID(d.get("nudge_id", ""))
                    await nudge_svc.dismiss(nudge_id)
                    await websocket.send(json.dumps({
                        "type": "nudge_updated",
                        "nudge_id": str(nudge_id),
                        "status": "dismissed",
                    }))
                except Exception as nudge_err:
                    print(f">>> [SOCKET] nudge_dismiss error: {nudge_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "nudge_dismiss",
                        "message": str(nudge_err),
                    }))

            # =================================================================
            # AI MODES — TriCorder / Archivist / Guardian / Supervisor
            # =================================================================

            elif t == "ai_mode_activate":
                try:
                    from app.services.ai_modes import (
                        TriCorderMode, ArchivistMode, GuardianMode, SupervisorMode,
                    )
                    from uuid import UUID as _UUID
                    mode_name = d.get("mode", "").lower()
                    session_id = _UUID(d.get("session_id", ""))
                    mode_map = {
                        "tri_corder": TriCorderMode,
                        "archivist": ArchivistMode,
                        "guardian": GuardianMode,
                        "supervisor": SupervisorMode,
                    }
                    mode_cls = mode_map.get(mode_name)
                    if not mode_cls:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "handler": "ai_mode_activate",
                            "message": f"Unknown mode: {mode_name}",
                            "available": list(mode_map.keys()),
                        }))
                    else:
                        mode_instance = mode_cls(db_pool=db_pool)
                        result = await mode_instance.activate(
                            session_id=session_id,
                            user_id=uid if uid != "GUEST" else None,
                            **{k: v for k, v in d.items()
                               if k not in ("type", "mode", "session_id")},
                        )
                        # Store in connection state for subsequent process/output calls
                        if not hasattr(websocket, "_ai_modes"):
                            websocket._ai_modes = {}
                        websocket._ai_modes[str(session_id)] = mode_instance
                        await websocket.send(json.dumps({
                            "type": "ai_mode_activated",
                            "mode": mode_name,
                            "session_id": str(session_id),
                            "result": result,
                        }))
                except Exception as aim_err:
                    print(f">>> [SOCKET] ai_mode_activate error: {aim_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "ai_mode_activate",
                        "message": str(aim_err),
                    }))

            elif t == "ai_mode_process":
                try:
                    from uuid import UUID as _UUID
                    session_id = str(d.get("session_id", ""))
                    modes = getattr(websocket, "_ai_modes", {})
                    mode_instance = modes.get(session_id)
                    if not mode_instance:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "handler": "ai_mode_process",
                            "message": "No active mode for this session. Activate first.",
                        }))
                    else:
                        payload = d.get("data", {})
                        result = await mode_instance.process(payload)
                        await websocket.send(json.dumps({
                            "type": "ai_mode_processed",
                            "session_id": session_id,
                            "mode": mode_instance.MODE_NAME,
                            "result": result,
                        }))
                except Exception as aim_err:
                    print(f">>> [SOCKET] ai_mode_process error: {aim_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "ai_mode_process",
                        "message": str(aim_err),
                    }))

            elif t == "ai_mode_get_output":
                try:
                    session_id = str(d.get("session_id", ""))
                    modes = getattr(websocket, "_ai_modes", {})
                    mode_instance = modes.get(session_id)
                    if not mode_instance:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "handler": "ai_mode_get_output",
                            "message": "No active mode for this session.",
                        }))
                    else:
                        output = await mode_instance.generate_output()
                        await websocket.send(json.dumps({
                            "type": "ai_mode_output",
                            "session_id": session_id,
                            "mode": mode_instance.MODE_NAME,
                            "output": output,
                        }))
                except Exception as aim_err:
                    print(f">>> [SOCKET] ai_mode_get_output error: {aim_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "ai_mode_get_output",
                        "message": str(aim_err),
                    }))

            elif t == "ai_mode_deactivate":
                try:
                    session_id = str(d.get("session_id", ""))
                    modes = getattr(websocket, "_ai_modes", {})
                    mode_instance = modes.get(session_id)
                    if mode_instance:
                        result = mode_instance.deactivate()
                        del modes[session_id]
                        await websocket.send(json.dumps({
                            "type": "ai_mode_deactivated",
                            "session_id": session_id,
                            "result": result,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "ai_mode_deactivated",
                            "session_id": session_id,
                            "result": {"status": "no_active_mode"},
                        }))
                except Exception as aim_err:
                    print(f">>> [SOCKET] ai_mode_deactivate error: {aim_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "ai_mode_deactivate",
                        "message": str(aim_err),
                    }))

            # =================================================================
            # ADMIN: LIVE SESSIONS (from LIVE_SESSION_TRACKER)
            # =================================================================

            elif t == "admin_get_live_sessions":
                if current_profile and current_profile.get("role") == "ADMIN":
                    try:
                        live = []
                        for sid, sess in LIVE_SESSION_TRACKER.items():
                            live.append({
                                "session_id": sid,
                                "client_id": sess.get("client_id", ""),
                                "started_at": sess.get("started_at", ""),
                                "session_type": sess.get("session_type", "ai"),
                                "mood": sess.get("mood_at_start", ""),
                            })
                        await websocket.send(json.dumps({
                            "type": "live_sessions",
                            "sessions": live,
                            "count": len(live),
                        }))
                    except Exception as ls_err:
                        print(f">>> [SOCKET] admin_get_live_sessions error: {ls_err}")
                        await websocket.send(json.dumps({
                            "type": "error",
                            "handler": "admin_get_live_sessions",
                            "message": str(ls_err),
                        }))
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "admin_get_live_sessions",
                        "message": "Admin access required",
                    }))

            # =================================================================
            # SWARM RELAY — trigger swarm services on the FastAPI process
            # =================================================================

            elif t == "swarm_request":
                try:
                    action = d.get("action", "")
                    payload = d.get("payload", {})
                    if swarm_relay:
                        result = await swarm_relay.request(action, payload)
                        await websocket.send(json.dumps({
                            "type": "swarm_response",
                            "action": action,
                            "result": result,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "swarm_response",
                            "action": action,
                            "result": {"status": "unavailable", "message": "Swarm relay not connected"},
                        }))
                except Exception as sr_err:
                    print(f">>> [SOCKET] swarm_request error: {sr_err}")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "handler": "swarm_request",
                        "message": str(sr_err),
                    }))

            # =================================================================
            # ZEFCP Layer 1 — Mobile Fragment Transport (Phase 7)
            # =================================================================

            elif t == "zefcp_fragment":
                # Mobile device uploads a captured BLE fragment
                try:
                    fragment_data = d.get("fragment", {})
                    endpoint_id = d.get("endpoint_id", uid)
                    if swarm_relay:
                        result = await swarm_relay.request("zefcp_fragment_ingest", {
                            "fragment": fragment_data,
                            "endpoint_id": endpoint_id,
                            "source_uid": uid,
                        })
                        await websocket.send(json.dumps({
                            "type": "zefcp_fragment_ack",
                            "status": result.get("status", "received"),
                            "fragment_id": fragment_data.get("fragment_id"),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "zefcp_fragment_ack",
                            "status": "buffered",
                            "fragment_id": fragment_data.get("fragment_id"),
                        }))
                except Exception as zf_err:
                    print(f">>> [SOCKET] zefcp_fragment error: {zf_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "zefcp_fragment",
                        "message": str(zf_err),
                    }))

            elif t == "zefcp_assembly":
                # Mobile requests assembly status for a given observation
                try:
                    observation_id = d.get("observation_id", "")
                    endpoint_id = d.get("endpoint_id", uid)
                    if swarm_relay:
                        result = await swarm_relay.request("zefcp_assembly_status", {
                            "observation_id": observation_id,
                            "endpoint_id": endpoint_id,
                        })
                        await websocket.send(json.dumps({
                            "type": "zefcp_assembly_status",
                            "observation_id": observation_id,
                            **result,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "zefcp_assembly_status",
                            "observation_id": observation_id,
                            "status": "unavailable",
                        }))
                except Exception as za_err:
                    print(f">>> [SOCKET] zefcp_assembly error: {za_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "zefcp_assembly",
                        "message": str(za_err),
                    }))

            elif t == "zefcp_capacity":
                # Mobile queries available BLE transport capacity
                try:
                    endpoint_id = d.get("endpoint_id", uid)
                    if swarm_relay:
                        result = await swarm_relay.request("zefcp_capacity_query", {
                            "endpoint_id": endpoint_id,
                        })
                        await websocket.send(json.dumps({
                            "type": "zefcp_capacity_report",
                            **result,
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "zefcp_capacity_report",
                            "capacity": "unknown", "status": "relay_unavailable",
                        }))
                except Exception as zc_err:
                    print(f">>> [SOCKET] zefcp_capacity error: {zc_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "zefcp_capacity",
                        "message": str(zc_err),
                    }))

            elif t == "zefcp_embed_request":
                # Mobile requests fragments to embed in outbound BLE advertising
                try:
                    fibre_id = d.get("fibre_id", uid)
                    max_fragments = d.get("max_fragments", 10)
                    if swarm_relay:
                        result = await swarm_relay.request("zefcp_embed_queue", {
                            "fibre_id": fibre_id,
                            "max_fragments": max_fragments,
                        })
                        await websocket.send(json.dumps({
                            "type": "zefcp_embed_payload",
                            "fibre_id": fibre_id,
                            "fragments": result.get("fragments", []),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "zefcp_embed_payload",
                            "fibre_id": fibre_id,
                            "fragments": [],
                        }))
                except Exception as ze_err:
                    print(f">>> [SOCKET] zefcp_embed_request error: {ze_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "zefcp_embed_request",
                        "message": str(ze_err),
                    }))

            # =================================================================
            # Quakete Layer 8 — Mobile Solidarity Transport (Phase 7)
            # =================================================================

            elif t == "trail_emission":
                # Mobile Fibre emits a trail (heartbeat with coherence data)
                try:
                    emission_data = d.get("emission", {})
                    fibre_id = emission_data.get("fibre_id", uid)
                    if swarm_relay:
                        result = await swarm_relay.request("quakete_trail_emission", {
                            "emission": emission_data,
                            "source_uid": uid,
                        })
                        await websocket.send(json.dumps({
                            "type": "trail_emission_ack",
                            "fibre_id": fibre_id,
                            "status": result.get("status", "received"),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "trail_emission_ack",
                            "fibre_id": fibre_id,
                            "status": "buffered",
                        }))
                except Exception as te_err:
                    print(f">>> [SOCKET] trail_emission error: {te_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "trail_emission",
                        "message": str(te_err),
                    }))

            elif t == "quakete_mode_update":
                # Mobile updates its Quakete operational mode
                try:
                    new_mode = d.get("mode", "dormant")
                    fibre_id = d.get("fibre_id", uid)
                    if swarm_relay:
                        result = await swarm_relay.request("quakete_mode_update", {
                            "fibre_id": fibre_id,
                            "mode": new_mode,
                        })
                        await websocket.send(json.dumps({
                            "type": "quakete_mode_ack",
                            "fibre_id": fibre_id,
                            "mode": new_mode,
                            "status": result.get("status", "updated"),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "quakete_mode_ack",
                            "fibre_id": fibre_id,
                            "mode": new_mode,
                            "status": "buffered",
                        }))
                except Exception as qm_err:
                    print(f">>> [SOCKET] quakete_mode_update error: {qm_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "quakete_mode_update",
                        "message": str(qm_err),
                    }))

            elif t == "distress_beacon":
                # Mobile sends an emergency distress beacon (Quakete Ramp-Up trigger)
                try:
                    fibre_id = d.get("fibre_id", uid)
                    severity = d.get("severity", "critical")
                    reason = d.get("reason", "mobile_distress")
                    if swarm_relay:
                        result = await swarm_relay.request("quakete_distress_beacon", {
                            "fibre_id": fibre_id,
                            "severity": severity,
                            "reason": reason,
                            "source_uid": uid,
                        })
                        await websocket.send(json.dumps({
                            "type": "distress_beacon_ack",
                            "fibre_id": fibre_id,
                            "status": result.get("status", "escalated"),
                            "response_eta": result.get("response_eta"),
                        }))
                    else:
                        await websocket.send(json.dumps({
                            "type": "distress_beacon_ack",
                            "fibre_id": fibre_id,
                            "status": "relay_unavailable",
                        }))
                    print(f">>> [DISTRESS] Beacon from fibre={fibre_id} severity={severity}")
                except Exception as db_err:
                    print(f">>> [SOCKET] distress_beacon error: {db_err}")
                    await websocket.send(json.dumps({
                        "type": "error", "handler": "distress_beacon",
                        "message": str(db_err),
                    }))

            # =================================================================
            # UNKNOWN MESSAGE TYPE — catch-all
            # =================================================================

            else:
                print(f">>> [SOCKET] Unknown message type: {t} from uid={uid}")
                await websocket.send(json.dumps({
                    "type": "error",
                    "message": f"Unknown message type: {t}",
                    "hint": "Check the API documentation for valid message types.",
                }))

    except websockets.exceptions.ConnectionClosed:
        print(f">>> [SOCKET] Connection closed for {uid}")
        # #region agent log
        print(f">>> [DBG-H2] ConnectionClosed uid={uid} remaining_sockets={len(cortex.sockets.get(uid, set()))}")
        # #endregion
    except Exception as e:
        print(f">>> [ERROR] {type(e).__name__}: {e}")
        # #region agent log
        print(f">>> [DBG-H2] handle_client EXCEPTION uid={uid} err={type(e).__name__}: {e}")
        # #endregion
    finally:
        # #region agent log
        print(f">>> [DBG-H2] handle_client FINALLY uid={uid} unregistering socket, sockets_before={len(cortex.sockets.get(uid, set()))}")
        # #endregion
        if _connections_per_ip.get(client_ip, 0) > 0:
            _connections_per_ip[client_ip] -= 1
        else:
            _connections_per_ip.pop(client_ip, None)
        cortex.unregister(uid, websocket)
        notification_system.unregister_connection(uid, websocket)
        nevedal_handler.cleanup_connection(websocket)

        # Clean up sanctuary websocket registrations (prevent stale sends)
        try:
            for sanc_id in list(sanctuary_engine._websocket_registry.keys()):
                if uid in sanctuary_engine._websocket_registry.get(sanc_id, {}):
                    sanctuary_engine.member_disconnect(sanc_id, uid)
                    print(f"[Sanctuary] Unregistered {uid} from sanctuary {sanc_id}")
        except Exception as sanc_cleanup_err:
            print(f"[Sanctuary] Disconnect cleanup error: {sanc_cleanup_err}")

        # Clean up coach connection for classroom notifications
        if uid and uid in connected_coaches:
            connected_coaches.pop(uid, None)
            print(f"[Classroom] Unregistered coach connection: {uid}")
        
        # Clean up client connection tracking
        if uid and uid in connected_clients:
            connected_clients.pop(uid, None)
            print(f"[Dashboard] Unregistered client connection: {uid}")
        
        # Broadcast updated stats to connected admins on disconnect
        try:
            await _broadcast_admin_stats()
        except Exception:
            pass


swarm_relay = None  # Initialized in main()

async def main():
    """Start the WebSocket server"""
    global db_pool, swarm_relay, _pg_user_store, _registry_cache

    print(f"[*] Starting Sovereign Bridge v16.1 on {HOST}:{PORT}")
    print(f"[*] Azure Endpoint: {AZURE_ENDPOINT[:50]}...")
    print(f"[*] Data Directory: {DATA_DIR}")
    print(f"[*] PostgreSQL Registry: {'ENABLED' if _use_pg_registry else 'DISABLED (JSON fallback)'}")

    # ── Create asyncpg database pool for services that need SQL access ──
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            import asyncpg
            db_pool = await asyncpg.create_pool(
                database_url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            print(f"[*] Database pool created ({db_pool.get_size()} connections)")
            billing_system.db_pool = db_pool  # Founding member eligibility (platform_config)
            # B5: Vault integration for chat file uploads/previews
            try:
                from .vault_bridge import VaultBridge
                bridge_context.vault_bridge = VaultBridge(db_pool)
                print(f"[*] VaultBridge initialized for chat file interactions")
            except Exception as vb_err:
                print(f"[!] VaultBridge init failed: {vb_err}")
                bridge_context.vault_bridge = None
        except Exception as db_err:
            print(f"[!] Database pool creation failed: {db_err}")
            print(f"[!] NateNudge and AI Mode handlers will be unavailable")
            db_pool = None
    else:
        print(f"[!] DATABASE_URL not set — NateNudge and AI Mode handlers unavailable")
        db_pool = None

    # ── Initialize PostgreSQL-backed UserStore ──
    if _use_pg_registry and db_pool:
        try:
            from .user_store import UserStore
        except ImportError:
            try:
                from user_store import UserStore
            except ImportError:
                from app.websocket.user_store import UserStore

        _pg_user_store = UserStore(db_pool, json_path=REGISTRY_FILE)
        pg_registry = await _pg_user_store.initialize()

        if _pg_user_store.is_ready:
            if pg_registry:
                _registry_cache = pg_registry
                print(f"[*] UserStore ready: {len(_registry_cache)} users loaded from PostgreSQL")
            else:
                # PG is empty — seed from JSON registry
                json_registry = load_json_file(REGISTRY_FILE, {}) or {}
                backend_registry = load_json_file(BACKEND_REGISTRY_FILE, {}) or {}
                merged = dict(backend_registry)
                merged.update(json_registry)
                if merged:
                    saved = await _pg_user_store.save_all(merged)
                    _registry_cache = merged
                    print(f"[*] UserStore seeded from JSON: {saved} users imported to PostgreSQL")
                else:
                    _registry_cache = {}
                    print(f"[*] UserStore ready (empty — no users in JSON or PostgreSQL)")
        else:
            print(f"[!] UserStore initialization failed — falling back to JSON registry")
    else:
        if _use_pg_registry:
            print(f"[!] USE_POSTGRES_REGISTRY=true but no db_pool — falling back to JSON")

    # ── Swarm Relay Client — allows bridge to invoke FastAPI swarm services ──
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
    try:
        from app.services.swarm_relay import SwarmRelayClient
        swarm_relay = SwarmRelayClient(redis_url)
        await swarm_relay.connect()
        print(f"[*] Swarm Relay Client connected (bridge → API swarm services)")
    except Exception as sr_err:
        print(f"[!] Swarm Relay Client failed: {sr_err}")
        swarm_relay = None

    # Run Night School on startup (async background task)
    asyncio.create_task(night_school.start_session())

    # Start periodic stale WebSocket connection cleanup
    asyncio.create_task(_ws_stale_cleanup_loop())
    
    async with websockets.serve(
        handle_client, HOST, PORT,
        ping_interval=20,   # Send ping every 20 seconds
        ping_timeout=10,    # Wait 10 seconds for pong before closing
        max_size=1_048_576,  # 1MB max message size — prevents memory exhaustion DoS
    ):
        print(f"[*] Bridge Online. Awaiting connections... (ping_interval=20s, ping_timeout=10s)")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
