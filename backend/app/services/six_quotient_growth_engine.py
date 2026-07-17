"""
Six-Quotient Growth Engine — Lived Intelligence Measurement & Crystal Learning

Nate evaluates his own clinical performance after every interaction,
identifies which quotient dimensions were exercised, detects quality
signals and anti-patterns, and crystallizes growth lessons that get
recalled in future similar scenarios.

This is the mechanism by which Nate gets BETTER over time — not through
prompt engineering, but through lived experience crystals that reinforce
correct clinical behavior and flag persistent weaknesses.

Architecture:
    1. Per-interaction hook (heuristic, zero-latency, no LLM)
       - Tags quotient dimensions exercised
       - Detects quality signals and anti-patterns in Nate's response
       - Logs growth entry to `six_quotient_growth` table
       - Crystallizes lessons when anti-patterns detected

    2. Background synthesis (6h cycle)
       - Aggregates recent growth entries
       - Identifies persistent weaknesses
       - Creates targeted reinforcement crystals
       - Tracks score trajectory over time

Six Quotients:
    IQ — Intelligence: pattern recognition, systemic formulation, diagnostic precision
    EQ — Emotional: somatic tracking, affect attunement, paradox holding
    MQ — Moral: witnessing, ethical navigation, moral injury tolerance
    SQ — Social: parallel process detection, transference, relational dynamics
    CQ — Cultural/Creative: metaphor integrity, cultural humility, generational context
    AQ — Adversity: crisis engagement, lethality, therapeutic helplessness
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sovereign.six_quotient_growth")

# ---------------------------------------------------------------------------
# Baseline scores from March 28, 2026 v4 Assessment
# ---------------------------------------------------------------------------
BASELINE_SCORES = {
    "IQ": {"score": 34, "max": 36, "pct": 94.4, "tier": "Elite"},
    "EQ": {"score": 36, "max": 36, "pct": 100.0, "tier": "Elite"},
    "MQ": {"score": 34, "max": 36, "pct": 94.4, "tier": "Advanced"},
    "SQ": {"score": 29, "max": 36, "pct": 80.5, "tier": "Proficient"},
    "CQ": {"score": 28, "max": 36, "pct": 77.7, "tier": "Proficient"},
    "AQ": {"score": 27, "max": 36, "pct": 75.0, "tier": "Proficient"},
}
COMPOSITE_BASELINE = {"score": 188, "max": 216, "pct": 87.0, "tier": "Advanced Proficiency"}

# Tier thresholds
TIER_THRESHOLDS = {
    "Elite": 90.0,
    "Advanced": 80.0,
    "Proficient": 65.0,
    "Competent": 50.0,
    "Limited": 0.0,
}

# ---------------------------------------------------------------------------
# Quotient signal detection (in CLIENT message)
# ---------------------------------------------------------------------------
_IQ_CLIENT_SIGNALS = [
    re.compile(r"\b(pattern|cycle|always do|keep doing|every time|recurring)\b", re.I),
    re.compile(r"\b(system|family dynamic|power|hierarchy|role)\b", re.I),
    re.compile(r"\b(diagnos\w+|disorder|condition|symptoms?|medication)\b", re.I),
    re.compile(r"\b(connect\w+|relat\w+ to|linked|root cause|origin)\b", re.I),
]

_EQ_CLIENT_SIGNALS = [
    re.compile(r"\b(i feel|feeling|felt|emotions?|overwhelm\w*)\b", re.I),
    re.compile(r"\b(body|chest|stomach|throat|heart|hands|shaking|numb)\b", re.I),
    re.compile(r"\b(crying|tears|sob|weep|rage|fury|terror)\b", re.I),
    re.compile(r"\b(joy|happy|peace|calm|relief|surprise)\b", re.I),
    re.compile(r"\b(afraid|scared|anxious|panic|dread)\b", re.I),
]

_MQ_CLIENT_SIGNALS = [
    re.compile(r"\b(right thing|wrong thing|should i|moral|ethical|guilty)\b", re.I),
    re.compile(r"\b(kill\w*|murder|shot|cleared hot|collateral|drone)\b", re.I),
    re.compile(r"\b(betray|complicit|responsible|fault|blame|innocent)\b", re.I),
    re.compile(r"\b(forgive|absolut\w+|atone|redempt\w+|justice)\b", re.I),
    re.compile(r"\b(dying|terminal|end.of.life|hospice|euthan\w*)\b", re.I),
]

_SQ_CLIENT_SIGNALS = [
    re.compile(r"\b(you need to|i need you to|don't ask me|just give me)\b", re.I),
    re.compile(r"\b(actionable|practical|strategies|solutions|fix)\b", re.I),
    re.compile(r"\b(controlling|manipulat\w+|power struggle|dominating)\b", re.I),
    re.compile(r"\b(therapist|counselor|previous therapist|you remind me)\b", re.I),
    re.compile(r"\b(stop asking|that's not helpful|can we focus|not about feelings)\b", re.I),
]

_CQ_CLIENT_SIGNALS = [
    re.compile(r"\b(culture|tradition|ancestors|elders|community|tribe)\b", re.I),
    re.compile(r"\b(metaphor|image|dream|vision|story|like a|as if)\b", re.I),
    re.compile(r"\b(generational|grandfather|grandmother|heritage|legacy)\b", re.I),
    re.compile(r"\b(spiritual|god|pray|faith|church|mosque|temple|ritual)\b", re.I),
    re.compile(r"\b(race|racism|identity|queer|lgbtq|immigrant|refugee)\b", re.I),
]

_AQ_CLIENT_SIGNALS = [
    re.compile(r"\b(suicide|kill myself|end it|die|not worth|better off dead)\b", re.I),
    re.compile(r"\b(hurt someone|kill (him|her|them)|shoot|stab|violence)\b", re.I),
    re.compile(r"\b(no point|give up|can't go on|nothing left|hopeless)\b", re.I),
    re.compile(r"\b(unsolvable|no solution|can't fix|nothing works|impossible)\b", re.I),
    re.compile(r"\b(depersonaliz\w+|tachycardia|cortisol|amygdala|precipitating)\b", re.I),
    re.compile(r"\b(textbook|from a research|logically i understand)\b", re.I),
]

# ---------------------------------------------------------------------------
# Quality signals in NATE's response (positive = good clinical work)
# ---------------------------------------------------------------------------
_QUALITY_POSITIVE = {
    "somatic_tracking": re.compile(
        r"\b(body|chest|stomach|throat|hands|breathing|heart rate|pulse|tension)\b", re.I
    ),
    "witness_language": re.compile(
        r"\b(witness|carrying|weight|not look away|stay.{0,15}here|not going anywhere)\b", re.I
    ),
    "mirror_naming": re.compile(
        r"\b(right now.{0,30}you are|doing to me|in this room|between us|dynamic|power struggle)\b", re.I
    ),
    "metaphor_entry": re.compile(
        r"\b(tell me more about|stay in|what happens to|if you could reach)\b", re.I
    ),
    "helplessness_presence": re.compile(
        r"\b(i don't have anything|no technique|no reframe|no words|sit here with you)\b", re.I
    ),
    "specificity": re.compile(
        r"\b(you said|you mentioned|you described|the moment when|that hour|that room)\b", re.I
    ),
    "client_words_echo": re.compile(
        r'"[^"]{10,}"', re.I  # quoting client's own words back
    ),
}

# ---------------------------------------------------------------------------
# Anti-patterns in NATE's response (negative = clinical weakness)
# ---------------------------------------------------------------------------
_QUALITY_ANTIPATTERN = {
    "banned_word": re.compile(
        r"\b(liminal|threshold|holding space|sit with that|honor your journey|"
        r"in-between space|tender|sacred ground|aching|tender place)\b", re.I
    ),
    "metaphor_decode": re.compile(
        r"\b(represents?|symboliz\w+|stands for|is (really|actually) about|inner world)\b", re.I
    ),
    "solution_offering": re.compile(
        r"\b(try (this|to)|consider|breathing exercise|grounding technique|coping strateg\w+|"
        r"have you tried|one thing you could|let me suggest)\b", re.I
    ),
    "accommodation": re.compile(
        r"\b(absolutely|of course|let's focus on|i can give you|actionable steps|"
        r"here are some|practical approach|let me help you with)\b", re.I
    ),
    "intellectualization_trap": re.compile(
        r"\b(that's a (great|excellent|interesting) (observation|insight|analysis)|"
        r"from a clinical perspective|diagnostically)\b", re.I
    ),
    "generic_validation": re.compile(
        r"\b(i hear you|that must be|that sounds|i can imagine|how (brave|courageous))\b", re.I
    ),
}

GROWTH_CYCLE_SECONDS = 21600  # 6 hours


class SixQuotientGrowthEngine:
    """Background agent + per-interaction hook for quotient self-measurement."""

    def __init__(self, db_pool):
        self.db_pool = db_pool
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._growth_loop())
        logger.info("Six-Quotient Growth Engine started — lived wisdom measurement active")

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Six-Quotient Growth Engine stopped")

    async def _growth_loop(self):
        """Background synthesis: aggregate growth entries, identify weaknesses, crystallize."""
        await asyncio.sleep(600)  # 10 min startup delay
        while self._running:
            try:
                await self._synthesize_growth()
            except Exception as e:
                logger.error("Growth synthesis error: %s", e)
            await asyncio.sleep(GROWTH_CYCLE_SECONDS)

    # ------------------------------------------------------------------
    # Per-interaction hook (called after every AI response)
    # ------------------------------------------------------------------
    async def assess_interaction(
        self,
        user_text: str,
        nate_response: str,
        uid: str,
        provider: str = "",
    ) -> None:
        """
        Heuristic self-assessment after each interaction.
        Zero-latency, no LLM call. Tags quotient dimensions,
        detects quality signals and anti-patterns, logs growth entry,
        and crystallizes lessons when anti-patterns are detected.
        """
        if not self.db_pool or not user_text or not nate_response:
            return

        quotients_exercised = self._detect_quotient_dimensions(user_text)
        if not quotients_exercised:
            return

        quality_positive, quality_negative = self._assess_response_quality(
            nate_response, quotients_exercised
        )

        growth_score = len(quality_positive) - (len(quality_negative) * 2)

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO six_quotient_growth
                       (user_id, quotients_exercised, quality_positive,
                        quality_negative, growth_score, provider,
                        user_snippet, nate_snippet)
                     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    uid,
                    quotients_exercised,
                    quality_positive,
                    quality_negative,
                    growth_score,
                    provider,
                    user_text[:300],
                    nate_response[:300],
                )
        except Exception as e:
            logger.warning("Growth log failed: %s", e)

        if quality_negative:
            asyncio.create_task(
                self._crystallize_lesson(uid, user_text, nate_response,
                                         quotients_exercised, quality_negative)
            )

    # ------------------------------------------------------------------
    # Signal detection
    # ------------------------------------------------------------------
    def _detect_quotient_dimensions(self, user_text: str) -> List[str]:
        """Detect which quotient dimensions the client message activates."""
        dimensions = []
        signal_map = {
            "IQ": _IQ_CLIENT_SIGNALS,
            "EQ": _EQ_CLIENT_SIGNALS,
            "MQ": _MQ_CLIENT_SIGNALS,
            "SQ": _SQ_CLIENT_SIGNALS,
            "CQ": _CQ_CLIENT_SIGNALS,
            "AQ": _AQ_CLIENT_SIGNALS,
        }
        for quotient, patterns in signal_map.items():
            hits = sum(1 for p in patterns if p.search(user_text))
            if hits >= 2:
                dimensions.append(quotient)
        return dimensions

    def _assess_response_quality(
        self, nate_response: str, quotients: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Assess Nate's response quality: positive signals and anti-patterns."""
        positives = []
        for name, pattern in _QUALITY_POSITIVE.items():
            if pattern.search(nate_response):
                positives.append(name)

        negatives = []
        for name, pattern in _QUALITY_ANTIPATTERN.items():
            if pattern.search(nate_response):
                negatives.append(name)

        return positives, negatives

    # ------------------------------------------------------------------
    # Crystal learning from anti-patterns
    # ------------------------------------------------------------------
    async def _crystallize_lesson(
        self,
        uid: str,
        user_text: str,
        nate_response: str,
        quotients: List[str],
        anti_patterns: List[str],
    ) -> None:
        """Create a growth crystal encoding what went wrong and the correction."""
        if not self.db_pool:
            return

        lesson_parts = []
        for ap in anti_patterns:
            correction = _ANTIPATTERN_CORRECTIONS.get(ap)
            if correction:
                lesson_parts.append(correction)

        if not lesson_parts:
            return

        q_label = "/".join(quotients)
        crystal_text = (
            f"GROWTH LESSON ({q_label}): In a conversation where the client "
            f"presented {q_label}-level material, the following clinical errors "
            f"were detected: {', '.join(anti_patterns)}. "
            + " ".join(lesson_parts)
        )

        content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()

        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO nate_intelligence_crystals
                       (crystal_text, domain, scope, topics, source_count,
                        generation, confidence, content_hash, origin_surface,
                        metadata)
                     VALUES ($1, 'clinical', 'global', $2, 1, 0, 0.70, $3,
                             'growth_engine',
                             $4::jsonb)
                     ON CONFLICT (content_hash) DO UPDATE
                       SET confidence = LEAST(nate_intelligence_crystals.confidence + 0.05, 0.95),
                           recall_count = nate_intelligence_crystals.recall_count + 1,
                           updated_at = NOW()""",
                    crystal_text,
                    quotients,
                    content_hash,
                    '{"growth_crystal": true, "quotients": '
                    + str(quotients).replace("'", '"')
                    + ', "anti_patterns": '
                    + str(anti_patterns).replace("'", '"')
                    + "}",
                )
                logger.info(
                    "Growth crystal forged: %s anti-patterns in %s context",
                    anti_patterns, q_label,
                )
                # QUANTUM-CRYSTAL-ARCH: Vectorize embedding
                try:
                    from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                    if is_vectorize_configured():
                        await index_wisdom(
                            user_id="nate_crystal",
                            wisdom_id=f"crystal_{content_hash[:16]}",
                            insight_type="growth_engine_clinical",
                            content=crystal_text,
                            source="growth_engine",
                            domain="clinical",
                        )
                except Exception as _v:
                    logger.debug("Growth engine: vectorize non-fatal: %s", _v)
        except Exception as e:
            logger.warning("Growth crystallization failed: %s", e)

    # ------------------------------------------------------------------
    # Background synthesis: identify persistent weaknesses
    # ------------------------------------------------------------------
    async def _synthesize_growth(self) -> None:
        """6h cycle: aggregate growth data, identify persistent weaknesses, crystallize."""
        if not self.db_pool:
            return

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT quotients_exercised, quality_positive, quality_negative,
                              growth_score, created_at
                       FROM six_quotient_growth
                       WHERE created_at > NOW() - INTERVAL '24 hours'
                       ORDER BY created_at DESC
                       LIMIT 500"""
                )

                if len(rows) < 5:
                    return

                quotient_stats: Dict[str, Dict] = {
                    q: {"exercises": 0, "positive": 0, "negative": 0, "anti_patterns": {}}
                    for q in ["IQ", "EQ", "MQ", "SQ", "CQ", "AQ"]
                }

                for row in rows:
                    for q in (row["quotients_exercised"] or []):
                        if q in quotient_stats:
                            quotient_stats[q]["exercises"] += 1
                            quotient_stats[q]["positive"] += len(row["quality_positive"] or [])
                            quotient_stats[q]["negative"] += len(row["quality_negative"] or [])
                            for ap in (row["quality_negative"] or []):
                                quotient_stats[q]["anti_patterns"][ap] = (
                                    quotient_stats[q]["anti_patterns"].get(ap, 0) + 1
                                )

                weakest = sorted(
                    quotient_stats.items(),
                    key=lambda x: x[1]["negative"],
                    reverse=True,
                )

                for quotient, stats in weakest[:3]:
                    if stats["negative"] < 3:
                        continue

                    top_anti = sorted(
                        stats["anti_patterns"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )[:3]

                    if not top_anti:
                        continue

                    reinforcement_parts = []
                    for ap_name, count in top_anti:
                        correction = _ANTIPATTERN_CORRECTIONS.get(ap_name, "")
                        if correction:
                            reinforcement_parts.append(
                                f"{ap_name} ({count}x in 24h): {correction}"
                            )

                    if not reinforcement_parts:
                        continue

                    crystal_text = (
                        f"PERSISTENT WEAKNESS — {quotient} QUOTIENT: "
                        f"Over the last 24 hours across {stats['exercises']} "
                        f"interactions, {stats['negative']} clinical anti-patterns "
                        f"were detected. Most frequent: "
                        + " | ".join(reinforcement_parts)
                    )

                    content_hash = hashlib.sha256(
                        f"persistent_{quotient}_{datetime.now(timezone.utc).strftime('%Y%m%d')}".encode()
                    ).hexdigest()

                    await conn.execute(
                        """INSERT INTO nate_intelligence_crystals
                           (crystal_text, domain, scope, topics, source_count,
                            generation, confidence, content_hash, origin_surface,
                            metadata)
                         VALUES ($1, 'clinical', 'global', $2, $3, 0, 0.80, $4,
                                 'growth_engine',
                                 '{"growth_crystal": true, "persistent_weakness": true}'::jsonb)
                         ON CONFLICT (content_hash) DO UPDATE
                           SET crystal_text = EXCLUDED.crystal_text,
                               confidence = LEAST(nate_intelligence_crystals.confidence + 0.05, 0.95),
                               updated_at = NOW()""",
                        crystal_text,
                        [quotient],
                        stats["exercises"],
                        content_hash,
                    )

                    logger.info(
                        "Persistent weakness crystal: %s (%d anti-patterns in 24h)",
                        quotient, stats["negative"],
                    )
                    # QUANTUM-CRYSTAL-ARCH: Vectorize persistent weakness crystal
                    try:
                        from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                        if is_vectorize_configured():
                            await index_wisdom(
                                user_id="nate_crystal",
                                wisdom_id=f"crystal_{content_hash[:16]}",
                                insight_type="growth_persistent_weakness",
                                content=crystal_text,
                                source="growth_engine",
                                domain="clinical",
                            )
                    except Exception as _v:
                        logger.debug("Growth persistent: vectorize non-fatal: %s", _v)

                # Store daily quotient snapshot
                await self._store_quotient_snapshot(conn, quotient_stats, len(rows))

        except Exception as e:
            logger.error("Growth synthesis failed: %s", e)

    async def _store_quotient_snapshot(
        self, conn, stats: Dict, total_interactions: int
    ) -> None:
        """Store a daily snapshot of quotient health for trajectory tracking."""
        import json
        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "total_interactions": total_interactions,
            "quotients": {},
        }
        for q, data in stats.items():
            exercises = max(data["exercises"], 1)
            quality_ratio = data["positive"] / max(data["positive"] + data["negative"], 1)
            snapshot["quotients"][q] = {
                "exercises": data["exercises"],
                "positive_signals": data["positive"],
                "negative_signals": data["negative"],
                "quality_ratio": round(quality_ratio, 3),
                "top_anti_patterns": sorted(
                    data["anti_patterns"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:3],
                "baseline_pct": BASELINE_SCORES[q]["pct"],
            }

        try:
            await conn.execute(
                """INSERT INTO six_quotient_growth
                   (user_id, quotients_exercised, quality_positive,
                    quality_negative, growth_score, provider,
                    user_snippet, nate_snippet)
                 VALUES ('__system_snapshot__', $1, $2, $3, $4,
                         'growth_engine', $5, '')""",
                list(stats.keys()),
                [f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H')}"],
                [],
                total_interactions,
                json.dumps(snapshot)[:300],
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Battery feed — only after external scores confirm weaknesses
    # ------------------------------------------------------------------
    async def ingest_battery_findings(
        self, run_id: str, analysis: Dict
    ) -> Dict:
        """
        Crystallize lessons from a scored battery run.
        Confidence capped at 0.50; tagged source=six_quotient_battery.
        """
        if not self.db_pool or not analysis or not analysis.get("ok"):
            return {"forged": 0}
        quotients = analysis.get("quotients") or {}
        forged = 0
        for q, data in quotients.items():
            if data.get("risk") not in ("RED", "YELLOW"):
                continue
            if data.get("delta_pct", 0) >= 0 and data.get("risk") != "RED":
                continue
            crystal_text = (
                f"BATTERY-VALIDATED WEAKNESS — {q} QUOTIENT (run {run_id}): "
                f"External score {data.get('score')}/{data.get('max')} "
                f"({data.get('pct')}%) vs baseline {data.get('baseline_pct')}% "
                f"(delta {data.get('delta_pct')} pts%). "
                f"Prioritize clinical reinforcement for {q} scenarios. "
                f"Do not self-score; this lesson is externally confirmed."
            )
            content_hash = hashlib.sha256(
                f"battery_{q}_{run_id}".encode()
            ).hexdigest()
            try:
                import json as _json
                meta = _json.dumps({
                    "growth_crystal": True,
                    "source": "six_quotient_battery",
                    "run_id": str(run_id),
                    "quotient": q,
                    "risk": data.get("risk"),
                })
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO nate_intelligence_crystals
                           (crystal_text, domain, scope, topics, source_count,
                            generation, confidence, content_hash, origin_surface,
                            metadata)
                         VALUES ($1, 'clinical', 'global', $2, 2, 0, 0.45, $3,
                                 'six_quotient_battery', $4::jsonb)
                         ON CONFLICT (content_hash) DO UPDATE
                           SET confidence = LEAST(
                                 nate_intelligence_crystals.confidence + 0.02, 0.50),
                               updated_at = NOW()""",
                        crystal_text,
                        [q],
                        content_hash,
                        meta,
                    )
                forged += 1
            except Exception as e:
                logger.warning("Battery crystal forge failed for %s: %s", q, e)
        return {"forged": forged, "run_id": str(run_id)}

    # ------------------------------------------------------------------
    # Public: get current growth status (for admin/API)
    # ------------------------------------------------------------------
    async def get_growth_status(self) -> Dict:
        """Return current quotient health and trajectory."""
        if not self.db_pool:
            return {"baseline": BASELINE_SCORES, "recent": {}}

        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """SELECT quotients_exercised, quality_positive,
                              quality_negative, growth_score
                       FROM six_quotient_growth
                       WHERE created_at > NOW() - INTERVAL '7 days'
                         AND user_id != '__system_snapshot__'
                       ORDER BY created_at DESC
                       LIMIT 1000"""
                )

                quotient_health = {}
                for q in ["IQ", "EQ", "MQ", "SQ", "CQ", "AQ"]:
                    exercises = sum(
                        1 for r in rows if q in (r["quotients_exercised"] or [])
                    )
                    positives = sum(
                        len(r["quality_positive"] or [])
                        for r in rows if q in (r["quotients_exercised"] or [])
                    )
                    negatives = sum(
                        len(r["quality_negative"] or [])
                        for r in rows if q in (r["quotients_exercised"] or [])
                    )
                    quality_ratio = positives / max(positives + negatives, 1)
                    quotient_health[q] = {
                        "baseline": BASELINE_SCORES[q],
                        "exercises_7d": exercises,
                        "positive_signals_7d": positives,
                        "negative_signals_7d": negatives,
                        "quality_ratio_7d": round(quality_ratio, 3),
                        "growth_trajectory": (
                            "improving" if quality_ratio > 0.7
                            else "stable" if quality_ratio > 0.4
                            else "needs_attention"
                        ),
                    }

                return {
                    "baseline": BASELINE_SCORES,
                    "composite_baseline": COMPOSITE_BASELINE,
                    "recent_7d": quotient_health,
                    "total_interactions_7d": len(rows),
                }
        except Exception as e:
            logger.warning("Growth status query failed: %s", e)
            return {"baseline": BASELINE_SCORES, "error": str(e)}


# ---------------------------------------------------------------------------
# Anti-pattern corrections: what Nate should have done instead
# ---------------------------------------------------------------------------
_ANTIPATTERN_CORRECTIONS = {
    "banned_word": (
        "CORRECTION: You used a banned word (liminal, threshold, holding space, "
        "tender, sacred ground, aching, or similar). Replace with the client's "
        "OWN words or a concrete sensory description of what is actually happening. "
        "WRONG: 'You are standing at this aching threshold of grief.' "
        "RIGHT: 'You are sitting in a room with a mother who no longer knows your name.'"
    ),
    "metaphor_decode": (
        "CORRECTION: You decoded the client's metaphor into clinical language. "
        "NEVER say 'represents,' 'symbolizes,' or 'is really about.' Enter the "
        "image and explore WITHIN it: 'Tell me more about the water. If you could "
        "reach the child in the basement, what would happen to the water?'"
    ),
    "solution_offering": (
        "CORRECTION: You offered solutions to a problem that may be unsolvable. "
        "When a client faces irreversible loss, terminal diagnosis, or moral injury, "
        "do NOT offer coping strategies, breathing exercises, or reframes. Instead: "
        "'I don't have anything that fixes this. What I can do is sit here with you "
        "inside it and not look away.'"
    ),
    "accommodation": (
        "CORRECTION: You accommodated the client's demand for control instead of "
        "naming the parallel process. When a client dictates session rules, they are "
        "recreating a power dynamic. Your response must BE the mirror: 'Right now, "
        "you are deciding what is allowed in this room. That is the EXACT dynamic "
        "you described with your partner.'"
    ),
    "intellectualization_trap": (
        "CORRECTION: You validated the client's intellectual analysis instead of "
        "interrupting their dissociative defense. Use a somatic interrupt: 'Stop. "
        "Put the clipboard down. You are narrating your own crisis from behind a "
        "wall of language. What is happening in your chest right now?'"
    ),
    "generic_validation": (
        "CORRECTION: You used generic validation ('I hear you,' 'that must be') "
        "instead of specific clinical observation. Replace with the client's OWN "
        "words and concrete sensory details of what is actually happening in the room."
    ),
}
