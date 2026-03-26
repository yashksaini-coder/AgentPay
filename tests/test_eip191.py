"""Tests for EIP-191 identity binding (PeerId ↔ ETH wallet proof)."""

from __future__ import annotations

from agentic_payments.identity.eip191 import (
    DOMAIN_PREFIX,
    IdentityProof,
    sign_identity,
    verify_identity,
)


class TestEIP191Identity:
    def test_sign_and_verify(self, eth_keypair):
        """Identity proof created with a key should verify successfully."""
        peer_id = "12D3KooWTestPeerId123456789"
        proof = sign_identity(peer_id, eth_keypair.key.hex())

        assert proof.peer_id == peer_id
        assert proof.eth_address.lower() == eth_keypair.address.lower()
        assert len(proof.signature) == 65
        assert verify_identity(proof)

    def test_verify_wrong_address(self, eth_keypair, eth_keypair_b):
        """Proof should not verify if eth_address is forged."""
        peer_id = "12D3KooWTestPeerId123456789"
        proof = sign_identity(peer_id, eth_keypair.key.hex())

        # Tamper with the address
        forged = IdentityProof(
            peer_id=proof.peer_id,
            eth_address=eth_keypair_b.address,
            signature=proof.signature,
        )
        assert not verify_identity(forged)

    def test_verify_wrong_peer_id(self, eth_keypair):
        """Proof should not verify if peer_id is different from what was signed."""
        proof = sign_identity("12D3KooWOriginalPeerId", eth_keypair.key.hex())

        # Tamper with the peer_id
        forged = IdentityProof(
            peer_id="12D3KooWDifferentPeerId",
            eth_address=proof.eth_address,
            signature=proof.signature,
        )
        assert not verify_identity(forged)

    def test_verify_invalid_signature(self, eth_keypair):
        """Random bytes should not verify as a valid identity proof."""
        proof = IdentityProof(
            peer_id="12D3KooWTestPeerId",
            eth_address=eth_keypair.address,
            signature=b"\x00" * 65,
        )
        assert not verify_identity(proof)

    def test_domain_prefix(self):
        """Domain prefix should match the expected format."""
        assert DOMAIN_PREFIX == "AgentPay:identity:"

    def test_roundtrip_serialization(self, eth_keypair):
        """Proof should survive dict serialization round-trip."""
        peer_id = "12D3KooWTestPeerId123456789"
        proof = sign_identity(peer_id, eth_keypair.key.hex())

        data = proof.to_dict()
        restored = IdentityProof.from_dict(data)

        assert restored.peer_id == proof.peer_id
        assert restored.eth_address == proof.eth_address
        assert restored.signature == proof.signature
        assert verify_identity(restored)

    def test_different_keys_different_proofs(self, eth_keypair, eth_keypair_b):
        """Different keys should produce different signatures for the same peer_id."""
        peer_id = "12D3KooWTestPeerId123456789"
        proof_a = sign_identity(peer_id, eth_keypair.key.hex())
        proof_b = sign_identity(peer_id, eth_keypair_b.key.hex())

        assert proof_a.signature != proof_b.signature
        assert proof_a.eth_address != proof_b.eth_address
        assert verify_identity(proof_a)
        assert verify_identity(proof_b)

    def test_proof_from_dict_hex_string(self, eth_keypair):
        """from_dict should handle hex-encoded signature strings."""
        proof = sign_identity("12D3KooWTest", eth_keypair.key.hex())
        data = {
            "peer_id": proof.peer_id,
            "eth_address": proof.eth_address,
            "signature": proof.signature.hex(),
        }
        restored = IdentityProof.from_dict(data)
        assert restored.signature == proof.signature
