"""
Factual grounding bridge — validates AI responses before sending to clients.

Wires NateResponseValidator Layer 8 into the live chat pipeline with a
false-positive guard: if the client introduced the factual topic first,
Nate is reflecting (safe), not asserting (flag).
"""

import re
import logging

logger = logging.getLogger(__name__)

try:
    from app.services.nate_response_validator import NateResponseValidator
except ImportError:
    NateResponseValidator = None

_validator = NateResponseValidator() if NateResponseValidator else None


def _extract_subject_words(matched_text: str) -> list:
    """Extract likely subject words (names/nouns) from a factual assertion match."""
    cleaned = re.sub(
        r'\b(he|she|they|is|are|was|were|dead|alive|deceased|'
        r'still alive|still living|passed away|died|yes|no|actually|'
        r'in fact|confirmed|can confirm|I can tell you|that|did|has|have)\b',
        '',
        matched_text,
        flags=re.IGNORECASE,
    )
    return [w.strip() for w in cleaned.split() if len(w.strip()) > 2]


async def validate_before_send(
    nate_response: str,
    client_messages_this_session: list,
    db_pool=None,
    session_id: str = "",
    user_id: str = "",
) -> dict:
    """
    Run Layer 8 factual grounding check on Nate's response.

    Returns ``{"safe": True}`` or ``{"safe": False, "reason": ..., "redirect": ...}``.

    False-positive guard: if the assertion references something the CLIENT
    said first, skip — Nate is reflecting, not volunteering.
    """
    if not _validator:
        return {"safe": True, "note": "validator_unavailable"}

    try:
        _, warnings = await _validator.validate(
            nate_response,
            context={"client_message": " ".join(client_messages_this_session[-5:])},
        )

        layer8_fired = any(
            "unverified_factual_assertion" in w for w in warnings
        )
        if not layer8_fired:
            return {"safe": True}

        client_text_combined = " ".join(client_messages_this_session).lower()

        for patt in _validator.FACTUAL_ASSERTION_PATTERNS:
            match = patt.search(nate_response)
            if match:
                subject_words = _extract_subject_words(match.group(0))
                client_introduced = any(
                    word.lower() in client_text_combined
                    for word in subject_words
                    if len(word) > 3
                )
                if client_introduced:
                    return {"safe": True, "note": "client_introduced_topic"}
                break

        logger.warning(
            "Layer 8 factual grounding: blocked assertion in response "
            "for user=%s session=%s",
            user_id, session_id,
        )

        if db_pool:
            try:
                await _validator.log_warnings(
                    warnings, nate_response,
                    session_id=session_id,
                    user_id=user_id,
                    odpe_signal="TENSION",
                )
            except Exception:
                pass

        return {
            "safe": False,
            "reason": "unverified_factual_assertion",
            "redirect": (
                "I want to be honest \u2014 I\u2019m not certain about the factual "
                "details there. What\u2019s coming up for you around this?"
            ),
        }
    except Exception as exc:
        logger.warning("validate_before_send error (non-fatal): %s", exc)
        return {"safe": True, "note": "validation_error"}
