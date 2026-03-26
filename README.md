<div align="center">

# AgentPay

**Decentralized micropayment channels for autonomous AI agents over libp2p**

[![CI](https://github.com/yashksaini-coder/AgentPay/actions/workflows/ci.yml/badge.svg)](https://github.com/yashksaini-coder/AgentPay/actions/workflows/ci.yml)
[![Security](https://github.com/yashksaini-coder/AgentPay/actions/workflows/security.yml/badge.svg)](https://github.com/yashksaini-coder/AgentPay/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-d7ff64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)

[Quick Start](#quick-start) · [Architecture](docs/ARCHITECTURE.md) · [CLI & API](docs/COMMANDS.md) · [Ecosystem Alignment](docs/ECOSYSTEM-ALIGNMENT.md) · [Contributing](CONTRIBUTING.md)

</div>

---

Agents discover each other via **mDNS**, negotiate service terms over **libp2p streams**, exchange **Filecoin-style signed payment vouchers** off-chain, and settle on **Ethereum**, **Algorand**, or **Filecoin FEVM**. Built for the [Filecoin Agents](https://filecoin.cloud/agents) ecosystem and the [ARIA Scaling Trust](https://www.aria.org.uk/programme/scaling-trust/) programme.

<div align="center">
  <img src="https://raw.githubusercontent.com/yashksaini-coder/AgentPay/master/images/system-architecture.png" alt="System Architecture" width="800" />
</div>

## Architecture

AgentPay is structured as a modular agent runtime with six layers:

- **Networking** — [py-libp2p](https://github.com/libp2p/py-libp2p) 0.6.0 with TCP/WebSocket transports, Noise encryption, Yamux multiplexing, mDNS discovery, and GossipSub pubsub
- **Wire Protocol** — 13 message types over length-prefixed msgpack streams (`/agentic-payments/1.0.0`), covering payments, HTLCs, negotiations, and announcements. TaskId correlation on vouchers for per-request settlement attestation
- **Payment Channels** — Filecoin-style cumulative vouchers with ECDSA signatures and task correlation, HTLC multi-hop routing via reputation-weighted BFS, one-shot x402 stateless payments, and a 6-state channel lifecycle
- **Settlement** — Tri-chain: **Ethereum** (Solidity `PaymentChannel.sol`), **Algorand** (ARC-4 + box storage), and **Filecoin FEVM** (same contract on FEVM with f4 address support) — selectable at startup
- **Identity** — [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) on-chain agent registration (ERC-721 identity token), EIP-191 PeerId-to-wallet cryptographic binding, reputation sync, and discovery fallback
- **Trust Layer** — Reputation scoring, GossipSub peer scoring (time-in-mesh, first-delivery, app-specific weights), SLA monitoring, dynamic pricing engine, dispute detection, wallet policies, standardized payment error codes, and hash-chained signed receipt audit trails
- **Storage** — IPFS content-addressed pinning for receipts and capabilities, with CID-based retrieval and GossipSub broadcast
- **Interfaces** — Quart-Trio REST API (~50 endpoints), Typer CLI (~50 commands), and a Next.js 15 real-time dashboard

<div align="center">
  <img src="https://raw.githubusercontent.com/yashksaini-coder/AgentPay/master/images/module-architecture.png" alt="Module Architecture" width="800" />
  <br />
  <em>Module dependency map — interface, core, network, business, trust, and settlement layers</em>
</div>

> See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design with 13 architecture diagrams.

## Quick Start

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 22+ (for the dashboard)
- Docker (optional — PostgreSQL + Anvil for on-chain settlement)

### Install & Run

```bash
# Install dependencies
uv sync --group dev

# Start agents + dashboard (recommended)
./scripts/dev.sh              # 2 agents + frontend at localhost:3000
./scripts/dev.sh --agents 3   # 3 agents

# Or start manually
uv run agentpay start --port 9000 --api-port 8080
```

### Verify

```bash
curl http://127.0.0.1:8080/health       # {"status":"ok","version":"0.1.0"}
curl http://127.0.0.1:8080/identity     # peer_id, eth_address, listen addrs
curl http://127.0.0.1:8080/peers        # discovered peers
```

### Open a Channel & Pay

```bash
# Open a payment channel (locks 1 ETH deposit)
curl -X POST http://127.0.0.1:8080/channels \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"12D3KooW...","receiver":"0xAbC...","deposit":1000000000000000000}'

# Send micropayments (off-chain, sub-millisecond)
curl -X POST http://127.0.0.1:8080/pay \
  -H "Content-Type: application/json" \
  -d '{"channel_id":"abcdef01...","amount":100000000000000}'
```

## Dashboard

The Next.js dashboard at `localhost:3000` provides a real-time multi-agent network view.

| | |
|---|---|
| **Network Graph** | Interactive force-directed graph — click nodes to open channels, click edges to send payments. Trust-colored nodes (green/amber/red). |
| **Trust Panels** | Discovery, negotiations, receipt chains, wallet policies — all in the left sidebar. |
| **Simulation** | Batch payment rounds, topology control (mesh/ring/star), success rate tracking. |
| **Actions** | Open channels, route multi-hop HTLC payments, propose service negotiations. |
| **Monitoring** | SLA violations, dispute scanning, dynamic pricing quotes, live event feed. |

<div align="center">
  <img src="https://raw.githubusercontent.com/yashksaini-coder/AgentPay/master/images/payment-channel-lifecycle.png" alt="Payment Channel Lifecycle" width="700" />
  <br />
  <em>Payment channel lifecycle — open, pay, close, settle</em>
</div>

## CLI

```bash
agentpay start [--port 9000] [--api-port 8080] [--eth-rpc URL]   # Start agent node
agentpay identity generate                                         # Create Ed25519 keypair
agentpay channel open --peer <id> --deposit <wei>                  # Open payment channel
agentpay pay --channel <id> --amount <wei>                         # Send micropayment
agentpay negotiate propose --peer <id> --service compute           # Negotiate terms
agentpay reputation list                                           # View trust scores
agentpay dispute scan                                              # Detect stale vouchers
agentpay pricing quote --service inference                         # Dynamic price quote
```

> Full CLI reference with all subcommands: **[COMMANDS.md](docs/COMMANDS.md)**

## REST API

~50 JSON endpoints across 10 groups. CORS enabled. Default: `http://127.0.0.1:8080`

| Group | Endpoints | Description |
|-------|-----------|-------------|
| **Core** | `/health` `/identity` `/peers` `/channels` `/pay` `/balance` `/graph` `/route-pay` `/connect` `/chain` | Node identity, peer discovery, channel management, payments, routing |
| **Discovery** | `/discovery/agents` `/discovery/resources` | Agent capability registry, Bazaar-compatible resource listing |
| **Negotiation** | `/negotiate` `/negotiations` `/negotiations/:id/*` | Propose/counter/accept/reject service terms with SLA |
| **Trust** | `/reputation` `/receipts` `/policies` | Per-peer trust scores, hash-chained receipts, wallet spend policies |
| **Pricing** | `/pricing/quote` `/pricing/config` | Dynamic price quotes with trust discounts and congestion premiums |
| **SLA** | `/sla/violations` `/sla/channels` | Per-channel latency/error-rate monitoring, violation detection |
| **Disputes** | `/disputes` `/disputes/scan` `/channels/:id/dispute` | Stale voucher detection, dispute filing and resolution |
| **Gateway** | `/gateway/resources` `/gateway/register` `/gateway/access` `/gateway/log` `/gateway/pay-oneshot` | x402 payment-gated resource access, one-shot stateless payments |
| **Roles** | `/role` | Agent role assignment (coordinator, worker, data_provider, validator, gateway) |
| **Work Rounds** | `/work-rounds` | Coordinator-managed task distribution and worker assignment |

## Development

```bash
make ci            # Run full CI pipeline locally (lint + format + typecheck + test + frontend + contracts)
make test          # 680 tests
make lint          # ruff check
make fmt           # ruff format (auto-fix)
make typecheck     # mypy
```

Tests cover the protocol codec, channel state machine, voucher cryptography, REST API, Algorand settlement, SLA monitoring, dynamic pricing, disputes, reputation, multi-hop routing, EIP-191 identity binding, payment error codes, role-based coordination, and full integration flows.

## Contributing

See **[CONTRIBUTING.md](./CONTRIBUTING.md)** for setup instructions, branch rules, and code quality requirements. All changes require a PR with passing CI and one approving review.

## Support

<div align="center">

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/yashksaini)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue?style=for-the-badge&logo=paypal)](https://paypal.me/yashksaini)
[![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-Support-pink?style=for-the-badge&logo=github)](https://github.com/sponsors/yashksaini-coder)

</div>

---

<div align="center">

[![Yash K. Saini](https://img.shields.io/badge/Portfolio-Visit-blue?style=flat&logo=google-chrome)](https://www.yashksaini.systems/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Follow-blue?style=flat&logo=linkedin)](https://www.linkedin.com/in/yashksaini/)
[![Twitter](https://img.shields.io/badge/Follow-blue?style=flat&logo=X)](https://x.com/0xCracked_dev)
[![GitHub](https://img.shields.io/badge/Follow-black?style=flat&logo=github)](https://github.com/yashksaini-coder)

</div>
