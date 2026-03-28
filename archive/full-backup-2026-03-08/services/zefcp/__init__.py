"""
SOVEREIGN SWARM — ZEFCP (Zero-Energy Fibre Communication Protocol)
Layer 1: Physical Transport via Parasitic-Symbiotic BLE Handshake Piggybacking.
Patent Claim 25: Zero-Energy Parasitic BLE Communication.

Fibres encode micro-fragments into the overhead bytes of ambient BLE advertising
handshakes. Zero energy cost. Zero payload burden on carrier devices.
Spider Web endpoints passively detect fragments and reassemble observations
with Reed-Solomon error correction.

Capacity: 800 bytes/min urban | 0.00228% false positive | 70% reconstruction threshold
"""

from app.services.zefcp.constants import *  # noqa: F401, F403
from app.services.zefcp.spider_web import SpiderWebDetector  # noqa: F401
from app.services.zefcp.fragment_buffer import FragmentBuffer  # noqa: F401
from app.services.zefcp.assembly_coordinator import DistributedAssemblyCoordinator  # noqa: F401

# Patent Claim 25 modules
from app.services.zefcp.ble_encoder import BLEAdvertisingModulator  # noqa: F401
from app.services.zefcp.scheduler import EmbeddingScheduler  # noqa: F401
from app.services.zefcp.adaptive_redundancy import AdaptiveRedundancy, ArrivalStats  # noqa: F401
from app.services.zefcp.nfc_provisioner import NFCProvisioner  # noqa: F401
from app.services.zefcp.bridge import ZEFCPBridge  # noqa: F401
from app.services.zefcp.environment import EnvironmentInference  # noqa: F401
from app.services.zefcp.metrics import ZEFCPMetrics  # noqa: F401
