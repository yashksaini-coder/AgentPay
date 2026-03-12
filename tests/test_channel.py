"""Tests for PaymentChannel state machine."""

from __future__ import annotations

import pytest

from agentic_payments.payments.channel import ChannelError, ChannelState, PaymentChannel
from agentic_payments.payments.voucher import SignedVoucher


@pytest.fixture
def channel(channel_id):
    return PaymentChannel(
        channel_id=channel_id,
        sender="0x2c7536E3605D9C16a7a3D7b1898e529396a65c23",
        receiver="0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf",
        total_deposit=1_000_000,
    )


class TestChannelStateMachine:
    def test_initial_state(self, channel):
        assert channel.state == ChannelState.PROPOSED

    def test_happy_path(self, channel):
        """PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED."""
        channel.accept()
        assert channel.state == ChannelState.OPEN

        channel.activate()
        assert channel.state == ChannelState.ACTIVE

        channel.cooperative_close()
        assert channel.state == ChannelState.CLOSING

        channel.settle()
        assert channel.state == ChannelState.SETTLED

    def test_invalid_transition(self, channel):
        """Cannot skip states."""
        with pytest.raises(ChannelError):
            channel.activate()  # Can't activate from PROPOSED

    def test_cannot_close_proposed(self, channel):
        with pytest.raises(ChannelError):
            channel.request_close()

    def test_dispute_from_active(self, channel):
        channel.accept()
        channel.activate()
        channel.dispute()
        assert channel.state == ChannelState.DISPUTED

    def test_settle_after_dispute(self, channel):
        channel.accept()
        channel.activate()
        channel.dispute()
        # Expire challenge period for test
        channel.close_expiration = 0
        channel.settle()
        assert channel.state == ChannelState.SETTLED


class TestVoucherApplication:
    def test_apply_voucher(self, channel, eth_keypair, channel_id):
        channel.accept()
        channel.activate()

        voucher = SignedVoucher.create(channel_id, 1, 500_000, eth_keypair.key.hex())
        channel.apply_voucher(voucher)

        assert channel.nonce == 1
        assert channel.total_paid == 500_000
        assert channel.remaining_balance == 500_000

    def test_reject_stale_nonce(self, channel, eth_keypair, channel_id):
        channel.accept()
        channel.activate()

        v1 = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        channel.apply_voucher(v1)

        v_stale = SignedVoucher.create(channel_id, 1, 200, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="nonce"):
            channel.apply_voucher(v_stale)

    def test_reject_decreasing_amount(self, channel, eth_keypair, channel_id):
        channel.accept()
        channel.activate()

        v1 = SignedVoucher.create(channel_id, 1, 500, eth_keypair.key.hex())
        channel.apply_voucher(v1)

        v2 = SignedVoucher.create(channel_id, 2, 400, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="amount"):
            channel.apply_voucher(v2)

    def test_reject_exceeds_deposit(self, channel, eth_keypair, channel_id):
        channel.accept()
        channel.activate()

        v = SignedVoucher.create(channel_id, 1, 2_000_000, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="exceeds deposit"):
            channel.apply_voucher(v)

    def test_cannot_apply_when_not_active(self, channel, eth_keypair, channel_id):
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError):
            channel.apply_voucher(v)

    def test_remaining_balance(self, channel, eth_keypair, channel_id):
        channel.accept()
        channel.activate()

        v1 = SignedVoucher.create(channel_id, 1, 300_000, eth_keypair.key.hex())
        channel.apply_voucher(v1)
        assert channel.remaining_balance == 700_000

        v2 = SignedVoucher.create(channel_id, 2, 600_000, eth_keypair.key.hex())
        channel.apply_voucher(v2)
        assert channel.remaining_balance == 400_000
