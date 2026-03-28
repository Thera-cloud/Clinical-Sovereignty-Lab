"""
Bulk Redirect Pre-Warmer — EXA Edge Latency Optimizer.

Uses Cloudflare Bulk Redirect Lists to pre-warm up to 24,000 crystals
at the edge globally. Each redirect list maps a crystal lookup URL to
the R2 presigned URL containing the crystal content, giving ~5ms latency
for pre-warmed crystals vs ~200ms for cold lookups.

24 domain-specific pools (1,000 entries each):
  pool-code-{00..11}: 12 pools for coding crystals (12,000 capacity)
  pool-clinical-{00..03}: 4 pools for clinical
  pool-marketing-{00..03}: 4 pools for marketing
  pool-general-{00..03}: 4 pools for general/coaching/research/culture

Requires:
  CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN env vars.
  R2 bucket with crystal content for presigned URL generation.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", os.getenv("R2_ACCOUNT_ID", ""))
_CF_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
_CF_BASE = "https://api.cloudflare.com/client/v4"

POOL_CONFIG = {
    "coding": 12,
    "clinical": 4,
    "marketing": 4,
    "general": 4,
}
ENTRIES_PER_POOL = 1000
TOTAL_CAPACITY = sum(POOL_CONFIG.values()) * ENTRIES_PER_POOL  # 24,000


class BulkRedirectPreWarmer:
    """Manages Cloudflare Bulk Redirect Lists for crystal pre-warming."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._pool_ids: Dict[str, str] = {}
        self._last_sync: Optional[datetime] = None

    async def ensure_pools_exist(self):
        """Create redirect lists if they don't exist yet."""
        if not _CF_ACCOUNT_ID or not _CF_API_TOKEN:
            logger.info("BulkRedirectPreWarmer: Cloudflare credentials not configured, skipping")
            return

        headers = {
            "Authorization": f"Bearer {_CF_API_TOKEN}",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as sess:
                list_url = f"{_CF_BASE}/accounts/{_CF_ACCOUNT_ID}/rules/lists"
                async with sess.get(list_url, headers=headers) as resp:
                    if resp.status != 200:
                        logger.warning("BulkRedirectPreWarmer: list fetch failed: %d", resp.status)
                        return
                    data = await resp.json()
                    existing = {r["name"]: r["id"] for r in data.get("result", [])}

                for domain, count in POOL_CONFIG.items():
                    for i in range(count):
                        pool_name = f"pool-{domain}-{i:02d}"
                        if pool_name in existing:
                            self._pool_ids[pool_name] = existing[pool_name]
                        else:
                            create_resp = await sess.post(list_url, headers=headers, json={
                                "name": pool_name,
                                "description": f"Nate crystal pre-warm: {domain} shard {i}",
                                "kind": "redirect",
                            })
                            if create_resp.status in (200, 201):
                                result = await create_resp.json()
                                self._pool_ids[pool_name] = result["result"]["id"]
                                logger.info("Created redirect pool: %s", pool_name)

                logger.info("BulkRedirectPreWarmer: %d/%d pools ready",
                            len(self._pool_ids), TOTAL_CAPACITY // ENTRIES_PER_POOL)
        except Exception as e:
            logger.warning("BulkRedirectPreWarmer: pool init failed: %s", e)

    async def sync_top_crystals(self, domain: str = "coding", limit: int = 1000):
        """Push top N crystals for a domain into their redirect pools."""
        if not self._db_pool or not self._pool_ids:
            return {"status": "not_ready", "pools": len(self._pool_ids)}

        try:
            async with self._db_pool.acquire() as conn:
                crystals = await conn.fetch("""
                    SELECT id, crystal_text, confidence, recall_count, content_hash
                    FROM nate_intelligence_crystals
                    WHERE domain = $1 AND scope != 'archived'
                    ORDER BY confidence DESC, recall_count DESC
                    LIMIT $2
                """, domain, limit)

            pool_count = POOL_CONFIG.get(domain, 4)
            entries_per_pool: Dict[str, List] = {
                f"pool-{domain}-{i:02d}": [] for i in range(pool_count)
            }

            for idx, crystal in enumerate(crystals):
                pool_idx = idx % pool_count
                pool_name = f"pool-{domain}-{pool_idx:02d}"
                if len(entries_per_pool[pool_name]) >= ENTRIES_PER_POOL:
                    continue
                entries_per_pool[pool_name].append({
                    "redirect": {
                        "source_url": f"crystals.sovereignsanctuary.net/c/{crystal['content_hash'][:16]}",
                        "target_url": f"https://api.sovereignsanctuary.net/api/nate/crystal/{crystal['id']}",
                        "status_code": 301,
                    }
                })

            pushed = 0
            headers = {
                "Authorization": f"Bearer {_CF_API_TOKEN}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as sess:
                for pool_name, items in entries_per_pool.items():
                    if not items:
                        continue
                    list_id = self._pool_ids.get(pool_name)
                    if not list_id:
                        continue

                    url = f"{_CF_BASE}/accounts/{_CF_ACCOUNT_ID}/rules/lists/{list_id}/items"
                    async with sess.put(url, headers=headers, json=items) as resp:
                        if resp.status in (200, 201):
                            pushed += len(items)
                        else:
                            body = await resp.text()
                            logger.warning("Pool %s push failed (%d): %s",
                                           pool_name, resp.status, body[:200])

            self._last_sync = datetime.now(timezone.utc)
            return {
                "status": "ok",
                "domain": domain,
                "crystals_pushed": pushed,
                "pools_used": pool_count,
            }
        except Exception as e:
            logger.warning("BulkRedirectPreWarmer sync failed: %s", e)
            return {"status": "error", "error": str(e)}

    def get_status(self) -> Dict[str, Any]:
        return {
            "pools_configured": len(self._pool_ids),
            "total_capacity": TOTAL_CAPACITY,
            "last_sync": self._last_sync.isoformat() if self._last_sync else None,
            "cloudflare_configured": bool(_CF_ACCOUNT_ID and _CF_API_TOKEN),
        }
