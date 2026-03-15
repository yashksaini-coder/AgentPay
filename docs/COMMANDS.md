# CLI Commands Reference

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
| `agentpay discovery resources` | List resources in Bazaar-compatible format |
| `agentpay negotiate propose` | Propose a negotiation with a peer |
| `agentpay negotiate counter` | Counter-propose a negotiation price |
| `agentpay negotiate accept` | Accept a negotiation |
| `agentpay negotiate reject` | Reject a negotiation |
| `agentpay negotiate list` | List all negotiations |
| `agentpay negotiate show` | Show negotiation details |
| `agentpay reputation list` | List all peer trust scores |
| `agentpay reputation show` | Show a specific peer's reputation |
| `agentpay receipts list` | List all receipt chains |
| `agentpay receipts show` | Show receipts for a specific channel |
| `agentpay policy show` | Show current wallet policies |
| `agentpay policy set` | Update wallet policies |
| `agentpay pricing quote` | Get a dynamic price quote |
| `agentpay pricing config` | View pricing engine config |
| `agentpay dispute list` | List all disputes |
| `agentpay dispute show` | Show dispute details |
| `agentpay dispute scan` | Scan for stale voucher disputes |
| `agentpay dispute file` | File a manual dispute |
| `agentpay gateway resources` | List x402 gated resources |
| `agentpay gateway register` | Register a gated resource |
| `agentpay identity register-onchain` | Register agent on-chain via ERC-8004 |
| `agentpay identity lookup` | Look up agent by ERC-8004 token ID |
| `agentpay identity erc8004-status` | Show ERC-8004 registration status |
| `agentpay reputation sync-onchain` | Push trust score to on-chain registry |
| `agentpay storage status` | Check IPFS daemon connectivity |
| `agentpay storage pin` | Pin data or receipt chain to IPFS |
| `agentpay storage get` | Retrieve content from IPFS by CID |
| `agentpay storage list` | List pinned IPFS objects |
| `agentpay sla` | Show SLA violations summary |
| `agentpay chain` | Show chain type and settlement info |

---

## `agentpay start`

Start an agent node. This launches the libp2p host (TCP + WebSocket transports), GossipSub pubsub, mDNS peer discovery, and the REST API server.

```
Usage: agentpay start [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--port` | INTEGER | `9000` | TCP listen port for libp2p peer connections |
| `--ws-port` | INTEGER | `9001` | WebSocket listen port for browser/WS clients |
| `--api-port` | INTEGER | `8080` | REST API port (frontend connects here) |
| `--eth-rpc` | TEXT | `http://localhost:8545` | Ethereum JSON-RPC endpoint URL |
| `--chain` | TEXT | `ethereum` | Settlement chain: `ethereum`, `algorand`, or `filecoin` |
| `--algo-url` | TEXT | `http://localhost:4001` | Algorand node URL |
| `--algo-token` | TEXT | | Algorand API token |
| `--algo-app-id` | INTEGER | `0` | Algorand payment channel app ID |
| `--fil-rpc` | TEXT | | Filecoin FEVM RPC URL |
| `--fil-contract` | TEXT | | PaymentChannel contract address on FEVM |
| `--ipfs-url` | TEXT | | IPFS HTTP API URL (enables storage) |
| `--erc8004-identity` | TEXT | | ERC-8004 Identity Registry contract address |
| `--erc8004-reputation` | TEXT | | ERC-8004 Reputation Registry contract address |
| `--log-level` | TEXT | `INFO` | Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `--identity-path` | PATH | `~/.agentic-payments/identity.key` | Path to Ed25519 identity key file |

### Examples

```bash
# Start with defaults (TCP :9000, WS :9001, API :8080)
uv run agentpay start

# Start Agent A on custom ports
uv run agentpay start --port 9000 --api-port 8080

# Start Agent B on different ports (avoids conflicts with Agent A)
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key

# Start with debug logging
uv run agentpay start --log-level DEBUG

# Connect to a remote Ethereum RPC
uv run agentpay start --eth-rpc https://mainnet.infura.io/v3/YOUR_KEY
```

### What happens on start

1. Loads or generates an Ed25519 identity at `--identity-path`
2. Generates an in-memory Ethereum wallet (ECDSA)
3. Starts the libp2p host on `--port` (TCP) and `--ws-port` (WebSocket)
4. Registers the `/agentic-payments/1.0.0` stream protocol handler
5. Starts GossipSub pubsub and subscribes to discovery/capabilities/receipts topics
6. Starts mDNS peer discovery (peers on the same LAN are found automatically)
7. Starts the REST API server on `--api-port`

---

## `agentpay identity generate`

Generate a new Ed25519 keypair and save it to disk. This is the node's cryptographic identity used for libp2p peer authentication (Noise protocol).

```
Usage: agentpay identity generate [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--path` | PATH | `~/.agentic-payments/identity.key` | Output path for the key file |

### Examples

```bash
# Generate default identity
uv run agentpay identity generate

# Generate a second identity for a second node
uv run agentpay identity generate --path ~/.agentic-payments/identity2.key
```

### Output

```
PeerID: 12D3KooWQ1og24JN7vgK2SD57wM4XkrRWEk1QgwPxbtdCbt9cKDR
Saved to: /home/user/.agentic-payments/identity.key
```

> Note: If no identity exists when running `agentpay start`, one is auto-generated.

---

## `agentpay identity show`

Display the Peer ID derived from an existing identity key file.

```
Usage: agentpay identity show [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--path` | PATH | `~/.agentic-payments/identity.key` | Path to the identity key file |

### Examples

```bash
# Show default identity
uv run agentpay identity show

# Show a specific identity
uv run agentpay identity show --path ~/.agentic-payments/identity2.key
```

### Output

```
PeerID: 12D3KooWQ1og24JN7vgK2SD57wM4XkrRWEk1QgwPxbtdCbt9cKDR
Key file: /home/user/.agentic-payments/identity.key
```

---

## `agentpay peer list`

List all discovered peers. Queries the running node's REST API.

```
Usage: agentpay peer list [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# List peers from default node
uv run agentpay peer list

# List peers from Agent B
uv run agentpay peer list --api-url http://127.0.0.1:8081
```

### Output

```
  12D3KooWNCDbp5VnAgKM7CCi5srDFdaBzU7iUqKkm2nZyQLc4D7E  ['/ip4/192.168.1.8/tcp/9000']
```

If no peers are found:

```
No peers discovered.
```

---

## `agentpay peer connect`

Connect to a peer by its multiaddr. Requires a running node.

```
Usage: agentpay peer connect [OPTIONS] MULTIADDR
```

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `MULTIADDR` | TEXT | Yes | Peer multiaddr (e.g., `/ip4/192.168.1.5/tcp/9000/p2p/12D3KooW...`) |

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# Connect to a peer on the local network
uv run agentpay peer connect /ip4/192.168.1.5/tcp/9000/p2p/12D3KooWNCDbp5VnAgKM7CCi5srDFdaBzU7iUqKkm2nZyQLc4D7E
```

---

## `agentpay channel open`

Open a payment channel with a connected peer. Sends a `PaymentOpen` message over libp2p and waits for the peer's acknowledgement.

```
Usage: agentpay channel open [OPTIONS]
```

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--peer` | TEXT | Yes | — | Peer ID of the receiver (base58 encoded) |
| `--deposit` | INTEGER | Yes | — | Deposit amount in wei |
| `--api-url` | TEXT | No | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# Open a channel with 1 ETH deposit
uv run agentpay channel open \
  --peer 12D3KooWNCDbp5VnAgKM7CCi5srDFdaBzU7iUqKkm2nZyQLc4D7E \
  --deposit 1000000000000000000

# Open a channel via Agent B's API
uv run agentpay channel open \
  --peer 12D3KooWQ1og24JN7vgK2SD57wM4XkrRWEk1QgwPxbtdCbt9cKDR \
  --deposit 500000000000000000 \
  --api-url http://127.0.0.1:8081
```

### Output

```
Channel opened: a1b2c3d4e5f60000...
```

---

## `agentpay channel close`

Close a payment channel cooperatively. Sends a `PaymentClose` to the peer and transitions the channel to SETTLED on acceptance.

```
Usage: agentpay channel close [OPTIONS]
```

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--channel` | TEXT | Yes | — | Channel ID in hex |
| `--api-url` | TEXT | No | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# Close a channel
uv run agentpay channel close --channel a1b2c3d4e5f6000000000000000000000000000000000000000000000000000000

# Close via Agent B
uv run agentpay channel close \
  --channel a1b2c3d4e5f6000000000000000000000000000000000000000000000000000000 \
  --api-url http://127.0.0.1:8081
```

---

## `agentpay pay`

Send a micropayment on an existing active channel. Creates a signed cumulative voucher and sends it to the peer.

```
Usage: agentpay pay [OPTIONS]
```

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--channel` | TEXT | Yes | — | Channel ID in hex |
| `--amount` | INTEGER | Yes | — | Payment amount in wei (incremental, added to cumulative total) |
| `--api-url` | TEXT | No | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# Send 0.001 ETH
uv run agentpay pay \
  --channel a1b2c3d4e5f6000000000000000000000000000000000000000000000000000000 \
  --amount 1000000000000000

# Send multiple small payments
uv run agentpay pay --channel a1b2c3... --amount 100000000000000
uv run agentpay pay --channel a1b2c3... --amount 100000000000000
uv run agentpay pay --channel a1b2c3... --amount 100000000000000
```

### Output

```
Payment sent. Nonce: 1
```

> Vouchers are cumulative: each payment adds `--amount` to the running total. Only the latest voucher is needed for on-chain settlement.

---

## `agentpay balance`

Display the aggregated balance across all payment channels on the node.

```
Usage: agentpay balance [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL of the running node |

### Examples

```bash
# Check balance on default node
uv run agentpay balance

# Check Agent B's balance
uv run agentpay balance --api-url http://127.0.0.1:8081
```

### Output

```
Address:    0x9daE199C4D8e6CCEC8e6070ad75055Eb90d89112
Deposited:  1000000000000000000 wei
Paid:       300000000000000000 wei
Remaining:  700000000000000000 wei
Channels:   2
```

---

## `agentpay discovery list`

List all discovered agents with their capabilities and pricing.

```
Usage: agentpay discovery list [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL |

### Examples

```bash
uv run agentpay discovery list
```

### Output

```
  12D3KooWNCDb...  compute ($500/call)  inference ($1000/call)
  12D3KooWQ1og...  storage ($200/call)
```

---

## `agentpay negotiate propose`

Propose a service negotiation with a peer, including optional SLA terms.

```
Usage: agentpay negotiate propose [OPTIONS]
```

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--peer` | TEXT | Yes | — | Peer ID to negotiate with |
| `--service` | TEXT | Yes | — | Service type (compute, storage, inference, etc.) |
| `--price` | INTEGER | Yes | — | Proposed price in wei |
| `--deposit` | INTEGER | Yes | — | Channel deposit in wei |
| `--api-url` | TEXT | No | `http://127.0.0.1:8080` | REST API URL |

### Examples

```bash
uv run agentpay negotiate propose \
  --peer 12D3KooWNCDb... \
  --service compute \
  --price 5000 \
  --deposit 100000
```

---

## `agentpay reputation list`

List trust scores for all known peers.

```
Usage: agentpay reputation list [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL |

---

## `agentpay pricing quote`

Get a dynamic price quote for a service, factoring in trust and congestion.

```
Usage: agentpay pricing quote [OPTIONS]
```

| Flag | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `--service` | TEXT | Yes | — | Service type |
| `--api-url` | TEXT | No | `http://127.0.0.1:8080` | REST API URL |

---

## `agentpay dispute scan`

Scan all channels for stale voucher attacks and auto-file disputes.

```
Usage: agentpay dispute scan [OPTIONS]
```

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api-url` | TEXT | `http://127.0.0.1:8080` | REST API URL |

---

## REST API Endpoints

The REST API is started alongside the node on `--api-port`. All endpoints return JSON.

### Core

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/identity` | Peer ID, ETH address, listen addresses, connected peer count |
| GET | `/peers` | Discovered peers with addresses |
| GET | `/channels` | All payment channels with state |
| GET | `/channels/:id` | Single channel by hex ID |
| POST | `/channels` | Open a payment channel |
| POST | `/channels/:id/close` | Close a channel cooperatively |
| POST | `/pay` | Send a micropayment voucher |
| GET | `/balance` | Aggregated balance |
| GET | `/graph` | Network topology graph |
| POST | `/route` | Compute a multi-hop route to a peer |
| POST | `/route-pay` | Send a routed multi-hop payment |
| POST | `/connect` | Connect to a peer by multiaddr |
| GET | `/chain` | Chain type and settlement info |

### Discovery

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/discovery/agents` | List discovered agents with capabilities and pricing |
| GET | `/discovery/resources` | List resources in Bazaar-compatible format |

### Negotiation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/negotiate` | Propose a new negotiation |
| GET | `/negotiations` | List all negotiations |
| GET | `/negotiations/:id` | Get negotiation details |
| POST | `/negotiations/:id/counter` | Counter-propose a negotiation price |
| POST | `/negotiations/:id/accept` | Accept a negotiation |
| POST | `/negotiations/:id/reject` | Reject a negotiation |

### Trust

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/reputation` | List all peer trust scores |
| GET | `/reputation/:peer_id` | Get a specific peer's reputation |
| GET | `/receipts` | List all receipt chains |
| GET | `/receipts/:channel_id` | Get receipts for a specific channel |
| GET | `/policies` | Show current wallet policies |
| PUT | `/policies` | Update wallet policies |

### Pricing

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/pricing/quote` | Get a dynamic price quote |
| GET | `/pricing/config` | View pricing engine configuration |
| PUT | `/pricing/config` | Update pricing engine configuration |

### SLA

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sla/violations` | List SLA violations summary |
| GET | `/sla/channels` | List channels with SLA tracking |
| GET | `/sla/channels/:id` | Get SLA details for a specific channel |

### Disputes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/disputes` | List all disputes |
| GET | `/disputes/:id` | Get dispute details |
| POST | `/disputes/scan` | Scan for stale voucher disputes |
| POST | `/channels/:id/dispute` | File a dispute on a channel |
| POST | `/disputes/:id/resolve` | Resolve a dispute |

### Gateway

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/gateway/resources` | List x402 gated resources |
| POST | `/gateway/register` | Register a gated resource |
| POST | `/gateway/access` | Verify payment and grant access (x402 flow) |
| GET | `/gateway/log` | Access audit log |

### ERC-8004 Identity

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/identity/erc8004` | ERC-8004 registration status |
| POST | `/identity/erc8004/register` | Register agent on-chain |
| GET | `/identity/erc8004/lookup/:id` | Look up agent by token ID |
| POST | `/reputation/sync-onchain` | Push trust score to on-chain registry |

### Storage (IPFS)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/storage/status` | IPFS daemon connectivity |
| POST | `/storage/pin` | Pin data to IPFS |
| GET | `/storage/get/:cid` | Retrieve content by CID |
| POST | `/storage/receipts/:channel_id/pin` | Pin receipt chain to IPFS |
| GET | `/storage/pins` | List pinned objects |

### curl Examples

```bash
# Health check
curl http://127.0.0.1:8080/health

# Get node identity
curl http://127.0.0.1:8080/identity

# List peers
curl http://127.0.0.1:8080/peers

# List channels
curl http://127.0.0.1:8080/channels

# Get a specific channel
curl http://127.0.0.1:8080/channels/a1b2c3d4e5f6...

# Open a channel
curl -X POST http://127.0.0.1:8080/channels \
  -H "Content-Type: application/json" \
  -d '{"peer_id":"12D3KooW...","receiver":"0xAbC...","deposit":1000000000000000000}'

# Send a payment
curl -X POST http://127.0.0.1:8080/pay \
  -H "Content-Type: application/json" \
  -d '{"channel_id":"a1b2c3d4...","amount":100000000000000}'

# Close a channel
curl -X POST http://127.0.0.1:8080/channels/a1b2c3d4.../close

# Check balance
curl http://127.0.0.1:8080/balance
```

---

## Frontend Dashboard

The Next.js dashboard at `localhost:3000` provides a real-time multi-agent network view with interactive force-directed graph, trust panels, simulation controls, and monitoring.

### Setup

```bash
# 1. Install frontend dependencies (one time)
cd frontend && npm install

# 2. Start the dev server
npm run dev
```

Open **http://localhost:3000** in your browser.

### What you see

The dashboard has three areas:
| Area | Description |
|------|-------------|
| **Center** | Interactive force-directed network graph. Click nodes to open channels, click edges to send payments. Trust-colored nodes (green/amber/red). |
| **Left Sidebar** | Network stats, financial summary, trust scores, agent roster. Tabs: Identity, Discovery, Negotiations, SLA, Disputes, Pricing, Receipts, Policies. |
| **Right Sidebar** | Simulate tab (batch payments, topology), Actions tab (open channel, route payment, negotiate), live event feed. |

### How to use the dashboard

1. Start agents with `./scripts/dev.sh` — nodes appear in the graph automatically
2. **Open a channel**: Click two nodes in the graph, enter deposit, click "Open Channel"
3. **Send a payment**: Click a channel edge, enter amount, or use the route payment form for multi-hop HTLC
4. **Simulate**: Use the Simulate tab to run batch payment rounds across the network
5. **Negotiate**: Use the Actions tab to propose service terms between agents
6. **Identity**: Check the Identity tab to view ERC-8004 registration status

---

## Quick Start

```bash
# Start multi-agent network + dashboard
./scripts/dev.sh --agents 3

# Or start manually
uv run agentpay start --port 9000 --api-port 8080
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key

# Dashboard
cd frontend && npm install && npm run dev
# → http://localhost:3000
```

## Live End-to-End Testing

```bash
# Deploy contracts to local Anvil + test all features
./scripts/deploy_local.sh
source .env.local
./scripts/live_test.sh
```
   - **"Agent A -> Agent B"** means Agent A is the sender (payer)
   - **"Agent B -> Agent A"** means Agent B is the sender
3. Enter the deposit amount in wei (e.g., `1000000000000000000` for 1 ETH)
4. Click **"Open Channel"**
5. On success, a green confirmation message appears with the channel ID
6. The channel appears in the sender's card under "Channels" with an **ACTIVE** badge

#### Step 3: Send payments

1. Click the **"Send Payment"** tab in the center panel
2. Select **"Agent A"** or **"Agent B"** as the sender
3. Select the active channel from the dropdown (shows channel ID + remaining balance)
4. Enter the payment amount in wei (e.g., `100000000000000` for 0.0001 ETH)
5. Click **"Send Payment"**
6. On success, a green message shows the voucher nonce and cumulative amount
7. The channel balance updates automatically in the agent card

#### Step 4: Monitor state

- All data refreshes automatically every **4 seconds**
- Channel state badges update in real time: PROPOSED, OPEN, **ACTIVE**, CLOSING, SETTLED
- Balance stats (deposited / paid / remaining) update after each payment
- New peers appear in the "Discovered Peers" section when found via mDNS

### Port configuration

By default the dashboard connects to:

| Agent | API URL |
|-------|---------|
| Agent A | `http://127.0.0.1:8080` |
| Agent B | `http://127.0.0.1:8081` |

To use custom ports, set environment variables before starting the frontend:

```bash
NEXT_PUBLIC_AGENT_A_PORT=8080 NEXT_PUBLIC_AGENT_B_PORT=8081 npm run dev
```

Or for non-standard setups:

```bash
NEXT_PUBLIC_AGENT_A_PORT=9080 NEXT_PUBLIC_AGENT_B_PORT=9081 npm run dev
```

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Both cards show "Offline" | Agents not running | Start both agents in separate terminals |
| One card shows "Offline" | Wrong port or agent crashed | Check the agent's terminal for errors |
| "Node unreachable" error | API port mismatch | Verify `--api-port` matches dashboard config |
| "API error: ..." | Node is running but returned an error | Check the agent's terminal logs |
| Channel open fails | Agents haven't discovered each other | Wait ~10 seconds for mDNS, or both agents must be on the same LAN |
| CORS error in browser console | Frontend origin not in allowlist | Frontend must run on `localhost:3000` or `127.0.0.1:3000` |
| Port 3000 already in use | Another dev server running | Kill it: `lsof -i :3000` then `kill <PID>`, or use `npx kill-port 3000` |

---

## Common Workflows

### Two-agent local test

```bash
# Terminal 1: Start Agent A
uv run agentpay start --port 9000 --api-port 8080

# Terminal 2: Start Agent B
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key

# Terminal 3: Open channel from A to B
uv run agentpay channel open \
  --peer $(curl -s http://127.0.0.1:8081/identity | python3 -c "import sys,json; print(json.load(sys.stdin)['peer_id'])") \
  --deposit 1000000000000000000

# Send payments
uv run agentpay pay --channel <CHANNEL_ID> --amount 100000000000000
uv run agentpay pay --channel <CHANNEL_ID> --amount 100000000000000

# Check balances
uv run agentpay balance
uv run agentpay balance --api-url http://127.0.0.1:8081

# Close the channel
uv run agentpay channel close --channel <CHANNEL_ID>
```

### Frontend dashboard

```bash
# Start both agents (see above), then:
cd frontend && npm install && npm run dev

# Open http://localhost:3000 in your browser
# Agent A (left) connects to :8080, Agent B (right) connects to :8081
```

See [Frontend Dashboard (Browser)](#frontend-dashboard-browser) above for full step-by-step usage.

### Custom ports via environment variables

```bash
# Override defaults via env vars instead of flags
NODE_PORT=9200 NODE_WS_PORT=9201 API_PORT=8090 uv run agentpay start
```

### Show identity without starting the node

```bash
uv run agentpay identity show
# PeerID: 12D3KooWQ1og24JN7vgK2SD57wM4XkrRWEk1QgwPxbtdCbt9cKDR
# Key file: /home/user/.agentic-payments/identity.key
```
