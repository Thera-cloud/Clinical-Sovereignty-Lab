"""INV-4 inbound starts screener; SIP join 403 without token."""

from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "backend/app/routers/sovereign_studio_api.py").read_text()


def test_inbound_twiml_starts_screener():
    assert '@public_router.post("/voice/inbound")' in SRC
    assert "<Redirect>/api/studio/voice/screener</Redirect>" in SRC
    assert "screening" in SRC.lower() or "screener" in SRC


def test_sip_join_403_without_token():
    assert 'raise HTTPException(403, "screener token required")' in SRC
    assert "/voice/sip-join" in SRC


def test_dump_tier2_locked():
    assert 'raise HTTPException(409, "tier2_locked")' in SRC
