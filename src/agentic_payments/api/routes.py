"""REST API endpoints for the agentic payments node."""

from __future__ import annotations

import time
from typing import Any

import structlog
from quart import request, websocket
from quart_trio import QuartTrio

from agentic_payments.payments.channel import ChannelError

logger = structlog.get_logger(__name__)


def register_routes(app: QuartTrio) -> None:
    """Register all API routes on the Quart app."""

    def _node() -> Any:
        return app.config["node"]

    # ── Logging helper ──────────────────────────────────────────

    def _log_api(
        endpoint: str,
        status: int,
        duration_ms: float,
        *,
        method: str = "GET",
        detail: str = "",
        error: str = "",
    ) -> None:
        """Log every API call with result and timing."""
        if status < 400:
            # GET reads are noisy from polling — log at debug
            log_fn = logger.debug if method == "GET" else logger.info
            log_fn(
                "api_response",
                endpoint=endpoint,
                method=method,
                status=status,
                duration_ms=round(duration_ms, 1),
                detail=detail or None,
            )
        else:
            logger.warning(
                "api_error",
                endpoint=endpoint,
                method=method,
                status=status,
                duration_ms=round(duration_ms, 1),
                error=error or f"HTTP {status}",
            )

    # ── Health ──────────────────────────────────────────────────

    @app.route("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "0.1.0"}

    # ── WebSocket push endpoint ─────────────────────────────────

    @app.websocket("/ws")
    async def ws_state() -> None:
        """Push agent state to connected frontends.

        Sends a JSON snapshot of identity + balance + peers + channels
        every time a change is detected, or at minimum every 2 seconds.
        """
        import json
        import trio

        try:
            await websocket.accept()
        except Exception:
            logger.warning("ws_accept_failed", exc_info=True)
            return

        node = _node()
        logger.info("ws_client_connected")

        def _snapshot() -> dict:
            """Build current state snapshot."""
            channels = node.channel_manager.list_channels() if node.channel_manager else []
            ch_list = [ch.to_dict() for ch in channels]
            total_deposited = sum(ch.total_deposit for ch in channels)
            total_paid = sum(ch.total_paid for ch in channels)
            peers = node.discovery.get_peers() if node.discovery else []
            connected = node.discovery.connected_count if node.discovery else 0
            return {
                "type": "state",
                "identity": {
                    "peer_id": node.peer_id.to_base58() if node.peer_id else None,
                    "eth_address": node.wallet.address if node.wallet else None,
                    "addrs": node.listen_addrs,
                    "connected_peers": len(node.get_connected_peers()) if node.host else 0,
                },
                "balance": {
                    "address": node.wallet.address if node.wallet else None,
                    "total_deposited": total_deposited,
                    "total_paid": total_paid,
                    "total_remaining": total_deposited - total_paid,
                    "channel_count": len(channels),
                },
                "peers": {"peers": peers, "count": len(peers), "connected": connected},
                "channels": {"channels": ch_list, "count": len(ch_list)},
            }

        prev_hash = ""
        try:
            while True:
                snap = _snapshot()
                snap_json = json.dumps(snap, sort_keys=True)
                h = str(hash(snap_json))
                if h != prev_hash:
                    await websocket.send(snap_json)
                    prev_hash = h
                await trio.sleep(1.5)
        except Exception:
            logger.debug("ws_client_disconnected")

    # ── REST endpoints ──────────────────────────────────────────

    @app.route("/peers")
    async def list_peers() -> dict:
        t0 = time.monotonic()
        node = _node()
        peers = node.discovery.get_peers() if node.discovery else []
        connected_count = node.discovery.connected_count if node.discovery else 0
        result = {"peers": peers, "count": len(peers), "connected": connected_count}
        _log_api("/peers", 200, (time.monotonic() - t0) * 1000, detail=f"{len(peers)} peers")
        return result

    @app.route("/channels")
    async def list_channels() -> dict:
        t0 = time.monotonic()
        node = _node()
        channels = [ch.to_dict() for ch in node.channel_manager.list_channels()]
        result = {"channels": channels, "count": len(channels)}
        _log_api("/channels", 200, (time.monotonic() - t0) * 1000, detail=f"{len(channels)} channels")
        return result

    @app.route("/channels/<channel_id>")
    async def get_channel(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            _log_api(f"/channels/{channel_id[:8]}", 400, (time.monotonic() - t0) * 1000, error="invalid hex")
            return {"error": "Invalid channel ID: not valid hex"}, 400
        try:
            ch = node.channel_manager.get_channel(cid)
            _log_api(f"/channels/{channel_id[:8]}", 200, (time.monotonic() - t0) * 1000, detail=ch.state.name)
            return ch.to_dict(), 200
        except KeyError:
            _log_api(f"/channels/{channel_id[:8]}", 404, (time.monotonic() - t0) * 1000, error="not found")
            return {"error": "Channel not found"}, 404

    @app.route("/connect", methods=["POST"])
    async def connect_peer() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        maddr = data.get("multiaddr")
        if not maddr or not isinstance(maddr, str):
            return {"error": "multiaddr is required"}, 400

        try:
            await node.connect(maddr)
            _log_api("/connect", 200, (time.monotonic() - t0) * 1000, method="POST", detail=maddr[-20:])
            return {"status": "connected", "multiaddr": maddr}, 200
        except ValueError as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/connect", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.exception("api_connect_peer_error")
            _log_api("/connect", 500, ms, method="POST", error=str(e)[:60])
            return {"error": str(e)}, 500

    @app.route("/channels", methods=["POST"])
    async def open_channel() -> tuple[dict, int]:
        t0 = time.monotonic()
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

        if not receiver.startswith("0x") or len(receiver) != 42:
            return {"error": "receiver must be a valid Ethereum address (0x + 40 hex chars)"}, 400

        try:
            channel = await node.open_payment_channel(
                peer_id=peer_id,
                receiver=receiver,
                deposit=deposit_int,
            )
            ms = (time.monotonic() - t0) * 1000
            _log_api("/channels", 201, ms, method="POST", detail=f"opened {channel.channel_id.hex()[:12]} deposit={deposit_int}")
            return {"channel": channel.to_dict()}, 201
        except (ChannelError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/channels", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.exception("api_open_channel_error")
            _log_api("/channels", 500, ms, method="POST", error=str(e)[:60])
            return {"error": str(e)}, 500

    @app.route("/pay", methods=["POST"])
    async def send_payment() -> tuple[dict, int]:
        t0 = time.monotonic()
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
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pay", 200, ms, method="POST", detail=f"nonce={voucher.nonce} amount={amount_int}")
            return {"voucher": voucher.to_json_dict()}, 200
        except KeyError:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pay", 404, ms, method="POST", error="channel not found")
            return {"error": "Channel not found"}, 404
        except (ChannelError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pay", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.exception("api_send_payment_error")
            _log_api("/pay", 500, ms, method="POST", error=str(e)[:60])
            return {"error": str(e)}, 500

    @app.route("/channels/<channel_id>/close", methods=["POST"])
    async def close_channel(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            return {"error": "Invalid channel ID: not valid hex"}, 400

        try:
            await node.close_channel(cid)
            ch = node.channel_manager.get_channel(cid)
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/channels/{channel_id[:8]}/close", 200, ms, method="POST", detail=f"settled nonce={ch.nonce}")
            return {"channel": ch.to_dict()}, 200
        except KeyError:
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/channels/{channel_id[:8]}/close", 404, ms, method="POST", error="not found")
            return {"error": "Channel not found"}, 404
        except (ChannelError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/channels/{channel_id[:8]}/close", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.exception("api_close_channel_error")
            _log_api(f"/channels/{channel_id[:8]}/close", 500, ms, method="POST", error=str(e)[:60])
            return {"error": str(e)}, 500

    @app.route("/balance")
    async def balance() -> dict:
        t0 = time.monotonic()
        node = _node()
        channels = node.channel_manager.list_channels()
        total_deposited = sum(ch.total_deposit for ch in channels)
        total_paid = sum(ch.total_paid for ch in channels)
        result = {
            "address": node.wallet.address if node.wallet else None,
            "total_deposited": total_deposited,
            "total_paid": total_paid,
            "total_remaining": total_deposited - total_paid,
            "channel_count": len(channels),
        }
        _log_api("/balance", 200, (time.monotonic() - t0) * 1000, detail=f"remaining={total_deposited - total_paid}")
        return result

    @app.route("/identity")
    async def identity() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = {
            "peer_id": node.peer_id.to_base58() if node.peer_id else None,
            "eth_address": node.wallet.address if node.wallet else None,
            "addrs": node.listen_addrs,
            "connected_peers": len(node.get_connected_peers()) if node.host else 0,
        }
        _log_api("/identity", 200, (time.monotonic() - t0) * 1000, detail=result.get("peer_id", "")[:12])
        return result

    @app.route("/graph")
    async def network_graph() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = node.network_graph.to_dict()
        _log_api("/graph", 200, (time.monotonic() - t0) * 1000, detail=f"{result['peer_count']}p/{result['channel_count']}ch")
        return result

    @app.route("/route", methods=["POST"])
    async def find_route_endpoint() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        destination = data.get("destination")
        amount = data.get("amount")

        if not destination or not isinstance(destination, str):
            return {"error": "destination peer_id is required"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400

        try:
            amount_int = int(amount)
        except (ValueError, TypeError):
            return {"error": "amount must be an integer"}, 400
        if amount_int <= 0:
            return {"error": "amount must be positive"}, 400

        known_channels = data.get("known_channels")
        if known_channels and isinstance(known_channels, list):
            for ch in known_channels:
                cid = ch.get("channel_id")
                pa = ch.get("peer_a")
                pb = ch.get("peer_b")
                cap = ch.get("capacity")
                if cid and pa and pb and cap:
                    node.network_graph.add_channel(cid, pa, pb, int(cap))

        route = node.find_route(destination, amount_int)
        ms = (time.monotonic() - t0) * 1000
        if route is None:
            _log_api("/route", 404, ms, method="POST", error=f"no route to {destination[:12]}")
            return {"error": "No route found", "destination": destination, "amount": amount_int}, 404

        _log_api("/route", 200, ms, method="POST", detail=f"{route.hop_count} hops to {destination[:12]}")
        return {"route": route.to_dict()}, 200

    @app.route("/route-pay", methods=["POST"])
    async def route_pay() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        destination = data.get("destination")
        amount = data.get("amount")

        if not destination or not isinstance(destination, str):
            return {"error": "destination peer_id is required"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400

        try:
            amount_int = int(amount)
        except (ValueError, TypeError):
            return {"error": "amount must be an integer"}, 400
        if amount_int <= 0:
            return {"error": "amount must be positive"}, 400

        known_channels = data.get("known_channels")
        if known_channels and isinstance(known_channels, list):
            for ch in known_channels:
                cid = ch.get("channel_id")
                pa = ch.get("peer_a")
                pb = ch.get("peer_b")
                cap = ch.get("capacity")
                if cid and pa and pb and cap:
                    node.network_graph.add_channel(cid, pa, pb, int(cap))

        try:
            result = await node.route_payment(destination, amount_int)
            ms = (time.monotonic() - t0) * 1000
            hops = result.get("route", {}).get("hop_count", "?")
            _log_api("/route-pay", 200, ms, method="POST", detail=f"amount={amount_int} hops={hops} to {destination[:12]}")
            return {"payment": result}, 200
        except (RuntimeError, ChannelError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/route-pay", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            logger.exception("api_route_pay_error")
            _log_api("/route-pay", 500, ms, method="POST", error=str(e)[:60])
            return {"error": str(e)}, 500
