"""Tests for the signed receipt chain."""

from __future__ import annotations

import os

import pytest
from eth_account import Account

from agentic_payments.reporting.receipts import GENESIS_HASH, ReceiptStore, SignedReceipt


@pytest.fixture
def keypair():
    acct = Account.create()
    return acct.key.hex(), acct.address


def test_create_signed_receipt(keypair):
    privkey, addr = keypair
    receipt = SignedReceipt.create(
        channel_id=os.urandom(32),
        nonce=1,
        amount=1000,
        sender=addr,
        receiver="0x" + "ab" * 20,
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    assert receipt.nonce == 1
    assert receipt.amount == 1000
    assert len(receipt.signature) > 0
    assert len(receipt.receipt_hash) == 32


def test_verify_receipt_signature(keypair):
    privkey, addr = keypair
    receipt = SignedReceipt.create(
        channel_id=os.urandom(32),
        nonce=1,
        amount=1000,
        sender=addr,
        receiver="0x" + "cd" * 20,
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    assert receipt.verify(addr) is True
    assert receipt.verify("0x" + "00" * 20) is False


def test_receipt_to_dict(keypair):
    privkey, addr = keypair
    receipt = SignedReceipt.create(
        channel_id=b"\x01" * 32,
        nonce=3,
        amount=5000,
        sender=addr,
        receiver="0xdef",
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    d = receipt.to_dict()
    assert d["nonce"] == 3
    assert d["amount"] == 5000
    assert "receipt_hash" in d
    assert "signature" in d


def test_receipt_store_add_and_get(keypair):
    privkey, addr = keypair
    store = ReceiptStore()
    channel_id = os.urandom(32)
    r = SignedReceipt.create(
        channel_id=channel_id,
        nonce=1,
        amount=100,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    store.add(r)
    chain = store.get_chain(channel_id)
    assert len(chain) == 1
    assert store.get_latest(channel_id) == r


def test_receipt_chain_integrity(keypair):
    privkey, addr = keypair
    store = ReceiptStore()
    channel_id = os.urandom(32)

    r1 = SignedReceipt.create(
        channel_id=channel_id,
        nonce=1,
        amount=100,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    store.add(r1)

    r2 = SignedReceipt.create(
        channel_id=channel_id,
        nonce=2,
        amount=200,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=r1.receipt_hash,
        private_key=privkey,
    )
    store.add(r2)

    assert store.verify_chain(channel_id) is True


def test_receipt_chain_broken(keypair):
    privkey, addr = keypair
    store = ReceiptStore()
    channel_id = os.urandom(32)

    r1 = SignedReceipt.create(
        channel_id=channel_id,
        nonce=1,
        amount=100,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    store.add(r1)

    # Wrong previous hash
    r2 = SignedReceipt.create(
        channel_id=channel_id,
        nonce=2,
        amount=200,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=b"\xff" * 32,
        private_key=privkey,
    )
    store.add(r2)

    assert store.verify_chain(channel_id) is False


def test_receipt_store_empty_chain():
    store = ReceiptStore()
    assert store.verify_chain(b"\x00" * 32) is True
    assert store.get_latest(b"\x00" * 32) is None


def test_receipt_store_previous_hash(keypair):
    privkey, addr = keypair
    store = ReceiptStore()
    channel_id = os.urandom(32)
    assert store.get_previous_hash(channel_id) == GENESIS_HASH

    r1 = SignedReceipt.create(
        channel_id=channel_id,
        nonce=1,
        amount=100,
        sender=addr,
        receiver="0xabc",
        previous_receipt_hash=GENESIS_HASH,
        private_key=privkey,
    )
    store.add(r1)
    assert store.get_previous_hash(channel_id) == r1.receipt_hash


def test_receipt_store_list_channels(keypair):
    privkey, addr = keypair
    store = ReceiptStore()
    ch1, ch2 = os.urandom(32), os.urandom(32)
    store.add(
        SignedReceipt.create(
            channel_id=ch1,
            nonce=1,
            amount=100,
            sender=addr,
            receiver="0xabc",
            previous_receipt_hash=GENESIS_HASH,
            private_key=privkey,
        )
    )
    store.add(
        SignedReceipt.create(
            channel_id=ch2,
            nonce=1,
            amount=200,
            sender=addr,
            receiver="0xdef",
            previous_receipt_hash=GENESIS_HASH,
            private_key=privkey,
        )
    )
    channels = store.list_channels()
    assert len(channels) == 2
