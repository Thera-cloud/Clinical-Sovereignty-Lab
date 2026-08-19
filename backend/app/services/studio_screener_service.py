"""S2 screener TwiML — disclosure → consent → intake → risk → waiting room.

INV-4: inbound always starts here. Risk branch is private-support only.
Never imports therapeutic/crystal/sensitive modules. QUANTUM-CRYSTAL-ARCH
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from typing import Any, Dict, Optional
from xml.sax.saxutils import escape

from app.services.studio_invariants import SCREENER_TOKEN_TTL_S

logger = logging.getLogger("studio_screener")

RISK_RE = re.compile(
    r"\b(suicid|kill myself|end my life|want to die|self-harm|overdose|hurt myself)\w*\b",
    re.IGNORECASE,
)
STEPS = ("disclosure", "consent", "intake", "risk", "wait")
BASE = "/api/studio/voice/screener"


def _xml(inner: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'


def inbound_twiml() -> str:
    return _xml(
        "<Say>This line starts the screening. Please stay on the line.</Say>"
        f"<Redirect>{BASE}?step=disclosure</Redirect>"
    )


def disclosure_twiml() -> str:
    return _xml(
        "<Say>This is a public educational show with an AI co-host and knowledge companion. "
        "It is not therapy, diagnosis, or clinical care. Press 1 to continue or 2 to hang up.</Say>"
        f'<Gather numDigits="1" action="{BASE}?step=consent" method="POST"/>'
        "<Hangup/>"
    )


def consent_twiml(digits: str) -> str:
    if (digits or "").strip() != "1":
        return _xml("<Say>Goodbye.</Say><Hangup/>")
    return _xml(
        "<Say>Press 1 to consent to being on air and recorded. Press 2 to decline.</Say>"
        f'<Gather numDigits="1" action="{BASE}?step=intake" method="POST"/>'
        "<Hangup/>"
    )


def intake_twiml(digits: str) -> str:
    if (digits or "").strip() != "1":
        return _xml("<Say>Consent declined. Goodbye.</Say><Hangup/>")
    return _xml(
        "<Say>In a short sentence, what would you like to talk about on the show?</Say>"
        f'<Gather input="speech" timeout="6" action="{BASE}?step=risk" method="POST"/>'
        "<Hangup/>"
    )


def risk_or_wait_twiml(speech: str) -> Dict[str, Any]:
    text = (speech or "").strip()
    if RISK_RE.search(text):
        return {
            "risk": True,
            "twiml": _xml(
                "<Say>I am connecting you with private support, not the show. "
                "If you are in immediate danger, call emergency services or 988.</Say>"
                "<Hangup/>"
            ),
        }
    return {
        "risk": False,
        "twiml": _xml(
            "<Say>You are in the waiting room. A host will bring you on as audio only. "
            "Please stay on the line.</Say>"
            f'<Redirect>{BASE}?step=wait</Redirect>'
        ),
    }


def handle_screener(*, step: str, digits: str = "", speech: str = "") -> Dict[str, Any]:
    st = (step or "disclosure").strip().lower()
    if st in ("", "disclosure"):
        return {"twiml": disclosure_twiml(), "persist": False}
    if st == "consent":
        return {"twiml": consent_twiml(digits), "persist": False}
    if st == "intake":
        return {"twiml": intake_twiml(digits), "persist": False, "consented": (digits or "").strip() == "1"}
    if st == "risk":
        out = risk_or_wait_twiml(speech)
        return {
            "twiml": out["twiml"],
            "persist": True,
            "risk": out["risk"],
            "consented": not out["risk"],
            "speech": speech,
        }
    return {"twiml": wait_twiml(), "persist": False}


def wait_twiml() -> str:
    return _xml(
        "<Say>Still waiting. Guests are audio only. Video is not available on this line.</Say>"
        "<Pause length=\"8\"/>"
        "<Hangup/>"
    )


def phone_hash(phone: str) -> str:
    return hashlib.sha256((phone or "").encode("utf-8")).hexdigest()


def is_risk(text: str) -> bool:
    return bool(RISK_RE.search(text or ""))


async def issue_join_token(redis) -> str:
    token = secrets.token_urlsafe(24)
    if redis:
        await redis.setex(f"studio_screener:{token}", SCREENER_TOKEN_TTL_S, "1")
    return token


async def persist_screener(
    db_pool,
    *,
    show_id: Optional[str],
    session_id: Optional[str],
    phone: str,
    speech: str,
    consented: bool,
    risk: bool,
) -> None:
    if not db_pool or not show_id:
        return
    topic = (speech or "").strip()[:240]
    async with db_pool.acquire() as conn:
        caller = await conn.fetchrow(
            """
            INSERT INTO show_callers (show_id, session_id, phone_hash, opted_in, risk_flag)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5)
            RETURNING id
            """,
            show_id,
            session_id,
            phone_hash(phone),
            consented and not risk,
            risk,
        )
        await conn.execute(
            """
            INSERT INTO consent_records (show_id, caller_id, consent_kind, granted, source)
            VALUES ($1::uuid, $2::uuid, 'air', $3, 'screener')
            """,
            show_id,
            caller["id"],
            consented and not risk,
        )
        if consented and not risk:
            await conn.execute(
                """
                INSERT INTO consent_records (show_id, caller_id, consent_kind, granted, source)
                VALUES ($1::uuid, $2::uuid, 'recording', TRUE, 'screener')
                """,
                show_id,
                caller["id"],
            )
        if topic and not risk:
            await conn.execute(
                """
                INSERT INTO caller_topics (caller_id, topic_deidentified)
                VALUES ($1::uuid, $2)
                """,
                caller["id"],
                topic,
            )


async def lookup_show_by_did(db_pool, did: str) -> Optional[str]:
    if not db_pool or not did:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE did_e164 = $1 LIMIT 1",
            did.strip(),
        )
    return str(row["id"]) if row else None


async def caller_memory_counts(db_pool, show_id: str, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        show = await conn.fetchrow(
            "SELECT id FROM studio_shows WHERE id = $1::uuid AND coach_id = $2",
            show_id,
            coach_id,
        )
        if not show:
            return {"ok": False, "reason": "not_found", "code": 404}
        logged = await conn.fetchval(
            "SELECT COUNT(*) FROM show_callers WHERE show_id = $1::uuid",
            show_id,
        )
        opted = await conn.fetchval(
            "SELECT COUNT(*) FROM show_callers WHERE show_id = $1::uuid AND opted_in = TRUE",
            show_id,
        )
        topics = await conn.fetchval(
            """
            SELECT COUNT(*) FROM caller_topics t
            JOIN show_callers c ON c.id = t.caller_id
            WHERE c.show_id = $1::uuid
            """,
            show_id,
        )
    return {
        "ok": True,
        "logged": int(logged or 0),
        "opted_in": int(opted or 0),
        "deidentified_topics": int(topics or 0),
        "browse": False,
    }


def escape_say(text: str) -> str:
    return escape(text or "")
