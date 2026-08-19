"""INV-5 style whitelist + INV-6 copy + clone context."""

from _studio_load import load_svc

_inv = load_svc("studio_invariants")
_bp = load_svc("broadcast_persona_resolver")
validate_show_copy = _bp.validate_show_copy
validate_vertical = _bp.validate_vertical
STYLE_KEYS = _inv.STYLE_KEYS
VERTICALS = _inv.VERTICALS
clone_context_allowed = _inv.clone_context_allowed
filter_style_layer = _inv.filter_style_layer
inv6_blocks = _inv.inv6_blocks


def test_style_whitelist_rejects_guardrail_keys():
    cleaned, rejected = filter_style_layer(
        {
            "tone": "warm",
            "_guardrail_secret": "x",
            "_vertical_override": "y",
            "diagnose": "no",
        }
    )
    assert cleaned == {"tone": "warm"}
    assert "_guardrail_secret" in rejected
    assert "_vertical_override" in rejected
    assert "diagnose" in rejected


def test_style_keys_are_allowlist():
    assert "tone" in STYLE_KEYS
    assert "do_not_say" in STYLE_KEYS
    assert "_guardrail_secret" not in STYLE_KEYS


def test_five_verticals():
    assert VERTICALS == (
        "life_coaching",
        "grief",
        "relationships_intimacy",
        "trauma_modalities",
        "neuroscience_education",
    )
    assert validate_vertical("grief") is None
    assert validate_vertical("therapy") is not None


def test_inv6_and_show_copy():
    assert inv6_blocks("We will diagnose you")
    assert validate_show_copy("Clinical hour", "therapy") is not None
    assert validate_show_copy("Morning show", "education") is None


def test_clone_never_ln_broadcast():
    assert clone_context_allowed("ln_broadcast") is False
    assert clone_context_allowed("coach_clone") is True
