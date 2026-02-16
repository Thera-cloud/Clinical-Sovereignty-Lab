"""
Tests for QuaketeTransferService.
"""

import pytest

from app.models.quakete import FibreTrailEmission, QuaketeMode
from app.services.quakete.transfer_service import QuaketeTransferService
from app.services.quakete.reconnection import MagneticReconnectionEngine


@pytest.fixture
def transfer_service(
    ring_manager,
    trail_map,
    resonance_engine,
    wave_particle,
    lorentz,
    ion_pool,
):
    reconnection_engine = MagneticReconnectionEngine(resonance_engine)
    return QuaketeTransferService(
        ring_manager=ring_manager,
        trail_map=trail_map,
        resonance_engine=resonance_engine,
        reconnection_engine=reconnection_engine,
        wave_particle=wave_particle,
        lorentz=lorentz,
        ion_pool=ion_pool,
        particle_beam_generator=None,
    )


@pytest.mark.asyncio
async def test_successful_transfer(transfer_service, ring_manager, trail_map):
    """Set up ring with one REQUESTING fibre, execute transfer."""
    ring = ring_manager.create_ring(
        cord1_id="recipient",
        cord1_type="a",
        cord2_id="donor1",
        cord2_type="b",
        cord3_id="donor2",
        cord3_type="c",
    )

    trail_map.update(FibreTrailEmission(
        fibre_id="recipient",
        fibre_type="a",
        trail_sequence=1,
        deficit_capacity=0.5,
        surplus_capacity=0.0,
        communication_health=0.1,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.REQUESTING,
        ring_id=ring.ring_id,
        ring_partners=["donor1", "donor2"],
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="donor1",
        fibre_type="b",
        trail_sequence=1,
        surplus_capacity=1.0,
        deficit_capacity=0.0,
        communication_health=0.9,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.SURPLUS,
        ring_id=ring.ring_id,
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="donor2",
        fibre_type="c",
        trail_sequence=1,
        surplus_capacity=0.5,
        deficit_capacity=0.0,
        communication_health=0.9,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.SURPLUS,
        ring_id=ring.ring_id,
    ))

    result = await transfer_service.execute_transfer("recipient")
    assert result.success is True
    assert result.ions_transferred > 0
    assert result.total_energy > 0
    assert result.acceleration is not None


@pytest.mark.asyncio
async def test_no_ring_fails(transfer_service, trail_map):
    """Fibre with no ring returns failure."""
    trail_map.update(FibreTrailEmission(
        fibre_id="orphan",
        fibre_type="x",
        trail_sequence=1,
        deficit_capacity=1.0,
        surplus_capacity=0.0,
        communication_health=0.1,
        quakete_mode=QuaketeMode.REQUESTING,
    ))

    result = await transfer_service.execute_transfer("orphan")
    assert result.success is False
    assert "ring" in result.reason.lower()


@pytest.mark.asyncio
async def test_no_surplus_partial(transfer_service, ring_manager, trail_map):
    """Ring partners have no surplus."""
    ring = ring_manager.create_ring(
        cord1_id="recipient",
        cord1_type="a",
        cord2_id="donor1",
        cord2_type="b",
        cord3_id="donor2",
        cord3_type="c",
    )

    trail_map.update(FibreTrailEmission(
        fibre_id="recipient",
        fibre_type="a",
        trail_sequence=1,
        deficit_capacity=1.0,
        surplus_capacity=0.0,
        communication_health=0.1,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.REQUESTING,
        ring_id=ring.ring_id,
        ring_partners=["donor1", "donor2"],
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="donor1",
        fibre_type="b",
        trail_sequence=1,
        surplus_capacity=0.0,
        deficit_capacity=0.0,
        communication_health=0.9,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.NOMINAL,
        ring_id=ring.ring_id,
    ))
    trail_map.update(FibreTrailEmission(
        fibre_id="donor2",
        fibre_type="c",
        trail_sequence=1,
        surplus_capacity=0.0,
        deficit_capacity=0.0,
        communication_health=0.9,
        resonance_frequency=0.5,
        quakete_mode=QuaketeMode.NOMINAL,
        ring_id=ring.ring_id,
    ))

    result = await transfer_service.execute_transfer("recipient")
    assert result.success is False
    assert "surplus" in result.reason.lower()
