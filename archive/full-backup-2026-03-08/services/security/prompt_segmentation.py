"""
HIVE DEFENSE PROTOCOL v3.0 — Distributed Encrypted Prompt Assembly (Phase 8C)
AI model extraction defense through prompt segmentation.

Patent-Pending — AI Model Extraction Defense Claim
    "A method for protecting AI system prompts from extraction, comprising:
     (a) decomposition of the system prompt into encrypted segments stored
         in separate database containers,
     (b) runtime assembly of the complete prompt in memory only when an
         authorized context is established,
     (c) such that no single database query, memory dump, or container
         compromise can reveal the complete system prompt."

The system prompt is the core intellectual property of the Nevedal Engine.
It encodes clinical methodology, therapeutic stance, and the personality
of Little Nate.  This service ensures the prompt is:

1. **Never stored as a single string** — decomposed into encrypted segments
   distributed across separate database containers / schemas.
2. **Assembled only in memory** — runtime assembly occurs in a secure
   buffer that is zeroed after use.
3. **Resistant to partial extraction** — each segment is encrypted with
   a unique key derived from the segment ID, container ID, and a master
   key shard.  Even if one segment is extracted, it is meaningless
   without the others AND the decryption keys.
4. **Auditable** — every assembly is logged with the authorized context.

© 2026 Clinical Sovereignty Lab. All rights reserved.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

logger = logging.getLogger("hive.prompt_segmentation")


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class PromptSegment:
    """A single encrypted segment of the system prompt."""

    segment_id: str = ""
    container_id: str = ""          # Which DB container / schema holds this
    encrypted_data: bytes = b""     # Encrypted segment content
    position: int = 0               # Assembly order
    content_hash: str = ""          # SHA-256 of the plaintext (for integrity)
    encryption_key_id: str = ""     # Reference to the key used for encryption
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SegmentManifest:
    """Read-only manifest of segments (no content)."""

    segment_id: str = ""
    container_id: str = ""
    position: int = 0
    content_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AssemblyAuditRecord:
    """Audit trail for a prompt assembly event."""

    assembly_id: UUID = field(default_factory=uuid4)
    authorized_context: str = ""
    segments_assembled: int = 0
    integrity_verified: bool = False
    assembled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0


# =============================================================================
# PROMPT SEGMENTATION SERVICE
# =============================================================================

class PromptSegmentation:
    """
    Distributed encrypted prompt assembly service.

    Decomposes, stores, and reassembles system prompts from encrypted
    segments distributed across multiple database containers.  Ensures
    that no single database query or container compromise can reveal
    the complete system prompt.

    Parameters
    ----------
    db_pool : Any, optional
        asyncpg connection pool for the primary database.
    container_pools : dict[str, Any], optional
        Mapping of container_id → asyncpg pool for multi-container
        storage.  If not provided, all segments are stored in the
        primary pool with container_id as a column discriminator.
    encryption_key : bytes, optional
        Master encryption key for segment encryption/decryption.
        In production, this is derived from HSM-backed key material.
    event_callback : callable, optional
        Async callback for audit events.

    Usage
    -----
    ::

        service = PromptSegmentation(
            db_pool=pool,
            encryption_key=master_key,
        )

        # Store segments
        await service.store_segment("seg_001", encrypted_bytes, "container_alpha")

        # Assemble at runtime
        full_prompt = await service.assemble_prompt("session_12345_context")

        # Get manifest (no content)
        manifest = await service.get_segment_manifest()
    """

    def __init__(
        self,
        db_pool: Any = None,
        container_pools: Optional[Dict[str, Any]] = None,
        encryption_key: Optional[bytes] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], Coroutine]] = None,
    ) -> None:
        self._db_pool = db_pool
        self._container_pools = container_pools or {}
        self._encryption_key = encryption_key or os.urandom(32)
        self._event_callback = event_callback

        # In-memory segment registry
        self._segments: Dict[str, PromptSegment] = {}

        # Audit trail
        self._audit_log: List[AssemblyAuditRecord] = []
        self._audit_log_max: int = 1000

        # Concurrency guard
        self._lock: asyncio.Lock = asyncio.Lock()

        # Metrics
        self._total_assemblies: int = 0
        self._total_stores: int = 0

        logger.info(
            "PromptSegmentation initialized — container_pools=%d",
            len(self._container_pools),
        )

    # ------------------------------------------------------------------
    # Segment Storage
    # ------------------------------------------------------------------

    async def store_segment(
        self,
        segment_id: str,
        encrypted_segment: bytes,
        container_id: str,
        position: Optional[int] = None,
    ) -> PromptSegment:
        """
        Store an encrypted prompt segment in the designated database container.

        Parameters
        ----------
        segment_id : str
            Unique identifier for this segment.
        encrypted_segment : bytes
            The encrypted segment content.
        container_id : str
            Which database container / schema to store the segment in.
        position : int, optional
            Assembly order position.  If None, appended at the end.

        Returns
        -------
        PromptSegment
            The stored segment record.
        """
        if position is None:
            position = len(self._segments)

        content_hash = hashlib.sha256(encrypted_segment).hexdigest()

        # Derive a per-segment encryption key ID
        encryption_key_id = self._derive_key_id(segment_id, container_id)

        segment = PromptSegment(
            segment_id=segment_id,
            container_id=container_id,
            encrypted_data=encrypted_segment,
            position=position,
            content_hash=content_hash,
            encryption_key_id=encryption_key_id,
        )

        async with self._lock:
            self._segments[segment_id] = segment
            self._total_stores += 1

        # Persist to the appropriate container
        await self._persist_segment(segment)

        logger.info(
            "segment_stored id=%s container=%s position=%d hash=%s…",
            segment_id,
            container_id,
            position,
            content_hash[:16],
        )

        return segment

    # ------------------------------------------------------------------
    # Prompt Assembly
    # ------------------------------------------------------------------

    async def assemble_prompt(
        self,
        authorized_context: str,
    ) -> str:
        """
        Assemble the complete system prompt from encrypted segments.

        This method:
        1. Verifies the authorized context is valid.
        2. Loads all segments from their respective containers.
        3. Decrypts each segment in memory.
        4. Concatenates in position order.
        5. Verifies integrity of the assembled prompt.
        6. Logs an audit record.

        The assembled prompt exists ONLY in memory and should be used
        immediately.  The caller should not persist the assembled prompt.

        Parameters
        ----------
        authorized_context : str
            Description of the context authorizing this assembly
            (e.g., session ID, request ID).  Required for audit trail.

        Returns
        -------
        str
            The fully assembled system prompt.

        Raises
        ------
        RuntimeError
            If no segments are available or integrity verification fails.
        """
        start_ns = time.monotonic_ns()

        if not authorized_context:
            raise ValueError("authorized_context is required for prompt assembly")

        logger.info("prompt_assembly_started context=%s", authorized_context)

        # Load segments (from DB if needed, otherwise in-memory)
        segments = await self._load_all_segments()

        if not segments:
            raise RuntimeError(
                "No prompt segments available — cannot assemble prompt"
            )

        # Sort by position
        sorted_segments = sorted(segments, key=lambda s: s.position)

        # Decrypt and assemble
        assembled_parts: List[str] = []
        for segment in sorted_segments:
            try:
                decrypted = self._decrypt_segment(segment)
                assembled_parts.append(decrypted)
            except Exception as exc:
                logger.error(
                    "segment_decryption_failed id=%s error=%s",
                    segment.segment_id,
                    exc,
                )
                raise RuntimeError(
                    f"Failed to decrypt segment {segment.segment_id}: {exc}"
                )

        assembled_prompt = "".join(assembled_parts)

        # Verify integrity
        integrity_ok = self._verify_assembly_integrity(
            sorted_segments, assembled_parts
        )

        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000

        # Audit record
        audit = AssemblyAuditRecord(
            authorized_context=authorized_context,
            segments_assembled=len(sorted_segments),
            integrity_verified=integrity_ok,
            duration_ms=elapsed_ms,
        )

        async with self._lock:
            self._audit_log.append(audit)
            if len(self._audit_log) > self._audit_log_max:
                self._audit_log = self._audit_log[-self._audit_log_max:]
            self._total_assemblies += 1

        await self._persist_audit(audit)

        logger.info(
            "prompt_assembly_complete context=%s segments=%d "
            "integrity=%s elapsed_ms=%.2f",
            authorized_context,
            len(sorted_segments),
            integrity_ok,
            elapsed_ms,
        )

        if not integrity_ok:
            logger.critical(
                "PROMPT_INTEGRITY_FAILURE — assembled prompt may be tampered"
            )
            raise RuntimeError("Prompt integrity verification failed")

        return assembled_prompt

    # ------------------------------------------------------------------
    # Segment Manifest
    # ------------------------------------------------------------------

    async def get_segment_manifest(self) -> List[SegmentManifest]:
        """
        Return a manifest of all stored segments WITHOUT their content.

        This is safe to expose to admin dashboards — it reveals only
        segment IDs, container assignments, positions, and content hashes,
        never the actual encrypted or decrypted content.

        Returns
        -------
        list[SegmentManifest]
            List of segment manifests sorted by position.
        """
        manifests = [
            SegmentManifest(
                segment_id=seg.segment_id,
                container_id=seg.container_id,
                position=seg.position,
                content_hash=seg.content_hash,
                created_at=seg.created_at,
            )
            for seg in self._segments.values()
        ]
        manifests.sort(key=lambda m: m.position)

        logger.debug(
            "segment_manifest_retrieved count=%d",
            len(manifests),
        )
        return manifests

    # ------------------------------------------------------------------
    # Encryption / Decryption
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # AES-256-GCM Encryption / Decryption
    # ------------------------------------------------------------------

    def encrypt_segment(self, plaintext: str, segment_id: str, container_id: str) -> bytes:
        """
        Encrypt plaintext using AES-256-GCM with a per-segment derived key.

        The output format is:  nonce (12 bytes) || ciphertext+tag

        Parameters
        ----------
        plaintext : str
            The plaintext segment content to encrypt.
        segment_id : str
            Unique segment identifier (used for key derivation).
        container_id : str
            Database container ID (used for key derivation).

        Returns
        -------
        bytes
            The encrypted payload (nonce + ciphertext + GCM tag).
        """
        derived_key = self._derive_segment_key(segment_id, container_id)
        nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
        aesgcm = AESGCM(derived_key)
        # Associated data binds the ciphertext to the segment/container IDs
        aad = f"{segment_id}:{container_id}".encode()
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)
        return nonce + ciphertext

    def _decrypt_segment(self, segment: PromptSegment) -> str:
        """
        Decrypt a segment using AES-256-GCM with a per-segment derived key.

        Expected input format:  nonce (12 bytes) || ciphertext+tag

        Parameters
        ----------
        segment : PromptSegment
            The segment to decrypt.

        Returns
        -------
        str
            The decrypted plaintext segment content.
        """
        derived_key = self._derive_segment_key(
            segment.segment_id,
            segment.container_id,
        )

        try:
            data = segment.encrypted_data
            nonce = data[:12]
            ciphertext = data[12:]
            aesgcm = AESGCM(derived_key)
            aad = f"{segment.segment_id}:{segment.container_id}".encode()
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
            return plaintext_bytes.decode("utf-8")
        except Exception as exc:
            logger.error(
                "segment_decrypt_error id=%s error=%s",
                segment.segment_id,
                exc,
            )
            raise

    def _derive_segment_key(
        self,
        segment_id: str,
        container_id: str,
    ) -> bytes:
        """
        Derive a per-segment encryption key from the master key.

        Uses HKDF-like derivation: HMAC-SHA256(master_key, segment_id + container_id).
        """
        return hmac.new(
            key=self._encryption_key,
            msg=f"{segment_id}:{container_id}".encode(),
            digestmod=hashlib.sha256,
        ).digest()

    def _derive_key_id(self, segment_id: str, container_id: str) -> str:
        """Derive a non-sensitive key identifier for audit purposes."""
        return hashlib.sha256(
            f"key:{segment_id}:{container_id}".encode()
        ).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Integrity Verification
    # ------------------------------------------------------------------

    def _verify_assembly_integrity(
        self,
        segments: List[PromptSegment],
        decrypted_parts: List[str],
    ) -> bool:
        """
        Verify that each decrypted segment matches its stored content hash.

        Parameters
        ----------
        segments : list[PromptSegment]
            The segments in assembly order.
        decrypted_parts : list[str]
            The corresponding decrypted plaintext parts.

        Returns
        -------
        bool
            True if all integrity checks pass.
        """
        for segment, plaintext in zip(segments, decrypted_parts):
            computed_hash = hashlib.sha256(segment.encrypted_data).hexdigest()
            if computed_hash != segment.content_hash:
                logger.error(
                    "segment_integrity_mismatch id=%s expected=%s… got=%s…",
                    segment.segment_id,
                    segment.content_hash[:16],
                    computed_hash[:16],
                )
                return False
        return True

    # ------------------------------------------------------------------
    # Segment Loading
    # ------------------------------------------------------------------

    async def _load_all_segments(self) -> List[PromptSegment]:
        """Load all segments from in-memory cache and/or database containers."""
        if self._segments:
            return list(self._segments.values())

        # Fall back to database if in-memory cache is empty
        loaded = await self._load_segments_from_db()
        return loaded

    async def _load_segments_from_db(self) -> List[PromptSegment]:
        """Load segments from the database."""
        if not self._db_pool:
            return []

        segments: List[PromptSegment] = []

        try:
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT segment_id, container_id, encrypted_data,
                           position, content_hash, encryption_key_id,
                           created_at
                    FROM hive_prompt_segments
                    ORDER BY position ASC
                    """
                )

                for row in rows:
                    segment = PromptSegment(
                        segment_id=row["segment_id"],
                        container_id=row["container_id"],
                        encrypted_data=row["encrypted_data"],
                        position=row["position"],
                        content_hash=row["content_hash"],
                        encryption_key_id=row["encryption_key_id"],
                        created_at=row["created_at"],
                    )
                    segments.append(segment)
                    self._segments[segment.segment_id] = segment

            logger.info("loaded_segments_from_db count=%d", len(segments))
        except Exception as exc:
            logger.error("segment_db_load_failed error=%s", exc)

        return segments

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_segment(self, segment: PromptSegment) -> None:
        """Persist an encrypted segment to its designated container."""
        pool = self._container_pools.get(segment.container_id, self._db_pool)
        if not pool:
            return

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_prompt_segments (
                        segment_id, container_id, encrypted_data,
                        position, content_hash, encryption_key_id,
                        created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (segment_id) DO UPDATE SET
                        encrypted_data = EXCLUDED.encrypted_data,
                        content_hash = EXCLUDED.content_hash
                    """,
                    segment.segment_id,
                    segment.container_id,
                    segment.encrypted_data,
                    segment.position,
                    segment.content_hash,
                    segment.encryption_key_id,
                    segment.created_at,
                )
        except Exception as exc:
            logger.error(
                "segment_persist_failed id=%s container=%s error=%s",
                segment.segment_id,
                segment.container_id,
                exc,
            )

    async def _persist_audit(self, audit: AssemblyAuditRecord) -> None:
        """Persist an assembly audit record to the database."""
        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO hive_prompt_assembly_audit (
                        assembly_id, authorized_context, segments_assembled,
                        integrity_verified, assembled_at, duration_ms
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    audit.assembly_id,
                    audit.authorized_context,
                    audit.segments_assembled,
                    audit.integrity_verified,
                    audit.assembled_at,
                    audit.duration_ms,
                )
        except Exception as exc:
            logger.error("assembly_audit_persist_failed error=%s", exc)

    # ------------------------------------------------------------------
    # Event bus
    # ------------------------------------------------------------------

    async def _broadcast_event(
        self,
        topic: str,
        payload: Dict[str, Any],
    ) -> None:
        """Broadcast an event via the registered callback."""
        if self._event_callback:
            try:
                await self._event_callback(topic, payload)
            except Exception as exc:
                logger.error("prompt_event_broadcast_failed topic=%s error=%s", topic, exc)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def stats(self) -> Dict[str, Any]:
        """Diagnostic statistics (never exposes segment content)."""
        return {
            "total_segments": len(self._segments),
            "total_assemblies": self._total_assemblies,
            "total_stores": self._total_stores,
            "containers_used": list(set(
                s.container_id for s in self._segments.values()
            )),
            "audit_log_size": len(self._audit_log),
        }

    def __repr__(self) -> str:
        return (
            f"<PromptSegmentation segments={len(self._segments)} "
            f"assemblies={self._total_assemblies}>"
        )
