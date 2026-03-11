"""Shared test fixtures for pytest-trio."""

from __future__ import annotations

import pytest
from eth_account import Account


@pytest.fixture
def eth_keypair():
    """Generate a deterministic Ethereum keypair for testing."""
    account = Account.from_key("0x4c0883a69102937d6231471b5dbb6204fe512961708279f25e3a0a9b3a6e8c01")
    return account


@pytest.fixture
def eth_keypair_b():
    """Second Ethereum keypair for testing."""
    account = Account.from_key("0x6370fd033278c143179d81c5526140625662b8daa446c22ee2d73db3707e620c")
    return account


@pytest.fixture
def channel_id():
    """Deterministic channel ID for testing."""
    return bytes.fromhex("a1b2c3d4e5f6" + "00" * 26)


# Deterministic test addresses (from eth_keypair fixtures)
TEST_SENDER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
TEST_RECEIVER = "0x7e5F4552091A69125d5DfCb7b8C2659029395Bdf"


@pytest.fixture
def test_sender():
    """Valid Ethereum address for test sender."""
    return TEST_SENDER


@pytest.fixture
def test_receiver():
    """Valid Ethereum address for test receiver."""
    return TEST_RECEIVER
