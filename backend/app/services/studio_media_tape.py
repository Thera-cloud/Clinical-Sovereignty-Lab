"""Stamp LiveKit egress tape onto sessions/episodes + FFmpeg cuts. QUANTUM-CRYSTAL-ARCH"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("studio_media_tape")

_MAX_CUTS = 12
_MAX_WINDOW_S = 3600.0
_MAX_TOTAL_S = 7200.0
_MAX_DOWNLOAD_B = 400_000_000


def parse_cut_windows(cuts: Any) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    if not cuts:
        return out
    if isinstance(cuts, str):
        parts = [p.strip() for p in cuts.split(",") if p.strip()]
        parsed: List[Any] = []
        for part in parts:
            bits = [b.strip() for b in part.replace("–", "-").split("-") if b.strip()]
            if len(bits) == 2:
                parsed.append({"start_s": bits[0], "end_s": bits[1]})
        cuts = parsed
    if not isinstance(cuts, list):
        return out
    for item in cuts:
        start: Optional[float] = None
        end: Optional[float] = None
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            start, end = _num(item[0]), _num(item[1])
        elif isinstance(item, dict):
            start = _num(
                item.get("start_s")
                if item.get("start_s") is not None
                else item.get("start")
                if item.get("start") is not None
                else item.get("start_sec")
            )
            end = _num(
                item.get("end_s")
                if item.get("end_s") is not None
                else item.get("end")
                if item.get("end") is not None
                else item.get("end_sec")
            )
        if start is None or end is None:
            continue
        if start < 0 or end <= start:
            continue
        if (end - start) > _MAX_WINDOW_S:
            continue
        out.append((start, end))
        if len(out) >= _MAX_CUTS:
            break
    total = sum(b - a for a, b in out)
    if total > _MAX_TOTAL_S:
        return []
    return out


def _num(raw: Any) -> Optional[float]:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def stamp_session_tape(
    db_pool,
    session_id: str,
    *,
    media_r2_key: str = "",
    egress_id: str = "",
    ready: bool = False,
) -> Dict[str, Any]:
    sid = (session_id or "").strip()
    key = (media_r2_key or "").strip()
    eid = (egress_id or "").strip()
    if not sid or not db_pool:
        return {"ok": False, "reason": "no_session_or_db"}
    if not key:
        from app.services.studio_livekit import session_media_r2_key

        key = session_media_r2_key(sid)
    if not key:
        return {"ok": False, "reason": "no_key"}
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE studio_sessions
                SET media_r2_key = COALESCE(NULLIF($2, ''), media_r2_key),
                    egress_id = COALESCE(NULLIF($3, ''), egress_id),
                    media_ready = (media_ready OR $4)
                WHERE id = $1::uuid
                """,
                sid,
                key,
                eid,
                bool(ready),
            )
            await conn.execute(
                """
                UPDATE studio_episodes
                SET media_r2_key = COALESCE(media_r2_key, $2),
                    media_master_r2_key = COALESCE(media_master_r2_key, $2),
                    updated_at = NOW()
                WHERE session_id = $1::uuid
                """,
                sid,
                key,
            )
    except Exception as exc:
        logger.warning("studio tape stamp failed: %s", exc)
        return {"ok": False, "reason": str(exc)[:120]}
    return {"ok": True, "session_id": sid, "media_r2_key": key, "ready": bool(ready)}


async def attach_session_media_key(db_pool, session_id: str) -> Dict[str, Any]:
    """Resolve the R2 key for a session: stamped, or object already in R2."""
    from app.services.studio_livekit import session_media_r2_key

    sid = (session_id or "").strip()
    key = session_media_r2_key(sid)
    ready = False
    stamped = ""
    if db_pool and sid:
        try:
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT media_r2_key, media_ready
                    FROM studio_sessions WHERE id = $1::uuid
                    """,
                    sid,
                )
            if row:
                stamped = (row.get("media_r2_key") or "").strip()
                ready = bool(row.get("media_ready"))
        except Exception as exc:
            logger.warning("studio tape session read: %s", exc)
    if stamped:
        key = stamped
    if key and not ready:
        ready = _r2_has(key)
    return {"ok": True, "media_r2_key": key if (stamped or ready) else "", "ready": ready}


def _r2_has(key: str) -> bool:
    try:
        from app.services.r2_storage import head_object

        return bool(head_object(key=key))
    except Exception:
        return False


async def apply_cuts(
    db_pool, episode_id: str, coach_id: str, cuts: Optional[List[Any]] = None
) -> Dict[str, Any]:
    windows = parse_cut_windows(cuts)
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.session_id, e.media_r2_key, e.media_master_r2_key,
                   e.cuts_json, s.coach_id
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    if not windows:
        windows = parse_cut_windows(row.get("cuts_json"))
    if not windows:
        return {"ok": False, "reason": "cuts required", "code": 422}
    if not shutil.which("ffmpeg"):
        return {"ok": False, "reason": "ffmpeg_missing", "code": 503}
    master = (row.get("media_master_r2_key") or row.get("media_r2_key") or "").strip()
    if not master:
        from app.services.studio_livekit import session_media_r2_key

        sid = str(row.get("session_id") or "")
        master = session_media_r2_key(sid)
    if not master:
        return {"ok": False, "reason": "no_media", "code": 409}
    from app.services.studio_livekit import session_cut_r2_key

    dest = session_cut_r2_key(str(row.get("session_id") or episode_id))
    rendered = await _ffmpeg_cut_r2(master, dest, windows)
    if not rendered.get("ok"):
        rendered.setdefault("code", 409)
        return rendered
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE studio_episodes
                SET cuts_json = $2::jsonb,
                    media_master_r2_key = COALESCE(media_master_r2_key, $3),
                    media_cut_r2_key = $4,
                    media_r2_key = $4,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                episode_id,
                json.dumps([{"start_s": a, "end_s": b} for a, b in windows]),
                master,
                dest,
            )
    except Exception as exc:
        logger.warning("studio cut stamp failed: %s", exc)
        return {"ok": False, "reason": str(exc)[:120], "code": 500}
    return {
        "ok": True,
        "applied": True,
        "media_r2_key": dest,
        "media_master_r2_key": master,
        "cuts": [{"start_s": a, "end_s": b} for a, b in windows],
    }


async def _ffmpeg_cut_r2(
    master_key: str, dest_key: str, windows: List[Tuple[float, float]]
) -> Dict[str, Any]:
    try:
        from app.services.r2_storage import (
            download_bytes_async,
            head_object,
            is_r2_configured,
            upload_bytes_async,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"r2_import:{exc}"}
    if not is_r2_configured():
        return {"ok": False, "reason": "r2_not_configured"}
    try:
        meta = head_object(key=master_key)
        size = int((meta or {}).get("ContentLength") or 0)
        if size > _MAX_DOWNLOAD_B:
            return {"ok": False, "reason": "tape_too_large", "code": 413}
    except Exception:
        pass
    blob = await download_bytes_async(key=master_key)
    if not blob:
        return {"ok": False, "reason": "r2_empty"}
    with tempfile.TemporaryDirectory(prefix="studio_cut_") as tmp:
        src = os.path.join(tmp, "master.mp4")
        dest = os.path.join(tmp, "cut.mp4")
        Path(src).write_bytes(blob)
        if not _ffmpeg_windows(src, dest, windows):
            return {"ok": False, "reason": "ffmpeg_failed"}
        out = Path(dest).read_bytes()
        if len(out) < 200:
            return {"ok": False, "reason": "cut_empty"}
        try:
            await upload_bytes_async(key=dest_key, content=out, content_type="video/mp4")
        except Exception as exc:
            logger.warning("studio cut upload: %s", exc)
            return {"ok": False, "reason": "r2_write_failed"}
    return {"ok": True, "bytes": len(out)}


def _ffmpeg_windows(src: str, dest: str, windows: List[Tuple[float, float]]) -> bool:
    if len(windows) == 1:
        return _ffmpeg_one(src, dest, windows[0][0], windows[0][1])
    parts: List[str] = []
    work = os.path.dirname(dest)
    for i, (start, end) in enumerate(windows):
        part = os.path.join(work, f"part{i}.mp4")
        if not _ffmpeg_one(src, part, start, end):
            return False
        parts.append(part)
    lst = os.path.join(work, "concat.txt")
    Path(lst).write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        lst,
        "-c",
        "copy",
        dest,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=180)
        if proc.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200:
            return True
        reenc = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            lst,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            dest,
        ]
        proc2 = subprocess.run(reenc, capture_output=True, timeout=300)
        return proc2.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200
    except Exception as exc:
        logger.warning("studio ffmpeg concat: %s", exc)
        return False


def _ffmpeg_one(src: str, dest: str, start: float, end: float) -> bool:
    copy = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        src,
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-c",
        "copy",
        dest,
    ]
    try:
        proc = subprocess.run(copy, capture_output=True, timeout=180)
        if proc.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200:
            return True
        reenc = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            src,
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            dest,
        ]
        proc2 = subprocess.run(reenc, capture_output=True, timeout=300)
        return proc2.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200
    except Exception as exc:
        logger.warning("studio ffmpeg trim: %s", exc)
        return False
