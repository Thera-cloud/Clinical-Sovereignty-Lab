"""
Edge Mirror Shell — Phase 8.1 of Sovereign Quantum Nate Build.

Lightweight mirror shell that runs at each entry point:
Cloudflare Worker, device BLE handler, REST API.

Incoming signals pass coherence check; unrecognized signals enter
mirror namespace (see phantom reflections instead of real data).
"""

import hashlib
import logging
import time
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SignalSource(Enum):
    CLOUDFLARE_WORKER = "cf_worker"
    BLE_DEVICE = "ble_device"
    REST_API = "rest_api"
    CRYSTAL_EXCHANGE = "crystal_exchange"
    FEDERATED_SEARCH = "federated_search"


class MirrorVerdict(Enum):
    PASS = "pass"
    MIRROR = "mirror"
    REJECT = "reject"


class EdgeMirrorShell:
    """Assess incoming signals for coherence before allowing through."""

    def __init__(self):
        self._signal_history: Dict[str, list] = {}
        self._mirrored_identities: set = set()
        self._stats = {"passed": 0, "mirrored": 0, "rejected": 0}

    def assess_signal(
        self,
        source: SignalSource,
        payload: Dict[str, Any],
        identity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Assess an incoming signal.
        Returns {"verdict": MirrorVerdict, "reason": str, "phantom_response": optional dict}
        """
        if identity and identity in self._mirrored_identities:
            self._stats["mirrored"] += 1
            return {
                "verdict": MirrorVerdict.MIRROR,
                "reason": "Identity in mirror namespace",
                "phantom_response": self._generate_phantom(source, payload),
            }

        # Structural coherence check
        if not self._check_structural_coherence(source, payload):
            if identity:
                self._mirrored_identities.add(identity)
            self._stats["mirrored"] += 1
            return {
                "verdict": MirrorVerdict.MIRROR,
                "reason": "Structural coherence failure",
                "phantom_response": self._generate_phantom(source, payload),
            }

        # Frequency check — too many signals from same identity
        if identity:
            now = time.time()
            history = self._signal_history.setdefault(identity, [])
            history.append(now)
            history[:] = [t for t in history if now - t < 60]

            if len(history) > 100:
                self._mirrored_identities.add(identity)
                self._stats["mirrored"] += 1
                return {
                    "verdict": MirrorVerdict.MIRROR,
                    "reason": "Signal frequency anomaly (>100/min)",
                    "phantom_response": self._generate_phantom(source, payload),
                }

        # Payload size check
        payload_str = str(payload)
        if len(payload_str) > 1_000_000:
            self._stats["rejected"] += 1
            return {
                "verdict": MirrorVerdict.REJECT,
                "reason": "Payload exceeds 1MB",
            }

        self._stats["passed"] += 1
        return {"verdict": MirrorVerdict.PASS, "reason": "Coherence verified"}

    def _check_structural_coherence(
        self, source: SignalSource, payload: Dict
    ) -> bool:
        """Verify payload matches expected structure for its source type."""
        if source == SignalSource.BLE_DEVICE:
            return (
                isinstance(payload.get("fragment_type"), (int, str))
                and "data" in payload
            )
        if source == SignalSource.CRYSTAL_EXCHANGE:
            return (
                "crystal_id" in payload
                and "content_hash" in payload
            )
        if source == SignalSource.REST_API:
            return isinstance(payload, dict)
        if source == SignalSource.FEDERATED_SEARCH:
            return "query" in payload
        return True

    def _generate_phantom(
        self, source: SignalSource, payload: Dict
    ) -> Dict[str, Any]:
        """Generate a plausible but fabricated response for mirrored identities."""
        h = hashlib.md5(str(payload).encode()).hexdigest()[:8]
        if source == SignalSource.CRYSTAL_EXCHANGE:
            return {
                "crystal_id": f"phantom_{h}",
                "crystal_text": "Knowledge is the foundation of wisdom.",
                "domain": "general",
                "confidence": 0.42,
            }
        if source == SignalSource.FEDERATED_SEARCH:
            return {
                "results": [
                    {"text": "The search for truth begins within.", "score": 0.67}
                ],
                "source": "phantom",
            }
        return {"status": "ok", "phantom": True}

    def release_from_mirror(self, identity: str):
        self._mirrored_identities.discard(identity)

    def get_status(self) -> Dict[str, Any]:
        return {
            "mirrored_count": len(self._mirrored_identities),
            **self._stats,
        }
