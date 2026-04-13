"""
Nate Memory Crystallizer — Phase 4 of Sovereign Quantum Nate Build.

Harvests knowledge from skyeye_chat, web_wisdom, and wisdom_extractions.
Clusters related items (cosine similarity >= 0.75, 3+ items).
Synthesizes via inference router into intelligence crystals.
Validates via NateResponseValidator. Stores in nate_intelligence_crystals
and embeds in Vectorize nate-wisdom index.

Dual-mode architecture (BLUE/GREEN):
  GREEN (production): PostgreSQL primary, Vectorize + R2 replication
  BLUE  (local dev):  SQLite fallback at data/local_crystals.db,
                      harvests from local files (rules, conversations, tool calls)
  Crystals forged on BLUE sync to GREEN via _sync_to_production().

Cycle: 30-min harvest, 6h cluster/synthesize, 6h decay scan.
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class LocalCrystalStore:
    """SQLite-backed crystal store for BLUE (local dev) when PostgreSQL is unavailable.

    Stores crystals locally and tracks sync status so they can be pushed
    to GREEN (production PostgreSQL) when connectivity is available.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            _data_dir = Path(os.environ.get("CLI_PROJECT_ROOT", ".")) / "backend" / "app" / "websocket" / "data"
            _data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(_data_dir / "local_crystals.db")
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS crystals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crystal_text TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'general',
                scope TEXT NOT NULL DEFAULT 'global',
                topics TEXT DEFAULT '[]',
                source_count INTEGER DEFAULT 1,
                generation INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.6,
                content_hash TEXT UNIQUE NOT NULL,
                context_start TEXT,
                context_end TEXT,
                face_path TEXT,
                recall_count INTEGER DEFAULT 0,
                last_recalled_at TEXT,
                superseded_by TEXT,
                synced_to_production INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS harvest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                fragment_count INTEGER DEFAULT 0,
                harvested_at TEXT NOT NULL
            )
        """)
        self._conn.commit()
        logger.info("LocalCrystalStore ready at %s", self._db_path)

    def store_crystal(self, crystal_text: str, domain: str, scope: str,
                      topics: List[str], source_count: int, confidence: float,
                      content_hash: str, context_start: datetime,
                      context_end: datetime, face_path: Optional[str] = None) -> bool:
        try:
            # Forge-time deduplication: check for existing crystal with same
            # domain and similar content (first 200 chars). If found, strengthen
            # the existing crystal instead of creating a duplicate.
            _prefix = crystal_text[:200].strip()
            existing = self._conn.execute("""
                SELECT content_hash, confidence, source_count
                FROM crystals
                WHERE domain = ? AND scope != 'archived'
                  AND SUBSTR(crystal_text, 1, 200) = ?
                  AND superseded_by IS NULL
                LIMIT 1
            """, (domain, _prefix)).fetchone()

            if existing:
                _new_conf = min(existing[1] + PROMOTION_INCREMENT, PROMOTION_CAP)
                _new_sc = existing[2] + source_count
                _now = datetime.now(timezone.utc).isoformat()
                self._conn.execute("""
                    UPDATE crystals
                    SET confidence = ?, source_count = ?, updated_at = ?
                    WHERE content_hash = ?
                """, (_new_conf, _new_sc, _now, existing[0]))
                self._conn.commit()
                logger.info("Forge dedup: bumped existing crystal %s (%.2f → %.2f)",
                            existing[0][:12], existing[1], _new_conf)
                return False  # not a new crystal

            self._conn.execute("""
                INSERT OR IGNORE INTO crystals
                (crystal_text, domain, scope, topics, source_count, confidence,
                 content_hash, context_start, context_end, face_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (crystal_text, domain, scope, json.dumps(topics), source_count,
                  confidence, content_hash,
                  context_start.isoformat() if context_start else None,
                  context_end.isoformat() if context_end else None,
                  face_path,
                  datetime.now(timezone.utc).isoformat()))
            self._conn.commit()
            return self._conn.total_changes > 0
        except Exception as e:
            logger.warning("LocalCrystalStore.store_crystal failed: %s", e)
            return False

    def get_crystal_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM crystals").fetchone()
        return row[0] if row else 0

    def get_unsynced_crystals(self, limit: int = 50) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT * FROM crystals WHERE synced_to_production = 0
            ORDER BY created_at ASC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_low_confidence_crystals(self, limit: int = 5) -> List[Dict]:
        rows = self._conn.execute("""
            SELECT * FROM crystals WHERE confidence < 0.5
            ORDER BY confidence ASC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def search_crystals(self, query: str, limit: int = 5) -> List[Dict]:
        """Keyword search across BLUE crystal store for recall during inference.
        Also promotes confidence on each successful recall."""
        keywords = [w.lower() for w in query.split() if len(w) > 3][:6]
        if not keywords:
            return []
        like_clauses = " OR ".join(
            "LOWER(crystal_text) LIKE '%' || ? || '%'" for _ in keywords
        )
        rows = self._conn.execute(f"""
            SELECT crystal_text, domain, confidence, content_hash, created_at, recall_count
            FROM crystals
            WHERE scope != 'archived' AND superseded_by IS NULL AND ({like_clauses})
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """, (*keywords, limit)).fetchall()
        recalled = [dict(r) for r in rows]
        if recalled:
            _now = datetime.now(timezone.utc).isoformat()
            for r in recalled:
                new_conf = min(r["confidence"] + PROMOTION_INCREMENT, PROMOTION_CAP)
                new_rc = (r.get("recall_count") or 0) + 1
                self._conn.execute(
                    """UPDATE crystals SET recall_count = ?, confidence = ?,
                       last_recalled_at = ?, updated_at = ?
                       WHERE content_hash = ?""",
                    (new_rc, new_conf, _now, _now, r["content_hash"]))
                r["confidence"] = new_conf
                r["recall_count"] = new_rc
            self._conn.commit()
        return recalled

    def mark_synced(self, content_hashes: List[str]):
        if not content_hashes:
            return
        placeholders = ",".join("?" for _ in content_hashes)
        self._conn.execute(
            f"UPDATE crystals SET synced_to_production = 1 WHERE content_hash IN ({placeholders})",
            content_hashes)
        self._conn.commit()

    def has_been_harvested(self, source: str) -> bool:
        """Check if a source has EVER been harvested (persists across restarts)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM harvest_log WHERE source = ?", (source,)).fetchone()
        return row[0] > 0 if row else False

    def log_harvest(self, source: str, fragment_count: int):
        self._conn.execute(
            "INSERT INTO harvest_log (source, fragment_count, harvested_at) VALUES (?, ?, ?)",
            (source, fragment_count, datetime.now(timezone.utc).isoformat()))
        self._conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        total = self.get_crystal_count()
        synced = self._conn.execute(
            "SELECT COUNT(*) FROM crystals WHERE synced_to_production = 1").fetchone()[0]
        domains = {}
        for row in self._conn.execute(
                "SELECT domain, COUNT(*) as cnt FROM crystals GROUP BY domain").fetchall():
            domains[row[0]] = row[1]
        return {
            "total_crystals": total,
            "synced": synced,
            "unsynced": total - synced,
            "by_domain": domains,
            "db_path": self._db_path,
        }

    def close(self):
        if self._conn:
            self._conn.close()

# Privacy scoping rules
SCOPE_RULES = {
    "skyeye_chat": "admin_only",
    "marketing": "global",
    "client_session": "user:{username}",
    "coaching_aggregate": "global",
    "defense": "admin_only",
    "web_wisdom": "global",
    "wisdom_extraction": "global",
    "coding": "global",
    "checkin_wisdom": "user:{username}",
    "community_wisdom": "global",
    "livestream_wisdom": "global",
    "summon_interaction": "global",
    "me2me_imprint": "user:{username}",
    "me2me_identity": "user:{username}",
    "assessment": "user:{username}",
    "published_content": "global",
    "dojo_mentor": "admin_only",
}

DOMAIN_TEMPERATURES = {
    "clinical": 0.3,
    "defense": 0.3,
    "coding": 0.3,
    "research": 0.6,
    "marketing": 0.8,
    "culture": 0.9,
    "coaching": 0.5,
    "general": 0.6,
    "legal": 0.3,
    "pmp": 0.5,
    "machining": 0.3,
    "teaching": 0.5,
    "business": 0.5,
    "accounting": 0.3,
    "crisis": 0.3,
}

_VALID_DOMAINS = {
    "clinical", "coaching", "marketing", "research", "culture", "defense",
    "general", "coding", "legal", "pmp", "machining", "teaching",
    "business", "accounting", "crisis", "liminal_resolve", "ln_self_curiosity",
}

DECAY_THRESHOLD_DAYS = 90
DECAY_MIN_RECALLS = 3
CONFIDENCE_PRUNE_DAYS = 30
CLUSTER_SIMILARITY_THRESHOLD = 0.75
CLUSTER_MIN_ITEMS = 2

CLUSTER_MIN_ITEMS_BY_DOMAIN = {
    "coding": 2,
    "architecture": 2,
    "operations": 2,
    "defense": 2,
    "clinical": 3,
    "coaching": 3,
    "therapeutic": 3,
    "general": 3,
}

# Domain-specific confidence floors (crystals below this are archived, not deleted)
CONFIDENCE_FLOOR_BY_DOMAIN = {
    "coding": 0.15,
    "defense": 0.15,
    "machining": 0.15,
    "general": 0.20,
    "clinical": 0.25,
    "coaching": 0.20,
    "research": 0.20,
    "marketing": 0.20,
    "culture": 0.20,
    "legal": 0.20,
    "pmp": 0.18,
    "teaching": 0.18,
    "business": 0.18,
    "accounting": 0.20,
    "crisis": 0.30,
}
CONFIDENCE_PRUNE_THRESHOLD = 0.15   # absolute floor — below this in any domain = archived

# Domains that NEVER time-decay (only supersession or confidence <floor removes them)
DECAY_EXEMPT_DOMAINS = frozenset({"coding", "defense", "machining", "crisis"})

# Confidence promotion: import canonical values from crystal_constants
from app.services.crystal_constants import (
    PROMOTION_INCREMENT,
    PROMOTION_CAP,
    CONFIDENCE_TENSION as CONFIDENCE_PROVISIONAL,
    CONFIDENCE_PROMOTED,
    CONFIDENCE_LOCKED,
)

# EXA Methodology: Acceleration mode controls synthesis frequency and budget
_CRYSTAL_ACCELERATION_MODE = os.getenv("CRYSTAL_ACCELERATION_MODE", "false").lower() in ("true", "1", "yes")
SYNTHESIS_BUDGET_NORMAL = 20
SYNTHESIS_BUDGET_ACCELERATION = 80
CLUSTER_INTERVAL_NORMAL_HOURS = 6
CLUSTER_INTERVAL_ACCEL_HOURS = 0.5  # 30 minutes in acceleration mode


def _content_hash(text: str, domain: str = "", scope: str = "", generation: int = 0) -> str:
    """SHA-256 of crystal_text only. Must match verify_crystal_integrity() in quantum_knowledge_field.py."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class NateMemoryCrystallizer:
    """Background agent that harvests, clusters, and crystallizes knowledge.

    Operates in two modes:
      GREEN mode (db_pool available):  Harvests from 18 PostgreSQL tables,
                                       stores to nate_intelligence_crystals.
      BLUE mode  (db_pool is None):    Harvests from local files (rules,
                                       conversations, tool calls), stores
                                       to SQLite via LocalCrystalStore.
    """

    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_harvest = datetime.min.replace(tzinfo=timezone.utc)
        self._last_cluster = datetime.min.replace(tzinfo=timezone.utc)
        self._last_decay = datetime.min.replace(tzinfo=timezone.utc)
        self._harvest_buffer: List[Dict] = []
        self._cycle_count = 0
        self._acceleration_mode = _CRYSTAL_ACCELERATION_MODE
        self._synthesis_count_this_cycle = 0

        self._local_store: Optional[LocalCrystalStore] = None
        self._is_blue = db_pool is None
        if self._is_blue:
            try:
                self._local_store = LocalCrystalStore()
                self._acceleration_mode = True
                print("[CRYSTALLIZER] BLUE mode: SQLite local store active, acceleration=ON")
                logger.info("Crystallizer BLUE mode: SQLite local store active, acceleration=ON")
            except Exception as e:
                print(f"[CRYSTALLIZER] LocalCrystalStore init failed: {e}")
                logger.warning("LocalCrystalStore init failed: %s", e)
        else:
            print("[CRYSTALLIZER] GREEN mode: PostgreSQL primary store")

        self._project_root = Path(os.environ.get("CLI_PROJECT_ROOT", "."))

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NateMemoryCrystallizer started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if getattr(self, "_blue_sync_pool", None):
            try:
                await self._blue_sync_pool.close()
            except Exception:
                pass
            self._blue_sync_pool = None
        logger.info("NateMemoryCrystallizer stopped")

    async def run_maintenance(self) -> Dict:
        """On-demand maintenance: decay stale crystals, resolve contradictions.

        Called by the autonomous controller's learn mode when time budget allows.
        """
        now = datetime.now(timezone.utc)
        try:
            await self._decay_cycle(now)
            self._last_decay = now
            return {"status": "ok", "action": "decay_cycle", "buffer_size": len(self._harvest_buffer)}
        except Exception as e:
            logger.warning("run_maintenance failed: %s", e)
            return {"status": "error", "error": str(e)}

    async def run_organic_ingestion(self) -> Dict:
        """On-demand harvest: pull fresh fragments from all 18 DB sources.

        Called by the autonomous controller when time budget allows.
        """
        now = datetime.now(timezone.utc)
        buffer_before = len(self._harvest_buffer)
        try:
            await self._harvest_cycle(now)
            harvested = len(self._harvest_buffer) - buffer_before
            return {"status": "ok", "action": "harvest_cycle", "new_fragments": harvested,
                    "buffer_size": len(self._harvest_buffer)}
        except Exception as e:
            logger.warning("run_organic_ingestion failed: %s", e)
            return {"status": "error", "error": str(e)}

    async def _run_loop(self):
        _initial_delay = 10 if self._is_blue else 300
        await asyncio.sleep(_initial_delay)
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                await self._harvest_cycle(now)

                cluster_interval = (CLUSTER_INTERVAL_ACCEL_HOURS
                                    if self._acceleration_mode
                                    else CLUSTER_INTERVAL_NORMAL_HOURS)
                hours_since_cluster = (now - self._last_cluster).total_seconds() / 3600
                if hours_since_cluster >= cluster_interval and len(self._harvest_buffer) >= CLUSTER_MIN_ITEMS:
                    self._synthesis_count_this_cycle = 0
                    await self._cluster_and_synthesize_cycle(now)
                    self._last_cluster = now

                hours_since_decay = (now - self._last_decay).total_seconds() / 3600
                if hours_since_decay >= 6:
                    await self._decay_cycle(now)
                    await self._warm_cold_crystals()
                    self._last_decay = now

                # GAP 5: Meta-crystal synthesis on 6h cycle
                if hours_since_cluster >= cluster_interval:
                    try:
                        _cg = getattr(self._app_state, "crystal_graph", None) if self._app_state else None
                        if _cg:
                            await _cg.maybe_rebuild()
                            _meta_results = await _cg.synthesize_meta_crystals(max_meta=5)
                            if _meta_results.get("created", 0):
                                print(f"[CRYSTALLIZER] Meta-crystal synthesis: +{_meta_results['created']} meta-crystals")
                                logger.info("Meta-crystal synthesis: %s", _meta_results)
                    except Exception as _mg_err:
                        logger.warning("Meta-crystal synthesis failed: %s", _mg_err)

                self._cycle_count += 1
            except Exception as e:
                logger.warning("Crystallizer cycle error: %s", e)

            await asyncio.sleep(1800)  # 30 minutes

    # ── Harvest ──

    async def _harvest_cycle(self, now: datetime):
        """Pull new knowledge fragments from multiple sources.

        GREEN mode: queries 18 PostgreSQL tables.
        BLUE mode:  harvests from local files (rules, conversations, tool calls).
        """
        if self._is_blue:
            await self._harvest_local(now)
            return

        since = self._last_harvest
        self._last_harvest = now
        fragments = []

        async with self._db_pool.acquire() as conn:
            # Big Nate Chat
            rows = await conn.fetch("""
                SELECT id, message, sender, created_at
                FROM skyeye_chat
                WHERE created_at > $1 AND sender = 'little_nate'
                ORDER BY created_at ASC LIMIT 200
            """, since)
            for r in rows:
                if len(r["message"]) > 50:
                    fragments.append({
                        "text": r["message"][:2000],
                        "source": "skyeye_chat",
                        "domain": "general",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })

            # Web wisdom — auto-research results (query + searched_at path)
            web_rows = await conn.fetch("""
                SELECT query, summary AS summary_text, searched_at
                FROM web_wisdom
                WHERE searched_at > $1 AND query IS NOT NULL
                  AND summary IS NOT NULL AND LENGTH(summary) > 30
                ORDER BY searched_at ASC LIMIT 100
            """, since)
            for r in web_rows:
                _summary = r["summary_text"]
                if _summary and len(_summary) > 30:
                    fragments.append({
                        "text": f"Q: {r['query']}\nA: {_summary[:1500]}",
                        "source": "web_wisdom",
                        "domain": "research",
                        "scope": "global",
                        "created_at": r["searched_at"],
                    })

            # Web wisdom — RSS feeds via WebContentReader (url + fetched_at path)
            try:
                rss_rows = await conn.fetch("""
                    SELECT title, summary, key_insights, source_type,
                           relevance_score, themes, fetched_at
                    FROM web_wisdom
                    WHERE fetched_at > $1
                      AND (searched_at IS NULL OR searched_at < '2000-01-01')
                      AND summary IS NOT NULL AND LENGTH(summary) > 30
                    ORDER BY fetched_at ASC LIMIT 100
                """, since)
                for r in rss_rows:
                    _text = r["summary"][:1500]
                    _title = r.get("title") or ""
                    if _title:
                        _text = f"{_title}\n{_text}"
                    _insights = r.get("key_insights")
                    if _insights and isinstance(_insights, list):
                        _text += "\nKey insights: " + "; ".join(
                            str(i) for i in _insights[:5]
                        )
                    _src_type = r.get("source_type", "")
                    _domain = "research" if _src_type in (
                        "psychology", "research", "advocacy", "wellness", "mindfulness"
                    ) else "coding" if _src_type == "code" else "general"
                    fragments.append({
                        "text": _text,
                        "source": "web_wisdom",
                        "domain": _domain,
                        "scope": "global",
                        "created_at": r["fetched_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: RSS web_wisdom harvest skipped: %s", e)

            # Wisdom extractions
            wisdom_rows = await conn.fetch("""
                SELECT id, content, insight_type, extracted_at
                FROM wisdom_extractions
                WHERE extracted_at > $1 AND approved = true
                ORDER BY extracted_at ASC LIMIT 100
            """, since)
            for r in wisdom_rows:
                if r["content"] and len(r["content"]) > 20:
                    fragments.append({
                        "text": r["content"][:1500],
                        "source": "wisdom_extraction",
                        "domain": _classify_domain(r.get("insight_type", "")),
                        "scope": "global",
                        "created_at": r["extracted_at"],
                    })

            # Client AI conversations (privacy-safe: only AI responses, never user messages)
            try:
                from app.services.pii_cipher import decrypt_pii
                client_rows = await conn.fetch("""
                    SELECT ai_text, session_id, user_id, created_at,
                           client_timezone, content_encrypted
                    FROM conversation_history
                    WHERE created_at > $1
                      AND ai_text IS NOT NULL
                      AND LENGTH(ai_text) > 100
                    ORDER BY created_at ASC LIMIT 200
                """, since)
                for r in client_rows:
                    _ai_text = r["ai_text"]
                    if r.get("content_encrypted"):
                        _ai_text = decrypt_pii(_ai_text) or ""
                    if _ai_text.startswith("[encrypted"):
                        continue
                    if len(_ai_text) > 100:
                        fragments.append({
                            "text": _ai_text[:2000],
                            "source": "client_session",
                            "domain": "clinical",
                            "scope": f"user:{r['user_id']}",
                            "created_at": r["created_at"],
                            "client_timezone": r.get("client_timezone"),
                        })
            except Exception as e:
                logger.warning("Crystallizer: conversation_history harvest skipped: %s", e)

            # Coach-Nate chat (coaching insights from coach-AI exchanges)
            try:
                coach_rows = await conn.fetch("""
                    SELECT message, coach_username, mode, created_at
                    FROM coach_nate_chat_history
                    WHERE created_at > $1
                      AND role = 'assistant'
                      AND LENGTH(message) > 80
                    ORDER BY created_at ASC LIMIT 150
                """, since)
                for r in coach_rows:
                    fragments.append({
                        "text": r["message"][:2000],
                        "source": "skyeye_chat",
                        "domain": "coaching",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: coach_nate_chat_history harvest skipped: %s", e)

            # Session summaries (AI-generated session insights)
            try:
                summary_rows = await conn.fetch("""
                    SELECT summary_text, session_id, client_id, themes, created_at
                    FROM session_summaries
                    WHERE created_at > $1
                      AND summary_text IS NOT NULL
                      AND LENGTH(summary_text) > 50
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in summary_rows:
                    _themes = r.get("themes") or []
                    _theme_str = ", ".join(_themes[:5]) if isinstance(_themes, list) else ""
                    _text = r["summary_text"][:1500]
                    if _theme_str:
                        _text = f"Themes: {_theme_str}\n{_text}"
                    fragments.append({
                        "text": _text,
                        "source": "wisdom_extraction",
                        "domain": "clinical",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: session_summaries harvest skipped: %s", e)

            # Cycle detections (predictive intelligence)
            try:
                cycle_rows = await conn.fetch("""
                    SELECT id, user_id, domain, detected_period_days, phase_offset, amplitude,
                           confidence, detected_at
                    FROM cycle_detections
                    WHERE detected_at > $1 AND confidence > 0.7
                    ORDER BY detected_at ASC LIMIT 50
                """, since)
                for r in cycle_rows:
                    cycle_domain = r["domain"] or "general"
                    mapped_domain = "clinical" if cycle_domain in (
                        "addiction", "harm_risk", "criminal_intent", "sexual_desire", "porn_addiction"
                    ) else "coaching" if cycle_domain in (
                        "emotional_state", "coping", "legacy"
                    ) else "research"
                    fragments.append({
                        "text": (
                            f"Cycle detected for user {r['user_id']}: {cycle_domain} domain, "
                            f"{r['detected_period_days']:.1f}-day period, phase {r['phase_offset']}, "
                            f"amplitude {r['amplitude']:.2f}, confidence {r['confidence']:.2f}"
                        ),
                        "source": "cycle_detection",
                        "domain": mapped_domain,
                        "scope": f"user:{r['user_id']}",
                        "created_at": r["detected_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: cycle_detections harvest skipped: %s", e)

            # Foresight alerts
            try:
                alert_rows = await conn.fetch("""
                    SELECT id, signal_description, confidence, created_at
                    FROM foresight_alerts
                    WHERE created_at > $1 AND resolved_at IS NULL
                    ORDER BY created_at ASC LIMIT 50
                """, since)
                for r in alert_rows:
                    fragments.append({
                        "text": (
                            f"Foresight alert: {r['signal_description']}. "
                            f"Confidence: {r['confidence']:.2f}"
                        ),
                        "source": "foresight_alert",
                        "domain": "research",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: foresight_alerts harvest skipped: %s", e)

            # ── External + cross-platform sources ──

            # Check-in wisdom (user replies to Nate outreach + AI summaries)
            try:
                checkin_rows = await conn.fetch("""
                    SELECT response_text, ai_summary, user_id, created_at
                    FROM checkin_wisdom
                    WHERE created_at > $1
                      AND (response_text IS NOT NULL OR ai_summary IS NOT NULL)
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in checkin_rows:
                    _text = r.get("ai_summary") or r.get("response_text") or ""
                    if len(_text) > 30:
                        fragments.append({
                            "text": _text[:1500],
                            "source": "checkin_wisdom",
                            "domain": "clinical",
                            "scope": f"user:{r['user_id']}",
                            "created_at": r["created_at"],
                        })
            except Exception as e:
                logger.warning("Crystallizer: checkin_wisdom harvest skipped: %s", e)

            # Community wisdom (anonymous group therapeutic insights)
            try:
                comm_rows = await conn.fetch("""
                    SELECT insight_text, topic, created_at
                    FROM community_wisdom
                    WHERE created_at > $1
                      AND insight_text IS NOT NULL AND LENGTH(insight_text) > 30
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in comm_rows:
                    _text = r["insight_text"][:1500]
                    _topic = r.get("topic") or ""
                    if _topic:
                        _text = f"Topic: {_topic}\n{_text}"
                    fragments.append({
                        "text": _text,
                        "source": "community_wisdom",
                        "domain": "clinical",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: community_wisdom harvest skipped: %s", e)

            # Livestream wisdom (viewer Q&A and Nate responses)
            try:
                live_rows = await conn.fetch("""
                    SELECT viewer_question, nate_response, created_at
                    FROM livestream_wisdom
                    WHERE created_at > $1
                      AND nate_response IS NOT NULL AND LENGTH(nate_response) > 30
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in live_rows:
                    _q = r.get("viewer_question") or ""
                    _a = r["nate_response"][:1500]
                    _text = f"Q: {_q}\nA: {_a}" if _q else _a
                    fragments.append({
                        "text": _text,
                        "source": "livestream_wisdom",
                        "domain": "coaching",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: livestream_wisdom harvest skipped: %s", e)

            # Summon interactions (public summon Q&A)
            try:
                summon_rows = await conn.fetch("""
                    SELECT user_message, nate_response, created_at
                    FROM summon_interactions
                    WHERE created_at > $1
                      AND nate_response IS NOT NULL AND LENGTH(nate_response) > 50
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in summon_rows:
                    _q = r.get("user_message") or ""
                    _a = r["nate_response"][:1500]
                    _text = f"Q: {_q[:500]}\nA: {_a}" if _q else _a
                    fragments.append({
                        "text": _text,
                        "source": "summon_interaction",
                        "domain": "general",
                        "scope": "global",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: summon_interactions harvest skipped: %s", e)

            # Me2Me imprint entries (identity-level content, privacy-scoped)
            try:
                imprint_rows = await conn.fetch("""
                    SELECT content, themes, user_id, captured_at
                    FROM me2me_imprint_entries
                    WHERE captured_at > $1
                      AND content IS NOT NULL AND LENGTH(content) > 30
                    ORDER BY captured_at ASC LIMIT 100
                """, since)
                for r in imprint_rows:
                    _text = r["content"][:1500]
                    _themes = r.get("themes")
                    if _themes and isinstance(_themes, list):
                        _text = f"Themes: {', '.join(str(t) for t in _themes[:5])}\n{_text}"
                    fragments.append({
                        "text": _text,
                        "source": "me2me_imprint",
                        "domain": "clinical",
                        "scope": f"user:{r['user_id']}",
                        "created_at": r["captured_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: me2me_imprint_entries harvest skipped: %s", e)

            # Me2Me identity crystals (pre-synthesized identity wisdom)
            try:
                identity_rows = await conn.fetch("""
                    SELECT therapeutic_journey_summary, growth_narrative,
                           core_values, life_themes, user_id, synthesized_at
                    FROM me2me_identity_crystals
                    WHERE synthesized_at > $1
                      AND (therapeutic_journey_summary IS NOT NULL
                           OR growth_narrative IS NOT NULL)
                    ORDER BY synthesized_at ASC LIMIT 50
                """, since)
                for r in identity_rows:
                    parts = []
                    if r.get("therapeutic_journey_summary"):
                        parts.append(r["therapeutic_journey_summary"][:600])
                    if r.get("growth_narrative"):
                        parts.append(r["growth_narrative"][:600])
                    if r.get("core_values"):
                        parts.append(f"Values: {r['core_values'][:200]}")
                    if r.get("life_themes"):
                        parts.append(f"Themes: {r['life_themes'][:200]}")
                    _text = "\n".join(parts)
                    if len(_text) > 50:
                        fragments.append({
                            "text": _text[:2000],
                            "source": "me2me_identity",
                            "domain": "clinical",
                            "scope": f"user:{r['user_id']}",
                            "created_at": r["synthesized_at"],
                        })
            except Exception as e:
                logger.warning("Crystallizer: me2me_identity_crystals harvest skipped: %s", e)

            # Assessment responses (client assessment answers + reflections)
            try:
                assess_rows = await conn.fetch("""
                    SELECT ar.question_text, ar.answer_text, ar.reflection,
                           da.user_id, ar.created_at
                    FROM assessment_responses ar
                    JOIN dynamic_assessments da ON da.id = ar.assessment_id
                    WHERE ar.created_at > $1
                      AND ar.answer_text IS NOT NULL AND LENGTH(ar.answer_text) > 20
                    ORDER BY ar.created_at ASC LIMIT 100
                """, since)
                for r in assess_rows:
                    _q = r.get("question_text") or ""
                    _a = r["answer_text"][:800]
                    _ref = r.get("reflection") or ""
                    _text = f"Q: {_q}\nA: {_a}"
                    if _ref:
                        _text += f"\nReflection: {_ref[:500]}"
                    fragments.append({
                        "text": _text[:1500],
                        "source": "assessment",
                        "domain": "clinical",
                        "scope": f"user:{r['user_id']}",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: assessment_responses harvest skipped: %s", e)

            # Published content (Nate's posted social content — voice training)
            try:
                content_rows = await conn.fetch("""
                    SELECT content_text, platform, emotion_context, posted_at
                    FROM skyeye_content_queue
                    WHERE posted_at > $1
                      AND status = 'posted'
                      AND content_text IS NOT NULL AND LENGTH(content_text) > 30
                    ORDER BY posted_at ASC LIMIT 100
                """, since)
                for r in content_rows:
                    _platform = r.get("platform") or "unknown"
                    _text = r["content_text"][:1500]
                    _emo = r.get("emotion_context") or ""
                    if _emo:
                        _text = f"[{_platform}] Emotion: {_emo}\n{_text}"
                    else:
                        _text = f"[{_platform}] {_text}"
                    fragments.append({
                        "text": _text,
                        "source": "published_content",
                        "domain": "marketing",
                        "scope": "global",
                        "created_at": r["posted_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: skyeye_content_queue harvest skipped: %s", e)

            # DOJO mentor interactions (mentor Q&A from training sessions)
            try:
                dojo_rows = await conn.fetch("""
                    SELECT content, session_id, interaction_type, created_at
                    FROM dojo_mentor_interactions
                    WHERE created_at > $1
                      AND interaction_type = 'mentor'
                      AND content IS NOT NULL AND LENGTH(content) > 50
                    ORDER BY created_at ASC LIMIT 100
                """, since)
                for r in dojo_rows:
                    fragments.append({
                        "text": r["content"][:1500],
                        "source": "dojo_mentor",
                        "domain": "coaching",
                        "scope": "admin_only",
                        "created_at": r["created_at"],
                    })
            except Exception as e:
                logger.warning("Crystallizer: dojo_mentor_interactions harvest skipped: %s", e)

        # Tables 19-28: additional harvest sources (separate connection scope)
        async with self._db_pool.acquire() as conn2:
            try:
                insight_rows = await conn2.fetch("""
                    SELECT content, category, insight_type, created_at
                    FROM sovereign_insight_journal
                    WHERE created_at > $1 AND content IS NOT NULL AND LENGTH(content) > 50
                    ORDER BY created_at DESC LIMIT 100
                """, since)
                for r in insight_rows:
                    _d = r.get("category") or "general"
                    fragments.append({"text": f"[Insight: {r.get('insight_type', 'general')}] {r['content']}", "source": "insight_journal", "domain": _d if _d in _VALID_DOMAINS else "general", "scope": "global", "created_at": r["created_at"]})
            except Exception as e:
                logger.warning("Crystallizer: sovereign_insight_journal harvest skipped: %s", e)

            try:
                nev_rows = await conn2.fetch("""
                    SELECT user_id, c_emo, p_ent, t_tunnel, gamma_env, biometrics, recorded_at
                    FROM nevedal_metrics WHERE recorded_at > $1 ORDER BY recorded_at DESC LIMIT 50
                """, since)
                for r in nev_rows:
                    _bio = r.get("biometrics") or {}
                    if isinstance(_bio, str):
                        try:
                            _bio = json.loads(_bio)
                        except Exception:
                            _bio = {}
                    fragments.append({"text": f"[Coherence Measurement] C_emo={r.get('c_emo', 0):.4f}, pitch={_bio.get('pitch_mean', 0):.1f}Hz, energy={_bio.get('energy', 0):.3f}, speech_rate={_bio.get('speech_rate', 0):.1f}, p_ent={r.get('p_ent', 0):.3f}, T_tunnel={r.get('t_tunnel', 0):.3f}, gamma_env={r.get('gamma_env', 0):.3f}", "source": "nevedal_metrics", "domain": "clinical", "scope": "admin_only", "created_at": r["recorded_at"]})
            except Exception as e:
                logger.warning("Crystallizer: nevedal_metrics harvest skipped: %s", e)

            try:
                notif_rows = await conn2.fetch("""
                    SELECT platform, notification_type, actor_handle, post_id, created_at
                    FROM skyeye_notifications WHERE created_at > $1 ORDER BY created_at DESC LIMIT 100
                """, since)
                for r in notif_rows:
                    fragments.append({"text": f"[Engagement: {r.get('notification_type', 'unknown')}] Platform: {r.get('platform', '')}, Actor: {r.get('actor_handle', 'unknown')}, Post: {r.get('post_id', 'N/A')}", "source": "skyeye_notifications", "domain": "marketing", "scope": "global", "created_at": r["created_at"]})
            except Exception as e:
                logger.warning("Crystallizer: skyeye_notifications harvest skipped: %s", e)

            try:
                analytics_rows = await conn2.fetch("""
                    SELECT platform, post_id, likes, reposts, comments, impressions, captured_at
                    FROM skyeye_post_analytics WHERE captured_at > $1 ORDER BY captured_at DESC LIMIT 50
                """, since)
                for r in analytics_rows:
                    fragments.append({"text": f"[Post Analytics] {r.get('platform', '')} post {r.get('post_id', '')}: likes={r.get('likes', 0)}, reposts={r.get('reposts', 0)}, comments={r.get('comments', 0)}, impressions={r.get('impressions', 0)}", "source": "post_analytics", "domain": "marketing", "scope": "global", "created_at": r["captured_at"]})
            except Exception as e:
                logger.warning("Crystallizer: skyeye_post_analytics harvest skipped: %s", e)

            try:
                vault_rows = await conn2.fetch("""
                    SELECT content, metadata, user_id, created_at FROM vault_item_annotations
                    WHERE created_at > $1 AND content IS NOT NULL AND LENGTH(content) > 30
                    ORDER BY created_at DESC LIMIT 50
                """, since)
                for r in vault_rows:
                    _meta = r.get("metadata") or {}
                    if isinstance(_meta, str):
                        try:
                            _meta = json.loads(_meta)
                        except Exception:
                            _meta = {}
                    _tags = [f"{k}: {_meta[k]}" for k in ("emotions", "emotion_tags", "scene_tags", "themes") if _meta.get(k)]
                    _text = f"[Photo Analysis] {r['content'][:500]}"
                    if _tags:
                        _text += f" ({', '.join(_tags)})"
                    fragments.append({"text": _text, "source": "vault_annotation", "domain": "clinical", "scope": f"user:{r['user_id']}" if r.get("user_id") else "admin_only", "created_at": r["created_at"]})
            except Exception as e:
                logger.warning("Crystallizer: vault_item_annotations harvest skipped: %s", e)

            try:
                tc_rows = await conn2.fetch("""
                    SELECT member_id, source_platform, crystal, created_at FROM transfer_crystals
                    WHERE created_at > $1 ORDER BY created_at DESC LIMIT 20
                """, since)
                for r in tc_rows:
                    _crystal = r.get("crystal") or {}
                    if isinstance(_crystal, str):
                        try:
                            _crystal = json.loads(_crystal)
                        except Exception:
                            _crystal = {}
                    for key, label in [("core_identity_summary", "Identity"), ("active_therapeutic_themes", "Therapeutic Themes"), ("communication_profile", "Communication"), ("emotional_landscape", "Emotional Landscape"), ("growth_trajectory", "Growth"), ("risk_factors", "Risk Factors")]:
                        text = _crystal.get(key, "")
                        if text and len(text) > 20:
                            fragments.append({"text": f"[Transfer Crystal — {label}] {text[:800]}", "source": "transfer_crystal", "domain": "clinical", "scope": f"user:{r['member_id']}", "created_at": r["created_at"]})
            except Exception as e:
                logger.warning("Crystallizer: transfer_crystals harvest skipped: %s", e)

            try:
                doc_rows = await conn2.fetch("""
                    SELECT member_id, display_name, extracted_text_preview, created_at FROM vault_items
                    WHERE created_at > $1 AND extracted_text_preview IS NOT NULL AND LENGTH(extracted_text_preview) > 50
                    ORDER BY created_at DESC LIMIT 30
                """, since)
                for r in doc_rows:
                    fragments.append({"text": f"[Vault Document: {r.get('display_name', 'untitled')}] {r['extracted_text_preview'][:1500]}", "source": "vault_document", "domain": "clinical", "scope": f"user:{r['member_id']}" if r.get("member_id") else "admin_only", "created_at": r["created_at"]})
            except Exception as e:
                logger.warning("Crystallizer: vault_items document harvest skipped: %s", e)

            try:
                brief_rows = await conn2.fetch("""
                    SELECT briefing_data, coach_id, member_id, session_datetime FROM coach_briefings
                    WHERE session_datetime > $1 AND briefing_data IS NOT NULL ORDER BY session_datetime DESC LIMIT 30
                """, since)
                for r in brief_rows:
                    _bd = r.get("briefing_data") or {}
                    if isinstance(_bd, str):
                        try:
                            _bd = json.loads(_bd)
                        except Exception:
                            _bd = {}
                    _parts = [f"{key}: {val[:300]}" for key in ("recommended_focus", "risk_assessment", "current_state", "trajectory", "prediction") for val in [_bd.get(key, "")] if val and len(val) > 10]
                    if _parts:
                        fragments.append({"text": f"[Coach Briefing] {' | '.join(_parts)}"[:1500], "source": "coach_briefing", "domain": "coaching", "scope": "admin_only", "created_at": r.get("session_datetime", now)})
            except Exception as e:
                logger.warning("Crystallizer: coach_briefings harvest skipped: %s", e)

            try:
                class_rows = await conn2.fetch("""
                    SELECT payload, assessments, analyzed_at FROM classroom_session_analyses
                    WHERE analyzed_at > $1 AND payload IS NOT NULL
                    ORDER BY analyzed_at DESC LIMIT 30
                """, since)
                for r in class_rows:
                    _payload = r.get("payload") or {}
                    if isinstance(_payload, str):
                        try:
                            _payload = json.loads(_payload)
                        except Exception:
                            _payload = {}
                    _strengths = "; ".join(str(s)[:100] for s in (_payload.get("strengths") or [])[:3])
                    _growth = "; ".join(str(g)[:100] for g in (_payload.get("growth_areas") or [])[:3])
                    _text = "[Classroom Analysis]"
                    if _strengths:
                        _text += f" Strengths: {_strengths}"
                    if _growth:
                        _text += f" Growth: {_growth}"
                    if len(_text) > 25:
                        fragments.append({"text": _text[:1500], "source": "classroom_analysis", "domain": "coaching", "scope": "admin_only", "created_at": r.get("analyzed_at", now)})
            except Exception as e:
                logger.warning("Crystallizer: classroom_session_analyses harvest skipped: %s", e)

            try:
                live_rows = await conn2.fetch("""
                    SELECT nate_summary, session_type, coach_id, client_id, ended_at FROM coaching_sessions
                    WHERE ended_at > $1 AND nate_summary IS NOT NULL AND LENGTH(nate_summary) > 30
                    ORDER BY ended_at DESC LIMIT 30
                """, since)
                for r in live_rows:
                    fragments.append({"text": f"[Live Session Summary — {r.get('session_type', 'coaching')}] {r['nate_summary'][:1500]}", "source": "live_session", "domain": "clinical", "scope": "admin_only", "created_at": r.get("ended_at", now)})
            except Exception as e:
                logger.warning("Crystallizer: coaching_sessions nate_summary harvest skipped: %s", e)

        self._harvest_buffer.extend(fragments)

        if fragments:
            logger.info("Crystallizer harvested %d fragments (buffer: %d)", len(fragments), len(self._harvest_buffer))

    # ── BLUE Mode: Local Harvest ──

    async def _harvest_local(self, now: datetime):
        """BLUE mode harvest: pull knowledge from local files when PostgreSQL is unavailable.

        Sources:
          1. Sovereign rules (.sovereign/rules/) — 132 files of domain knowledge
          2. Cursor rules (.cursor/rules/) — 130 files of system architecture knowledge
          3. CLI tool call logs (cli_tool_calls.jsonl) — TENSION resolutions
          4. Night School materials (coaching_tips.txt, etc.)
          5. CLI conversation logs (from nate_cli_chat exchanges)
        """
        since = self._last_harvest
        self._last_harvest = now
        fragments = []
        first_run = since == datetime.min.replace(tzinfo=timezone.utc)

        def _should_harvest(source_key: str) -> bool:
            """Skip sources already harvested in a previous bridge lifetime."""
            if self._local_store and self._local_store.has_been_harvested(source_key):
                return False
            return True

        # Source 1 + 2: Sovereign & Cursor rules (skip if already harvested in a previous lifetime)
        if first_run:
            for rules_dir, label in [
                (self._project_root / ".sovereign" / "rules", "sovereign_rule"),
                (self._project_root / ".cursor" / "rules", "cursor_rule"),
            ]:
                if not _should_harvest(label):
                    print(f"[CRYSTALLIZER] BLUE skip: {label} already harvested")
                    continue
                if rules_dir.is_dir():
                    rule_count = 0
                    for rule_file in sorted(rules_dir.glob("*.md")) + sorted(rules_dir.glob("*.mdc")):
                        try:
                            text = rule_file.read_text(errors="replace")[:3000]
                            if len(text) > 50:
                                _domain = "defense" if any(
                                    k in rule_file.name for k in ("security", "defense", "sentinel", "shield")
                                ) else "coding" if any(
                                    k in rule_file.name for k in ("deploy", "build", "docker", "flutter", "bridge")
                                ) else "general"
                                fragments.append({
                                    "text": f"[{rule_file.name}]\n{text}",
                                    "source": label,
                                    "domain": _domain,
                                    "scope": "global",
                                    "created_at": now,
                                })
                                rule_count += 1
                        except Exception:
                            continue
                    if rule_count and self._local_store:
                        self._local_store.log_harvest(label, rule_count)
                    print(f"[CRYSTALLIZER] BLUE harvest: {rule_count} {label} files")
                    logger.info("BLUE harvest: %d %s files", rule_count, label)

        # Source 3: CLI tool call logs (incremental by date, full scan on first-ever harvest)
        _TOOL_CALL_MAX_FRAGMENTS = 500
        jsonl_path = self._project_root / "backend" / "app" / "websocket" / "data" / "cli_tool_calls.jsonl"
        if jsonl_path.exists():
            _do_full_scan = first_run and _should_harvest("cli_tool_call_full")
            tool_count = 0
            try:
                today_str = now.strftime("%Y-%m-%d")
                with open(jsonl_path, "r") as f:
                    for line_no, line in enumerate(f):
                        if tool_count >= _TOOL_CALL_MAX_FRAGMENTS:
                            break
                        if line_no % 2000 == 1999:
                            await asyncio.sleep(0)
                        try:
                            entry = json.loads(line)
                            entry_date = entry.get("date", "")[:10]
                            if _do_full_scan or entry_date == today_str:
                                if entry.get("success"):
                                    fragments.append({
                                        "text": f"Tool: {entry.get('tool', 'unknown')}, "
                                                f"Query: {entry.get('query', '')[:500]}, "
                                                f"Signal: {entry.get('signal', 'PROVISIONAL')}",
                                        "source": "cli_tool_call",
                                        "domain": "coding",
                                        "scope": "global",
                                        "created_at": now,
                                    })
                                    tool_count += 1
                        except (json.JSONDecodeError, KeyError):
                            continue
            except Exception as e:
                logger.warning("BLUE harvest: cli_tool_calls.jsonl read failed: %s", e)
            if tool_count and self._local_store:
                self._local_store.log_harvest("cli_tool_call", tool_count)
                if _do_full_scan:
                    self._local_store.log_harvest("cli_tool_call_full", tool_count)

        # Source 4: Night School materials (recursive scan for workbooks)
        if first_run and _should_harvest("night_school"):
            ns_dirs = [
                self._project_root / "backend" / "app" / "websocket" / "data" / "Vaults" / "Admin" / "admin_LN_training_folder",
                self._project_root / "backend" / "app" / "websocket" / "data" / "Vaults" / "Admin" / "night_school",
                self._project_root / "backend" / "app" / "websocket" / "data" / "night_school",
            ]
            ns_count = 0
            for ns_dir in ns_dirs:
                if ns_dir.is_dir():
                    for ns_file in sorted(f for f in ns_dir.rglob("*") if f.suffix in (".txt", ".md")):
                        if ns_file.name.startswith(".ingested"):
                            continue
                        try:
                            text = ns_file.read_text(errors="replace")[:3000]
                            if len(text) > 30:
                                _rel = ns_file.relative_to(ns_dir)
                                fragments.append({
                                    "text": f"[Night School: {_rel}]\n{text}",
                                    "source": "night_school",
                                    "domain": "clinical" if any(
                                        k in str(_rel).lower() for k in ("trauma", "attachment", "polyvagal", "memory_recon")
                                    ) else "coaching",
                                    "scope": "global",
                                    "created_at": now,
                                })
                                ns_count += 1
                        except Exception:
                            continue
            if ns_count and self._local_store:
                self._local_store.log_harvest("night_school", ns_count)
            if ns_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {ns_count} Night School files")
                logger.info("BLUE harvest: %d Night School files", ns_count)

        # Source 5: CLI conversation logs (incremental — track last-processed file+line)
        _CONV_MAX_FRAGMENTS = 500
        _CONV_MAX_FILES = 50
        conv_dir = self._project_root / "backend" / "app" / "websocket" / "data" / "cli_conversations"
        if conv_dir.is_dir():
            _already_harvested = self._local_store.has_been_harvested("cli_conversation") if self._local_store else False
            _last_conv_pos = getattr(self, "_conv_last_positions", {})
            conv_count = 0
            _files_processed = 0
            for conv_file in sorted(conv_dir.glob("*.jsonl")):
                if conv_count >= _CONV_MAX_FRAGMENTS or _files_processed >= _CONV_MAX_FILES:
                    break
                _files_processed += 1
                fname = str(conv_file)
                _prev_lines = _last_conv_pos.get(fname, 0) if not first_run else 0
                if first_run and _already_harvested:
                    _prev_lines = _last_conv_pos.get(fname, 999999)
                try:
                    line_no = 0
                    with open(conv_file, "r") as f:
                        for line in f:
                            line_no += 1
                            if line_no <= _prev_lines:
                                continue
                            if conv_count >= _CONV_MAX_FRAGMENTS:
                                break
                            if line_no % 2000 == 1999:
                                await asyncio.sleep(0)
                            try:
                                msg = json.loads(line)
                                if msg.get("role") == "assistant" and len(msg.get("text", "")) > 80:
                                    fragments.append({
                                        "text": msg["text"][:2000],
                                        "source": "cli_conversation",
                                        "domain": "coding",
                                        "scope": "global",
                                        "created_at": now,
                                    })
                                    conv_count += 1
                            except (json.JSONDecodeError, KeyError):
                                continue
                    _last_conv_pos[fname] = line_no
                except Exception:
                    continue
            self._conv_last_positions = _last_conv_pos
            if conv_count and self._local_store:
                self._local_store.log_harvest("cli_conversation", conv_count)

        # Source 6: Git commit history (last 200 commits, first run only)
        _GIT_MAX_COMMITS = 200
        if first_run and _should_harvest("git_history"):
            git_count = 0
            try:
                import subprocess
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["git", "log", f"--max-count={_GIT_MAX_COMMITS}",
                     "--format=%H|%ai|%an|%s"],
                    cwd=str(self._project_root), capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        parts = line.split("|", 3)
                        if len(parts) == 4 and len(parts[0]) == 40:
                            commit_text = (f"[Git Commit {parts[0][:8]}] {parts[1].strip()}\n"
                                           f"Author: {parts[2].strip()}\n"
                                           f"Message: {parts[3].strip()}")
                            if len(commit_text) > 50:
                                fragments.append({
                                    "text": commit_text[:3000],
                                    "source": "git_history",
                                    "domain": "coding",
                                    "scope": "global",
                                    "created_at": now,
                                })
                                git_count += 1
            except Exception as e:
                print(f"[CRYSTALLIZER] Git history harvest failed: {e}")
            if git_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {git_count} git commits")
                if self._local_store:
                    self._local_store.log_harvest("git_history", git_count)

        # Source 7: Project documentation (README, AGENTS.md, patents, marketing)
        if first_run and _should_harvest("project_doc"):
            doc_count = 0
            doc_patterns = ["*.md", "patent/*.md", "Marketing Sales/**/*.md",
                            "docs/*.md", "GKM_DONATION_FRAMEWORK.md"]
            for pattern in doc_patterns:
                for doc_file in sorted(self._project_root.glob(pattern)):
                    if any(skip in str(doc_file) for skip in [".cursor", ".git", "node_modules", "build"]):
                        continue
                    try:
                        text = doc_file.read_text(errors="replace")[:4000]
                        if len(text) > 80:
                            _rel = doc_file.relative_to(self._project_root)
                            _domain = "defense" if "patent" in str(_rel).lower() else \
                                      "marketing" if "marketing" in str(_rel).lower() else \
                                      "research" if "phd" in str(_rel).lower() else "general"
                            fragments.append({
                                "text": f"[Doc: {_rel}]\n{text}",
                                "source": "project_doc",
                                "domain": _domain,
                                "scope": "global",
                                "created_at": now,
                            })
                            doc_count += 1
                    except Exception:
                        continue
            if doc_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {doc_count} project docs (README, patents, marketing)")
                if self._local_store:
                    self._local_store.log_harvest("project_doc", doc_count)

        # Source 8: Bridge operational data (JSON state files with domain knowledge)
        if first_run and _should_harvest("bridge_data"):
            data_dir = self._project_root / "backend" / "app" / "websocket" / "data"
            data_count = 0
            for json_file in sorted(data_dir.glob("*.json")):
                if json_file.name in ("local_crystals.db", ".DS_Store"):
                    continue
                try:
                    text = json_file.read_text(errors="replace")
                    if len(text) > 100 and len(text) < 50000:
                        fragments.append({
                            "text": f"[Bridge Data: {json_file.name}]\n{text[:3000]}",
                            "source": "bridge_data",
                            "domain": "clinical" if any(k in json_file.name for k in
                                ("crisis", "session", "family")) else "general",
                            "scope": "admin_only",
                            "created_at": now,
                        })
                        data_count += 1
                except Exception:
                    continue
            if data_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {data_count} bridge data files")
                if self._local_store:
                    self._local_store.log_harvest("bridge_data", data_count)

        # Source 9: Infrastructure configs (docker-compose, env template, nginx patterns)
        if first_run and _should_harvest("infrastructure"):
            infra_count = 0
            infra_files = [
                "docker-compose.yml", "docker-compose.prod.yml",
                "docker-compose.clone.yml", ".env.template",
                "Dockerfile", "backend/Dockerfile",
                "requirements.txt", "backend/requirements.txt",
            ]
            for fname in infra_files:
                fpath = self._project_root / fname
                if fpath.exists():
                    try:
                        text = fpath.read_text(errors="replace")[:3000]
                        if len(text) > 50:
                            fragments.append({
                                "text": f"[Infra: {fname}]\n{text}",
                                "source": "infrastructure",
                                "domain": "coding",
                                "scope": "admin_only",
                                "created_at": now,
                            })
                            infra_count += 1
                    except Exception:
                        continue
            if infra_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {infra_count} infrastructure configs")
                if self._local_store:
                    self._local_store.log_harvest("infrastructure", infra_count)

        # Source 10: Database migrations (schema evolution history)
        if first_run and _should_harvest("migration"):
            mig_dir = self._project_root / "backend" / "migrations"
            mig_count = 0
            if mig_dir.exists():
                for mig_file in sorted(mig_dir.glob("*.sql")):
                    try:
                        text = mig_file.read_text(errors="replace")[:3000]
                        if len(text) > 30:
                            fragments.append({
                                "text": f"[Migration: {mig_file.name}]\n{text}",
                                "source": "migration",
                                "domain": "coding",
                                "scope": "admin_only",
                                "created_at": now,
                            })
                            mig_count += 1
                    except Exception:
                        continue
            if mig_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {mig_count} database migrations")
                if self._local_store:
                    self._local_store.log_harvest("migration", mig_count)

        # Source 11: Cloudflare Worker scripts (edge intelligence code)
        if first_run and _should_harvest("cloudflare_worker"):
            cf_count = 0
            cf_dir = self._project_root / "cloudflare"
            if cf_dir.exists():
                for cf_file in sorted(cf_dir.rglob("*.js")):
                    try:
                        text = cf_file.read_text(errors="replace")[:3000]
                        if len(text) > 100:
                            _rel = cf_file.relative_to(self._project_root)
                            fragments.append({
                                "text": f"[Worker: {_rel}]\n{text}",
                                "source": "cloudflare_worker",
                                "domain": "coding",
                                "scope": "admin_only",
                                "created_at": now,
                            })
                            cf_count += 1
                    except Exception:
                        continue
                for wrangler in sorted(cf_dir.rglob("wrangler.toml")):
                    try:
                        text = wrangler.read_text(errors="replace")[:2000]
                        if len(text) > 50:
                            _rel = wrangler.relative_to(self._project_root)
                            fragments.append({
                                "text": f"[Wrangler: {_rel}]\n{text}",
                                "source": "cloudflare_worker",
                                "domain": "coding",
                                "scope": "admin_only",
                                "created_at": now,
                            })
                            cf_count += 1
                    except Exception:
                        continue
            if cf_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {cf_count} Cloudflare worker files")
                if self._local_store:
                    self._local_store.log_harvest("cloudflare_worker", cf_count)

        # Source 12: Vault coaching materials and admin training folders
        _VAULT_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".toml", ".html", ".xml", ".rtf"}
        _VAULT_MAX_FILES = 300
        if first_run and _should_harvest("vault_material"):
            vault_count = 0
            vault_dirs = [
                self._project_root / "backend" / "app" / "websocket" / "data" / "Vaults",
                self._project_root / "Vaults",
            ]
            for vd in vault_dirs:
                if not vd.exists():
                    continue
                for vf in sorted(vd.rglob("*")):
                    if vault_count >= _VAULT_MAX_FILES:
                        break
                    if vf.is_dir() or vf.suffix.lower() not in _VAULT_TEXT_SUFFIXES:
                        continue
                    try:
                        text = vf.read_text(errors="replace")[:3000]
                        if len(text) > 50:
                            _rel = str(vf.name)
                            fragments.append({
                                "text": f"[Vault: {_rel}]\n{text}",
                                "source": "vault_material",
                                "domain": "coaching",
                                "scope": "admin_only",
                                "created_at": now,
                            })
                            vault_count += 1
                    except Exception:
                        continue
            if vault_count:
                print(f"[CRYSTALLIZER] BLUE harvest: {vault_count} vault/training materials")
                if self._local_store:
                    self._local_store.log_harvest("vault_material", vault_count)

        self._harvest_buffer.extend(fragments)

        if fragments:
            print(f"[CRYSTALLIZER] BLUE harvested {len(fragments)} fragments (buffer: {len(self._harvest_buffer)})")
            logger.info("BLUE harvested %d fragments (buffer: %d)", len(fragments), len(self._harvest_buffer))

    # ── Cluster + Synthesize ──

    async def _cluster_and_synthesize_cycle(self, now: datetime):
        """Group related fragments and synthesize into crystals."""
        if len(self._harvest_buffer) < CLUSTER_MIN_ITEMS:
            return

        # Solo forge: high-confidence fragments (>= 0.75) bypass clustering
        solo_forged = 0
        _solo_ids: set = set()
        for frag in list(self._harvest_buffer):
            conf = frag.get("confidence", 0)
            if isinstance(conf, (int, float)) and conf >= 0.75:
                crystal_text = frag.get("text", "")
                if crystal_text and len(crystal_text) >= 40:
                    _domain = frag.get("domain", "general")
                    _scope = frag.get("scope", "global")
                    _h = _content_hash(crystal_text, _domain, _scope, 0)
                    _fp = frag.get("face_path", "bridge:mac-blue" if self._is_blue else "")
                    if self._is_blue and self._local_store:
                        stored = self._local_store.store_crystal(
                            crystal_text=crystal_text, domain=_domain, scope=_scope,
                            topics=[frag.get("source", "solo_forge")],
                            source_count=1, confidence=conf, content_hash=_h,
                            context_start=now, context_end=now, face_path=_fp)
                        if stored:
                            _solo_ids.add(id(frag))
                            solo_forged += 1
                            logger.info("Solo forge (BLUE): %s/%s (%.2f conf)",
                                        _domain, _h[:12], conf)
                    elif self._db_pool:
                        try:
                            async with self._db_pool.acquire() as _sf_conn:
                                await _sf_conn.execute("""
                                    INSERT INTO nate_intelligence_crystals
                                    (crystal_text, domain, scope, topics, source_count,
                                     confidence, content_hash, face_path, created_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                                    ON CONFLICT (content_hash) DO NOTHING
                                """, crystal_text, _domain, _scope,
                                    [frag.get("source", "solo_forge")],
                                    1, conf, _h, _fp)
                            _solo_ids.add(id(frag))
                            solo_forged += 1
                            logger.info("Solo forge (GREEN): %s/%s (%.2f conf)",
                                        _domain, _h[:12], conf)
                        except Exception as _sf_err:
                            logger.warning("Solo forge write failed: %s", _sf_err)
        if _solo_ids:
            self._harvest_buffer = [f for f in self._harvest_buffer if id(f) not in _solo_ids]

        clusters = self._cluster_by_domain(self._harvest_buffer)
        crystals_created = solo_forged

        # Preserve unclustered fragments — they haven't had a chance to
        # find siblings yet. Only fragments that participate in a cluster
        # (>= domain min items) are consumed.
        _clustered_ids: set = set()

        for cluster in clusters:
            if self._synthesis_count_this_cycle >= self.synthesis_budget:
                logger.info("Crystallizer: synthesis budget reached (%d/%d)",
                            self._synthesis_count_this_cycle, self.synthesis_budget)
                break

            _domain_min = CLUSTER_MIN_ITEMS_BY_DOMAIN.get(
                cluster.get("domain", "general"), CLUSTER_MIN_ITEMS)
            if len(cluster["items"]) < _domain_min:
                continue

            # Mark these fragments as consumed
            for item in cluster["items"]:
                _clustered_ids.add(id(item))

            crystal_text = await self._synthesize_cluster(cluster)
            if not crystal_text:
                continue

            _rejection_phrases = (
                "temporarily unable", "i cannot", "i'm sorry", "i apologize",
                "as an ai", "i don't have", "unable to process",
            )
            if any(p in crystal_text.lower()[:200] for p in _rejection_phrases):
                logger.warning("Crystal rejected (LLM refusal detected): %s", crystal_text[:100])
                continue

            self._synthesis_count_this_cycle += 1

            # Validate via NateResponseValidator before storage
            validator = getattr(self._app_state, "nate_response_validator", None) if self._app_state else None
            if validator:
                try:
                    _, val_warnings = await validator.validate(crystal_text, {})
                    if validator.is_high_severity(val_warnings):
                        logger.warning("Crystal rejected by validator (high severity): %s", val_warnings)
                        await validator.log_warnings(val_warnings, crystal_text[:200])
                        continue
                except Exception as ve:
                    logger.warning("Crystal validation error (allowing storage): %s", ve)

            # Crystal Integrity Helix verification (defense Layer 3)
            defense = getattr(self._app_state, "distributed_defense", None) if self._app_state else None
            if defense and hasattr(defense, "helix"):
                try:
                    helix_input = {
                        "crystal_text": crystal_text,
                        "domain": cluster["domain"],
                        "content_hash": _content_hash(crystal_text, cluster["domain"], cluster.get("scope", "global"), 0),
                        "scope": cluster.get("scope", "global"),
                        "generation": 0,
                    }
                    verdict = defense.helix.verify(helix_input)
                    if hasattr(verdict, "status") and verdict.status != "INTACT":
                        logger.warning("Crystal failed integrity helix: %s", verdict.status)
                        continue
                except Exception as he:
                    logger.warning("Crystal helix verification error (allowing storage): %s", he)

            # Contradiction Detector (defense Layer 6) — check before storage.
            # Instead of blindly rejecting the new crystal, compare recency
            # and confidence. If the new crystal is more recent, supersede
            # the old one. For ambiguous cases, keep the new crystal and
            # enqueue a research query so the autonomous learner can resolve it.
            try:
                from app.services.contradiction_detector import ContradictionDetector
                _cd = ContradictionDetector(db_pool=self._db_pool)
                _cd_result = await _cd.check(crystal_text, cluster["domain"])
                if _cd_result.has_contradiction and _cd_result.confidence > 0.7:
                    _old_id = _cd_result.contradicting_crystal_id
                    _should_supersede = False
                    _old_confidence = 0.0
                    if _old_id and self._db_pool:
                        try:
                            async with self._db_pool.acquire() as _sc:
                                _old_row = await _sc.fetchrow(
                                    "SELECT confidence FROM nate_intelligence_crystals WHERE id = $1::int",
                                    int(_old_id),
                                )
                                _old_confidence = float(_old_row["confidence"]) if _old_row else 0.0
                                _should_supersede = confidence >= _old_confidence
                        except Exception:
                            pass
                    if _should_supersede and _old_id:
                        try:
                            async with self._db_pool.acquire() as _sc2:
                                await _sc2.execute("""
                                    UPDATE nate_intelligence_crystals
                                    SET scope = 'archived', superseded_by = -1, updated_at = NOW()
                                    WHERE id = $1::int
                                """, int(_old_id))
                            logger.info(
                                "New crystal supersedes old #%s (old conf=%.2f, new conf=%.2f, type=%s)",
                                _old_id, _old_confidence, confidence,
                                _cd_result.contradiction_type,
                            )
                        except Exception as _sup_err:
                            logger.warning("Supersession update failed: %s", _sup_err)
                    else:
                        # Enqueue a research query so the autonomous learner
                        # can gather evidence and resolve the contradiction.
                        _research_hint = crystal_text.split(".")[0][:80]
                        self._harvest_buffer.append({
                            "text": f"[Contradiction Research Needed] {_cd_result.explanation}. "
                                    f"Topic: {_research_hint}",
                            "source": "contradiction_resolver",
                            "domain": cluster["domain"],
                            "scope": "admin_only",
                            "created_at": now,
                        })
                        logger.warning(
                            "Crystal contradicts #%s (%.0f%% conf, type=%s) — "
                            "enqueued research instead of rejecting: %s",
                            _old_id, _cd_result.confidence * 100,
                            _cd_result.contradiction_type,
                            _cd_result.explanation,
                        )
                        continue
            except Exception as cd_err:
                logger.warning("Contradiction detection skipped (allowing storage): %s", cd_err)

            domain = cluster["domain"]
            scope = cluster["scope"]
            h = _content_hash(crystal_text, domain, scope, 0)

            context_times = [i["created_at"] for i in cluster["items"] if i.get("created_at")]
            ctx_start = min(context_times) if context_times else now
            ctx_end = max(context_times) if context_times else now

            tz_set = list({
                i.get("client_timezone") for i in cluster["items"]
                if i.get("client_timezone")
            }) or None

            # Apply workspace verification confidence modifier from fragments
            _base_confidence = 0.6
            _verification_modifiers = [
                i.get("verification", {}).get("confidence_modifier", 0)
                for i in cluster["items"] if i.get("verification")
            ]
            if _verification_modifiers:
                _base_confidence += sum(_verification_modifiers) / len(_verification_modifiers)
            _base_confidence = min(_base_confidence, 0.95)

            face_path = cluster.get("face_path", None)
            if not face_path and self._is_blue:
                face_path = "bridge:mac-blue"
            elif not face_path:
                # SOVEREIGN-VOICE: auto-generate 3-segment face_path for L2 population
                _cl_topics = cluster.get("topics", [])
                _t1 = _cl_topics[0] if _cl_topics else "general"
                _t2 = _cl_topics[1] if len(_cl_topics) > 1 else "observation"
                face_path = f"{domain}/{_t1}/{_t2}"

            # ── Store crystal: BLUE (SQLite) or GREEN (PostgreSQL) ──
            if self._is_blue and self._local_store:
                stored = self._local_store.store_crystal(
                    crystal_text=crystal_text, domain=domain, scope=scope,
                    topics=cluster.get("topics", []),
                    source_count=len(cluster["items"]),
                    confidence=_base_confidence, content_hash=h,
                    context_start=ctx_start, context_end=ctx_end,
                    face_path=face_path)
                if stored:
                    crystals_created += 1
                    print(f"[CRYSTALLIZER] BLUE crystal forged: {domain}/{h[:12]} "
                          f"({_base_confidence:.2f} conf, {len(cluster['items'])} sources)")
                    logger.info("BLUE crystal forged: %s/%s (%.2f conf, %d sources)",
                                domain, h[:12], _base_confidence, len(cluster["items"]))
            elif self._db_pool:
                try:
                    async with self._db_pool.acquire() as conn:
                        # Forge-time dedup: check for existing crystal with same
                        # domain and similar content prefix before inserting
                        _prefix = crystal_text[:200].strip()
                        _existing = await conn.fetchrow("""
                            SELECT id, confidence, source_count FROM nate_intelligence_crystals
                            WHERE domain = $1 AND scope != 'archived'
                              AND LEFT(crystal_text, 200) = $2
                              AND superseded_by IS NULL
                            LIMIT 1
                        """, domain, _prefix)
                        if _existing:
                            _bumped = min(float(_existing["confidence"]) + PROMOTION_INCREMENT, PROMOTION_CAP)
                            await conn.execute("""
                                UPDATE nate_intelligence_crystals
                                SET confidence = $1, source_count = source_count + $2,
                                    updated_at = NOW()
                                WHERE id = $3
                            """, _bumped, len(cluster["items"]), _existing["id"])
                            logger.info("GREEN forge dedup: bumped crystal %s (%.2f → %.2f)",
                                        str(_existing["id"])[:12], float(_existing["confidence"]), _bumped)
                            crystals_created += 0  # not a new crystal
                            continue

                        _crystal_user_id = None
                        if scope and scope.startswith("user:"):
                            _scope_uname = scope[5:]
                            if _scope_uname:
                                _uid_row = await conn.fetchrow(
                                    "SELECT id FROM users WHERE username = $1 OR hardware_id = $1 LIMIT 1",
                                    _scope_uname,
                                )
                                if _uid_row:
                                    _crystal_user_id = _uid_row["id"]

                        await conn.execute("""
                            INSERT INTO nate_intelligence_crystals
                            (crystal_text, domain, scope, topics, source_count,
                             generation, confidence, content_hash, context_start, context_end,
                             face_path, timezone_spread, user_id)
                            VALUES ($1, $2, $3, $4, $5, 0, $6, $7, $8, $9, $10, $11, $12)
                            ON CONFLICT (content_hash) DO NOTHING
                        """, crystal_text, domain, scope,
                            cluster.get("topics", []),
                            len(cluster["items"]),
                            _base_confidence,
                            h, ctx_start, ctx_end, face_path, tz_set,
                            _crystal_user_id)

                    # Index in Vectorize
                    try:
                        from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                        if is_vectorize_configured():
                            await index_wisdom(
                                user_id="nate_crystal",
                                wisdom_id=f"crystal_{h[:16]}",
                                insight_type=f"crystal_{domain}",
                                content=crystal_text,
                                source="crystallizer",
                                domain=domain,
                                timestamp=now.isoformat() if hasattr(now, "isoformat") else str(now),
                                face_path=face_path or "",
                            )
                    except Exception as _vz_err:
                        logger.warning("Crystal Vectorize indexing failed: %s", _vz_err)

                    # L2 face auto-population
                    if face_path and len(face_path.split("/")) >= 3:
                        parts = face_path.split("/")
                        l1_path = "/".join(parts[:2])
                        l2_label = "/".join(parts[2:]) or parts[-1]
                        try:
                            async with self._db_pool.acquire() as l2conn:
                                await l2conn.execute("""
                                    INSERT INTO odpe_l2_faces
                                        (l1_face_path, l2_label, face_path, activation_count, last_activated)
                                    VALUES ($1, $2, $3, 1, NOW())
                                    ON CONFLICT (l1_face_path, l2_label) DO UPDATE SET
                                        activation_count = odpe_l2_faces.activation_count + 1,
                                        last_activated = NOW()
                                """, l1_path, l2_label, face_path)
                        except Exception as _face_err:
                            logger.warning("Crystal ODPE L2 face upsert failed: %s", _face_err)

                    # Replicate to R2
                    try:
                        from app.services.blob_storage import upload_bytes
                        crystal_payload = json.dumps({
                            "crystal_text": crystal_text,
                            "domain": domain, "scope": scope,
                            "content_hash": h, "face_path": face_path,
                            "source_count": len(cluster["items"]),
                            "created_at": now.isoformat(),
                        })
                        await asyncio.to_thread(
                            upload_bytes,
                            rel_path=f"crystals/{h}.json",
                            content=crystal_payload.encode(),
                        )
                    except Exception as r2_err:
                        logger.warning("Crystal R2 replication failed (non-fatal): %s", r2_err)

                    crystals_created += 1
                except Exception as e:
                    logger.warning("Crystal store failed: %s", e)

        # Drain only clustered fragments; preserve orphans for future synthesis.
        # Orphans age out after 48h to prevent unbounded growth of stale fragments.
        _cutoff = now - timedelta(hours=48)
        self._harvest_buffer = [
            f for f in self._harvest_buffer
            if id(f) not in _clustered_ids
            and f.get("created_at", now) > _cutoff
        ]
        if crystals_created:
            _total = self._local_store.get_crystal_count() if self._local_store else "N/A"
            _orphans = len(self._harvest_buffer)
            print(f"[CRYSTALLIZER] Synthesis complete: +{crystals_created} crystals (total: {_total}), {_orphans} fragments maturing")
            logger.info("Crystallizer created %d crystals, %d orphan fragments retained", crystals_created, _orphans)
        elif clusters:
            print(f"[CRYSTALLIZER] Synthesis attempted {len(clusters)} clusters, 0 crystals stored")

        # Sync BLUE crystals to production every cycle (not just on new crystal creation)
        if self._is_blue and self._local_store:
            _api_url = os.environ.get("PRODUCTION_API_URL", "")
            _api_token = os.environ.get("SKYEYE_AUDIT_TOKEN", "")
            _prod_url = os.environ.get("PRODUCTION_DATABASE_URL", "")

            if _api_url and _api_token:
                try:
                    _sync_result = await self._sync_via_api(_api_url, _api_token)
                    if _sync_result.get("synced", 0) > 0:
                        print(f"[CRYSTALLIZER] API sync: {_sync_result}")
                except Exception as _fs_err:
                    logger.warning("Forge-time API sync failed: %s", _fs_err)
            elif _prod_url:
                try:
                    if not getattr(self, "_blue_sync_pool", None):
                        import asyncpg as _sync_pg
                        self._blue_sync_pool = await _sync_pg.create_pool(
                            _prod_url, min_size=1, max_size=2, timeout=10)
                    _sync_result = await self.sync_to_production(self._blue_sync_pool)
                    if _sync_result.get("synced", 0) > 0:
                        print(f"[CRYSTALLIZER] DB sync: {_sync_result}")
                except Exception as _fs_err:
                    self._blue_sync_pool = None
                    logger.debug("Forge-time DB sync skipped: %s", _fs_err)

    # Domains that share enough conceptual overlap to merge fragments.
    # A "research" fragment about polyvagal theory and a "clinical" fragment
    # about vagal tone should cluster together — both feed the Nevedal formula.
    _DOMAIN_AFFINITY = {
        frozenset({"clinical", "research"}): "clinical",
        frozenset({"clinical", "coaching"}): "clinical",
        frozenset({"coaching", "research"}): "coaching",
        frozenset({"defense", "coding"}): "defense",
    }

    def _cluster_by_domain(self, fragments: List[Dict]) -> List[Dict]:
        """Domain+scope clustering — never mixes fragments from different users."""
        domain_scope_groups: Dict[str, List[Dict]] = {}
        for f in fragments:
            d = f.get("domain", "general")
            s = f.get("scope", "global")
            key = f"{d}||{s}"
            domain_scope_groups.setdefault(key, []).append(f)

        # Affinity merge only within the same scope
        merged: set = set()
        for pair, target_domain in self._DOMAIN_AFFINITY.items():
            d1, d2 = tuple(pair)
            scopes_seen = set()
            for key in list(domain_scope_groups.keys()):
                parts = key.split("||", 1)
                if parts[0] in (d1, d2):
                    scopes_seen.add(parts[1] if len(parts) > 1 else "global")
            for scope in scopes_seen:
                k1 = f"{d1}||{scope}"
                k2 = f"{d2}||{scope}"
                if k1 in merged or k2 in merged:
                    continue
                g1 = domain_scope_groups.get(k1, [])
                g2 = domain_scope_groups.get(k2, [])
                if not g1 or not g2:
                    continue
                if len(g1) < CLUSTER_MIN_ITEMS or len(g2) < CLUSTER_MIN_ITEMS:
                    combined = g1 + g2
                    if len(combined) >= CLUSTER_MIN_ITEMS:
                        target_key = f"{target_domain}||{scope}"
                        domain_scope_groups[target_key] = combined
                        if k1 != target_key and k1 in domain_scope_groups:
                            del domain_scope_groups[k1]
                        if k2 != target_key and k2 in domain_scope_groups:
                            del domain_scope_groups[k2]
                        merged.add(k1)
                        merged.add(k2)

        clusters = []
        for key, items in domain_scope_groups.items():
            parts = key.split("||", 1)
            domain = parts[0]
            scope = parts[1] if len(parts) > 1 else "global"
            sub_clusters = self._sub_cluster_by_keywords(items, domain)
            for sc_items in sub_clusters:
                topics = list(set(f.get("source", "") for f in sc_items))
                clusters.append({
                    "domain": domain,
                    "scope": scope,
                    "items": sc_items,
                    "topics": topics[:10],
                })

        return clusters

    @staticmethod
    def _extract_keywords(text: str) -> set:
        """Extract significant keywords from text for similarity comparison."""
        _stop = {"the", "and", "for", "that", "with", "this", "from", "have",
                 "been", "are", "was", "were", "will", "would", "could", "should",
                 "they", "them", "their", "what", "when", "where", "which", "about",
                 "into", "more", "some", "also", "than", "then", "very", "just",
                 "like", "each", "other", "does", "your", "can", "not", "but", "how"}
        words = set()
        for w in text.lower().split():
            w = w.strip(".,;:!?\"'()[]{}/-")
            if len(w) > 3 and w not in _stop:
                words.add(w)
        return words

    _SUB_CLUSTER_CAP = 200

    def _sub_cluster_by_keywords(self, items: List[Dict], domain: str) -> List[List[Dict]]:
        """Split a domain group into keyword-similar sub-clusters.

        Uses Jaccard similarity (>= 0.15) to group fragments that share
        vocabulary, producing tighter clusters than domain-only grouping.
        Falls back to one cluster per domain when all items are small.
        Caps pairwise comparison at _SUB_CLUSTER_CAP to avoid O(n²) hang.
        """
        if len(items) <= CLUSTER_MIN_ITEMS + 1:
            return [items]

        work_items = items[:self._SUB_CLUSTER_CAP]
        overflow = items[self._SUB_CLUSTER_CAP:]

        kw_sets = []
        for it in work_items:
            kw_sets.append(self._extract_keywords(it.get("text", "")[:500]))

        assigned = [False] * len(work_items)
        groups: List[List[Dict]] = []
        JACCARD_THRESHOLD = 0.15

        for i in range(len(work_items)):
            if assigned[i]:
                continue
            group = [work_items[i]]
            assigned[i] = True
            for j in range(i + 1, len(work_items)):
                if assigned[j]:
                    continue
                inter = len(kw_sets[i] & kw_sets[j])
                union = len(kw_sets[i] | kw_sets[j])
                if union > 0 and inter / union >= JACCARD_THRESHOLD:
                    group.append(work_items[j])
                    assigned[j] = True
            if len(group) >= CLUSTER_MIN_ITEMS:
                groups.append(group)

        if overflow and groups:
            groups[-1].extend(overflow)
        elif overflow:
            groups.append(overflow)

        if not groups:
            return [items]
        return groups

    async def synthesize_cluster(self, items: List[Dict], domain: str = "general") -> Optional[str]:
        """Public API for fibre hooks to synthesize a cluster."""
        return await self._synthesize_cluster({"items": items, "domain": domain, "scope": "global"})

    async def _synthesize_cluster(self, cluster: Dict) -> Optional[str]:
        """Use inference router to synthesize fragments into a crystal.

        Priority chain: inference_router → Grok direct → Azure direct → None.
        BLUE mode typically hits Grok (configured via NATE_CHAT_* env vars).
        """
        items = cluster["items"]
        domain = cluster.get("domain", "general")
        temp = DOMAIN_TEMPERATURES.get(domain, 0.6)

        fragments_text = "\n---\n".join(i["text"][:500] for i in items[:10])

        prompt = (
            f"Synthesize these {len(items)} knowledge fragments into a single, "
            f"authoritative insight crystal for the '{domain}' domain.\n\n"
            f"Requirements:\n"
            f"1. Identify SECOND-ORDER patterns — connections between the fragments "
            f"that none of them state individually.\n"
            f"2. Extract the non-obvious principle or mechanism at work.\n"
            f"3. State the crystal as a standalone, actionable truth — someone "
            f"reading it without the source fragments should gain genuine insight.\n"
            f"4. Be precise and factual. Do not invent data or cite studies that "
            f"don't appear in the fragments.\n"
            f"5. If cross-domain connections exist (e.g., clinical insight that "
            f"informs coaching practice), call them out explicitly.\n\n"
            f"{fragments_text}"
        )

        sys_msg = (
            "You are a deep knowledge synthesis engine. Your purpose is not to "
            "summarize — it is to discover the hidden pattern that connects these "
            "fragments and express it as a single crystallized insight. Think like "
            "a researcher finding a unifying principle across disparate observations."
        )

        try:
            # Path 1: inference_router (GREEN mode, backend process)
            inference = getattr(self._app_state, "inference_router", None) if self._app_state else None
            if inference:
                result = await inference.generate(
                    prompt=prompt, system=sys_msg, temperature=temp, max_tokens=500,
                )
                return result.get("text", "").strip() if isinstance(result, dict) else str(result).strip()

            import aiohttp

            # Path 2: Grok direct (BLUE mode primary — $0 via Foundry)
            try:
                from app.services.nate_ai_config import NATE_CHAT_URL, nate_chat_headers, nate_chat_payload
            except ImportError:
                try:
                    from nate_ai_config import NATE_CHAT_URL, nate_chat_headers, nate_chat_payload  # type: ignore
                except ImportError:
                    NATE_CHAT_URL = None

            if NATE_CHAT_URL:
                async with aiohttp.ClientSession() as sess:
                    payload = nate_chat_payload(
                        messages=[
                            {"role": "system", "content": sys_msg},
                            {"role": "user", "content": prompt},
                        ],
                        max_tokens=500,
                        user_id="crystallizer",
                    )
                    payload["temperature"] = temp
                    async with sess.post(
                        NATE_CHAT_URL, headers=nate_chat_headers(),
                        json=payload, timeout=aiohttp.ClientTimeout(total=45),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                return choices[0].get("message", {}).get("content", "").strip()

            # Path 3: Azure direct (fallback)
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            key = os.getenv("AZURE_API_KEY", "")
            deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
            if endpoint and key:
                url = f"https://{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-06-01"
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(url, json={
                        "messages": [
                            {"role": "system", "content": sys_msg},
                            {"role": "user", "content": prompt},
                        ],
                        "max_completion_tokens": 500,
                        "temperature": temp,
                    }, headers={"api-key": key}, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["choices"][0]["message"]["content"].strip()

            return None
        except Exception as e:
            logger.warning("Crystal synthesis failed: %s", e)
            return None

    # ── Decay + Forgetting ──

    async def _decay_cycle(self, now: datetime):
        """Archive stale crystals. Never deletes — always archives.

        Domain-specific rules:
          - coding, defense: NEVER time-decay. Only supersession or confidence
            below domain floor (0.15) removes them.
          - All other domains: archive after 90 days unretrieved with <3 recalls.
          - Confidence pruning uses per-domain floors from CONFIDENCE_FLOOR_BY_DOMAIN.
        BLUE mode: no decay (crystals sync to GREEN for lifecycle management).
        """
        if self._is_blue:
            return
        _exempt = ", ".join(f"'{d}'" for d in DECAY_EXEMPT_DOMAINS)
        async with self._db_pool.acquire() as conn:
            # Time-based decay: archive unretrieved crystals > 90 days with <3 recalls
            # EXEMPT coding + defense — these never time-decay
            decay_cutoff = now - timedelta(days=DECAY_THRESHOLD_DAYS)
            archived = await conn.execute(f"""
                UPDATE nate_intelligence_crystals
                SET scope = 'archived'
                WHERE superseded_by IS NULL
                  AND recall_count < $1
                  AND (last_recalled_at IS NULL OR last_recalled_at < $2)
                  AND created_at < $2
                  AND scope != 'archived'
                  AND domain NOT IN ({_exempt})
            """, DECAY_MIN_RECALLS, decay_cutoff)

            # Domain-specific confidence pruning (archives, never deletes)
            prune_cutoff = now - timedelta(days=CONFIDENCE_PRUNE_DAYS)
            pruned_total = 0
            for domain, floor in CONFIDENCE_FLOOR_BY_DOMAIN.items():
                r = await conn.execute("""
                    UPDATE nate_intelligence_crystals
                    SET scope = 'archived'
                    WHERE domain = $1
                      AND confidence < $2
                      AND created_at < $3
                      AND superseded_by IS NULL
                      AND scope != 'archived'
                """, domain, floor, prune_cutoff)
                _cnt = int(r.split()[-1]) if isinstance(r, str) and r.split()[-1].isdigit() else 0
                pruned_total += _cnt

            logger.info("Decay cycle: time_archived=%s, confidence_pruned=%d", archived, pruned_total)

    async def _warm_cold_crystals(self):
        """Proactively warm cold crystals by matching them against recent conversation topics.

        Runs every 6h alongside decay. Finds cold crystals (recall_count=0) whose
        content matches recent conversation keywords, then gives them a single
        recall increment so they exit the cold pool and enter the normal rotation.
        """
        if self._is_blue or not self._db_pool:
            return
        try:
            async with self._db_pool.acquire() as conn:
                topics_row = await conn.fetch("""
                    SELECT DISTINCT LEFT(user_text, 100) as snippet
                    FROM conversation_history
                    WHERE LENGTH(user_text) > 30
                      AND created_at > NOW() - INTERVAL '7 days'
                    ORDER BY created_at DESC
                    LIMIT 50
                """)
                if not topics_row:
                    return

                keywords = set()
                for row in topics_row:
                    for word in (row["snippet"] or "").split():
                        w = word.strip(".,!?\"'()[]{}:;").lower()
                        if len(w) >= 5 and w.isalpha():
                            keywords.add(w)

                if len(keywords) < 3:
                    return

                query_str = " | ".join(list(keywords)[:30])
                warmed = await conn.execute("""
                    UPDATE nate_intelligence_crystals
                    SET recall_count = 1,
                        last_recalled_at = NOW(),
                        updated_at = NOW()
                    WHERE id IN (
                        SELECT id FROM nate_intelligence_crystals
                        WHERE (recall_count IS NULL OR recall_count = 0)
                          AND scope NOT IN ('archived')
                          AND superseded_by IS NULL
                          AND to_tsvector('english', crystal_text) @@ to_tsquery('english', $1)
                        ORDER BY confidence DESC
                        LIMIT 100
                    )
                """, query_str)
                _cnt = int(warmed.split()[-1]) if isinstance(warmed, str) and warmed.split()[-1].isdigit() else 0
                if _cnt > 0:
                    logger.info("Crystal warming: %d cold crystals matched recent topics", _cnt)
        except Exception as e:
            logger.warning("Crystal warming failed: %s", e)

    # ── Recall tracking ──

    async def record_recall(self, crystal_id: int, odpe_signal: Optional[str] = None, face_path: Optional[str] = None):
        """
        Update recall stats when a crystal is retrieved via semantic search.

        When odpe_signal is provided:
          LOCKED → double reinforcement (recall_count += 2)
          TENSION → standard increment + flag needs_reeval in metadata
          NOISE → no increment (crystal surfaced but discarded)
          Others → standard increment (recall_count += 1)
        """
        if odpe_signal == "NOISE":
            return

        increment = 2 if odpe_signal == "LOCKED" else 1

        # BLUE mode: update local SQLite store directly
        if self._is_blue and self._local_store:
            try:
                _now = datetime.now(timezone.utc).isoformat()
                self._local_store._conn.execute(f"""
                    UPDATE crystals
                    SET recall_count = recall_count + ?,
                        last_recalled_at = ?,
                        updated_at = ?,
                        confidence = MIN(confidence + ? * {PROMOTION_INCREMENT}, {PROMOTION_CAP})
                    WHERE rowid = ?
                """, (increment, _now, _now, increment, crystal_id))
                self._local_store._conn.commit()
            except Exception as e:
                logger.warning("BLUE recall tracking failed for crystal %s: %s", crystal_id, e)
            return

        if not self._db_pool:
            return

        try:
            async with self._db_pool.acquire() as conn:
                if odpe_signal == "TENSION":
                    await conn.execute(f"""
                        UPDATE nate_intelligence_crystals
                        SET last_recalled_at = NOW(),
                            recall_count = recall_count + $2,
                            confidence = LEAST(COALESCE(confidence, 0.5) + $2 * {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                            updated_at = NOW(),
                            metadata = COALESCE(metadata, '{{}}'::jsonb) || '{{"needs_reeval": true}}'::jsonb
                        WHERE id = $1
                    """, crystal_id, increment)
                else:
                    await conn.execute(f"""
                        UPDATE nate_intelligence_crystals
                        SET last_recalled_at = NOW(),
                            recall_count = recall_count + $2,
                            confidence = LEAST(COALESCE(confidence, 0.5) + $2 * {PROMOTION_INCREMENT}, {PROMOTION_CAP}),
                            updated_at = NOW()
                        WHERE id = $1
                    """, crystal_id, increment)
                if face_path:
                    await conn.execute("""
                        UPDATE nate_intelligence_crystals
                        SET face_path = $1
                        WHERE id = $2 AND face_path IS NULL
                    """, face_path, crystal_id)

                # UCD event hook: fire crystal_locked when confidence crosses LOCKED threshold
                if odpe_signal == "LOCKED":
                    try:
                        row = await conn.fetchrow(
                            "SELECT user_id, confidence, domain FROM nate_intelligence_crystals WHERE id = $1",
                            crystal_id,
                        )
                        if row and row["confidence"] and float(row["confidence"]) >= CONFIDENCE_LOCKED:
                            import asyncio as _aio
                            from app.sse.ucd.event_hooks import fire_ucd_event
                            _uid = str(row["user_id"]) if row["user_id"] else None
                            if _uid:
                                _aio.create_task(fire_ucd_event(
                                    _uid, "crystal_locked",
                                    {"crystal_id": crystal_id, "confidence": float(row["confidence"]),
                                     "domain": row["domain"]},
                                    self._db_pool, self._app_state,
                                ))
                    except Exception:
                        pass

        except Exception as e:
            logger.warning("Recall tracking failed for crystal %s: %s", crystal_id, e)

    # ── fetch_relevant (Gap A) — wires crystallizer into neural_tract_pipeline ──

    async def fetch_relevant(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.3,
    ) -> List[Dict]:
        """Retrieve crystals relevant to *query*, updating recall metadata.

        This method is called by ``neural_tract_pipeline.py`` (ascending
        stage 6) and by any other subsystem that holds a reference to the
        crystallizer.  It delegates to LocalCrystalStore in BLUE mode and
        to PostgreSQL keyword + confidence search in GREEN mode.  In both
        cases recalled crystals get their ``recall_count`` and
        ``confidence`` bumped so they progress toward LOCKED status.
        """

        # ── BLUE mode (local SQLite) ──
        if self._is_blue and self._local_store:
            results = self._local_store.search_crystals(query, limit=limit)
            filtered = [r for r in results if r.get("confidence", 0) >= min_confidence][:limit]
            for r in filtered:
                cid = r.get("id")
                if cid:
                    try:
                        self._local_store._conn.execute(
                            "UPDATE crystals SET recall_count = COALESCE(recall_count, 0) + 1, "
                            f"confidence = MIN(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP}), "
                            "last_recalled_at = ? WHERE id = ?",
                            (datetime.now(timezone.utc).isoformat(), cid),
                        )
                        self._local_store._conn.commit()
                    except Exception:
                        pass
            return [
                {
                    "crystal_text": r.get("crystal_text", ""),
                    "domain": r.get("domain", "general"),
                    "confidence": r.get("confidence", 0.5),
                    "recall_count": r.get("recall_count", 0),
                    "content_hash": r.get("content_hash", ""),
                    "source": "blue_local",
                }
                for r in filtered
            ]

        # ── GREEN mode (PostgreSQL) ──
        if not self._db_pool:
            return []

        try:
            async with self._db_pool.acquire() as conn:
                keywords = [w.lower() for w in query.split() if len(w) > 3][:6]
                if not keywords:
                    return []
                like_clauses = " OR ".join(
                    f"LOWER(crystal_text) LIKE '%' || ${i+3} || '%'"
                    for i in range(len(keywords))
                )
                rows = await conn.fetch(f"""
                    SELECT id, crystal_text, domain, confidence, content_hash,
                           recall_count, created_at
                    FROM nate_intelligence_crystals
                    WHERE superseded_by IS NULL
                      AND scope != 'archived'
                      AND confidence >= $1
                      AND ({like_clauses})
                    ORDER BY confidence DESC, recall_count DESC
                    LIMIT $2
                """, min_confidence, limit, *keywords)

                results = []
                now = datetime.now(timezone.utc)
                for row in rows:
                    await conn.execute(f"""
                        UPDATE nate_intelligence_crystals
                        SET recall_count = COALESCE(recall_count, 0) + 1,
                            last_recalled_at = $1,
                            confidence = LEAST(COALESCE(confidence, 0.5) + {PROMOTION_INCREMENT}, {PROMOTION_CAP})
                        WHERE id = $2
                    """, now, row["id"])
                    results.append({
                        "crystal_text": row["crystal_text"],
                        "domain": row["domain"],
                        "confidence": float(row["confidence"]),
                        "recall_count": (row["recall_count"] or 0) + 1,
                        "content_hash": row["content_hash"],
                        "source": "green_pg",
                    })
                return results
        except Exception as e:
            logger.warning("fetch_relevant failed: %s", e)
            return []

    # ── Knowledge Architect ──

    async def propose_index(self, domain: str, topic_cluster: str, crystal_ids: List[str]) -> Dict:
        """Propose a new crystal index grouping. Requires DrNevedal1 approval."""
        proposal_id = str(uuid4())
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                    VALUES ('system', 'crystal_index_proposal', $1, 'info', $2::jsonb, NOW())
                """,
                    f"Index proposal: {domain}/{topic_cluster} ({len(crystal_ids)} crystals)",
                    json.dumps({
                        "proposal_id": proposal_id,
                        "domain": domain,
                        "topic_cluster": topic_cluster,
                        "crystal_ids": crystal_ids,
                        "requires_approval": "DrNevedal1",
                    }),
                )
        except Exception as e:
            logger.warning("Failed to log crystal index proposal: %s", e)

        return {
            "status": "proposed",
            "proposal_id": proposal_id,
            "domain": domain,
            "topic": topic_cluster,
            "crystal_count": len(crystal_ids),
        }

    async def merge_indices(self, source_indices: List[str], target_index: str) -> Dict:
        """Propose merging crystal indices into a single target. Requires DrNevedal1 approval."""
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO skyeye_activity (platform, type, content, severity, metadata, created_at)
                    VALUES ('system', 'crystal_index_merge', $1, 'info', $2::jsonb, NOW())
                """,
                    f"Index merge proposal: {len(source_indices)} sources -> {target_index}",
                    json.dumps({
                        "source_indices": source_indices,
                        "target_index": target_index,
                        "requires_approval": "DrNevedal1",
                    }),
                )
        except Exception as e:
            logger.warning("Failed to log crystal index merge proposal: %s", e)

        return {
            "status": "proposed",
            "source_count": len(source_indices),
            "target": target_index,
        }

    # ── Status ──

    def set_acceleration_mode(self, enabled: bool):
        """Toggle EXA acceleration mode. In accel mode, synthesis runs every
        30min instead of every 6h and the per-cycle budget increases 4x."""
        prev = self._acceleration_mode
        self._acceleration_mode = enabled
        logger.info("Crystal acceleration mode: %s → %s", prev, enabled)

    @property
    def synthesis_budget(self) -> int:
        return (SYNTHESIS_BUDGET_ACCELERATION
                if self._acceleration_mode
                else SYNTHESIS_BUDGET_NORMAL)

    async def _push_blue_watermark(self, api_url: str, api_token: str):
        """Report BLUE local total to GREEN so factory --status shows true count."""
        if not self._local_store:
            return
        try:
            import aiohttp
            url = f"{api_url.rstrip('/')}/api/nate-agent/admin/crystal-network/push"
            headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
            body = {
                "crystals": [],
                "node_id": "mac-blue",
                "node_total": self._local_store.get_crystal_count(),
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(url, json=body, headers=headers) as resp:
                    pass
        except Exception:
            pass

    async def _sync_via_api(self, api_url: str, api_token: str) -> Dict[str, Any]:
        """Push unsynced BLUE crystals to production via REST API."""
        if not self._local_store:
            return {"status": "no_local_store"}
        unsynced = self._local_store.get_unsynced_crystals(limit=100)
        if not unsynced:
            await self._push_blue_watermark(api_url, api_token)
            return {"status": "ok", "synced": 0}

        import aiohttp
        payload = []
        for c in unsynced:
            topics = json.loads(c["topics"]) if isinstance(c["topics"], str) else c["topics"]
            payload.append({
                "crystal_text": c["crystal_text"],
                "domain": c["domain"],
                "scope": c["scope"],
                "topics": topics,
                "source_count": c["source_count"],
                "confidence": c["confidence"],
                "content_hash": c["content_hash"],
                "context_start": c.get("context_start"),
                "context_end": c.get("context_end"),
                "face_path": c.get("face_path") or "bridge:mac-blue",
            })

        url = f"{api_url.rstrip('/')}/api/nate-agent/admin/crystal-network/push"
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        push_body = {
            "crystals": payload,
            "node_id": "mac-blue",
            "node_total": self._local_store.get_crystal_count(),
        }
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(url, json=push_body, headers=headers) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    synced_count = result.get("inserted", 0) + result.get("skipped", 0)
                    synced_hashes = [c["content_hash"] for c in payload]
                    self._local_store.mark_synced(synced_hashes)
                    print(f"[CRYSTALLIZER] API sync: {result.get('inserted', 0)} inserted, "
                          f"{result.get('skipped', 0)} deduped")
                    return {"status": "ok", "synced": synced_count, "via": "api"}
                else:
                    body = await resp.text()
                    return {"status": "error", "code": resp.status, "body": body[:200]}

    async def sync_to_production(self, production_db_pool) -> Dict[str, Any]:
        """Push BLUE-forged crystals to GREEN PostgreSQL + Vectorize + R2.

        Called when BLUE has connectivity to the production database.
        Crystals are written to nate_intelligence_crystals, indexed in
        Vectorize for semantic search, and backed up to R2.
        """
        if not self._local_store:
            return {"status": "no_local_store"}
        unsynced = self._local_store.get_unsynced_crystals(limit=100)
        if not unsynced:
            return {"status": "ok", "synced": 0}

        synced_hashes = []
        vectorized = 0
        r2_backed = 0
        try:
            async with production_db_pool.acquire() as conn:
                for c in unsynced:
                    try:
                        topics = json.loads(c["topics"]) if isinstance(c["topics"], str) else c["topics"]
                        _sync_user_id = None
                        _sync_scope = c.get("scope") or ""
                        if _sync_scope.startswith("user:"):
                            _sync_uname = _sync_scope[5:]
                            if _sync_uname:
                                _uid_row = await conn.fetchrow(
                                    "SELECT id FROM users WHERE username = $1 OR hardware_id = $1 LIMIT 1",
                                    _sync_uname,
                                )
                                if _uid_row:
                                    _sync_user_id = _uid_row["id"]

                        await conn.execute("""
                            INSERT INTO nate_intelligence_crystals
                            (crystal_text, domain, scope, topics, source_count,
                             generation, confidence, content_hash, context_start, context_end,
                             face_path, user_id)
                            VALUES ($1, $2, $3, $4, $5, 0, $6, $7, $8::timestamptz, $9::timestamptz, $10, $11)
                            ON CONFLICT (content_hash) DO NOTHING
                        """, c["crystal_text"], c["domain"], c["scope"],
                            topics, c["source_count"], c["confidence"],
                            c["content_hash"], c.get("context_start"), c.get("context_end"),
                            c.get("face_path") or "bridge:mac-blue",
                            _sync_user_id)
                        synced_hashes.append(c["content_hash"])

                        # Push to Vectorize for semantic search
                        try:
                            from app.services.vectorize_service import index_wisdom, is_vectorize_configured
                            if is_vectorize_configured():
                                await index_wisdom(
                                    user_id="nate_crystal",
                                    wisdom_id=f"crystal_{c['content_hash'][:16]}",
                                    insight_type=f"crystal_{c['domain']}",
                                    content=c["crystal_text"],
                                    source="blue_sync",
                                    domain=c["domain"],
                                )
                                vectorized += 1
                        except Exception:
                            pass

                        # Backup to R2
                        try:
                            from app.services.blob_storage import upload_bytes
                            _key = f"crystals/{c['domain']}/{c['content_hash']}.json"
                            _payload = json.dumps({
                                "crystal_text": c["crystal_text"],
                                "domain": c["domain"],
                                "scope": c["scope"],
                                "topics": topics,
                                "confidence": c["confidence"],
                                "content_hash": c["content_hash"],
                                "synced_from": "BLUE",
                            }).encode()
                            upload_bytes(rel_path=_key, content=_payload,
                                         content_type="application/json")
                            r2_backed += 1
                        except Exception:
                            pass

                    except Exception as row_err:
                        logger.warning("Sync crystal %s failed: %s", c["content_hash"][:12], row_err)
        except Exception as e:
            logger.warning("sync_to_production failed: %s", e)
            return {"status": "error", "error": str(e), "synced": len(synced_hashes)}

        self._local_store.mark_synced(synced_hashes)
        print(f"[CRYSTALLIZER] BLUE→GREEN sync: {len(synced_hashes)} crystals "
              f"(+{vectorized} vectorized, +{r2_backed} R2 backed)")
        logger.info("Synced %d crystals BLUE→GREEN (%d vectorized, %d R2)",
                     len(synced_hashes), vectorized, r2_backed)
        return {
            "status": "ok",
            "synced": len(synced_hashes),
            "vectorized": vectorized,
            "r2_backed": r2_backed,
            "remaining": len(unsynced) - len(synced_hashes),
        }

    def get_status(self) -> Dict[str, Any]:
        status = {
            "running": self._running,
            "mode": "BLUE" if self._is_blue else "GREEN",
            "cycle_count": self._cycle_count,
            "buffer_size": len(self._harvest_buffer),
            "acceleration_mode": self._acceleration_mode,
            "synthesis_budget": self.synthesis_budget,
            "cluster_interval_hours": (CLUSTER_INTERVAL_ACCEL_HOURS
                                       if self._acceleration_mode
                                       else CLUSTER_INTERVAL_NORMAL_HOURS),
            "last_harvest": self._last_harvest.isoformat() if self._last_harvest != datetime.min.replace(tzinfo=timezone.utc) else None,
            "last_cluster": self._last_cluster.isoformat() if self._last_cluster != datetime.min.replace(tzinfo=timezone.utc) else None,
            "last_decay": self._last_decay.isoformat() if self._last_decay != datetime.min.replace(tzinfo=timezone.utc) else None,
        }
        if self._local_store:
            status["local_store"] = self._local_store.get_stats()
        return status


async def auto_execute_index(index_name: str, db_pool) -> Dict[str, Any]:
    """
    Create a Vectorize index via Cloudflare API after admin approval is confirmed in DB.

    Approval must exist in skyeye_activity: type='crystal_index_approved',
    metadata->>'index_name' = index_name, metadata->>'approved_by' = 'DrNevedal1'.

    Uses BGE embedding config: 1024 dimensions, cosine metric.
    """
    if not db_pool:
        return {"status": "error", "error": "No db_pool"}

    try:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT 1 FROM skyeye_activity
                WHERE type = 'crystal_index_approved'
                  AND metadata->>'index_name' = $1
                  AND metadata->>'approved_by' = 'DrNevedal1'
                LIMIT 1
            """, index_name)
        if not row:
            return {
                "status": "not_approved",
                "error": "Admin approval required. Insert crystal_index_approved in skyeye_activity.",
            }
    except Exception as e:
        logger.warning("auto_execute_index: approval check failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}

    try:
        from app.services.vectorize_service import is_vectorize_configured
        if not is_vectorize_configured():
            return {"status": "error", "error": "Vectorize not configured"}

        import os
        import aiohttp
        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        if not account_id or not token:
            return {"status": "error", "error": "Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN"}

        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/vectorize/v2/indexes"
        payload = {
            "name": index_name,
            "description": f"Lived Wisdom domain index: {index_name}",
            "config": {
                "dimensions": 1024,
                "metric": "cosine",
            },
        }

        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    return {"status": "created", "index_name": index_name, "details": data}
                body = await resp.text()
                return {
                    "status": "error",
                    "error": f"Cloudflare API {resp.status}: {body[:300]}",
                }
    except Exception as e:
        logger.warning("auto_execute_index: create failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}


def _classify_domain(insight_type: str) -> str:
    mapping = {
        "clinical": "clinical",
        "coaching": "coaching",
        "therapeutic": "clinical",
        "marketing": "marketing",
        "defense": "defense",
        "cultural": "culture",
        "research": "research",
    }
    for key, domain in mapping.items():
        if key in (insight_type or "").lower():
            return domain
    return "general"
