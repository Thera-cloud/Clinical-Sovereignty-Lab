"""
Six-Quotient Standards Index — allowlisted professional feeds → pending review items.

Recency-aware: newer approved items can supersede older same-topic rows.
Crystallizes only after human approval (never auto-promotes into scoring rubrics).
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
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import aiohttp

logger = logging.getLogger("sovereign.six_quotient_standards")

CYCLE_SECONDS = 6 * 3600  # 6h


def _registry_path() -> Path:
    candidates = [
        Path(__file__).resolve().parents[1] / "data" / "six_quotient_standards_registry.json",
        Path("/app/app/data/six_quotient_standards_registry.json"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _flag_on() -> bool:
    return os.getenv("ENABLE_SIX_QUOTIENT_STANDARDS_INDEX", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def load_registry() -> Dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return {"quotients": {}}
    return json.loads(path.read_text(encoding="utf-8"))


class SixQuotientStandardsIndex:
    """Background reader for quotient-mapped allowlisted sources."""

    def __init__(self, db_pool, app_state=None):
        self.db_pool = db_pool
        self.app_state = app_state
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.last_cycle: Dict[str, Any] = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("SixQuotientStandardsIndex started (enabled=%s)", _flag_on())

    async def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self):
        await asyncio.sleep(240)
        while self._running:
            try:
                if _flag_on():
                    self.last_cycle = await self.run_once()
            except Exception as e:
                logger.error("StandardsIndex cycle: %s", e)
            await asyncio.sleep(CYCLE_SECONDS)

    async def run_once(self, *, max_per_source: int = 3) -> Dict[str, Any]:
        reg = load_registry()
        inserted = 0
        scanned = 0
        errors: List[str] = []
        # QUANTUM-CRYSTAL-ARCH — WHO/CDC send large CSP headers (>8190); raise limits
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=25),
            max_line_size=65536,
            max_field_size=65536,
        ) as session:
            for quotient, block in (reg.get("quotients") or {}).items():
                for src in block.get("sources") or []:
                    if src.get("type") != "rss":
                        continue
                    try:
                        articles = await self._fetch_rss(session, src["url"])
                        scanned += len(articles)
                        for art in articles[:max_per_source]:
                            ok = await self._store_candidate(
                                quotient=quotient.upper(),
                                source_key=src.get("key") or "",
                                source_name=src.get("name") or "",
                                title=art.get("title") or "",
                                url=art.get("url") or "",
                                authority_tier=int(src.get("authority_tier") or 2),
                                topics=src.get("topics") or [],
                            )
                            if ok:
                                inserted += 1
                    except Exception as e:
                        errors.append(f"{src.get('key')}: {e}"[:120])
                        logger.warning("standards feed %s: %s", src.get("key"), e)
        result = {
            "ok": True,
            "scanned": scanned,
            "inserted": inserted,
            "errors": errors[:10],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.last_cycle = result
        return result

    async def _fetch_rss(self, session: aiohttp.ClientSession, url: str) -> List[Dict[str, str]]:
        async with session.get(
            url, headers={"User-Agent": "Mozilla/5.0 LittleNateStandards/1.0"}
        ) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
        # QUANTUM-CRYSTAL-ARCH — reject HTML error pages masquerading as feeds
        head = (text or "")[:400].lower()
        if "<html" in head or "<!doctype html" in head:
            return []
        items = self._parse_rss_xml(text)
        if not items:
            items = self._parse_rss_regex(text)
        return items[:15]

    def _parse_rss_xml(self, text: str) -> List[Dict[str, str]]:
        try:
            root = ElementTree.fromstring(text)
        except Exception:
            return []
        items: List[Dict[str, str]] = []
        for item in root.findall(".//item")[:15]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if title and link:
                items.append({"title": title, "url": link})
        if not items:
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//a:entry", ns)[:15]:
                title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
                link_el = entry.find("a:link", ns)
                link = (link_el.get("href") if link_el is not None else "") or ""
                if title and link:
                    items.append({"title": title, "url": link})
        return items

    def _parse_rss_regex(self, text: str) -> List[Dict[str, str]]:
        """Best-effort extract when ElementTree rejects the feed body."""
        items: List[Dict[str, str]] = []
        for block in re.findall(r"<item\b[^>]*>(.*?)</item>", text, flags=re.I | re.S)[:15]:
            tm = re.search(r"<title[^>]*>(.*?)</title>", block, flags=re.I | re.S)
            lm = re.search(r"<link[^>]*>(.*?)</link>", block, flags=re.I | re.S)
            if not lm:
                lm = re.search(r'href=["\'](https?://[^"\']+)["\']', block, flags=re.I)
            title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
            link = (lm.group(1) if lm else "").strip()
            link = re.sub(r"<[^>]+>", "", link).strip()
            if title and link.startswith("http"):
                items.append({"title": title[:500], "url": link[:1000]})
        return items

    async def _store_candidate(
        self,
        *,
        quotient: str,
        source_key: str,
        source_name: str,
        title: str,
        url: str,
        authority_tier: int,
        topics: List[str],
    ) -> bool:
        year = datetime.now(timezone.utc).year
        # Prefer year from URL if present
        m = re.search(r"(20\d{2})", url + " " + title)
        if m:
            year = int(m.group(1))
        summary = f"[{quotient}] {title}"
        ch = _hash(f"{url}|{title}|{quotient}")
        try:
            async with self.db_pool.acquire() as conn:
                status = await conn.execute(
                    """INSERT INTO six_quotient_standards_items
                       (quotient, source_key, source_name, title, url, published_year,
                        authority_tier, summary, content_hash, status, metadata_json)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'pending_review',$10::jsonb)
                       ON CONFLICT (content_hash) DO NOTHING""",
                    quotient,
                    source_key,
                    source_name,
                    title[:500],
                    url[:1000],
                    year,
                    authority_tier,
                    summary[:2000],
                    ch,
                    json.dumps({"topics": topics}),
                )
                return status.endswith("1")
        except Exception as e:
            logger.warning("store standards: %s", e)
            return False

    async def list_items(
        self, *, status: str = "pending_review", quotient: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 200))
        args: List[Any] = [status]
        clause = "status = $1"
        if quotient:
            args.append(quotient.upper())
            clause += f" AND quotient = ${len(args)}"
        args.append(limit)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id::text, quotient, source_key, source_name, title, url,
                           published_year, authority_tier, summary, status,
                           approved_by, fetched_at
                    FROM six_quotient_standards_items
                    WHERE {clause}
                    ORDER BY published_year DESC NULLS LAST, fetched_at DESC
                    LIMIT ${len(args)}""",
                *args,
            )
        out = []
        for r in rows:
            d = dict(r)
            if d.get("fetched_at"):
                d["fetched_at"] = d["fetched_at"].isoformat()
            out.append(d)
        return out

    async def approve(
        self, item_id: str, approved_by: str, *, crystallize: bool = True
    ) -> Dict[str, Any]:
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE six_quotient_standards_items
                   SET status = 'approved', approved_by = $2, approved_at = NOW()
                   WHERE id = $1::uuid AND status = 'pending_review'
                   RETURNING id::text, quotient, title, summary, url, published_year,
                             authority_tier, source_name""",
                item_id,
                (approved_by or "").strip() or "admin",
            )
            if not row:
                return {"ok": False, "error": "not found or not pending"}
            # Supersede older approved items with same source_key+quotient and older year
            await conn.execute(
                """UPDATE six_quotient_standards_items AS old
                   SET status = 'superseded', supersedes_id = $1::uuid
                   FROM six_quotient_standards_items AS neu
                   WHERE neu.id = $1::uuid
                     AND old.quotient = neu.quotient
                     AND old.source_key = neu.source_key
                     AND old.status = 'approved'
                     AND old.id <> neu.id
                     AND COALESCE(old.published_year, 0) < COALESCE(neu.published_year, 0)""",
                item_id,
            )
        crystal_hook = None
        if crystallize and self.app_state:
            cryst = getattr(self.app_state, "nate_memory_crystallizer", None)
            if cryst and hasattr(cryst, "_harvest_buffer"):
                frag = {
                    "text": (
                        f"Clinical standard [{row['quotient']}] {row['published_year']}: "
                        f"{row['title']}. {row['summary']}. Source: {row['source_name']}."
                    ),
                    "domain": "research",
                    "source": "six_quotient_standards",
                    "confidence": 0.45,
                    "metadata": {
                        "quotient": row["quotient"],
                        "url": row["url"],
                        "year": row["published_year"],
                        "authority_tier": row["authority_tier"],
                    },
                }
                try:
                    cryst._harvest_buffer.append(frag)
                    crystal_hook = "harvest_buffer"
                except Exception as e:
                    logger.warning("standards crystallize hook: %s", e)
        return {"ok": True, "item": dict(row), "crystal_hook": crystal_hook}

    async def reject(self, item_id: str, rejected_by: str = "admin") -> Dict[str, Any]:
        """Mark pending_review item rejected (junk / off-topic RSS)."""
        # QUANTUM-CRYSTAL-ARCH
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE six_quotient_standards_items
                   SET status = 'rejected', approved_by = $2, approved_at = NOW()
                   WHERE id = $1::uuid AND status = 'pending_review'
                   RETURNING id::text, quotient, title, status""",
                item_id,
                (rejected_by or "").strip() or "admin",
            )
        if not row:
            return {"ok": False, "error": "not found or not pending"}
        return {"ok": True, "item": dict(row)}

    async def approved_for_prompt(self, *, max_per_q: int = 2) -> str:
        """Compact context block for scenario generator."""
        parts = []
        async with self.db_pool.acquire() as conn:
            for q in ("IQ", "EQ", "MQ", "SQ", "CQ", "AQ"):
                rows = await conn.fetch(
                    """SELECT title, published_year, source_name, authority_tier
                       FROM six_quotient_standards_items
                       WHERE status = 'approved' AND quotient = $1
                       ORDER BY authority_tier ASC, published_year DESC NULLS LAST
                       LIMIT $2""",
                    q,
                    max_per_q,
                )
                if rows:
                    lines = [
                        f"  - ({r['published_year'] or '?'}) {r['title']} [{r['source_name']}]"
                        for r in rows
                    ]
                    parts.append(f"{q}:\n" + "\n".join(lines))
        if not parts:
            return "[STANDARDS INDEX: 0 APPROVED — Do not invent guidelines.]"
        return "[CURRENT STANDARDS — prefer newest / tier-1]\n" + "\n".join(parts)
