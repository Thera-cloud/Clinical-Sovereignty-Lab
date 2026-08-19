"""INV-4 inbound starts screener; SIP join 403 without token."""

from pathlib import Path

from _studio_load import load_svc

inbound_twiml = load_svc("studio_screener_service").inbound_twiml
dump_allowed = load_svc("studio_tier2").dump_allowed

SRC = (Path(__file__).resolve().parents[2] / "backend/app/routers/sovereign_studio_api.py").read_text()


def test_inbound_twiml_starts_screener():
    assert '@public_router.post("/voice/inbound")' in SRC
    xml = inbound_twiml()
    assert "/api/studio/voice/screener" in xml
    assert "screening" in xml.lower()


def test_sip_join_403_without_token():
    assert 'raise HTTPException(403, "screener token required")' in SRC
    assert "/voice/sip-join" in SRC


def test_dump_tier2_locked():
    assert dump_allowed(0) is False
    assert "studio_tier2" in SRC
    assert "tier2_locked" in SRC
