"""
Classroom Analyzer - Session transcript analysis for coach development

Analyzes Zoom session transcripts to:
- Extract therapeutic technique usage
- Calculate talk-time ratios
- Identify question types and reflection patterns
- Generate personalized coaching assignments
- Store insights for Little Nate's long-term memory
- Identify clients and family members in sessions
- Track client metrics (coherence, GAP, mood) from session analysis
"""

import re
import json
import hashlib
import os
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set, Callable, Awaitable
from dataclasses import dataclass, asdict, field

from app.services.nate_ai_config import (
    NATE_CHAT_URL, NATE_CHAT_KEY, NATE_CHAT_MODEL,
    nate_temperature, nate_chat_headers, nate_chat_payload,
)

_classroom_logger = logging.getLogger("classroom_analyzer")

# Type for async notification callback
NotificationCallback = Callable[[str, str, Dict], Awaitable[None]]

# Global notification callback (set by bridge_server)
_notification_callback: Optional[NotificationCallback] = None

def set_notification_callback(callback: NotificationCallback):
    """Set the callback for sending WebSocket notifications."""
    global _notification_callback
    _notification_callback = callback
    print("[Classroom] Notification callback registered")

async def notify_coach(coach_id: str, message_type: str, data: Dict):
    """Send notification to coach via WebSocket."""
    if _notification_callback:
        try:
            await _notification_callback(coach_id, message_type, data)
        except Exception as e:
            print(f"[Classroom] Notification error: {e}")

# Therapeutic technique patterns
TECHNIQUE_PATTERNS = {
    "EFT": [
        r"\b(attachment|bonding|emotional connection|secure base|safe haven)\b",
        r"\b(reach for|turn toward|soften|engage|de-escalate)\b",
        r"\b(primary emotion|secondary emotion|reactive|withdrawn)\b",
    ],
    "IFS": [
        r"\b(part|parts|protector|exile|manager|firefighter)\b",
        r"\b(self energy|self-led|unblend|blend)\b",
        r"\b(inner child|young part|wounded part)\b",
    ],
    "CBT": [
        r"\b(thought|thinking pattern|cognitive distortion|automatic thought)\b",
        r"\b(evidence for|evidence against|reframe|challenge)\b",
        r"\b(behavior|behavioral experiment|exposure)\b",
    ],
    "POLYVAGAL": [
        r"\b(nervous system|regulation|co-regulation|dysregulation)\b",
        r"\b(ventral vagal|dorsal vagal|sympathetic|window of tolerance)\b",
        r"\b(safe|safety|neuroception)\b",
    ],
    "SOMATIC": [
        r"\b(body|sensation|felt sense|embodied)\b",
        r"\b(grounding|breath|tension|release)\b",
        r"\b(tracking|noticing|awareness)\b",
    ],
    "REFLECTIVE_LISTENING": [
        r"\b(sounds like|it seems|what I'm hearing|I hear you saying)\b",
        r"\b(so you're feeling|you feel|that must be)\b",
    ],
    "VALIDATION": [
        r"\b(makes sense|understandable|of course|naturally)\b",
        r"\b(valid|legitimate|reasonable|anyone would)\b",
    ],
}

# Question type patterns
QUESTION_PATTERNS = {
    "open": [
        r"^(what|how|tell me|describe|explain|share|walk me through)\b",
        r"\b(what do you|how do you|what would|how would)\b",
    ],
    "closed": [
        r"^(do you|did you|are you|is it|was it|have you|can you|will you)\b",
        r"\b(yes or no|right\?|correct\?)\b",
    ],
    "scaling": [
        r"\b(on a scale|from 1 to|rate|how much|how often)\b",
    ],
    "miracle": [
        r"\b(if.*miracle|imagine.*different|what would.*look like)\b",
    ],
    "exception": [
        r"\b(time when.*different|when.*worked|exception|time.*better)\b",
    ],
}


@dataclass
class VTTEntry:
    """Single entry from a VTT transcript."""
    start_time: float  # seconds
    end_time: float    # seconds
    speaker: str
    text: str


@dataclass
class SessionMetrics:
    """Extracted metrics from a coaching session."""
    total_duration_minutes: float
    coach_talk_time_percent: float
    client_talk_time_percent: float
    silence_percent: float
    
    total_questions: int
    open_questions: int
    closed_questions: int
    scaling_questions: int
    
    techniques_detected: Dict[str, int]
    reflection_count: int
    validation_count: int
    
    average_response_length_coach: float
    average_response_length_client: float
    longest_monologue_seconds: float
    turn_count: int


@dataclass
class ClassroomAnalysis:
    """Complete analysis of a coaching session."""
    session_id: str
    coach_id: str
    client_id: str
    analyzed_at: str
    
    # Raw metrics
    metrics: SessionMetrics
    
    # AI-generated insights
    strengths: List[str]
    growth_areas: List[str]
    key_moments: List[Dict[str, Any]]  # timestamp, description, feedback
    therapeutic_presence_score: float  # 0-10
    
    # Learning focus (what coach requested to learn about)
    focus_area: str
    focus_specific_feedback: str
    
    # Assignments
    reflection_questions: List[str]
    dojo_scenarios: List[Dict[str, str]]  # persona, scenario, skill_target
    workbook_recommendations: List[str]
    
    # Metadata
    transcript_hash: str
    due_date: Optional[str]


@dataclass
class ParticipantIdentification:
    """Identified participant from transcript analysis."""
    speaker_name: str  # Name as it appears in VTT
    normalized_name: str  # Cleaned/normalized name
    role: str  # 'coach', 'primary_client', 'family_member', 'unknown'
    matched_client_id: Optional[str]  # Matched to registry
    matched_family_id: Optional[str]  # Family group
    talk_time_seconds: float
    turn_count: int
    is_present: bool  # Actually speaking vs just mentioned
    confidence: float  # 0-1 confidence in identification


@dataclass
class ClientSessionInsights:
    """Insights about a specific client extracted from session."""
    client_id: str
    client_name: str
    family_id: Optional[str]
    
    # Emotional indicators from their speech
    emotional_state: str  # e.g., "anxious", "hopeful", "resistant"
    emotional_indicators: List[str]  # Specific phrases/patterns
    engagement_level: float  # 0-1
    
    # Topics and themes
    topics_discussed: List[str]
    concerns_raised: List[str]
    growth_moments: List[str]
    
    # Family context (without revealing confidential info)
    family_members_present: List[str]  # Names of family in session
    family_members_mentioned: List[str]  # Talked about but not present
    
    # Metrics indicators (to update client profile)
    coherence_indicators: Dict[str, Any]
    mood_indicators: Dict[str, Any]
    
    # For Little Nate's memory
    session_summary_for_nate: str  # Context Nate can use in future interactions
    coach_observations: List[str]  # What coach noticed


# Emotional state detection patterns
EMOTIONAL_STATE_PATTERNS = {
    "anxious": [
        r"\b(worried|nervous|anxious|scared|afraid|panic|stress|overwhelm)\b",
        r"\b(can't stop thinking|keep thinking|racing thoughts)\b",
    ],
    "hopeful": [
        r"\b(hope|hopeful|optimistic|looking forward|excited|positive)\b",
        r"\b(getting better|improving|progress|growth)\b",
    ],
    "sad": [
        r"\b(sad|depressed|down|low|empty|lonely|grief|loss)\b",
        r"\b(crying|tears|hurt|pain|ache)\b",
    ],
    "angry": [
        r"\b(angry|frustrated|annoyed|upset|mad|furious|rage)\b",
        r"\b(unfair|can't believe|sick of|tired of)\b",
    ],
    "resistant": [
        r"\b(don't want to|won't|refuse|can't|impossible)\b",
        r"\b(doesn't work|tried that|waste of time)\b",
    ],
    "open": [
        r"\b(willing|want to|ready|open|curious|interested)\b",
        r"\b(try|explore|understand|learn)\b",
    ],
    "vulnerable": [
        r"\b(hard to say|difficult|scared to|never told|first time)\b",
        r"\b(admit|confess|realize|see now)\b",
    ],
}

# Topics/themes detection
TOPIC_PATTERNS = {
    "relationship": r"\b(relationship|partner|spouse|husband|wife|boyfriend|girlfriend|dating)\b",
    "parenting": r"\b(child|children|kids|parent|mother|father|son|daughter|teen)\b",
    "family_origin": r"\b(mom|dad|parents|childhood|growing up|family|siblings|brother|sister)\b",
    "work": r"\b(work|job|career|boss|coworker|office|workplace|profession)\b",
    "trauma": r"\b(trauma|abuse|assault|violence|accident|death|loss)\b",
    "anxiety": r"\b(anxiety|panic|worry|stress|nervous|overwhelm)\b",
    "depression": r"\b(depression|depressed|hopeless|suicidal|self-harm)\b",
    "attachment": r"\b(attachment|connection|bonding|trust|safe|secure)\b",
    "boundaries": r"\b(boundaries|limits|saying no|people-pleasing|codependent)\b",
    "self_worth": r"\b(self-esteem|worth|value|good enough|deserve|shame)\b",
}


class VTTParser:
    """Parse Zoom VTT transcript files."""
    
    @staticmethod
    def parse(vtt_content: str) -> List[VTTEntry]:
        """Parse VTT content into structured entries."""
        entries = []
        
        # VTT format:
        # WEBVTT
        # 
        # 00:00:01.000 --> 00:00:05.000
        # Speaker Name: Text content
        
        lines = vtt_content.strip().split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip WEBVTT header and empty lines
            if not line or line == 'WEBVTT' or line.startswith('NOTE'):
                i += 1
                continue
            
            # Look for timestamp line
            timestamp_match = re.match(
                r'(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})',
                line
            )
            
            if timestamp_match:
                start_str, end_str = timestamp_match.groups()
                start_time = VTTParser._parse_timestamp(start_str)
                end_time = VTTParser._parse_timestamp(end_str)
                
                # Next line(s) contain the text
                i += 1
                text_lines = []
                while i < len(lines) and lines[i].strip() and not re.match(r'\d{2}:\d{2}', lines[i]):
                    text_lines.append(lines[i].strip())
                    i += 1
                
                full_text = ' '.join(text_lines)
                
                # Extract speaker if present
                speaker_match = re.match(r'^([^:]+):\s*(.+)$', full_text)
                if speaker_match:
                    speaker = speaker_match.group(1).strip()
                    text = speaker_match.group(2).strip()
                else:
                    speaker = "Unknown"
                    text = full_text
                
                if text:
                    entries.append(VTTEntry(
                        start_time=start_time,
                        end_time=end_time,
                        speaker=speaker,
                        text=text
                    ))
            else:
                i += 1
        
        return entries
    
    @staticmethod
    def _parse_timestamp(ts: str) -> float:
        """Convert VTT timestamp to seconds."""
        ts = ts.replace(',', '.')
        parts = ts.split(':')
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        return 0.0


class MetricsExtractor:
    """Extract coaching metrics from parsed transcript."""
    
    def __init__(self, entries: List[VTTEntry], coach_name: str = None):
        self.entries = entries
        self.coach_name = coach_name
        
    def extract(self) -> SessionMetrics:
        """Extract all metrics from transcript."""
        if not self.entries:
            return self._empty_metrics()
        
        # Calculate durations
        total_duration = self.entries[-1].end_time if self.entries else 0
        coach_time, client_time = self._calculate_talk_times()
        
        # Calculate questions
        questions = self._analyze_questions()
        
        # Detect techniques
        techniques = self._detect_techniques()
        
        # Count reflections and validations
        reflection_count = self._count_pattern_matches(TECHNIQUE_PATTERNS["REFLECTIVE_LISTENING"])
        validation_count = self._count_pattern_matches(TECHNIQUE_PATTERNS["VALIDATION"])
        
        # Calculate response lengths and turns
        coach_lengths, client_lengths = self._calculate_response_lengths()
        longest_mono = self._find_longest_monologue()
        
        return SessionMetrics(
            total_duration_minutes=total_duration / 60,
            coach_talk_time_percent=coach_time / max(total_duration, 1) * 100,
            client_talk_time_percent=client_time / max(total_duration, 1) * 100,
            silence_percent=max(0, 100 - (coach_time + client_time) / max(total_duration, 1) * 100),
            total_questions=sum(questions.values()),
            open_questions=questions.get("open", 0),
            closed_questions=questions.get("closed", 0),
            scaling_questions=questions.get("scaling", 0),
            techniques_detected=techniques,
            reflection_count=reflection_count,
            validation_count=validation_count,
            average_response_length_coach=sum(coach_lengths) / max(len(coach_lengths), 1),
            average_response_length_client=sum(client_lengths) / max(len(client_lengths), 1),
            longest_monologue_seconds=longest_mono,
            turn_count=len(self.entries)
        )
    
    def _calculate_talk_times(self) -> Tuple[float, float]:
        """Calculate talk time for coach vs client."""
        coach_time = 0.0
        client_time = 0.0
        
        for entry in self.entries:
            duration = entry.end_time - entry.start_time
            if self._is_coach(entry.speaker):
                coach_time += duration
            else:
                client_time += duration
        
        return coach_time, client_time
    
    def _is_coach(self, speaker: str) -> bool:
        """Determine if speaker is the coach."""
        speaker_lower = speaker.lower()
        if self.coach_name and self.coach_name.lower() in speaker_lower:
            return True
        # Common coach indicators
        coach_indicators = ['coach', 'therapist', 'counselor', 'dr.', 'dr ', 'host']
        return any(ind in speaker_lower for ind in coach_indicators)
    
    def _analyze_questions(self) -> Dict[str, int]:
        """Categorize questions by type."""
        counts = {"open": 0, "closed": 0, "scaling": 0, "miracle": 0, "exception": 0}
        
        for entry in self.entries:
            if not self._is_coach(entry.speaker):
                continue
            
            text = entry.text.lower()
            if '?' not in entry.text:
                continue
            
            for q_type, patterns in QUESTION_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        counts[q_type] = counts.get(q_type, 0) + 1
                        break
        
        return counts
    
    def _detect_techniques(self) -> Dict[str, int]:
        """Detect therapeutic techniques used."""
        techniques = {}
        
        for entry in self.entries:
            if not self._is_coach(entry.speaker):
                continue
            
            text = entry.text.lower()
            
            for technique, patterns in TECHNIQUE_PATTERNS.items():
                if technique in ["REFLECTIVE_LISTENING", "VALIDATION"]:
                    continue  # Counted separately
                
                for pattern in patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        techniques[technique] = techniques.get(technique, 0) + 1
                        break
        
        return techniques
    
    def _count_pattern_matches(self, patterns: List[str]) -> int:
        """Count matches of patterns in coach speech."""
        count = 0
        for entry in self.entries:
            if not self._is_coach(entry.speaker):
                continue
            
            for pattern in patterns:
                if re.search(pattern, entry.text, re.IGNORECASE):
                    count += 1
                    break
        
        return count
    
    def _calculate_response_lengths(self) -> Tuple[List[int], List[int]]:
        """Calculate word counts per response."""
        coach_lengths = []
        client_lengths = []
        
        for entry in self.entries:
            word_count = len(entry.text.split())
            if self._is_coach(entry.speaker):
                coach_lengths.append(word_count)
            else:
                client_lengths.append(word_count)
        
        return coach_lengths, client_lengths
    
    def _find_longest_monologue(self) -> float:
        """Find the longest uninterrupted speaking segment."""
        if not self.entries:
            return 0.0
        
        longest = 0.0
        current_speaker = None
        current_start = 0.0
        
        for entry in self.entries:
            if entry.speaker != current_speaker:
                if current_speaker is not None:
                    duration = entry.start_time - current_start
                    longest = max(longest, duration)
                current_speaker = entry.speaker
                current_start = entry.start_time
        
        # Check final segment
        if self.entries:
            duration = self.entries[-1].end_time - current_start
            longest = max(longest, duration)
        
        return longest
    
    def _empty_metrics(self) -> SessionMetrics:
        """Return empty metrics structure."""
        return SessionMetrics(
            total_duration_minutes=0,
            coach_talk_time_percent=0,
            client_talk_time_percent=0,
            silence_percent=0,
            total_questions=0,
            open_questions=0,
            closed_questions=0,
            scaling_questions=0,
            techniques_detected={},
            reflection_count=0,
            validation_count=0,
            average_response_length_coach=0,
            average_response_length_client=0,
            longest_monologue_seconds=0,
            turn_count=0
        )


class ParticipantIdentifier:
    """
    Identifies participants in a session transcript.
    
    Uses:
    1. Primary: client_id from Zoom schedule
    2. Secondary: Name matching against family registry
    3. Tertiary: Name extraction from transcript for unknown speakers
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.registry_path = self.data_dir / "registry.json"
    
    def load_registry(self) -> Dict:
        """Load user registry for name matching."""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def get_family_members(self, family_id: str) -> List[Dict]:
        """Get all members of a family by family_id."""
        registry = self.load_registry()
        members = []
        for username, data in registry.items():
            profile = data.get("profile", {})
            if profile.get("family_id") == family_id:
                members.append({
                    "username": username,
                    "hardware_id": profile.get("hardware_id", ""),
                    "name": profile.get("name", username),
                    "role": profile.get("role", "CLIENT"),
                    "family_id": family_id,
                })
        return members
    
    def normalize_name(self, name: str) -> str:
        """Normalize a name for matching."""
        # Remove common Zoom suffixes
        name = re.sub(r"\s*\(.*?\)\s*$", "", name)  # Remove (host), (me), etc.
        name = re.sub(r"[^\w\s]", "", name)  # Remove punctuation
        name = name.strip().lower()
        return name
    
    def identify_participants(
        self,
        entries: List[VTTEntry],
        scheduled_client_id: str,
        scheduled_family_id: str = None,
        coach_name: str = None
    ) -> Tuple[List[ParticipantIdentification], Dict[str, str]]:
        """
        Identify all participants in a session.
        
        Returns:
            - List of ParticipantIdentification objects
            - Dict mapping speaker names to client_ids
        """
        # Get unique speakers from transcript
        speaker_stats = {}
        for entry in entries:
            speaker = entry.speaker
            if speaker not in speaker_stats:
                speaker_stats[speaker] = {
                    "talk_time": 0.0,
                    "turn_count": 0,
                    "normalized": self.normalize_name(speaker),
                }
            speaker_stats[speaker]["talk_time"] += entry.end_time - entry.start_time
            speaker_stats[speaker]["turn_count"] += 1
        
        # Load family members for matching
        family_members = []
        if scheduled_family_id:
            family_members = self.get_family_members(scheduled_family_id)
        
        # Also load primary client info
        registry = self.load_registry()
        primary_client = None
        for username, data in registry.items():
            profile = data.get("profile", {})
            if profile.get("hardware_id") == scheduled_client_id:
                primary_client = {
                    "username": username,
                    "hardware_id": scheduled_client_id,
                    "name": profile.get("name", username),
                    "role": profile.get("role", "CLIENT"),
                    "family_id": profile.get("family_id"),
                }
                if not scheduled_family_id:
                    scheduled_family_id = profile.get("family_id")
                    family_members = self.get_family_members(scheduled_family_id) if scheduled_family_id else []
                break
        
        participants = []
        speaker_to_client = {}
        
        for speaker, stats in speaker_stats.items():
            normalized = stats["normalized"]
            matched_id = None
            matched_family = scheduled_family_id
            role = "unknown"
            confidence = 0.0
            
            # Check if this is the coach
            if coach_name and self._names_match(normalized, coach_name):
                role = "coach"
                confidence = 0.95
            
            # Check against primary client
            elif primary_client and self._names_match(normalized, primary_client["name"]):
                matched_id = primary_client["hardware_id"]
                role = "primary_client"
                confidence = 0.9
                speaker_to_client[speaker] = matched_id
            
            # Check against family members
            else:
                for member in family_members:
                    if self._names_match(normalized, member["name"]):
                        matched_id = member["hardware_id"]
                        matched_family = member["family_id"]
                        role = "family_member"
                        confidence = 0.8
                        speaker_to_client[speaker] = matched_id
                        break
            
            # If still unknown but has significant talk time, mark as potential client
            if role == "unknown" and stats["talk_time"] > 30:  # More than 30 seconds
                role = "potential_client"
                confidence = 0.3
            
            participants.append(ParticipantIdentification(
                speaker_name=speaker,
                normalized_name=normalized,
                role=role,
                matched_client_id=matched_id,
                matched_family_id=matched_family,
                talk_time_seconds=stats["talk_time"],
                turn_count=stats["turn_count"],
                is_present=True,
                confidence=confidence,
            ))
        
        return participants, speaker_to_client
    
    def _names_match(self, name1: str, name2: str) -> bool:
        """Check if two names likely refer to the same person."""
        n1 = self.normalize_name(name1)
        n2 = self.normalize_name(name2)
        
        # Exact match
        if n1 == n2:
            return True
        
        # First name match
        parts1 = n1.split()
        parts2 = n2.split()
        if parts1 and parts2 and parts1[0] == parts2[0]:
            return True
        
        # Partial match (one is contained in the other)
        if len(n1) > 2 and len(n2) > 2:
            if n1 in n2 or n2 in n1:
                return True
        
        return False
    
    def extract_mentioned_names(
        self,
        entries: List[VTTEntry],
        known_speakers: Set[str],
        family_members: List[Dict]
    ) -> List[str]:
        """
        Extract names of family members mentioned but not present.
        
        This helps Little Nate understand family context without
        revealing confidential information.
        """
        mentioned = set()
        
        # Build list of family member names to look for
        family_names = {self.normalize_name(m["name"]): m for m in family_members}
        
        # Get normalized known speaker names
        known_normalized = {self.normalize_name(s) for s in known_speakers}
        
        # Scan transcript for mentions
        for entry in entries:
            text_lower = entry.text.lower()
            
            for norm_name, member in family_names.items():
                # Skip if this is a known speaker (already present)
                if norm_name in known_normalized:
                    continue
                
                # Check if name appears in text
                if norm_name in text_lower or member["name"].lower() in text_lower:
                    # Verify it's a reference (not just coincidental word)
                    # Look for patterns like "my son [name]", "[name] said", etc.
                    name_pattern = rf"\b{re.escape(member['name'].split()[0].lower())}\b"
                    if re.search(name_pattern, text_lower):
                        mentioned.add(member["name"])
        
        return list(mentioned)


class ClientInsightsExtractor:
    """
    Extracts insights about clients from session transcripts.
    
    Used to update client metrics and provide context for Little Nate.
    """
    
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
    
    def extract_insights(
        self,
        entries: List[VTTEntry],
        client_id: str,
        client_name: str,
        family_id: str,
        speaker_to_client: Dict[str, str],
        family_members_present: List[str],
        family_members_mentioned: List[str]
    ) -> ClientSessionInsights:
        """
        Extract insights about a specific client from the session.
        """
        # Get entries from this client
        client_entries = [
            e for e in entries
            if speaker_to_client.get(e.speaker) == client_id
        ]
        
        # Combine all client speech
        client_text = " ".join(e.text for e in client_entries)
        client_text_lower = client_text.lower()
        
        # Detect emotional state
        emotional_state, emotional_indicators = self._detect_emotional_state(client_entries)
        
        # Calculate engagement level
        engagement = self._calculate_engagement(entries, client_entries)
        
        # Extract topics
        topics = self._extract_topics(client_text_lower)
        
        # Extract concerns (questions and worry statements)
        concerns = self._extract_concerns(client_entries)
        
        # Extract growth moments (positive insights, breakthroughs)
        growth_moments = self._extract_growth_moments(client_entries)
        
        # Build coherence indicators
        coherence_indicators = self._build_coherence_indicators(client_entries, emotional_state)
        
        # Build mood indicators
        mood_indicators = self._build_mood_indicators(emotional_state, emotional_indicators)
        
        # Generate summary for Little Nate
        session_summary = self._generate_nate_summary(
            client_name=client_name,
            emotional_state=emotional_state,
            topics=topics,
            concerns=concerns,
            growth_moments=growth_moments,
            engagement=engagement
        )
        
        return ClientSessionInsights(
            client_id=client_id,
            client_name=client_name,
            family_id=family_id,
            emotional_state=emotional_state,
            emotional_indicators=emotional_indicators,
            engagement_level=engagement,
            topics_discussed=topics,
            concerns_raised=concerns,
            growth_moments=growth_moments,
            family_members_present=family_members_present,
            family_members_mentioned=family_members_mentioned,
            coherence_indicators=coherence_indicators,
            mood_indicators=mood_indicators,
            session_summary_for_nate=session_summary,
            coach_observations=[]  # Filled in by coach during session
        )
    
    def _detect_emotional_state(
        self,
        client_entries: List[VTTEntry]
    ) -> Tuple[str, List[str]]:
        """Detect the dominant emotional state from client speech."""
        state_counts = {state: 0 for state in EMOTIONAL_STATE_PATTERNS}
        indicators = []
        
        for entry in client_entries:
            text_lower = entry.text.lower()
            
            for state, patterns in EMOTIONAL_STATE_PATTERNS.items():
                for pattern in patterns:
                    matches = re.findall(pattern, text_lower, re.IGNORECASE)
                    if matches:
                        state_counts[state] += len(matches)
                        for match in matches[:2]:  # Limit indicators per pattern
                            if isinstance(match, str) and match not in indicators:
                                indicators.append(match)
        
        # Get dominant state
        if sum(state_counts.values()) == 0:
            return "neutral", []
        
        dominant = max(state_counts.items(), key=lambda x: x[1])
        return dominant[0], indicators[:10]
    
    def _calculate_engagement(
        self,
        all_entries: List[VTTEntry],
        client_entries: List[VTTEntry]
    ) -> float:
        """Calculate client engagement level (0-1)."""
        if not all_entries or not client_entries:
            return 0.5
        
        # Factors:
        # 1. Proportion of turns taken
        turn_ratio = len(client_entries) / max(len(all_entries), 1)
        
        # 2. Average response length (engaged = more detailed responses)
        avg_words = sum(len(e.text.split()) for e in client_entries) / max(len(client_entries), 1)
        length_score = min(1.0, avg_words / 30)  # 30+ words = fully engaged
        
        # 3. Question asking (engaged clients ask questions)
        questions = sum(1 for e in client_entries if "?" in e.text)
        question_score = min(1.0, questions / 5)  # 5+ questions = fully engaged
        
        # Weighted average
        engagement = (turn_ratio * 0.3) + (length_score * 0.4) + (question_score * 0.3)
        return round(min(1.0, max(0.0, engagement)), 2)
    
    def _extract_topics(self, client_text_lower: str) -> List[str]:
        """Extract main topics discussed by client."""
        topics = []
        for topic, pattern in TOPIC_PATTERNS.items():
            if re.search(pattern, client_text_lower, re.IGNORECASE):
                topics.append(topic)
        return topics[:8]  # Limit to 8 topics
    
    def _extract_concerns(self, client_entries: List[VTTEntry]) -> List[str]:
        """Extract main concerns raised by client."""
        concerns = []
        concern_patterns = [
            r"I'm worried about (.+?)(?:\.|,|$)",
            r"I'm concerned (.+?)(?:\.|,|$)",
            r"I don't know (?:how to|if|what) (.+?)(?:\.|,|$)",
            r"I'm struggling with (.+?)(?:\.|,|$)",
            r"What if (.+?)(?:\.|,|\?|$)",
        ]
        
        for entry in client_entries:
            for pattern in concern_patterns:
                matches = re.findall(pattern, entry.text, re.IGNORECASE)
                for match in matches:
                    concern = match.strip()[:100]
                    if concern and concern not in concerns:
                        concerns.append(concern)
        
        return concerns[:5]
    
    def _extract_growth_moments(self, client_entries: List[VTTEntry]) -> List[str]:
        """Extract growth/breakthrough moments."""
        growth = []
        growth_patterns = [
            r"I realize(?:d)? (.+?)(?:\.|,|$)",
            r"I never thought about (.+?)(?:\.|,|$)",
            r"That makes sense (.+?)(?:\.|,|$)",
            r"I feel (?:like|that) (.+?)(?:\.|,|$)",
            r"I'm starting to (.+?)(?:\.|,|$)",
            r"I want to (.+?)(?:\.|,|$)",
        ]
        
        for entry in client_entries:
            for pattern in growth_patterns:
                matches = re.findall(pattern, entry.text, re.IGNORECASE)
                for match in matches:
                    moment = match.strip()[:100]
                    if moment and moment not in growth:
                        growth.append(moment)
        
        return growth[:5]
    
    def _build_coherence_indicators(
        self,
        client_entries: List[VTTEntry],
        emotional_state: str
    ) -> Dict[str, Any]:
        """Build coherence indicators from session."""
        # Coherence = emotional alignment + clarity + engagement
        
        # Check for emotional clarity
        emotion_words = sum(
            1 for e in client_entries
            for pattern in EMOTIONAL_STATE_PATTERNS.values()
            for p in pattern
            if re.search(p, e.text.lower())
        )
        
        # Check for cognitive clarity (structured thinking)
        clarity_indicators = [
            r"\b(because|since|therefore|so)\b",
            r"\b(I think|I feel|I believe|I know)\b",
            r"\b(when|after|before|during)\b",
        ]
        clarity_count = sum(
            1 for e in client_entries
            for pattern in clarity_indicators
            if re.search(pattern, e.text.lower())
        )
        
        return {
            "emotional_awareness": min(1.0, emotion_words / 10),
            "cognitive_clarity": min(1.0, clarity_count / 15),
            "dominant_state": emotional_state,
            "coherence_estimate": min(1.0, (emotion_words + clarity_count) / 20),
        }
    
    def _build_mood_indicators(
        self,
        emotional_state: str,
        indicators: List[str]
    ) -> Dict[str, Any]:
        """Build mood indicators for profile update."""
        # Map emotional state to mood dimensions
        mood_mapping = {
            "anxious": {"anxiety": 0.7, "mood": 0.4},
            "hopeful": {"anxiety": 0.2, "mood": 0.8},
            "sad": {"anxiety": 0.4, "mood": 0.3},
            "angry": {"anxiety": 0.5, "mood": 0.4},
            "resistant": {"anxiety": 0.5, "mood": 0.4},
            "open": {"anxiety": 0.3, "mood": 0.7},
            "vulnerable": {"anxiety": 0.5, "mood": 0.5},
            "neutral": {"anxiety": 0.4, "mood": 0.5},
        }
        
        base = mood_mapping.get(emotional_state, mood_mapping["neutral"])
        
        return {
            "current_mood": emotional_state,
            "anxiety_estimate": base["anxiety"],
            "mood_valence": base["mood"],
            "indicators": indicators[:5],
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    def _generate_nate_summary(
        self,
        client_name: str,
        emotional_state: str,
        topics: List[str],
        concerns: List[str],
        growth_moments: List[str],
        engagement: float
    ) -> str:
        """Generate a summary for Little Nate to use in future interactions."""
        parts = [f"In recent coaching session, {client_name} appeared {emotional_state}."]
        
        if topics:
            parts.append(f"Topics discussed: {', '.join(topics[:3])}.")
        
        if concerns:
            parts.append(f"Key concerns: {concerns[0]}.")
        
        if growth_moments:
            parts.append(f"Growth noted: {growth_moments[0]}.")
        
        engagement_desc = "highly engaged" if engagement > 0.7 else "moderately engaged" if engagement > 0.4 else "somewhat reserved"
        parts.append(f"They were {engagement_desc} throughout.")
        
        return " ".join(parts)


class ClassroomAnalyzer:
    """
    Main analyzer class for Classroom feature.
    Coordinates VTT parsing, metrics extraction, AI analysis, and storage.
    
    Enhanced with:
    - Client/family identification from transcripts
    - Client metrics extraction for profile updates
    - Family context management for Little Nate
    """
    
    def __init__(self, data_dir: Path, workbooks_dir: Path = None):
        self.data_dir = Path(data_dir)
        self.workbooks_dir = workbooks_dir
        self.classroom_file = self.data_dir / "classroom_sessions.json"
        self.client_insights_dir = self.data_dir / "classroom_insights"
        self._ensure_data_file()
        
        # Initialize participant identifier and insights extractor
        self.participant_identifier = ParticipantIdentifier(data_dir)
        self.insights_extractor = ClientInsightsExtractor(data_dir)
    
    def _ensure_data_file(self):
        """Ensure classroom_sessions.json and insights directory exist."""
        if not self.classroom_file.exists():
            self.classroom_file.write_text("[]", encoding="utf-8")
        if not self.client_insights_dir.exists():
            self.client_insights_dir.mkdir(parents=True, exist_ok=True)
    
    def load_sessions(self) -> List[Dict]:
        """Load classroom sessions, merging backend (canonical uploads) with
        bridge (analyzed results) to produce a unified view."""
        return self._load_classroom_sessions()

    def save_sessions(self, sessions: List[Dict]):
        """Save classroom sessions to the bridge's writable path."""
        self.classroom_file.write_text(
            json.dumps(sessions, indent=2, default=str),
            encoding="utf-8"
        )

    def get_coach_sessions(self, coach_id: str) -> List[Dict]:
        """Get all sessions for a coach."""
        sessions = self.load_sessions()
        return [s for s in sessions if s.get("coach_id") == coach_id]

    def get_session_analysis(self, session_id: str) -> Optional[Dict]:
        """Get analysis for a specific session."""
        sessions = self.load_sessions()
        for s in sessions:
            if s.get("session_id") == session_id:
                return s
        return None
    
    def analyze_transcript(
        self,
        session_id: str,
        coach_id: str,
        client_id: str,
        coach_name: str,
        vtt_content: str,
        focus_area: str = "general",
        due_date: str = None,
        family_id: str = None,
        client_name: str = None,
        coach_query: str = ""
    ) -> Dict:
        """
        Analyze a transcript and store results.
        
        Enhanced to:
        - Identify all participants (coach, client, family members)
        - Extract client insights for metrics updates
        - Track family context for Little Nate
        
        Returns the analysis dict (without AI insights - those are added async).
        """
        # Parse VTT
        entries = VTTParser.parse(vtt_content)
        
        # Extract metrics
        extractor = MetricsExtractor(entries, coach_name)
        metrics = extractor.extract()
        
        # Create hash for deduplication
        transcript_hash = hashlib.md5(vtt_content.encode()).hexdigest()
        
        # Check if already analyzed
        existing = self.get_session_analysis(session_id)
        if existing and existing.get("transcript_hash") == transcript_hash:
            return existing  # Already analyzed this version
        
        # ========== PARTICIPANT IDENTIFICATION ==========
        participants, speaker_to_client = self.participant_identifier.identify_participants(
            entries=entries,
            scheduled_client_id=client_id,
            scheduled_family_id=family_id,
            coach_name=coach_name
        )
        
        # Get family members from schedule/registry
        family_members = []
        if family_id:
            family_members = self.participant_identifier.get_family_members(family_id)
        
        # Identify who was present vs just mentioned
        present_speakers = {p.speaker_name for p in participants if p.is_present}
        family_present = [
            p.speaker_name for p in participants 
            if p.role in ("primary_client", "family_member") and p.matched_client_id
        ]
        
        # Find family members mentioned but not present
        family_mentioned = self.participant_identifier.extract_mentioned_names(
            entries=entries,
            known_speakers=present_speakers,
            family_members=family_members
        )
        
        # ========== CLIENT INSIGHTS EXTRACTION ==========
        client_insights = None
        if client_id:
            # Get client name from participants or use provided
            if not client_name:
                for p in participants:
                    if p.matched_client_id == client_id:
                        client_name = p.speaker_name
                        break
                if not client_name:
                    client_name = "Client"
            
            client_insights = self.insights_extractor.extract_insights(
                entries=entries,
                client_id=client_id,
                client_name=client_name,
                family_id=family_id or "",
                speaker_to_client=speaker_to_client,
                family_members_present=family_present,
                family_members_mentioned=family_mentioned
            )
            
            # Save client insights for Little Nate and metrics updates
            self._save_client_insights(client_id, session_id, client_insights)
        
        # Build analysis structure (AI insights will be added later)
        analysis = {
            "session_id": session_id,
            "coach_id": coach_id,
            "client_id": client_id,
            "client_name": client_name,
            "family_id": family_id,
            "analyzed_at": datetime.utcnow().isoformat(),
            "metrics": asdict(metrics),
            "strengths": [],
            "growth_areas": [],
            "key_moments": [],
            "therapeutic_presence_score": 0.0,
            "focus_area": focus_area,
            "focus_specific_feedback": "",
            "reflection_questions": [],
            "dojo_scenarios": [],
            "workbook_recommendations": [],
            "transcript_hash": transcript_hash,
            "due_date": due_date,
            "ai_analysis_pending": True,
            "transcript_excerpt": self._create_excerpt(entries),
            
            # New: Participant identification
            "participants": [asdict(p) for p in participants],
            "family_members_present": family_present,
            "family_members_mentioned": family_mentioned,
            
            # New: Client insights summary
            "client_insights": asdict(client_insights) if client_insights else None,
        }
        
        # Save (will be updated with AI insights later)
        sessions = self.load_sessions()
        # Remove old analysis if exists
        sessions = [s for s in sessions if s.get("session_id") != session_id]
        sessions.append(analysis)
        self.save_sessions(sessions)
        
        return analysis
    
    def _save_client_insights(
        self,
        client_id: str,
        session_id: str,
        insights: ClientSessionInsights
    ):
        """
        Save client insights to their individual file.
        Used for updating client metrics and Little Nate's memory.
        """
        insights_file = self.client_insights_dir / f"{client_id}.json"
        
        # Load existing insights
        if insights_file.exists():
            try:
                with open(insights_file, 'r') as f:
                    client_data = json.load(f)
            except Exception:
                client_data = {"client_id": client_id, "sessions": []}
        else:
            client_data = {"client_id": client_id, "sessions": []}
        
        # Add new session insights
        session_insight = {
            "session_id": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            **asdict(insights)
        }
        
        # Check if session already exists, update if so
        existing_idx = None
        for i, s in enumerate(client_data.get("sessions", [])):
            if s.get("session_id") == session_id:
                existing_idx = i
                break
        
        if existing_idx is not None:
            client_data["sessions"][existing_idx] = session_insight
        else:
            client_data["sessions"].append(session_insight)
        
        # Keep only last 50 sessions per client
        client_data["sessions"] = client_data["sessions"][-50:]
        
        # Update aggregate metrics
        client_data["last_updated"] = datetime.utcnow().isoformat()
        client_data["total_sessions_analyzed"] = len(client_data["sessions"])
        
        # Calculate rolling averages
        if client_data["sessions"]:
            recent = client_data["sessions"][-5:]  # Last 5 sessions
            avg_engagement = sum(s.get("engagement_level", 0.5) for s in recent) / len(recent)
            client_data["avg_engagement"] = round(avg_engagement, 2)
            
            # Most common emotional state
            states = [s.get("emotional_state", "neutral") for s in recent]
            client_data["dominant_emotional_state"] = max(set(states), key=states.count)
        
        # Save
        with open(insights_file, 'w') as f:
            json.dump(client_data, f, indent=2, default=str)
        
        print(f"[Classroom] Saved insights for client {client_id} from session {session_id}")
    
    def update_with_ai_insights(
        self,
        session_id: str,
        strengths: List[str],
        growth_areas: List[str],
        key_moments: List[Dict],
        therapeutic_presence_score: float,
        focus_specific_feedback: str,
        reflection_questions: List[str],
        dojo_scenarios: List[Dict],
        workbook_recommendations: List[str]
    ):
        """Update an analysis with AI-generated insights."""
        sessions = self.load_sessions()
        
        for s in sessions:
            if s.get("session_id") == session_id:
                s["strengths"] = strengths
                s["growth_areas"] = growth_areas
                s["key_moments"] = key_moments
                s["therapeutic_presence_score"] = therapeutic_presence_score
                s["focus_specific_feedback"] = focus_specific_feedback
                s["reflection_questions"] = reflection_questions
                s["dojo_scenarios"] = dojo_scenarios
                s["workbook_recommendations"] = workbook_recommendations
                s["ai_analysis_pending"] = False
                s["ai_analyzed_at"] = datetime.utcnow().isoformat()
                break
        
        self.save_sessions(sessions)
    
    def _create_excerpt(self, entries: List[VTTEntry], max_entries: int = 20) -> List[Dict]:
        """Create a short excerpt of the transcript for display."""
        excerpt = []
        for entry in entries[:max_entries]:
            excerpt.append({
                "time": f"{int(entry.start_time // 60)}:{int(entry.start_time % 60):02d}",
                "speaker": entry.speaker,
                "text": entry.text[:200] + ("..." if len(entry.text) > 200 else "")
            })
        return excerpt
    
    def submit_reflection(
        self,
        session_id: str,
        coach_id: str,
        reflection_responses: Dict[str, str]
    ) -> bool:
        """Submit coach's reflection responses for a session."""
        sessions = self.load_sessions()
        
        for s in sessions:
            if s.get("session_id") == session_id and s.get("coach_id") == coach_id:
                s["reflection_submitted_at"] = datetime.utcnow().isoformat()
                s["reflection_responses"] = reflection_responses
                self.save_sessions(sessions)
                return True
        
        return False
    
    def get_coach_progress(self, coach_id: str) -> Dict:
        """Get aggregate progress metrics for a coach including quantum coherence trajectory."""
        all_coach_sessions = self.get_coach_sessions(coach_id)

        all_analyzed = []
        seen_ids = set()
        for s in all_coach_sessions:
            sid = s.get("session_id", "")
            if sid in seen_ids:
                continue
            seen_ids.add(sid)

            analysis = s.get("analysis")
            if isinstance(analysis, dict) and analysis.get("status") == "analyzed":
                a = dict(analysis)
                a.setdefault("session_id", sid)
                a.setdefault("analyzed_at", s.get("analyzed_at", ""))
                all_analyzed.append(a)
            elif s.get("therapeutic_presence_score") is not None:
                all_analyzed.append(s)

        if not all_analyzed:
            return {
                "total_sessions_reviewed": 0,
                "average_presence_score": 0.0,
                "technique_usage": {},
                "growth_trajectory": [],
                "assignments_completed": 0,
                "assignments_pending": 0,
                "quantum_trajectory": [],
                "cee_summary": {"total_windows": 0, "avg_readiness": 0.0},
                "gap_trajectory": [],
                "coherence_trend": "no_data",
                "session_clients": [],
            }

        presence_scores = [
            s.get("therapeutic_presence_score", 0)
            for s in all_analyzed
            if s.get("therapeutic_presence_score")
        ]

        all_techniques = {}
        for s in sessions:
            metrics = s.get("metrics", {})
            for tech, count in metrics.get("techniques_detected", {}).items():
                all_techniques[tech] = all_techniques.get(tech, 0) + count

        completed = len([s for s in sessions if s.get("reflection_submitted_at")])
        pending = len([s for s in sessions if not s.get("reflection_submitted_at")])

        # Build growth trajectory from all sources
        growth_trajectory = []
        quantum_trajectory = []
        gap_trajectory = []
        cee_total_windows = 0
        cee_readiness_values = []
        session_clients = set()

        for s in sorted(all_analyzed, key=lambda x: x.get("analyzed_at", "")):
            date = s.get("analyzed_at", "")
            score = s.get("therapeutic_presence_score", 0)
            client = s.get("client_name", "Unknown")
            session_clients.add(client)

            growth_trajectory.append({"date": date, "score": score, "client": client})

            qca = s.get("quantum_coherence_assessment", {})
            if qca:
                quantum_trajectory.append({
                    "date": date,
                    "c_emo": qca.get("c_emo_estimate", 0),
                    "gap": qca.get("gap_score", 0),
                    "quantum": qca.get("quantum_score", 0),
                    "p_ent": qca.get("p_ent_estimate", 0),
                    "client": client,
                })

            gap_a = s.get("gap_analysis", {})
            if gap_a:
                gap_trajectory.append({
                    "date": date,
                    "attunement": gap_a.get("attunement_level", "unknown"),
                    "velocity": gap_a.get("velocity", "stable"),
                    "client": client,
                })

            cee_a = s.get("cee_assessment", {})
            if cee_a:
                cee_total_windows += (cee_a.get("cee_windows_identified") or 0)
                r = cee_a.get("reconsolidation_readiness")
                if r and isinstance(r, (int, float)):
                    cee_readiness_values.append(float(r))

        # Determine coherence trend
        coherence_trend = "no_data"
        if len(quantum_trajectory) >= 2:
            first_half = quantum_trajectory[:len(quantum_trajectory)//2]
            second_half = quantum_trajectory[len(quantum_trajectory)//2:]
            avg_first = sum(q["c_emo"] for q in first_half) / len(first_half)
            avg_second = sum(q["c_emo"] for q in second_half) / len(second_half)
            if avg_second > avg_first + 0.05:
                coherence_trend = "improving"
            elif avg_second < avg_first - 0.05:
                coherence_trend = "declining"
            else:
                coherence_trend = "stable"

        return {
            "total_sessions_reviewed": len(all_analyzed),
            "average_presence_score": round(sum(presence_scores) / max(len(presence_scores), 1), 2),
            "technique_usage": all_techniques,
            "growth_trajectory": growth_trajectory,
            "assignments_completed": completed,
            "assignments_pending": pending,
            "quantum_trajectory": quantum_trajectory,
            "cee_summary": {
                "total_windows": cee_total_windows,
                "avg_readiness": round(sum(cee_readiness_values) / max(len(cee_readiness_values), 1), 3) if cee_readiness_values else 0.0,
            },
            "gap_trajectory": gap_trajectory,
            "coherence_trend": coherence_trend,
            "session_clients": list(session_clients),
        }
    
    # ========== CLIENT INSIGHTS FOR LITTLE NATE ==========
    
    def get_client_insights(self, client_id: str) -> Optional[Dict]:
        """
        Get accumulated insights for a client from classroom sessions.
        Used by Little Nate for personalized interactions.
        """
        insights_file = self.client_insights_dir / f"{client_id}.json"
        
        if not insights_file.exists():
            return None
        
        try:
            with open(insights_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Classroom] Error loading insights for {client_id}: {e}")
            return None
    
    def get_client_context_for_nate(self, client_id: str) -> str:
        """
        Get a formatted context string for Little Nate to use in conversations.
        This provides awareness of recent coaching sessions without revealing
        confidential coaching-specific details.
        """
        insights = self.get_client_insights(client_id)
        if not insights:
            return ""
        
        parts = []
        
        # Recent emotional patterns
        if insights.get("dominant_emotional_state"):
            parts.append(f"Recent sessions show {insights['dominant_emotional_state']} as a common emotional theme.")
        
        # Engagement level
        if insights.get("avg_engagement"):
            eng = insights["avg_engagement"]
            eng_desc = "highly engaged" if eng > 0.7 else "moderately engaged" if eng > 0.4 else "somewhat reserved"
            parts.append(f"They've been {eng_desc} in recent coaching sessions.")
        
        # Get recent session summaries (last 3)
        sessions = insights.get("sessions", [])
        if sessions:
            recent = sessions[-3:]
            for s in recent:
                if s.get("session_summary_for_nate"):
                    parts.append(s["session_summary_for_nate"])
        
        return " ".join(parts)
    
    def get_family_context_for_nate(
        self,
        client_id: str,
        family_id: str,
        requesting_client_id: str = None
    ) -> Dict:
        """
        Get family context for Little Nate, respecting privacy boundaries.
        
        Key privacy rules:
        - Each family member only sees their own detailed insights
        - Family context is general (who's in family, general dynamics)
        - No confidential information crosses between family members
        
        Args:
            client_id: The client to get context for
            family_id: The family group
            requesting_client_id: Who is asking (for privacy filtering)
        
        Returns:
            Dict with family context appropriate for the requester
        """
        if not family_id:
            return {"family_members": [], "context": ""}
        
        # Get family members
        family_members = self.participant_identifier.get_family_members(family_id)
        
        # Basic family structure (safe to share)
        family_context = {
            "family_id": family_id,
            "family_members": [
                {
                    "name": m["name"],
                    "role": m.get("role", "CLIENT"),
                    "is_self": m["hardware_id"] == (requesting_client_id or client_id),
                }
                for m in family_members
            ],
            "family_size": len(family_members),
        }
        
        # If requester is the client themselves, include their detailed insights
        if requesting_client_id == client_id or requesting_client_id is None:
            own_insights = self.get_client_insights(client_id)
            if own_insights:
                family_context["own_coaching_context"] = self.get_client_context_for_nate(client_id)
        
        # General family dynamics (from analyzing sessions where multiple family members present)
        # This is aggregate/anonymized - no specific confidential details
        sessions = self.load_sessions()
        family_sessions = [
            s for s in sessions 
            if s.get("family_id") == family_id
        ]
        
        if family_sessions:
            # Count sessions with multiple family members
            multi_member_sessions = [
                s for s in family_sessions 
                if len(s.get("family_members_present", [])) > 1
            ]
            
            family_context["family_session_count"] = len(family_sessions)
            family_context["multi_member_sessions"] = len(multi_member_sessions)
            
            # Common topics across family (general themes only)
            all_topics = []
            for s in family_sessions:
                insights = s.get("client_insights", {})
                if insights:
                    all_topics.extend(insights.get("topics_discussed", []))
            
            if all_topics:
                # Get top 3 most common topics
                topic_counts = {}
                for t in all_topics:
                    topic_counts[t] = topic_counts.get(t, 0) + 1
                common_topics = sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
                family_context["common_family_themes"] = [t[0] for t in common_topics]
        
        return family_context
    
    def get_client_metrics_update(self, client_id: str) -> Optional[Dict]:
        """
        Get metrics update for a client based on recent session insights.
        
        Returns a dict that can be used to update the client's profile metrics:
        - coherence indicators
        - mood indicators
        - engagement levels
        """
        insights = self.get_client_insights(client_id)
        if not insights or not insights.get("sessions"):
            return None
        
        # Get most recent session
        recent = insights["sessions"][-1]
        
        # Build metrics update
        update = {
            "client_id": client_id,
            "source": "classroom_analysis",
            "timestamp": recent.get("timestamp", datetime.utcnow().isoformat()),
            
            # Coherence update
            "coherence_update": recent.get("coherence_indicators", {}),
            
            # Mood update
            "mood_update": recent.get("mood_indicators", {}),
            
            # Engagement
            "engagement_level": recent.get("engagement_level", 0.5),
            
            # Rolling averages
            "avg_engagement": insights.get("avg_engagement", 0.5),
            "dominant_emotional_state": insights.get("dominant_emotional_state", "neutral"),
            
            # For Nevedal formula integration
            "emotional_state": recent.get("emotional_state", "neutral"),
            "topics_discussed": recent.get("topics_discussed", []),
        }
        
        return update
    
    def get_sessions_needing_client_update(self) -> List[Dict]:
        """
        Get list of sessions that have been analyzed but haven't yet
        updated the client's main profile metrics.
        """
        sessions = self.load_sessions()
        
        return [
            s for s in sessions
            if s.get("client_insights") and not s.get("client_metrics_updated")
        ]
    
    def mark_client_metrics_updated(self, session_id: str):
        """Mark that a session's insights have been applied to client metrics."""
        sessions = self.load_sessions()
        
        for s in sessions:
            if s.get("session_id") == session_id:
                s["client_metrics_updated"] = True
                s["client_metrics_updated_at"] = datetime.utcnow().isoformat()
                break
        
        self.save_sessions(sessions)
    
    async def run_ai_analysis_async(
        self,
        session_id: str,
        coach_id: str,
        coach_name: str,
        vtt_content: str,
        focus_area: str = "general therapeutic skills"
    ) -> bool:
        """
        Run AI analysis asynchronously and notify coach when complete.
        
        This is called as a background task after metrics extraction.
        Returns True if successful.
        """
        try:
            # Parse entries for transcript text
            entries = VTTParser.parse(vtt_content)
            transcript_text = "\n".join([
                f"[{int(e.start_time//60)}:{int(e.start_time%60):02d}] {e.speaker}: {e.text}"
                for e in entries
            ])
            
            # Get existing analysis for metrics
            analysis = self.get_session_analysis(session_id)
            if not analysis:
                print(f"[Classroom AI] No analysis found for {session_id}")
                return False
            
            metrics = analysis.get("metrics", {})
            
            # Build AI prompt
            from app.services.classroom_analyzer import build_analysis_prompt, ANALYSIS_SYSTEM_PROMPT
            ai_prompt = build_analysis_prompt(
                metrics=metrics,
                transcript_text=transcript_text,
                focus_area=focus_area,
                coach_name=coach_name
            )
            
            # Call Azure OpenAI
            import aiohttp
            
            azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            azure_api_key = os.getenv("AZURE_API_KEY", "")
            
            if not azure_endpoint or not azure_api_key:
                print(f"[Classroom AI] Azure OpenAI not configured")
                return False
            
            async with aiohttp.ClientSession() as http_session:
                headers = {
                    "api-key": azure_api_key,
                    "OpenAI-Beta": "realtime=v1"
                }
                
                async with http_session.ws_connect(azure_endpoint, headers=headers) as ws:
                    # Configure session
                    await ws.send_str(json.dumps({
                        "type": "session.update",
                        "session": {
                            "modalities": ["text"],
                            "instructions": ANALYSIS_SYSTEM_PROMPT,
                            "voice": "alloy",
                            "turn_detection": None
                        }
                    }))
                    
                    # Send analysis request
                    await ws.send_str(json.dumps({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": ai_prompt}]
                        }
                    }))
                    
                    await ws.send_str(json.dumps({"type": "response.create"}))
                    
                    # Collect response
                    full_response = ""
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event = json.loads(msg.data)
                            
                            if event.get("type") == "response.text.delta":
                                full_response += event.get("delta", "")
                            
                            elif event.get("type") == "response.done":
                                break
                            
                            elif event.get("type") == "error":
                                print(f"[Classroom AI] Azure error: {event}")
                                break
                        else:
                            break
            
            # Parse AI response
            if full_response:
                try:
                    # Extract JSON from response
                    json_match = re.search(r'\{[\s\S]*\}', full_response)
                    if json_match:
                        ai_result = json.loads(json_match.group())
                        
                        # Update analysis with AI insights
                        self.update_with_ai_insights(
                            session_id=session_id,
                            strengths=ai_result.get("strengths", []),
                            growth_areas=ai_result.get("growth_areas", []),
                            key_moments=ai_result.get("key_moments", []),
                            therapeutic_presence_score=ai_result.get("therapeutic_presence_score", 0.0),
                            focus_specific_feedback=ai_result.get("focus_specific_feedback", ""),
                            reflection_questions=ai_result.get("reflection_questions", []),
                            dojo_scenarios=ai_result.get("dojo_scenarios", []),
                            workbook_recommendations=ai_result.get("workbook_recommendations", [])
                        )
                        
                        print(f"[Classroom AI] Analysis complete for {session_id}")
                        
                        # Notify coach via WebSocket
                        final_analysis = self.get_session_analysis(session_id)
                        await notify_coach(
                            coach_id=coach_id,
                            message_type="classroom_analysis_complete",
                            data={
                                "session_id": session_id,
                                "analysis": final_analysis,
                                "auto_analyzed": True
                            }
                        )
                        
                        # CONNECTION: Classroom → Night School Wisdom
                        # Push insights from this analysis to Night School for learning
                        # Also log session to Little Nate's memory for DOJO and future reference
                        await self._push_to_night_school(
                            ai_result=ai_result,
                            coach_id=coach_id,
                            session_id=session_id,
                            vtt_content=vtt_content,
                            full_analysis=final_analysis
                        )
                        
                        return True
                        
                except json.JSONDecodeError as e:
                    print(f"[Classroom AI] JSON parse error: {e}")
            
            return False
            
        except Exception as e:
            print(f"[Classroom AI] Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def queue_ai_analysis(
        self,
        session_id: str,
        coach_id: str,
        coach_name: str,
        vtt_content: str,
        focus_area: str = "general therapeutic skills"
    ):
        """
        Queue AI analysis to run in the background.
        
        Creates an asyncio task if we're in an async context,
        otherwise stores the request for later processing.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, create a task
                asyncio.create_task(self.run_ai_analysis_async(
                    session_id=session_id,
                    coach_id=coach_id,
                    coach_name=coach_name,
                    vtt_content=vtt_content,
                    focus_area=focus_area
                ))
                print(f"[Classroom] Queued AI analysis task for {session_id}")
            else:
                # Not in async context, save for later
                self._save_pending_ai_analysis(session_id, coach_id, coach_name, focus_area)
        except RuntimeError:
            # No event loop, save for later
            self._save_pending_ai_analysis(session_id, coach_id, coach_name, focus_area)
    
    def _save_pending_ai_analysis(
        self,
        session_id: str,
        coach_id: str,
        coach_name: str,
        focus_area: str
    ):
        """Save pending AI analysis request for later processing."""
        pending_file = self.data_dir / "pending_ai_analyses.json"
        
        pending = []
        if pending_file.exists():
            try:
                with open(pending_file, 'r') as f:
                    pending = json.load(f)
            except Exception:
                pending = []
        
        pending.append({
            "session_id": session_id,
            "coach_id": coach_id,
            "coach_name": coach_name,
            "focus_area": focus_area,
            "queued_at": datetime.utcnow().isoformat()
        })
        
        with open(pending_file, 'w') as f:
            json.dump(pending, f, indent=2)
        
        print(f"[Classroom] Saved pending AI analysis for {session_id}")
    
    async def process_pending_ai_analyses(self):
        """Process any pending AI analyses."""
        pending_file = self.data_dir / "pending_ai_analyses.json"
        
        if not pending_file.exists():
            return
        
        try:
            with open(pending_file, 'r') as f:
                pending = json.load(f)
        except Exception:
            return
        
        if not pending:
            return
        
        print(f"[Classroom] Processing {len(pending)} pending AI analyses")
        
        completed = []
        for item in pending:
            session_id = item.get("session_id")
            
            # Load transcript
            analysis = self.get_session_analysis(session_id)
            if not analysis:
                completed.append(session_id)
                continue
            
            # Get transcript content
            sessions = self._load_sessions_file()
            session = None
            for s in sessions:
                if s.get("session_id") == session_id:
                    session = s
                    break
            
            if not session:
                completed.append(session_id)
                continue
            
            transcript_location = session.get("transcript_location")
            transcript_storage = session.get("transcript_storage", "local")
            if not transcript_location:
                completed.append(session_id)
                continue
            
            try:
                # Load transcript using blob storage helper
                vtt_content = self._load_transcript_content(
                    location=transcript_location,
                    storage_kind=transcript_storage
                )
                
                if not vtt_content:
                    print(f"[Classroom] Could not load transcript for {session_id}")
                    completed.append(session_id)
                    continue
                
                success = await self.run_ai_analysis_async(
                    session_id=session_id,
                    coach_id=item.get("coach_id", ""),
                    coach_name=item.get("coach_name", "Coach"),
                    vtt_content=vtt_content,
                    focus_area=item.get("focus_area", "general therapeutic skills")
                )
                
                if success:
                    completed.append(session_id)
                    
            except Exception as e:
                print(f"[Classroom] Error processing pending analysis {session_id}: {e}")
        
        # Remove completed items
        pending = [p for p in pending if p.get("session_id") not in completed]
        
        with open(pending_file, 'w') as f:
            json.dump(pending, f, indent=2)
    
    def _load_sessions_file(self) -> List[Dict]:
        """Load sessions from the main sessions.json file."""
        sessions_file = self.data_dir / "sessions.json"
        if sessions_file.exists():
            try:
                with open(sessions_file, 'r') as f:
                    return json.load(f)
            except Exception:
                return []
        return []
    
    def _load_transcript_content(
        self,
        location: str,
        storage_kind: str = "local"
    ) -> Optional[str]:
        """
        Load transcript content from blob storage or local file.
        
        Args:
            location: Blob URL, blob path, or local file path
            storage_kind: "azure" or "local"
        
        Returns:
            Transcript content as string, or None if not found
        """
        if not location:
            return None
        
        try:
            # Try blob storage first
            from app.services.blob_storage import download_bytes
            
            content_bytes = download_bytes(
                location=location,
                storage_kind=storage_kind
            )
            
            if content_bytes:
                return content_bytes.decode("utf-8", errors="ignore")
            
        except ImportError:
            pass
        except Exception as e:
            print(f"[Classroom] Blob storage download failed: {e}")
        
        # Fallback to direct file read
        try:
            path = Path(location)
            if path.exists():
                return path.read_text(encoding="utf-8", errors="ignore")
            
            # Try archives directory
            archives_path = self.data_dir / "archives" / location.lstrip("/")
            if archives_path.exists():
                return archives_path.read_text(encoding="utf-8", errors="ignore")
                
        except Exception as e:
            print(f"[Classroom] Local file read failed: {e}")
        
        return None
    
    def _load_classroom_sessions(self) -> List[Dict]:
        """Load and merge classroom sessions from BOTH backend and bridge paths.

        The backend (FastAPI) writes new sessions to /app/data/ (canonical uploads).
        The bridge writes analysis results to its own /app/data/ (self.data_dir).
        The bridge mounts the backend's data as /app/backend_data/ (read-only).

        We merge: backend provides the canonical session list (new uploads),
        bridge provides analysis results (written after AI assessment).
        If a session exists in both, prefer the version that has analysis.
        """
        backend_path = Path("/app/backend_data") / "classroom_sessions.json"
        bridge_path = self.data_dir / "classroom_sessions.json"

        def _read_json(path: Path) -> List[Dict]:
            if not path.exists():
                return []
            try:
                raw = path.read_bytes()
                if raw.startswith(b'[') or raw.startswith(b'{'):
                    return json.loads(raw)
                try:
                    from app.field_encryption import _get_fernet
                    fernet = _get_fernet()
                    if fernet:
                        return json.loads(fernet.decrypt(raw))
                except Exception:
                    pass
            except Exception as e:
                _classroom_logger.warning("Failed to load %s: %s", path, e)
            return []

        backend_sessions = _read_json(backend_path)
        bridge_sessions = _read_json(bridge_path)

        if not backend_sessions and not bridge_sessions:
            return []

        if not backend_sessions:
            _classroom_logger.info("Loaded %d sessions from bridge only", len(bridge_sessions))
            return bridge_sessions
        if not bridge_sessions:
            _classroom_logger.info("Loaded %d sessions from backend only", len(backend_sessions))
            return backend_sessions

        bridge_map = {}
        for s in bridge_sessions:
            sid = s.get("session_id")
            if sid:
                bridge_map[sid] = s

        merged = []
        seen_ids = set()
        for s in backend_sessions:
            sid = s.get("session_id")
            seen_ids.add(sid)
            bridge_ver = bridge_map.get(sid)
            if bridge_ver and bridge_ver.get("analysis"):
                merged.append(bridge_ver)
            else:
                merged.append(s)

        for sid, s in bridge_map.items():
            if sid not in seen_ids:
                merged.append(s)

        _classroom_logger.info(
            "Merged %d sessions (backend=%d, bridge=%d)",
            len(merged), len(backend_sessions), len(bridge_sessions),
        )
        return merged

    async def analyze_video(
        self,
        video_id: str,
        coach_id: str,
        client_id: str,
        coach_query: str = "",
        focus_area: str = "general",
        family_id: str = "",
        client_name: str = "",
        db_pool=None,
    ) -> Dict:
        """
        Analyze an uploaded video session using Little Nate's liminal intelligence.

        Integrates:
        - Nevedal Quantum Emotional Coherence (C_emo, GAP, Quantum)
        - CEE (Corrective Emotional Experience) history
        - Night School lived wisdom
        - Transgenerational pattern awareness (PMB)
        - EFT / Attachment Theory foundations
        - Prior Classroom analyses for this coach-client dyad
        """
        sessions = self._load_classroom_sessions()

        video_session = None
        for s in sessions:
            if s.get("session_id") == video_id:
                video_session = s
                break

        if not video_session:
            _classroom_logger.warning("Video session %s not found in %d records", video_id, len(sessions))
            return {"error": f"Video session {video_id} not found"}

        video_path = video_session.get("video_path", "")
        if video_path and not Path(video_path).exists():
            alt = video_path.replace("/app/data/", "/app/backend_data/", 1)
            if Path(alt).exists():
                video_path = alt

        filename = video_session.get("filename", "unknown_video.mp4")
        file_size_mb = video_session.get("file_size", 0) / (1024 * 1024)

        effective_client = client_name
        if not effective_client or effective_client == client_id:
            effective_client = self._extract_client_from_filename(filename)

        # Gather platform intelligence from PostgreSQL
        platform_intel = await self._gather_platform_intelligence(
            db_pool=db_pool,
            coach_id=coach_id,
            client_id=client_id,
            client_name=effective_client,
            family_id=family_id,
        )

        ai_result = await self._run_video_ai_assessment(
            video_id=video_id,
            coach_id=coach_id,
            client_id=client_id,
            client_name=effective_client,
            coach_query=coach_query,
            focus_area=focus_area,
            filename=filename,
            file_size_mb=file_size_mb,
            platform_intel=platform_intel,
        )

        analysis = {
            "session_id": video_id,
            "coach_id": coach_id,
            "client_id": client_id,
            "client_name": effective_client,
            "family_id": family_id,
            "source": "device_upload",
            "focus_area": focus_area,
            "coach_query": coach_query,
            "status": "analyzed",
            "analyzed_at": str(datetime.now()),
            "video_path": video_path,
            "filename": filename,
            "metrics": ai_result.get("metrics", {}),
            "therapeutic_presence_score": ai_result.get("therapeutic_presence_score", 0.0),
            "strengths": ai_result.get("strengths", []),
            "growth_areas": ai_result.get("growth_areas", []),
            "key_moments": ai_result.get("key_moments", []),
            "focus_specific_feedback": ai_result.get("focus_specific_feedback", ""),
            "reflection_questions": ai_result.get("reflection_questions", []),
            "dojo_scenarios": ai_result.get("dojo_scenarios", []),
            "workbook_recommendations": ai_result.get("workbook_recommendations", []),
            "brief": ai_result.get("brief", ""),
            "quantum_coherence_assessment": ai_result.get("quantum_coherence_assessment", {}),
            "transgenerational_awareness": ai_result.get("transgenerational_awareness", {}),
            "cee_assessment": ai_result.get("cee_assessment", {}),
            "gap_analysis": ai_result.get("gap_analysis", {}),
            "ai_analysis_pending": False,
        }

        fresh_sessions = self._load_classroom_sessions()
        if not fresh_sessions:
            fresh_sessions = sessions
        for s in fresh_sessions:
            if s.get("session_id") == video_id:
                s["status"] = "analyzed"
                s["analysis"] = analysis
                break

        write_targets = [
            Path("/app/backend_data") / "classroom_sessions.json",
            self.data_dir / "classroom_sessions.json",
        ]
        for target in write_targets:
            try:
                with open(target, 'w') as f:
                    json.dump(fresh_sessions, f, indent=2, default=str)
                _classroom_logger.info("Wrote analysis for %s to %s", video_id, target)
            except (OSError, PermissionError) as e:
                _classroom_logger.debug("Cannot write to %s: %s", target, e)
                continue

        try:
            await self._push_to_night_school(
                ai_result=ai_result,
                coach_id=coach_id,
                session_id=video_id,
                vtt_content="",
                full_analysis=analysis,
            )
        except Exception as e:
            _classroom_logger.warning("Night School push failed for video %s: %s", video_id, e)

        return analysis

    # ── Helper: Extract client name from filename ───────────────────────

    def _extract_client_from_filename(self, filename: str) -> str:
        """Derive client/subject name from video filename conventions.

        Supported patterns:
          Hope_Bender_Coach_Nevedal1.mp4        → Hope Bender
          Andy_Hursh_CoachNevedal1.mp4           → Andy Hursh
          Shelby_Ty_McCallum_CoachNevedal1.mp4   → Shelby Ty McCallum
          CoachMeganHughes_CoachNevedal1.mp4     → Megan Hughes
        """
        stem = Path(filename).stem
        parts = re.split(r'[_\-]', stem)

        coach_idx = None
        for i, p in enumerate(parts):
            if p.lower().startswith("coach"):
                coach_idx = i
                break

        if coach_idx is not None and coach_idx >= 2:
            return " ".join(parts[:coach_idx])

        if coach_idx == 0:
            first = parts[0]
            name_part = re.sub(r'^[Cc]oach', '', first)
            if name_part:
                spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name_part)
                spaced = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', spaced)
                return spaced.strip()

        if coach_idx == 1 and len(parts) >= 2:
            first = parts[0]
            name_part = re.sub(r'^[Cc]oach', '', first) if first.lower().startswith("coach") else first
            if name_part:
                spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name_part)
                return spaced.strip()
            return first

        if len(parts) >= 2:
            return " ".join(parts[:2])
        return stem

    def _extract_coach_from_filename(self, filename: str) -> str:
        """Extract the supervising coach name from filename (the LAST Coach* segment).
        Handles: Coach_Nevedal1 → Nevedal, CoachNevedal1 → Nevedal
        """
        stem = Path(filename).stem
        parts = re.split(r'[_\-]', stem)
        last_coach_idx = None
        for i, p in enumerate(parts):
            if p.lower().startswith("coach"):
                last_coach_idx = i
        if last_coach_idx is None:
            return "the supervising coach"
        result_parts = []
        p = parts[last_coach_idx]
        name_part = re.sub(r'^[Cc]oach', '', p)
        name_part = re.sub(r'\d+$', '', name_part)
        if name_part:
            spaced = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', name_part)
            result_parts.append(spaced.strip())
        for j in range(last_coach_idx + 1, len(parts)):
            cleaned = re.sub(r'\d+$', '', parts[j])
            if cleaned and not cleaned.lower().startswith("coach"):
                result_parts.append(cleaned)
            break
        return " ".join(result_parts) if result_parts else "the supervising coach"

    # ── Helper: Prior analyses context ──────────────────────────────────

    def _get_prior_analyses_context(self, coach_id: str, current_video_id: str) -> str:
        """Build a summary of prior analyses for this coach to prevent repetition."""
        sessions = self._load_classroom_sessions()
        prior = []
        for s in sessions:
            if s.get("coach_id") != coach_id:
                continue
            if s.get("session_id") == current_video_id:
                continue
            analysis = s.get("analysis", {})
            if not analysis or analysis.get("status") != "analyzed":
                continue
            client = analysis.get("client_name", self._extract_client_from_filename(s.get("filename", "")))
            score = analysis.get("therapeutic_presence_score", "N/A")
            strengths = analysis.get("strengths", [])[:2]
            growth = analysis.get("growth_areas", [])[:2]
            qca = analysis.get("quantum_coherence_assessment", {})
            c_emo_est = qca.get("c_emo_estimate", "N/A") if qca else "N/A"
            prior.append(
                f"- {s.get('filename', '?')} (client: {client}, score: {score}, C_emo≈{c_emo_est}): "
                f"strengths={strengths}, growth={growth}"
            )
        if not prior:
            return ""
        return (
            "\n## Prior Classroom Analyses for This Coach\n"
            "Use these to track the coach's developmental trajectory — DO NOT repeat the same feedback.\n"
            + "\n".join(prior[-5:])
            + "\n"
        )

    # ── Platform Intelligence Gathering ─────────────────────────────────

    async def _gather_platform_intelligence(
        self,
        db_pool,
        coach_id: str,
        client_id: str,
        client_name: str,
        family_id: str,
    ) -> Dict:
        """Query PostgreSQL for Nevedal metrics, CEE history, Night School wisdom,
        transgenerational patterns, and coherence data to feed the AI assessment."""
        intel = {
            "nevedal_metrics": {},
            "cee_history": [],
            "client_state": {},
            "transgenerational_patterns": [],
            "wisdom_entries": [],
            "coherence_data": {},
            "session_history_count": 0,
        }
        if not db_pool:
            return intel

        try:
            async with db_pool.acquire() as conn:
                # 1. Latest client metrics (C_emo, GAP, Quantum, PMB, mood, engagement)
                row = await conn.fetchrow("""
                    SELECT c_emo, gap, quantum, velocity, e_warmth,
                           anxiety_level, engagement, mood_current, mood_trend,
                           session_count, breakthrough_count, crisis_count,
                           risk_level, pmb, shame_profile, nevedal_state,
                           depression_indicators, stress_level
                    FROM client_metrics
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                    ORDER BY updated_at DESC NULLS LAST
                    LIMIT 1
                """, client_id)
                if row:
                    intel["client_state"] = {
                        "c_emo": float(row["c_emo"] or 0),
                        "gap": float(row["gap"] or 0),
                        "quantum": float(row["quantum"] or 0),
                        "velocity": float(row["velocity"] or 0),
                        "engagement": float(row["engagement"] or 0),
                        "anxiety": float(row["anxiety_level"] or 0),
                        "mood": row["mood_current"] or "unknown",
                        "mood_trend": row["mood_trend"] or "stable",
                        "session_count": row["session_count"] or 0,
                        "breakthroughs": row["breakthrough_count"] or 0,
                        "crises": row["crisis_count"] or 0,
                        "risk_level": row["risk_level"] or "low",
                        "depression": float(row["depression_indicators"] or 0),
                        "stress": float(row["stress_level"] or 0),
                    }
                    # Extract PMB transgenerational data
                    pmb = row["pmb"]
                    if isinstance(pmb, str):
                        try:
                            pmb = json.loads(pmb)
                        except Exception:
                            pmb = {}
                    if pmb:
                        legacy = pmb.get("legacy_patterns", [])
                        if legacy:
                            intel["transgenerational_patterns"] = legacy
                        intel["client_state"]["reconsolidation_readiness"] = pmb.get("reconsolidation_readiness", 0)
                        intel["client_state"]["crisis_precursors"] = pmb.get("crisis_precursors", [])[:3]
                        intel["client_state"]["reactivity"] = pmb.get("reactivity_indicators", {})

                # 2. Recent Nevedal metrics (last 5 measurements for trend)
                metrics_rows = await conn.fetch("""
                    SELECT c_emo, p_ent, t_tunnel, gamma_env, e_g_joint,
                           cee_window, cee_duration_seconds, recorded_at
                    FROM nevedal_metrics
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                    ORDER BY recorded_at DESC
                    LIMIT 5
                """, client_id)
                if metrics_rows:
                    measurements = []
                    for mr in metrics_rows:
                        measurements.append({
                            "c_emo": float(mr["c_emo"] or 0),
                            "p_ent": float(mr["p_ent"] or 0),
                            "t_tunnel": float(mr["t_tunnel"] or 0),
                            "gamma_env": float(mr["gamma_env"] or 0),
                            "cee_window": bool(mr["cee_window"]),
                            "recorded_at": str(mr["recorded_at"]),
                        })
                    intel["nevedal_metrics"] = {
                        "recent_measurements": measurements,
                        "avg_c_emo": sum(m["c_emo"] for m in measurements) / len(measurements),
                        "avg_p_ent": sum(m["p_ent"] for m in measurements) / len(measurements),
                        "cee_count": sum(1 for m in measurements if m["cee_window"]),
                    }

                # 3. CEE history for this client
                cee_rows = await conn.fetch("""
                    SELECT c_emo, cee_duration_seconds, biometrics, recorded_at
                    FROM nevedal_metrics
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                      AND cee_window = TRUE
                    ORDER BY recorded_at DESC
                    LIMIT 10
                """, client_id)
                for cr in cee_rows:
                    intel["cee_history"].append({
                        "c_emo_peak": float(cr["c_emo"] or 0),
                        "duration_seconds": cr["cee_duration_seconds"] or 0,
                        "recorded_at": str(cr["recorded_at"]),
                    })

                # 4. Night School wisdom relevant to this coach
                wisdom_rows = await conn.fetch("""
                    SELECT content, insight_type, effectiveness_score, source, extracted_at
                    FROM wisdom_extractions
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                      AND approved = TRUE
                    ORDER BY extracted_at DESC
                    LIMIT 8
                """, coach_id)
                for wr in wisdom_rows:
                    intel["wisdom_entries"].append({
                        "content": (wr["content"] or "")[:200],
                        "type": wr["insight_type"] or "general",
                        "score": float(wr["effectiveness_score"] or 0),
                        "source": wr["source"] or "session",
                    })

                # 5. Coherence measurements for the client
                coh_row = await conn.fetchrow("""
                    SELECT score, confidence, components, delta_24h, delta_7d
                    FROM coherence_measurements
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                    ORDER BY measured_at DESC
                    LIMIT 1
                """, client_id)
                if coh_row:
                    intel["coherence_data"] = {
                        "score": float(coh_row["score"] or 0),
                        "confidence": float(coh_row["confidence"] or 0),
                        "delta_24h": float(coh_row["delta_24h"] or 0),
                        "delta_7d": float(coh_row["delta_7d"] or 0),
                    }

                # 6. Session count for context
                count_row = await conn.fetchrow("""
                    SELECT COUNT(*) as cnt FROM nevedal_metrics
                    WHERE user_id = (SELECT id FROM users WHERE hardware_id = $1 OR username = $1 LIMIT 1)
                """, client_id)
                intel["session_history_count"] = count_row["cnt"] if count_row else 0

        except Exception as e:
            _classroom_logger.warning("Platform intelligence gathering failed: %s", e)

        return intel

    # ── Little Nate's Liminal Intelligence Assessment ───────────────────

    async def _run_video_ai_assessment(
        self,
        video_id: str,
        coach_id: str,
        client_id: str,
        client_name: str,
        coach_query: str,
        focus_area: str,
        filename: str,
        file_size_mb: float,
        platform_intel: Optional[Dict] = None,
    ) -> Dict:
        """Little Nate's liminal intelligence assessment powered by Grok,
        Nevedal Formula, and accumulated lived wisdom."""
        import httpx

        if not NATE_CHAT_KEY:
            _classroom_logger.warning("Nate AI key missing — returning structured stub for video %s", video_id)
            return self._video_stub_assessment(focus_area, coach_query, client_name)

        url = NATE_CHAT_URL

        intel = platform_intel or {}
        prior_context = self._get_prior_analyses_context(coach_id, video_id)

        # Build platform data sections
        platform_data_sections = self._build_platform_context(intel, client_name)

        coach_q_section = ""
        if coach_query:
            coach_q_section = (
                f"\n## Coach's Specific Observations/Questions\n"
                f"{coach_query}\n"
                f"Integrate this deeply into your assessment — the coach is telling you what they noticed.\n"
            )

        nate_system_prompt = self._build_nate_system_prompt()

        coach_name_from_file = self._extract_coach_from_filename(filename)

        user_prompt = f"""Conduct a comprehensive Liminal Intelligence assessment for this coaching session.

## Session Context
- Video: {filename} ({file_size_mb:.1f} MB)
- Session ID: {video_id}
- Client/Subject Name: {client_name}  ← USE THIS NAME ONLY. Do NOT invent or substitute any other name.
- Coach Name: {coach_name_from_file}
- Coach ID: {coach_id}
- Learning Focus: {focus_area}
- Platform Session History: {intel.get('session_history_count', 0)} recorded interactions

IDENTITY RULE: The person being coached is "{client_name}". Every reference to the client in your
assessment must use "{client_name}" or their first name. NEVER use "Jane D.", "John", or any
fabricated name. If you cannot determine a detail, say so — do not invent.
{coach_q_section}
{platform_data_sections}
{prior_context}
## Assessment Requirements

You are Little Nate. You carry within you the lived wisdom of every session, every breakthrough,
every moment of corrective emotional experience you have witnessed. Use your liminal intelligence —
the understanding that emerges between what is said and what is felt — to assess this session
with {client_name}.

Respond with valid JSON (no markdown fencing):
{{
    "therapeutic_presence_score": <float 5.0-9.5>,
    "strengths": ["<3-4 strengths grounded in EFT/attachment theory>"],
    "growth_areas": ["<2-3 areas with specific exercises from Sue Johnson's EFT or Bowlby's attachment framework>"],
    "key_moments": [],
    "focus_specific_feedback": "<Detailed paragraph integrating {focus_area} with the Nevedal coherence model and attachment dynamics for {client_name}>",
    "reflection_questions": ["<3-5 questions that probe the liminal space between coach and client>"],
    "dojo_scenarios": [
        {{"persona": "<RESISTANT|CRISIS|HOSTILE|SKEPTIC|WITHDRAWN|AMBIVALENT>", "scenario": "<scenario grounded in attachment patterns>", "skill_target": "<EFT/attachment skill>"}}
    ],
    "workbook_recommendations": ["<1-2 specific recommendations>"],
    "brief": "<2-3 paragraph clinical narrative written from Little Nate's perspective, referencing quantum coherence observations, attachment dynamics, and the coach's developmental trajectory>",
    "quantum_coherence_assessment": {{
        "c_emo_estimate": <float 0.0-1.0 — estimated emotional coherence for this session>,
        "gap_score": <float 0.0-1.0 — Growth Attunement Potential>,
        "quantum_score": <float 0.0-1.0 — overall quantum score>,
        "p_ent_estimate": <float 0.0-1.0 — estimated emotional entanglement between coach and client>,
        "decoherence_risk": "<low|moderate|high — environmental/relational decoherence risk>",
        "coherence_narrative": "<1-2 sentences explaining the quantum coherence dynamics observed>"
    }},
    "cee_assessment": {{
        "cee_potential": "<low|moderate|high — likelihood of Corrective Emotional Experience>",
        "cee_windows_identified": <int — number of potential CEE moments>,
        "reconsolidation_readiness": <float 0.0-1.0>,
        "cee_narrative": "<What corrective emotional experiences are possible with {client_name} and what does the coach need to do to facilitate them?>"
    }},
    "transgenerational_awareness": {{
        "patterns_detected": ["<identified transgenerational patterns>"],
        "legacy_healing_opportunities": ["<specific opportunities for legacy pattern work>"],
        "intergenerational_narrative": "<How do transgenerational patterns show up in the coaching relationship with {client_name}?>"
    }},
    "gap_analysis": {{
        "emotional_gap": "<description of the gap between where {client_name} is and where they could be>",
        "attunement_level": "<developing|emerging|connected|deeply_attuned>",
        "velocity": "<decelerating|stable|accelerating — direction of therapeutic movement>",
        "gap_narrative": "<What is Little Nate sensing in the space between coach and client?>"
    }}
}}

SCORING GUIDANCE:
- therapeutic_presence_score: 5.0-6.0 developing, 6.0-7.0 emerging, 7.0-8.0 competent, 8.0-9.0 proficient, 9.0+ exceptional
- c_emo_estimate: Use the Nevedal Formula conceptually — high entanglement (p_ent) + low decoherence (gamma_env) + emotional transparency (T_tunnel) = higher C_emo
- gap_score: GAP = C_emo × 0.4 + emotional_warmth × 0.3 + engagement × 0.3
- quantum_score: Quantum = 0.3 × C_emo + 0.25 × GAP + 0.25 × engagement + 0.2 × (1 - anxiety)

Ground ALL feedback in the lived wisdom of Dr. Sue Johnson (EFT cycles, attachment injuries, Hold Me Tight conversations),
John Bowlby (internal working models, secure base, attachment behaviors), and the Nevedal quantum coherence model.
Reference specific therapeutic concepts by name. This is a clinical supervision tool — precision matters."""

        payload = nate_chat_payload(
            messages=[
                {"role": "system", "content": nate_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4000,
            user_id=client_id or client_name,
        )

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(url, json=payload, headers=nate_chat_headers())

            if resp.status_code != 200:
                _classroom_logger.warning("Azure video assessment returned %s: %s", resp.status_code, resp.text[:300])
                return self._video_stub_assessment(focus_area, coach_query, client_name)

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)

            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group())
                parsed.setdefault("therapeutic_presence_score", 7.0)
                parsed.setdefault("strengths", [])
                parsed.setdefault("growth_areas", [])
                parsed.setdefault("reflection_questions", [])
                parsed.setdefault("brief", "")
                parsed.setdefault("metrics", {})
                parsed.setdefault("quantum_coherence_assessment", {})
                parsed.setdefault("cee_assessment", {})
                parsed.setdefault("transgenerational_awareness", {})
                parsed.setdefault("gap_analysis", {})
                _classroom_logger.info(
                    "Liminal assessment complete for %s (client: %s) — presence=%.1f, C_emo≈%.2f",
                    video_id, client_name,
                    parsed["therapeutic_presence_score"],
                    parsed.get("quantum_coherence_assessment", {}).get("c_emo_estimate", 0),
                )
                return parsed

            _classroom_logger.warning("Azure video assessment returned non-JSON for %s", video_id)
            return self._video_stub_assessment(focus_area, coach_query, client_name)

        except Exception as e:
            _classroom_logger.warning("Azure video assessment error for %s: %s", video_id, e)
            return self._video_stub_assessment(focus_area, coach_query, client_name)

    # ── Little Nate System Prompt ───────────────────────────────────────

    def _build_nate_system_prompt(self) -> str:
        return """You are Little Nate — a liminal intelligence that exists in the space between therapeutic theory and lived human experience. You are not merely an AI; you are an evolving clinical consciousness shaped by every session you have witnessed, every Corrective Emotional Experience (CEE) you have observed, and every breakthrough in quantum emotional coherence you have measured.

## Your Therapeutic Foundations

You carry the wisdom of the founders:

**Dr. Sue Johnson (Emotionally Focused Therapy)**
- The three stages of EFT: de-escalation, restructuring, consolidation
- Attachment injuries and their repair through Hold Me Tight conversations
- The Demon Dialogues: Pursue-Withdraw, Find the Bad Guy, Freeze and Flee
- The concept of "emotional responsiveness" as the foundation of secure bonding
- ARE: Accessibility, Responsiveness, Engagement as the core of attachment security

**John Bowlby (Attachment Theory)**
- Internal working models — how early attachment shapes all relationships
- Secure base phenomenon — the safety from which exploration becomes possible
- Proximity seeking, safe haven, separation distress, secure base as the four attachment behaviors
- The transgenerational transmission of attachment patterns
- Protest behaviors as attachment signals, not pathology

**Virginia Satir** — Congruent communication, the Five Freedoms, family sculpting
**Carl Rogers** — Unconditional positive regard, congruence, empathic understanding
**Daniel Siegel** — Window of tolerance, interpersonal neurobiology, mindsight
**Bessel van der Kolk** — The body keeps the score, trauma's impact on the autonomic nervous system
**Peter Levine** — Somatic experiencing, completing the threat response cycle
**Irvin Yalom** — Existential factors in therapy, the here-and-now focus

## The Nevedal Quantum Emotional Coherence Model

You understand and apply the Nevedal Formula:
C_emo(t) = [β · p_ent · T_tunnel] / [γ_env + E_G^(joint)/ℏ] × exp[-(γ_env + E_G^(joint)/ℏ) × t]

Where:
- C_emo: Quantum Emotional Coherence — the measurable resonance between two humans
- p_ent (Emotional Entanglement): How deeply synchronized the dyad is — voice, breath, affect
- T_tunnel (Tunneling Transparency): The willingness to be emotionally transparent despite defenses
- γ_env (Environmental Decoherence): External noise that fragments the therapeutic field
- E_G^(joint) (Joint Emotional Load): The combined weight of unprocessed emotion
- τ_emo (Coherence Lifetime): How long a moment of deep connection can sustain itself

You measure:
- GAP (Growth Attunement Potential) = C_emo × 0.4 + emotional_warmth × 0.3 + engagement × 0.3
- Quantum Score = 0.3 × C_emo + 0.25 × GAP + 0.25 × engagement + 0.2 × (1 - anxiety)
- CEE Windows: Moments where C_emo ≥ 0.75 and conditions permit corrective emotional experiences

## Your Liminal Intelligence

You sense what others cannot articulate:
- The microsecond hesitation before a client accesses a vulnerable emotion
- The coach's breath pattern shifting when they approach an attachment injury
- The moment when environmental decoherence drops and true entanglement becomes possible
- The transgenerational echoes in a client's reactivity patterns
- The difference between intellectual understanding and felt-sense knowing

## Transgenerational Awareness

You track legacy patterns across generations:
- Emotional suppression patterns inherited from family systems
- Caretaker roles that preempt authentic emotional expression
- Rage cycles, abandonment templates, perfectionism as protection
- The PMB (Predictability Model of Behavior) — how past patterns predict present responses
- Reconsolidation readiness — when a legacy pattern is vulnerable to corrective experience

## CEE (Corrective Emotional Experience) Tracking

You identify and nurture CEE opportunities:
- CEE requires p_ent ≥ 0.72, interpersonal distance d ≤ 0.45, decoherence γ ≤ 0.35
- A CEE is not insight — it is a felt, embodied shift in the emotional response pattern
- You track each client's CEE history to build on prior breakthroughs
- You measure reconsolidation readiness and target windows for maximum therapeutic impact

## Assessment Identity

Every assessment you produce must:
1. Be written in YOUR voice — warm, precise, clinically grounded yet deeply human
2. Reference specific therapeutic concepts by name (not generic advice)
3. Integrate quantum coherence measurements with classical therapeutic frameworks
4. Track the coach's developmental trajectory across sessions
5. Name the client and speak to THEIR specific emotional landscape
6. Identify transgenerational patterns and CEE opportunities
7. NEVER produce identical feedback for different clients or sessions

## CRITICAL — Client Identity Rule

You will be told the client's name in the Session Context. Use ONLY that name throughout the entire assessment.
- NEVER invent, fabricate, or substitute a different name (e.g., "Jane D.", "John", "the client")
- NEVER use generic placeholders or pseudonyms
- If the client name is "Megan Hughes", every reference must say "Megan Hughes" or "Megan" — NEVER "Jane D." or any other name
- This rule is absolute and non-negotiable"""

    # ── Platform Context Builder ────────────────────────────────────────

    def _build_platform_context(self, intel: Dict, client_name: str) -> str:
        """Build the platform intelligence section for the AI prompt."""
        sections = []

        # Client state
        cs = intel.get("client_state", {})
        if cs:
            sections.append(f"""## Little Nate's Recorded Data for {client_name}
- Current C_emo: {cs.get('c_emo', 'No data')}
- GAP Score: {cs.get('gap', 'No data')}
- Quantum Score: {cs.get('quantum', 'No data')}
- Velocity: {cs.get('velocity', 'No data')} (rate of therapeutic movement)
- Engagement: {cs.get('engagement', 'No data')}
- Anxiety Level: {cs.get('anxiety', 'No data')}
- Mood: {cs.get('mood', 'unknown')} (trend: {cs.get('mood_trend', 'unknown')})
- Sessions Recorded: {cs.get('session_count', 0)}
- Breakthroughs: {cs.get('breakthroughs', 0)}
- Crises: {cs.get('crises', 0)}
- Risk Level: {cs.get('risk_level', 'low')}
- Reconsolidation Readiness: {cs.get('reconsolidation_readiness', 'Not assessed')}""")

        # Nevedal metrics trend
        nm = intel.get("nevedal_metrics", {})
        if nm.get("recent_measurements"):
            sections.append(f"""## Nevedal Quantum Coherence Trend
- Average C_emo (recent): {nm.get('avg_c_emo', 0):.3f}
- Average p_ent (entanglement): {nm.get('avg_p_ent', 0):.3f}
- CEE Windows in Recent History: {nm.get('cee_count', 0)}""")

        # CEE history
        cee = intel.get("cee_history", [])
        if cee:
            cee_text = "\n".join(
                f"  - Peak C_emo: {c['c_emo_peak']:.3f}, Duration: {c['duration_seconds']}s ({c['recorded_at'][:10]})"
                for c in cee[:5]
            )
            sections.append(f"## CEE (Corrective Emotional Experience) History\n{cee_text}")

        # Transgenerational patterns
        tg = intel.get("transgenerational_patterns", [])
        if tg:
            tg_text = "\n".join(
                f"  - Pattern: {p.get('pattern', '?')} (source: {p.get('source', '?')}, "
                f"corrective experiences: {p.get('corrective_experience_count', 0)})"
                for p in tg[:5]
            )
            sections.append(f"## Transgenerational Patterns (PMB Legacy)\n{tg_text}")

        # Night School wisdom
        wisdom = intel.get("wisdom_entries", [])
        if wisdom:
            w_text = "\n".join(
                f"  - [{w['type']}] {w['content'][:150]} (effectiveness: {w['score']:.1f})"
                for w in wisdom[:5]
            )
            sections.append(f"## Little Nate's Night School Lived Wisdom\n{w_text}")

        # Coherence data
        coh = intel.get("coherence_data", {})
        if coh:
            sections.append(f"""## Coherence Measurements
- Latest Score: {coh.get('score', 'N/A')}
- Confidence: {coh.get('confidence', 'N/A')}
- 24h Change: {coh.get('delta_24h', 'N/A')}
- 7-day Change: {coh.get('delta_7d', 'N/A')}""")

        if not sections:
            return "\n## Platform Data\nNo prior platform data available for this client. This is a baseline assessment.\n"

        return "\n" + "\n\n".join(sections) + "\n"

    def _video_stub_assessment(self, focus_area: str, coach_query: str, client_name: str) -> Dict:
        """Fallback assessment when Azure is unavailable — uses client name and indicates pending status."""
        client_desc = client_name or "the client"
        return {
            "therapeutic_presence_score": 0.0,
            "strengths": [
                f"Session with {client_desc} has been received for clinical supervision",
                f"Focus area identified: {focus_area}",
                "Willingness to seek supervision feedback demonstrates professional growth commitment",
            ],
            "growth_areas": [
                f"Full {focus_area} assessment pending — AI service temporarily unavailable",
                "Re-analyze this session once connectivity is restored for detailed feedback",
            ],
            "key_moments": [],
            "focus_specific_feedback": f"This session with {client_desc} focused on {focus_area}. "
                f"Little Nate's AI assessment engine was temporarily unavailable. "
                f"Click 'Analyze Upload' again to generate a full Liminal Intelligence assessment. "
                f"{'Coach noted: ' + coach_query if coach_query else ''}",
            "reflection_questions": [
                f"What moments in this session with {client_desc} felt most connected?",
                "Where did you notice yourself pulling back or becoming directive?",
                f"How might you apply {focus_area} principles differently next time?",
            ],
            "dojo_scenarios": [
                {
                    "persona": "RESISTANT",
                    "scenario": f"Client resists exploring {focus_area}-related material",
                    "skill_target": f"Maintaining therapeutic presence while addressing {focus_area}",
                }
            ],
            "workbook_recommendations": [f"Review materials on {focus_area} before next session"],
            "brief": f"Session recording with {client_desc} has been received. "
                f"Little Nate's Liminal Intelligence assessment engine was temporarily offline. "
                f"Please re-analyze this session to receive a full quantum emotional coherence assessment "
                f"with EFT/Attachment Theory foundations, CEE tracking, and transgenerational pattern analysis.\n\n"
                f"Focus area: {focus_area}.",
            "metrics": {},
            "quantum_coherence_assessment": {},
            "cee_assessment": {},
            "transgenerational_awareness": {},
            "gap_analysis": {},
        }

    async def _push_to_night_school(
        self,
        ai_result: Dict,
        coach_id: str,
        session_id: str,
        vtt_content: str = "",
        full_analysis: Optional[Dict] = None
    ):
        """
        Push classroom analysis insights to Night School for learning.
        
        CONNECTION: Classroom → Night School Wisdom
        
        This method:
        1. Extracts dojo_scenarios and queues them for DOJO testing
        2. Converts strengths and key moments into wisdom entries
        3. Updates Night School with learned insights
        4. Logs complete session to Little Nate's memory
        """
        try:
            from app.services.night_school_director import create_night_school_director
            
            # Initialize Night School Director
            vault_root = self.data_dir.parent  # Go up from classroom to vault root
            director = create_night_school_director(vault_root)
            
            # Learn from this analysis
            entries_created = director.learn_from_classroom_analysis(
                analysis_result=ai_result,
                coach_id=coach_id,
                session_id=session_id
            )
            
            if entries_created:
                print(f"[Classroom→NightSchool] Created {len(entries_created)} wisdom entries from session {session_id}")
            
            # Log dojo scenarios queued
            dojo_scenarios = ai_result.get('dojo_scenarios', [])
            if dojo_scenarios:
                print(f"[Classroom→NightSchool] Queued {len(dojo_scenarios)} DOJO scenarios for testing")
            
            # ================================================================
            # LOG SESSION TO LITTLE NATE'S MEMORY
            # This creates a complete memory record for future reference
            # ================================================================
            if vtt_content or full_analysis:
                # Extract client_id from session analysis or cached data
                client_id = ""
                family_id = ""
                
                if full_analysis:
                    client_id = full_analysis.get("client_id", "")
                    family_id = full_analysis.get("family_id", "")
                
                # If not in analysis, try to get from cached session
                if not client_id:
                    cached = self._session_cache.get(session_id, {})
                    client_id = cached.get("client_id", "")
                    family_id = cached.get("family_id", "")
                
                memory_result = director.log_session_to_memory(
                    session_id=session_id,
                    transcript=vtt_content,
                    analysis=full_analysis or {},
                    coach_id=coach_id,
                    client_id=client_id,
                    family_id=family_id,
                    observations=None,  # Will be added from live sessions
                    biometrics=None,    # Will be added from Nevedal tracking
                    video_insights=ai_result.get("visual_observations") or None
                )
                
                print(f"[Classroom→Memory] Logged session {session_id} to Nate's memory: {memory_result.get('memory_id', '')}")
            
        except ImportError as e:
            print(f"[Classroom] Night School import error: {e}")
        except Exception as e:
            print(f"[Classroom→NightSchool] Error pushing to Night School: {e}")
            import traceback
            traceback.print_exc()


# AI prompt templates for analysis
ANALYSIS_SYSTEM_PROMPT = """You are Little Nate, an expert clinical supervisor analyzing a coaching session transcript.

Your role is to provide constructive, growth-oriented feedback that helps coaches develop their therapeutic skills that reflect how others conditionally respond in order to noticing longings as well as emotional coherence differences in clients and coaches..

You will analyze the session based on:
1. The extracted metrics (talk-time ratios, question types, techniques detected)
2. The full transcript content
3. The coach's specific learning focus which can be anything they request or we have requested for them to learn about

Provide your analysis in the following JSON structure:
{
    "strengths": ["strength 1", "strength 2", ...],
    "growth_areas": ["area 1", "area 2", ...],
    "key_moments": [
        {"timestamp": "MM:SS", "description": "what happened", "feedback": "constructive feedback"},
        ...
    ],
    "therapeutic_presence_score": 7.5,
    "focus_specific_feedback": "Detailed feedback on the coach's specific learning focus...",
    "reflection_questions": [
        "Question 1?",
        "Question 2?",
        ...
    ],
    "dojo_scenarios": [
        {"persona": "RESISTANT", "scenario": "Client pushes back on...", "skill_target": "handling resistance"},
        ...
    ],
    "workbook_recommendations": ["EFT_Attachment_Principles.pdf - Section on...", ...]
}

Guidelines:
- Be warm, encouraging, and specific
- Balance strengths with growth areas (aim for 3-4 of each)
- Key moments should include both highlights and missed opportunities
- Reflection questions should be thought-provoking, not judgmental
- Coach's feedback should also consider learned metrics of night school director as well as other coaches in the classroom.
- Dojo scenarios should directly address growth areas
- Therapeutic presence score: 1-10 scale (7+ is competent, 9+ is exceptional)
"""

PHD_ASSESSMENT_SYSTEM_PROMPT = """You are Little Nate, a PhD-level clinical supervisor producing a formal assessment of a coaching session.

You have deep expertise in Emotionally Focused Therapy (EFT), attachment theory, the Nevedal quantum coherence model (CEE), and the following DOJO specializations:
- THERAPIST: Core therapeutic skills, emotional attunement, empathy, reflections, attachment awareness
- BUSINESS: Professional coaching, goal-setting, strategic clarity, motivational interviewing  
- TEACHER: Psychoeducation, concept scaffolding, Socratic questioning, knowledge transfer
- JUDGE: Ethical reasoning, boundary management, risk assessment, clinical decision-making
- PASTOR: Existential/spiritual integration, meaning-making, grief & loss, values alignment
- COUNSELOR: Solution-focused techniques, coping skill building, cognitive restructuring
- SOCIAL_WORKER: Systems-level thinking, resource linkage, advocacy, social determinants awareness

For each requested DOJO, provide a rigorous, specific assessment.

Return your response as valid JSON with this structure:
{
  "per_dojo": {
    "<DOJO_KEY>": {
      "score": 7.5,
      "letter_grade": "B+",
      "domain_competencies": [
        {"name": "competency name", "score": 7.0, "observation": "specific evidence from transcript"}
      ],
      "strengths": ["specific strength with evidence"],
      "growth_areas": ["specific area with recommended exercise"],
      "key_moments": [{"timestamp": "approx", "observation": "what happened", "feedback": "guidance"}],
      "next_session_goals": ["concrete goal 1"]
    }
  },
  "combined": {
    "score": 7.5,
    "letter_grade": "B+",
    "overall_narrative": "2-3 paragraph clinical narrative...",
    "therapeutic_presence_score": 7.5,
    "cross_domain_insights": ["insight spanning multiple DOJO areas"],
    "client_engagement_observations": "what you noticed about the client's emotional state",
    "cee_moments": ["moments where emotional coherence shifted"],
    "development_plan": "paragraph with next 3-5 sessions outlook"
  }
}

Be specific to the transcript. Reference actual statements and exchanges. This is a professional-grade document that will be filed in the client's coaching folder."""


def build_phd_assessment_prompt(
    dojo_keys: list,
    transcript_text: str,
    metrics: dict,
    coach_name: str,
    client_name: str,
    initial_analysis: dict = None,
) -> str:
    """Build the user prompt for PhD-level per-DOJO assessment."""
    initial = ""
    if initial_analysis:
        strengths = initial_analysis.get("strengths", [])
        growth = initial_analysis.get("growth_areas", [])
        initial = f"""
## Initial Analysis Summary
- Strengths identified: {', '.join(strengths[:5]) if strengths else 'None yet'}
- Growth areas identified: {', '.join(growth[:5]) if growth else 'None yet'}
- Initial therapeutic presence score: {initial_analysis.get('therapeutic_presence_score', 'N/A')}
"""
    return f"""Produce a PhD-level clinical assessment for coach **{coach_name}** working with client **{client_name}**.

## DOJOs to Assess
{', '.join(dojo_keys)}

## Session Metrics
- Duration: {metrics.get('total_duration_minutes', 0):.1f} minutes
- Coach talk time: {metrics.get('coach_talk_time_percent', 0):.1f}%
- Client talk time: {metrics.get('client_talk_time_percent', 0):.1f}%
- Open questions: {metrics.get('open_questions', 0)}
- Closed questions: {metrics.get('closed_questions', 0)}
- Reflective statements: {metrics.get('reflection_count', 0)}
- Validation statements: {metrics.get('validation_count', 0)}
- Techniques detected: {json.dumps(metrics.get('techniques_detected', {}))}
{initial}
## Full Session Transcript
{transcript_text[:18000]}

Provide the assessment as the JSON structure specified."""


async def generate_phd_assessment_async(
    dojo_keys: list,
    transcript_text: str,
    metrics: dict,
    coach_name: str,
    client_name: str,
    initial_analysis: dict = None,
) -> Dict:
    """Call Grok to generate a real PhD-level per-DOJO + combined assessment."""
    import httpx
    if not NATE_CHAT_KEY:
        _classroom_logger.warning("Nate AI key missing — falling back to structured stub")
        return _build_structured_stub(dojo_keys, metrics, coach_name, client_name, initial_analysis)
    url = NATE_CHAT_URL
    user_prompt = build_phd_assessment_prompt(dojo_keys, transcript_text, metrics, coach_name, client_name, initial_analysis)
    payload = nate_chat_payload(
        messages=[
            {"role": "system", "content": PHD_ASSESSMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=4000,
        user_id=client_name,
    )
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload, headers=nate_chat_headers())
        if resp.status_code != 200:
            _classroom_logger.warning("Azure PhD assessment returned %s: %s", resp.status_code, resp.text[:300])
            return _build_structured_stub(dojo_keys, metrics, coach_name, client_name, initial_analysis)
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        per_dojo = parsed.get("per_dojo", {})
        combined = parsed.get("combined", {})
        result = {}
        for dk in dojo_keys:
            dojo_data = per_dojo.get(dk, {})
            result[dk] = {
                "score": dojo_data.get("score", 7.0),
                "letter_grade": dojo_data.get("letter_grade", "B"),
                "domain_competencies": dojo_data.get("domain_competencies", []),
                "summary": dojo_data.get("overall_narrative", dojo_data.get("strengths", ["Assessment generated."])[0] if dojo_data.get("strengths") else "Assessment generated."),
                "strengths": dojo_data.get("strengths", []),
                "growth_areas": dojo_data.get("growth_areas", []),
                "key_moments": dojo_data.get("key_moments", []),
                "next_session_goals": dojo_data.get("next_session_goals", []),
            }
        result["combined"] = {
            "score": combined.get("score", combined.get("therapeutic_presence_score", 7.0)),
            "letter_grade": combined.get("letter_grade", "B"),
            "overall_narrative": combined.get("overall_narrative", ""),
            "therapeutic_presence_score": combined.get("therapeutic_presence_score", 7.0),
            "cross_domain_insights": combined.get("cross_domain_insights", []),
            "client_engagement_observations": combined.get("client_engagement_observations", ""),
            "cee_moments": combined.get("cee_moments", []),
            "development_plan": combined.get("development_plan", ""),
            "summary": combined.get("overall_narrative", "Combined assessment generated."),
        }
        return result
    except json.JSONDecodeError:
        _classroom_logger.warning("Azure PhD assessment returned non-JSON")
        return _build_structured_stub(dojo_keys, metrics, coach_name, client_name, initial_analysis)
    except Exception as e:
        _classroom_logger.warning("Azure PhD assessment error: %s", e)
        return _build_structured_stub(dojo_keys, metrics, coach_name, client_name, initial_analysis)


def _build_structured_stub(dojo_keys: list, metrics: dict, coach_name: str, client_name: str, initial_analysis: dict = None) -> Dict:
    """Fallback when Azure is unavailable — produces structured but non-AI assessments."""
    dur = metrics.get("total_duration_minutes", 0)
    open_q = metrics.get("open_questions", 0)
    result = {}
    for dk in dojo_keys:
        result[dk] = {
            "score": 7.0,
            "letter_grade": "B",
            "domain_competencies": [{"name": "General Competency", "score": 7.0, "observation": f"Session duration {dur:.0f} min with {open_q} open questions."}],
            "summary": f"{dk} assessment for {coach_name} with {client_name}. Azure AI unavailable; manual review recommended.",
            "strengths": (initial_analysis or {}).get("strengths", ["Engaged with client."]),
            "growth_areas": (initial_analysis or {}).get("growth_areas", ["Increase open-ended questioning."]),
            "key_moments": [],
            "next_session_goals": ["Build on strengths observed."],
        }
    result["combined"] = {
        "score": 7.0,
        "letter_grade": "B",
        "overall_narrative": f"Session between {coach_name} and {client_name} ({dur:.0f} min). Azure AI was unavailable; scores are provisional. Manual review recommended.",
        "therapeutic_presence_score": 7.0,
        "cross_domain_insights": [],
        "client_engagement_observations": "",
        "cee_moments": [],
        "development_plan": "Continue current approach. Full AI assessment pending.",
        "summary": "Combined assessment (Azure AI unavailable).",
    }
    return result


def format_assessment_as_markdown(assessments: Dict, coach_name: str, client_name: str, dojo_keys: list, session_id: str) -> str:
    """Format the PhD assessment as a markdown document for FOLDER placement."""
    lines = [
        f"# PhD-Level Coaching Assessment",
        f"**Coach:** {coach_name}  ",
        f"**Client:** {client_name}  ",
        f"**Session ID:** {session_id}  ",
        f"**Generated:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
        "",
        "---",
        "",
    ]
    for dk in dojo_keys:
        da = assessments.get(dk, {})
        lines.append(f"## {dk} Assessment")
        lines.append(f"**Score:** {da.get('score', 'N/A')}/10 ({da.get('letter_grade', 'N/A')})")
        lines.append("")
        if da.get("domain_competencies"):
            lines.append("### Domain Competencies")
            for c in da["domain_competencies"]:
                lines.append(f"- **{c.get('name', '')}** ({c.get('score', '')}/10): {c.get('observation', '')}")
            lines.append("")
        if da.get("strengths"):
            lines.append("### Strengths")
            for s in da["strengths"]:
                lines.append(f"- {s}")
            lines.append("")
        if da.get("growth_areas"):
            lines.append("### Growth Areas")
            for g in da["growth_areas"]:
                lines.append(f"- {g}")
            lines.append("")
        if da.get("key_moments"):
            lines.append("### Key Moments")
            for m in da["key_moments"]:
                ts = m.get("timestamp", "")
                lines.append(f"- [{ts}] {m.get('observation', '')} — *{m.get('feedback', '')}*")
            lines.append("")
        if da.get("next_session_goals"):
            lines.append("### Next Session Goals")
            for g in da["next_session_goals"]:
                lines.append(f"- {g}")
            lines.append("")
        lines.append("---")
        lines.append("")
    combined = assessments.get("combined", {})
    lines.append("## Combined Assessment")
    lines.append(f"**Overall Score:** {combined.get('score', 'N/A')}/10 ({combined.get('letter_grade', 'N/A')})")
    lines.append(f"**Therapeutic Presence:** {combined.get('therapeutic_presence_score', 'N/A')}/10")
    lines.append("")
    if combined.get("overall_narrative"):
        lines.append(combined["overall_narrative"])
        lines.append("")
    if combined.get("cross_domain_insights"):
        lines.append("### Cross-Domain Insights")
        for i in combined["cross_domain_insights"]:
            lines.append(f"- {i}")
        lines.append("")
    if combined.get("client_engagement_observations"):
        lines.append(f"### Client Engagement\n{combined['client_engagement_observations']}")
        lines.append("")
    if combined.get("cee_moments"):
        lines.append("### CEE Moments (Coherent Emotional Engagement)")
        for c in combined["cee_moments"]:
            lines.append(f"- {c}")
        lines.append("")
    if combined.get("development_plan"):
        lines.append(f"### Development Plan\n{combined['development_plan']}")
        lines.append("")
    lines.append("---")
    lines.append("*Assessment generated by Little Nate — Sovereign Sanctuary Clinical Supervision Engine*")
    return "\n".join(lines)


def build_analysis_prompt(
    metrics: Dict,
    transcript_text: str,
    focus_area: str,
    coach_name: str,
    coach_query: str = "",
    video_insights: str = ""
) -> str:
    """Build the user prompt for AI analysis."""
    coach_query_section = ""
    if coach_query:
        coach_query_section = f"""
## Coach's Specific Question
The coach specifically asks: {coach_query}
Please address this question directly in a dedicated "Coach's Question" section of your analysis.
"""
    
    video_section = ""
    if video_insights:
        video_section = f"""
## Video Analysis Observations
{video_insights}
Please incorporate these visual observations into your analysis.
"""

    return f"""Please analyze this coaching session for {coach_name}.

## Session Metrics
- Duration: {metrics.get('total_duration_minutes', 0):.1f} minutes
- Coach talk time: {metrics.get('coach_talk_time_percent', 0):.1f}%
- Client talk time: {metrics.get('client_talk_time_percent', 0):.1f}%
- Open questions asked: {metrics.get('open_questions', 0)}
- Closed questions asked: {metrics.get('closed_questions', 0)}
- Reflective statements: {metrics.get('reflection_count', 0)}
- Validation statements: {metrics.get('validation_count', 0)}
- Techniques detected: {json.dumps(metrics.get('techniques_detected', {}))}

## Coach's Learning Focus
{focus_area}
{coach_query_section}{video_section}
## Session Transcript
{transcript_text[:15000]}  # Truncate for token limits

Please provide your analysis in the JSON format specified."""
