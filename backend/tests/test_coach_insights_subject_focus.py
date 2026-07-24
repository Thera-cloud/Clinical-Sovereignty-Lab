"""Coach Insights subject focus — override dropdown must not invent a client."""

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "coach_insights_subject.py"
)
_spec = importlib.util.spec_from_file_location("coach_insights_subject", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)
resolve_coach_focus_client_id = _mod.resolve_coach_focus_client_id


def test_message_name_wins_over_context():
    ctx = {
        "client_id": "CLIENT_A_ID",
        "override_active": True,
        "subject_locked": True,
        "client_names": [
            {"name": "Alice Rivera", "id": "CLIENT_A_ID", "username": "alice"},
            {"name": "Bob Chen", "id": "CLIENT_B_ID", "username": "bob"},
        ],
    }
    assert resolve_coach_focus_client_id(ctx, "Tell me about Bob Chen") == "CLIENT_B_ID"


def test_dropdown_context_ignored_without_lock():
    ctx = {
        "client_id": "CLIENT_A_ID",
        "focused_client_id": "CLIENT_A_ID",
        "override_active": False,
        "subject_locked": False,
        "client_names": [
            {"name": "Alice Example", "id": "CLIENT_A_ID", "username": "alice"},
        ],
        "briefing_data": {"client_id": "CLIENT_A_ID"},
    }
    assert resolve_coach_focus_client_id(ctx, "What should I focus on today?") is None


def test_saved_override_locks_subject():
    ctx = {
        "client_id": "CLIENT_A_ID",
        "override_active": True,
        "subject_locked": True,
        "client_names": [
            {"name": "Alice Example", "id": "CLIENT_A_ID", "username": "alice"},
        ],
    }
    assert resolve_coach_focus_client_id(ctx, "How is coherence trending?") == "CLIENT_A_ID"


def test_free_text_subject_does_not_force_roster_id():
    ctx = {
        "override_active": False,
        "subject_locked": True,
        "insights_subject_name": "Jordan Neighbor",
        "mentioned_subjects": ["Jordan Neighbor"],
        "client_names": [
            {"name": "Alice Example", "id": "CLIENT_A_ID", "username": "alice"},
        ],
    }
    assert resolve_coach_focus_client_id(ctx, "Jordan Neighbor had a hard week") is None
