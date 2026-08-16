"""LiveBuildBoundary degrades without a pool. Undeclared contracts raise."""

import pytest

from app.services.disco.boundary import LiveBuildBoundary
from app.services.disco.pipeline import BuildBoundary


def test_undeclared_raises():
    b = LiveBuildBoundary()
    with pytest.raises(KeyError):
        b.get("coaches", None)


def test_missing_contracts_degrade():
    b = LiveBuildBoundary()
    ready = b.readiness()
    assert ready == {c: False for c in BuildBoundary.CONTRACTS}
    r = b.get("credentials", {"class": "coaching"})
    assert r["degraded"] is True
    assert r["value"]["class"] == "coaching"


@pytest.mark.asyncio
async def test_refresh_without_pool():
    b = LiveBuildBoundary(db_pool=None)
    ready = await b.refresh()
    assert ready["authoring"] is False
    creds = await b.credentials_for("CoachN")
    assert creds["degraded"] is True
