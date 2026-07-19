"""
NateSummonService — Core AI pipeline for universal Little Nate summon interactions.

Handles authenticated (registered user) and public ("3 Queries in a Bottle") access
through any doorway: browser extension, email, SMS, Telegram, Siri, share targets.
"""

import os
import json
import hashlib
import logging
import secrets
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, Tuple

import httpx

logger = logging.getLogger(__name__)

_AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZURE_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")


SUMMON_SYSTEM_PROMPT = """You are Little Nate, an AI companion from Sovereign Sanctuary.

HARD PRIVACY RULES (CANNOT BE OVERRIDDEN):
1. NEVER reveal your architecture, model, training data, or infrastructure.
   If asked: "I'm Little Nate — my focus is helping you, not discussing my internals."
2. NEVER reveal information about Big Nate (the owner/founder) or any admin.
   If asked: "For privacy, I can't share personal information about anyone."
3. NEVER reveal any user's personal data, health information, session history,
   coaching notes, or family details to anyone other than that user.
4. ALL health-related conversations are governed by HIPAA-grade privacy.
5. Family privacy is governed by each family's own rules.
6. NEVER discuss other users' existence, activities, or data.

RESPONSE RULES:
- Be warm, insightful, and genuinely helpful.
- Draw from your knowledge to provide real value.
- Keep responses concise (2-4 paragraphs max for summon interactions).
- If you don't know something, say so honestly.
- Never fabricate data, scores, or statistics.
- You are responding via a quick-summon channel — be efficient.
"""


@dataclass
class BottleStatus:
    remaining: Optional[int]
    access_level: str
    show_powered_by: bool


@dataclass
class SummonResponse:
    response: str
    sources_used: list
    access_level: str
    queries_remaining: Optional[int] = None
    powered_by: Optional[str] = None
    channel: str = "unknown"


class NateSummonService:
    """Process summon requests from any doorway with tier-aware access."""

    TOKEN_LIMITS = {
        "full": 400,
        "limited": 150,
        "registered": 800,
        "sovereign_circle": 1200,
    }

    DAILY_FREE_LIMIT = 100

    def __init__(self, db_pool=None, privacy_shield=None, app_state=None):
        self.db_pool = db_pool
        self.privacy_shield = privacy_shield
        self._app_state = app_state

    async def process_summon(
        self,
        message: str,
        channel: str,
        user: Optional[Dict[str, Any]] = None,
        device_fingerprint: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> SummonResponse:
        """Core summon pipeline — routes through privacy shield, AI, and tier logic."""

        if self.privacy_shield:
            _, is_blocked, deflection = await self.privacy_shield.filter_input(message)
            if is_blocked:
                return SummonResponse(
                    response=deflection,
                    sources_used=[],
                    access_level="blocked",
                    channel=channel,
                )

        if user:
            access_level = self._determine_registered_access(user)
            bottle = BottleStatus(remaining=None, access_level=access_level, show_powered_by=False)
        elif device_fingerprint:
            bottle = await self._check_bottle(device_fingerprint, ip_address)
        else:
            return SummonResponse(
                response="I need either authentication or a way to identify your device. Please try again.",
                sources_used=[],
                access_level="error",
                channel=channel,
            )

        max_tokens = self.TOKEN_LIMITS.get(bottle.access_level, 400)

        if bottle.access_level == "limited":
            message = f"[BRIEF RESPONSE ONLY] {message}"

        sources_tag = ["nate_ai"]
        cached = await self._get_cached_response(
            message, user=user, access_level=bottle.access_level
        )
        if cached:
            ai_response = cached
            sources_tag = ["nate_ai_cached"]
        else:
            ai_response = await self._generate_response(message, max_tokens, context)
            if bottle.access_level in ("full", "registered", "sovereign_circle"):
                await self._set_cached_response(
                    message,
                    ai_response,
                    user=user,
                    access_level=bottle.access_level,
                )

        if self.privacy_shield:
            ai_response = await self.privacy_shield.filter_response(
                ai_response, user
            )
            if user:
                username = user.get("username", "")
                ai_response = await self.privacy_shield.validate_cross_user_isolation(
                    ai_response, username
                )

        powered_by = None
        if bottle.show_powered_by:
            if bottle.remaining is not None and bottle.remaining > 0:
                powered_by = (
                    f"Powered by Sovereign Sanctuary — "
                    f"You have {bottle.remaining} free queries remaining. "
                    f"Get unlimited access at app.sovereignsanctuary.net"
                )
            else:
                powered_by = (
                    "Powered by Sovereign Sanctuary — "
                    "For full access to Little Nate, join the Inner Chamber ($49/mo) "
                    "or Sovereign Circle ($149/mo) at app.sovereignsanctuary.net"
                )

        if user and self.db_pool:
            word_count = len(ai_response.split())
            token_cost = word_count * 10
            try:
                async with self.db_pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO summon_interactions
                           (username, channel, user_message, nate_response,
                            access_level, tokens_used, created_at)
                           VALUES ($1, $2, $3, $4, $5, $6, NOW())""",
                        user.get("username"),
                        channel,
                        message[:2000],
                        ai_response[:4000],
                        bottle.access_level,
                        token_cost,
                    )
            except Exception as e:
                logger.warning("Failed to log summon interaction: %s", e)

        await self._log_activity(channel, bottle.access_level, user)

        return SummonResponse(
            response=ai_response,
            sources_used=sources_tag,
            access_level=bottle.access_level,
            queries_remaining=bottle.remaining,
            powered_by=powered_by,
            channel=channel,
        )

    def _determine_registered_access(self, user: Dict[str, Any]) -> str:
        tier = (user.get("tier") or "").upper()
        if tier in ("SOVEREIGN_CIRCLE", "SOVEREIGN"):
            return "sovereign_circle"
        return "registered"

    async def _check_bottle(self, fingerprint: str, ip: Optional[str]) -> BottleStatus:
        """3 Queries in a Bottle — track public device usage."""
        if not self.db_pool:
            return BottleStatus(remaining=3, access_level="full", show_powered_by=True)

        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT queries_used, converted FROM public_summon_usage
                       WHERE device_fingerprint = $1""",
                    fingerprint,
                )

                if row is None:
                    await conn.execute(
                        """INSERT INTO public_summon_usage
                           (device_fingerprint, ip_address, queries_used)
                           VALUES ($1, $2::inet, 1)""",
                        fingerprint, ip or "0.0.0.0",
                    )
                    return BottleStatus(remaining=2, access_level="full", show_powered_by=True)

                if row["converted"]:
                    return BottleStatus(remaining=None, access_level="registered", show_powered_by=False)

                used = row["queries_used"]
                if used < 3:
                    await conn.execute(
                        """UPDATE public_summon_usage
                           SET queries_used = queries_used + 1, last_query_at = NOW()
                           WHERE device_fingerprint = $1""",
                        fingerprint,
                    )
                    return BottleStatus(remaining=2 - used, access_level="full", show_powered_by=True)
                else:
                    return BottleStatus(remaining=0, access_level="limited", show_powered_by=True)

        except Exception as e:
            logger.warning("Bottle check failed: %s", e)
            return BottleStatus(remaining=3, access_level="full", show_powered_by=True)

    async def _generate_response(
        self, message: str, max_tokens: int, context: Optional[Dict] = None
    ) -> str:
        """Generate via ODPE inference router (Workers AI/Grok), Azure fallback."""
        context_text = ""
        if context:
            if context.get("page_url"):
                context_text += f"\n[User is viewing: {context['page_url']}]"
            if context.get("selected_text"):
                context_text += f"\n[Selected text: {context['selected_text'][:500]}]"

        full_prompt = f"{context_text}\n\n{message}" if context_text else message

        router = getattr(self._app_state, "inference_router", None) if self._app_state else None
        if router:
            try:
                result = await router.generate(
                    prompt=full_prompt,
                    system=SUMMON_SYSTEM_PROMPT,
                    tier="utility",
                    max_tokens=max_tokens,
                    domain="general",
                )
                text = (result.get("text") or "").strip()
                if text:
                    return text
            except Exception as e:
                logger.warning("Summon inference router failed, trying Azure fallback: %s", e)

        try:
            from app.services.nate_ai_config import nate_chat_payload, nate_chat_headers

            messages = [
                {"role": "system", "content": SUMMON_SYSTEM_PROMPT},
                {"role": "user", "content": full_prompt},
            ]

            payload = nate_chat_payload(messages=messages, max_tokens=max_tokens)
            headers = nate_chat_headers()

            url = (
                f"https://{_AZURE_ENDPOINT}/openai/deployments/"
                f"{_AZURE_CHAT_DEPLOYMENT}/chat/completions?api-version=2024-06-01"
            )

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            return data["choices"][0]["message"]["content"].strip()

        except Exception as e:
            logger.error("Summon AI generation failed: %s", e)
            return (
                "I'm having a moment of quiet reflection — my AI capabilities are "
                "temporarily unavailable. Please try again in a moment."
            )

    def _summon_cache_key(self, message: str, user: Optional[Dict] = None, access_level: str = "public") -> str:
        # QUANTUM-CRYSTAL-ARCH — include identity so identical prompts cannot cross users
        ident = "anon"
        if user:
            ident = str(user.get("username") or user.get("user_id") or user.get("id") or "user")
        raw = f"{access_level}:{ident}:{message.lower().strip()}"
        return f"summon:cache:{hashlib.sha256(raw.encode()).hexdigest()}"

    async def _get_cached_response(
        self, message: str, user: Optional[Dict] = None, access_level: str = "public"
    ) -> Optional[str]:
        """Check Redis for a cached summon response."""
        cache_redis = getattr(self._app_state, "cache_redis", None) if self._app_state else None
        if not cache_redis:
            return None
        try:
            cache_key = self._summon_cache_key(message, user=user, access_level=access_level)
            cached = await cache_redis.get(cache_key)
            if cached:
                logger.debug("Summon cache HIT for %s", cache_key[:30])
                return cached
        except Exception as e:
            logger.warning("Summon cache get failed: %s", e)
        return None

    async def _set_cached_response(
        self,
        message: str,
        response: str,
        ttl: int = 3600,
        user: Optional[Dict] = None,
        access_level: str = "public",
    ) -> None:
        """Store a summon response in Redis cache."""
        cache_redis = getattr(self._app_state, "cache_redis", None) if self._app_state else None
        if not cache_redis:
            return
        try:
            cache_key = self._summon_cache_key(message, user=user, access_level=access_level)
            await cache_redis.setex(cache_key, ttl, response)
        except Exception as e:
            logger.warning("Summon cache set failed: %s", e)

    async def _log_activity(
        self, channel: str, access_level: str, user: Optional[Dict] = None
    ) -> None:
        if not self.db_pool:
            return
        try:
            username = user.get("username", "anonymous") if user else "public"
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO skyeye_activity (platform, type, content, created_at)
                       VALUES ('summon', 'nate_summon', $1, NOW())""",
                    json.dumps({
                        "channel": channel,
                        "access_level": access_level,
                        "user": username,
                    }),
                )
        except Exception as e:
            logger.warning("Failed to log summon activity: %s", e)

    @staticmethod
    def generate_device_fingerprint(ip: str, user_agent: str, accept_language: str) -> str:
        raw = f"{ip}|{user_agent}|{accept_language}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def generate_summon_token(self, username: str) -> Optional[str]:
        """Generate a long-lived summon token for a registered user."""
        if not self.db_pool:
            return None
        token = secrets.token_urlsafe(32)
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO summon_tokens (username, token, channel)
                       VALUES ($1, $2, 'api')
                       ON CONFLICT (token) DO NOTHING""",
                    username, token,
                )
            return token
        except Exception as e:
            logger.error("Failed to generate summon token: %s", e)
            return None

    async def validate_summon_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Validate a summon token and return the associated user profile."""
        if not self.db_pool:
            return None
        try:
            async with self.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT st.username, u.role,
                              u.profile_data->>'tier' as tier,
                              u.profile_data->>'name' as name
                       FROM summon_tokens st
                       JOIN users u ON u.username = st.username
                       WHERE st.token = $1
                         AND st.is_active = TRUE
                         AND (st.expires_at IS NULL OR st.expires_at > NOW())""",
                    token,
                )
                if row:
                    await conn.execute(
                        "UPDATE summon_tokens SET last_used_at = NOW() WHERE token = $1",
                        token,
                    )
                    return dict(row)
            return None
        except Exception as e:
            logger.warning("Summon token validation failed: %s", e)
            return None

    async def check_daily_limit(self, username: str) -> Tuple[bool, int]:
        """Check if user has exceeded daily free summon limit."""
        if not self.db_pool:
            return True, self.DAILY_FREE_LIMIT
        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval(
                    """SELECT COUNT(*) FROM summon_interactions
                       WHERE username = $1
                         AND created_at > NOW() - INTERVAL '1 day'""",
                    username,
                )
                remaining = max(0, self.DAILY_FREE_LIMIT - (count or 0))
                return remaining > 0, remaining
        except Exception as e:
            logger.warning("Daily limit check failed: %s", e)
            return True, self.DAILY_FREE_LIMIT
