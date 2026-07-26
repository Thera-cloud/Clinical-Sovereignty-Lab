"""
PGSD discernment scoring — past/present/future claim alignment.  # QUANTUM-CRYSTAL-ARCH

Gated by ENABLE_PGSD_ACCESS (requires PGSD_ENABLED).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PAST_RE = re.compile(
    r"\b(was|were|had|did|used to|always|never|childhood|growing up|"
    r"when I was|back then|my (?:mother|father|parent))\b",
    re.I,
)
_FUTURE_RE = re.compile(
    r"\b(will|going to|gonna|tomorrow|next week|next month|soon|"
    r"I plan|I hope|I want to|what if|when I)\b",
    re.I,
)
_PRESENT_RE = re.compile(
    r"\b(am|is|are|feel|feeling|right now|today|currently|this moment)\b",
    re.I,
)


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def access_enabled() -> bool:
    return _env_true("PGSD_ENABLED") and _env_true("ENABLE_PGSD_ACCESS")


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _score_axis(
    claim_count: int,
    aligned: int,
    trajectory: Optional[float],
) -> float:
    if claim_count <= 0:
        return 0.5
    ratio = aligned / max(claim_count, 1)
    traj = float(trajectory or 0.0)
    # trajectory direction: negative d4 = past-heavy, positive = future-heavy
    return _clamp(0.35 + 0.45 * ratio + 0.2 * (0.5 + 0.5 * traj))


class PGSDDiscernmentScorer:
    def __init__(self, db_pool: Any = None):
        self.db_pool = db_pool

    async def score_user(self, user_id: str) -> Dict[str, Any]:
        """
        Heuristic discernment from snapshots, chat correlation, conversation_history.
        Persists to pgsd_discernment_scores. Never raises.
        """
        empty = {
            "user_id": user_id,
            "score_past": 0.5,
            "score_present": 0.5,
            "score_future": 0.5,
            "score_composite": 0.5,
            "claim_count": 0,
            "enabled": access_enabled(),
        }
        try:
            if not access_enabled() or not self.db_pool or not user_id:
                return empty

            from app.services.pgsd_engine import PGSDEngine

            eng = PGSDEngine(db_pool=self.db_pool)
            resolved = await eng.resolve_pgsd_subject(user_id)
            if not resolved:
                return empty
            hw = resolved["hardware_id"]
            username = resolved.get("username") or ""

            async with self.db_pool.acquire() as conn:
                snap = await conn.fetchrow(
                    """
                    SELECT id, d4_temporal_depth, d1_valence, coherence
                    FROM pgsd_snapshots
                    WHERE user_id = $1
                    ORDER BY computed_at DESC
                    LIMIT 1
                    """,
                    hw,
                )
                corr_rows = await conn.fetch(
                    """
                    SELECT text_prefix, turn_created_at
                    FROM pgsd_chat_correlation
                    WHERE user_id = $1
                    ORDER BY created_at DESC
                    LIMIT 40
                    """,
                    hw,
                )
                texts: List[str] = []
                for r in corr_rows:
                    p = r.get("text_prefix")
                    if p:
                        texts.append(str(p))
                if username:
                    hist = await conn.fetch(
                        """
                        SELECT user_text
                        FROM conversation_history
                        WHERE user_id = $1
                          AND user_text IS NOT NULL
                          AND LENGTH(user_text) > 8
                        ORDER BY created_at DESC
                        LIMIT 25
                        """,
                        username,
                    )
                    for r in hist:
                        t = r.get("user_text")
                        if t:
                            texts.append(str(t)[:200])

            past_c = present_c = future_c = 0
            past_a = present_a = future_a = 0
            d4 = float((snap or {}).get("d4_temporal_depth") or 0.0)
            traj = max(-1.0, min(1.0, d4))

            for text in texts:
                tl = text.lower()
                if _PAST_RE.search(tl):
                    past_c += 1
                    if traj < 0:
                        past_a += 1
                if _PRESENT_RE.search(tl):
                    present_c += 1
                    if abs(traj) < 0.35:
                        present_a += 1
                if _FUTURE_RE.search(tl):
                    future_c += 1
                    if traj > 0:
                        future_a += 1

            claim_count = past_c + present_c + future_c
            score_past = _score_axis(past_c, past_a, -abs(traj) if traj <= 0 else 0.0)
            score_present = _score_axis(present_c, present_a, 0.0)
            score_future = _score_axis(future_c, future_a, abs(traj) if traj >= 0 else 0.0)
            score_composite = round(
                (score_past + score_present + score_future) / 3.0, 4
            )

            evidence = {
                "past_claims": past_c,
                "present_claims": present_c,
                "future_claims": future_c,
                "d4_temporal_depth": d4,
                "text_samples": len(texts),
            }

            prior = None
            async with self.db_pool.acquire() as conn:
                prior = await conn.fetchrow(
                    """
                    SELECT score_composite FROM pgsd_discernment_scores
                    WHERE user_id = $1
                    ORDER BY computed_at DESC LIMIT 1
                    """,
                    hw,
                )
                await conn.execute(
                    """
                    INSERT INTO pgsd_discernment_scores (
                        user_id, username,
                        score_past, score_present, score_future,
                        score_composite, claim_count, evidence_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                    """,
                    hw,
                    username or None,
                    score_past,
                    score_present,
                    score_future,
                    score_composite,
                    claim_count,
                    json.dumps(evidence),
                )

            # QUANTUM-CRYSTAL-ARCH — Dual-COO signal on discernment drop (ops only)
            try:
                prior_c = float((prior or {}).get("score_composite") or 0.5)
                if prior and score_composite < prior_c - 0.15:
                    from app.websocket.cli_dual_coo import RISK_YELLOW, enqueue_ceo

                    enqueue_ceo(
                        risk=RISK_YELLOW,
                        title=f"PGSD discernment drop: {username or hw}",
                        detail=(
                            f"composite {prior_c:.3f} → {score_composite:.3f} "
                            f"(claims={claim_count})"
                        ),
                        origin="pgsd",
                        task_id=f"pgsd-discern-{hw}",
                        payload={"user_id": hw, "score_composite": score_composite},
                    )
            except Exception:
                pass

            return {
                "user_id": hw,
                "username": username,
                "score_past": score_past,
                "score_present": score_present,
                "score_future": score_future,
                "score_composite": score_composite,
                "claim_count": claim_count,
                "evidence": evidence,
                "enabled": True,
            }
        except Exception as e:
            logger.debug("PGSDDiscernmentScorer.score_user failed: %s", e)
            return empty
