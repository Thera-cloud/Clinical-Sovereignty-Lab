"""R5: verify the droplet bootstrap lockfile is fully hash-pinned + mirror-declared.

Every droplet install (GPU provisioning, hive burst nodes) must install from this
frozen lockfile via the internal mirror, never `pip install <pkg>` unpinned against
the public index — that's the supply-chain-integrity gap this closes (plan:
"droplet installs from frozen lockfiles ... declared fallback engines").

This module only *verifies* the shipped lockfile (frozen-config artifact, present on
every node — always checkable, no graceful skip). It does not install anything;
installation is `backend/scripts/hive_gpu/droplet_bootstrap.sh`, which calls
`pip install --require-hashes -r <this lockfile> --index-url <internal mirror>`.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

LOCKFILE_NAME = "ln7_droplet_requirements.lock"

_REQ_LINE_RE = re.compile(r"^([A-Za-z0-9_.\-]+)==([A-Za-z0-9_.\-]+)\s*\\?\s*$")
_HASH_LINE_RE = re.compile(r"^\s*--hash=sha256:[0-9a-f]{64}\s*$")
_MIRROR_RE = re.compile(r"^#\s*internal-mirror-index-url:\s*(\S+)")


def _load_frozen_config_dir_fn():
    """Resolve ln7_frozen_config.frozen_config_dir without forcing a fresh
    `app.services` package __init__ (which imports nevedal_engine -> numpy;
    crashes with SIGFPE via Accelerate's buggy polyfit self-check on some
    macOS hosts). Same pattern as
    principal_review_crisis_policy._load_gold_stem_fingerprints_fn().
    """
    import sys

    mod = sys.modules.get("app.services.ln7_frozen_config")
    if mod is not None:
        return mod.frozen_config_dir
    if "app.services" in sys.modules:
        from app.services.ln7_frozen_config import frozen_config_dir

        return frozen_config_dir
    import importlib.util as _ilu

    _path = Path(__file__).resolve().parent / "ln7_frozen_config.py"
    _spec = _ilu.spec_from_file_location("_standalone_ln7_frozen_config", _path)
    _standalone = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_standalone)
    return _standalone.frozen_config_dir


def lockfile_path() -> Path:
    frozen_config_dir = _load_frozen_config_dir_fn()
    return frozen_config_dir() / LOCKFILE_NAME


def verify_droplet_lockfile() -> Dict[str, Any]:
    """Parse the lockfile; fail closed if any requirement line is unpinned or the
    internal mirror declaration is missing."""
    path = lockfile_path()
    if not path.is_file():
        return {"ok": False, "error": "lockfile_missing", "path": str(path)}

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as e:
        return {"ok": False, "error": f"read_failed:{e}", "path": str(path)}

    mirror_url = None
    packages: List[str] = []
    unpinned: List[str] = []
    pending_pkg = None

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not mirror_url:
            m = _MIRROR_RE.match(stripped)
            if m:
                mirror_url = m.group(1)
        if not stripped or stripped.startswith("#"):
            continue
        req_m = _REQ_LINE_RE.match(stripped)
        if req_m:
            if pending_pkg is not None:
                # Previous requirement line never got a --hash continuation.
                unpinned.append(pending_pkg)
            pending_pkg = f"{req_m.group(1)}=={req_m.group(2)}"
            packages.append(pending_pkg)
            continue
        if pending_pkg is not None and _HASH_LINE_RE.match(line):
            pending_pkg = None
            continue
        # Any other non-comment, non-blank, non-hash-continuation line is malformed.
        if pending_pkg is not None:
            unpinned.append(pending_pkg)
            pending_pkg = None

    if pending_pkg is not None:
        unpinned.append(pending_pkg)

    ok = bool(packages) and not unpinned and mirror_url is not None
    return {
        "ok": ok,
        "path": str(path),
        "package_count": len(packages),
        "packages": packages,
        "unpinned": unpinned,
        "mirror_url": mirror_url,
        "mirror_declared": mirror_url is not None,
    }
