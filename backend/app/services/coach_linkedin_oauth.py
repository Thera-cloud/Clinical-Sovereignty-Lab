"""Per-coach LinkedIn OAuth. Tokens live on coach_linkedin_connection only.

Never reads or writes SkyEye platform tokens (NG19).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any, Dict, Optional

LINKEDIN_AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_ME = "https://api.linkedin.com/v2/me"
COACH_SCOPES = "openid profile email w_member_social"
SKYEYE_LINKEDIN_CALLBACK = "/api/skyeye/platforms/linkedin/callback"
COACH_LINKEDIN_CALLBACK = "/api/coach/integrations/linkedin/callback"

logger = logging.getLogger("coach_linkedin_oauth")


def _flag_on(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in ("1", "true", "yes")


def _public_api() -> str:
    return (os.getenv("PUBLIC_BASE_URL") or "https://api.sovereignsanctuary.net").rstrip("/")


def canonicalize_linkedin_redirect(uri: str) -> str:
    u = (uri or "").strip()
    if not u:
        return f"{_public_api()}{SKYEYE_LINKEDIN_CALLBACK}"
    for _ in range(4):
        nxt = u.replace(
            "https://api.sovereignsanctuary.net/api.sovereignsanctuary.net",
            "https://api.sovereignsanctuary.net",
        ).replace(
            "http://api.sovereignsanctuary.net/api.sovereignsanctuary.net",
            "https://api.sovereignsanctuary.net",
        )
        if nxt == u:
            break
        u = nxt
    if u.startswith("api.sovereignsanctuary.net"):
        u = "https://" + u
    if u.startswith("/"):
        u = _public_api() + u
    return u


def coach_linkedin_credentials() -> tuple:
    dedicated = (os.getenv("LINKEDIN_COACH_CLIENT_ID") or "").strip()
    if dedicated:
        cid = dedicated
        secret = (os.getenv("LINKEDIN_COACH_CLIENT_SECRET") or "").strip()
        redirect = os.getenv(
            "LINKEDIN_COACH_REDIRECT_URI",
            f"{_public_api()}{COACH_LINKEDIN_CALLBACK}",
        )
    else:
        cid = (os.getenv("LINKEDIN_CLIENT_ID") or "").strip()
        secret = (os.getenv("LINKEDIN_CLIENT_SECRET") or "").strip()
        # SkyEye posting app (77wz5scwctl85s) only has the SkyEye callback registered.
        redirect = os.getenv("LINKEDIN_COACH_REGISTERED_REDIRECT_URI") or (
            f"{_public_api()}{SKYEYE_LINKEDIN_CALLBACK}"
        )
    return cid, secret, canonicalize_linkedin_redirect(redirect)


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
            if not person_urn:
                async with session.get(
                    LINKEDIN_ME,
                    headers={"Authorization": f"Bearer {token}"},
                ) as me2:
                    me_data = await me2.json(content_type=None)
                pid = str(me_data.get("id") or "")
                if pid:
                    person_urn = f"urn:li:person:{pid}"
    return {
        "access_token": token,
        "refresh_token": refresh,
        "person_urn": person_urn,
    }


async def try_complete_coach_linkedin_callback(request, code: str, state: str) -> Optional[Any]:
    """If Redis has coach_li_oauth_state, persist that coach's token and redirect.

    Returns None when this is SkyEye admin OAuth (no coach state).
    Never writes skyeye_platform_tokens (NG19).
    """
    from fastapi.responses import RedirectResponse

    r = getattr(request.app.state, "auth_redis", None) or getattr(
        request.app.state, "redis_pool", None
    )
    if not r or not state:
        return None
    raw = await r.get(f"coach_li_oauth_state:{state}")
    if not raw:
        return None
    await r.delete(f"coach_li_oauth_state:{state}")
    meta = json.loads(raw if isinstance(raw, str) else raw.decode())
    hw = (meta.get("hardware_id") or "").strip()
    post = os.getenv(
        "LINKEDIN_COACH_POST_AUTH_REDIRECT",
        "https://coach.sovereignsanctuary.net/?linkedin=connected",
    )
    err = post.replace("=connected", "=error")
    if not hw:
        return RedirectResponse(url=err)
    pool = getattr(request.app.state, "db_pool", None)
    try:
        tokens = await exchange_coach_linkedin_code(code)
        if not tokens.get("access_token"):
            logger.warning("Coach LinkedIn token exchange returned no access_token")
            return RedirectResponse(url=err)
        await persist_coach_linkedin(pool, hw, tokens)
        return RedirectResponse(url=post)
    except Exception as exc:
        logger.warning("Coach LinkedIn callback failed: %s", exc)
        return RedirectResponse(url=err)


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
    cid, secret, _ = coach_linkedin_credentials()
    configured = bool(cid and secret)
    return {
        "connected": connected,
        "person_urn": person_urn,
        "oauth_enabled": _flag_on("ENABLE_COACH_LINKEDIN"),
        "connect_visible": True,
        "oauth_configured": configured,
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
