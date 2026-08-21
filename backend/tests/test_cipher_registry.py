"""Unit tests for cipher_registry (Slice 6b).

Covers fallback semantics, strict-split mode, per-class isolation,
legacy plaintext passthrough, and invalid key handling.
"""

from __future__ import annotations

import os
import unittest

# Ensure a clean env at import time.
for _var in (
    "SKYEYE_TOKEN_ENCRYPTION_KEY",
    "SKYEYE_TOKEN_ENCRYPTION_KEY_PII",
    "SKYEYE_TOKEN_ENCRYPTION_KEY_CLINICAL",
    "ENCRYPTION_STRICT",
    "ENCRYPTION_STRICT_KEY_SPLIT",
    "ENVIRONMENT",
):
    os.environ.pop(_var, None)

from app.services.cipher_registry import (  # noqa: E402
    CipherKeyMissing,
    CipherRegistry,
    DATA_CLASS_CLINICAL,
    DATA_CLASS_OAUTH,
    DATA_CLASS_PII,
    get_registry,
)

try:
    from cryptography.fernet import Fernet  # type: ignore
    _HAS_FERNET = True
except Exception:  # pragma: no cover
    _HAS_FERNET = False


def _fresh(**env: str) -> CipherRegistry:
    """Reset the singleton and return a registry built with the given env."""
    for var in list(os.environ):
        if var.startswith("SKYEYE_TOKEN_ENCRYPTION_KEY") or var in (
            "ENCRYPTION_STRICT", "ENCRYPTION_STRICT_KEY_SPLIT", "ENVIRONMENT",
        ):
            os.environ.pop(var, None)
    for k, v in env.items():
        os.environ[k] = v
    CipherRegistry.reset()
    return get_registry()


@unittest.skipUnless(_HAS_FERNET, "cryptography not installed")
class TestFallbackAndIsolation(unittest.TestCase):
    def tearDown(self) -> None:
        CipherRegistry.reset()

    def test_no_keys_returns_plaintext_non_strict(self) -> None:
        reg = _fresh()
        self.assertFalse(reg.has_key(DATA_CLASS_OAUTH))
        self.assertFalse(reg.has_key(DATA_CLASS_PII))
        # Non-strict: encrypt returns plaintext (legacy behavior).
        self.assertEqual(reg.encrypt("hello", DATA_CLASS_PII), "hello")
        self.assertEqual(reg.decrypt("hello", DATA_CLASS_PII), "hello")

    def test_oauth_only_falls_back_for_pii_and_clinical(self) -> None:
        master = Fernet.generate_key().decode()
        reg = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY=master)
        self.assertTrue(reg.has_key(DATA_CLASS_OAUTH))
        self.assertTrue(reg.has_key(DATA_CLASS_PII))
        self.assertTrue(reg.has_key(DATA_CLASS_CLINICAL))
        # Fallback path: PII encrypted under oauth key still round-trips.
        ct = reg.encrypt("alice@example.com", DATA_CLASS_PII)
        self.assertTrue(ct.startswith("gAAAAA"))
        self.assertEqual(reg.decrypt(ct, DATA_CLASS_OAUTH), "alice@example.com")

    def test_split_keys_are_isolated(self) -> None:
        k_oauth = Fernet.generate_key().decode()
        k_pii = Fernet.generate_key().decode()
        k_clin = Fernet.generate_key().decode()
        reg = _fresh(
            SKYEYE_TOKEN_ENCRYPTION_KEY=k_oauth,
            SKYEYE_TOKEN_ENCRYPTION_KEY_PII=k_pii,
            SKYEYE_TOKEN_ENCRYPTION_KEY_CLINICAL=k_clin,
        )
        pii_ct = reg.encrypt("555-1234", DATA_CLASS_PII)
        # Decrypting a PII ciphertext with the clinical key must fail
        # (returns raw ciphertext, not the plaintext) — proves isolation.
        self.assertEqual(reg.decrypt(pii_ct, DATA_CLASS_CLINICAL), pii_ct)
        self.assertEqual(reg.decrypt(pii_ct, DATA_CLASS_OAUTH), pii_ct)
        # Own class decrypts correctly.
        self.assertEqual(reg.decrypt(pii_ct, DATA_CLASS_PII), "555-1234")

    def test_legacy_plaintext_passes_through(self) -> None:
        master = Fernet.generate_key().decode()
        reg = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY=master)
        # Non-Fernet value untouched.
        self.assertEqual(reg.decrypt("plain-old-token", DATA_CLASS_OAUTH), "plain-old-token")

    def test_empty_string_untouched(self) -> None:
        reg = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
        self.assertEqual(reg.encrypt("", DATA_CLASS_PII), "")
        self.assertEqual(reg.decrypt("", DATA_CLASS_PII), "")


@unittest.skipUnless(_HAS_FERNET, "cryptography not installed")
class TestStrictModes(unittest.TestCase):
    def tearDown(self) -> None:
        CipherRegistry.reset()

    def test_encryption_strict_raises_without_any_key(self) -> None:
        reg = _fresh(ENCRYPTION_STRICT="true")
        self.assertTrue(reg.is_strict())
        with self.assertRaises(CipherKeyMissing):
            reg.encrypt("secret", DATA_CLASS_PII)

    def test_strict_split_forbids_fallback(self) -> None:
        master = Fernet.generate_key().decode()
        reg = _fresh(
            SKYEYE_TOKEN_ENCRYPTION_KEY=master,
            ENCRYPTION_STRICT_KEY_SPLIT="true",
        )
        # oauth still works
        self.assertTrue(reg.has_key(DATA_CLASS_OAUTH))
        # pii has no key of its own → strict-split refuses fallback
        self.assertFalse(reg.has_key(DATA_CLASS_PII))
        with self.assertRaises(CipherKeyMissing):
            reg.encrypt("phi", DATA_CLASS_PII)

    def test_strict_split_ok_when_all_keys_present(self) -> None:
        reg = _fresh(
            SKYEYE_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            SKYEYE_TOKEN_ENCRYPTION_KEY_PII=Fernet.generate_key().decode(),
            SKYEYE_TOKEN_ENCRYPTION_KEY_CLINICAL=Fernet.generate_key().decode(),
            ENCRYPTION_STRICT_KEY_SPLIT="true",
        )
        for dc in (DATA_CLASS_OAUTH, DATA_CLASS_PII, DATA_CLASS_CLINICAL):
            ct = reg.encrypt("x", dc)
            self.assertTrue(ct.startswith("gAAAAA"), f"failed for {dc}")
            self.assertEqual(reg.decrypt(ct, dc), "x")

    def test_production_environment_activates_strict(self) -> None:
        reg = _fresh(ENVIRONMENT="production")
        self.assertTrue(reg.is_strict())
        with self.assertRaises(CipherKeyMissing):
            reg.encrypt("secret", DATA_CLASS_OAUTH)

    def test_encryption_strict_false_overrides_production(self) -> None:
        reg = _fresh(ENVIRONMENT="production", ENCRYPTION_STRICT="false")
        self.assertFalse(reg.is_strict())
        # Non-strict, no key → plaintext passthrough
        self.assertEqual(reg.encrypt("x", DATA_CLASS_OAUTH), "x")


@unittest.skipUnless(_HAS_FERNET, "cryptography not installed")
class TestInvalidInputs(unittest.TestCase):
    def tearDown(self) -> None:
        CipherRegistry.reset()

    def test_invalid_data_class_raises(self) -> None:
        reg = _fresh()
        with self.assertRaises(ValueError):
            reg.encrypt("x", "financial")
        with self.assertRaises(ValueError):
            reg.decrypt("x", "financial")

    def test_invalid_key_is_treated_as_missing(self) -> None:
        reg = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY="not-a-real-fernet-key")
        self.assertFalse(reg.has_key(DATA_CLASS_OAUTH))

    def test_wrong_key_decrypt_returns_ciphertext(self) -> None:
        k1 = Fernet.generate_key().decode()
        k2 = Fernet.generate_key().decode()
        reg = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY=k1)
        ct = reg.encrypt("hello", DATA_CLASS_OAUTH)
        # Swap to a different key and try to decrypt.
        reg2 = _fresh(SKYEYE_TOKEN_ENCRYPTION_KEY=k2)
        self.assertEqual(reg2.decrypt(ct, DATA_CLASS_OAUTH), ct)


@unittest.skipUnless(_HAS_FERNET, "cryptography not installed")
class TestSingleton(unittest.TestCase):
    def tearDown(self) -> None:
        CipherRegistry.reset()

    def test_get_returns_same_instance(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        self.assertIs(r1, r2)

    def test_reset_returns_new_instance(self) -> None:
        r1 = get_registry()
        CipherRegistry.reset()
        r2 = get_registry()
        self.assertIsNot(r1, r2)


if __name__ == "__main__":
    unittest.main()
