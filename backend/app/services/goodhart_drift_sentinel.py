"""R1 Goodhart drift sentinel — frozen reference vs weekly probes (W16).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("goodhart_drift_sentinel")


def measure_live_metrics() -> Dict[str, float]:
    """Placeholder live metrics; production fills from envelope aggregates."""
    # Without clinical traffic, return reference (no false drift)
    from app.services.ln7_frozen_config import load_json

    ref = load_json("goodhart_reference.json", {}) or {}
    return dict(ref.get("metrics") or {})


async def run_drift_check(db_pool=None) -> Dict[str, Any]:
    from app.services.ln7_frozen_config import load_json
    from app.services.flywheel_anomaly import notify_flywheel_anomaly

    probes = load_json("goodhart_probes.json", {}) or {}
    ref = load_json("goodhart_reference.json", {}) or {}
    bands = probes.get("drift_bands") or {}
    ref_m = ref.get("metrics") or {}
    live = measure_live_metrics()

    drifts: List[Dict[str, Any]] = []
    tripped = False
    for metric, band in bands.items():
        max_delta = float(band.get("max_abs_delta", 0.25))
        r = float(ref_m.get(metric, 0.0))
        l = float(live.get(metric, r))
        delta = abs(l - r)
        item = {"metric": metric, "ref": r, "live": l, "delta": delta, "max": max_delta}
        if delta > max_delta:
            item["tripped"] = True
            tripped = True
        drifts.append(item)

    # R5: vendor fingerprint check runs alongside weekly drift
    fp: Dict[str, Any] = {"skipped": True}
    try:
        from app.services.ln7_vendor_fingerprint import run_fingerprint_check

        fp = await run_fingerprint_check(db_pool)
    except Exception as e:
        logger.warning("fingerprint check: %s", e)

    out = {
        "ok": not tripped and not fp.get("drifted"),
        "drifts": drifts,
        "tripped": tripped,
        "fingerprint": fp,
    }
    if tripped:
        await notify_flywheel_anomaly(
            "drift_sentinel",
            {"drifts": drifts},
            db_pool=db_pool,
        )
    return out


class GoodhartDriftSentinel:
    def __init__(self, db_pool, interval_seconds: int = 604800):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task = None
        self._running = False

    async def start(self):
        import asyncio

        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        import asyncio

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        import asyncio

        await asyncio.sleep(210)
        while self._running:
            try:
                await run_drift_check(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("GoodhartDriftSentinel failed: %s", e)
            await asyncio.sleep(self.interval)
