"""
ZEFCP Protocol Constants — AD Types, Thresholds, Rates.
All tunable parameters for the BLE parasitic transport layer.
"""

# =============================================================================
# BLE AD TYPES — Exploitable overhead positions
# =============================================================================

# AD Types that commonly carry exploitable overhead
EXPLOITABLE_AD_TYPES = {
    0xFF,   # Manufacturer Specific Data
    0x16,   # Service Data - 16-bit UUID
    0x21,   # Service Data - 128-bit UUID
    0x02,   # Incomplete List of 16-bit Service UUIDs
    0x06,   # Incomplete List of 128-bit Service UUIDs
    0x09,   # Complete Local Name (trailing bytes after name)
}

# Minimum bytes in each AD structure that must remain untouched
MINIMUM_FUNCTIONAL_BYTES = {
    0xFF: 2,    # Company ID (2 bytes) must be preserved
    0x16: 2,    # UUID (2 bytes) must be preserved
    0x21: 16,   # UUID (16 bytes) must be preserved
    0x02: 0,    # UUID list — trailing entries are "incomplete" by definition
    0x06: 0,    # UUID list — trailing entries are "incomplete" by definition
    0x09: 1,    # At least first character of name must be preserved
}

# =============================================================================
# SIGNATURE ROTATION
# =============================================================================

SIGNATURE_ROTATION_MINUTES = 15
SIGNATURE_WINDOW_PERIODS = 3   # Accept current ± 1

# =============================================================================
# FRAGMENT ENCODING
# =============================================================================

STANDARD_LEADING_BYTES = 4
STANDARD_TRAILING_BYTES = 4
STANDARD_PAYLOAD_SIZE = 2
STANDARD_TOTAL_BYTES = 8

EXTENDED_LEADING_BYTES = 6
EXTENDED_TRAILING_BYTES = 6
EXTENDED_PAYLOAD_SIZE = 5
EXTENDED_TOTAL_BYTES = 12

MAX_FRAGMENTS_PER_OBSERVATION = 255

# Trail emission flag in FLAGS byte
TRAIL_FLAG_MASK = 0b10000000

# =============================================================================
# REED-SOLOMON ERROR CORRECTION
# =============================================================================

DEFAULT_REDUNDANCY_FACTOR = 0.3       # 30% overhead → reconstruct from 70%
MIN_REDUNDANCY_FACTOR = 0.1           # Very reliable environment
MAX_REDUNDANCY_FACTOR = 0.5           # Very harsh environment
RECONSTRUCTION_THRESHOLD = 0.7        # Minimum fragment ratio for RS decode
PARITY_INTERLEAVE_INTERVAL = 4        # Insert parity every Nth fragment

# =============================================================================
# FRAGMENT BUFFER
# =============================================================================

MAX_PENDING_OBSERVATIONS = 256
FRAGMENT_TIMEOUT_SECONDS = 3600       # 1 hour
DUPLICATE_DETECTION_WINDOW = 60       # Seconds

# =============================================================================
# EMBEDDING & DETECTION
# =============================================================================

MAX_EMBEDDING_RATE = 10               # Max fragments per second
CLOUD_FORWARDING_BATCH_SIZE = 50
CLOUD_FORWARDING_INTERVAL_SECONDS = 5

# =============================================================================
# ENCRYPTION
# =============================================================================

ENCRYPTION_ALGORITHM = "AES-128-CTR"
KEY_LENGTH_BYTES = 16                 # 128-bit AES key
NONCE_LENGTH_BYTES = 16               # CTR mode nonce
KEY_DERIVATION_INFO_PREFIX = b"fibre-obs-"

# =============================================================================
# PERFORMANCE THRESHOLDS
# =============================================================================

# Environment density profiles (handshakes/min)
DENSITY_URBAN_DENSE = 500
DENSITY_URBAN_STANDARD = 200
DENSITY_SUBURBAN = 100
DENSITY_CLINIC = 50
DENSITY_RURAL = 15

# False positive budget
MAX_FALSE_POSITIVE_RATE = 0.0001      # 0.01%
EXPECTED_FALSE_POSITIVE_RATE = 0.0000228  # 0.00228%

# Metrics reporting
METRICS_REPORTING_INTERVAL_SECONDS = 60

# =============================================================================
# CRC-8 POLYNOMIAL
# =============================================================================

CRC8_POLYNOMIAL = 0x07               # x^8 + x^2 + x + 1 (standard CRC-8)
CRC8_INIT = 0x00
