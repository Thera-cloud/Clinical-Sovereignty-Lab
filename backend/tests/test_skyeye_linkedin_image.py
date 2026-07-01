"""Offline tests for SkyEye LinkedIn Gemini image helpers."""
from app.services.skyeye_linkedin_image import (
    build_image_prompt,
    linkedin_images_enabled,
    should_attach_image_for_lane,
)


def test_linkedin_images_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_SKYEYE_LINKEDIN_IMAGES", raising=False)
    assert linkedin_images_enabled() is False
    assert should_attach_image_for_lane("ORIG") is False


def test_should_attach_orig_pers_only(monkeypatch):
    monkeypatch.setenv("ENABLE_SKYEYE_LINKEDIN_IMAGES", "true")
    assert should_attach_image_for_lane("ORIG") is True
    assert should_attach_image_for_lane("PERS") is True
    assert should_attach_image_for_lane("CUR") is False
    assert should_attach_image_for_lane("") is False


def test_build_image_prompt_includes_post_theme(monkeypatch):
    monkeypatch.setenv("SKYEYE_LINKEDIN_BRAND_STYLE", "false")
    prompt = build_image_prompt(
        "Leadership in uncertainty matters.",
        lane="ORIG",
        slot_key="2026-07-01_2000_d2",
    )
    assert "Leadership in uncertainty" in prompt
    assert "ORIG" in prompt
    assert "no text" in prompt.lower()


def test_build_branded_prompt_uses_infographic_system(monkeypatch):
    monkeypatch.setenv("SKYEYE_LINKEDIN_BRAND_STYLE", "true")
    prompt = build_image_prompt(
        "Leadership in uncertain times.\n\nTakeaway: Show up honestly.\n\n"
        "Nathaniel reviewed + approved — Little Nate, your AI companion",
        lane="ORIG",
    )
    assert "Sovereign Sanctuary" in prompt
    assert "16:9" in prompt
    assert "HEADLINE:" in prompt
    assert "LEADERSHIP IN UNCERTAIN TIMES" in prompt


def test_brand_reference_loader(monkeypatch):
    from app.services.skyeye_linkedin_brand import load_brand_reference_images

    monkeypatch.setenv("SKYEYE_LINKEDIN_BRAND_REFS", "true")
    refs = load_brand_reference_images()
    assert len(refs) >= 1
    assert all(isinstance(r[0], bytes) and r[1].startswith("image/") for r in refs)


def test_build_image_prompt_strips_banned_words(monkeypatch):
    monkeypatch.setenv("SKYEYE_LINKEDIN_BRAND_STYLE", "false")
    prompt = build_image_prompt("The liminal threshold aching space.")
    assert "liminal" not in prompt.lower()
    assert "threshold" not in prompt.lower()
    assert "aching" not in prompt.lower()


def test_gemini_aspect_maps_linkedin_to_16_9():
    from app.services.skyeye_gemini_image import _normalize_aspect_ratio

    assert _normalize_aspect_ratio("1.91:1") == "16:9"
    assert _normalize_aspect_ratio("16:9") == "16:9"
