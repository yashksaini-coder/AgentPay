"""Extensive edge-case tests for REST API endpoints.

Covers: wrong input types, invalid formats, boundary values, missing fields,
extra fields, malformed JSON, invalid hex, bad Ethereum addresses,
payment edge cases, multi-channel balance aggregation, and connect endpoint.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from agentic_payments.api.server import create_app
from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.manager import ChannelManager


# ---------------------------------------------------------------------------
# Mock infrastructure (reusing patterns from test_api.py)
# ---------------------------------------------------------------------------


class MockPeerID:
    def __init__(self, value="12D3KooWTestPeerId"):
        self._value = value

    def to_base58(self):
        return self._value

    def __str__(self):
        return self._value


class MockDiscovery:
    def __init__(self, peers=None):
        self._peers = peers or []

    def get_peers(self):
        return self._peers

    @property
    def connected_count(self):
        return len(self._peers)


class MockNode:
    def __init__(self):
        self.wallet = Wallet.generate()
        self.channel_manager = ChannelManager(self.wallet.address)
        self.peer_id = MockPeerID()
        self.listen_addrs = ["/ip4/127.0.0.1/tcp/9000"]
        self.discovery = MockDiscovery()
        self.host = None
        self._connect_mock = AsyncMock()

    def get_connected_peers(self):
        return []

    async def open_payment_channel(self, peer_id, receiver, deposit):
        import os

        channel = self.channel_manager.create_channel(
            channel_id=os.urandom(32),
            receiver=receiver,
            total_deposit=deposit,
            peer_id=peer_id,
        )
        channel.accept()
        channel.activate()
        return channel

    async def pay(self, channel_id, amount):
        return await self.channel_manager.send_payment(
            channel_id=channel_id,
            amount=amount,
            private_key=self.wallet.private_key,
            send_fn=AsyncMock(),
        )

    async def close_channel(self, channel_id):
        channel = self.channel_manager.get_channel(channel_id)
        channel.cooperative_close()
        channel.settle()

    async def connect(self, multiaddr):
        return await self._connect_mock(multiaddr)


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


def _json(payload):
    return json.dumps(payload)


def _headers():
    return {"Content-Type": "application/json"}


# ═══════════════════════════════════════════════════════════════════════════
# POST /channels — Open channel edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenChannelEdgeCases:
    async def test_missing_peer_id(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"receiver": "0x" + "ab" * 20, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        data = await resp.get_json()
        assert "peer_id" in data["error"]

    async def test_peer_id_not_string(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": 12345, "receiver": "0x" + "ab" * 20, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "peer_id" in (await resp.get_json())["error"]

    async def test_peer_id_empty_string(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "", "receiver": "0x" + "ab" * 20, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400

    async def test_missing_receiver(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "receiver" in (await resp.get_json())["error"]

    async def test_receiver_not_string(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": 12345, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400

    async def test_receiver_no_0x_prefix(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "ab" * 20, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "Ethereum address" in (await resp.get_json())["error"]

    async def test_receiver_too_short(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x1234", "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "Ethereum address" in (await resp.get_json())["error"]

    async def test_receiver_too_long(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 21, "deposit": 1000}),
            headers=_headers(),
        )
        assert resp.status_code == 400

    async def test_missing_deposit(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "deposit" in (await resp.get_json())["error"]

    async def test_deposit_zero(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20, "deposit": 0}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "positive" in (await resp.get_json())["error"]

    async def test_deposit_negative(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20, "deposit": -100}),
            headers=_headers(),
        )
        assert resp.status_code == 400

    async def test_deposit_string_non_numeric(self, client):
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20, "deposit": "abc"}),
            headers=_headers(),
        )
        assert resp.status_code == 400
        assert "integer" in (await resp.get_json())["error"]

    async def test_deposit_float(self, client):
        """Float deposit should be truncated to int or rejected."""
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20, "deposit": 1000.5}),
            headers=_headers(),
        )
        # int(1000.5) = 1000, so this should succeed as 1000
        assert resp.status_code == 201

    async def test_deposit_string_numeric(self, client):
        """String "1000" should be parsed to int."""
        resp = await client.post(
            "/channels",
            data=_json({"peer_id": "QmPeer", "receiver": "0x" + "ab" * 20, "deposit": "1000"}),
            headers=_headers(),
        )
        assert resp.status_code == 201

    async def test_no_json_body(self, client):
        resp = await client.post("/channels")
        assert resp.status_code == 400

    async def test_invalid_json_body(self, client):
        resp = await client.post("/channels", data="not-json", headers=_headers())
        assert resp.status_code in (400, 500)

    async def test_empty_json_body(self, client):
        resp = await client.post("/channels", data=_json({}), headers=_headers())
        assert resp.status_code == 400

    async def test_extra_fields_ignored(self, client):
        resp = await client.post(
            "/channels",
            data=_json(
                {
                    "peer_id": "QmPeer",
                    "receiver": "0x" + "ab" * 20,
                    "deposit": 1000,
                    "evil": "payload",
                }
            ),
            headers=_headers(),
        )
        assert resp.status_code == 201

    async def test_successful_open_returns_active(self, client):
        resp = await client.post(
            "/channels",
            data=_json(
                {
                    "peer_id": "QmPeer",
                    "receiver": "0x" + "ab" * 20,
                    "deposit": 500_000,
                }
            ),
            headers=_headers(),
        )
        assert resp.status_code == 201
        data = await resp.get_json()
        assert data["channel"]["state"] == "ACTIVE"
        assert data["channel"]["total_deposit"] == 500_000


# ═══════════════════════════════════════════════════════════════════════════
# POST /pay — Payment edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestPayEndpointEdgeCases:
    async def _open(self, client):
        resp = await client.post(
            "/channels",
            data=_json(
                {
                    "peer_id": "QmPayee",
                    "receiver": "0x" + "22" * 20,
                    "deposit": 1_000_000,
                }
            ),
            headers=_headers(),
        )
        return (await resp.get_json())["channel"]["channel_id"]

    async def test_missing_channel_id(self, client):
        resp = await client.post("/pay", data=_json({"amount": 100}), headers=_headers())
        assert resp.status_code == 400
        assert "channel_id" in (await resp.get_json())["error"]

    async def test_channel_id_not_string(self, client):
        resp = await client.post(
            "/pay", data=_json({"channel_id": 12345, "amount": 100}), headers=_headers()
        )
        assert resp.status_code == 400

    async def test_channel_id_empty_string(self, client):
        resp = await client.post(
            "/pay", data=_json({"channel_id": "", "amount": 100}), headers=_headers()
        )
        assert resp.status_code == 400

    async def test_channel_id_invalid_hex(self, client):
        resp = await client.post(
            "/pay", data=_json({"channel_id": "xyz-not-hex", "amount": 100}), headers=_headers()
        )
        assert resp.status_code == 400
        assert "hex" in (await resp.get_json())["error"]

    async def test_missing_amount(self, client):
        cid = await self._open(client)
        resp = await client.post("/pay", data=_json({"channel_id": cid}), headers=_headers())
        assert resp.status_code == 400
        assert "amount" in (await resp.get_json())["error"]

    async def test_amount_zero(self, client):
        cid = await self._open(client)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": 0}), headers=_headers()
        )
        assert resp.status_code == 400
        assert "positive" in (await resp.get_json())["error"]

    async def test_amount_negative(self, client):
        cid = await self._open(client)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": -500}), headers=_headers()
        )
        assert resp.status_code == 400

    async def test_amount_string_non_numeric(self, client):
        cid = await self._open(client)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": "abc"}), headers=_headers()
        )
        assert resp.status_code == 400
        assert "integer" in (await resp.get_json())["error"]

    async def test_amount_string_numeric(self, client):
        """String "100000" should be parsed to int."""
        cid = await self._open(client)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": "100000"}), headers=_headers()
        )
        assert resp.status_code == 200

    async def test_nonexistent_channel(self, client):
        resp = await client.post(
            "/pay", data=_json({"channel_id": "aa" * 32, "amount": 100}), headers=_headers()
        )
        assert resp.status_code == 404

    async def test_no_json_body(self, client):
        resp = await client.post("/pay")
        assert resp.status_code == 400

    async def test_multiple_payments_cumulative(self, client):
        cid = await self._open(client)
        # Pay 3 times
        for i in range(3):
            resp = await client.post(
                "/pay", data=_json({"channel_id": cid, "amount": 100_000}), headers=_headers()
            )
            assert resp.status_code == 200

        data = (await resp.get_json())["voucher"]
        assert data["nonce"] == 3
        assert data["amount"] == 300_000  # cumulative

    async def test_pay_exceeds_deposit(self, client):
        """Should fail when cumulative amount exceeds deposit."""
        cid = await self._open(client)
        # First payment uses most of the deposit
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": 900_000}), headers=_headers()
        )
        assert resp.status_code == 200
        # Second payment would exceed deposit (900k + 200k > 1M)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": 200_000}), headers=_headers()
        )
        assert resp.status_code == 400  # ChannelError returns 400

    async def test_pay_exact_deposit_amount(self, client):
        """Paying exactly the deposit amount should succeed."""
        cid = await self._open(client)
        resp = await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": 1_000_000}), headers=_headers()
        )
        assert resp.status_code == 200
        data = (await resp.get_json())["voucher"]
        assert data["amount"] == 1_000_000


# ═══════════════════════════════════════════════════════════════════════════
# GET /channels/<id> — Channel retrieval edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestGetChannelEdgeCases:
    async def test_invalid_hex_channel_id(self, client):
        resp = await client.get("/channels/not-valid-hex")
        assert resp.status_code == 400
        assert "hex" in (await resp.get_json())["error"]

    async def test_nonexistent_channel(self, client):
        resp = await client.get(f"/channels/{'ff' * 32}")
        assert resp.status_code == 404

    async def test_short_hex_channel_id(self, client):
        """Short hex string is valid hex but won't match any channel."""
        resp = await client.get("/channels/abcd")
        assert resp.status_code == 404

    async def test_odd_length_hex(self, client):
        resp = await client.get("/channels/abc")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# POST /channels/<id>/close — Close edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestCloseChannelEdgeCases:
    async def test_close_invalid_hex(self, client):
        resp = await client.post("/channels/not-hex/close")
        assert resp.status_code == 400

    async def test_close_nonexistent(self, client):
        resp = await client.post(f"/channels/{'cc' * 32}/close")
        assert resp.status_code == 404

    async def test_close_already_settled(self, client):
        """Closing an already-settled channel should fail."""
        # Open
        open_resp = await client.post(
            "/channels",
            data=_json(
                {
                    "peer_id": "QmPeer",
                    "receiver": "0x" + "11" * 20,
                    "deposit": 100_000,
                }
            ),
            headers=_headers(),
        )
        cid = (await open_resp.get_json())["channel"]["channel_id"]
        # Close once
        await client.post(f"/channels/{cid}/close")
        # Try close again
        resp = await client.post(f"/channels/{cid}/close")
        assert resp.status_code == 400  # ChannelError: already SETTLED


# ═══════════════════════════════════════════════════════════════════════════
# POST /connect — Peer connection edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestConnectEndpoint:
    async def test_connect_success(self, client, mock_node):
        resp = await client.post(
            "/connect",
            data=_json(
                {
                    "multiaddr": "/ip4/127.0.0.1/tcp/9000/p2p/QmPeer",
                }
            ),
            headers=_headers(),
        )
        assert resp.status_code == 200
        data = await resp.get_json()
        assert data["status"] == "connected"
        mock_node._connect_mock.assert_called_once()

    async def test_connect_missing_multiaddr(self, client):
        resp = await client.post("/connect", data=_json({}), headers=_headers())
        assert resp.status_code == 400
        data = await resp.get_json()
        assert "multiaddr" in data["error"] or "required" in data["error"]

    async def test_connect_multiaddr_not_string(self, client):
        resp = await client.post("/connect", data=_json({"multiaddr": 12345}), headers=_headers())
        assert resp.status_code == 400

    async def test_connect_multiaddr_empty_string(self, client):
        resp = await client.post("/connect", data=_json({"multiaddr": ""}), headers=_headers())
        assert resp.status_code == 400

    async def test_connect_no_json(self, client):
        resp = await client.post("/connect")
        assert resp.status_code == 400

    async def test_connect_failure_returns_500(self, client, mock_node):
        mock_node._connect_mock.side_effect = ConnectionError("refused")
        resp = await client.post(
            "/connect",
            data=_json(
                {
                    "multiaddr": "/ip4/10.0.0.1/tcp/9000/p2p/QmBad",
                }
            ),
            headers=_headers(),
        )
        assert resp.status_code == 500
        assert "refused" in (await resp.get_json())["error"]


# ═══════════════════════════════════════════════════════════════════════════
# GET /balance — Balance aggregation edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestBalanceEdgeCases:
    async def test_balance_with_multiple_channels(self, client):
        """Open 3 channels with different deposits, pay on some."""
        for dep in [100_000, 200_000, 300_000]:
            await client.post(
                "/channels",
                data=_json(
                    {
                        "peer_id": f"QmPeer{dep}",
                        "receiver": "0x" + f"{dep:040x}",
                        "deposit": dep,
                    }
                ),
                headers=_headers(),
            )

        resp = await client.get("/balance")
        data = await resp.get_json()
        assert data["total_deposited"] == 600_000
        assert data["total_paid"] == 0
        assert data["total_remaining"] == 600_000
        assert data["channel_count"] == 3

    async def test_balance_address_populated(self, client, mock_node):
        resp = await client.get("/balance")
        data = await resp.get_json()
        assert data["address"] == mock_node.wallet.address

    async def test_balance_after_pay_and_close(self, client):
        """Balance should still count closed channels."""
        open_resp = await client.post(
            "/channels",
            data=_json(
                {
                    "peer_id": "QmPayee",
                    "receiver": "0x" + "aa" * 20,
                    "deposit": 500_000,
                }
            ),
            headers=_headers(),
        )
        cid = (await open_resp.get_json())["channel"]["channel_id"]

        # Pay
        await client.post(
            "/pay", data=_json({"channel_id": cid, "amount": 100_000}), headers=_headers()
        )
        # Close
        await client.post(f"/channels/{cid}/close")

        resp = await client.get("/balance")
        data = await resp.get_json()
        assert data["total_deposited"] == 500_000
        assert data["total_paid"] == 100_000
        assert data["total_remaining"] == 400_000
        assert data["channel_count"] == 1  # Still counted


# ═══════════════════════════════════════════════════════════════════════════
# GET /identity — Identity edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestIdentityEdgeCases:
    async def test_identity_fields_present(self, client, mock_node):
        resp = await client.get("/identity")
        data = await resp.get_json()
        assert "peer_id" in data
        assert "eth_address" in data
        assert "addrs" in data
        assert "connected_peers" in data

    async def test_identity_peer_id_matches(self, client):
        resp = await client.get("/identity")
        data = await resp.get_json()
        assert data["peer_id"] == "12D3KooWTestPeerId"

    async def test_identity_with_no_host(self, client, mock_node):
        """When host is None, connected_peers should be 0."""
        mock_node.host = None
        resp = await client.get("/identity")
        data = await resp.get_json()
        assert data["connected_peers"] == 0
