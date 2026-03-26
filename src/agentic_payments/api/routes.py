"""REST API endpoints for the agentic payments node."""

from __future__ import annotations

import time
from typing import Any

import structlog
from quart import request, websocket
from quart_trio import QuartTrio

from agentic_payments.disputes.models import DisputeReason, DisputeResolution
from agentic_payments.gateway.x402 import AccessDecision, GatedResource, PaymentProof
from agentic_payments.agent.task import AgentTask, TaskStatus
from agentic_payments.node.roles import AgentRole, RoleAssignment, WorkRound
from agentic_payments.negotiation.models import SLATerms
from agentic_payments.payments.channel import ChannelError
from agentic_payments.policies.engine import WalletPolicy
from agentic_payments.pricing.engine import PricingPolicy

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
                "reputation": {
                    "peers": [r.to_dict() for r in node.reputation_tracker.get_all()],
                }
                if hasattr(node, "reputation_tracker")
                else {},
                "discovery": {
                    "agents": [a.to_dict() for a in node.capability_registry.search()],
                }
                if hasattr(node, "capability_registry")
                else {},
                "negotiations": {
                    "active": [n.to_dict() for n in node.negotiation_manager.list_active()],
                }
                if hasattr(node, "negotiation_manager")
                else {},
                "disputes": {
                    "active": [
                        d.to_dict() for d in node.dispute_monitor.list_disputes(pending_only=True)
                    ],
                }
                if node.dispute_monitor
                else {},
                "pricing": node.pricing_engine.policy.to_dict() if node.pricing_engine else {},
                "sla": {
                    "violations": len(node.sla_monitor.get_violations()),
                    "non_compliant": node.sla_monitor.get_non_compliant_channels(),
                },
                "chain_type": node.config.chain_type,
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
        _log_api(
            "/channels", 200, (time.monotonic() - t0) * 1000, detail=f"{len(channels)} channels"
        )
        return result

    @app.route("/channels/<channel_id>")
    async def get_channel(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            _log_api(
                f"/channels/{channel_id[:8]}",
                400,
                (time.monotonic() - t0) * 1000,
                error="invalid hex",
            )
            return {"error": "Invalid channel ID: not valid hex"}, 400
        try:
            ch = node.channel_manager.get_channel(cid)
            _log_api(
                f"/channels/{channel_id[:8]}",
                200,
                (time.monotonic() - t0) * 1000,
                detail=ch.state.name,
            )
            return ch.to_dict(), 200
        except KeyError:
            _log_api(
                f"/channels/{channel_id[:8]}",
                404,
                (time.monotonic() - t0) * 1000,
                error="not found",
            )
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
            _log_api(
                "/connect", 200, (time.monotonic() - t0) * 1000, method="POST", detail=maddr[-20:]
            )
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
            _log_api(
                "/channels",
                201,
                ms,
                method="POST",
                detail=f"opened {channel.channel_id.hex()[:12]} deposit={deposit_int}",
            )
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

        task_id = data.get("task_id", "")
        try:
            voucher = await node.pay(channel_id=cid, amount=amount_int, task_id=task_id)
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                "/pay", 200, ms, method="POST", detail=f"nonce={voucher.nonce} amount={amount_int}"
            )
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
            _log_api(
                f"/channels/{channel_id[:8]}/close",
                200,
                ms,
                method="POST",
                detail=f"settled nonce={ch.nonce}",
            )
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
        _log_api(
            "/balance",
            200,
            (time.monotonic() - t0) * 1000,
            detail=f"remaining={total_deposited - total_paid}",
        )
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
            "eip191_bound": node.identity_proof is not None
            if hasattr(node, "identity_proof")
            else False,
            "verified_peers": list(node._verified_identities.keys())
            if hasattr(node, "_verified_identities")
            else [],
        }
        _log_api(
            "/identity", 200, (time.monotonic() - t0) * 1000, detail=result.get("peer_id", "")[:12]
        )
        return result

    @app.route("/graph")
    async def network_graph() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = node.network_graph.to_dict()
        _log_api(
            "/graph",
            200,
            (time.monotonic() - t0) * 1000,
            detail=f"{result['peer_count']}p/{result['channel_count']}ch",
        )
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
            return {
                "error": "No route found",
                "destination": destination,
                "amount": amount_int,
            }, 404

        _log_api(
            "/route", 200, ms, method="POST", detail=f"{route.hop_count} hops to {destination[:12]}"
        )
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
            _log_api(
                "/route-pay",
                200,
                ms,
                method="POST",
                detail=f"amount={amount_int} hops={hops} to {destination[:12]}",
            )
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

    # ── Discovery endpoints ─────────────────────────────────────

    @app.route("/discovery/agents")
    async def discovery_agents() -> dict:
        t0 = time.monotonic()
        node = _node()
        capability = request.args.get("capability")
        agents = node.capability_registry.search(capability)
        result = {
            "agents": [a.to_dict() for a in agents],
            "count": len(agents),
        }
        _log_api(
            "/discovery/agents", 200, (time.monotonic() - t0) * 1000, detail=f"{len(agents)} agents"
        )
        return result

    @app.route("/discovery/resources")
    async def discovery_resources() -> dict:
        t0 = time.monotonic()
        node = _node()
        bazaar = node.capability_registry.to_bazaar_format()
        _log_api(
            "/discovery/resources",
            200,
            (time.monotonic() - t0) * 1000,
            detail=f"{len(bazaar)} providers",
        )
        return {"providers": bazaar, "count": len(bazaar)}

    # ── Negotiation endpoints ───────────────────────────────────

    @app.route("/negotiate", methods=["POST"])
    async def negotiate() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400

        peer_id = data.get("peer_id")
        service_type = data.get("service_type")
        proposed_price = data.get("proposed_price")
        channel_deposit = data.get("channel_deposit")

        if not peer_id:
            return {"error": "peer_id is required"}, 400
        if not service_type:
            return {"error": "service_type is required"}, 400
        if proposed_price is None:
            return {"error": "proposed_price is required"}, 400
        if channel_deposit is None:
            return {"error": "channel_deposit is required"}, 400

        sla_data = data.get("sla_terms")
        sla_terms = SLATerms.from_dict(sla_data) if sla_data else None

        try:
            result = await node.negotiate(
                peer_id=peer_id,
                service_type=service_type,
                proposed_price=int(proposed_price),
                channel_deposit=int(channel_deposit),
                sla_terms=sla_terms,
            )
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                "/negotiate", 201, ms, method="POST", detail=f"id={result['negotiation_id'][:12]}"
            )
            return {"negotiation": result}, 201
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/negotiate", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    @app.route("/negotiations")
    async def list_negotiations() -> dict:
        t0 = time.monotonic()
        node = _node()
        negs = node.negotiation_manager.list_all()
        result = {"negotiations": [n.to_dict() for n in negs], "count": len(negs)}
        _log_api(
            "/negotiations", 200, (time.monotonic() - t0) * 1000, detail=f"{len(negs)} negotiations"
        )
        return result

    @app.route("/negotiations/<negotiation_id>")
    async def get_negotiation(negotiation_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            neg = node.negotiation_manager.get(negotiation_id)
            _log_api(f"/negotiations/{negotiation_id[:8]}", 200, (time.monotonic() - t0) * 1000)
            return {"negotiation": neg.to_dict()}, 200
        except KeyError:
            _log_api(
                f"/negotiations/{negotiation_id[:8]}",
                404,
                (time.monotonic() - t0) * 1000,
                error="not found",
            )
            return {"error": "Negotiation not found"}, 404

    @app.route("/negotiations/<negotiation_id>/counter", methods=["POST"])
    async def counter_negotiation(negotiation_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        counter_price = data.get("counter_price")
        if counter_price is None:
            return {"error": "counter_price is required"}, 400
        try:
            by = node.peer_id.to_base58() if node.peer_id else ""
            neg = node.negotiation_manager.counter(negotiation_id, by, int(counter_price))
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/negotiations/{negotiation_id[:8]}/counter", 200, ms, method="POST")
            return {"negotiation": neg.to_dict()}, 200
        except (KeyError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                f"/negotiations/{negotiation_id[:8]}/counter", 400, ms, method="POST", error=str(e)
            )
            return {"error": str(e)}, 400

    @app.route("/negotiations/<negotiation_id>/accept", methods=["POST"])
    async def accept_negotiation(negotiation_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            by = node.peer_id.to_base58() if node.peer_id else ""
            neg = node.negotiation_manager.accept(negotiation_id, by)
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/negotiations/{negotiation_id[:8]}/accept", 200, ms, method="POST")
            return {"negotiation": neg.to_dict()}, 200
        except (KeyError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                f"/negotiations/{negotiation_id[:8]}/accept", 400, ms, method="POST", error=str(e)
            )
            return {"error": str(e)}, 400

    @app.route("/negotiations/<negotiation_id>/reject", methods=["POST"])
    async def reject_negotiation(negotiation_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            by = node.peer_id.to_base58() if node.peer_id else ""
            neg = node.negotiation_manager.reject(negotiation_id, by)
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/negotiations/{negotiation_id[:8]}/reject", 200, ms, method="POST")
            return {"negotiation": neg.to_dict()}, 200
        except (KeyError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                f"/negotiations/{negotiation_id[:8]}/reject", 400, ms, method="POST", error=str(e)
            )
            return {"error": str(e)}, 400

    # ── Policy endpoints ────────────────────────────────────────

    @app.route("/policies")
    async def get_policies() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = node.policy_engine.get_stats()
        _log_api("/policies", 200, (time.monotonic() - t0) * 1000)
        return result

    @app.route("/policies", methods=["PUT"])
    async def update_policies() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        try:
            policy = WalletPolicy.from_dict(data)
            node.policy_engine.update_policy(policy)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/policies", 200, ms, method="PUT")
            return {"policy": policy.to_dict()}, 200
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/policies", 400, ms, method="PUT", error=str(e))
            return {"error": str(e)}, 400

    # ── Reputation endpoints ────────────────────────────────────

    @app.route("/reputation")
    async def get_all_reputation() -> dict:
        t0 = time.monotonic()
        node = _node()
        reps = node.reputation_tracker.get_all()
        result = {"peers": [r.to_dict() for r in reps], "count": len(reps)}
        _log_api("/reputation", 200, (time.monotonic() - t0) * 1000, detail=f"{len(reps)} peers")
        return result

    @app.route("/reputation/<peer_id>")
    async def get_peer_reputation(peer_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        rep = node.reputation_tracker.get_reputation(peer_id)
        if rep is None:
            _log_api(
                f"/reputation/{peer_id[:12]}",
                404,
                (time.monotonic() - t0) * 1000,
                error="not found",
            )
            return {"error": "No reputation data for peer"}, 404
        _log_api(f"/reputation/{peer_id[:12]}", 200, (time.monotonic() - t0) * 1000)
        return {"reputation": rep.to_dict()}, 200

    # ── Receipt endpoints ───────────────────────────────────────

    @app.route("/receipts")
    async def list_receipts() -> dict:
        t0 = time.monotonic()
        node = _node()
        channels = node.receipt_store.list_channels()
        result = {
            "channels": [
                {
                    "channel_id": cid.hex(),
                    "receipt_count": len(node.receipt_store.get_chain(cid)),
                    "chain_valid": node.receipt_store.verify_chain(cid),
                }
                for cid in channels
            ],
            "count": len(channels),
        }
        _log_api(
            "/receipts", 200, (time.monotonic() - t0) * 1000, detail=f"{len(channels)} channels"
        )
        return result

    @app.route("/receipts/<channel_id>")
    async def get_receipts(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            cid = bytes.fromhex(channel_id)
        except ValueError:
            return {"error": "Invalid channel ID hex"}, 400
        chain = node.receipt_store.get_chain(cid)
        result = {
            "channel_id": channel_id,
            "receipts": [r.to_dict() for r in chain],
            "count": len(chain),
            "chain_valid": node.receipt_store.verify_chain(cid),
        }
        _log_api(
            f"/receipts/{channel_id[:8]}",
            200,
            (time.monotonic() - t0) * 1000,
            detail=f"{len(chain)} receipts",
        )
        return result, 200

    # ── ERC-8004 Identity endpoints ─────────────────────────────

    @app.route("/identity/erc8004")
    async def identity_erc8004() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.identity_bridge:
            _log_api("/identity/erc8004", 200, (time.monotonic() - t0) * 1000)
            return {"enabled": False, "registered_on_chain": False}, 200
        identity = node.identity_bridge.identity
        result = (
            identity.to_dict()
            if identity
            else {
                "enabled": True,
                "registered_on_chain": False,
                "eth_address": node.wallet.address if node.wallet else "",
                "peer_id": node.peer_id.to_base58() if node.peer_id else "",
            }
        )
        result["enabled"] = True
        _log_api("/identity/erc8004", 200, (time.monotonic() - t0) * 1000)
        return result, 200

    @app.route("/identity/erc8004/register", methods=["POST"])
    async def identity_erc8004_register() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.identity_bridge or not node.wallet:
            return {"error": "ERC-8004 not configured"}, 503
        try:
            identity = await node.identity_bridge.ensure_registered(node.wallet)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/identity/erc8004/register", 200, ms, method="POST")
            return identity.to_dict(), 200
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/identity/erc8004/register", 500, ms, method="POST", error=str(e))
            return {"error": str(e)}, 500

    @app.route("/identity/erc8004/lookup/<int:agent_id>")
    async def identity_erc8004_lookup(agent_id: int) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.erc8004_client:
            return {"error": "ERC-8004 not configured"}, 503
        identity = await node.erc8004_client.lookup_agent(agent_id)
        if not identity:
            return {"error": "Agent not found"}, 404
        _log_api(f"/identity/erc8004/lookup/{agent_id}", 200, (time.monotonic() - t0) * 1000)
        return identity.to_dict(), 200

    @app.route("/reputation/sync-onchain", methods=["POST"])
    async def reputation_sync_onchain() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.identity_bridge or not node.wallet:
            return {"error": "ERC-8004 not configured"}, 503
        data = await request.get_json()
        peer_id = data.get("peer_id", "") if data else ""
        if not peer_id:
            return {"error": "peer_id required"}, 400
        rep = node.reputation_tracker.get_reputation(peer_id)
        if not rep:
            return {"error": f"No reputation data for {peer_id}"}, 404
        try:
            tx_hash = await node.identity_bridge.sync_reputation(
                rep.trust_score, node.wallet, tag="payment"
            )
            ms = (time.monotonic() - t0) * 1000
            _log_api("/reputation/sync-onchain", 200, ms, method="POST")
            return {
                "peer_id": peer_id,
                "trust_score": rep.trust_score,
                "erc8004_score": round(rep.trust_score * 100),
                "tx_hash": tx_hash,
                "synced": tx_hash is not None,
            }, 200
        except Exception as e:
            return {"error": str(e)}, 500

    # ── Gateway endpoints ───────────────────────────────────────

    @app.route("/gateway/resources")
    async def gateway_resources() -> dict:
        t0 = time.monotonic()
        node = _node()
        bazaar = node.gateway.to_bazaar_format()
        _log_api("/gateway/resources", 200, (time.monotonic() - t0) * 1000)
        return bazaar

    @app.route("/gateway/register", methods=["POST"])
    async def gateway_register() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        path = data.get("path")
        price = data.get("price")
        if not path:
            return {"error": "path is required"}, 400
        if price is None:
            return {"error": "price is required"}, 400
        try:
            resource = GatedResource(
                path=path,
                price=int(price),
                description=data.get("description", ""),
                payment_type=data.get("payment_type", "payment-channel"),
            )
            node.gateway.register_resource(resource)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/gateway/register", 201, ms, method="POST", detail=path)
            return {"resource": resource.to_dict()}, 201
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/gateway/register", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    @app.route("/gateway/access", methods=["POST"])
    async def gateway_access() -> tuple[dict, int]:
        """Verify payment and grant access to a gated resource (x402 flow)."""
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        path = data.get("path")
        if not path:
            return {"error": "path is required"}, 400

        proof = None
        if "channel_id" in data:
            proof = PaymentProof.from_dict(data)

        decision, meta = node.gateway.verify_access(path, proof)

        if decision == AccessDecision.PAYMENT_REQUIRED:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/gateway/access", 402, ms, method="POST", detail=path)
            return meta, 402
        elif decision == AccessDecision.GRANTED:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/gateway/access", 200, ms, method="POST", detail=path)
            return meta, 200
        else:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/gateway/access", 403, ms, method="POST", error=str(meta))
            return meta, 403

    @app.route("/gateway/pay-oneshot", methods=["POST"])
    async def gateway_pay_oneshot() -> tuple[dict, int]:
        """One-shot x402 payment for stateless per-request settlement."""
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        path = data.get("path")
        sender = data.get("sender")
        amount = data.get("amount")
        if not path:
            return {"error": "path is required"}, 400
        if not sender:
            return {"error": "sender is required"}, 400
        if amount is None:
            return {"error": "amount is required"}, 400
        try:
            amount_int = int(amount)
        except (ValueError, TypeError):
            return {"error": "amount must be an integer"}, 400

        decision, meta = node.gateway.settle_oneshot(
            path=path,
            sender=sender,
            amount=amount_int,
            signature=data.get("signature", ""),
            task_id=data.get("task_id", ""),
        )

        ms = (time.monotonic() - t0) * 1000
        if decision == AccessDecision.GRANTED:
            _log_api("/gateway/pay-oneshot", 200, ms, method="POST", detail=path)
            return meta, 200
        else:
            _log_api("/gateway/pay-oneshot", 402, ms, method="POST", detail=path)
            return meta, 402

    @app.route("/gateway/log")
    async def gateway_log() -> dict:
        """Return recent gateway access log entries."""
        t0 = time.monotonic()
        node = _node()
        log = node.gateway.get_access_log()
        _log_api("/gateway/log", 200, (time.monotonic() - t0) * 1000)
        return {"log": log, "count": len(log)}

    # ── Pricing endpoints ──────────────────────────────────────

    @app.route("/pricing/quote", methods=["POST"])
    async def pricing_quote() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        base_price = data.get("base_price")
        peer_id = data.get("peer_id")
        if base_price is None or not peer_id:
            return {"error": "base_price and peer_id are required"}, 400
        try:
            quote = node.pricing_engine.get_quote(int(base_price), peer_id)
            ms = (time.monotonic() - t0) * 1000
            _log_api(
                "/pricing/quote", 200, ms, method="POST", detail=f"final={quote['final_price']}"
            )
            return {"quote": quote}, 200
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pricing/quote", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    @app.route("/pricing/config")
    async def pricing_config() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = node.pricing_engine.policy.to_dict()
        _log_api("/pricing/config", 200, (time.monotonic() - t0) * 1000)
        return result

    @app.route("/pricing/config", methods=["PUT"])
    async def update_pricing_config() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        try:
            policy = PricingPolicy.from_dict(data)
            node.pricing_engine.update_policy(policy)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pricing/config", 200, ms, method="PUT")
            return {"policy": policy.to_dict()}, 200
        except Exception as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/pricing/config", 400, ms, method="PUT", error=str(e))
            return {"error": str(e)}, 400

    # ── Dispute endpoints ──────────────────────────────────────

    @app.route("/disputes")
    async def list_disputes() -> dict:
        t0 = time.monotonic()
        node = _node()
        pending_only = request.args.get("pending") == "true"
        disputes = node.dispute_monitor.list_disputes(pending_only=pending_only)
        result = {"disputes": [d.to_dict() for d in disputes], "count": len(disputes)}
        _log_api(
            "/disputes", 200, (time.monotonic() - t0) * 1000, detail=f"{len(disputes)} disputes"
        )
        return result

    @app.route("/disputes/<dispute_id>")
    async def get_dispute(dispute_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        try:
            dispute = node.dispute_monitor.get_dispute(dispute_id)
            _log_api(f"/disputes/{dispute_id[:8]}", 200, (time.monotonic() - t0) * 1000)
            return {"dispute": dispute.to_dict()}, 200
        except KeyError:
            _log_api(
                f"/disputes/{dispute_id[:8]}",
                404,
                (time.monotonic() - t0) * 1000,
                error="not found",
            )
            return {"error": "Dispute not found"}, 404

    @app.route("/disputes/scan", methods=["POST"])
    async def scan_disputes() -> dict:
        t0 = time.monotonic()
        node = _node()
        new_disputes = node.dispute_monitor.scan_channels()
        result = {
            "new_disputes": [d.to_dict() for d in new_disputes],
            "count": len(new_disputes),
        }
        _log_api(
            "/disputes/scan",
            200,
            (time.monotonic() - t0) * 1000,
            method="POST",
            detail=f"{len(new_disputes)} new",
        )
        return result

    @app.route("/channels/<channel_id>/dispute", methods=["POST"])
    async def file_dispute(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json() or {}
        reason_str = data.get("reason", "stale_voucher")
        try:
            cid = bytes.fromhex(channel_id)
            reason = DisputeReason(reason_str)
            peer_id_str = node.peer_id.to_base58() if node.peer_id else ""
            ch = node.channel_manager.get_channel(cid)
            counterparty = ch.peer_id
            dispute = node.dispute_monitor.file_dispute(
                channel_id=cid,
                reason=reason,
                initiated_by=peer_id_str,
                counterparty=counterparty,
            )
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/channels/{channel_id[:8]}/dispute", 201, ms, method="POST")
            return {"dispute": dispute.to_dict()}, 201
        except (KeyError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/channels/{channel_id[:8]}/dispute", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    @app.route("/disputes/<dispute_id>/resolve", methods=["POST"])
    async def resolve_dispute(dispute_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json() or {}
        resolution_str = data.get("resolution", "settled")
        try:
            resolution = DisputeResolution(resolution_str)
            dispute = node.dispute_monitor.resolve_dispute(dispute_id, resolution)
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/disputes/{dispute_id[:8]}/resolve", 200, ms, method="POST")
            return {"dispute": dispute.to_dict()}, 200
        except (KeyError, ValueError) as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/disputes/{dispute_id[:8]}/resolve", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    # ── SLA endpoints ──────────────────────────────────────────

    @app.route("/sla/violations")
    async def sla_violations() -> dict:
        t0 = time.monotonic()
        node = _node()
        violations = node.sla_monitor.get_violations()
        result = {
            "violations": [v.to_dict() for v in violations[:50]],
            "count": len(violations),
        }
        _log_api(
            "/sla/violations",
            200,
            (time.monotonic() - t0) * 1000,
            detail=f"{len(violations)} violations",
        )
        return result

    @app.route("/sla/channels")
    async def sla_channels() -> dict:
        t0 = time.monotonic()
        node = _node()
        channels = node.sla_monitor.list_monitored()
        result = {"channels": channels, "count": len(channels)}
        _log_api("/sla/channels", 200, (time.monotonic() - t0) * 1000)
        return result

    @app.route("/sla/channels/<channel_id>")
    async def sla_channel_status(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        status = node.sla_monitor.get_status(channel_id)
        if status is None:
            _log_api(
                f"/sla/channels/{channel_id[:8]}",
                404,
                (time.monotonic() - t0) * 1000,
                error="not monitored",
            )
            return {"error": "Channel not being SLA-monitored"}, 404
        _log_api(f"/sla/channels/{channel_id[:8]}", 200, (time.monotonic() - t0) * 1000)
        return {"sla": status}, 200

    # ── Chain info endpoint ────────────────────────────────────

    @app.route("/chain")
    async def chain_info() -> dict:
        t0 = time.monotonic()
        node = _node()
        result = {
            "chain_type": node.config.chain_type,
            "ethereum": {
                "rpc_url": node.config.ethereum.rpc_url,
                "chain_id": node.config.ethereum.chain_id,
            },
            "algorand": {
                "algod_url": node.config.algorand.algod_url,
                "network": node.config.algorand.network,
                "app_id": node.config.algorand.app_id,
            },
            "filecoin": {
                "rpc_url": node.config.filecoin.rpc_url,
                "chain_id": node.config.filecoin.chain_id,
                "network": node.config.filecoin.network,
                "contract_address": node.config.filecoin.payment_channel_address,
            },
            "storage": {
                "enabled": node.config.storage.enabled,
                "ipfs_api_url": node.config.storage.ipfs_api_url,
            },
        }
        _log_api("/chain", 200, (time.monotonic() - t0) * 1000)
        return result

    # ── IPFS Storage endpoints ────────────────────────────────

    @app.route("/storage/status")
    async def storage_status() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.ipfs_client:
            _log_api("/storage/status", 503, (time.monotonic() - t0) * 1000)
            return {"enabled": False, "error": "IPFS storage not configured"}, 503
        healthy = await node.ipfs_client.health()
        status = 200 if healthy else 503
        _log_api("/storage/status", status, (time.monotonic() - t0) * 1000)
        return {
            "enabled": True,
            "healthy": healthy,
            "api_url": node.config.storage.ipfs_api_url,
            "auto_pin_receipts": node.config.storage.auto_pin_receipts,
        }, status

    @app.route("/storage/pin", methods=["POST"])
    async def storage_pin() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.ipfs_client:
            return {"error": "IPFS storage not configured"}, 503
        data = await request.get_json()
        if not data or "data" not in data:
            return {"error": "JSON body with 'data' field required"}, 400
        content = data["data"].encode() if isinstance(data["data"], str) else data["data"]
        result = await node.ipfs_client.add(content, name=data.get("name", ""))
        ms = (time.monotonic() - t0) * 1000
        _log_api("/storage/pin", 201, ms, method="POST")
        return {"cid": result.cid, "size": result.size}, 201

    @app.route("/storage/get/<cid>")
    async def storage_get(cid: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.ipfs_client:
            return {"error": "IPFS storage not configured"}, 503
        try:
            content = await node.ipfs_client.cat_json(cid)
            _log_api(f"/storage/get/{cid[:8]}", 200, (time.monotonic() - t0) * 1000)
            return content, 200
        except Exception as e:
            _log_api(f"/storage/get/{cid[:8]}", 404, (time.monotonic() - t0) * 1000, error=str(e))
            return {"error": str(e)}, 404

    @app.route("/storage/receipts/<channel_id>/pin", methods=["POST"])
    async def storage_pin_receipts(channel_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if not node.ipfs_receipt_store:
            return {"error": "IPFS storage not configured"}, 503
        try:
            cid_bytes = bytes.fromhex(channel_id)
            cid = await node.ipfs_receipt_store.pin_chain(cid_bytes)
            ms = (time.monotonic() - t0) * 1000
            _log_api(f"/storage/receipts/{channel_id[:8]}/pin", 201, ms, method="POST")
            return {"cid": cid, "channel_id": channel_id}, 201
        except ValueError as e:
            return {"error": str(e)}, 404

    @app.route("/storage/pins")
    async def storage_pins() -> dict:
        t0 = time.monotonic()
        node = _node()
        if not node.ipfs_receipt_store:
            return {"enabled": False, "pins": []}
        pinned = node.ipfs_receipt_store.list_pinned()
        _log_api("/storage/pins", 200, (time.monotonic() - t0) * 1000)
        return pinned

    # ── Role-Based Coordination endpoints ──────────────────────

    @app.route("/role")
    async def get_role() -> dict:
        t0 = time.monotonic()
        node = _node()
        rm = node.role_manager
        result = {
            "role": rm.role.value if rm.role else None,
            "assignment": rm.assignment.to_dict() if rm.assignment else None,
        }
        _log_api("/role", 200, (time.monotonic() - t0) * 1000)
        return result

    @app.route("/role", methods=["PUT"])
    async def set_role() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        role_str = data.get("role")
        if not role_str:
            return {"error": "role is required"}, 400
        try:
            role = AgentRole(role_str)
        except ValueError:
            valid = [r.value for r in AgentRole]
            return {"error": f"Invalid role. Valid roles: {valid}"}, 400
        assignment = RoleAssignment(
            role=role,
            capabilities=data.get("capabilities", []),
            max_concurrent_tasks=data.get("max_concurrent_tasks", 10),
            metadata=data.get("metadata", {}),
        )
        node.role_manager.assign_role(assignment)
        ms = (time.monotonic() - t0) * 1000
        _log_api("/role", 200, ms, method="PUT", detail=role.value)
        return {"assignment": assignment.to_dict()}, 200

    @app.route("/role", methods=["DELETE"])
    async def clear_role() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        node.role_manager.clear_role()
        _log_api("/role", 200, (time.monotonic() - t0) * 1000, method="DELETE")
        return {"status": "role cleared"}, 200

    @app.route("/work-rounds")
    async def list_work_rounds() -> dict:
        t0 = time.monotonic()
        node = _node()
        rounds = [wr.to_dict() for wr in node.role_manager.list_work_rounds()]
        _log_api("/work-rounds", 200, (time.monotonic() - t0) * 1000)
        return {"work_rounds": rounds, "count": len(rounds)}

    @app.route("/work-rounds", methods=["POST"])
    async def create_work_round() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        data = await request.get_json()
        if not data:
            return {"error": "JSON body required"}, 400
        round_id = data.get("round_id")
        task_type = data.get("task_type")
        if not round_id or not task_type:
            return {"error": "round_id and task_type are required"}, 400
        try:
            wr = WorkRound(
                round_id=round_id,
                coordinator_peer_id=node.peer_id.to_base58() if node.peer_id else "",
                task_type=task_type,
                required_role=AgentRole(data.get("required_role", "worker")),
                max_workers=data.get("max_workers", 10),
                reward_per_worker=data.get("reward_per_worker", 0),
                metadata=data.get("metadata", {}),
            )
            node.role_manager.create_work_round(wr)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/work-rounds", 201, ms, method="POST", detail=round_id)
            return {"work_round": wr.to_dict()}, 201
        except ValueError as e:
            ms = (time.monotonic() - t0) * 1000
            _log_api("/work-rounds", 400, ms, method="POST", error=str(e))
            return {"error": str(e)}, 400

    # ── Agent Runtime Endpoints ──────────────────────────────────────────

    @app.route("/agent/status")
    async def agent_status() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if node.runtime is None:
            _log_api("/agent/status", 200, (time.monotonic() - t0) * 1000)
            return {"enabled": False, "running": False}, 200
        status = node.runtime.status()
        status["enabled"] = True
        _log_api("/agent/status", 200, (time.monotonic() - t0) * 1000)
        return status, 200

    @app.route("/agent/tasks")
    async def agent_list_tasks() -> dict | tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if node.runtime is None:
            _log_api("/agent/tasks", 200, (time.monotonic() - t0) * 1000)
            return {"tasks": [], "count": 0}
        status_filter = request.args.get("status")
        if status_filter:
            try:
                ts = TaskStatus(status_filter)
            except ValueError:
                return {"error": f"Invalid status: {status_filter}"}, 400
            tasks = node.runtime.task_store.by_status(ts)
        else:
            tasks = node.runtime.task_store.all_tasks()
        _log_api("/agent/tasks", 200, (time.monotonic() - t0) * 1000)
        return {"tasks": [t.to_dict() for t in tasks], "count": len(tasks)}

    @app.route("/agent/tasks", methods=["POST"])
    async def agent_create_task() -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if node.runtime is None:
            return {"error": "Agent runtime not enabled"}, 400
        data = await request.get_json()
        if not data or not data.get("description"):
            return {"error": "description is required"}, 400
        task = AgentTask(
            task_id=data.get("task_id", ""),
            description=data["description"],
            requester_peer_id=data.get("requester_peer_id", ""),
            amount=data.get("amount", 0),
        )
        task = node.runtime.task_store.add(task)
        ms = (time.monotonic() - t0) * 1000
        _log_api("/agent/tasks", 201, ms, method="POST", detail=task.task_id)
        return {"task": task.to_dict()}, 201

    @app.route("/agent/tasks/<task_id>")
    async def agent_get_task(task_id: str) -> tuple[dict, int]:
        t0 = time.monotonic()
        node = _node()
        if node.runtime is None:
            return {"error": "Agent runtime not enabled"}, 400
        task = node.runtime.task_store.get(task_id)
        if task is None:
            _log_api(f"/agent/tasks/{task_id}", 404, (time.monotonic() - t0) * 1000)
            return {"error": f"Task {task_id} not found"}, 404
        _log_api(f"/agent/tasks/{task_id}", 200, (time.monotonic() - t0) * 1000)
        return {"task": task.to_dict()}, 200

    @app.route("/agent/execute", methods=["POST"])
    async def agent_execute_task() -> tuple[dict, int]:
        """Manually trigger task execution (bypass tick loop)."""
        t0 = time.monotonic()
        node = _node()
        if node.runtime is None:
            return {"error": "Agent runtime not enabled"}, 400
        data = await request.get_json()
        if not data or not data.get("task_id"):
            return {"error": "task_id is required"}, 400
        task_id = data["task_id"]
        task = node.runtime.task_store.get(task_id)
        if task is None:
            return {"error": f"Task {task_id} not found"}, 404
        if task.status not in (TaskStatus.PENDING, TaskStatus.ASSIGNED):
            return {"error": f"Task is {task.status}, cannot execute"}, 400
        try:
            if task.status == TaskStatus.PENDING:
                node.runtime.task_store.update_status(task_id, TaskStatus.ASSIGNED)
            node.runtime.task_store.update_status(task_id, TaskStatus.EXECUTING)
            result = await node.runtime.executor.execute(task)
            task.result = result
            node.runtime.task_store.update_status(task_id, TaskStatus.COMPLETED)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/agent/execute", 200, ms, method="POST", detail=task_id)
            return {"task": task.to_dict()}, 200
        except Exception as exc:
            task.error = str(exc)
            if task.status == TaskStatus.EXECUTING:
                node.runtime.task_store.update_status(task_id, TaskStatus.FAILED)
            ms = (time.monotonic() - t0) * 1000
            _log_api("/agent/execute", 500, ms, method="POST", error=str(exc))
            return {"error": str(exc), "task": task.to_dict()}, 500
