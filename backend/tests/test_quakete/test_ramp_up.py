"""
Tests for QuaketeRampUp.
"""

import pytest

from app.models.quakete import FibreTrailEmission, QuaketeMode
from app.services.quakete.ramp_up import QuaketeRampUp


@pytest.fixture
def ramp_up(trail_map, ion_pool):
    return QuaketeRampUp(trail_map=trail_map, ion_pool=ion_pool)


def test_should_ramp_up_critical(ramp_up, trail_map):
    """Fibre at 0.1 health and CRITICAL mode → True."""
    trail_map.update(FibreTrailEmission(
        fibre_id="critical-fibre",
        fibre_type="x",
        trail_sequence=1,
        communication_health=0.1,
        quakete_mode=QuaketeMode.CRITICAL,
    ))
    assert ramp_up.should_ramp_up("critical-fibre") is True


def test_should_ramp_up_healthy(ramp_up, trail_map):
    """Fibre at 0.8 health → False."""
    trail_map.update(FibreTrailEmission(
        fibre_id="healthy-fibre",
        fibre_type="x",
        trail_sequence=1,
        communication_health=0.8,
        quakete_mode=QuaketeMode.NOMINAL,
    ))
    assert ramp_up.should_ramp_up("healthy-fibre") is False


def test_prioritize_by_therapeutic_value(ramp_up):
    """Verify sorting by therapeutic value descending."""
    obs_ids = ["obs-a", "obs-b", "obs-c"]
    therapeutic_values = {
        "obs-a": 0.3,
        "obs-b": 0.9,
        "obs-c": 0.5,
    }
    result = ramp_up.prioritize_observations(obs_ids, therapeutic_values)
    assert result == ["obs-b", "obs-c", "obs-a"]
