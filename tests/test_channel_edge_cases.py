"""Extensive edge-case tests for PaymentChannel construction, state transitions,
voucher application, and serialization.

Covers: wrong types, invalid values, boundary conditions, concurrent-like
scenarios, and every forbidden state transition.
"""

from __future__ import annotations

import time

import pytest

from agentic_payments.payments.channel import ChannelError, PaymentChannel
from agentic_payments.payments.voucher import SignedVoucher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SENDER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
RECEIVER = "0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf"


def _ch(channel_id=None, sender=SENDER, receiver=RECEIVER, deposit=1_000_000, **kw):
    """Shortcut to create a PaymentChannel with defaults."""
    return PaymentChannel(
        channel_id=bytes(range(32)) if channel_id is None else channel_id,
        sender=sender,
        receiver=receiver,
        total_deposit=deposit,
        **kw,
    )


def _active_ch(**kw):
    """Return a channel already in ACTIVE state."""
    ch = _ch(**kw)
    ch.accept()
    ch.activate()
    return ch


# ═══════════════════════════════════════════════════════════════════════════
# Construction validation
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelConstruction:
    """Validate __post_init__ guards on PaymentChannel."""

    # -- channel_id ---

    def test_channel_id_must_be_bytes(self):
        with pytest.raises(ChannelError, match="channel_id must be exactly 32 bytes"):
            _ch(channel_id="not-bytes")

    def test_channel_id_too_short(self):
        with pytest.raises(ChannelError, match="32 bytes"):
            _ch(channel_id=b"\x00" * 16)

    def test_channel_id_too_long(self):
        with pytest.raises(ChannelError, match="32 bytes"):
            _ch(channel_id=b"\x00" * 64)

    def test_channel_id_empty_bytes(self):
        with pytest.raises(ChannelError, match="32 bytes"):
            _ch(channel_id=b"")

    def test_channel_id_none(self):
        with pytest.raises((ChannelError, TypeError)):
            PaymentChannel(
                channel_id=None,
                sender=SENDER,
                receiver=RECEIVER,
                total_deposit=100,
            )

    def test_channel_id_int(self):
        with pytest.raises((ChannelError, TypeError)):
            _ch(channel_id=12345)

    def test_channel_id_exactly_32_bytes(self):
        ch = _ch(channel_id=b"\xaa" * 32)
        assert len(ch.channel_id) == 32

    # -- total_deposit ---

    def test_deposit_zero(self):
        with pytest.raises(ChannelError, match="positive integer"):
            _ch(deposit=0)

    def test_deposit_negative(self):
        with pytest.raises(ChannelError, match="positive integer"):
            _ch(deposit=-1)

    def test_deposit_float(self):
        with pytest.raises(ChannelError, match="positive integer"):
            _ch(deposit=1.5)

    def test_deposit_string(self):
        with pytest.raises(ChannelError, match="positive integer"):
            _ch(deposit="1000000")

    def test_deposit_none(self):
        with pytest.raises(ChannelError):
            _ch(deposit=None)

    def test_deposit_very_large(self):
        """Massive deposit (100 ETH in wei) should be accepted."""
        ch = _ch(deposit=100 * 10**18)
        assert ch.total_deposit == 100 * 10**18

    def test_deposit_one_wei(self):
        ch = _ch(deposit=1)
        assert ch.total_deposit == 1

    # -- sender / receiver ---

    def test_sender_too_short(self):
        with pytest.raises(ChannelError, match="sender must be a valid"):
            _ch(sender="0x123")

    def test_sender_empty(self):
        with pytest.raises(ChannelError, match="sender must be a valid"):
            _ch(sender="")

    def test_sender_not_string(self):
        with pytest.raises(ChannelError, match="sender must be a valid"):
            _ch(sender=12345)

    def test_receiver_too_short(self):
        with pytest.raises(ChannelError, match="receiver must be a valid"):
            _ch(receiver="0x")

    def test_receiver_not_string(self):
        with pytest.raises(ChannelError, match="receiver must be a valid"):
            _ch(receiver=None)

    def test_sender_equals_receiver(self):
        """Self-payment channels are technically allowed by the constructor."""
        ch = _ch(sender=SENDER, receiver=SENDER)
        assert ch.sender == ch.receiver

    # -- total_paid at construction ---

    def test_initial_total_paid_negative(self):
        with pytest.raises(ChannelError, match="total_paid must be non-negative"):
            PaymentChannel(
                channel_id=bytes(range(32)),
                sender=SENDER,
                receiver=RECEIVER,
                total_deposit=1000,
                total_paid=-1,
            )

    def test_initial_total_paid_exceeds_deposit(self):
        with pytest.raises(ChannelError, match="total_paid cannot exceed total_deposit"):
            PaymentChannel(
                channel_id=bytes(range(32)),
                sender=SENDER,
                receiver=RECEIVER,
                total_deposit=1000,
                total_paid=2000,
            )

    def test_initial_total_paid_at_max(self):
        """Constructing with total_paid == deposit is valid (fully spent)."""
        ch = PaymentChannel(
            channel_id=bytes(range(32)),
            sender=SENDER,
            receiver=RECEIVER,
            total_deposit=1000,
            total_paid=1000,
        )
        assert ch.remaining_balance == 0

    # -- timestamps ---

    def test_created_at_auto_set(self):
        ch = _ch()
        assert abs(ch.created_at - int(time.time())) <= 2

    def test_updated_at_auto_set(self):
        ch = _ch()
        assert abs(ch.updated_at - int(time.time())) <= 2


# ═══════════════════════════════════════════════════════════════════════════
# Every invalid state transition (exhaustive matrix)
# ═══════════════════════════════════════════════════════════════════════════


class TestInvalidStateTransitions:
    """Every forbidden transition should raise ChannelError."""

    # From PROPOSED ---
    def test_proposed_cannot_activate(self):
        ch = _ch()
        with pytest.raises(ChannelError):
            ch.activate()

    def test_proposed_cannot_close(self):
        ch = _ch()
        with pytest.raises(ChannelError):
            ch.request_close()

    def test_proposed_cannot_settle(self):
        ch = _ch()
        with pytest.raises(ChannelError):
            ch.settle()

    def test_proposed_cannot_dispute(self):
        ch = _ch()
        with pytest.raises(ChannelError):
            ch.dispute()

    # From OPEN ---
    def test_open_cannot_accept_again(self):
        ch = _ch()
        ch.accept()
        with pytest.raises(ChannelError):
            ch.accept()

    def test_open_cannot_close(self):
        ch = _ch()
        ch.accept()
        with pytest.raises(ChannelError):
            ch.request_close()

    def test_open_cannot_settle(self):
        ch = _ch()
        ch.accept()
        with pytest.raises(ChannelError):
            ch.settle()

    def test_open_cannot_dispute(self):
        ch = _ch()
        ch.accept()
        with pytest.raises(ChannelError):
            ch.dispute()

    # From ACTIVE ---
    def test_active_cannot_accept(self):
        ch = _active_ch()
        with pytest.raises(ChannelError):
            ch.accept()

    def test_active_cannot_activate_again(self):
        ch = _active_ch()
        with pytest.raises(ChannelError):
            ch.activate()

    # From CLOSING ---
    def test_closing_cannot_accept(self):
        ch = _active_ch()
        ch.request_close()
        with pytest.raises(ChannelError):
            ch.accept()

    def test_closing_cannot_activate(self):
        ch = _active_ch()
        ch.request_close()
        with pytest.raises(ChannelError):
            ch.activate()

    def test_closing_cannot_close_again(self):
        ch = _active_ch()
        ch.request_close()
        with pytest.raises(ChannelError):
            ch.request_close()

    # From SETTLED ---
    def test_settled_is_terminal(self):
        ch = _active_ch()
        ch.cooperative_close()
        ch.settle()
        for action in [ch.accept, ch.activate, ch.request_close, ch.settle, ch.dispute]:
            with pytest.raises(ChannelError):
                action()

    # From DISPUTED ---
    def test_disputed_cannot_accept(self):
        ch = _active_ch()
        ch.dispute()
        with pytest.raises(ChannelError):
            ch.accept()

    def test_disputed_cannot_activate(self):
        ch = _active_ch()
        ch.dispute()
        with pytest.raises(ChannelError):
            ch.activate()

    def test_disputed_cannot_close(self):
        ch = _active_ch()
        ch.dispute()
        with pytest.raises(ChannelError):
            ch.request_close()

    def test_disputed_cannot_dispute_again(self):
        ch = _active_ch()
        ch.dispute()
        with pytest.raises(ChannelError):
            ch.dispute()


# ═══════════════════════════════════════════════════════════════════════════
# Voucher application edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestVoucherEdgeCases:
    """Boundary conditions for apply_voucher beyond the basics."""

    def test_voucher_in_proposed_state(self, eth_keypair, channel_id):
        ch = _ch(channel_id=channel_id)
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="Cannot apply voucher in state PROPOSED"):
            ch.apply_voucher(v)

    def test_voucher_in_open_state(self, eth_keypair, channel_id):
        ch = _ch(channel_id=channel_id)
        ch.accept()
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="Cannot apply voucher in state OPEN"):
            ch.apply_voucher(v)

    def test_voucher_in_closing_state(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        ch.request_close()
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="Cannot apply voucher in state CLOSING"):
            ch.apply_voucher(v)

    def test_voucher_in_settled_state(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        ch.cooperative_close()
        ch.settle()
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="Cannot apply voucher in state SETTLED"):
            ch.apply_voucher(v)

    def test_voucher_in_disputed_state(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        ch.dispute()
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="Cannot apply voucher in state DISPUTED"):
            ch.apply_voucher(v)

    def test_nonce_zero_rejected(self, eth_keypair, channel_id):
        """Nonce 0 is same as initial nonce, so must be rejected."""
        ch = _active_ch(channel_id=channel_id)
        v = SignedVoucher.create(channel_id, 0, 100, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="nonce"):
            ch.apply_voucher(v)

    def test_nonce_must_strictly_increase(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        v1 = SignedVoucher.create(channel_id, 5, 100, eth_keypair.key.hex())
        ch.apply_voucher(v1)
        # Same nonce
        v2 = SignedVoucher.create(channel_id, 5, 200, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="nonce"):
            ch.apply_voucher(v2)

    def test_nonce_gap_is_allowed(self, eth_keypair, channel_id):
        """Non-consecutive nonces (1 → 10) should work."""
        ch = _active_ch(channel_id=channel_id)
        v1 = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        ch.apply_voucher(v1)
        v2 = SignedVoucher.create(channel_id, 10, 200, eth_keypair.key.hex())
        ch.apply_voucher(v2)
        assert ch.nonce == 10

    def test_amount_equal_to_current_rejected(self, eth_keypair, channel_id):
        """Same cumulative amount (not greater) must be rejected."""
        ch = _active_ch(channel_id=channel_id)
        v1 = SignedVoucher.create(channel_id, 1, 500, eth_keypair.key.hex())
        ch.apply_voucher(v1)
        v2 = SignedVoucher.create(channel_id, 2, 500, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="amount"):
            ch.apply_voucher(v2)

    def test_amount_exactly_deposit(self, eth_keypair, channel_id):
        """Paying the entire deposit in one voucher should work."""
        ch = _active_ch(channel_id=channel_id)
        v = SignedVoucher.create(channel_id, 1, 1_000_000, eth_keypair.key.hex())
        ch.apply_voucher(v)
        assert ch.remaining_balance == 0

    def test_amount_one_over_deposit(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        v = SignedVoucher.create(channel_id, 1, 1_000_001, eth_keypair.key.hex())
        with pytest.raises(ChannelError, match="exceeds deposit"):
            ch.apply_voucher(v)

    def test_many_micropayments(self, eth_keypair, channel_id):
        """Apply 100 sequential micropayments (stress test)."""
        ch = _active_ch(channel_id=channel_id)
        for i in range(1, 101):
            v = SignedVoucher.create(channel_id, i, i * 10_000, eth_keypair.key.hex())
            ch.apply_voucher(v)
        assert ch.nonce == 100
        assert ch.total_paid == 1_000_000
        assert ch.remaining_balance == 0

    def test_voucher_updates_latest_voucher(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        v1 = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        ch.apply_voucher(v1)
        assert ch.latest_voucher is v1
        v2 = SignedVoucher.create(channel_id, 2, 200, eth_keypair.key.hex())
        ch.apply_voucher(v2)
        assert ch.latest_voucher is v2

    def test_voucher_updates_timestamp(self, eth_keypair, channel_id):
        ch = _active_ch(channel_id=channel_id)
        old_ts = ch.updated_at
        v = SignedVoucher.create(channel_id, 1, 100, eth_keypair.key.hex())
        ch.apply_voucher(v)
        assert ch.updated_at >= old_ts


# ═══════════════════════════════════════════════════════════════════════════
# Serialization
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelSerialization:
    def test_to_dict_fields_complete(self):
        ch = _ch(peer_id="QmTestPeer123")
        d = ch.to_dict()
        required = {
            "channel_id", "sender", "receiver", "total_deposit",
            "state", "nonce", "total_paid", "remaining_balance",
            "created_at", "updated_at", "peer_id",
        }
        assert required.issubset(d.keys())

    def test_to_dict_hex_channel_id(self):
        cid = b"\xab" * 32
        ch = _ch(channel_id=cid)
        d = ch.to_dict()
        assert d["channel_id"] == cid.hex()

    def test_to_dict_state_is_string(self):
        ch = _ch()
        assert isinstance(ch.to_dict()["state"], str)
        assert ch.to_dict()["state"] == "PROPOSED"

    def test_to_dict_after_payments(self, eth_keypair):
        cid = bytes(range(32))
        ch = _active_ch(channel_id=cid)
        v = SignedVoucher.create(cid, 1, 250_000, eth_keypair.key.hex())
        ch.apply_voucher(v)
        d = ch.to_dict()
        assert d["state"] == "ACTIVE"
        assert d["nonce"] == 1
        assert d["total_paid"] == 250_000
        assert d["remaining_balance"] == 750_000

    def test_remaining_balance_property(self):
        ch = _ch(deposit=500)
        assert ch.remaining_balance == 500

    def test_to_dict_peer_id_preserved(self):
        ch = _ch(peer_id="QmFoo")
        assert ch.to_dict()["peer_id"] == "QmFoo"
