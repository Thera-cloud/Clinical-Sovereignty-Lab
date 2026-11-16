"""Coach W-9 file handoff.

The backend vault mount is read-only. Checkout stores the upload on the
pending signup, finalize stashes the bytes in Redis, and the bridge writes
the file into the coach Documents folder when it reloads the new user.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

_MAX_CHARS = 12_000_000
_TTL_SECONDS = 7 * 24 * 3600


def w9_redis_key(hardware_id: str) -> str:
    return f"nate:w9doc:{hardware_id}"


def safe_w9_filename(name: str) -> str:
    base = os.path.basename(name or "w9.pdf")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80]
    return cleaned or "w9.pdf"


async def stash_w9_doc(redis, hardware_id: str, doc: dict) -> bool:
    if not redis or not hardware_id or not isinstance(doc, dict):
        return False
    data = doc.get("data") or ""
    filename = doc.get("filename") or ""
    if not data or not filename or len(data) > _MAX_CHARS:
        return False
    payload = json.dumps({"filename": safe_w9_filename(filename), "data": data})
    await redis.setex(w9_redis_key(hardware_id), _TTL_SECONDS, payload)
    return True


def _redis_client():
    import redis

    password = os.environ.get("REDIS_PASSWORD") or None
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=password,
        decode_responses=True,
        socket_connect_timeout=3,
    )


async def consume_pending_w9(db_pool, vault_root, username: str) -> bool:
    """Write a stashed W-9 into the coach vault and record the path."""
    if not db_pool or not username:
        return False
    row = await db_pool.fetchrow(
        "SELECT hardware_id, role FROM users WHERE username = $1",
        username,
    )
    if not row or (row["role"] or "").upper() != "COACH":
        return False
    hardware_id = row["hardware_id"]
    client = _redis_client()
    raw = client.get(w9_redis_key(hardware_id))
    if not raw:
        return False
    try:
        doc = json.loads(raw)
        file_bytes = base64.b64decode(doc.get("data") or "")
        filename = safe_w9_filename(doc.get("filename") or "w9.pdf")
        dest_dir = Path(vault_root) / "Coaches" / hardware_id / "Documents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"w9_{filename}"
        dest.write_bytes(file_bytes)
        await db_pool.execute(
            """
            UPDATE users
            SET profile_data = COALESCE(profile_data, '{}'::jsonb) || jsonb_build_object(
                    'tin_doc_uploaded', true,
                    'tin_doc_path', $2::text,
                    'tin_match_status', 'pending_admin_review',
                    'tin_verification_method', 'document_upload'
                )
            WHERE username = $1
            """,
            username,
            str(dest),
        )
        client.delete(w9_redis_key(hardware_id))
        return True
    except Exception:
        client.delete(w9_redis_key(hardware_id))
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass
