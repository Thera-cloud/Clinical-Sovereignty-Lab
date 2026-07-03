"""
LITTLE NATE — Avatar WebSocket Handlers
Version: 1.0

Handles avatar-specific WebSocket messages for voice-driven avatar interactions.
"""

import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

class AvatarHandler:
    """
    Handles avatar mode WebSocket messages.
    
    Processes voice input, determines avatar expressions/gestures,
    and manages avatar state for Top Tier clients.
    """
    
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self.avatar_configs_dir = vault_root / "avatar_configs"
        self.avatar_configs_dir.mkdir(parents=True, exist_ok=True)
    
    async def handle_avatar_user_speech(
        self, 
        ws, 
        profile: Dict[str, Any], 
        data: Dict[str, Any], 
        cortex
    ) -> None:
        """
        Process voice input from avatar mode client.
        
        Args:
            ws: WebSocket connection
            profile: User profile dictionary
            data: Message data containing 'text' field
            cortex: AzureCortex AI instance for processing
        """
        text = data.get('text', '').strip()
        
        if not text:
            await ws.send(json.dumps({
                'type': 'avatar_response',
                'error': 'Empty speech input',
            }))
            return
        
        try:
            # Process through existing AI pipeline
            ai_response = await cortex.process_interaction(profile, text)
            
            # Determine avatar state based on response
            avatar_state = self._determine_avatar_state(ai_response, text)
            environment = self._determine_environment(profile)
            
            # Calculate approximate speech duration
            response_text = ai_response.get('text', '') if isinstance(ai_response, dict) else str(ai_response)
            word_count = len(response_text.split())
            duration_ms = word_count * 300  # ~300ms per word
            
            await ws.send(json.dumps({
                'type': 'avatar_response',
                'speech': {
                    'text': response_text,
                    'duration_ms': duration_ms,
                },
                'avatar_state': avatar_state,
                'environment': environment,
                'timestamp': datetime.utcnow().isoformat(),
            }))
            
        except Exception as e:
            await ws.send(json.dumps({
                'type': 'avatar_response',
                'error': str(e),
                'speech': {
                    'text': "I'm having a moment of difficulty. Can you give me a second?",
                    'duration_ms': 3000,
                },
                'avatar_state': {
                    'expression': 'THOUGHTFUL',
                    'gesture': 'NONE',
                    'body_position': 'RELAXED_NEUTRAL',
                },
            }))
    
    def _determine_avatar_state(
        self, 
        response: Any, 
        user_input: str = ""
    ) -> Dict[str, Any]:
        """
        Map AI response content to avatar expression and gesture.
        
        Analyzes response text and user input to determine the most
        appropriate emotional expression and accompanying gesture.
        """
        # Extract text from response
        if isinstance(response, dict):
            text = response.get('text', '').lower()
            emotion = response.get('emotion', '')
            therapeutic_mode = response.get('therapeutic_mode', '')
        else:
            text = str(response).lower()
            emotion = ''
            therapeutic_mode = ''
        
        user_lower = user_input.lower()
        
        # Default state
        expression = 'WARM'
        gesture = 'NONE'
        body_position = 'RELAXED_NEUTRAL'
        transition_ms = 500
        
        # Empathy detection - responding to pain/struggle
        empathy_keywords = [
            'understand', 'hear you', 'that must be', 'sounds difficult',
            'sounds like', 'i sense', 'longing', 'draining',
            'i can see', 'that\'s hard', 'i\'m sorry', 'must feel',
            'pain', 'struggle', 'hurting'
        ]
        if any(kw in text for kw in empathy_keywords):
            expression = 'EMPATHETIC'
            gesture = 'HAND_ON_HEART'
            body_position = 'ATTENTIVE_LEAN'
            transition_ms = 600
        
        # Encouragement detection - celebrating progress
        elif any(kw in text for kw in ['great job', 'proud of you', 'amazing', 'wonderful', 'excellent', 'well done', 'congratulations']):
            expression = 'PROUD'
            gesture = 'THUMBS_UP'
            body_position = 'CELEBRATORY_RAISE'
            transition_ms = 400
        
        # Encouragement (lighter)
        elif any(kw in text for kw in ['you can', 'you\'re doing', 'keep going', 'good work', 'nice']):
            expression = 'ENCOURAGING'
            gesture = 'OPEN_PALMS'
            body_position = 'OPEN_WELCOMING'
        
        # Calming detection - stress/anxiety response
        elif any(kw in text for kw in ['breathe', 'calm', 'ground', 'relax', 'slow down', 'take a moment', 'pause']):
            expression = 'CALMING'
            gesture = 'HANDS_TOGETHER'
            body_position = 'RELAXED_NEUTRAL'
            transition_ms = 800
        
        # Question detection
        elif '?' in text:
            expression = 'CURIOUS'
            gesture = 'CHIN_REST'
            body_position = 'ATTENTIVE_LEAN'
        
        # Validation detection
        elif any(kw in text for kw in ['valid', 'makes sense', 'natural to feel', 'understandable', 'of course']):
            expression = 'VALIDATING'
            gesture = 'GENTLE_NOD'
        
        # Greeting detection
        elif any(kw in text for kw in ['hello', 'hi ', 'hey ', 'good morning', 'good evening', 'welcome']):
            expression = 'WARM'
            gesture = 'WAVE'
            body_position = 'OPEN_WELCOMING'
        
        # Check user's emotional state for additional context
        if any(kw in user_lower for kw in ['scared', 'afraid', 'anxious', 'worried', 'stressed']):
            if expression == 'WARM':
                expression = 'CALMING'
                gesture = 'HANDS_TOGETHER'
        
        elif any(kw in user_lower for kw in ['sad', 'depressed', 'hopeless', 'crying', 'hurt']):
            if expression == 'WARM':
                expression = 'EMPATHETIC'
                gesture = 'HAND_ON_HEART'

        # Mis-mirror guard — never celebrate or idle-warm at disclosed distress
        user_distress = any(
            kw in user_lower
            for kw in [
                'sad', 'exhaust', 'tired', 'anxious', 'scared', 'hurt', 'alone',
                'grief', 'cry', 'overwhelm', 'hopeless', 'draining', 'longing',
            ]
        )
        if user_distress and expression in ('WARM', 'PROUD', 'ENCOURAGING', 'CURIOUS'):
            expression = 'EMPATHETIC'
            gesture = 'HAND_ON_HEART'
            body_position = 'ATTENTIVE_LEAN'
        
        # Override based on therapeutic mode if available
        if therapeutic_mode:
            mode_lower = therapeutic_mode.lower()
            if 'grounding' in mode_lower:
                expression = 'CALMING'
                gesture = 'HANDS_TOGETHER'
            elif 'celebration' in mode_lower:
                expression = 'PROUD'
                gesture = 'THUMBS_UP'
            elif 'validation' in mode_lower:
                expression = 'VALIDATING'
                gesture = 'GENTLE_NOD'
        
        return {
            'expression': expression,
            'gesture': gesture,
            'body_position': body_position,
            'transition_duration_ms': transition_ms,
            'intensity': 0.8,
        }
    
    def _determine_environment(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Determine environment based on user preferences and session context.
        """
        # Check user preferences
        preferences = profile.get('avatar_preferences', {})
        default_env = preferences.get('default_environment', 'COZY_STUDY')
        
        # Time-based adjustments
        hour = datetime.now().hour
        if hour >= 21 or hour < 6:
            lighting = 'dim'
            if default_env == 'COZY_STUDY':
                default_env = 'WARM_FIREPLACE'
        elif hour < 9:
            lighting = 'natural'
        elif hour >= 17:
            lighting = 'warm'
        else:
            lighting = 'natural'
        
        return {
            'setting': default_env,
            'lighting': lighting,
            'soundscape': 'SILENCE',
        }
    
    def load_avatar_config(self, user_id: str) -> Dict[str, Any]:
        """
        Load user's avatar customization preferences.
        
        Returns default configuration if user hasn't customized.
        """
        config_path = self.avatar_configs_dir / f"{user_id}.json"
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        
        # Default configuration - friendly therapist appearance
        return {
            'appearance': {
                'skin_tone': 'MEDIUM',
                'hair_style': 'SHORT_CLASSIC',
                'hair_color': 'SALT_PEPPER',
                'eye_color': 'BROWN',
                'glasses': 'THIN_METAL',
                'clothing_style': 'CARDIGAN',
                'clothing_color': 'NAVY',
                'show_beard': False,
                'beard_style': 'CLEAN',
            },
            'preferences': {
                'default_environment': 'COZY_STUDY',
                'voice_speed': 1.0,
                'voice_pitch': 1.0,
                'enable_gestures': True,
                'enable_environment_sounds': False,
            },
            'voice': {
                'azure_voice': 'en-US-GuyNeural',
                'style': 'friendly',
            }
        }
    
    def save_avatar_config(self, user_id: str, config: Dict[str, Any]) -> bool:
        """
        Save user's avatar customization preferences.
        """
        config_path = self.avatar_configs_dir / f"{user_id}.json"
        
        try:
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            print(f"[AvatarHandler] Failed to save config for {user_id}: {e}")
            return False
    
    async def handle_breathing_exercise(
        self, 
        ws, 
        data: Dict[str, Any]
    ) -> None:
        """
        Guide a breathing exercise with avatar demonstration.
        """
        exercise_type = data.get('exercise', 'BOX')
        
        # Define breathing patterns
        patterns = {
            'BOX': [
                ('INHALE', 4000),
                ('HOLD', 4000),
                ('EXHALE', 4000),
                ('HOLD', 4000),
            ],
            '4_7_8': [
                ('INHALE', 4000),
                ('HOLD', 7000),
                ('EXHALE', 8000),
            ],
            'CALM': [
                ('INHALE', 4000),
                ('EXHALE', 6000),
            ],
            'GROUNDING': [
                ('INHALE', 5000),
                ('HOLD', 2000),
                ('EXHALE', 5000),
                ('HOLD', 2000),
            ],
        }
        
        pattern = patterns.get(exercise_type, patterns['BOX'])
        cycles = data.get('cycles', 4)
        
        await ws.send(json.dumps({
            'type': 'avatar_breathing_start',
            'exercise': exercise_type,
            'total_cycles': cycles,
        }))
        
        for cycle in range(cycles):
            for phase, duration_ms in pattern:
                await ws.send(json.dumps({
                    'type': 'avatar_breathing_phase',
                    'phase': phase,
                    'duration_ms': duration_ms,
                    'cycle': cycle + 1,
                    'total_cycles': cycles,
                }))
                await asyncio.sleep(duration_ms / 1000)
        
        await ws.send(json.dumps({
            'type': 'avatar_breathing_complete',
            'exercise': exercise_type,
            'cycles_completed': cycles,
        }))
    
    async def handle_celebration(
        self, 
        ws, 
        data: Dict[str, Any]
    ) -> None:
        """
        Trigger a celebration animation for milestone achievements.
        """
        milestone = data.get('milestone', 'general')
        intensity = data.get('intensity', 'normal')  # 'subtle', 'normal', 'big'
        
        celebration_states = {
            'subtle': {
                'expression': 'WARM',
                'gesture': 'GENTLE_NOD',
                'duration_ms': 2000,
            },
            'normal': {
                'expression': 'PROUD',
                'gesture': 'THUMBS_UP',
                'duration_ms': 3000,
            },
            'big': {
                'expression': 'PROUD',
                'gesture': 'OPEN_PALMS',
                'duration_ms': 4000,
                'confetti': True,
            },
        }
        
        state = celebration_states.get(intensity, celebration_states['normal'])
        
        await ws.send(json.dumps({
            'type': 'avatar_celebration',
            'milestone': milestone,
            **state,
        }))


def create_avatar_handler(vault_root: Path) -> AvatarHandler:
    """Factory function to create an AvatarHandler instance."""
    return AvatarHandler(vault_root)
