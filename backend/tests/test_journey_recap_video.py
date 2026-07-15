"""Offline tests for Journey Recap alignment + duration math."""
from __future__ import annotations

from app.sse import journey_recap_video as recap


def test_segment_duration_thirty_seconds_four_segments():
    assert recap.segment_duration(30, 4) == 7.5


def test_split_transcript_four_segments():
    text = (
        "I walked into the forest feeling lost. Nate helped me see the pattern. "
        "My archetype stepped forward with courage. I left knowing I belong."
    )
    parts = recap.split_transcript_segments(text, 4)
    assert len(parts) == 4
    assert all(isinstance(p, str) for p in parts)
    joined = " ".join(p for p in parts if p)
    assert "forest" in joined or "archetype" in joined


def test_align_transcript_to_panels_heuristic():
    panels = [
        {"id": "p1", "narrative_text": "A quiet forest path at dawn", "r2_url": "http://x/1.png"},
        {"id": "p2", "narrative_text": "The sovereign traveler faces the mirror", "r2_url": "http://x/2.png"},
        {"id": "p3", "narrative_text": "Courage rises in the clearing", "r2_url": "http://x/3.png"},
        {"id": "p4", "narrative_text": "Belonging by the hearth fire", "r2_url": "http://x/4.png"},
    ]
    transcript = (
        "I felt lost on a forest path. Nate mirrored my fear. "
        "Courage showed up. I finally felt belonging."
    )
    segments = recap.align_transcript_to_panels(transcript, panels, segment_count=4)
    assert len(segments) == 4
    assert segments[0]["transcript_excerpt"]
    assert segments[0]["panel_id"] in {"p1", "p2", "p3", "p4"}


def test_refresh_panel_r2_url_represigns():
    stored = (
        "https://acct.r2.cloudflarestorage.com/nate-vault/stories/u/daily_panel/2026-07-05/abc.png"
        "?X-Amz-Date=20260705T030047Z&X-Amz-Expires=86400"
    )
    key = recap._r2_key_from_url(stored)
    assert key == "stories/u/daily_panel/2026-07-05/abc.png"


def test_json_safe_datetime():
    from datetime import datetime, timezone

    dt = datetime(2026, 7, 15, 3, 53, 47, tzinfo=timezone.utc)
    out = recap._json_safe([{"generated_at": dt, "panel_id": "p1"}])
    assert out[0]["generated_at"] == dt.isoformat()


def test_manual_panel_alignment_override():
    panels = [
        {"id": "p1", "narrative_text": "forest", "r2_url": "u1"},
        {"id": "p2", "narrative_text": "mirror", "r2_url": "u2"},
    ]
    manual = [{"segment_index": 0, "panel_id": "p2", "transcript_excerpt": "custom beat"}]
    segments = recap.align_transcript_to_panels(
        "one two three four five six seven eight",
        panels,
        segment_count=2,
        manual_alignments=manual,
    )
    assert segments[0]["panel_id"] == "p2"
    assert segments[0]["transcript_excerpt"] == "custom beat"


def test_build_panel_visual_theme_includes_archetype_and_prompt():
    panel = {
        "panel_type": "daily_panel",
        "panel_tone": "threshold_pathway",
        "biome": "whisperwood",
        "character_manifest": "explorer at the gate",
        "prompt_used": "golden threshold light, painterly gouache, sovereign sanctuary palette",
    }
    theme = recap.build_panel_visual_theme(panel, archetype_hint="explorer")
    assert "daily panel" in theme.lower()
    assert "threshold" in theme.lower() or "liminal" in theme.lower()
    assert "golden threshold" in theme.lower() or "panel art direction" in theme.lower()


def test_build_motion_prompt_uses_panel_visual_lock():
    panel = {
        "panel_type": "journey",
        "panel_tone": "reflective",
        "prompt_used": "journey panel watercolor dusk",
    }
    theme = recap.build_panel_visual_theme(panel, archetype_hint="explorer")
    prompt = recap.build_motion_prompt(
        archetype_hint="explorer",
        narrative="Forest clearing",
        biome="whisperwood",
        transcript_excerpt="I found courage",
        chat_snippets=[],
        panel=panel,
        visual_theme=theme,
    )
    assert "VISUAL LOCK" in prompt
    assert "journey panel" in prompt.lower() or "panel art direction" in prompt.lower()


def test_plan_trailer_segment_durations_short_video():
    target, segs = recap.plan_trailer_segment_durations(45.0)
    assert target == 45
    assert segs == [10, 10, 10, 10, 5]


def test_plan_trailer_segment_durations_rounds_1_to_4_seconds():
    target, segs = recap.plan_trailer_segment_durations(54.0)
    assert target == 50
    assert segs == [10, 10, 10, 10, 10]
    target91, segs91 = recap.plan_trailer_segment_durations(91.0)
    assert target91 == 90
    assert segs91 == [30, 30, 30]


def test_plan_trailer_segment_durations_tail_clip():
    target, segs = recap.plan_trailer_segment_durations(95.0)
    assert target == 95
    assert segs == [30, 30, 30, 5]


def test_plan_trailer_segment_durations_caps_at_two_minutes():
    target, segs = recap.plan_trailer_segment_durations(1800.0)
    assert target == 120
    assert segs == [30, 30, 30, 30]


def test_estimate_duration_from_transcript_scales():
    short = recap.estimate_duration_from_transcript("hello world " * 10)
    long = recap.estimate_duration_from_transcript("word " * 1500)
    assert short >= recap.DEFAULT_TARGET_DURATION
    assert long > short
    assert long <= 7200.0


def test_split_text_chunks_respects_max():
    text = ". ".join([f"Sentence number {i} is here" for i in range(80)])
    chunks = recap._split_text_chunks(text, 200)
    assert len(chunks) >= 2
    assert all(len(c) <= 280 for c in chunks)  # soft bound with leftover sentence


def test_compress_transcript_passthrough_short():
    import asyncio

    short = "I was anxious. Nate mirrored me. I chose courage."
    out = asyncio.run(
        recap.compress_transcript_for_trailer(short, source_duration_seconds=90.0),
    )
    assert out == short


def test_plan_segments_for_duration_delegates_to_trailer():
    target, count = recap.plan_segments_for_duration(92.0)
    assert target == 90
    assert count == 3


def test_heuristic_story_beat_alignments_no_panels():
    transcript = (
        "I walked into the forest feeling lost. Nate helped me see the pattern. "
        "My archetype stepped forward with courage. I left knowing I belong."
    )
    beats = recap.heuristic_story_beat_alignments(
        transcript, segment_count=4, archetype_hint="explorer",
    )
    assert len(beats) == 4
    assert all(b.get("panel_type") == "story_beat" for b in beats)
    assert all(b.get("panel_id") is None for b in beats)
    assert all(b.get("ingest_mode") == "audio_driven" for b in beats)
    assert beats[0]["transcript_excerpt"]


def test_build_motion_prompt_story_beat_skips_visual_lock():
    panel = {"panel_type": "story_beat", "panel_visual_theme": "explorer style"}
    prompt = recap.build_motion_prompt(
        archetype_hint="explorer",
        narrative="Forest clearing at dawn",
        biome="whisperwood",
        transcript_excerpt="I found courage",
        chat_snippets=[],
        panel=panel,
        visual_theme="audio-driven story beat",
    )
    assert "VISUAL LOCK" not in prompt
    assert "generated story illustration" in prompt.lower()


def test_normalize_ingest_mode():
    assert recap.normalize_ingest_mode("audio_driven") == recap.INGEST_MODE_AUDIO
    assert recap.normalize_ingest_mode("panel_aligned") == recap.INGEST_MODE_PANEL
    assert recap.normalize_ingest_mode("panels") == recap.INGEST_MODE_PANEL
    assert recap.normalize_ingest_mode(None) == recap.INGEST_MODE_AUDIO


def test_usable_clip_count():
    assert recap._usable_clip_count([]) == 0
    assert recap._usable_clip_count([{"segment_index": 0, "video_url": "http://x/a.mp4"}]) == 1
    assert recap._usable_clip_count([{"segment_index": 0, "status": "failed"}]) == 0


def test_build_motion_prompt_includes_archetype_and_chat():
    prompt = recap.build_motion_prompt(
        archetype_hint="Luminous Guardian",
        narrative="Forest clearing",
        biome="whisperwood",
        transcript_excerpt="I found courage",
        chat_snippets=["What does courage feel like in your body?"],
    )
    assert "Luminous Guardian" in prompt
    assert "whisperwood" in prompt.lower()
    assert "courage" in prompt.lower()


def test_score_panel_for_excerpt():
    panel = {"narrative_text": "The forest path and morning light"}
    assert recap.score_panel_for_excerpt(panel, "I walked the forest at morning") > 0.2
    assert recap.score_panel_for_excerpt(panel, "xyz qqq") == 0.0


def test_build_studio_result_from_job_pending_returns_none():
    row = {
        "job_id": "00000000-0000-0000-0000-000000000001",
        "status": "pending",
        "transcript_text": "(processing upload…)",
        "panel_alignments": [],
    }
    assert recap.build_studio_result_from_job(row) is None


def test_build_studio_result_from_job_aligning_returns_scenes():
    row = {
        "job_id": "00000000-0000-0000-0000-000000000002",
        "user_id": "CLIENT_TEST",
        "status": "aligning",
        "transcript_text": "I felt lost in the dark forest but found my courage.",
        "target_duration_seconds": 45,
        "segment_count": 3,
        "archetype_hint": "explorer",
        "audio_r2_url": "https://example.com/audio.wav",
        "panel_alignments": [
            {
                "segment_index": 0,
                "panel_type": "story_beat",
                "narrative_text": "Lost in the forest",
                "transcript_excerpt": "felt lost",
                "ingest_mode": "audio_driven",
                "r2_url": "https://example.com/beat0.png",
            }
        ],
        "chat_captures": [{"segment_index": 0, "panel_id": None, "messages": []}],
    }
    result = recap.build_studio_result_from_job(row)
    assert result is not None
    assert result["ingest_mode"] == "audio_driven"
    assert len(result["scenes"]) == 1
    assert result["scenes"][0]["image_url"]
