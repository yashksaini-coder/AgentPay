"""Tests for SignedVoucher creation and verification."""

from __future__ import annotations

from agentic_payments.payments.voucher import SignedVoucher


class TestSignedVoucher:
    def test_create_and_verify(self, eth_keypair, channel_id):
        """Voucher created with a key should verify against that key's address."""
        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=1,
            amount=1000,
            private_key=eth_keypair.key.hex(),
        )

        assert voucher.channel_id == channel_id
        assert voucher.nonce == 1
        assert voucher.amount == 1000
        assert len(voucher.signature) == 65
        assert voucher.verify(eth_keypair.address)

    def test_verify_wrong_signer(self, eth_keypair, eth_keypair_b, channel_id):
        """Voucher should not verify against the wrong address."""
        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=1,
            amount=1000,
            private_key=eth_keypair.key.hex(),
        )

        assert not voucher.verify(eth_keypair_b.address)

    def test_roundtrip_serialization(self, eth_keypair, channel_id):
        """Voucher should survive dict serialization round-trip."""
        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=5,
            amount=50000,
            private_key=eth_keypair.key.hex(),
        )

        data = voucher.to_dict()
        restored = SignedVoucher.from_dict(data)

        assert restored.channel_id == voucher.channel_id
        assert restored.nonce == voucher.nonce
        assert restored.amount == voucher.amount
        assert restored.signature == voucher.signature
        assert restored.verify(eth_keypair.address)

    def test_nonce_increases(self, eth_keypair, channel_id):
        """Sequential vouchers should have increasing nonces."""
        v1 = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        v2 = SignedVoucher.create(channel_id, 2, 200, eth_keypair.key.hex())

        assert v2.nonce > v1.nonce
        assert v2.amount > v1.amount
        assert v1.verify(eth_keypair.address)
        assert v2.verify(eth_keypair.address)

    def test_task_id_correlation(self, eth_keypair, channel_id):
        """Voucher should carry task_id for work-request correlation."""
        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=1,
            amount=1000,
            private_key=eth_keypair.key.hex(),
            task_id="task-abc-123",
        )

        assert voucher.task_id == "task-abc-123"
        assert voucher.verify(eth_keypair.address)

        # Roundtrip through dict
        data = voucher.to_dict()
        assert data["task_id"] == "task-abc-123"
        restored = SignedVoucher.from_dict(data)
        assert restored.task_id == "task-abc-123"

        # JSON dict
        json_data = voucher.to_json_dict()
        assert json_data["task_id"] == "task-abc-123"

    def test_task_id_default_empty(self, eth_keypair, channel_id):
        """Voucher without task_id should default to empty string."""
        voucher = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        assert voucher.task_id == ""
        # task_id omitted from dict when empty
        data = voucher.to_dict()
        assert "task_id" not in data

    def test_task_id_roundtrip_missing(self, eth_keypair, channel_id):
        """from_dict should handle missing task_id gracefully."""
        voucher = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        data = voucher.to_dict()
        data.pop("task_id", None)
        restored = SignedVoucher.from_dict(data)
        assert restored.task_id == ""
