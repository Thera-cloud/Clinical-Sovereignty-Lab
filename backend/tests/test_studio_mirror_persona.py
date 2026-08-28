"""A–E Mirror Capture persona review: extract, diff, ops, booth fallback."""

from pathlib import Path

from app.services.coach_voice_profile_service import (
    apply_style_ops,
    extract_do_not_lines,
    extract_toss_lines,
    heuristic_style,
    merge_style,
    style_diff,
)
from app.services.studio_invariants import filter_style_layer
from app.services.studio_mirror_capture import (
    BOOTH_KINDS,
    _booth_fallback,
    review_fields,
    sniff_audio_type,
)

ROOT = Path(__file__).resolve().parents[2]


def test_e_merge_keeps_do_not_and_toss():
    merged = merge_style(
        heuristic_style("I never diagnose. I toss to Little Nate when they ramble."),
        {
            "do_not_say": ["journey"],
            "toss_phrases": ["Nate, take this."],
            "signature_frameworks": ["invitation close"],
        },
    )
    assert "journey" in merged["do_not_say"]
    assert any("never" in x.lower() or "diagnose" in x.lower() for x in merged["do_not_say"])
    assert "Nate, take this." in merged["toss_phrases"]
    assert "invitation close" in merged["signature_frameworks"]


def test_e_part7_all_lines_harvest():
    lines = extract_do_not_lines("clinical\ntherapy\nprescribe hope", all_lines=True)
    assert lines == ["clinical", "therapy", "prescribe hope"]


def test_e_toss_lines():
    found = extract_toss_lines("When they stall I toss to Little Nate and sit back.")
    assert found
    assert any("toss" in x.lower() for x in found)


def test_e_ln_prompt_asks_do_not():
    src = (ROOT / "backend/app/services/coach_voice_profile_service.py").read_text()
    assert "do_not_say (array of words/phrases they forbid)" in src
    assert "toss_phrases (array of on-air toss lines" in src


def test_e_filter_allows_do_not():
    cleaned, rejected = filter_style_layer(
        {"do_not_say": ["journey"], "_guardrail_x": "nope", "tone": "direct"}
    )
    assert cleaned["do_not_say"] == ["journey"]
    assert "_guardrail_x" in rejected


def test_persist_strips_meta_not_guardrails():
    cleaned, rejected = filter_style_layer(
        {"tone": "direct", "source": "merged", "version": 2, "_guardrail_x": "no"}
    )
    locked = [
        k
        for k in rejected
        if str(k).startswith("_guardrail_") or str(k).startswith("_vertical_")
    ]
    assert cleaned["tone"] == "direct"
    assert "source" in rejected
    assert locked == ["_guardrail_x"]


def test_a_style_diff_and_ops():
    old = {"tone": "warm", "phrases": ["stay with it"], "do_not_say": []}
    new = {"tone": "direct", "phrases": ["stay with it", "one invitation"], "do_not_say": ["journey"]}
    diff = style_diff(old, new)
    keys = {(d["key"], d["op"], d["value"]) for d in diff}
    assert ("tone", "set", "direct") in keys
    assert ("phrases", "add", "one invitation") in keys
    assert ("do_not_say", "add", "journey") in keys
    applied = apply_style_ops(old, [d for d in diff if d["op"] != "remove"])
    assert applied["tone"] == "direct"
    assert "journey" in applied["do_not_say"]


def test_a_review_fields_shape():
    fields = review_fields({"tone": "direct", "phrases": ["a", ""], "secret": "drop"})
    assert fields["tone"] == "direct"
    assert fields["phrases"] == ["a"]
    assert "secret" not in fields
    assert "do_not_say" in fields


def test_b_sniff_wav_and_webm():
    wav = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8
    assert sniff_audio_type(wav) == "audio/wav"
    assert sniff_audio_type(b"\x1aE\xdf\xa3") == "audio/webm"


def test_d_booth_kinds_and_fallback():
    assert set(BOOTH_KINDS) == {"newsletter_open", "toss", "caller_recovery", "free"}
    reply = _booth_fallback(
        {"phrases": ["Stay with what matters."], "toss_phrases": ["Nate, take this."]},
        "toss",
        "",
    )
    assert "Nate" in reply


def test_c_d_routes_exist():
    src = (ROOT / "backend/app/routers/coach_integrations_api.py").read_text()
    for path in (
        '/mirror-capture/persona',
        '/mirror-capture/style/apply',
        '/mirror-capture/parts/{n}/transcript',
        '/mirror-capture/parts/{n}/audio',
        '/mirror-capture/booth',
        '/mirror-capture/booth/feedback',
        "coach_note",
    ):
        assert path in src


def test_flutter_persona_surfaces():
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    tools = (ROOT / "mobile/lib/widgets/coach_studio_persona_tools.dart").read_text()
    assert "PERSONA REVIEW" in tools
    assert "LIKENESS BOOTH" in tools
    assert "CoachStudioPersonaTools" in dart
    assert "Show transcript" in dart
    assert "Play" in dart
