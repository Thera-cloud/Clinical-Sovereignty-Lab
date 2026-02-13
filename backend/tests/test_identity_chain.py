"""
Tests for IdentityChainService — Ed25519 key management and chain verification.
"""

import pytest
from uuid import uuid4

from app.services.identity_chain import IdentityChainService, IdentityRecord


class TestMasterKeyManagement:
    """Test master key generation, loading, and persistence."""

    def test_initialize_master_key(self):
        """Master key generation should produce a valid PEM string."""
        service = IdentityChainService()
        pem = service.initialize_master_key()

        assert pem is not None
        assert "BEGIN PRIVATE KEY" in pem
        assert "END PRIVATE KEY" in pem
        assert service.master_public_pem is not None
        assert "BEGIN PUBLIC KEY" in service.master_public_pem

    def test_load_master_key(self):
        """Should be able to round-trip a master key via PEM."""
        service1 = IdentityChainService()
        pem = service1.initialize_master_key()
        pub1 = service1.master_public_pem

        service2 = IdentityChainService()
        service2.load_master_key(pem)
        pub2 = service2.master_public_pem

        assert pub1 == pub2

    def test_load_invalid_key_raises(self):
        """Loading garbage PEM should raise IdentityException."""
        service = IdentityChainService()
        with pytest.raises(Exception):  # IdentityException
            service.load_master_key("not-a-valid-pem")

    def test_master_public_pem_before_init_raises(self):
        """Accessing public PEM before init should raise."""
        service = IdentityChainService()
        with pytest.raises(Exception):
            _ = service.master_public_pem


class TestFibreIdentity:
    """Test Fibre identity creation and chain verification."""

    def setup_method(self):
        self.service = IdentityChainService()
        self.service.initialize_master_key()

    def test_create_fibre_identity(self):
        """Should generate an identity record with valid signature."""
        fibre_id = uuid4()
        record, private_pem = self.service.create_fibre_identity(fibre_id)

        assert isinstance(record, IdentityRecord)
        assert record.entity_id == fibre_id
        assert "BEGIN PUBLIC KEY" in record.public_key_pem
        assert record.parent_signature is not None
        assert record.parent_public_key_pem == self.service.master_public_pem
        assert "BEGIN PRIVATE KEY" in private_pem

    def test_verify_chain_valid(self):
        """Chain verification should pass for a legitimately signed Fibre."""
        fibre_id = uuid4()
        record, _ = self.service.create_fibre_identity(fibre_id)

        assert self.service.verify_chain(record) is True

    def test_verify_chain_tampered_signature(self):
        """Chain verification should fail if signature is tampered."""
        fibre_id = uuid4()
        record, _ = self.service.create_fibre_identity(fibre_id)

        # Tamper with the signature
        record.parent_signature = "dGFtcGVyZWQ="  # base64("tampered")

        assert self.service.verify_chain(record) is False

    def test_verify_chain_wrong_parent(self):
        """Chain verification should fail with a different parent key."""
        fibre_id = uuid4()
        record, _ = self.service.create_fibre_identity(fibre_id)

        # Replace parent public key with a new one
        other_service = IdentityChainService()
        other_service.initialize_master_key()
        record.parent_public_key_pem = other_service.master_public_pem

        assert self.service.verify_chain(record) is False

    def test_create_multiple_fibres(self):
        """Should create distinct identities for different Fibres."""
        id1 = uuid4()
        id2 = uuid4()

        record1, pk1 = self.service.create_fibre_identity(id1)
        record2, pk2 = self.service.create_fibre_identity(id2)

        assert record1.public_key_pem != record2.public_key_pem
        assert pk1 != pk2
        assert record1.entity_id != record2.entity_id


class TestMessageSigning:
    """Test message signing and verification."""

    def setup_method(self):
        self.service = IdentityChainService()
        self.service.initialize_master_key()
        self.fibre_id = uuid4()
        self.record, self.private_pem = self.service.create_fibre_identity(self.fibre_id)

    def test_sign_and_verify(self):
        """Sign a payload and verify it."""
        payload = {"action": "test", "value": 42}
        signature = self.service.sign_message(self.private_pem, payload)

        assert signature is not None
        assert isinstance(signature, str)

        is_valid = self.service.verify_message(
            self.record.public_key_pem, payload, signature
        )
        assert is_valid is True

    def test_verify_tampered_payload(self):
        """Verification should fail if payload is tampered."""
        payload = {"action": "test", "value": 42}
        signature = self.service.sign_message(self.private_pem, payload)

        tampered_payload = {"action": "test", "value": 99}
        is_valid = self.service.verify_message(
            self.record.public_key_pem, tampered_payload, signature
        )
        assert is_valid is False

    def test_verify_wrong_key(self):
        """Verification should fail with a different public key."""
        payload = {"action": "test"}
        signature = self.service.sign_message(self.private_pem, payload)

        # Create another fibre with different keys
        other_record, _ = self.service.create_fibre_identity(uuid4())

        is_valid = self.service.verify_message(
            other_record.public_key_pem, payload, signature
        )
        assert is_valid is False


class TestIdentityRecordSerialization:
    """Test IdentityRecord to_dict / from_dict."""

    def test_round_trip(self):
        service = IdentityChainService()
        service.initialize_master_key()
        fibre_id = uuid4()
        record, _ = service.create_fibre_identity(fibre_id)

        data = record.to_dict()
        restored = IdentityRecord.from_dict(data)

        assert restored.entity_id == record.entity_id
        assert restored.public_key_pem == record.public_key_pem
        assert restored.parent_signature == record.parent_signature
        assert restored.parent_public_key_pem == record.parent_public_key_pem
