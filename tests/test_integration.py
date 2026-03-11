"""Integration tests for the full payment flow.

These tests require py-libp2p to be installed and functional.
They test the complete flow: discover → open channel → pay → settle.
"""

from __future__ import annotations


from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.channel import ChannelState, PaymentChannel
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.payments.voucher import SignedVoucher


class TestFullPaymentFlow:
    """Test the complete payment flow without network dependencies."""

    def test_end_to_end_channel_lifecycle(self):
        """Simulate a full channel lifecycle: open → pay → close."""
        wallet_a = Wallet.generate()
        wallet_b = Wallet.generate()

        # Sender creates a channel manager
        manager_a = ChannelManager(wallet_a.address)

        channel_id = bytes(range(32))
        deposit = 1_000_000

        # A creates outbound channel
        ch_a = manager_a.create_channel(
            channel_id=channel_id,
            receiver=wallet_b.address,
            total_deposit=deposit,
            peer_id="QmBobPeerId",
        )
        assert ch_a.state == ChannelState.PROPOSED

        # Simulate B accepting
        ch_a.accept()
        ch_a.activate()
        assert ch_a.state == ChannelState.ACTIVE

        # A sends 3 micropayments
        for i in range(1, 4):
            voucher = SignedVoucher.create(
                channel_id=channel_id,
                nonce=i,
                amount=i * 100_000,
                private_key=wallet_a.private_key,
            )
            assert voucher.verify(wallet_a.address)
            ch_a.apply_voucher(voucher)

        assert ch_a.nonce == 3
        assert ch_a.total_paid == 300_000
        assert ch_a.remaining_balance == 700_000

        # Close the channel
        ch_a.request_close()
        assert ch_a.state == ChannelState.CLOSING

        ch_a.settle()
        assert ch_a.state == ChannelState.SETTLED

    def test_voucher_verification_across_wallets(self):
        """Voucher signed by wallet A should only verify for A's address."""
        wallet_a = Wallet.generate()
        wallet_b = Wallet.generate()

        channel_id = bytes(range(32))
        voucher = SignedVoucher.create(
            channel_id=channel_id,
            nonce=1,
            amount=500,
            private_key=wallet_a.private_key,
        )

        assert voucher.verify(wallet_a.address)
        assert not voucher.verify(wallet_b.address)

    def test_channel_serialization(self):
        """Channel should serialize to a clean dict."""
        sender = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
        channel = PaymentChannel(
            channel_id=bytes(range(32)),
            sender=sender,
            receiver="0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf",
            total_deposit=1_000_000,
            peer_id="QmTestPeer",
        )
        d = channel.to_dict()
        assert d["sender"] == sender
        assert d["total_deposit"] == 1_000_000
        assert d["state"] == "PROPOSED"
        assert d["remaining_balance"] == 1_000_000
