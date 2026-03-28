"""
Visual Biometric Extractor - Azure Vision API integration for session analysis

This module uses Azure OpenAI's vision capabilities to analyze video frames and extract:
- Facial affect (valence, arousal)
- Eye contact / gaze patterns
- Body language (posture, lean, gestures)
- Engagement indicators
- Micro-expression detection

These visual biometrics integrate with the Nevedal Engine for comprehensive
emotional coherence analysis.
"""

import asyncio
import base64
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import aiohttp

from app.config import settings
from app.services.nate_ai_config import NATE_CHAT_URL, NATE_CHAT_KEY, nate_chat_headers, nate_chat_payload


class VisualBiometricExtractor:
    """
    Extracts visual biometrics from video frames using Azure OpenAI Vision API.
    
    Provides standardized metrics compatible with the Nevedal Engine:
    - gaze_contact_ratio (0-1)
    - body_lean_angle (degrees, negative=away, positive=toward)
    - facial_affect_valence (-1 to 1, negative=distress, positive=joy)
    - facial_affect_arousal (0 to 1, low=calm, high=activated)
    - engagement_score (0-1)
    """
    
    # Vision analysis prompt template
    ANALYSIS_PROMPT = """Analyze this therapy/coaching session video frame. You are helping Little Nate learn to observe and understand human emotional states during therapeutic sessions.

Please analyze the visible people in this frame and provide:

1. **Facial Affect**:
   - Valence: Overall emotional tone (-1.0 to 1.0, where -1 is distress/sadness, 0 is neutral, 1 is joy/happiness)
   - Arousal: Activation level (0.0 to 1.0, where 0 is calm/drowsy, 1 is highly activated/excited)
   - Primary emotion detected (if any): anger, sadness, fear, surprise, joy, disgust, contempt, or neutral

2. **Gaze and Eye Contact**:
   - Is there eye contact between people? (true/false)
   - Gaze direction: looking at each other, looking away, looking down

3. **Body Language**:
   - Posture: open/closed, relaxed/tense
   - Body lean: leaning toward (-positive), neutral (0), or away (+negative) in degrees (-30 to +30)
   - Visible gestures: none, hand movements, pointing, self-touch, etc.

4. **Engagement Indicators**:
   - Overall engagement score (0.0 to 1.0)
   - Signs of attentiveness or disconnection

5. **Notable Observations**:
   - Any micro-expressions or sudden changes
   - Signs of emotional dysregulation
   - Therapeutic moments (connection, breakthrough, repair)

Respond in JSON format:
{
    "facial_affect_valence": float,
    "facial_affect_arousal": float,
    "primary_emotion": "string",
    "gaze_contact": boolean,
    "gaze_direction": "string",
    "body_posture": "string",
    "body_lean_angle": float,
    "visible_gestures": ["string"],
    "engagement_score": float,
    "attentiveness": "string",
    "is_notable": boolean,
    "notable_description": "string",
    "people_count": int,
    "confidence": float
}"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: str = "gpt-4.1"
    ):
        """
        Initialize the Visual Biometric Extractor.
        
        Args:
            api_key: Azure OpenAI API key (defaults to settings)
            endpoint: Azure OpenAI endpoint URL (defaults to settings)
            model: Model to use for vision analysis
        """
        self.api_key = api_key or NATE_CHAT_KEY
        self.endpoint = endpoint or settings.AZURE_ENDPOINT
        self.model = model
        
        if not self.api_key:
            print("[VisualBiometrics] WARNING: No API key configured")
    
    async def analyze_frame(
        self,
        frame_base64: str,
        frame_index: int = 0,
        context: Optional[str] = None
    ) -> Dict:
        """
        Analyze a single video frame for visual biometrics.
        
        Args:
            frame_base64: Base64-encoded JPEG image
            frame_index: Index of this frame in the video
            context: Optional context about the session
            
        Returns:
            Dict with extracted biometrics
        """
        result = {
            "frame_index": frame_index,
            "analyzed_at": datetime.now().isoformat(),
            "facial_affect_valence": 0.0,
            "facial_affect_arousal": 0.5,
            "primary_emotion": "neutral",
            "gaze_contact": False,
            "gaze_direction": "unknown",
            "body_posture": "unknown",
            "body_lean_angle": 0.0,
            "visible_gestures": [],
            "engagement_score": 0.5,
            "attentiveness": "unknown",
            "is_notable": False,
            "notable_description": "",
            "people_count": 0,
            "confidence": 0.0,
            "error": None
        }
        
        if not self.api_key:
            result["error"] = "No API key configured"
            return result
        
        try:
            # Build the vision API request
            prompt = self.ANALYSIS_PROMPT
            if context:
                prompt = f"{context}\n\n{prompt}"
            
            async with aiohttp.ClientSession() as session:
                messages = [
                    {
                        "role": "system",
                        "content": "You are a visual analysis assistant helping with therapeutic session observation. Respond only with valid JSON."
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{frame_base64}"
                                }
                            }
                        ]
                    }
                ]
                payload = nate_chat_payload(messages, max_tokens=1000)
                
                async with session.post(NATE_CHAT_URL, headers=nate_chat_headers(), json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        result["error"] = f"API error {response.status}: {error_text[:200]}"
                        return result
                    
                    response_data = await response.json()
                    
                    # Extract the response content
                    choices = response_data.get("choices", [])
                    if not choices:
                        result["error"] = "No response from API"
                        return result
                    
                    content = choices[0].get("message", {}).get("content", "")
                    
                    # Parse JSON from response
                    try:
                        # Find JSON in response
                        import re
                        json_match = re.search(r'\{[\s\S]*\}', content)
                        if json_match:
                            analysis = json.loads(json_match.group())
                            
                            # Update result with analysis
                            result["facial_affect_valence"] = float(analysis.get("facial_affect_valence", 0))
                            result["facial_affect_arousal"] = float(analysis.get("facial_affect_arousal", 0.5))
                            result["primary_emotion"] = analysis.get("primary_emotion", "neutral")
                            result["gaze_contact"] = bool(analysis.get("gaze_contact", False))
                            result["gaze_direction"] = analysis.get("gaze_direction", "unknown")
                            result["body_posture"] = analysis.get("body_posture", "unknown")
                            result["body_lean_angle"] = float(analysis.get("body_lean_angle", 0))
                            result["visible_gestures"] = analysis.get("visible_gestures", [])
                            result["engagement_score"] = float(analysis.get("engagement_score", 0.5))
                            result["attentiveness"] = analysis.get("attentiveness", "unknown")
                            result["is_notable"] = bool(analysis.get("is_notable", False))
                            result["notable_description"] = analysis.get("notable_description", "")
                            result["people_count"] = int(analysis.get("people_count", 0))
                            result["confidence"] = float(analysis.get("confidence", 0.8))
                        else:
                            result["error"] = "Could not parse JSON from response"
                    except json.JSONDecodeError as e:
                        result["error"] = f"JSON parse error: {e}"
            
            return result
            
        except Exception as e:
            result["error"] = str(e)
            import traceback
            traceback.print_exc()
            return result
    
    async def analyze_frame_batch(
        self,
        frames_base64: List[str],
        context: Optional[str] = None,
        max_concurrent: int = 3
    ) -> List[Dict]:
        """
        Analyze multiple frames with concurrency control.
        
        Args:
            frames_base64: List of base64-encoded frames
            context: Optional context about the session
            max_concurrent: Maximum concurrent API calls
            
        Returns:
            List of analysis results
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_with_limit(idx: int, frame: str) -> Dict:
            async with semaphore:
                return await self.analyze_frame(frame, idx, context)
        
        tasks = [
            analyze_with_limit(i, frame)
            for i, frame in enumerate(frames_base64)
        ]
        
        return await asyncio.gather(*tasks)
    
    def to_nevedal_format(self, analysis: Dict) -> Dict:
        """
        Convert analysis to Nevedal Engine compatible format.
        
        The Nevedal Engine expects specific fields for visual biometrics.
        """
        return {
            "gaze_contact_ratio": 1.0 if analysis.get("gaze_contact") else 0.0,
            "body_lean_angle": analysis.get("body_lean_angle", 0.0),
            "facial_affect_valence": analysis.get("facial_affect_valence", 0.0),
            "facial_affect_arousal": analysis.get("facial_affect_arousal", 0.5),
            "micro_expression_count": 1 if analysis.get("is_notable") else 0,
            "engagement_score": analysis.get("engagement_score", 0.5),
            "timestamp": analysis.get("analyzed_at", datetime.now().isoformat()),
            "source": "visual_biometrics",
            "confidence": analysis.get("confidence", 0.0)
        }
    
    def aggregate_session_biometrics(self, analyses: List[Dict]) -> Dict:
        """
        Aggregate multiple frame analyses into session-level biometrics.
        
        Args:
            analyses: List of frame analysis results
            
        Returns:
            Aggregated session biometrics
        """
        if not analyses:
            return {
                "frames_analyzed": 0,
                "average_valence": 0.0,
                "average_arousal": 0.5,
                "eye_contact_ratio": 0.0,
                "average_engagement": 0.5,
                "emotion_distribution": {},
                "notable_moments": []
            }
        
        valence_sum = 0.0
        arousal_sum = 0.0
        engagement_sum = 0.0
        eye_contact_count = 0
        emotions = {}
        notable = []
        valid_count = 0
        
        for a in analyses:
            if a.get("error"):
                continue
            
            valid_count += 1
            valence_sum += a.get("facial_affect_valence", 0)
            arousal_sum += a.get("facial_affect_arousal", 0.5)
            engagement_sum += a.get("engagement_score", 0.5)
            
            if a.get("gaze_contact"):
                eye_contact_count += 1
            
            emotion = a.get("primary_emotion", "neutral")
            emotions[emotion] = emotions.get(emotion, 0) + 1
            
            if a.get("is_notable"):
                notable.append({
                    "frame_index": a.get("frame_index"),
                    "description": a.get("notable_description"),
                    "emotion": emotion,
                    "engagement": a.get("engagement_score")
                })
        
        n = max(valid_count, 1)
        
        return {
            "frames_analyzed": len(analyses),
            "valid_frames": valid_count,
            "average_valence": round(valence_sum / n, 3),
            "average_arousal": round(arousal_sum / n, 3),
            "eye_contact_ratio": round(eye_contact_count / n, 3),
            "average_engagement": round(engagement_sum / n, 3),
            "emotion_distribution": emotions,
            "notable_moments": notable,
            "dominant_emotion": max(emotions.items(), key=lambda x: x[1])[0] if emotions else "neutral"
        }


def create_visual_biometric_extractor(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None
) -> VisualBiometricExtractor:
    """Factory function to create a VisualBiometricExtractor instance."""
    return VisualBiometricExtractor(
        api_key=api_key,
        endpoint=endpoint
    )
