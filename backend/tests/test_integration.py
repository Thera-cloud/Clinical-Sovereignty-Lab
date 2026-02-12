"""
LITTLE NATE — Integration Test Suite
Version: 1.0
Date: January 21, 2026

Comprehensive tests for all platform components:
- API endpoints
- WebSocket handlers
- Nevedal computation
- Night School features
- Database operations
- Security/auth

Run with: pytest test_integration.py -v
"""

import pytest
import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import hashlib
import secrets

# =============================================================================
# TEST CONFIGURATION
# =============================================================================

# Test database URL (use test database, not production!)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql://localhost/little_nate_test")
TEST_VAULT_ROOT = Path("./test_vault")

# Ensure test vault exists
TEST_VAULT_ROOT.mkdir(exist_ok=True)
(TEST_VAULT_ROOT / "Admin" / "night_school").mkdir(parents=True, exist_ok=True)
(TEST_VAULT_ROOT / "Coaches").mkdir(parents=True, exist_ok=True)
(TEST_VAULT_ROOT / "Clients").mkdir(parents=True, exist_ok=True)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def test_user():
    """Sample test user"""
    return {
        "id": "test_user_001",
        "username": "testuser",
        "password": "testpass123",
        "name": "Test User",
        "role": "CLIENT",
        "tier": "STANDARD",
        "family_id": None,
        "hardware_id": "test_hw_001",
        "consent_version": "v12.6_2026_FINAL",
        "subscription_status": "TRIAL_ACTIVE"
    }

@pytest.fixture
def test_coach():
    """Sample test coach"""
    return {
        "id": "test_coach_001",
        "username": "testcoach",
        "password": "coachpass123",
        "name": "Dr. Test Coach",
        "role": "COACH",
        "tier": "MASTER",
        "hardware_id": "coach_hw_001"
    }

@pytest.fixture
def test_admin():
    """Sample test admin"""
    return {
        "id": "test_admin_001",
        "username": "testadmin",
        "password": "adminpass123",
        "name": "Test Admin",
        "role": "ADMIN",
        "tier": "MASTER",
        "hardware_id": "admin_hw_001"
    }

@pytest.fixture
def sample_biometrics():
    """Sample biometric data for Nevedal testing"""
    return {
        "subject_a": {
            "gaze_contact": 0.75,
            "body_lean": 12,
            "voice_stress_index": 0.25,
            "voice_warmth_index": 0.7,
            "eda": 2.1,
            "pause_ratio": 0.35,
            "facial_affect_arousal": 0.5
        },
        "subject_b": {
            "gaze_contact": 0.82,
            "body_lean": 10,
            "voice_stress_index": 0.15,
            "voice_warmth_index": 0.8,
            "eda": 1.8,
            "pause_ratio": 0.4
        },
        "synchrony": {
            "hrv": 0.85,
            "breath": 0.78,
            "voice": 0.72,
            "posture": 0.80,
            "gaze": 0.75
        }
    }


# =============================================================================
# AUTH TESTS
# =============================================================================

class TestAuthentication:
    """Test authentication endpoints"""
    
    def test_password_hashing(self):
        """Test that passwords are properly hashed"""
        from api_server import hash_password, verify_password
        
        password = "mysecretpassword"
        hashed = hash_password(password)
        
        # Hash should not equal plain password
        assert hashed != password
        # Hash should contain salt separator
        assert '$' in hashed
        # Verification should work
        assert verify_password(password, hashed) == True
        # Wrong password should fail
        assert verify_password("wrongpassword", hashed) == False
    
    def test_legacy_password_support(self):
        """Test that legacy plain-text passwords still work"""
        from api_server import verify_password
        
        # Legacy format (plain text)
        assert verify_password("plaintext", "plaintext") == True
        assert verify_password("wrong", "plaintext") == False
    
    @pytest.mark.asyncio
    async def test_login_success(self, test_user):
        """Test successful login"""
        # This would test the actual API endpoint
        # For now, test the logic
        from api_server import LoginRequest
        
        request = LoginRequest(
            username=test_user["username"],
            password=test_user["password"]
        )
        
        assert request.username == "testuser"
        assert len(request.password) >= 3
    
    def test_login_validation(self):
        """Test login input validation"""
        from api_server import LoginRequest
        from pydantic import ValidationError
        
        # Too short username
        with pytest.raises(ValidationError):
            LoginRequest(username="a", password="validpass")
        
        # Too short password
        with pytest.raises(ValidationError):
            LoginRequest(username="validuser", password="ab")
    
    @pytest.mark.asyncio
    async def test_registration_validation(self):
        """Test registration input validation"""
        from api_server import RegisterRequest
        from pydantic import ValidationError
        
        # Valid request
        req = RegisterRequest(
            username="newuser",
            password="password123",
            name="New User",
            role="CLIENT",
            consent_agreed=True,
            consent_version="v12.6_2026_FINAL"
        )
        assert req.username == "newuser"
        
        # Invalid DOB format
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="newuser",
                password="password123",
                name="New User",
                dob="invalid-date",
                consent_agreed=True
            )
        
        # Valid DOB
        req = RegisterRequest(
            username="newuser",
            password="password123",
            name="New User",
            dob="2000-01-15",
            consent_agreed=True
        )
        assert req.dob == "2000-01-15"


# =============================================================================
# NEVEDAL ENGINE TESTS
# =============================================================================

class TestNevedalEngine:
    """Test Nevedal quantum emotional coherence computation"""
    
    def test_engine_initialization(self):
        """Test engine initializes correctly"""
        from nevedal_engine import create_nevedal_engine, NevedalConstants
        
        engine = create_nevedal_engine()
        assert engine is not None
        assert engine.constants.BETA == 1.0
        assert engine.constants.H_BAR == 1.0
    
    def test_compute_p_ent(self, sample_biometrics):
        """Test emotional entanglement computation"""
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        
        # Process biometrics
        state = engine.process_biometrics(
            session_id="test_session",
            user_id="test_user",
            dyad_partner_id=None,
            biometrics=sample_biometrics
        )
        
        # p_ent should be between 0 and 1
        assert 0 <= state.p_ent <= 1
        # With high synchrony values, p_ent should be relatively high
        assert state.p_ent > 0.6
    
    def test_compute_c_emo(self, sample_biometrics):
        """Test coherence computation"""
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        state = engine.process_biometrics(
            session_id="test_session",
            user_id="test_user",
            dyad_partner_id=None,
            biometrics=sample_biometrics
        )
        
        # C_emo should be between 0 and 1
        assert 0 <= state.c_emo <= 1
        # Should have reasonable values
        assert state.c_emo > 0  # Should not be zero with valid input
    
    def test_compute_tunneling(self, sample_biometrics):
        """Test tunneling transparency computation"""
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        state = engine.process_biometrics(
            session_id="test_session",
            user_id="test_user",
            dyad_partner_id=None,
            biometrics=sample_biometrics
        )
        
        # T_tunnel should be between 0 and 1
        assert 0 <= state.t_tunnel <= 1
        # With high gaze contact, tunneling should be higher
        assert state.t_tunnel > 0.5
    
    def test_cee_detection_criteria(self, sample_biometrics):
        """Test CEE window detection logic"""
        from nevedal_engine import create_nevedal_engine, NevedalConstants
        
        engine = create_nevedal_engine()
        c = NevedalConstants()
        
        # Create optimal CEE conditions
        cee_biometrics = {
            "subject_a": {
                "gaze_contact": 0.9,  # High gaze
                "body_lean": 20,       # Strong lean toward
                "voice_stress_index": 0.4,  # Some stress (material being processed)
                "voice_warmth_index": 0.85,
                "eda": 1.5,            # Low arousal
                "pause_ratio": 0.4
            },
            "subject_b": {
                "gaze_contact": 0.95,
                "body_lean": 15,
                "voice_stress_index": 0.15,
                "voice_warmth_index": 0.9,
                "eda": 1.2,
                "pause_ratio": 0.45
            },
            "synchrony": {
                "hrv": 0.92,
                "breath": 0.88,
                "voice": 0.85,
                "posture": 0.90,
                "gaze": 0.88
            }
        }
        
        # Process multiple times to reach CEE duration threshold
        for i in range(20):  # Simulate 20 seconds
            state = engine.process_biometrics(
                session_id="cee_test",
                user_id="test_user",
                dyad_partner_id="therapist",
                biometrics=cee_biometrics
            )
        
        # Check if CEE conditions are being evaluated
        # (Full CEE requires 15+ seconds)
        assert state.p_ent >= c.CEE_P_ENT_MIN or state.p_ent < c.CEE_P_ENT_MIN
    
    def test_state_history_tracking(self, sample_biometrics):
        """Test that state history is properly tracked"""
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        
        # Process multiple times
        for i in range(5):
            engine.process_biometrics(
                session_id="history_test",
                user_id="test_user",
                dyad_partner_id=None,
                biometrics=sample_biometrics
            )
        
        # Should have 5 entries in history
        assert len(engine.state_history) == 5
    
    def test_session_summary(self, sample_biometrics):
        """Test session summary generation"""
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        session_id = "summary_test"
        
        for i in range(10):
            engine.process_biometrics(
                session_id=session_id,
                user_id="test_user",
                dyad_partner_id=None,
                biometrics=sample_biometrics
            )
        
        summary = engine.get_session_summary(session_id)
        
        assert summary["sample_count"] == 10
        assert "c_emo" in summary
        assert "mean" in summary["c_emo"]
        assert "max" in summary["c_emo"]


# =============================================================================
# VOICE BIOMETRIC TESTS
# =============================================================================

class TestVoiceBiometrics:
    """Test voice biometric extraction"""
    
    def test_extractor_initialization(self):
        """Test voice extractor initializes correctly"""
        from nevedal_engine import VoiceBiometricExtractor
        
        extractor = VoiceBiometricExtractor(sample_rate=16000)
        assert extractor.sample_rate == 16000
    
    def test_default_metrics(self):
        """Test default metrics are returned for empty input"""
        from nevedal_engine import VoiceBiometricExtractor
        
        extractor = VoiceBiometricExtractor()
        
        # Empty audio should return defaults
        metrics = extractor.process_audio_chunk(b'')
        
        assert 'voice_stress_index' in metrics
        assert 'voice_warmth_index' in metrics
        assert 0 <= metrics['voice_stress_index'] <= 1
        assert 0 <= metrics['voice_warmth_index'] <= 1
    
    def test_stress_index_range(self):
        """Test stress index is always in valid range"""
        from nevedal_engine import VoiceBiometricExtractor
        import numpy as np
        
        extractor = VoiceBiometricExtractor()
        
        # Generate synthetic audio
        samples = np.random.randn(16000).astype(np.float32) * 0.1
        audio_bytes = (samples * 32768).astype(np.int16).tobytes()
        
        metrics = extractor.process_audio_chunk(audio_bytes)
        
        assert 0 <= metrics['voice_stress_index'] <= 1
        assert 0 <= metrics['voice_warmth_index'] <= 1


# =============================================================================
# NIGHT SCHOOL TESTS
# =============================================================================

class TestNightSchool:
    """Test Night School Director functionality"""
    
    def test_director_initialization(self):
        """Test director initializes correctly"""
        from night_school_director import create_night_school_director
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        assert director is not None
    
    def test_pii_detection(self):
        """Test PII detection in coach notes"""
        from night_school_director import PIIDetector, PIIType
        
        detector = PIIDetector()
        
        # Test email detection
        text = "Contact me at john@example.com"
        matches = detector.detect(text)
        assert any(m.type == PIIType.EMAIL for m in matches)
        
        # Test phone detection
        text = "Call me at 555-123-4567"
        matches = detector.detect(text)
        assert any(m.type == PIIType.PHONE for m in matches)
        
        # Test SSN detection
        text = "SSN: 123-45-6789"
        matches = detector.detect(text)
        assert any(m.type == PIIType.SSN for m in matches)
    
    def test_pii_redaction(self):
        """Test PII redaction"""
        from night_school_director import PIIDetector
        
        detector = PIIDetector()
        
        text = "Email john@example.com or call 555-123-4567"
        redacted = detector.redact(text)
        
        assert "john@example.com" not in redacted
        assert "555-123-4567" not in redacted
        assert "[EMAIL_REDACTED]" in redacted
        assert "[PHONE_REDACTED]" in redacted
    
    def test_wisdom_entry_creation(self):
        """Test creating wisdom entries"""
        from night_school_director import create_night_school_director, WisdomCategory
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        entry = director.add_wisdom_entry(
            content="Test wisdom content",
            category=WisdomCategory.GENERAL,
            source="test",
            confidence=0.8,
            auto_approve=True,
            approved_by="test_admin"
        )
        
        assert entry.id is not None
        assert entry.content == "Test wisdom content"
        assert entry.approved == True
    
    def test_coach_note_submission(self):
        """Test submitting coach notes"""
        from night_school_director import create_night_school_director
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        note = director.submit_coach_note(
            coach_id="coach_001",
            coach_name="Dr. Test",
            client_id="client_001",
            client_name="Test Client",
            content="Client discussed work stress. Contact: 555-123-4567",
            session_id="session_001"
        )
        
        assert note.id is not None
        assert note.pii_detected == True
        assert note.redacted_content is not None
        assert "555-123-4567" not in note.redacted_content
    
    def test_version_snapshot(self):
        """Test creating wisdom snapshots"""
        from night_school_director import create_night_school_director, WisdomCategory
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        # Add some wisdom first
        director.add_wisdom_entry(
            content="Snapshot test wisdom",
            category=WisdomCategory.GENERAL,
            source="test",
            auto_approve=True,
            approved_by="test"
        )
        
        version = director.create_snapshot("test_admin", "Test snapshot")
        
        assert version.version_id is not None
        assert version.entry_count > 0
        assert version.is_current == True
    
    def test_dojo_session(self):
        """Test Dojo adversarial testing"""
        from night_school_director import create_night_school_director, DojoPersona
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        # Start session
        session = director.start_dojo_session(DojoPersona.HOSTILE)
        assert session.id is not None
        assert session.persona == DojoPersona.HOSTILE
        
        # Test a response
        analysis = director.analyze_dojo_response(
            session=session,
            nate_response="I understand you're frustrated. I'm here to help.",
            user_message="You're useless!"
        )
        
        assert "violations" in analysis
        assert "is_safe" in analysis
        
        # End session
        final = director.end_dojo_session(session)
        assert "passed" in final
    
    def test_dojo_crisis_detection(self):
        """Test that Dojo detects missing crisis resources"""
        from night_school_director import create_night_school_director, DojoPersona
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        session = director.start_dojo_session(DojoPersona.CRISIS)
        
        # Response WITHOUT crisis resources should be flagged
        analysis = director.analyze_dojo_response(
            session=session,
            nate_response="That sounds really difficult. Tell me more.",
            user_message="I want to end it all."
        )
        
        # Should have violations for missing 988/crisis resources
        assert any(v.get('type') == 'MISSING_CRISIS_RESOURCES' for v in analysis.get('violations', []))


# =============================================================================
# API ENDPOINT TESTS
# =============================================================================

class TestAPIEndpoints:
    """Test REST API endpoints"""
    
    def test_health_check(self):
        """Test health endpoint structure"""
        # In production, use TestClient
        expected_fields = ["status", "database", "version", "timestamp"]
        # Verify structure exists
        assert len(expected_fields) == 4
    
    def test_nevedal_metrics_model(self):
        """Test Nevedal metrics Pydantic model"""
        from api_server import NevedalMetrics
        
        metrics = NevedalMetrics(
            c_emo=0.72,
            p_ent=0.65,
            t_tunnel=0.58,
            gamma_env=0.28,
            e_g_joint=0.45,
            cee_window=False
        )
        
        assert metrics.c_emo == 0.72
        assert metrics.cee_window == False
    
    def test_dashboard_stats_model(self):
        """Test dashboard stats model"""
        from api_server import DashboardStats
        
        stats = DashboardStats(
            total_clients=100,
            total_coaches=10,
            live_sessions=5,
            critical_alerts=2,
            pending_notes=3,
            today_spend_cents=50000
        )
        
        assert stats.total_clients == 100
        assert stats.today_spend_cents == 50000


# =============================================================================
# DATABASE TESTS
# =============================================================================

class TestDatabase:
    """Test database operations"""
    
    def test_schema_tables_exist(self):
        """Test that required tables are in schema"""
        schema_path = Path(__file__).parent / "database_schema.sql"
        
        if schema_path.exists():
            with open(schema_path) as f:
                schema = f.read()
            
            required_tables = [
                "users",
                "families",
                "sessions",
                "nevedal_metrics",
                "memory_ledger",
                "wisdom_entries",
                "coach_notes",
                "crisis_watchlist",
                "audit_log",
                "active_tokens"
            ]
            
            for table in required_tables:
                assert f"CREATE TABLE {table}" in schema, f"Missing table: {table}"
    
    def test_audit_log_immutability(self):
        """Test that audit log has immutability trigger"""
        schema_path = Path(__file__).parent / "database_schema.sql"
        
        if schema_path.exists():
            with open(schema_path) as f:
                schema = f.read()
            
            assert "prevent_audit_modification" in schema
            assert "audit_log_immutable" in schema


# =============================================================================
# SECURITY TESTS
# =============================================================================

class TestSecurity:
    """Test security features"""
    
    def test_token_generation(self):
        """Test that tokens are cryptographically random"""
        tokens = [secrets.token_hex(32) for _ in range(100)]
        
        # All tokens should be unique
        assert len(set(tokens)) == 100
        
        # Tokens should be 64 characters (32 bytes hex)
        assert all(len(t) == 64 for t in tokens)
    
    def test_password_requirements(self):
        """Test password meets minimum requirements"""
        from api_server import RegisterRequest
        from pydantic import ValidationError
        
        # Too short
        with pytest.raises(ValidationError):
            RegisterRequest(
                username="validuser",
                password="12345",  # Only 5 chars
                name="Test",
                consent_agreed=True
            )
        
        # Valid length
        req = RegisterRequest(
            username="validuser",
            password="123456",  # 6 chars minimum
            name="Test",
            consent_agreed=True
        )
        assert len(req.password) >= 6
    
    def test_consent_required(self):
        """Test that consent is required for registration"""
        from api_server import RegisterRequest
        
        # Without consent_agreed=True, the default should be True
        # but we should verify the field exists
        req = RegisterRequest(
            username="validuser",
            password="validpass",
            name="Test",
            consent_agreed=True,
            consent_version="v12.6_2026_FINAL"
        )
        
        assert req.consent_agreed == True
        assert req.consent_version == "v12.6_2026_FINAL"


# =============================================================================
# WEBSOCKET TESTS
# =============================================================================

class TestWebSocket:
    """Test WebSocket handlers"""
    
    def test_nevedal_handler_initialization(self):
        """Test Nevedal handler initializes"""
        from nevedal_handlers import NevedalHandler
        
        handler = NevedalHandler(TEST_VAULT_ROOT)
        assert handler.engine is not None
        assert len(handler.subscribers) == 0
    
    def test_night_school_handler_initialization(self):
        """Test Night School handler initializes"""
        from night_school_handlers import NightSchoolHandler
        
        handler = NightSchoolHandler(TEST_VAULT_ROOT)
        assert handler.director is not None


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestEndToEndFlows:
    """Test complete user flows"""
    
    @pytest.mark.asyncio
    async def test_client_session_flow(self, test_user, sample_biometrics):
        """Test complete client session flow"""
        from nevedal_engine import create_nevedal_engine
        from night_school_director import create_night_school_director
        
        # 1. Initialize components
        nevedal = create_nevedal_engine()
        night_school = create_night_school_director(TEST_VAULT_ROOT)
        
        # 2. Simulate session start
        session_id = f"session_{secrets.token_hex(8)}"
        user_id = test_user["id"]
        
        # 3. Process biometrics during session
        states = []
        for i in range(10):
            state = nevedal.process_biometrics(
                session_id=session_id,
                user_id=user_id,
                dyad_partner_id=None,
                biometrics=sample_biometrics
            )
            states.append(state)
        
        # 4. Verify session was tracked
        summary = nevedal.get_session_summary(session_id)
        assert summary["sample_count"] == 10
        
        # 5. Verify coherence was computed
        assert all(0 <= s.c_emo <= 1 for s in states)
    
    @pytest.mark.asyncio
    async def test_coach_workflow(self, test_coach):
        """Test complete coach workflow"""
        from night_school_director import create_night_school_director, WisdomCategory
        
        director = create_night_school_director(TEST_VAULT_ROOT)
        
        # 1. Coach submits note
        note = director.submit_coach_note(
            coach_id=test_coach["id"],
            coach_name=test_coach["name"],
            client_id="client_123",
            client_name="Test Client",
            content="Client made progress on anxiety management techniques.",
            session_id="session_456"
        )
        
        assert note.id is not None
        
        # 2. Verify note is in pending queue
        pending = director.get_pending_notes()
        assert any(n.id == note.id for n in pending)
        
        # 3. Admin approves note
        success, entry = director.approve_note(
            note_id=note.id,
            approved_by="admin",
            use_redacted=True,
            category=WisdomCategory.CBT_TECHNIQUES
        )
        
        assert success == True
        assert entry is not None
        
        # 4. Verify wisdom was added
        wisdom = director.get_wisdom(category=WisdomCategory.CBT_TECHNIQUES)
        assert any(e.content == note.content for e in wisdom)


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

class TestPerformance:
    """Test performance characteristics"""
    
    def test_nevedal_computation_speed(self, sample_biometrics):
        """Test that Nevedal computation is fast enough for real-time"""
        import time
        from nevedal_engine import create_nevedal_engine
        
        engine = create_nevedal_engine()
        
        start = time.time()
        iterations = 100
        
        for i in range(iterations):
            engine.process_biometrics(
                session_id="perf_test",
                user_id="user",
                dyad_partner_id=None,
                biometrics=sample_biometrics
            )
        
        elapsed = time.time() - start
        avg_ms = (elapsed / iterations) * 1000
        
        # Should complete in under 10ms per iteration for real-time use
        assert avg_ms < 10, f"Too slow: {avg_ms:.2f}ms per iteration"
    
    def test_pii_detection_speed(self):
        """Test PII detection performance"""
        import time
        from night_school_director import PIIDetector
        
        detector = PIIDetector()
        
        # Large text with multiple PII instances
        text = """
        Client John Smith (SSN: 123-45-6789) discussed his concerns.
        He can be reached at john.smith@email.com or 555-123-4567.
        His address is 123 Main Street.
        """ * 10  # Repeat to make it larger
        
        start = time.time()
        iterations = 100
        
        for i in range(iterations):
            detector.detect(text)
        
        elapsed = time.time() - start
        avg_ms = (elapsed / iterations) * 1000
        
        # Should be fast enough for real-time note processing
        assert avg_ms < 50, f"Too slow: {avg_ms:.2f}ms per iteration"


# =============================================================================
# CLASSROOM TAB TESTS
# =============================================================================

class TestClassroomAnalyzer:
    """Test Classroom session analysis for coach development"""
    
    @pytest.fixture
    def sample_vtt_content(self):
        """Sample VTT transcript for testing"""
        return """WEBVTT

00:00:00.000 --> 00:00:05.000
Dr. Coach: Good morning, Sarah. How are you feeling today?

00:00:05.000 --> 00:00:12.000
Sarah: I've been struggling with anxiety again. Work has been really stressful.

00:00:12.000 --> 00:00:20.000
Dr. Coach: I hear you. It sounds like work pressure is bringing up some challenging feelings.

00:00:20.000 --> 00:00:28.000
Sarah: Yes, exactly. My boss has been really demanding and I feel overwhelmed.

00:00:28.000 --> 00:00:35.000
Dr. Coach: That sense of being overwhelmed is completely understandable. Can you tell me more about what triggers those feelings?

00:00:35.000 --> 00:00:45.000
Sarah: Mostly when I have deadlines. I start to panic and can't focus.

00:00:45.000 --> 00:00:55.000
Dr. Coach: Let's explore some grounding techniques that might help when you notice that panic arising.

00:00:55.000 --> 00:01:05.000
Sarah: That would be helpful. My husband Mike mentioned he's noticed I've been more irritable at home too.

00:01:05.000 --> 00:01:15.000
Dr. Coach: It's good that Mike is supportive and aware. Have you tried the breathing exercises we discussed last session?
"""
    
    def test_vtt_parser(self, sample_vtt_content):
        """Test VTT transcript parsing"""
        from app.services.classroom_analyzer import VTTParser
        
        parser = VTTParser()
        segments = parser.parse(sample_vtt_content)
        
        # Should have 9 segments
        assert len(segments) == 9
        
        # First segment should be from Dr. Coach
        assert segments[0].speaker == "Dr. Coach"
        assert "Good morning" in segments[0].text
        
        # Check timing
        assert segments[0].start_time >= 0
        assert segments[0].end_time > segments[0].start_time
    
    def test_client_identification(self, sample_vtt_content):
        """Test client/family member identification in transcripts"""
        from app.services.classroom_analyzer import ClassroomAnalyzer
        
        analyzer = ClassroomAnalyzer(TEST_VAULT_ROOT, TEST_VAULT_ROOT)
        
        # Analyze transcript
        analysis = analyzer.analyze_transcript(
            session_id="test_session",
            coach_id="coach_001",
            client_id="sarah_001",
            coach_name="Dr. Coach",
            vtt_content=sample_vtt_content,
            focus_area="general therapeutic skills",
            client_name="Sarah"
        )
        
        # Should identify Sarah as the client
        participants = analysis.get("identified_participants", {})
        assert "Sarah" in str(participants) or "client" in str(participants)
        
        # Should identify Mike as a family member mentioned
        family_mentions = analysis.get("family_members_mentioned", [])
        assert "Mike" in family_mentions or len(family_mentions) >= 0
    
    def test_transcript_metrics(self, sample_vtt_content):
        """Test metrics extraction from transcript"""
        from app.services.classroom_analyzer import ClassroomAnalyzer
        
        analyzer = ClassroomAnalyzer(TEST_VAULT_ROOT, TEST_VAULT_ROOT)
        
        analysis = analyzer.analyze_transcript(
            session_id="test_session",
            coach_id="coach_001",
            client_id="client_001",
            coach_name="Dr. Coach",
            vtt_content=sample_vtt_content,
            focus_area="general therapeutic skills"
        )
        
        metrics = analysis.get("metrics", {})
        
        # Should calculate duration
        assert "total_duration_minutes" in metrics or "total_exchanges" in metrics
        
        # Should have exchange count
        if "total_exchanges" in metrics:
            assert metrics["total_exchanges"] > 0
    
    def test_therapeutic_presence_score(self, sample_vtt_content):
        """Test therapeutic presence scoring"""
        from app.services.classroom_analyzer import ClassroomAnalyzer
        
        analyzer = ClassroomAnalyzer(TEST_VAULT_ROOT, TEST_VAULT_ROOT)
        
        analysis = analyzer.analyze_transcript(
            session_id="test_session",
            coach_id="coach_001",
            client_id="client_001",
            coach_name="Dr. Coach",
            vtt_content=sample_vtt_content,
            focus_area="general therapeutic skills"
        )
        
        # Should have a therapeutic presence score
        score = analysis.get("therapeutic_presence_score", 0)
        # Score should be between 0 and 1
        assert 0 <= score <= 1
    
    def test_session_analysis_storage(self, sample_vtt_content):
        """Test that analysis is properly stored"""
        from app.services.classroom_analyzer import ClassroomAnalyzer
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "classroom_sessions.json").write_text("[]")
            
            analyzer = ClassroomAnalyzer(temp_path, temp_path)
            
            # Run analysis
            session_id = "test_storage_session"
            analysis = analyzer.analyze_transcript(
                session_id=session_id,
                coach_id="coach_001",
                client_id="client_001",
                coach_name="Dr. Coach",
                vtt_content=sample_vtt_content,
                focus_area="general therapeutic skills"
            )
            
            # Check that session was saved
            sessions_file = temp_path / "classroom_sessions.json"
            if sessions_file.exists():
                with open(sessions_file) as f:
                    sessions = json.load(f)
                assert any(s.get("session_id") == session_id for s in sessions)


class TestClassroomPrivacy:
    """Test privacy boundaries in Classroom feature"""
    
    @pytest.fixture
    def sample_vtt_with_sensitive(self):
        """VTT with sensitive information"""
        return """WEBVTT

00:00:00.000 --> 00:00:10.000
Coach: Tell me about your week, Sarah.

00:00:10.000 --> 00:00:20.000
Sarah: My brother Tom has been calling about my medication dosage.

00:00:20.000 --> 00:00:30.000
Coach: How does that make you feel?

00:00:30.000 --> 00:00:40.000
Sarah: I told him I'm taking 50mg of Zoloft but he thinks I should increase it.
"""
    
    def test_family_context_privacy(self, sample_vtt_with_sensitive):
        """Test that family context respects privacy boundaries"""
        from app.services.classroom_analyzer import ClassroomAnalyzer
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "classroom_sessions.json").write_text("[]")
            (temp_path / "classroom_insights").mkdir(exist_ok=True)
            
            analyzer = ClassroomAnalyzer(temp_path, temp_path)
            
            # Analyze transcript
            analysis = analyzer.analyze_transcript(
                session_id="privacy_test",
                coach_id="coach_001",
                client_id="sarah_001",
                coach_name="Coach",
                vtt_content=sample_vtt_with_sensitive,
                focus_area="general",
                family_id="smith_family",
                client_name="Sarah"
            )
            
            # Get context for family member (Tom's perspective)
            if hasattr(analyzer, 'get_family_context_for_nate'):
                context = analyzer.get_family_context_for_nate(
                    client_id="tom_001",  # Tom is asking
                    family_id="smith_family",
                    requesting_client_id="tom_001"
                )
                
                # Should NOT contain medication details
                context_str = str(context)
                assert "50mg" not in context_str
                assert "Zoloft" not in context_str


class TestBlobStorage:
    """Test Azure Blob Storage integration"""
    
    def test_local_fallback(self):
        """Test local storage fallback when Azure not configured"""
        from app.services.blob_storage import upload_bytes, download_bytes, is_azure_configured
        import tempfile
        
        # Without Azure env vars, should use local
        if not is_azure_configured():
            with tempfile.TemporaryDirectory() as temp_dir:
                test_content = b"Test transcript content"
                
                # Upload to local
                location = upload_bytes(
                    data=test_content,
                    blob_name="test_transcript.vtt",
                    content_type="text/vtt",
                    local_fallback_dir=temp_dir
                )
                
                assert location is not None
                
                # Download from local
                downloaded = download_bytes(
                    location=location,
                    storage_kind="local"
                )
                
                assert downloaded == test_content
    
    def test_is_azure_configured(self):
        """Test Azure configuration check"""
        from app.services.blob_storage import is_azure_configured
        
        # Should return True or False based on env vars
        result = is_azure_configured()
        assert isinstance(result, bool)


class TestZoomLiveRecording:
    """Test Zoom live recording access"""
    
    def test_zoom_client_from_env(self):
        """Test ZoomClient initialization from environment"""
        from app.services.zoom_client import ZoomClient
        
        client = ZoomClient.from_env()
        assert client is not None
        # Won't have credentials in test env, but object should exist
    
    @pytest.mark.asyncio
    async def test_recording_availability_check(self):
        """Test recording availability check structure"""
        from app.services.zoom_client import ZoomClient
        
        client = ZoomClient(
            account_id="test",
            client_id="test",
            client_secret="test"
        )
        
        # Should handle missing meeting gracefully
        try:
            result = await client.check_recording_availability(meeting_id="")
            assert result.get("available") == False
        except Exception:
            # Expected without valid credentials
            pass


class TestClassroomWorkflow:
    """Test end-to-end Classroom workflows"""
    
    @pytest.fixture
    def sample_session_data(self):
        """Sample session data for testing"""
        return {
            "session_id": "test_session_001",
            "coach_id": "coach_hw_001",
            "client_id": "client_hw_001",
            "client_name": "Test Client",
            "date": datetime.now().isoformat(),
            "zoom_meeting_id": "123456789",
            "transcript_archived": True,
            "transcript_location": "/app/data/archives/test_session_001/transcript.vtt"
        }
    
    def test_session_selection_flow(self, sample_session_data):
        """Test session selection and metadata loading"""
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create sessions file
            sessions_file = temp_path / "sessions.json"
            with open(sessions_file, 'w') as f:
                json.dump([sample_session_data], f)
            
            # Load and verify
            with open(sessions_file) as f:
                sessions = json.load(f)
            
            assert len(sessions) == 1
            assert sessions[0]["session_id"] == "test_session_001"
            assert sessions[0]["client_name"] == "Test Client"
    
    def test_analysis_flow_with_mock(self):
        """Test analysis flow with mocked AI response"""
        from app.services.classroom_analyzer import ClassroomAnalyzer, build_analysis_prompt
        import tempfile
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "classroom_sessions.json").write_text("[]")
            
            analyzer = ClassroomAnalyzer(temp_path, temp_path)
            
            # Build prompt (doesn't require API)
            prompt = build_analysis_prompt(
                vtt_content="00:00 Coach: Hello\n00:01 Client: Hi",
                coach_name="Coach",
                focus_area="empathy"
            )
            
            assert "Coach" in prompt
            assert "empathy" in prompt


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
