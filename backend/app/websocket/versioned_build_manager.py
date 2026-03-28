"""
VersionedBuildManager — Blue-Green-Orange deployment orchestration.

Manages versioned builds: backup, fork, test, promote, rollback.
The bridge always runs from the live/ symlink. Promotion = atomic symlink swap.
Rollback = swap symlink back.

Directory structure:
    {project_root}/
        live/            → symlink to versions/vX.Y.Z.W/
        versions/
            v1.0.0.0/    (current stable)
            v1.0.0.1/    (being built/tested)
        backups/
            v1.0.0.0/    (frozen snapshot, read-only)
        .sovereign/
            versions.json (version history + promotion log)
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class VersionInfo:
    major: int = 1
    minor: int = 0
    patch: int = 0
    build: int = 0

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}.{self.patch}.{self.build}"

    def bump(self, level: str = "patch") -> "VersionInfo":
        """Return a new VersionInfo bumped at the given level."""
        if level == "breaking":
            return VersionInfo(self.major + 1, 0, 0, 0)
        elif level == "major":
            return VersionInfo(self.major, self.minor + 1, 0, 0)
        elif level == "minor":
            return VersionInfo(self.major, self.minor, self.patch + 1, 0)
        else:
            return VersionInfo(self.major, self.minor, self.patch, self.build + 1)

    @classmethod
    def parse(cls, version_str: str) -> "VersionInfo":
        """Parse 'v1.0.0.0' or '1.0.0.0' into a VersionInfo."""
        s = version_str.lstrip("v")
        parts = s.split(".")
        if len(parts) != 4:
            raise ValueError(f"Invalid version format: {version_str} (expected X.Y.Z.W)")
        return cls(*[int(p) for p in parts])


@dataclass
class BuildRecord:
    version: str
    action: str  # "created", "promoted", "rolled_back", "rejected"
    timestamp: str = ""
    cli: str = "blue"
    test_results: Dict[str, bool] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


# Files and directories to exclude when forking a version
_FORK_EXCLUDES = {
    "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "*.pyc", "*.pyo",
    "versions", "backups", "live",
}


def _should_exclude(name: str) -> bool:
    return name in _FORK_EXCLUDES or name.endswith((".pyc", ".pyo"))


class VersionedBuildManager:
    """Manages the Blue-Green-Orange versioned build lifecycle."""

    def __init__(self, project_root: Optional[str] = None) -> None:
        if project_root:
            self._root = Path(project_root).resolve()
        else:
            env_root = os.environ.get("CLI_PROJECT_ROOT")
            if env_root:
                self._root = Path(env_root).expanduser().resolve()
            else:
                self._root = Path(__file__).resolve().parent.parent.parent.parent

        self._versions_dir = self._root / "versions"
        self._backups_dir = self._root / "backups"
        self._live_link = self._root / "live"
        self._versions_json = self._root / ".sovereign" / "versions.json"
        self._history: List[Dict[str, Any]] = []
        self._current_build: Optional[str] = None

        self._versions_dir.mkdir(parents=True, exist_ok=True)
        self._backups_dir.mkdir(parents=True, exist_ok=True)
        self._versions_json.parent.mkdir(parents=True, exist_ok=True)

        self._load_history()

    @property
    def project_root(self) -> Path:
        return self._root

    @property
    def current_build(self) -> Optional[str]:
        return self._current_build

    def _load_history(self) -> None:
        if self._versions_json.exists():
            try:
                data = json.loads(self._versions_json.read_text(encoding="utf-8"))
                self._history = data.get("history", [])
            except (json.JSONDecodeError, KeyError):
                self._history = []

    def _save_history(self) -> None:
        data = {
            "current_stable": self.get_stable_version(),
            "current_build": self._current_build,
            "history": self._history,
        }
        self._versions_json.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )

    def _record(self, version: str, action: str, **kwargs: Any) -> None:
        rec = BuildRecord(version=version, action=action, **kwargs)
        self._history.append(asdict(rec))
        self._save_history()

    def get_stable_version(self) -> Optional[str]:
        """Return the version that live/ currently points to, or None."""
        if not self._live_link.exists():
            return None
        try:
            target = self._live_link.resolve()
            return target.name
        except (OSError, ValueError):
            return None

    def get_available_versions(self) -> List[str]:
        if not self._versions_dir.exists():
            return []
        return sorted(
            [d.name for d in self._versions_dir.iterdir() if d.is_dir()],
            key=lambda v: v,
        )

    def build_start(self, bump_level: str = "patch") -> Dict[str, Any]:
        """Phase 1: Start a new build — backup current, fork to new version.

        Returns a status dict with version info and paths.
        """
        stable = self.get_stable_version()

        if stable:
            current_vi = VersionInfo.parse(stable)
        else:
            current_vi = VersionInfo(1, 0, 0, 0)
            stable_dir = self._versions_dir / str(current_vi)
            if not stable_dir.exists():
                self._fork_project_to(stable_dir)
                self._set_live(str(current_vi))
                self._record(str(current_vi), "created", notes="Initial version from project root")
            stable = str(current_vi)

        new_vi = current_vi.bump(bump_level)
        new_version = str(new_vi)
        new_dir = self._versions_dir / new_version
        stable_dir = self._versions_dir / stable

        if new_dir.exists():
            return {
                "ok": False,
                "error": f"Version {new_version} already exists. Delete it or bump again.",
            }

        backup_dir = self._backups_dir / stable
        if not backup_dir.exists():
            shutil.copytree(stable_dir, backup_dir, dirs_exist_ok=True)
            self._make_readonly(backup_dir)

        shutil.copytree(
            stable_dir, new_dir,
            ignore=shutil.ignore_patterns(*_FORK_EXCLUDES),
            dirs_exist_ok=True,
        )

        self._current_build = new_version
        self._record(new_version, "created", notes=f"Forked from {stable}")
        self._save_history()

        return {
            "ok": True,
            "stable_version": stable,
            "new_version": new_version,
            "working_dir": str(new_dir),
            "backup_dir": str(backup_dir),
        }

    def build_promote(self, version: Optional[str] = None, cli: str = "blue",
                      test_results: Optional[Dict[str, bool]] = None) -> Dict[str, Any]:
        """Phase 4: Promote a verified version to live.

        Atomically swaps the live/ symlink.
        """
        version = version or self._current_build
        if not version:
            return {"ok": False, "error": "No version specified and no current build"}

        version_dir = self._versions_dir / version
        if not version_dir.exists():
            return {"ok": False, "error": f"Version directory not found: {version}"}

        old_stable = self.get_stable_version()
        self._set_live(version)
        self._current_build = None

        self._record(
            version, "promoted",
            cli=cli,
            test_results=test_results or {},
            notes=f"Promoted from {old_stable or 'none'}",
        )

        return {
            "ok": True,
            "promoted": version,
            "previous": old_stable,
            "live_path": str(self._live_link),
        }

    def build_rollback(self, target_version: Optional[str] = None) -> Dict[str, Any]:
        """Phase 5 (rollback): Swap live/ back to a previous version.

        If no target given, rolls back to the most recent promoted version
        before the current one.
        """
        current = self.get_stable_version()
        if not current:
            return {"ok": False, "error": "No current stable version to rollback from"}

        if target_version:
            target = target_version
        else:
            promoted = [
                r for r in reversed(self._history)
                if r.get("action") == "promoted" and r.get("version") != current
            ]
            if not promoted:
                return {"ok": False, "error": "No previous promoted version found in history"}
            target = promoted[0]["version"]

        target_dir = self._versions_dir / target
        if not target_dir.exists():
            backup_dir = self._backups_dir / target
            if backup_dir.exists():
                shutil.copytree(backup_dir, target_dir)
            else:
                return {"ok": False, "error": f"Version {target} not found in versions/ or backups/"}

        self._set_live(target)
        self._record(current, "rolled_back", notes=f"Rolled back from {current} to {target}")

        return {
            "ok": True,
            "rolled_back_from": current,
            "rolled_back_to": target,
            "live_path": str(self._live_link),
        }

    def get_working_dir(self) -> Optional[Path]:
        """Return the working directory for the current build, or None."""
        if not self._current_build:
            return None
        d = self._versions_dir / self._current_build
        return d if d.exists() else None

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive build status."""
        return {
            "stable_version": self.get_stable_version(),
            "current_build": self._current_build,
            "available_versions": self.get_available_versions(),
            "backups": sorted(
                [d.name for d in self._backups_dir.iterdir() if d.is_dir()]
            ) if self._backups_dir.exists() else [],
            "live_target": str(self._live_link.resolve()) if self._live_link.exists() else None,
            "history_count": len(self._history),
            "last_action": self._history[-1] if self._history else None,
        }

    def _set_live(self, version: str) -> None:
        """Atomically set the live/ symlink to a version directory."""
        target = self._versions_dir / version
        if not target.exists():
            raise FileNotFoundError(f"Version directory not found: {target}")

        tmp_link = self._root / ".live_swap_tmp"
        try:
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink()
            tmp_link.symlink_to(target)
            tmp_link.rename(self._live_link)
        except Exception:
            if tmp_link.exists() or tmp_link.is_symlink():
                tmp_link.unlink(missing_ok=True)
            raise

    def _fork_project_to(self, dest: Path) -> None:
        """Copy the project root into dest, excluding build artifacts."""
        shutil.copytree(
            self._root, dest,
            ignore=shutil.ignore_patterns(*_FORK_EXCLUDES),
            dirs_exist_ok=True,
        )

    @staticmethod
    def _make_readonly(path: Path) -> None:
        """Make a directory tree read-only (backup protection)."""
        for dirpath, dirnames, filenames in os.walk(path):
            dp = Path(dirpath)
            for fn in filenames:
                fp = dp / fn
                try:
                    fp.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
                except OSError:
                    pass
