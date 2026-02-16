"""
SOVEREIGN SWARM — AI Modes for Little Nate
Four specialized AI operational modes per SC_06 specification.

Modes:
    TriCorder   — 30-second biometric baseline calibration + voice stress analysis
    Archivist   — Legacy builder for elderly/terminally ill, biography chapters
    Guardian    — Parental proxy summaries for minors (confidentiality-preserving)
    Supervisor  — Coach session analysis, empathy/technique grading

Each mode implements activate(), process(), and generate_output().
Integration points:
    - VoiceBiometricExtractor (nevedal_engine.py)
    - LegacyVaultService (legacy_vault.py)
    - Azure OpenAI (GPT-4o) for narrative generation
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID


# ─── Base AI Mode ────────────────────────────────────────────────────────────

class BaseAIMode(ABC):
    """Abstract base class for AI operational modes."""

    MODE_NAME: str = "base"

    def __init__(self, db_pool, azure_client=None):
        self.db_pool = db_pool
        self.azure_client = azure_client
        self._active = False
        self._session_id: Optional[UUID] = None

    @abstractmethod
    async def activate(self, session_id: UUID, **kwargs) -> Dict[str, Any]:
        """Activate this mode for a session."""
        ...

    @abstractmethod
    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Process incoming data through this mode."""
        ...

    @abstractmethod
    async def generate_output(self) -> Dict[str, Any]:
        """Generate the mode's final output/report."""
        ...

    def deactivate(self) -> Dict[str, Any]:
        """Deactivate this mode."""
        self._active = False
        self.reset()
        return {"mode": self.MODE_NAME, "status": "deactivated"}

    def reset(self) -> None:
        """Clear all per-session state to prevent data leaking between sessions.

        Subclasses should override to clear their own fields, calling super().reset().
        """
        self._active = False
        self._session_id = None


# ─── Tri-Corder Mode ────────────────────────────────────────────────────────

class TriCorderMode(BaseAIMode):
    """
    30-second biometric baseline calibration.
    Collects voice stress analysis, estimates resting HR, stress index.
    Produces a waveform visualization dataset.
    """

    MODE_NAME = "tri_corder"

    def __init__(self, db_pool, azure_client=None):
        super().__init__(db_pool, azure_client)
        self._baseline_samples: List[Dict[str, Any]] = []
        self._calibration_start: Optional[datetime] = None
        self._calibration_complete = False

    def reset(self) -> None:
        super().reset()
        self._baseline_samples = []
        self._calibration_start = None
        self._calibration_complete = False
        self._user_id = None

    async def activate(self, session_id: UUID, **kwargs) -> Dict[str, Any]:
        self.reset()
        self._active = True
        self._session_id = session_id
        self._user_id = kwargs.get("user_id")
        self._calibration_start = datetime.now(timezone.utc)
        return {
            "mode": self.MODE_NAME,
            "status": "calibrating",
            "message": "Please sit quietly for 30 seconds while Nate establishes your baseline...",
            "duration_seconds": 30,
        }

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept biometric samples during the 30-second calibration window.
        Expected data: {hrv, gsr, voice_stress, breathing_rate, timestamp}
        """
        if not self._active:
            return {"error": "Tri-Corder mode not active"}

        self._baseline_samples.append({
            "hrv": data.get("hrv", 0),
            "gsr": data.get("gsr", 0),
            "voice_stress": data.get("voice_stress", 0),
            "breathing_rate": data.get("breathing_rate", 0),
            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        })

        elapsed = (datetime.now(timezone.utc) - self._calibration_start).total_seconds()
        if elapsed >= 30 and not self._calibration_complete:
            self._calibration_complete = True
            return await self.generate_output()

        return {
            "mode": self.MODE_NAME,
            "status": "calibrating",
            "samples_collected": len(self._baseline_samples),
            "elapsed_seconds": round(elapsed, 1),
        }

    async def generate_output(self) -> Dict[str, Any]:
        """Compute baseline metrics from collected samples."""
        if not self._baseline_samples:
            return {"mode": self.MODE_NAME, "error": "No samples collected"}

        # Compute averages
        n = len(self._baseline_samples)
        avg_hrv = sum(s["hrv"] for s in self._baseline_samples) / n
        avg_gsr = sum(s["gsr"] for s in self._baseline_samples) / n
        avg_voice_stress = sum(s["voice_stress"] for s in self._baseline_samples) / n
        avg_breathing = sum(s["breathing_rate"] for s in self._baseline_samples) / n

        # Compute variance for stress index
        hrv_variance = sum((s["hrv"] - avg_hrv) ** 2 for s in self._baseline_samples) / max(n - 1, 1)

        # Stress index: higher GSR + higher voice stress + lower HRV variance → more stressed
        stress_index = min(1.0, max(0.0,
            (avg_voice_stress * 0.4) +
            (min(avg_gsr / 100, 1.0) * 0.3) +
            ((1.0 - min(math.sqrt(hrv_variance) / 50, 1.0)) * 0.3)
        ))

        # Estimated resting HR from HRV (simplified: HR ≈ 60000 / avg HRV ms)
        resting_hr = round(60000 / max(avg_hrv, 400)) if avg_hrv > 0 else 72

        # Waveform data for visualization
        waveform = [
            {"t": s["timestamp"], "hrv": s["hrv"], "gsr": s["gsr"]}
            for s in self._baseline_samples
        ]

        baseline = {
            "mode": self.MODE_NAME,
            "status": "complete",
            "baseline": {
                "avg_hrv_ms": round(avg_hrv, 1),
                "hrv_variance": round(hrv_variance, 2),
                "avg_gsr": round(avg_gsr, 2),
                "avg_voice_stress": round(avg_voice_stress, 3),
                "avg_breathing_rate": round(avg_breathing, 1),
                "resting_hr_estimate": resting_hr,
                "stress_index": round(stress_index, 3),
            },
            "waveform": waveform,
            "samples_collected": n,
            "calibrated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist baseline to nevedal_metrics
        if self.db_pool and self._session_id and self._user_id:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO nevedal_metrics
                            (session_id, user_id, c_emo, biometrics, cee_window)
                        VALUES ($1, $2, 0, $3, FALSE)""",
                        self._session_id,
                        self._user_id,
                        json.dumps({"tri_corder_baseline": baseline["baseline"]}),
                    )
            except Exception as e:
                print(f">>> [TRI-CORDER] Baseline persist error: {e}")

        return baseline


# ─── Archivist Mode ──────────────────────────────────────────────────────────

class ArchivistMode(BaseAIMode):
    """
    Legacy builder for elderly/terminally ill clients.
    Creates biography chapters with voice recordings and
    'Wisdom Memories' for the family Legacy Vault.
    """

    MODE_NAME = "archivist"

    def __init__(self, db_pool, azure_client=None):
        super().__init__(db_pool, azure_client)
        self._user_id: Optional[UUID] = None
        self._family_id: Optional[UUID] = None
        self._chapters: List[Dict[str, Any]] = []
        self._current_chapter: Dict[str, Any] = {}

    def reset(self) -> None:
        super().reset()
        self._user_id = None
        self._family_id = None
        self._chapters = []
        self._current_chapter = {}

    async def activate(self, session_id: UUID, **kwargs) -> Dict[str, Any]:
        self.reset()
        self._active = True
        self._session_id = session_id
        self._user_id = kwargs.get("user_id")
        self._family_id = kwargs.get("family_id")
        self._current_chapter = {
            "number": 1,
            "title": "The Beginning",
            "fragments": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "mode": self.MODE_NAME,
            "status": "active",
            "message": (
                "Archivist Mode activated. I'm here to help capture your story — "
                "the moments, the lessons, the things you want your family to know. "
                "Where would you like to begin?"
            ),
            "chapter": 1,
        }

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accept narrative fragments (text and/or voice transcripts).
        data: {text, voice_transcript, topic, emotion}
        """
        if not self._active:
            return {"error": "Archivist mode not active"}

        fragment = {
            "text": data.get("text", ""),
            "voice_transcript": data.get("voice_transcript", ""),
            "topic": data.get("topic", "general"),
            "emotion": data.get("emotion", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._current_chapter["fragments"].append(fragment)

        # Auto-advance chapter after 10 fragments or explicit new_chapter
        if data.get("new_chapter") or len(self._current_chapter["fragments"]) >= 10:
            self._chapters.append(self._current_chapter)
            chapter_num = len(self._chapters) + 1
            self._current_chapter = {
                "number": chapter_num,
                "title": data.get("chapter_title", f"Chapter {chapter_num}"),
                "fragments": [],
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            return {
                "mode": self.MODE_NAME,
                "status": "new_chapter",
                "chapter": chapter_num,
                "total_fragments": sum(len(c["fragments"]) for c in self._chapters),
            }

        return {
            "mode": self.MODE_NAME,
            "status": "recording",
            "chapter": self._current_chapter["number"],
            "fragments_in_chapter": len(self._current_chapter["fragments"]),
        }

    async def generate_output(self) -> Dict[str, Any]:
        """Generate the completed biography and wisdom memories for the vault."""
        # Include current chapter
        if self._current_chapter.get("fragments"):
            self._chapters.append(self._current_chapter)

        # Build biography summary
        all_texts = []
        for ch in self._chapters:
            for frag in ch["fragments"]:
                text = frag.get("text") or frag.get("voice_transcript", "")
                if text:
                    all_texts.append(text)

        biography_outline = {
            "total_chapters": len(self._chapters),
            "total_fragments": sum(len(c["fragments"]) for c in self._chapters),
            "chapters": [
                {
                    "number": ch["number"],
                    "title": ch["title"],
                    "fragment_count": len(ch["fragments"]),
                    "started_at": ch["started_at"],
                }
                for ch in self._chapters
            ],
        }

        # ── Azure OpenAI Narrative Generation ──
        narrative = None
        if self.azure_client and all_texts:
            narrative = await self._generate_narrative(all_texts)
        if narrative:
            biography_outline["narrative"] = narrative

        # Store as Legacy Vault entry
        if self.db_pool and self._family_id:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO legacy_vault_entries
                            (entry_type, family_id, data)
                        VALUES ('biography', $1, $2)""",
                        self._family_id,
                        json.dumps({
                            "user_id": str(self._user_id) if self._user_id else None,
                            "biography_outline": biography_outline,
                            "narrative": narrative,
                            "chapters": [
                                {**ch, "fragments": ch["fragments"]}
                                for ch in self._chapters
                            ],
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        }),
                    )
            except Exception as e:
                print(f">>> [ARCHIVIST] Vault store error: {e}")

        return {
            "mode": self.MODE_NAME,
            "status": "complete",
            "biography": biography_outline,
            "narrative": narrative,
            "stored_to_vault": bool(self._family_id),
        }

    async def _generate_narrative(self, texts: List[str]) -> Optional[str]:
        """Use Azure OpenAI to synthesize a warm, dignified biographical narrative."""
        try:
            import httpx

            endpoint = self.azure_client.get("endpoint", "")
            api_key = self.azure_client.get("api_key", "")
            deployment = self.azure_client.get("chat_deployment", "gpt-4o")

            if not endpoint or not api_key:
                return None

            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-02-15-preview"

            combined = "\n\n".join(texts[:50])[:6000]  # Cap input

            system_prompt = (
                "You are a compassionate biographical narrator for a therapeutic platform's Legacy Vault. "
                "Given fragments of a person's story — memories, reflections, wisdom — synthesize them "
                "into a warm, dignified narrative biography. Write in third person. "
                "Preserve the person's voice and the emotional truth of their experiences. "
                "Include 'Wisdom Memories' — distilled life lessons suitable for passing to family. "
                "Structure: Opening, Life Chapters, Wisdom Memories, Closing Reflection. "
                "Tone: Warm, respectful, honoring. Length: 500-1000 words."
            )

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Story fragments:\n\n{combined}"},
                        ],
                        "temperature": 0.7,
                        "max_tokens": 2000,
                    },
                )

                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    print(f">>> [ARCHIVIST] Azure narrative failed: {resp.status_code}")
                    return None

        except Exception as e:
            print(f">>> [ARCHIVIST] Narrative generation error: {e}")
            return None


# ─── Guardian Mode ───────────────────────────────────────────────────────────

class GuardianMode(BaseAIMode):
    """
    Parental proxy summaries for minor clients.
    Generates confidentiality-preserving summaries:
    e.g. 'anxious about school' not specifics.
    """

    MODE_NAME = "guardian"

    def __init__(self, db_pool, azure_client=None):
        super().__init__(db_pool, azure_client)
        self._minor_id: Optional[UUID] = None
        self._guardian_id: Optional[UUID] = None
        self._session_themes: List[str] = []

    def reset(self) -> None:
        super().reset()
        self._minor_id = None
        self._guardian_id = None
        self._session_themes = []

    async def activate(self, session_id: UUID, **kwargs) -> Dict[str, Any]:
        self.reset()
        self._active = True
        self._session_id = session_id
        self._minor_id = kwargs.get("minor_id")
        self._guardian_id = kwargs.get("guardian_id")
        return {
            "mode": self.MODE_NAME,
            "status": "active",
            "message": "Guardian Mode active. Session themes will be tracked for parent summary.",
        }

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze session messages and extract safe, high-level themes.
        data: {message_text, sender_type, timestamp}
        """
        if not self._active:
            return {"error": "Guardian mode not active"}

        # Extract high-level theme from message (privacy-preserving)
        message = data.get("message_text", "")
        theme = self._extract_safe_theme(message)
        if theme and theme not in self._session_themes:
            self._session_themes.append(theme)

        return {
            "mode": self.MODE_NAME,
            "status": "monitoring",
            "themes_detected": len(self._session_themes),
        }

    async def generate_output(self) -> Dict[str, Any]:
        """Generate a parent-safe summary of the session."""
        # Build privacy-preserving summary
        if not self._session_themes:
            summary_text = "Your child had a session today. No specific concerns flagged."
        else:
            themes_str = ", ".join(self._session_themes[:5])
            summary_text = (
                f"Your child explored the following themes today: {themes_str}. "
                f"No confidential details are shared to protect the therapeutic relationship."
            )

        summary = {
            "mode": self.MODE_NAME,
            "status": "complete",
            "minor_id": str(self._minor_id) if self._minor_id else None,
            "guardian_id": str(self._guardian_id) if self._guardian_id else None,
            "session_id": str(self._session_id) if self._session_id else None,
            "summary": summary_text,
            "themes": self._session_themes,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "privacy_notice": "This summary is intentionally vague to preserve therapeutic confidentiality.",
        }

        # Store summary for guardian access
        if self.db_pool and self._guardian_id:
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO nate_nudges
                            (user_id, nudge_type, title, content, metadata, scheduled_at, status)
                        VALUES ($1, 'milestone', 'Session Summary Available', $2, $3, NOW(), 'pending')""",
                        self._guardian_id,
                        summary_text,
                        json.dumps({
                            "source": "guardian_mode",
                            "minor_id": str(self._minor_id) if self._minor_id else None,
                        }),
                    )
            except Exception as e:
                print(f">>> [GUARDIAN] Summary store error: {e}")

        return summary

    @staticmethod
    def _extract_safe_theme(message: str) -> Optional[str]:
        """Extract a privacy-safe theme from a message. No specifics."""
        msg_lower = message.lower()
        theme_keywords = {
            "school concerns": ["school", "homework", "teacher", "grade", "class"],
            "peer relationships": ["friend", "bully", "popular", "group", "social"],
            "family dynamics": ["mom", "dad", "parent", "sibling", "brother", "sister"],
            "emotional regulation": ["angry", "anxious", "sad", "scared", "worried", "upset"],
            "self-esteem": ["confident", "worth", "ugly", "stupid", "smart", "good enough"],
            "sleep and wellness": ["sleep", "tired", "nightmare", "eat", "appetite"],
            "identity exploration": ["who am i", "identity", "gender", "sexuality", "future"],
        }
        for theme, keywords in theme_keywords.items():
            if any(kw in msg_lower for kw in keywords):
                return theme
        return None


# ─── Supervisor Mode ─────────────────────────────────────────────────────────

class SupervisorMode(BaseAIMode):
    """
    Coach session analysis: empathy grading, technique identification,
    and training recommendations.
    """

    MODE_NAME = "supervisor"

    def __init__(self, db_pool, azure_client=None):
        super().__init__(db_pool, azure_client)
        self._coach_id: Optional[UUID] = None
        self._messages: List[Dict[str, Any]] = []

    def reset(self) -> None:
        super().reset()
        self._coach_id = None
        self._messages = []

    async def activate(self, session_id: UUID, **kwargs) -> Dict[str, Any]:
        self.reset()
        self._active = True
        self._session_id = session_id
        self._coach_id = kwargs.get("coach_id")
        return {
            "mode": self.MODE_NAME,
            "status": "active",
            "message": "Supervisor Mode active. Coach interactions will be analyzed.",
        }

    async def process(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collect session messages for analysis.
        data: {sender_type, message_text, timestamp}
        """
        if not self._active:
            return {"error": "Supervisor mode not active"}

        self._messages.append({
            "sender": data.get("sender_type", "unknown"),
            "text": data.get("message_text", ""),
            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        })

        return {
            "mode": self.MODE_NAME,
            "status": "collecting",
            "messages_analyzed": len(self._messages),
        }

    async def generate_output(self) -> Dict[str, Any]:
        """Generate coach performance analysis report."""
        if not self._messages:
            return {"mode": self.MODE_NAME, "status": "no_data"}

        coach_msgs = [m for m in self._messages if m["sender"] == "coach"]
        client_msgs = [m for m in self._messages if m["sender"] == "client"]

        # ── Empathy Score ──
        empathy_keywords = [
            "understand", "feel", "hear you", "that must be", "it sounds like",
            "i can see", "tell me more", "that's important", "i appreciate",
            "how did that make you feel", "what was that like",
        ]
        empathy_count = 0
        for msg in coach_msgs:
            text = msg["text"].lower()
            empathy_count += sum(1 for kw in empathy_keywords if kw in text)
        empathy_score = min(1.0, empathy_count / max(len(coach_msgs) * 2, 1))

        # ── Technique Identification ──
        technique_markers = {
            "reflective_listening": ["i hear", "it sounds like", "you're saying"],
            "open_questions": ["how do you", "what do you think", "tell me about", "can you describe"],
            "validation": ["that makes sense", "of course", "it's understandable", "your feelings are valid"],
            "reframing": ["another way to look at", "what if we consider", "have you thought about"],
            "psychoeducation": ["research shows", "studies suggest", "this is called", "in psychology"],
            "boundary_setting": ["boundary", "limits", "saying no", "your right to"],
        }
        detected_techniques = {}
        for technique, markers in technique_markers.items():
            count = 0
            for msg in coach_msgs:
                text = msg["text"].lower()
                count += sum(1 for m in markers if m in text)
            if count > 0:
                detected_techniques[technique] = count

        # ── Technique Score ──
        technique_score = min(1.0, len(detected_techniques) / 4)

        # ── Response Ratio ──
        response_ratio = len(coach_msgs) / max(len(client_msgs), 1)
        # Ideal ratio is ~0.8-1.2 (coach shouldn't dominate)
        balance_score = 1.0 - min(abs(response_ratio - 1.0), 1.0)

        # ── Overall Grade ──
        overall = (empathy_score * 0.4) + (technique_score * 0.35) + (balance_score * 0.25)
        if overall >= 0.85:
            grade = "EXCELLENT"
        elif overall >= 0.70:
            grade = "PROFICIENT"
        elif overall >= 0.55:
            grade = "DEVELOPING"
        else:
            grade = "NEEDS_IMPROVEMENT"

        # ── Training Recommendations ──
        recommendations = []
        if empathy_score < 0.5:
            recommendations.append("Practice reflective listening — paraphrase client statements before responding.")
        if "open_questions" not in detected_techniques:
            recommendations.append("Use more open-ended questions to encourage client exploration.")
        if "validation" not in detected_techniques:
            recommendations.append("Increase emotional validation to strengthen therapeutic alliance.")
        if response_ratio > 1.5:
            recommendations.append("Allow more space for client to speak — reduce coach talk time.")
        if not recommendations:
            recommendations.append("Strong session. Consider exploring advanced techniques like IFS or somatic experiencing.")

        report = {
            "mode": self.MODE_NAME,
            "status": "complete",
            "coach_id": str(self._coach_id) if self._coach_id else None,
            "session_id": str(self._session_id) if self._session_id else None,
            "analysis": {
                "empathy_score": round(empathy_score, 3),
                "technique_score": round(technique_score, 3),
                "balance_score": round(balance_score, 3),
                "overall_score": round(overall, 3),
                "grade": grade,
                "techniques_detected": detected_techniques,
                "response_ratio": round(response_ratio, 2),
                "total_coach_messages": len(coach_msgs),
                "total_client_messages": len(client_msgs),
            },
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        return report


# ─── Organizer Mode (Sovereign Circle — Accessibility) ───────────────────────

# OrganizerMode is imported lazily to avoid circular dependencies.
# It manages its own session lifecycle (OrgSessionManager) and does NOT
# extend BaseAIMode, but is registered here for discovery/factory use.

def _get_organizer_mode_cls():
    """Lazy import to avoid circular dependency with vault services."""
    from app.services.vault.document_organizer import OrganizerMode
    return OrganizerMode


# ─── Mode Registry ───────────────────────────────────────────────────────────

AI_MODE_REGISTRY: Dict[str, type] = {
    "tri_corder": TriCorderMode,
    "archivist": ArchivistMode,
    "guardian": GuardianMode,
    "supervisor": SupervisorMode,
    # Note: 'organizer' is NOT in this registry — it has a different constructor
    # signature and must be instantiated via get_organizer_mode().
}


def get_ai_mode(mode_name: str, db_pool, azure_client=None) -> BaseAIMode:
    """Factory function to instantiate an AI mode by name.

    Note: 'organizer' mode is not in AI_MODE_REGISTRY because it has its
    own constructor signature (azure_endpoint, azure_api_key, deployment).
    Callers should use get_organizer_mode() for direct instantiation.
    """
    if mode_name == "organizer":
        raise ValueError(
            "OrganizerMode must be instantiated via get_organizer_mode() "
            "because it requires Azure credentials directly."
        )
    cls = AI_MODE_REGISTRY.get(mode_name)
    if not cls:
        all_modes = list(AI_MODE_REGISTRY.keys()) + ["organizer"]
        raise ValueError(f"Unknown AI mode: {mode_name}. "
                         f"Available: {all_modes}")
    return cls(db_pool=db_pool, azure_client=azure_client)


def get_organizer_mode(db_pool, azure_endpoint: str, azure_api_key: str,
                       deployment: str = "gpt-4o"):
    """Instantiate OrganizerMode with Azure credentials."""
    cls = _get_organizer_mode_cls()
    return cls(db_pool=db_pool, azure_endpoint=azure_endpoint,
               azure_api_key=azure_api_key, deployment=deployment)
