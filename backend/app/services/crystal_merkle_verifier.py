"""
Crystal Merkle Verifier — Phase 5 Security Hardening.

Merkle-style integrity verification for intelligence crystals.
Verifies content_hash matches SHA-256 of crystal_text; quarantines tampered crystals.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _compute_hash(text: str) -> str:
    """SHA-256 hexdigest of crystal_text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_compare(expected: str, actual: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    if not expected or not actual:
        return False
    return hmac.compare_digest(expected, actual)


class CrystalMerkleVerifier:
    """
    Merkle integrity verification for nate_intelligence_crystals.
    Verifies content_hash == SHA-256(crystal_text); quarantines tampered crystals.
    """

    def __init__(self, db_pool: Optional[Any] = None) -> None:
        self.db_pool = db_pool

    @staticmethod
    def _compute_hash(text: str) -> str:
        """SHA-256 of crystal_text. Public for consistency with verify_crystal."""
        return _compute_hash(text)

    async def verify_crystal(self, crystal_id: str) -> Dict[str, Any]:
        """
        Verify a single crystal's content_hash matches SHA-256(crystal_text).
        Returns verification result dict.
        """
        result: Dict[str, Any] = {
            "crystal_id": crystal_id,
            "valid": False,
            "expected_hash": "",
            "actual_hash": "",
            "status": "NOT_FOUND",
        }

        if not self.db_pool:
            return result

        try:
            id_val = int(crystal_id) if str(crystal_id).isdigit() else crystal_id
        except (ValueError, TypeError):
            result["status"] = "NOT_FOUND"
            return result

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, crystal_text, content_hash, scope
                FROM nate_intelligence_crystals
                WHERE id = $1
                """,
                id_val,
            )

        if not row:
            return result

        crystal_text = row.get("crystal_text") or ""
        content_hash = row.get("content_hash") or ""

        if not content_hash:
            result["status"] = "MISSING_HASH"
            result["expected_hash"] = _compute_hash(crystal_text)
            return result

        expected_hash = _compute_hash(crystal_text)

        if _safe_compare(content_hash, expected_hash):
            result["valid"] = True
            result["expected_hash"] = content_hash
            result["actual_hash"] = content_hash
            result["status"] = "VERIFIED"
        else:
            result["valid"] = False
            result["expected_hash"] = expected_hash
            result["actual_hash"] = content_hash
            result["status"] = "TAMPERED"

        return result

    async def verify_batch(self, crystal_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch verification. Returns {crystal_id: result_dict}."""
        results: Dict[str, Dict[str, Any]] = {}
        for cid in crystal_ids:
            results[cid] = await self.verify_crystal(cid)
        return results

    async def scan_integrity(self, limit: int = 1000) -> Dict[str, Any]:
        """
        Scan recent crystals (scope != 'archived', ordered by last_recalled_at DESC)
        for integrity violations. Returns summary and quarantined list.
        """
        summary: Dict[str, Any] = {
            "total_scanned": 0,
            "verified_count": 0,
            "tampered_count": 0,
            "missing_hash_count": 0,
            "quarantined": [],
        }

        if not self.db_pool:
            return summary

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, crystal_text, content_hash
                FROM nate_intelligence_crystals
                WHERE scope != 'archived'
                ORDER BY last_recalled_at DESC NULLS LAST, created_at DESC
                LIMIT $1
                """,
                limit,
            )

        for row in rows:
            cid = str(row["id"])
            crystal_text = row.get("crystal_text") or ""
            content_hash = row.get("content_hash") or ""

            summary["total_scanned"] += 1

            if not content_hash:
                summary["missing_hash_count"] += 1
                continue

            expected = _compute_hash(crystal_text)
            if _safe_compare(content_hash, expected):
                summary["verified_count"] += 1
            else:
                summary["tampered_count"] += 1
                await self.quarantine_crystal(
                    cid,
                    f"Merkle mismatch: expected {expected[:16]}..., got {content_hash[:16]}...",
                )
                summary["quarantined"].append(cid)

        return summary

    async def quarantine_crystal(self, crystal_id: str, reason: str) -> Optional[Dict[str, Any]]:
        """
        Set scope='archived' and log the quarantine to skyeye_activity.
        Returns the updated crystal record or None if not found.
        """
        if not self.db_pool:
            logger.warning("CrystalMerkleVerifier: no db_pool, cannot quarantine %s", crystal_id)
            return None

        try:
            id_val = int(crystal_id) if str(crystal_id).isdigit() else crystal_id
        except (ValueError, TypeError):
            return None

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE nate_intelligence_crystals
                SET scope = 'archived', updated_at = NOW()
                WHERE id = $1
                RETURNING id, crystal_text, domain, scope, content_hash
                """,
                id_val,
            )

            if not row:
                return None

            await conn.execute(
                """
                INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                VALUES ('crystal_verifier', 'crystal_quarantine', $1, 'warning', $2::jsonb, NOW())
                """,
                reason,
                json.dumps({"crystal_id": crystal_id, "reason": reason}),
            )

        logger.warning("CrystalMerkleVerifier: quarantined crystal %s — %s", crystal_id, reason)
        return dict(row)
