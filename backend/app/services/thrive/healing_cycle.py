"""Healing-cycle detector — QUANTUM-CRYSTAL-ARCH.

Composite, explainable score in [0, 1] describing how far a client has moved
from *processing* toward *consolidation / thriving*. It is the single input the
phase resolver uses for auto-promotion / demotion, and it is what the coach
sees as "why LN moved this client".

Components (each optional; weights renormalise over what exists):

| key          | source                                                           | w    |
|--------------|------------------------------------------------------------------|------|
| language     | conversation_history.user_text — forward/retrospective vs wound | 0.35 |
| coherence    | client_metrics.c_emo trend (recent window vs prior window)       | 0.20 |
| pmb          | client_metrics.shame_profile.shame_index, pmb.legacy_depth,      | 0.20 |
|              | pmb.reconsolidation_readiness                                    |      |
| cycles       | cycle_detections: healing domain (+), harm_risk/addiction (−)    | 0.10 |
| behaviour    | practice completions, habit streaks, commitments completed       | 0.15 |

Nothing here writes. Nothing here calls an LLM. Every component returns the
raw evidence it used so the transition can be audited in
client_growth_phase_history.evidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.thrive import growth_phase as gp

logger = logging.getLogger(__name__)

WEIGHTS: Dict[str, float] = {
    "language": 0.35,
    "coherence": 0.20,
    "pmb": 0.20,
    "cycles": 0.10,
    "behaviour": 0.15,
}

# Present-tense wound / processing language (the *opposite* pole of FORWARD_DECLARATION).
ACTIVE_WOUND = (
    r"\b(i can'?t (stop|get past|move on|sleep)|still (haunts|hurts|triggers)|"
    r"flashback|nightmare|panic attack|i keep (reliving|replaying)|"
    r"i feel (worthless|hopeless|numb|empty|broken)|i hate myself|"
    r"what'?s wrong with me|i'?m (drowning|falling apart|spiralling|spiraling))\b",
    r"\b(relapsed|used again|drank again|cut myself|self[- ]harm)\b",
)


@dataclass
class HealingSignal:
    score: Optional[float]
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    days: int = 14

    @property
    def available(self) -> List[str]:
        return [k for k, v in self.components.items() if v is not None]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "components": self.components,
            "evidence": self.evidence,
            "days": self.days,
        }


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _count(patterns, text: str) -> int:
    return sum(len(re.findall(p, text, re.I)) for p in patterns)


# ── language ───────────────────────────────────────────────────────────────

def score_language(user_texts: List[str]) -> Optional[Dict[str, Any]]:
    """Pure function so it is unit-testable without a DB."""
    texts = [t for t in (user_texts or []) if t and len(t.strip()) > 8]
    if len(texts) < 4:
        return None
    joined = "\n".join(texts)
    forward = _count(gp.FORWARD_DECLARATION, joined)
    retro = _count(gp.RETROSPECTIVE_WOUND, joined)
    asks = _count(gp.WORK_THROUGH_REQUEST, joined)
    wound = _count(ACTIVE_WOUND, joined)
    positive = forward + retro
    negative = wound + asks
    total = positive + negative
    if total == 0:
        # No signal either way — neutral, low confidence.
        return {"score": 0.5, "forward": 0, "retrospective": 0, "asks": 0, "wound": 0, "n": len(texts), "neutral": True}
    ratio = positive / total
    # Density bonus: consistent forward language across many turns is stronger
    # evidence than one celebratory message.
    density = _clamp(positive / max(len(texts), 1), 0, 1)
    score = _clamp(0.75 * ratio + 0.25 * density)
    return {
        "score": round(score, 4),
        "forward": forward,
        "retrospective": retro,
        "asks": asks,
        "wound": wound,
        "n": len(texts),
    }


# ── coherence ──────────────────────────────────────────────────────────────

def score_coherence(recent: List[float], prior: List[float]) -> Optional[Dict[str, Any]]:
    recent = [float(x) for x in recent if x is not None]
    if len(recent) < 3:
        return None
    r_avg = sum(recent) / len(recent)
    p_avg = (sum(prior) / len(prior)) if prior else None
    level = _clamp(r_avg)
    if p_avg is None:
        trend = 0.0
    else:
        trend = _clamp((r_avg - p_avg) * 2.0, -1, 1)  # ±0.5 c_emo swing saturates
    score = _clamp(0.7 * level + 0.3 * (0.5 + trend / 2))
    return {"score": round(score, 4), "recent_avg": round(r_avg, 4), "prior_avg": None if p_avg is None else round(p_avg, 4), "n": len(recent)}


# ── pmb ────────────────────────────────────────────────────────────────────

def score_pmb(shame_index: Optional[float], legacy_depth: Optional[float], readiness: Optional[float]) -> Optional[Dict[str, Any]]:
    parts = []
    if shame_index is not None:
        parts.append(1.0 - _clamp(float(shame_index)))
    if legacy_depth is not None:
        parts.append(1.0 - _clamp(float(legacy_depth)))
    if readiness is not None:
        parts.append(_clamp(float(readiness)))
    if not parts:
        return None
    return {
        "score": round(sum(parts) / len(parts), 4),
        "shame_index": shame_index,
        "legacy_depth": legacy_depth,
        "reconsolidation_readiness": readiness,
    }


# ── cycles ─────────────────────────────────────────────────────────────────

RISK_DOMAINS = {"harm_risk", "addiction", "porn_addiction", "criminal_intent"}


def score_cycles(detections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not detections:
        return None
    score = 0.5
    used = []
    for d in detections:
        dom = d.get("domain")
        conf = float(d.get("confidence") or 0)
        amp = float(d.get("amplitude") or 0)
        if dom == "healing":
            score += 0.35 * conf * _clamp(amp)
            used.append(dom)
        elif dom in RISK_DOMAINS and conf >= 0.5:
            score -= 0.3 * conf
            used.append(dom)
    if not used:
        return None
    return {"score": round(_clamp(score), 4), "domains": used}


# ── behaviour ──────────────────────────────────────────────────────────────

def score_behaviour(practice_completions: int, active_streak_max: int, commitments_done: int, commitments_active: int) -> Optional[Dict[str, Any]]:
    if practice_completions == 0 and active_streak_max == 0 and commitments_done + commitments_active == 0:
        return None
    s = 0.0
    s += _clamp(practice_completions / 10.0) * 0.4          # 10 completions / window saturates
    s += _clamp(active_streak_max / 7.0) * 0.3               # a week-long streak saturates
    total_c = commitments_done + commitments_active
    s += (commitments_done / total_c if total_c else 0.0) * 0.3
    return {
        "score": round(_clamp(s), 4),
        "practice_completions": practice_completions,
        "streak_max": active_streak_max,
        "commitments_done": commitments_done,
        "commitments_active": commitments_active,
    }


# ── composite ──────────────────────────────────────────────────────────────

def compose(components: Dict[str, Optional[Dict[str, Any]]], days: int = 14) -> HealingSignal:
    scores: Dict[str, Optional[float]] = {}
    evidence: Dict[str, Any] = {}
    num = 0.0
    den = 0.0
    for key, w in WEIGHTS.items():
        comp = components.get(key)
        if comp is None or comp.get("score") is None:
            scores[key] = None
            continue
        sc = float(comp["score"])
        scores[key] = sc
        evidence[key] = comp
        # A neutral, signal-free language read carries half weight.
        eff_w = w * (0.5 if comp.get("neutral") else 1.0)
        num += sc * eff_w
        den += eff_w
    score = round(num / den, 4) if den > 0 else None
    return HealingSignal(score=score, components=scores, evidence=evidence, days=days)


# ── DB-backed collector ────────────────────────────────────────────────────

async def compute_healing_signal(
    db_pool: Any,
    username: str,
    *,
    hardware_id: Optional[str] = None,
    days: int = 14,
) -> HealingSignal:
    """Collect all components for ``username`` and compose. Never raises."""
    if not db_pool or not username:
        return compose({}, days)
    ident = hardware_id or username
    comps: Dict[str, Optional[Dict[str, Any]]] = {}
    try:
        async with db_pool.acquire() as conn:
            # language — user_text only; conversation_history.user_id stores username or hw_id
            try:
                rows = await conn.fetch(
                    """
                    SELECT user_text FROM conversation_history
                    WHERE (user_id = $1 OR user_id = $2)
                      AND created_at > NOW() - ($3 || ' days')::INTERVAL
                    ORDER BY created_at DESC LIMIT 200
                    """,
                    username, ident, str(days),
                )
                comps["language"] = score_language([r["user_text"] for r in rows])
            except Exception as e:
                logger.debug("healing_cycle: language query failed: %s", e)

            # coherence — client_metrics.c_emo recent vs prior window
            try:
                rows = await conn.fetch(
                    """
                    SELECT c_emo, updated_at FROM client_metrics
                    WHERE (hardware_id = $1 OR user_id::text = $1 OR hardware_id = $2)
                      AND c_emo IS NOT NULL
                      AND updated_at > NOW() - ($3 || ' days')::INTERVAL
                    ORDER BY updated_at DESC LIMIT 400
                    """,
                    ident, username, str(days * 2),
                )
                from datetime import datetime, timedelta, timezone
                cut = datetime.now(timezone.utc) - timedelta(days=days)
                recent = [float(r["c_emo"]) for r in rows if r["updated_at"] and r["updated_at"] >= cut]
                prior = [float(r["c_emo"]) for r in rows if r["updated_at"] and r["updated_at"] < cut]
                comps["coherence"] = score_coherence(recent, prior)
            except Exception as e:
                logger.debug("healing_cycle: coherence query failed: %s", e)

            # pmb — latest row
            try:
                row = await conn.fetchrow(
                    """
                    SELECT shame_profile->>'shame_index' AS si,
                           pmb->>'legacy_depth' AS ld,
                           pmb->>'reconsolidation_readiness' AS rr
                    FROM client_metrics
                    WHERE (hardware_id = $1 OR user_id::text = $1 OR hardware_id = $2)
                    ORDER BY updated_at DESC LIMIT 1
                    """,
                    ident, username,
                )
                if row:
                    def _f(v):
                        try:
                            return None if v in (None, "") else float(v)
                        except (TypeError, ValueError):
                            return None
                    comps["pmb"] = score_pmb(_f(row["si"]), _f(row["ld"]), _f(row["rr"]))
            except Exception as e:
                logger.debug("healing_cycle: pmb query failed: %s", e)

            # cycles — active detections
            try:
                rows = await conn.fetch(
                    """
                    SELECT domain, confidence, amplitude FROM cycle_detections
                    WHERE (user_id = $1 OR user_id = $2)
                      AND (expires_at IS NULL OR expires_at > NOW())
                    """,
                    username, ident,
                )
                comps["cycles"] = score_cycles([dict(r) for r in rows])
            except Exception as e:
                logger.debug("healing_cycle: cycles query failed: %s", e)

            # behaviour — practice log + habit streaks + commitments
            try:
                pc = await conn.fetchval(
                    "SELECT COUNT(*) FROM client_practice_log WHERE username = $1 AND completed_at > NOW() - ($2 || ' days')::INTERVAL",
                    username, str(days),
                ) or 0
            except Exception:
                pc = 0
            try:
                streak = await conn.fetchval(
                    """
                    SELECT COALESCE(MAX(current_streak), 0) FROM therapeutic_habit_tracking
                    WHERE (user_id = $1 OR user_id = $2) AND status = 'active'
                    """,
                    username, ident,
                ) or 0
            except Exception:
                streak = 0
            try:
                crow = await conn.fetchrow(
                    """
                    SELECT COUNT(*) FILTER (WHERE status = 'completed' AND updated_at > NOW() - ($3 || ' days')::INTERVAL) AS done,
                           COUNT(*) FILTER (WHERE status = 'active') AS active
                    FROM nate_commitments WHERE (user_id = $1 OR user_id = $2)
                    """,
                    username, ident, str(days),
                )
                done = int(crow["done"] or 0) if crow else 0
                active = int(crow["active"] or 0) if crow else 0
            except Exception:
                done, active = 0, 0
            comps["behaviour"] = score_behaviour(int(pc), int(streak), done, active)
    except Exception as e:
        logger.warning("healing_cycle: signal collection failed for %s: %s", username, e)
    return compose(comps, days)
