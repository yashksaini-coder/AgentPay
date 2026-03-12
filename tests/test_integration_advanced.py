"""Advanced integration tests for end-to-end payment flows.

Covers: multi-party scenarios, bidirectional channels, full channel
depletion, dispute lifecycle, receiver-side payment verification,
and the send-first-then-commit pattern with network failures.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.channel import ChannelError, ChannelState, PaymentChannel
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.messages import PaymentClose, PaymentOpen, PaymentUpdate


# ═══════════════════════════════════════════════════════════════════════════
# Two-party full flow (sender + receiver managers)
# ═══════════════════════════════════════════════════════════════════════════


class TestTwoPartyFlow:
    """Simulate sender and receiver each with their own ChannelManager."""

    def _setup(self):
        wa = Wallet.generate()
        wb = Wallet.generate()
        return wa, wb, ChannelManager(wa.address), ChannelManager(wb.address)

    async def test_open_pay_close_full_flow(self):
        wa, wb, mgr_a, mgr_b = self._setup()
        cid = bytes(range(32))

        # A creates outbound channel
        ch_a = mgr_a.create_channel(cid, wb.address, 1_000_000, "QmB")
        ch_a.accept()
        ch_a.activate()

        # B receives open request
        open_msg = PaymentOpen(
            channel_id=cid, sender=wa.address, receiver=wb.address,
            total_deposit=1_000_000,
        )
        ch_b = await mgr_b.handle_open_request(open_msg, "QmA")
        assert ch_b.state == ChannelState.ACTIVE

        # A sends 5 payments
        mock_send = AsyncMock()
        for i in range(5):
            voucher = await mgr_a.send_payment(cid, 100_000, wa.private_key, mock_send)

            # B receives each update
            update = PaymentUpdate(
                channel_id=cid, nonce=voucher.nonce, amount=voucher.amount,
                timestamp=voucher.timestamp, signature=voucher.signature,
            )
            await mgr_b.handle_payment_update(update)

        # Both sides agree on state
        assert mgr_a.get_channel(cid).nonce == 5
        assert mgr_b.get_channel(cid).nonce == 5
        assert mgr_a.get_channel(cid).total_paid == 500_000
        assert mgr_b.get_channel(cid).total_paid == 500_000

        # Cooperative close
        close_msg = PaymentClose(
            channel_id=cid, final_nonce=5, final_amount=500_000, cooperative=True,
        )
        await mgr_b.handle_close_request(close_msg)
        assert mgr_b.get_channel(cid).state == ChannelState.CLOSING

        # Settle
        mgr_a.get_channel(cid).cooperative_close()
        mgr_a.get_channel(cid).settle()
        mgr_b.get_channel(cid).settle()
        assert mgr_a.get_channel(cid).state == ChannelState.SETTLED
        assert mgr_b.get_channel(cid).state == ChannelState.SETTLED

    async def test_receiver_rejects_wrong_sender_signature(self):
        """If attacker signs voucher instead of real sender, receiver rejects."""
        wa, wb, mgr_a, mgr_b = self._setup()
        attacker = Wallet.generate()
        cid = bytes(range(32))

        # B opens channel with A as sender
        open_msg = PaymentOpen(
            channel_id=cid, sender=wa.address, receiver=wb.address,
            total_deposit=1_000_000,
        )
        await mgr_b.handle_open_request(open_msg, "QmA")

        # Attacker signs the voucher (not A)
        v = SignedVoucher.create(cid, 1, 100_000, attacker.private_key)
        update = PaymentUpdate(
            channel_id=cid, nonce=v.nonce, amount=v.amount,
            timestamp=v.timestamp, signature=v.signature,
        )
        with pytest.raises(ValueError, match="Invalid voucher signature"):
            await mgr_b.handle_payment_update(update)

    async def test_full_channel_depletion(self):
        """Pay the entire deposit, then verify no more payments possible."""
        wa, wb, mgr_a, mgr_b = self._setup()
        cid = bytes(range(32))
        deposit = 500_000

        ch_a = mgr_a.create_channel(cid, wb.address, deposit, "QmB")
        ch_a.accept()
        ch_a.activate()

        mock_send = AsyncMock()
        # Pay full deposit
        await mgr_a.send_payment(cid, deposit, wa.private_key, mock_send)
        assert mgr_a.get_channel(cid).remaining_balance == 0

        # Any further payment should fail
        with pytest.raises(ChannelError, match="exceeds deposit"):
            await mgr_a.send_payment(cid, 1, wa.private_key, mock_send)


# ═══════════════════════════════════════════════════════════════════════════
# Bidirectional channels (A → B and B → A simultaneously)
# ═══════════════════════════════════════════════════════════════════════════


class TestBidirectionalChannels:
    async def test_two_channels_opposite_directions(self):
        wa, wb = Wallet.generate(), Wallet.generate()
        mgr_a = ChannelManager(wa.address)
        mgr_b = ChannelManager(wb.address)

        cid_ab = bytes([0x01]) + b"\x00" * 31  # A → B
        cid_ba = bytes([0x02]) + b"\x00" * 31  # B → A

        # A → B channel
        ch_ab_a = mgr_a.create_channel(cid_ab, wb.address, 500_000, "QmB")
        ch_ab_a.accept()
        ch_ab_a.activate()

        # B → A channel
        ch_ba_b = mgr_b.create_channel(cid_ba, wa.address, 300_000, "QmA")
        ch_ba_b.accept()
        ch_ba_b.activate()

        mock_send = AsyncMock()

        # A pays B 100k
        v1 = await mgr_a.send_payment(cid_ab, 100_000, wa.private_key, mock_send)
        # B pays A 50k
        v2 = await mgr_b.send_payment(cid_ba, 50_000, wb.private_key, mock_send)

        assert mgr_a.get_channel(cid_ab).total_paid == 100_000
        assert mgr_b.get_channel(cid_ba).total_paid == 50_000
        assert v1.verify(wa.address)
        assert v2.verify(wb.address)

    async def test_channels_independent_nonces(self):
        wa, wb = Wallet.generate(), Wallet.generate()
        mgr_a = ChannelManager(wa.address)

        cid1 = bytes([0x01]) + b"\x00" * 31
        cid2 = bytes([0x02]) + b"\x00" * 31

        for cid in [cid1, cid2]:
            ch = mgr_a.create_channel(cid, wb.address, 1_000_000, "QmB")
            ch.accept()
            ch.activate()

        mock_send = AsyncMock()
        await mgr_a.send_payment(cid1, 100, wa.private_key, mock_send)
        await mgr_a.send_payment(cid1, 200, wa.private_key, mock_send)
        await mgr_a.send_payment(cid2, 50, wa.private_key, mock_send)

        assert mgr_a.get_channel(cid1).nonce == 2
        assert mgr_a.get_channel(cid2).nonce == 1


# ═══════════════════════════════════════════════════════════════════════════
# Dispute scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestDisputeScenarios:
    def test_dispute_from_active_then_settle(self):
        w = Wallet.generate()
        ch = PaymentChannel(
            channel_id=bytes(range(32)),
            sender=w.address,
            receiver="0x" + "ab" * 20,
            total_deposit=1_000_000,
        )
        ch.accept()
        ch.activate()
        ch.dispute()
        assert ch.state == ChannelState.DISPUTED
        ch.close_expiration = 0  # Expire challenge for test
        ch.settle()
        assert ch.state == ChannelState.SETTLED

    def test_dispute_from_closing_then_settle(self):
        w = Wallet.generate()
        ch = PaymentChannel(
            channel_id=bytes(range(32)),
            sender=w.address,
            receiver="0x" + "ab" * 20,
            total_deposit=1_000_000,
        )
        ch.accept()
        ch.activate()
        ch.request_close()
        ch.dispute()
        assert ch.state == ChannelState.DISPUTED
        # For test: set expiration to past so settle works
        ch.close_expiration = 0
        ch.settle()
        assert ch.state == ChannelState.SETTLED

    def test_cannot_pay_after_dispute(self):
        w = Wallet.from_private_key(
            "0x4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
        )
        cid = bytes(range(32))
        ch = PaymentChannel(
            channel_id=cid, sender=w.address,
            receiver="0x" + "ab" * 20, total_deposit=1_000_000,
        )
        ch.accept()
        ch.activate()
        ch.dispute()
        v = SignedVoucher.create(cid, 1, 100, w.private_key)
        with pytest.raises(ChannelError, match="DISPUTED"):
            ch.apply_voucher(v)


# ═══════════════════════════════════════════════════════════════════════════
# Network failure resilience
# ═══════════════════════════════════════════════════════════════════════════


class TestNetworkFailureResilience:
    async def test_send_failure_leaves_channel_unchanged(self):
        """If send_fn fails, nonce and total_paid must not advance."""
        wa = Wallet.generate()
        mgr = ChannelManager(wa.address)
        cid = bytes(range(32))
        ch = mgr.create_channel(cid, "0x" + "bb" * 20, 1_000_000, "QmPeer")
        ch.accept()
        ch.activate()

        # First payment succeeds
        mock_ok = AsyncMock()
        await mgr.send_payment(cid, 100_000, wa.private_key, mock_ok)
        assert ch.nonce == 1

        # Second payment fails at network layer
        mock_fail = AsyncMock(side_effect=ConnectionError("timeout"))
        with pytest.raises(ConnectionError):
            await mgr.send_payment(cid, 200_000, wa.private_key, mock_fail)

        # State must still be at nonce 1, 100k paid
        assert ch.nonce == 1
        assert ch.total_paid == 100_000

        # Third payment should succeed with nonce 2 (not 3)
        await mgr.send_payment(cid, 200_000, wa.private_key, mock_ok)
        assert ch.nonce == 2
        assert ch.total_paid == 300_000

    async def test_multiple_failures_dont_corrupt_state(self):
        wa = Wallet.generate()
        mgr = ChannelManager(wa.address)
        cid = bytes(range(32))
        ch = mgr.create_channel(cid, "0x" + "cc" * 20, 1_000_000, "QmPeer")
        ch.accept()
        ch.activate()

        mock_fail = AsyncMock(side_effect=IOError("network"))
        for _ in range(10):
            with pytest.raises(IOError):
                await mgr.send_payment(cid, 50_000, wa.private_key, mock_fail)

        # No progress
        assert ch.nonce == 0
        assert ch.total_paid == 0

        # Recovery
        mock_ok = AsyncMock()
        await mgr.send_payment(cid, 50_000, wa.private_key, mock_ok)
        assert ch.nonce == 1
        assert ch.total_paid == 50_000


# ═══════════════════════════════════════════════════════════════════════════
# Voucher verification across the full pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestVoucherVerificationPipeline:
    def test_voucher_from_create_verifies(self):
        w = Wallet.generate()
        cid = bytes(range(32))
        v = SignedVoucher.create(cid, 1, 1000, w.private_key)
        assert v.verify(w.address)

    def test_voucher_survives_dict_roundtrip_and_verifies(self):
        w = Wallet.generate()
        cid = bytes(range(32))
        v = SignedVoucher.create(cid, 5, 50000, w.private_key)

        # Serialize → deserialize (simulates wire transport)
        d = v.to_dict()
        restored = SignedVoucher.from_dict(d)

        assert restored.verify(w.address)
        assert not restored.verify(Wallet.generate().address)

    def test_json_dict_loses_bytes_but_hex_is_consistent(self):
        w = Wallet.generate()
        cid = bytes(range(32))
        v = SignedVoucher.create(cid, 1, 1000, w.private_key)

        jd = v.to_json_dict()
        assert jd["channel_id"] == cid.hex()
        assert bytes.fromhex(jd["channel_id"]) == cid
        assert bytes.fromhex(jd["signature"]) == v.signature

    async def test_send_payment_voucher_verifiable_by_receiver(self):
        wa = Wallet.generate()
        wb = Wallet.generate()
        mgr = ChannelManager(wa.address)
        cid = bytes(range(32))
        mgr.create_channel(cid, wb.address, 1_000_000, "QmB")
        mgr.get_channel(cid).accept()
        mgr.get_channel(cid).activate()

        mock_send = AsyncMock()
        voucher = await mgr.send_payment(cid, 100_000, wa.private_key, mock_send)

        # Receiver verifies
        assert voucher.verify(wa.address)
        assert not voucher.verify(wb.address)

    def test_many_wallets_cross_verification(self):
        """Generate 5 wallets, sign vouchers, verify no cross-contamination."""
        wallets = [Wallet.generate() for _ in range(5)]
        cid = bytes(range(32))

        vouchers = [
            SignedVoucher.create(cid, i + 1, (i + 1) * 100, w.private_key)
            for i, w in enumerate(wallets)
        ]

        for i, v in enumerate(vouchers):
            for j, w in enumerate(wallets):
                if i == j:
                    assert v.verify(w.address), f"Voucher {i} should verify for wallet {j}"
                else:
                    assert not v.verify(w.address), f"Voucher {i} should NOT verify for wallet {j}"
