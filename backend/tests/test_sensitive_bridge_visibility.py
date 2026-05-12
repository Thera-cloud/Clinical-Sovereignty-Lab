"""Unit tests for Sensitive Clinical Bridge View Brief visibility states."""

from app.services.sensitive_bridge_visibility import derive_button_state


def test_derive_button_state_three_way_contract():
    assert derive_button_state(False, False) == "hidden"
    assert derive_button_state(False, True) == "hidden"
    assert derive_button_state(True, False) == "enroll_available"
    assert derive_button_state(True, True) == "active"
