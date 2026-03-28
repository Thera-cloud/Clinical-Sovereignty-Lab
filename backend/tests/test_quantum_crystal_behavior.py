from datetime import datetime, timedelta, timezone

from app.services.quantum_crystal_orchestrator import FiveDMemoryCrystal
from app.services.time_crystal_forge import TimeCrystalForge


def test_staleness_factor_is_ranking_only_and_bounded():
    c = FiveDMemoryCrystal(
        id=1,
        content_hash="abc123",
        confidence=0.7,
        created_at=datetime.now(timezone.utc) - timedelta(days=365),
    )
    sf = c.staleness_factor
    assert 0.3 <= sf <= 1.0
    # staleness_factor must not mutate confidence
    assert c.confidence == 0.7


def test_reinforce_is_monotonic_non_decreasing():
    c = FiveDMemoryCrystal(id=1, content_hash="abc123", confidence=0.80)
    before = c.confidence
    c.reinforce()
    assert c.confidence >= before
    c.reinforce(increment=2)
    assert c.confidence >= before
    assert c.confidence <= 0.95


def test_periodicity_detection_confident_when_intervals_regular():
    forge = TimeCrystalForge(db_pool=None)
    base = datetime.now(timezone.utc) - timedelta(days=21)
    timestamps = [
        base,
        base + timedelta(days=7),
        base + timedelta(days=14),
        base + timedelta(days=21),
    ]
    out = forge._detect_periodicity(timestamps)
    assert out is not None
    assert out["period_days"] >= 6.0
    assert out["confidence"] >= 0.60
