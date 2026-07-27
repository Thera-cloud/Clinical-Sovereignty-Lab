"""Offline unit tests for coach Nate check-in (no DB/Redis/Twilio).

Loads the service module by file path to avoid app.services.__init__
pulling nevedal_engine/numpy (macOS Accelerate SIGFPE).
"""

from pathlib import Path
import importlib.util

_ROOT = Path(__file__).resolve().parents[1]
_SVC = _ROOT / "app" / "services" / "coach_nate_checkin_service.py"
_spec = importlib.util.spec_from_file_location("coach_nate_checkin_service", _SVC)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)

normalize_e164 = _mod.normalize_e164
build_coach_checkin_prompt = _mod.build_coach_checkin_prompt
twiml_connect_stream = _mod.twiml_connect_stream


def test_normalize_e164_ten_digit():
    assert normalize_e164("(586) 524-3969") == "+15865243969"


def test_normalize_e164_already_e164():
    assert normalize_e164("+15865243969") == "+15865243969"


def test_normalize_e164_empty():
    assert normalize_e164("") == ""


def test_cold_prompt_locks_phi():
    prompt = build_coach_checkin_prompt(
        client_name="Jane Doe",
        coach_name="CoachN",
        opening_line="Hey Jane, it's Little Nate.",
        confidential_unlocked=False,
        verified=False,
        is_callback=False,
    )
    assert "LOCKED" in prompt
    assert "Do NOT discuss clinical history" in prompt
    assert "Hey Jane, it's Little Nate." in prompt


def test_unlocked_prompt_marks_unlocked():
    prompt = build_coach_checkin_prompt(
        client_name="Jane",
        coach_name="CoachN",
        opening_line="",
        confidential_unlocked=True,
        verified=True,
        is_callback=True,
    )
    assert "UNLOCKED" in prompt
    assert "CALLBACK" in prompt


def test_twiml_machine_says_and_hangs_up():
    xml = twiml_connect_stream("cid", 42, answered_by="machine_start")
    assert "<Say" in xml
    assert "<Hangup" in xml
    assert "Stream" not in xml


def test_twiml_human_connects_stream_with_task():
    xml = twiml_connect_stream("abc-uuid", 99, answered_by="human")
    assert 'name="call_id" value="abc-uuid"' in xml
    assert 'name="coach_checkin_task_id" value="99"' in xml
    assert "<Stream" in xml
