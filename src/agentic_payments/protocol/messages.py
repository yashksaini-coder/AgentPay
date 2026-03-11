"""Payment protocol message types — msgpack-serializable dataclasses."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class MessageType(IntEnum):
    """Wire message type identifiers."""

    PAYMENT_OPEN = 1
    PAYMENT_UPDATE = 2
    PAYMENT_CLOSE = 3
    PAYMENT_ACK = 4
    ERROR = 15


class AckStatus(StrEnum):
    """Typed status for payment acknowledgements."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass
class PaymentOpen:
    """Request to open a payment channel."""

    channel_id: bytes
    sender: str  # Ethereum address
    receiver: str  # Ethereum address
    total_deposit: int  # Wei
    nonce: int = 0
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: bytes = b""

    @staticmethod
    def new(sender: str, receiver: str, total_deposit: int) -> PaymentOpen:
        return PaymentOpen(
            channel_id=os.urandom(32),
            sender=sender,
            receiver=receiver,
            total_deposit=total_deposit,
        )


@dataclass
class PaymentUpdate:
    """Incremental micropayment via signed voucher."""

    channel_id: bytes
    nonce: int
    amount: int  # Cumulative wei
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: bytes = b""


@dataclass
class PaymentClose:
    """Request to close a payment channel."""

    channel_id: bytes
    final_nonce: int
    final_amount: int  # Cumulative
    cooperative: bool = True
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: bytes = b""


@dataclass
class PaymentAck:
    """Acknowledgement of a payment message."""

    channel_id: bytes
    nonce: int
    status: str = AckStatus.ACCEPTED
    reason: str = ""


@dataclass
class ErrorMessage:
    """Protocol error."""

    code: int
    message: str


def to_wire(msg_type: MessageType, msg: Any) -> dict[str, Any]:
    """Convert a message to a wire-format dict."""
    return {"type": int(msg_type), "data": asdict(msg)}


# Expected fields per message type (for wire validation)
_EXPECTED_FIELDS: dict[MessageType, set[str]] = {
    MessageType.PAYMENT_OPEN: {
        "channel_id",
        "sender",
        "receiver",
        "total_deposit",
        "nonce",
        "timestamp",
        "signature",
    },
    MessageType.PAYMENT_UPDATE: {
        "channel_id",
        "nonce",
        "amount",
        "timestamp",
        "signature",
    },
    MessageType.PAYMENT_CLOSE: {
        "channel_id",
        "final_nonce",
        "final_amount",
        "cooperative",
        "timestamp",
        "signature",
    },
    MessageType.PAYMENT_ACK: {"channel_id", "nonce", "status", "reason"},
    MessageType.ERROR: {"code", "message"},
}


def _validate_wire_data(msg_type: MessageType, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize wire data before constructing message objects.

    Drops unknown keys, checks required fields, validates types and ranges.
    Raises ValueError on invalid input.
    """
    expected = _EXPECTED_FIELDS.get(msg_type)
    if expected is None:
        raise ValueError(f"Unknown message type: {msg_type}")

    # Drop unknown keys to prevent TypeError on dataclass construction
    filtered = {k: v for k, v in data.items() if k in expected}

    # Check required fields (fields without defaults)
    if msg_type == MessageType.PAYMENT_OPEN:
        for req in ("channel_id", "sender", "receiver", "total_deposit"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["channel_id"], bytes) or len(filtered["channel_id"]) != 32:
            raise ValueError("channel_id must be exactly 32 bytes")
        if not isinstance(filtered["total_deposit"], int) or filtered["total_deposit"] <= 0:
            raise ValueError("total_deposit must be a positive integer")
        if not isinstance(filtered["sender"], str) or len(filtered["sender"]) < 10:
            raise ValueError("sender must be a valid address string")
        if not isinstance(filtered["receiver"], str) or len(filtered["receiver"]) < 10:
            raise ValueError("receiver must be a valid address string")

    elif msg_type == MessageType.PAYMENT_UPDATE:
        for req in ("channel_id", "nonce", "amount"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["channel_id"], bytes) or len(filtered["channel_id"]) != 32:
            raise ValueError("channel_id must be exactly 32 bytes")
        if not isinstance(filtered["nonce"], int) or filtered["nonce"] < 0:
            raise ValueError("nonce must be a non-negative integer")
        if not isinstance(filtered["amount"], int) or filtered["amount"] <= 0:
            raise ValueError("amount must be a positive integer")

    elif msg_type == MessageType.PAYMENT_CLOSE:
        for req in ("channel_id", "final_nonce", "final_amount"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["channel_id"], bytes) or len(filtered["channel_id"]) != 32:
            raise ValueError("channel_id must be exactly 32 bytes")
        if not isinstance(filtered["final_nonce"], int) or filtered["final_nonce"] < 0:
            raise ValueError("final_nonce must be a non-negative integer")
        if not isinstance(filtered["final_amount"], int) or filtered["final_amount"] < 0:
            raise ValueError("final_amount must be a non-negative integer")

    elif msg_type == MessageType.PAYMENT_ACK:
        for req in ("channel_id", "nonce"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        status = filtered.get("status", AckStatus.ACCEPTED)
        if status not in (AckStatus.ACCEPTED, AckStatus.REJECTED):
            raise ValueError(f"Invalid ack status: {status}")

    return filtered


def from_wire(raw: dict[str, Any]) -> tuple[MessageType, Any]:
    """Parse a wire-format dict into a typed message.

    Validates the structure and field types of untrusted wire data
    before constructing message objects.
    """
    if not isinstance(raw, dict) or "type" not in raw or "data" not in raw:
        raise ValueError("Malformed wire message: missing 'type' or 'data' keys")

    try:
        msg_type = MessageType(raw["type"])
    except ValueError:
        raise ValueError(f"Unknown wire message type: {raw.get('type')}")

    data = raw["data"]
    if not isinstance(data, dict):
        raise ValueError("Wire message 'data' must be a dict")

    validated = _validate_wire_data(msg_type, data)

    match msg_type:
        case MessageType.PAYMENT_OPEN:
            return msg_type, PaymentOpen(**validated)
        case MessageType.PAYMENT_UPDATE:
            return msg_type, PaymentUpdate(**validated)
        case MessageType.PAYMENT_CLOSE:
            return msg_type, PaymentClose(**validated)
        case MessageType.PAYMENT_ACK:
            return msg_type, PaymentAck(**validated)
        case MessageType.ERROR:
            return msg_type, ErrorMessage(**validated)
        case _:
            raise ValueError(f"Unknown message type: {msg_type}")
