"""S4 LiveKit + INV-2 guest audio-only. JWT if env set. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from app.services.studio_invariants import guest_video_allowed

DELAY_S = 45
EGRESS_HTTP_TIMEOUT_S = 30
_EGRESS_ACTIVE = {0, 1, 2, "0", "1", "2", "EGRESS_STARTING", "EGRESS_ACTIVE", "EGRESS_ENDING"}

_ROOM_FILE = Path(__file__).with_name("studio_livekit_room.html")
ROOM_HTML = _ROOM_FILE.read_text(encoding="utf-8") if _ROOM_FILE.is_file() else ""


def room_origin() -> str:
    return os.getenv("STUDIO_ROOM_ORIGIN", "https://coach.sovereignsanctuary.net").rstrip("/")


def room_embed_url(lk_url: str, token: str, role: str, session_id: str = "") -> str:
    api = os.getenv("STUDIO_API_ORIGIN", "https://api.sovereignsanctuary.net").rstrip("/")
    q = urlencode(
        {
            "url": lk_url or "",
            "token": token or "",
            "role": role or "host",
            "session": session_id or "",
            "api": api,
        }
    )
    return f"{room_origin()}/studio_nate_room.html?v=20260902u#{q}"


def verify_livekit_jwt(token: str) -> Dict[str, Any]:
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    key = os.getenv("LIVEKIT_API_KEY", "")
    parts = (token or "").split(".")
    if len(parts) != 3 or not secret:
        return {"ok": False, "reason": "bad_token"}
    h, p, s = parts
    expect = _b64(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expect, s):
        return {"ok": False, "reason": "bad_sig"}

    def _pad(raw: str) -> str:
        return raw + "=" * (-len(raw) % 4)

    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad(p)))
    except Exception:
        return {"ok": False, "reason": "bad_payload"}
    if int(payload.get("exp") or 0) < int(time.time()):
        return {"ok": False, "reason": "expired"}
    if key and payload.get("iss") != key:
        return {"ok": False, "reason": "iss"}
    room = str((payload.get("video") or {}).get("room") or "")
    sid = room[7:] if room.startswith("studio-") else ""
    return {
        "ok": True,
        "room": room,
        "session_id": sid,
        "identity": str(payload.get("sub") or ""),
    }


def session_media_r2_key(session_id: str) -> str:
    sid = (session_id or "").strip()
    return f"studio/{sid}.mp4" if sid else ""


def session_cut_r2_key(session_id: str) -> str:
    sid = (session_id or "").strip()
    return f"studio/{sid}/cut.mp4" if sid else ""


def egress_plan(session_id: str, rtmp_url: str = "", live_unlocked: bool = False) -> Dict[str, Any]:
    return {
        "ok": True,
        "session_id": session_id,
        "delay_s": DELAY_S,
        "composited": True,
        "avatar": "audio_envelope",
        "photoreal": False,
        "rtmp": bool(rtmp_url) and live_unlocked,
        "rtmp_url_set": bool(rtmp_url),
        "dump_cuts_delayed_output": True,
        "installed": bool(os.getenv("LIVEKIT_INTERNAL_URL")),
        "media_r2_key": session_media_r2_key(session_id),
    }


def _probe_internal() -> Dict[str, Any]:
    internal = (os.getenv("LIVEKIT_INTERNAL_URL") or "").rstrip("/")
    if not internal:
        return {"reachable": False, "reason": "unset"}
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(internal + "/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return {"reachable": True, "code": int(resp.status)}
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code:
            return {"reachable": True, "code": int(code)}
        return {"reachable": False, "reason": str(exc)[:80]}


def mint_api_jwt(*, api_key: str, api_secret: str, room: str = "", ttl_s: int = 120) -> str:
    """Server Twirp grants (List/Record). Distinct from participant join JWTs."""
    now = int(time.time())
    video: Dict[str, Any] = {
        "roomCreate": True,
        "roomList": True,
        "roomRecord": True,
        "roomAdmin": True,
        "roomJoin": True,
    }
    if room:
        video["room"] = room
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "nbf": now - 10,
        "exp": now + ttl_s,
        "video": video,
    }
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    p = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(api_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64(sig)}"


def verify_livekit_webhook(auth_header: str, raw_body: bytes) -> Dict[str, Any]:
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    key = os.getenv("LIVEKIT_API_KEY", "")
    if not secret or not key:
        return {"ok": False, "reason": "livekit_not_configured"}
    token = (auth_header or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not token:
        return {"ok": False, "reason": "missing_auth"}
    checked = verify_livekit_jwt(token)
    if not checked.get("ok"):
        return {"ok": False, "reason": checked.get("reason") or "bad_token"}

    def _pad(raw: str) -> str:
        return raw + "=" * (-len(raw) % 4)

    try:
        payload = json.loads(base64.urlsafe_b64decode(_pad(token.split(".")[1])))
    except Exception:
        return {"ok": False, "reason": "bad_payload"}
    claimed = str(payload.get("sha256") or payload.get("sha_256") or "").strip()
    if claimed:
        digest = hashlib.sha256(raw_body or b"").hexdigest()
        if not hmac.compare_digest(claimed.lower(), digest.lower()):
            return {"ok": False, "reason": "bad_body_hash"}
    return {"ok": True}


def _lk_creds() -> tuple[str, str, str]:
    return (
        (os.getenv("LIVEKIT_INTERNAL_URL") or "").rstrip("/"),
        os.getenv("LIVEKIT_API_KEY", ""),
        os.getenv("LIVEKIT_API_SECRET", ""),
    )


async def _twirp(path: str, body: Dict[str, Any], *, room: str = "", timeout: float = 8.0) -> Dict[str, Any]:
    internal, key, secret = _lk_creds()
    if not internal or not key or not secret:
        return {"ok": False, "reason": "livekit_not_configured", "http": 0}
    token = mint_api_jwt(api_key=key, api_secret=secret, room=room)
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{internal}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        data: Any = {}
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {"raw": (resp.text or "")[:240]}
        return {
            "ok": resp.status_code < 400,
            "http": resp.status_code,
            "data": data,
            "text": (resp.text or "")[:240],
        }
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:120], "http": 0}


def _probe_egress_worker() -> bool:
    internal, key, secret = _lk_creds()
    if not internal or not key or not secret:
        return False
    try:
        import urllib.request

        token = mint_api_jwt(api_key=key, api_secret=secret)
        req = urllib.request.Request(
            f"{internal}/twirp/livekit.Egress/ListEgress",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            return int(resp.status) < 400
    except Exception as exc:
        code = getattr(exc, "code", None)
        return bool(code and int(code) < 400)


def _active_egress_id(data: Dict[str, Any]) -> str:
    items = data.get("items") or data.get("egress_info") or data.get("egressInfo") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        status_s = str(status or "").upper()
        if status in _EGRESS_ACTIVE or status_s in _EGRESS_ACTIVE:
            return str(item.get("egress_id") or item.get("egressId") or "")
    return ""


def _publisher_count(data: Dict[str, Any]) -> int:
    parts = data.get("participants") or []
    if not isinstance(parts, list):
        return 0
    n = 0
    for part in parts:
        if not isinstance(part, dict):
            continue
        ident = str(part.get("identity") or part.get("sid") or "")
        if ident.startswith("egress") or ident == "egress":
            continue
        n += 1
    return n


def health() -> Dict[str, Any]:
    url = os.getenv("LIVEKIT_URL", "")
    internal = os.getenv("LIVEKIT_INTERNAL_URL", "")
    probe = _probe_internal()
    ready = bool(url) and bool(os.getenv("LIVEKIT_API_KEY")) and probe.get("reachable")
    return {
        "status": "ok" if ready else "pending",
        "url_configured": bool(url),
        "jwt_configured": bool(os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")),
        "allow_video_guest": False,
        "node": "orange",
        "installed": bool(internal),
        "internal_configured": bool(internal),
        "internal_reachable": bool(probe.get("reachable")),
        "internal_probe": probe,
        "room_origin": room_origin(),
        "sip_uri_set": bool(os.getenv("LIVEKIT_SIP_URI")),
        "egress_worker": bool(_probe_egress_worker()),
    }


def reject_guest_video(role: str, video_track_key: Optional[str]) -> Dict[str, Any]:
    if guest_video_allowed(role, video_track_key):
        return {"ok": True}
    return {"ok": False, "reason": "INV-2 guest video forbidden", "code": 422}


def join_token_stub(session_id: str, role: str) -> Dict[str, Any]:
    if role == "guest":
        return {
            "ok": True,
            "session_id": session_id,
            "role": "guest",
            "allowed_media_kinds": ["audio"],
            "allow_video": False,
        }
    return {
        "ok": True,
        "session_id": session_id,
        "role": role,
        "allowed_media_kinds": ["audio", "video"],
    }


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_livekit_jwt(
    *,
    api_key: str,
    api_secret: str,
    room: str,
    identity: str,
    role: str,
    ttl_s: int = 28800,
) -> str:
    now = int(time.time())
    can_video = role != "guest"
    # Omit canPublishSources for host — string names decode as UNKNOWN and
    # canvas captureStream is screen_share, not camera. Guest: proto MICROPHONE=2.
    video = {
        "roomJoin": True,
        "room": room,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
        "roomRecord": True,
        "roomAdmin": can_video,
    }
    if not can_video:
        video["canPublishSources"] = [2]
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": api_key,
        "sub": identity or role,
        "nbf": now - 10,
        "exp": now + ttl_s,
        "video": video,
    }
    h = _b64(json.dumps(header, separators=(",", ":")).encode())
    p = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(api_secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64(sig)}"


def parse_egress_event(body: Dict[str, Any]) -> Dict[str, Any]:
    raw = body or {}
    event = str(raw.get("event") or raw.get("event_type") or "").strip()
    info = raw.get("egressInfo") or raw.get("egress_info") or raw
    if not isinstance(info, dict):
        info = {}
    room = str(info.get("roomName") or info.get("room_name") or raw.get("room") or "")
    sid = room[7:] if room.startswith("studio-") else ""
    file_obj: Any = info.get("file") or info.get("fileResults") or info.get("file_results") or {}
    if isinstance(file_obj, list) and file_obj:
        file_obj = file_obj[0]
    if not isinstance(file_obj, dict):
        file_obj = {}
    filepath = str(
        file_obj.get("filename")
        or file_obj.get("filepath")
        or info.get("filepath")
        or ""
    )
    if not sid and filepath.startswith("studio/") and filepath.endswith(".mp4"):
        mid = filepath[7:-4]
        if "/" not in mid:
            sid = mid
    egress_id = str(
        info.get("egressId") or info.get("egress_id") or raw.get("egress_id") or ""
    )
    status = info.get("status")
    if status is None:
        status = raw.get("status")
    status_s = str(status or "").upper()
    failed = status in (4, 5, 6, "4", "5", "6") or status_s in (
        "EGRESS_FAILED",
        "EGRESS_ABORTED",
        "EGRESS_LIMIT_REACHED",
    )
    complete = (not failed) and (
        event in ("egress_ended", "egress_complete", "egress_finished")
        or status in (3, "3")
        or status_s == "EGRESS_COMPLETE"
    )
    return {
        "event": event or "unknown",
        "session_id": sid,
        "egress_id": egress_id,
        "complete": bool(complete and sid),
        "media_r2_key": session_media_r2_key(sid) if sid else "",
        "failed": failed,
    }


def handle_event(body: Dict[str, Any]) -> Dict[str, Any]:
    parsed = parse_egress_event(body)
    return {
        "ok": True,
        "event": parsed.get("event") or "unknown",
        "allow_video_guest": False,
        "installed": bool(os.getenv("LIVEKIT_INTERNAL_URL")),
        "session_id": parsed.get("session_id") or "",
        "egress_id": parsed.get("egress_id") or "",
        "complete": bool(parsed.get("complete")),
        "media_r2_key": parsed.get("media_r2_key") or "",
    }


async def start_room_egress(
    session_id: str, rtmp_url: str = "", live_unlocked: bool = False
) -> Dict[str, Any]:
    plan = egress_plan(session_id, rtmp_url=rtmp_url, live_unlocked=live_unlocked)
    plan["started"] = False
    internal, key, secret = _lk_creds()
    if not internal or not key or not secret:
        plan["reason"] = "livekit_not_configured"
        return plan
    room = f"studio-{session_id}"
    listed = await _twirp(
        "/twirp/livekit.Egress/ListEgress",
        {"room": room},
        room=room,
        timeout=5.0,
    )
    if listed.get("ok"):
        existing = _active_egress_id(listed.get("data") or {})
        if existing:
            plan["started"] = True
            plan["egress_id"] = existing
            plan["http"] = listed.get("http")
            plan["reason"] = "already"
            plan["r2"] = bool(os.getenv("R2_ACCOUNT_ID") and os.getenv("R2_ACCESS_KEY_ID"))
            return plan
    elif listed.get("reason") == "livekit_not_configured":
        plan["reason"] = "livekit_not_configured"
        return plan
    elif listed.get("http") in (500, 501, 502, 503) or "panic" in (
        str(listed.get("text") or "")
    ).lower():
        plan["reason"] = "egress_worker_or_api"
        plan["http"] = listed.get("http")
        plan["egress_reply"] = listed.get("text") or ""
        return plan
    people = await _twirp(
        "/twirp/livekit.RoomService/ListParticipants",
        {"room": room},
        room=room,
        timeout=5.0,
    )
    if people.get("ok") and _publisher_count(people.get("data") or {}) < 1:
        plan["reason"] = "room_empty"
        plan["http"] = people.get("http")
        return plan
    if not people.get("ok") and people.get("http") in (400, 404):
        plan["reason"] = "room_empty"
        plan["http"] = people.get("http")
        return plan
    file_out: Dict[str, Any] = {
        "file_type": "MP4",
        "filepath": f"studio/{session_id}.mp4",
    }
    acct = os.getenv("R2_ACCOUNT_ID", "")
    r2_key = os.getenv("R2_ACCESS_KEY_ID", "")
    r2_secret = os.getenv("R2_SECRET_ACCESS_KEY", "")
    bucket = os.getenv("R2_DEFAULT_BUCKET", "nate-vault")
    if acct and r2_key and r2_secret:
        file_out["s3"] = {
            "access_key": r2_key,
            "secret": r2_secret,
            "region": "auto",
            "endpoint": f"https://{acct}.r2.cloudflarestorage.com",
            "bucket": bucket,
            "force_path_style": True,
        }
        plan["r2"] = True
    body: Dict[str, Any] = {
        "room_name": room,
        "layout": "speaker",
        "audio_only": False,
        "file_outputs": [file_out],
    }
    if rtmp_url and live_unlocked:
        body["stream_outputs"] = [{"protocol": "RTMP", "urls": [rtmp_url]}]
    started = await _twirp(
        "/twirp/livekit.Egress/StartRoomCompositeEgress",
        body,
        room=room,
        timeout=float(EGRESS_HTTP_TIMEOUT_S),
    )
    plan["http"] = started.get("http")
    plan["egress_reply"] = started.get("text") or ""
    data = started.get("data") if isinstance(started.get("data"), dict) else {}
    eid = str((data or {}).get("egress_id") or (data or {}).get("egressId") or "")
    plan["egress_id"] = eid
    plan["started"] = bool(started.get("ok") and eid)
    if not plan["started"]:
        plan["reason"] = started.get("reason") or "egress_worker_or_api"
    return plan


async def stop_room_egress(egress_id: str, session_id: str = "") -> Dict[str, Any]:
    eid = (egress_id or "").strip()
    out: Dict[str, Any] = {"ok": True, "stopped": False, "egress_id": eid}
    if not eid:
        out["reason"] = "no_egress_id"
        return out
    room = f"studio-{session_id}" if session_id else ""
    stopped = await _twirp(
        "/twirp/livekit.Egress/StopEgress",
        {"egress_id": eid},
        room=room,
        timeout=20.0,
    )
    out["http"] = stopped.get("http")
    out["stopped"] = bool(stopped.get("ok"))
    if not out["stopped"]:
        out["reason"] = stopped.get("reason") or "egress_stop"
    return out


async def stop_session_egress(session_id: str, egress_id: str = "") -> Dict[str, Any]:
    sid = (session_id or "").strip()
    ids: list[str] = []
    if (egress_id or "").strip():
        ids.append(egress_id.strip())
    if sid:
        room = f"studio-{sid}"
        listed = await _twirp(
            "/twirp/livekit.Egress/ListEgress",
            {"room": room},
            room=room,
            timeout=5.0,
        )
        if listed.get("ok"):
            found = _active_egress_id(listed.get("data") or {})
            if found and found not in ids:
                ids.append(found)
    stopped = False
    last: Dict[str, Any] = {"ok": True, "stopped": False, "reason": "no_egress_id"}
    for eid in ids:
        last = await stop_room_egress(eid, sid)
        stopped = stopped or bool(last.get("stopped"))
    last["stopped"] = stopped
    last["egress_ids"] = ids
    return last


async def list_room_participants(session_id: str) -> Dict[str, Any]:
    from app.services.studio_cohost_share import is_studio_host_identity

    sid = (session_id or "").strip()
    if not sid:
        return {"ok": False, "participants": []}
    room = f"studio-{sid}"
    resp = await _twirp(
        "/twirp/livekit.RoomService/ListParticipants",
        {"room": room},
        room=room,
        timeout=5.0,
    )
    out: List[Dict[str, Any]] = []
    if resp.get("ok"):
        for part in (resp.get("data") or {}).get("participants") or []:
            if not isinstance(part, dict):
                continue
            ident = str(part.get("identity") or "").strip()
            if not ident or ident.startswith("egress"):
                continue
            out.append(
                {
                    "identity": ident,
                    "name": str(part.get("name") or ident),
                    "is_host": bool(is_studio_host_identity(ident)),
                }
            )
    return {"ok": bool(resp.get("ok")), "participants": out, "http": resp.get("http")}


async def send_room_data(session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    if not sid:
        return {"ok": False, "reason": "no_session"}
    room = f"studio-{sid}"
    raw = json.dumps(payload or {}).encode("utf-8")
    data_b64 = base64.b64encode(raw).decode("ascii")
    sent = await _twirp(
        "/twirp/livekit.RoomService/SendData",
        {"room": room, "data": data_b64, "kind": "RELIABLE"},
        room=room,
        timeout=5.0,
    )
    return {"ok": bool(sent.get("ok")), "http": sent.get("http"), "reason": sent.get("reason")}


def join_token(session_id: str, role: str, identity: str = "") -> Dict[str, Any]:
    out = join_token_stub(session_id, role)
    key = os.getenv("LIVEKIT_API_KEY", "")
    secret = os.getenv("LIVEKIT_API_SECRET", "")
    url = os.getenv("LIVEKIT_URL", "")
    token = ""
    rid = (identity or "").strip() or f"{role}-{uuid.uuid4().hex[:10]}"
    if key and secret:
        token = mint_livekit_jwt(
            api_key=key,
            api_secret=secret,
            room=f"studio-{session_id}",
            identity=rid,
            role=role,
        )
        out["token"] = token
        out["jwt"] = True
        out["url"] = url
        out["room"] = f"studio-{session_id}"
    else:
        out["jwt"] = False
        out["url"] = url
    out["room_url"] = room_embed_url(url, token, role, session_id)
    return out
