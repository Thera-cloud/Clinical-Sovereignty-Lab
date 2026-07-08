"""Semantic passive-suicidal-ideation detector — embedding-similarity layer
that sits alongside `suicide_ideation_lexicon.match_user_text()`, never
replacing it.

2026-07 Public Trial Funnel audit: three consecutive, distinct real-user
phrasings of passive suicidal ideation each defeated the regex lexicon in
turn --
  Round 1 (Q7): "my wife and kids would be better off without me"
  Round 2 (T12): "everyone would manage fine without me" (read by the model
                 as a relocation plan and debated on its logistics)
Phrase-list matching cannot keep pace with how people actually talk about
wanting to not exist -- every new session risks a fourth phrasing neither
list anticipated. Per the audit conclusion: "Stop extending the list. The
fix that ships is semantic ... tune for recall -- a false-positive costs one
warm check-in question, a false-negative costs the thing this product
exists to prevent."

This module embeds the user's text (Cloudflare Workers AI, bge-small-en-v1.5
via `vectorize_service.generate_embeddings`) and compares it by cosine
similarity against a curated exemplar set of passive/active ideation
statements, including the exact phrasings above as the first regression
fixtures.

Fails safe: any embedding-service outage, missing Cloudflare credentials, or
exception returns `None` (no semantic signal) -- it never raises and never
widens detection beyond what the lexicon already found on its own. The
lexicon remains the fast, zero-latency first line; this is a slower,
broader second line layered on top for the cases language alone escapes.
"""
from __future__ import annotations

import logging
import math
import os
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def is_semantic_si_enabled() -> bool:
    """Flag-gated so a bad embedding backend can be killed instantly without
    a deploy. Defaults ON — this is the durable fix the 2026-07 audit
    requires, not an opt-in experiment."""
    return (os.getenv("SI_SEMANTIC_ENABLED", "true") or "").strip().lower() not in (
        "0", "false", "no", "off",
    )


try:
    # Deliberately permissive — tuned for recall per the audit's explicit
    # instruction. bge-small-en-v1.5 cosine similarity between short,
    # differently-worded but same-topic sentences commonly falls in the
    # 0.65-0.85 band; 0.72 favors catching a genuine fourth phrasing over
    # precision. Re-tune from real SI-probe transcripts as they accumulate —
    # never raise this without first confirming Marcus's three fixtures
    # below still trip it.
    SI_SEMANTIC_THRESHOLD: float = float(os.getenv("SI_SEMANTIC_THRESHOLD", "0.72"))
except ValueError:
    SI_SEMANTIC_THRESHOLD = 0.72

# Exemplar anchor set. Order-independent; kept short and high-signal on
# purpose (a similarity anchor set, not an exhaustive catalog). The first
# three groups are the exact production misses from the 2026-07 audit and
# MUST stay — they are also the first fixtures in
# test_si_semantic_detector.py and test_public_trial_crisis.py.
SI_EXEMPLARS: Tuple[str, ...] = (
    # Round 1, Q7 — "better off without me" family (near-miss phrasing;
    # canonical form is already in the lexicon, this exemplar is the
    # softer/hedged variant that surrounds it in real speech)
    "Some nights I lay there thinking my wife and kids would be better off without me. Not that I'd actually do anything.",
    "Everyone would be better off without me around, honestly.",
    # Round 2, T12 — "manage fine without me" / disappearing-as-euphemism
    "I've been thinking about disappearing. Everyone would manage fine without me.",
    "I keep thinking about just disappearing and letting everyone move on without me.",
    "Sometimes I think about just not being around anymore and everyone would be fine.",
    # Other passive-ideation phrasings not yet covered by the lexicon
    "I'm so tired of existing, I just want it all to stop.",
    "Sometimes I think everyone would be relieved if I just wasn't here anymore.",
    "I don't see the point in sticking around much longer.",
    "I keep wondering what it would be like if I just wasn't around anymore.",
    "Maybe things would be easier for everyone if I weren't in the picture.",
    "I feel like such a weight on everyone, they'd probably be relieved if I were gone.",
    # Active ideation, so the anchor set isn't purely passive-only
    "I've been thinking about ending my life.",
    "I don't want to wake up tomorrow.",
)

_exemplar_embeddings: Optional[List[List[float]]] = None
_exemplar_load_failed = False


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


async def _get_exemplar_embeddings() -> Optional[List[List[float]]]:
    """Lazy, memoized per-process. Returns None if the embedding backend is
    unavailable or misbehaves — callers MUST treat that as 'no semantic
    signal available', never as a match."""
    global _exemplar_embeddings, _exemplar_load_failed
    if _exemplar_embeddings is not None:
        return _exemplar_embeddings
    if _exemplar_load_failed:
        return None
    try:
        from app.services.vectorize_service import generate_embeddings
        embeddings = await generate_embeddings(list(SI_EXEMPLARS))
        if not embeddings or len(embeddings) != len(SI_EXEMPLARS):
            _exemplar_load_failed = True
            return None
        _exemplar_embeddings = embeddings
        return _exemplar_embeddings
    except Exception as e:
        logger.warning("si_semantic_detector: exemplar embedding load failed: %s", e)
        _exemplar_load_failed = True
        return None


def reset_exemplar_cache() -> None:
    """Test-only hook — clears the memoized exemplar embeddings/failure flag."""
    global _exemplar_embeddings, _exemplar_load_failed
    _exemplar_embeddings = None
    _exemplar_load_failed = False


async def semantic_si_match(text: str) -> Optional[Tuple[str, float]]:
    """Returns `(matched_exemplar, similarity)` if `text` is semantically
    close to a passive/active suicidal-ideation exemplar at or above
    `SI_SEMANTIC_THRESHOLD`, else `None`.

    Never raises — any failure (disabled flag, unconfigured Cloudflare
    credentials, network error, malformed response) returns `None`, which
    callers must interpret as "no additional signal", not "safe". The
    lexicon check remains authoritative when this layer is unavailable.
    """
    if not is_semantic_si_enabled() or not text or not str(text).strip():
        return None
    try:
        from app.services.vectorize_service import generate_embeddings, is_vectorize_configured
        if not is_vectorize_configured():
            return None
        exemplar_vecs = await _get_exemplar_embeddings()
        if not exemplar_vecs:
            return None
        text_vecs = await generate_embeddings([text])
        if not text_vecs:
            return None
        text_vec = text_vecs[0]
        best_score = 0.0
        best_exemplar = ""
        for exemplar, vec in zip(SI_EXEMPLARS, exemplar_vecs):
            score = _cosine(text_vec, vec)
            if score > best_score:
                best_score = score
                best_exemplar = exemplar
        if best_score >= SI_SEMANTIC_THRESHOLD:
            return best_exemplar, best_score
        return None
    except Exception as e:
        logger.warning("si_semantic_detector: semantic check failed: %s", e)
        return None
