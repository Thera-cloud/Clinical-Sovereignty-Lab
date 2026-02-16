"""
Tests for MagneticReconnectionEngine.
"""

import pytest

from app.services.quakete.reconnection import MagneticReconnectionEngine
from app.services.quakete.resonance import QuaketeResonanceEngine


@pytest.fixture
def reconnection_engine(resonance_engine):
    return MagneticReconnectionEngine(resonance_engine)


def test_reconnection_plan_covers_deficit(reconnection_engine):
    """Three donors with surplus, deficit is covered."""
    donors = [
        {"fibre_id": "d1", "surplus": 5.0, "resonance_frequency": 0.5},
        {"fibre_id": "d2", "surplus": 3.0, "resonance_frequency": 0.5},
        {"fibre_id": "d3", "surplus": 2.0, "resonance_frequency": 0.5},
    ]
    plan = reconnection_engine.compute_reconnection_plan(
        recipient_id="recipient",
        recipient_deficit=6.0,
        donors=donors,
        recipient_resonance_frequency=0.5,
    )
    assert plan.deficit_covered is True
    assert plan.total_transfer >= 6.0
    assert len(plan.allocations) >= 1


def test_reconnection_plan_partial(reconnection_engine):
    """Insufficient donors, deficit_covered=False."""
    donors = [
        {"fibre_id": "d1", "surplus": 1.0, "resonance_frequency": 0.5},
    ]
    plan = reconnection_engine.compute_reconnection_plan(
        recipient_id="recipient",
        recipient_deficit=10.0,
        donors=donors,
        recipient_resonance_frequency=0.5,
    )
    assert plan.deficit_covered is False
    assert plan.total_transfer == 1.0
    assert plan.recipient_id == "recipient"


def test_recovery_time_estimate(reconnection_engine):
    """Verify recovery time formula."""
    from app.models.quakete import ReconnectionPlan, QuaketeAllocation

    plan = ReconnectionPlan(
        recipient_id="r",
        allocations=[
            QuaketeAllocation(donor_id="d1", recipient_id="r", capacity_transfer=5.0, resonance=1.0),
        ],
        total_transfer=5.0,
        deficit_covered=True,
    )
    # recovery_time = (deficit / total_transfer) * 60, capped at 600
    # deficit=10, total=5 -> 10/5*60 = 120
    result = reconnection_engine.estimate_recovery_time(plan, recipient_deficit=10.0)
    expected = (10.0 / 5.0) * 60.0
    assert result == min(expected, 600.0)
    assert result == 120.0
