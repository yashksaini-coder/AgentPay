---
title: Home
layout: default
nav_order: 1
---

# AgentPay

**Decentralized micropayment channels for autonomous AI agents over libp2p**
{: .fs-6 .fw-300 }

[Get Started](#quick-start){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View on GitHub](https://github.com/yashksaini-coder/AgentPay){: .btn .fs-5 .mb-4 .mb-md-0 }

---

Agents discover each other via **mDNS**, negotiate service terms over **libp2p streams**, exchange **Filecoin-style signed payment vouchers** off-chain, and settle on **Ethereum**, **Algorand**, or **Filecoin FEVM**. Built for the [Filecoin Agents](https://filecoin.cloud/agents) ecosystem and the [ARIA Scaling Trust](https://www.aria.org.uk/programme/scaling-trust/) programme.

![System Architecture]({{ site.baseurl }}/assets/images/system-architecture.png)

## Architecture

AgentPay is structured as a modular agent runtime with six layers:

- **Networking** — [py-libp2p](https://github.com/libp2p/py-libp2p) 0.6.0 with TCP/WebSocket transports, Noise encryption, Yamux multiplexing, mDNS discovery, and GossipSub pubsub
- **Wire Protocol** — 13 message types over length-prefixed msgpack streams (`/agentic-payments/1.0.0`), covering payments, HTLCs, negotiations, and announcements
- **Payment Channels** — Filecoin-style cumulative vouchers with ECDSA signatures and task correlation, HTLC multi-hop routing, one-shot x402 stateless payments, and a 6-state channel lifecycle
- **Settlement** — Tri-chain: **Ethereum** (Solidity), **Algorand** (ARC-4 + box storage), and **Filecoin FEVM** — selectable at startup
- **Identity** — [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) on-chain agent registration, EIP-191 PeerId-to-wallet cryptographic binding
- **Trust Layer** — Reputation scoring, GossipSub peer scoring, SLA monitoring, dynamic pricing, dispute detection, wallet policies, and hash-chained signed receipt audit trails

![Module Architecture]({{ site.baseurl }}/assets/images/module-architecture.png)
*Module dependency map — interface, core, network, business, trust, and settlement layers*

> See [Architecture]({{ site.baseurl }}/architecture) for the full system design with 11 architecture diagrams.

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

| Feature | Description |
|---|---|
| **Network Graph** | Interactive force-directed graph — click nodes to open channels, click edges to send payments. Trust-colored nodes (green/amber/red). |
| **Trust Panels** | Discovery, negotiations, receipt chains, wallet policies — all in the left sidebar. |
| **Simulation** | Batch payment rounds, topology control (mesh/ring/star), success rate tracking. |
| **Actions** | Open channels, route multi-hop HTLC payments, propose service negotiations. |
| **Monitoring** | SLA violations, dispute scanning, dynamic pricing quotes, live event feed. |

![Payment Channel Lifecycle]({{ site.baseurl }}/assets/images/payment-channel-lifecycle.png)
*Payment channel lifecycle — open, pay, close, settle*

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

> Full CLI reference with all subcommands: **[CLI & API Reference]({{ site.baseurl }}/commands)**

## Development

```bash
make ci            # Run full CI pipeline locally
make test          # 680 tests
make lint          # ruff check
make fmt           # ruff format (auto-fix)
make typecheck     # mypy
```

## Contributing

See **[Contributing]({{ site.baseurl }}/contributing)** for setup instructions, branch rules, and code quality requirements.
