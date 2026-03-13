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
    HTLC_PROPOSE = 5
    HTLC_FULFILL = 6
    HTLC_CANCEL = 7
    CHANNEL_ANNOUNCE = 8
    NEGOTIATE_PROPOSE = 9
    NEGOTIATE_COUNTER = 10
    NEGOTIATE_ACCEPT = 11
    NEGOTIATE_REJECT = 12
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
class HtlcPropose:
    """Propose an HTLC for multi-hop payment forwarding."""

    channel_id: bytes
    payment_hash: bytes  # SHA-256 hash of the preimage
    amount: int  # Wei to lock
    timeout: int  # Absolute unix timestamp for expiry
    onion_next: bytes = b""  # Encrypted routing info for next hop (empty = final)
    htlc_id: bytes = field(default_factory=lambda: os.urandom(16))
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class HtlcFulfill:
    """Fulfill an HTLC by revealing the preimage."""

    channel_id: bytes
    htlc_id: bytes
    preimage: bytes  # SHA-256 preimage that hashes to payment_hash
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class HtlcCancel:
    """Cancel an HTLC (timeout or routing failure)."""

    channel_id: bytes
    htlc_id: bytes
    reason: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class ChannelAnnounce:
    """Broadcast channel existence for network topology discovery."""

    channel_id: bytes
    peer_a: str  # Peer ID
    peer_b: str  # Peer ID
    capacity: int  # Total deposit in wei
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class NegotiatePropose:
    """Propose a service negotiation."""

    negotiation_id: str
    service_type: str
    proposed_price: int
    channel_deposit: int
    timeout: int  # absolute unix timestamp
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class NegotiateCounter:
    """Counter-offer in a negotiation."""

    negotiation_id: str
    counter_price: int
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class NegotiateAccept:
    """Accept negotiation terms."""

    negotiation_id: str
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class NegotiateReject:
    """Reject a negotiation."""

    negotiation_id: str
    reason: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))


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
    MessageType.HTLC_PROPOSE: {
        "channel_id",
        "payment_hash",
        "amount",
        "timeout",
        "onion_next",
        "htlc_id",
        "timestamp",
    },
    MessageType.HTLC_FULFILL: {"channel_id", "htlc_id", "preimage", "timestamp"},
    MessageType.HTLC_CANCEL: {"channel_id", "htlc_id", "reason", "timestamp"},
    MessageType.CHANNEL_ANNOUNCE: {
        "channel_id",
        "peer_a",
        "peer_b",
        "capacity",
        "timestamp",
    },
    MessageType.NEGOTIATE_PROPOSE: {
        "negotiation_id",
        "service_type",
        "proposed_price",
        "channel_deposit",
        "timeout",
        "timestamp",
    },
    MessageType.NEGOTIATE_COUNTER: {"negotiation_id", "counter_price", "timestamp"},
    MessageType.NEGOTIATE_ACCEPT: {"negotiation_id", "timestamp"},
    MessageType.NEGOTIATE_REJECT: {"negotiation_id", "reason", "timestamp"},
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

    elif msg_type == MessageType.HTLC_PROPOSE:
        for req in ("channel_id", "payment_hash", "amount", "timeout"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["payment_hash"], bytes) or len(filtered["payment_hash"]) != 32:
            raise ValueError("payment_hash must be exactly 32 bytes")
        if not isinstance(filtered["amount"], int) or filtered["amount"] <= 0:
            raise ValueError("amount must be a positive integer")
        if not isinstance(filtered["timeout"], int) or filtered["timeout"] <= 0:
            raise ValueError("timeout must be a positive integer")

    elif msg_type == MessageType.HTLC_FULFILL:
        for req in ("channel_id", "htlc_id", "preimage"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["preimage"], bytes) or len(filtered["preimage"]) != 32:
            raise ValueError("preimage must be exactly 32 bytes")

    elif msg_type == MessageType.HTLC_CANCEL:
        for req in ("channel_id", "htlc_id"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")

    elif msg_type == MessageType.CHANNEL_ANNOUNCE:
        for req in ("channel_id", "peer_a", "peer_b", "capacity"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["capacity"], int) or filtered["capacity"] <= 0:
            raise ValueError("capacity must be a positive integer")

    elif msg_type == MessageType.NEGOTIATE_PROPOSE:
        for req in (
            "negotiation_id",
            "service_type",
            "proposed_price",
            "channel_deposit",
            "timeout",
        ):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["proposed_price"], int) or filtered["proposed_price"] <= 0:
            raise ValueError("proposed_price must be a positive integer")
        if not isinstance(filtered["channel_deposit"], int) or filtered["channel_deposit"] <= 0:
            raise ValueError("channel_deposit must be a positive integer")

    elif msg_type == MessageType.NEGOTIATE_COUNTER:
        for req in ("negotiation_id", "counter_price"):
            if req not in filtered:
                raise ValueError(f"Missing required field: {req}")
        if not isinstance(filtered["counter_price"], int) or filtered["counter_price"] <= 0:
            raise ValueError("counter_price must be a positive integer")

    elif msg_type == MessageType.NEGOTIATE_ACCEPT:
        if "negotiation_id" not in filtered:
            raise ValueError("Missing required field: negotiation_id")

    elif msg_type == MessageType.NEGOTIATE_REJECT:
        if "negotiation_id" not in filtered:
            raise ValueError("Missing required field: negotiation_id")

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
        case MessageType.HTLC_PROPOSE:
            return msg_type, HtlcPropose(**validated)
        case MessageType.HTLC_FULFILL:
            return msg_type, HtlcFulfill(**validated)
        case MessageType.HTLC_CANCEL:
            return msg_type, HtlcCancel(**validated)
        case MessageType.CHANNEL_ANNOUNCE:
            return msg_type, ChannelAnnounce(**validated)
        case MessageType.NEGOTIATE_PROPOSE:
            return msg_type, NegotiatePropose(**validated)
        case MessageType.NEGOTIATE_COUNTER:
            return msg_type, NegotiateCounter(**validated)
        case MessageType.NEGOTIATE_ACCEPT:
            return msg_type, NegotiateAccept(**validated)
        case MessageType.NEGOTIATE_REJECT:
            return msg_type, NegotiateReject(**validated)
        case MessageType.ERROR:
            return msg_type, ErrorMessage(**validated)
        case _:
            raise ValueError(f"Unknown message type: {msg_type}")
