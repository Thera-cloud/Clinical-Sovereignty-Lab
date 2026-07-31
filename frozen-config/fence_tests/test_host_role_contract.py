"""Fence: Attempt 4 host-role contract must remain in-tree and fail-closed.

Lives under frozen-config (Queens SA must not write this tree).
# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root (frozen-config/../)
SCRIPTS = ROOT / "scripts"


def test_host_roles_library_present():
    assert (SCRIPTS / "ln7_host_roles.sh").is_file()
    assert (SCRIPTS / "ln7_host_roles_preflight.sh").is_file()
    assert (SCRIPTS / "ln7_binary_audit_preflight.sh").is_file()


def test_host_roles_preflight_offline_pass():
    r = subprocess.run(
        ["bash", str(SCRIPTS / "ln7_host_roles_preflight.sh")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "HOST_ROLES_PREFLIGHT=PASS" in (r.stdout + r.stderr)


def test_binary_audit_preflight_pass():
    r = subprocess.run(
        ["bash", str(SCRIPTS / "ln7_binary_audit_preflight.sh")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "BINARY_AUDIT_PREFLIGHT=PASS" in (r.stdout + r.stderr)
