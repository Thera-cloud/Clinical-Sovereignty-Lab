"""
Version-bump enforcement test for `specialized_resources.py`.

Why this test exists
--------------------
`sensitive_bridge_log` retains decision rows for 7 years (per migration 202
and Gap L jurisdiction policy). Each row records `specialized_resources_version`
so a forensic auditor can reconstruct *which exact resource block was shown*
to a survivor at any point in the retention window.

If a maintainer changes a phone number, URL, or block_text without bumping
`REGISTRY_VERSION`, that correlation breaks silently — every historical log
entry now points to a version string that no longer describes the content
that was actually delivered. The harm is invisible at deploy time and only
surfaces during an audit, subpoena, or post-incident review.

This test makes the silent failure loud:
  - Computes a deterministic SHA256 of the entire registry + block texts.
  - Compares to the stored `REGISTRY_CONTENT_HASH` constant.
  - On mismatch, fails with a step-by-step remediation message.

To intentionally change a resource:
  1. Make the change.
  2. Run this test — it will fail and print the new hash.
  3. Bump `REGISTRY_VERSION` (semver).
  4. Replace `REGISTRY_CONTENT_HASH` with the new hash.
  5. Re-run; test passes.

This is the cheapest possible enforcement (5 lines of test logic, ~80 lines
of in-module hash machinery). It runs in any CI pipeline that runs pytest
and in any pre-commit hook configured to invoke pytest on staged tests.
"""

from __future__ import annotations

import pytest

from app.services.specialized_resources import (
    REGISTRY_CONTENT_HASH,
    REGISTRY_VERSION,
    assert_version_aligned,
    compute_registry_hash,
)


def test_registry_content_hash_matches_stored_constant():
    """The stored hash MUST match the computed hash, or REGISTRY_VERSION needs
    a bump alongside REGISTRY_CONTENT_HASH. See module docstring above."""
    assert_version_aligned()


def test_registry_version_format():
    """REGISTRY_VERSION must follow `MAJOR.MINOR.PATCH-YYYY-MM-DD` so that
    audit log queries can sort by version string lexically and remain in
    chronological order."""
    parts = REGISTRY_VERSION.split("-", 1)
    assert len(parts) == 2, (
        f"REGISTRY_VERSION {REGISTRY_VERSION!r} must be 'X.Y.Z-YYYY-MM-DD'"
    )
    semver, datestamp = parts
    semver_parts = semver.split(".")
    assert len(semver_parts) == 3 and all(p.isdigit() for p in semver_parts), (
        f"REGISTRY_VERSION semver portion must be MAJOR.MINOR.PATCH: {semver!r}"
    )
    # YYYY-MM-DD = 10 chars
    assert len(datestamp) == 10 and datestamp[4] == "-" and datestamp[7] == "-", (
        f"REGISTRY_VERSION date portion must be YYYY-MM-DD: {datestamp!r}"
    )


def test_registry_content_hash_is_64_hex():
    """REGISTRY_CONTENT_HASH must be a 64-char hex string (SHA256). Catches
    accidental truncation when pasting a new hash."""
    assert len(REGISTRY_CONTENT_HASH) == 64, (
        f"REGISTRY_CONTENT_HASH must be 64 hex chars, got {len(REGISTRY_CONTENT_HASH)}"
    )
    int(REGISTRY_CONTENT_HASH, 16)  # raises ValueError if not hex


def test_compute_registry_hash_is_deterministic():
    """Two consecutive calls to `compute_registry_hash()` must return the
    same value. Catches non-deterministic serialization (e.g., if the
    payload ever switches from sorted dict to set iteration)."""
    h1 = compute_registry_hash()
    h2 = compute_registry_hash()
    assert h1 == h2, "compute_registry_hash() must be deterministic"
