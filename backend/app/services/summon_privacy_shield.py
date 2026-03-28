"""
Sovereignty Privacy Shield — Central privacy enforcement for all summon responses.

Blocks architecture probes, owner PII leaks, cross-user data contamination,
and applies family privacy rules. Used by NateSummonService before returning
any response to external doorways.
"""

import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

_ARCHITECTURE_PROBES = [
    re.compile(p, re.IGNORECASE) for p in [
        r"what (model|LLM|AI|engine|framework|architecture|database|server)",
        r"(run on|built with|powered by|using) (what|which)",
        r"\b(GPT|Claude|Llama|Gemini|grok|Azure|OpenAI|Anthropic)\b",
        r"how (are you|do you work|were you built|is your)",
        r"\b(tech stack|infrastructure|backend|codebase|source code)\b",
        r"what (language|programming|stack|cloud) (do you|are you)",
        r"(API|endpoint|webhook|websocket).*(architecture|design|structure)",
    ]
]

_OWNER_PROBES = [
    re.compile(p, re.IGNORECASE) for p in [
        r"(nathaniel|nevedal|big nate|dr\.?\s*nevedal|the owner|the founder|who (made|created|built|owns))",
        r"(email|phone|address|contact).*(owner|creator|founder|admin)",
        r"who (is|runs|manages|operates) (this|sovereign|the sanctuary|the platform)",
    ]
]

_PII_REDACTION_PATTERNS = [
    (re.compile(r"\b\d{3}[-.]?\d{2}[-.]?\d{4}\b"), "[REDACTED-SSN]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED-EMAIL]"),
    (re.compile(r"\b(?:\+1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b"), "[REDACTED-PHONE]"),
    (re.compile(r"\b\d{1,5}\s+\w+\s+(street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|way|court|ct)\b", re.I),
     "[REDACTED-ADDRESS]"),
]

_OWNER_NAME_VARIANTS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"\bnathan(iel)?\s+nevedal\b",
        r"\bdr\.?\s*nevedal\b",
        r"\bnevedal\b",
        r"\bnathan\.nevedal\b",
        r"\badmin_nevedalnj\b",
        r"\bDrNevedal1\b",
        r"\b68\.183\.168\.75\b",
    ]
]

ARCHITECTURE_DEFLECTION = (
    "I'm Little Nate — my focus is helping you, not discussing my internals. "
    "What can I help you with today?"
)

OWNER_DEFLECTION = (
    "For privacy, I can't share personal information about anyone. "
    "I'm here to help you — what's on your mind?"
)


class SovereigntyPrivacyShield:
    """Central privacy enforcement for all Nate summon interactions."""

    def __init__(self, db_pool=None):
        self.db_pool = db_pool

    async def filter_input(self, message: str) -> Tuple[str, bool, Optional[str]]:
        """Check user input for architecture or owner probes.

        Returns:
            (cleaned_message, is_blocked, deflection_response)
            If is_blocked is True, deflection_response contains the canned reply.
        """
        for pattern in _ARCHITECTURE_PROBES:
            if pattern.search(message):
                logger.info("Privacy shield: blocked architecture probe")
                return message, True, ARCHITECTURE_DEFLECTION

        for pattern in _OWNER_PROBES:
            if pattern.search(message):
                logger.info("Privacy shield: blocked owner probe")
                return message, True, OWNER_DEFLECTION

        return message, False, None

    async def filter_response(self, response: str, user: Optional[dict] = None) -> str:
        """Strip PII, owner references, and architecture leaks from AI output."""
        filtered = response

        for pattern in _OWNER_NAME_VARIANTS:
            filtered = pattern.sub("[the platform team]", filtered)

        for pattern, replacement in _PII_REDACTION_PATTERNS:
            filtered = pattern.sub(replacement, filtered)

        arch_leaks = [
            (re.compile(r"\bAzure OpenAI\b", re.I), "my AI capabilities"),
            (re.compile(r"\bFastAPI\b", re.I), "our platform"),
            (re.compile(r"\bPostgreSQL\b", re.I), "our data systems"),
            (re.compile(r"\bRedis\b", re.I), "our systems"),
            (re.compile(r"\bCloudflare\b", re.I), "our infrastructure"),
            (re.compile(r"\bDocker\b", re.I), "our systems"),
            (re.compile(r"\bFlutter\b", re.I), "our app"),
            (re.compile(r"\bPython\b", re.I), "our platform"),
            (re.compile(r"\basyncpg\b", re.I), "our data layer"),
        ]
        for pattern, replacement in arch_leaks:
            filtered = pattern.sub(replacement, filtered)

        return filtered

    async def apply_family_rules(self, response: str, user_id: str) -> str:
        """Apply family-scoped privacy rules if user is in a family."""
        if not self.db_pool:
            return response

        try:
            async with self.db_pool.acquire() as conn:
                family_id = await conn.fetchval(
                    """SELECT profile_data->>'family_id' FROM users
                       WHERE username = $1""",
                    user_id
                )
                if not family_id:
                    return response

                family_members = await conn.fetch(
                    """SELECT username, profile_data->>'name' as name
                       FROM users
                       WHERE profile_data->>'family_id' = $1
                         AND username != $2""",
                    family_id, user_id
                )

                for member in family_members:
                    name = member.get("name")
                    if name:
                        response = re.sub(
                            rf"\b{re.escape(name)}\b",
                            "[family member]",
                            response,
                            flags=re.I
                        )

        except Exception as e:
            logger.warning("Family rule application failed: %s", e)

        return response

    async def validate_cross_user_isolation(self, response: str, requesting_user: str) -> str:
        """Ensure no other user's data leaked into the response."""
        if not self.db_pool:
            return response

        try:
            async with self.db_pool.acquire() as conn:
                other_usernames = await conn.fetch(
                    """SELECT username FROM users
                       WHERE username != $1 AND role = 'CLIENT'
                       LIMIT 100""",
                    requesting_user
                )
                for row in other_usernames:
                    uname = row["username"]
                    if len(uname) > 3 and uname.lower() in response.lower():
                        response = re.sub(
                            rf"\b{re.escape(uname)}\b",
                            "[another user]",
                            response,
                            flags=re.I
                        )
        except Exception as e:
            logger.warning("Cross-user isolation check failed: %s", e)

        return response
