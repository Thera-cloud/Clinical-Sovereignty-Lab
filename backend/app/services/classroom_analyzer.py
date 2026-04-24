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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set, Callable, Awaitable
from dataclasses import dataclass, asdict, field

_HAS_LIBROSA = False
_HAS_MOVIEPY = False
try:
    import librosa as _librosa_check  # noqa: F401

    _HAS_LIBROSA = True
except ImportError:
    pass
try:
    import moviepy as _moviepy_check  # noqa: F401

    _HAS_MOVIEPY = True
except ImportError:
    pass

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
        """Load all analyzed classroom sessions."""
        try:
            return json.loads(self.classroom_file.read_text(encoding="utf-8"))
        except Exception:
            return []
    
    def save_sessions(self, sessions: List[Dict]):
        """Save classroom sessions."""
        self.classroom_file.write_text(
            json.dumps(sessions, indent=2, default=str),
            encoding="utf-8"
        )
    
    def get_coach_sessions(self, coach_id: str) -> List[Dict]:
        """Get all analyzed sessions for a coach."""
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
        """Get aggregate progress metrics for a coach."""
        sessions = self.get_coach_sessions(coach_id)
        
        if not sessions:
            return {
                "total_sessions_reviewed": 0,
                "average_presence_score": 0.0,
                "technique_usage": {},
                "growth_trajectory": [],
                "assignments_completed": 0,
                "assignments_pending": 0,
            }
        
        # Calculate aggregates
        presence_scores = [
            s.get("therapeutic_presence_score", 0)
            for s in sessions
            if s.get("therapeutic_presence_score")
        ]
        
        all_techniques = {}
        for s in sessions:
            metrics = s.get("metrics", {})
            for tech, count in metrics.get("techniques_detected", {}).items():
                all_techniques[tech] = all_techniques.get(tech, 0) + count
        
        completed = len([s for s in sessions if s.get("reflection_submitted_at")])
        pending = len([s for s in sessions if not s.get("reflection_submitted_at")])
        
        return {
            "total_sessions_reviewed": len(sessions),
            "average_presence_score": sum(presence_scores) / max(len(presence_scores), 1),
            "technique_usage": all_techniques,
            "growth_trajectory": [
                {"date": s.get("analyzed_at"), "score": s.get("therapeutic_presence_score", 0)}
                for s in sorted(sessions, key=lambda x: x.get("analyzed_at", ""))
            ],
            "assignments_completed": completed,
            "assignments_pending": pending,
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
    
    async def analyze_video(
        self,
        video_id: str,
        coach_id: str,
        client_id: str,
        coach_query: str = "",
        focus_area: str = "general",
        family_id: str = "",
        client_name: str = "",
    ) -> Dict:
        """
        Analyze an uploaded video using VideoAnalyzer for visual sampling + optional audio timeline.
        Creates crystals / wisdom when DB is available. Never raises on missing AV libraries.
        """
        classroom_sessions_file = self.data_dir / "classroom_sessions.json"
        sessions = []
        try:
            with open(classroom_sessions_file, "r", encoding="utf-8") as f:
                sessions = json.load(f)
        except Exception:
            pass

        video_session = None
        for s in sessions:
            if s.get("session_id") == video_id:
                video_session = s
                break

        if not video_session:
            return {"error": f"Video session {video_id} not found"}

        video_path_str = video_session.get("video_path", "")
        vp = Path(video_path_str) if video_path_str else Path()

        frame_analysis: Dict[str, Any] = {}
        visual_insights = ""
        voice_metrics_timeline: Optional[List[Dict[str, float]]] = None

        try:
            from app.services.video_analyzer import (
                VideoAnalyzer,
                extract_audio_wav,
                compute_voice_metrics_timeline,
            )

            analyzer = VideoAnalyzer()
            frames: List[bytes] = []
            if vp.exists():
                frames = analyzer.extract_frames(vp, interval_seconds=5, max_frames=5)
            if frames:
                frame_analysis = analyzer.analyze_classroom_frames(frames)
            else:
                frame_analysis = {
                    "coaching_insights": "No frames extracted (missing codecs or unreadable video).",
                    "key_moments": [],
                    "therapeutic_presence_score": 6.0,
                    "frames_analyzed": 0,
                }

            combined_visual = {
                "frame_analysis": frame_analysis,
                "voice_metrics_timeline": None,
                "librosa_gate": _HAS_LIBROSA,
                "moviepy_gate": _HAS_MOVIEPY,
            }

            wav_path: Optional[Path] = None
            voice_emotion_result: Optional[Dict[str, Any]] = None
            try:
                if vp.exists() and _HAS_LIBROSA:
                    wav_path = await asyncio.to_thread(extract_audio_wav, vp)
                    if wav_path:
                        voice_metrics_timeline = await asyncio.to_thread(
                            compute_voice_metrics_timeline, wav_path, 5.0
                        )
                        combined_visual["voice_metrics_timeline"] = voice_metrics_timeline

                        # Voice emotion classification (transformer or librosa rules)
                        try:
                            from app.services.voice_emotion_analyzer import (
                                VoiceEmotionAnalyzer,
                            )

                            ve = VoiceEmotionAnalyzer()
                            if ve.available:
                                voice_emotion_result = await ve.analyze_audio(
                                    str(wav_path), segment_seconds=10
                                )
                                combined_visual["voice_emotion"] = voice_emotion_result
                            else:
                                combined_visual["voice_emotion"] = {
                                    "error": "no voice emotion backend available"
                                }
                        except Exception as _ve_err:
                            print(f"[Classroom] voice emotion (non-fatal): {_ve_err}")
                            voice_emotion_result = None
            except Exception as _aud_err:
                print(f"[Classroom] audio pipeline (non-fatal): {_aud_err}")
                voice_metrics_timeline = None
            finally:
                try:
                    if wav_path and wav_path.exists():
                        wav_path.unlink(missing_ok=True)
                except Exception:
                    pass

            visual_insights = json.dumps(combined_visual, indent=2, default=str)
        except ImportError:
            visual_insights = json.dumps(
                {"error": "VideoAnalyzer not available - visual analysis skipped"}
            )
            frame_analysis = {
                "coaching_insights": "VideoAnalyzer unavailable.",
                "key_moments": [],
                "therapeutic_presence_score": 6.0,
                "frames_analyzed": 0,
            }
        except Exception as e:
            visual_insights = json.dumps({"error": f"Visual analysis error: {e}"})
            frame_analysis = {
                "coaching_insights": f"Analysis error: {e}",
                "key_moments": [],
                "therapeutic_presence_score": 6.0,
                "frames_analyzed": 0,
            }

        coaching_insights = str(frame_analysis.get("coaching_insights") or "")
        key_moments = list(frame_analysis.get("key_moments") or [])
        if voice_metrics_timeline:
            try:
                from app.services.video_analyzer import voice_timeline_key_moments

                for m in voice_timeline_key_moments(voice_metrics_timeline):
                    if m not in key_moments:
                        key_moments.append(m)
            except Exception:
                pass

        # ===== FACIAL / BODY-LANGUAGE ANALYSIS =====
        # Sample frames every 5s and extract facial expression + gaze
        # indicators via MediaPipe FaceMesh. Module is import-safe — falls
        # back gracefully when opencv-python-headless / mediapipe are
        # unavailable (i.e. before Docker rebuild). Output is aggregate
        # only — no face images / embeddings are stored.
        facial_results: Dict[str, Any] = {}
        try:
            from app.services.facial_analyzer import FacialAnalyzer

            facial = FacialAnalyzer()
            if facial.available and vp.exists():
                facial_results = await facial.analyze_video_frames(
                    str(vp), sample_interval_seconds=5
                )
            elif not facial.available:
                facial_results = {
                    "error": "facial analysis unavailable — opencv/mediapipe not installed",
                    "frames_analyzed": 0,
                }
        except Exception as _f_err:
            print(f"[Classroom] facial analysis (non-fatal): {_f_err}")
            facial_results = {"error": str(_f_err), "frames_analyzed": 0}

        tps = float(frame_analysis.get("therapeutic_presence_score") or 7.0)
        transcript_summary_parts = [
            coaching_insights,
            f"Coach focus: {focus_area}." if focus_area else "",
            f"Coach question: {coach_query}" if coach_query else "",
        ]
        transcript_summary = "\n".join(p for p in transcript_summary_parts if p).strip()[:4000]

        facial_summary = (facial_results or {}).get("summary", {}) or {}
        emotional_timeline = (facial_results or {}).get("emotional_timeline", []) or []

        analysis: Dict[str, Any] = {
            "session_id": video_id,
            "coach_id": coach_id,
            "client_id": client_id,
            "client_name": client_name,
            "family_id": family_id,
            "source": "device_upload",
            "focus_area": focus_area,
            "coach_query": coach_query,
            "visual_insights": visual_insights,
            "transcript_summary": transcript_summary or None,
            "coaching_insights": coaching_insights,
            "voice_metrics_timeline": voice_metrics_timeline,
            "voice_emotion": voice_emotion_result,
            "therapeutic_presence_score": tps,
            "key_moments": key_moments,
            "facial_analysis": facial_results,
            "facial_summary": facial_summary,
            "emotional_timeline": emotional_timeline,
            "status": "analyzed",
            "analyzed_at": str(datetime.now()),
            "video_path": video_path_str,
            "filename": video_session.get("filename", ""),
            "crystals_created": [],
        }

        # Align voice emotion with any prior transcript (VTT) we have for
        # this session. Surfaces incongruence: text says "I'm fine" while
        # voice reads "sad".
        try:
            if voice_emotion_result and voice_emotion_result.get("emotion_timeline"):
                prior = self.get_session_analysis(video_id) or {}
                excerpt = prior.get("transcript_excerpt") or []
                vtt_loc = video_session.get("transcript_location")
                vtt_storage = video_session.get("transcript_storage", "local")
                vtt_entries: List[VTTEntry] = []
                if vtt_loc:
                    vtt_text = self._load_transcript_content(vtt_loc, vtt_storage)
                    if vtt_text:
                        vtt_entries = VTTParser.parse(vtt_text)
                if vtt_entries:
                    from app.services.voice_emotion_analyzer import (
                        VoiceEmotionAnalyzer as _VEA,
                    )
                    aligned = _VEA.align_with_transcript(
                        voice_emotion_result["emotion_timeline"], vtt_entries
                    )
                    if aligned:
                        analysis["aligned_transcript_emotions"] = aligned
                elif excerpt:
                    converted: List[Dict[str, Any]] = []
                    for e in excerpt:
                        ts = e.get("time", "0:00")
                        try:
                            mm, ss = ts.split(":")
                            secs = int(mm) * 60 + int(ss)
                        except Exception:
                            secs = 0
                        converted.append({
                            "start_time": float(secs),
                            "end_time": float(secs + 5),
                            "speaker": e.get("speaker", "Unknown"),
                            "text": e.get("text", ""),
                        })
                    from app.services.voice_emotion_analyzer import (
                        VoiceEmotionAnalyzer as _VEA,
                    )
                    aligned = _VEA.align_with_transcript(
                        voice_emotion_result["emotion_timeline"], converted
                    )
                    if aligned:
                        analysis["aligned_transcript_emotions"] = aligned
        except Exception as _al_err:
            print(f"[Classroom] voice/transcript alignment (non-fatal): {_al_err}")

        db_pool = None
        try:
            from app.main import app as _app

            db_pool = getattr(_app.state, "db_pool", None) if _app else None
        except Exception:
            db_pool = None

        crystals_created: List[Dict[str, str]] = []
        summary_for_wisdom = (
            f"Classroom video {video_id}\n{transcript_summary}\n{coaching_insights}\n"
            f"Key moments: {json.dumps(key_moments, default=str)[:4000]}"
        )

        if db_pool and (transcript_summary or coaching_insights or key_moments):
            try:
                from app.websocket.crystal_recall_bridge import crystallize_from_conversation

                user_text = (
                    f"Classroom video session {video_id} for professional review. "
                    f"Summary and observations: {transcript_summary[:1800]}\n"
                    f"Coaching lens: {coaching_insights[:1200]}\n"
                    "Patterns around empathy, trust, attunement, and therapeutic presence "
                    "are relevant for ongoing skill development."
                )
                nate_response = (
                    coaching_insights
                    or "Consider how safety, pacing, and connection show up on camera for the client."
                )
                if coach_query:
                    nate_response = f"{nate_response}\nCoach asked: {coach_query[:500]}"

                ch = await crystallize_from_conversation(
                    db_pool,
                    coach_id,
                    user_text,
                    nate_response,
                    user_name=client_name or coach_id[:12],
                    domain="clinical",
                    min_score=3,
                    origin_surface="classroom_video",
                )
                if ch:
                    crystals_created.append({"hash": ch, "domain": "clinical"})
            except Exception as _cr_err:
                print(f"[Classroom] crystallize_from_conversation (non-fatal): {_cr_err}")

            try:
                from app.services.wisdom_lifecycle_manager import WisdomLifecycleManager

                coach_uuid = None
                if db_pool:
                    async with db_pool.acquire() as _conn:
                        coach_uuid = await _conn.fetchval(
                            """
                            SELECT id::text FROM users
                            WHERE hardware_id = $1 OR username = $1
                            LIMIT 1
                            """,
                            coach_id,
                        )
                mgr = WisdomLifecycleManager(db_pool, None)
                conf = min(0.95, max(0.5, tps / 10.0))
                await mgr.extract_wisdom(
                    "classroom",
                    summary_for_wisdom.strip()[:20000],
                    user_id=coach_uuid,
                    domain="clinical",
                    confidence=conf,
                )

                # ===== FACIAL ANALYSIS → PMB WISDOM =====
                # Elevated gaze aversion correlates with shame / avoidance
                # in the shame_resilience domain. Push as a separate
                # wisdom entry so the PMB predictability model can pick it
                # up alongside the verbal/voice signal.
                aversion = float(facial_summary.get("gaze_aversion_ratio", 0.0))
                if aversion > 0.4:
                    facial_wisdom_text = (
                        f"Video session facial analysis ({client_name or client_id[:12]}): "
                        f"gaze aversion ratio {aversion:.2f} across "
                        f"{facial_summary.get('frames_with_face', 0)} frames; "
                        f"dominant expression "
                        f"{facial_summary.get('dominant_expression', 'neutral')}. "
                        f"Indicators: {', '.join(facial_summary.get('potential_indicators', []))}"
                    )
                    await mgr.extract_wisdom(
                        "facial_analysis",
                        facial_wisdom_text[:20000],
                        user_id=coach_uuid,
                        domain="shame_resilience",
                        confidence=0.7,
                    )
            except Exception as _w_err:
                print(f"[Classroom] extract_wisdom (non-fatal): {_w_err}")

            # ===== FACIAL ANALYSIS → CLIENT-SCOPED CRYSTALS =====
            # One crystal per significant indicator so coach + Nate can
            # surface them in future sessions. Origin tagged so they can
            # be distinguished from verbal-only crystals downstream.
            try:
                from app.websocket.crystal_recall_bridge import (
                    crystallize_from_conversation,
                )

                indicators = facial_summary.get("potential_indicators", []) or []
                frames_n = int(facial_results.get("frames_analyzed", 0) or 0)
                # Crystals attach to the *client* if we have one — that's
                # whose session it is — otherwise fall back to the coach.
                target_id = client_id or coach_id
                target_name = client_name or (target_id[:12] if target_id else "")

                for indicator in indicators:
                    user_text = (
                        f"Video session facial analysis: {indicator}. "
                        f"Detected from {frames_n} sampled frames "
                        f"(dominant expression: "
                        f"{facial_summary.get('dominant_expression', 'neutral')}, "
                        f"engagement: {facial_summary.get('avg_engagement', 0)})."
                    )
                    nate_response = (
                        "Treat as one signal among many — combine with verbal "
                        "content and voice timeline before drawing conclusions."
                    )
                    try:
                        ch = await crystallize_from_conversation(
                            db_pool,
                            target_id,
                            user_text,
                            nate_response,
                            user_name=target_name,
                            domain="clinical",
                            min_score=0,  # facial signal is already pre-scored
                            origin_surface="facial_analysis",
                        )
                        if ch:
                            crystals_created.append(
                                {"hash": ch, "domain": "clinical", "source": "facial_analysis"}
                            )
                    except Exception as _ic_err:
                        print(f"[Classroom] facial crystal (non-fatal): {_ic_err}")
            except Exception as _fc_err:
                print(f"[Classroom] facial crystallize import (non-fatal): {_fc_err}")

            # ===== VOICE EMOTION → CRYSTALS + WISDOM =====
            # Each detected pattern (sustained sadness, anger, volatility…)
            # becomes a client-scoped crystal so coach + Nate surface it
            # later. High shift counts also feed the emotional_regulation
            # wisdom domain for the predictive cycle.
            try:
                ve_patterns = (voice_emotion_result or {}).get("patterns", []) or []
                seg_count = int((voice_emotion_result or {}).get("segments_analyzed", 0) or 0)
                shift_count = int((voice_emotion_result or {}).get("shift_count", 0) or 0)
                ve_target_id = client_id or coach_id
                ve_target_name = client_name or (ve_target_id[:12] if ve_target_id else "")

                if ve_patterns and ve_target_id:
                    from app.websocket.crystal_recall_bridge import (
                        crystallize_from_conversation as _vec_crystallize,
                    )
                    for pattern in ve_patterns:
                        try:
                            ch = await _vec_crystallize(
                                db_pool,
                                ve_target_id,
                                f"Voice emotion analysis: {pattern}",
                                f"Detected across {seg_count} audio segments "
                                f"(shifts: {shift_count}). Treat as one signal "
                                "alongside transcript and facial cues.",
                                user_name=ve_target_name,
                                domain="clinical",
                                min_score=0,
                                origin_surface="voice_emotion",
                            )
                            if ch:
                                crystals_created.append({
                                    "hash": ch,
                                    "domain": "clinical",
                                    "source": "voice_emotion",
                                })
                        except Exception as _vc_err:
                            print(f"[Classroom] voice emotion crystal (non-fatal): {_vc_err}")

                # Volatility → emotional_regulation wisdom
                if seg_count > 0 and shift_count > seg_count * 0.4:
                    try:
                        from app.services.wisdom_lifecycle_manager import (
                            WisdomLifecycleManager as _WLM,
                        )
                        coach_uuid_v = None
                        async with db_pool.acquire() as _conn:
                            coach_uuid_v = await _conn.fetchval(
                                """
                                SELECT id::text FROM users
                                WHERE hardware_id = $1 OR username = $1
                                LIMIT 1
                                """,
                                coach_id,
                            )
                        wisdom_text = (
                            f"Voice emotion analysis ({ve_target_name or ve_target_id}): "
                            f"{shift_count} emotional shifts across {seg_count} segments "
                            f"(dominant: {(voice_emotion_result or {}).get('dominant_emotion', 'neutral')}). "
                            f"Patterns: {'; '.join(ve_patterns) or 'none'}."
                        )
                        await _WLM(db_pool, None).extract_wisdom(
                            "voice_emotion",
                            wisdom_text[:20000],
                            user_id=coach_uuid_v,
                            domain="emotional_regulation",
                            confidence=0.7,
                        )
                    except Exception as _vw_err:
                        print(f"[Classroom] voice emotion wisdom (non-fatal): {_vw_err}")
            except Exception as _vall_err:
                print(f"[Classroom] voice emotion pipeline (non-fatal): {_vall_err}")

            # ===== MULTI-MODAL FUSION + LONGITUDINAL PATTERNS =====
            # Fuse text sentiment + voice emotion + facial expression into a
            # unified per-moment emotional state, then compare against this
            # client's prior sessions for shame cycles, attachment patterns,
            # volatility trends, and transgenerational matches.
            try:
                from app.services.multimodal_fusion import (
                    MultiModalFusionEngine,
                    transcript_segments_from_vtt,
                )
                from app.services.longitudinal_patterns import (
                    LongitudinalPatternDetector,
                )

                voice_tl_for_fusion: List[Dict[str, Any]] = (
                    (voice_emotion_result or {}).get("emotion_timeline", []) or []
                )
                facial_tl_for_fusion: List[Dict[str, Any]] = list(
                    emotional_timeline or []
                )

                # Build transcript_segments. Prefer parsed VTT (real
                # timestamps); fall back to cached excerpt.
                transcript_segments: List[Dict[str, Any]] = []
                vtt_loc_f = video_session.get("transcript_location")
                vtt_storage_f = video_session.get(
                    "transcript_storage", "local"
                )
                vtt_entries_f: List[VTTEntry] = []
                if vtt_loc_f:
                    try:
                        vtt_text_f = self._load_transcript_content(
                            vtt_loc_f, vtt_storage_f
                        )
                        if vtt_text_f:
                            vtt_entries_f = VTTParser.parse(vtt_text_f)
                    except Exception as _vtt_err:
                        print(f"[Classroom] fusion vtt load (non-fatal): {_vtt_err}")
                if vtt_entries_f:
                    transcript_segments = transcript_segments_from_vtt(
                        vtt_entries_f,
                        client_speaker_hint=(client_name or None),
                    )
                else:
                    prior_f = self.get_session_analysis(video_id) or {}
                    excerpt_f = prior_f.get("transcript_excerpt") or []
                    converted_f: List[Dict[str, Any]] = []
                    for _e in excerpt_f:
                        ts_str = _e.get("time", "0:00")
                        try:
                            mm, ss = ts_str.split(":")
                            secs = int(mm) * 60 + int(ss)
                        except Exception:
                            secs = 0
                        converted_f.append({
                            "start_time": float(secs),
                            "end_time": float(secs + 5),
                            "speaker": _e.get("speaker", "Unknown"),
                            "text": _e.get("text", ""),
                        })
                    if converted_f:
                        transcript_segments = transcript_segments_from_vtt(
                            converted_f,
                            client_speaker_hint=(client_name or None),
                        )

                # Even with no transcript, run fusion if we have voice or
                # facial — synthesize timestamp anchors from voice timeline.
                if not transcript_segments and (
                    voice_tl_for_fusion or facial_tl_for_fusion
                ):
                    anchor = voice_tl_for_fusion or facial_tl_for_fusion
                    transcript_segments = [
                        {
                            "timestamp": float(seg.get("timestamp", 0) or 0),
                            "speaker": "",
                            "text": "",
                            "sentiment": "neutral",
                        }
                        for seg in anchor
                    ]

                fusion_engine = MultiModalFusionEngine()
                fused = fusion_engine.fuse_session_analysis(
                    transcript_segments,
                    voice_tl_for_fusion,
                    facial_tl_for_fusion,
                )
                # Attach voice volatility for downstream longitudinal trend.
                fused["shift_count"] = int(
                    (voice_emotion_result or {}).get("shift_count", 0) or 0
                )
                fused["avg_engagement"] = float(
                    facial_summary.get("avg_engagement", 0.0) or 0.0
                )
                analysis["multimodal_fusion"] = fused
                analysis["clinical_flags"] = fused.get("clinical_flags", [])
                analysis["session_arc"] = fused.get("session_arc", {})
                analysis["incongruence_count"] = len(
                    fused.get("incongruence_moments", [])
                )

                # Longitudinal patterns require a db_pool + a real client.
                detected: Dict[str, Any] = {
                    "patterns": [],
                    "sessions_analyzed": 0,
                    "trend_direction": "insufficient_data",
                }
                target_client_id = client_id or coach_id
                if db_pool and target_client_id:
                    try:
                        detector = LongitudinalPatternDetector(db_pool)
                        detected = await detector.detect_patterns(
                            target_client_id, fused
                        )
                        if family_id:
                            try:
                                trans = await detector.detect_transgenerational(
                                    target_client_id, family_id
                                )
                                if trans:
                                    detected.setdefault(
                                        "patterns", []
                                    ).append(trans)
                            except Exception as _tg_err:
                                print(
                                    f"[Classroom] transgenerational "
                                    f"(non-fatal): {_tg_err}"
                                )
                    except Exception as _lp_err:
                        print(f"[Classroom] longitudinal (non-fatal): {_lp_err}")

                analysis["longitudinal_patterns"] = detected

                # Persist fusion + patterns onto coaching_sessions if a row
                # exists for this session_id (additive jsonb merge — never
                # clobber other keys).
                if db_pool:
                    try:
                        merged_sd = {
                            "multimodal_fusion": fused,
                            "longitudinal_patterns": detected,
                        }
                        async with db_pool.acquire() as _sd_conn:
                            await _sd_conn.execute(
                                """
                                UPDATE coaching_sessions
                                SET session_data = COALESCE(session_data, '{}'::jsonb)
                                                   || $1::jsonb
                                WHERE session_id = $2
                                """,
                                json.dumps(merged_sd),
                                video_id,
                            )
                    except Exception as _sd_err:
                        print(f"[Classroom] session_data merge (non-fatal): {_sd_err}")

                # Crystallize each significant pattern so coach + Nate can
                # surface it later.
                try:
                    from app.websocket.crystal_recall_bridge import (
                        crystallize_from_conversation as _pat_crystallize,
                    )
                    pat_target_id = client_id or coach_id
                    pat_target_name = client_name or (
                        pat_target_id[:12] if pat_target_id else ""
                    )
                    sessions_n = int(detected.get("sessions_analyzed", 0) or 0)
                    for pattern in detected.get("patterns", []) or []:
                        try:
                            ch = await _pat_crystallize(
                                db_pool,
                                pat_target_id,
                                f"Longitudinal pattern: "
                                f"{pattern.get('pattern', 'PATTERN')} — "
                                f"{pattern.get('clinical_note', '')}",
                                f"Detected across {sessions_n} sessions. "
                                "Treat as one signal alongside coach "
                                "judgment.",
                                user_name=pat_target_name,
                                domain=pattern.get(
                                    "recommended_focus", "clinical"
                                ),
                                min_score=0,
                                origin_surface="multimodal_pattern",
                            )
                            if ch:
                                crystals_created.append({
                                    "hash": ch,
                                    "domain": pattern.get(
                                        "recommended_focus", "clinical"
                                    ),
                                    "source": "multimodal_pattern",
                                })
                        except Exception as _pc_err:
                            print(f"[Classroom] pattern crystal (non-fatal): {_pc_err}")
                except ImportError as _pi_err:
                    print(f"[Classroom] pattern crystallize import (non-fatal): {_pi_err}")
            except Exception as _mf_err:
                print(f"[Classroom] multimodal fusion (non-fatal): {_mf_err}")

        analysis["crystals_created"] = crystals_created

        for s in sessions:
            if s.get("session_id") == video_id:
                s["status"] = "analyzed"
                s["analysis"] = analysis
                break
        try:
            with open(classroom_sessions_file, "w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2)
        except Exception:
            pass

        try:
            ai_result = {
                "strengths": ["Video analysis completed"],
                "growth_areas": ["Review voice timeline and visual cues for presence"],
                "key_moments": key_moments,
                "overall_rating": int(round(tps)),
                "dojo_scenarios": [],
                "coach_query_response": f"Coach asked: {coach_query}" if coach_query else "",
                "visual_observations": visual_insights,
                "coaching_insights": coaching_insights,
            }
            await self._push_to_night_school(
                ai_result=ai_result,
                coach_id=coach_id,
                session_id=video_id,
                vtt_content="",
                full_analysis=analysis,
            )
        except Exception as e:
            print(f"[Classroom] Night School push failed for video: {e}")

        try:
            payload = dict(analysis)
            payload.setdefault("strengths", ["Video session processed"])
            payload.setdefault("growth_areas", ["Review observations and voice timeline for pacing"])
            payload.setdefault("reflection_questions", [
                "What did you notice about your therapeutic presence on camera?",
                "Where might you deepen attunement in the next session?",
            ])
            payload.setdefault("metrics", {})
            if visual_insights:
                payload["visual_observations_summary"] = (visual_insights or "")[:4000]
            if facial_summary:
                payload["facial_summary"] = facial_summary
            if emotional_timeline:
                payload["emotional_timeline"] = emotional_timeline
            if analysis.get("multimodal_fusion"):
                payload["multimodal_fusion"] = analysis["multimodal_fusion"]
            if analysis.get("clinical_flags"):
                payload["clinical_flags"] = analysis["clinical_flags"]
            if analysis.get("session_arc"):
                payload["session_arc"] = analysis["session_arc"]
            if analysis.get("longitudinal_patterns"):
                payload["longitudinal_patterns"] = analysis["longitudinal_patterns"]
            await notify_coach(
                coach_id=coach_id,
                message_type="classroom_analysis_complete",
                data={
                    "session_id": video_id,
                    "source": "video",
                    "analysis": payload,
                },
            )
        except Exception as _n_err:
            print(f"[Classroom] Video notify_coach failed: {_n_err}")

        return analysis

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
