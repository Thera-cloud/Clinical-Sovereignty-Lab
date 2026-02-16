"""
SOVEREIGN SWARM — ZEFCP Models
Zero-Energy Fibre Communication Protocol data contracts (Patent Claim 25).

Layer 1: Physical Transport — Parasitic-Symbiotic BLE Handshake Piggybacking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class FragmentMode(str, Enum):
    """Fragment encoding modes based on available BLE overhead window size."""
    STANDARD = "standard"     # 8 bytes: 4 leading + 4 trailing (2B payload)
    EXTENDED = "extended"     # 12 bytes: 6 leading + 6 trailing (5B payload)


class FragmentType(str, Enum):
    """Distinguishes data fragments from Reed-Solomon parity fragments."""
    DATA = "data"             # Contains observation payload
    PARITY = "parity"         # Reed-Solomon error correction


# =============================================================================
# MICRO-FRAGMENT — The atomic unit of parasitic BLE transport
# =============================================================================

class MicroFragment(BaseModel):
    """
    The atomic unit of parasitic-symbiotic BLE transport.
    Sized to fit within the overhead bytes of a single
    BLE advertising handshake exchange.

    Standard mode: 8 bytes (SIG/SEQ/TOTAL/FRAG_HI + FRAG_LO/PAYLOAD[2]/CHK)
    Extended mode: 12 bytes (SIG/OBS_ID/SEQ/TOTAL/FLAGS/EPOCH + PAYLOAD[5]/CHK)
    """
    # Header
    signature: int = Field(..., ge=0, le=255, description="SIG byte (rotation-scheduled)")
    sequence: int = Field(..., ge=0, le=255, description="Fragment position (0-255)")
    total: int = Field(..., ge=1, le=255, description="Total fragments in observation")

    # Extended mode fields (None in standard mode)
    observation_id: Optional[int] = Field(None, ge=0, le=255, description="Observation discriminator")
    flags: Optional[int] = Field(None, ge=0, le=255, description="Bit flags: redundancy(2)|priority(2)|compression(1)|trail(1)|reserved(2)")
    epoch: Optional[int] = Field(None, ge=0, le=255, description="Truncated timestamp (minutes mod 256)")

    # Standard mode field
    frag_id: Optional[int] = Field(None, ge=0, le=65535, description="Fragment identifier (standard mode)")

    # Payload
    payload: bytes = Field(..., description="2 bytes (standard) or 5 bytes (extended)")
    fragment_type: FragmentType = FragmentType.DATA

    # Integrity
    checksum: int = Field(..., ge=0, le=255, description="CRC-8")

    # Mode
    mode: FragmentMode = FragmentMode.EXTENDED

    # Metadata (not transmitted — local tracking)
    detected_at: Optional[float] = None
    detected_by: Optional[str] = None
    rssi: Optional[int] = None
    carrier_device: Optional[str] = None
    priority_boost: float = Field(default=1.0, description="Quakete boost multiplier")

    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# FIBRE OBSERVATION — Pre-fragmentation intelligence package
# =============================================================================

class FibreObservation(BaseModel):
    """
    A complete observation package from a field-deployed Fibre.
    This is the pre-fragmentation data structure that gets
    serialized, encrypted, and fragmented for BLE transport.
    """
    observation_id: UUID = Field(default_factory=uuid4)
    fibre_id: str = Field(..., description="Fibre identity (truncated to 4 bytes for transport)")
    fibre_type: str = Field(..., description="FibreType enum value")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    coherence_data: Optional[bytes] = None
    cultural_signal: Optional[bytes] = None
    foresight_signal: Optional[bytes] = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    priority: int = Field(default=1, ge=0, le=255)
    ed25519_signature: Optional[bytes] = Field(None, description="Observation authenticity signature")

    # Assembly metadata (populated after reassembly)
    assembly_total_fragments: Optional[int] = None
    assembly_local_count: Optional[int] = None
    assembly_remote_count: Optional[int] = None
    assembly_duration_seconds: Optional[float] = None
    assembly_endpoint_id: Optional[str] = None


class ObservationAssembly(BaseModel):
    """Tracks the assembly state of a single observation being reconstructed."""
    observation_key: str
    total_fragments: int
    received_sequences: List[int] = Field(default_factory=list)
    fragments: Dict[int, Any] = Field(default_factory=dict)
    created_at: float
    last_fragment_at: float
    is_trail: bool = False


# =============================================================================
# BLE ADVERTISING PDU MODEL
# =============================================================================

class ADStructure(BaseModel):
    """A single AD structure within a BLE advertising PDU."""
    length: int
    ad_type: int
    data: bytes

    class Config:
        arbitrary_types_allowed = True


class BLEAdvertisingPDU(BaseModel):
    """
    Representation of a BLE advertising PDU for fragment extraction.
    The Spider Web Detector processes these to find embedded fragments.
    """
    preamble: Optional[bytes] = None
    access_address: Optional[bytes] = None
    ad_structures: List[ADStructure] = Field(default_factory=list)
    scan_response_data: Optional[List[ADStructure]] = None
    rssi: Optional[int] = None
    source_address: Optional[str] = None
    timestamp: float = 0.0

    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# TRANSPORT CONFIGURATION
# =============================================================================

class BLETransportConfig(BaseModel):
    """
    Configuration for the BLE parasitic transport layer.
    Stored in Sovereign Command for administrator tuning.
    """
    # Encoding
    default_mode: FragmentMode = FragmentMode.EXTENDED
    default_redundancy: float = Field(default=0.3, description="RS redundancy factor")
    adaptive_redundancy_enabled: bool = True

    # Signature
    signature_rotation_minutes: int = 15
    signature_window_periods: int = 3

    # Detection
    false_positive_crc_validation: bool = True
    structural_coherence_check: bool = True

    # Assembly
    max_pending_observations: int = 256
    fragment_timeout_seconds: int = 3600
    min_reconstruction_ratio: float = 0.7

    # Security
    encryption_algorithm: str = "AES-128-CTR"
    signature_algorithm: str = "Ed25519"
    key_derivation: str = "HKDF-SHA256"

    # Performance
    max_embedding_rate: int = 10
    cloud_forwarding_batch_size: int = 50
    cloud_forwarding_interval_seconds: int = 5

    # Monitoring
    metrics_reporting_interval_seconds: int = 60
    log_fragment_detections: bool = True
    log_false_positives: bool = True


# =============================================================================
# TRANSPORT METRICS
# =============================================================================

class TransportMetrics(BaseModel):
    """
    Performance metrics for the BLE transport layer.
    Reported to The Eye dashboard via Sovereign Command.
    """
    endpoint_id: str
    period_start: datetime
    period_end: datetime

    # Detection
    total_ble_pdus_scanned: int = 0
    signature_matches: int = 0
    crc_validated: int = 0
    false_positives_discarded: int = 0
    valid_fragments_detected: int = 0

    # Assembly
    observations_completed: int = 0
    observations_expired: int = 0
    avg_assembly_time_seconds: float = 0.0
    avg_fragments_per_observation: float = 0.0
    avg_fragment_loss_rate: float = 0.0
    reed_solomon_corrections: int = 0

    # Environment
    ambient_ble_density: float = 0.0
    unique_ble_devices_observed: int = 0

    # Cloud bridge
    fragments_forwarded_to_cloud: int = 0
    observations_forwarded_to_mesh: int = 0


# =============================================================================
# NFC PROVISIONING
# =============================================================================

class NFCProvisioningPayload(BaseModel):
    """
    Data transferred via NFC tap during device onboarding.
    NFC's extremely short range (< 4cm) ensures this transfer
    cannot be intercepted remotely.
    """
    device_id: str
    swarm_secret_encrypted: bytes
    identity_signature: bytes
    transport_config: BLETransportConfig = Field(default_factory=BLETransportConfig)
    device_keypair_seed: bytes = b""
    observation_key_material: bytes = b""
    mesh_endpoint_config: Dict[str, Any] = Field(default_factory=dict)
    assigned_domain_tags: List[str] = Field(default_factory=list)
    fibre_config: Optional[Dict[str, Any]] = None

    class Config:
        arbitrary_types_allowed = True
