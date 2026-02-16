"""
HIVE DEFENSE PROTOCOL — Forensic Logger (Phase 8A)
Immutable append-only evidence chain with SHA-256 hash linking.

Every ForensicRecord is chained to its predecessor via a cryptographic hash,
forming a tamper-evident log analogous to a blockchain ledger.  Records
accumulate in a thread-safe in-memory buffer and are periodically flushed
to PostgreSQL (``hive_forensic_logs`` table) via an asyncpg connection pool.

Chain Hash Algorithm:
    H(n) = SHA-256( record_id || event_type || timestamp_iso || H(n-1) )

Patent-Pending — Claim 30
© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.hive_defense import ForensicRecord

logger = logging.getLogger("hive.forensic_logger")


# =============================================================================
# FORENSIC LOGGER
# =============================================================================

class ForensicLogger:
    """
    Immutable append-only evidence chain for the Hive Defense Protocol.

    Features
    --------
    * **Chain integrity** — each record's ``chain_hash`` is computed from
      its own fields plus the previous record's hash, making retrospective
      tampering cryptographically detectable.
    * **Thread-safe append** — an ``asyncio.Lock`` serialises writes so
      that concurrent coroutines never produce a broken chain.
    * **Buffered flush** — records accumulate in memory and are batch-
      inserted into PostgreSQL on demand (or at a configurable threshold).
    * **Verification** — ``verify_chain()`` validates the hash linkage of
      an arbitrary sequence of records.

    Usage
    -----
    ::

        logger = ForensicLogger()
        await logger.log_event(
            event_type="hive.trap.interaction",
            source_entity="penetrator-001",
            target_entity="attacker-cnc-42",
            evidence={"packets_captured": 14},
        )
        # Later, flush buffered records to the database:
        await logger.flush_to_db(pool)
    """

    # Maximum number of records to buffer before an automatic flush warning
    _BUFFER_HIGH_WATER: int = 500

    def __init__(self, *, auto_flush_threshold: int = 0) -> None:
        """
        Parameters
        ----------
        auto_flush_threshold:
            If > 0, a warning is emitted when the buffer exceeds this size.
            Actual flushing is left to the caller (via ``flush_to_db``).
        """
        # In-memory evidence chain (append-only list)
        self._chain: List[ForensicRecord] = []

        # Unflushed buffer (subset of _chain awaiting DB write)
        self._buffer: List[ForensicRecord] = []

        # The hash of the most-recently appended record (or genesis seed)
        self._latest_hash: str = self._genesis_hash()

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        # Configuration
        self._auto_flush_threshold = auto_flush_threshold or self._BUFFER_HIGH_WATER

        # Metrics
        self._total_logged: int = 0
        self._total_flushed: int = 0

        logger.info(
            "ForensicLogger initialised — genesis hash: %s",
            self._latest_hash[:16],
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def log_event(
        self,
        event_type: str,
        source_entity: Optional[str] = None,
        target_entity: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> ForensicRecord:
        """
        Create and append a new :class:`ForensicRecord` to the evidence chain.

        Parameters
        ----------
        event_type:
            A topic string from ``HIVE_EVENT_TOPICS`` (e.g.
            ``"hive.trap.interaction"``).
        source_entity:
            Identifier of the entity that produced the event.
        target_entity:
            Identifier of the entity the event relates to.
        evidence:
            Arbitrary JSON-serialisable evidence payload.

        Returns
        -------
        ForensicRecord
            The newly created (and chained) record.
        """
        async with self._lock:
            record = ForensicRecord(
                record_id=uuid4(),
                event_type=event_type,
                source_entity=source_entity,
                target_entity=target_entity,
                evidence=evidence or {},
                timestamp=datetime.utcnow(),
            )

            # Compute the chain hash linking to the previous record
            record.compute_chain_hash(previous_hash=self._latest_hash)
            self._latest_hash = record.chain_hash

            # Append to both the full chain and the unflushed buffer
            self._chain.append(record)
            self._buffer.append(record)
            self._total_logged += 1

            if len(self._buffer) >= self._auto_flush_threshold:
                logger.warning(
                    "Forensic buffer high-water reached (%d records) — "
                    "consider flushing to database",
                    len(self._buffer),
                )

            logger.debug(
                "Forensic record logged: type=%s src=%s tgt=%s hash=%s",
                event_type,
                source_entity,
                target_entity,
                record.chain_hash[:16],
            )

            return record

    async def get_chain(
        self,
        start_id: Optional[UUID] = None,
        count: int = 50,
    ) -> List[ForensicRecord]:
        """
        Retrieve a contiguous slice of the evidence chain.

        Parameters
        ----------
        start_id:
            The ``record_id`` to start from.  If *None*, the chain is read
            from the beginning.
        count:
            Maximum number of records to return.

        Returns
        -------
        list[ForensicRecord]
            Up to *count* records starting from *start_id* (or index 0).
        """
        async with self._lock:
            if start_id is None:
                return list(self._chain[:count])

            # Locate the starting record
            for idx, rec in enumerate(self._chain):
                if rec.record_id == start_id:
                    return list(self._chain[idx : idx + count])

            logger.warning(
                "get_chain: start_id %s not found in local chain", start_id
            )
            return []

    @staticmethod
    def verify_chain(records: List[ForensicRecord]) -> bool:
        """
        Verify the cryptographic integrity of a sequence of records.

        Each record's ``chain_hash`` must equal the SHA-256 of::

            record_id : event_type : timestamp_iso : previous_hash

        Parameters
        ----------
        records:
            An ordered list of :class:`ForensicRecord` instances.

        Returns
        -------
        bool
            ``True`` if every hash in the sequence is valid and each record's
            ``previous_record_hash`` matches the preceding record's
            ``chain_hash``.
        """
        if not records:
            return True

        for idx, record in enumerate(records):
            # Determine expected previous hash
            if idx == 0:
                expected_prev = record.previous_record_hash  # trust genesis
            else:
                expected_prev = records[idx - 1].chain_hash

            # Verify the previous_record_hash pointer
            if record.previous_record_hash != expected_prev:
                logger.error(
                    "Chain break at index %d (record %s): previous_hash "
                    "mismatch — expected %s, got %s",
                    idx,
                    record.record_id,
                    expected_prev[:16],
                    record.previous_record_hash[:16],
                )
                return False

            # Recompute the chain hash and compare
            data = (
                f"{record.record_id}:{record.event_type}:"
                f"{record.timestamp.isoformat()}:{expected_prev}"
            )
            expected_hash = hashlib.sha256(data.encode()).hexdigest()

            if record.chain_hash != expected_hash:
                logger.error(
                    "Chain break at index %d (record %s): hash mismatch — "
                    "expected %s, got %s",
                    idx,
                    record.record_id,
                    expected_hash[:16],
                    record.chain_hash[:16],
                )
                return False

        logger.info(
            "Chain verification passed for %d record(s)", len(records)
        )
        return True

    async def flush_to_db(self, pool) -> int:
        """
        Write all buffered :class:`ForensicRecord` instances to the
        ``hive_forensic_logs`` PostgreSQL table and clear the buffer.

        Parameters
        ----------
        pool:
            An ``asyncpg.Pool`` instance.

        Returns
        -------
        int
            Number of records flushed.

        Raises
        ------
        Exception
            Propagates any database error after logging.
        """
        async with self._lock:
            if not self._buffer:
                return 0

            records_to_flush = list(self._buffer)
            self._buffer.clear()

        # Outside the lock — batch insert via asyncpg
        flushed = 0
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for record in records_to_flush:
                        await conn.execute(
                            """
                            INSERT INTO hive_forensic_logs (
                                record_id,
                                event_type,
                                source_entity,
                                target_entity,
                                evidence,
                                chain_hash,
                                previous_record_hash,
                                timestamp
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                            ON CONFLICT (record_id) DO NOTHING
                            """,
                            record.record_id,
                            record.event_type,
                            record.source_entity,
                            record.target_entity,
                            json.dumps(record.evidence),
                            record.chain_hash,
                            record.previous_record_hash,
                            record.timestamp,
                        )
                        flushed += 1

            self._total_flushed += flushed
            logger.info(
                "Flushed %d forensic record(s) to database "
                "(total flushed: %d)",
                flushed,
                self._total_flushed,
            )
        except Exception:
            # Re-buffer the records so they aren't lost
            async with self._lock:
                self._buffer = records_to_flush + self._buffer
            logger.exception(
                "Failed to flush %d forensic records — re-buffered",
                len(records_to_flush),
            )
            raise

        return flushed

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def chain_length(self) -> int:
        """Total number of records in the local evidence chain."""
        return len(self._chain)

    @property
    def buffer_size(self) -> int:
        """Number of records awaiting database flush."""
        return len(self._buffer)

    @property
    def latest_hash(self) -> str:
        """The chain hash of the most recently appended record."""
        return self._latest_hash

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics for monitoring."""
        return {
            "chain_length": self.chain_length,
            "buffer_size": self.buffer_size,
            "total_logged": self._total_logged,
            "total_flushed": self._total_flushed,
            "latest_hash": self._latest_hash[:16],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _genesis_hash() -> str:
        """
        Compute the genesis (seed) hash that anchors the very first record
        in the chain.  This is deterministic so that independent verifiers
        can reproduce the expected starting point.
        """
        seed = "HIVE_DEFENSE_FORENSIC_GENESIS_v1"
        return hashlib.sha256(seed.encode()).hexdigest()

    def __repr__(self) -> str:
        return (
            f"<ForensicLogger chain={self.chain_length} "
            f"buffer={self.buffer_size} "
            f"latest_hash={self._latest_hash[:12]}…>"
        )
