"""Fence: R5 droplet bootstrap lockfile must stay fully hash-pinned and
mirror-declared.

ln7_droplet_requirements.lock is what backend/scripts/hive_gpu/droplet_bootstrap.sh
installs from (`pip install --require-hashes -r <lockfile> --index-url <mirror>`).
An edit that adds an unpinned requirement line or drops the internal-mirror-index-url
header would silently degrade every future droplet provision back to an unpinned,
public-index install — the exact supply-chain gap this lockfile exists to close.
Catch that drift here at commit time instead of on a live GPU node.

Lives under frozen-config (Queens SA must not write this tree).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def _load_droplet_lockfile_module():
    """Load ln7_droplet_lockfile.py by file path, NOT via ``app.services``
    (mirrors test_shadow_eval_weld.py's loader) — importing the ``app.services``
    package pulls in nevedal_engine.py -> numpy, which SIGFPEs on some macOS
    hosts during package __init__. This module has no app.* imports at top
    level, so a direct file-path load is safe and avoids the whole package
    import."""
    mod_path = REPO_ROOT / "backend" / "app" / "services" / "ln7_droplet_lockfile.py"
    spec = importlib.util.spec_from_file_location("ln7_droplet_lockfile", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_droplet_lockfile_exists():
    d = _load_droplet_lockfile_module()
    assert d.lockfile_path().is_file(), (
        f"missing {d.LOCKFILE_NAME} — droplet_bootstrap.sh has nothing to install from"
    )


def test_droplet_lockfile_fully_hash_pinned():
    d = _load_droplet_lockfile_module()
    result = d.verify_droplet_lockfile()
    assert result["unpinned"] == [], (
        f"unpinned requirement(s) in {d.LOCKFILE_NAME}: {result['unpinned']} "
        "— every requirement line must carry --hash=sha256:..."
    )


def test_droplet_lockfile_declares_internal_mirror():
    d = _load_droplet_lockfile_module()
    result = d.verify_droplet_lockfile()
    assert result["mirror_declared"] is True, (
        f"{d.LOCKFILE_NAME} is missing its '# internal-mirror-index-url:' header — "
        "droplet_bootstrap.sh refuses to install without a declared mirror"
    )
    assert result["mirror_url"], "mirror_url must be non-empty when declared"


def test_droplet_lockfile_has_at_least_one_package():
    d = _load_droplet_lockfile_module()
    result = d.verify_droplet_lockfile()
    assert result["package_count"] >= 1


def test_droplet_lockfile_overall_ok():
    """The single boolean droplet_bootstrap.sh's supply_chain_pin drill step
    depends on — every sub-check above rolled into one fail-closed gate."""
    d = _load_droplet_lockfile_module()
    result = d.verify_droplet_lockfile()
    assert result["ok"] is True, result
