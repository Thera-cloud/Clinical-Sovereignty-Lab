"""S3 compliance pass — INV-6 + NateResponseValidator patterns. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.services.studio_invariants import INV6_BLOCKED

logger = logging.getLogger("studio_compliance")

PII_RE = re.compile(
    r"\b(\d{3}-\d{2}-\d{4}|\d{3}-\d{3}-\d{4}|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})\b",
    re.IGNORECASE,
)
MEDICAL_RE = re.compile(
    r"\b(diagnos\w+|prescri\w+|treatment plan|you have (ptsd|bipolar|depression))\b",
    re.IGNORECASE,
)
CRISIS_RE = re.compile(
    r"\b(suicid|kill yourself|end your life)\w*\b",
    re.IGNORECASE,
)


def prescan_outgoing(text: str) -> Dict[str, Any]:
    flags = scan_text(text or "")
    blocked = bool(INV6_BLOCKED.search(text or "")) or any(
        f.get("severity") == "high" for f in flags
    )
    return {"ok": not blocked, "blocked": blocked, "flags": flags, "pre_synthesis": True}


def scan_text(text: str, *, vertical: str = "") -> List[Dict[str, str]]:
    flags: List[Dict[str, str]] = []
    blob = text or ""
    if PII_RE.search(blob):
        flags.append({"severity": "high", "category": "pii", "detail": "possible PII in transcript"})
    if MEDICAL_RE.search(blob) or INV6_BLOCKED.search(blob):
        flags.append(
            {
                "severity": "high",
                "category": "guardrail",
                "detail": "clinical/therapy language blocked for broadcast",
            }
        )
    if CRISIS_RE.search(blob):
        flags.append({"severity": "high", "category": "crisis", "detail": "crisis language on air"})
    if vertical == "trauma_modalities" and re.search(r"\bexpose(d)? your trauma\b", blob, re.I):
        flags.append(
            {"severity": "med", "category": "vertical", "detail": "trauma vertical safety phrasing"}
        )
    return flags


async def run_pass(db_pool, episode_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.transcript_json, e.title, s.vertical
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid
            """,
            episode_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        transcript = row["transcript_json"] or []
        if isinstance(transcript, str):
            blob = transcript
        else:
            blob = " ".join(
                str(seg.get("text") or "") for seg in transcript if isinstance(seg, dict)
            )
        blob = f"{row['title'] or ''} {blob}"
        flags = scan_text(blob, vertical=row["vertical"] or "")
        try:
            from app.services.nate_response_validator import NateResponseValidator

            _text, warns = await NateResponseValidator().validate(blob, {})
            for w in warns:
                flags.append({"severity": "med", "category": "validator", "detail": str(w)})
        except Exception as exc:
            logger.warning("studio compliance validator skipped: %s", exc)
        for f in flags:
            await conn.execute(
                """
                INSERT INTO studio_compliance_flags (episode_id, severity, category, detail)
                VALUES ($1::uuid, $2, $3, $4)
                """,
                episode_id,
                f["severity"],
                f["category"],
                f["detail"],
            )
    return {"ok": True, "flag_count": len(flags), "flags": flags}
