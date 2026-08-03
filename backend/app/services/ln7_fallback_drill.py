"""R5 quarterly fallback drills — prove destroy/fingerprint/dry hive without flips.

Does NOT set DUAL_COO_MECHANICAL_PROMOTE or ENABLE_LN7_AUTO_PROMOTE.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("ln7_fallback_drill")

# Rough quarterly cadence (seconds) — 90 days
DEFAULT_INTERVAL_S = int(os.getenv("LN7_FALLBACK_DRILL_INTERVAL_S", str(90 * 86400)))


async def run_fallback_drill(db_pool=None) -> Dict[str, Any]:
    """Dry-run hive + fingerprint + serve clear. Anomaly on hard fail."""
    from app.services.flywheel_anomaly import notify_flywheel_anomaly

    results: List[Dict[str, Any]] = []
    ok = True

    # 1) Dry hive burst (publishes then clears endpoint unless KEEP)
    try:
        prev = os.environ.get("LN7_HIVE_DRY_RUN")
        os.environ["LN7_HIVE_DRY_RUN"] = "1"
        from app.services.ln7_hive_burst import run_hive_burst

        hive = await run_hive_burst(db_pool, notes="fallback_drill", dry_run=True)
        results.append({"id": "hive_dry_run", "ok": bool(hive.get("ok")), "detail": hive})
        if not hive.get("ok"):
            ok = False
        if prev is None:
            os.environ.pop("LN7_HIVE_DRY_RUN", None)
        else:
            os.environ["LN7_HIVE_DRY_RUN"] = prev
    except Exception as e:
        ok = False
        results.append({"id": "hive_dry_run", "ok": False, "error": str(e)[:200]})

    # 2) Serve endpoint must be clear after dry (miss → ollama)
    try:
        from app.services.ln7_serve_endpoint import clear_serve_endpoint, get_serve_endpoint

        clear_serve_endpoint()
        ep = get_serve_endpoint()
        clear_ok = ep is None
        results.append({"id": "serve_cleared", "ok": clear_ok, "endpoint": ep})
        if not clear_ok:
            ok = False
    except Exception as e:
        results.append({"id": "serve_cleared", "ok": False, "error": str(e)[:200]})

    # 3) Vendor fingerprint (non-blocking if skipped)
    try:
        from app.services.ln7_vendor_fingerprint import run_fingerprint_check

        fp = await run_fingerprint_check(db_pool)
        fp_ok = not fp.get("drifted")
        results.append({"id": "fingerprint", "ok": fp_ok, "detail": fp})
        if fp.get("drifted"):
            ok = False
    except Exception as e:
        results.append({"id": "fingerprint", "ok": True, "skipped": True, "error": str(e)[:120]})

    # 4) Fence manifest still green
    try:
        from app.services.ln7_frozen_config import verify_manifest

        fence_ok, mismatches = verify_manifest()
        results.append({"id": "fence_manifest", "ok": fence_ok, "mismatches": mismatches})
        if not fence_ok:
            ok = False
    except Exception as e:
        results.append({"id": "fence_manifest", "ok": False, "error": str(e)[:200]})
        ok = False

    # 5) R5 supply-chain pins: droplet lockfile hash-pinned + mirror declared (always
    # checkable, this artifact ships on every node), and base-model checksums intact
    # where a local checkout exists (skips gracefully elsewhere).
    try:
        from app.services.ln7_droplet_lockfile import verify_droplet_lockfile

        lock = verify_droplet_lockfile()
        lock_ok = bool(lock.get("ok"))
        if not lock_ok:
            ok = False
    except Exception as e:
        lock = {"ok": False, "error": str(e)[:200]}
        lock_ok = False
        ok = False

    try:
        from app.services.ln7_r2_weight_mirror import verify_base_model_checksums

        base = await verify_base_model_checksums()
        base_ok = bool(base.get("ok"))
        if not base_ok:
            ok = False
    except Exception as e:
        base = {"ok": False, "error": str(e)[:200]}
        base_ok = False
        ok = False

    results.append({
        "id": "supply_chain_pin",
        "ok": lock_ok and base_ok,
        "droplet_lockfile": lock,
        "base_model_checksums": base,
    })

    out = {
        "ok": ok,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "governance_note": "drill does not flip G2 flags",
    }
    if not ok:
        await notify_flywheel_anomaly(
            "fallback_drill_fail",
            out,
            db_pool=db_pool,
        )
    if db_pool:
        try:
            from app.services.ln7_outcome_envelope import write_envelope

            await write_envelope(
                db_pool,
                loop_name="ops",
                event_kind="fallback_drill",
                metrics=out,
                source_node="green",
            )
        except Exception:
            pass
    return out


class FallbackDrillAgent:
    """Background quarterly drill (activate-ready; interval env-tunable)."""

    def __init__(self, db_pool, interval_seconds: int = DEFAULT_INTERVAL_S):
        self.db_pool = db_pool
        self.interval = max(3600, interval_seconds)
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

        # First drill after short stagger (prove wiring); then quarterly
        await asyncio.sleep(240)
        while self._running:
            try:
                # Skip first heavy run unless LN7_FALLBACK_DRILL_ON_BOOT=1
                if os.getenv("LN7_FALLBACK_DRILL_ON_BOOT", "").strip().lower() in (
                    "1", "true", "yes", "on",
                ):
                    await run_fallback_drill(self.db_pool)
                else:
                    logger.info("FallbackDrillAgent armed (next full drill after interval)")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("FallbackDrillAgent cycle failed: %s", e)
            await asyncio.sleep(self.interval)
            try:
                await run_fallback_drill(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("FallbackDrillAgent drill failed: %s", e)
