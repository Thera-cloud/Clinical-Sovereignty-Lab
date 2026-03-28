"""
BuildProtocol — WebSocket message types for Blue-Green-Orange cross-CLI verification.

Message Types:
  build_verify_request   Blue → Green  (diff bundle + Blue's test results)
  build_verify_result    Green → Blue  (independent verification pass/fail)
  build_promote_green    Blue → Green  (signal Green to promote after soak)
  build_promote_complete Green → Blue  (confirmation)
  build_rollback         Either → Either (emergency rollback)
  build_status           Either → Either (read-only status query)

Per Rule 25: build_status is read-only → add to _SENTINEL_SKIP.
All other types are stateful → must pass Sentinel scoring.
"""
import hashlib
import json
import subprocess
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# All WebSocket message types used by the build system
BUILD_MESSAGE_TYPES = frozenset({
    "build_verify_request",
    "build_verify_result",
    "build_promote_green",
    "build_promote_complete",
    "build_rollback",
    "build_status",
})

SENTINEL_SKIP_TYPES = frozenset({
    "build_status",
})

STATEFUL_TYPES = BUILD_MESSAGE_TYPES - SENTINEL_SKIP_TYPES


@dataclass
class DiffBundle:
    """Compressed unified diff with integrity checksum."""
    version: str
    diff_text: str = ""
    new_files: List[str] = field(default_factory=list)
    deleted_files: List[str] = field(default_factory=list)
    migrations: List[str] = field(default_factory=list)
    checksum: str = ""
    compressed: bytes = b""

    def compute_checksum(self) -> str:
        content = (self.diff_text + "|" + ",".join(sorted(self.new_files))).encode("utf-8")
        self.checksum = hashlib.sha256(content).hexdigest()
        return self.checksum

    def compress(self) -> bytes:
        self.compressed = zlib.compress(self.diff_text.encode("utf-8"), level=6)
        return self.compressed

    @classmethod
    def decompress(cls, data: bytes) -> str:
        return zlib.decompress(data).decode("utf-8")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "diff_text": self.diff_text,
            "new_files": self.new_files,
            "deleted_files": self.deleted_files,
            "migrations": self.migrations,
            "checksum": self.checksum,
        }


def generate_diff_bundle(stable_dir: str, working_dir: str, version: str) -> DiffBundle:
    """Generate a diff bundle between stable and working version directories.

    Uses `diff -ruN` for a unified diff. Falls back to file listing if
    diff is unavailable.
    """
    bundle = DiffBundle(version=version)
    stable = Path(stable_dir)
    working = Path(working_dir)

    try:
        proc = subprocess.run(
            ["diff", "-ruN", "--exclude=__pycache__", "--exclude=.git",
             str(stable), str(working)],
            capture_output=True, text=True, timeout=30,
        )
        bundle.diff_text = proc.stdout or ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        bundle.diff_text = f"[diff unavailable — manual comparison required]"

    stable_files = set(_relative_files(stable))
    working_files = set(_relative_files(working))
    bundle.new_files = sorted(working_files - stable_files)
    bundle.deleted_files = sorted(stable_files - working_files)

    migrations_dir = working / "backend" / "migrations"
    if migrations_dir.exists():
        stable_migrations = set(
            f.name for f in (stable / "backend" / "migrations").glob("*.sql")
        ) if (stable / "backend" / "migrations").exists() else set()
        bundle.migrations = sorted(
            f.name for f in migrations_dir.glob("*.sql")
            if f.name not in stable_migrations
        )

    bundle.compute_checksum()
    return bundle


def _relative_files(root: Path) -> List[str]:
    """List all files under root as relative paths, excluding build artifacts."""
    result = []
    excludes = {"__pycache__", ".git", "node_modules", ".venv", "versions", "backups"}
    for f in root.rglob("*"):
        if f.is_file() and not any(ex in f.parts for ex in excludes):
            try:
                result.append(str(f.relative_to(root)))
            except ValueError:
                pass
    return result


def build_verify_request_msg(
    version: str,
    diff_bundle: DiffBundle,
    test_results: Dict[str, bool],
    rules_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Construct the build_verify_request WebSocket message (Blue → Green)."""
    return {
        "type": "build_verify_request",
        "version": version,
        "diff_bundle": diff_bundle.to_dict(),
        "test_results_blue": test_results,
        "build_rules_version": rules_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_verify_result_msg(
    version: str,
    verified: bool,
    test_results: Dict[str, bool],
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct the build_verify_result WebSocket message (Green → Blue)."""
    return {
        "type": "build_verify_result",
        "version": version,
        "verified": verified,
        "test_results_green": test_results,
        "rejection_reason": rejection_reason,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def build_promote_green_msg(version: str) -> Dict[str, Any]:
    """Signal Green to promote after Blue's soak period passes."""
    return {
        "type": "build_promote_green",
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_promote_complete_msg(version: str, success: bool, error: Optional[str] = None) -> Dict[str, Any]:
    """Green confirms promotion completed (or failed)."""
    return {
        "type": "build_promote_complete",
        "version": version,
        "success": success,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_rollback_msg(from_version: str, to_version: str, reason: str = "") -> Dict[str, Any]:
    return {
        "type": "build_rollback",
        "from_version": from_version,
        "to_version": to_version,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_status_msg(status: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "build_status",
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
