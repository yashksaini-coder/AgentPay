<div align="center">

# AgentPay

**Decentralized P2P micropayment channels for autonomous AI agents**

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-63%20passing-brightgreen?style=flat-square&logo=pytest&logoColor=white)]()
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
| Payments | Filecoin-style cumulative vouchers, ECDSA signatures via eth-account |
| Settlement | Solidity unidirectional payment channel on Ethereum |
| API | Quart-Trio REST + Hypercorn ASGI server |
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
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

### 2. Start Agent A (Terminal 1)

```bash
uv run agentpay start --port 9000 --api-port 8080
```

This starts an agent node listening on:
- **TCP :9000** — libp2p peer-to-peer transport
- **WS :9001** — WebSocket transport
- **HTTP :8080** — REST API for the frontend and CLI

On first run, an Ed25519 identity is auto-generated at `~/.agentic-payments/identity.key`.

### 3. Start Agent B (Terminal 2)

```bash
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key
```

Agent B runs on separate ports to avoid conflicts. Both agents discover each other automatically via mDNS on the same local network.

### 4. Start the frontend dashboard (Terminal 3)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** in your browser.

The dashboard shows both agents side by side:
- **Agent A** (left) — connected to `http://127.0.0.1:8080`
- **Agent B** (right) — connected to `http://127.0.0.1:8081`
- **Center panel** — open channels and send payments between them

To use custom API ports, set environment variables before starting the frontend:

```bash
NEXT_PUBLIC_AGENT_A_PORT=8080 NEXT_PUBLIC_AGENT_B_PORT=8081 npm run dev
```

### 5. Verify via curl

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

The dashboard at `http://localhost:3000` provides a dual-agent view for testing P2P payments.

**What you see in the browser:**

| Section | Description |
|---------|-------------|
| Agent A card (left) | Peer ID, ETH address, balance, channels, discovered peers |
| Agent B card (right) | Same as Agent A, independent node on a different port |
| Action panel (center) | Tabbed UI — "Open Channel" and "Send Payment" |

**Using the dashboard:**

1. Start both agents (see Quick Start steps 2-3)
2. Open `http://localhost:3000` — both cards should show "Online" with green indicators
3. **Open a channel**: Select direction (A→B or B→A), enter deposit in wei, click "Open Channel"
4. **Send a payment**: Switch to "Send Payment" tab, select the active channel from the dropdown, enter amount, click "Send Payment"
5. Channels and balances update automatically every 4 seconds

**Ports summary:**

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | Next.js dashboard |
| Agent A API | http://127.0.0.1:8080 | REST API for Agent A |
| Agent B API | http://127.0.0.1:8081 | REST API for Agent B |
| Agent A P2P | TCP :9000, WS :9001 | libp2p transport |
| Agent B P2P | TCP :9100, WS :9101 | libp2p transport |

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
| GET | `/health` | Health check (`{"status":"ok","version":"0.1.0"}`) |
| GET | `/identity` | Peer ID, ETH address, listen addresses, connected peer count |
| GET | `/peers` | Discovered peers with addresses and connection count |
| GET | `/channels` | All payment channels with state |
| GET | `/channels/:id` | Single channel by hex ID |
| POST | `/channels` | Open channel |
| POST | `/channels/:id/close` | Cooperative close |
| POST | `/pay` | Send micropayment voucher |
| GET | `/balance` | Aggregate balance across all channels |

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

## Project Structure

```
src/agentic_payments/
├── cli.py              # Typer CLI entrypoint
├── config.py           # Pydantic settings (node, ethereum, db, api)
├── node/
│   ├── agent_node.py   # AgentNode orchestrator (host, pubsub, discovery, API)
│   ├── identity.py     # Ed25519 key generation, PeerID derivation
│   └── discovery.py    # mDNS peer discovery via host peerstore
├── protocol/
│   ├── messages.py     # Wire message types (Open, Update, Close, Ack)
│   ├── codec.py        # Length-prefix framing + msgpack serialization
│   └── handler.py      # Stream handler for /agentic-payments/1.0.0
├── payments/
│   ├── channel.py      # Payment channel state machine
│   ├── voucher.py      # Signed cumulative vouchers (ECDSA)
│   ├── manager.py      # In-memory channel registry
│   └── store.py        # PostgreSQL persistence (optional)
├── chain/
│   ├── wallet.py       # Ethereum wallet (eth-account)
│   ├── contracts.py    # Solidity ABI bindings (web3.py)
│   └── settlement.py   # On-chain open/close/dispute
├── pubsub/
│   ├── topics.py       # GossipSub topic definitions
│   └── broadcaster.py  # Pubsub publish/subscribe wrapper
└── api/
    ├── server.py       # Quart-Trio + Hypercorn server
    └── routes.py       # REST endpoint handlers

frontend/
├── src/app/
│   ├── layout.tsx      # Root layout with dark theme
│   ├── page.tsx        # Dual-agent dashboard page
│   └── globals.css     # Tailwind + custom theme tokens
├── src/components/
│   ├── AgentCard.tsx   # Agent identity, balance, channels, peers
│   ├── ActionPanel.tsx # Tabbed open-channel + send-payment forms
│   └── StatusBadge.tsx # Channel state badge (ACTIVE, CLOSING, etc.)
├── src/lib/
│   ├── api.ts          # API client factory (per-agent port)
│   └── useAgent.ts     # React hook for agent state polling
└── package.json

contracts/src/PaymentChannel.sol   # Unidirectional payment channel (Foundry)
examples/                          # Demo scripts
tests/                             # 63 tests (pytest-trio)
```

## Testing

```bash
uv run pytest                       # All 63 tests
uv run pytest -v                    # Verbose output
uv run pytest tests/test_api.py     # Single test file
uv run ruff check src/ tests/       # Lint
uv run ruff format src/ tests/      # Format
uv run ruff format --check src/ tests/  # Format check (CI)
```

| Test File | Count | Coverage |
|-----------|-------|---------|
| test_api.py | 24 | REST endpoints, CORS, error handling |
| test_channel.py | 12 | State machine, voucher application |
| test_protocol.py | 13 | Message codec, framing, wire validation |
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

```bash
NEXT_PUBLIC_AGENT_A_PORT=8080    # Agent A REST API port (default: 8080)
NEXT_PUBLIC_AGENT_B_PORT=8081    # Agent B REST API port (default: 8081)
NEXT_PUBLIC_API_URL=http://127.0.0.1:8080  # Legacy single-agent mode
```

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