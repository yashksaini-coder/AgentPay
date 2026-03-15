"""Tests for Filecoin FEVM wallet and address conversion."""

from __future__ import annotations

from pathlib import Path

from agentic_payments.chain.filecoin.wallet import (
    FilecoinWallet,
    eth_address_to_f4,
    f4_to_eth_address,
)
from agentic_payments.chain.protocols import WalletProtocol


def test_generate_produces_valid_address():
    wallet = FilecoinWallet.generate()
    assert wallet.address.startswith("0x")
    assert len(wallet.address) == 42


def test_f4_address_starts_with_prefix():
    wallet = FilecoinWallet.generate()
    assert wallet.f4_address.startswith("f410f")


def test_f4_roundtrip():
    wallet = FilecoinWallet.generate()
    f4 = eth_address_to_f4(wallet.address)
    recovered = f4_to_eth_address(f4)
    assert recovered.lower() == wallet.address.lower()


def test_from_private_key_roundtrip():
    wallet = FilecoinWallet.generate()
    pk = wallet.private_key
    restored = FilecoinWallet.from_private_key(pk)
    assert restored.address == wallet.address


def test_save_and_load_keyfile(tmp_path: Path):
    wallet = FilecoinWallet.generate()
    keyfile = tmp_path / "fil_key.json"
    wallet.save_keyfile(keyfile, password="test123")
    loaded = FilecoinWallet.from_keyfile(keyfile, password="test123")
    assert loaded.address == wallet.address
    assert loaded.private_key == wallet.private_key


def test_wallet_satisfies_protocol():
    wallet = FilecoinWallet.generate()
    assert isinstance(wallet, WalletProtocol)


def test_sign_transaction_returns_bytes():
    wallet = FilecoinWallet.generate()
    tx = {
        "to": wallet.address,
        "value": 0,
        "gas": 21000,
        "gasPrice": 1,
        "nonce": 0,
        "chainId": 314159,
    }
    signed = wallet.sign_transaction(tx)
    assert isinstance(signed, bytes)
    assert len(signed) > 0


def test_sign_message_returns_bytes():
    wallet = FilecoinWallet.generate()
    msg = b"test message hash for filecoin"
    sig = wallet.sign_message(msg)
    assert isinstance(sig, bytes)
    assert len(sig) == 65  # r + s + v


def test_f4_address_deterministic():
    """Same ETH address always produces same f4 address."""
    wallet = FilecoinWallet.generate()
    f4_1 = eth_address_to_f4(wallet.address)
    f4_2 = eth_address_to_f4(wallet.address)
    assert f4_1 == f4_2


def test_filecoin_config_defaults():
    from agentic_payments.config import FilecoinConfig

    cfg = FilecoinConfig()
    assert cfg.chain_id == 314159
    assert cfg.network == "calibration"
    assert "glif" in cfg.rpc_url


def test_chain_type_includes_filecoin():
    from agentic_payments.config import Settings

    settings = Settings()
    settings.chain_type = "filecoin"  # type: ignore[assignment]
    assert settings.chain_type == "filecoin"
