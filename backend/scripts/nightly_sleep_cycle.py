#!/usr/bin/env python3
"""
Sovereign Sanctuary — Nightly Sleep Cycle
=========================================
Reticular formation maintenance cycle.

Suggested cron:
0 3 * * * cd /opt/clinical-sovereignty-lab/backend && /usr/bin/python3 -m scripts.nightly_sleep_cycle
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow script execution as module or direct file
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("sovereign.sleep")


def _phase_enabled(env_key: str) -> bool:
    """
    Opt-in phase loading for heavy service imports.
    Defaults to disabled to keep cron/script execution safe when optional
    service dependencies are unavailable in the runtime image.
    """
    return os.getenv(env_key, "0").strip().lower() in {"1", "true", "yes", "on"}


async def run_sleep_cycle():
    """Execute nightly consolidation with graceful fallback."""
    logger.info("=" * 60)
    logger.info("RETICULAR FORMATION — SLEEP CYCLE INITIATED")
    logger.info("Timestamp: %s", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 60)

    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "audit": None,
        "foresight": None,
        "cycle_analysis": None,
        "errors": [],
    }

    # PHASE 1: Crystal Quality Audit
    logger.info("[PHASE 1] Crystal Quality Audit — cerebellum consolidation")
    if not _phase_enabled("SLEEP_PHASE_AUDIT"):
        logger.info("[PHASE 1] disabled by env SLEEP_PHASE_AUDIT=0")
        results["audit"] = {"status": "disabled_by_env"}
    else:
        try:
            from app.services.crystal_quality_auditor import CrystalQualityAuditor  # type: ignore

            auditor = CrystalQualityAuditor()
            run_nightly_audit = getattr(auditor, "run_nightly_audit", None)
            if callable(run_nightly_audit):
                results["audit"] = await run_nightly_audit()
            else:
                results["audit"] = {"status": "method_missing"}
            logger.info("[PHASE 1] Complete")
        except ImportError:
            logger.info("[PHASE 1] CrystalQualityAuditor not yet built — skipping")
            results["audit"] = {"status": "not_implemented"}
        except Exception as e:
            logger.error("[PHASE 1] Audit error: %s", e)
            results["errors"].append(f"audit: {e}")

    # PHASE 2: Foresight Trajectory
    logger.info("[PHASE 2] Foresight Trajectory — thalamic steering update")
    if not _phase_enabled("SLEEP_PHASE_FORESIGHT"):
        logger.info("[PHASE 2] disabled by env SLEEP_PHASE_FORESIGHT=0")
        results["foresight"] = {"status": "disabled_by_env"}
    else:
        try:
            from app.services.code_foresight_engine import CodeForesightEngine  # type: ignore

            foresight = CodeForesightEngine()
            trajectory = {}
            forecast = getattr(foresight, "forecast_c_emo_trajectory", None)
            if callable(forecast):
                trajectory = await forecast()
            detect_stall = getattr(foresight, "detect_and_respond_to_stall", None)
            if callable(detect_stall):
                stall_response = await detect_stall()
                if stall_response and stall_response.get("stall_detected"):
                    trajectory["stall_response"] = stall_response
            predict_idle = getattr(foresight, "predict_idle_capacity_window", None)
            if callable(predict_idle):
                trajectory["idle_capacity"] = await predict_idle()
            results["foresight"] = trajectory or {"status": "ok"}
            logger.info("[PHASE 2] Complete")
        except ImportError:
            logger.info("[PHASE 2] CodeForesightEngine not yet built — skipping")
            results["foresight"] = {"status": "not_implemented"}
        except Exception as e:
            logger.error("[PHASE 2] Foresight error: %s", e)
            results["errors"].append(f"foresight: {e}")

    # PHASE 3: Cycle Pattern Analysis
    logger.info("[PHASE 3] Cycle Pattern Analysis — spinothalamic refinement")
    if not _phase_enabled("SLEEP_PHASE_CYCLE"):
        logger.info("[PHASE 3] disabled by env SLEEP_PHASE_CYCLE=0")
        results["cycle_analysis"] = {"status": "disabled_by_env"}
    else:
        try:
            from app.services.code_cycle_detector import CodeCycleDetector  # type: ignore

            _ = CodeCycleDetector
            results["cycle_analysis"] = {"status": "active"}
            logger.info("[PHASE 3] Complete")
        except ImportError:
            logger.info("[PHASE 3] CodeCycleDetector not yet built — skipping")
            results["cycle_analysis"] = {"status": "not_implemented"}
        except Exception as e:
            logger.error("[PHASE 3] Cycle analysis error: %s", e)
            results["errors"].append(f"cycle: {e}")

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    logger.info("=" * 60)
    logger.info("RETICULAR FORMATION — AROUSAL RESTORING")
    logger.info("Errors: %s", len(results["errors"]))
    logger.info("=" * 60)

    output_path = PROJECT_ROOT / "data" / "sleep_cycle_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results written to %s", output_path)
    return results


if __name__ == "__main__":
    outcome = asyncio.run(run_sleep_cycle())
    if outcome.get("errors"):
        sys.exit(1)
