"""
Tests for MemorialService.
"""

import pytest

from app.models.quakete import FibreTrailEmission, Memorial
from app.services.quakete.memorial import MemorialService


@pytest.fixture
def memorial_service(ring_manager):
    return MemorialService(ring_manager)


def test_create_memorial(memorial_service, ring_manager):
    """Create memorial, verify fields."""
    ring_manager.create_ring(
        cord1_id="lost",
        cord1_type="x",
        cord2_id="survivor1",
        cord2_type="y",
        cord3_id="survivor2",
        cord3_type="z",
    )
    memorial = memorial_service.create_memorial(
        lost_fibre_id="lost",
        lost_fibre_type="x",
        last_health=0.0,
        last_mission="final mission",
        pending_observations=3,
        quaketes_received=5,
    )
    assert memorial.lost_fibre_id == "lost"
    assert memorial.lost_fibre_type == "x"
    assert memorial.last_known_health == 0.0
    assert memorial.last_known_mission == "final mission"
    assert memorial.pending_observations == 3
    assert memorial.quaketes_received_before_loss == 5
    assert memorial.memorial_hash is not None


def test_memorials_carried_by(memorial_service, ring_manager):
    """Ring partners appear in carried_by."""
    ring_manager.create_ring(
        cord1_id="lost",
        cord1_type="x",
        cord2_id="survivor1",
        cord2_type="y",
        cord3_id="survivor2",
        cord3_type="z",
    )
    memorial_service.create_memorial(
        lost_fibre_id="lost",
        lost_fibre_type="x",
        last_health=0.0,
    )
    carried = memorial_service.get_memorials_carried_by("survivor1")
    assert len(carried) == 1
    assert carried[0].lost_fibre_id == "lost"
    assert "survivor1" in carried[0].carried_by
    assert "survivor2" in carried[0].carried_by


def test_encode_in_trail(memorial_service, ring_manager):
    """Memorial encoded in trail emission."""
    ring_manager.create_ring(
        cord1_id="lost",
        cord1_type="x",
        cord2_id="survivor1",
        cord2_type="y",
        cord3_id="survivor2",
        cord3_type="z",
    )
    memorial = memorial_service.create_memorial(
        lost_fibre_id="lost",
        lost_fibre_type="x",
        last_health=0.0,
    )
    trail = FibreTrailEmission(
        fibre_id="survivor1",
        fibre_type="y",
        trail_sequence=1,
        observation_queue_depth=0,
    )
    encoded = memorial_service.encode_in_trail(memorial, trail)
    assert encoded.observation_queue_depth != 0
    assert encoded.observation_queue_depth != trail.observation_queue_depth
    # Hash encoded as int (first 8 hex chars)
    assert isinstance(encoded.observation_queue_depth, int)
