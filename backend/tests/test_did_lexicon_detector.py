"""D.I.D. lexicon detector_patterns → Layer 1 cue wiring (pattern-gated)."""

from app.services.lexicon_loader import (
    collect_did_lexicon_layer1_cues,
    invalidate_cache,
    load_active_lexicons,
)


def setup_function() -> None:
    invalidate_cache()


def test_did_systems_yaml_loaded_when_clinically_active() -> None:
    merged = load_active_lexicons(["did_systems"])
    assert merged, "repo did_systems/*.yaml must be clinically_active for this suite"


def test_collect_empty_without_message() -> None:
    cues, hits = collect_did_lexicon_layer1_cues(None)
    assert cues == [] and hits == []


def test_collect_empty_when_no_pattern_match() -> None:
    cues, hits = collect_did_lexicon_layer1_cues(
        "generic weather small talk nothing clinical here",
        max_items=10,
    )
    assert hits == []
    assert cues == []


def test_collect_matches_multiphrase_and_records_hits() -> None:
    cues, hits = collect_did_lexicon_layer1_cues(
        "I've been fronting all day and my system is exhausted",
        max_items=10,
    )
    assert "fronting" in hits
    assert "my system" in hits
    assert cues, "matched patterns should yield at least one cue line"


def test_alter_word_boundary_avoids_altercation() -> None:
    _cues, hits = collect_did_lexicon_layer1_cues(
        "there was an altercation outside",
        max_items=10,
    )
    assert "alter" not in hits


def test_alter_matches_as_standalone_word() -> None:
    _cues, hits = collect_did_lexicon_layer1_cues(
        "one of my alters needed a break",
        max_items=10,
    )
    assert "alter" in hits
