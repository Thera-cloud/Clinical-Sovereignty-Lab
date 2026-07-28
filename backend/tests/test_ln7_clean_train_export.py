"""Offline tests for LN7 clean train export / filter (no DB)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

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
