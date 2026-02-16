"""
Tests for ParticleBeamGenerator.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models.quakete import ParticleBeam
from app.services.quakete.particle_beam import ParticleBeamGenerator
from app.services.quakete.constants import PARTICLE_BEAM_HALF_LIFE_SECONDS


@pytest.fixture
def particle_beam_generator(lorentz):
    return ParticleBeamGenerator(lorentz)


def test_create_and_get_beam(particle_beam_generator):
    """Create beam, verify exists."""
    beam = particle_beam_generator.create_beam(
        target_fibre_id="fibre-x",
        energy=2.0,
        endpoints=["ep1", "ep2"],
    )
    assert beam is not None
    assert beam.target_fibre_id == "fibre-x"
    assert beam.initial_energy == 2.0
    assert beam.current_energy == 2.0

    retrieved = particle_beam_generator.get_beam("fibre-x")
    assert retrieved is beam


def test_beam_energy_decay(particle_beam_generator):
    """Create beam, advance time, verify energy decreased."""
    beam = particle_beam_generator.create_beam(
        target_fibre_id="fibre-decay",
        energy=2.0,
    )
    half_life = PARTICLE_BEAM_HALF_LIFE_SECONDS

    with patch("app.services.quakete.particle_beam.datetime") as mock_dt:
        mock_dt.utcnow.return_value = beam.created_at + timedelta(seconds=half_life)
        remaining = particle_beam_generator.update_beam_energy("fibre-decay")

    assert remaining is not None
    assert remaining < 2.0
    assert remaining == pytest.approx(1.0, rel=0.01)  # One half-life: 50% remaining


def test_beam_expiration(particle_beam_generator):
    """After 5 half-lives, beam is purged."""
    beam = particle_beam_generator.create_beam(
        target_fibre_id="fibre-expire",
        energy=1.0,
    )
    assert particle_beam_generator.get_beam("fibre-expire") is not None

    with patch("app.services.quakete.particle_beam.datetime") as mock_dt:
        mock_dt.utcnow.return_value = beam.created_at + timedelta(
            seconds=PARTICLE_BEAM_HALF_LIFE_SECONDS * 5 + 1
        )

        remaining = particle_beam_generator.update_beam_energy("fibre-expire")
        assert remaining is None

        assert particle_beam_generator.get_beam("fibre-expire") is None
