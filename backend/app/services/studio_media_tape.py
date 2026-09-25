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

STORYBOARD_SLOTS: Tuple[Dict[str, Any], ...] = (
    {"id": 1, "slot": "intro", "label": "Podcast Intro", "max_s": 20.0, "kind": "video"},
    {"id": 2, "slot": "hook", "label": "Hook Video", "max_s": 30.0, "kind": "video"},
    {"id": 3, "slot": "topic1", "label": "Topic 1", "max_s": 330.0, "kind": "video"},
    {"id": 4, "slot": "commercial", "label": "Commercial Plug", "max_s": 120.0, "kind": "mixed"},
    {"id": 5, "slot": "topic2", "label": "Topic 2", "max_s": 330.0, "kind": "video"},
    {"id": 6, "slot": "closing", "label": "Closing Plug", "max_s": 120.0, "kind": "mixed"},
    {"id": 7, "slot": "credential", "label": "Credential Video", "max_s": 60.0, "kind": "video"},
)


def storyboard_blueprint() -> List[Dict[str, Any]]:
    return [dict(row) for row in STORYBOARD_SLOTS]


def edited_title(title: str) -> str:
    raw = (title or "").strip() or "Episode"
    if "(Edited Version)" in raw:
        return raw
    return f"{raw} (Edited Version)"


def clip_fits_slot(duration_s: float, max_s: float) -> bool:
    return duration_s > 0.04 and duration_s <= (float(max_s) + 0.08)


def parse_cut_windows(cuts: Any) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    if not cuts:
        return out
    if isinstance(cuts, dict):
        if cuts.get("removed"):
            return out
        nested = (
            cuts.get("storyboard")
            or cuts.get("windows")
            or cuts.get("slots")
            or cuts.get("cuts")
        )
        return parse_cut_windows(nested)
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
            clip = item.get("clip") if isinstance(item.get("clip"), dict) else item
            start = _num(
                clip.get("start_s")
                if clip.get("start_s") is not None
                else clip.get("start")
                if clip.get("start") is not None
                else clip.get("start_sec")
                if clip.get("start_sec") is not None
                else clip.get("startTime")
            )
            end = _num(
                clip.get("end_s")
                if clip.get("end_s") is not None
                else clip.get("end")
                if clip.get("end") is not None
                else clip.get("end_sec")
                if clip.get("end_sec") is not None
                else clip.get("endTime")
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


def tape_slice_progress(session_id: str) -> Dict[str, int]:
    """How much of the live room recording is already on this server."""
    folder = _tape_dir(session_id)
    parts = 0
    total = 0
    if not folder.is_dir():
        return {"parts": 0, "bytes": 0}
    try:
        for path in folder.glob("*.bin"):
            parts += 1
            try:
                total += path.stat().st_size
            except OSError:
                pass
    except OSError:
        return {"parts": 0, "bytes": 0}
    return {"parts": parts, "bytes": total}


def tape_coach_status(*, media_ready: bool, parts: int, session_state: str) -> str:
    """What EDIT should say. Uploading stays visible until the file is ready."""
    if media_ready:
        return "ready"
    if parts > 0:
        return "uploading"
    if (session_state or "") == "active":
        return "waiting"
    if (session_state or "") == "ended":
        return "missed"
    return "none"


def tape_play_url(key: str, expires_in: int = 3600) -> str:
    """Presigned R2 GET for coach review player. Empty when R2/key missing."""
    path = (key or "").strip()
    if not path:
        return ""
    try:
        from app.services.r2_storage import generate_presigned_url, head_object

        meta = head_object(key=path) or {}
        if int(meta.get("ContentLength") or 0) < 200:
            return ""
        return generate_presigned_url(key=path, expires_in=expires_in) or ""
    except Exception:
        return ""


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


def _tape_dir(session_id: str):
    from pathlib import Path

    sid = (session_id or "").strip()
    root = Path("/tmp/studio_tapes") / sid
    return root


def save_tape_part(session_id: str, index: int, raw: bytes) -> Dict[str, Any]:
    """Store one MediaRecorder timeslice. The host room uploads these while live."""
    sid = (session_id or "").strip()
    if not sid or index < 0 or index > 5000:
        return {"ok": False, "reason": "bad_part"}
    if not raw or len(raw) > 8_000_000:
        return {"ok": False, "reason": "bad_size", "code": 413}
    folder = _tape_dir(sid)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{index:05d}.bin").write_bytes(raw)
    return {"ok": True, "index": index, "bytes": len(raw)}


async def finish_show_tape(db_pool, session_id: str) -> Dict[str, Any]:
    """Join the host-room slices, store the file, and mark the session ready for Edit."""
    sid = (session_id or "").strip()
    folder = _tape_dir(sid)
    parts = sorted(folder.glob("*.bin")) if folder.is_dir() else []
    if not parts:
        return {"ok": True, "ready": False, "reason": "no_parts"}
    blob = b"".join(p.read_bytes() for p in parts)
    if len(blob) < 200:
        return {"ok": False, "reason": "tape_empty"}
    key = f"studio/{sid}.webm"
    try:
        from app.services.r2_storage import upload_bytes

        upload_bytes(key=key, content=blob, content_type="video/webm")
    except Exception as exc:
        logger.warning("studio show tape upload: %s", exc)
        return {"ok": False, "reason": "upload_failed"}
    stamped = await stamp_session_tape(db_pool, sid, media_r2_key=key, ready=True)
    if not stamped.get("ok"):
        return stamped
    for p in parts:
        try:
            p.unlink()
        except Exception:
            pass
    return {"ok": True, "ready": True, "media_r2_key": key, "bytes": len(blob)}


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

        meta = head_object(key=key) or {}
        return int(meta.get("ContentLength") or 0) >= 200
    except Exception:
        return False


def tape_removed_marker(cuts: Any) -> bool:
    """True when delete_tape hid this episode from the EDIT list."""
    if isinstance(cuts, str):
        try:
            cuts = json.loads(cuts)
        except Exception:
            return False
    return isinstance(cuts, dict) and cuts.get("removed") is True


def slot_spec(slot_id: Any) -> Optional[Dict[str, Any]]:
    try:
        sid = int(slot_id)
    except (TypeError, ValueError):
        sid = 0
    for row in STORYBOARD_SLOTS:
        if int(row["id"]) == sid or str(row["slot"]) == str(slot_id):
            return dict(row)
    return None


def normalize_storyboard(raw: Any) -> Tuple[List[Dict[str, Any]], str]:
    """Seven slots. Empty clips stay null. Over-length clips are rejected."""
    incoming: List[Any] = []
    if isinstance(raw, dict):
        incoming = list(raw.get("storyboard") or raw.get("slots") or [])
    elif isinstance(raw, list):
        incoming = list(raw)
    by_id: Dict[int, Dict[str, Any]] = {}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        spec = slot_spec(item.get("id") or item.get("slot"))
        if not spec:
            continue
        clip = item.get("clip") if isinstance(item.get("clip"), dict) else item
        start = _num(
            clip.get("start_s")
            if clip.get("start_s") is not None
            else clip.get("startTime")
        )
        end = _num(
            clip.get("end_s") if clip.get("end_s") is not None else clip.get("endTime")
        )
        if start is None or end is None or end <= start:
            continue
        duration = end - start
        if not clip_fits_slot(duration, float(spec["max_s"])):
            return [], f"slot_{spec['id']}_over_max"
        source_id = str(clip.get("source_id") or clip.get("sourceMediaId") or "master")
        by_id[int(spec["id"])] = {
            "id": int(spec["id"]),
            "slot": spec["slot"],
            "label": spec["label"],
            "max_s": spec["max_s"],
            "kind": spec["kind"],
            "clip": {
                "source_id": source_id,
                "source_title": str(
                    clip.get("source_title") or clip.get("sourceTitle") or ""
                ),
                "r2_key": str(clip.get("r2_key") or clip.get("r2Key") or ""),
                "start_s": start,
                "end_s": end,
                "duration_s": duration,
                "audio_id": str(
                    clip.get("audio_id") or clip.get("backgroundAudioId") or ""
                ),
                "audio_r2_key": str(
                    clip.get("audio_r2_key") or clip.get("backgroundAudioKey") or ""
                ),
            },
        }
    slots: List[Dict[str, Any]] = []
    for spec in STORYBOARD_SLOTS:
        filled = by_id.get(int(spec["id"]))
        if filled:
            slots.append(filled)
        else:
            slots.append(
                {
                    "id": int(spec["id"]),
                    "slot": spec["slot"],
                    "label": spec["label"],
                    "max_s": spec["max_s"],
                    "kind": spec["kind"],
                    "clip": None,
                }
            )
    return slots, ""


def storyboard_segments(
    slots: List[Dict[str, Any]], master_key: str
) -> List[Dict[str, Any]]:
    segs: List[Dict[str, Any]] = []
    master = (master_key or "").strip()
    for slot in slots:
        clip = slot.get("clip") if isinstance(slot, dict) else None
        if not isinstance(clip, dict):
            continue
        key = (clip.get("r2_key") or "").strip() or master
        if not key:
            continue
        segs.append(
            {
                "r2_key": key,
                "start_s": float(clip["start_s"]),
                "end_s": float(clip["end_s"]),
                "audio_key": (clip.get("audio_r2_key") or "").strip(),
            }
        )
    return segs


def tape_keys_for_delete(session_id: str, stored: List[str]) -> List[str]:
    """R2 keys this episode may remove. Only studio/{session} objects."""
    from app.services.studio_livekit import session_cut_r2_key, session_media_r2_key

    sid = (session_id or "").strip()
    keys: List[str] = []
    candidates = list(stored or [])
    if sid:
        candidates.extend([session_media_r2_key(sid), session_cut_r2_key(sid)])
    for raw in candidates:
        key = str(raw or "").strip().lstrip("/")
        if not key.startswith("studio/"):
            continue
        if sid and sid not in key:
            continue
        if ".." in key or key in keys:
            continue
        keys.append(key)
    return keys


async def apply_cuts(
    db_pool,
    episode_id: str,
    coach_id: str,
    cuts: Optional[List[Any]] = None,
    storyboard: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    slots: List[Dict[str, Any]] = []
    windows = parse_cut_windows(cuts)
    if storyboard is not None:
        slots, err = normalize_storyboard(storyboard)
        if err:
            return {"ok": False, "reason": err, "code": 422}
        windows = parse_cut_windows(slots)
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.session_id, e.media_r2_key, e.media_master_r2_key,
                   e.cuts_json, e.title, s.coach_id
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    if tape_removed_marker(row.get("cuts_json")):
        return {"ok": False, "reason": "tape_deleted", "code": 409}
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
    segs = storyboard_segments(slots, master) if slots else []
    mixed = bool(segs) and (
        len({s["r2_key"] for s in segs}) > 1 or any(s.get("audio_key") for s in segs)
    )
    if mixed:
        rendered = await _ffmpeg_storyboard(dest, segs)
    else:
        rendered = await _ffmpeg_cut_r2(master, dest, windows)
    if not rendered.get("ok"):
        rendered.setdefault("code", 409)
        return rendered
    win_payload = [{"start_s": a, "end_s": b} for a, b in windows]
    payload: Any = (
        {"storyboard": slots, "windows": win_payload} if slots else win_payload
    )
    new_title = edited_title(str(row.get("title") or ""))
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE studio_episodes
                SET cuts_json = $2::jsonb,
                    media_master_r2_key = COALESCE(media_master_r2_key, $3),
                    media_cut_r2_key = $4,
                    media_r2_key = $4,
                    title = $5,
                    updated_at = NOW()
                WHERE id = $1::uuid
                """,
                episode_id,
                json.dumps(payload),
                master,
                dest,
                new_title,
            )
    except Exception as exc:
        logger.warning("studio cut stamp failed: %s", exc)
        return {"ok": False, "reason": str(exc)[:120], "code": 500}
    return {
        "ok": True,
        "applied": True,
        "media_r2_key": dest,
        "media_master_r2_key": master,
        "cuts": win_payload,
        "title": new_title,
        "storyboard": slots,
    }


async def save_storyboard(
    db_pool, episode_id: str, coach_id: str, storyboard: Optional[List[Any]]
) -> Dict[str, Any]:
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    slots, err = normalize_storyboard(storyboard or [])
    if err:
        return {"ok": False, "reason": err, "code": 422}
    windows = parse_cut_windows(slots)
    payload = {
        "storyboard": slots,
        "windows": [{"start_s": a, "end_s": b} for a, b in windows],
    }
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.cuts_json
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
        if not row:
            return {"ok": False, "reason": "not_found", "code": 404}
        if tape_removed_marker(row.get("cuts_json")):
            return {"ok": False, "reason": "tape_deleted", "code": 409}
        await conn.execute(
            """
            UPDATE studio_episodes
            SET cuts_json = $2::jsonb, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            episode_id,
            json.dumps(payload),
        )
    return {"ok": True, "storyboard": slots, "windows": len(windows)}


async def delete_tape(db_pool, episode_id: str, coach_id: str) -> Dict[str, Any]:
    """Remove this episode's video from R2 and clear the tape pointers."""
    if not db_pool:
        return {"ok": False, "reason": "no_db", "code": 503}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT e.id, e.session_id, e.media_r2_key, e.media_master_r2_key,
                   e.media_cut_r2_key, ss.media_r2_key AS session_key
            FROM studio_episodes e
            JOIN studio_shows s ON s.id = e.show_id
            LEFT JOIN studio_sessions ss ON ss.id = e.session_id
            WHERE e.id = $1::uuid AND s.coach_id = $2
            """,
            episode_id,
            coach_id,
        )
    if not row:
        return {"ok": False, "reason": "not_found", "code": 404}
    sid = str(row.get("session_id") or "")
    keys = tape_keys_for_delete(
        sid,
        [
            str(row.get("media_r2_key") or ""),
            str(row.get("media_master_r2_key") or ""),
            str(row.get("media_cut_r2_key") or ""),
            str(row.get("session_key") or ""),
        ],
    )
    from app.services.r2_storage import delete_object_async

    removed: List[str] = []
    failed: List[str] = []
    for key in keys:
        gone = await delete_object_async(key=key)
        if gone or not _r2_has(key):
            removed.append(key)
        else:
            failed.append(key)
    if failed:
        return {
            "ok": False,
            "reason": "r2_delete_failed",
            "code": 502,
            "removed": removed,
            "failed": failed,
        }
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE studio_episodes
            SET media_r2_key = NULL,
                media_master_r2_key = NULL,
                media_cut_r2_key = NULL,
                cuts_json = '{"removed": true}'::jsonb,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            episode_id,
        )
        if sid:
            await conn.execute(
                """
                UPDATE studio_sessions
                SET media_r2_key = NULL, media_ready = FALSE
                WHERE id = $1::uuid
                """,
                sid,
            )
    return {"ok": True, "deleted": True, "removed": len(removed)}


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


async def _ffmpeg_storyboard(
    dest_key: str, segments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    try:
        from app.services.r2_storage import (
            download_bytes_async,
            is_r2_configured,
            upload_bytes_async,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"r2_import:{exc}"}
    if not is_r2_configured():
        return {"ok": False, "reason": "r2_not_configured"}
    if not segments:
        return {"ok": False, "reason": "cuts required"}
    unique = []
    for seg in segments:
        key = (seg.get("r2_key") or "").strip()
        if key and key not in unique:
            unique.append(key)
        audio = (seg.get("audio_key") or "").strip()
        if audio and audio not in unique:
            unique.append(audio)
    blobs: Dict[str, bytes] = {}
    for key in unique:
        blob = await download_bytes_async(key=key)
        if not blob or len(blob) < 200:
            return {"ok": False, "reason": "r2_empty"}
        if len(blob) > _MAX_DOWNLOAD_B:
            return {"ok": False, "reason": "tape_too_large", "code": 413}
        blobs[key] = blob
    with tempfile.TemporaryDirectory(prefix="studio_sb_") as tmp:
        local: Dict[str, str] = {}
        for i, key in enumerate(unique):
            path = os.path.join(tmp, f"src{i}.bin")
            Path(path).write_bytes(blobs[key])
            local[key] = path
        parts: List[str] = []
        for i, seg in enumerate(segments):
            src = local[seg["r2_key"]]
            part = os.path.join(tmp, f"part{i}.mp4")
            if not _ffmpeg_one(src, part, float(seg["start_s"]), float(seg["end_s"])):
                return {"ok": False, "reason": "ffmpeg_failed"}
            audio = (seg.get("audio_key") or "").strip()
            if audio and audio in local:
                mixed = os.path.join(tmp, f"mix{i}.mp4")
                if _ffmpeg_overlay_audio(part, local[audio], mixed):
                    part = mixed
            parts.append(part)
        dest = os.path.join(tmp, "cut.mp4")
        lst = os.path.join(tmp, "concat.txt")
        Path(lst).write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        if not _ffmpeg_concat_list(lst, dest):
            return {"ok": False, "reason": "ffmpeg_failed"}
        out = Path(dest).read_bytes()
        if len(out) < 200:
            return {"ok": False, "reason": "cut_empty"}
        try:
            await upload_bytes_async(key=dest_key, content=out, content_type="video/mp4")
        except Exception as exc:
            logger.warning("studio storyboard upload: %s", exc)
            return {"ok": False, "reason": "r2_write_failed"}
    return {"ok": True, "bytes": len(out)}


def _ffmpeg_overlay_audio(video: str, audio: str, dest: str) -> bool:
    mix = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        video,
        "-i",
        audio,
        "-filter_complex",
        "[1:a]volume=0.28[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ac",
        "2",
        "-shortest",
        dest,
    ]
    try:
        proc = subprocess.run(mix, capture_output=True, timeout=180)
        if proc.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200:
            return True
        replace = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            video,
            "-i",
            audio,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            dest,
        ]
        proc2 = subprocess.run(replace, capture_output=True, timeout=180)
        return proc2.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200
    except Exception as exc:
        logger.warning("studio ffmpeg mix: %s", exc)
        return False


def _ffmpeg_concat_list(lst: str, dest: str) -> bool:
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
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-c:a",
        "aac",
        dest,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=300)
        return proc.returncode == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 200
    except Exception as exc:
        logger.warning("studio ffmpeg concat mix: %s", exc)
        return False


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
