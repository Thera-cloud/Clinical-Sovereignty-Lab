"""S2–S5 offline gates: screener tree, INV-6 scan, dump gate, LiveKit guest video."""

from pathlib import Path

from _studio_load import load_svc

_comp = load_svc("studio_compliance")
_inv = load_svc("studio_invariants")
_lk = load_svc("studio_livekit")
_sc = load_svc("studio_screener_service")
_t2 = load_svc("studio_tier2")
scan_text = _comp.scan_text
LIVE_TIER_CLEAN_EPISODES = _inv.LIVE_TIER_CLEAN_EPISODES
LN_COHOST_LABEL = _inv.LN_COHOST_LABEL
join_token_stub = _lk.join_token_stub
reject_guest_video = _lk.reject_guest_video
handle_screener = _sc.handle_screener
inbound_twiml = _sc.inbound_twiml
is_risk = _sc.is_risk
DELAY_S = _t2.DELAY_S
dump_allowed = _t2.dump_allowed

ROOT = Path(__file__).resolve().parents[2]


def test_inbound_always_screener():
    xml = inbound_twiml()
    assert "/api/studio/voice/screener" in xml
    assert "screening" in xml.lower()


def test_screener_risk_private_support_not_show():
    out = handle_screener(step="risk", speech="I want to die tonight")
    assert out["risk"] is True
    assert "988" in out["twiml"]
    assert "private support" in out["twiml"].lower()
    assert "waiting room" not in out["twiml"].lower()


def test_screener_safe_wait():
    out = handle_screener(step="risk", speech="I want to talk about habits")
    assert out["risk"] is False
    assert "waiting room" in out["twiml"].lower()
    assert "audio only" in out["twiml"].lower()


def test_is_risk_false_on_ordinary():
    assert is_risk("how do I keep a morning routine") is False


def test_compliance_inv6_and_pii():
    flags = scan_text("I diagnose you have depression. Call 555-123-4567")
    cats = {f["category"] for f in flags}
    assert "guardrail" in cats
    assert "pii" in cats


def test_dump_gate_one_clean_episode():
    assert LIVE_TIER_CLEAN_EPISODES == 1
    assert dump_allowed(0) is False
    assert dump_allowed(1) is True
    assert DELAY_S == 45


def test_livekit_guest_audio_only():
    assert reject_guest_video("guest", "track-1")["ok"] is False
    assert reject_guest_video("guest", None)["ok"] is True
    tok = join_token_stub("sid", "guest")
    assert tok["allow_video"] is False
    assert tok["allowed_media_kinds"] == ["audio"]


def test_migration_407_and_api_routes():
    sql = (ROOT / "backend/migrations/407_studio_s2_s5.sql").read_text()
    assert "studio_youtube_connection" in sql
    assert "rtmp_url" in sql
    c402 = (ROOT / "backend/migrations/402_studio_callers.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS consent_records" not in c402
    c408 = (ROOT / "backend/migrations/408_studio_consent_records.sql").read_text()
    assert "studio_consent_records" in c408
    src = (ROOT / "backend/app/routers/sovereign_studio_api.py").read_text()
    assert "studio_screener_service" in src
    assert "studio_tier2" in src
    assert "regenerate" in src
    dart = (ROOT / "mobile/lib/widgets/coach_sovereign_studio_tab.dart").read_text()
    assert "EPISODE REVIEW" in dart
    assert LN_COHOST_LABEL in dart
    assert "Dump locked" in dart
