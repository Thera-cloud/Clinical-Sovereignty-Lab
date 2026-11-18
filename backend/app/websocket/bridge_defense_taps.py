"""Bridge-local Guardian Fibre and Pipeline Drum.

The backend hive dict is not in this process. These are the taps the bridge
already calls. A score is recorded and is not used to reject a login.
The drum does not write the backend baseline tables. # SOVEREIGN-VOICE
"""
from __future__ import annotations

_guardian = None
_drum = None
_tapped = False


def bridge_guardian(db_pool):
    """Fibre for this process. No pool means no observation and no login change."""
    global _guardian
    if db_pool is None:
        return None
    if _guardian is None:
        from app.services.guardian_fibre import GuardianFibre
        _guardian = GuardianFibre(db_pool)
        print(">>> [HIVE] Bridge guardian fibre ready", flush=True)
    return _guardian


async def bridge_drum():
    """In-process sensor for websocket frames. No shared baseline writes."""
    global _drum
    if _drum is None:
        from app.services.pipeline_drum import PipelineDrum
        drum = PipelineDrum(db_pool=None)
        await drum.start()
        _drum = drum
        print(">>> [HIVE] Bridge pipeline drum ready", flush=True)
    return _drum


def note_drum_tap(drum, endpoint: str, payload: bytes) -> None:
    """Record one websocket frame. The body is not stored."""
    global _tapped
    drum.tap_request(
        endpoint=endpoint,
        method="WS",
        status_code=200,
        response_time_ms=0,
        payload=payload or b"",
    )
    if not _tapped:
        _tapped = True
        print(">>> [HIVE] Bridge pipeline drum tapped", flush=True)
