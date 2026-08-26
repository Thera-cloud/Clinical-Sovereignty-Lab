"""Offline Phase B tests: synthetic grid, regulation window, validated scorer.

Loads modules by file path so collection does not import app.services.__init__
(Stripe/FastAPI side effects).
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_SERVICES = _BACKEND / "app" / "services"
_ROUTERS = _BACKEND / "app" / "routers"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def synthetic_mod():
    return _load("alphaln_synthetic_client", _SERVICES / "alphaln_synthetic_client.py")


@pytest.fixture(scope="module")
def gym_mod():
    return _load("alphaln_gym_service", _SERVICES / "alphaln_gym_service.py")


@pytest.fixture(scope="module")
def scorer_mod():
    return _load("alphaln_validated_scorer", _SERVICES / "alphaln_validated_scorer.py")


def test_synthetic_profile_grid_combinatorics(synthetic_mod):
    grid = synthetic_mod.generate_profile_grid()
    assert len(synthetic_mod.BASE_PERSONAS) == 7
    assert len(synthetic_mod.PATTERN_COMBOS) == 30
    assert len(synthetic_mod.TRIGGER_CONTEXTS) == 5
    assert len(grid) == 7 * 30 * 5
    assert len(grid) >= 500
    ids = {p["profile_id"] for p in grid}
    assert len(ids) == len(grid)
    first = grid[0]
    assert first["profile_id"] == str(
        synthetic_mod.profile_uuid(
            first["base_persona"],
            first["co_occurring_patterns"],
            first["trigger_context"],
        )
    )


def test_render_client_turn_is_stateful(synthetic_mod):
    lib = synthetic_mod.SyntheticClientLibrary()
    profile = {
        "profile_id": str(uuid.uuid4()),
        "base_persona": "SKEPTIC",
        "co_occurring_patterns": ["anxiety", "panic", "avoidance"],
        "trigger_context": "loss",
    }
    t0 = lib.render_client_turn(profile, None, 0)
    t1 = lib.render_client_turn(
        profile, "I'm with you. What is coming up as you stay with that?", 1
    )
    assert t0["state"]["turns"] == 1
    assert t1["state"]["turns"] == 2
    assert t1["state"]["trust"] > t0["state"]["trust"]
    assert t0["text"] != t1["text"]


def test_score_regulation_three_turn_window(gym_mod):
    cold = {"p_ent": 0.25, "t_tunnel": 0.25, "gamma_env": 0.50, "e_g": 0.60}
    hot = {"p_ent": 0.90, "t_tunnel": 0.90, "gamma_env": 0.12, "e_g": 0.12}
    miss = gym_mod.score_regulation([cold, cold, hot, hot])
    assert miss["regulation_achieved"] is False
    assert miss["turns_to_regulation"] is None

    hit = gym_mod.score_regulation([cold, hot, hot, hot])
    assert hit["regulation_achieved"] is True
    assert hit["turns_to_regulation"] == 4
    assert len(hit["c_emo_series"]) == 4
    assert all(s > 0.6 for s in hit["c_emo_series"][1:])

    early = gym_mod.score_regulation([hot, hot, hot])
    assert early["regulation_achieved"] is True
    assert early["turns_to_regulation"] == 3


def test_score_regulation_escalation_count(gym_mod):
    high = {"p_ent": 0.90, "t_tunnel": 0.90, "gamma_env": 0.10, "e_g": 0.10}
    crash = {"p_ent": 0.15, "t_tunnel": 0.15, "gamma_env": 0.70, "e_g": 0.80}
    out = gym_mod.score_regulation([high, crash])
    assert out["escalation_events"] >= 1


@pytest.mark.asyncio
async def test_wai_sr_srs_contract_mocked(scorer_mod):
    async def judge(prompt: str):
        if "Working Alliance" in prompt:
            return {"item_scores": [4.0] * 12, "notes": "alliance ok"}
        return {"item_scores": [8.0] * 4, "notes": "srs ok"}

    wai = await scorer_mod.score_wai_sr("client: hi\nnate: I'm with you.", judge=judge)
    assert wai["score_method"] == "wai_sr_v1"
    assert wai["agreed"] is True
    assert len(wai["item_scores"]) == 12
    assert wai["score"] == pytest.approx(4.0)

    srs = await scorer_mod.score_srs("short session", judge=judge)
    assert srs["score_method"] == "srs_v1"
    assert srs["agreed"] is True
    assert len(srs["item_scores"]) == 4
    assert srs["score"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_wai_sr_two_run_disagreement(scorer_mod):
    n = {"i": 0}

    async def judge(_prompt: str):
        n["i"] += 1
        scores = [5.0] * 12 if n["i"] % 2 else [1.0] * 12
        return {"item_scores": scores, "notes": "split"}

    wai = await scorer_mod.score_wai_sr("x", judge=judge)
    assert wai["agreed"] is False
    assert wai["item_scores"] == []
    assert wai["run_delta"] >= 0.5


def test_phq9_delta_proxy(scorer_mod):
    before = {"affect": 0.9, "trust": 0.1}
    after = {"affect": 0.3, "trust": 0.7}
    out = scorer_mod.score_phq9_delta(before, after)
    assert out["score_method"] == "phq9_delta_v1"
    assert out["score"] < 0
    assert len(out["item_scores"]) == 2


def test_score_method_sql_accepts_validated_values():
    sql = (_BACKEND / "migrations" / "432_alphaln_score_method_expansion.sql").read_text()
    for method in ("heuristic_v1", "wai_sr_v1", "srs_v1", "phq9_delta_v1"):
        assert method in sql
    assert "alphaln_shadow_observations_score_method_check" in sql


def test_search_intent_and_recall_source_tag():
    src = (_ROUTERS / "alphaln_admin_api.py").read_text()
    assert 'source="alphaln_twin"' in src
    # First recall call site must not use the chat default source.
    after = src.split("recall_crystals_for_context(")[1][:500]
    assert 'source="alphaln_twin"' in after
    assert "bridge_chat" not in after
    assert "search" in src.lower() and "SecureSearchProxy" in src
    assert "alphaln_research" in src
