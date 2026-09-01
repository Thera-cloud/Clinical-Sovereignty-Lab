"""R3 — Shadow evaluators (weld ossification without self-edit).

No loop edits its own evaluator (absolute — see the flywheel plan's R3
section). This module runs a *read-only* candidate parameter overlay
alongside the live, frozen Goodhart drift-band evaluator
(``goodhart_drift_sentinel.run_drift_check``). The shadow verdict never
influences the live tripped/anomaly decision — it is only logged to
``outcome_envelope`` (loop_name="shadow_eval") for later comparison.

On a monthly cadence, ``run_monthly_divergence_check`` inspects the last 30
days of logged (live, shadow) verdict pairs. If the divergence rate exceeds
``shadow_eval_params.json``'s threshold, it drafts a config diff and opens a
**draft-only** PR against ``frozen-config/`` via ``sovereign_weld_bot`` —
this module never writes frozen-config/ directly and never merges. Merge is
out-of-band, by a human with non-agent credentials
(``sovereign_weld_bot.open_shadow_eval_pr`` shells out to ``gh pr create
--draft`` and cannot push to ``main``).

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ln7_shadow_evaluator")

DEFAULT_SAMPLE_INTERVAL_S = int(
    os.getenv("LN7_SHADOW_EVAL_INTERVAL_S", str(7 * 24 * 3600))
)  # weekly sampling, matches R1's cadence
DEFAULT_DIVERGENCE_INTERVAL_S = int(
    os.getenv("LN7_SHADOW_EVAL_DIVERGENCE_INTERVAL_S", str(30 * 24 * 3600))
)  # monthly divergence check

# Safety allowlist: shadow variants may only target evaluator config files
# that are (a) purely numeric threshold banks, (b) already read by a live
# evaluator via app.services.ln7_frozen_config.load_json, and (c) NOT the
# held-out floor, adversarial criteria, or any file whose mutation could
# change what data trains/blocks (that boundary belongs to Phase H, not R3).
ALLOWED_SHADOW_TARGETS = frozenset({"goodhart_probes"})


def _overlay_json(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursive dict overlay — overlay wins on leaf conflicts. Never mutates
    ``base`` (returns a deep copy)."""
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _overlay_json(out[k], v)
        else:
            out[k] = v
    return out


def load_shadow_params() -> Dict[str, Any]:
    from app.services.ln7_frozen_config import load_json

    return load_json("shadow_eval_params.json", {}) or {}


def shadow_drift_bands(live_probes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the shadow-overlaid ``goodhart_probes.json`` drift_bands, or
    None if no active variant targets goodhart_probes. Every ``target`` is
    checked against ``ALLOWED_SHADOW_TARGETS`` — an unrecognized or
    disallowed target is skipped, never applied."""
    params = load_shadow_params()
    for variant in params.get("variants", []) or []:
        target = variant.get("target")
        if target not in ALLOWED_SHADOW_TARGETS:
            continue
        if target == "goodhart_probes":
            overlaid = _overlay_json(live_probes, variant.get("overlay") or {})
            return overlaid.get("drift_bands")
    return None


def _verdict(bands: Dict[str, Any], ref: Dict[str, Any], live_metrics: Dict[str, Any]) -> Dict[str, Any]:
    drifts: List[Dict[str, Any]] = []
    tripped = False
    for metric, band in (bands or {}).items():
        max_delta = float(band.get("max_abs_delta", 0.25))
        r = float(ref.get(metric, 0.0))
        live_val = float(live_metrics.get(metric, r))
        delta = abs(live_val - r)
        item = {
            "metric": metric,
            "delta": delta,
            "max": max_delta,
            "tripped": delta > max_delta,
        }
        if item["tripped"]:
            tripped = True
        drifts.append(item)
    return {"tripped": tripped, "drifts": drifts}


def iso_week_start_utc(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    monday = now.date() - timedelta(days=now.isoweekday() - 1)
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


async def already_sampled_this_iso_week(db_pool) -> bool:
    """Durable weekly dedupe — survives backend restart (agent loop does not)."""
    if not db_pool or not hasattr(db_pool, "acquire"):
        return False
    try:
        since = iso_week_start_utc()
        async with db_pool.acquire() as conn:
            val = await conn.fetchval(
                """
                SELECT 1 FROM outcome_envelope
                WHERE loop_name = 'shadow_eval' AND event_kind = 'weekly_sample'
                  AND created_at >= $1
                LIMIT 1
                """,
                since,
            )
        return bool(val)
    except Exception as e:
        logger.warning("already_sampled_this_iso_week: %s", e)
        return False


async def run_shadow_sample(db_pool=None, *, force: bool = False) -> Dict[str, Any]:
    """Run the live evaluator's measurement once, score it against BOTH the
    live (frozen) bands and the shadow (candidate) bands, and log both
    verdicts to outcome_envelope. Never mutates frozen-config, never
    influences the live drift_sentinel's tripped/anomaly decision."""
    if db_pool and not force and await already_sampled_this_iso_week(db_pool):
        return {"ok": True, "skipped": "already_sampled_this_week"}
    from app.services.ln7_frozen_config import load_json
    from app.services.goodhart_drift_sentinel import measure_live_metrics
    from app.services.ln7_outcome_envelope import write_envelope

    live_probes = load_json("goodhart_probes.json", {}) or {}
    live_bands = live_probes.get("drift_bands") or {}
    ref = (load_json("goodhart_reference.json", {}) or {}).get("metrics") or {}
    shadow_bands = shadow_drift_bands(live_probes)

    live_metrics = measure_live_metrics()
    live_verdict = _verdict(live_bands, ref, live_metrics)

    result: Dict[str, Any] = {
        "ok": True,
        "live_verdict": live_verdict,
        "shadow_verdict": None,
        "diverged": False,
        "skipped_shadow": shadow_bands is None,
    }
    if shadow_bands is None:
        return result

    shadow_verdict = _verdict(shadow_bands, ref, live_metrics)
    diverged = shadow_verdict["tripped"] != live_verdict["tripped"]
    result["shadow_verdict"] = shadow_verdict
    result["diverged"] = diverged

    try:
        await write_envelope(
            db_pool,
            loop_name="shadow_eval",
            event_kind="weekly_sample",
            domain_tag="goodhart_shadow",  # QUANTUM-CRYSTAL-ARCH — E2 join key for digest
            metrics=live_metrics,
            shadow_outcome={
                "live_tripped": live_verdict["tripped"],
                "shadow_tripped": shadow_verdict["tripped"],
                "diverged": diverged,
                "sampled_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        logger.warning("run_shadow_sample: envelope write failed: %s", e)
    return result


def _parse_shadow_outcome(raw: Any) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


async def run_monthly_divergence_check(db_pool=None) -> Dict[str, Any]:
    """Inspect the last 30 days of shadow_eval samples. If the divergence
    rate crosses the configured threshold, draft (never merge) a PR against
    frozen-config/ with the candidate config + evidence appendix. Emits a
    ``shadow_eval_divergence`` anomaly regardless of whether the PR call
    actually reached GitHub (dry_run is the safe default)."""
    if not db_pool:
        return {"ok": False, "error": "no_db_pool"}

    params = load_shadow_params()
    threshold = float(params.get("divergence_threshold", 0.20))
    min_samples = int(params.get("min_samples", 4))

    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT shadow_outcome FROM outcome_envelope
                WHERE loop_name = 'shadow_eval'
                  AND event_kind = 'weekly_sample'
                  AND created_at >= NOW() - INTERVAL '30 days'
                  AND shadow_outcome IS NOT NULL
                """
            )
    except Exception as e:
        logger.warning("monthly divergence query failed: %s", e)
        return {"ok": False, "error": str(e)}

    samples: List[Dict[str, Any]] = []
    for r in rows or []:
        parsed = _parse_shadow_outcome(r["shadow_outcome"])
        if parsed is not None:
            samples.append(parsed)

    total = len(samples)
    if total < min_samples:
        return {"ok": True, "skipped": True, "reason": "insufficient_samples", "count": total}

    diverged_count = sum(1 for s in samples if s.get("diverged"))
    rate = diverged_count / total if total else 0.0

    out: Dict[str, Any] = {
        "ok": True,
        "sample_count": total,
        "diverged_count": diverged_count,
        "divergence_rate": rate,
        "threshold": threshold,
        "pr_opened": False,
    }
    if rate <= threshold:
        return out

    from app.services.ln7_frozen_config import load_json
    from app.services.sovereign_weld_bot import open_shadow_eval_pr

    live_probes = load_json("goodhart_probes.json", {}) or {}
    candidate = dict(live_probes)
    bands = shadow_drift_bands(live_probes)
    if bands is not None:
        candidate["drift_bands"] = bands
        candidate["version"] = int(live_probes.get("version", 1)) + 1

    evidence = {
        "sample_count": total,
        "diverged_count": diverged_count,
        "divergence_rate": rate,
        "threshold": threshold,
        "window_days": 30,
    }
    body = (
        "## R3 shadow evaluator monthly divergence\n\n"
        f"Divergence rate {rate:.2%} over {total} weekly samples exceeded "
        f"threshold {threshold:.2%}.\n\n"
        "### Evidence\n```json\n" + json.dumps(evidence, indent=2) + "\n```\n\n"
        "Draft only — requires human review and merge with non-agent "
        "credentials. Opened by the sovereign-weld-bot GitHub App (W14), "
        "which can open PRs only and cannot merge or push to main."
    )
    try:
        pr_result = open_shadow_eval_pr(
            title="R3: shadow evaluator monthly divergence — goodhart_probes.json candidate",
            body=body,
            branch=f"sovereign-weld-bot/shadow-divergence-{datetime.now(timezone.utc):%Y%m}",
            files={"frozen-config/goodhart_probes.json": json.dumps(candidate, indent=2) + "\n"},
        )
    except Exception as e:
        logger.warning("open_shadow_eval_pr failed: %s", e)
        pr_result = {"ok": False, "error": str(e)}

    out["pr_result"] = pr_result
    out["pr_opened"] = bool(pr_result.get("ok")) and not pr_result.get("dry_run", True)

    try:
        from app.services.flywheel_anomaly import notify_flywheel_anomaly

        await notify_flywheel_anomaly(
            "shadow_eval_divergence",
            {"evidence": evidence, "pr_result": pr_result},
            db_pool=db_pool,
        )
    except Exception as e:
        logger.warning("shadow_eval_divergence anomaly notify failed: %s", e)

    return out


class ShadowEvaluatorAgent:
    """Background agent: weekly shadow sample + monthly divergence check."""

    def __init__(
        self,
        db_pool,
        sample_interval_s: int = DEFAULT_SAMPLE_INTERVAL_S,
        divergence_interval_s: int = DEFAULT_DIVERGENCE_INTERVAL_S,
    ):
        self.db_pool = db_pool
        self.sample_interval = max(3600, sample_interval_s)
        self.divergence_interval = max(3600, divergence_interval_s)
        self._task = None
        self._running = False
        self._cycles_since_divergence_check = 0
        self._divergence_ratio = max(1, self.divergence_interval // self.sample_interval)

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

        await asyncio.sleep(280)
        while self._running:
            try:
                await run_shadow_sample(self.db_pool)
                self._cycles_since_divergence_check += 1
                if self._cycles_since_divergence_check >= self._divergence_ratio:
                    self._cycles_since_divergence_check = 0
                    await run_monthly_divergence_check(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("ShadowEvaluatorAgent cycle failed: %s", e)
            await asyncio.sleep(self.sample_interval)
