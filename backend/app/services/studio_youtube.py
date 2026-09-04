"""S3 per-coach YouTube OAuth + upload when media exists. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("studio_youtube")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YT_API_BASE = "https://www.googleapis.com/youtube/v3"
SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload "
    "https://www.googleapis.com/auth/youtube.readonly "
    "https://www.googleapis.com/auth/youtube"
)


def _client() -> tuple[str, str]:
    cid = os.getenv("YOUTUBE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    secret = os.getenv("YOUTUBE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or ""
    return cid, secret


def _redirect() -> str:
    return os.getenv(
        "STUDIO_YOUTUBE_REDIRECT_URI",
        "https://api.sovereignsanctuary.net/api/studio/youtube/callback",
    )


def _secret() -> bytes:
    return (os.getenv("JWT_SECRET") or os.getenv("SKYEYE_TOKEN_ENCRYPTION_KEY") or "studio-yt").encode()


def _sign_state(coach_id: str) -> str:
    raw = json.dumps({"c": coach_id, "e": int(time.time()) + 600}, separators=(",", ":"))
    b = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{b}.{sig}"


def parse_state(state: str) -> Optional[str]:
    try:
        b, sig = (state or "").split(".", 1)
        expect = hmac.new(_secret(), b.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expect, sig):
            return None
        pad = "=" * (-len(b) % 4)
        data = json.loads(base64.urlsafe_b64decode(b + pad))
        if int(data.get("e") or 0) < int(time.time()):
            return None
        return str(data.get("c") or "") or None
    except Exception:
        return None


async def oauth_status(db_pool, coach_id: str) -> Dict[str, Any]:
    connected = False
    channel = ""
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT channel_name FROM studio_youtube_connection
                WHERE coach_id = $1 AND refresh_ciphertext IS NOT NULL
                """,
                coach_id,
            )
            connected = bool(row)
            if row:
                channel = row.get("channel_name") or ""
    cid, _ = _client()
    return {
        "status": "ok",
        "connected": connected,
        "phase": "S3",
        "oauth_configured": bool(cid),
        "channel_owned_by": "coach",
        "channel_name": channel,
        "can_create_live": connected,
        "live_hint": (
            "Go live creates a YouTube Live event on this channel and writes the RTMP ingest. "
            "If Google returns insufficient permissions, tap Connect YouTube again to grant live access."
        ),
    }


def connect_url(coach_id: str) -> Dict[str, Any]:
    cid, secret = _client()
    if not cid or not secret:
        return {"ok": False, "reason": "youtube oauth not configured", "code": 503}
    state = _sign_state(coach_id)
    params = {
        "client_id": cid,
        "redirect_uri": _redirect(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"ok": True, "url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}", "state": state}


async def store_tokens(db_pool, coach_id: str, refresh_cipher: str) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO studio_youtube_connection (coach_id, refresh_ciphertext, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (coach_id) DO UPDATE SET
              refresh_ciphertext = EXCLUDED.refresh_ciphertext,
              updated_at = NOW()
            """,
            coach_id,
            refresh_cipher,
        )
    return {"ok": True, "connected": True}


async def exchange_code(db_pool, code: str, state: str) -> Dict[str, Any]:
    coach_id = parse_state(state)
    if not coach_id:
        return {"ok": False, "reason": "invalid_state", "code": 400}
    cid, secret = _client()
    if not cid or not secret:
        return {"ok": False, "reason": "youtube oauth not configured", "code": 503}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": cid,
                    "client_secret": secret,
                    "redirect_uri": _redirect(),
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
        if "access_token" not in data:
            return {
                "ok": False,
                "reason": data.get("error_description") or "token_exchange_failed",
                "code": 400,
            }
        from app.services.skyeye_platform_base import TokenCipher

        cipher = TokenCipher.get()
        refresh = data.get("refresh_token") or ""
        access = data["access_token"]
        channel_id = ""
        channel_name = ""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                ch = await client.get(
                    f"{YT_API_BASE}/channels",
                    params={"part": "snippet", "mine": "true"},
                    headers={"Authorization": f"Bearer {access}"},
                )
                items = (ch.json() or {}).get("items") or []
                if items:
                    channel_id = items[0].get("id") or ""
                    channel_name = ((items[0].get("snippet") or {}).get("title")) or ""
        except Exception as exc:
            logger.warning("studio youtube channel lookup: %s", exc)
        if not db_pool:
            return {"ok": True, "connected": True, "dry": True, "coach_id": coach_id}
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO studio_youtube_connection
                  (coach_id, refresh_ciphertext, access_ciphertext, channel_id, channel_name, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                ON CONFLICT (coach_id) DO UPDATE SET
                  refresh_ciphertext = COALESCE(EXCLUDED.refresh_ciphertext, studio_youtube_connection.refresh_ciphertext),
                  access_ciphertext = EXCLUDED.access_ciphertext,
                  channel_id = COALESCE(EXCLUDED.channel_id, studio_youtube_connection.channel_id),
                  channel_name = COALESCE(EXCLUDED.channel_name, studio_youtube_connection.channel_name),
                  updated_at = NOW()
                """,
                coach_id,
                cipher.encrypt(refresh) if refresh else None,
                cipher.encrypt(access),
                channel_id or None,
                channel_name or None,
            )
        return {"ok": True, "connected": True, "coach_id": coach_id, "channel_name": channel_name}
    except Exception as exc:
        logger.warning("studio youtube exchange: %s", exc)
        return {"ok": False, "reason": str(exc)[:160], "code": 400}


async def upload_episode(db_pool, coach_id: str, episode_id: str) -> Dict[str, Any]:
    status = await oauth_status(db_pool, coach_id)
    if not status.get("connected"):
        return {"ok": False, "reason": "youtube_not_connected", "code": 409}
    media_key = None
    title = "Studio episode"
    show_id = ""
    if db_pool:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT e.id, e.title, e.media_r2_key, e.youtube_video_id, e.show_id,
                       e.session_id
                FROM studio_episodes e
                JOIN studio_shows s ON s.id = e.show_id
                WHERE e.id = $1::uuid AND s.coach_id = $2
                """,
                episode_id,
                coach_id,
            )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        if row.get("youtube_video_id"):
            return {
                "ok": True,
                "uploaded": True,
                "already": True,
                "video_id": row["youtube_video_id"],
            }
        media_key = row.get("media_r2_key")
        if not media_key and row.get("session_id"):
            from app.services.studio_media_tape import attach_session_media_key

            tape = await attach_session_media_key(db_pool, str(row["session_id"]))
            media_key = (tape.get("media_r2_key") or "").strip() or None
            if media_key:
                async with db_pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE studio_episodes
                        SET media_r2_key = COALESCE(media_r2_key, $2),
                            media_master_r2_key = COALESCE(media_master_r2_key, $2)
                        WHERE id = $1::uuid
                        """,
                        episode_id,
                        media_key,
                    )
        title = row.get("title") or title
        show_id = str(row.get("show_id") or "")
    if not media_key:
        return {
            "ok": True,
            "uploaded": False,
            "dry_run": False,
            "reason": "no_media",
            "oauth_ready": True,
            "episode_id": episode_id,
            "destination": "coach_channel",
        }
    pushed = await _upload_r2_media(db_pool, coach_id, episode_id, media_key, title)
    if pushed.get("uploaded"):
        if show_id:
            from app.services.studio_meter import add_youtube_push

            await add_youtube_push(db_pool, show_id)
        return pushed
    return {
        "ok": True,
        "uploaded": False,
        "queued": True,
        "media_r2_key": media_key,
        "title": title,
        "destination": "coach_channel",
        "reason": pushed.get("reason") or "r2_or_youtube_unavailable",
    }


async def _upload_r2_media(
    db_pool, coach_id: str, episode_id: str, media_key: str, title: str
) -> Dict[str, Any]:
    try:
        from app.services.r2_storage import download_bytes_async

        blob = await download_bytes_async(key=media_key)
    except Exception as exc:
        logger.warning("studio youtube r2: %s", exc)
        return {"uploaded": False, "reason": "r2_read_failed"}
    if not blob:
        return {"uploaded": False, "reason": "r2_empty"}
    token = await _access_token(db_pool, coach_id)
    if not token:
        return {"uploaded": False, "reason": "youtube_token"}
    try:
        import httpx

        meta = {"snippet": {"title": title[:90], "description": "Sovereign Studio episode"}, "status": {"privacyStatus": "unlisted"}}
        async with httpx.AsyncClient(timeout=60) as client:
            init = await client.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/mp4",
                    "X-Upload-Content-Length": str(len(blob)),
                },
                json=meta,
            )
            loc = init.headers.get("Location") or ""
            if init.status_code >= 400 or not loc:
                return {"uploaded": False, "reason": f"yt_init_{init.status_code}"}
            put = await client.put(loc, content=blob, headers={"Content-Type": "video/mp4"})
            body = put.json() if put.headers.get("content-type", "").startswith("application/json") else {}
            vid = (body or {}).get("id")
        if not vid:
            return {"uploaded": False, "reason": f"yt_put_{put.status_code}"}
        if db_pool:
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "UPDATE studio_episodes SET youtube_video_id = $2 WHERE id = $1::uuid",
                    episode_id,
                    vid,
                )
        return {"ok": True, "uploaded": True, "video_id": vid, "destination": "coach_channel"}
    except Exception as exc:
        logger.warning("studio youtube upload: %s", exc)
        return {"uploaded": False, "reason": "yt_upload_failed"}


async def _access_token(db_pool, coach_id: str) -> str:
    if not db_pool:
        return ""
    try:
        from app.services.skyeye_platform_base import TokenCipher

        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT access_ciphertext, refresh_ciphertext
                FROM studio_youtube_connection WHERE coach_id = $1
                """,
                coach_id,
            )
        if not row:
            return ""
        cipher = TokenCipher.get()
        access = ""
        if row.get("access_ciphertext"):
            access = cipher.decrypt(row["access_ciphertext"]) or ""
        if access:
            return access
        refresh = cipher.decrypt(row["refresh_ciphertext"]) if row.get("refresh_ciphertext") else ""
        if not refresh:
            return ""
        cid, secret = _client()
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "refresh_token": refresh,
                    "client_id": cid,
                    "client_secret": secret,
                    "grant_type": "refresh_token",
                },
            )
            return (resp.json() or {}).get("access_token") or ""
    except Exception as exc:
        logger.warning("studio youtube access: %s", exc)
        return ""


def _yt_error(data: Any) -> str:
    err = (data or {}).get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        errors = err.get("errors") or []
        if errors and isinstance(errors[0], dict):
            return str(errors[0].get("reason") or errors[0].get("message") or "")[:160]
        return str(err.get("message") or err.get("status") or "")[:160]
    return ""


async def go_live(
    db_pool,
    coach_id: str,
    show_id: str,
    title: str = "",
    privacy: str = "unlisted",
) -> Dict[str, Any]:
    """Create a Live event on the coach's connected channel and store RTMP. QUANTUM-CRYSTAL-ARCH"""
    status = await oauth_status(db_pool, coach_id)
    if not status.get("connected"):
        return {"ok": False, "reason": "youtube_not_connected", "code": 409}
    vis = (privacy or "unlisted").strip().lower()
    if vis not in {"unlisted", "public"}:
        vis = "unlisted"
    token = await _access_token(db_pool, coach_id)
    if not token:
        return {"ok": False, "reason": "youtube_token", "code": 409}
    name = (title or "").strip()[:90] or "Sovereign Studio live"
    from datetime import datetime, timedelta, timezone

    start = (datetime.now(timezone.utc) + timedelta(seconds=20)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        import httpx

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30) as client:
            br = await client.post(
                f"{YT_API_BASE}/liveBroadcasts",
                params={"part": "snippet,status,contentDetails"},
                headers=headers,
                json={
                    "snippet": {"title": name, "scheduledStartTime": start},
                    "status": {"privacyStatus": vis, "selfDeclaredMadeForKids": False},
                    "contentDetails": {
                        "enableAutoStart": True,
                        "enableAutoStop": True,
                        "enableDvr": True,
                    },
                },
            )
            br_data = br.json() if br.headers.get("content-type", "").startswith("application/json") else {}
            if br.status_code >= 400:
                reason = _yt_error(br_data) or f"yt_broadcast_{br.status_code}"
                code = 409 if "insufficient" in reason.lower() or br.status_code == 403 else 400
                return {
                    "ok": False,
                    "reason": "reconnect_youtube" if code == 409 else reason,
                    "detail": reason,
                    "code": code,
                }
            broadcast_id = br_data.get("id") or ""
            st = await client.post(
                f"{YT_API_BASE}/liveStreams",
                params={"part": "snippet,cdn"},
                headers=headers,
                json={
                    "snippet": {"title": name},
                    "cdn": {
                        "frameRate": "variable",
                        "ingestionType": "rtmp",
                        "resolution": "variable",
                    },
                },
            )
            st_data = st.json() if st.headers.get("content-type", "").startswith("application/json") else {}
            if st.status_code >= 400:
                reason = _yt_error(st_data) or f"yt_stream_{st.status_code}"
                return {"ok": False, "reason": reason, "code": 400}
            stream_id = st_data.get("id") or ""
            info = ((st_data.get("cdn") or {}).get("ingestionInfo") or {})
            ingest = (info.get("ingestionAddress") or "").rstrip("/")
            key = info.get("streamName") or ""
            rtmp_url = f"{ingest}/{key}" if ingest and key else ""
            if not rtmp_url:
                return {"ok": False, "reason": "yt_ingest_missing", "code": 502}
            if broadcast_id and stream_id:
                bound = await client.post(
                    f"{YT_API_BASE}/liveBroadcasts/bind",
                    params={
                        "id": broadcast_id,
                        "streamId": stream_id,
                        "part": "id,contentDetails,status",
                    },
                    headers=headers,
                )
                if bound.status_code >= 400:
                    logger.warning("studio youtube bind %s", bound.status_code)
            from app.services.studio_tier2 import store_rtmp

            stored = await store_rtmp(db_pool, show_id, coach_id, rtmp_url)
            if not stored.get("ok"):
                return stored
            watch_url = f"https://www.youtube.com/watch?v={broadcast_id}" if broadcast_id else ""
            return {
                "ok": True,
                "live": True,
                "broadcast_id": broadcast_id,
                "stream_id": stream_id,
                "rtmp_set": True,
                "watch_url": watch_url,
                "privacy": vis,
                "channel_name": status.get("channel_name") or "",
                "destination": "coach_channel",
            }
    except Exception as exc:
        logger.warning("studio youtube go_live: %s", exc)
        return {"ok": False, "reason": "yt_live_failed", "code": 400}


async def upload_dry_run(db_pool, coach_id: str, episode_id: str) -> Dict[str, Any]:
    return await upload_episode(db_pool, coach_id, episode_id)
