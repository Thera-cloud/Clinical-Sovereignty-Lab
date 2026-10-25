"""asyncpg JSONB bind: dict must become JSON text (image upload 500)."""
import importlib.util
import json
import os

_PATH = os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "vault", "vault_operations.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("vault_ops_jsonb_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jsonb_param_dumps_image_dimensions():
    mod = _load()
    raw = {"width": 1536, "height": 2048}
    out = mod._jsonb_param(raw)
    assert isinstance(out, str)
    assert json.loads(out) == raw


def test_jsonb_param_none_and_string_passthrough():
    mod = _load()
    assert mod._jsonb_param(None) is None
    assert mod._jsonb_param("[]") == "[]"
    assert json.loads(mod._jsonb_param(["clinical"])) == ["clinical"]
