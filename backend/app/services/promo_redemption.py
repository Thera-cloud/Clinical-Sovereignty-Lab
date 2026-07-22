"""Promo / discount redemption counters for Sovereign Command dashboards."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_PROMO_SOURCES = frozenset({"promotional_specials", "school_codes", "corporate_sponsors"})


def _normalize_code(promo_code: str) -> str:
    return (promo_code or "").strip().upper()[:40]


async def record_promo_redemption(
    db: Any,
    *,
    promo_code: str,
    source: str = "promotional_specials",
) -> bool:
    """Increment redemption counter after a successful paid checkout.

    Only increases counts (never decrements). Respects max_redemptions caps.
    Returns True when a row was updated.
    """
    cleaned = _normalize_code(promo_code)
    if not cleaned:
        return False

    src = (source or "promotional_specials").strip()
    if src not in _PROMO_SOURCES:
        logger.warning("Promo redemption skipped: unknown source %s", src)
        return False

    sql_by_source = {
        "promotional_specials": (
            "UPDATE promotional_specials "
            "SET current_redemptions = current_redemptions + 1 "
            "WHERE promo_code = $1 "
            "AND (max_redemptions IS NULL OR current_redemptions < max_redemptions)"
        ),
        "school_codes": (
            "UPDATE school_codes "
            "SET current_students = current_students + 1 "
            "WHERE school_code = $1 "
            "AND (max_students IS NULL OR current_students < max_students)"
        ),
        "corporate_sponsors": (
            "UPDATE corporate_sponsors "
            "SET current_employees = current_employees + 1 "
            "WHERE sponsor_code = $1 "
            "AND (max_employees IS NULL OR current_employees < max_employees)"
        ),
    }

    try:
        status = await db.execute(sql_by_source[src], cleaned)
    except Exception as exc:
        logger.warning(
            "Promo redemption update failed (%s/%s): %s",
            src,
            cleaned,
            exc,
        )
        return False

    if isinstance(status, str):
        return status.endswith("1")
    return bool(status)
