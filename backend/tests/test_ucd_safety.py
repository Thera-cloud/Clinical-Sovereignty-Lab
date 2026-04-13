"""Tests for UCD Safety mechanisms: S1 (Intensity Governor), S2 (Modality Safety Matrix),
S3 (Predictive Restraint), and integrated TMC safety gates."""

import pytest
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Minimal DB mocks (reusable pattern from test_sse_engine.py)
# ---------------------------------------------------------------------------

class FakeConn:
    def __init__(self, rows=None, fetchval_map=None, fetch_rows=None):
        self._rows = rows or {}
        self._fetchval_map = fetchval_map or {}
        self._fetch_rows = fetch_rows or {}
        self.executed = []

    async def fetchrow(self, query, *args):
        for key, val in self._rows.items():
            if key in query:
                return val
        return None

    async def fetchval(self, query, *args):
        for key, val in self._fetchval_map.items():
            if key in query:
                return val
        row = await self.fetchrow(query, *args)
        if row and isinstance(row, dict):
            return list(row.values())[0]
        return row

    async def fetch(self, query, *args):
        for key, val in self._fetch_rows.items():
            if key in query:
                return val
        return []

    async def execute(self, query, *args):
        self.executed.append((query, args))


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *a):
        pass


def _pool(rows=None, fetchval_map=None, fetch_rows=None):
    return FakePool(FakeConn(rows, fetchval_map, fetch_rows))


# ---------------------------------------------------------------------------
# S1: Intensity Governor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intensity_governor_records_within_cap():
    from app.sse.ucd.intensity_governor import IntensityGovernor
    pool = _pool(
        fetchval_map={"SUM(intensity_score)": 1.5},
    )
    gov = IntensityGovernor(pool)
    result = await gov.check_and_record("user1", "THRESHOLD", 0.5)
    assert result["capped"] is False
    assert result["recorded_intensity"] == 0.5


@pytest.mark.asyncio
async def test_intensity_governor_caps_at_limit():
    from app.sse.ucd.intensity_governor import IntensityGovernor, DEFAULT_INTENSITY_CAP
    pool = _pool(
        rows={"MAX(intensity_score)": {"peak": DEFAULT_INTENSITY_CAP * 0.95, "overrides": 0}},
    )
    gov = IntensityGovernor(pool)
    result = await gov.check_and_record("user1", "BREAKTHROUGH", 0.95)
    assert result["capped"] is True
    assert result["recorded_intensity"] <= DEFAULT_INTENSITY_CAP


@pytest.mark.asyncio
async def test_intensity_governor_no_db():
    from app.sse.ucd.intensity_governor import IntensityGovernor
    gov = IntensityGovernor(None)
    result = await gov.check_and_record("user1", "THRESHOLD", 0.5)
    assert result["recorded_intensity"] == 0.5
    assert result["capped"] is False


# ---------------------------------------------------------------------------
# S2: Modality Safety Matrix (via ModalitySelector)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_crisis_blocks_video():
    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    result = await sel.select("u1", "CRISIS", "private")
    assert "video" not in result["allowed"]
    assert "composite" not in result["allowed"]


@pytest.mark.asyncio
async def test_institutional_blocks_video():
    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    result = await sel.select("u1", "BREAKTHROUGH", "institutional")
    assert "video" not in result["allowed"]
    assert "composite" not in result["allowed"]


@pytest.mark.asyncio
async def test_additional_blocked_modalities():
    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    result = await sel.select(
        "u1", "THRESHOLD", "private",
        additional_blocked=["audio_narrative"],
    )
    assert "audio_narrative" not in result["allowed"]
    assert any("safety gate" in r for r in result["blocked_reasons"])


@pytest.mark.asyncio
async def test_all_blocked_falls_back_to_text():
    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    result = await sel.select(
        "u1", "REST", "private",
        additional_blocked=["panel", "text_reflection", "guided_meditation"],
    )
    assert result["selected_modality"] == "text_reflection"


# ---------------------------------------------------------------------------
# S3: Predictive Restraint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_predictive_restraint_masked_blocks():
    from app.sse.ucd.predictive_restraint import evaluate_safety
    pool = _pool(rows={
        "sse_identity_forge": {"mask_detection_state": {"active": True}},
    })
    gate = await evaluate_safety("user1", pool, "private")
    assert gate["blocked"] is True
    assert gate["masked"] is True
    assert "MASKED" in gate["reason"]


@pytest.mark.asyncio
async def test_predictive_restraint_surveillance_restricts():
    from app.sse.ucd.predictive_restraint import evaluate_safety
    pool = _pool(rows={
        "sse_identity_forge": {"mask_detection_state": None},
    })
    gate = await evaluate_safety("user1", pool, "institutional")
    assert gate["surveillance"] is True
    assert "narration" in gate["modality_restrictions"]
    assert "video_clip" in gate["modality_restrictions"]


@pytest.mark.asyncio
async def test_predictive_restraint_escalation_blocks():
    from app.sse.ucd.predictive_restraint import evaluate_safety

    now = datetime.now(timezone.utc)
    velocity_rows = [
        {"intensity_score": 0.2, "created_at": now - timedelta(minutes=30)},
        {"intensity_score": 0.7, "created_at": now},
    ]
    pool = _pool(
        rows={"sse_identity_forge": {"mask_detection_state": None}},
        fetch_rows={"intensity_ledger": velocity_rows},
    )
    gate = await evaluate_safety("user1", pool)
    assert gate["blocked"] is True
    assert gate["escalation_velocity"] >= 0.3


@pytest.mark.asyncio
async def test_predictive_restraint_clean_passes():
    from app.sse.ucd.predictive_restraint import evaluate_safety
    pool = _pool(rows={
        "sse_identity_forge": {"mask_detection_state": None},
    })
    gate = await evaluate_safety("user1", pool, "private")
    assert gate["blocked"] is False
    assert gate["masked"] is False


@pytest.mark.asyncio
async def test_predictive_restraint_no_db():
    from app.sse.ucd.predictive_restraint import evaluate_safety
    gate = await evaluate_safety("user1", None)
    assert gate["blocked"] is False


# ---------------------------------------------------------------------------
# Integrated: TMC safety gates include S3
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tmc_safety_integrates_predictive_restraint():
    """TMC classify should call predictive restraint and block on masked user."""
    from app.sse.ucd.tmc import TherapeuticMomentClassifier
    pool = _pool(
        rows={
            "sse_identity_forge": {
                "mask_detection_state": {"active": True},
                "deployment_context": "private",
            },
        },
    )
    tmc = TherapeuticMomentClassifier(pool)
    result = await tmc.classify("user_masked")
    assert result["moment_class"] == "REST"
    gate = result["safety_gate"]
    assert gate["blocked"] is True
    pr = gate.get("predictive_restraint", {})
    assert pr.get("masked") is True


# ---------------------------------------------------------------------------
# Engagement ranking in ModalitySelector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engagement_ranking_prefers_discussed():
    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    history = [
        {"modality": "panel", "engagement_action": "discussed"},
        {"modality": "panel", "engagement_action": "discussed"},
        {"modality": "text_reflection", "engagement_action": "skipped"},
        {"modality": "audio_narrative", "engagement_action": "viewed"},
    ]
    result = await sel.select("u1", "THRESHOLD", "private", engagement_history=history)
    assert result["selected_modality"] == "panel"


# ---------------------------------------------------------------------------
# Scenario Coverage (plan-required)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_masked_user_breakthrough_blocked():
    """MASKED user receiving BREAKTHROUGH classification must be blocked to REST."""
    from app.sse.ucd.tmc import TherapeuticMomentClassifier

    pool = _pool(
        rows={
            "nate_intelligence_crystals": {"confidence": 0.9, "domain": "clinical"},
            "cycle_detections": {"is_first_break": True, "detected_at": datetime.now(timezone.utc)},
            "sse_identity_forge": {
                "mask_detection_state": "MASKED",
                "deployment_context": "private",
            },
        },
        fetchval_map={
            "conversation_history": datetime.now(timezone.utc),
            "heritage_correlation_index": 0.0,
        },
    )
    tmc = TherapeuticMomentClassifier(pool)
    result = await tmc.classify("masked_user")
    assert result["moment_class"] in ("REST", "THRESHOLD"), \
        f"MASKED user should not get BREAKTHROUGH, got {result['moment_class']}"
    assert result["safety_gate"]["blocked"] is True


@pytest.mark.asyncio
async def test_breakthrough_48h_cooldown():
    """Only one BREAKTHROUGH per 48h — second attempt within window falls to THRESHOLD."""
    from app.sse.ucd.tmc import TherapeuticMomentClassifier, _BREAKTHROUGH_COOLDOWN_HOURS

    recent_breakthrough = datetime.now(timezone.utc) - timedelta(hours=24)
    pool = _pool(
        rows={
            "sse_identity_forge": {
                "mask_detection_state": None,
                "deployment_context": "private",
            },
        },
        fetchval_map={
            "intensity_ledger": recent_breakthrough,
            "heritage_correlation_index": 0.0,
            "conversation_history": datetime.now(timezone.utc),
        },
    )
    tmc = TherapeuticMomentClassifier(pool)
    result = await tmc.classify("user_recent_bt")
    gate = result["safety_gate"]
    assert gate.get("breakthrough_cooldown_active") is True
    assert gate["blocked"] is True
    assert gate.get("hours_remaining", 0) > 0


@pytest.mark.asyncio
async def test_breakthrough_cooldown_timezone_edge():
    """Breakthrough exactly at 48h boundary should NOT be blocked."""
    from app.sse.ucd.tmc import TherapeuticMomentClassifier, _BREAKTHROUGH_COOLDOWN_HOURS

    exactly_expired = datetime.now(timezone.utc) - timedelta(hours=_BREAKTHROUGH_COOLDOWN_HOURS + 0.1)
    pool = _pool(
        rows={
            "sse_identity_forge": {
                "mask_detection_state": None,
                "deployment_context": "private",
            },
        },
        fetchval_map={
            "intensity_ledger": exactly_expired,
            "heritage_correlation_index": 0.0,
            "conversation_history": datetime.now(timezone.utc),
        },
    )
    tmc = TherapeuticMomentClassifier(pool)
    result = await tmc.classify("user_bt_expired")
    gate = result["safety_gate"]
    assert gate.get("breakthrough_cooldown_active") is not True, \
        "Cooldown should not be active after 48h has elapsed"


@pytest.mark.asyncio
async def test_crisis_never_produces_video():
    """CRISIS moment must never have video or composite as allowed modalities."""
    from app.sse.ucd.modality_selector import ModalitySelector, ALLOWED_MODALITIES, FORBIDDEN_PAIRS

    assert "video" not in ALLOWED_MODALITIES.get("CRISIS", []), \
        "video must not be in CRISIS allowed modalities"
    assert ("CRISIS", "video") in FORBIDDEN_PAIRS
    assert ("CRISIS", "composite") in FORBIDDEN_PAIRS
    assert ("CRISIS", "panel") in FORBIDDEN_PAIRS

    sel = ModalitySelector(None)
    for ctx in ("private", "institutional", "court_ordered"):
        result = await sel.select("u1", "CRISIS", ctx)
        assert result["selected_modality"] not in ("video", "composite", "panel"), \
            f"CRISIS in {ctx} should not select {result['selected_modality']}"


@pytest.mark.asyncio
async def test_heritage_without_clinician_blocked():
    """HERITAGE content requires clinician approval; without it, falls to INTEGRATION."""
    from app.sse.ucd.tmc import TherapeuticMomentClassifier

    pool = _pool(
        rows={
            "sse_identity_forge": {
                "mask_detection_state": None,
                "deployment_context": "private",
            },
        },
        fetchval_map={
            "heritage_correlation_index": 0.5,
            "intensity_ledger": None,
            "conversation_history": datetime.now(timezone.utc),
        },
    )
    tmc = TherapeuticMomentClassifier(pool)
    result = await tmc.classify("heritage_user")
    gate = result["safety_gate"]
    assert gate.get("heritage_requires_clinician") is True
    assert gate["blocked"] is True
    assert gate.get("fallback_class") == "INTEGRATION"


@pytest.mark.asyncio
async def test_predictive_restraint_blocks_breakthrough_imagery_until_crystal():
    """S3 should block when escalation velocity is high (no stable crystal yet)."""
    from app.sse.ucd.predictive_restraint import evaluate_safety

    now = datetime.now(timezone.utc)
    velocity_rows = [
        {"intensity_score": 0.1, "created_at": now - timedelta(minutes=90)},
        {"intensity_score": 0.3, "created_at": now - timedelta(minutes=60)},
        {"intensity_score": 0.6, "created_at": now - timedelta(minutes=30)},
        {"intensity_score": 0.8, "created_at": now},
    ]
    pool = _pool(
        rows={"sse_identity_forge": {"mask_detection_state": None}},
        fetch_rows={"intensity_ledger": velocity_rows},
    )
    gate = await evaluate_safety("escalating_user", pool, "private")
    assert gate["blocked"] is True
    assert gate["escalation_velocity"] >= 0.3

    from app.sse.ucd.modality_selector import ModalitySelector
    sel = ModalitySelector(None)
    restrictions = gate.get("modality_restrictions", [])
    result = await sel.select(
        "escalating_user", "THRESHOLD", "private",
        additional_blocked=restrictions,
    )
    assert result["selected_modality"] in ("panel", "text_reflection", "audio_narrative")


@pytest.mark.asyncio
async def test_clinician_override_respects_safety_floor():
    """Clinician override is limited to DEFAULT_CLINICIAN_OVERRIDE_LIMIT per window."""
    from app.sse.ucd.intensity_governor import IntensityGovernor, DEFAULT_CLINICIAN_OVERRIDE_LIMIT

    pool = _pool(
        fetchval_map={
            "clinician_override": DEFAULT_CLINICIAN_OVERRIDE_LIMIT,
        },
    )
    gov = IntensityGovernor(pool)
    result = await gov.clinician_override(
        "user1", "BREAKTHROUGH", 0.95, "testing override"
    )
    assert result["allowed"] is False
    assert "limit" in result.get("reason", "").lower()


@pytest.mark.asyncio
async def test_clinician_override_allowed_under_limit():
    """Clinician override should succeed when under the limit."""
    from app.sse.ucd.intensity_governor import IntensityGovernor, DEFAULT_CLINICIAN_OVERRIDE_LIMIT

    pool = _pool(
        fetchval_map={
            "clinician_override": 1,
        },
    )
    gov = IntensityGovernor(pool)
    result = await gov.clinician_override(
        "user1", "BREAKTHROUGH", 0.95, "clinical justification"
    )
    assert result["allowed"] is True
    assert result["overrides_used"] == 2
    assert result["override_limit"] == DEFAULT_CLINICIAN_OVERRIDE_LIMIT
