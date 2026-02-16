"""
Tests for CosmicRingManager.
"""

import pytest
from datetime import datetime

from app.models.quakete import QuaketeMode, RingState
from app.services.quakete.cosmic_ring import CosmicRingManager


def test_create_ring(ring_manager):
    """Create ring with 3 fibres, verify structure."""
    ring = ring_manager.create_ring(
        cord1_id="fibre-1",
        cord1_type="cultural_sentinel",
        cord2_id="fibre-2",
        cord2_type="coach_support",
        cord3_id="fibre-3",
        cord3_type="community",
    )
    assert ring is not None
    assert ring.ring_id
    assert ring.cord_1.fibre_id == "fibre-1"
    assert ring.cord_2.fibre_id == "fibre-2"
    assert ring.cord_3.fibre_id == "fibre-3"
    assert ring.ring_state == RingState.HEALTHY
    assert ring.ring_coherence == 1.0


def test_update_cord_health(ring_manager):
    """Update one cord, verify ring_state changes."""
    ring = ring_manager.create_ring(
        cord1_id="f1", cord1_type="a",
        cord2_id="f2", cord2_type="b",
        cord3_id="f3", cord3_type="c",
    )
    ring_manager.update_cord_health("f1", health=0.2, mode=QuaketeMode.REQUESTING)
    updated = ring_manager.get_ring(ring.ring_id)
    assert updated is not None
    cord = updated.get_cord("f1")
    assert cord.current_health == 0.2
    assert cord.current_mode == QuaketeMode.REQUESTING
    assert updated.ring_state == RingState.SUPPORTING


def test_ring_state_transitions(ring_manager):
    """HEALTHY→SUPPORTING→STRAINED→DISTRESSED→RESCUE."""
    ring = ring_manager.create_ring(
        cord1_id="a", cord1_type="x",
        cord2_id="b", cord2_type="x",
        cord3_id="c", cord3_type="x",
    )
    assert ring_manager.get_ring(ring.ring_id).ring_state == RingState.HEALTHY

    ring_manager.update_cord_health("a", 0.2, QuaketeMode.REQUESTING)
    assert ring_manager.get_ring(ring.ring_id).ring_state == RingState.SUPPORTING

    ring_manager.update_cord_health("b", 0.2, QuaketeMode.REQUESTING)
    assert ring_manager.get_ring(ring.ring_id).ring_state == RingState.STRAINED

    ring_manager.update_cord_health("c", 0.2, QuaketeMode.CRITICAL)
    assert ring_manager.get_ring(ring.ring_id).ring_state == RingState.DISTRESSED

    ring_manager.update_cord_health("a", 0.0, QuaketeMode.SILENT)
    assert ring_manager.get_ring(ring.ring_id).ring_state == RingState.RESCUE


def test_dissolve_ring(ring_manager):
    """Create then dissolve, verify removed."""
    ring = ring_manager.create_ring(
        cord1_id="x", cord1_type="t",
        cord2_id="y", cord2_type="t",
        cord3_id="z", cord3_type="t",
    )
    ring_id = ring.ring_id
    assert ring_manager.get_ring(ring_id) is not None
    assert ring_manager.get_fibre_ring("x") is not None

    dissolved = ring_manager.dissolve_ring(ring_id)
    assert dissolved is not None
    assert dissolved.ring_id == ring_id
    assert ring_manager.get_ring(ring_id) is None
    assert ring_manager.get_fibre_ring("x") is None
