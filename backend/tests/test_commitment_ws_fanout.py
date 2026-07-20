"""Phase 1: commitment_touch Redis fanout helper is importable and publishes."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = _ROOT / "app" / "services" / "nate_commitment_agent.py"


def _load():
    name = "nate_commitment_agent_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    sys.modules[name] = mod
    return mod


agent_mod = _load()


@pytest.mark.asyncio
async def test_publish_commitment_touch_fanout():
    mock_client = MagicMock()
    mock_client.publish = AsyncMock()
    mock_client.aclose = AsyncMock()

    with patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}):
        with patch("redis.asyncio.from_url", return_value=mock_client):
            await agent_mod.publish_commitment_touch_fanout(
                {
                    "type": "commitment_touch",
                    "hardware_id": "HW_TEST",
                    "text": "hi",
                    "commitment_id": "c1",
                }
            )
    mock_client.publish.assert_awaited()
    args = mock_client.publish.await_args.args
    assert args[0] == agent_mod.COMMITMENT_TOUCH_CHANNEL
    assert "HW_TEST" in args[1]
