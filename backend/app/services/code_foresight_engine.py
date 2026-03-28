"""
Code Foresight Engine — EXA Methodology v5 Self-Steering.

Forecasts C_emo trajectory using linear regression on nevedal_coherence_log,
detects stalls (< 1% growth across 48 samples), and predicts idle compute
capacity windows for scheduling bulk ingestion bursts.

Runs as a background agent with a 4h cycle.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from app.services.nate_agent_template import NateAutonomousAgent
except ImportError:
    NateAutonomousAgent = object

STALL_THRESHOLD_PCT = 1.0
MIN_SAMPLES_FOR_FORECAST = 12
FORECAST_HORIZON_HOURS = 168  # 7 days


class CodeForesightEngine(NateAutonomousAgent):
    """Forecasts C_emo growth, detects stalls, triggers acceleration bursts."""

    def __init__(self, db_pool=None, app_state=None):
        super().__init__(
            agent_name="CodeForesightEngine",
            domain="coding",
            cycle_hours=4.0,
            db_pool=db_pool,
            app_state=app_state,
        )
        self._last_forecast: Optional[Dict] = None
        self._stall_count = 0

    async def observe(self) -> List[Dict]:
        """Foresight engine uses _cycle directly, not observe/reason/crystallize."""
        return []

    async def _run_loop(self):
        await asyncio.sleep(210)
        while self._running:
            try:
                await self._cycle()
                self._cycle_count += 1
                self._last_cycle = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("CodeForesightEngine cycle error: %s", e)
            await asyncio.sleep(int(self.cycle_hours * 3600))

    async def _cycle(self):
        if not self._db_pool:
            return

        try:
            samples = await self._fetch_coherence_samples()
            if len(samples) < MIN_SAMPLES_FOR_FORECAST:
                logger.info("CodeForesight: only %d samples, need %d",
                            len(samples), MIN_SAMPLES_FOR_FORECAST)
                return

            forecast = self._compute_forecast(samples)
            self._last_forecast = forecast

            if forecast.get("stall_detected"):
                self._stall_count += 1
                logger.warning("CodeForesight: C_emo STALL detected (count=%d). "
                               "Growth=%.2f%% over %d samples",
                               self._stall_count,
                               forecast.get("growth_pct", 0),
                               len(samples))
                await self._trigger_acceleration_burst()
            else:
                self._stall_count = 0

            await self._log_forecast(forecast)
        except Exception as e:
            logger.warning("CodeForesight cycle error: %s", e)

    async def _fetch_coherence_samples(self) -> List[Dict]:
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT C_emo, crystal_count, created_at
                FROM nevedal_coherence_log
                WHERE domain = 'coding'
                ORDER BY created_at DESC
                LIMIT 96
            """)
            return [
                {"c_emo": float(r["c_emo"] or 0),
                 "crystals": int(r["crystal_count"]),
                 "ts": r["created_at"].timestamp()}
                for r in reversed(rows)
            ]

    def _compute_forecast(self, samples: List[Dict]) -> Dict[str, Any]:
        n = len(samples)
        xs = [s["ts"] for s in samples]
        ys = [s["c_emo"] for s in samples]

        x_min, x_max = xs[0], xs[-1]
        x_range = x_max - x_min or 1.0
        xs_norm = [(x - x_min) / x_range for x in xs]

        x_mean = sum(xs_norm) / n
        y_mean = sum(ys) / n

        ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs_norm, ys))
        ss_xx = sum((x - x_mean) ** 2 for x in xs_norm)

        slope = ss_xy / ss_xx if ss_xx > 0 else 0
        intercept = y_mean - slope * x_mean

        y_first = ys[0] if ys[0] > 0 else 0.001
        growth_pct = ((ys[-1] - ys[0]) / y_first * 100) if y_first > 0 else 0

        stall = abs(growth_pct) < STALL_THRESHOLD_PCT and n >= 48

        forecast_ts = x_max + (FORECAST_HORIZON_HOURS * 3600)
        forecast_x_norm = (forecast_ts - x_min) / x_range
        forecast_c_emo = slope * forecast_x_norm + intercept
        forecast_c_emo = max(0.0, min(1.0, forecast_c_emo))

        crystal_xs = [s["crystals"] for s in samples]
        crystal_slope = ((crystal_xs[-1] - crystal_xs[0]) / n) if n > 1 else 0
        crystals_per_day = crystal_slope * (86400 / (x_range / n)) if x_range > 0 and n > 1 else 0

        return {
            "current_c_emo": round(ys[-1], 4),
            "current_crystals": crystal_xs[-1],
            "slope": round(slope, 6),
            "growth_pct": round(growth_pct, 2),
            "stall_detected": stall,
            "forecast_7d_c_emo": round(forecast_c_emo, 4),
            "crystals_per_day": round(crystals_per_day, 1),
            "sample_count": n,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _trigger_acceleration_burst(self):
        """If stall persists for 3+ cycles, trigger a synthesis burst."""
        if self._stall_count < 3:
            return

        crystallizer = getattr(self._app_state, "nate_memory_crystallizer", None) if self._app_state else None
        if crystallizer and hasattr(crystallizer, "set_acceleration_mode"):
            crystallizer.set_acceleration_mode(True)
            logger.info("CodeForesight: activated acceleration mode after %d stalls",
                        self._stall_count)

        ingestion = getattr(self._app_state, "bulk_crystal_ingestion", None) if self._app_state else None
        if ingestion and hasattr(ingestion, "run_synthesis_burst"):
            try:
                await ingestion.run_synthesis_burst(rounds=4)
                logger.info("CodeForesight: synthesis burst triggered")
            except Exception as e:
                logger.warning("CodeForesight: synthesis burst failed: %s", e)

    async def _log_forecast(self, forecast: Dict):
        if not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (type, content, created_at)
                    VALUES ('code_foresight_cycle', $1, NOW())
                """, f"C_emo={forecast['current_c_emo']:.4f} "
                     f"slope={forecast['slope']:.6f} "
                     f"growth={forecast['growth_pct']:.1f}% "
                     f"forecast_7d={forecast['forecast_7d_c_emo']:.4f} "
                     f"crystals/day={forecast['crystals_per_day']:.0f} "
                     f"stall={'YES' if forecast['stall_detected'] else 'no'}")
        except Exception as e:
            logger.debug("Forecast log failed: %s", e)

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "CodeForesightEngine",
            "running": self._running,
            "stall_count": self._stall_count,
            "last_forecast": self._last_forecast,
        }
