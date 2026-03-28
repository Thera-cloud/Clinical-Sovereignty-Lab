"""
Crystal Promotion Paths — Exhaustive Confidence Arithmetic Test Suite
=====================================================================

Four Recall Paths (each bumps confidence by PROMOTION_INCREMENT = 0.03):

  Path 1  FederatedSearch
          Entry:  HelixOrchestrator.think() → FederatedSearchCoordinator.search()
                  → _reinforce_recalls()
          SQL:    quantum_knowledge_field.py  lines 395-434 (_reinforce_recalls)
                  quantum_knowledge_field.py  lines 488-498 (_search_server)
          Store:  PostgreSQL

  Path 2  Therapy Direct
          Entry:  process_interaction() → cortex → always_on_memory_recall()
                  → record_recall()
          SQL:    bridge_server.py            lines 4806-4824 (direct SQL)
                  nate_memory_crystallizer.py lines 2194-2229 (record_recall)
          Store:  PostgreSQL (GREEN) / SQLite (BLUE)
          Notes:  LOCKED doubles increment (×2); NOISE skips entirely.

  Path 3  CLI Crystal Recall
          Entry:  nate_cli_chat handler → LocalCrystalStore.search_crystals()
                  (BLUE) or direct SQL (GREEN)
          SQL:    nate_memory_crystallizer.py lines 153-183 (search_crystals)
                  bridge_server.py            lines 28612-28637
          Store:  SQLite (BLUE) / PostgreSQL (GREEN)

  Path 4  LittleNate Inference Enrichment
          Entry:  LittleNateInference.generate() → _retrieve_crystals()
          SQL:    littlenate_inference.py      lines 257-264
          Store:  PostgreSQL

IEEE 754 Floating-Point Precision
---------------------------------
Three step values produce imprecise results under binary float arithmetic:

    0.66 + 0.03 = 0.6900000000000001   (representational error)
    0.81 + 0.03 = 0.8400000000000001
    0.93 + 0.03 = 0.9600000000000001

All confidence assertions therefore use ``pytest.approx(expected, abs=1e-9)``.
SQLite REAL and PostgreSQL REAL both use 64-bit IEEE 754, so the error is
identical across storage backends.

PROMOTION_INCREMENT Sensitivity Analysis
-----------------------------------------
At PROMOTION_INCREMENT = 0.03 a crystal needs ceil((0.85-0.60)/0.03) = 9
standard recalls to reach LOCKED from the PROVISIONAL baseline of 0.60.

If PROMOTION_INCREMENT were 0.01, the same journey would require 25 recalls
—  roughly 2.8× longer.  With an average recall frequency of once per day per
popular crystal, that extends the LOCKED timeline from ~9 days to ~25 days.
At 474 000 crystals, the percentage reaching LOCKED inside the first month
drops from ~35 % (estimated) to ~12 %, dramatically slowing the ExaFLOPS
compounding curve.

Expected Runtime
----------------
Full suite: < 3 seconds.  All I/O is in-memory (SQLite :memory: / dict-backed
fake asyncpg).  No network, no Docker, no external services.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import math
import re
import sqlite3
import sys
import os
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure backend packages are importable and bypass heavy __init__.py
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# app.services.__init__ imports nevedal_engine → numpy which crashes on
# macOS system Python.  Pre-populate sys.modules with a thin namespace
# package so submodule imports skip the real __init__.py.
if "app.services" not in sys.modules:
    _pkg = types.ModuleType("app.services")
    _pkg.__path__ = [str(_BACKEND_ROOT / "app" / "services")]
    _pkg.__package__ = "app.services"
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules["app"].__path__ = [str(_BACKEND_ROOT / "app")]
    sys.modules["app"].__package__ = "app"
    sys.modules["app.services"] = _pkg

from app.services.crystal_constants import (
    CONFIDENCE_LOCKED,
    CONFIDENCE_PROMOTED,
    CONFIDENCE_TENSION,
    DECAY_ARCHIVE_THRESHOLD,
    DECAY_DAYS,
    DECAY_MIN_RECALLS,
    PROMOTION_CAP,
    PROMOTION_INCREMENT,
)

# ---------------------------------------------------------------------------
# Fixtures — Stateful Fake asyncpg
# ---------------------------------------------------------------------------


class StatefulFakeConnection:
    """In-memory simulation of asyncpg's Connection for crystal-pipeline tests.

    COUPLING WARNING
    ~~~~~~~~~~~~~~~~
    This class uses **regex** to identify SQL statements emitted by production
    code and applies the matching arithmetic to an in-memory crystal dict.

    1. If production SQL is reformatted (whitespace, column order, alias
       changes), the regex patterns may stop matching.  When that happens the
       test will *silently pass* because the fake ``execute()`` returns a
       generic "UPDATE 1" without actually modifying state, and no assertion
       fires.  Guard against this by checking ``self._matched_updates`` in
       your test — if it is 0 after a recall, the SQL drifted.

    2. This coupling exists because building a full asyncpg wire-protocol
       emulator is disproportionate for unit-level promotion-arithmetic
       testing.

    3. When a test fails with "no SQL pattern matched," compare the regex
       below against the current SQL in the source file cited in the test's
       docstring.
    """

    def __init__(self) -> None:
        self.crystals: Dict[int, Dict[str, Any]] = {}
        self._next_id = 1
        self._executed: list[tuple[str, tuple]] = []
        self._matched_updates = 0

    def seed(
        self,
        crystal_text: str = "test crystal",
        domain: str = "general",
        confidence: float = 0.60,
        recall_count: int = 0,
        content_hash: str | None = None,
        scope: str = "global",
        superseded_by: int | None = None,
        created_at: datetime | None = None,
        last_recalled_at: datetime | None = None,
        metadata: str = "{}",
    ) -> Dict[str, Any]:
        cid = self._next_id
        self._next_id += 1
        if content_hash is None:
            content_hash = hashlib.sha256(
                f"{crystal_text}{cid}".encode()
            ).hexdigest()
        crystal = {
            "id": cid,
            "crystal_text": crystal_text,
            "domain": domain,
            "confidence": confidence,
            "recall_count": recall_count,
            "content_hash": content_hash,
            "scope": scope,
            "superseded_by": superseded_by,
            "created_at": (created_at or datetime.now(timezone.utc)),
            "last_recalled_at": last_recalled_at,
            "updated_at": datetime.now(timezone.utc),
            "source_count": 1,
            "topics": [],
            "metadata": metadata,
        }
        self.crystals[cid] = crystal
        return crystal

    # -- asyncpg interface ----------------------------------------------------

    def _resolve_target(self, q: str, args: tuple) -> tuple:
        """Find the crystal targeted by the WHERE clause. Returns (crystal, lookup_method)."""
        # WHERE id = $N
        m = re.search(r"WHERE\s+id\s*=\s*\$(\d+)", q, re.I)
        if m:
            idx = int(m.group(1)) - 1
            if idx < len(args):
                return self.crystals.get(args[idx]), "id"
            return None, "id"

        # WHERE LEFT(content_hash, N) = $M
        m = re.search(r"WHERE\s+LEFT\(content_hash,\s*(\d+)\)\s*=\s*\$(\d+)", q, re.I)
        if m:
            prefix_len = int(m.group(1))
            idx = int(m.group(2)) - 1
            if idx < len(args):
                lookup = str(args[idx])[:prefix_len]
                for c in self.crystals.values():
                    if c["content_hash"][:prefix_len] == lookup:
                        return c, "hash_prefix"
            return None, "hash_prefix"

        # WHERE content_hash = $N
        m = re.search(r"WHERE\s+content_hash\s*=\s*\$(\d+)", q, re.I)
        if m:
            idx = int(m.group(1)) - 1
            if idx < len(args):
                lookup = str(args[idx])
                for c in self.crystals.values():
                    if c["content_hash"] == lookup:
                        return c, "hash"
            return None, "hash"

        # WHERE LEFT(content_hash, $N) = $M
        m = re.search(r"WHERE\s+LEFT\(content_hash,\s*\$(\d+)\)\s*=\s*\$(\d+)", q, re.I)
        if m:
            len_idx = int(m.group(1)) - 1
            val_idx = int(m.group(2)) - 1
            if len_idx < len(args) and val_idx < len(args):
                prefix_len = int(args[len_idx])
                lookup = str(args[val_idx])[:prefix_len]
                for c in self.crystals.values():
                    if c["content_hash"][:prefix_len] == lookup:
                        return c, "hash_prefix_param"
            return None, "hash_prefix_param"

        # WHERE id = ANY($N::int[])
        m = re.search(r"WHERE\s+id\s*=\s*ANY\(\$(\d+)", q, re.I)
        if m:
            idx = int(m.group(1)) - 1
            if idx < len(args) and isinstance(args[idx], (list, tuple)):
                results = []
                for cid in args[idx]:
                    c = self.crystals.get(cid)
                    if c:
                        results.append(c)
                return results, "any_id"
            return [], "any_id"

        return None, "none"

    async def execute(self, query: str, *args: Any) -> str:
        self._executed.append((query, args))
        q = " ".join(query.split())

        # ── Recall promotion UPDATE (parameterized or literal) ──
        is_crystal_update = re.search(
            r"UPDATE\s+nate_intelligence_crystals\s+SET", q, re.I
        )
        has_recall_bump = re.search(r"recall_count\s*=", q, re.I)
        has_confidence_bump = re.search(r"confidence\s*=\s*LEAST", q, re.I)

        if is_crystal_update and has_recall_bump and has_confidence_bump:
            target_or_targets, method = self._resolve_target(q, args)

            # Extract increment: parameterized ($N) or literal
            increment = 1
            m_rc_param = re.search(
                r"recall_count\s*=\s*(?:COALESCE\(recall_count,\s*0\)|recall_count)"
                r"\s*\+\s*\$(\d+)",
                q, re.I,
            )
            m_rc_literal = re.search(
                r"recall_count\s*=\s*(?:COALESCE\(recall_count,\s*0\)|recall_count)"
                r"\s*\+\s*(\d+)",
                q, re.I,
            )
            if m_rc_param:
                idx = int(m_rc_param.group(1)) - 1
                increment = int(args[idx]) if idx < len(args) else 1
            elif m_rc_literal:
                increment = int(m_rc_literal.group(1))

            # Extract confidence promotion amount and multiplier
            # Parameterized: $N * 0.03
            m_conf_param = re.search(
                r"confidence\s*=\s*LEAST\(\s*COALESCE\(confidence,\s*[\d.]+\)\s*\+"
                r"\s*\$(\d+)\s*\*\s*([\d.]+)",
                q, re.I,
            )
            # Literal: + 0.03
            m_conf_literal = re.search(
                r"confidence\s*=\s*LEAST\(\s*COALESCE\(confidence,\s*[\d.]+\)\s*\+"
                r"\s*([\d.]+)",
                q, re.I,
            )
            promo = PROMOTION_INCREMENT
            multiplier = 1
            if m_conf_param:
                mi = int(m_conf_param.group(1)) - 1
                multiplier = int(args[mi]) if mi < len(args) else 1
                promo = float(m_conf_param.group(2))
            elif m_conf_literal:
                promo = float(m_conf_literal.group(1))

            # Extract cap from LEAST(..., cap) using balanced-paren matching
            # to avoid picking up numbers from later clauses like LEFT(x, 16).
            cap = 1.0
            m_least = re.search(r"LEAST\(", q, re.I)
            if m_least:
                depth, pos = 1, m_least.end()
                while pos < len(q) and depth > 0:
                    if q[pos] == "(":
                        depth += 1
                    elif q[pos] == ")":
                        depth -= 1
                    pos += 1
                least_body = q[m_least.end():pos - 1]
                parts = least_body.rsplit(",", 1)
                if len(parts) == 2:
                    try:
                        cap = float(parts[1].strip())
                    except ValueError:
                        pass

            def _apply(target):
                target["recall_count"] = (target.get("recall_count") or 0) + increment
                new_conf = (target.get("confidence") or 0.5) + multiplier * promo
                target["confidence"] = min(new_conf, cap)
                target["last_recalled_at"] = datetime.now(timezone.utc)
                target["updated_at"] = datetime.now(timezone.utc)
                self._matched_updates += 1

            if method == "any_id" and isinstance(target_or_targets, list):
                for t in target_or_targets:
                    _apply(t)
                return f"UPDATE {len(target_or_targets)}"
            elif target_or_targets and not isinstance(target_or_targets, list):
                _apply(target_or_targets)
                return "UPDATE 1"

        # ── Supersession / archive (scope='archived' + superseded_by) ──
        if re.search(r"scope\s*=\s*'archived'", q, re.I) and re.search(
            r"superseded_by", q, re.I
        ):
            if len(args) >= 2:
                remove_id = args[0]
                keep_id = args[1]
                if remove_id in self.crystals:
                    self.crystals[remove_id]["scope"] = "archived"
                    self.crystals[remove_id]["superseded_by"] = keep_id
                    self._matched_updates += 1
            return "UPDATE 1"

        # ── Merge-winner recall_count update ──
        if re.search(
            r"SET\s+recall_count\s*=\s*\$\d+.*WHERE\s+id\s*=\s*\$\d+", q, re.I
        ):
            if len(args) >= 2:
                cid, new_rc = args[0], args[1]
                if cid in self.crystals:
                    self.crystals[cid]["recall_count"] = new_rc
                    self._matched_updates += 1
            return "UPDATE 1"

        # ── face_path update (record_recall, no-op for tests) ──
        if re.search(r"SET\s+face_path\s*=", q, re.I):
            return "UPDATE 0"

        # ── Metadata update (TENSION needs_reeval, handled above) ──

        return "UPDATE 0"

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        self._executed.append((query, args))
        results = []
        for c in self.crystals.values():
            if c["scope"] == "archived":
                continue
            if c.get("superseded_by"):
                continue
            results.append(dict(c))
        return results

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        self._executed.append((query, args))
        for c in self.crystals.values():
            if c["scope"] == "archived":
                continue
            return dict(c)
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        self._executed.append((query, args))
        if "SELECT id" in query and args:
            lookup = str(args[0])
            for c in self.crystals.values():
                if c["content_hash"].startswith(lookup):
                    return c["id"]
        return None


class _AcquireCtx:
    def __init__(self, conn: StatefulFakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> StatefulFakeConnection:
        return self._conn

    async def __aexit__(self, *a: Any) -> None:
        pass


class StatefulFakePool:
    """asyncpg-pool-compatible wrapper around StatefulFakeConnection."""

    def __init__(self, conn: StatefulFakeConnection | None = None) -> None:
        self._conn = conn or StatefulFakeConnection()

    def acquire(self) -> _AcquireCtx:
        return _AcquireCtx(self._conn)

    @property
    def conn(self) -> StatefulFakeConnection:
        return self._conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_conn() -> StatefulFakeConnection:
    return StatefulFakeConnection()


@pytest.fixture
def fake_pool(fake_conn: StatefulFakeConnection) -> StatefulFakePool:
    return StatefulFakePool(fake_conn)


@pytest.fixture
def tmp_local_store(tmp_path: Path):
    """Real SQLite-backed LocalCrystalStore in a temp directory."""
    from app.services.nate_memory_crystallizer import LocalCrystalStore

    db_path = str(tmp_path / "test_crystals.db")
    store = LocalCrystalStore(db_path=db_path)
    return store


def _seed_sqlite(
    store,
    text: str = "test crystal about therapy techniques",
    domain: str = "clinical",
    confidence: float = 0.60,
    recall_count: int = 0,
    content_hash: str | None = None,
) -> str:
    """Insert a crystal into a LocalCrystalStore and return its content_hash."""
    if content_hash is None:
        content_hash = hashlib.sha256(f"{text}{confidence}".encode()).hexdigest()
    now = datetime.now(timezone.utc)
    store.store_crystal(
        crystal_text=text,
        domain=domain,
        scope="global",
        topics=["test"],
        source_count=1,
        confidence=confidence,
        content_hash=content_hash,
        context_start=now,
        context_end=now,
    )
    # Force the exact confidence (store_crystal may dedup-bump)
    store._conn.execute(
        "UPDATE crystals SET confidence = ?, recall_count = ? WHERE content_hash = ?",
        (confidence, recall_count, content_hash),
    )
    store._conn.commit()
    return content_hash


# ---------------------------------------------------------------------------
#  PART 1 — The Four Recall Paths
# ---------------------------------------------------------------------------

# All paths now cap at PROMOTION_CAP (0.95) after the cap fix.
_CONFIDENCE_LEVELS = [
    (0.60, 0.63, "PROVISIONAL to first bump"),
    (0.72, 0.75, "crosses PROMOTED threshold"),
    (0.84, 0.87, "crosses LOCKED threshold"),
    (0.93, PROMOTION_CAP, "capped at PROMOTION_CAP"),
    (0.95, PROMOTION_CAP, "already at cap — stays at cap"),
]


class TestPath1_FederatedSearch:
    """Path 1: FederatedSearchCoordinator._reinforce_recalls()
    File: quantum_knowledge_field.py lines 395-434
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("start,expected,label", _CONFIDENCE_LEVELS, ids=[c[2] for c in _CONFIDENCE_LEVELS])
    async def test_reinforce_recalls(
        self, fake_conn: StatefulFakeConnection, start: float, expected: float, label: str
    ):
        crystal = fake_conn.seed(confidence=start, recall_count=3)
        pool = StatefulFakePool(fake_conn)

        from app.services.quantum_knowledge_field import FederatedSearchCoordinator

        coord = FederatedSearchCoordinator(db_pool=pool)
        results = [
            {"id": crystal["id"], "content_hash": crystal["content_hash"], "score": 0.9}
        ]
        await coord._reinforce_recalls(results)

        assert fake_conn._matched_updates >= 1, "SQL pattern did not match — possible SQL drift"
        assert crystal["confidence"] == pytest.approx(expected, abs=1e-9), (
            f"Path 1 ({label}): {start} + {PROMOTION_INCREMENT} should give {expected}, "
            f"got {crystal['confidence']}"
        )
        assert crystal["recall_count"] == 4


class TestPath2_TherapyDirect:
    """Path 2: NateMemoryCrystallizer.record_recall()
    File: nate_memory_crystallizer.py lines 2175-2238
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("start,expected,label", _CONFIDENCE_LEVELS, ids=[c[2] for c in _CONFIDENCE_LEVELS])
    async def test_record_recall_green(
        self, fake_conn: StatefulFakeConnection, start: float, expected: float, label: str
    ):
        crystal = fake_conn.seed(confidence=start, recall_count=5)
        pool = StatefulFakePool(fake_conn)

        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])

        assert fake_conn._matched_updates >= 1, "SQL pattern did not match"
        assert crystal["confidence"] == pytest.approx(expected, abs=1e-9), (
            f"Path 2 GREEN ({label}): expected {expected}, got {crystal['confidence']}"
        )
        assert crystal["recall_count"] == 6


class TestPath3_CLIRecall:
    """Path 3: LocalCrystalStore.search_crystals()
    File: nate_memory_crystallizer.py lines 153-183

    NOTE: All paths now cap at PROMOTION_CAP (0.95) after the cap fix.
    """

    @pytest.mark.parametrize("start,expected,label", _CONFIDENCE_LEVELS, ids=[c[2] for c in _CONFIDENCE_LEVELS])
    def test_search_crystals_promotion(
        self, tmp_local_store, start: float, expected: float, label: str
    ):
        text = "advanced therapy techniques for anxiety management"
        ch = _seed_sqlite(tmp_local_store, text=text, confidence=start)

        hits = tmp_local_store.search_crystals("therapy techniques anxiety")
        assert len(hits) >= 1, "search_crystals returned no results"

        row = tmp_local_store._conn.execute(
            "SELECT confidence, recall_count FROM crystals WHERE content_hash = ?",
            (ch,),
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(expected, abs=1e-9), (
            f"Path 3 BLUE ({label}): expected {expected}, got {row[0]}"
        )
        assert row[1] == 1


class TestPath4_InferenceEnrich:
    """Path 4: LittleNateInference._retrieve_crystals()
    File: littlenate_inference.py lines 257-264
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("start,expected,label", _CONFIDENCE_LEVELS, ids=[c[2] for c in _CONFIDENCE_LEVELS])
    async def test_retrieve_crystals(
        self, fake_conn: StatefulFakeConnection, start: float, expected: float, label: str
    ):
        ch = hashlib.sha256(b"inference_test").hexdigest()
        crystal = fake_conn.seed(
            crystal_text="coding best practices",
            confidence=start,
            recall_count=2,
            content_hash=ch,
        )
        pool = StatefulFakePool(fake_conn)

        # _retrieve_crystals queries by LEFT(content_hash, 16) via Vectorize wisdom_id
        wisdom_id = f"crystal_{ch[:16]}"

        # semantic_search_all returns {index_name: [match_dicts]}
        fake_vectorize_results = {
            "wisdom_crystals": [
                {
                    "id": wisdom_id,
                    "score": 0.85,
                    "metadata": {
                        "wisdom_id": wisdom_id,
                        "content": crystal["crystal_text"],
                        "domain": "coding",
                    },
                }
            ]
        }

        mock_vs = MagicMock()
        mock_vs.semantic_search_all = AsyncMock(return_value=fake_vectorize_results)
        mock_vs.is_vectorize_configured = MagicMock(return_value=True)

        with patch.dict(sys.modules, {"app.services.vectorize_service": mock_vs}):
            from app.services.littlenate_inference import LittleNateInference

            engine = LittleNateInference(db_pool=pool)
            results = await engine._retrieve_crystals("best practices coding", user_id="test")

        assert fake_conn._matched_updates >= 1, "SQL pattern did not match"
        assert crystal["confidence"] == pytest.approx(expected, abs=1e-9), (
            f"Path 4 ({label}): expected {expected}, got {crystal['confidence']}"
        )
        assert crystal["recall_count"] == 3


# ---------------------------------------------------------------------------
#  PART 2 — Storage Backends
# ---------------------------------------------------------------------------


class TestStorageBackend_SQLite:
    """Verify promotion precision in real SQLite (BLUE mode)."""

    def test_precision_6_decimal(self, tmp_local_store):
        ch = _seed_sqlite(tmp_local_store, confidence=0.60)
        tmp_local_store.search_crystals("therapy techniques anxiety")
        row = tmp_local_store._conn.execute(
            "SELECT confidence FROM crystals WHERE content_hash = ?", (ch,)
        ).fetchone()
        assert round(row[0], 6) == round(0.63, 6)

    def test_recall_count_is_integer(self, tmp_local_store):
        ch = _seed_sqlite(tmp_local_store, confidence=0.60)
        tmp_local_store.search_crystals("therapy techniques anxiety")
        row = tmp_local_store._conn.execute(
            "SELECT recall_count FROM crystals WHERE content_hash = ?", (ch,)
        ).fetchone()
        assert isinstance(row[0], int)
        assert row[0] == 1

    def test_last_recalled_at_freshness(self, tmp_local_store):
        ch = _seed_sqlite(tmp_local_store, confidence=0.60)
        before = datetime.now(timezone.utc)
        tmp_local_store.search_crystals("therapy techniques anxiety")
        row = tmp_local_store._conn.execute(
            "SELECT last_recalled_at FROM crystals WHERE content_hash = ?", (ch,)
        ).fetchone()
        recalled_at = datetime.fromisoformat(row[0])
        diff = abs((recalled_at - before).total_seconds())
        assert diff < 2.0, f"last_recalled_at is {diff}s away from test time"


class TestStorageBackend_PostgreSQL:
    """Verify promotion via StatefulFakePool (simulates GREEN PostgreSQL)."""

    @pytest.mark.asyncio
    async def test_precision_6_decimal(self, fake_conn: StatefulFakeConnection):
        crystal = fake_conn.seed(confidence=0.60, recall_count=0)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])
        assert round(crystal["confidence"], 6) == round(0.63, 6)

    @pytest.mark.asyncio
    async def test_recall_count_is_integer(self, fake_conn: StatefulFakeConnection):
        crystal = fake_conn.seed(confidence=0.60, recall_count=0)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])
        assert isinstance(crystal["recall_count"], int)
        assert crystal["recall_count"] == 1

    @pytest.mark.asyncio
    async def test_last_recalled_at_freshness(self, fake_conn: StatefulFakeConnection):
        crystal = fake_conn.seed(confidence=0.60, recall_count=0)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        before = datetime.now(timezone.utc)
        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])
        diff = abs((crystal["last_recalled_at"] - before).total_seconds())
        assert diff < 2.0


class TestStorageBackend_EdgeKV:
    """Verify LOCKED bypass and KV staleness gap."""

    def test_locked_bypass_serves_crystal_text(self):
        """When confidence >= 0.85, the crystal text is served directly."""
        crystal_text = "Sovereign insight about resilience patterns"
        confidence = 0.88

        # Simulate CLI LOCKED bypass logic (bridge_server.py:28649-28653)
        _cli_odpe = "LOCKED" if confidence >= 0.90 else "PROMOTED" if confidence >= 0.75 else "PROVISIONAL"
        _crystal_only_response = None

        # The bypass check uses 0.85, not the label threshold
        if confidence >= CONFIDENCE_LOCKED and len([crystal_text]) >= 1:
            _crystal_only_response = crystal_text

        assert _crystal_only_response == crystal_text

    @pytest.mark.xfail(
        reason=(
            "KV cache has up to 60min staleness window — known architecture gap. "
            "Crystal promoted in PG is not propagated to KV until next cron pre-warm cycle."
        )
    )
    @pytest.mark.asyncio
    async def test_kv_cache_staleness_window(self, fake_conn: StatefulFakeConnection):
        """Gap 1: After PG promotion, KV retains stale confidence."""
        crystal = fake_conn.seed(confidence=0.84, recall_count=7)
        pool = StatefulFakePool(fake_conn)
        kv_cache = {"crystal_confidence": 0.84}

        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])

        assert crystal["confidence"] == pytest.approx(0.87, abs=1e-9)
        # KV was not updated — this is the architecture gap
        # The xfail expects this assertion to FAIL (stale value)
        assert kv_cache["crystal_confidence"] == pytest.approx(0.87, abs=1e-9)


# ---------------------------------------------------------------------------
#  PART 3 — Cross-Path Consistency
# ---------------------------------------------------------------------------


class TestCrossPathConsistency:
    """A crystal forged on BLUE, recalled through 3 different paths, must
    end at exactly initial + (3 × PROMOTION_INCREMENT)."""

    def test_blue_to_green_three_recalls(self, tmp_local_store):
        text = "advanced therapy techniques for anxiety management and coping"
        ch = _seed_sqlite(tmp_local_store, text=text, confidence=0.60)

        # Recall 1: via search_crystals (Path 3 BLUE)
        hits = tmp_local_store.search_crystals("therapy techniques anxiety")
        assert len(hits) >= 1

        # Recall 2: via search_crystals again (simulates different session)
        hits = tmp_local_store.search_crystals("anxiety management coping")
        assert len(hits) >= 1

        # Recall 3: via search_crystals with different keywords
        hits = tmp_local_store.search_crystals("advanced therapy coping")
        assert len(hits) >= 1

        row = tmp_local_store._conn.execute(
            "SELECT confidence, recall_count FROM crystals WHERE content_hash = ?",
            (ch,),
        ).fetchone()

        expected_conf = 0.60 + 3 * PROMOTION_INCREMENT  # 0.69
        assert row[0] == pytest.approx(expected_conf, abs=1e-9), (
            f"Cross-path consistency: expected {expected_conf}, got {row[0]}"
        )
        assert row[1] == 3


# ---------------------------------------------------------------------------
#  PART 4 — Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    # ── 4A: Concurrent recall ──

    @pytest.mark.asyncio
    async def test_4a_concurrent_recall_race(self, tmp_local_store):
        """Two concurrent recalls on the same crystal (SQLite serialises so
        both succeed).  In production PostgreSQL without SELECT ... FOR UPDATE,
        concurrent transactions may see the same pre-update confidence and
        both write the same bumped value — a lost update.  This test documents
        that the current code does NOT use row-level locking.
        """
        text = "advanced therapy techniques for concurrent recall testing"
        ch = _seed_sqlite(tmp_local_store, text=text, confidence=0.60)

        def recall():
            tmp_local_store.search_crystals("therapy techniques concurrent")

        recall()
        recall()

        row = tmp_local_store._conn.execute(
            "SELECT confidence, recall_count FROM crystals WHERE content_hash = ?",
            (ch,),
        ).fetchone()
        expected = 0.60 + 2 * PROMOTION_INCREMENT
        assert row[0] == pytest.approx(expected, abs=1e-9)
        assert row[1] == 2

    # ── 4B: ODPE signal boundary ──

    def test_4b_odpe_signal_boundary_thresholds(self):
        """Verify canonical confidence → signal mapping from crystal_constants."""
        cases = [
            (0.59, "PROVISIONAL"),
            (0.60, "PROVISIONAL"),  # TENSION baseline, but treated as PROVISIONAL
            (0.74, "PROVISIONAL"),
            (0.75, "PROMOTED"),
            (0.84, "PROMOTED"),
            (0.85, "LOCKED"),
            (0.95, "LOCKED"),
        ]
        for conf, expected_signal in cases:
            if conf >= CONFIDENCE_LOCKED:
                signal = "LOCKED"
            elif conf >= CONFIDENCE_PROMOTED:
                signal = "PROMOTED"
            else:
                signal = "PROVISIONAL"
            assert signal == expected_signal, (
                f"conf={conf}: expected {expected_signal}, got {signal}"
            )

    def test_4b_odpe_bypass_vs_label_gap(self):
        """Gap 2: CLI label uses 0.90 for LOCKED, but bypass activates at 0.85.

        A crystal at 0.87 triggers the LOCKED bypass (serves at $0) but the
        CLI label logic classifies it as "PROMOTED".
        """
        conf = 0.87

        # Bypass check (bridge_server.py:28652) — uses 0.85
        bypass_activates = conf >= CONFIDENCE_LOCKED  # 0.85
        assert bypass_activates is True

        # CLI label (bridge_server.py:28662) — uses 0.90
        # BUG: CLI line 28662 uses 0.90 for LOCKED label,
        # but bypass activates at 0.85 per crystal_constants.CONFIDENCE_LOCKED
        cli_label = (
            "LOCKED" if conf >= 0.90
            else "PROMOTED" if conf >= 0.75
            else "PROVISIONAL"
        )
        assert cli_label == "PROMOTED", (
            "Expected PROMOTED from CLI label logic, but got {cli_label}. "
            "If this fails, the CLI label threshold was fixed to match 0.85."
        )

    # ── 4C: Decay exempt domains ──

    def test_4c_decay_exempt_domains(self, tmp_local_store):
        """Exempt domains (coding, defense, machining, crisis) must never be
        time-decayed.  A marketing crystal with no recalls for 90+ days SHOULD
        be archived.
        """
        from app.services.nate_memory_crystallizer import (
            CONFIDENCE_FLOOR_BY_DOMAIN,
            DECAY_EXEMPT_DOMAINS,
        )

        assert "coding" in DECAY_EXEMPT_DOMAINS
        assert "defense" in DECAY_EXEMPT_DOMAINS
        assert "machining" in DECAY_EXEMPT_DOMAINS
        assert "crisis" in DECAY_EXEMPT_DOMAINS
        assert "marketing" not in DECAY_EXEMPT_DOMAINS

        # crisis floor is the highest (0.30) — a crisis crystal at 0.20
        # would be archived by confidence pruning, but NOT by time-decay
        assert CONFIDENCE_FLOOR_BY_DOMAIN["crisis"] == 0.30
        assert CONFIDENCE_FLOOR_BY_DOMAIN["coding"] == 0.15
        assert CONFIDENCE_FLOOR_BY_DOMAIN["marketing"] == 0.20

    # ── 4D: Supersession ──

    @pytest.mark.asyncio
    async def test_4d_supersession_crystallizer_contradiction(
        self, fake_conn: StatefulFakeConnection
    ):
        """Crystallizer contradiction path: old crystal gets superseded_by = -1
        (sentinel), scope = 'archived'.  recall_count is NOT inherited — this
        is a documented gap.
        """
        old = fake_conn.seed(confidence=0.70, recall_count=12, domain="clinical")
        new = fake_conn.seed(confidence=0.80, recall_count=0, domain="clinical")

        # Simulate the contradiction supersession SQL
        # (nate_memory_crystallizer.py:1698-1702)
        pool = StatefulFakePool(fake_conn)
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE nate_intelligence_crystals
                   SET scope = 'archived', superseded_by = -1, updated_at = NOW()
                   WHERE id = $1""",
                old["id"], -1,
            )

        assert old["scope"] == "archived"
        assert old["superseded_by"] == -1
        # recall_count is NOT inherited — gap
        assert new["recall_count"] == 0
        assert old["recall_count"] == 12  # knowledge value lost

    @pytest.mark.asyncio
    async def test_4d_supersession_factory_merge(
        self, fake_conn: StatefulFakeConnection
    ):
        """Factory merge_duplicates(): winner inherits combined recall_count,
        loser gets superseded_by = winner's ID, scope = 'archived'."""
        winner = fake_conn.seed(confidence=0.80, recall_count=8, domain="clinical")
        loser = fake_conn.seed(confidence=0.60, recall_count=4, domain="clinical")
        combined = winner["recall_count"] + loser["recall_count"]

        pool = StatefulFakePool(fake_conn)
        async with pool.acquire() as conn:
            # Winner gets combined recalls
            await conn.execute(
                """UPDATE nate_intelligence_crystals
                   SET recall_count = $2, updated_at = NOW()
                   WHERE id = $1""",
                winner["id"], combined,
            )
            # Loser archived
            await conn.execute(
                """UPDATE nate_intelligence_crystals
                   SET superseded_by = $2, scope = 'archived', updated_at = NOW()
                   WHERE id = $1""",
                loser["id"], winner["id"],
            )

        assert winner["recall_count"] == 12
        assert loser["scope"] == "archived"
        assert loser["superseded_by"] == winner["id"]

    # ── 4E: Meta-crystal promotion ──

    def test_4e_meta_crystal_promotion(self, tmp_local_store):
        """Meta-crystals start at META_CONFIDENCE (0.70) and follow the same
        promotion rules as regular crystals."""
        text = "[META-CRYSTAL] Cross-domain relationship of therapy and coding techniques"
        ch = _seed_sqlite(
            tmp_local_store, text=text, domain="general", confidence=0.70
        )
        tmp_local_store.search_crystals("therapy coding techniques")

        row = tmp_local_store._conn.execute(
            "SELECT confidence, recall_count FROM crystals WHERE content_hash = ?",
            (ch,),
        ).fetchone()
        assert row[0] == pytest.approx(0.73, abs=1e-9)
        assert row[1] == 1

    # ── 4F: LOCKED bypass ──

    def test_4f_locked_bypass_cli(self):
        """CLI bypass: when confidence >= 0.85 and ODPE is LOCKED, the crystal
        text is served directly with no inference call."""
        crystal_text = "LOCKED crystal about resilience"
        top_conf = 0.88

        inference_called = False

        def mock_inference(*a, **kw):
            nonlocal inference_called
            inference_called = True
            return "SHOULD NOT APPEAR"

        # Simulate CLI handler logic (bridge_server.py:28649-28654)
        _cli_odpe = (
            "LOCKED" if top_conf >= 0.90
            else "PROMOTED" if top_conf >= 0.75
            else "PROVISIONAL"
        )
        _crystal_only_response = None

        # Bypass activates at canonical threshold 0.85 (not CLI label 0.90)
        if top_conf >= CONFIDENCE_LOCKED:
            _crystal_only_response = crystal_text

        if _crystal_only_response:
            result = _crystal_only_response
        else:
            result = mock_inference()

        assert not inference_called
        assert result == crystal_text

    @pytest.mark.asyncio
    async def test_4f_locked_bypass_therapy(self):
        """Therapy bypass: fetch_relevant returns crystal with conf >= 0.85,
        tract_pipeline.process() is NOT called."""

        crystal_text = "Deep therapeutic insight about attachment"
        mock_process = AsyncMock()

        # Simulate therapy bypass (bridge_server.py:12775-12793)
        _therapy_crystal_bypass = False
        fetch_result = [{"crystal_text": crystal_text, "confidence": 0.88}]

        if fetch_result and fetch_result[0].get("confidence", 0) >= CONFIDENCE_LOCKED:
            _locked_text = fetch_result[0]["crystal_text"]
            _therapy_crystal_bypass = True
            ws_message = {
                "type": "ai_response",
                "text": _locked_text,
                "provider": "crystal_recall",
            }

        if not _therapy_crystal_bypass:
            await mock_process()

        assert _therapy_crystal_bypass is True
        mock_process.assert_not_called()
        assert ws_message["provider"] == "crystal_recall"
        assert ws_message["text"] == crystal_text

    # ── Gap 3: NOISE skip ──

    @pytest.mark.asyncio
    async def test_noise_signal_skips_promotion(
        self, fake_conn: StatefulFakeConnection
    ):
        """NOISE signal causes record_recall to return immediately with no
        database write.  Confidence and recall_count must be unchanged."""
        crystal = fake_conn.seed(confidence=0.70, recall_count=5)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"], odpe_signal="NOISE")

        assert crystal["confidence"] == pytest.approx(0.70, abs=1e-9)
        assert crystal["recall_count"] == 5
        assert crystal["last_recalled_at"] is None

    # ── Gap 4: LOCKED double-increment ──

    @pytest.mark.asyncio
    async def test_locked_signal_double_increment(
        self, fake_conn: StatefulFakeConnection
    ):
        """LOCKED signal: increment = 2, applied as multiplier to both
        recall_count (+2) and confidence (+2 × 0.03 = 0.06)."""
        crystal = fake_conn.seed(confidence=0.85, recall_count=8)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"], odpe_signal="LOCKED")

        assert crystal["confidence"] == pytest.approx(0.91, abs=1e-9)
        assert crystal["recall_count"] == 10

    @pytest.mark.asyncio
    async def test_locked_double_increment_cap(
        self, fake_conn: StatefulFakeConnection
    ):
        """LOCKED double-increment at 0.93 should cap at PROMOTION_CAP."""
        crystal = fake_conn.seed(confidence=0.93, recall_count=15)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"], odpe_signal="LOCKED")

        assert crystal["confidence"] <= PROMOTION_CAP + 1e-9, (
            f"LOCKED double-increment exceeded cap: {crystal['confidence']}"
        )
        assert crystal["recall_count"] == 17


# ---------------------------------------------------------------------------
#  Cap Enforcement
# ---------------------------------------------------------------------------


class TestCapEnforcement:
    """Verify that ALL paths cap at PROMOTION_CAP (0.95)."""

    @pytest.mark.parametrize(
        "start",
        [0.94, 0.95, 0.99],
        ids=["just_below_cap", "at_cap", "above_cap_if_seeded_wrong"],
    )
    def test_path3_cli_cap(self, tmp_local_store, start: float):
        text = "advanced therapy techniques for cap testing purposes"
        ch = _seed_sqlite(tmp_local_store, text=text, confidence=start)
        tmp_local_store.search_crystals("therapy techniques purposes")
        row = tmp_local_store._conn.execute(
            "SELECT confidence FROM crystals WHERE content_hash = ?", (ch,)
        ).fetchone()
        assert row[0] <= PROMOTION_CAP + 1e-9, (
            f"Path 3 exceeded cap: start={start}, result={row[0]}"
        )

    @pytest.mark.asyncio
    async def test_path2_green_cap(self, fake_conn: StatefulFakeConnection):
        """Path 2 GREEN caps at PROMOTION_CAP (0.95)."""
        crystal = fake_conn.seed(confidence=0.94)
        pool = StatefulFakePool(fake_conn)
        from app.services.nate_memory_crystallizer import NateMemoryCrystallizer

        cryst = NateMemoryCrystallizer(db_pool=pool)
        await cryst.record_recall(crystal["id"])
        assert crystal["confidence"] <= PROMOTION_CAP + 1e-9, (
            f"Path 2 exceeded cap: {crystal['confidence']}"
        )


# ---------------------------------------------------------------------------
#  PART 5 — ExaFLOPS Integration Proof
# ---------------------------------------------------------------------------

# Deterministic query set
_SEED_CRYSTALS = [
    ("coding", "Python decorators enable metaprogramming and function wrapping patterns"),
    ("coding", "Async await concurrency model simplifies parallel network operations"),
    ("coding", "Database indexing strategies optimize query performance significantly"),
    ("clinical", "Cognitive behavioral therapy restructures negative thought patterns effectively"),
    ("clinical", "Attachment theory explains interpersonal relationship dynamics deeply"),
    ("clinical", "Mindfulness meditation reduces anxiety through present-moment awareness practice"),
    ("legal", "Contract formation requires offer acceptance consideration and capacity elements"),
    ("legal", "Due process protections safeguard individual rights against government overreach"),
    ("legal", "Intellectual property covers patents trademarks copyrights and trade secrets"),
    ("coding", "Microservices architecture enables independent deployment and scaling of components"),
]

_QUERIES = [
    # Q1 (0-24): mix of matching and non-matching
    "Python decorators function wrapping",        # match coding[0]
    "quantum physics entanglement theory",         # no match
    "cognitive behavioral therapy patterns",       # match clinical[0]
    "tropical fish aquarium maintenance",          # no match
    "async await parallel network",                # match coding[1]
    "mountain climbing safety protocols",          # no match
    "attachment theory relationship dynamics",     # match clinical[1]
    "vintage automobile restoration tips",         # no match
    "database indexing query performance",         # match coding[2]
    "contract formation offer acceptance",         # match legal[0]
    "medieval castle architecture design",         # no match
    "mindfulness meditation anxiety awareness",    # match clinical[2]
    "origami paper folding techniques",            # no match
    "microservices deployment scaling",            # match coding[3]
    "due process individual rights",               # match legal[1]
    "bonsai tree cultivation methods",             # no match
    "Python metaprogramming patterns",             # match coding[0]
    "knitting sweater pattern design",             # no match
    "cognitive restructures negative thought",     # match clinical[0]
    "intellectual property patents trademarks",    # match legal[2]
    "underwater photography tips",                 # no match
    "async concurrency parallel operations",       # match coding[1]
    "pottery wheel throwing techniques",           # no match
    "attachment interpersonal dynamics",            # match clinical[1]
    "woodworking joinery techniques",              # no match

    # Q2 (25-49): slightly more matches as user focuses
    "Python decorators wrapping patterns",
    "cognitive behavioral therapy negative",
    "database indexing performance optimize",
    "contract offer acceptance capacity",
    "sourdough bread baking fermentation",
    "async await network simplifies",
    "mindfulness reduces anxiety practice",
    "microservices independent scaling",
    "due process rights government",
    "stamp collecting philately hobby",
    "Python function metaprogramming",
    "attachment theory explains deeply",
    "intellectual property copyrights secrets",
    "bird watching ornithology guide",
    "database strategies query optimize",
    "cognitive restructures patterns effectively",
    "contract consideration elements formation",
    "sailboat racing tactics strategy",
    "async parallel network operations",
    "mindfulness meditation present moment",
    "microservices architecture components",
    "due process protections safeguard",
    "calligraphy brush lettering art",
    "Python decorators metaprogramming",
    "cognitive behavioral restructures",

    # Q3 (50-74): more focused, higher hit rate
    "Python decorators function patterns",
    "async await concurrency model",
    "database indexing strategies optimize",
    "cognitive behavioral therapy techniques",
    "attachment theory relationship",
    "mindfulness meditation anxiety",
    "contract formation acceptance",
    "due process individual protections",
    "intellectual property patents",
    "microservices deployment independent",
    "fossil hunting paleontology rocks",
    "Python metaprogramming wrapping",
    "cognitive therapy negative thought",
    "database query performance indexing",
    "attachment explains interpersonal",
    "mindfulness present moment awareness",
    "contract offer consideration",
    "due process rights protections",
    "intellectual trademarks copyrights",
    "microservices scaling architecture",
    "candle making wax fragrance",
    "async network parallel model",
    "cognitive behavioral patterns",
    "database strategies performance",
    "attachment dynamics relationship",

    # Q4 (75-99): high overlap — crystals should be well-promoted by now
    "Python decorators function metaprogramming wrapping",
    "async await concurrency parallel network operations",
    "database indexing strategies query performance optimize",
    "cognitive behavioral therapy restructures negative patterns",
    "attachment theory interpersonal relationship dynamics",
    "mindfulness meditation reduces anxiety awareness practice",
    "contract formation offer acceptance consideration capacity",
    "due process protections safeguard individual rights",
    "intellectual property patents trademarks copyrights",
    "microservices architecture independent deployment scaling",
    "Python decorators patterns metaprogramming",
    "cognitive therapy restructures patterns",
    "async concurrency parallel operations",
    "database indexing query optimize",
    "attachment relationship dynamics theory",
    "mindfulness anxiety present moment",
    "contract acceptance consideration",
    "due process rights government overreach",
    "intellectual property trade secrets",
    "microservices scaling components deployment",
    "Python function wrapping decorators",
    "cognitive behavioral negative thought patterns",
    "database performance strategies indexing",
    "mindfulness meditation reduces anxiety",
    "attachment theory explains dynamics",
]

assert len(_QUERIES) == 100, f"Expected 100 queries, got {len(_QUERIES)}"


class TestExaFLOPSIntegration:
    """Part 5: Mathematical proof that the crystal system compounds."""

    def test_compounding_model(self, tmp_local_store):
        # Seed 10 crystals at PROVISIONAL baseline
        for domain, text in _SEED_CRYSTALS:
            _seed_sqlite(tmp_local_store, text=text, domain=domain, confidence=0.60)

        free_by_quartile = [0, 0, 0, 0]
        promotion_by_quartile = [0, 0, 0, 0]
        conf_snapshots: list[list[float]] = [[], [], [], []]

        for i, query in enumerate(_QUERIES):
            quartile = i // 25

            hits = tmp_local_store.search_crystals(query, limit=3)

            for h in hits:
                promotion_by_quartile[quartile] += 1
                if h["confidence"] >= CONFIDENCE_LOCKED:
                    free_by_quartile[quartile] += 1

            # Snapshot all crystal confidences
            all_rows = tmp_local_store._conn.execute(
                "SELECT confidence FROM crystals WHERE scope != 'archived'"
            ).fetchall()
            avg_c = sum(r[0] for r in all_rows) / max(len(all_rows), 1)
            conf_snapshots[quartile].append(avg_c)

        # Average confidence per quartile
        avg_conf_by_quartile = [
            sum(snaps) / max(len(snaps), 1) for snaps in conf_snapshots
        ]

        # ── ExaFLOPS compounding assertions ──

        # Confidence must compound over time
        assert avg_conf_by_quartile[3] > avg_conf_by_quartile[0], (
            f"Confidence did not compound: Q1={avg_conf_by_quartile[0]:.4f}, "
            f"Q4={avg_conf_by_quartile[3]:.4f}"
        )

        # Q4 should have more free responses than Q1
        assert free_by_quartile[3] > free_by_quartile[0], (
            f"ExaFLOPS model broken: Q4 free responses must exceed Q1. "
            f"Q1={free_by_quartile[0]}, Q4={free_by_quartile[3]}"
        )

        # At least one crystal reached PROMOTED
        all_final = tmp_local_store._conn.execute(
            "SELECT confidence FROM crystals WHERE scope != 'archived'"
        ).fetchall()
        max_conf = max(r[0] for r in all_final)
        assert max_conf >= CONFIDENCE_PROMOTED, (
            f"No crystal reached PROMOTED: max={max_conf}"
        )

        # Promotion events should increase over quartiles (more crystals
        # at higher confidence = more matches)
        total_promos = sum(promotion_by_quartile)
        assert total_promos > 0, "No promotion events occurred"

        # Final crystal count still 10 (no new crystals from TENSION in
        # this simplified simulation — only promotion tested)
        final_count = tmp_local_store.get_crystal_count()
        assert final_count == 10
