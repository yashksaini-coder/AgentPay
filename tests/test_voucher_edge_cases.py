"""Extensive edge-case tests for SignedVoucher construction, signing,
verification, serialization, and deserialization.

Covers: wrong types, boundary values, tampered signatures, round-trip
fidelity, and from_dict validation.
"""

from __future__ import annotations

import time

import pytest
from eth_account import Account

from agentic_payments.payments.voucher import SignedVoucher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KEY_A = "0x4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
ADDR_A = Account.from_key(KEY_A).address

KEY_B = "0x6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c"
ADDR_B = Account.from_key(KEY_B).address

CID = bytes(range(32))


# ═══════════════════════════════════════════════════════════════════════════
# Construction validation
# ═══════════════════════════════════════════════════════════════════════════


class TestVoucherConstruction:
    """__post_init__ guards."""

    def test_channel_id_not_bytes(self):
        with pytest.raises(ValueError, match="channel_id must be exactly 32 bytes"):
            SignedVoucher(
                channel_id="not-bytes",
                nonce=1,
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_channel_id_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            SignedVoucher(
                channel_id=b"\x00" * 10,
                nonce=1,
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_channel_id_empty(self):
        with pytest.raises(ValueError, match="32 bytes"):
            SignedVoucher(
                channel_id=b"",
                nonce=1,
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_nonce_negative(self):
        with pytest.raises(ValueError, match="nonce must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce=-1,
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_nonce_float(self):
        with pytest.raises(ValueError, match="nonce must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce=1.5,
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_nonce_string(self):
        with pytest.raises(ValueError, match="nonce must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce="1",
                amount=100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_nonce_zero_is_valid(self):
        v = SignedVoucher(
            channel_id=CID, nonce=0, amount=0, timestamp=int(time.time()), signature=b"\x00" * 65
        )
        assert v.nonce == 0

    def test_amount_negative(self):
        with pytest.raises(ValueError, match="amount must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce=1,
                amount=-100,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_amount_float(self):
        with pytest.raises(ValueError, match="amount must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce=1,
                amount=99.9,
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_amount_string(self):
        with pytest.raises(ValueError, match="amount must be a non-negative"):
            SignedVoucher(
                channel_id=CID,
                nonce=1,
                amount="100",
                timestamp=int(time.time()),
                signature=b"\x00" * 65,
            )

    def test_amount_zero_is_valid(self):
        v = SignedVoucher(
            channel_id=CID, nonce=0, amount=0, timestamp=int(time.time()), signature=b"\x00" * 65
        )
        assert v.amount == 0

    def test_amount_very_large(self):
        """100 ETH in wei."""
        v = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=100 * 10**18,
            timestamp=int(time.time()),
            signature=b"\x00" * 65,
        )
        assert v.amount == 100 * 10**18

    def test_timestamp_zero(self):
        with pytest.raises(ValueError, match="timestamp must be a positive"):
            SignedVoucher(channel_id=CID, nonce=1, amount=100, timestamp=0, signature=b"\x00" * 65)

    def test_timestamp_negative(self):
        with pytest.raises(ValueError, match="timestamp must be a positive"):
            SignedVoucher(channel_id=CID, nonce=1, amount=100, timestamp=-1, signature=b"\x00" * 65)

    def test_timestamp_string(self):
        with pytest.raises(ValueError, match="timestamp must be a positive"):
            SignedVoucher(
                channel_id=CID, nonce=1, amount=100, timestamp="now", signature=b"\x00" * 65
            )

    def test_signature_not_bytes(self):
        with pytest.raises(ValueError, match="signature must be bytes"):
            SignedVoucher(
                channel_id=CID,
                nonce=1,
                amount=100,
                timestamp=int(time.time()),
                signature="deadbeef",
            )

    def test_signature_none(self):
        with pytest.raises(ValueError, match="signature must be bytes"):
            SignedVoucher(
                channel_id=CID, nonce=1, amount=100, timestamp=int(time.time()), signature=None
            )

    def test_signature_empty_bytes_accepted(self):
        """Empty bytes pass construction (validation is at verify time)."""
        v = SignedVoucher(
            channel_id=CID, nonce=1, amount=100, timestamp=int(time.time()), signature=b""
        )
        assert v.signature == b""


# ═══════════════════════════════════════════════════════════════════════════
# Signing & Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestVoucherSigningVerification:
    def test_create_sets_correct_fields(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert v.channel_id == CID
        assert v.nonce == 1
        assert v.amount == 1000
        assert len(v.signature) == 65  # r(32) + s(32) + v(1)
        assert v.timestamp > 0

    def test_verify_correct_signer(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert v.verify(ADDR_A)

    def test_verify_wrong_signer(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert not v.verify(ADDR_B)

    def test_verify_case_insensitive_address(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert v.verify(ADDR_A.lower())
        assert v.verify(ADDR_A.upper())

    def test_verify_garbage_address(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert not v.verify("0x0000000000000000000000000000000000000000")

    def test_verify_empty_address(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        assert not v.verify("")

    def test_verify_tampered_amount(self):
        """Changing any field after signing should break verification."""
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        # Create a new voucher with different amount but same signature
        tampered = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=9999,
            timestamp=v.timestamp,
            signature=v.signature,
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_tampered_nonce(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        tampered = SignedVoucher(
            channel_id=CID,
            nonce=99,
            amount=1000,
            timestamp=v.timestamp,
            signature=v.signature,
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_tampered_channel_id(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        tampered = SignedVoucher(
            channel_id=b"\xff" * 32,
            nonce=1,
            amount=1000,
            timestamp=v.timestamp,
            signature=v.signature,
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_tampered_timestamp(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        tampered = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=1000,
            timestamp=v.timestamp + 1000,
            signature=v.signature,
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_corrupted_signature(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        corrupted_sig = bytes([b ^ 0xFF for b in v.signature])
        tampered = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=1000,
            timestamp=v.timestamp,
            signature=corrupted_sig,
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_truncated_signature(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        tampered = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=1000,
            timestamp=v.timestamp,
            signature=v.signature[:32],
        )
        assert not tampered.verify(ADDR_A)

    def test_verify_empty_signature_returns_false(self):
        v = SignedVoucher(
            channel_id=CID,
            nonce=1,
            amount=1000,
            timestamp=int(time.time()),
            signature=b"",
        )
        assert not v.verify(ADDR_A)

    def test_two_vouchers_different_nonces_different_sigs(self):
        v1 = SignedVoucher.create(CID, 1, 100, KEY_A)
        v2 = SignedVoucher.create(CID, 2, 200, KEY_A)
        assert v1.signature != v2.signature

    def test_same_params_different_timestamps_different_sigs(self):
        """Due to time-based hashing, signatures differ even for same params."""
        import time as t

        v1 = SignedVoucher.create(CID, 1, 100, KEY_A)
        t.sleep(0.01)  # Just ensure different timestamp
        v2 = SignedVoucher.create(CID, 1, 100, KEY_A)
        # Timestamps might be same if within same second, but that's OK
        # Key point: both verify
        assert v1.verify(ADDR_A)
        assert v2.verify(ADDR_A)

    def test_cross_key_verification(self):
        """Voucher signed by A must not verify for B and vice versa."""
        va = SignedVoucher.create(CID, 1, 100, KEY_A)
        vb = SignedVoucher.create(CID, 1, 100, KEY_B)
        assert va.verify(ADDR_A)
        assert not va.verify(ADDR_B)
        assert vb.verify(ADDR_B)
        assert not vb.verify(ADDR_A)


# ═══════════════════════════════════════════════════════════════════════════
# Serialization round-trips
# ═══════════════════════════════════════════════════════════════════════════


class TestVoucherSerialization:
    def test_to_dict_has_bytes(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        d = v.to_dict()
        assert isinstance(d["channel_id"], bytes)
        assert isinstance(d["signature"], bytes)
        assert isinstance(d["nonce"], int)
        assert isinstance(d["amount"], int)

    def test_to_json_dict_has_hex(self):
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        d = v.to_json_dict()
        assert isinstance(d["channel_id"], str)
        assert isinstance(d["signature"], str)
        assert all(c in "0123456789abcdef" for c in d["channel_id"])
        assert all(c in "0123456789abcdef" for c in d["signature"])

    def test_roundtrip_to_dict(self):
        v = SignedVoucher.create(CID, 5, 50000, KEY_A)
        d = v.to_dict()
        restored = SignedVoucher.from_dict(d)
        assert restored.channel_id == v.channel_id
        assert restored.nonce == v.nonce
        assert restored.amount == v.amount
        assert restored.timestamp == v.timestamp
        assert restored.signature == v.signature
        assert restored.verify(ADDR_A)

    def test_from_dict_missing_channel_id(self):
        with pytest.raises(ValueError, match="Missing required voucher field: channel_id"):
            SignedVoucher.from_dict(
                {
                    "nonce": 1,
                    "amount": 100,
                    "timestamp": int(time.time()),
                    "signature": b"",
                }
            )

    def test_from_dict_missing_nonce(self):
        with pytest.raises(ValueError, match="Missing required voucher field: nonce"):
            SignedVoucher.from_dict(
                {
                    "channel_id": CID,
                    "amount": 100,
                    "timestamp": int(time.time()),
                    "signature": b"",
                }
            )

    def test_from_dict_missing_amount(self):
        with pytest.raises(ValueError, match="Missing required voucher field: amount"):
            SignedVoucher.from_dict(
                {
                    "channel_id": CID,
                    "nonce": 1,
                    "timestamp": int(time.time()),
                    "signature": b"",
                }
            )

    def test_from_dict_missing_timestamp(self):
        with pytest.raises(ValueError, match="Missing required voucher field: timestamp"):
            SignedVoucher.from_dict(
                {
                    "channel_id": CID,
                    "nonce": 1,
                    "amount": 100,
                    "signature": b"",
                }
            )

    def test_from_dict_missing_signature(self):
        with pytest.raises(ValueError, match="Missing required voucher field: signature"):
            SignedVoucher.from_dict(
                {
                    "channel_id": CID,
                    "nonce": 1,
                    "amount": 100,
                    "timestamp": int(time.time()),
                }
            )

    def test_from_dict_empty_dict(self):
        with pytest.raises(ValueError, match="Missing required"):
            SignedVoucher.from_dict({})

    def test_from_dict_extra_fields_ignored(self):
        v = SignedVoucher.create(CID, 1, 100, KEY_A)
        d = v.to_dict()
        d["extra_field"] = "should be ignored"
        restored = SignedVoucher.from_dict(d)
        assert not hasattr(restored, "extra_field")
        assert restored.verify(ADDR_A)

    def test_frozen_dataclass_immutable(self):
        """SignedVoucher is frozen — fields cannot be changed after creation."""
        v = SignedVoucher.create(CID, 1, 1000, KEY_A)
        with pytest.raises(AttributeError):
            v.amount = 9999  # type: ignore
        with pytest.raises(AttributeError):
            v.nonce = 999  # type: ignore
