"""
Tests for RingCirculator.
"""

import pytest

from app.models.quakete import FibreTrailEmission, QuaketeMode, RingState
from app.services.quakete.ring_circulator import RingCirculator


@pytest.mark.asyncio
async def test_circulation_donates_surplus(
    ring_manager,
    trail_map,
    wave_particle,
    ion_pool,
):
    """Set up ring with one SURPLUS cord, one REQUESTING, circulate."""
    ring = ring_manager.create_ring(
        cord1_id="donor",
        cord1_type="a",
        cord2_id="recipient",
        cord2_type="b",
        cord3_id="neutral",
        cord3_type="c",
    )
    ring_manager.update_cord_health("donor", 0.9, QuaketeMode.SURPLUS)
    ring_manager.update_cord_health("recipient", 0.2, QuaketeMode.REQUESTING)
    ring_manager.update_cord_health("neutral", 0.8, QuaketeMode.NOMINAL)

    trail_map.update(FibreTrailEmission(
        fibre_id="donor",
        fibre_type="a",
        trail_sequence=1,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.SURPLUS,
        ring_id=ring.ring_id,
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="recipient",
        fibre_type="b",
        trail_sequence=1,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.REQUESTING,
        ring_id=ring.ring_id,
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="neutral",
        fibre_type="c",
        trail_sequence=1,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.NOMINAL,
        ring_id=ring.ring_id,
    ))

    circulator = RingCirculator(
        ring_manager=ring_manager,
        trail_map=trail_map,
        wave_particle=wave_particle,
        ion_pool=ion_pool,
    )
    result = await circulator.circulate(ring)

    assert result["donations"] >= 1
    assert result["ions_generated"] >= 1
    assert result["total_energy"] > 0
    assert ion_pool.total_ions() >= 1


@pytest.mark.asyncio
async def test_circulation_skips_broken_rings(
    ring_manager,
    trail_map,
    wave_particle,
    ion_pool,
):
    """Broken ring not circulated."""
    ring = ring_manager.create_ring(
        cord1_id="a",
        cord1_type="x",
        cord2_id="b",
        cord2_type="x",
        cord3_id="c",
        cord3_type="x",
    )
    ring.ring_state = RingState.BROKEN

    circulator = RingCirculator(
        ring_manager=ring_manager,
        trail_map=trail_map,
        wave_particle=wave_particle,
        ion_pool=ion_pool,
    )
    result = await circulator.circulate(ring)

    assert result["donations"] == 0
    assert result["ions_generated"] == 0
    assert result["total_energy"] == 0.0
