"""Watch Workbooks/ + protocol dir, crystallize coaching tools, start learn cycle.

New or changed files become global coaching crystals (not therapy).
LN recalls them; AlphaLN and Queens get the catalog digest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.services.workbook_catalog import (
    COACHING_STANCE,
    relative_label,
    resolve_workbook_roots,
)
from app.services.workbook_library import _extract_pdf_text

logger = logging.getLogger("workbook_sync_agent")

POLL_INTERVAL_SECONDS = int(os.getenv("WORKBOOK_SYNC_INTERVAL_S", "180"))
MAX_LEARN_BYTES = int(os.getenv("WORKBOOK_LEARN_MAX_BYTES", str(8 * 1024 * 1024)))
MAX_IMPL_CRYSTALS = 8
MAX_CHUNK_CHARS = 700
_SKIP_FULL = re.compile(r"(king[- ]james|nkjv|new-king-james)", re.I)

_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS workbook_ingest_index (
    rel_path TEXT PRIMARY KEY,
    content_sha256 CHAR(64) NOT NULL,
    file_mtime TIMESTAMPTZ,
    bytes BIGINT,
    last_learned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    crystals_created INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'learned',
    notes TEXT
)
"""


def workbook_sync_enabled() -> bool:
    raw = (os.getenv("ENABLE_WORKBOOK_SYNC") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def file_sha256(path: Path, cap: int = MAX_LEARN_BYTES) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        remaining = cap + 1
        while remaining > 0:
            chunk = fh.read(min(65536, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def extract_workbook_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path, max_pages=80)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def should_full_learn(path: Path) -> Tuple[bool, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, f"stat_failed:{exc}"
    if size > MAX_LEARN_BYTES or _SKIP_FULL.search(path.name):
        return False, "catalog_only_large_or_reference"
    return True, "full"


def build_learn_crystals(label: str, text: str, *, full: bool) -> List[str]:
    """Deterministic coaching crystals from extracted text. No LLM."""
    stance = COACHING_STANCE
    summary = re.sub(r"\s+", " ", (text or "").strip())[:420]
    catalog = (
        f"[COACHING WORKBOOK: {label}] Stance: {stance} "
        f"Access the file in Workbooks to formulate a coaching plan. "
        f"Summary: {summary or 'Catalog entry — extract empty or deferred.'}"
    )
    out = [catalog]
    if not full or len((text or "").strip()) < 80:
        out.append(
            f"[COACHING IMPLEMENTATION: {label}] Begin a learn cycle: read the "
            f"workbook, name 3 client-facing exercises, and offer them as optional "
            f"coaching tools. Do not present this as therapy."
        )
        return out

    impl = (
        f"[COACHING IMPLEMENTATION: {label}] How to coach this: (1) Name the "
        f"workbook as a suggested tool. (2) Ask if the client wants to try a step. "
        f"(3) Walk one exercise at a time. (4) Stop if they decline. Not therapy. "
        f"Key material: {summary}"
    )
    out.append(impl)

    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if len(p.strip()) >= 80]
    used = 0
    for para in paras:
        if used >= MAX_IMPL_CRYSTALS:
            break
        snippet = para[:MAX_CHUNK_CHARS].rstrip()
        out.append(
            f"[COACHING METHOD: {label}] Client-consider tool (not therapy): {snippet}"
        )
        used += 1
    return out


class WorkbookSyncAgent:
    def __init__(self, db_pool, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._running = False
        self._task = None
        self._cycle_count = 0

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("WorkbookSyncAgent started (%ss cycle)", POLL_INTERVAL_SECONDS)

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("WorkbookSyncAgent stopped")

    async def _run_loop(self):
        await asyncio.sleep(20)
        while self._running:
            try:
                await self.cycle_once()
            except Exception as exc:
                logger.error("WorkbookSyncAgent cycle error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def cycle_once(self) -> Dict:
        if not self._db_pool:
            logger.warning("WorkbookSyncAgent: no db_pool — skip")
            return {"error": "no_db_pool", "learned": 0}

        async with self._db_pool.acquire() as conn:
            await conn.execute(_ENSURE_TABLE_SQL)

        try:
            from app.sse.workbook_ingestion import ingest_workbooks

            proto = await ingest_workbooks(self._db_pool)
        except Exception as exc:
            logger.warning("WorkbookSyncAgent: protocol ingest skipped: %s", exc)
            proto = {"error": str(exc)}

        roots = resolve_workbook_roots()
        learned = 0
        skipped = 0
        new_labels: List[str] = []
        for path in _iter_files(roots):
            label = relative_label(path, roots)
            result = await self._learn_file(path, label)
            if result.get("created", 0) > 0:
                learned += 1
                new_labels.append(label)
            else:
                skipped += 1

        if new_labels:
            await self._notify_queens(new_labels)

        self._cycle_count += 1
        logger.info(
            "WorkbookSyncAgent: cycle=%s learned=%s unchanged=%s roots=%s",
            self._cycle_count,
            learned,
            skipped,
            [str(r) for r in roots],
        )
        return {
            "learned": learned,
            "unchanged": skipped,
            "protocol": proto,
            "new": new_labels,
            "cycle": self._cycle_count,
        }

    async def _learn_file(self, path: Path, label: str) -> Dict:
        try:
            digest = file_sha256(path)
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            size = path.stat().st_size
        except OSError as exc:
            logger.warning("WorkbookSyncAgent: cannot read %s: %s", label, exc)
            return {"created": 0}

        async with self._db_pool.acquire() as conn:
            prior = await conn.fetchval(
                "SELECT content_sha256 FROM workbook_ingest_index WHERE rel_path = $1",
                label,
            )
            if prior == digest:
                return {"created": 0, "status": "unchanged"}

        full, reason = should_full_learn(path)
        try:
            text = extract_workbook_text(path) if full else ""
        except Exception as exc:
            logger.warning("WorkbookSyncAgent: extract failed %s: %s", label, exc)
            text = ""
            full = False
            reason = f"extract_failed:{exc}"

        crystals = build_learn_crystals(label, text, full=full)
        created = 0
        new_for_index: List[Tuple[str, str]] = []
        async with self._db_pool.acquire() as conn:
            for crystal_text in crystals:
                content_hash = hashlib.sha256(crystal_text.encode()).hexdigest()
                row = await conn.fetchrow(
                    "INSERT INTO nate_intelligence_crystals "
                    "(crystal_text, domain, scope, topics, source_count, generation, "
                    " confidence, content_hash, metadata, created_at, updated_at) "
                    "VALUES ($1, 'coaching', 'global', $2::text[], 2, 0, 0.78, $3, "
                    " $4::jsonb, NOW(), NOW()) "
                    "ON CONFLICT (content_hash) DO NOTHING RETURNING id",
                    crystal_text,
                    ["workbook", "coaching_tool", label[:80]],
                    content_hash,
                    json.dumps(
                        {
                            "ingestion_source": "workbook_sync_agent",
                            "workbook": label,
                            "stance": "coaching_not_therapy",
                        }
                    ),
                )
                if row:
                    created += 1
                    new_for_index.append((crystal_text, content_hash))

            await conn.execute(
                "INSERT INTO workbook_ingest_index "
                "(rel_path, content_sha256, file_mtime, bytes, last_learned_at, "
                " crystals_created, status, notes) "
                "VALUES ($1, $2, $3, $4, NOW(), $5, $6, $7) "
                "ON CONFLICT (rel_path) DO UPDATE SET "
                " content_sha256 = EXCLUDED.content_sha256, "
                " file_mtime = EXCLUDED.file_mtime, "
                " bytes = EXCLUDED.bytes, "
                " last_learned_at = NOW(), "
                " crystals_created = workbook_ingest_index.crystals_created "
                "   + EXCLUDED.crystals_created, "
                " status = EXCLUDED.status, "
                " notes = EXCLUDED.notes",
                label,
                digest,
                mtime,
                size,
                created,
                "learned" if full else "catalog_only",
                reason,
            )
        for crystal_text, content_hash in new_for_index:
            await _index_vectorize_outside(crystal_text, content_hash)
        return {"created": created, "status": "learned" if created else "deduped"}

    async def _notify_queens(self, labels: List[str]) -> None:
        try:
            from app.websocket.cli_task_bus import publish_task, task_bus_enabled

            if not task_bus_enabled():
                return
            notes = (
                "New coaching workbooks to specialize on (not therapy): "
                + ", ".join(labels[:12])
                + ". Draft how LN/AlphaLN coach a client through each as an optional tool."
            )
            publish_task(
                origin="cloud",
                kind="work",
                notes=notes,
                files=["Workbooks/", "backend/resources/therapeutic_library/protocol_workbooks/"],
            )
        except Exception as exc:
            logger.warning("WorkbookSyncAgent: Queens notify skipped: %s", exc)


def _iter_files(roots) -> List[Path]:
    from app.services.workbook_catalog import iter_workbook_files

    return iter_workbook_files(roots)


async def _index_vectorize_outside(crystal_text: str, content_hash: str) -> None:
    try:
        from app.services.vectorize_service import index_wisdom, is_vectorize_configured

        if not is_vectorize_configured():
            return
        await index_wisdom(
            user_id="nate_crystal",
            wisdom_id=f"crystal_{content_hash[:16]}",
            insight_type="crystal_coaching",
            content=crystal_text,
            source="workbook_sync",
            domain="coaching",
        )
    except Exception as exc:
        logger.warning("WorkbookSyncAgent: Vectorize skip: %s", exc)
