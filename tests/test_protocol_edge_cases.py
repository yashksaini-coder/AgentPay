"""Extensive edge-case tests for protocol messages: wire format validation,
from_wire parsing with every type of bad input, boundary values, and codec
size limits.

Covers: missing fields, wrong types, negative values, empty strings,
non-dict data, corrupted payloads, oversized messages, all MessageType
variants, and AckStatus validation.
"""

from __future__ import annotations

import struct

import pytest

from agentic_payments.protocol.codec import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    decode_payload,
    encode_message,
)
from agentic_payments.protocol.messages import (
    AckStatus,
    ErrorMessage,
    MessageType,
    PaymentAck,
    PaymentClose,
    PaymentOpen,
    PaymentUpdate,
    from_wire,
    to_wire,
)

SENDER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
RECEIVER = "0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf"
CID = b"\x00" * 32


# ═══════════════════════════════════════════════════════════════════════════
# from_wire: structural validation
# ═══════════════════════════════════════════════════════════════════════════


class TestFromWireStructural:
    def test_none_input(self):
        with pytest.raises(ValueError, match="Malformed wire message"):
            from_wire(None)

    def test_list_input(self):
        with pytest.raises(ValueError, match="Malformed wire message"):
            from_wire([1, 2, 3])

    def test_string_input(self):
        with pytest.raises(ValueError, match="Malformed wire message"):
            from_wire("not a dict")

    def test_empty_dict(self):
        with pytest.raises(ValueError, match="Malformed wire message"):
            from_wire({})

    def test_missing_type_key(self):
        with pytest.raises(ValueError, match="missing 'type' or 'data'"):
            from_wire({"data": {}})

    def test_missing_data_key(self):
        with pytest.raises(ValueError, match="missing 'type' or 'data'"):
            from_wire({"type": 1})

    def test_data_not_dict(self):
        with pytest.raises(ValueError, match="'data' must be a dict"):
            from_wire({"type": 1, "data": "not-a-dict"})

    def test_data_is_list(self):
        with pytest.raises(ValueError, match="'data' must be a dict"):
            from_wire({"type": 1, "data": [1, 2, 3]})

    def test_data_is_none(self):
        with pytest.raises(ValueError, match="'data' must be a dict"):
            from_wire({"type": 1, "data": None})

    def test_unknown_message_type_zero(self):
        with pytest.raises(ValueError, match="Unknown wire message type"):
            from_wire({"type": 0, "data": {}})

    def test_unknown_message_type_high(self):
        with pytest.raises(ValueError, match="Unknown wire message type"):
            from_wire({"type": 999, "data": {}})

    def test_unknown_message_type_negative(self):
        with pytest.raises(ValueError, match="Unknown wire message type"):
            from_wire({"type": -1, "data": {}})

    def test_type_as_string(self):
        with pytest.raises(ValueError):
            from_wire({"type": "1", "data": {}})


# ═══════════════════════════════════════════════════════════════════════════
# PaymentOpen wire validation
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentOpenWire:
    def _wire(self, **overrides):
        base = {
            "channel_id": CID, "sender": SENDER,
            "receiver": RECEIVER, "total_deposit": 1000,
        }
        base.update(overrides)
        return {"type": int(MessageType.PAYMENT_OPEN), "data": base}

    def test_valid_open(self):
        _, msg = from_wire(self._wire())
        assert isinstance(msg, PaymentOpen)
        assert msg.sender == SENDER
        assert msg.total_deposit == 1000

    def test_missing_channel_id(self):
        wire = self._wire()
        del wire["data"]["channel_id"]
        with pytest.raises(ValueError, match="Missing required field: channel_id"):
            from_wire(wire)

    def test_missing_sender(self):
        wire = self._wire()
        del wire["data"]["sender"]
        with pytest.raises(ValueError, match="Missing required field: sender"):
            from_wire(wire)

    def test_missing_receiver(self):
        wire = self._wire()
        del wire["data"]["receiver"]
        with pytest.raises(ValueError, match="Missing required field: receiver"):
            from_wire(wire)

    def test_missing_deposit(self):
        wire = self._wire()
        del wire["data"]["total_deposit"]
        with pytest.raises(ValueError, match="Missing required field: total_deposit"):
            from_wire(wire)

    def test_channel_id_wrong_type_string(self):
        with pytest.raises(ValueError, match="32 bytes"):
            from_wire(self._wire(channel_id="not-bytes"))

    def test_channel_id_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            from_wire(self._wire(channel_id=b"\x00" * 16))

    def test_deposit_zero(self):
        with pytest.raises(ValueError, match="positive integer"):
            from_wire(self._wire(total_deposit=0))

    def test_deposit_negative(self):
        with pytest.raises(ValueError, match="positive integer"):
            from_wire(self._wire(total_deposit=-500))

    def test_deposit_string(self):
        with pytest.raises(ValueError, match="positive integer"):
            from_wire(self._wire(total_deposit="1000"))

    def test_deposit_float(self):
        with pytest.raises(ValueError, match="positive integer"):
            from_wire(self._wire(total_deposit=10.5))

    def test_sender_empty_string(self):
        with pytest.raises(ValueError, match="valid address"):
            from_wire(self._wire(sender=""))

    def test_sender_too_short(self):
        with pytest.raises(ValueError, match="valid address"):
            from_wire(self._wire(sender="0x123"))

    def test_sender_not_string(self):
        with pytest.raises(ValueError, match="valid address"):
            from_wire(self._wire(sender=12345))

    def test_receiver_empty_string(self):
        with pytest.raises(ValueError, match="valid address"):
            from_wire(self._wire(receiver=""))

    def test_receiver_not_string(self):
        with pytest.raises(ValueError, match="valid address"):
            from_wire(self._wire(receiver=None))

    def test_extra_fields_dropped(self):
        wire = self._wire()
        wire["data"]["malicious_field"] = "should_be_dropped"
        _, msg = from_wire(wire)
        assert not hasattr(msg, "malicious_field")

    def test_deposit_very_large(self):
        """100 ETH in wei."""
        _, msg = from_wire(self._wire(total_deposit=100 * 10**18))
        assert msg.total_deposit == 100 * 10**18


# ═══════════════════════════════════════════════════════════════════════════
# PaymentUpdate wire validation
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentUpdateWire:
    def _wire(self, **overrides):
        base = {"channel_id": CID, "nonce": 1, "amount": 500}
        base.update(overrides)
        return {"type": int(MessageType.PAYMENT_UPDATE), "data": base}

    def test_valid_update(self):
        _, msg = from_wire(self._wire())
        assert isinstance(msg, PaymentUpdate)
        assert msg.nonce == 1 and msg.amount == 500

    def test_missing_channel_id(self):
        wire = self._wire()
        del wire["data"]["channel_id"]
        with pytest.raises(ValueError, match="Missing required field: channel_id"):
            from_wire(wire)

    def test_missing_nonce(self):
        wire = self._wire()
        del wire["data"]["nonce"]
        with pytest.raises(ValueError, match="Missing required field: nonce"):
            from_wire(wire)

    def test_missing_amount(self):
        wire = self._wire()
        del wire["data"]["amount"]
        with pytest.raises(ValueError, match="Missing required field: amount"):
            from_wire(wire)

    def test_channel_id_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            from_wire(self._wire(channel_id=b"\x00" * 5))

    def test_nonce_negative(self):
        with pytest.raises(ValueError, match="nonce must be a non-negative"):
            from_wire(self._wire(nonce=-1))

    def test_nonce_string(self):
        with pytest.raises(ValueError, match="nonce must be a non-negative"):
            from_wire(self._wire(nonce="5"))

    def test_nonce_zero_allowed(self):
        _, msg = from_wire(self._wire(nonce=0))
        assert msg.nonce == 0

    def test_amount_zero(self):
        with pytest.raises(ValueError, match="amount must be a positive"):
            from_wire(self._wire(amount=0))

    def test_amount_negative(self):
        with pytest.raises(ValueError, match="amount must be a positive"):
            from_wire(self._wire(amount=-100))

    def test_amount_string(self):
        with pytest.raises(ValueError, match="amount must be a positive"):
            from_wire(self._wire(amount="500"))

    def test_extra_fields_dropped(self):
        wire = self._wire()
        wire["data"]["injected"] = True
        _, msg = from_wire(wire)
        assert not hasattr(msg, "injected")


# ═══════════════════════════════════════════════════════════════════════════
# PaymentClose wire validation
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentCloseWire:
    def _wire(self, **overrides):
        base = {"channel_id": CID, "final_nonce": 5, "final_amount": 1000}
        base.update(overrides)
        return {"type": int(MessageType.PAYMENT_CLOSE), "data": base}

    def test_valid_close(self):
        _, msg = from_wire(self._wire())
        assert isinstance(msg, PaymentClose)
        assert msg.final_nonce == 5 and msg.final_amount == 1000

    def test_missing_channel_id(self):
        wire = self._wire()
        del wire["data"]["channel_id"]
        with pytest.raises(ValueError, match="Missing required field: channel_id"):
            from_wire(wire)

    def test_missing_final_nonce(self):
        wire = self._wire()
        del wire["data"]["final_nonce"]
        with pytest.raises(ValueError, match="Missing required field: final_nonce"):
            from_wire(wire)

    def test_missing_final_amount(self):
        wire = self._wire()
        del wire["data"]["final_amount"]
        with pytest.raises(ValueError, match="Missing required field: final_amount"):
            from_wire(wire)

    def test_channel_id_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            from_wire(self._wire(channel_id=b"\x00" * 1))

    def test_final_nonce_negative(self):
        with pytest.raises(ValueError, match="final_nonce must be a non-negative"):
            from_wire(self._wire(final_nonce=-1))

    def test_final_amount_negative(self):
        with pytest.raises(ValueError, match="final_amount must be a non-negative"):
            from_wire(self._wire(final_amount=-1))

    def test_final_nonce_zero_allowed(self):
        """Channel with no payments closes with nonce 0."""
        _, msg = from_wire(self._wire(final_nonce=0, final_amount=0))
        assert msg.final_nonce == 0

    def test_cooperative_defaults_true(self):
        _, msg = from_wire(self._wire())
        assert msg.cooperative is True

    def test_cooperative_false(self):
        _, msg = from_wire(self._wire(cooperative=False))
        assert msg.cooperative is False


# ═══════════════════════════════════════════════════════════════════════════
# PaymentAck wire validation
# ═══════════════════════════════════════════════════════════════════════════


class TestPaymentAckWire:
    def _wire(self, **overrides):
        base = {"channel_id": CID, "nonce": 1, "status": "accepted", "reason": ""}
        base.update(overrides)
        return {"type": int(MessageType.PAYMENT_ACK), "data": base}

    def test_valid_ack(self):
        _, msg = from_wire(self._wire())
        assert isinstance(msg, PaymentAck)
        assert msg.status == "accepted"

    def test_rejected_status(self):
        _, msg = from_wire(self._wire(status="rejected", reason="insufficient funds"))
        assert msg.status == "rejected"
        assert msg.reason == "insufficient funds"

    def test_missing_channel_id(self):
        wire = self._wire()
        del wire["data"]["channel_id"]
        with pytest.raises(ValueError, match="Missing required field: channel_id"):
            from_wire(wire)

    def test_missing_nonce(self):
        wire = self._wire()
        del wire["data"]["nonce"]
        with pytest.raises(ValueError, match="Missing required field: nonce"):
            from_wire(wire)

    def test_invalid_ack_status(self):
        with pytest.raises(ValueError, match="Invalid ack status"):
            from_wire(self._wire(status="maybe"))

    def test_empty_status_invalid(self):
        with pytest.raises(ValueError, match="Invalid ack status"):
            from_wire(self._wire(status=""))


# ═══════════════════════════════════════════════════════════════════════════
# to_wire / from_wire round-trips for all message types
# ═══════════════════════════════════════════════════════════════════════════


class TestWireRoundTrips:
    def test_open_roundtrip_preserves_all_fields(self):
        msg = PaymentOpen(
            channel_id=CID, sender=SENDER, receiver=RECEIVER,
            total_deposit=999_999, nonce=0, signature=b"\xab" * 65,
        )
        wire = to_wire(MessageType.PAYMENT_OPEN, msg)
        _, restored = from_wire(wire)
        assert restored.channel_id == CID
        assert restored.sender == SENDER
        assert restored.receiver == RECEIVER
        assert restored.total_deposit == 999_999

    def test_update_roundtrip(self):
        msg = PaymentUpdate(channel_id=CID, nonce=42, amount=12345, signature=b"\x01" * 65)
        wire = to_wire(MessageType.PAYMENT_UPDATE, msg)
        _, restored = from_wire(wire)
        assert restored.nonce == 42
        assert restored.amount == 12345

    def test_close_roundtrip(self):
        msg = PaymentClose(
            channel_id=CID, final_nonce=100, final_amount=999,
            cooperative=False, signature=b"\x02" * 65,
        )
        wire = to_wire(MessageType.PAYMENT_CLOSE, msg)
        _, restored = from_wire(wire)
        assert restored.final_nonce == 100
        assert restored.final_amount == 999
        assert restored.cooperative is False

    def test_ack_roundtrip(self):
        msg = PaymentAck(channel_id=CID, nonce=7, status="rejected", reason="bad sig")
        wire = to_wire(MessageType.PAYMENT_ACK, msg)
        _, restored = from_wire(wire)
        assert restored.nonce == 7
        assert restored.status == "rejected"
        assert restored.reason == "bad sig"

    def test_error_roundtrip(self):
        msg = ErrorMessage(code=500, message="internal server error")
        wire = to_wire(MessageType.ERROR, msg)
        msg_type, restored = from_wire(wire)
        assert msg_type == MessageType.ERROR
        assert restored.code == 500
        assert restored.message == "internal server error"


# ═══════════════════════════════════════════════════════════════════════════
# Codec edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestCodecEdgeCases:
    def test_header_is_4_bytes(self):
        assert HEADER_SIZE == 4

    def test_header_format_big_endian(self):
        assert HEADER_FORMAT == ">I"

    def test_encode_decode_nested_data(self):
        data = {"type": 1, "data": {"nested": {"deep": [1, 2, 3]}}}
        encoded = encode_message(data)
        decoded = decode_payload(encoded[4:])
        assert decoded["data"]["nested"]["deep"] == [1, 2, 3]

    def test_encode_decode_binary_values(self):
        data = {"type": 1, "data": {"bytes_val": b"\xde\xad\xbe\xef"}}
        encoded = encode_message(data)
        decoded = decode_payload(encoded[4:])
        assert decoded["data"]["bytes_val"] == b"\xde\xad\xbe\xef"

    def test_encode_decode_unicode(self):
        data = {"msg": "hello world 🌍"}
        encoded = encode_message(data)
        decoded = decode_payload(encoded[4:])
        assert decoded["msg"] == "hello world 🌍"

    def test_length_prefix_accuracy(self):
        data = {"key": "value" * 100}
        encoded = encode_message(data)
        (length,) = struct.unpack(">I", encoded[:4])
        assert length == len(encoded) - 4

    def test_max_message_size_constant(self):
        assert MAX_MESSAGE_SIZE == 1024 * 1024  # 1 MB

    def test_encode_oversized_message_raises(self):
        """A message larger than MAX_MESSAGE_SIZE should raise."""
        huge_data = {"data": "x" * (MAX_MESSAGE_SIZE + 1)}
        with pytest.raises(ValueError, match="Message too large"):
            encode_message(huge_data)

    def test_empty_dict_roundtrip(self):
        encoded = encode_message({})
        decoded = decode_payload(encoded[4:])
        assert decoded == {}

    def test_encode_large_but_valid_message(self):
        """Just under the limit should work."""
        # msgpack overhead is small, so ~1MB of data should be fine
        data = {"payload": "A" * (MAX_MESSAGE_SIZE - 100)}
        encoded = encode_message(data)
        decoded = decode_payload(encoded[4:])
        assert len(decoded["payload"]) == MAX_MESSAGE_SIZE - 100
