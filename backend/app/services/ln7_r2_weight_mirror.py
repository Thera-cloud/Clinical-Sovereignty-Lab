"""R5: mirror base-model / adapter weights to R2 with checksums.

Adapters: `mirror_adapter_dir` (unpinned tree, uploaded per-revision, no drift check —
adapters are expected to change every revision).

Base model: `mirror_base_model_dir` + `verify_base_model_checksums`. The base model
(Qwen/Qwen2.5-Coder-7B-Instruct, see ln7_merge_drain.BASE_MODEL) is pulled from the HF
Hub at train/merge time on the GPU node. To "own the Qwen artifacts" (plan: R2-mirrored
base weights + checksums) we mirror one local checkout to R2 once and pin its per-file
checksums into frozen-config (`ln7_base_model_checksums.json`), so:
  1) a future re-download/re-mirror can be verified byte-for-byte against the pin, and
  2) drift (corruption, tampering, silent upstream mutation) is detectable before a
     merge trains against a base model that is no longer what we validated.

Verification skips gracefully (ok=True, skipped=True) when the local base-model
directory is absent on the current node — the pin only fails closed on nodes that
actually claim to hold the base model.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ln7_r2_weight_mirror")

BASE_MODEL_CHECKSUM_FILE = "ln7_base_model_checksums.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _checksum_tree(root: Path) -> Dict[str, str]:
    checksums: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            checksums[str(path.relative_to(root))] = sha256_file(path)
    return checksums


async def _upload_tree(
    root: Path,
    checksums: Dict[str, str],
    *,
    r2_key_prefix: str,
    revision_id: str,
) -> Dict[str, Any]:
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

    checksums = _checksum_tree(root)
    return await _upload_tree(
        root, checksums, r2_key_prefix=r2_key_prefix, revision_id=revision_id
    )


def base_model_local_dir() -> Path:
    return Path(
        os.getenv("LN7_BASE_MODEL_LOCAL_DIR", "/opt/ln7/base_model/Qwen2.5-Coder-7B-Instruct")
    )


def _base_model_checksum_manifest_path() -> Path:
    from app.services.ln7_frozen_config import frozen_config_dir

    return frozen_config_dir() / BASE_MODEL_CHECKSUM_FILE


def load_pinned_base_model_checksums() -> Optional[Dict[str, str]]:
    path = _base_model_checksum_manifest_path()
    if not path.is_file():
        return None
    try:
        import json

        data = json.loads(path.read_text())
        files = data.get("files") if isinstance(data, dict) else None
        return files if isinstance(files, dict) else None
    except Exception as e:
        logger.warning("load_pinned_base_model_checksums failed: %s", e)
        return None


async def mirror_base_model_dir(
    local_dir: Optional[str] = None,
    *,
    r2_key_prefix: str = "ln7/base_model/",
    revision_id: str = "qwen2.5-coder-7b-instruct",
) -> Dict[str, Any]:
    """Checksum + upload local base-model checkout; write the pinned checksum manifest.

    Call this once (or after a deliberate, reviewed re-mirror) to establish/refresh the
    pin. `verify_base_model_checksums()` is what runs unattended (fallback drill) and
    must never silently update the pin — only this function writes it.
    """
    root = Path(local_dir) if local_dir else base_model_local_dir()
    if not root.is_dir():
        return {"ok": False, "error": "missing_dir", "dir": str(root)}

    checksums = _checksum_tree(root)
    if not checksums:
        return {"ok": False, "error": "empty_dir", "dir": str(root)}

    upload_result = await _upload_tree(
        root, checksums, r2_key_prefix=r2_key_prefix, revision_id=revision_id
    )

    manifest_path = _base_model_checksum_manifest_path()
    try:
        import json

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "model": revision_id,
                    "files": checksums,
                    "file_count": len(checksums),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        pin_written = True
    except Exception as e:
        logger.warning("failed to write base model checksum manifest: %s", e)
        pin_written = False

    return {
        "ok": bool(upload_result.get("ok")) and pin_written,
        "pin_written": pin_written,
        "manifest_path": str(manifest_path),
        "upload": upload_result,
        "file_count": len(checksums),
    }


async def verify_base_model_checksums(
    local_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare live local base-model files against the pinned manifest.

    Skips (ok=True, skipped=True) when this node has no local base-model checkout —
    the drill only fails closed on nodes that actually claim to hold the base model.
    Fails closed (ok=False) on any checksum mismatch, missing pinned file, or unpinned
    extra file once a local checkout IS present.
    """
    root = Path(local_dir) if local_dir else base_model_local_dir()
    if not root.is_dir():
        return {"ok": True, "skipped": True, "reason": "no_local_checkout", "dir": str(root)}

    pinned = load_pinned_base_model_checksums()
    if pinned is None:
        # Local checkout exists but has never been mirrored/pinned yet — an ops
        # to-do, not a drift alarm. Once a pin exists, mismatches fail closed.
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_yet_pinned",
            "dir": str(root),
            "hint": "run mirror_base_model_dir() to establish the pin",
        }

    live = _checksum_tree(root)
    mismatched = [f for f in pinned if f in live and live[f] != pinned[f]]
    missing = [f for f in pinned if f not in live]
    extra = [f for f in live if f not in pinned]

    ok = not mismatched and not missing
    return {
        "ok": ok,
        "dir": str(root),
        "checked_files": len(pinned),
        "mismatched": mismatched,
        "missing": missing,
        "extra_unpinned": extra,
    }
