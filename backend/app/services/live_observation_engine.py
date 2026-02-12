"""
Live Observation Engine - Real-time session analysis with wisdom integration

This module provides enhanced observation capabilities during live coaching sessions:
- Combines transcript keywords with biometric data
- Uses Night School wisdom for context-aware suggestions
- Generates observations based on therapeutic patterns
- Tracks session dynamics in real-time
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class ObservationType(str, Enum):
    """Types of observations the engine can generate."""
    LONGING_SIGNAL = "LONGING_SIGNAL"
    FIXING_SIGNAL = "FIXING_SIGNAL"
    ESCALATION_SIGNAL = "ESCALATION_SIGNAL"
    DYSREGULATION_DETECTED = "DYSREGULATION_DETECTED"
    BREAKTHROUGH_MOMENT = "BREAKTHROUGH_MOMENT"
    HIGH_GAP_DETECTED = "HIGH_GAP_DETECTED"
    WISDOM_OPPORTUNITY = "WISDOM_OPPORTUNITY"
    ATTACHMENT_CUE = "ATTACHMENT_CUE"
    REGULATORY_CUE = "REGULATORY_CUE"
    DEFENSIVE_PATTERN = "DEFENSIVE_PATTERN"


@dataclass
class Observation:
    """An observation generated during a live session."""
    id: str
    timestamp: str
    type: ObservationType
    message: str
    evidence: str
    source: str  # 'keywords', 'biometrics', 'wisdom', 'combined'
    confidence: float
    wisdom_reference: Optional[str] = None
    suggested_response: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            'type': self.type.value
        }


class LiveObservationEngine:
    """
    Enhanced real-time observation engine for live coaching sessions.
    
    Combines:
    - Keyword-based detection (longing, fixing, escalation signals)
    - Biometric analysis (C_emo, GAP, stability)
    - Night School wisdom (therapeutic guidelines)
    - Pattern recognition (attachment, regulatory, defensive)
    """
    
    # Keyword patterns for signal detection
    KEYWORD_PATTERNS = {
        ObservationType.LONGING_SIGNAL: [
            r"\b(longing|need|i never|i always|i feel|i'm hurt|i am hurt|want you to|wish you would)\b",
            r"\b(never listen|don't care|feel alone|abandoned|rejected)\b"
        ],
        ObservationType.FIXING_SIGNAL: [
            r"\b(fix|solution|should|just|advice|here's what|you need to|why don't you)\b",
            r"\b(try this|have you tried|the answer is|simply|easy)\b"
        ],
        ObservationType.ESCALATION_SIGNAL: [
            r"\b(angry|shut down|silent|leave|divorce|done|finished)\b",
            r"\b(hate|can't stand|unbearable|worst|never again)\b"
        ],
        ObservationType.ATTACHMENT_CUE: [
            r"\b(hold me|need you|afraid you'll leave|don't abandon|stay with me)\b",
            r"\b(reach for|pull away|withdraw|chase|pursue)\b"
        ],
        ObservationType.REGULATORY_CUE: [
            r"\b(calm down|breathe|ground|pause|slow down|take a moment)\b",
            r"\b(overwhelming|flooded|can't think|spinning|racing)\b"
        ],
        ObservationType.DEFENSIVE_PATTERN: [
            r"\b(but you|what about|you always|you never|it's not my fault)\b",
            r"\b(defending|justify|excuse|blame|attack)\b"
        ]
    }
    
    # Biometric thresholds
    THRESHOLDS = {
        'c_emo_low': 0.3,           # Below this = dysregulation
        'c_emo_high': 0.9,          # Above this = breakthrough potential
        'gap_high': 0.5,            # High emotional gap
        'stability_low': 0.4,       # Unstable state
        'cee_window_min_seconds': 15  # Minimum for CEE window significance
    }
    
    def __init__(self, wisdom_cache: Optional[Dict] = None):
        """
        Initialize the observation engine.
        
        Args:
            wisdom_cache: Pre-loaded Night School wisdom entries
        """
        self.wisdom_cache = wisdom_cache or {}
        self.session_history: Dict[str, List[Observation]] = {}
        self.observation_counts: Dict[str, Dict[str, int]] = {}
        
        # Compile regex patterns for efficiency
        self._compiled_patterns = {}
        for obs_type, patterns in self.KEYWORD_PATTERNS.items():
            self._compiled_patterns[obs_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
    
    def update_wisdom_cache(self, wisdom: Dict):
        """Update the wisdom cache with new entries."""
        self.wisdom_cache = wisdom
    
    def analyze_moment(
        self,
        live_session_id: str,
        text: Optional[str] = None,
        biometrics: Optional[Dict] = None,
        nevedal_state: Optional[Dict] = None,
        context: Optional[Dict] = None
    ) -> Optional[Observation]:
        """
        Analyze a moment in the session and generate observation if warranted.
        
        Args:
            live_session_id: Session identifier
            text: Transcript text or note to analyze
            biometrics: Raw biometric data
            nevedal_state: Processed Nevedal state (C_emo, GAP, etc.)
            context: Additional context (client history, etc.)
            
        Returns:
            Observation if one is warranted, None otherwise
        """
        observations = []
        
        # Initialize session tracking
        if live_session_id not in self.session_history:
            self.session_history[live_session_id] = []
            self.observation_counts[live_session_id] = {}
        
        # Analyze text for keyword patterns
        if text:
            text_obs = self._analyze_text(text, live_session_id)
            if text_obs:
                observations.append(text_obs)
        
        # Analyze biometrics for state changes
        if nevedal_state:
            bio_obs = self._analyze_biometrics(nevedal_state, live_session_id)
            if bio_obs:
                observations.append(bio_obs)
        
        # Check wisdom for opportunities
        if text or nevedal_state:
            wisdom_obs = self._check_wisdom_opportunities(
                text=text,
                nevedal_state=nevedal_state,
                live_session_id=live_session_id
            )
            if wisdom_obs:
                observations.append(wisdom_obs)
        
        # Return highest priority observation (if any)
        if observations:
            # Sort by priority and return best
            best = self._select_best_observation(observations, live_session_id)
            if best:
                self.session_history[live_session_id].append(best)
                obs_type = best.type.value
                self.observation_counts[live_session_id][obs_type] = \
                    self.observation_counts[live_session_id].get(obs_type, 0) + 1
                return best
        
        return None
    
    def _analyze_text(self, text: str, live_session_id: str) -> Optional[Observation]:
        """Analyze text for keyword patterns."""
        import uuid
        
        for obs_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    message = self._get_message_for_type(obs_type)
                    
                    return Observation(
                        id=f"LSO_{uuid.uuid4().hex[:10]}",
                        timestamp=datetime.now().isoformat(),
                        type=obs_type,
                        message=message,
                        evidence=text[:220],
                        source="keywords",
                        confidence=0.7,
                        suggested_response=self._get_suggested_response(obs_type)
                    )
        
        return None
    
    def _analyze_biometrics(
        self,
        nevedal_state: Dict,
        live_session_id: str
    ) -> Optional[Observation]:
        """Analyze Nevedal state for significant changes."""
        import uuid
        
        c_emo = nevedal_state.get('c_emo', 0.5)
        gap = nevedal_state.get('gap', 0.0)
        stability = nevedal_state.get('stability', 0.5)
        trend = nevedal_state.get('trend', 'STABLE')
        cee_window = nevedal_state.get('cee_window', False)
        cee_duration = nevedal_state.get('cee_duration_seconds', 0)
        
        # Check for dysregulation
        if c_emo < self.THRESHOLDS['c_emo_low'] and trend == 'FALLING':
            return Observation(
                id=f"LSO_{uuid.uuid4().hex[:10]}",
                timestamp=datetime.now().isoformat(),
                type=ObservationType.DYSREGULATION_DETECTED,
                message=f"Emotional coherence dropping (C_emo: {c_emo:.2f}). Consider a grounding pause or regulation exercise.",
                evidence=f"C_emo: {c_emo:.2f}, GAP: {gap:.2f}, Trend: {trend}",
                source="biometrics",
                confidence=0.85,
                suggested_response="Let's pause for a moment. Take a breath. Can you notice where you feel this in your body?"
            )
        
        # Check for breakthrough moment
        if cee_window and c_emo > self.THRESHOLDS['c_emo_high'] and cee_duration >= self.THRESHOLDS['cee_window_min_seconds']:
            return Observation(
                id=f"LSO_{uuid.uuid4().hex[:10]}",
                timestamp=datetime.now().isoformat(),
                type=ObservationType.BREAKTHROUGH_MOMENT,
                message=f"Strong emotional coherence detected (C_emo: {c_emo:.2f}). CEE window active - this is a therapeutic opportunity.",
                evidence=f"C_emo: {c_emo:.2f}, CEE Duration: {cee_duration}s",
                source="biometrics",
                confidence=0.9,
                suggested_response="This is a beautiful moment of connection. Let it land. You might ask: 'What are you noticing right now?'"
            )
        
        # Check for high GAP
        if gap > self.THRESHOLDS['gap_high']:
            return Observation(
                id=f"LSO_{uuid.uuid4().hex[:10]}",
                timestamp=datetime.now().isoformat(),
                type=ObservationType.HIGH_GAP_DETECTED,
                message=f"High emotional gap detected (GAP: {gap:.2f}). The client may be disconnecting or flooding.",
                evidence=f"GAP: {gap:.2f}, Stability: {stability:.2f}",
                source="biometrics",
                confidence=0.75,
                suggested_response="I'm noticing some intensity. Let's slow down. What's happening for you right now?"
            )
        
        return None
    
    def _check_wisdom_opportunities(
        self,
        text: Optional[str],
        nevedal_state: Optional[Dict],
        live_session_id: str
    ) -> Optional[Observation]:
        """Check if Night School wisdom applies to current moment."""
        import uuid
        
        if not self.wisdom_cache:
            return None
        
        # Simple keyword matching against wisdom content
        combined_text = (text or "").lower()
        
        # Add biometric context
        if nevedal_state:
            if nevedal_state.get('c_emo', 0.5) < 0.5:
                combined_text += " distress dysregulation "
            if nevedal_state.get('gap', 0) > 0.3:
                combined_text += " disconnection gap "
        
        # Search wisdom for relevant entries
        relevant_wisdom = []
        for entry in self.wisdom_cache.get('entries', []):
            if not entry.get('approved', False):
                continue
            
            content = (entry.get('content') or "").lower()
            category = entry.get('category', '')
            
            # Check for keyword overlap
            if any(word in combined_text for word in content.split()[:10]):
                relevant_wisdom.append(entry)
        
        if relevant_wisdom:
            # Use the most relevant wisdom
            best = relevant_wisdom[0]
            
            return Observation(
                id=f"LSO_{uuid.uuid4().hex[:10]}",
                timestamp=datetime.now().isoformat(),
                type=ObservationType.WISDOM_OPPORTUNITY,
                message=f"Night School wisdom applies: {best.get('content', '')[:150]}...",
                evidence=f"Category: {best.get('category', 'general')}",
                source="wisdom",
                confidence=0.6,
                wisdom_reference=best.get('id'),
                suggested_response=self._extract_suggestion_from_wisdom(best)
            )
        
        return None
    
    def _get_message_for_type(self, obs_type: ObservationType) -> str:
        """Get the coaching message for an observation type."""
        messages = {
            ObservationType.LONGING_SIGNAL: 
                "Possible longing signal detected. Consider slowing down and asking for the underlying need in one sentence.",
            ObservationType.FIXING_SIGNAL:
                "Possible 'fixing' move. Consider: 'Before solutions, can you reflect what you heard and what it meant to them?'",
            ObservationType.ESCALATION_SIGNAL:
                "Escalation cue. Consider a brief regulation pause + name the cycle without blame.",
            ObservationType.ATTACHMENT_CUE:
                "Attachment need emerging. This is an opportunity for co-regulation and secure base presence.",
            ObservationType.REGULATORY_CUE:
                "Regulatory moment. Support their window of tolerance - validate and ground.",
            ObservationType.DEFENSIVE_PATTERN:
                "Defensive pattern observed. Avoid engaging with content - focus on the underlying feeling.",
        }
        return messages.get(obs_type, "Observation noted.")
    
    def _get_suggested_response(self, obs_type: ObservationType) -> str:
        """Get a suggested response for an observation type."""
        responses = {
            ObservationType.LONGING_SIGNAL:
                "Can you tell me more about what you need right now?",
            ObservationType.FIXING_SIGNAL:
                "Before we go to solutions, I want to make sure I understand. What did that feel like for you?",
            ObservationType.ESCALATION_SIGNAL:
                "Let's pause for a moment. I can see this is bringing up a lot. What's happening inside right now?",
            ObservationType.ATTACHMENT_CUE:
                "I'm right here with you. I'm not going anywhere. What do you need from me in this moment?",
            ObservationType.REGULATORY_CUE:
                "Let's take a breath together. Can you feel your feet on the floor?",
            ObservationType.DEFENSIVE_PATTERN:
                "I hear you. It sounds like this is really important to you. Can we slow down and look at what's underneath?",
        }
        return responses.get(obs_type, "")
    
    def _extract_suggestion_from_wisdom(self, wisdom_entry: Dict) -> str:
        """Extract a suggested response from wisdom content."""
        content = wisdom_entry.get('content', '')
        
        # Look for actionable phrases
        if 'consider' in content.lower():
            idx = content.lower().find('consider')
            return content[idx:idx+200]
        if 'try' in content.lower():
            idx = content.lower().find('try')
            return content[idx:idx+200]
        
        return content[:200] if content else ""
    
    def _select_best_observation(
        self,
        observations: List[Observation],
        live_session_id: str
    ) -> Optional[Observation]:
        """Select the best observation from candidates, avoiding repetition."""
        if not observations:
            return None
        
        # Get recent observation types for this session
        recent_types = set()
        for obs in self.session_history.get(live_session_id, [])[-10:]:
            recent_types.add(obs.type)
        
        # Sort by confidence and novelty
        scored = []
        for obs in observations:
            score = obs.confidence
            
            # Reduce score for repeated types
            if obs.type in recent_types:
                score *= 0.5
            
            # Boost biometric observations (higher confidence)
            if obs.source == "biometrics":
                score *= 1.2
            
            # Boost wisdom opportunities (valuable context)
            if obs.source == "wisdom":
                score *= 1.1
            
            scored.append((score, obs))
        
        # Return highest scoring observation if above threshold
        scored.sort(key=lambda x: x[0], reverse=True)
        
        if scored and scored[0][0] > 0.3:
            return scored[0][1]
        
        return None
    
    def get_session_summary(self, live_session_id: str) -> Dict:
        """Get a summary of observations for a session."""
        history = self.session_history.get(live_session_id, [])
        counts = self.observation_counts.get(live_session_id, {})
        
        return {
            "total_observations": len(history),
            "observation_counts": counts,
            "observation_types": list(counts.keys()),
            "sources": list(set(o.source for o in history)),
            "most_common_type": max(counts.items(), key=lambda x: x[1])[0] if counts else None,
        }
    
    def clear_session(self, live_session_id: str):
        """Clear history for a completed session."""
        self.session_history.pop(live_session_id, None)
        self.observation_counts.pop(live_session_id, None)


def create_live_observation_engine(wisdom_cache: Optional[Dict] = None) -> LiveObservationEngine:
    """Factory function to create a LiveObservationEngine instance."""
    return LiveObservationEngine(wisdom_cache=wisdom_cache)
