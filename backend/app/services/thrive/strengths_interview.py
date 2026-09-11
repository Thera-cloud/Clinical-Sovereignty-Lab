"""LN-led in-house strengths interview + phase-aware thrive memory — QUANTUM-CRYSTAL-ARCH.

Free, in-conversation replacement for the VIA survey (decision 4: in-house, no
licence). Little Nate asks one question at a time over several turns; every
first-person strengths disclosure the client makes is observed and tallied.
When enough distinct strengths recur, the top five are saved as the client's
signature strengths (``client_strengths.method = 'ln_interview'``).

Also provides the phase-aware crystal layer for coaching phases:
``thrive_memory`` recall (thrive/coaching-domain user crystals) and
``crystallize_thrive`` (forge goal / practice / strength harvests into the
``thrive`` crystal domain so they survive the 90-day decay via recall).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services._identity_resolver import resolve_username

logger = logging.getLogger(__name__)

# ── in-house 24 (VIA-shaped, free) ─────────────────────────────────────────

STRENGTHS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "curiosity": ("Curiosity", ("curious", "curiosity", "fascinated", "want to know how", "explore")),
    "creativity": ("Creativity", ("creative", "creativity", "make things", "invent", "imaginative", "artist")),
    "judgment": ("Judgment", ("think it through", "weigh", "critical thinker", "see both sides", "judgment")),
    "love_of_learning": ("Love of learning", ("love learning", "love to learn", "read everything", "study", "learner")),
    "perspective": ("Perspective", ("perspective", "big picture", "people come to me for advice", "wise", "wisdom")),
    "bravery": ("Bravery", ("brave", "bravery", "courage", "stood up", "faced it", "spoke up")),
    "perseverance": ("Perseverance", ("persevere", "perseverance", "kept going", "keep going", "don't quit", "didn't quit", "finish what i start", "persistent", "persistence", "stick with", "sticking with", "stuck with", "grit", "never give up")),
    "honesty": ("Honesty", ("honest", "honesty", "tell the truth", "authentic", "integrity", "genuine")),
    "zest": ("Zest", ("zest", "energy", "energetic", "full of life", "enthusias", "alive")),
    "love": ("Love", ("loving", "close relationships", "cherish", "warmth", "my people")),
    "kindness": ("Kindness", ("kind", "kindness", "generous", "help people", "caring", "compassionate", "nurtur")),
    "social_intelligence": ("Social intelligence", ("read people", "read the room", "know what people feel", "emotionally intelligent", "pick up on")),
    "teamwork": ("Teamwork", ("team", "teamwork", "loyal", "show up for", "do my part", "collaborat")),
    "fairness": ("Fairness", ("fair", "fairness", "justice", "treat everyone the same", "equal")),
    "leadership": ("Leadership", ("lead", "leader", "leadership", "organize people", "take charge")),
    "forgiveness": ("Forgiveness", ("forgive", "forgave", "forgiveness", "let it go", "second chance", "mercy")),
    "humility": ("Humility", ("humble", "humility", "don't need the credit", "modest")),
    "prudence": ("Prudence", ("careful", "prudent", "plan ahead", "think before", "cautious")),
    "self_regulation": ("Self-regulation", ("discipline", "disciplined", "self-control", "regulate", "stay calm", "routine")),
    "appreciation_of_beauty": ("Appreciation of beauty", ("beauty", "beautiful", "awe", "in awe", "excellence", "art moves me")),
    "gratitude": ("Gratitude", ("grateful", "gratitude", "thankful", "blessed", "appreciate")),
    "hope": ("Hope", ("hope", "hopeful", "optimis", "future is", "things will get better", "look forward")),
    "humor": ("Humor", ("funny", "humor", "make people laugh", "laugh", "playful", "joke")),
    "spirituality": ("Spirituality", ("faith", "spiritual", "god", "purpose", "meaning", "prayer", "pray")),
}

# CliftonStrengths-style domain rollup (free mapping; used for coach briefing only)
CLIFTON_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "executing": ("perseverance", "self_regulation", "prudence", "honesty", "fairness"),
    "influencing": ("leadership", "bravery", "zest", "humor", "hope"),
    "relationship_building": ("love", "kindness", "teamwork", "forgiveness", "humility", "social_intelligence", "gratitude"),
    "strategic_thinking": ("curiosity", "creativity", "judgment", "love_of_learning", "perspective", "appreciation_of_beauty", "spirituality"),
}

# First-person ownership cues — a strength counts only when the client claims it.
_OWN = re.compile(
    r"\b(i am|i'm|i was|i've always been|i tend to|i can|my (strength|gift|superpower|nature|way)|i (always|usually|naturally)|people say i|they say i|friends say i|i'm known for|i used my|i get told|i'm good at|i'm great at|comes naturally)\b",
    re.I,
)

INTERVIEW_QUESTIONS: Sequence[str] = (
    "Tell me about a moment in the last year when you felt most like yourself — what were you doing, and what did it take?",
    "If three people who love you described you at your best, which words would keep coming up?",
    "What do you lose track of time doing — the thing you'd keep doing even if nobody paid or praised you?",
    "Think of the hardest stretch you've come through. What did you lean on inside yourself to get through it?",
    "What do people thank you for, or come to you for, without you asking?",
    "When you're handed a problem, what's the very first move you naturally make?",
)

MIN_DISTINCT = 3
MIN_TURNS = 2
TOP_N = 5


def detect_strength_mentions(text: str) -> List[str]:
    """Return strength keys the client *claims* in this text (first-person)."""
    t = (text or "").strip()
    if len(t) < 12 or not _OWN.search(t):
        return []
    low = t.lower()
    hits: List[str] = []
    for key, (_label, cues) in STRENGTHS.items():
        if any(c in low for c in cues):
            hits.append(key)
    return hits


def label(key: str) -> str:
    return STRENGTHS.get(key, (key.replace("_", " ").title(), ()))[0]


def clifton_rollup(keys: Sequence[str]) -> List[str]:
    scores: Dict[str, int] = {}
    for d, members in CLIFTON_DOMAINS.items():
        scores[d] = sum(1 for k in keys if k in members)
    return [d for d, n in sorted(scores.items(), key=lambda kv: -kv[1]) if n > 0][:2]


def interview_lines(answers: Optional[Dict[str, Any]], has_signature: bool) -> List[str]:
    """Prompt lines steering LN's in-conversation strengths interview."""
    if has_signature:
        return []
    a = answers or {}
    asked = int(a.get("asked") or 0)
    observed = a.get("observed") or {}
    lines = [
        "STRENGTHS INTERVIEW (in-house, no survey): the client has no saved signature strengths yet. "
        "Over the next several turns, when it fits naturally, ask ONE of these — never more than one per turn, never as a checklist:"
    ]
    q = INTERVIEW_QUESTIONS[asked % len(INTERVIEW_QUESTIONS)]
    lines.append(f"  next question: \"{q}\"")
    if observed:
        top = sorted(observed.items(), key=lambda kv: -int(kv[1]))[:4]
        lines.append("  strengths already heard: " + ", ".join(label(k) for k, _ in top) + ". Reflect them back in the client's own words when you hear them again.")
    lines.append("  When you hear a strength, name it plainly (e.g. 'that's perseverance') so the client can own it.")
    return lines


async def observe_turn(db_pool: Any, user_id: str, user_text: str, *, nate_asked: bool = False) -> Optional[List[str]]:
    """Tally first-person strengths in this turn; save signature when the bar is met.

    Returns the new signature (top N keys) when one was just saved, else None.
    """
    if db_pool is None:
        return None
    hits = detect_strength_mentions(user_text)
    if not hits and not nate_asked:
        return None
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT via_top, answers, method FROM client_strengths WHERE username = $1", username)
            answers: Dict[str, Any] = {}
            via_top: List[str] = []
            if row:
                via_top = list(row["via_top"] or [])
                raw = row["answers"]
                answers = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            observed: Dict[str, int] = {k: int(v) for k, v in (answers.get("observed") or {}).items()}
            for h in hits:
                observed[h] = observed.get(h, 0) + 1
            answers["observed"] = observed
            answers["turns"] = int(answers.get("turns") or 0) + (1 if hits else 0)
            if nate_asked:
                answers["asked"] = int(answers.get("asked") or 0) + 1

            new_sig: Optional[List[str]] = None
            already = bool(via_top) and (row["method"] or "") != "ln_interview_partial"
            if not already and len(observed) >= MIN_DISTINCT and answers["turns"] >= MIN_TURNS:
                new_sig = [k for k, _ in sorted(observed.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]]
            method = "ln_interview" if new_sig else ((row["method"] if row else None) or "ln_interview_partial")
            sig = new_sig or via_top
            await conn.execute(
                """
                INSERT INTO client_strengths (username, via_top, clifton_domains, answers, method, assessed_at, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, NOW(), NOW())
                ON CONFLICT (username) DO UPDATE SET
                    via_top = EXCLUDED.via_top, clifton_domains = EXCLUDED.clifton_domains,
                    answers = EXCLUDED.answers, method = EXCLUDED.method, updated_at = NOW(),
                    assessed_at = CASE WHEN EXCLUDED.method = 'ln_interview' THEN NOW() ELSE client_strengths.assessed_at END
                """,
                username, sig[:7], clifton_rollup(sig), json.dumps(answers, default=str), method,
            )
        if new_sig:
            logger.info("strengths_interview: signature saved for %s: %s", username, new_sig)
            asyncio.create_task(
                crystallize_thrive(
                    db_pool, username,
                    "Signature strengths (LN interview): " + ", ".join(label(k) for k in new_sig),
                    kind="strengths",
                )
            )
        return new_sig
    except Exception as e:
        logger.warning("strengths_interview: observe_turn failed for %s: %s", username, e)
        return None


# ── phase-aware crystal layer ──────────────────────────────────────────────

THRIVE_DOMAIN = "thrive"
_RECALL_DOMAINS = (THRIVE_DOMAIN, "coaching")


async def thrive_memory(db_pool: Any, user_id: str, *, limit: int = 4) -> List[str]:
    """User-scoped thrive/coaching crystals (goal, practice, strength harvests).

    Recall is reinforced here (recall_count / last_recalled_at / +0.03 confidence)
    so growth memory survives the 90-day decay the same way clinical memory does.
    """
    if db_pool is None:
        return []
    username = await resolve_username(db_pool, user_id) or user_id
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH u AS (SELECT id FROM users WHERE username = $1 OR hardware_id = $1 LIMIT 1),
                picked AS (
                    SELECT c.id, c.crystal_text
                    FROM nate_intelligence_crystals c, u
                    WHERE c.user_id = u.id
                      AND c.domain = ANY($2::text[])
                      AND COALESCE(c.scope, '') <> 'archived'
                      AND c.superseded_by IS NULL
                      AND c.confidence >= 0.30
                    ORDER BY c.created_at DESC
                    LIMIT $3
                )
                UPDATE nate_intelligence_crystals c
                   SET recall_count = COALESCE(c.recall_count, 0) + 1,
                       last_recalled_at = NOW(),
                       confidence = LEAST(0.95, COALESCE(c.confidence, 0.5) + 0.03)
                  FROM picked
                 WHERE c.id = picked.id
                RETURNING picked.crystal_text
                """,
                username, list(_RECALL_DOMAINS), limit,
            )
        return [str(r["crystal_text"]).strip()[:280] for r in rows if r["crystal_text"]]
    except Exception as e:
        logger.debug("strengths_interview: thrive_memory failed for %s: %s", username, e)
        return []


async def crystallize_thrive(db_pool: Any, user_id: str, text: str, *, kind: str = "harvest") -> Optional[str]:
    """Forge a thrive-domain user crystal from a goal / practice / strengths harvest."""
    if db_pool is None or not (text or "").strip():
        return None
    try:
        from app.websocket.crystal_recall_bridge import crystallize_from_conversation
    except Exception:
        return None
    try:
        return await crystallize_from_conversation(
            db_pool, user_id, f"[thrive:{kind}] {text.strip()[:1500]}", "",
            domain=THRIVE_DOMAIN, min_score=0, origin_surface="thrive_coach",
        )
    except Exception as e:
        logger.debug("strengths_interview: crystallize_thrive failed: %s", e)
        return None
