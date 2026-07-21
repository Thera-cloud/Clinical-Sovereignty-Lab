"""
QUANTUM-CRYSTAL-ARCH: Commitment + symbolic extraction (Agentic Phase 1 / 5a).
Post-turn async utility LLM; sensitivity set deterministically from PII/Bridge.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nate.commitment_extractor")

_TEMPORAL_RE = re.compile(
    r"\b(tomorrow|tonight|next week|next month|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|\d{1,2}/\d{1,2})\b",
    re.I,
)
_INTENT_RE = re.compile(
    r"\b(going to|trying to|planning to|plan to|have a|i'm doing|i will|i'll)\b",
    re.I,
)


VALID_COMMITMENT_TYPES = frozenset(
    {"appointment", "practice_goal", "milestone", "custom"}
)


@dataclass
class CommitmentSymbol:
    text: str
    type: str
    target_date_iso: Optional[str] = None
    recurrence: Optional[str] = None
    sensitivity: str = "routine"


def validate_commitment_symbol(data: Optional[Dict[str, Any]]) -> Optional[CommitmentSymbol]:
    """Schema guard for Phase 5a — rejects partial or invalid symbols."""
    if not isinstance(data, dict):
        return None
    text = (data.get("text") or "").strip()
    ctype = (data.get("type") or "").strip()
    if not text or ctype not in VALID_COMMITMENT_TYPES:
        return None
    sens = data.get("sensitivity") or "routine"
    if sens not in ("routine", "sensitive"):
        sens = "routine"
    return CommitmentSymbol(
        text=text,
        type=ctype,
        target_date_iso=data.get("target_date_iso"),
        recurrence=data.get("recurrence"),
        sensitivity=sens,
    )


@dataclass
class StateSymbol:
    emotional_valence: str = "neutral"
    distress_present: bool = False
    topics: List[str] = None
    flags: List[str] = None

    def __post_init__(self):
        if self.topics is None:
            self.topics = []
        if self.flags is None:
            self.flags = []


def commitments_enabled() -> bool:
    return os.getenv("ENABLE_PROACTIVE_COMMITMENTS", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def symbolic_extraction_enabled() -> bool:
    return os.getenv("ENABLE_SYMBOLIC_EXTRACTION", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def heuristic_prefilter(user_text: str) -> bool:
    if not user_text or len(user_text) < 12:
        return False
    return bool(_TEMPORAL_RE.search(user_text) and _INTENT_RE.search(user_text))


def build_state_symbol(
    user_text: str,
    *,
    audit_metadata: Optional[Dict[str, Any]] = None,
    bridge_flags: Optional[List[str]] = None,
) -> StateSymbol:
    """Deterministic StateSymbol — no LLM."""
    distress = False
    flags: List[str] = list(bridge_flags or [])
    valence = "neutral"
    topics: List[str] = []

    if audit_metadata:
        if audit_metadata.get("distress_present") or audit_metadata.get("tmc_class") in (
            "crisis",
            "high_arousal",
        ):
            distress = True
            valence = "distressed"
        autonomic = (audit_metadata.get("autonomic_state") or "").lower()
        if autonomic in ("fight", "flight", "freeze"):
            distress = True

    try:
        from app.services.night_school_director import PIIDetector

        for match in PIIDetector.detect(user_text):
            flags.append(f"pii:{match.type.value if hasattr(match.type, 'value') else match.type}")
    except Exception:
        pass

    lower = user_text.lower()
    if any(
        w in lower
        for w in (
            "afraid",
            "scared",
            "anxious",
            "panic",
            "overwhelmed",
            "hopeless",
            "want to die",
            "end my life",
            "kill myself",
            "suicide",
        )
    ):
        distress = True
        valence = "distressed"
    elif any(w in lower for w in ("excited", "proud", "happy", "grateful")):
        valence = "positive"

    for word in re.findall(r"\b[A-Z][a-z]{3,}\b", user_text):
        if word not in topics:
            topics.append(word)

    return StateSymbol(
        emotional_valence=valence,
        distress_present=distress,
        topics=topics[:10],
        flags=flags[:20],
    )


def classify_sensitivity(
    user_text: str,
    *,
    bridge_decision: Any = None,
) -> str:
    """Deterministic sensitivity — never from LLM."""
    lower = (user_text or "").lower()
    sensitive_markers = (
        "abuse",
        "trauma",
        "suicide",
        "self-harm",
        "addiction",
        "relapse",
        "court",
        "custody",
        "subpoena",
    )
    if any(m in lower for m in sensitive_markers):
        return "sensitive"
    if bridge_decision is not None:
        sev = getattr(bridge_decision, "coach_alert", None)
        if sev is not None:
            return "sensitive"
        tmc = getattr(bridge_decision, "tmc_class", "") or ""
        if str(tmc).lower() in ("crisis", "mandatory_reporting"):
            return "sensitive"
    return "routine"


async def extract_commitment_candidate(
    db_pool: Any,
    *,
    username: Optional[str],
    hardware_id: str,
    user_text: str,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Phase 1 extraction — returns dict ready for nate_commitments INSERT."""
    if not commitments_enabled() and not symbolic_extraction_enabled():
        return None
    if not username:
        return None
    if not heuristic_prefilter(user_text):
        return None

    structured: Optional[Dict[str, Any]] = None
    try:
        from app.services.nate_inference_router import NateInferenceRouter

        router = NateInferenceRouter()
        prompt = (
            "Extract a single client commitment from the message as JSON only: "
            '{"text":"","type":"appointment|practice_goal|milestone|custom",'
            '"target_date_iso":null,"recurrence":null}. '
            "Return null JSON if not a genuine commitment. Message: "
            + json.dumps(user_text[:1500])
        )
        # QUANTUM-CRYSTAL-ARCH: NateInferenceRouter.generate(prompt=..., system=...) → dict
        out = await router.generate(
            prompt=prompt,
            system="Return valid JSON only. No markdown fences.",
            domain="utility",
            max_tokens=200,
        )
        raw = (out.get("text") if isinstance(out, dict) else out) or ""
        text = str(raw).strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text) if text and text.lower() != "null" else None
        if isinstance(parsed, dict) and parsed.get("text"):
            structured = parsed
    except Exception as e:
        logger.warning("commitment_extractor: LLM parse failed: %s", e)
        return None

    if not structured:
        return None

    sensitivity = classify_sensitivity(user_text)
    state = build_state_symbol(user_text, audit_metadata=audit_metadata)
    result = {
        "user_id": hardware_id,
        "username": username,
        "commitment_text": structured["text"],
        "commitment_type": structured.get("type") or "custom",
        "target_date_iso": structured.get("target_date_iso"),
        "recurrence": structured.get("recurrence"),
        "sensitivity": sensitivity,
        "source": "auto_extracted",
    }
    if symbolic_extraction_enabled():
        result["symbols"] = {
            "commitment": asdict(
                CommitmentSymbol(
                    text=structured["text"],
                    type=structured.get("type") or "custom",
                    target_date_iso=structured.get("target_date_iso"),
                    recurrence=structured.get("recurrence"),
                    sensitivity=sensitivity,
                )
            ),
            "state": asdict(state),
        }
    return result


async def persist_commitment(db_pool: Any, payload: Dict[str, Any]) -> Optional[str]:
    if not db_pool or not payload:
        return None
    try:
        target = payload.get("target_date_iso")
        target_dt = None
        if target:
            try:
                target_dt = datetime.fromisoformat(str(target).replace("Z", "+00:00"))
            except Exception:
                target_dt = None
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO nate_commitments
                    (user_id, commitment_text, commitment_type, target_date,
                     recurrence, sensitivity, source, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
                RETURNING id
                """,
                payload["user_id"],
                payload["commitment_text"],
                payload.get("commitment_type", "custom"),
                target_dt,
                payload.get("recurrence"),
                payload.get("sensitivity", "routine"),
                payload.get("source", "auto_extracted"),
            )
            if row:
                return str(row["id"])
            return None
    except Exception as e:
        logger.warning("commitment_extractor: persist failed: %s", e)
        return None


async def attach_symbols_to_conversation_turn(
    db_pool: Any,
    *,
    username: str,
    user_text: str,
    symbols: Dict[str, Any],
) -> bool:
    """QUANTUM-CRYSTAL-ARCH: Phase 5a — merge symbols onto matching chat row metadata."""
    if not symbolic_extraction_enabled() or not db_pool or not username or not symbols:
        return False
    try:
        async with db_pool.acquire() as conn:
            updated = await conn.fetchval(
                """
                UPDATE conversation_history
                SET metadata = COALESCE(metadata, '{}'::jsonb)
                    || jsonb_build_object('symbols', $1::jsonb)
                WHERE id = (
                    SELECT id FROM conversation_history
                    WHERE user_id = $2
                      AND left(user_text, 200) = left($3::text, 200)
                      AND created_at > NOW() - INTERVAL '10 minutes'
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                RETURNING id
                """,
                json.dumps(symbols),
                username,
                (user_text or "")[:4000],
            )
            return updated is not None
    except Exception as e:
        logger.warning("commitment_extractor: attach symbols failed: %s", e)
        return False


_VALID_COMMITMENT_TYPES = frozenset(
    {"appointment", "practice_goal", "milestone", "custom"}
)


def validate_commitment_symbol(data: Dict[str, Any]) -> Optional[CommitmentSymbol]:
    """Schema reject — never return partial symbols (Phase 5a seam-tests)."""
    if not isinstance(data, dict):
        return None
    text = (data.get("text") or "").strip()
    if not text or len(text) < 3:
        return None
    ctype = (data.get("type") or "custom").strip()
    if ctype not in _VALID_COMMITMENT_TYPES:
        return None
    sensitivity = data.get("sensitivity") or "routine"
    if sensitivity not in ("routine", "sensitive"):
        return None
    return CommitmentSymbol(
        text=text,
        type=ctype,
        target_date_iso=data.get("target_date_iso"),
        recurrence=data.get("recurrence"),
        sensitivity=sensitivity,
    )


async def run_post_turn_extraction(
    db_pool: Any,
    *,
    username: Optional[str],
    hardware_id: str,
    user_text: str,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget entry point (mirrors crystallize timing)."""
    try:
        payload = await extract_commitment_candidate(
            db_pool,
            username=username,
            hardware_id=hardware_id,
            user_text=user_text,
            audit_metadata=audit_metadata,
        )
        if payload:
            await persist_commitment(db_pool, payload)
            # QUANTUM-CRYSTAL-ARCH: Phase 5a — full {commitment,state} onto chat metadata
            _syms = payload.get("symbols")
            if _syms and username:
                await attach_symbols_to_conversation_turn(
                    db_pool,
                    username=username,
                    user_text=user_text,
                    symbols=_syms,
                )
    except Exception as e:
        logger.warning("commitment_extractor: post-turn failed: %s", e)


def schedule_post_turn_extraction(
    db_pool: Any,
    *,
    username: Optional[str],
    hardware_id: str,
    user_text: str,
    audit_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """QUANTUM-CRYSTAL-ARCH: one-liner schedule for chat surfaces (flag-gated)."""
    import asyncio

    # QUANTUM-CRYSTAL-ARCH: Phase 5a — schedule when commitments OR symbolic extraction ON
    if not commitments_enabled() and not symbolic_extraction_enabled():
        return
    if not db_pool or not hardware_id or not (user_text or "").strip():
        return
    try:
        asyncio.create_task(
            run_post_turn_extraction(
                db_pool,
                username=username or hardware_id,
                hardware_id=hardware_id,
                user_text=user_text,
                audit_metadata=audit_metadata,
            )
        )
    except Exception as e:
        logger.warning("commitment_extractor: schedule failed: %s", e)
