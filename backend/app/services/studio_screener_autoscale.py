"""S5 screener autoscale hint — request-response, no ORANGE install. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

from typing import Any, Dict


def scale_hint(waiting: int) -> Dict[str, Any]:
    n = max(0, int(waiting or 0))
    workers = 1
    if n >= 20:
        workers = 4
    elif n >= 10:
        workers = 3
    elif n >= 4:
        workers = 2
    return {"ok": True, "waiting": n, "workers": workers, "autoscale": True}


async def waiting_count(db_pool, show_id: str) -> int:
    if not db_pool or not show_id:
        return 0
    async with db_pool.acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT COUNT(*) FROM show_callers
            WHERE show_id = $1::uuid AND risk_flag = FALSE AND opted_in = TRUE
              AND created_at > NOW() - INTERVAL '2 hours'
            """,
            show_id,
        )
    return int(n or 0)
