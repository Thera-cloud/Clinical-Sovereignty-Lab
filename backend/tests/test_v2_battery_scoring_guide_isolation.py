"""Fence: scoring_guide must never reach response-generation prompts.

v2 battery stems carry a clinician/draft `scoring_guide` (expected moves).
Generation paths (fill_human_gold_nate_responses, live_stack_blinds) MUST
SELECT client_says only — never scoring_guide.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
V2_STEMS = ROOT / "backend" / "app" / "data" / "six_quotient_human_gold_stems_v2.json"
GENERATION_SOURCES = [
    ROOT / "backend" / "scripts" / "fill_human_gold_nate_responses.py",
    ROOT / "backend" / "app" / "services" / "live_stack_blinds.py",
]


def test_v2_stems_file_exists_and_has_70():
    data = json.loads(V2_STEMS.read_text())
    stems = data["stems"]
    assert len(stems) == 70, f"expected 70 stems (batches 1+2+3), got {len(stems)}"
    ids = [s["scenario_id"] for s in stems]
    assert len(ids) == len(set(ids))


def test_batch3_provenance_clinician_revised():
    data = json.loads(V2_STEMS.read_text())
    b3 = [s for s in data["stems"] if s["scenario_id"].endswith(("-V09", "-V10", "-V11", "-V12"))]
    assert len(b3) == 22, len(b3)
    for s in b3:
        assert s["provenance"] == "model_generated_then_clinician_revised", s["scenario_id"]


def test_no_stems_remain_pending_clinician_revision():
    data = json.loads(V2_STEMS.read_text())
    pending = [
        s for s in data["stems"]
        if s["provenance"] == "model_generated_pending_clinician_revision"
    ]
    assert not pending, [s["scenario_id"] for s in pending]


def test_batch2_provenance_clinician_revised():
    data = json.loads(V2_STEMS.read_text())
    b2 = [s for s in data["stems"] if s["scenario_id"].endswith(tuple(f"-V0{i}" for i in range(5, 9)))]
    assert len(b2) == 24
    for s in b2:
        assert s["provenance"] == "model_generated_then_clinician_revised", s["scenario_id"]


def test_battery_total_is_70_stems_across_6_quotients():
    data = json.loads(V2_STEMS.read_text())
    from collections import Counter

    secs = Counter(s["section"] for s in data["stems"])
    assert sum(secs.values()) == 70
    assert set(secs.keys()) == {"IQ", "EQ", "MQ", "SQ", "CQ", "AQ"}


def test_batch1_provenance_clinician_authored():
    data = json.loads(V2_STEMS.read_text())
    b1 = [s for s in data["stems"] if s["scenario_id"].endswith(tuple(f"-V0{i}" for i in range(1, 5)))]
    assert len(b1) == 24
    for s in b1:
        assert s["provenance"] == "v2_battery_clinician_authored", s["scenario_id"]


def test_every_stem_has_scoring_guide_separate_from_client_says():
    data = json.loads(V2_STEMS.read_text())
    for s in data["stems"]:
        assert (s.get("scoring_guide") or "").strip(), s["scenario_id"]
        assert (s.get("client_says") or "").strip(), s["scenario_id"]
        cs = s["client_says"]
        assert "tests:" not in cs.lower(), s["scenario_id"]
        # Full guide text must not be concatenated into the stem
        assert s["scoring_guide"] not in cs, s["scenario_id"]


def test_generation_sources_never_select_scoring_guide():
    pattern = re.compile(r"\bscoring_guide\b")
    for path in GENERATION_SOURCES:
        text = path.read_text()
        hits = pattern.findall(text)
        assert not hits, (
            f"{path.name} references scoring_guide — generation must not "
            f"load the rater rubric into prompts"
        )


def test_infer_one_and_live_stack_use_client_says_only():
    """AST-level: _infer_one body only formats client_says into the prompt."""
    fill = (ROOT / "backend" / "scripts" / "fill_human_gold_nate_responses.py").read_text()
    tree = ast.parse(fill)
    found = False
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_infer_one":
            found = True
            src = ast.get_source_segment(fill, node) or ""
            assert "scoring_guide" not in src
            assert "client_says" in src
    assert found, "_infer_one missing"

    live = (ROOT / "backend" / "app" / "services" / "live_stack_blinds.py").read_text()
    # Generation SELECT blocks must not include scoring_guide
    for m in re.finditer(
        r"SELECT[\s\S]{0,400}?FROM\s+six_quotient_human_gold",
        live,
        re.IGNORECASE,
    ):
        block = m.group(0)
        assert "scoring_guide" not in block, block[:200]


def test_migration_323_adds_scoring_guide_column():
    mig = ROOT / "backend" / "migrations" / "323_v2_battery_scoring_guide.sql"
    text = mig.read_text()
    assert "ADD COLUMN IF NOT EXISTS scoring_guide" in text
    assert "Never" in text or "never" in text


# `scoring_guide` is display-only rater reference. It is allowed in the
# read-only GET /gold/items handler (gold_items) that feeds the scoring UI,
# and nowhere else in the Principal-Review API — never in a promote/write
# function, never threaded into notes/principal_response/crystal_text.
_ALLOWED_SCORING_GUIDE_FUNCS = frozenset({"gold_items"})


def test_scoring_guide_confined_to_gold_items_read_endpoint():
    api = ROOT / "backend" / "app" / "routers" / "principal_review_api.py"
    src = api.read_text()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name in _ALLOWED_SCORING_GUIDE_FUNCS:
            continue
        body_src = ast.get_source_segment(src, node) or ""
        if "scoring_guide" in body_src:
            offenders.append(node.name)
    assert not offenders, (
        f"scoring_guide referenced outside {sorted(_ALLOWED_SCORING_GUIDE_FUNCS)}: "
        f"{offenders} — it must stay display-only, never written into any "
        f"promote/library/crystal path"
    )


def test_gold_items_scoring_guide_is_schema_guarded():
    """gold_items() must tolerate migration 323 not being applied yet."""
    api = ROOT / "backend" / "app" / "routers" / "principal_review_api.py"
    src = api.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "gold_items":
            body_src = ast.get_source_segment(src, node) or ""
            assert "information_schema.columns" in body_src
            assert "has_scoring_guide" in body_src
            return
    raise AssertionError("gold_items endpoint not found")
