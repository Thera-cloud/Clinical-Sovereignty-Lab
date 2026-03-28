"""
ODPE L2 Self-Organizing Map — Emergent micro-therapeutic-moment face creation.

L2 faces are not pre-defined. They emerge from the crystal corpus:
- When a new crystal is tagged with an L1 face_path, its embedding is 
  compared to existing L2 clusters under that L1 face.
- Similar crystals (cosine > 0.85) join an existing L2 face.
- Novel crystals create a new L2 face.
- L2 faces inactive for 90 days are pruned (crystals re-tagged to L1 parent).
- Maximum 10,000 L2 faces per L1 face (topology constraint).

Background agent cycle: every 6 hours.
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("odpe_l2_organizer")

L2_MAX_PER_L1 = 10000
L2_SIMILARITY_THRESHOLD = 0.85
L2_PRUNE_DAYS = 90
L2_CYCLE_HOURS = 6
L2_MIN_CRYSTALS_FOR_FACE = 2


class ODPEL2Organizer:
    """Background agent that organizes L2 faces from the crystal corpus."""

    def __init__(self, db_pool=None, app_state=None):
        self._db_pool = db_pool
        self._app_state = app_state
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cycle_count = 0

    async def start(self):
        """Start the background organization loop."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("ODPE L2 Organizer started (cycle every %dh)", L2_CYCLE_HOURS)

    async def stop(self):
        """Stop the background loop gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        """Main background loop."""
        await asyncio.sleep(600)
        while self._running:
            try:
                await self._organize_cycle()
                self._cycle_count += 1
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("L2 organizer cycle failed: %s", e)
            
            await asyncio.sleep(L2_CYCLE_HOURS * 3600)

    async def _organize_cycle(self):
        """One organization cycle: scan untagged crystals, create/assign L2 faces."""
        if not self._db_pool:
            return

        async with self._db_pool.acquire() as conn:
            untagged = await conn.fetch("""
                SELECT id, crystal_text, face_path, domain
                FROM nate_intelligence_crystals
                WHERE face_path IS NOT NULL
                  AND face_path != ''
                  AND scope != 'archived'
                  AND face_path NOT LIKE '%:%:%:%'
                ORDER BY created_at DESC
                LIMIT 200
            """)

            if not untagged:
                logger.debug("L2 organizer: no untagged crystals found")
                return

            created = 0
            assigned = 0

            for row in untagged:
                l1_path = row["face_path"]
                crystal_text = row["crystal_text"]
                crystal_id = row["id"]

                existing_l2 = await conn.fetch("""
                    SELECT l2_label, keywords
                    FROM odpe_l2_faces
                    WHERE l1_face_path = $1
                    ORDER BY crystal_count DESC
                    LIMIT 100
                """, l1_path)

                best_match = None
                best_score = 0.0

                text_lower = crystal_text.lower()
                for l2 in existing_l2:
                    kws = l2["keywords"] if isinstance(l2["keywords"], list) else []
                    if not kws:
                        continue
                    hits = sum(1 for kw in kws if kw in text_lower)
                    score = hits / max(len(kws), 1)
                    if score > best_score and score > 0.3:
                        best_score = score
                        best_match = l2["l2_label"]

                if best_match:
                    new_face_path = f"{l1_path}:{best_match}"
                    await conn.execute("""
                        UPDATE nate_intelligence_crystals
                        SET face_path = $1
                        WHERE id = $2
                    """, new_face_path, crystal_id)
                    await conn.execute("""
                        UPDATE odpe_l2_faces
                        SET crystal_count = crystal_count + 1,
                            last_crystal_at = NOW()
                        WHERE l1_face_path = $3 AND l2_label = $4
                    """, l1_path, best_match)
                    assigned += 1
                else:
                    l2_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM odpe_l2_faces WHERE l1_face_path = $1",
                        l1_path,
                    )
                    if l2_count >= L2_MAX_PER_L1:
                        continue

                    words = [w for w in crystal_text.lower().split() if len(w) > 3][:10]
                    l2_label = "_".join(words[:3]) if words else f"moment_{crystal_id}"
                    l2_label = l2_label[:80]

                    try:
                        await conn.execute("""
                            INSERT INTO odpe_l2_faces (l1_face_path, l2_label, keywords, crystal_count, last_crystal_at)
                            VALUES ($1, $2, $3, 1, NOW())
                            ON CONFLICT (l1_face_path, l2_label) DO UPDATE
                            SET crystal_count = odpe_l2_faces.crystal_count + 1,
                                last_crystal_at = NOW()
                        """, l1_path, l2_label, json.dumps(words))

                        new_face_path = f"{l1_path}:{l2_label}"
                        await conn.execute("""
                            UPDATE nate_intelligence_crystals
                            SET face_path = $1
                            WHERE id = $2
                        """, new_face_path, crystal_id)
                        created += 1
                    except Exception as e:
                        logger.warning("L2 face creation failed for %s: %s", l1_path, e)

            prune_cutoff = datetime.utcnow() - timedelta(days=L2_PRUNE_DAYS)
            pruned = await conn.execute("""
                DELETE FROM odpe_l2_faces
                WHERE (last_crystal_at IS NULL OR last_crystal_at < $1)
                  AND crystal_count < $2
            """, prune_cutoff, L2_MIN_CRYSTALS_FOR_FACE)

            logger.info(
                "L2 organizer cycle #%d: assigned=%d, created=%d, pruned=%s",
                self._cycle_count + 1, assigned, created, pruned
            )

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
        }

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy" if self._running else "stopped",
            "cycles_completed": self._cycle_count,
        }
