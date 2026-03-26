---
title: CLI & API Reference
layout: default
nav_order: 3
---

# CLI & API Reference

All commands are run with `uv run agentpay` (or `agentpay` if installed globally).

## Command Overview

| Command | Description |
|---------|-------------|
| `agentpay start` | Start an agent node (libp2p + REST API) |
| `agentpay identity generate` | Generate a new Ed25519 node identity |
| `agentpay identity show` | Display the node's Peer ID and key path |
| `agentpay peer list` | List all discovered peers |
| `agentpay peer connect` | Connect to a peer by multiaddr |
| `agentpay channel open` | Open a payment channel with a peer |
| `agentpay channel close` | Close a payment channel |
| `agentpay pay` | Send a micropayment on a channel |
| `agentpay balance` | Show aggregated balance across all channels |
| `agentpay discovery list` | List discovered agents with capabilities |
| `agentpay negotiate propose` | Propose a negotiation with a peer |
| `agentpay negotiate counter` | Counter-propose a negotiation price |
| `agentpay negotiate accept` | Accept a negotiation |
| `agentpay negotiate reject` | Reject a negotiation |
| `agentpay reputation list` | List all peer trust scores |
| `agentpay pricing quote` | Get a dynamic price quote |
| `agentpay dispute scan` | Scan for stale voucher disputes |
| `agentpay gateway resources` | List x402 gated resources |
| `agentpay sla` | Show SLA violations summary |
| `agentpay chain` | Show chain type and settlement info |

---

## `agentpay start`

Start an agent node with libp2p host, GossipSub pubsub, mDNS discovery, and REST API.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port` | INTEGER | `9000` | TCP listen port for libp2p |
| `--ws-port` | INTEGER | `9001` | WebSocket listen port |
| `--api-port` | INTEGER | `8080` | REST API port |
| `--eth-rpc` | TEXT | `http://localhost:8545` | Ethereum JSON-RPC endpoint |
| `--chain` | TEXT | `ethereum` | Settlement chain: `ethereum`, `algorand`, or `filecoin` |
| `--agent-enabled` | BOOL | `false` | Enable autonomous agent runtime |
| `--agent-tick` | FLOAT | `5.0` | Agent runtime tick interval (seconds) |
| `--log-level` | TEXT | `INFO` | Log level |

```bash
# Start with defaults
uv run agentpay start

# Start with agent runtime
uv run agentpay start --agent-enabled --agent-tick 2

# Connect to remote Ethereum RPC
uv run agentpay start --eth-rpc https://mainnet.infura.io/v3/YOUR_KEY
```

---

## REST API Endpoints

The REST API starts on `--api-port`. All endpoints return JSON. CORS enabled.

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/identity` | Peer ID, ETH address, listen addresses |
| GET | `/peers` | Discovered peers with addresses |
| GET | `/channels` | All payment channels with state |
| GET | `/channels/:id` | Single channel by hex ID |
| POST | `/channels` | Open a payment channel |
| POST | `/channels/:id/close` | Close a channel cooperatively |
| POST | `/pay` | Send a micropayment voucher |
| GET | `/balance` | Aggregated balance |
| GET | `/graph` | Network topology graph |
| POST | `/route` | Compute a multi-hop route |
| POST | `/route-pay` | Send a routed multi-hop payment |
| POST | `/connect` | Connect to peer by multiaddr |
| GET | `/chain` | Chain type and settlement info |

### Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/discovery/agents` | List discovered agents with capabilities |
| GET | `/discovery/resources` | Bazaar-compatible resource listing |

### Negotiation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/negotiate` | Propose a new negotiation |
| GET | `/negotiations` | List all negotiations |
| GET | `/negotiations/:id` | Get negotiation details |
| POST | `/negotiations/:id/counter` | Counter-propose |
| POST | `/negotiations/:id/accept` | Accept |
| POST | `/negotiations/:id/reject` | Reject |

### Trust

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reputation` | List all peer trust scores |
| GET | `/reputation/:peer_id` | Specific peer's reputation |
| GET | `/receipts` | List all receipt chains |
| GET | `/receipts/:channel_id` | Channel receipts |
| GET | `/policies` | Wallet policies |
| PUT | `/policies` | Update wallet policies |

### Pricing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pricing/quote` | Dynamic price quote |
| GET | `/pricing/config` | Pricing engine config |
| PUT | `/pricing/config` | Update pricing config |

### SLA

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sla/violations` | List SLA violations |
| GET | `/sla/channels` | Channels with SLA tracking |
| GET | `/sla/channels/:id` | SLA details for a channel |

### Disputes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/disputes` | List all disputes |
| GET | `/disputes/:id` | Dispute details |
| POST | `/disputes/scan` | Scan for stale voucher disputes |
| POST | `/channels/:id/dispute` | File a dispute |

### Gateway

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/gateway/resources` | List x402 gated resources |
| POST | `/gateway/register` | Register a gated resource |
| POST | `/gateway/access` | Verify payment and grant access |
| GET | `/gateway/log` | Access audit log |
| POST | `/gateway/pay-oneshot` | One-shot x402 stateless payment |

### Roles & Work Rounds

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/role` | Current agent role |
| PUT | `/role` | Assign role |
| DELETE | `/role` | Clear role |
| GET | `/work-rounds` | List work rounds |
| POST | `/work-rounds` | Create work round |

### ERC-8004 Identity

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/identity/erc8004` | Registration status |
| POST | `/identity/erc8004/register` | Register agent on-chain |
| GET | `/identity/erc8004/lookup/:id` | Look up agent by token ID |
| POST | `/reputation/sync-onchain` | Push trust score on-chain |

### Agent Runtime

Requires `--agent-enabled` on `agentpay start`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/agent/status` | Agent runtime status |
| GET | `/agent/tasks` | List all tasks |
| POST | `/agent/tasks` | Submit a new task |
| GET | `/agent/tasks/:task_id` | Task details |
| POST | `/agent/execute` | Execute a task |

---

## curl Examples

```bash
# Health check
curl http://127.0.0.1:8080/health

# Open a channel
curl -X POST http://127.0.0.1:8080/channels \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"12D3KooW...","receiver":"0xAbC...","deposit":1000000000000000000}'

# Send a payment with task correlation
curl -X POST http://127.0.0.1:8080/pay \
  -H "Content-Type: application/json" \
  -d '{"channel_id":"a1b2c3d4...","amount":100000000000000,"task_id":"task-inference-001"}'

# One-shot x402 payment
curl -X POST http://127.0.0.1:8080/gateway/pay-oneshot \
  -H "Content-Type: application/json" \
  -d '{"path":"/api/v1/inference","amount":1000,"sender":"0xAbC..."}'

# Assign agent role
curl -X PUT http://127.0.0.1:8080/role \
  -H "Content-Type: application/json" \
  -d '{"role":"coordinator","capabilities":["llm-inference"]}'
```

## Frontend Dashboard

The Next.js dashboard at `localhost:3000` provides a real-time multi-agent network view. See [Home]({{ site.baseurl }}/) for dashboard details.
