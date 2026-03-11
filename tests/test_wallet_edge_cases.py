"""Tests for Wallet: generation, key loading, keyfile persistence,
signing, and edge cases.

Covers: deterministic key loading, address formats, keyfile round-trips,
permissions, signing, and invalid inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eth_account import Account

from agentic_payments.chain.wallet import Wallet


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


class TestWalletGeneration:
    def test_generate_creates_valid_address(self):
        w = Wallet.generate()
        assert w.address.startswith("0x")
        assert len(w.address) == 42

    def test_generate_creates_valid_private_key(self):
        w = Wallet.generate()
        # Private key is hex string (64 hex chars = 32 bytes)
        assert len(bytes.fromhex(w.private_key.replace("0x", ""))) == 32

    def test_two_generated_wallets_differ(self):
        w1 = Wallet.generate()
        w2 = Wallet.generate()
        assert w1.address != w2.address
        assert w1.private_key != w2.private_key

    def test_address_is_checksummed(self):
        """Address should be EIP-55 checksummed."""
        w = Wallet.generate()
        # Verify it's checksummed by checking mixed case
        stripped = w.address[2:]  # remove 0x
        assert stripped != stripped.lower()  # Not all lower
        assert stripped != stripped.upper()  # Not all upper (usually)


# ---------------------------------------------------------------------------
# From private key
# ---------------------------------------------------------------------------


class TestWalletFromPrivateKey:
    def test_from_known_key(self):
        key = "0x4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
        w = Wallet.from_private_key(key)
        expected = Account.from_key(key).address
        assert w.address == expected

    def test_from_key_without_0x_prefix(self):
        key = "4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
        w = Wallet.from_private_key(key)
        expected = Account.from_key(key).address
        assert w.address == expected

    def test_from_invalid_key_raises(self):
        with pytest.raises(Exception):
            Wallet.from_private_key("not-a-valid-key")

    def test_from_too_short_key(self):
        with pytest.raises(Exception):
            Wallet.from_private_key("0x1234")

    def test_from_empty_key(self):
        with pytest.raises(Exception):
            Wallet.from_private_key("")

    def test_deterministic_address(self):
        """Same key always produces same address."""
        key = "0x6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c"
        w1 = Wallet.from_private_key(key)
        w2 = Wallet.from_private_key(key)
        assert w1.address == w2.address

    def test_private_key_property_matches_input(self):
        key_hex = "4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01"
        w = Wallet.from_private_key("0x" + key_hex)
        # private_key property returns hex without 0x
        assert w.private_key == key_hex or w.private_key == "0x" + key_hex


# ---------------------------------------------------------------------------
# Keyfile persistence
# ---------------------------------------------------------------------------


class TestWalletKeyfile:
    def test_save_and_load_keyfile(self, tmp_path):
        w = Wallet.generate()
        path = tmp_path / "test_wallet.json"
        password = "test-password-123"

        w.save_keyfile(path, password)

        # File should exist
        assert path.exists()

        # Load back
        loaded = Wallet.from_keyfile(path, password)
        assert loaded.address == w.address
        assert loaded.private_key == w.private_key

    def test_keyfile_permissions(self, tmp_path):
        w = Wallet.generate()
        path = tmp_path / "wallet.json"
        w.save_keyfile(path, "pass")
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_keyfile_is_valid_json(self, tmp_path):
        w = Wallet.generate()
        path = tmp_path / "wallet.json"
        w.save_keyfile(path, "pass")
        data = json.loads(path.read_text())
        assert "crypto" in data or "Crypto" in data  # eth-account keystore format

    def test_wrong_password_raises(self, tmp_path):
        w = Wallet.generate()
        path = tmp_path / "wallet.json"
        w.save_keyfile(path, "correct-password")
        with pytest.raises(Exception):
            Wallet.from_keyfile(path, "wrong-password")

    def test_nonexistent_keyfile(self, tmp_path):
        with pytest.raises(Exception):
            Wallet.from_keyfile(tmp_path / "missing.json", "pass")

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "wallet.json"
        w = Wallet.generate()
        w.save_keyfile(path, "pass")
        assert path.exists()


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


class TestWalletSigning:
    def test_sign_message_returns_bytes(self):
        w = Wallet.generate()
        msg_hash = b"\x00" * 32
        sig = w.sign_message(msg_hash)
        assert isinstance(sig, bytes)
        assert len(sig) == 65  # r(32) + s(32) + v(1)

    def test_sign_message_different_hashes_differ(self):
        w = Wallet.generate()
        sig1 = w.sign_message(b"\x00" * 32)
        sig2 = w.sign_message(b"\xff" * 32)
        assert sig1 != sig2

    def test_sign_message_deterministic(self):
        """Same message produces same signature with same key."""
        w = Wallet.generate()
        msg = b"\xab" * 32
        sig1 = w.sign_message(msg)
        sig2 = w.sign_message(msg)
        assert sig1 == sig2

    def test_different_wallets_different_sigs(self):
        w1 = Wallet.generate()
        w2 = Wallet.generate()
        msg = b"\x42" * 32
        assert w1.sign_message(msg) != w2.sign_message(msg)
