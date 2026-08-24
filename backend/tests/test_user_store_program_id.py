"""users.program_id column is source of truth over profile_data JSONB."""

from app.websocket.user_store import UserStore


def _row(**overrides):
    base = {
        "username": "alice",
        "password_hash": "salt:hash",
        "role": "CLIENT",
        "name": "Alice",
        "email": "alice@example.com",
        "hardware_id": "HW_ALICE",
        "consent_version": "v13.0_2026",
        "subscription_status": "ACTIVE",
        "profile_data": {},
        "resolved_family_code": None,
        "tier": None,
        "phone": None,
        "timezone": None,
        "timezone_source": None,
        "dob": None,
        "specialties": None,
        "coaching_style": None,
        "token_balance": None,
        "subscription_token_balance": None,
        "purchased_token_balance": None,
        "login_count": None,
        "last_login": None,
        "stripe_customer_id": None,
    }
    base.update(overrides)
    return base


def test_column_overlays_program_id():
    store = UserStore(None)
    _, entry = store._row_to_entry(_row(program_id="bee_hiv_plus"))
    assert entry["profile"]["program_id"] == "bee_hiv_plus"


def test_empty_column_clears_stale_jsonb_program_id():
    store = UserStore(None)
    _, entry = store._row_to_entry(
        _row(
            program_id=None,
            profile_data={"program_id": "bee_hiv_plus", "name": "Alice"},
        )
    )
    assert "program_id" not in entry["profile"]


def test_pre414_row_without_column_leaves_jsonb():
    """SELECT without program_id (old schema) must not pop JSONB."""
    store = UserStore(None)
    row = _row(profile_data={"program_id": "bee_hiv_plus"})
    row.pop("program_id", None)
    assert "program_id" not in row
    _, entry = store._row_to_entry(row)
    assert entry["profile"]["program_id"] == "bee_hiv_plus"


def test_non_cohort_column_does_not_invent_program_id():
    store = UserStore(None)
    _, entry = store._row_to_entry(_row(program_id=None, profile_data={}))
    assert "program_id" not in entry["profile"]
