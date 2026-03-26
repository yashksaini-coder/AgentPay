"""Standardized payment error codes matching a2a-x402 patterns.

Provides programmatic error handling for agent clients with
structured error codes, categories, and HTTP status mappings.
"""

from __future__ import annotations

from enum import IntEnum


class PaymentErrorCode(IntEnum):
    """Standardized error codes for payment protocol operations.

    Ranges:
        1000-1099: Channel errors
        1100-1199: Payment/voucher errors
        1200-1299: Identity/trust errors
        1300-1399: Gateway/x402 errors
        1400-1499: Routing errors
        1500-1599: Protocol errors
    """

    # Channel errors (1000-1099)
    CHANNEL_NOT_FOUND = 1000
    CHANNEL_ALREADY_EXISTS = 1001
    CHANNEL_NOT_ACTIVE = 1002
    CHANNEL_DEPOSIT_INVALID = 1003
    CHANNEL_CLOSE_MISMATCH = 1004

    # Payment/voucher errors (1100-1199)
    INSUFFICIENT_FUNDS = 1100
    INVALID_SIGNATURE = 1101
    EXPIRED_PAYMENT = 1102
    DUPLICATE_NONCE = 1103
    INVALID_AMOUNT = 1104
    NONCE_TOO_OLD = 1105

    # Identity/trust errors (1200-1299)
    TRUST_BELOW_MINIMUM = 1200
    IDENTITY_NOT_VERIFIED = 1201
    PEER_BLACKLISTED = 1202

    # Gateway/x402 errors (1300-1399)
    RESOURCE_NOT_FOUND = 1300
    PAYMENT_REQUIRED = 1301
    INSUFFICIENT_PAYMENT = 1302
    INVALID_PROOF = 1303

    # Routing errors (1400-1499)
    NO_ROUTE_FOUND = 1400
    HTLC_TIMEOUT = 1401
    HTLC_ROUTING_FAILED = 1402

    # Protocol errors (1500-1599)
    UNSUPPORTED_MESSAGE = 1500
    MALFORMED_MESSAGE = 1501
    INTERNAL_ERROR = 1502
    NEGOTIATION_NOT_SUPPORTED = 1503
    RATE_LIMITED = 1504


# Human-readable messages for each error code
_ERROR_MESSAGES: dict[PaymentErrorCode, str] = {
    PaymentErrorCode.CHANNEL_NOT_FOUND: "Channel not found",
    PaymentErrorCode.CHANNEL_ALREADY_EXISTS: "Channel ID already exists",
    PaymentErrorCode.CHANNEL_NOT_ACTIVE: "Channel is not in an active state",
    PaymentErrorCode.CHANNEL_DEPOSIT_INVALID: "Invalid deposit amount",
    PaymentErrorCode.CHANNEL_CLOSE_MISMATCH: "Close parameters do not match channel state",
    PaymentErrorCode.INSUFFICIENT_FUNDS: "Insufficient funds in channel",
    PaymentErrorCode.INVALID_SIGNATURE: "Invalid payment signature",
    PaymentErrorCode.EXPIRED_PAYMENT: "Payment has expired",
    PaymentErrorCode.DUPLICATE_NONCE: "Duplicate payment nonce",
    PaymentErrorCode.INVALID_AMOUNT: "Invalid payment amount",
    PaymentErrorCode.NONCE_TOO_OLD: "Payment nonce is older than current state",
    PaymentErrorCode.TRUST_BELOW_MINIMUM: "Peer trust score below required minimum",
    PaymentErrorCode.IDENTITY_NOT_VERIFIED: "Peer identity not verified",
    PaymentErrorCode.PEER_BLACKLISTED: "Peer is blacklisted",
    PaymentErrorCode.RESOURCE_NOT_FOUND: "Gated resource not found",
    PaymentErrorCode.PAYMENT_REQUIRED: "Payment required to access resource",
    PaymentErrorCode.INSUFFICIENT_PAYMENT: "Payment amount insufficient for resource",
    PaymentErrorCode.INVALID_PROOF: "Invalid payment proof",
    PaymentErrorCode.NO_ROUTE_FOUND: "No payment route found to destination",
    PaymentErrorCode.HTLC_TIMEOUT: "HTLC timed out",
    PaymentErrorCode.HTLC_ROUTING_FAILED: "HTLC routing failed",
    PaymentErrorCode.UNSUPPORTED_MESSAGE: "Unsupported message type",
    PaymentErrorCode.MALFORMED_MESSAGE: "Malformed message",
    PaymentErrorCode.INTERNAL_ERROR: "Internal error",
    PaymentErrorCode.NEGOTIATION_NOT_SUPPORTED: "Negotiation not supported",
    PaymentErrorCode.RATE_LIMITED: "Rate limited",
}

# HTTP status code mapping
_HTTP_STATUS: dict[PaymentErrorCode, int] = {
    PaymentErrorCode.CHANNEL_NOT_FOUND: 404,
    PaymentErrorCode.CHANNEL_ALREADY_EXISTS: 409,
    PaymentErrorCode.CHANNEL_NOT_ACTIVE: 409,
    PaymentErrorCode.CHANNEL_DEPOSIT_INVALID: 400,
    PaymentErrorCode.CHANNEL_CLOSE_MISMATCH: 409,
    PaymentErrorCode.INSUFFICIENT_FUNDS: 402,
    PaymentErrorCode.INVALID_SIGNATURE: 403,
    PaymentErrorCode.EXPIRED_PAYMENT: 410,
    PaymentErrorCode.DUPLICATE_NONCE: 409,
    PaymentErrorCode.INVALID_AMOUNT: 400,
    PaymentErrorCode.NONCE_TOO_OLD: 409,
    PaymentErrorCode.TRUST_BELOW_MINIMUM: 403,
    PaymentErrorCode.IDENTITY_NOT_VERIFIED: 403,
    PaymentErrorCode.PEER_BLACKLISTED: 403,
    PaymentErrorCode.RESOURCE_NOT_FOUND: 404,
    PaymentErrorCode.PAYMENT_REQUIRED: 402,
    PaymentErrorCode.INSUFFICIENT_PAYMENT: 402,
    PaymentErrorCode.INVALID_PROOF: 403,
    PaymentErrorCode.NO_ROUTE_FOUND: 404,
    PaymentErrorCode.HTLC_TIMEOUT: 408,
    PaymentErrorCode.HTLC_ROUTING_FAILED: 502,
    PaymentErrorCode.UNSUPPORTED_MESSAGE: 400,
    PaymentErrorCode.MALFORMED_MESSAGE: 400,
    PaymentErrorCode.INTERNAL_ERROR: 500,
    PaymentErrorCode.NEGOTIATION_NOT_SUPPORTED: 501,
    PaymentErrorCode.RATE_LIMITED: 429,
}


class PaymentError(ValueError):
    """Structured payment error with error code, message, and optional details.

    Inherits from ValueError for backward compatibility with existing
    except ValueError handlers in the protocol handler and tests.
    """

    def __init__(
        self,
        code: PaymentErrorCode,
        detail: str = "",
        data: dict | None = None,
    ) -> None:
        self.code = code
        self.detail = detail or _ERROR_MESSAGES.get(code, "Unknown error")
        self.data = data or {}
        super().__init__(self.detail)

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS.get(self.code, 500)

    def to_dict(self) -> dict:
        """Serialize to a structured error response."""
        d: dict = {
            "error": {
                "code": int(self.code),
                "name": self.code.name,
                "message": self.detail,
            }
        }
        if self.data:
            d["error"]["data"] = self.data
        return d

    def to_wire_error(self) -> tuple:
        """Convert to wire-format ErrorMessage for protocol responses."""
        from agentic_payments.protocol.messages import ErrorMessage, MessageType

        return MessageType.ERROR, ErrorMessage(
            code=int(self.code),
            message=self.detail,
        )
