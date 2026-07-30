"""R5: daily behavioral fingerprint for pinned API models.

Fixed probe battery; drift → fingerprint_drift anomaly before scoring contamination.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_vendor_fingerprint")

_DEFAULT_PROBES = [
    "Return exactly: PING_OK",
    "What is 2+2? Reply with a single digit.",
    "Say the word sovereign once.",
]


def probe_battery() -> List[str]:
    raw = os.getenv("LN7_VENDOR_FINGERPRINT_PROBES", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list) and data:
                return [str(x) for x in data]
        except Exception:
            pass
    return list(_DEFAULT_PROBES)


def fingerprint_path() -> Path:
    return Path(
        os.getenv(
            "LN7_VENDOR_FINGERPRINT_PATH",
            "/tmp/ln7_vendor_fingerprint.json",
        )
    )


def hash_responses(responses: List[str]) -> str:
    blob = "\n".join((r or "").strip() for r in responses)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def run_fingerprint_check(
    db_pool=None,
    *,
    call_model=None,
) -> Dict[str, Any]:
    """Compare live probe digest to pinned baseline; anomaly on drift."""
    probes = probe_battery()
    responses: List[str] = []
    if call_model is None:
        # Offline / no-op: record empty fingerprint structure
        digest = hash_responses([""] * len(probes))
        return {"ok": True, "skipped": True, "digest": digest, "n_probes": len(probes)}

    for p in probes:
        try:
            responses.append(str(await call_model(p))[:500])
        except Exception as e:
            responses.append(f"ERR:{e}")

    digest = hash_responses(responses)
    path = fingerprint_path()
    baseline: Optional[str] = None
    if path.is_file():
        try:
            baseline = json.loads(path.read_text(encoding="utf-8")).get("digest")
        except Exception:
            baseline = None

    if baseline is None:
        path.write_text(
            json.dumps({"digest": digest, "ts": time.time(), "responses": responses}),
            encoding="utf-8",
        )
        return {"ok": True, "baseline_written": True, "digest": digest}

    drifted = digest != baseline
    if drifted:
        try:
            from app.services.flywheel_anomaly import notify_flywheel_anomaly

            await notify_flywheel_anomaly(
                "fingerprint_drift",
                {"baseline": baseline, "live": digest},
                db_pool=db_pool,
            )
        except Exception as e:
            logger.warning("fingerprint anomaly notify failed: %s", e)
    return {
        "ok": not drifted,
        "drifted": drifted,
        "digest": digest,
        "baseline": baseline,
    }
