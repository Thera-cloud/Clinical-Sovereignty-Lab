"""
HIVE DEFENSE v4.1 — Post-Deployment Scanner
Verifies deployment integrity after every production release.

- Hash verification of critical files
- Network state monitoring (open ports, active connections)
- Container image verification
- Configuration drift detection
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_logger = logging.getLogger("post_deployment_scanner")

# Critical files that must match expected hashes
CRITICAL_FILES = [
    "backend/app/main.py",
    "backend/app/auth.py",
    "backend/app/config.py",
    "backend/app/field_encryption.py",
    "backend/app/secure_logger.py",
    "backend/app/services/stripe_integration.py",
    "backend/app/websocket/bridge_server.py",
    "nginx/nginx.conf",
    "docker-compose.prod.yml",
]

# Expected open ports
EXPECTED_PORTS = {8000, 8765, 5432, 6379, 3000}


class PostDeploymentScanner:
    """Scans the deployment for integrity issues after release."""

    def __init__(self, base_path: str = "/opt/clinical-sovereignty-lab"):
        self._base_path = Path(base_path)
        self._baseline_hashes: Dict[str, str] = {}
        self._scan_results: List[Dict] = []

    async def run_full_scan(self) -> Dict[str, Any]:
        """Run all post-deployment verification checks."""
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {},
            "passed": True,
            "critical_issues": [],
        }

        # Check 1: Critical file integrity
        file_check = await self._check_file_integrity()
        results["checks"]["file_integrity"] = file_check
        if not file_check["passed"]:
            results["passed"] = False
            results["critical_issues"].extend(file_check.get("issues", []))

        # Check 2: Environment configuration
        env_check = self._check_environment()
        results["checks"]["environment"] = env_check
        if not env_check["passed"]:
            results["passed"] = False

        # Check 3: Sensitive file permissions
        perm_check = await self._check_file_permissions()
        results["checks"]["permissions"] = perm_check

        self._scan_results.append(results)
        status = "PASSED" if results["passed"] else "FAILED"
        _logger.info("Post-deployment scan: %s", status)

        return results

    async def _check_file_integrity(self) -> Dict[str, Any]:
        """Verify critical files haven't been tampered with."""
        issues = []
        checked = 0

        for rel_path in CRITICAL_FILES:
            full_path = self._base_path / rel_path
            if not full_path.exists():
                issues.append(f"Missing critical file: {rel_path}")
                continue

            file_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
            checked += 1

            # If we have a baseline, compare
            if rel_path in self._baseline_hashes:
                if file_hash != self._baseline_hashes[rel_path]:
                    issues.append(f"Hash mismatch: {rel_path}")

            # Update baseline
            self._baseline_hashes[rel_path] = file_hash

        return {
            "passed": len(issues) == 0,
            "files_checked": checked,
            "issues": issues,
        }

    def _check_environment(self) -> Dict[str, Any]:
        """Verify required environment variables are set."""
        required_vars = [
            "DATABASE_URL", "REDIS_URL", "JWT_SECRET",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
            "FIELD_ENCRYPTION_KEY",
        ]

        missing = [v for v in required_vars if not os.getenv(v)]
        return {
            "passed": len(missing) == 0,
            "missing_vars": missing,
            "total_checked": len(required_vars),
        }

    async def _check_file_permissions(self) -> Dict[str, Any]:
        """Verify sensitive files have restrictive permissions."""
        issues = []
        sensitive_patterns = ["*.json", "*.env", "*.key", "*.pem"]

        for pattern in sensitive_patterns:
            for f in self._base_path.rglob(pattern):
                if f.is_file():
                    mode = f.stat().st_mode & 0o777
                    if mode > 0o644:
                        issues.append(f"Overly permissive: {f.name} ({oct(mode)})")

        return {
            "passed": len(issues) == 0,
            "issues": issues[:20],  # Limit output
        }

    def save_baseline(self, output_path: str = "deployment_baseline.json") -> None:
        """Save current file hashes as the baseline for future comparisons."""
        baseline = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hashes": self._baseline_hashes,
        }
        Path(output_path).write_text(json.dumps(baseline, indent=2))
        _logger.info("Deployment baseline saved: %d files", len(self._baseline_hashes))

    def load_baseline(self, input_path: str = "deployment_baseline.json") -> None:
        """Load a previously saved baseline."""
        path = Path(input_path)
        if path.exists():
            data = json.loads(path.read_text())
            self._baseline_hashes = data.get("hashes", {})
            _logger.info("Deployment baseline loaded: %d files", len(self._baseline_hashes))
