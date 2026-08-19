"""S1 wiring: migrations, prefix, auditor 15, Flutter copy, mirror parts."""

from pathlib import Path

from _studio_load import load_svc

TAB_ENDPOINTS = load_svc("studio_auditor").TAB_ENDPOINTS
LN_COHOST_LABEL = load_svc("studio_invariants").LN_COHOST_LABEL
MIRROR_CAPTURE_PARTS = load_svc("studio_mirror_capture").MIRROR_CAPTURE_PARTS

ROOT = Path(__file__).resolve().parents[2]


def test_migrations_400_408_exist():
    names = [p.name for p in (ROOT / "backend/migrations").glob("40[0-8]_*.sql")]
    for n in (
        "400_studio_shows.sql",
        "401_studio_sessions.sql",
        "402_studio_callers.sql",
        "403_studio_episodes.sql",
        "404_studio_roles.sql",
        "405_mirror_capture.sql",
        "406_studio_trust_baseline.sql",
        "407_studio_s2_s5.sql",
        "408_studio_consent_records.sql",
    ):
        assert n in names


def test_api_prefix_is_studio_not_sse():
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert 'prefix="/api/studio"' in src
    assert 'prefix="/api/sse/admin/studio"' not in src
    sse = (ROOT / "backend/app/routers/studio_api.py").read_text()
    assert 'prefix="/api/sse/admin/studio"' in sse


def test_auditor_has_15_checks():
    total = sum(len(t["endpoints"]) for t in TAB_ENDPOINTS)
    assert total == 15


def test_mirror_has_seven_parts():
    assert len(MIRROR_CAPTURE_PARTS) == 7
    kinds = [p["kind"] for p in MIRROR_CAPTURE_PARTS]
    assert kinds[0] == "mirror_1_voice"
    assert kinds[-1] == "mirror_7_donot"


def test_flutter_label_and_live_gate():
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert LN_COHOST_LABEL in dart
    assert "1 clean published episode" in dart
    hub = (ROOT / "mobile/lib/widgets/coach_integrations_hub.dart").read_text()
    assert "CoachSovereignStudioTab" in hub
    assert "length: 8" in hub


def test_ingest_accepts_capture_kwargs():
    src = (ROOT / "backend/app/services/voice_campaign_ingest.py").read_text()
    assert "capture_part_index" in src
    assert "capture_kind" in src
    assert "clone_consent" in src


def test_trust_enforcer_five_locations():
    te = (ROOT / "backend/app/services/trust_enforcer.py").read_text()
    assert '"studio_audit_sent"' in te
    assert '"Sovereign Studio"' in te
    assert '"studio_check_count"' in te
    main = (ROOT / "backend/app/main.py").read_text()
    assert '("studio_auditor"' in main or '"studio_auditor"' in main
    assert "sovereign_studio_api" in main
