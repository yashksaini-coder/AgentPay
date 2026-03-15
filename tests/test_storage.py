"""Tests for IPFS storage module (unit tests, no daemon required)."""

from __future__ import annotations

from unittest.mock import patch

import trio

from agentic_payments.storage.ipfs import IPFSClient
from agentic_payments.storage.models import PinnedObject, StorageResult
from agentic_payments.storage.receipt_store import IPFSReceiptStore
from agentic_payments.reporting.receipts import ReceiptStore, SignedReceipt


def test_storage_result_to_dict():
    r = StorageResult(cid="QmTest123", size=42, pinned=True)
    d = r.to_dict()
    assert d["cid"] == "QmTest123"
    assert d["size"] == 42
    assert d["pinned"] is True


def test_pinned_object_to_dict():
    p = PinnedObject(cid="QmTest", name="data.json", size=100)
    d = p.to_dict()
    assert d["cid"] == "QmTest"
    assert d["name"] == "data.json"


def test_ipfs_client_init():
    client = IPFSClient("http://localhost:5001")
    assert client.api_url == "http://localhost:5001"


def test_ipfs_client_strips_trailing_slash():
    client = IPFSClient("http://localhost:5001/")
    assert client.api_url == "http://localhost:5001"


def test_ipfs_client_list_pins_empty():
    client = IPFSClient()
    assert client.list_pins() == []


def test_ipfs_receipt_store_init():
    client = IPFSClient()
    store = ReceiptStore()
    ipfs_store = IPFSReceiptStore(client, store)
    assert ipfs_store.ipfs is client
    assert ipfs_store.store is store


def test_ipfs_receipt_store_list_pinned_empty():
    client = IPFSClient()
    store = ReceiptStore()
    ipfs_store = IPFSReceiptStore(client, store)
    pinned = ipfs_store.list_pinned()
    assert pinned["receipt_count"] == 0
    assert pinned["chain_count"] == 0


def test_ipfs_receipt_store_cid_lookups():
    client = IPFSClient()
    store = ReceiptStore()
    ipfs_store = IPFSReceiptStore(client, store)
    assert ipfs_store.get_receipt_cid(b"\x01\x02\x03") is None
    assert ipfs_store.get_chain_cid(b"\x01\x02\x03") is None


def test_storage_config_defaults():
    from agentic_payments.config import StorageConfig

    cfg = StorageConfig()
    assert cfg.ipfs_api_url == "http://localhost:5001"
    assert cfg.auto_pin_receipts is False
    assert cfg.enabled is False


async def _run_async(fn):
    """Helper to run async test functions under trio."""
    await fn()


def test_ipfs_client_add_mock():
    """Test add() with mocked HTTP call."""
    client = IPFSClient()

    # Mock the sync POST to return a fake IPFS response
    client._post_sync = lambda *a, **kw: {"Hash": "QmFakeHash123", "Size": "11"}

    async def _test():
        result = await client.add(b"hello world", name="test.txt")
        assert result.cid == "QmFakeHash123"
        assert result.pinned is True
        # Check it was tracked
        pins = client.list_pins()
        assert len(pins) == 1
        assert pins[0].cid == "QmFakeHash123"

    trio.run(_test)


def test_ipfs_client_add_json_mock():
    """Test add_json() with mocked HTTP call."""
    client = IPFSClient()
    client._post_sync = lambda *a, **kw: {"Hash": "QmJsonHash", "Size": "20"}

    async def _test():
        result = await client.add_json({"key": "value"})
        assert result.cid == "QmJsonHash"

    trio.run(_test)


def test_ipfs_client_cat_mock():
    """Test cat() with mocked HTTP call."""
    import io

    client = IPFSClient()

    def mock_urlopen(req, timeout=None):
        response = io.BytesIO(b'{"key":"value"}')
        response.read_orig = response.read
        response.__enter__ = lambda s: s
        response.__exit__ = lambda s, *a: None
        return response

    async def _test():
        with patch("urllib.request.urlopen", mock_urlopen):
            data = await client.cat("QmTest")
            assert b"key" in data

    trio.run(_test)


def test_ipfs_client_health_mock():
    """Test health() with mocked HTTP call."""
    client = IPFSClient()
    client._post_sync = lambda *a, **kw: {"ID": "12D3KooW...", "AgentVersion": "kubo"}

    async def _test():
        healthy = await client.health()
        assert healthy is True

    trio.run(_test)


def test_ipfs_receipt_store_pin_receipt_mock():
    """Test pin_receipt() with mocked IPFS client."""
    client = IPFSClient()
    client._post_sync = lambda *a, **kw: {"Hash": "QmReceipt123", "Size": "200"}

    store = ReceiptStore()
    ipfs_store = IPFSReceiptStore(client, store)

    receipt = SignedReceipt(
        receipt_id=b"\x01" * 16,
        channel_id=b"\xaa" * 32,
        nonce=1,
        amount=1000,
        sender="0xSender",
        receiver="0xReceiver",
        timestamp=1234567890,
        previous_receipt_hash=b"\x00" * 32,
        signature=b"\xff" * 65,
    )

    async def _test():
        cid = await ipfs_store.pin_receipt(receipt)
        assert cid == "QmReceipt123"
        assert ipfs_store.get_receipt_cid(receipt.receipt_id) == "QmReceipt123"
        pinned = ipfs_store.list_pinned()
        assert pinned["receipt_count"] == 1

    trio.run(_test)
