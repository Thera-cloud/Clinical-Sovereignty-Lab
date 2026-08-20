"""Slice 0.5 unit tests — TokenCipher + pii_cipher fail-closed policy.

Verifies:
- Strict mode auto-derives from ENVIRONMENT=production.
- ENCRYPTION_STRICT=true|false explicitly overrides the env detection.
- In strict mode WITHOUT a key, encrypt raises instead of silently
  passing plaintext through.
- In strict mode WITH a valid key, encrypt/decrypt round-trips normally.
- Non-strict mode preserves legacy behaviour so local dev still works.
- decrypt still handles legacy plaintext gracefully in both modes.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Iterator

import pytest


def _reload_pii_cipher(env: dict[str, str]):
    """Reload pii_cipher.py with a mutated environment so the module-level
    strict / key detection re-evaluates."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for k in ("SKYEYE_TOKEN_ENCRYPTION_KEY", "ENVIRONMENT", "ENCRYPTION_STRICT"):
        if k not in env:
            os.environ.pop(k, None)
    if "app.services.pii_cipher" in sys.modules:
        del sys.modules["app.services.pii_cipher"]
    import app.services.pii_cipher as mod
    return importlib.reload(mod)


def _reload_token_cipher(env: dict[str, str]):
    """Reload skyeye_platform_base so a fresh TokenCipher singleton picks
    up the mutated environment. Also patches app.config.settings so pydantic
    doesn't leak values from the repo .env file into these tests."""
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    for k in ("SKYEYE_TOKEN_ENCRYPTION_KEY", "ENVIRONMENT", "ENCRYPTION_STRICT"):
        if k not in env:
            os.environ.pop(k, None)

    # Neutralise cached pydantic settings — the repo .env sets both
    # ENVIRONMENT and SKYEYE_TOKEN_ENCRYPTION_KEY at module load time.
    import app.config as _cfg  # type: ignore
    if hasattr(_cfg, "settings"):
        _cfg.settings.SKYEYE_TOKEN_ENCRYPTION_KEY = env.get(
            "SKYEYE_TOKEN_ENCRYPTION_KEY", ""
        )
        _cfg.settings.ENVIRONMENT = env.get("ENVIRONMENT", "test")

    if "app.services.skyeye_platform_base" in sys.modules:
        del sys.modules["app.services.skyeye_platform_base"]
    import app.services.skyeye_platform_base as mod
    mod = importlib.reload(mod)
    mod.TokenCipher._instance = None  # force re-init
    return mod


@pytest.fixture(autouse=True)
def _snapshot_env() -> Iterator[None]:
    saved = {
        k: os.environ.get(k)
        for k in ("SKYEYE_TOKEN_ENCRYPTION_KEY", "ENVIRONMENT", "ENCRYPTION_STRICT")
    }
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── pii_cipher tests ─────────────────────────────────────────────────


def test_pii_dev_mode_passthrough_when_key_missing():
    mod = _reload_pii_cipher({"ENVIRONMENT": "development"})
    assert mod.is_strict_mode() is False
    assert mod.encrypt_pii("nathan@example.com") == "nathan@example.com"
    assert mod.decrypt_pii("nathan@example.com") == "nathan@example.com"


def test_pii_strict_mode_raises_without_key():
    mod = _reload_pii_cipher({"ENVIRONMENT": "production"})
    assert mod.is_strict_mode() is True
    with pytest.raises(mod.PIIEncryptionError):
        mod.encrypt_pii("nathan@example.com")


def test_pii_strict_mode_roundtrip_with_key():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    mod = _reload_pii_cipher({"ENVIRONMENT": "production", "SKYEYE_TOKEN_ENCRYPTION_KEY": key})
    ct = mod.encrypt_pii("nathan@example.com")
    assert ct != "nathan@example.com"
    assert ct.startswith("gAAAAA")
    assert mod.decrypt_pii(ct) == "nathan@example.com"


def test_pii_decrypt_returns_placeholder_when_key_missing():
    """Existing ciphertext must never be exposed as raw ciphertext."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    seed = _reload_pii_cipher({"ENVIRONMENT": "production", "SKYEYE_TOKEN_ENCRYPTION_KEY": key})
    ct = seed.encrypt_pii("secret")

    mod = _reload_pii_cipher({"ENVIRONMENT": "development"})
    assert mod.decrypt_pii(ct) == "[encrypted — key unavailable]"


def test_pii_strict_override_can_force_off_in_production():
    mod = _reload_pii_cipher(
        {"ENVIRONMENT": "production", "ENCRYPTION_STRICT": "false"}
    )
    assert mod.is_strict_mode() is False
    assert mod.encrypt_pii("hi") == "hi"


def test_pii_strict_override_can_force_on_in_dev():
    mod = _reload_pii_cipher(
        {"ENVIRONMENT": "development", "ENCRYPTION_STRICT": "true"}
    )
    assert mod.is_strict_mode() is True
    with pytest.raises(mod.PIIEncryptionError):
        mod.encrypt_pii("hi")


# ── TokenCipher tests ────────────────────────────────────────────────


def test_token_dev_mode_passthrough_when_key_missing():
    mod = _reload_token_cipher({"ENVIRONMENT": "development"})
    cipher = mod.TokenCipher.get()
    assert cipher.is_strict() is False
    assert cipher.encrypt("access-token-xyz") == "access-token-xyz"
    assert cipher.decrypt("access-token-xyz") == "access-token-xyz"


def test_token_strict_mode_raises_without_key():
    mod = _reload_token_cipher({"ENVIRONMENT": "production"})
    cipher = mod.TokenCipher.get()
    assert cipher.is_strict() is True
    with pytest.raises(mod.TokenEncryptionError):
        cipher.encrypt("access-token-xyz")


def test_token_strict_mode_roundtrip_with_key():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    mod = _reload_token_cipher(
        {"ENVIRONMENT": "production", "SKYEYE_TOKEN_ENCRYPTION_KEY": key}
    )
    cipher = mod.TokenCipher.get()
    ct = cipher.encrypt("oauth-secret-42")
    assert ct.startswith("gAAAAA")
    assert cipher.decrypt(ct) == "oauth-secret-42"


def test_token_decrypt_handles_legacy_plaintext():
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    mod = _reload_token_cipher(
        {"ENVIRONMENT": "production", "SKYEYE_TOKEN_ENCRYPTION_KEY": key}
    )
    cipher = mod.TokenCipher.get()
    # A legacy plaintext value (not starting with gAAAAA) must pass through.
    assert cipher.decrypt("legacy-plain-token") == "legacy-plain-token"


def test_token_empty_string_shortcircuits_in_strict_mode():
    mod = _reload_token_cipher({"ENVIRONMENT": "production"})
    cipher = mod.TokenCipher.get()
    # Empty inputs must not raise — they're valid "no token to store".
    assert cipher.encrypt("") == ""
    assert cipher.decrypt("") == ""
