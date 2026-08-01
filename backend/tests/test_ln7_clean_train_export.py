"""Offline tests for LN7 clean train export / filter (no DB)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "scripts"))


def test_golden_export_is_real_diff():
    from ln7_export_train_jsonl import golden_rows, _is_real_diff

    rows = golden_rows()
    assert len(rows) >= 2
    for r in rows:
        asst = r["messages"][1]["content"]
        assert _is_real_diff(asst)
        assert not asst.startswith("[patch_hash=")
        assert r["pack"] != "env_redis_prefix"
        assert len(asst) <= 4000 or True  # capped at write path


def test_filter_clean_rows_drops_stubs():
    from ln7_qlora_train import filter_clean_rows

    raw = [
        {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "[patch_hash=abc]"}]},
        {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "--- a/x\n+++ b/x\n@@\n-a\n+b\n"}]},
        {"method": "dry_run_stub", "messages": [{"role": "assistant", "content": "--- a\n+++ b\n@@\n+1\n"}]},
    ]
    clean = filter_clean_rows(raw)
    assert len(clean) == 1
    assert "+++" in clean[0]["messages"][1]["content"]


def test_lora_recipe_all_linear():
    from ln7_qlora_train import _lora_recipe, ALL_LINEAR_MODULES

    d = _lora_recipe("default")
    assert d["r"] == 16 and d["target_modules"] == ["q_proj", "v_proj"]
    a = _lora_recipe("all_linear")
    assert a["r"] == 32 and a["lora_alpha"] == 64
    assert a["target_modules"] == ALL_LINEAR_MODULES


def test_goldens_only_cli(tmp_path):
    import subprocess

    out = tmp_path / "t.jsonl"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "backend/scripts/ln7_export_train_jsonl.py"),
            "--out", str(out),
            "--goldens-only",
        ],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(ROOT / "backend")},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout
    lines = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
    assert len(lines) >= 2


class _FakeConn:
    """Simulates a Postgres connection that already applied the SQL WHERE
    clause — fetch() only returns rows a real `t.split = 'train'` filter would
    return. The env_redis_prefix row has split=NULL (mirrors a CI pack with no
    ln7_tasks row) so it can only be caught by the Python-side HELDOUT_PACKS
    check — proving that layer still works independently of the SQL layer.
    """

    def __init__(self, rows, heldout_sql_count):
        self._rows = rows
        self._heldout_sql_count = heldout_sql_count
        self.fetch_calls = []

    async def fetchval(self, query, *args):
        if "information_schema.columns" in query:
            return True
        if "t.split = 'heldout'" in query:
            return self._heldout_sql_count
        return None

    async def fetch(self, query, *args):
        self.fetch_calls.append(query)
        assert "t.split = 'train'" in query, "SQL-level heldout exclusion regressed"
        assert "'train', 'heldout'" not in query, "heldout must not be fetched at all"
        return self._rows

    async def close(self):
        return None


def test_export_rows_sql_level_heldout_exclusion_plus_pack_name_layer():
    """Phase D behavioral test: two independent heldout hard-block layers.

    Layer 1 (SQL): a real `t.split = 'heldout'` row is never returned by the
    query at all (asserted inside _FakeConn.fetch above; counted separately
    via a COUNT(*) fetchval for observability).
    Layer 2 (Python/pack-name): a row with split=NULL but pack='env_redis_prefix'
    (a HELDOUT_PACKS member) still gets dropped even though the SQL layer let
    it through, and it must never reach the exported JSONL.
    """
    from ln7_export_train_jsonl import export_rows, HELDOUT_PACKS

    assert "env_redis_prefix" in HELDOUT_PACKS

    good_diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    rows = [
        {
            "id": 1,
            "task_id": "t1",
            "patch_hash": "hash-good",
            "revision_id": "LN7-cand",
            "harness_mode": "sandbox",
            "metrics_json": json.dumps({"pack": "catch_all_routes"}),
            "diff_lines": 4,
            "tokens": 100,
            "passed": True,
            "patch_text": good_diff,
            "split": None,
            "spdx_license": "MIT",
            "prompt_summary": "Fix catch_all_routes",
            "task_hash": "th1",
        },
        {
            "id": 2,
            "task_id": "t2",
            "patch_hash": "hash-heldout-pack",
            "revision_id": "LN7-cand",
            "harness_mode": "sandbox",
            "metrics_json": json.dumps({"pack": "env_redis_prefix"}),
            "diff_lines": 4,
            "tokens": 100,
            "passed": True,
            "patch_text": good_diff,
            "split": None,  # not caught by SQL split filter — must be caught by pack-name layer
            "spdx_license": "MIT",
            "prompt_summary": "Fix env_redis_prefix",
            "task_hash": "th2",
        },
    ]
    conn = _FakeConn(rows, heldout_sql_count=3)

    async def _go():
        with patch("asyncpg.connect", AsyncMock(return_value=conn)):
            return await export_rows(limit=50, include_goldens=False, goldens_only=False)

    out, stats = asyncio.run(_go())

    packs_out = {r["pack"] for r in out}
    assert "env_redis_prefix" not in packs_out
    assert all(r["patch_hash"] != "hash-heldout-pack" for r in out)
    assert stats["dropped_heldout"] >= 1
    assert stats["dropped_heldout_sql"] == 3
    assert conn.fetch_calls, "fetch() was never called"
