"""Tests for protocol message encoding/decoding and codec."""

from __future__ import annotations

import pytest

from agentic_payments.protocol.codec import decode_payload, encode_message
from agentic_payments.protocol.messages import (
    MessageType,
    PaymentAck,
    PaymentClose,
    PaymentOpen,
    PaymentUpdate,
    from_wire,
    to_wire,
)

# Valid test addresses for wire validation
SENDER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
RECEIVER = "0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf"


class TestCodec:
    def test_encode_decode_roundtrip(self):
        """Message should survive encode -> decode round-trip."""
        data = {"type": 1, "data": {"key": "value", "number": 42}}
        encoded = encode_message(data)
        # Skip 4-byte length header
        decoded = decode_payload(encoded[4:])
        assert decoded == data

    def test_length_prefix(self):
        """Encoded message should start with 4-byte length prefix."""
        data = {"hello": "world"}
        encoded = encode_message(data)
        import struct

        (length,) = struct.unpack(">I", encoded[:4])
        assert length == len(encoded) - 4

    def test_empty_message(self):
        data = {}
        encoded = encode_message(data)
        decoded = decode_payload(encoded[4:])
        assert decoded == {}


class TestMessages:
    def test_payment_open_roundtrip(self):
        msg = PaymentOpen.new(
            sender=SENDER,
            receiver=RECEIVER,
            total_deposit=1000,
        )
        wire = to_wire(MessageType.PAYMENT_OPEN, msg)
        msg_type, restored = from_wire(wire)

        assert msg_type == MessageType.PAYMENT_OPEN
        assert restored.sender == SENDER
        assert restored.receiver == RECEIVER
        assert restored.total_deposit == 1000
        assert len(restored.channel_id) == 32

    def test_payment_update_roundtrip(self):
        msg = PaymentUpdate(
            channel_id=b"\x00" * 32,
            nonce=5,
            amount=500,
            signature=b"\x01" * 65,
        )
        wire = to_wire(MessageType.PAYMENT_UPDATE, msg)
        msg_type, restored = from_wire(wire)

        assert msg_type == MessageType.PAYMENT_UPDATE
        assert restored.nonce == 5
        assert restored.amount == 500

    def test_payment_close_roundtrip(self):
        msg = PaymentClose(
            channel_id=b"\x00" * 32,
            final_nonce=10,
            final_amount=1000,
            cooperative=True,
        )
        wire = to_wire(MessageType.PAYMENT_CLOSE, msg)
        msg_type, restored = from_wire(wire)

        assert msg_type == MessageType.PAYMENT_CLOSE
        assert restored.cooperative is True

    def test_payment_ack_roundtrip(self):
        msg = PaymentAck(
            channel_id=b"\x00" * 32,
            nonce=1,
            status="accepted",
        )
        wire = to_wire(MessageType.PAYMENT_ACK, msg)
        msg_type, restored = from_wire(wire)

        assert msg_type == MessageType.PAYMENT_ACK
        assert restored.status == "accepted"

    def test_unknown_message_type_raises(self):
        with pytest.raises(ValueError):
            from_wire({"type": 99, "data": {}})

    def test_malformed_wire_missing_type(self):
        with pytest.raises(ValueError, match="missing 'type' or 'data'"):
            from_wire({"data": {}})

    def test_malformed_wire_missing_data(self):
        with pytest.raises(ValueError, match="missing 'type' or 'data'"):
            from_wire({"type": 1})

    def test_wire_drops_unknown_fields(self):
        """Extra fields from untrusted peer should be silently dropped."""
        wire = {
            "type": int(MessageType.PAYMENT_ACK),
            "data": {
                "channel_id": b"\x00" * 32,
                "nonce": 1,
                "status": "accepted",
                "reason": "",
                "extra_evil_field": "should_be_dropped",
            },
        }
        msg_type, restored = from_wire(wire)
        assert msg_type == MessageType.PAYMENT_ACK
        assert not hasattr(restored, "extra_evil_field")

    def test_wire_rejects_negative_deposit(self):
        wire = {
            "type": int(MessageType.PAYMENT_OPEN),
            "data": {
                "channel_id": b"\x00" * 32,
                "sender": SENDER,
                "receiver": RECEIVER,
                "total_deposit": -100,
            },
        }
        with pytest.raises(ValueError, match="positive integer"):
            from_wire(wire)

    def test_wire_rejects_short_channel_id(self):
        wire = {
            "type": int(MessageType.PAYMENT_UPDATE),
            "data": {
                "channel_id": b"\x00" * 10,
                "nonce": 1,
                "amount": 100,
            },
        }
        with pytest.raises(ValueError, match="32 bytes"):
            from_wire(wire)
