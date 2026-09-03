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
                "If you are in immediate danger, stay on the line for 988.</Say>"
                "<Dial>988</Dial>"
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


def handle_screener(*, step: str, digits: str = "", speech: str = "", n: int = 0) -> Dict[str, Any]:
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
    return {"twiml": wait_twiml(n), "persist": False}


def wait_twiml(n: int = 0) -> str:
    try:
        loops = max(0, int(n))
    except (TypeError, ValueError):
        loops = 0
    if loops >= 8:
        return _xml("<Say>Waiting room closed. Please call back.</Say><Hangup/>")
    return _xml(
        "<Say>Still waiting. Guests are audio only. Video is not available on this line.</Say>"
        "<Pause length=\"8\"/>"
        f'<Redirect>{BASE}?step=wait&amp;n={loops + 1}</Redirect>'
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
            INSERT INTO studio_consent_records (show_id, caller_id, consent_kind, granted, source)
            VALUES ($1::uuid, $2::uuid, 'air', $3, 'screener')
            """,
            show_id,
            caller["id"],
            consented and not risk,
        )
        if consented and not risk:
            await conn.execute(
                """
                INSERT INTO studio_consent_records (show_id, caller_id, consent_kind, granted, source)
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
    if consented and not risk and phone:
        try:
            from app.services.studio_sms import send_opt_in_sms

            send_opt_in_sms(phone)
        except Exception as exc:
            logger.warning("studio SMS dispatch skipped: %s", exc)
    if show_id:
        try:
            from app.services.studio_screener_autoscale import scale_hint, waiting_count

            n = await waiting_count(db_pool, show_id)
            logger.info("studio autoscale %s", scale_hint(n))
        except Exception as exc:
            logger.warning("studio autoscale skipped: %s", exc)
    if session_id and consented and not risk and caller:
        try:
            from app.services.studio_caller_queue import caller_identity, enqueue_db_caller

            ident = caller_identity(str(caller["id"]))
            await enqueue_db_caller(None, str(session_id), ident, topic or "Caller")
        except Exception as exc:
            logger.warning("studio queue enqueue skipped: %s", exc)


async def lookup_show_by_did(db_pool, did: str) -> Optional[str]:
    if not db_pool or not did:
        return None
    from app.services.studio_did_service import digits_only

    digits = digits_only(did)
    if not digits:
        return None
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id FROM studio_shows
            WHERE regexp_replace(COALESCE(did_e164, ''), '[^0-9]', '', 'g') = $1
            LIMIT 1
            """,
            digits,
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
        recent = await conn.fetch(
            """
            SELECT t.topic_deidentified
            FROM caller_topics t
            JOIN show_callers c ON c.id = t.caller_id
            WHERE c.show_id = $1::uuid AND c.opted_in = TRUE
            ORDER BY t.created_at DESC
            LIMIT 5
            """,
            show_id,
        )
    labels = [r["topic_deidentified"] for r in recent] if recent else []
    return {
        "ok": True,
        "logged": int(logged or 0),
        "opted_in": int(opted or 0),
        "deidentified_topics": int(topics or 0),
        "recent_topics": labels,
        "ack_only": True,
        "browse": False,
    }


async def acknowledge_caller(db_pool, show_id: str, phone: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    ph = phone_hash(phone)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n, BOOL_OR(opted_in) AS opted
            FROM show_callers WHERE show_id = $1::uuid AND phone_hash = $2
            """,
            show_id,
            ph,
        )
        topic = None
        if row and row["opted"]:
            topic = await conn.fetchval(
                """
                SELECT t.topic_deidentified
                FROM caller_topics t
                JOIN show_callers c ON c.id = t.caller_id
                WHERE c.show_id = $1::uuid AND c.phone_hash = $2 AND c.opted_in = TRUE
                ORDER BY t.created_at DESC LIMIT 1
                """,
                show_id,
                ph,
            )
    n = int((row["n"] if row else 0) or 0)
    return {
        "ok": True,
        "prior_calls": n,
        "ack": "I remember you have been on the show before." if n else "First time on the show.",
        "last_topic": topic if (row and row["opted"]) else None,
        "browse": False,
    }


async def apply_sms_reply(db_pool, did: str, phone: str, body: str) -> Dict[str, Any]:
    from app.services.studio_sms import parse_sms_reply

    action = parse_sms_reply(body)
    if action == "ignore":
        return {"ok": True, "action": "ignore"}
    show_id = await lookup_show_by_did(db_pool, did)
    if not db_pool or not show_id:
        return {"ok": True, "action": action, "persisted": False}
    opted = action == "opt_in"
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE show_callers SET opted_in = $3
            WHERE show_id = $1::uuid AND phone_hash = $2
            """,
            show_id,
            phone_hash(phone),
            opted,
        )
        await conn.execute(
            """
            INSERT INTO studio_consent_records (show_id, consent_kind, granted, source)
            VALUES ($1::uuid, 'sms_opt_in', $2, 'sms')
            """,
            show_id,
            opted,
        )
    return {"ok": True, "action": action, "persisted": True}


def escape_say(text: str) -> str:
    return escape(text or "")
