"""
HIVE DEFENSE v4.3 — Recovery Drill Framework (Window 8)
Automated and scheduled recovery testing.

Monthly: Key derivation test, vault access test
Quarterly: Shamir share reconstruction verify
Annual: Full system recovery simulation

Tracks drill results and alerts on failures.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("recovery_drill")


class DrillType:
    MONTHLY_KEY = "monthly_key_test"
    MONTHLY_VAULT = "monthly_vault_test"
    QUARTERLY_SHAMIR = "quarterly_shamir_verify"
    ANNUAL_RECOVERY = "annual_full_recovery"


# Drill schedule (days between drills)
DRILL_SCHEDULES = {
    DrillType.MONTHLY_KEY: 30,
    DrillType.MONTHLY_VAULT: 30,
    DrillType.QUARTERLY_SHAMIR: 90,
    DrillType.ANNUAL_RECOVERY: 365,
}


class RecoveryDrillFramework:
    """Automated recovery drill scheduling and execution."""

    def __init__(self, db_pool=None, sovereign_key_manager=None, succession_protocol=None, hepa_filter=None):
        self._db = db_pool
        self._key_manager = sovereign_key_manager
        self._succession = succession_protocol
        self._hepa = hepa_filter
        self._drill_history: List[Dict] = []
        self._running = False

    async def start(self) -> None:
        """Start the drill scheduler."""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._scheduler_loop())
        _logger.info("RecoveryDrillFramework started")

    async def stop(self) -> None:
        """Stop the drill scheduler."""
        self._running = False

    async def _scheduler_loop(self) -> None:
        """Check if any drills are due and run them."""
        while self._running:
            try:
                await self._check_due_drills()
            except Exception as exc:
                _logger.error("Drill scheduler error: %s", exc)
            await asyncio.sleep(86400)  # Check daily

    async def _check_due_drills(self) -> None:
        """Check each drill type and run if due."""
        now = datetime.now(timezone.utc)

        for drill_type, interval_days in DRILL_SCHEDULES.items():
            last_run = self._get_last_drill(drill_type)
            if last_run is None or (now - last_run).days >= interval_days:
                _logger.info("Running drill: %s", drill_type)
                result = await self.run_drill(drill_type)
                if not result.get("passed"):
                    _logger.critical("DRILL FAILED: %s — %s", drill_type, result.get("reason", "unknown"))

    def _get_last_drill(self, drill_type: str) -> Optional[datetime]:
        """Get the timestamp of the last drill of this type."""
        for drill in reversed(self._drill_history):
            if drill["type"] == drill_type:
                return datetime.fromisoformat(drill["timestamp"])
        return None

    # ─── Drill Execution ──────────────────────────────────────────────────────

    async def run_drill(self, drill_type: str) -> Dict[str, Any]:
        """Run a specific drill and record the result."""
        start_time = datetime.now(timezone.utc)

        if drill_type == DrillType.MONTHLY_KEY:
            result = await self._drill_key_derivation()
        elif drill_type == DrillType.MONTHLY_VAULT:
            result = await self._drill_vault_access()
        elif drill_type == DrillType.QUARTERLY_SHAMIR:
            result = await self._drill_shamir_verify()
        elif drill_type == DrillType.ANNUAL_RECOVERY:
            result = await self._drill_full_recovery()
        else:
            result = {"passed": False, "reason": f"Unknown drill type: {drill_type}"}

        end_time = datetime.now(timezone.utc)
        result["type"] = drill_type
        result["timestamp"] = start_time.isoformat()
        result["duration_sec"] = (end_time - start_time).total_seconds()

        self._drill_history.append(result)
        return result

    async def _drill_key_derivation(self) -> Dict[str, Any]:
        """Monthly: Verify key derivation still works correctly."""
        if not self._key_manager:
            return {"passed": False, "reason": "key_manager_not_available"}

        try:
            if not self._key_manager.is_initialized():
                return {"passed": False, "reason": "key_manager_not_initialized"}

            # Test: derive a test key, encrypt, decrypt, verify
            test_data = b"recovery_drill_test_payload_" + datetime.now(timezone.utc).isoformat().encode()
            encrypted = self._key_manager.encrypt("clinical", "drill_test_record", test_data)
            decrypted = self._key_manager.decrypt("clinical", "drill_test_record", encrypted)

            if decrypted == test_data:
                return {"passed": True, "details": "key_derivation_and_encryption_verified"}
            else:
                return {"passed": False, "reason": "decrypted_data_mismatch"}

        except Exception as exc:
            return {"passed": False, "reason": f"key_derivation_error_{type(exc).__name__}"}

    async def _drill_vault_access(self) -> Dict[str, Any]:
        """Monthly: Verify Heritage Vault is accessible."""
        if not self._hepa:
            return {"passed": False, "reason": "hepa_not_available"}

        try:
            test_content = b"vault_drill_test_" + datetime.now(timezone.utc).isoformat().encode()
            result = await self._hepa.archive_to_heritage_vault(
                "drill_test_user", "drill_test", test_content, retention_years=1,
            )

            if result.get("archived"):
                return {"passed": True, "details": "heritage_vault_write_verified"}
            else:
                return {"passed": False, "reason": "vault_write_failed"}

        except Exception as exc:
            return {"passed": False, "reason": f"vault_access_error_{type(exc).__name__}"}

    async def _drill_shamir_verify(self) -> Dict[str, Any]:
        """Quarterly: Verify Shamir share reconstruction."""
        if not self._succession:
            return {"passed": False, "reason": "succession_not_available"}

        try:
            # Generate a test secret and split/reconstruct
            import secrets as secrets_mod
            test_secret = secrets_mod.token_bytes(32)
            shares = self._succession.shamir.split_secret(test_secret, 5, 3)

            # Reconstruct from 3 random shares
            import random
            selected = random.sample(shares, 3)
            reconstructed = self._succession.shamir.reconstruct_secret(selected, 3)

            if reconstructed == test_secret:
                return {"passed": True, "details": "shamir_3_of_5_reconstruction_verified"}
            else:
                return {"passed": False, "reason": "reconstruction_mismatch"}

        except Exception as exc:
            return {"passed": False, "reason": f"shamir_error_{type(exc).__name__}"}

    async def _drill_full_recovery(self) -> Dict[str, Any]:
        """Annual: Full system recovery simulation."""
        results = {
            "passed": True,
            "steps": [],
        }

        # Step 1: Key derivation
        key_result = await self._drill_key_derivation()
        results["steps"].append({"name": "key_derivation", **key_result})
        if not key_result["passed"]:
            results["passed"] = False

        # Step 2: Vault access
        vault_result = await self._drill_vault_access()
        results["steps"].append({"name": "vault_access", **vault_result})
        if not vault_result["passed"]:
            results["passed"] = False

        # Step 3: Shamir reconstruction
        shamir_result = await self._drill_shamir_verify()
        results["steps"].append({"name": "shamir_verify", **shamir_result})
        if not shamir_result["passed"]:
            results["passed"] = False

        # Step 4: Database connectivity
        db_result = await self._check_db_connectivity()
        results["steps"].append({"name": "db_connectivity", **db_result})
        if not db_result["passed"]:
            results["passed"] = False

        return results

    async def _check_db_connectivity(self) -> Dict[str, Any]:
        """Verify database is accessible."""
        if not self._db:
            return {"passed": False, "reason": "no_db_pool"}
        try:
            row = await self._db.fetchrow("SELECT 1 as ok")
            return {"passed": True, "details": "database_responsive"}
        except Exception as exc:
            return {"passed": False, "reason": f"db_error_{type(exc).__name__}"}

    def get_drill_history(self, limit: int = 20) -> List[Dict]:
        """Get recent drill history."""
        return self._drill_history[-limit:]

    def get_overdue_drills(self) -> List[str]:
        """Get list of drills that are overdue."""
        now = datetime.now(timezone.utc)
        overdue = []
        for drill_type, interval_days in DRILL_SCHEDULES.items():
            last_run = self._get_last_drill(drill_type)
            if last_run is None or (now - last_run).days >= interval_days:
                overdue.append(drill_type)
        return overdue
