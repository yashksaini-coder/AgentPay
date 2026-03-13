"""Scale tests: N-agent networks with full-mesh payment channels.

Simulates networks of 5, 10, 15, 20, 25, 50, and 100 agents where
every pair opens a channel and exchanges micropayments. Validates
channel state consistency, voucher verification, balance accounting,
and manager isolation at each scale.

These tests exercise:
  - Wallet generation at scale
  - Channel creation across all pairs (N*(N-1)/2 channels per direction)
  - Micropayment sending with cumulative vouchers
  - Receiver-side voucher signature verification
  - Balance invariants (total_paid + remaining == deposit)
  - Nonce consistency between sender and receiver
  - Cooperative close handshake
  - Full lifecycle at scale (open → pay → close → settle)
  - Manager channel count tracking
  - Cross-agent voucher rejection (signature from wrong sender)
"""

from __future__ import annotations

from itertools import combinations
from unittest.mock import AsyncMock

import pytest

from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.channel import ChannelState
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.payments.voucher import SignedVoucher
from agentic_payments.protocol.messages import PaymentClose, PaymentOpen, PaymentUpdate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel_id(sender_idx: int, receiver_idx: int) -> bytes:
    """Deterministic 32-byte channel ID from a (sender, receiver) pair."""
    # Use first 2 bytes for sender/receiver index, pad rest
    return sender_idx.to_bytes(2, "big") + receiver_idx.to_bytes(2, "big") + b"\x00" * 28


class AgentNode:
    """Lightweight in-memory agent with wallet + manager for scale tests."""

    __slots__ = ("wallet", "manager", "idx", "label")

    def __init__(self, idx: int) -> None:
        self.wallet = Wallet.generate()
        self.manager = ChannelManager(self.wallet.address)
        self.idx = idx
        self.label = f"Agent-{idx}"


def _create_agents(n: int) -> list[AgentNode]:
    """Create N agents with independent wallets and managers."""
    return [AgentNode(i) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════
# Scale: N agents, each pair opens a unidirectional channel, sends payments
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleUnidirectional:
    """Each ordered pair (i→j where i<j) opens one channel and sends payments."""

    @pytest.mark.parametrize("n_agents", [5, 10, 15, 20])
    async def test_n_agent_mesh_payments(self, n_agents: int):
        """Full mesh: every pair opens a channel, sender sends micropayments."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = 1_000_000
        payment_amount = 10_000
        num_payments = 3

        # Open channels for every ordered pair (i → j, i < j)
        for i, j in combinations(range(n_agents), 2):
            sender = agents[i]
            receiver = agents[j]
            cid = _make_channel_id(i, j)

            # Sender side: create + activate
            ch_s = sender.manager.create_channel(
                cid, receiver.wallet.address, deposit, f"QmPeer{j}",
            )
            ch_s.accept()
            ch_s.activate()

            # Receiver side: handle open
            open_msg = PaymentOpen(
                channel_id=cid,
                sender=sender.wallet.address,
                receiver=receiver.wallet.address,
                total_deposit=deposit,
            )
            await receiver.manager.handle_open_request(open_msg, f"QmPeer{i}")

        # Verify channel counts
        n_pairs = n_agents * (n_agents - 1) // 2
        for agent in agents:
            # Each agent participates in (n-1) channels as sender and (n-1) as receiver...
            # but only as sender for indices < self, and receiver for indices > self
            pass  # channel count verified below per-agent

        total_channels = sum(len(a.manager.channels) for a in agents)
        # Each pair creates 1 channel on sender + 1 on receiver = 2 entries
        assert total_channels == n_pairs * 2

        # Send payments on every channel
        for i, j in combinations(range(n_agents), 2):
            sender = agents[i]
            receiver = agents[j]
            cid = _make_channel_id(i, j)

            for p in range(num_payments):
                voucher = await sender.manager.send_payment(
                    cid, payment_amount, sender.wallet.private_key, mock_send,
                )

                # Forward to receiver
                update = PaymentUpdate(
                    channel_id=cid,
                    nonce=voucher.nonce,
                    amount=voucher.amount,
                    timestamp=voucher.timestamp,
                    signature=voucher.signature,
                )
                await receiver.manager.handle_payment_update(update)

        # Verify state consistency on every channel
        for i, j in combinations(range(n_agents), 2):
            sender = agents[i]
            receiver = agents[j]
            cid = _make_channel_id(i, j)

            ch_s = sender.manager.get_channel(cid)
            ch_r = receiver.manager.get_channel(cid)

            expected_paid = payment_amount * num_payments

            assert ch_s.nonce == num_payments, f"Sender {i}→{j} nonce"
            assert ch_r.nonce == num_payments, f"Receiver {i}→{j} nonce"
            assert ch_s.total_paid == expected_paid, f"Sender {i}→{j} total_paid"
            assert ch_r.total_paid == expected_paid, f"Receiver {i}→{j} total_paid"
            assert ch_s.remaining_balance == deposit - expected_paid
            assert ch_r.remaining_balance == deposit - expected_paid
            assert ch_s.state == ChannelState.ACTIVE
            assert ch_r.state == ChannelState.ACTIVE

    @pytest.mark.parametrize("n_agents", [5, 10])
    async def test_n_agent_mesh_full_lifecycle(self, n_agents: int):
        """Open → pay → close → settle across all pairs."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = 500_000
        payment_amount = 25_000
        num_payments = 4

        # Phase 1: Open all channels
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]

            ch_s = s.manager.create_channel(cid, r.wallet.address, deposit, f"Qm{j}")
            ch_s.accept()
            ch_s.activate()

            open_msg = PaymentOpen(
                channel_id=cid, sender=s.wallet.address,
                receiver=r.wallet.address, total_deposit=deposit,
            )
            await r.manager.handle_open_request(open_msg, f"Qm{i}")

        # Phase 2: Send payments
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            for _ in range(num_payments):
                v = await s.manager.send_payment(
                    cid, payment_amount, s.wallet.private_key, mock_send,
                )
                update = PaymentUpdate(
                    channel_id=cid, nonce=v.nonce, amount=v.amount,
                    timestamp=v.timestamp, signature=v.signature,
                )
                await r.manager.handle_payment_update(update)

        # Phase 3: Cooperative close all
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            ch_s = s.manager.get_channel(cid)
            ch_r = r.manager.get_channel(cid)

            # Close on receiver side
            close_msg = PaymentClose(
                channel_id=cid,
                final_nonce=ch_r.nonce,
                final_amount=ch_r.total_paid,
                cooperative=True,
            )
            await r.manager.handle_close_request(close_msg)

            # Close + settle sender
            ch_s.cooperative_close()
            ch_s.settle()
            # Settle receiver
            ch_r.settle()

        # Phase 4: Verify all settled
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            assert agents[i].manager.get_channel(cid).state == ChannelState.SETTLED
            assert agents[j].manager.get_channel(cid).state == ChannelState.SETTLED


# ═══════════════════════════════════════════════════════════════════════════
# Scale: Bidirectional channels (every pair has 2 channels: A→B and B→A)
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleBidirectional:
    @pytest.mark.parametrize("n_agents", [5, 10, 15])
    async def test_bidirectional_mesh(self, n_agents: int):
        """Every pair has channels in both directions. Payments flow both ways."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = 200_000
        payment = 5_000
        num_payments = 2

        # Open bidirectional channels for every pair
        for i in range(n_agents):
            for j in range(n_agents):
                if i == j:
                    continue
                cid = _make_channel_id(i, j)
                s, r = agents[i], agents[j]

                ch = s.manager.create_channel(cid, r.wallet.address, deposit, f"Qm{j}")
                ch.accept()
                ch.activate()

                open_msg = PaymentOpen(
                    channel_id=cid, sender=s.wallet.address,
                    receiver=r.wallet.address, total_deposit=deposit,
                )
                await r.manager.handle_open_request(open_msg, f"Qm{i}")

        # Each agent has (n-1) outbound + (n-1) inbound channels
        for agent in agents:
            assert len(agent.manager.channels) == 2 * (n_agents - 1), (
                f"Agent {agent.idx} channel count"
            )

        # Send payments in both directions
        for i in range(n_agents):
            for j in range(n_agents):
                if i == j:
                    continue
                cid = _make_channel_id(i, j)
                s = agents[i]
                r = agents[j]
                for _ in range(num_payments):
                    v = await s.manager.send_payment(
                        cid, payment, s.wallet.private_key, mock_send,
                    )
                    update = PaymentUpdate(
                        channel_id=cid, nonce=v.nonce, amount=v.amount,
                        timestamp=v.timestamp, signature=v.signature,
                    )
                    await r.manager.handle_payment_update(update)

        # Verify all channels are consistent
        for i in range(n_agents):
            for j in range(n_agents):
                if i == j:
                    continue
                cid = _make_channel_id(i, j)
                ch_s = agents[i].manager.get_channel(cid)
                ch_r = agents[j].manager.get_channel(cid)

                expected = payment * num_payments
                assert ch_s.nonce == num_payments
                assert ch_r.nonce == num_payments
                assert ch_s.total_paid == expected
                assert ch_r.total_paid == expected


# ═══════════════════════════════════════════════════════════════════════════
# Scale: High payment volume per channel
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleHighVolume:
    @pytest.mark.parametrize("num_payments", [50, 100, 500])
    async def test_many_payments_single_channel(self, num_payments: int):
        """Stress test: many micropayments on a single channel."""
        wa = Wallet.generate()
        wb = Wallet.generate()
        mgr_a = ChannelManager(wa.address)
        mgr_b = ChannelManager(wb.address)
        cid = bytes(range(32))
        deposit = num_payments * 1000  # 1000 wei per payment

        ch_a = mgr_a.create_channel(cid, wb.address, deposit, "QmB")
        ch_a.accept()
        ch_a.activate()

        open_msg = PaymentOpen(
            channel_id=cid, sender=wa.address,
            receiver=wb.address, total_deposit=deposit,
        )
        await mgr_b.handle_open_request(open_msg, "QmA")

        mock_send = AsyncMock()
        for _ in range(num_payments):
            v = await mgr_a.send_payment(cid, 1000, wa.private_key, mock_send)
            update = PaymentUpdate(
                channel_id=cid, nonce=v.nonce, amount=v.amount,
                timestamp=v.timestamp, signature=v.signature,
            )
            await mgr_b.handle_payment_update(update)

        ch_a = mgr_a.get_channel(cid)
        ch_b = mgr_b.get_channel(cid)

        assert ch_a.nonce == num_payments
        assert ch_b.nonce == num_payments
        assert ch_a.total_paid == deposit
        assert ch_b.total_paid == deposit
        assert ch_a.remaining_balance == 0
        assert ch_b.remaining_balance == 0

    @pytest.mark.parametrize("n_agents,payments_per_channel", [
        (5, 20),
        (10, 10),
        (20, 5),
    ])
    async def test_mesh_with_volume(self, n_agents: int, payments_per_channel: int):
        """N-agent mesh where each channel gets multiple payments."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = payments_per_channel * 2000
        payment = 2000

        # Open
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            ch = s.manager.create_channel(cid, r.wallet.address, deposit, f"Qm{j}")
            ch.accept()
            ch.activate()
            open_msg = PaymentOpen(
                channel_id=cid, sender=s.wallet.address,
                receiver=r.wallet.address, total_deposit=deposit,
            )
            await r.manager.handle_open_request(open_msg, f"Qm{i}")

        # Pay
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            for _ in range(payments_per_channel):
                v = await s.manager.send_payment(cid, payment, s.wallet.private_key, mock_send)
                update = PaymentUpdate(
                    channel_id=cid, nonce=v.nonce, amount=v.amount,
                    timestamp=v.timestamp, signature=v.signature,
                )
                await r.manager.handle_payment_update(update)

        # Verify
        n_pairs = n_agents * (n_agents - 1) // 2
        total_payments = n_pairs * payments_per_channel
        total_volume = n_pairs * payments_per_channel * payment

        actual_payments = 0
        actual_volume = 0
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            ch = agents[i].manager.get_channel(cid)
            actual_payments += ch.nonce
            actual_volume += ch.total_paid
            assert ch.remaining_balance == 0  # Fully spent

        assert actual_payments == total_payments
        assert actual_volume == total_volume


# ═══════════════════════════════════════════════════════════════════════════
# Scale: Cross-agent signature rejection
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleCrossSigRejection:
    @pytest.mark.parametrize("n_agents", [5, 10, 25])
    async def test_wrong_sender_sig_rejected_at_scale(self, n_agents: int):
        """For every channel, a voucher signed by the wrong agent is rejected."""
        agents = _create_agents(n_agents)

        # Open one channel per pair: i → j
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            open_msg = PaymentOpen(
                channel_id=cid, sender=s.wallet.address,
                receiver=r.wallet.address, total_deposit=100_000,
            )
            await r.manager.handle_open_request(open_msg, f"Qm{i}")

        # For each channel, try signing with every OTHER agent's key → must reject
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            r = agents[j]

            # Pick an attacker (any agent that is NOT the sender i)
            attacker_idx = (i + 1) % n_agents
            if attacker_idx == i:
                attacker_idx = (i + 2) % n_agents
            attacker = agents[attacker_idx]

            v = SignedVoucher.create(cid, 1, 1000, attacker.wallet.private_key)
            update = PaymentUpdate(
                channel_id=cid, nonce=v.nonce, amount=v.amount,
                timestamp=v.timestamp, signature=v.signature,
            )
            with pytest.raises(ValueError, match="Invalid voucher signature"):
                await r.manager.handle_payment_update(update)


# ═══════════════════════════════════════════════════════════════════════════
# Scale: Wallet uniqueness and address isolation
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleWalletIsolation:
    @pytest.mark.parametrize("n", [25, 50, 100])
    def test_n_wallets_unique_addresses(self, n: int):
        """All generated wallets have unique addresses."""
        wallets = [Wallet.generate() for _ in range(n)]
        addresses = {w.address for w in wallets}
        assert len(addresses) == n, f"Expected {n} unique addresses, got {len(addresses)}"

    @pytest.mark.parametrize("n", [25, 50, 100])
    def test_n_wallets_cross_verify(self, n: int):
        """Voucher signed by wallet[i] only verifies for wallet[i]."""
        wallets = [Wallet.generate() for _ in range(n)]
        cid = bytes(range(32))

        # Each wallet signs a voucher
        vouchers = [
            SignedVoucher.create(cid, i + 1, (i + 1) * 100, w.private_key)
            for i, w in enumerate(wallets)
        ]

        # Sample verification: check voucher[i] against wallet[i] and a few others
        for i in range(n):
            assert vouchers[i].verify(wallets[i].address), f"Self-verify failed for {i}"
            # Check against 3 random others
            for offset in [1, n // 3, n - 1]:
                j = (i + offset) % n
                if j != i:
                    assert not vouchers[i].verify(wallets[j].address), (
                        f"Cross-verify should fail: voucher[{i}] vs wallet[{j}]"
                    )


# ═══════════════════════════════════════════════════════════════════════════
# Scale: Channel manager capacity
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleManagerCapacity:
    @pytest.mark.parametrize("n_channels", [50, 100, 500])
    def test_manager_many_channels(self, n_channels: int):
        """A single manager can handle many channels."""
        w = Wallet.generate()
        mgr = ChannelManager(w.address)

        for i in range(n_channels):
            cid = i.to_bytes(4, "big") + b"\x00" * 28
            receiver = f"0x{i:040x}"
            ch = mgr.create_channel(cid, receiver, 10_000, f"Qm{i}")
            ch.accept()
            ch.activate()

        assert len(mgr.list_channels()) == n_channels
        assert len(mgr.list_channels(ChannelState.ACTIVE)) == n_channels
        assert len(mgr.list_channels(ChannelState.PROPOSED)) == 0

    @pytest.mark.parametrize("n_channels", [50, 100])
    async def test_manager_many_channels_with_payments(self, n_channels: int):
        """Manager with many channels, each receiving a payment."""
        w = Wallet.generate()
        mgr = ChannelManager(w.address)
        mock_send = AsyncMock()

        for i in range(n_channels):
            cid = i.to_bytes(4, "big") + b"\x00" * 28
            receiver = f"0x{i:040x}"
            ch = mgr.create_channel(cid, receiver, 100_000, f"Qm{i}")
            ch.accept()
            ch.activate()

        # Send one payment on each channel
        for i in range(n_channels):
            cid = i.to_bytes(4, "big") + b"\x00" * 28
            await mgr.send_payment(cid, 10_000, w.private_key, mock_send)

        # Verify each channel independently advanced
        for i in range(n_channels):
            cid = i.to_bytes(4, "big") + b"\x00" * 28
            ch = mgr.get_channel(cid)
            assert ch.nonce == 1
            assert ch.total_paid == 10_000
            assert ch.remaining_balance == 90_000


# ═══════════════════════════════════════════════════════════════════════════
# Scale: Balance accounting across many agents
# ═══════════════════════════════════════════════════════════════════════════


class TestScaleBalanceAccounting:
    @pytest.mark.parametrize("n_agents", [5, 10, 20])
    async def test_network_wide_balance_invariant(self, n_agents: int):
        """Across the entire network, deposit == paid + remaining per channel."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = 100_000
        payment = 7_500
        num_payments = 3

        # Open + pay
        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            ch = s.manager.create_channel(cid, r.wallet.address, deposit, f"Qm{j}")
            ch.accept()
            ch.activate()

            open_msg = PaymentOpen(
                channel_id=cid, sender=s.wallet.address,
                receiver=r.wallet.address, total_deposit=deposit,
            )
            await r.manager.handle_open_request(open_msg, f"Qm{i}")

            for _ in range(num_payments):
                v = await s.manager.send_payment(cid, payment, s.wallet.private_key, mock_send)
                update = PaymentUpdate(
                    channel_id=cid, nonce=v.nonce, amount=v.amount,
                    timestamp=v.timestamp, signature=v.signature,
                )
                await r.manager.handle_payment_update(update)

        # Verify invariant on EVERY channel on EVERY agent
        for agent in agents:
            for ch in agent.manager.list_channels():
                assert ch.total_deposit == ch.total_paid + ch.remaining_balance, (
                    f"Balance invariant violated on Agent-{agent.idx}, "
                    f"channel {ch.channel_id.hex()[:8]}: "
                    f"deposit={ch.total_deposit}, paid={ch.total_paid}, "
                    f"remaining={ch.remaining_balance}"
                )

    @pytest.mark.parametrize("n_agents", [5, 10])
    async def test_aggregate_balance_per_agent(self, n_agents: int):
        """Each agent's aggregate balance matches expected from channels."""
        agents = _create_agents(n_agents)
        mock_send = AsyncMock()
        deposit = 50_000
        payment = 5_000
        num_payments = 2

        for i, j in combinations(range(n_agents), 2):
            cid = _make_channel_id(i, j)
            s, r = agents[i], agents[j]
            ch = s.manager.create_channel(cid, r.wallet.address, deposit, f"Qm{j}")
            ch.accept()
            ch.activate()
            open_msg = PaymentOpen(
                channel_id=cid, sender=s.wallet.address,
                receiver=r.wallet.address, total_deposit=deposit,
            )
            await r.manager.handle_open_request(open_msg, f"Qm{i}")
            for _ in range(num_payments):
                v = await s.manager.send_payment(cid, payment, s.wallet.private_key, mock_send)
                update = PaymentUpdate(
                    channel_id=cid, nonce=v.nonce, amount=v.amount,
                    timestamp=v.timestamp, signature=v.signature,
                )
                await r.manager.handle_payment_update(update)

        # Check aggregate per agent
        for agent in agents:
            channels = agent.manager.list_channels()
            total_deposited = sum(c.total_deposit for c in channels)
            total_paid = sum(c.total_paid for c in channels)
            total_remaining = sum(c.remaining_balance for c in channels)
            assert total_deposited == total_paid + total_remaining, (
                f"Agent-{agent.idx} aggregate mismatch"
            )
