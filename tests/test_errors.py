"""Tests for standardized payment error codes."""

from __future__ import annotations

from agentic_payments.protocol.errors import (
    PaymentError,
    PaymentErrorCode,
)


class TestPaymentErrorCode:
    def test_error_code_ranges(self):
        """Error codes should fall within defined ranges."""
        for code in PaymentErrorCode:
            assert 1000 <= code <= 1599, f"{code.name} = {code} outside range"

    def test_channel_errors_range(self):
        """Channel errors should be in 1000-1099."""
        channel_codes = [c for c in PaymentErrorCode if 1000 <= c <= 1099]
        assert len(channel_codes) >= 5
        assert PaymentErrorCode.CHANNEL_NOT_FOUND in channel_codes

    def test_payment_errors_range(self):
        """Payment errors should be in 1100-1199."""
        payment_codes = [c for c in PaymentErrorCode if 1100 <= c <= 1199]
        assert len(payment_codes) >= 4
        assert PaymentErrorCode.INSUFFICIENT_FUNDS in payment_codes
        assert PaymentErrorCode.INVALID_SIGNATURE in payment_codes

    def test_all_codes_unique(self):
        """All error codes should have unique integer values."""
        values = [int(c) for c in PaymentErrorCode]
        assert len(values) == len(set(values))


class TestPaymentError:
    def test_basic_error(self):
        """PaymentError should carry code, message, and data."""
        err = PaymentError(PaymentErrorCode.INSUFFICIENT_FUNDS)
        assert err.code == PaymentErrorCode.INSUFFICIENT_FUNDS
        assert "Insufficient funds" in err.detail
        assert err.http_status == 402

    def test_custom_detail(self):
        """PaymentError should accept custom detail message."""
        err = PaymentError(
            PaymentErrorCode.CHANNEL_NOT_FOUND,
            detail="Channel abc123 not found",
        )
        assert err.detail == "Channel abc123 not found"
        assert err.http_status == 404

    def test_to_dict(self):
        """to_dict should produce structured error response."""
        err = PaymentError(
            PaymentErrorCode.INVALID_SIGNATURE,
            data={"expected": "0xabc", "recovered": "0xdef"},
        )
        d = err.to_dict()
        assert d["error"]["code"] == 1101
        assert d["error"]["name"] == "INVALID_SIGNATURE"
        assert d["error"]["data"]["expected"] == "0xabc"

    def test_to_wire_error(self):
        """to_wire_error should produce (MessageType.ERROR, ErrorMessage)."""
        from agentic_payments.protocol.messages import MessageType

        err = PaymentError(PaymentErrorCode.NO_ROUTE_FOUND)
        msg_type, msg = err.to_wire_error()
        assert msg_type == MessageType.ERROR
        assert msg.code == 1400

    def test_http_status_mapping(self):
        """Key error codes should map to correct HTTP statuses."""
        assert PaymentError(PaymentErrorCode.INSUFFICIENT_FUNDS).http_status == 402
        assert PaymentError(PaymentErrorCode.CHANNEL_NOT_FOUND).http_status == 404
        assert PaymentError(PaymentErrorCode.INVALID_SIGNATURE).http_status == 403
        assert PaymentError(PaymentErrorCode.INTERNAL_ERROR).http_status == 500
        assert PaymentError(PaymentErrorCode.RATE_LIMITED).http_status == 429

    def test_error_as_exception(self):
        """PaymentError should be catchable as an Exception."""
        try:
            raise PaymentError(PaymentErrorCode.EXPIRED_PAYMENT)
        except PaymentError as e:
            assert e.code == PaymentErrorCode.EXPIRED_PAYMENT
        except Exception:
            raise AssertionError("PaymentError should be catchable as PaymentError")
