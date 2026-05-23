"""Phase 1 family_linkage — enrich profile stamps and dual-read guardian match."""

import pytest
from unittest.mock import AsyncMock

from app.services.family_linkage import (
    enrich_family_profile,
    enrich_family_profile_if_needed,
    extract_family_columns,
    guardian_ref_matches,
    is_uuid,
)


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    return conn


def test_is_uuid():
    assert is_uuid("342b9152-8764-4dc1-a3a6-610f9744fecc")
    assert not is_uuid("CLIENT_LONGRA_ID")


def test_guardian_ref_matches_hardware_or_uuid():
    uid = "342b9152-8764-4dc1-a3a6-610f9744fecc"
    assert guardian_ref_matches("CLIENT_LONGRA_ID", "CLIENT_LONGRA_ID")
    assert guardian_ref_matches(uid, "CLIENT_LONGRA_ID", member_user_id=uid)
    assert not guardian_ref_matches(uid, "CLIENT_OTHER_ID", member_user_id=uid)


def test_extract_family_columns():
    cols = extract_family_columns(
        {
            "family_role": "DEPENDENT",
            "is_minor": True,
            "guardian_id": "342b9152-8764-4dc1-a3a6-610f9744fecc",
            "linked_by": "342b9152-8764-4dc1-a3a6-610f9744fecc",
        }
    )
    assert cols["guardian_id"] == "342b9152-8764-4dc1-a3a6-610f9744fecc"
    assert cols["family_role"] == "dependent"
    assert cols["is_minor"] is True


@pytest.mark.asyncio
async def test_enrich_from_parent_username(mock_conn):
    parent_id = "342b9152-8764-4dc1-a3a6-610f9744fecc"

    async def _fetchrow(sql, *args):
        if "LOWER(username)" in sql or "hardware_id" in sql:
            return {
                "id": parent_id,
                "username": "longra",
                "hardware_id": "CLIENT_LONGRA_ID",
                "family_id": parent_id,
            }
        return None

    mock_conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    profile = await enrich_family_profile(
        mock_conn,
        profile={"family_role": "DEPENDENT", "is_minor": True},
        parent_username="longra",
    )
    assert profile["parent_username"] == "longra"
    assert profile["guardian_id"] == parent_id
    assert profile["linked_by"] == parent_id


@pytest.mark.asyncio
async def test_enrich_if_needed_skips_complete_profile(mock_conn):
    complete = {
        "parent_username": "longra",
        "guardian_id": "342b9152-8764-4dc1-a3a6-610f9744fecc",
        "linked_by": "342b9152-8764-4dc1-a3a6-610f9744fecc",
        "family_role": "DEPENDENT",
    }
    out = await enrich_family_profile_if_needed(
        mock_conn, complete, "3976f0b5-c7f1-4a27-8fbf-dc0275c210ca"
    )
    assert out == complete
    mock_conn.fetchrow.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_from_hardware_guardian(mock_conn):
    parent_id = "342b9152-8764-4dc1-a3a6-610f9744fecc"

    async def _fetchrow(sql, *args):
        if args and args[0] == "CLIENT_LONGRA_ID":
            return {
                "id": parent_id,
                "username": "longra",
                "hardware_id": "CLIENT_LONGRA_ID",
                "family_id": parent_id,
            }
        return None

    mock_conn.fetchrow = AsyncMock(side_effect=_fetchrow)
    profile = await enrich_family_profile(
        mock_conn,
        profile={
            "family_role": "DEPENDENT",
            "guardian_id": "CLIENT_LONGRA_ID",
            "linked_by": "CLIENT_LONGRA_ID",
        },
        parent_username=None,
    )
    assert profile["parent_username"] == "longra"
    assert profile["guardian_id"] == parent_id
