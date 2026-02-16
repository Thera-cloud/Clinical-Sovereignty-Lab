"""
SOVEREIGN SWARM — Wisdom Mesh Service
Inter-Fibre communication system built on Redis Streams.

Features:
    - Pub/Sub with topic-based and direct routing
    - Priority delivery (low/normal/high/critical)
    - Convergence detection — tiered similarity pipeline:
        1. Azure OpenAI embeddings (highest accuracy, requires API key)
        2. TF-IDF cosine similarity via sklearn (good offline fallback)
        3. Jaccard word-overlap (fast, zero-dependency baseline)
    - Bandwidth management (relevance filtering, temporal batching)
    - Health metrics

Theoretical Basis:
    - Swarm Intelligence (Bonabeau, Dorigo & Theraulaz, 1999) — decentralized
      self-organized systems achieving collective intelligence through local interactions.
    - Stigmergy (Grassé, 1959) — indirect coordination through environmental
      modification, here via shared message streams.
    - Convergence Detection — identifies when independent Fibres reach similar
      conclusions, signaling emergent collective insight.

    References:
        Bonabeau, E., Dorigo, M. & Theraulaz, G. (1999). Swarm Intelligence.
            Oxford University Press.
        Grassé, P.P. (1959). La reconstruction du nid et les coordinations
            interindividuelles chez Bellicositermes natalensis.

Phase 3C — Code Guidelines Section IX / XII.
Embedding-based convergence detection implemented (Phase 5 upgrade).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from uuid import UUID, uuid4

import numpy as np

from app.models.mesh import (
    ConvergenceAlert,
    MeshHealth,
    MeshMessage,
    MeshMessageType,
    MeshPriority,
    MeshTopology,
)
from app.services.exceptions import MeshDeliveryException, MeshBandwidthException

logger = logging.getLogger(__name__)

# ── Similarity backend detection ──
# We probe once at import time so the hot path never pays import cost.

_SIMILARITY_BACKEND: str = "jaccard"  # default fallback

try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine  # type: ignore
    _SIMILARITY_BACKEND = "tfidf"
except ImportError:
    pass

try:
    import httpx  # type: ignore  # used for Azure OpenAI embedding calls
    from app.config import settings as _app_settings
    if _app_settings.AZURE_API_KEY and _app_settings.AZURE_OPENAI_ENDPOINT:
        _SIMILARITY_BACKEND = "embeddings"
except Exception:
    pass

logger.info("Wisdom Mesh similarity backend: %s", _SIMILARITY_BACKEND)


class WisdomMeshService:
    """
    Wisdom Mesh — the communication backbone of the Sovereign Swarm.

    Phase 3: Redis Streams implementation.
    Phase 5: Migrate to Azure Service Bus (same interface).
    """

    # Redis stream names follow topic structure from code guidelines Section 6.2
    STREAM_PREFIX = "mesh:"
    DIRECT_PREFIX = "mesh:direct:"

    # Sourced from centralized swarm config (overridable via SWARM_* env vars)
    from app.swarm_config import swarm_settings as _cfg
    CONVERGENCE_WINDOW_SECONDS = _cfg.MESH_CONVERGENCE_WINDOW_SECONDS
    MAX_MESSAGES_PER_MINUTE = _cfg.MESH_MAX_MESSAGES_PER_MINUTE

    # Default temporal batching window (seconds) for low-priority messages (§5.4)
    DEFAULT_BATCH_WINDOW_SECONDS = _cfg.MESH_BATCH_WINDOW_SECONDS

    def __init__(self, redis_client=None, db_pool=None, immunity_service=None,
                 batch_window_seconds: float = None):
        self._redis = redis_client
        self.db_pool = db_pool
        self._immunity_service = immunity_service
        self._subscriptions: Dict[UUID, Set[str]] = {}  # fibre_id -> set of topics
        self._message_log: List[MeshMessage] = []  # in-memory log (Redis is primary)
        self._convergence_buffer: List[Dict[str, Any]] = []
        self._metrics = {
            "messages_sent": 0,
            "messages_delivered": 0,
            "delivery_failures": 0,
            "convergence_alerts": 0,
            "start_time": datetime.utcnow(),
        }

        # Temporal batching for low-priority messages (PhD Spec §5.3)
        self._batch_window = batch_window_seconds if batch_window_seconds is not None else self.DEFAULT_BATCH_WINDOW_SECONDS
        self._batch_queue: List[MeshMessage] = []
        self._batch_task: Optional[asyncio.Task] = None
        self._batch_lock = asyncio.Lock()

    # ── Connection ──

    async def connect(self, redis_url: str = None) -> None:
        """Connect to Redis if not already connected."""
        if redis_url is None:
            import os
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(redis_url, decode_responses=True)
                await self._redis.ping()
                print(">>> [WISDOM MESH] Connected to Redis")
            except Exception as e:
                print(f">>> [WISDOM MESH] Redis connection failed: {e}")
                self._redis = None

    # ── Publish ──

    async def publish(self, message: MeshMessage) -> bool:
        """
        Publish a message on the Wisdom Mesh.
        Routes by recipient_id (direct) or domain_tags (topic-based).
        Sovereign Immunity guard checks sender identity and anomaly status.

        Low-priority messages are held in a temporal batch queue and flushed
        periodically (PhD Spec §5.4 — bandwidth management via temporal batching).
        """
        # Sovereign Immunity gate
        if self._immunity_service:
            try:
                allowed = await self._immunity_service.guard_message(message)
                if not allowed:
                    self._metrics["delivery_failures"] += 1
                    return False
            except Exception as e:
                print(f">>> [WISDOM MESH] Immunity check error (allowing): {e}")

        # ── Temporal batching for LOW-priority messages (§5.4) ──
        if message.priority == MeshPriority.LOW and self._batch_window > 0:
            return await self._enqueue_batch(message)

        # ── Immediate publish for NORMAL / HIGH / CRITICAL ──
        return await self._publish_immediate(message)

    async def _publish_immediate(self, message: MeshMessage) -> bool:
        """Publish a message immediately (non-batched path)."""
        try:
            self._metrics["messages_sent"] += 1

            # Determine routing
            if message.recipient_id:
                # Direct delivery
                stream_name = f"{self.DIRECT_PREFIX}{message.recipient_id}"
            elif message.domain_tags:
                # Topic-based: publish to each domain tag stream
                for tag in message.domain_tags:
                    stream_name = f"{self.STREAM_PREFIX}{tag}"
                    await self._publish_to_stream(stream_name, message)
                await self._log_message(message)
                return True
            else:
                # Broadcast to general stream
                stream_name = f"{self.STREAM_PREFIX}general"

            await self._publish_to_stream(stream_name, message)
            await self._log_message(message)

            # Add to convergence buffer with PII-redacted body
            redacted_body = self._redact_for_convergence(message.body)
            self._convergence_buffer.append({
                "message_id": str(message.message_id),
                "sender_id": str(message.sender_id),
                "body": redacted_body,
                "domain_tags": message.domain_tags,
                "timestamp": datetime.utcnow(),
            })

            return True

        except Exception as e:
            self._metrics["delivery_failures"] += 1
            print(f">>> [WISDOM MESH] Publish error: {e}")
            return False

    # ── Temporal Batching (PhD Spec §5.4) ──

    async def _enqueue_batch(self, message: MeshMessage) -> bool:
        """
        Add a low-priority message to the temporal batch queue.

        Messages accumulate for up to ``_batch_window`` seconds and are then
        flushed together. This prevents information overload from frequent
        low-priority chatter (heartbeats, routine observations) while
        preserving ordering and convergence buffer inclusion.
        """
        async with self._batch_lock:
            self._batch_queue.append(message)
            logger.debug(
                "Batched low-priority message %s (queue depth: %d)",
                message.message_id, len(self._batch_queue),
            )
            # Ensure the background flusher is running
            if self._batch_task is None or self._batch_task.done():
                self._batch_task = asyncio.create_task(self._batch_flush_loop())
        return True

    async def _batch_flush_loop(self) -> None:
        """
        Background coroutine that waits for the configured batch window
        then flushes all accumulated low-priority messages at once.

        The loop runs once per flush; a new task is spawned on the next
        enqueue if needed, keeping CPU at zero when no low-priority traffic
        is flowing.
        """
        try:
            await asyncio.sleep(self._batch_window)
            await self.flush_batch_queue()
        except asyncio.CancelledError:
            # Graceful shutdown — flush remaining messages immediately
            await self.flush_batch_queue()
        except Exception as e:
            logger.error("Batch flush loop error: %s", e)

    async def flush_batch_queue(self) -> int:
        """
        Flush all queued low-priority messages, publishing each immediately.

        Returns the number of messages flushed.  Thread-safe via ``_batch_lock``.
        """
        async with self._batch_lock:
            to_flush = list(self._batch_queue)
            self._batch_queue.clear()

        flushed = 0
        for msg in to_flush:
            ok = await self._publish_immediate(msg)
            if ok:
                flushed += 1
            else:
                logger.warning("Batch flush failed for message %s", msg.message_id)

        if flushed:
            logger.info(
                "Flushed %d low-priority messages (batch window: %.1fs)",
                flushed, self._batch_window,
            )
        return flushed

    async def _publish_to_stream(self, stream_name: str, message: MeshMessage) -> None:
        """Publish a message to a specific Redis stream."""
        msg_data = {
            "message_id": str(message.message_id),
            "message_type": message.message_type.value,
            "priority": message.priority.value,
            "sender_id": str(message.sender_id),
            "sender_type": message.sender_type,
            "subject": message.subject,
            "body": json.dumps(message.body),
            "domain_tags": json.dumps(message.domain_tags),
            "signature": message.signature or "",
            "created_at": message.created_at.isoformat(),
        }

        if self._redis:
            await self._redis.xadd(
                stream_name, msg_data,
                maxlen=10000,  # keep last 10k messages per stream
            )
        else:
            # Fallback: in-memory only
            self._message_log.append(message)

    # ── Subscribe / Unsubscribe ──

    async def subscribe(self, fibre_id: UUID, topic: str) -> None:
        """Subscribe a Fibre to a topic stream."""
        if fibre_id not in self._subscriptions:
            self._subscriptions[fibre_id] = set()
        self._subscriptions[fibre_id].add(topic)

        # Create Redis consumer group for this Fibre
        stream_name = f"{self.STREAM_PREFIX}{topic}"
        group_name = f"fibre_{fibre_id}"

        if self._redis:
            try:
                await self._redis.xgroup_create(
                    stream_name, group_name, id="0", mkstream=True
                )
            except Exception:
                pass  # Group may already exist

        print(f">>> [WISDOM MESH] {fibre_id} subscribed to '{topic}'")

    async def unsubscribe(self, fibre_id: UUID, topic: str) -> None:
        """Unsubscribe a Fibre from a topic stream."""
        if fibre_id in self._subscriptions:
            self._subscriptions[fibre_id].discard(topic)

        if self._redis:
            try:
                stream_name = f"{self.STREAM_PREFIX}{topic}"
                group_name = f"fibre_{fibre_id}"
                await self._redis.xgroup_delconsumer(
                    stream_name, group_name, str(fibre_id)
                )
            except Exception:
                pass

    # ── Read ──

    async def read_messages(
        self, fibre_id: UUID, count: int = 10, block_ms: int = 0
    ) -> List[Dict[str, Any]]:
        """Read pending messages for a Fibre from all subscribed topics."""
        topics = self._subscriptions.get(fibre_id, set())
        if not topics:
            return []

        messages = []

        # Read from direct stream
        direct_stream = f"{self.DIRECT_PREFIX}{fibre_id}"
        messages.extend(await self._read_stream(direct_stream, fibre_id, count))

        # Read from topic streams
        for topic in topics:
            stream_name = f"{self.STREAM_PREFIX}{topic}"
            messages.extend(await self._read_stream(stream_name, fibre_id, count))

        # Sort by priority then timestamp
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        messages.sort(key=lambda m: (priority_order.get(m.get("priority", "normal"), 2), m.get("created_at", "")))

        self._metrics["messages_delivered"] += len(messages)
        return messages[:count]

    async def _read_stream(
        self, stream_name: str, fibre_id: UUID, count: int
    ) -> List[Dict[str, Any]]:
        """Read messages from a specific Redis stream."""
        if not self._redis:
            return []

        group_name = f"fibre_{fibre_id}"
        try:
            results = await self._redis.xreadgroup(
                groupname=group_name,
                consumername=str(fibre_id),
                streams={stream_name: ">"},
                count=count,
            )

            messages = []
            for stream, entries in results:
                for entry_id, data in entries:
                    data["_stream_id"] = entry_id
                    data["_stream"] = stream
                    if "body" in data and isinstance(data["body"], str):
                        try:
                            data["body"] = json.loads(data["body"])
                        except Exception:
                            pass
                    messages.append(data)

            return messages
        except Exception as e:
            # Stream or group may not exist yet
            return []

    # ── Convergence Detection ──

    async def detect_convergence(self, min_score: float = None) -> List[ConvergenceAlert]:
        """
        Detect when multiple Fibres independently reach similar conclusions.
        Uses cosine similarity on message body content with temporal correlation.
        """
        if min_score is None:
            min_score = self._cfg.MESH_CONVERGENCE_MIN_SCORE
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.CONVERGENCE_WINDOW_SECONDS)

        # Filter recent messages
        recent = [
            m for m in self._convergence_buffer
            if m["timestamp"] >= window_start
        ]

        if len(recent) < 2:
            return []

        # Group by unique senders
        sender_messages: Dict[str, List[Dict]] = {}
        for msg in recent:
            sid = msg["sender_id"]
            if sid not in sender_messages:
                sender_messages[sid] = []
            sender_messages[sid].append(msg)

        if len(sender_messages) < 2:
            return []

        # Compare messages across different senders
        alerts = []
        senders = list(sender_messages.keys())

        for i in range(len(senders)):
            for j in range(i + 1, len(senders)):
                s1_msgs = sender_messages[senders[i]]
                s2_msgs = sender_messages[senders[j]]

                for m1 in s1_msgs:
                    for m2 in s2_msgs:
                        similarity = self._compute_similarity(m1["body"], m2["body"])

                        if similarity >= min_score:
                            # Temporal correlation: closer in time = stronger
                            time_diff = abs((m1["timestamp"] - m2["timestamp"]).total_seconds())
                            temporal = max(0, 1.0 - time_diff / self.CONVERGENCE_WINDOW_SECONDS)

                            # Domain overlap
                            shared_tags = set(m1.get("domain_tags", [])) & set(m2.get("domain_tags", []))

                            alert = ConvergenceAlert(
                                converging_fibre_ids=[UUID(senders[i]), UUID(senders[j])],
                                converging_message_ids=[UUID(m1["message_id"]), UUID(m2["message_id"])],
                                topic=", ".join(shared_tags) if shared_tags else "general",
                                convergence_score=round(similarity, 4),
                                temporal_correlation=round(temporal, 4),
                                domain_tags=list(shared_tags),
                            )
                            alerts.append(alert)
                            self._metrics["convergence_alerts"] += 1

        # Store alerts
        for alert in alerts:
            await self._store_convergence(alert)

        # Clean old buffer entries
        self._convergence_buffer = [
            m for m in self._convergence_buffer
            if m["timestamp"] >= window_start
        ]

        return alerts

    # ── Similarity helpers (module-level backend selected at import) ──

    @staticmethod
    def _body_to_text(body: Any) -> str:
        """Normalise a message body (dict or str) into a plain text string."""
        if isinstance(body, dict):
            return json.dumps(body, default=str)
        return str(body)

    @staticmethod
    def _redact_for_convergence(body: Any) -> Any:
        """Redact PII from message body before storing in convergence buffer.

        Preserves semantic meaning (domain tags, topic keywords) while stripping
        personally identifiable information that could leak therapy details.
        """
        import re
        _PII_PATTERNS = [
            (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL]'),
            (re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'), '[PHONE]'),
            (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[SSN]'),
        ]
        if isinstance(body, str):
            text = body
            for pattern, replacement in _PII_PATTERNS:
                text = pattern.sub(replacement, text)
            return text
        elif isinstance(body, dict):
            redacted = {}
            for k, v in body.items():
                if isinstance(v, str):
                    text = v
                    for pattern, replacement in _PII_PATTERNS:
                        text = pattern.sub(replacement, text)
                    redacted[k] = text
                else:
                    redacted[k] = v
            return redacted
        return body

    @staticmethod
    def _compute_similarity(body1: Any, body2: Any) -> float:
        """
        Compute semantic similarity between two message bodies.

        Tiered strategy (selected once at module import):
            1. **Azure OpenAI embeddings** — highest quality; requires
               AZURE_API_KEY and AZURE_OPENAI_ENDPOINT in env.
            2. **TF-IDF cosine similarity** — good offline fallback using
               sklearn (if installed).
            3. **Jaccard word overlap** — zero-dependency baseline.

        All tiers return a float in [0.0, 1.0].
        """
        text1 = WisdomMeshService._body_to_text(body1)
        text2 = WisdomMeshService._body_to_text(body2)

        if not text1.strip() or not text2.strip():
            return 0.0

        # ── Tier 1: Azure OpenAI Embeddings ──
        if _SIMILARITY_BACKEND == "embeddings":
            try:
                return WisdomMeshService._embedding_similarity(text1, text2)
            except Exception as exc:
                logger.warning("Embedding similarity failed, falling back to TF-IDF: %s", exc)
                # Fall through to TF-IDF / Jaccard

        # ── Tier 2: TF-IDF Cosine Similarity ──
        if _SIMILARITY_BACKEND in ("embeddings", "tfidf"):
            try:
                return WisdomMeshService._tfidf_similarity(text1, text2)
            except Exception as exc:
                logger.warning("TF-IDF similarity failed, falling back to Jaccard: %s", exc)

        # ── Tier 3: Jaccard word overlap ──
        return WisdomMeshService._jaccard_similarity(text1, text2)

    @staticmethod
    def _embedding_similarity(text1: str, text2: str) -> float:
        """
        Compute cosine similarity using Azure OpenAI text-embedding-3-small.
        Uses a synchronous httpx call (the method is static / called from sync context).
        """
        endpoint = _app_settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        # Use text-embedding-3-small — cost-effective and fast
        url = f"{endpoint}/openai/deployments/text-embedding-3-small/embeddings?api-version=2024-06-01"
        headers = {
            "api-key": _app_settings.AZURE_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {"input": [text1, text2]}

        resp = httpx.post(url, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

        emb1 = np.array(data["data"][0]["embedding"], dtype=np.float64)
        emb2 = np.array(data["data"][1]["embedding"], dtype=np.float64)

        # Cosine similarity
        dot = np.dot(emb1, emb2)
        norm = np.linalg.norm(emb1) * np.linalg.norm(emb2)
        if norm == 0:
            return 0.0
        return float(np.clip(dot / norm, 0.0, 1.0))

    @staticmethod
    def _tfidf_similarity(text1: str, text2: str) -> float:
        """Compute cosine similarity on TF-IDF vectors (sklearn)."""
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform([text1, text2])
        sim_matrix = sklearn_cosine(tfidf_matrix[0:1], tfidf_matrix[1:2])
        return float(np.clip(sim_matrix[0][0], 0.0, 1.0))

    @staticmethod
    def _jaccard_similarity(text1: str, text2: str) -> float:
        """Jaccard word-overlap — zero-dependency baseline."""
        w1 = set(text1.lower().split())
        w2 = set(text2.lower().split())
        if not w1 or not w2:
            return 0.0
        intersection = len(w1 & w2)
        union = len(w1 | w2)
        return intersection / union if union > 0 else 0.0

    async def _store_convergence(self, alert: ConvergenceAlert) -> None:
        """Persist a convergence alert to database."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO convergence_alerts
                        (alert_id, converging_fibre_ids, converging_message_ids,
                         topic, convergence_score, temporal_correlation,
                         synthesis, domain_tags)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """, alert.alert_id,
                     [str(fid) for fid in alert.converging_fibre_ids],
                     [str(mid) for mid in alert.converging_message_ids],
                     alert.topic, alert.convergence_score,
                     alert.temporal_correlation, alert.synthesis,
                     alert.domain_tags)
        except Exception as e:
            print(f">>> [WISDOM MESH] Convergence storage error: {e}")

    # ── Health Metrics ──

    async def get_mesh_health(self) -> MeshHealth:
        """Get real-time health metrics for the Wisdom Mesh."""
        elapsed = max(1, (datetime.utcnow() - self._metrics["start_time"]).total_seconds())
        msgs_per_min = (self._metrics["messages_sent"] / elapsed) * 60

        total_sent = max(1, self._metrics["messages_sent"])
        success_rate = (total_sent - self._metrics["delivery_failures"]) / total_sent

        pending = 0
        if self._redis:
            try:
                # Scan mesh streams and sum pending entries across consumer groups
                cursor = b"0"
                while True:
                    cursor, keys = await self._redis.scan(cursor, match=f"{self.STREAM_PREFIX}*", count=100)
                    for key in keys:
                        key_str = key if isinstance(key, str) else key.decode()
                        try:
                            groups = await self._redis.xinfo_groups(key_str)
                            for g in groups:
                                pending += g.get("pending", 0)
                        except Exception:
                            pass  # Stream may have no consumer groups
                    if cursor == b"0" or cursor == 0:
                        break
            except Exception as e:
                print(f">>> [WISDOM MESH] Pending count error: {e}")

        return MeshHealth(
            total_messages_24h=self._metrics["messages_sent"],
            messages_per_minute=round(msgs_per_min, 2),
            average_latency_ms=5.0,  # Redis Streams ≈ 5ms
            delivery_success_rate=round(success_rate, 4),
            bandwidth_utilization=min(1.0, msgs_per_min / self.MAX_MESSAGES_PER_MINUTE),
            active_subscriptions=sum(len(topics) for topics in self._subscriptions.values()),
            pending_messages=pending,
            convergence_alerts_24h=self._metrics["convergence_alerts"],
            batched_messages_pending=len(self._batch_queue),
        )

    # ── Lifecycle ──

    async def disconnect(self) -> None:
        """Close Redis connection and clean up resources."""
        # Cancel batch flusher and flush remaining messages
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
        # Final flush of any remaining batched messages before disconnect
        if self._batch_queue:
            await self.flush_batch_queue()

        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
        self._subscriptions.clear()
        self._message_log.clear()
        self._convergence_buffer.clear()
        self._batch_queue.clear()

    # ── Message Logging ──

    async def _log_message(self, message: MeshMessage) -> None:
        """Persist message to database for audit/replay."""
        if not self.db_pool:
            return
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO wisdom_mesh_messages
                        (message_id, message_type, priority, sender_id, sender_type,
                         recipient_id, domain_tags, topology_level, subject, body,
                         signature, ttl_seconds, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """, message.message_id, message.message_type.value,
                     message.priority.value, message.sender_id,
                     message.sender_type,
                     message.recipient_id,
                     message.domain_tags,
                     message.topology_level.value,
                     message.subject, json.dumps(message.body),
                     message.signature, message.ttl_seconds,
                     json.dumps(message.metadata))
        except Exception as e:
            print(f">>> [WISDOM MESH] Message log error: {e}")
