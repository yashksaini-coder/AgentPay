"""Tests for all REST API endpoints.

Uses a mock AgentNode to test the Quart routes without needing
a real libp2p host or Ethereum connection.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from agentic_payments.api.server import create_app
from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.manager import ChannelManager

# ---------------------------------------------------------------------------
# Mock node that satisfies what the routes expect
# ---------------------------------------------------------------------------


class MockPeerID:
    """Mock PeerID that supports to_base58()."""

    def __init__(self, value: str = "12D3KooWTestPeerId"):
        self._value = value

    def to_base58(self) -> str:
        return self._value

    def __str__(self) -> str:
        return self._value


class MockDiscovery:
    def __init__(self, peers: list[dict] | None = None):
        self._peers = peers or []

    def get_peers(self) -> list[dict]:
        return self._peers

    @property
    def connected_count(self) -> int:
        return 0


class MockNode:
    """Lightweight stand-in for AgentNode used by route tests."""

    def __init__(self) -> None:
        self.wallet = Wallet.generate()
        self.channel_manager = ChannelManager(self.wallet.address)
        self.peer_id = MockPeerID("12D3KooWTestPeerId")
        self.listen_addrs = ["/ip4/127.0.0.1/tcp/9000"]
        self.discovery = MockDiscovery()
        self.host = None  # No real libp2p host in tests
        self._open_channel_mock = AsyncMock()
        self._pay_mock = AsyncMock()
        self._close_mock = AsyncMock()

    def get_connected_peers(self) -> list:
        return []

    async def open_payment_channel(self, peer_id: str, receiver: str, deposit: int):
        channel = self.channel_manager.create_channel(
            channel_id=bytes(range(32)),
            receiver=receiver,
            total_deposit=deposit,
            peer_id=peer_id,
        )
        channel.accept()
        channel.activate()
        return channel

    async def pay(self, channel_id: bytes, amount: int):
        return await self.channel_manager.send_payment(
            channel_id=channel_id,
            amount=amount,
            private_key=self.wallet.private_key,
            send_fn=AsyncMock(),
        )

    async def close_channel(self, channel_id: bytes):
        channel = self.channel_manager.get_channel(channel_id)
        channel.request_close()
        channel.settle()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_node():
    return MockNode()


@pytest.fixture
def app(mock_node):
    return create_app(mock_node)


@pytest.fixture
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    async def test_health_returns_ok(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_health_has_cors_headers(self, client):
        resp = await client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert resp.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"

    async def test_cors_rejected_for_unknown_origin(self, client):
        resp = await client.get("/health", headers={"Origin": "http://evil.com"})
        assert "Access-Control-Allow-Origin" not in resp.headers


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentityEndpoint:
    async def test_identity_returns_peer_info(self, client, mock_node):
        resp = await client.get("/identity")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["peer_id"] == "12D3KooWTestPeerId"
        assert data["eth_address"] == mock_node.wallet.address
        assert isinstance(data["addrs"], list)
        assert len(data["addrs"]) == 1
        assert data["connected_peers"] == 0


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------


class TestPeersEndpoint:
    async def test_list_peers_empty(self, client):
        resp = await client.get("/peers")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["peers"] == []
        assert data["count"] == 0

    async def test_list_peers_with_discovered(self, client, mock_node):
        mock_node.discovery = MockDiscovery(
            peers=[
                {"peer_id": "QmAlice", "addrs": ["/ip4/10.0.0.1/tcp/9000"]},
                {"peer_id": "QmBob", "addrs": ["/ip4/10.0.0.2/tcp/9000"]},
            ]
        )
        resp = await client.get("/peers")
        data = await resp.get_json()
        assert data["count"] == 2
        assert data["peers"][0]["peer_id"] == "QmAlice"


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


class TestChannelsEndpoint:
    async def test_list_channels_empty(self, client):
        resp = await client.get("/channels")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["channels"] == []
        assert data["count"] == 0

    async def test_open_channel_success(self, client, mock_node):
        payload = {
            "peer_id": "QmPeerA",
            "receiver": "0x1234567890abcdef1234567890abcdef12345678",
            "deposit": 1_000_000,
        }
        resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 201
        data = await resp.get_json()
        assert "channel" in data
        assert data["channel"]["state"] == "ACTIVE"
        assert data["channel"]["total_deposit"] == 1_000_000

    async def test_open_channel_missing_fields(self, client):
        payload = {"peer_id": "QmPeerA"}  # missing receiver and deposit
        resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        data = await resp.get_json()
        assert "error" in data

    async def test_open_channel_no_json(self, client):
        resp = await client.post("/channels")
        assert resp.status_code == 400

    async def test_list_channels_after_open(self, client, mock_node):
        # Open a channel first
        payload = {
            "peer_id": "QmPeerA",
            "receiver": "0xabcdef1234567890abcdef1234567890abcdef12",
            "deposit": 500_000,
        }
        await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        # Now list
        resp = await client.get("/channels")
        data = await resp.get_json()
        assert data["count"] == 1
        assert data["channels"][0]["total_deposit"] == 500_000

    async def test_get_channel_by_id(self, client, mock_node):
        # Open a channel
        payload = {
            "peer_id": "QmPeerB",
            "receiver": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "deposit": 200_000,
        }
        open_resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        channel_id = (await open_resp.get_json())["channel"]["channel_id"]

        resp = await client.get(f"/channels/{channel_id}")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["total_deposit"] == 200_000

    async def test_get_channel_not_found(self, client):
        fake_id = "aa" * 32
        resp = await client.get(f"/channels/{fake_id}")
        assert resp.status_code == 404
        data = await resp.get_json()
        assert data["error"] == "Channel not found"

    async def test_close_channel(self, client, mock_node):
        # Open a channel
        payload = {
            "peer_id": "QmPeerC",
            "receiver": "0x1111111111111111111111111111111111111111",
            "deposit": 300_000,
        }
        open_resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        channel_id = (await open_resp.get_json())["channel"]["channel_id"]

        # Close
        resp = await client.post(f"/channels/{channel_id}/close")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["channel"]["state"] == "SETTLED"

    async def test_close_channel_not_found(self, client):
        fake_id = "bb" * 32
        resp = await client.post(f"/channels/{fake_id}/close")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Pay
# ---------------------------------------------------------------------------


class TestPayEndpoint:
    async def _open_channel(self, client):
        """Helper to open a channel and return its hex ID."""
        payload = {
            "peer_id": "QmPayee",
            "receiver": "0x2222222222222222222222222222222222222222",
            "deposit": 1_000_000,
        }
        resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        return (await resp.get_json())["channel"]["channel_id"]

    async def test_pay_success(self, client, mock_node):
        channel_id = await self._open_channel(client)
        payload = {"channel_id": channel_id, "amount": 100_000}
        resp = await client.post(
            "/pay",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = await resp.get_json()
        assert "voucher" in data
        assert data["voucher"]["nonce"] == 1
        assert data["voucher"]["amount"] == 100_000

    async def test_pay_increments_nonce(self, client, mock_node):
        channel_id = await self._open_channel(client)
        # First payment
        resp1 = await client.post(
            "/pay",
            data=json.dumps({"channel_id": channel_id, "amount": 50_000}),
            headers={"Content-Type": "application/json"},
        )
        assert resp1.status_code == 200
        # Second payment
        resp2 = await client.post(
            "/pay",
            data=json.dumps({"channel_id": channel_id, "amount": 75_000}),
            headers={"Content-Type": "application/json"},
        )
        v2 = (await resp2.get_json())["voucher"]

        assert v2["nonce"] == 2
        assert v2["amount"] == 125_000  # cumulative: 50k + 75k

    async def test_pay_missing_fields(self, client):
        resp = await client.post(
            "/pay",
            data=json.dumps({"channel_id": "abc"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    async def test_pay_no_json(self, client):
        resp = await client.post("/pay")
        assert resp.status_code == 400

    async def test_pay_nonexistent_channel(self, client):
        payload = {"channel_id": "cc" * 32, "amount": 100}
        resp = await client.post(
            "/pay",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 404  # Channel not found


# ---------------------------------------------------------------------------
# Balance
# ---------------------------------------------------------------------------


class TestBalanceEndpoint:
    async def test_balance_empty(self, client, mock_node):
        resp = await client.get("/balance")
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["total_deposited"] == 0
        assert data["total_paid"] == 0
        assert data["total_remaining"] == 0
        assert data["channel_count"] == 0
        assert data["address"] == mock_node.wallet.address

    async def test_balance_after_channel_and_payment(self, client, mock_node):
        # Open
        payload = {
            "peer_id": "QmBal",
            "receiver": "0x3333333333333333333333333333333333333333",
            "deposit": 500_000,
        }
        open_resp = await client.post(
            "/channels",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        channel_id = (await open_resp.get_json())["channel"]["channel_id"]

        # Pay
        await client.post(
            "/pay",
            data=json.dumps({"channel_id": channel_id, "amount": 100_000}),
            headers={"Content-Type": "application/json"},
        )

        resp = await client.get("/balance")
        data = await resp.get_json()
        assert data["total_deposited"] == 500_000
        assert data["total_paid"] == 100_000
        assert data["total_remaining"] == 400_000
        assert data["channel_count"] == 1


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


class TestCORS:
    async def test_options_preflight(self, client):
        resp = await client.options("/channels", headers={"Origin": "http://localhost:3000"})
        assert resp.status_code in (200, 204)
        assert resp.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
        assert "POST" in resp.headers["Access-Control-Allow-Methods"]

    async def test_cors_on_all_get_routes(self, client):
        for path in ["/health", "/peers", "/channels", "/balance", "/identity"]:
            resp = await client.get(path, headers={"Origin": "http://localhost:3000"})
            assert resp.headers["Access-Control-Allow-Origin"] == "http://localhost:3000", (
                f"Missing CORS on {path}"
            )
