"""
Unified Ingest Validator — Phase 6.8 of Sovereign Quantum Nate Build.

Chains WisdomIntegrityGate + UploadContainment + rate check + reputation
for ALL data paths from external sources into Nate's knowledge.

Ingest paths: community wisdom, BLE mesh, federated search, device history
push, crystal exchange.
"""

import logging
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Per-user rate limits
_user_submission_counts: Dict[str, list] = {}
MAX_PER_HOUR = 50
MAX_PER_DAY = 200
MAX_PER_SESSION = 20

# Device reputation cache
_device_reputation: Dict[str, Dict] = {}
REPUTATION_QUARANTINE_THRESHOLD = 0.3
REPUTATION_MIN_SUBMISSIONS = 10


class IngestValidationResult:
    __slots__ = ("allowed", "reason", "quarantined")

    def __init__(self, allowed: bool, reason: str = "", quarantined: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.quarantined = quarantined


async def validate_ingest(
    text: str,
    source: str,
    user_id: str,
    device_id: Optional[str] = None,
    db_pool=None,
    app_state=None,
) -> IngestValidationResult:
    """
    Unified validation for all data entering Nate's knowledge stores.

    Returns IngestValidationResult with allowed=True/False and reason.
    """
    if not text or len(text.strip()) < 3:
        return IngestValidationResult(False, "Empty or trivial content")

    if len(text) > 50000:
        return IngestValidationResult(False, "Content exceeds 50K character limit")

    # Rate limiting
    rate_result = _check_rate_limit(user_id)
    if not rate_result.allowed:
        return rate_result

    # Device reputation check
    if device_id:
        rep_result = _check_device_reputation(device_id)
        if not rep_result.allowed:
            return rep_result

    # WisdomIntegrityGate
    if app_state:
        try:
            gate = getattr(app_state, "wisdom_integrity_gate", None)
            if gate and hasattr(gate, "validate_for_wisdom"):
                from enum import Enum

                class WisdomSource(Enum):
                    COMMUNITY_MESH = "community_mesh"
                    DEVICE_PUSH = "device_push"
                    CRYSTAL_EXCHANGE = "crystal_exchange"
                    FEDERATED_SEARCH = "federated_search"
                    BLE_MESH = "ble_mesh"

                source_enum = WisdomSource.COMMUNITY_MESH
                for ws in WisdomSource:
                    if ws.value == source:
                        source_enum = ws
                        break

                result = gate.validate_for_wisdom(text, source_enum, user_id)
                if hasattr(result, "approved") and not result.approved:
                    return IngestValidationResult(False, f"WisdomIntegrityGate rejected: {getattr(result, 'reason', 'policy violation')}")
        except Exception as e:
            logger.debug("WisdomIntegrityGate check skipped: %s", e)

    # UploadContainment — prompt injection + phishing detection
    if app_state:
        try:
            containment = getattr(app_state, "upload_containment", None)
            if containment and hasattr(containment, "scan_text"):
                scan = containment.scan_text(text, source)
                if hasattr(scan, "blocked") and scan.blocked:
                    return IngestValidationResult(False, f"UploadContainment blocked: {getattr(scan, 'reason', 'threat detected')}")
        except Exception as e:
            logger.debug("UploadContainment check skipped: %s", e)

    # Content hash dedup check
    if db_pool:
        try:
            import hashlib
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            async with db_pool.acquire() as conn:
                existing = await conn.fetchval(
                    "SELECT id FROM nate_intelligence_crystals WHERE content_hash = $1",
                    content_hash,
                )
                if existing:
                    return IngestValidationResult(False, "Duplicate content (hash match)")
        except Exception:
            pass

    # Track successful submission for rate limiting
    _record_submission(user_id)
    if device_id:
        _record_device_submission(device_id, accepted=True)

    return IngestValidationResult(True)


def _check_rate_limit(user_id: str) -> IngestValidationResult:
    now = time.time()
    entries = _user_submission_counts.get(user_id, [])
    entries = [t for t in entries if now - t < 86400]
    _user_submission_counts[user_id] = entries

    hour_count = sum(1 for t in entries if now - t < 3600)
    day_count = len(entries)

    if hour_count >= MAX_PER_HOUR:
        return IngestValidationResult(False, f"Rate limit: {MAX_PER_HOUR}/hour exceeded")
    if day_count >= MAX_PER_DAY:
        return IngestValidationResult(False, f"Rate limit: {MAX_PER_DAY}/day exceeded")

    return IngestValidationResult(True)


def _record_submission(user_id: str):
    _user_submission_counts.setdefault(user_id, []).append(time.time())


def _check_device_reputation(device_id: str) -> IngestValidationResult:
    rep = _device_reputation.get(device_id)
    if not rep:
        return IngestValidationResult(True)

    total = rep.get("submissions", 0)
    if total < REPUTATION_MIN_SUBMISSIONS:
        return IngestValidationResult(True)

    score = rep.get("score", 1.0)
    if score < REPUTATION_QUARANTINE_THRESHOLD:
        return IngestValidationResult(
            False,
            f"Device quarantined (reputation {score:.2f})",
            quarantined=True,
        )

    return IngestValidationResult(True)


def _record_device_submission(device_id: str, accepted: bool):
    rep = _device_reputation.setdefault(device_id, {
        "submissions": 0, "accepted": 0, "rejected": 0, "score": 1.0,
    })
    rep["submissions"] += 1
    if accepted:
        rep["accepted"] += 1
    else:
        rep["rejected"] += 1

    total = max(rep["submissions"], 1)
    rep["score"] = (rep["accepted"] - rep["rejected"] * 3) / total


def record_rejection(device_id: str):
    """Called when a submission is rejected post-validation."""
    _record_device_submission(device_id, accepted=False)


def get_device_reputation(device_id: str) -> Dict:
    return _device_reputation.get(device_id, {
        "submissions": 0, "accepted": 0, "rejected": 0, "score": 1.0,
    })
