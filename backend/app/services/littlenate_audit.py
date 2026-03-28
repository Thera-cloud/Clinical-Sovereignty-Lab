"""
LittleNate-1.X HIPAA Coherence Audit Logger.

Records coherence scores (C_knowledge, C_quantum_self, felt_sense) alongside
every API call. This creates a HIPAA audit trail that proves not just WHO
accessed what, but WHY the AI responded the way it did.

Audio is never stored — streaming only. Transcripts are logged only when
the client config has audit_transcripts=true.
"""

import hashlib
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class LittleNateAudit:
    """HIPAA coherence audit logger for the LittleNate-1.X API."""

    def __init__(self, db_pool=None):
        self._db_pool = db_pool
        self._log_count = 0

    def set_db_pool(self, pool):
        self._db_pool = pool

    async def log_request(
        self,
        *,
        client_id: Optional[str] = None,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        user_agent: str = "",
        ip_address: str = "",
        c_knowledge: float = 0.0,
        c_quantum_self: float = 0.0,
        felt_sense: str = "grounded",
        latency_ms: int = 0,
        tokens_used: int = 0,
        provider: str = "",
    ):
        """Log an API request with coherence metadata to the audit trail."""
        self._log_count += 1

        ip_hash = hashlib.sha256(ip_address.encode()).hexdigest()[:16] if ip_address else ""

        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO api_audit_log
                       (client_id, endpoint, method, status_code, user_agent,
                        ip_hash, c_knowledge, c_quantum_self, felt_sense, latency_ms)
                       VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    client_id if client_id else None,
                    endpoint, method, status_code,
                    user_agent[:500] if user_agent else "",
                    ip_hash,
                    c_knowledge, c_quantum_self, felt_sense,
                    latency_ms,
                )
        except Exception as e:
            logger.warning("LittleNateAudit: failed to log request: %s", e)

    async def log_usage(
        self,
        *,
        client_id: Optional[str] = None,
        endpoint: str,
        tokens_used: int = 0,
        latency_ms: int = 0,
        coherence_score: float = 0.0,
        provider: str = "",
    ):
        """Log token usage for metering and billing."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO api_usage
                       (client_id, endpoint, tokens_used, latency_ms, coherence_score, provider)
                       VALUES ($1::uuid, $2, $3, $4, $5, $6)""",
                    client_id if client_id else None,
                    endpoint, tokens_used, latency_ms, coherence_score, provider,
                )
        except Exception as e:
            logger.warning("LittleNateAudit: failed to log usage: %s", e)

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_logged": self._log_count,
            "db_connected": self._db_pool is not None,
        }
