"""Tests for the dispute system."""

from __future__ import annotations

import os


from agentic_payments.disputes.models import Dispute, DisputeReason, DisputeResolution
from agentic_payments.disputes.monitor import DisputeMonitor
from agentic_payments.payments.channel import PaymentChannel
from agentic_payments.payments.manager import ChannelManager
from agentic_payments.reputation.tracker import ReputationTracker


SENDER = "0xSenderAddress1234567890"
RECEIVER = "0xReceiverAddress1234567890"


def _make_channel_id() -> bytes:
    return os.urandom(32)


def _make_channel(channel_id: bytes, **kwargs) -> PaymentChannel:
    defaults = {
        "channel_id": channel_id,
        "sender": SENDER,
        "receiver": RECEIVER,
        "total_deposit": 100_000,
    }
    defaults.update(kwargs)
    return PaymentChannel(**defaults)


def _make_monitor(local_address: str = RECEIVER) -> tuple[DisputeMonitor, ChannelManager]:
    cm = ChannelManager(local_address=local_address)
    rep = ReputationTracker()
    mon = DisputeMonitor(channel_manager=cm, reputation_tracker=rep)
    return mon, cm


def test_dispute_serialization_roundtrip():
    cid = _make_channel_id()
    d = Dispute(
        channel_id=cid,
        initiated_by="peer-A",
        counterparty="peer-B",
        reason=DisputeReason.STALE_VOUCHER,
        evidence_nonce=5,
        evidence_amount=5000,
        slash_amount=1000,
    )
    data = d.to_dict()
    restored = Dispute.from_dict(data)
    assert restored.channel_id == cid
    assert restored.initiated_by == "peer-A"
    assert restored.counterparty == "peer-B"
    assert restored.reason == DisputeReason.STALE_VOUCHER
    assert restored.evidence_nonce == 5
    assert restored.evidence_amount == 5000
    assert restored.slash_amount == 1000
    assert restored.resolution == DisputeResolution.PENDING


def test_scan_channels_no_closing_channels():
    mon, _cm = _make_monitor()
    disputes = mon.scan_channels()
    assert disputes == []


def test_scan_channels_detects_stale_voucher():
    mon, cm = _make_monitor(local_address=RECEIVER)
    cid = _make_channel_id()
    ch = _make_channel(cid, sender=SENDER, receiver=RECEIVER, total_deposit=100_000)
    # Advance channel to CLOSING with a stale nonce
    ch.accept()
    ch.activate()
    ch.nonce = 10
    ch.total_paid = 5000
    ch.request_close()
    # Simulate: our local nonce is higher than the closing nonce
    ch.nonce = 15
    ch.total_paid = 8000
    cm.channels[cid] = ch

    disputes = mon.scan_channels()
    assert len(disputes) == 1
    assert disputes[0].reason == DisputeReason.STALE_VOUCHER
    assert disputes[0].evidence_nonce == 15
    assert disputes[0].channel_id == cid


def test_scan_channels_ignores_sender_side():
    """Sender-side closing channels should NOT trigger disputes (only receiver detects stale)."""
    mon, cm = _make_monitor(local_address=SENDER)
    cid = _make_channel_id()
    ch = _make_channel(cid, sender=SENDER, receiver=RECEIVER, total_deposit=100_000)
    ch.accept()
    ch.activate()
    ch.nonce = 10
    ch.total_paid = 5000
    ch.request_close()
    ch.nonce = 15  # higher nonce, but we're the sender — no dispute
    cm.channels[cid] = ch

    disputes = mon.scan_channels()
    assert disputes == []


def test_file_dispute_creates_dispute():
    mon, cm = _make_monitor()
    cid = _make_channel_id()
    ch = _make_channel(cid, total_deposit=50_000)
    ch.accept()
    ch.activate()
    ch.nonce = 3
    ch.total_paid = 2000
    cm.channels[cid] = ch

    dispute = mon.file_dispute(
        channel_id=cid,
        reason=DisputeReason.SLA_VIOLATION,
        initiated_by=RECEIVER,
        counterparty=SENDER,
    )
    assert dispute.reason == DisputeReason.SLA_VIOLATION
    assert dispute.channel_id == cid
    assert dispute.slash_amount == int(50_000 * 0.10)
    assert dispute.resolution == DisputeResolution.PENDING


def test_resolve_dispute_updates_resolution():
    mon, cm = _make_monitor()
    cid = _make_channel_id()
    ch = _make_channel(cid, total_deposit=50_000)
    ch.accept()
    ch.activate()
    cm.channels[cid] = ch

    dispute = mon.file_dispute(
        channel_id=cid,
        reason=DisputeReason.UNRESPONSIVE,
        initiated_by=RECEIVER,
        counterparty=SENDER,
    )
    resolved = mon.resolve_dispute(dispute.dispute_id, DisputeResolution.CHALLENGER_WINS)
    assert resolved.resolution == DisputeResolution.CHALLENGER_WINS
    assert resolved.resolved_at > 0


def test_list_disputes_pending_only():
    mon, cm = _make_monitor()
    cid1 = _make_channel_id()
    cid2 = _make_channel_id()
    ch1 = _make_channel(cid1, total_deposit=50_000)
    ch2 = _make_channel(cid2, total_deposit=50_000)
    ch1.accept()
    ch1.activate()
    ch2.accept()
    ch2.activate()
    cm.channels[cid1] = ch1
    cm.channels[cid2] = ch2

    d1 = mon.file_dispute(cid1, DisputeReason.STALE_VOUCHER, RECEIVER, SENDER)
    d2 = mon.file_dispute(cid2, DisputeReason.DOUBLE_SPEND, RECEIVER, SENDER)
    mon.resolve_dispute(d1.dispute_id, DisputeResolution.SETTLED)

    all_disputes = mon.list_disputes(pending_only=False)
    assert len(all_disputes) == 2

    pending = mon.list_disputes(pending_only=True)
    assert len(pending) == 1
    assert pending[0].dispute_id == d2.dispute_id


def test_dispute_reason_enum_values():
    assert DisputeReason.STALE_VOUCHER == "stale_voucher"
    assert DisputeReason.SLA_VIOLATION == "sla_violation"
    assert DisputeReason.DOUBLE_SPEND == "double_spend"
    assert DisputeReason.UNRESPONSIVE == "unresponsive"


def test_dispute_resolution_enum_values():
    assert DisputeResolution.PENDING == "pending"
    assert DisputeResolution.CHALLENGER_WINS == "challenger_wins"
    assert DisputeResolution.RESPONDER_WINS == "responder_wins"
    assert DisputeResolution.SETTLED == "settled"
