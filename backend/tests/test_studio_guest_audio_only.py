"""INV-2 guests audio-only."""

from pathlib import Path

from app.services.studio_invariants import guest_video_allowed

SQL = (Path(__file__).resolve().parents[2] / "backend/migrations/401_studio_sessions.sql").read_text()


def test_check_constraint_in_migration():
    assert "session_legs_guest_audio_only_chk" in SQL
    assert "role <> 'guest' OR video_track_key IS NULL" in SQL


def test_guest_video_rejected():
    assert guest_video_allowed("guest", None) is True
    assert guest_video_allowed("guest", "track") is False
    assert guest_video_allowed("host", "track") is True
    assert guest_video_allowed("cohost_ai", None) is True
