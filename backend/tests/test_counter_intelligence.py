"""
Counter-Intelligence Test Suite — Attack simulation tests for all 3 tiers.

Tests:
  - Tier 1: Fingerprinting, pattern analysis, swarm alert propagation
  - Tier 2: Honeypot engagement, canary deployment/triggering, tarpit delays
  - Tier 3: Retrieval seed crafting, counter-fragment emission, beacon activation
  - Integration: Full pipeline from attack signal to graduated response
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Tier 1: Fingerprinting & Pattern Analysis
# ---------------------------------------------------------------------------


class TestAttackFingerprinter:
    """Test BLE, network, and behavioral fingerprinting."""

    def test_create_profile_from_ble_signal(self):
        from app.services.counter_intelligence.fingerprinter import (
            AttackFingerprinter,
            AttackerProfile,
        )
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal,
            AttackSource,
        )

        fp = AttackFingerprinter()
        signal = AttackSignal(
            source=AttackSource.BLE,
            failure_type="signature_mismatch",
            device_address="AA:BB:CC:DD:EE:FF",
            metadata={"rssi": -65, "signature_guess": 42},
        )

        profile_id = asyncio.get_event_loop().run_until_complete(
            fp.process_signal(signal)
        )

        assert profile_id is not None
        profile = fp.get_profile_obj(profile_id)
        assert profile is not None
        assert "AA:BB:CC:DD:EE:FF" in profile.ble_addresses
        assert profile.total_events == 1
        assert 42 in profile.signature_guesses

    def test_correlate_same_device_address(self):
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal, AttackSource,
        )

        fp = AttackFingerprinter()
        signal1 = AttackSignal(
            source=AttackSource.BLE,
            failure_type="sig_fail",
            device_address="AA:BB:CC:DD:EE:FF",
        )
        signal2 = AttackSignal(
            source=AttackSource.BLE,
            failure_type="crc_fail",
            device_address="AA:BB:CC:DD:EE:FF",
        )

        loop = asyncio.get_event_loop()
        pid1 = loop.run_until_complete(fp.process_signal(signal1))
        pid2 = loop.run_until_complete(fp.process_signal(signal2))

        assert pid1 == pid2  # Same device → same profile
        profile = fp.get_profile_obj(pid1)
        assert profile.total_events == 2

    def test_correlate_same_ip(self):
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal, AttackSource,
        )

        fp = AttackFingerprinter()
        signal1 = AttackSignal(
            source=AttackSource.WEBSOCKET,
            failure_type="login_failed",
            ip_address="1.2.3.4",
        )
        signal2 = AttackSignal(
            source=AttackSource.REST,
            failure_type="suspicious_api",
            ip_address="1.2.3.4",
        )

        loop = asyncio.get_event_loop()
        pid1 = loop.run_until_complete(fp.process_signal(signal1))
        pid2 = loop.run_until_complete(fp.process_signal(signal2))

        assert pid1 == pid2

    def test_ad_pattern_hash(self):
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter

        hash1 = AttackFingerprinter.compute_ad_pattern_hash(
            ad_types=[0xFF, 0x16, 0x09],
            ad_lengths=[10, 4, 8],
            manufacturer_ids=[0x004C],  # Apple
        )
        hash2 = AttackFingerprinter.compute_ad_pattern_hash(
            ad_types=[0xFF, 0x16, 0x09],
            ad_lengths=[10, 4, 8],
            manufacturer_ids=[0x004C],
        )
        hash3 = AttackFingerprinter.compute_ad_pattern_hash(
            ad_types=[0xFF, 0x02],
            ad_lengths=[6, 2],
        )

        assert hash1 == hash2  # Same pattern → same hash
        assert hash1 != hash3  # Different pattern → different hash
        assert len(hash1) == 16


class TestPatternAnalyzer:
    """Test attack pattern detection algorithms."""

    def test_brute_force_detection(self):
        from app.services.counter_intelligence.fingerprinter import (
            AttackFingerprinter, AttackerProfile,
        )
        from app.services.counter_intelligence.pattern_analyzer import (
            AttackPatternAnalyzer,
        )
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal, AttackSource, ThreatLevel,
        )

        fp = AttackFingerprinter()
        analyzer = AttackPatternAnalyzer(fingerprinter=fp)

        # Simulate 25 rapid signals (brute force threshold = 20)
        loop = asyncio.get_event_loop()
        pid = None
        for i in range(25):
            signal = AttackSignal(
                source=AttackSource.BLE,
                failure_type="sig_fail",
                device_address="AA:BB:CC:DD:EE:FF",
                metadata={"signature_guess": i},
            )
            pid = loop.run_until_complete(fp.process_signal(signal))

        assessment = loop.run_until_complete(analyzer.assess(pid))
        assert assessment is not None
        assert assessment.threat_level >= ThreatLevel.HIGH

    def test_sweep_detection(self):
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.pattern_analyzer import AttackPatternAnalyzer
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal, AttackSource, AttackType,
        )

        fp = AttackFingerprinter()
        analyzer = AttackPatternAnalyzer(fingerprinter=fp)

        loop = asyncio.get_event_loop()
        pid = None
        # Sequential signature guesses (0, 1, 2, 3, 4, 5, 6, 7)
        for i in range(8):
            signal = AttackSignal(
                source=AttackSource.BLE,
                failure_type="sig_fail",
                device_address="11:22:33:44:55:66",
                metadata={"signature_guess": i},
            )
            pid = loop.run_until_complete(fp.process_signal(signal))

        assessment = loop.run_until_complete(analyzer.assess(pid))
        assert assessment is not None
        # Should detect sweep pattern
        assert assessment.attack_type in (AttackType.SWEEP, AttackType.BRUTE_FORCE, AttackType.UNKNOWN)

    def test_low_event_count_returns_low_threat(self):
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.pattern_analyzer import AttackPatternAnalyzer
        from app.services.counter_intelligence.orchestrator import (
            AttackSignal, AttackSource, ThreatLevel,
        )

        fp = AttackFingerprinter()
        analyzer = AttackPatternAnalyzer(fingerprinter=fp)

        loop = asyncio.get_event_loop()
        signal = AttackSignal(
            source=AttackSource.BLE,
            failure_type="sig_fail",
            device_address="XX:XX:XX:XX:XX:XX",
        )
        pid = loop.run_until_complete(fp.process_signal(signal))

        assessment = loop.run_until_complete(analyzer.assess(pid))
        assert assessment is not None
        assert assessment.threat_level == ThreatLevel.LOW


# ---------------------------------------------------------------------------
# Tier 2: Honeypots, Canaries, Tarpits
# ---------------------------------------------------------------------------


class TestHoneypot:
    """Test honeypot Fibre deployment and engagement tracking."""

    def test_deploy_honeypot(self):
        from app.services.counter_intelligence.honeypot import HoneypotService

        service = HoneypotService()
        loop = asyncio.get_event_loop()
        hp = loop.run_until_complete(
            service.deploy_for_attacker("attacker-123", ["fibre-a"])
        )

        assert hp is not None
        assert hp.target_attacker_id == "attacker-123"
        assert hp.engagement_depth == 0
        assert hp.fibre_id in service.get_honeypot_fibre_ids()

    def test_honeypot_trail_emission(self):
        from app.services.counter_intelligence.honeypot import HoneypotFibre

        hp = HoneypotFibre(fibre_id="hp-test", target_attacker_id="atk-1")
        trail = hp.get_trail_emission()

        assert trail["fibre_id"] == "hp-test"
        assert trail["quakete_mode"] == "REQUESTING"
        assert trail["deficit_capacity"] > 0
        assert trail["communication_health"] < 0.5  # Looks vulnerable


class TestCanary:
    """Test canary token generation and triggering."""

    def test_generate_fragment_canary(self):
        from app.services.counter_intelligence.canary import CanaryTokenService

        svc = CanaryTokenService()
        loop = asyncio.get_event_loop()
        payload = loop.run_until_complete(svc.generate_fragment_canary())

        assert len(payload) == 4
        assert isinstance(payload, bytes)
        assert len(svc._tokens) == 1

    def test_generate_dns_canary(self):
        from app.services.counter_intelligence.canary import CanaryTokenService

        svc = CanaryTokenService()
        loop = asyncio.get_event_loop()
        hostname = loop.run_until_complete(svc.generate_dns_canary())

        assert hostname.endswith(".canary.sovereignsanctuary.net")
        assert len(svc._tokens) == 1

    def test_generate_web_beacon(self):
        from app.services.counter_intelligence.canary import CanaryTokenService

        svc = CanaryTokenService()
        loop = asyncio.get_event_loop()
        url = loop.run_until_complete(svc.generate_web_beacon())

        assert "beacon" in url
        assert len(svc._tokens) == 1

    def test_beacon_trigger(self):
        from app.services.counter_intelligence.canary import CanaryTokenService

        svc = CanaryTokenService()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(svc.generate_web_beacon())

        token = list(svc._tokens.values())[0]
        loop.run_until_complete(
            svc.on_beacon_hit(token.canary_id, "1.2.3.4", "evil-scanner")
        )

        assert token.triggered is True
        assert token.trigger_data["requester_ip"] == "1.2.3.4"

    def test_deploy_canary_suite(self):
        from app.services.counter_intelligence.canary import CanaryTokenService

        svc = CanaryTokenService()
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            svc.deploy_canaries("attacker-1", "brute_force")
        )

        assert "dns_canary" in result
        assert "web_beacon" in result
        assert "wisdom_canary_id" in result
        assert len(svc._tokens) == 4  # fragment + dns + web + wisdom


class TestTarpit:
    """Test tarpit resource-wasting mechanisms."""

    def test_ws_delay_escalation(self):
        from app.services.counter_intelligence.tarpit import TarpitEngine
        from app.services.counter_intelligence.orchestrator import ThreatLevel

        engine = TarpitEngine()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            engine.activate_for_attacker("atk-1", ThreatLevel.HIGH)
        )
        loop.run_until_complete(engine.register_attacker_ip("atk-1", "1.2.3.4"))

        delay1 = loop.run_until_complete(engine.get_ws_delay("1.2.3.4"))
        delay2 = loop.run_until_complete(engine.get_ws_delay("1.2.3.4"))
        delay3 = loop.run_until_complete(engine.get_ws_delay("1.2.3.4"))

        assert delay1 > 0
        assert delay2 > delay1  # Escalating
        assert delay3 > delay2  # Still escalating

    def test_non_tarpitted_ip_has_no_delay(self):
        from app.services.counter_intelligence.tarpit import TarpitEngine

        engine = TarpitEngine()
        loop = asyncio.get_event_loop()
        delay = loop.run_until_complete(engine.get_ws_delay("5.5.5.5"))
        assert delay == 0.0

    def test_decoy_fragment_generation(self):
        from app.services.counter_intelligence.tarpit import TarpitEngine

        engine = TarpitEngine()
        loop = asyncio.get_event_loop()
        fragments = loop.run_until_complete(
            engine.generate_decoy_fragments(10)
        )

        assert len(fragments) == 10
        assert all(f["decoy"] is True for f in fragments)
        assert all(f["mode"] == "EXTENDED" for f in fragments)


# ---------------------------------------------------------------------------
# Tier 3: Retrieval Seeds & Counter-Emission
# ---------------------------------------------------------------------------


class TestRetrievalSeed:
    """Test retrieval seed crafting."""

    def test_craft_dns_seed(self):
        from app.services.counter_intelligence.retrieval_seed import (
            RetrievalSeedCrafter, SeedType,
        )

        crafter = RetrievalSeedCrafter()
        loop = asyncio.get_event_loop()
        seed = loop.run_until_complete(crafter.craft_dns_seed("atk-1"))

        assert seed.seed_type == SeedType.DNS
        assert "seed.sovereignsanctuary.net" in seed.tracking_endpoint
        assert len(seed.payload) > 0

    def test_craft_http_seed(self):
        from app.services.counter_intelligence.retrieval_seed import (
            RetrievalSeedCrafter, SeedType,
        )

        crafter = RetrievalSeedCrafter()
        loop = asyncio.get_event_loop()
        seed = loop.run_until_complete(crafter.craft_http_seed("atk-1"))

        assert seed.seed_type == SeedType.HTTP
        assert "beacon" in seed.tracking_endpoint

    def test_craft_cascade_seed(self):
        from app.services.counter_intelligence.retrieval_seed import (
            RetrievalSeedCrafter, SeedType,
        )

        crafter = RetrievalSeedCrafter()
        loop = asyncio.get_event_loop()
        seed = loop.run_until_complete(crafter.craft_cascade_seed("atk-1"))

        assert seed.seed_type == SeedType.CASCADE
        # Cascade should have multiple callback levels
        import json
        payload = json.loads(seed.payload)
        assert "level_0" in payload
        assert "processing" in payload

    def test_craft_full_suite(self):
        from app.services.counter_intelligence.retrieval_seed import RetrievalSeedCrafter

        crafter = RetrievalSeedCrafter()
        loop = asyncio.get_event_loop()
        seeds = loop.run_until_complete(
            crafter.craft_for_attacker("atk-1", "apt")
        )

        # APT should get all seed types including cascade
        assert len(seeds) >= 4
        types = {s.seed_type.value for s in seeds}
        assert "dns" in types
        assert "http" in types
        assert "cascade" in types


class TestCounterEmitter:
    """Test counter-fragment emission coordination."""

    def test_register_device(self):
        from app.services.counter_intelligence.counter_emitter import (
            CounterFragmentEmitter,
        )

        emitter = CounterFragmentEmitter()
        emitter.register_sovereign_device("dev-001", "mobile")

        status = emitter.get_status()
        assert status["sovereign_devices"] == 1

    def test_queue_and_retrieve_fragments(self):
        from app.services.counter_intelligence.counter_emitter import (
            CounterFragmentEmitter,
        )
        from app.services.counter_intelligence.retrieval_seed import (
            RetrievalSeedCrafter,
        )

        emitter = CounterFragmentEmitter()
        emitter.register_sovereign_device("dev-001", "mobile")
        crafter = RetrievalSeedCrafter()

        loop = asyncio.get_event_loop()
        seed = loop.run_until_complete(crafter.craft_dns_seed("atk-1"))
        loop.run_until_complete(emitter.queue_seed(seed))

        fragments = loop.run_until_complete(
            emitter.get_pending_fragments("dev-001", max_count=10)
        )
        assert len(fragments) > 0
        assert fragments[0]["seed_type"] == "dns"


class TestBeaconListener:
    """Test beacon activation handling."""

    def test_http_beacon_returns_pixel(self):
        from app.services.counter_intelligence.beacon_listener import (
            BeaconListener, TRANSPARENT_PIXEL,
        )

        listener = BeaconListener()
        loop = asyncio.get_event_loop()
        pixel = loop.run_until_complete(
            listener.on_http_beacon(
                str(uuid4()), "1.2.3.4", "evil-browser/1.0",
            )
        )

        assert pixel == TRANSPARENT_PIXEL
        assert len(listener._activations) == 1
        assert listener._activations[0].requester_ip == "1.2.3.4"


class TestReverseMapper:
    """Test infrastructure map assembly."""

    def test_ingest_creates_map(self):
        from app.services.counter_intelligence.reverse_mapper import ReverseMapper
        from app.services.counter_intelligence.beacon_listener import BeaconActivation

        mapper = ReverseMapper()
        activation = BeaconActivation(
            canary_or_seed_id=uuid4(),
            activation_type="http_beacon",
            requester_ip="1.2.3.4",
            requester_ua="evil-scanner",
        )
        activation.resolved_attacker_id = "atk-123"

        loop = asyncio.get_event_loop()
        loop.run_until_complete(mapper.ingest_activation(activation))

        result = loop.run_until_complete(mapper.get_map("atk-123"))
        assert result is not None
        assert "1.2.3.4" in result["network"]["ip_addresses"]

    def test_ble_rssi_proximity(self):
        from app.services.counter_intelligence.reverse_mapper import ReverseMapper

        mapper = ReverseMapper()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            mapper.ingest_ble_rssi("atk-123", "dev-001", -65, time.time())
        )

        result = loop.run_until_complete(mapper.get_map("atk-123"))
        assert result is not None
        assert len(result["physical"]["ble_locations"]) == 1


# ---------------------------------------------------------------------------
# Integration: Full Pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """Test the complete attack signal → graduated response pipeline."""

    def test_orchestrator_processes_signal(self):
        from app.services.counter_intelligence.orchestrator import (
            ImmuneResponseOrchestrator, AttackSignal, AttackSource,
        )
        from app.services.counter_intelligence.fingerprinter import AttackFingerprinter
        from app.services.counter_intelligence.pattern_analyzer import AttackPatternAnalyzer
        from app.services.counter_intelligence.threat_db import ThreatIntelligenceDB

        fp = AttackFingerprinter()
        analyzer = AttackPatternAnalyzer(fingerprinter=fp)
        threat_db = ThreatIntelligenceDB()

        orchestrator = ImmuneResponseOrchestrator(
            fingerprinter=fp,
            pattern_analyzer=analyzer,
            threat_db=threat_db,
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(orchestrator.start())

        # Ingest a signal
        signal = AttackSignal(
            source=AttackSource.BLE,
            failure_type="signature_mismatch",
            device_address="AA:BB:CC:DD:EE:FF",
            metadata={"signature_guess": 42, "rssi": -70},
        )
        loop.run_until_complete(orchestrator.ingest_signal(signal))

        # Give the background processor time to handle it
        loop.run_until_complete(asyncio.sleep(1))
        loop.run_until_complete(orchestrator.stop())

        # Profile should have been created
        profiles = loop.run_until_complete(fp.get_all_active())
        assert len(profiles) >= 1

    def test_orchestrator_status(self):
        from app.services.counter_intelligence.orchestrator import (
            ImmuneResponseOrchestrator,
        )

        orchestrator = ImmuneResponseOrchestrator(tier3_enabled=False)
        status = orchestrator.get_status()

        assert status["running"] is False
        assert status["tier3_enabled"] is False
        assert status["queue_size"] == 0


class TestDecoyGenerator:
    """Test decoy data generation."""

    def test_coherence_metrics(self):
        from app.services.counter_intelligence.decoy_generator import DecoyGenerator

        gen = DecoyGenerator()
        metrics = gen.generate_coherence_metrics()

        assert 0.0 <= metrics["individual_score"] <= 1.0
        assert 0.0 <= metrics["global_composite"] <= 1.0
        assert "timestamp" in metrics

    def test_trail_emission(self):
        from app.services.counter_intelligence.decoy_generator import DecoyGenerator

        gen = DecoyGenerator()
        trail = gen.generate_trail_emission()

        assert "fibre_id" in trail
        assert trail["quakete_mode"] in ("NOMINAL", "SURPLUS", "REQUESTING")

    def test_honeypot_response_depth(self):
        from app.services.counter_intelligence.decoy_generator import DecoyGenerator

        gen = DecoyGenerator()
        loop = asyncio.get_event_loop()

        resp_d0 = loop.run_until_complete(gen.generate_honeypot_response(0))
        resp_d5 = loop.run_until_complete(gen.generate_honeypot_response(5))
        resp_d10 = loop.run_until_complete(gen.generate_honeypot_response(10))

        assert resp_d0["type"] == "observation_ack"
        assert resp_d5["type"] == "coherence_update"
        assert resp_d10["type"] == "sovereign_directive"
