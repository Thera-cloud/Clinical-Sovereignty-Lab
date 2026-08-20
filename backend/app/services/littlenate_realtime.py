"""
LittleNate-1.X Realtime WebSocket Server.

OpenAI-Realtime-compatible protocol for bidirectional audio streaming.

Pipeline per turn:
  1. Accumulate audio buffer from input_audio_buffer.append
  2. On commit → STT via sovereign Whisper (or Azure fallback)
  3. Extract client voice biometrics
  4. Relational attunement: assess therapeutic vs friendship mode
  5. Build conversation-aware prompt with memory of all prior turns
  6. Transcript → LittleNateInference.generate() (Helix + LLM)
  7. Response text → RISSC TTS with coherence modulation
  8. Stream audio chunks as response.audio.delta
  9. Score via VoiceBiometricExtractor + Nevedal reward loop
  10. Store turn in conversation memory
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

try:
    from app.services.backchannel_engine import BackchannelEngine, MultiSignalTurnDetector
except ImportError:
    BackchannelEngine = None  # type: ignore[assignment,misc]
    MultiSignalTurnDetector = None  # type: ignore[assignment,misc]

try:
    from app.services.neural_mirror import NeuralMirrorSession
except ImportError:
    NeuralMirrorSession = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

COHERENCE_TTS_MAP = {
    "deeply_coherent": {"rate": "-5%", "pitch": "-2Hz"},
    "grounded": {"rate": "+0%", "pitch": "+0Hz"},
    "uncertain": {"rate": "-3%", "pitch": "+0Hz"},
    "seeking": {"rate": "-8%", "pitch": "-1Hz"},
}

DEFAULT_VOICE = "nate_warm"

# Phrases commonly spoken by carrier phone assistants / voicemail intercepts
# before the actual person picks up. Nate must ignore these.
_CARRIER_GREETING_PATTERNS = [
    "see if this person is available",
    "i'll see if they're available",
    "let me see if they can take your call",
    "please hold while i connect",
    "please hold while i transfer",
    "please hold while we connect",
    "hold while i try to reach",
    "connecting you now",
    "transferring your call",
    "the person you are trying to reach",
    "the subscriber you have dialed",
    "is not available",
    "leave a message after the beep",
    "leave a message after the tone",
    "record your message",
    "at the tone please record",
    "press 1 to leave a callback",
    "press 1 to leave a voice",
    "your call has been forwarded",
    "the google subscriber",
    "google voice",
    "the mailbox is full",
    "this call is being screened",
    "who's calling please",
    "who is calling",
    "may i ask who's calling",
    "state your name",
    "please say your name",
]


def _is_carrier_greeting(transcript: str) -> bool:
    """Check if a transcript matches a carrier/phone assistant greeting."""
    t = transcript.lower().strip()
    if len(t) < 5:
        return False
    for pattern in _CARRIER_GREETING_PATTERNS:
        if pattern in t:
            return True
    return False


class RealtimeSession:
    """A single realtime voice session with conversation memory."""

    def __init__(self, session_id: str, websocket, app_state=None):
        self.session_id = session_id
        self.ws = websocket
        self._app_state = app_state
        self._audio_buffer = bytearray()
        self._voice = DEFAULT_VOICE
        self._modalities = ["text", "audio"]
        self._instructions = ""
        self._cancel_event = asyncio.Event()
        self._active_task: Optional[asyncio.Task] = None
        self._client_biometrics: Dict[str, float] = {}
        # Slice 0: user identity captured from webrtc.setup / session.update
        # for per-user biometrics opt-out enforcement (IL BIPA §15(b)).
        self._user_id: Optional[str] = None

        # Cloudflare Realtime integration
        self._sfu_session_id: Optional[str] = None
        self._moq_namespace: Optional[str] = None
        self._turn_credentials: Optional[Dict] = None
        self._use_webrtc: bool = False  # Toggle: True = SFU/WebRTC, False = raw WebSocket

        # Conversation memory: per-session, not global
        from app.services.relational_attunement import ConversationState
        self._conversation = ConversationState()

    async def setup_webrtc(self, user_id: str) -> Dict[str, Any]:
        """
        Bootstrap Cloudflare Realtime for this session.
        Returns TURN credentials + SFU session info + MoQ namespace for client.
        """
        import httpx

        _cf_turn_id = os.getenv("CLOUDFLARE_TURN_TOKEN_ID", "")
        _cf_turn_key = os.getenv("CLOUDFLARE_TURN_API_TOKEN", "")
        _cf_sfu_app = os.getenv("CLOUDFLARE_SFU_APP_ID", "")
        _cf_sfu_key = os.getenv("CLOUDFLARE_SFU_API_TOKEN", "")
        _cf_moq = os.getenv("CLOUDFLARE_MOQ_ENDPOINT", "draft-14.cloudflare.mediaoverquic.com")

        result: Dict[str, Any] = {"turn": None, "sfu": None, "moq": None}

        async with httpx.AsyncClient(timeout=10) as client:
            if _cf_turn_id and _cf_turn_key:
                try:
                    resp = await client.post(
                        f"https://rtc.live.cloudflare.com/v1/turn/keys/{_cf_turn_id}/credentials/generate",
                        headers={"Authorization": f"Bearer {_cf_turn_key}", "Content-Type": "application/json"},
                        json={"ttl": 86400},
                    )
                    if resp.status_code == 201:
                        self._turn_credentials = resp.json()
                        result["turn"] = self._turn_credentials
                except Exception as e:
                    logger.warning("TURN credential fetch failed: %s", e)

            if _cf_sfu_app and _cf_sfu_key:
                try:
                    resp = await client.post(
                        f"https://rtc.live.cloudflare.com/v1/apps/{_cf_sfu_app}/sessions/new",
                        headers={"Authorization": f"Bearer {_cf_sfu_key}", "Content-Type": "application/json"},
                        json={},
                    )
                    if resp.status_code == 201:
                        sfu_data = resp.json()
                        self._sfu_session_id = sfu_data.get("sessionId")
                        result["sfu"] = sfu_data
                        self._use_webrtc = True
                except Exception as e:
                    logger.warning("SFU session creation failed: %s", e)

            self._moq_namespace = f"sanctuary/{self.session_id}/nate-voice-{user_id}"
            result["moq"] = {
                "endpoint": _cf_moq,
                "namespace": self._moq_namespace,
                "protocol": "draft-14",
            }

        return result

    async def handle_message(self, msg: Dict[str, Any]):
        """Process an incoming client message."""
        msg_type = msg.get("type", "")

        if msg_type == "session.update":
            session_cfg = msg.get("session", {})
            self._voice = session_cfg.get("voice", self._voice)
            self._modalities = session_cfg.get("modalities", self._modalities)
            self._instructions = session_cfg.get("instructions", self._instructions)
            await self._send({"type": "session.updated", "session": {
                "id": self.session_id,
                "voice": self._voice,
                "modalities": self._modalities,
            }})

        elif msg_type == "webrtc.setup":
            user_id = msg.get("user_id", self.session_id)
            self._user_id = user_id
            webrtc_info = await self.setup_webrtc(user_id)
            await self._send({"type": "webrtc.ready", "webrtc": webrtc_info})

        elif msg_type == "input_audio_buffer.append":
            audio_b64 = msg.get("audio", "")
            if audio_b64:
                self._audio_buffer.extend(base64.b64decode(audio_b64))

        elif msg_type == "input_audio_buffer.commit":
            if self._active_task and not self._active_task.done():
                self._cancel_event.set()
                self._active_task.cancel()

            self._cancel_event = asyncio.Event()
            audio_data = bytes(self._audio_buffer)
            self._audio_buffer.clear()

            self._active_task = asyncio.create_task(
                self._process_turn(audio_data)
            )

        elif msg_type == "input_audio_buffer.clear":
            self._audio_buffer.clear()

        elif msg_type == "response.cancel":
            self._cancel_event.set()
            if self._active_task and not self._active_task.done():
                self._active_task.cancel()

    async def _process_turn(self, audio_data: bytes):
        """Full pipeline for one conversational turn with memory and attunement."""
        from app.services.relational_attunement import (
            TurnMemory,
            assess_relational_mode,
            build_relational_system_prompt,
            build_conversation_context,
            detect_silence_opportunity,
        )

        response_id = f"resp_{uuid.uuid4().hex[:12]}"
        start = time.time()

        try:
            await self._send({"type": "response.created", "response": {"id": response_id}})

            # ── 1. Extract client voice biometrics (Slice 0: honor opt-out) ─
            try:
                extractor = getattr(self._app_state, "voice_biometric_extractor", None)
                if extractor and len(audio_data) > 1000:
                    _bio_disabled = False
                    if self._user_id:
                        try:
                            from app.services.biometrics_consent import is_biometrics_disabled

                            _pool = getattr(self._app_state, "db_pool", None)
                            _bio_disabled = await is_biometrics_disabled(self._user_id, _pool)
                        except Exception:
                            _bio_disabled = False
                    if not _bio_disabled:
                        self._client_biometrics = extractor.process_audio_chunk(audio_data)
            except Exception:
                pass

            # ── 2. Transcribe ───────────────────────────────────────────
            transcript = await self._stt(audio_data)
            if not transcript:
                await self._send({
                    "type": "response.done",
                    "response": {"id": response_id, "status": "failed",
                                 "status_details": {"error": "Could not transcribe audio"}},
                })
                return

            await self._send({
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": transcript,
            })

            # ── 3. Inference with cognitive stack ───────────────────────
            inference = getattr(self._app_state, "littlenate_inference", None)
            if not inference:
                await self._send_text_and_done(response_id, "Inference service not available.", start)
                return

            # Pre-inference quantum eval gives us coherence for attunement
            quantum = getattr(self._app_state, "quantum_cognition_engine", None)
            current_coherence = 0.5
            current_felt_sense = "grounded"
            if quantum:
                try:
                    qeval = await quantum.evaluate(transcript)
                    qs = qeval.get("quantum_self", {})
                    current_coherence = qs.get("c_quantum_self", 0.5)
                    current_felt_sense = qs.get("felt_sense", "grounded")
                except Exception:
                    pass

            # ── 4. Record the user's turn in memory ─────────────────────
            user_turn = TurnMemory(
                role="user",
                text=transcript,
                timestamp=time.time(),
                felt_sense=current_felt_sense,
                c_quantum_self=current_coherence,
                voice_stress=self._client_biometrics.get("voice_stress_index", 0.0),
                voice_warmth=self._client_biometrics.get("voice_warmth_index", 0.0),
            )
            self._conversation.add_turn(user_turn)

            # ── 5. Relational attunement: therapeutic or friendship? ────
            mode, mode_confidence = assess_relational_mode(
                self._conversation,
                current_felt_sense,
                current_coherence,
                self._client_biometrics or None,
            )

            # Build conversation-aware context and system prompt
            conversation_context = build_conversation_context(self._conversation)
            relational_prompt = build_relational_system_prompt(
                self._conversation, mode, mode_confidence,
                current_felt_sense, domain="clinical",
            )

            # Silence spark: if they're coherent and brief, suggest a conversation spark
            silence_spark = detect_silence_opportunity(self._conversation)

            # ── 6. Generate with full context ───────────────────────────
            result = await inference.generate(
                prompt=transcript,
                system=self._instructions,
                domain="clinical",
                tier="clinical",
                conversation_context=conversation_context,
                relational_system_prompt=relational_prompt,
                silence_spark=silence_spark,
                include_quantum=False,  # already evaluated above
            )
            result.c_quantum_self = current_coherence
            result.felt_sense = current_felt_sense
            result.relational_mode = mode

            if self._cancel_event.is_set():
                return

            # ── 7. Record Nate's response in memory ─────────────────────
            nate_turn = TurnMemory(
                role="nate",
                text=result.text,
                timestamp=time.time(),
                felt_sense=result.felt_sense,
                c_quantum_self=result.c_quantum_self,
                relational_mode=mode,
            )
            self._conversation.add_turn(nate_turn)

            # ── 8. Send text + audio ────────────────────────────────────
            if "text" in self._modalities:
                await self._send({
                    "type": "response.text.delta",
                    "response_id": response_id,
                    "delta": result.text,
                })

            if "audio" in self._modalities and result.text:
                await self._stream_tts(response_id, result.text, result.felt_sense)

            # ── 9. Reward scoring ───────────────────────────────────────
            reward = getattr(self._app_state, "littlenate_reward", None)
            if reward:
                await reward.score_and_store(
                    prompt=transcript,
                    response=result.text,
                    c_knowledge=result.c_knowledge,
                    c_quantum_self=result.c_quantum_self,
                    felt_sense=result.felt_sense,
                    domain=result.domain,
                    provider=result.provider,
                    tokens_used=result.tokens_used,
                    latency_ms=result.latency_ms,
                )

            # ── 10. Final response event ────────────────────────────────
            elapsed = int((time.time() - start) * 1000)
            await self._send({
                "type": "response.done",
                "response": {
                    "id": response_id,
                    "status": "completed",
                    "output": [{"type": "message", "content": [
                        {"type": "text", "text": result.text},
                    ]}],
                    "usage": {
                        "total_tokens": result.tokens_used,
                        "input_tokens": 0,
                        "output_tokens": result.tokens_used,
                    },
                    "metadata": {
                        "provider": result.provider,
                        "felt_sense": result.felt_sense,
                        "c_quantum_self": result.c_quantum_self,
                        "relational_mode": mode,
                        "rapport_score": self._conversation.rapport_score,
                        "coherence_trend": self._conversation.coherence_trend(),
                        "turn_number": self._conversation.user_turn_count(),
                        "latency_ms": elapsed,
                    },
                },
            })

        except asyncio.CancelledError:
            logger.info("RealtimeSession %s: turn cancelled", self.session_id)
        except Exception as e:
            logger.error("RealtimeSession %s: turn failed: %s", self.session_id, e)
            await self._send({
                "type": "response.done",
                "response": {"id": response_id, "status": "failed",
                             "status_details": {"error": str(e)}},
            })

    async def _stt(self, audio_data: bytes) -> Optional[str]:
        """Transcribe audio via sovereign Whisper with Azure fallback."""
        try:
            from app.services.sovereign_whisper import transcribe
            result = await transcribe(audio_data)
            return result.get("text", "").strip() or None
        except Exception as e:
            logger.warning("RealtimeSession STT failed: %s", e)
            return None

    async def _stream_tts(self, response_id: str, text: str, felt_sense: str):
        """Stream TTS audio with RISSC voice modulation — sovereign XTTS first, Edge TTS fallback."""
        biometrics = self._client_biometrics or None
        rissc = None
        sovereign_audio = None

        try:
            from app.services.sovereign_tts import synthesize as xtts_synthesize
            from app.services.rissc_voice import get_rissc_params, rissc_to_dict
            rissc = get_rissc_params(felt_sense, biometrics)
            sovereign_audio = await xtts_synthesize(
                text,
                rissc_params=rissc_to_dict(rissc),
                speed=rissc.speed,
                temperature=rissc.temperature,
                top_p=rissc.top_p,
                top_k=rissc.top_k,
                repetition_penalty=rissc.repetition_penalty,
            )
        except Exception as e:
            logger.warning("RealtimeSession RISSC XTTS failed: %s", e)

        if sovereign_audio:
            chunk_size = 4096
            for i in range(0, len(sovereign_audio), chunk_size):
                if self._cancel_event.is_set():
                    return
                chunk = sovereign_audio[i:i + chunk_size]
                await self._send({
                    "type": "response.audio.delta",
                    "response_id": response_id,
                    "delta": base64.b64encode(chunk).decode(),
                })
            await self._send({
                "type": "response.audio.rissc",
                "response_id": response_id,
                "rissc_mode": rissc.rissc_mode if rissc else "unknown",
                "felt_sense": felt_sense,
            })
            return

        from app.services import edge_tts_service
        try:
            from app.services.rissc_voice import get_rissc_params, rissc_to_edge_tts
            if not rissc:
                rissc = get_rissc_params(felt_sense, biometrics)
            edge_params = rissc_to_edge_tts(rissc)
        except ImportError:
            edge_params = COHERENCE_TTS_MAP.get(felt_sense, COHERENCE_TTS_MAP["grounded"])

        try:
            async for chunk_type, chunk_data in edge_tts_service.synthesize_streaming(
                text,
                voice=self._voice,
                rate=edge_params.get("rate", "+0%"),
                pitch=edge_params.get("pitch", "+0Hz"),
            ):
                if self._cancel_event.is_set():
                    return
                if chunk_type == "audio":
                    await self._send({
                        "type": "response.audio.delta",
                        "response_id": response_id,
                        "delta": base64.b64encode(chunk_data).decode(),
                    })
        except Exception as e:
            logger.warning("RealtimeSession TTS streaming failed: %s", e)

    async def _send_text_and_done(self, response_id: str, text: str, start: float):
        elapsed = int((time.time() - start) * 1000)
        await self._send({
            "type": "response.text.delta",
            "response_id": response_id,
            "delta": text,
        })
        await self._send({
            "type": "response.done",
            "response": {"id": response_id, "status": "completed",
                         "usage": {"total_tokens": 0},
                         "metadata": {"latency_ms": elapsed}},
        })

    async def _send(self, data: Dict):
        try:
            await self.ws.send_text(json.dumps(data))
        except Exception:
            pass


def _twilio_stream_custom_parameters(start_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize Twilio Media Stream ``start.customParameters`` into string values.

    Twilio sends ``<Stream><Parameter name=... value=.../>`` as a JSON object.
    Some gateways may expose a list of {name, value}; support both.
    """
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


class TwilioMediaSession:
    """
    Handles Twilio Media Stream WebSocket for phone-based conversations.

    Twilio sends mulaw 8kHz audio; we convert to PCM for STT, run the full
    cognitive pipeline (attunement, inference, RISSC TTS), convert back to
    mulaw, and stream to the caller.

    Unlike RealtimeSession which uses OpenAI's protocol, this speaks
    Twilio's Media Stream JSON protocol (event: connected, start, media, stop).
    """

    def __init__(
        self,
        session_id: str,
        websocket,
        app_state=None,
        call_context: Optional[Dict] = None,
        stream_sid: str = "",
    ):
        self.session_id = session_id
        self.ws = websocket
        self._app_state = app_state
        self._stream_sid = stream_sid
        self._audio_chunks: list = []
        self._chunk_count = 0
        self._cancel_event = asyncio.Event()
        self._active_task: Optional[asyncio.Task] = None
        self._client_biometrics: Dict[str, float] = {}
        self._call_context = call_context or {}

        # Silence-based turn detection
        self._silence_chunks = 0
        self._has_speech = False
        self._SILENCE_THRESHOLD = 40  # ~0.8s -- early candidate signal, MultiSignalTurnDetector is the real gate
        self._MIN_SPEECH_CHUNKS = 25  # Need at least ~500ms of speech
        self._MAX_TURN_CHUNKS = 750   # Force-process after ~15s of speech (let them talk)
        self._ENERGY_THRESHOLD = 25   # mulaw energy threshold (slightly higher to reduce noise)
        self._is_speaking = False     # Nate is currently outputting audio

        # Caller speech rate tracking (WPM)
        self._caller_wpm: float = 0.0
        self._wpm_samples: list = []  # rolling window of (wpm, weight) tuples

        # Queued audio: when Nate is responding, new speech goes here
        # instead of cancelling his response
        self._pending_chunks: list = []

        # Carrier greeting detection: the first utterance(s) may be a phone
        # assistant ("I'll see if this person is available"). Nate must ignore
        # these and wait for the real person.
        self._carrier_passed = False
        self._carrier_check_window = 3  # only check first N user utterances

        from app.services.relational_attunement import ConversationState
        self._conversation = ConversationState()
        self._conversation.is_nate_initiated = self._call_context.get("is_nate_initiated", True)

        self._instructions = self._call_context.get("system_prompt", "")
        self._opening_delivered = False
        self._finalized = False
        self._on_start_callback = None
        self._duration_task: Optional[asyncio.Task] = None
        self._voice_stream_started_at: Optional[float] = None
        self._user_memory_context: Optional[str] = None
        self._user_name: str = ""

        # 10-Dimension Conversational Coherence Helix
        from app.services.conversational_coherence_helix import ConversationalCoherenceHelix
        username = self._call_context.get("username", "")
        rapport_topics = self._call_context.get("rapport_topics", [])
        self._helix = ConversationalCoherenceHelix(
            username=username,
            rapport_topics=rapport_topics,
        )
        self._last_helix_output = None
        self._turn_start_time: float = 0.0

        # SOVEREIGN-VOICE: prepaid billing state
        self._voice_billing_user_id: Optional[str] = None
        self._voice_billing_session_id: Optional[str] = None
        self._admin_bypass: bool = False
        self._billing_active: bool = False
        self._waiting_extension: bool = False
        self._extension_decision: Optional[str] = None
        self._server_initiated_hangup: bool = False
        self._total_billed_seconds: int = 0
        self._billing_context_addon: str = ""
        self._billing_task: Optional[asyncio.Task] = None
        self._last_low_balance_alert: float = 0.0
        self._last_recovery_sms: float = 0.0

        # Patent 8: Backchannel engine + multi-signal turn detector
        self._bc_engine = BackchannelEngine() if BackchannelEngine else None
        self._turn_detector = MultiSignalTurnDetector() if MultiSignalTurnDetector else None

        # Patent 11: Neural Mirror session
        self._neural_mirror = None
        if NeuralMirrorSession and self._voice_billing_user_id:
            try:
                self._neural_mirror = NeuralMirrorSession(
                    user_id=self._voice_billing_user_id,
                    session_id=self.session_id,
                    sample_rate=8000,
                )
            except Exception as e:
                logger.debug("NeuralMirrorSession init failed: %s", e)

    async def _recv_twilio_ws_text(self) -> Optional[str]:
        """Read one WebSocket frame as text. Handles text or binary JSON from Twilio.

        Starlette's ``iter_text()`` / ``receive_text()`` only accept text frames; if Twilio
        ever sends UTF-8 JSON as binary, ``receive_text()`` raises and the session dies.
        Returns None on disconnect.
        """
        message = await self.ws.receive()
        if message["type"] == "websocket.disconnect":
            return None
        if "text" in message and message["text"] is not None:
            return message["text"]
        if "bytes" in message and message["bytes"] is not None:
            raw = message["bytes"]
            if isinstance(raw, (bytes, bytearray, memoryview)):
                return bytes(raw).decode("utf-8", errors="replace")
        return ""

    async def _handle_twilio_start_event(self, start_data: dict):
        """Apply Twilio ``start`` payload: stream ids, custom parameters, helix, duration, opening."""
        self._stream_sid = start_data.get("streamSid", self._stream_sid)
        csid = start_data.get("callSid", "")
        if csid:
            self._call_context["twilio_call_sid"] = csid
        custom = _twilio_stream_custom_parameters(start_data)
        for k, v in custom.items():
            ks = str(k)
            if ks == "max_call_seconds":
                try:
                    self._call_context["max_call_seconds"] = int(v)
                except (TypeError, ValueError):
                    pass
            else:
                self._call_context[ks] = v

        # Inbound TwiML passes <Parameter name="user_id" …> but the pipeline expects "username".
        uname = (self._call_context.get("username") or self._call_context.get("user_id") or "").strip()
        if uname:
            self._call_context["username"] = uname
        # Helix was constructed before customParameters arrived — rebind with resolved username.
        from app.services.conversational_coherence_helix import ConversationalCoherenceHelix

        self._helix = ConversationalCoherenceHelix(
            username=self._call_context.get("username", ""),
            rapport_topics=self._call_context.get("rapport_topics", []),
        )

        logger.info(
            "Twilio stream start: session=%s streamSid=%s callSid=%s customKeys=%s username=%s",
            self.session_id,
            self._stream_sid,
            csid,
            sorted(custom.keys()),
            self._call_context.get("username", ""),
        )
        print(f"[TWILIO-CALL] {self.session_id}: stream started (sid={self._stream_sid})")
        self._voice_stream_started_at = time.time()

        if self._on_start_callback:
            await self._on_start_callback(start_data)

        # SOVEREIGN-VOICE: initialize billing from TwiML custom parameters
        vb_uid = self._call_context.get("voice_billing_user_id", "")
        vb_bypass = self._call_context.get("admin_bypass", "") == "true"
        vb_session = self._call_context.get("voice_billing_session_id", "")
        vb_resume = self._call_context.get("resume_session_id", "")

        if vb_uid:
            self._voice_billing_user_id = vb_uid

            pool = getattr(self._app_state, "db_pool", None)
            # Defense in depth: re-verify admin role from DB even though
            # TwiML parameters come from our own server.
            if vb_bypass and pool:
                try:
                    async with pool.acquire() as conn:
                        admin_check = await conn.fetchval(
                            """SELECT 1 FROM users
                               WHERE (username = $1 OR hardware_id = $1)
                                 AND role = 'ADMIN'
                                 AND deleted_at IS NULL
                               LIMIT 1""",
                            vb_uid,
                        )
                    if not admin_check:
                        logger.warning(
                            "admin_bypass=true in stream but %s is not ADMIN in DB — forcing bypass=false",
                            vb_uid,
                        )
                        vb_bypass = False
                except Exception as e:
                    logger.warning(
                        "admin_bypass DB re-verify failed for %s: %s — forcing bypass=false",
                        vb_uid,
                        e,
                    )
                    vb_bypass = False
            elif vb_bypass and not pool:
                logger.warning(
                    "admin_bypass=true but no db_pool for verification — forcing bypass=false",
                )
                vb_bypass = False

            self._admin_bypass = vb_bypass
            self._voice_billing_session_id = vb_session or vb_resume or ""
            if not vb_bypass:
                self._billing_active = True

            if pool and vb_uid and not vb_resume:
                try:
                    crystal = await pool.fetchrow(
                        "SELECT summary, topics, emotional_state FROM voice_crystals "
                        "WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                        vb_uid,
                    )
                    if crystal:
                        self._billing_context_addon = (
                            f"\n\nLast time you spoke with this client: {crystal['summary']}. "
                            f"Topics: {crystal['topics']}. Emotional state: {crystal['emotional_state']}. "
                            f"Open with a warm check-in referencing where they left off."
                        )
                except Exception as e:
                    logger.warning("Voice crystal recall failed: %s", e)

            if vb_resume:
                self._billing_context_addon = (
                    "\n\nThe client just called back after a dropped call. "
                    "Say something like 'I'm glad you called back, let's pick up where we left off.'"
                )

        # SOVEREIGN-VOICE: skip tier-based duration enforcement when billing loop handles it
        if self._billing_active and not self._admin_bypass:
            self._billing_task = asyncio.create_task(self._voice_billing_loop())
        elif self._duration_task is None:
            self._duration_task = asyncio.create_task(self._enforce_max_call_duration())

        if not self._opening_delivered:
            await asyncio.sleep(0.3)
            asyncio.create_task(self._deliver_opening())

    async def handle_twilio_messages(self):
        """Main loop: process Twilio Media Stream JSON messages."""
        try:
            while True:
                raw_msg = await self._recv_twilio_ws_text()
                if raw_msg is None:
                    print(f"[TWILIO-CALL] {self.session_id}: WebSocket disconnected (client)")
                    break
                if not (raw_msg or "").strip():
                    continue
                try:
                    data = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                event = data.get("event", "")

                if event == "connected":
                    print(f"[TWILIO-CALL] {self.session_id}: Twilio connected")

                elif event == "start":
                    try:
                        await self._handle_twilio_start_event(data.get("start", {}) or {})
                    except Exception as e:
                        logger.error(
                            "TwilioMediaSession %s start handler failed (stream stays up): %s",
                            self.session_id,
                            e,
                            exc_info=True,
                        )

                elif event == "media":
                    payload = data.get("media", {}).get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)

                        # Don't accumulate while Nate is speaking (echo prevention)
                        if self._is_speaking:
                            continue

                        # Simple energy-based VAD: mulaw byte 0xFF = silence
                        energy = sum(abs(b - 0xFF) for b in audio_bytes) / max(len(audio_bytes), 1)
                        is_speech = energy > self._ENERGY_THRESHOLD

                        # Patent 8: feed turn detector + backchannel engine
                        if self._turn_detector:
                            self._turn_detector.on_audio_frame(energy, is_speech, self._chunk_count * 20.0)
                        # Patent 11: feed audio to Neural Mirror
                        if self._neural_mirror and is_speech:
                            mirror_state = self._neural_mirror.on_audio_chunk(audio_bytes)
                            if mirror_state and self._bc_engine:
                                bias = self._neural_mirror.get_backchannel_bias()
                                if bias:
                                    self._bc_engine.set_register_bias(bias)
                        if self._bc_engine:
                            clip = self._bc_engine.get_backchannel(energy=energy / 127.0)
                            if clip:
                                try:
                                    clip_bytes = base64.b64decode(clip.audio_b64)
                                    b64_payload = base64.b64encode(clip_bytes).decode("ascii")
                                    await self.ws.send_json({
                                        "event": "media",
                                        "streamSid": self._stream_sid,
                                        "media": {"payload": b64_payload},
                                    })
                                except Exception as e:
                                    logger.debug("Backchannel inject failed: %s", e)

                        if is_speech:
                            self._audio_chunks.append(audio_bytes)
                            self._chunk_count += 1
                            self._has_speech = True
                            self._silence_chunks = 0
                        else:
                            self._silence_chunks += 1
                            if self._has_speech:
                                self._audio_chunks.append(audio_bytes)
                                self._chunk_count += 1

                        # Turn boundary: MultiSignalTurnDetector is the real gate (1500ms),
                        # basic silence check (800ms) is an early candidate signal only.
                        silence_end = (self._has_speech
                                       and self._silence_chunks >= self._SILENCE_THRESHOLD
                                       and self._chunk_count >= self._MIN_SPEECH_CHUNKS)
                        max_length = (self._has_speech
                                      and self._chunk_count >= self._MAX_TURN_CHUNKS)

                        if silence_end and self._turn_detector:
                            self._turn_detector.on_vad_speech_stopped()
                            should_fire, confidence = self._turn_detector.should_trigger_response()
                            if not should_fire:
                                silence_end = False

                        if silence_end or max_length:
                            if max_length and not silence_end:
                                print(f"[TWILIO-CALL] {self.session_id}: max turn length ({self._chunk_count} chunks), processing mid-speech")
                            await self._process_accumulated_audio()
                            self._has_speech = False
                            self._silence_chunks = 0
                            if self._turn_detector:
                                self._turn_detector.reset()

                elif event == "mark":
                    mark_name = data.get("mark", {}).get("name", "")
                    print(f"[TWILIO-CALL] {self.session_id}: mark received: {mark_name}")

                elif event == "stop":
                    print(f"[TWILIO-CALL] {self.session_id}: stream stopped")
                    if self._audio_chunks:
                        # Process final audio synchronously so TTS can still
                        # stream before the WebSocket tears down
                        chunks = list(self._audio_chunks)
                        self._audio_chunks.clear()
                        self._chunk_count = 0
                        self._cancel_event = asyncio.Event()
                        await self._process_turn(chunks)
                    if self._active_task and not self._active_task.done():
                        try:
                            await asyncio.wait_for(self._active_task, timeout=30)
                        except asyncio.TimeoutError:
                            pass
                    await self._finalize()
                    break

        except Exception as e:
            logger.error("TwilioMediaSession %s error: %s", self.session_id, e)
        finally:
            if not self._finalized:
                await self._finalize()

    async def _deliver_opening(self, is_redelivery: bool = False):
        """Stream the opening line to the caller.

        Called once when the call connects, and again if the first delivery
        was consumed by a carrier phone assistant. On re-delivery the
        conversation turn is NOT re-recorded (the opening text is already
        in memory from the first delivery).

        Priority chain:
          1. Pre-synthesized mulaw from Redis (zero latency)
          2. Live Azure TTS (fast, <2s)
          3. Live XTTS synthesis (3-8s delay)
        """
        # Inbound calls: TwiML already has <Say> before <Stream> — do not stream a duplicate greeting.
        if self._call_context.get("stream_profile") == "inbound_voice" and not is_redelivery:
            self._opening_delivered = True
            # Polly greeting already opened the conversation; keep attunement state aligned.
            self._conversation.conversation_opened = True
            print(
                f"[TWILIO-CALL] {self.session_id}: skip stream opening "
                "(inbound_voice — TwiML Say already played)"
            )
            return

        opening = self._call_context.get("opening_line", "")
        if not opening:
            name = self._call_context.get("name", "there")
            if name and name != "there":
                first = name.split()[0]
                if "@" in first or first == first.lower() and len(first) > 10:
                    name = "there"
                else:
                    name = first.capitalize()
            opening = f"Hey {name}, it's Little Nate. Just wanted to check in — how are you doing?"
            self._call_context["opening_line"] = opening
            print(f"[TWILIO-CALL] {self.session_id}: generated fallback opening: {opening}")

        self._opening_delivered = True
        tag = "re-delivering" if is_redelivery else "delivering"
        print(f"[TWILIO-CALL] {self.session_id}: {tag} opening: {opening[:60]}...")

        self._is_speaking = True
        try:
            presynth_b64 = self._call_context.get("presynthesized_opening_mulaw")
            if presynth_b64:
                mulaw_data = base64.b64decode(presynth_b64)
                print(f"[TWILIO-CALL] {self.session_id}: streaming pre-synthesized audio ({len(mulaw_data)} bytes mulaw)")
                await self._stream_raw_mulaw(mulaw_data)
            else:
                print(f"[TWILIO-CALL] {self.session_id}: no pre-synth, synthesizing live...")
                audio_bytes = await self._synthesize_rissc(opening, "grounded", tts_speed=1.0)
                if audio_bytes:
                    print(f"[TWILIO-CALL] {self.session_id}: live TTS produced {len(audio_bytes)} bytes")
                    await self._stream_mulaw_to_twilio(audio_bytes)
                else:
                    print(f"[TWILIO-CALL] {self.session_id}: TTS returned no audio")
                    return

            if not is_redelivery:
                from app.services.relational_attunement import TurnMemory
                nate_turn = TurnMemory(
                    role="nate",
                    text=opening,
                    timestamp=time.time(),
                    felt_sense="grounded",
                    relational_mode="relational",
                )
                self._conversation.add_turn(nate_turn)

            self._conversation.conversation_opened = True
            print(f"[TWILIO-CALL] {self.session_id}: opening {tag} successfully")

        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: opening delivery failed: {e}")
            logger.warning("TwilioMediaSession opening delivery failed: %s", e)
        finally:
            self._is_speaking = False
            if self._bc_engine:
                self._bc_engine.enable()

    async def _stream_raw_mulaw(self, mulaw_data: bytes):
        """Stream pre-converted mulaw directly to Twilio at real-time rate.

        Twilio expects ~20ms of audio per chunk (160 bytes at 8kHz mulaw).
        Blasting all chunks instantly causes Twilio to drop or buffer them.
        We pace delivery and insert mark events so Twilio can sync playback.
        """
        chunk_size = 160
        total_chunks = (len(mulaw_data) + chunk_size - 1) // chunk_size
        print(f"[TWILIO-CALL] {self.session_id}: streaming {len(mulaw_data)} bytes ({total_chunks} chunks) at real-time pace")

        if not self._stream_sid:
            print(f"[TWILIO-CALL] {self.session_id}: WARNING — no stream_sid, audio will not play")
            return

        for i in range(0, len(mulaw_data), chunk_size):
            if self._cancel_event.is_set():
                return
            chunk = mulaw_data[i:i + chunk_size]
            media_msg = {
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {
                    "payload": base64.b64encode(chunk).decode(),
                },
            }
            try:
                await self.ws.send_text(json.dumps(media_msg))
            except Exception:
                return

            # Pace at real-time: 160 bytes = 20ms of 8kHz mulaw
            # Send in bursts of 10 chunks (200ms) with a small sleep between
            # to avoid overloading Twilio's buffer while keeping latency low
            chunk_index = i // chunk_size
            if chunk_index % 10 == 9:
                await asyncio.sleep(0.18)

        # Send a mark so Twilio signals when playback finishes
        try:
            await self.ws.send_text(json.dumps({
                "event": "mark",
                "streamSid": self._stream_sid,
                "mark": {"name": "opening_complete"},
            }))
        except Exception:
            pass

    async def _process_accumulated_audio(self):
        """Convert accumulated mulaw chunks to PCM, transcribe, and respond.

        If Nate is currently generating or speaking a response, the new audio
        is queued instead of cancelling him. After his turn completes, the
        queued audio is processed automatically.
        """
        if not self._audio_chunks:
            return

        chunks = list(self._audio_chunks)
        self._audio_chunks.clear()
        self._chunk_count = 0

        if self._active_task and not self._active_task.done():
            self._pending_chunks.extend(chunks)
            print(f"[TWILIO-CALL] {self.session_id}: queued {len(chunks)} chunks (Nate is responding)")
            return

        self._cancel_event = asyncio.Event()
        self._active_task = asyncio.create_task(self._process_turn(chunks))

    async def _load_user_memory(self):
        """Load conversation history + crystals from PG/Vectorize once per call."""
        if self._user_memory_context is not None:
            return
        username = self._call_context.get("username", "")
        if not username:
            self._user_memory_context = ""
            return
        db_pool = getattr(self._app_state, "db_pool", None)
        parts: list = []
        try:
            if db_pool:
                async with db_pool.acquire() as conn:
                    profile = await conn.fetchrow(
                        "SELECT profile_data->>'name' AS name, "
                        "profile_data->>'tier' AS tier "
                        "FROM users WHERE username = $1", username,
                    )
                    if profile and profile.get("name"):
                        self._user_name = profile["name"]
                        parts.append(f"[CALLER] Name: {self._user_name}")
                    rows = await conn.fetch(
                        "SELECT user_text, ai_text, created_at "
                        "FROM conversation_history "
                        "WHERE user_id = $1 "
                        "ORDER BY created_at DESC LIMIT 10",
                        username,
                    )
                    if rows:
                        parts.append("[RECENT CONVERSATION HISTORY]")
                        for r in reversed(rows):
                            if r["user_text"]:
                                parts.append(f"User: {r['user_text'][:200]}")
                            if r["ai_text"]:
                                parts.append(f"Nate: {r['ai_text'][:200]}")
        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: memory PG load failed: {e}")
        try:
            from app.services.vectorize_service import semantic_search_all
            if username:
                results = await semantic_search_all(
                    f"conversation with {username}", username, top_k=5,
                )
                crystals = []
                for matches in results.values():
                    crystals.extend(matches)
                if crystals:
                    parts.append("[YOUR KNOWLEDGE ABOUT THIS PERSON]")
                    for c in crystals[:5]:
                        text = c.get("metadata", {}).get("crystal_text", "") or c.get("text", "")
                        if text:
                            parts.append(f"- {text[:250]}")
        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: crystal recall failed: {e}")
        self._user_memory_context = "\n".join(parts) if parts else ""
        if self._user_memory_context:
            print(f"[TWILIO-CALL] {self.session_id}: loaded memory ({len(parts)} fragments, {len(self._user_memory_context)} chars)")

    async def _process_turn(self, mulaw_chunks: list):
        """Full pipeline: mulaw -> STT -> Helix -> inference -> TTS -> mulaw.

        The 10-Dimension Coherence Helix runs every turn, feeding:
        - Dynamic max_tokens (keeps Nate concise)
        - TTS speed matched to caller WPM
        - System prompt injection for texture/trauma/CEE awareness
        - Silence threshold adapted to clinical state
        """
        from app.services.relational_attunement import (
            TurnMemory,
            assess_relational_mode,
            build_relational_system_prompt,
            build_conversation_context,
            detect_silence_opportunity,
        )
        from app.services.audio_conversion import mulaw_chunks_to_whisper_wav

        start = time.time()
        self._turn_start_time = start

        await self._load_user_memory()

        try:
            # 1. Convert mulaw chunks -> WAV for Whisper
            wav_data = mulaw_chunks_to_whisper_wav(mulaw_chunks)
            print(f"[TWILIO-CALL] {self.session_id}: processing {len(mulaw_chunks)} chunks ({len(wav_data)} bytes WAV)")

            # 2. Voice biometrics from raw audio (Slice 0: honor opt-out)
            try:
                extractor = getattr(self._app_state, "voice_biometric_extractor", None)
                if extractor and len(wav_data) > 1000:
                    _bio_disabled = False
                    _uname = (self._call_context.get("username") or "").strip()
                    if _uname:
                        try:
                            from app.services.biometrics_consent import is_biometrics_disabled

                            _pool = getattr(self._app_state, "db_pool", None)
                            _bio_disabled = await is_biometrics_disabled(_uname, _pool)
                        except Exception:
                            _bio_disabled = False
                    if not _bio_disabled:
                        self._client_biometrics = extractor.process_audio_chunk(wav_data)
            except Exception:
                pass

            # 3. STT
            transcript = await self._stt(wav_data)
            if not transcript or len(transcript.strip()) < 3:
                print(f"[TWILIO-CALL] {self.session_id}: STT empty/short, skipping")
                return

            # Measure caller's WPM from transcript word count and audio duration
            audio_duration_s = len(b"".join(mulaw_chunks)) / 8000.0
            word_count = len(transcript.split())
            if audio_duration_s > 0.5 and word_count >= 2:
                measured_wpm = (word_count / audio_duration_s) * 60.0
                measured_wpm = max(60.0, min(250.0, measured_wpm))
                self._wpm_samples.append(measured_wpm)
                if len(self._wpm_samples) > 5:
                    self._wpm_samples = self._wpm_samples[-5:]
                self._caller_wpm = sum(self._wpm_samples) / len(self._wpm_samples)

            print(f"[TWILIO-CALL] {self.session_id}: >>> HEARD: \"{transcript}\" (WPM={self._caller_wpm:.0f})")

            # 3b. Carrier greeting filter
            user_turns_so_far = self._conversation.user_turn_count()
            if not self._carrier_passed and user_turns_so_far < self._carrier_check_window:
                if _is_carrier_greeting(transcript):
                    print(f"[TWILIO-CALL] {self.session_id}: 📞 CARRIER GREETING detected, ignoring: \"{transcript[:80]}\"")
                    return
                else:
                    self._carrier_passed = True
                    if self._opening_delivered and user_turns_so_far == 0 and word_count < 5:
                        print(f"[TWILIO-CALL] {self.session_id}: 👋 Short greeting — re-delivering opening")
                        await self._deliver_opening(is_redelivery=True)
                        return
                    elif self._opening_delivered and user_turns_so_far == 0:
                        print(f"[TWILIO-CALL] {self.session_id}: 👋 Real person detected (long reply)")
            else:
                self._carrier_passed = True

            # 4. Get inference engine
            inference = getattr(self._app_state, "littlenate_inference", None)
            if not inference:
                print(f"[TWILIO-CALL] {self.session_id}: ❌ inference not available")
                return

            # 5. Quantum coherence (non-blocking)
            current_coherence = 0.5
            current_felt_sense = "grounded"
            quantum = getattr(self._app_state, "quantum_cognition_engine", None)
            if quantum:
                try:
                    qeval = await quantum.evaluate(transcript)
                    qs = qeval.get("quantum_self", {})
                    current_coherence = qs.get("c_quantum_self", 0.5)
                    current_felt_sense = qs.get("felt_sense", "grounded")
                except Exception:
                    pass

            if self._caller_wpm > 0:
                self._client_biometrics["speech_rate"] = self._caller_wpm

            # 6. Record user turn in memory
            user_turn = TurnMemory(
                role="user",
                text=transcript,
                timestamp=time.time(),
                felt_sense=current_felt_sense,
                c_quantum_self=current_coherence,
                voice_stress=self._client_biometrics.get("voice_stress_index", 0.0),
                voice_warmth=self._client_biometrics.get("voice_warmth_index", 0.0),
            )
            self._conversation.add_turn(user_turn)

            # ── 7. COHERENCE HELIX — 10 dimensions ───────────────────────
            stt_end = time.time()
            response_gap_ms = (stt_end - self._turn_start_time) * 1000

            helix_output = self._helix.update(
                caller_transcript=transcript,
                nate_response="",
                caller_wpm=self._caller_wpm,
                response_gap_ms=response_gap_ms,
                nate_audio_duration_s=0.0,
                caller_audio_duration_s=audio_duration_s,
                voice_biometrics=self._client_biometrics,
                conversation_turns=self._conversation.turns,
            )
            self._last_helix_output = helix_output

            # Helix-driven silence threshold
            self._SILENCE_THRESHOLD = helix_output.recommended_silence_threshold

            # 8. Relational attunement
            mode, mode_confidence = assess_relational_mode(
                self._conversation,
                current_felt_sense,
                current_coherence,
                self._client_biometrics or None,
            )

            conversation_context = build_conversation_context(self._conversation, max_turns=6)
            relational_prompt = build_relational_system_prompt(
                self._conversation, mode, mode_confidence,
                current_felt_sense, domain="coaching",
            )
            silence_spark = detect_silence_opportunity(self._conversation)

            if self._user_memory_context:
                relational_prompt += "\n\n" + self._user_memory_context
            if self._user_name:
                relational_prompt += f"\n\nThe caller's name is {self._user_name}. Use it naturally."

            if helix_output.system_prompt_injection:
                relational_prompt += "\n\n" + helix_output.system_prompt_injection

            # SOVEREIGN-VOICE: inject billing context (crystal recall / extension detection)
            if self._billing_context_addon:
                relational_prompt += "\n\n" + self._billing_context_addon

            # Patent 11: Short response lever -- triples effective concurrent capacity
            relational_prompt += (
                "\n\nYou are on a live phone call. Keep every response to 2-4 sentences maximum. "
                "Speak naturally and conversationally. Do not monologue. Pause and let the client react."
            )

            # Patent 11: Neural Mirror prompt injection
            if self._neural_mirror:
                nm_injection = self._neural_mirror.get_prompt_injection()
                if nm_injection:
                    relational_prompt += "\n\n" + nm_injection

            max_tok = helix_output.recommended_max_tokens
            h = helix_output
            print(
                f"[TWILIO-CALL] {self.session_id}: 🌀 HELIX: "
                f"tokens={max_tok}, tts_speed={h.recommended_tts_speed}, "
                f"texture={h.relational.texture}, trauma={h.clinical.trauma_detected}, "
                f"cee={h.clinical.cee_recommended}, "
                f"pacing={h.pacing.pacing_coherence:.2f}, "
                f"c_emo={h.clinical.present_c_emo:.2f}, "
                f"nate_self={h.relational.nate_self_coherence:.2f}, "
                f"turn_ratio={h.pacing.turn_ratio:.2f}"
            )

            # 9. Fast-path: direct Azure inference for phone
            print(f"[TWILIO-CALL] {self.session_id}: 🧠 generating (mode={mode}, tokens={max_tok})...")
            try:
                result = await asyncio.wait_for(
                    self._fast_azure_inference(
                        transcript, relational_prompt, conversation_context,
                        max_tok, silence_spark,
                    ),
                    timeout=8.0,
                )
            except asyncio.TimeoutError:
                print(f"[TWILIO-CALL] {self.session_id}: ⏱️ inference timed out (8s)")
                from app.services.littlenate_inference import InferenceResult
                result = InferenceResult(
                    text="That's a good point — let me think on that for a second. What else is on your mind?",
                    provider="timeout_fallback",
                )

            if self._cancel_event.is_set():
                return

            # SOVEREIGN-VOICE: strip billing markers before TTS
            if self._waiting_extension:
                raw = result.text
                if "[EXTEND_SESSION]" in raw:
                    self._extension_decision = "extend"
                    result.text = raw.replace("[EXTEND_SESSION]", "").strip()
                elif "[DECLINE_EXTENSION]" in raw:
                    self._extension_decision = "decline"
                    result.text = raw.replace("[DECLINE_EXTENSION]", "").strip()

            print(f"[TWILIO-CALL] {self.session_id}: <<< NATE: \"{result.text[:120]}\" (provider={result.provider}, {result.latency_ms}ms)")

            # 10. Record Nate's response in conversation memory
            nate_turn = TurnMemory(
                role="nate",
                text=result.text,
                timestamp=time.time(),
                felt_sense=result.felt_sense or current_felt_sense,
                c_quantum_self=result.c_quantum_self or current_coherence,
                relational_mode=mode,
            )
            self._conversation.add_turn(nate_turn)

            # 11. Synthesize TTS with helix-driven speed and stream to caller
            self._is_speaking = True
            if self._bc_engine:
                self._bc_engine.disable()
            tts_start = time.time()
            try:
                audio_bytes = await self._synthesize_rissc(
                    result.text,
                    result.felt_sense or current_felt_sense,
                    tts_speed=helix_output.recommended_tts_speed,
                )
                nate_audio_duration_s = 0.0
                if audio_bytes and not self._cancel_event.is_set():
                    nate_audio_duration_s = max(0.0, (len(audio_bytes) - 44) / 48000.0)
                    print(f"[TWILIO-CALL] {self.session_id}: 🔊 streaming {len(audio_bytes)} bytes TTS ({nate_audio_duration_s:.1f}s audio)")
                    await self._stream_mulaw_to_twilio(audio_bytes)
                    print(f"[TWILIO-CALL] {self.session_id}: ✅ response delivered")
                elif not audio_bytes:
                    print(f"[TWILIO-CALL] {self.session_id}: ⚠️ TTS returned no audio")
            finally:
                self._is_speaking = False
                if self._bc_engine:
                    self._bc_engine.enable()

            # Update helix with Nate's actual response data for next-turn accuracy
            self._helix.update(
                caller_transcript="",
                nate_response=result.text,
                caller_wpm=self._caller_wpm,
                response_gap_ms=response_gap_ms,
                nate_audio_duration_s=nate_audio_duration_s if 'nate_audio_duration_s' in dir() else 3.0,
                caller_audio_duration_s=audio_duration_s,
                voice_biometrics=self._client_biometrics,
            )

            elapsed = int((time.time() - start) * 1000)
            print(
                f"[TWILIO-CALL] {self.session_id}: turn complete ({elapsed}ms, "
                f"mode={mode}, coherence={current_coherence:.2f}, "
                f"rapport={self._conversation.rapport_score:.2f}, "
                f"helix_overall={helix_output.overall_coherence:.2f})"
            )

        except asyncio.CancelledError:
            self._is_speaking = False
            print(f"[TWILIO-CALL] {self.session_id}: turn cancelled")
        except Exception as e:
            self._is_speaking = False
            print(f"[TWILIO-CALL] {self.session_id}: ❌ turn failed: {e}")
            logger.error("TwilioMediaSession %s: turn failed: %s", self.session_id, e, exc_info=True)

        # After turn completes, process queued audio
        if self._pending_chunks:
            queued = list(self._pending_chunks)
            self._pending_chunks.clear()
            print(f"[TWILIO-CALL] {self.session_id}: processing {len(queued)} queued chunks")
            self._cancel_event = asyncio.Event()
            self._active_task = asyncio.create_task(self._process_turn(queued))

    def _compute_latency_budget(
        self,
        mode: str,
        posture: str,
        conversation,
    ) -> tuple:
        """Adaptive latency routing for phone calls.

        Strategy: burn Azure credits early to build rapport (speed = engagement),
        then shift to sovereign once rapport is established (cost efficiency).

        Returns (tier, max_tokens, reason).

        Rapport phases:
          < 0.45  → Building rapport: every turn must be fast (Azure)
          0.45-0.65 → Rapport growing: fast on lean-in, patient on lean-back
          > 0.65  → Rapport established: sovereign is fine, save Azure costs
        """
        turns = conversation.user_turn_count()
        rapport = conversation.rapport_score
        last_user_words = conversation.last_user_response_length()

        # Opening turn: ALWAYS fastest — first impression is everything
        if turns == 0:
            return ("realtime", 60, "opening_fast")

        # Therapeutic mode: patience IS the tool, sovereign is fine
        if mode == "therapeutic":
            return ("clinical", 100, "therapeutic_patient")

        # ── Rapport building phase (rapport < 0.45) ──────────────────
        # Speed drives engagement. Every response must be snappy.
        if rapport < 0.45:
            return ("realtime", 80, f"rapport_building_{rapport:.2f}")

        # ── Rapport growing (0.45 - 0.65) ────────────────────────────
        # Blend: fast when leaning in or sparking, patient when leaning back
        if rapport < 0.65:
            if posture in ("lean_in", "spark"):
                return ("realtime", 80, f"growing_lean_in_{rapport:.2f}")
            if posture == "lean_back":
                return ("clinical", 60, f"growing_lean_back_{rapport:.2f}")
            if last_user_words > 30:
                return ("clinical", 100, f"growing_thoughtful_{rapport:.2f}")
            return ("realtime", 80, f"growing_default_{rapport:.2f}")

        # ── Rapport established (> 0.65) ─────────────────────────────
        # They trust Nate. Slight pauses feel natural, not awkward.
        # Save Azure costs — sovereign quality is fine here.
        if posture in ("lean_in", "spark"):
            # Re-engage moments still benefit from speed even at high rapport
            return ("realtime", 80, f"established_re_engage_{rapport:.2f}")
        if last_user_words > 30:
            return ("clinical", 120, f"established_thoughtful_{rapport:.2f}")
        return ("clinical", 80, f"established_sovereign_{rapport:.2f}")

    async def _fast_azure_inference(
        self, transcript: str, system_prompt: str,
        conversation_context: str, max_tokens: int,
        silence_spark: Optional[str],
    ):
        """Direct Azure inference for phone calls — no router, no fallback chain."""
        import aiohttp
        from app.services.littlenate_inference import InferenceResult

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key = os.environ.get("AZURE_API_KEY", "")
        deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

        if not endpoint or not api_key:
            raise RuntimeError("Azure not configured")

        # Hard brevity constraint baked into every phone call
        phone_system = (
            system_prompt + "\n\n"
            "PHONE CALL RULES (NON-NEGOTIABLE):\n"
            "- You are on a live phone call. Respond in 1-2 SHORT sentences.\n"
            "- 15 words MAXIMUM per response.\n"
            "- Ask ONE question OR make ONE comment. Never both.\n"
            "- Sound natural like a real person, not an AI assistant.\n"
            "- LISTEN to what they actually said and respond to THAT specific thing.\n"
            "- Do NOT repeat yourself or give generic responses.\n"
        )

        messages = [{"role": "system", "content": phone_system}]
        user_content = ""
        if conversation_context:
            user_content += conversation_context + "\n"
        if silence_spark:
            user_content += f"[CONVERSATION SPARK] {silence_spark}\n"
        user_content += transcript
        messages.append({"role": "user", "content": user_content})

        url = (
            f"https://{endpoint}/openai/deployments/"
            f"{deployment}/chat/completions?api-version=2024-06-01"
        )

        start = time.time()
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json={
                "messages": messages,
                "temperature": 0.7,
                "max_completion_tokens": max_tokens,
            }, headers={"api-key": api_key},
                timeout=aiohttp.ClientTimeout(total=7)) as resp:

                if resp.status != 200:
                    body = await resp.text()
                    print(f"[TWILIO-CALL] {self.session_id}: Azure inference {resp.status}: {body[:150]}")
                    raise RuntimeError(f"Azure returned {resp.status}")

                data = await resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                latency = int((time.time() - start) * 1000)

                return InferenceResult(
                    text=text,
                    provider="azure",
                    tokens_used=usage.get("total_tokens", 0),
                    latency_ms=latency,
                )

    async def _stt(self, audio_data: bytes) -> Optional[str]:
        """Transcribe audio via Sovereign Whisper."""
        try:
            from app.services.sovereign_whisper import transcribe
            result = await transcribe(audio_data)
            return result.get("text", "").strip() or None
        except Exception as e:
            logger.warning("TwilioMediaSession STT failed: %s", e)
            return None

    async def _synthesize_rissc(self, text: str, felt_sense: str, tts_speed: float = 1.05) -> Optional[bytes]:
        """Synthesize speech for phone calls.

        Priority: Azure TTS (fast, <2s) → XTTS (voice clone, 5-15s) → Edge TTS.
        Phone calls need speed over perfect voice cloning.
        tts_speed is driven by the Coherence Helix WPM matching.
        """
        # Azure TTS — fastest path for phone calls
        try:
            audio = await self._azure_tts(text, speed=tts_speed)
            if audio:
                return audio
        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: Azure TTS failed: {e}")

        # XTTS fallback — voice clone but slower (3s timeout for phone)
        biometrics = self._client_biometrics or None
        try:
            from app.services.sovereign_tts import synthesize as xtts_synthesize
            from app.services.rissc_voice import get_rissc_params, rissc_to_dict
            rissc = get_rissc_params(felt_sense, biometrics)
            audio = await asyncio.wait_for(
                xtts_synthesize(
                    text,
                    rissc_params=rissc_to_dict(rissc),
                    speed=rissc.speed,
                    temperature=rissc.temperature,
                    top_p=rissc.top_p,
                    top_k=rissc.top_k,
                    repetition_penalty=rissc.repetition_penalty,
                ),
                timeout=5.0,
            )
            if audio:
                return audio
        except asyncio.TimeoutError:
            print(f"[TWILIO-CALL] {self.session_id}: XTTS timed out (5s), skipping")
        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: XTTS failed: {e}")

        return None

    async def _azure_tts(self, text: str, speed: float = 1.05) -> Optional[bytes]:
        """Synthesize speech via Azure OpenAI TTS (gpt-4o-mini-tts).

        Speed is dynamically matched to the caller's WPM by the Coherence Helix.
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
            "instructions": "Speak as a warm, confident young man in his late 20s. "
                "Natural and conversational — like talking to a trusted older brother. "
                "Relaxed pace, occasional light laugh energy. Never robotic or clinical.",
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
                print(f"[TWILIO-CALL] {self.session_id}: Azure TTS: {len(resp.content)} bytes WAV")
                return resp.content

            print(f"[TWILIO-CALL] {self.session_id}: Azure TTS returned {resp.status_code}: {resp.text[:100]}")
            return None
        except Exception as e:
            print(f"[TWILIO-CALL] {self.session_id}: Azure TTS error: {e}")
            return None

    async def _stream_mulaw_to_twilio(self, wav_audio: bytes):
        """Convert WAV audio to mulaw 8kHz and stream to Twilio at real-time rate."""
        from app.services.audio_conversion import wav_to_mulaw8k

        try:
            mulaw_data = wav_to_mulaw8k(wav_audio)
        except Exception as e:
            logger.warning("Audio conversion to mulaw failed: %s", e)
            return

        if not mulaw_data:
            return

        await self._stream_raw_mulaw(mulaw_data)

    async def _play_wrap_up_warning(self, text: str):
        """Spoken ~2 minutes before server-side max call duration."""
        if self._call_context.get("_duration_warning_played"):
            return
        self._call_context["_duration_warning_played"] = True
        self._is_speaking = True
        try:
            audio_bytes = await self._synthesize_rissc(text, "grounded", tts_speed=0.95)
            if audio_bytes:
                await self._stream_mulaw_to_twilio(audio_bytes)
        except Exception as e:
            logger.warning("TwilioMediaSession wrap-up TTS failed: %s", e)
        finally:
            self._is_speaking = False

    async def _hangup_twilio_call(self, call_sid: str) -> None:
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if not account_sid or not token or not call_sid:
            return

        def _complete():
            from twilio.rest import Client

            Client(account_sid, token).calls(call_sid).update(status="completed")

        try:
            await asyncio.to_thread(_complete)
            print(f"[TWILIO-CALL] {self.session_id}: requested Twilio hangup call_sid={call_sid}")
        except Exception as e:
            logger.warning("Twilio hangup failed: %s", e)

    async def _enforce_max_call_duration(self):
        """Sleep until wrap-up window, speak wrap-up, then hard hangup via Twilio REST."""
        from app.services.voice_metering import (
            VOICE_CALL_WRAP_UP_MESSAGE,
            max_single_call_seconds,
        )

        raw = self._call_context.get("max_call_seconds")
        if raw is None:
            max_sec = max_single_call_seconds(self._call_context.get("tier"))
        else:
            try:
                max_sec = int(raw)
            except (TypeError, ValueError):
                max_sec = max_single_call_seconds(self._call_context.get("tier"))
        if max_sec <= 0:
            return

        call_sid = (self._call_context.get("twilio_call_sid") or "").strip()
        warn_after = max(0, max_sec - 120)
        remaining = max_sec - warn_after

        try:
            await asyncio.sleep(warn_after)
            if self._finalized:
                return
            await self._play_wrap_up_warning(VOICE_CALL_WRAP_UP_MESSAGE)
            await asyncio.sleep(remaining)
            if self._finalized:
                return
            if call_sid:
                await self._hangup_twilio_call(call_sid)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("TwilioMediaSession duration enforcement: %s", e)

    # SOVEREIGN-VOICE: prepaid billing loop -----------------------------------------------
    async def _voice_billing_loop(self):
        """Deduct balance every 10 seconds; offer extensions at low balance."""
        try:
            pool = getattr(self._app_state, "db_pool", None)
            billing = getattr(self._app_state, "voice_billing", None)
            if not pool or not billing or not self._voice_billing_user_id:
                logger.warning("Voice billing loop: missing pool/billing/user_id, exiting")
                return

            while not self._cancel_event.is_set():
                await asyncio.sleep(10)
                if self._cancel_event.is_set():
                    break
                if self._waiting_extension:
                    continue

                try:
                    status = await billing.deduct_seconds(
                        self._voice_billing_user_id,
                        self._voice_billing_session_id,
                        10,
                    )
                    self._total_billed_seconds += 10

                    if status.get("is_zero"):
                        self._server_initiated_hangup = True
                        self._billing_context_addon = (
                            "\n\nThe client has run out of prepaid minutes. "
                            "Say: 'We've reached the end of your prepaid time for today. "
                            "I'll send you a text with a link to add more minutes whenever you're ready. "
                            "Take care of yourself.' Then end naturally."
                        )
                        from app.services.voice_notifications import send_zero_balance_decline_sms
                        phone = await billing.get_phone_for_user(self._voice_billing_user_id)
                        if phone:
                            asyncio.create_task(send_zero_balance_decline_sms(phone))
                        await asyncio.sleep(15)
                        break

                    remaining = status.get("remaining", 999)

                    if remaining <= 300 and not self._waiting_extension:
                        now = time.time()
                        if now - self._last_low_balance_alert > 3600:
                            self._last_low_balance_alert = now
                            self._waiting_extension = True
                            mins_left = remaining // 60
                            self._billing_context_addon = (
                                f"\n\nThe client has about {mins_left} minutes left in their prepaid block. "
                                "Gently let them know and ask if they'd like to extend their session with another "
                                "block of minutes. If they say yes, respond with [EXTEND_SESSION] at the end. "
                                "If they decline, respond with [DECLINE_EXTENSION] at the end. "
                                "Do NOT speak these markers aloud — they are instructions for the system."
                            )

                except Exception as e:
                    logger.warning("Voice billing loop deduction error: %s", e)

                if self._waiting_extension and self._extension_decision:
                    if self._extension_decision == "extend":
                        try:
                            charged = await billing.extend_session(
                                self._voice_billing_user_id,
                                self._voice_billing_session_id,
                            )
                            if charged:
                                self._billing_context_addon = (
                                    "\n\nThe extension has been charged. Let the client know "
                                    "their session has been extended and continue the conversation naturally."
                                )
                            else:
                                self._billing_context_addon = (
                                    "\n\nThe extension charge failed. Let the client know gently "
                                    "and continue with the remaining time."
                                )
                        except Exception as e:
                            logger.warning("Voice billing extension error: %s", e)
                    self._waiting_extension = False
                    self._extension_decision = None

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Voice billing loop fatal error: %s", e)

    async def _finalize(self):
        """Store conversation and log activity after call ends."""
        if self._finalized:
            return
        self._finalized = True

        if self._duration_task and not self._duration_task.done():
            self._duration_task.cancel()
            try:
                await self._duration_task
            except asyncio.CancelledError:
                pass

        # SOVEREIGN-VOICE: cancel billing loop
        if self._billing_task and not self._billing_task.done():
            self._billing_task.cancel()
            try:
                await self._billing_task
            except asyncio.CancelledError:
                pass

        db_pool = getattr(self._app_state, "db_pool", None)
        billing = getattr(self._app_state, "voice_billing", None)

        # SOVEREIGN-VOICE: handle PAUSED state vs final end
        if (
            self._billing_active
            and billing
            and self._voice_billing_session_id
            and not self._server_initiated_hangup
            and not self._admin_bypass
        ):
            try:
                await billing.pause_session(self._voice_billing_session_id)
                phone = await billing.get_phone_for_user(self._voice_billing_user_id)
                if phone:
                    now = time.time()
                    if now - self._last_recovery_sms > 120:
                        self._last_recovery_sms = now
                        from app.services.voice_notifications import send_call_drop_recovery_sms
                        asyncio.create_task(send_call_drop_recovery_sms(phone))
                logger.info(
                    "TwilioMediaSession %s: PAUSED (call drop), session=%s",
                    self.session_id, self._voice_billing_session_id,
                )
            except Exception as e:
                logger.warning("Voice billing pause error: %s", e)

        elif self._billing_active and billing and self._voice_billing_session_id:
            try:
                await billing.end_session(
                    self._voice_billing_session_id,
                    end_reason="completed",
                )
            except Exception as e:
                logger.warning("Voice billing end_session error: %s", e)

        # SOVEREIGN-VOICE: crystallize session via LLM
        if (
            self._voice_billing_user_id
            and self._conversation.turns
            and db_pool
            and (self._server_initiated_hangup or self._admin_bypass)
        ):
            try:
                transcript_parts = []
                for turn in self._conversation.turns:
                    speaker = "Client" if turn.role == "user" else "Nate"
                    transcript_parts.append(f"{speaker}: {turn.text}")
                transcript = "\n".join(transcript_parts)

                lni = getattr(self._app_state, "littlenate_inference", None)
                if lni and len(transcript) > 50:
                    crystal_prompt = (
                        "Summarize this therapy session in 2-3 sentences. "
                        "Then list the main topics discussed (comma-separated). "
                        "Then describe the client's emotional state in 2-4 words.\n\n"
                        "Format your response exactly as:\n"
                        "SUMMARY: <summary>\n"
                        "TOPICS: <topics>\n"
                        "EMOTIONAL_STATE: <state>\n\n"
                        f"Transcript:\n{transcript[-4000:]}"
                    )
                    crystal_result = await lni.generate(
                        prompt=crystal_prompt,
                        system="You are a clinical summarizer.",
                        domain="clinical",
                        temperature=0.3,
                        max_tokens=300,
                        include_crystals=False,
                        include_helix=False,
                        include_quantum=False,
                    )
                    if crystal_result and crystal_result.text:
                        summary, topics, emo = "", "", ""
                        for line in crystal_result.text.strip().split("\n"):
                            if line.startswith("SUMMARY:"):
                                summary = line[8:].strip()
                            elif line.startswith("TOPICS:"):
                                topics = line[7:].strip()
                            elif line.startswith("EMOTIONAL_STATE:"):
                                emo = line[16:].strip()
                        if summary:
                            _vs_id = self._voice_billing_session_id or self.session_id
                            await db_pool.execute(
                                "INSERT INTO voice_crystals "
                                "(user_id, session_id, summary, topics, emotional_state) "
                                "VALUES ($1, $2, $3, $4, $5)",
                                self._voice_billing_user_id,
                                _vs_id,
                                summary[:500],
                                topics[:200],
                                emo[:100],
                            )
                            # Fix 6: embed voice crystal into Vectorize
                            try:
                                from app.services.vectorize_service import index_conversation
                                await index_conversation(
                                    user_id=self._voice_billing_user_id,
                                    record_id=f"voice_crystal_{_vs_id}",
                                    user_text=transcript[-2000:],
                                    ai_text=summary,
                                    session_id=_vs_id,
                                    timestamp=str(int(time.time())),
                                )
                            except Exception as _ve:
                                logger.debug("voice crystal vectorize upsert: %s", _ve)
            except Exception as e:
                logger.warning("Voice crystallization failed: %s", e)

        csid = (self._call_context.get("twilio_call_sid") or "").strip()
        if csid:
            try:
                from app.services.voice_capacity import release_voice_slot

                await release_voice_slot(csid)
            except Exception as e:
                logger.warning("release_voice_slot on finalize: %s", e)

        user_uuid = (self._call_context.get("user_uuid") or "").strip()
        if db_pool and user_uuid:
            try:
                from app.services.voice_metering import add_voice_minutes

                started = self._voice_stream_started_at
                elapsed = max(0.0, time.time() - started) if started else 0.0
                minutes = elapsed / 60.0
                if minutes > 0.05:
                    await add_voice_minutes(db_pool, user_uuid, minutes)
            except Exception as e:
                logger.warning("add_voice_minutes on finalize: %s", e)

        # Patent 11: finalize Neural Mirror session and store EEG trace
        if self._neural_mirror and db_pool:
            try:
                nm_summary = self._neural_mirror.finalize()
                if nm_summary.get("n_samples", 0) > 0:
                    import json as _json
                    session_uuid = None
                    try:
                        session_uuid = uuid.UUID(self.session_id)
                    except (ValueError, AttributeError):
                        pass
                    await db_pool.execute(
                        "INSERT INTO virtual_eeg_traces "
                        "(user_id, session_id, nevedal_factors, tunneling_events, "
                        "duration_seconds, created_at) "
                        "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, NOW())",
                        self._voice_billing_user_id,
                        session_uuid,
                        _json.dumps(nm_summary.get("mean_nevedal_factors", {})),
                        _json.dumps(nm_summary.get("tunneling_events", [])),
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
                            self._voice_billing_user_id,
                            _json.dumps(fp_data.get("mean_vector")),
                            fp_data.get("n_samples", 0),
                            True,
                        )
            except Exception as e:
                logger.debug("Neural Mirror finalize: %s", e)

        username = self._call_context.get("username", "unknown")
        call_id = self._call_context.get("call_id", "")

        # Store conversation in conversation_history
        if db_pool and self._conversation.turns:
            try:
                async with db_pool.acquire() as conn:
                    for turn in self._conversation.turns:
                        if turn.role == "user":
                            user_text = turn.text
                            # Find the next nate response
                            nate_text = ""
                            idx = self._conversation.turns.index(turn)
                            for nt in self._conversation.turns[idx + 1:]:
                                if nt.role == "nate":
                                    nate_text = nt.text
                                    break
                            if user_text:
                                await conn.execute("""
                                    INSERT INTO conversation_history
                                        (user_id, user_text, ai_text, created_at)
                                    VALUES ($1, $2, $3, to_timestamp($4))
                                    ON CONFLICT DO NOTHING
                                """, username, user_text, nate_text, turn.timestamp)

                    # Build helix summary for call log
                    helix_summary = {}
                    if self._last_helix_output:
                        helix_summary = self._last_helix_output.to_dict()
                    nate_reflection = self._helix.get_nate_self_summary()

                    await conn.execute("""
                        INSERT INTO skyeye_activity (platform, type, content, created_at)
                        VALUES ('voice', 'nate_checkin_call', $1, NOW())
                    """, json.dumps({
                        "username": username,
                        "call_id": call_id,
                        "turns": len(self._conversation.turns),
                        "final_mode": self._conversation.relational_mode,
                        "rapport_score": round(self._conversation.rapport_score, 3),
                        "coherence_trend": self._conversation.coherence_trend(),
                        "helix": helix_summary,
                        "nate_self_reflection": nate_reflection,
                    }))

            except Exception as e:
                logger.error("TwilioMediaSession finalize DB error: %s", e)

        logger.info(
            "TwilioMediaSession %s finalized: %d turns, mode=%s, rapport=%.2f",
            self.session_id,
            len(self._conversation.turns),
            self._conversation.relational_mode,
            self._conversation.rapport_score,
        )


class LittleNateRealtime:
    """Manager for all active realtime sessions."""

    def __init__(self, app_state=None):
        self._app_state = app_state
        self._sessions: Dict[str, RealtimeSession] = {}

    def bind(self, app_state):
        self._app_state = app_state

    async def create_session(self, websocket) -> RealtimeSession:
        session_id = f"sess_{uuid.uuid4().hex[:16]}"
        session = RealtimeSession(session_id, websocket, self._app_state)
        self._sessions[session_id] = session

        await session._send({
            "type": "session.created",
            "session": {"id": session_id, "model": "littlenate-1.0-realtime"},
        })

        return session

    async def create_twilio_session(
        self,
        websocket,
        call_context: Optional[Dict] = None,
    ) -> TwilioMediaSession:
        """Create a TwilioMediaSession for phone-based conversations."""
        session_id = f"twilio_{uuid.uuid4().hex[:12]}"
        session = TwilioMediaSession(
            session_id, websocket, self._app_state,
            call_context=call_context,
        )
        self._sessions[session_id] = session
        return session

    def remove_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    async def create_family_session(
        self,
        websocket,
        family_members: list,
    ) -> RealtimeSession:
        """
        Create a RealtimeSession wired for multi-participant MoQ delivery.
        Each family member gets a dedicated MoQ namespace so Nate can address
        them with individualized voice, context, and therapeutic direction
        simultaneously via Cloudflare's 302 edge locations.
        """
        session_id = f"family_{uuid.uuid4().hex[:12]}"
        session = RealtimeSession(session_id, websocket, self._app_state)
        self._sessions[session_id] = session

        _cf_moq = os.getenv("CLOUDFLARE_MOQ_ENDPOINT", "draft-14.cloudflare.mediaoverquic.com")
        moq_namespaces = {}
        for member in family_members:
            uid = member.get("user_id") or member.get("username", "unknown")
            ns = f"sanctuary/{session_id}/nate-voice-{uid}"
            moq_namespaces[uid] = ns

        session._moq_namespace = f"sanctuary/{session_id}/nate-voice-broadcast"

        await session._send({
            "type": "session.created",
            "session": {
                "id": session_id,
                "model": "littlenate-1.0-realtime",
                "family_mode": True,
                "moq": {
                    "endpoint": _cf_moq,
                    "protocol": "draft-14",
                    "broadcast_namespace": session._moq_namespace,
                    "member_namespaces": moq_namespaces,
                },
            },
        })

        return session

    def get_status(self) -> Dict[str, Any]:
        return {
            "active_sessions": len(self._sessions),
            "session_ids": list(self._sessions.keys()),
        }
