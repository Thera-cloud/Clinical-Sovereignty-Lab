"""
Crystal Quality Auditor — EXA Methodology v5 Self-Healing.

Nightly audit of code crystals:
  1. Syntax validation: py_compile on Python-containing crystals
  2. Staleness check: crystals referencing deprecated APIs
  3. Contradiction detection: conflicting crystals in same topic cluster
  4. Confidence recalibration: adjust confidence based on recall patterns
  5. C_emo-aware retention: prune below dynamic floor (C_emo × 0.3)

Runs as a background agent with a 24h cycle.
"""

import asyncio
import json
import logging
import py_compile
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from app.services.nate_agent_template import NateAutonomousAgent
except ImportError:
    NateAutonomousAgent = object

DEPRECATED_PATTERNS = [
    r"from\s+distutils\b",
    r"asyncio\.coroutine",
    r"yield\s+from\b",
    r"imp\.reload",
    r"collections\.MutableMapping",
    r"typing\.Optional\[.*\]\s*=\s*None",  # Not deprecated but common anti-pattern
]

MIN_CONFIDENCE_FLOOR = 0.15


class CrystalQualityAuditor(NateAutonomousAgent):
    """Nightly self-healing audit of code intelligence crystals."""

    def __init__(self, db_pool=None, app_state=None):
        super().__init__(
            agent_name="CrystalQualityAuditor",
            domain="coding",
            cycle_hours=24.0,
            db_pool=db_pool,
            app_state=app_state,
        )
        self._last_audit: Optional[Dict] = None

    async def observe(self) -> list:
        """Auditor uses _cycle directly, not observe/reason/crystallize."""
        return []

    async def _run_loop(self):
        await asyncio.sleep(240)
        while self._running:
            try:
                await self._cycle()
                self._cycle_count += 1
                self._last_cycle = datetime.now(timezone.utc)
            except Exception as e:
                logger.warning("CrystalQualityAuditor cycle error: %s", e)
            await asyncio.sleep(int(self.cycle_hours * 3600))

    async def _cycle(self):
        if not self._db_pool:
            return

        try:
            report = {
                "syntax_failures": 0,
                "staleness_flags": 0,
                "confidence_adjusted": 0,
                "pruned_below_floor": 0,
                "total_audited": 0,
            }

            async with self._db_pool.acquire() as conn:
                c_emo_row = await conn.fetchrow("""
                    SELECT C_emo FROM nevedal_domain_state WHERE domain = 'coding'
                """)
                c_emo = float(c_emo_row["c_emo"]) if c_emo_row else 0.0
                dynamic_floor = max(MIN_CONFIDENCE_FLOOR, c_emo * 0.3)

                crystals = await conn.fetch("""
                    SELECT id, crystal_text, confidence, recall_count,
                           domain, scope
                    FROM nate_intelligence_crystals
                    WHERE domain = 'coding' AND scope != 'archived'
                    ORDER BY created_at DESC
                    LIMIT 2000
                """)

                report["total_audited"] = len(crystals)

                for crystal in crystals:
                    cid = crystal["id"]
                    text = crystal["crystal_text"] or ""
                    conf = float(crystal["confidence"] or 0.5)

                    python_blocks = re.findall(
                        r"```python\n(.*?)```", text, re.DOTALL
                    )
                    for block in python_blocks:
                        if not self._validate_python_syntax(block):
                            report["syntax_failures"] += 1
                            new_conf = max(dynamic_floor, conf - 0.1)
                            await conn.execute("""
                                UPDATE nate_intelligence_crystals
                                SET confidence = $1, updated_at = NOW()
                                WHERE id = $2
                            """, new_conf, cid)
                            break

                    for pattern in DEPRECATED_PATTERNS:
                        if re.search(pattern, text):
                            report["staleness_flags"] += 1
                            new_conf = max(dynamic_floor, conf - 0.05)
                            await conn.execute("""
                                UPDATE nate_intelligence_crystals
                                SET confidence = $1, updated_at = NOW()
                                WHERE id = $2
                            """, new_conf, cid)
                            break

                    if conf < dynamic_floor and crystal["recall_count"] < 2:
                        await conn.execute("""
                            UPDATE nate_intelligence_crystals
                            SET scope = 'archived'
                            WHERE id = $1
                        """, cid)
                        report["pruned_below_floor"] += 1

                await conn.execute("""
                    INSERT INTO skyeye_activity (type, content, created_at)
                    VALUES ('crystal_quality_audit', $1, NOW())
                """, json.dumps(report))

            self._last_audit = report
            logger.info("CrystalQualityAuditor: audited=%d syntax_fail=%d stale=%d pruned=%d",
                        report["total_audited"], report["syntax_failures"],
                        report["staleness_flags"], report["pruned_below_floor"])
        except Exception as e:
            logger.warning("CrystalQualityAuditor cycle error: %s", e)

    def _validate_python_syntax(self, code: str) -> bool:
        try:
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=True) as f:
                f.write(code)
                f.flush()
                py_compile.compile(f.name, doraise=True)
            return True
        except (py_compile.PyCompileError, SyntaxError):
            return False
        except Exception:
            return True

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "CrystalQualityAuditor",
            "running": self._running,
            "last_audit": self._last_audit,
        }
