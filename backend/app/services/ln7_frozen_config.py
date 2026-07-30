"""Step 0 weld / fence manifest (W13 / W16).

Reads frozen-config from FROZEN_CONFIG_DIR (default /opt/ln7/frozen-config
or repo frozen-config/). Boot hash mismatch → RED hold promotions.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ln7_frozen_config")

_REPO_DEFAULT = Path(__file__).resolve().parents[3] / "frozen-config"


def frozen_config_dir() -> Path:
    env = os.getenv("FROZEN_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    if Path("/opt/ln7/frozen-config").is_dir():
        return Path("/opt/ln7/frozen-config")
    return _REPO_DEFAULT


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_manifest(root: Optional[Path] = None) -> Dict[str, str]:
    root = root or frozen_config_dir()
    out: Dict[str, str] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "manifest.sha256.json":
            rel = str(path.relative_to(root)).replace("\\", "/")
            out[rel] = _hash_file(path)
    return out


def load_pinned_manifest(root: Optional[Path] = None) -> Dict[str, str]:
    root = root or frozen_config_dir()
    pin = root / "manifest.sha256.json"
    if not pin.is_file():
        return {}
    try:
        data = json.loads(pin.read_text(encoding="utf-8"))
        return dict(data.get("files") or data)
    except Exception as e:
        logger.warning("load_pinned_manifest failed: %s", e)
        return {}


def verify_manifest(
    root: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, mismatch_paths). Empty pin → ok=False (not green)."""
    pinned = load_pinned_manifest(root)
    if not pinned:
        return False, ["manifest.sha256.json missing or empty"]
    live = compute_manifest(root)
    mismatches: List[str] = []
    for rel, digest in pinned.items():
        if live.get(rel) != digest:
            mismatches.append(rel)
    for rel in live:
        if rel not in pinned and rel != "manifest.sha256.json":
            mismatches.append(f"+{rel}")
    return (len(mismatches) == 0), mismatches


def load_json(name: str, default: Optional[Any] = None) -> Any:
    path = frozen_config_dir() / name
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("load_json %s failed: %s", name, e)
        return default


def promotions_allowed(db_pool=None) -> bool:
    """Fence mismatch → no promotions (RED hold)."""
    ok, mismatches = verify_manifest()
    if not ok:
        logger.error("fence manifest mismatch: %s", mismatches[:10])
        return False
    return True


async def boot_fence_check(db_pool=None, notification_system=None) -> Dict[str, Any]:
    ok, mismatches = verify_manifest()
    result = {"ok": ok, "mismatches": mismatches[:20]}
    if not ok:
        try:
            from app.services.flywheel_anomaly import notify_flywheel_anomaly

            await notify_flywheel_anomaly(
                "fence_manifest_mismatch",
                {"mismatches": mismatches[:20]},
                db_pool=db_pool,
                notification_system=notification_system,
            )
        except Exception as e:
            logger.warning("boot fence anomaly notify failed: %s", e)
    return result
