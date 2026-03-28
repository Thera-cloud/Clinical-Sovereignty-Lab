"""
HIVE DEFENSE PROTOCOL — Phase 8 Security Architecture
The Mirror Dimension, Three Cords Doctrine, Trinity Helix, and Projected Helix.

Phase 8B additions:
    - DefconController      (Claim 40)  — 5-level graduated defense posture
    - KeySharding           (Claim 36)  — Shamir 3-of-5 over GF(256)
    - EphemeralCertificateAuthority (Claim 38) — Scoped birth certificates
    - EntropyForge          (Cold Start) — Bootstrap entropy & birth chaining

Patent-Pending — Claims 30-56
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from app.services.security.defcon_controller import DefconController  # noqa: F401
from app.services.security.key_sharding import KeySharding  # noqa: F401
from app.services.security.ephemeral_certificates import EphemeralCertificateAuthority  # noqa: F401
from app.services.security.entropy_forge import EntropyForge  # noqa: F401

# Phase 8B — Hive Defense Protocol extensions
from app.services.security.behavioral_analytics import BehavioralAnalytics  # noqa: F401
from app.services.security.dependency_quarantine import DependencyQuarantine  # noqa: F401
from app.services.security.canary_credentials import CanaryCredentialManager  # noqa: F401
from app.services.security.cert_pinning import CertPinningConfig  # noqa: F401
from app.services.security.backup_encryption import BackupEncryptionManager  # noqa: F401

# Phase 8C — Third Cord services
from app.services.security.request_path_randomizer import RequestPathRandomizer  # noqa: F401
from app.services.security.adaptive_load_simulator import AdaptiveLoadSimulator  # noqa: F401
from app.services.security.recursive_containment import RecursiveContainment  # noqa: F401
from app.services.security.network_topology_fingerprint import NetworkTopologyFingerprint  # noqa: F401
from app.services.security.tripwire_network import TripwireNetwork  # noqa: F401
from app.services.security.cross_ref_consistency import CrossRefConsistencyEngine  # noqa: F401
from app.services.security.auto_triage import AutoTriage  # noqa: F401
from app.services.security.progressive_data_gating import ProgressiveDataGating  # noqa: F401
from app.services.security.differential_privacy import DifferentialPrivacy  # noqa: F401
