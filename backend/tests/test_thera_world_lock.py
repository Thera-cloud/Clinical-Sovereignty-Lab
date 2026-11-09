"""Offline Thera-world lock: alias metadata merge, champion fallback, greeting still."""

from app.sse.neuro_region_engine import merge_journey_metadata_dicts
from app.sse.neuro_scoring import pair_champion
from app.sse.thera_world_regions import REGION_NEURO, REGION_ORIGIN


def test_merge_metadata_neuro_beats_wander():
    merged = merge_journey_metadata_dicts(
        {"explore_region": "wander"},
        {"explore_region": "neuro", "explore_regen_count": 1},
    )
    assert merged["explore_region"] == REGION_NEURO
    assert merged["explore_regen_count"] == 1


def test_merge_metadata_origin_beats_later_wander():
    merged = merge_journey_metadata_dicts(
        {"explore_region": "origin"},
        {"explore_region": "wander"},
    )
    assert merged["explore_region"] == REGION_ORIGIN


def test_pair_champion_skip_falls_back_to_ranked():
    from app.sse.neuro_scoring import STRUCTURE_TO_BIOME, champions_for_biome

    biome = next(iter(STRUCTURE_TO_BIOME.values()))
    cands = champions_for_biome(biome)
    assert cands, biome
    skip = [c.get("name") or "" for c in cands]
    champ = pair_champion({"authority_deficit": 0.8}, biome, skip_names=skip)
    assert champ is not None
    assert champ.get("name")


def test_greeting_uses_panel_of_the_day_resolver():
    """Greeting reads the shared resolver (journey still OR storyboard daily
    panel); the resolver itself keeps the journey + r2_url filter."""
    from app.services.thrive import entry_greeting as eg
    from app.sse import panel_of_the_day as pod
    src = open(eg.__file__).read()
    assert "resolve_panel_of_the_day" in src
    assert "FROM sse_panel_log" not in src
    rsrc = open(pod.__file__).read()
    assert "AND panel_type = 'journey'" in rsrc
    assert "AND r2_url IS NOT NULL" in rsrc
    assert "generation_type = 'daily_panel'" in rsrc


def test_recap_and_chat_fallback_use_resolver():
    import os
    from app.services import sse_panel_chat_context as spc
    # admin.py is import-heavy (needs JWT_SECRET etc.) — read by path.
    admin_path = os.path.join(os.path.dirname(spc.__file__), "..", "routers", "admin.py")
    asrc = open(admin_path).read()
    assert "resolve_panel_of_the_day(conn, ids)" in asrc
    assert "last_panel_source" in asrc and "last_panel_is_today" in asrc
    csrc = open(spc.__file__).read()
    assert "resolve_panel_of_the_day" in csrc
    assert "fetch_panel_row_by_id" in csrc


def test_layer0_skips_on_journey_aliases():
    from app.sse import layer0_orchestrator as lo
    src = open(lo.__file__).read()
    assert "panel_type = 'journey'" in src
    assert "resolve_journey_aliases" in src


def test_neuro_resolve_walks_champion_map():
    from app.sse import neuro_region_engine as nre
    src = open(nre.__file__).read()
    assert "champions_for_biome" in src
    assert "STRUCTURE_TO_BIOME.values()" in src
    assert "ORDER BY CASE WHEN role = 'CLIENT'" in src
    assert "(hardware_id = ANY($1::text[]) OR username = ANY($1::text[]))" in src
