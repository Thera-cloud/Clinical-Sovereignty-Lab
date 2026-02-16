"""
Tests for TrailEmitter and trail flag encoding.
"""

import pytest

from app.models.quakete import QuaketeMode
from app.services.quakete.trail_emission import TrailEmitter, encode_trail_flag
from app.services.quakete.constants import TRAIL_FLAG_MASK


def test_trail_emitter_increments_sequence():
    """Emit twice, check sequence increments (1 then 2)."""
    emitter = TrailEmitter(
        fibre_id="fibre-a",
        fibre_type="cultural_sentinel",
        swarm_secret=b"secret",
    )
    t1 = emitter.emit(
        ble_density=10.0,
        throughput=1.0,
        queue_depth=0,
        time_since_delivery=0,
        quakete_mode=QuaketeMode.NOMINAL,
        surplus=0.0,
        deficit=0.0,
        resonance=0.5,
    )
    t2 = emitter.emit(
        ble_density=10.0,
        throughput=1.0,
        queue_depth=0,
        time_since_delivery=0,
        quakete_mode=QuaketeMode.NOMINAL,
        surplus=0.0,
        deficit=0.0,
        resonance=0.5,
    )
    assert t1.trail_sequence == 1
    assert t2.trail_sequence == 2


def test_trail_communication_health_calculation():
    """With known density and throughput, verify communication_health."""
    emitter = TrailEmitter(
        fibre_id="fibre-b",
        fibre_type="coach_support",
        swarm_secret=b"secret",
    )
    # health = min(1.0, throughput / max(ble_density * 0.01, 0.001))
    # ble_density=100 -> denom=max(1,0.001)=1; throughput=0.5 -> health=0.5
    trail = emitter.emit(
        ble_density=100.0,
        throughput=0.5,
        queue_depth=2,
        time_since_delivery=30,
        quakete_mode=QuaketeMode.NOMINAL,
        surplus=0.0,
        deficit=0.0,
        resonance=0.6,
    )
    assert trail.communication_health == 0.5
    assert trail.ambient_ble_density == 100.0
    assert trail.fragment_throughput == 0.5


def test_encode_trail_flag():
    """Verify TRAIL_FLAG_MASK bit is set on fragment flags."""
    flags = 0x00
    result = encode_trail_flag(flags)
    assert (result & TRAIL_FLAG_MASK) == TRAIL_FLAG_MASK
    assert result == 0b10000000

    # With other bits set, TRAIL_FLAG_MASK remains set
    flags = 0b00110011
    result = encode_trail_flag(flags)
    assert (result & TRAIL_FLAG_MASK) == TRAIL_FLAG_MASK
    assert result == 0b10110011
