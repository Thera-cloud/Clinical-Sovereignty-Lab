"""Living CI packs from Queens merges (R2 / W8).

Materializes pack dirs under backend/app/data/ln_sandbox_ci_packs/living_*
and records a sandbox deploy hook marker for Orange sync.

# QUANTUM-CRYSTAL-ARCH
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ln7_living_packs")

_PACKS_ROOT = Path(__file__).resolve().parents[1] / "data" / "ln_sandbox_ci_packs"


def packs_root() -> Path:
    override = os.getenv("LN7_SANDBOX_PACKS_DIR", "").strip()
    return Path(override) if override else _PACKS_ROOT


def materialize_living_pack(
    pack_name: str,
    *,
    patch_hash: str,
    domain: str = "",
    split: str = "train",
) -> Dict[str, Any]:
    """Write a self-contained sandbox CI pack (broken + tests + golden + task)."""
    root = packs_root() / pack_name
    broken = root / "broken"
    tests = root / "tests"
    broken.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)

    short = (patch_hash or "unknown")[:12]
    tag = f"living_{short}"

    (broken / "__init__.py").write_text(
        '"""Broken on purpose — living CI pack distilled from Queens merge."""\n',
        encoding="utf-8",
    )
    (broken / "fix.py").write_text(
        f'"""Broken living pack: {tag}."""\n\n'
        f"def value() -> str:\n"
        f"    # BUG: living probe {short} not fixed\n"
        f'    return "LIVING_BUG {short}"\n\n'
        f"def looks_fixed(s: str) -> bool:\n"
        f'    return "LIVING_OK {short}" in s and "LIVING_BUG {short}" not in s\n',
        encoding="utf-8",
    )
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_fix.py").write_text(
        "from broken.fix import value, looks_fixed\n\n\n"
        "def test_fixed():\n"
        "    assert looks_fixed(value())\n",
        encoding="utf-8",
    )
    (root / "golden.patch").write_text(
        "--- a/broken/fix.py\n"
        "+++ b/broken/fix.py\n"
        "@@ -2,7 +2,7 @@\n"
        "\n"
        " def value() -> str:\n"
        f"-    # BUG: living probe {short} not fixed\n"
        f"+    # Fixed: living probe {short}\n"
        f'-    return "LIVING_BUG {short}"\n'
        f'+    return "LIVING_OK {short}"\n',
        encoding="utf-8",
    )
    task = {
        "task_key": f"ci_{pack_name}",
        "title": f"Living pack {short}",
        "prompt": (
            f"broken/fix.py returns 'LIVING_BUG {short}'. Change the return to "
            f"'LIVING_OK {short}' and update the BUG comment. Return ONLY a unified "
            "diff for broken/fix.py. No markdown fences."
        ),
        "test_path": "tests/test_fix.py",
        "target_files": ["broken/fix.py"],
        "domain": domain or "coding",
        "split": split,
        "domain_tag": "python",
        "provenance": {"patch_hash": patch_hash, "kind": "living_distill"},
    }
    (root / "task.json").write_text(
        json.dumps(task, indent=2) + "\n", encoding="utf-8"
    )
    return {"ok": True, "path": str(root), "pack_name": pack_name}


def sandbox_deploy_hook(pack_name: str) -> Dict[str, Any]:
    """Record deploy intent for Orange sandbox sync (no SSH from GREEN by default)."""
    marker_dir = packs_root() / ".deploy_queue"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f"{pack_name}.ready"
    marker.write_text(
        json.dumps(
            {
                "pack_name": pack_name,
                "ready_at": datetime.now(timezone.utc).isoformat(),
                "dest": "/opt/sandbox/ln_sandbox_ci_packs/",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Optional bus publish for Twin/Orange consumer
    try:
        from app.websocket.cli_task_bus import publish_task

        publish_task(
            origin="ln7_living_packs",
            kind="sandbox_pack_sync",
            notes=json.dumps({"pack_name": pack_name, "action": "rsync_living"}),
            files=[],
        )
    except Exception as e:
        logger.debug("sandbox_deploy_hook bus: %s", e)
    return {"ok": True, "marker": str(marker)}


async def record_pack_candidate(
    db_pool,
    *,
    patch_hash: str,
    domain: str = "",
    evidence_uri: str = "",
) -> bool:
    if not db_pool or not patch_hash:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ln7_pack_candidates (patch_hash, domain, evidence_uri)
                VALUES ($1, $2, $3)
                ON CONFLICT (patch_hash) DO NOTHING
                """,
                patch_hash,
                domain or None,
                evidence_uri or None,
            )
        return True
    except Exception as e:
        logger.warning("record_pack_candidate failed: %s", e)
        return False


async def mark_revert(db_pool, patch_hash: str) -> bool:
    if not db_pool or not patch_hash:
        return False
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ln7_pack_candidates
                SET revert_seen = TRUE
                WHERE patch_hash = $1
                """,
                patch_hash,
            )
        return True
    except Exception as e:
        logger.warning("mark_revert failed: %s", e)
        return False


async def distill_due_packs(
    db_pool,
    *,
    min_age_days: int = 7,
) -> Dict[str, Any]:
    """Daily job: materialize packs aged ≥ N days with no revert."""
    if not db_pool:
        return {"ok": False, "distilled": 0}
    try:
        from app.services.ln7_frozen_config import load_json

        gov = load_json("governance.json", {}) or {}
        min_age_days = int(gov.get("living_pack_min_age_days", min_age_days))
    except Exception:
        pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    distilled = 0
    materialized: List[str] = []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, patch_hash, domain
                FROM ln7_pack_candidates
                WHERE distilled_at IS NULL
                  AND retired_at IS NULL
                  AND revert_seen = FALSE
                  AND merged_at <= $1
                LIMIT 20
                """,
                cutoff,
            )
            for row in rows:
                split = random.choice(["train", "heldout"])
                pack_name = f"living_{row['patch_hash'][:12]}"
                try:
                    mat = materialize_living_pack(
                        pack_name,
                        patch_hash=str(row["patch_hash"]),
                        domain=str(row["domain"] or ""),
                        split=split,
                    )
                    if mat.get("ok"):
                        sandbox_deploy_hook(pack_name)
                        materialized.append(pack_name)
                except Exception as me:
                    logger.warning("materialize %s failed: %s", pack_name, me)
                    continue
                await conn.execute(
                    """
                    UPDATE ln7_pack_candidates
                    SET distilled_at = NOW(), pack_name = $2, split = $3
                    WHERE id = $1
                    """,
                    row["id"],
                    pack_name,
                    split,
                )
                distilled += 1
                logger.info(
                    "living pack distilled: %s domain=%s split=%s",
                    pack_name,
                    row["domain"],
                    split,
                )
    except Exception as e:
        logger.warning("distill_due_packs failed: %s", e)
        return {
            "ok": False,
            "distilled": distilled,
            "materialized": materialized,
            "error": str(e),
        }
    return {"ok": True, "distilled": distilled, "materialized": materialized}


class LivingPackAgent:
    """Background daily distill."""

    def __init__(self, db_pool, interval_seconds: int = 86400):
        self.db_pool = db_pool
        self.interval = interval_seconds
        self._task = None
        self._running = False

    async def start(self):
        import asyncio

        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        import asyncio

        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_loop(self):
        import asyncio

        await asyncio.sleep(190)
        while self._running:
            try:
                await distill_due_packs(self.db_pool)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("LivingPackAgent cycle failed: %s", e)
            await asyncio.sleep(self.interval)
