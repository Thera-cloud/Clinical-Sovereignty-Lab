"""Per-coach LinkedIn OAuth. Tokens live on coach_linkedin_connection only.

Never reads or writes SkyEye platform tokens (NG19).
"""

from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO = "https://api.linkedin.com/v2/userinfo"
COACH_SCOPES = "openid profile email w_member_social"


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def coach_linkedin_credentials() -> tuple:
    cid = (os.getenv("LINKEDIN_COACH_CLIENT_ID") or os.getenv("LINKEDIN_CLIENT_ID") or "").strip()
    secret = (
        os.getenv("LINKEDIN_COACH_CLIENT_SECRET") or os.getenv("LINKEDIN_CLIENT_SECRET") or ""
    ).strip()
    redirect = os.getenv(
        "LINKEDIN_COACH_REDIRECT_URI",
        "https://api.sovereignsanctuary.net/api/coach/integrations/linkedin/callback",
    )
    return cid, secret, redirect


def build_coach_linkedin_oauth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": COACH_SCOPES,
        "state": state,
    }
    return f"{LINKEDIN_AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_coach_linkedin_code(code: str) -> Dict[str, Any]:
    cid, secret, redirect = coach_linkedin_credentials()
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": cid,
                "client_secret": secret,
            },
        ) as resp:
            data = await resp.json(content_type=None)
        token = data.get("access_token") or ""
        refresh = data.get("refresh_token") or ""
        person_urn = ""
        if token:
            async with session.get(
                LINKEDIN_USERINFO,
                headers={"Authorization": f"Bearer {token}"},
            ) as me:
                info = await me.json(content_type=None)
            sub = str(info.get("sub") or "")
            if sub.startswith("urn:"):
                person_urn = sub
            elif sub:
                person_urn = f"urn:li:person:{sub}"
    return {
        "access_token": token,
        "refresh_token": refresh,
        "person_urn": person_urn,
    }


async def persist_coach_linkedin(db_pool, coach_id: str, tokens: Dict[str, Any]) -> None:
    from app.services.skyeye_platform_base import TokenCipher

    cipher = TokenCipher.get()
    access = tokens.get("access_token") or ""
    refresh = tokens.get("refresh_token") or ""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO coach_linkedin_connection
              (coach_id, access_token, refresh_token, person_urn, revoked_at, updated_at)
            VALUES ($1, $2, $3, $4, NULL, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              access_token = EXCLUDED.access_token,
              refresh_token = EXCLUDED.refresh_token,
              person_urn = EXCLUDED.person_urn,
              revoked_at = NULL,
              updated_at = NOW()
            """,
            coach_id,
            cipher.encrypt(access),
            cipher.encrypt(refresh) if refresh else None,
            tokens.get("person_urn") or "",
        )


async def coach_linkedin_status(db_pool, coach_id: str) -> Dict[str, Any]:
    connected = False
    person_urn = ""
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT person_urn, revoked_at FROM coach_linkedin_connection
                WHERE coach_id = $1
                """,
                coach_id,
            )
        if row and row["revoked_at"] is None:
            connected = True
            person_urn = row["person_urn"] or ""
    return {
        "connected": connected,
        "person_urn": person_urn,
        "oauth_enabled": _flag_on("ENABLE_COACH_LINKEDIN"),
        "connect_visible": _flag_on("ENABLE_COACH_LINKEDIN"),
        "skyeye_fallback": False,
    }


async def revoke_coach_linkedin(db_pool, coach_id: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "connected": False}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE coach_linkedin_connection
            SET revoked_at = NOW(), updated_at = NOW()
            WHERE coach_id = $1 AND revoked_at IS NULL
            """,
            coach_id,
        )
    return {"ok": True, "connected": False, "skyeye_fallback": False}
