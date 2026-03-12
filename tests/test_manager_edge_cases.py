"""Extensive tests for ChannelManager: creation, open handling, payment
sending, close handling, and multi-channel scenarios.

Covers: duplicate channels, wrong inputs, timestamp skew, signature
mismatches, concurrent channels, nonce/amount mismatches on close, and
the send-first-then-commit pattern.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.channel import ChannelError, ChannelState, PaymentChannel
from agentic_payments.payments.manager import ChannelManager, MAX_TIMESTAMP_SKEW
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.messages import PaymentClose, PaymentOpen, PaymentUpdate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SENDER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
RECEIVER = "0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf"
CID = bytes(range(32))
CID_2 = bytes(range(32, 64))


@pytest.fixture
def manager():
    return ChannelManager(SENDER)


@pytest.fixture
def wallet_a():
    return Wallet.from_private_key(
        "0x4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
    )


@pytest.fixture
def wallet_b():
    return Wallet.from_private_key(
        "0x6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Channel creation & lookup
# ═══════════════════════════════════════════════════════════════════════════


class TestChannelCreation:
    def test_create_channel(self, manager):
        ch = manager.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        assert ch.state == ChannelState.PROPOSED
        assert ch.sender == SENDER
        assert ch.receiver == RECEIVER
        assert ch.total_deposit == 1_000_000
        assert ch.peer_id == "QmPeer"

    def test_created_channel_is_retrievable(self, manager):
        manager.create_channel(CID, RECEIVER, 500, "QmPeer")
        ch = manager.get_channel(CID)
        assert ch.total_deposit == 500

    def test_get_nonexistent_channel(self, manager):
        with pytest.raises(KeyError, match="Channel not found"):
            manager.get_channel(b"\xff" * 32)

    def test_list_channels_empty(self, manager):
        assert manager.list_channels() == []

    def test_list_channels_with_filter(self, manager):
        ch1 = manager.create_channel(CID, RECEIVER, 1000, "QmA")
        ch2 = manager.create_channel(CID_2, RECEIVER, 2000, "QmB")
        ch1.accept()
        ch1.activate()
        # ch2 stays PROPOSED
        active = manager.list_channels(state=ChannelState.ACTIVE)
        proposed = manager.list_channels(state=ChannelState.PROPOSED)
        assert len(active) == 1
        assert len(proposed) == 1
        assert active[0].channel_id == CID
        assert proposed[0].channel_id == CID_2

    def test_list_all_channels(self, manager):
        manager.create_channel(CID, RECEIVER, 1000, "QmA")
        manager.create_channel(CID_2, RECEIVER, 2000, "QmB")
        assert len(manager.list_channels()) == 2

    def test_remove_channel(self, manager):
        manager.create_channel(CID, RECEIVER, 1000, "QmA")
        manager.remove_channel(CID)
        with pytest.raises(KeyError):
            manager.get_channel(CID)

    def test_remove_nonexistent_channel_is_safe(self, manager):
        """remove_channel on unknown ID should not raise."""
        manager.remove_channel(b"\xab" * 32)  # no-op

    def test_create_multiple_channels_different_ids(self, manager):
        for i in range(5):
            cid = bytes([i]) + b"\x00" * 31
            manager.create_channel(cid, RECEIVER, 1000 * (i + 1), f"QmPeer{i}")
        assert len(manager.list_channels()) == 5

    def test_create_duplicate_channel_id_overwrites(self, manager):
        """Creating with same ID overwrites silently (dict assignment)."""
        manager.create_channel(CID, RECEIVER, 1000, "QmA")
        manager.create_channel(CID, RECEIVER, 9999, "QmB")
        ch = manager.get_channel(CID)
        assert ch.total_deposit == 9999


# ═══════════════════════════════════════════════════════════════════════════
# Handle open request (incoming from peer)
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleOpenRequest:
    async def test_accept_open_request(self, manager):
        msg = PaymentOpen(
            channel_id=CID, sender=RECEIVER, receiver=SENDER,
            total_deposit=500_000,
        )
        ch = await manager.handle_open_request(msg, "QmRemotePeer")
        assert ch.state == ChannelState.ACTIVE  # accept + activate
        assert ch.sender == RECEIVER
        assert ch.receiver == SENDER
        assert ch.peer_id == "QmRemotePeer"

    async def test_open_request_duplicate_channel_id(self, manager):
        msg = PaymentOpen(
            channel_id=CID, sender=RECEIVER, receiver=SENDER,
            total_deposit=500_000,
        )
        await manager.handle_open_request(msg, "QmPeer1")
        with pytest.raises(ValueError, match="Channel ID already exists"):
            await manager.handle_open_request(msg, "QmPeer2")

    async def test_open_request_zero_deposit(self, manager):
        msg = PaymentOpen(
            channel_id=CID, sender=RECEIVER, receiver=SENDER,
            total_deposit=0,
        )
        with pytest.raises(ValueError, match="Deposit must be positive"):
            await manager.handle_open_request(msg, "QmPeer")

    async def test_open_request_negative_deposit(self, manager):
        msg = PaymentOpen(
            channel_id=CID, sender=RECEIVER, receiver=SENDER,
            total_deposit=-100,
        )
        with pytest.raises(ValueError, match="Deposit must be positive"):
            await manager.handle_open_request(msg, "QmPeer")

    async def test_open_request_channel_stored(self, manager):
        msg = PaymentOpen(
            channel_id=CID, sender=RECEIVER, receiver=SENDER,
            total_deposit=1000,
        )
        await manager.handle_open_request(msg, "QmPeer")
        assert CID in manager.channels
        assert manager.get_channel(CID).state == ChannelState.ACTIVE


# ═══════════════════════════════════════════════════════════════════════════
# Handle payment update (incoming voucher)
# ═══════════════════════════════════════════════════════════════════════════


class TestHandlePaymentUpdate:
    async def _setup_channel(self, manager, wallet):
        """Create an active channel where wallet is the sender."""
        ch = PaymentChannel(
            channel_id=CID, sender=wallet.address, receiver=manager.local_address,
            total_deposit=1_000_000, peer_id="QmPeer",
        )
        ch.accept()
        ch.activate()
        manager.channels[CID] = ch
        return ch

    async def test_valid_payment_update(self, manager, wallet_a):
        await self._setup_channel(manager, wallet_a)
        v = SignedVoucher.create(CID, 1, 100_000, wallet_a.private_key)
        msg = PaymentUpdate(
            channel_id=CID, nonce=v.nonce, amount=v.amount,
            timestamp=v.timestamp, signature=v.signature,
        )
        await manager.handle_payment_update(msg)
        ch = manager.get_channel(CID)
        assert ch.nonce == 1
        assert ch.total_paid == 100_000

    async def test_payment_update_unknown_channel(self, manager, wallet_a):
        v = SignedVoucher.create(CID, 1, 100, wallet_a.private_key)
        msg = PaymentUpdate(
            channel_id=b"\xff" * 32, nonce=v.nonce, amount=v.amount,
            timestamp=v.timestamp, signature=v.signature,
        )
        with pytest.raises(KeyError, match="Channel not found"):
            await manager.handle_payment_update(msg)

    async def test_payment_update_timestamp_too_old(self, manager, wallet_a):
        await self._setup_channel(manager, wallet_a)
        old_ts = int(time.time()) - MAX_TIMESTAMP_SKEW - 100
        v = SignedVoucher(
            channel_id=CID, nonce=1, amount=100,
            timestamp=old_ts, signature=b"\x00" * 65,
        )
        msg = PaymentUpdate(
            channel_id=CID, nonce=1, amount=100,
            timestamp=old_ts, signature=b"\x00" * 65,
        )
        with pytest.raises(ValueError, match="timestamp too skewed"):
            await manager.handle_payment_update(msg)

    async def test_payment_update_timestamp_too_future(self, manager, wallet_a):
        await self._setup_channel(manager, wallet_a)
        future_ts = int(time.time()) + MAX_TIMESTAMP_SKEW + 100
        msg = PaymentUpdate(
            channel_id=CID, nonce=1, amount=100,
            timestamp=future_ts, signature=b"\x00" * 65,
        )
        with pytest.raises(ValueError, match="timestamp too skewed"):
            await manager.handle_payment_update(msg)

    async def test_payment_update_invalid_signature(self, manager, wallet_a, wallet_b):
        """Voucher signed by B on a channel where A is sender → rejected."""
        await self._setup_channel(manager, wallet_a)
        v = SignedVoucher.create(CID, 1, 100_000, wallet_b.private_key)
        msg = PaymentUpdate(
            channel_id=CID, nonce=v.nonce, amount=v.amount,
            timestamp=v.timestamp, signature=v.signature,
        )
        with pytest.raises(ValueError, match="Invalid voucher signature"):
            await manager.handle_payment_update(msg)

    async def test_sequential_payment_updates(self, manager, wallet_a):
        await self._setup_channel(manager, wallet_a)
        for i in range(1, 6):
            v = SignedVoucher.create(CID, i, i * 50_000, wallet_a.private_key)
            msg = PaymentUpdate(
                channel_id=CID, nonce=v.nonce, amount=v.amount,
                timestamp=v.timestamp, signature=v.signature,
            )
            await manager.handle_payment_update(msg)
        ch = manager.get_channel(CID)
        assert ch.nonce == 5
        assert ch.total_paid == 250_000

    async def test_payment_update_stale_nonce_rejected(self, manager, wallet_a):
        await self._setup_channel(manager, wallet_a)
        v1 = SignedVoucher.create(CID, 3, 100, wallet_a.private_key)
        msg1 = PaymentUpdate(
            channel_id=CID, nonce=v1.nonce, amount=v1.amount,
            timestamp=v1.timestamp, signature=v1.signature,
        )
        await manager.handle_payment_update(msg1)
        # Now try nonce 2 (stale)
        v2 = SignedVoucher.create(CID, 2, 200, wallet_a.private_key)
        msg2 = PaymentUpdate(
            channel_id=CID, nonce=v2.nonce, amount=v2.amount,
            timestamp=v2.timestamp, signature=v2.signature,
        )
        with pytest.raises(ChannelError, match="nonce"):
            await manager.handle_payment_update(msg2)


# ═══════════════════════════════════════════════════════════════════════════
# Handle close request
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleCloseRequest:
    def _active_channel(self, manager, nonce=0, total_paid=0):
        ch = PaymentChannel(
            channel_id=CID, sender=SENDER, receiver=RECEIVER,
            total_deposit=1_000_000, peer_id="QmPeer",
        )
        ch.accept()
        ch.activate()
        # Manually set nonce/paid for testing close validation
        ch.nonce = nonce
        ch.total_paid = total_paid
        manager.channels[CID] = ch
        return ch

    async def test_close_matching_state(self, manager):
        self._active_channel(manager, nonce=5, total_paid=250_000)
        msg = PaymentClose(
            channel_id=CID, final_nonce=5, final_amount=250_000, cooperative=True,
        )
        await manager.handle_close_request(msg)
        ch = manager.get_channel(CID)
        assert ch.state == ChannelState.CLOSING

    async def test_close_nonce_mismatch(self, manager):
        self._active_channel(manager, nonce=5, total_paid=250_000)
        msg = PaymentClose(
            channel_id=CID, final_nonce=3, final_amount=250_000,
        )
        with pytest.raises(ValueError, match="Close nonce mismatch"):
            await manager.handle_close_request(msg)

    async def test_close_amount_mismatch(self, manager):
        self._active_channel(manager, nonce=5, total_paid=250_000)
        msg = PaymentClose(
            channel_id=CID, final_nonce=5, final_amount=999_999,
        )
        with pytest.raises(ValueError, match="Close amount mismatch"):
            await manager.handle_close_request(msg)

    async def test_close_unknown_channel(self, manager):
        msg = PaymentClose(
            channel_id=b"\xff" * 32, final_nonce=0, final_amount=0,
        )
        with pytest.raises(KeyError, match="Channel not found"):
            await manager.handle_close_request(msg)

    async def test_close_zero_nonce_zero_amount(self, manager):
        """Close a channel with no payments made."""
        self._active_channel(manager, nonce=0, total_paid=0)
        msg = PaymentClose(
            channel_id=CID, final_nonce=0, final_amount=0, cooperative=True,
        )
        await manager.handle_close_request(msg)
        assert manager.get_channel(CID).state == ChannelState.CLOSING


# ═══════════════════════════════════════════════════════════════════════════
# Send payment (outbound — send-first-then-commit)
# ═══════════════════════════════════════════════════════════════════════════


class TestSendPayment:
    def _active_channel(self, manager):
        ch = manager.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        ch.accept()
        ch.activate()
        return ch

    async def test_send_payment_success(self, manager, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        ch = mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        ch.accept()
        ch.activate()

        mock_send = AsyncMock()
        voucher = await mgr.send_payment(CID, 100_000, wallet_a.private_key, mock_send)

        assert voucher.nonce == 1
        assert voucher.amount == 100_000
        assert voucher.verify(wallet_a.address)
        mock_send.assert_called_once()
        assert ch.nonce == 1
        assert ch.total_paid == 100_000

    async def test_send_payment_zero_amount(self, manager, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        mgr.get_channel(CID).accept()
        mgr.get_channel(CID).activate()

        with pytest.raises(ValueError, match="Payment amount must be positive"):
            await mgr.send_payment(CID, 0, wallet_a.private_key, AsyncMock())

    async def test_send_payment_negative_amount(self, manager, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        mgr.get_channel(CID).accept()
        mgr.get_channel(CID).activate()

        with pytest.raises(ValueError, match="Payment amount must be positive"):
            await mgr.send_payment(CID, -50, wallet_a.private_key, AsyncMock())

    async def test_send_payment_exceeds_remaining(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        mgr.create_channel(CID, RECEIVER, 1000, "QmPeer")
        mgr.get_channel(CID).accept()
        mgr.get_channel(CID).activate()

        mock_send = AsyncMock()
        # Cumulative amount will be 2000 > deposit 1000
        with pytest.raises(ChannelError, match="exceeds deposit"):
            await mgr.send_payment(CID, 2000, wallet_a.private_key, mock_send)

    async def test_send_payment_unknown_channel(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        with pytest.raises(KeyError, match="Channel not found"):
            await mgr.send_payment(b"\xff" * 32, 100, wallet_a.private_key, AsyncMock())

    async def test_send_fails_channel_unchanged(self, wallet_a):
        """If send_fn raises, channel state must NOT be updated."""
        mgr = ChannelManager(wallet_a.address)
        mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        mgr.get_channel(CID).accept()
        mgr.get_channel(CID).activate()

        failing_send = AsyncMock(side_effect=ConnectionError("network down"))
        with pytest.raises(ConnectionError):
            await mgr.send_payment(CID, 100_000, wallet_a.private_key, failing_send)

        # Channel must remain at nonce 0, total_paid 0
        ch = mgr.get_channel(CID)
        assert ch.nonce == 0
        assert ch.total_paid == 0

    async def test_send_multiple_payments_cumulative(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        mgr.get_channel(CID).accept()
        mgr.get_channel(CID).activate()

        mock_send = AsyncMock()
        v1 = await mgr.send_payment(CID, 100_000, wallet_a.private_key, mock_send)
        v2 = await mgr.send_payment(CID, 150_000, wallet_a.private_key, mock_send)
        v3 = await mgr.send_payment(CID, 200_000, wallet_a.private_key, mock_send)

        assert v1.nonce == 1 and v1.amount == 100_000
        assert v2.nonce == 2 and v2.amount == 250_000  # cumulative
        assert v3.nonce == 3 and v3.amount == 450_000
        ch = mgr.get_channel(CID)
        assert ch.nonce == 3
        assert ch.total_paid == 450_000
        assert ch.remaining_balance == 550_000


# ═══════════════════════════════════════════════════════════════════════════
# Multi-channel scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiChannelScenarios:
    async def test_multiple_channels_independent_state(self, wallet_a):
        """Payments on one channel shouldn't affect another."""
        mgr = ChannelManager(wallet_a.address)
        ch1 = mgr.create_channel(CID, RECEIVER, 500_000, "QmA")
        ch2 = mgr.create_channel(CID_2, RECEIVER, 300_000, "QmB")
        ch1.accept(); ch1.activate()
        ch2.accept(); ch2.activate()

        mock_send = AsyncMock()
        await mgr.send_payment(CID, 100_000, wallet_a.private_key, mock_send)
        await mgr.send_payment(CID_2, 50_000, wallet_a.private_key, mock_send)

        assert mgr.get_channel(CID).total_paid == 100_000
        assert mgr.get_channel(CID_2).total_paid == 50_000
        assert mgr.get_channel(CID).nonce == 1
        assert mgr.get_channel(CID_2).nonce == 1

    async def test_close_one_channel_other_unaffected(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        ch1 = mgr.create_channel(CID, RECEIVER, 500_000, "QmA")
        ch2 = mgr.create_channel(CID_2, RECEIVER, 300_000, "QmB")
        ch1.accept(); ch1.activate()
        ch2.accept(); ch2.activate()

        ch1.cooperative_close()
        ch1.settle()

        assert mgr.get_channel(CID).state == ChannelState.SETTLED
        assert mgr.get_channel(CID_2).state == ChannelState.ACTIVE

    def test_list_channels_by_state_mixed(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        ch1 = mgr.create_channel(CID, RECEIVER, 500_000, "QmA")
        ch2 = mgr.create_channel(CID_2, RECEIVER, 300_000, "QmB")
        cid3 = bytes([99]) + b"\x00" * 31
        ch3 = mgr.create_channel(cid3, RECEIVER, 100_000, "QmC")

        ch1.accept(); ch1.activate()  # ACTIVE
        ch2.accept(); ch2.activate(); ch2.request_close()  # CLOSING
        # ch3 stays PROPOSED

        assert len(mgr.list_channels(ChannelState.ACTIVE)) == 1
        assert len(mgr.list_channels(ChannelState.CLOSING)) == 1
        assert len(mgr.list_channels(ChannelState.PROPOSED)) == 1
        assert len(mgr.list_channels(ChannelState.SETTLED)) == 0
        assert len(mgr.list_channels()) == 3


# ═══════════════════════════════════════════════════════════════════════════
# Full lifecycle through manager
# ═══════════════════════════════════════════════════════════════════════════


class TestFullLifecycleThroughManager:
    async def test_create_pay_close_settle(self, wallet_a):
        mgr = ChannelManager(wallet_a.address)
        ch = mgr.create_channel(CID, RECEIVER, 1_000_000, "QmPeer")
        assert ch.state == ChannelState.PROPOSED

        ch.accept()
        assert ch.state == ChannelState.OPEN

        ch.activate()
        assert ch.state == ChannelState.ACTIVE

        mock_send = AsyncMock()
        for i in range(1, 11):
            v = await mgr.send_payment(CID, 50_000, wallet_a.private_key, mock_send)
            assert v.nonce == i
            assert v.amount == i * 50_000

        assert ch.total_paid == 500_000
        assert ch.remaining_balance == 500_000

        ch.cooperative_close()
        assert ch.state == ChannelState.CLOSING

        ch.settle()
        assert ch.state == ChannelState.SETTLED

    async def test_receive_open_then_receive_payments(self, wallet_a, wallet_b):
        """Simulate being the receiver: handle open, then handle payment updates."""
        receiver_mgr = ChannelManager(wallet_b.address)

        # Sender opens
        msg = PaymentOpen(
            channel_id=CID, sender=wallet_a.address, receiver=wallet_b.address,
            total_deposit=500_000,
        )
        ch = await receiver_mgr.handle_open_request(msg, "QmSenderPeer")
        assert ch.state == ChannelState.ACTIVE

        # Sender sends 3 payments
        for i in range(1, 4):
            v = SignedVoucher.create(CID, i, i * 50_000, wallet_a.private_key)
            update = PaymentUpdate(
                channel_id=CID, nonce=v.nonce, amount=v.amount,
                timestamp=v.timestamp, signature=v.signature,
            )
            await receiver_mgr.handle_payment_update(update)

        ch = receiver_mgr.get_channel(CID)
        assert ch.nonce == 3
        assert ch.total_paid == 150_000
        assert ch.remaining_balance == 350_000
