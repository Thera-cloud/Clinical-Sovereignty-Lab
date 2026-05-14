"""Unit tests for FamilySanctuaryEngine.all_members_joined (Track 1 global fix)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.websocket.sanctuary_engine import FamilySanctuaryEngine


@pytest.fixture
def engine(tmp_path: Path) -> FamilySanctuaryEngine:
    (tmp_path / "family_sanctuaries.json").write_text(
        '{"active_sanctuaries": {}, "completed_sanctuaries": {}}',
        encoding="utf-8",
    )
    return FamilySanctuaryEngine(
        tmp_path, MagicMock(), MagicMock(), MagicMock(), None
    )


def _put(
    engine: FamilySanctuaryEngine,
    sid: str,
    *,
    members: list,
    invited: list,
    hoh: str,
    created_by: str | None = None,
) -> None:
    engine.data["active_sanctuaries"][sid] = {
        "sanctuary_id": sid,
        "members": members,
        "invited_member_ids": invited,
        "head_of_household_id": hoh,
        "created_by": created_by or hoh,
    }


def test_creator_and_one_invited_true_when_both_consented(engine: FamilySanctuaryEngine) -> None:
    sid = "S_TEST_1"
    _put(
        engine,
        sid,
        members=[
            {"user_id": "HOH", "name": "Head", "member_consent_agreed": True},
            {"user_id": "M1", "name": "Member", "member_consent_agreed": True},
        ],
        invited=["M1"],
        hoh="HOH",
    )
    assert engine.all_members_joined(sid) is True


def test_three_invited_false_until_all_consent(engine: FamilySanctuaryEngine) -> None:
    sid = "S_TEST_2"
    _put(
        engine,
        sid,
        members=[
            {"user_id": "HOH", "name": "Head", "member_consent_agreed": True},
            {"user_id": "A", "name": "A", "member_consent_agreed": True},
            {"user_id": "B", "name": "B", "member_consent_agreed": False},
            {"user_id": "C", "name": "C", "member_consent_agreed": False},
        ],
        invited=["A", "B", "C"],
        hoh="HOH",
    )
    assert engine.all_members_joined(sid) is False
    # All three invited + HoH consented
    s = engine.data["active_sanctuaries"][sid]
    for m in s["members"]:
        if m["user_id"] in ("A", "B", "C"):
            m["member_consent_agreed"] = True
    assert engine.all_members_joined(sid) is True


def test_creator_only_no_invited_true_after_hoh_consents(engine: FamilySanctuaryEngine) -> None:
    sid = "S_TEST_3"
    _put(
        engine,
        sid,
        members=[
            {"user_id": "ONLY", "name": "Solo", "member_consent_agreed": True},
        ],
        invited=[],
        hoh="ONLY",
    )
    assert engine.all_members_joined(sid) is True


def test_empty_members_false(engine: FamilySanctuaryEngine) -> None:
    sid = "S_TEST_4"
    engine.data["active_sanctuaries"][sid] = {
        "members": [],
        "invited_member_ids": [],
        "head_of_household_id": "X",
        "created_by": "X",
    }
    assert engine.all_members_joined(sid) is False


def test_regression_creator_consented_old_equality_would_fail(engine: FamilySanctuaryEngine) -> None:
    """HoH consented, no other family on invite list → must be able to start."""
    sid = "S_TEST_5"
    _put(
        engine,
        sid,
        members=[
            {"user_id": "CREATOR", "name": "C", "member_consent_agreed": True},
        ],
        invited=[],
        hoh="CREATOR",
        created_by="CREATOR",
    )
    assert engine.all_members_joined(sid) is True


def test_invited_all_consent_but_hoh_not_false(engine: FamilySanctuaryEngine) -> None:
    sid = "S_TEST_6"
    _put(
        engine,
        sid,
        members=[
            {"user_id": "HOH", "name": "Head", "member_consent_agreed": False},
            {"user_id": "M1", "name": "M", "member_consent_agreed": True},
        ],
        invited=["M1"],
        hoh="HOH",
    )
    assert engine.all_members_joined(sid) is False


def test_unknown_sanctuary_false(engine: FamilySanctuaryEngine) -> None:
    assert engine.all_members_joined("NO_SUCH") is False
