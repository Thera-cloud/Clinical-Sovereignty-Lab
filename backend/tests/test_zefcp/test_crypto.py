"""Tests for crypto.py — encrypt/decrypt, sign/verify."""

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.services.zefcp.crypto import FibreFragmentCrypto


def _private_bytes_raw(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def test_encrypt_decrypt_roundtrip(swarm_secret: bytes) -> None:
    """Encrypt then decrypt, verify match."""
    crypto = FibreFragmentCrypto(swarm_secret)
    plaintext = b"sensitive observation data"
    obs_id = b"obs_001"
    ct = crypto.encrypt_payload(plaintext, obs_id)
    pt = crypto.decrypt_payload(ct, obs_id)
    assert pt == plaintext


def test_different_observations_different_keys(swarm_secret: bytes) -> None:
    """Two observation IDs produce different ciphertext."""
    crypto = FibreFragmentCrypto(swarm_secret)
    plaintext = b"same content"
    ct1 = crypto.encrypt_payload(plaintext, b"obs_A")
    ct2 = crypto.encrypt_payload(plaintext, b"obs_B")
    assert ct1 != ct2
    assert crypto.decrypt_payload(ct1, b"obs_A") == plaintext
    assert crypto.decrypt_payload(ct2, b"obs_B") == plaintext


def test_sign_verify_roundtrip(swarm_secret: bytes) -> None:
    """Sign then verify with correct key succeeds."""
    crypto = FibreFragmentCrypto(swarm_secret)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    data = b"observation payload"
    sig = crypto.sign_observation(data, _private_bytes_raw(private_key))
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    assert crypto.verify_observation(data, sig, pub_bytes)


def test_verify_wrong_key_fails(swarm_secret: bytes) -> None:
    """Verify with wrong public key returns False."""
    crypto = FibreFragmentCrypto(swarm_secret)
    private_key = Ed25519PrivateKey.generate()
    wrong_key = Ed25519PrivateKey.generate().public_key()
    data = b"observation payload"
    sig = crypto.sign_observation(data, _private_bytes_raw(private_key))
    wrong_pub_bytes = wrong_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    result = crypto.verify_observation(data, sig, wrong_pub_bytes)
    assert result is False
