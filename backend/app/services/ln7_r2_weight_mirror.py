"""R5: mirror base-model / adapter weights to R2 with checksums.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("ln7_r2_weight_mirror")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def mirror_adapter_dir(
    local_dir: str,
    *,
    r2_key_prefix: str = "ln7/adapters/",
    revision_id: str = "",
) -> Dict[str, Any]:
    """Checksum local adapter tree; upload via r2_storage when configured."""
    root = Path(local_dir)
    if not root.is_dir():
        return {"ok": False, "error": "missing_dir"}

    checksums: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            checksums[str(path.relative_to(root))] = sha256_file(path)

    try:
        from app.services import r2_storage
    except Exception as e:
        return {
            "ok": True,
            "skipped": True,
            "checksums": checksums,
            "reason": f"r2_import:{e}",
        }

    upload = getattr(r2_storage, "upload_file", None)
    if upload is None:
        return {
            "ok": True,
            "skipped": True,
            "checksums": checksums,
            "reason": "r2_upload_unavailable",
        }

    uploaded = 0
    prefix = f"{r2_key_prefix}{revision_id or root.name}/"
    for rel in checksums:
        key = prefix + rel
        try:
            res = upload(str(root / rel), key)
            if hasattr(res, "__await__"):
                await res
            uploaded += 1
        except Exception as e:
            logger.warning("R2 upload %s failed: %s", key, e)
    return {
        "ok": True,
        "uploaded": uploaded,
        "checksums": checksums,
        "revision_id": revision_id,
    }
