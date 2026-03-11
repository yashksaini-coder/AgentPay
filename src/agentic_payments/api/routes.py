"""REST API endpoints for the agentic payments node."""

from __future__ import annotations

from typing import Any

import structlog
from quart import request
from quart_trio import QuartTrio

logger = structlog.get_logger(__name__)


def register_routes(app: QuartTrio) -> None:
    """Register all API routes on the Quart app."""

    def _node() -> Any:
        return app.config["node"]

    @app.route("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "0.1.0"}

    @app.route("/peers")
    async def list_peers() -> dict:
        node = _node()
        peers = node.discovery.get_peers() if node.discovery else []
        connected_count = node.discovery.connected_count if node.discovery else 0
        return {"peers": peers, "count": len(peers), "connected": connected_count}

    @app.route("/channels")
    async def list_channels() -> dict:
        node = _node()
        channels = [ch.to_dict() for ch in node.channel_manager.list_channels()]
        return {"channels": channels, "count": len(channels)}

    @app.route("/channels/<channel_id>")
    async def get_channel(channel_id: str) -> tuple[dict, int]:
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            return {"error": "Invalid channel ID: not valid hex"}, 400
        try:
            ch = node.channel_manager.get_channel(cid)
            return ch.to_dict(), 200
        except KeyError:
            return {"error": "Channel not found"}, 404

    @app.route("/connect", methods=["POST"])
    async def connect_peer() -> tuple[dict, int]:
        """Connect to a peer by multiaddr.

        JSON body: {"multiaddr": "/ip4/.../tcp/.../p2p/..."}
        """
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        maddr = data.get("multiaddr")
        if not maddr or not isinstance(maddr, str):
            return {"error": "multiaddr is required"}, 400

        try:
            await node.connect(maddr)
            return {"status": "connected", "multiaddr": maddr}, 200
        except Exception as e:
            logger.exception("api_connect_peer_error")
            return {"error": str(e)}, 500

    @app.route("/channels", methods=["POST"])
    async def open_channel() -> tuple[dict, int]:
        """Open a new payment channel.

        JSON body: {"peer_id": "...", "receiver": "0x...", "deposit": 1000000}
        """
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        peer_id = data.get("peer_id")
        receiver = data.get("receiver")
        deposit = data.get("deposit")

        if not peer_id or not isinstance(peer_id, str):
            return {"error": "peer_id is required and must be a string"}, 400
        if not receiver or not isinstance(receiver, str):
            return {"error": "receiver is required and must be a string"}, 400
        if deposit is None:
            return {"error": "deposit is required"}, 400

        try:
            deposit_int = int(deposit)
        except (ValueError, TypeError):
            return {"error": "deposit must be an integer"}, 400
        if deposit_int <= 0:
            return {"error": "deposit must be a positive integer"}, 400

        # Validate receiver looks like an Ethereum address
        if not receiver.startswith("0x") or len(receiver) != 42:
            return {"error": "receiver must be a valid Ethereum address (0x + 40 hex chars)"}, 400

        try:
            channel = await node.open_payment_channel(
                peer_id=peer_id,
                receiver=receiver,
                deposit=deposit_int,
            )
            return {"channel": channel.to_dict()}, 201
        except Exception as e:
            logger.exception("api_open_channel_error")
            return {"error": str(e)}, 500

    @app.route("/pay", methods=["POST"])
    async def send_payment() -> tuple[dict, int]:
        """Send a micropayment on an existing channel.

        JSON body: {"channel_id": "hex...", "amount": 100000}
        """
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        channel_id_hex = data.get("channel_id")
        amount = data.get("amount")

        if not channel_id_hex or not isinstance(channel_id_hex, str):
            return {"error": "channel_id is required and must be a string"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400

        try:
            amount_int = int(amount)
        except (ValueError, TypeError):
            return {"error": "amount must be an integer"}, 400
        if amount_int <= 0:
            return {"error": "amount must be a positive integer"}, 400

        try:
            cid = bytes.fromhex(channel_id_hex)
        except ValueError:
            return {"error": "channel_id is not valid hex"}, 400

        try:
            voucher = await node.pay(channel_id=cid, amount=amount_int)
            return {"voucher": voucher.to_json_dict()}, 200
        except KeyError:
            return {"error": "Channel not found"}, 404
        except Exception as e:
            logger.exception("api_send_payment_error")
            return {"error": str(e)}, 500

    @app.route("/channels/<channel_id>/close", methods=["POST"])
    async def close_channel(channel_id: str) -> tuple[dict, int]:
        """Close a payment channel."""
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            return {"error": "Invalid channel ID: not valid hex"}, 400

        try:
            await node.close_channel(cid)
            ch = node.channel_manager.get_channel(cid)
            return {"channel": ch.to_dict()}, 200
        except KeyError:
            return {"error": "Channel not found"}, 404
        except Exception as e:
            logger.exception("api_close_channel_error")
            return {"error": str(e)}, 500

    @app.route("/balance")
    async def balance() -> dict:
        node = _node()
        channels = node.channel_manager.list_channels()
        total_deposited = sum(ch.total_deposit for ch in channels)
        total_paid = sum(ch.total_paid for ch in channels)
        return {
            "address": node.wallet.address if node.wallet else None,
            "total_deposited": total_deposited,
            "total_paid": total_paid,
            "total_remaining": total_deposited - total_paid,
            "channel_count": len(channels),
        }

    @app.route("/identity")
    async def identity() -> dict:
        node = _node()
        return {
            "peer_id": node.peer_id.to_base58() if node.peer_id else None,
            "eth_address": node.wallet.address if node.wallet else None,
            "addrs": node.listen_addrs,
            "connected_peers": len(node.get_connected_peers()) if node.host else 0,
        }
