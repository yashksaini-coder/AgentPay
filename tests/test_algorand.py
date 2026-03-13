"""Tests for the Algorand wallet integration."""

from __future__ import annotations

from pathlib import Path


from agentic_payments.chain.algorand.wallet import AlgorandWallet
from agentic_payments.chain.protocols import WalletProtocol
from agentic_payments.config import AlgorandConfig


def test_generate_produces_valid_address():
    wallet = AlgorandWallet.generate()
    assert len(wallet.address) == 58


def test_from_private_key_roundtrip():
    wallet = AlgorandWallet.generate()
    restored = AlgorandWallet.from_private_key(wallet.private_key)
    assert restored.address == wallet.address
    assert restored.private_key == wallet.private_key


def test_sign_bytes_returns_bytes():
    wallet = AlgorandWallet.generate()
    sig = wallet.sign_bytes(b"hello world")
    assert isinstance(sig, bytes)
    assert len(sig) > 0


def test_mnemonic_phrase_returns_25_words():
    wallet = AlgorandWallet.generate()
    words = wallet.mnemonic_phrase.split()
    assert len(words) == 25


def test_save_and_load_keyfile(tmp_path: Path):
    wallet = AlgorandWallet.generate()
    keyfile = tmp_path / "algo.key"
    wallet.save_keyfile(keyfile)
    assert keyfile.exists()
    # File should be owner-only readable
    assert oct(keyfile.stat().st_mode & 0o777) == "0o600"

    loaded = AlgorandWallet.from_keyfile(keyfile)
    assert loaded.address == wallet.address
    assert loaded.private_key == wallet.private_key


def test_algorand_config_defaults():
    config = AlgorandConfig()
    assert config.algod_url == "http://localhost:4001"
    assert config.network == "localnet"
    assert config.app_id == 0


def test_wallet_protocol_compliance():
    wallet = AlgorandWallet.generate()
    assert isinstance(wallet, WalletProtocol)
