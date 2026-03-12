<div align="center">

# AgentPay

**Decentralized P2P micropayment channels for autonomous AI agents**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-120%20passing-brightgreen?style=flat-square&logo=pytest&logoColor=white)]()
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-d7ff64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![libp2p](https://img.shields.io/badge/libp2p-0.6.0-blue?style=flat-square&logo=libp2p&logoColor=white)](https://libp2p.io)
[![Solidity](https://img.shields.io/badge/solidity-%5E0.8-363636?style=flat-square&logo=solidity&logoColor=white)](https://soliditylang.org)
[![Next.js 15](https://img.shields.io/badge/next.js-15-000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![Ethereum](https://img.shields.io/badge/ethereum-settlement-3c3c3d?style=flat-square&logo=ethereum&logoColor=white)](https://ethereum.org)

Agents discover each other via **mDNS**, negotiate over **libp2p streams**, exchange **signed payment vouchers** off-chain, and settle on **Ethereum**.

Built on [py-libp2p](https://github.com/libp2p/py-libp2p) with Noise encryption, Yamux multiplexing, and GossipSub pubsub.

[Quick Start](#quick-start) | [CLI Commands](docs/COMMANDS.md) | [Architecture](docs/ARCHITECTURE.md) | [REST API](#rest-api) | [Dashboard](#frontend-dashboard)

</div>

---

## Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, [trio](https://trio.readthedocs.io/) structured concurrency |
| Networking | py-libp2p 0.6.0 — TCP/WS transports, Noise security, Yamux muxing, mDNS discovery, GossipSub pubsub |
| Payments | Filecoin-style cumulative vouchers, ECDSA signatures via eth-account, HTLC multi-hop routing |
| Settlement | Solidity unidirectional payment channel on Ethereum |
| Discovery | Capability registry with mDNS-based agent advertisement, Bazaar-compatible format |
| Negotiation | Propose/counter/accept/reject protocol with state machine |
| Trust | Reputation scoring (success rate, volume, response time), wallet policies, signed receipt chains |
| Gateway | x402-compatible resource gating for ecosystem interoperability |
| API | Quart-Trio REST (~25 endpoints) + Hypercorn ASGI server |
| Frontend | Next.js 15, React 19, Tailwind CSS 4 — network graph, trust panels, simulation |
| Persistence | PostgreSQL via asyncpg (optional) |
| Tooling | uv (package manager), hatchling (build), ruff (lint/format), Foundry (contracts) |

<div align="center">
  <img src="public/system-architecture.png" alt="System Architecture" width="800" />
</div>

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ (for frontend dashboard)
- Docker (optional — for PostgreSQL + Anvil on-chain settlement)

## Quick Start

### 1. Install backend dependencies

```bash
uv sync --group dev
```

### 2. Start agents + frontend (recommended)

```bash
./scripts/dev.sh              # 5 agents (default)
./scripts/dev.sh --agents 3   # 3 agents
./scripts/dev.sh --no-agents  # frontend only
```

This starts N agent nodes with auto-allocated ports (API=8080+i, P2P=9000+i*100, WS=9001+i*100) plus the Next.js dashboard at **http://localhost:3000**.

### 2b. Manual startup (alternative)

```bash
# Terminal 1 — Agent A
uv run agentpay start --port 9000 --api-port 8080

# Terminal 2 — Agent B
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key

# Terminal 3 — Frontend
cd frontend && npm install && npm run dev
```

Agents discover each other automatically via mDNS on the same local network.

### 3. Verify via curl

```bash
# Agent A
curl http://127.0.0.1:8080/health       # {"status":"ok","version":"0.1.0"}
curl http://127.0.0.1:8080/identity     # peer_id, eth_address, listen addrs
curl http://127.0.0.1:8080/peers        # discovered peers
curl http://127.0.0.1:8080/channels     # payment channels
curl http://127.0.0.1:8080/balance      # wallet balance summary

# Agent B
curl http://127.0.0.1:8081/health
curl http://127.0.0.1:8081/identity
```

### Infrastructure (optional)

PostgreSQL and Anvil are only needed for on-chain settlement features.

```bash
docker compose up -d   # postgres :5432, anvil :8545
```

## Frontend Dashboard

The dashboard at `http://localhost:3000` provides a multi-agent network view for testing P2P payments.

| Area | Description |
|------|-------------|
| Center | Interactive force-directed network graph — click nodes to open channels/send payments, trust-colored nodes (green/amber/red) |
| Left sidebar | Network stats, financial summary, trust scores, agent roster + Trust panel (Discovery, Negotiations, Receipts, Policies) |
| Right sidebar | Simulate tab (batch payments, topology control), Actions tab (open channel, route payment, negotiate), live event feed |

**Using the dashboard:**

1. Start agents (see Quick Start step 2) — nodes appear in the graph automatically
2. **Open a channel**: Click two agent nodes in the graph, enter deposit, click "Open Channel"
3. **Send a payment**: Click a channel link, enter amount, or use the route payment form for multi-hop HTLC
4. **Simulate**: Use the Simulate tab to run batch payment rounds across the network
5. **Negotiate**: Use the Actions tab to propose service terms between agents
6. Operations flash **green** on success, **yellow** on failure on the involved nodes

<div align="center">
  <img src="public/Payment-channel-lifecycle.png" alt="Payment Channel Lifecycle" width="700" />
  <br />
  <em>Payment channel lifecycle — open, pay, close, settle</em>
</div>

<div align="center">
  <img src="public/state-machine.png" alt="Channel State Machine" width="700" />
  <br />
  <em>Channel state machine — PROPOSED → ACTIVE → SETTLED</em>
</div>

## CLI

All commands use `uv run agentpay` (or just `agentpay` if installed).

```bash
# Start an agent node
agentpay start [--port 9000] [--ws-port 9001] [--api-port 8080] \
               [--eth-rpc http://localhost:8545] [--log-level INFO] \
               [--identity-path ~/.agentic-payments/identity.key]

# Identity management
agentpay identity generate [--path ~/.agentic-payments/identity.key]
agentpay identity show [--path ~/.agentic-payments/identity.key]

# Peer operations (requires running node)
agentpay peer list [--api-url http://127.0.0.1:8080]
agentpay peer connect <multiaddr> [--api-url http://127.0.0.1:8080]

# Payment channels (requires running node)
agentpay channel open --peer <peer_id> --deposit <wei> [--api-url http://127.0.0.1:8080]
agentpay channel close --channel <hex_id> [--api-url http://127.0.0.1:8080]

# Payments (requires running node)
agentpay pay --channel <hex_id> --amount <wei> [--api-url http://127.0.0.1:8080]
agentpay balance [--api-url http://127.0.0.1:8080]
```

## REST API

All endpoints return JSON. CORS enabled. Default base URL: `http://127.0.0.1:8080`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/identity` | Peer ID, ETH address, listen addresses |
| GET | `/peers` | Discovered peers with addresses |
| GET | `/channels` | All payment channels with state |
| GET | `/channels/:id` | Single channel by hex ID |
| POST | `/channels` | Open channel |
| POST | `/channels/:id/close` | Cooperative close |
| POST | `/pay` | Send micropayment voucher |
| POST | `/pay/route` | Multi-hop HTLC payment |
| GET | `/balance` | Aggregate balance across all channels |
| GET | `/discovery/agents` | Discovered agents with capabilities |
| POST | `/negotiate` | Propose negotiation |
| GET | `/negotiations` | List all negotiations |
| POST | `/negotiations/:id/accept` | Accept negotiation |
| POST | `/negotiations/:id/reject` | Reject negotiation |
| POST | `/negotiations/:id/counter` | Counter-propose price |
| GET | `/reputation` | All peer trust scores |
| GET | `/reputation/:peer_id` | Single peer reputation |
| GET | `/receipts` | All signed receipts |
| GET | `/receipts/:channel_id` | Receipt chain for a channel |
| GET | `/policies` | Current wallet policies |
| PUT | `/policies` | Update wallet policies |
| GET | `/gateway/resources` | x402-compatible resource listing |
| POST | `/gateway/register` | Register a gated resource |

### POST Examples

```bash
# Open a payment channel
curl -X POST http://127.0.0.1:8080/channels \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"12D3KooW...","receiver":"0xAbC...","deposit":1000000000000000000}'

# Send a micropayment
curl -X POST http://127.0.0.1:8080/pay \
  -H "Content-Type: application/json" \
  -d '{"channel_id":"abcdef01...","amount":100000000000000}'

# Close a channel cooperatively
curl -X POST http://127.0.0.1:8080/channels/abcdef01.../close
```

## Testing

```bash
uv run pytest                       # All ~120 tests
uv run pytest -v                    # Verbose output
uv run pytest tests/test_api.py     # Single test file
uv run ruff check src/ tests/       # Lint
uv run ruff format src/ tests/      # Format
```

| Test File | Count | Coverage |
|-----------|-------|---------|
| test_api.py | 24 | REST endpoints, CORS, error handling |
| test_channel.py | 12 | State machine, voucher application |
| test_protocol.py | 13 | Message codec, framing, wire validation |
| test_discovery.py | 10 | Capability registry, search, pruning |
| test_negotiation.py | 12 | Negotiation state machine, history |
| test_policies.py | 10 | Spend limits, rate limiting, whitelist/blacklist |
| test_reputation.py | 10 | Trust scoring, payment/HTLC tracking |
| test_receipts.py | 10 | Signed receipt chains, verification |
| test_gateway.py | 5 | x402 resource gating, Bazaar format |
| test_voucher.py | 4 | Signing, verification, serialization |
| test_node.py | 4 | Identity generation, persistence |
| test_pubsub.py | 3 | Topic definitions |
| test_integration.py | 3 | End-to-end channel lifecycle |

## Environment Variables

### Backend

```bash
ETH_RPC_URL=http://localhost:8545
ETH_CHAIN_ID=31337
NODE_PORT=9000
NODE_WS_PORT=9001
API_PORT=8080
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentic_payments
LOG_LEVEL=INFO
```

### Frontend

The dashboard auto-discovers agents via `GET /api/agents`. No port configuration needed when using `./scripts/dev.sh`.

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed system design.

## 💖 Support

If you find this project helpful, please consider:

<div align="center">

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/yashksaini)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?style=for-the-badge&logo=paypal)](https://paypal.me/yashksaini)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Support-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/yashksaini-coder)
    
**⭐ Star this repository** | **🐛 Report a bug** | **💡 Request a feature**

</div>

---

<div align="center">

[![Yash K. Saini](https://img.shields.io/badge/Portfolio-Visit-blue?style=flat&logo=google-chrome)](https://www.yashksaini.systems/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Follow-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/yashksaini/)
[![Twitter](https://img.shields.io/badge/Follow-blue?style=flat&logo=X)](https://x.com/0xCracked_dev)
[![GitHub](https://img.shields.io/badge/Follow-black?style=flat&logo=github)](https://github.com/yashksaini-coder)

</div>