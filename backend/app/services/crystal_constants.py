"""Canonical crystal pipeline constants.

Every file that touches crystal confidence, decay, or promotion
must import from here — never hardcode these values.
"""

PROMOTION_INCREMENT = 0.03
PROMOTION_CAP = 0.95

CONFIDENCE_LOCKED = 0.85
CONFIDENCE_PROMOTED = 0.75
CONFIDENCE_TENSION = 0.60
CONFIDENCE_SOVEREIGN = 0.95

DECAY_DAYS = 90
DECAY_MIN_RECALLS = 3
DECAY_ARCHIVE_THRESHOLD = 0.15
