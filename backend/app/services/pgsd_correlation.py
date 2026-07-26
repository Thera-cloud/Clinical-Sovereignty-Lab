"""
PGSD chat ↔ snapshot correlation (redacted).  # QUANTUM-CRYSTAL-ARCH

Gated by ENABLE_PGSD_ACCESS.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def access_enabled() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS")


def _prefix(text: str, n: int = 32) -> str:
    t = (text or "").strip().replace("\n", " ")
    return t[:n] if t else ""


async def correlate_recent_chat(
    db_pool: Any,
    hardware_id: str,
    snapshot_id: Optional[int],
    surface: str,
    window_minutes: int = 120,
) -> int:
    """
    Write redacted rows to pgsd_chat_correlation for turns in the window.
    Returns insert count. Never raises.
    """
    try:
        if not access_enabled() or db_pool is None or not hardware_id:
            return 0

        from app.services.pgsd_engine import PGSDEngine

        eng = PGSDEngine(db_pool=db_pool)
        resolved = await eng.resolve_pgsd_subject(hardware_id)
        if not resolved:
            return 0
        hw = resolved["hardware_id"]
        username = resolved.get("username") or ""
        if not username:
            return 0

        since = datetime.now(timezone.utc) - timedelta(minutes=int(window_minutes))
        inserted = 0
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT session_id, created_at, user_text
                FROM conversation_history
                WHERE user_id = $1
                  AND created_at >= $2
                  AND user_text IS NOT NULL
                  AND LENGTH(TRIM(user_text)) > 0
                ORDER BY created_at DESC
                LIMIT 50
                """,
                username,
                since,
            )
            for row in rows:
                prefix = _prefix(row.get("user_text") or "")
                if not prefix:
                    continue
                await conn.execute(
                    """
                    INSERT INTO pgsd_chat_correlation (
                        user_id, username, snapshot_id, surface,
                        session_id, turn_created_at, text_prefix
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    hw,
                    username,
                    snapshot_id,
                    surface or "auto",
                    row.get("session_id"),
                    row.get("created_at"),
                    prefix,
                )
                inserted += 1
        return inserted
    except Exception as e:
        logger.debug("correlate_recent_chat failed (non-fatal): %s", e)
        return 0


async def compute_cross_domain_series(
    db_pool: Any,
    user_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Same-mind series: group recent snapshots by trigger_source / surface.
    Persists agreement row. Never raises.
    """
    empty: Dict[str, Any] = {
        "user_id": user_id,
        "surfaces": {},
        "agreement_score": None,
        "enabled": access_enabled(),
    }
    try:
        if not access_enabled() or db_pool is None or not user_id:
            return empty

        from app.services.pgsd_engine import PGSDEngine

        eng = PGSDEngine(db_pool=db_pool)
        resolved = await eng.resolve_pgsd_subject(user_id)
        if not resolved:
            return empty
        hw = resolved["hardware_id"]
        username = resolved.get("username") or ""
        since = datetime.now(timezone.utc) - timedelta(days=int(days))

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, trigger_source, computed_at,
                       d1_valence, d2_arousal, d3_relational,
                       d4_temporal_depth, d5_integration, coherence
                FROM pgsd_snapshots
                WHERE user_id = $1 AND computed_at >= $2
                ORDER BY computed_at DESC
                LIMIT 200
                """,
                hw,
                since,
            )
            by_surface: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                surf = (r.get("trigger_source") or "unknown").strip() or "unknown"
                by_surface.setdefault(surf, []).append(
                    {
                        "snapshot_id": r["id"],
                        "computed_at": r["computed_at"].isoformat()
                        if r.get("computed_at")
                        else None,
                        "d1": r.get("d1_valence"),
                        "d2": r.get("d2_arousal"),
                        "d3": r.get("d3_relational"),
                        "d4": r.get("d4_temporal_depth"),
                        "d5": r.get("d5_integration"),
                        "coherence": r.get("coherence"),
                    }
                )

            # Mean pairwise Euclidean distance across latest pin per surface
            pins = []
            for surf, items in by_surface.items():
                if not items:
                    continue
                latest = items[0]
                pins.append(
                    (
                        surf,
                        [
                            float(latest.get("d1") or 0),
                            float(latest.get("d2") or 0),
                            float(latest.get("d3") or 0),
                            float(latest.get("d4") or 0),
                            float(latest.get("d5") or 0),
                        ],
                    )
                )
            agreement = None
            if len(pins) >= 2:
                dists = []
                for i in range(len(pins)):
                    for j in range(i + 1, len(pins)):
                        a, b = pins[i][1], pins[j][1]
                        dists.append(
                            math.sqrt(sum((a[k] - b[k]) ** 2 for k in range(5)))
                        )
                mean_d = sum(dists) / len(dists)
                # Map distance→agreement in [0,1]; ~√5 max for unit coords
                agreement = max(0.0, min(1.0, 1.0 - (mean_d / 2.5)))

            detail = {
                "surface_counts": {k: len(v) for k, v in by_surface.items()},
                "pin_surfaces": [p[0] for p in pins],
            }
            await conn.execute(
                """
                INSERT INTO pgsd_cross_domain_agreement (
                    user_id, username, window_start, window_end,
                    surfaces, agreement_score, detail_json
                ) VALUES ($1, $2, $3, NOW(), $4::jsonb, $5, $6::jsonb)
                """,
                hw,
                username or None,
                since,
                json.dumps({k: len(v) for k, v in by_surface.items()}),
                agreement,
                json.dumps(detail),
            )

            empty.update(
                {
                    "user_id": hw,
                    "username": username,
                    "surfaces": by_surface,
                    "agreement_score": agreement,
                    "detail": detail,
                    "enabled": True,
                }
            )
            return empty
    except Exception as e:
        logger.debug("compute_cross_domain_series failed: %s", e)
        return empty
