import asyncio, json, logging, os, time, base64, random
from pathlib import Path
import aiohttp
from websockets import serve

# ==============================================================================
# SOVEREIGN BRIDGE v23.41: SYNTAX PATCH
# ==============================================================================
logger = logging.getLogger("azure_bridge")

# Secure logging with PII auto-redaction
try:
    from app.secure_logger import get_secure_logger
    secure_log = get_secure_logger("azure_bridge.secure")
except Exception:
    secure_log = logger  # Fallback to standard logger

print(">>> [SYSTEM] Initializing Sovereign Bridge v23.41 (Syntax Patch)...")

try:
    from dotenv import load_dotenv
    script_dir = Path(__file__).resolve().parent
    env_path = script_dir / '.env' 
    load_dotenv(dotenv_path=env_path, override=False)
except ImportError: pass

# --- TRIAL MANAGER ---
class TrialManager:
    def __init__(self):
        self.ledger_path = Path("./trial_ledger.json")
        self.subscribers = ["ADMIN_PRIMARY_DEVICE", "MOBILE_CLIENT_V1"] 
        self.load_ledger()

    def load_ledger(self):
        if not self.ledger_path.exists(): 
            self.data = {}
            self.save_ledger()
        else:
            # FIX: Expanded to multi-line syntax
            try: 
                with open(self.ledger_path, 'r') as f: 
                    self.data = json.load(f)
            except Exception as e:
                logger.debug(f"Error loading trial ledger: {e}")
                self.data = {}

    def save_ledger(self):
        with open(self.ledger_path, 'w') as f: json.dump(self.data, f, indent=2)

    def check_status(self, profile=None, hardware_id=None):
        """
        Two-phase 14-day trial gating.
        profile: user profile dict (from registry); may be None for unknown users.
        hardware_id: for VIP bypass when profile lookup fails.
        """
        hw_id = (profile.get("hardware_id") if profile else None) or hardware_id or ""
        if hw_id and str(hw_id).upper() in self.subscribers:
            return {"access": True, "tier": "TOP_TIER", "msg": "VIP Access"}

        if not profile:
            return {"access": True, "tier": "STANDARD", "ai_minutes": 300, "tokens": 50000, "phase": "full", "msg": "Standard Mode"}

        from datetime import datetime, timezone

        trial_start_str = profile.get("trial_start_date") or profile.get("created_at")
        if not trial_start_str:
            return {"access": True, "tier": "STANDARD", "ai_minutes": 300, "tokens": 50000, "phase": "full", "msg": "Standard Mode"}

        try:
            trial_start = datetime.fromisoformat(str(trial_start_str).replace("Z", "+00:00"))
            if trial_start.tzinfo is None:
                trial_start = trial_start.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return {"access": True, "tier": "STANDARD", "ai_minutes": 300, "tokens": 50000, "phase": "full", "msg": "Standard Mode"}

        now = datetime.now(timezone.utc)
        trial_day = (now - trial_start).days + 1
        if trial_day < 1:
            trial_day = 1

        if 1 <= trial_day <= 7:
            return {
                "access": True,
                "tier": "STANDARD",
                "ai_minutes": 300,
                "tokens": 50000,
                "phase": "full",
                "msg": "Full trial access (Week 1)",
            }
        if 8 <= trial_day <= 14:
            return {
                "access": True,
                "tier": "TRIAL",
                "phase": "gated",
                "ai_minutes_per_day": 30,
                "tokens": 50000,
                "coherence_prompt": True,
                "gated": True,
                "msg": "Reduced trial access (Week 2)",
            }
        return {
            "access": False,
            "tier": "EXPIRED",
            "phase": "expired",
            "msg": "Trial expired",
        }

# --- KNOWLEDGE VECTORS ---
class KnowledgeVectors:
    def __init__(self):
        self.data = {
            "IFS": {"txt": ["All parts are welcome.", "No bad parts, only burdens."]},
            "CHRISTIAN_NEURO": {"txt": ["Grace rewires the brain.", "Safety is the prerequisite for vulnerability."]}
        }
    def get_wisdom(self, modality):
        if modality in self.data: return f"[{modality} AXIOM]: {random.choice(self.data[modality]['txt'])}"
        return "[LITTLE NATE WISDOM]: Love is the answer."

class SovereignBridge:
    # Subscription tiers that grant access to full Realtime interactive voice
    REALTIME_VOICE_TIERS = {"TOP_TIER", "SOVEREIGN_CIRCLE"}
    
    def __init__(self):
        self.active_sessions = {}
        self.user_sockets = {} 
        self.api_key = os.getenv("AZURE_API_KEY")
        self.endpoint = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").replace("wss://", "").replace("https://", "").replace("/", "")
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-realtime")
        
        # User registry path — matches bridge_server.py's DATA_DIR
        self._registry_path = Path("./data/user_registry.json")
        
        Path("./Vaults").mkdir(exist_ok=True)
        telemetry_path = Path("./telemetry_stream.csv")
        if not telemetry_path.exists():
            with open(telemetry_path, "w", encoding="utf-8") as f: f.write("timestamp,user,tier,coherence,stability,message\n")
            
        self.kb = KnowledgeVectors()
        self.trial_manager = TrialManager()
    
    def _get_user_profile(self, hardware_id: str) -> dict | None:
        """Look up a user's profile from user_registry.json. Returns None if not found."""
        try:
            if self._registry_path.exists():
                with open(self._registry_path, "r") as f:
                    registry = json.load(f)
                for k, v in registry.items():
                    profile = v.get("profile", {})
                    if profile.get("hardware_id", "").upper() == hardware_id.upper():
                        return profile
        except Exception as e:
            print(f">>> [TIER] Error reading registry: {e}")
        return None

    def _get_user_subscription(self, hardware_id: str) -> str:
        """Look up a user's subscription_plan from user_registry.json.
        Returns the plan string (e.g. 'TRIAL', 'STANDARD', 'TOP_TIER', 'SOVEREIGN_CIRCLE')."""
        profile = self._get_user_profile(hardware_id)
        if profile:
            return (profile.get("subscription_plan") or profile.get("tier") or "STANDARD").upper()
        return "STANDARD"
    
    def _can_use_realtime(self, hardware_id: str) -> bool:
        """Check if a user's subscription allows full Realtime voice sessions.
        Only Sovereign Circle (TOP_TIER / SOVEREIGN_CIRCLE) gets access."""
        plan = self._get_user_subscription(hardware_id)
        allowed = plan in self.REALTIME_VOICE_TIERS
        if not allowed:
            print(f">>> [TIER GATE] {hardware_id} on plan '{plan}' — Realtime DENIED (requires Sovereign Circle)")
        else:
            print(f">>> [TIER GATE] {hardware_id} on plan '{plan}' — Realtime APPROVED")
        return allowed

    def get_omni_context(self, user_id):
        """Scans the Vault for ALL txt files and indexes ALL video files."""
        
        # 1. EPISODIC (Chat History)
        chat_context = ""
        try:
            p = Path(f"./Vaults/{user_id}/memory_ledger.txt")
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    chat_context = "".join(lines[-15:]) 
        except Exception as e:
            logger.debug(f"Error reading chat history: {e}")
            chat_context = "No recent chat history."

        # 2. SEMANTIC (Text Files)
        library_context = ""
        try:
            vault_path = Path("./Vaults")
            txt_files = list(vault_path.glob("*.txt"))
            for f in txt_files:
                if f.name != "memory_ledger.txt" and f.name != "knowledge_base.txt": 
                    with open(f, "r", encoding="utf-8") as txt:
                        library_context += f"\n[SOURCE: {f.name}]: {txt.read()[:1000]}..." 
        except Exception as e: library_context = f"Error reading library: {e}"

        # 3. VISUAL INDEX (Video Files)
        video_index = ""
        try:
            vault_path = Path("./Vaults")
            videos = list(vault_path.glob("*.mp4")) + list(vault_path.glob("*.mov")) + list(vault_path.glob("*.m4a"))
            if videos:
                file_names = [v.name for v in videos]
                video_index = f"AVAILABLE VIDEO ARCHIVES (Index Only): {', '.join(file_names)}"
            else:
                video_index = "No video archives found."
        except Exception as e:
            logger.debug(f"Error indexing videos: {e}")
            video_index = "Error indexing videos."

        return chat_context, library_context, video_index

    def route_to_vaults(self, content, user_id):
        try:
            session = self.active_sessions.get(user_id, {})
            tier = session.get("tier", "UNKNOWN")
            coh = session.get("coherence", 50.0)
            stab = "STABLE" if coh > 30 else "UNSTABLE"

            p = Path(f"./Vaults/{user_id}")
            p.mkdir(parents=True, exist_ok=True)
            with open(p / "memory_ledger.txt", "a", encoding="utf-8") as f:
                f.write(f"[{time.ctime()}] [Coh:{coh:.1f}] {content}\n")
            
            # SECURITY: Do NOT log user message content to telemetry CSV.
            # Only log metadata (timestamp, user_id hash, tier, metrics).
            with open("./telemetry_stream.csv", "a", encoding="utf-8") as f:
                msg_len = len(content) if content else 0
                f.write(f"{time.strftime('%H:%M:%S')},{user_id},{tier},{coh},{stab},{msg_len}_chars\n")
            print(f">>> [RECORDER] Telemetry logged ({msg_len} chars)")
        except Exception as e: print(f"Vault Error: {e}")

    async def broadcast_send(self, user_id, message_dict):
        if user_id not in self.user_sockets: return
        payload = json.dumps(message_dict)
        for ws in list(self.user_sockets[user_id]):
            try: await ws.send(payload)
            except Exception as e:
                logger.debug(f"Stale socket on broadcast: {e}")
                pass  # stale socket — will be cleaned on next iteration
        if message_dict.get("type") == "nate_audio_delta": print(".", end="", flush=True)

    async def start_realtime_session(self, user_id, modality):
        # ── HIVE DEFENSE v4.3: Enforce pinned model version ──
        _deployment = self.deployment
        try:
            import sys as _sys
            _hive_state = getattr(getattr(_sys.modules.get('__main__'), 'app', None), 'state', None)
            _hive_v4 = getattr(_hive_state, 'hive_v4', None) if _hive_state else None
            if _hive_v4:
                _msl = _hive_v4.get("model_stability")
                if _msl:
                    _pinned = _msl.get_pinned_deployment("realtime")
                    if _pinned:
                        _deployment = _pinned
                        print(f">>> [ModelStability] Using pinned deployment: {_deployment}")
        except Exception as _msl_err:
            print(f">>> [ModelStability] Non-blocking error: {_msl_err}")

        url = f"wss://{self.endpoint}/openai/realtime?api-version=2024-10-01-preview&deployment={_deployment}"
        headers = {"api-key": self.api_key, "OpenAI-Beta": "realtime=v1"}
        print(f">>> [REALTIME] Connecting to: {url}")

        chat_hist, lib_know, vid_idx = self.get_omni_context(user_id)
        axiom = self.kb.get_wisdom(modality)
        
        print(f">>> [LIBRARIAN] Injected: {len(lib_know)} chars of text, {len(vid_idx)} chars of video index.")

        system_instruction = (
            "You are Little Nate. "
            f"AXIOM: {axiom}\n"
            "DEEP MEMORY: You have access to the Sovereign Vaults. "
            "You do not 'watch' videos, but you see their filenames and understand they are part of your memory. "
            f"{vid_idx}\n"
            f"LIBRARY KNOWLEDGE:\n{lib_know}\n\n"
            f"RECENT CONVERSATION:\n{chat_hist}"
        )

        # ── HIVE DEFENSE v4.3: Anonymize system instruction before Azure ──
        # FAIL-CLOSED: If anonymization fails, do NOT send raw PII to Azure.
        # This is a hard requirement — the prompt must be scrubbed or blocked.
        _anon_map = None
        try:
            if _hive_v4:
                _anon_proxy = _hive_v4.get("anonymization_proxy")
                if _anon_proxy:
                    system_instruction, _anon_map = await _anon_proxy.anonymize_for_ai(system_instruction)
                    print(f">>> [AnonymizationProxy] Realtime system instruction anonymized ({len(_anon_map or {})} tokens replaced)")
        except Exception as _anon_err:
            print(f">>> [AnonymizationProxy] FAIL-CLOSED: anonymization failed, blocking prompt: {_anon_err}")
            # Notify user that session cannot start safely
            try:
                await self.broadcast_send(user_id, {
                    "type": "nate_response",
                    "text": "I'm having trouble preparing our session securely. Please try again in a moment.",
                })
            except Exception:
                pass
            return  # Do NOT proceed with raw PII

        try:
            # ── HIVE DEFENSE v4.3: Explicit 30s connection timeout (GAP W2) ──
            _azure_timeout = aiohttp.ClientTimeout(total=30, connect=15)
            async with aiohttp.ClientSession(timeout=_azure_timeout) as session:
                async with session.ws_connect(url, headers=headers) as azure_ws:
                    print(f">>> [REALTIME] âœ… Brain Active for {user_id}")
                    if user_id in self.active_sessions: self.active_sessions[user_id]["realtime_ws"] = azure_ws
                    
                    await azure_ws.send_str(json.dumps({
                        "type": "session.update",
                        "session": {
                            "modalities": ["text", "audio"],
                            "instructions": system_instruction,
                            "voice": "echo", 
                            "turn_detection": {"type": "server_vad"},
                            "input_audio_transcription": {"model": "whisper-1"}
                        }
                    }))
                    
                    current_transcript = ""
                    async for msg in azure_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            event_type = event.get("type")
                            
                            if event_type == "error": print(f"\n>>> [AZURE ERROR] {json.dumps(event)}")
                            
                            if event_type == "response.audio.delta":
                                asyncio.create_task(self.broadcast_send(user_id, {"type": "nate_audio_delta", "payload": event.get("delta")}))
                            elif event_type == "response.audio_transcript.delta" or event_type == "response.text.delta":
                                delta = event.get("delta", "")
                                if delta:
                                    current_transcript += delta
                                    # De-anonymize before sending to user
                                    _display_text = current_transcript
                                    if _anon_map and _hive_v4:
                                        try:
                                            _ap = _hive_v4.get("anonymization_proxy")
                                            if _ap:
                                                _display_text = await _ap.deanonymize(_display_text, _anon_map)
                                        except Exception:
                                            pass
                                    asyncio.create_task(self.broadcast_send(user_id, {"type": "nate_response", "text": _display_text}))
                            elif event_type == "response.audio_transcript.done":
                                full_text = event.get("transcript", "")
                                if not full_text: full_text = current_transcript
                                # De-anonymize final transcript
                                if _anon_map and _hive_v4:
                                    try:
                                        _ap = _hive_v4.get("anonymization_proxy")
                                        if _ap:
                                            full_text = await _ap.deanonymize(full_text, _anon_map)
                                    except Exception:
                                        pass
                                print(f">>> [BRAIN] Nate response generated ({len(full_text)} chars)")
                                self.route_to_vaults(f"NATE: {full_text}", user_id)
                                current_transcript = "" 
        except Exception as e: print(f">>> [REALTIME FAILED]: {e}")

    async def relay_command(self, websocket):
        try:
            async for message in websocket:
                try: 
                    data = json.loads(message)
                    m_type = data.get('type')
                    if m_type == "auth_handshake":
                        user_id = str(data.get('hardware_id', 'GUEST')).strip().upper()
                        profile = self._get_user_profile(user_id)
                        status = self.trial_manager.check_status(profile=profile, hardware_id=user_id)
                        print(f">>> [ACCESS] User: {user_id} | Status: {status['msg']}")
                        
                        self.active_sessions[user_id] = {"ws": websocket, "tier": status["tier"], "coherence": 50.0}
                        if user_id not in self.user_sockets: self.user_sockets[user_id] = set()
                        self.user_sockets[user_id].add(websocket)
                        
                        # TIER GATE: Only Sovereign Circle gets full Realtime voice
                        if self._can_use_realtime(user_id):
                            modality = data.get('modality', 'IFS')
                            asyncio.create_task(self.start_realtime_session(user_id, modality))
                            await websocket.send(json.dumps({"type": "nate_response", "text": f"System Online. {status['msg']}"}))
                        else:
                            await websocket.send(json.dumps({
                                "type": "nate_response",
                                "text": "Text mode active. Upgrade to Sovereign Circle for live voice conversations."
                            }))
                            await websocket.send(json.dumps({
                                "type": "error",
                                "message": "UPGRADE_REQUIRED",
                                "detail": "Live voice requires Sovereign Circle subscription ($149/mo)"
                            }))
                        
                    elif m_type == "nate_query":
                        text = data.get('nate_query', '')
                        print(f">>> [INPUT] User query received ({len(text)} chars)")
                        if user_id in self.active_sessions: self.active_sessions[user_id]["coherence"] = float(data.get('c_val', 50.0))
                        self.route_to_vaults(f"USER: {text}", user_id)
                        session = self.active_sessions.get(user_id)
                        if session and "realtime_ws" in session:
                            await session["realtime_ws"].send_str(json.dumps({
                                "type": "conversation.item.create",
                                "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}
                            }))
                            await session["realtime_ws"].send_str(json.dumps({"type": "response.create"}))
                    else:
                        print(f">>> [UNKNOWN PACKET] {data}")
                except Exception as relay_err:
                    print(f">>> [RELAY] Message handling error: {relay_err}")
        except Exception as e: print(f">>> [ERROR] {e}")

async def main():
    import subprocess
    subprocess.run(["sh", "-c", "lsof -ti:8765 | xargs kill -9 2>/dev/null"], check=False)
    print("=" * 70)
    print("SOVEREIGN BRIDGE v23.41: SYNTAX PATCH")
    print("=" * 70)
    async with serve(SovereignBridge().relay_command, "0.0.0.0", 8765):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())