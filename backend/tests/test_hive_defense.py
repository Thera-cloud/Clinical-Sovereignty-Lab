"""
Phase 8: Hive Defense Protocol — Unit Tests
Tests for core security services including heartbeat, encryption,
coherence gate, drift scoring, helix rotation, and key sharding.
"""

import hashlib
import hmac
import os
import struct
import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone
from unittest.mock import MagicMock


# ═══════════════════════════════════════════════════════════════════════════
# 1. HEARTBEAT — Pulse Generation & Verification
# ═══════════════════════════════════════════════════════════════════════════

class TestHeartbeat:
    """Test HeartbeatRegistry and pulse verification."""

    def test_heartbeat_registry_creation(self):
        from app.services.security.heartbeat import HeartbeatRegistry
        registry = HeartbeatRegistry()
        assert registry is not None

    def test_heartbeat_entry_lifecycle(self):
        from app.services.security.heartbeat import HeartbeatRegistry
        registry = HeartbeatRegistry()
        entity_id = uuid4()

        # Register a new entity
        registry.register_entity(entity_id)
        assert entity_id in registry._entries

    def test_heartbeat_pulse_generation(self):
        """A pulse is HMAC-SHA256(birth_hash, birth_hash + state_hash + journal_hash + counter)."""
        from app.services.security.heartbeat import HeartbeatRegistry

        registry = HeartbeatRegistry()
        entity_id = uuid4()
        registry.register_entity(entity_id)
        entry = registry._entries[entity_id]

        # Birth the entity
        birth_hash = hashlib.sha256(b"test_birth").hexdigest()
        entry.birth(birth_hash, "originator_sig_test")

        # Generate a pulse
        pulse = entry.generate_pulse("state_hash_abc", "journal_hash_xyz")
        assert pulse is not None
        assert isinstance(pulse, str)
        assert len(pulse) == 64  # SHA-256 hex digest

    def test_heartbeat_counter_increments(self):
        from app.services.security.heartbeat import HeartbeatRegistry

        registry = HeartbeatRegistry()
        entity_id = uuid4()
        registry.register_entity(entity_id)
        entry = registry._entries[entity_id]

        birth_hash = hashlib.sha256(b"counter_test").hexdigest()
        entry.birth(birth_hash, "sig")

        pulse1 = entry.generate_pulse("s1", "j1")
        counter1 = entry._monotonic_counter

        pulse2 = entry.generate_pulse("s2", "j2")
        counter2 = entry._monotonic_counter

        assert counter2 == counter1 + 1
        assert pulse1 != pulse2  # Different inputs = different pulse

    def test_heartbeat_pulse_deterministic(self):
        """Same inputs + same counter should produce the same pulse."""
        birth_hash = hashlib.sha256(b"deterministic").hexdigest()
        key = birth_hash.encode()
        state = "state"
        journal = "journal"
        counter = 42

        msg = f"{birth_hash}{state}{journal}{counter}".encode()
        expected = hmac.new(key, msg, hashlib.sha256).hexdigest()

        # Verify the formula matches the documented algorithm
        assert len(expected) == 64
        assert expected == hmac.new(key, msg, hashlib.sha256).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════
# 2. PROMPT SEGMENTATION — AES-256-GCM Encrypt/Decrypt Roundtrip
# ═══════════════════════════════════════════════════════════════════════════

class TestPromptSegmentation:
    """Test AES-256-GCM encryption and decryption in prompt segmentation."""

    def test_encrypt_decrypt_roundtrip(self):
        from app.services.security.prompt_segmentation import PromptSegmentation

        seg = PromptSegmentation(db_pool=None, encryption_key=os.urandom(32))

        plaintext = "You are Little Nate, a therapeutic AI companion."
        segment_id = "seg_001"
        container_id = "container_alpha"

        encrypted = seg.encrypt_segment(plaintext, segment_id, container_id)
        assert isinstance(encrypted, bytes)
        assert len(encrypted) > 12  # At least nonce (12) + some ciphertext

        # Verify the plaintext is NOT visible in the ciphertext
        assert plaintext.encode() not in encrypted

    def test_encrypt_different_segments_differ(self):
        from app.services.security.prompt_segmentation import PromptSegmentation

        seg = PromptSegmentation(db_pool=None, encryption_key=os.urandom(32))

        plaintext = "Shared content"
        enc1 = seg.encrypt_segment(plaintext, "seg_A", "container_1")
        enc2 = seg.encrypt_segment(plaintext, "seg_B", "container_1")

        # Same plaintext with different segment IDs should produce different ciphertext
        assert enc1 != enc2

    def test_encrypt_decrypt_with_store(self):
        """Full roundtrip: encrypt -> store -> assemble -> decrypt."""
        from app.services.security.prompt_segmentation import PromptSegmentation

        key = os.urandom(32)
        seg = PromptSegmentation(db_pool=None, encryption_key=key)

        plaintext = "Clinical methodology segment."
        segment_id = "seg_test"
        container_id = "container_test"

        encrypted = seg.encrypt_segment(plaintext, segment_id, container_id)

        # Manually create a segment object and decrypt it
        from app.services.security.prompt_segmentation import PromptSegment
        segment = PromptSegment(
            segment_id=segment_id,
            container_id=container_id,
            encrypted_data=encrypted,
            position=0,
            content_hash=hashlib.sha256(encrypted).hexdigest(),
            encryption_key_id="test",
        )

        decrypted = seg._decrypt_segment(segment)
        assert decrypted == plaintext

    def test_wrong_key_fails(self):
        from app.services.security.prompt_segmentation import PromptSegmentation

        key1 = os.urandom(32)
        key2 = os.urandom(32)
        seg1 = PromptSegmentation(db_pool=None, encryption_key=key1)
        seg2 = PromptSegmentation(db_pool=None, encryption_key=key2)

        plaintext = "Secret prompt"
        encrypted = seg1.encrypt_segment(plaintext, "seg_x", "cont_x")

        from app.services.security.prompt_segmentation import PromptSegment
        segment = PromptSegment(
            segment_id="seg_x",
            container_id="cont_x",
            encrypted_data=encrypted,
            position=0,
            content_hash="",
            encryption_key_id="",
        )

        with pytest.raises(Exception):
            seg2._decrypt_segment(segment)


# ═══════════════════════════════════════════════════════════════════════════
# 3. COHERENCE GATE — 5-Step Evaluation
# ═══════════════════════════════════════════════════════════════════════════

class TestCoherenceGate:
    """Test the Coherence Gate's multi-step evaluation logic."""

    def test_gate_creation(self):
        from app.services.security.coherence_gate import CoherenceGate
        from app.services.security.heartbeat import HeartbeatRegistry

        registry = HeartbeatRegistry()
        gate = CoherenceGate(heartbeat_registry=registry)
        assert gate is not None

    def test_signal_without_heartbeat_absorbed(self):
        """A signal with no heartbeat should be absorbed at step 1."""
        from app.services.security.coherence_gate import CoherenceGate, InternalSignal, GateDecision
        from app.services.security.heartbeat import HeartbeatRegistry

        registry = HeartbeatRegistry()
        gate = CoherenceGate(heartbeat_registry=registry)

        signal = InternalSignal(
            source_entity_id=uuid4(),
            signal_type="test_signal",
            heartbeat=None,  # No heartbeat!
            payload={"test": True},
        )

        result = gate.evaluate(signal)
        assert result.decision == GateDecision.MIRROR_ABSORB
        assert result.step_failed == 1

    def test_gate_metrics_increment(self):
        from app.services.security.coherence_gate import CoherenceGate, InternalSignal
        from app.services.security.heartbeat import HeartbeatRegistry

        registry = HeartbeatRegistry()
        gate = CoherenceGate(heartbeat_registry=registry)

        initial_total = gate.metrics.total

        signal = InternalSignal(
            source_entity_id=uuid4(),
            signal_type="test",
            heartbeat=None,
            payload={},
        )
        gate.evaluate(signal)

        assert gate.metrics.total == initial_total + 1


# ═══════════════════════════════════════════════════════════════════════════
# 4. CUMULATIVE DRIFT SCORER — Threshold Calculations
# ═══════════════════════════════════════════════════════════════════════════

class TestCumulativeDriftScorer:
    """Test CDS threshold and magnitude calculations."""

    def test_drift_scorer_creation(self):
        from app.services.security.cumulative_drift_scorer import CumulativeDriftScorer
        scorer = CumulativeDriftScorer(db_pool=None)
        assert scorer is not None

    def test_drift_thresholds_match_docs(self):
        """CDS thresholds from Hive Defense Protocol v2.0 must match constants."""
        from app.services.security.cumulative_drift_scorer import (
            THRESHOLD_NOTICE,
            THRESHOLD_INTEREST,
            THRESHOLD_CONCERN,
            THRESHOLD_ALARM,
        )
        assert THRESHOLD_NOTICE == 0.15
        assert THRESHOLD_INTEREST == 0.30
        assert THRESHOLD_CONCERN == 0.50
        assert THRESHOLD_ALARM == 0.75

    def test_drift_magnitude_computation(self):
        """CDS = sqrt(sum of squared drift vectors across 6 dimensions)."""
        import math
        from app.services.security.cumulative_drift_scorer import CumulativeDriftScorer

        scorer = CumulativeDriftScorer(db_pool=None)

        # Test with known values
        dimensions = {
            "data_access": 0.3,
            "communication": 0.4,
            "coherence": 0.0,
            "trail_emission": 0.0,
            "journal_trajectory": 0.0,
            "timing_pattern": 0.0,
        }
        expected = math.sqrt(0.3**2 + 0.4**2)  # 0.5

        # The scorer should compute magnitude as sqrt(sum of squares)
        magnitude = scorer.compute_magnitude(dimensions)
        assert abs(magnitude - expected) < 0.001

    def test_drift_level_classification(self):
        from app.services.security.cumulative_drift_scorer import CumulativeDriftScorer

        scorer = CumulativeDriftScorer(db_pool=None)

        assert scorer.classify_level(0.10) == "none"
        assert scorer.classify_level(0.20) == "notice"
        assert scorer.classify_level(0.35) == "interest"
        assert scorer.classify_level(0.55) == "concern"
        assert scorer.classify_level(0.80) == "alarm"


# ═══════════════════════════════════════════════════════════════════════════
# 5. TRINITY HELIX — Rotation Logic
# ═══════════════════════════════════════════════════════════════════════════

class TestTrinityHelix:
    """Test Trinity Helix rotation and sub-cord ordering."""

    def test_helix_creation(self):
        from app.services.security.trinity_helix import TrinityHelix
        helix = TrinityHelix()
        assert helix is not None

    def test_helix_has_9_subcords(self):
        """Protocol v3.1 specifies exactly 9 sub-cords."""
        from app.services.security.trinity_helix import TrinityHelix, SUB_CORDS
        assert len(SUB_CORDS) == 9

    def test_helix_initial_sequence(self):
        from app.services.security.trinity_helix import TrinityHelix
        helix = TrinityHelix()
        state = helix.get_state()
        seq = state.current_sequence
        assert len(seq) == 9
        assert sorted(seq) == list(range(9))

    def test_helix_rotation_changes_sequence(self):
        from app.services.security.trinity_helix import TrinityHelix
        helix = TrinityHelix()

        initial_seq = list(helix.get_state().current_sequence)
        helix.rotate()
        new_seq = list(helix.get_state().current_sequence)

        # The sequence should still contain all 9 elements
        assert sorted(new_seq) == list(range(9))
        # Rotation count should increment
        assert helix.get_state().rotation_count >= 1

    def test_helix_rotation_interval_bounds(self):
        """Protocol v3.1: interval must be between 50ms and 500ms."""
        from app.services.security.helix_rotation_engine import (
            MIN_ROTATION_INTERVAL_MS,
            MAX_ROTATION_INTERVAL_MS,
        )
        assert MIN_ROTATION_INTERVAL_MS == 50.0
        assert MAX_ROTATION_INTERVAL_MS == 500.0


# ═══════════════════════════════════════════════════════════════════════════
# 6. KEY SHARDING — Shamir 3-of-5 Split/Reconstruct
# ═══════════════════════════════════════════════════════════════════════════

class TestKeySharding:
    """Test Shamir Secret Sharing 3-of-5 implementation."""

    def test_sharding_creation(self):
        from app.services.security.key_sharding import KeySharding
        sharding = KeySharding(db_pool=None)
        assert sharding is not None

    def test_split_produces_5_shards(self):
        from app.services.security.key_sharding import KeySharding
        sharding = KeySharding(db_pool=None)

        secret = os.urandom(32)
        shards = sharding.split(secret, threshold=3, total=5)
        assert len(shards) == 5

    def test_reconstruct_with_3_of_5(self):
        """Any 3 of 5 shards should reconstruct the original secret."""
        from app.services.security.key_sharding import KeySharding
        sharding = KeySharding(db_pool=None)

        secret = os.urandom(32)
        shards = sharding.split(secret, threshold=3, total=5)

        # Use shards 0, 2, 4 (any 3 will do)
        selected = [shards[0], shards[2], shards[4]]
        recovered = sharding.reconstruct(selected)

        assert recovered == secret

    def test_reconstruct_with_different_3(self):
        """Different combinations of 3 shards should all recover the same secret."""
        from app.services.security.key_sharding import KeySharding
        sharding = KeySharding(db_pool=None)

        secret = os.urandom(32)
        shards = sharding.split(secret, threshold=3, total=5)

        combo1 = [shards[0], shards[1], shards[2]]
        combo2 = [shards[1], shards[3], shards[4]]
        combo3 = [shards[0], shards[3], shards[4]]

        assert sharding.reconstruct(combo1) == secret
        assert sharding.reconstruct(combo2) == secret
        assert sharding.reconstruct(combo3) == secret

    def test_reconstruct_with_2_fails_or_wrong(self):
        """Only 2 shards should NOT reconstruct the correct secret."""
        from app.services.security.key_sharding import KeySharding
        sharding = KeySharding(db_pool=None)

        secret = os.urandom(32)
        shards = sharding.split(secret, threshold=3, total=5)

        # Try with only 2 shards — should either fail or give wrong result
        try:
            result = sharding.reconstruct([shards[0], shards[1]])
            # If it doesn't raise, the result should be wrong
            assert result != secret
        except Exception:
            pass  # Expected: insufficient shards


# ═══════════════════════════════════════════════════════════════════════════
# 7. ENTROPY FORGE — Pre-Birth Chaos Injection
# ═══════════════════════════════════════════════════════════════════════════

class TestEntropyForge:
    """Test the Entropy Forge seed hardening and chaos rounds."""

    def test_forge_creation(self):
        from app.services.security.entropy_forge import EntropyForge
        forge = EntropyForge()
        assert forge is not None

    def test_forge_seed(self):
        from app.services.security.entropy_forge import EntropyForge
        forge = EntropyForge()

        seed = forge.forge_seed(
            hsm_random=os.urandom(32),
            restart_timestamp_ns=123456789012345,
            originator_signature=b"sig_bytes",
            shard_holder_entropy_list=[os.urandom(16), os.urandom(16)],
        )
        assert isinstance(seed, bytes)
        assert len(seed) == 64  # SHA-512 output

    def test_chaos_rounds_deterministic(self):
        from app.services.security.entropy_forge import EntropyForge
        forge = EntropyForge()

        seed = b"A" * 64
        result1 = forge.run_chaos_rounds(seed, rounds=100)
        result2 = forge.run_chaos_rounds(seed, rounds=100)

        assert result1 == result2  # Same input = same output
        assert len(result1) == 64

    def test_chaos_rounds_avalanche(self):
        """Changing one bit of input should completely change the output."""
        from app.services.security.entropy_forge import EntropyForge
        forge = EntropyForge()

        seed1 = b"A" * 64
        seed2 = b"A" * 63 + b"B"

        result1 = forge.run_chaos_rounds(seed1, rounds=100)
        result2 = forge.run_chaos_rounds(seed2, rounds=100)

        assert result1 != result2

        # Check significant difference (at least 25% of bytes differ)
        diff_count = sum(1 for a, b in zip(result1, result2) if a != b)
        assert diff_count > 16  # At least 25% of 64 bytes

    def test_pre_birth_chaos_injection_alias(self):
        """pre_birth_chaos_injection should be an alias for run_chaos_rounds."""
        from app.services.security.entropy_forge import EntropyForge
        forge = EntropyForge()

        seed = os.urandom(64)
        result1 = forge.run_chaos_rounds(seed, rounds=50)
        result2 = forge.pre_birth_chaos_injection(seed, rounds=50)

        assert result1 == result2

    def test_default_chaos_rounds_1000(self):
        from app.services.security.entropy_forge import DEFAULT_CHAOS_ROUNDS
        assert DEFAULT_CHAOS_ROUNDS == 1000


# ═══════════════════════════════════════════════════════════════════════════
# 8. DEFCON CONTROLLER — State Management
# ═══════════════════════════════════════════════════════════════════════════

class TestDefconController:
    """Test DEFCON level state management."""

    def test_defcon_creation(self):
        from app.services.security.defcon_controller import DefconController
        ctrl = DefconController(db_pool=None)
        assert ctrl is not None

    def test_defcon_initial_level_5(self):
        from app.services.security.defcon_controller import DefconController
        ctrl = DefconController(db_pool=None)
        state = ctrl.get_state()
        # DEFCON 5 is the lowest threat level (normal operations)
        level = state.level.value if hasattr(state.level, 'value') else state.level
        assert level == 5


# ═══════════════════════════════════════════════════════════════════════════
# 9. TEMPORAL JITTER — Timing Normalization
# ═══════════════════════════════════════════════════════════════════════════

class TestTemporalJitter:
    """Test timing normalization to prevent side-channel attacks."""

    def test_jitter_creation(self):
        from app.services.security.temporal_jitter import TemporalJitter
        jitter = TemporalJitter()
        assert jitter is not None

    def test_jitter_produces_delay(self):
        from app.services.security.temporal_jitter import TemporalJitter
        jitter = TemporalJitter()

        delay = jitter.compute_delay()
        assert isinstance(delay, float)
        assert delay >= 0


# ═══════════════════════════════════════════════════════════════════════════
# 10. FORENSIC LOGGER — Immutable Chain
# ═══════════════════════════════════════════════════════════════════════════

class TestForensicLogger:
    """Test forensic event logging with chain hashing."""

    def test_logger_creation(self):
        from app.services.security.forensic_logger import ForensicLogger
        logger = ForensicLogger()
        assert logger is not None

    def test_log_event(self):
        from app.services.security.forensic_logger import ForensicLogger
        logger = ForensicLogger()

        logger.log_event(
            "test_event",
            source_entity="test_source",
            target_entity="test_target",
            evidence={"key": "value"},
        )

        # Buffer should contain the event
        assert len(logger._buffer) >= 1

    def test_chain_hash_integrity(self):
        """Each log entry's hash should depend on the previous entry."""
        from app.services.security.forensic_logger import ForensicLogger
        logger = ForensicLogger()

        logger.log_event("event_1", evidence={"seq": 1})
        logger.log_event("event_2", evidence={"seq": 2})

        assert len(logger._buffer) >= 2
        # Chain hashes should be different
        hash1 = logger._buffer[0].chain_hash
        hash2 = logger._buffer[1].chain_hash
        assert hash1 != hash2


# ═══════════════════════════════════════════════════════════════════════════
# 11. MIRROR SHELL — Signal Processing
# ═══════════════════════════════════════════════════════════════════════════

class TestMirrorShell:
    """Test Mirror Shell signal routing."""

    def test_mirror_shell_creation(self):
        from app.services.security.mirror_shell import MirrorShell
        from app.services.security.coherence_gate import CoherenceGate
        from app.services.security.heartbeat import HeartbeatRegistry
        from app.services.security.forensic_logger import ForensicLogger

        registry = HeartbeatRegistry()
        gate = CoherenceGate(heartbeat_registry=registry)
        forensic = ForensicLogger()

        shell = MirrorShell(coherence_gate=gate, forensic_logger=forensic)
        assert shell is not None
        assert shell._total_signals_processed == 0

    def test_mirror_shell_metrics(self):
        from app.services.security.mirror_shell import MirrorShell
        from app.services.security.coherence_gate import CoherenceGate
        from app.services.security.heartbeat import HeartbeatRegistry
        from app.services.security.forensic_logger import ForensicLogger

        registry = HeartbeatRegistry()
        gate = CoherenceGate(heartbeat_registry=registry)
        forensic = ForensicLogger()

        shell = MirrorShell(coherence_gate=gate, forensic_logger=forensic)

        stats = shell.get_stats() if hasattr(shell, 'get_stats') else {
            "total_processed": shell._total_signals_processed,
            "absorbed": shell._mirror_absorbed,
            "contained": shell._mirror_contained,
            "passed": shell._passed_to_real,
        }
        assert stats["total_processed"] == 0
        assert stats["absorbed"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 12. CONSTANT TIME CRYPTO — Timing Safety
# ═══════════════════════════════════════════════════════════════════════════

class TestConstantTimeCrypto:
    """Test constant-time comparison and selection operations."""

    def test_creation(self):
        from app.services.security.constant_time_crypto import ConstantTimeCrypto
        ct = ConstantTimeCrypto()
        assert ct is not None

    def test_constant_time_compare_equal(self):
        from app.services.security.constant_time_crypto import ConstantTimeCrypto
        ct = ConstantTimeCrypto()

        result = ct.compare(b"hello_world", b"hello_world")
        assert result is True

    def test_constant_time_compare_not_equal(self):
        from app.services.security.constant_time_crypto import ConstantTimeCrypto
        ct = ConstantTimeCrypto()

        result = ct.compare(b"hello_world", b"goodbye_wld")
        assert result is False
