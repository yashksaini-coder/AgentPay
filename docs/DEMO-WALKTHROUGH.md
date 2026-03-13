# Demo Walkthrough

> Step-by-step live demo of AgentPay — from zero to micropayments in 5 minutes.

## Prerequisites

Make sure you have installed:

```bash
# Backend
uv sync --group dev

# Frontend
cd frontend && npm install && cd ..
```

---

## Demo 1: Two-Agent Local Payment (Terminal Only)

**Audience**: Developers, protocol reviewers, hackathon judges
**Duration**: ~3 minutes
**What it shows**: P2P discovery, channel lifecycle, signed voucher exchange

### Step 1 — Start Agent A

```bash
uv run agentpay start --port 9000 --api-port 8080
```

Wait for the log line:
```
INFO  agent_node: Node started  peer_id=12D3KooW...  eth_address=0x...
```

### Step 2 — Start Agent B (new terminal)

```bash
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key
```

Wait for:
```
INFO  discovery: New peer discovered  peer_id=12D3KooW...
```

> **Talking point**: "Both agents discovered each other automatically via mDNS — no central registry, no config files."

### Step 3 — Verify discovery

```bash
# Agent A sees Agent B
curl -s http://127.0.0.1:8080/peers | python3 -m json.tool

# Agent B sees Agent A
curl -s http://127.0.0.1:8081/peers | python3 -m json.tool
```

### Step 4 — Get Agent B's identity

```bash
PEER_B=$(curl -s http://127.0.0.1:8081/identity | python3 -c "import sys,json; print(json.load(sys.stdin)['peer_id'])")
ETH_B=$(curl -s http://127.0.0.1:8081/identity | python3 -c "import sys,json; print(json.load(sys.stdin)['eth_address'])")
echo "Agent B: $PEER_B ($ETH_B)"
```

### Step 5 — Open a payment channel (A → B)

```bash
curl -s -X POST http://127.0.0.1:8080/channels \
  -H "Content-Type: application/json" \
  -d "{\"peer_id\":\"$PEER_B\",\"receiver\":\"$ETH_B\",\"deposit\":1000000000000000000}" \
  | python3 -m json.tool
```

> **Talking point**: "Agent A just locked 1 ETH into a payment channel with Agent B. This would be an on-chain deposit in production. Now all payments happen off-chain."

### Step 6 — Send micropayments

```bash
# Get the channel ID
CHANNEL=$(curl -s http://127.0.0.1:8080/channels | python3 -c "import sys,json; print(json.load(sys.stdin)['channels'][0]['channel_id'])")

# Send 3 micropayments
for i in 1 2 3; do
  echo "--- Payment $i ---"
  curl -s -X POST http://127.0.0.1:8080/pay \
    -H "Content-Type: application/json" \
    -d "{\"channel_id\":\"$CHANNEL\",\"amount\":100000000000000}" \
    | python3 -m json.tool
  sleep 0.5
done
```

> **Talking point**: "Each payment is a signed voucher with a cumulative amount. No on-chain transaction needed — just a signature. Sub-second latency."

### Step 7 — Check balances

```bash
echo "=== Agent A (sender) ==="
curl -s http://127.0.0.1:8080/balance | python3 -m json.tool

echo "=== Agent B (receiver) ==="
curl -s http://127.0.0.1:8081/balance | python3 -m json.tool
```

### Step 8 — Close the channel

```bash
curl -s -X POST "http://127.0.0.1:8080/channels/$CHANNEL/close" | python3 -m json.tool
```

> **Talking point**: "Channel closed cooperatively. In production, the final voucher would be submitted on-chain and both parties settle."

---

## Demo 2: Automated API Demo (Screen Recording)

**Audience**: Anyone — run the script while screen-recording the terminal and dashboard
**Duration**: ~3 minutes
**What it shows**: Full lifecycle driven by the automated `scripts/demo.sh`

### Setup

```bash
# Terminal 1 — Start agents + dashboard
./scripts/dev.sh --agents 3

# Wait ~10 seconds for all agents to boot

# Terminal 2 — Run the automated demo
./scripts/demo.sh
```

### What the script does

The demo runs through 9 phases automatically with color-coded output:

1. **Discovery** — Shows each agent's PeerID and ETH address, verifies mDNS peer discovery
2. **Open Channels** — Opens A→B, B→C, and A→C payment channels with deposits
3. **Micropayments** — Sends a burst of 3 payments per channel (10K, 25K, 50K wei) with nonce/cumulative tracking
4. **Balances & Receipts** — Checks deposited/paid/remaining on all agents, shows receipt chain validity
5. **Negotiation** — Agent A proposes compute service to B, B counters, A accepts
6. **Trust Scores** — Displays reputation bars with trust percentages for each peer
7. **Dynamic Pricing** — Gets a price quote showing trust discounts and congestion premiums
8. **Dispute Detection** — Scans channels for stale vouchers
9. **Channel Close** — Cooperatively closes all channels

### Options

```bash
./scripts/demo.sh --speed slow      # Longer pauses (for narrated recordings)
./scripts/demo.sh --agents 5        # Use 5 agents instead of 3
./scripts/demo.sh --skip-cleanup    # Leave channels open at the end
```

### Recording tips

- Tile Terminal 1 (dev.sh) and Terminal 2 (demo.sh) side by side
- Have the dashboard (localhost:3000) visible in a browser behind or alongside
- The dashboard updates in real-time as the API script runs
- Use OBS Studio or your OS screen recorder at 1920x1080

---

## Demo 3: Dashboard UI (Click-by-Click Video Guide)

**Audience**: Non-technical stakeholders, product demos, conference talks
**Duration**: ~5 minutes
**What it shows**: Every panel and interaction in the Next.js dashboard

### Setup

```bash
./scripts/dev.sh --agents 3     # Start 3 agents + frontend
```

Open **http://localhost:3000** in your browser. Wait for nodes to appear in the graph.

### Scene 1 — Overview (~30s)

1. **Header bar** — Point out: `3/3 nodes` online (green dot), `0 ch`, `0 paid`
2. **Center graph** — 3 nodes (Agent A, B, C) displayed as circles. Hover to see PeerID tooltips
3. **Left sidebar** — Network stats (nodes, peers, channels), Financial summary (all zeroes), Trust & Discovery counts
4. **Right sidebar** — Event log showing "Network monitor started"
5. **Bottom hint** — "Click two nodes to connect or pay"

### Scene 2 — Open a Payment Channel (~45s)

1. **Click Agent A node** in the graph, then **click Agent B node**
2. A popup appears: **"Open Channel — Agent A → Agent B"**
3. The deposit field shows `1000000` — leave it or change it
4. Click **"Open Channel"**
5. Watch: Both nodes flash **blue** (executing), then **green** (success)
6. A **line** appears between A and B in the graph
7. Left sidebar updates: `1 active / 1` channels, deposited amount
8. Event log: "Opened channel to Agent B — Deposit: 1,000,000 wei"
9. Repeat: Click A → C and B → C to create a mesh

### Scene 3 — Send Direct Payments (~45s)

1. **Click the line** between Agent A and Agent B
2. Popup: **"Send Payment — Agent A → Agent B"** with amount field
3. Enter `50000`, click **"Send Payment"**
4. Nodes flash blue → green, line animates
5. Event log: "Sent 50,000 wei — Nonce: 1"
6. Left sidebar: "Paid" counter increases
7. Send 2-3 more payments — watch the nonce increment and cumulative amount grow
8. **Payment Flow chart** in the left sidebar starts plotting amounts over time

### Scene 4 — Multi-Hop Route Payment (~30s)

1. Close channels between A and C (if any) so only A→B and B→C exist
2. **Click Agent A** then **click Agent C** — popup shows **"Route Payment"** mode
3. Enter amount `25000`, click **"Route Payment"**
4. Watch: The animation traces A → B → C (multi-hop HTLC)
5. All 3 nodes flash green on success
6. Event log: "Routed 25,000 wei to Agent C (2 hops)"

### Scene 5 — Trust Panels (~60s)

Click through the **left sidebar tabs** below the stats:

1. **Discovery tab** — Shows discovered agents with capabilities and Bazaar-compatible format
2. **Negotiations tab** — Start a negotiation:
   - Right sidebar → **Actions tab** → Negotiate section
   - Select Agent A as proposer, Agent B as counterparty
   - Service: `compute`, Price: `5000`, Deposit: `100000`
   - Click **"Propose"**
   - The negotiation appears in the timeline with status badges
3. **Receipts tab** — Shows receipt chains per channel with validity checkmarks
4. **Policies tab** — Shows wallet spend limits, rate limiting rules

### Scene 6 — Right Sidebar Deep Dive (~45s)

1. **Simulate tab** — Select topology (mesh/ring/star), set payment rounds and amounts
   - Click **"Run Simulation"** — watch payments animate across the graph in batch
   - Stats update in real-time: channels opened, payments sent, success rate
2. **Actions tab** — Manual controls for:
   - Open Channel (select sender/receiver/deposit)
   - Route Payment (select source/destination/amount)
   - Negotiate (propose/counter/accept between agents)
3. **SLA Panel** — Shows SLA violations, latency thresholds
4. **Disputes Panel** — Scan for stale vouchers, view dispute status
5. **Pricing Panel** — Dynamic pricing config, trust discounts, congestion premiums

### Scene 7 — Agent Management (~30s)

1. **Right sidebar top** — "Agent Processes" section
2. Click **"Add Node"** — a new Agent D appears in the graph
3. It auto-discovers existing peers via mDNS
4. Open channels to it, send payments — full participation
5. Click the **stop button** on Agent D — node disappears, channels show as stale

### Screen Recording Tips

- **Resolution**: 1920x1080 or 2560x1440 (dashboard is responsive)
- **Theme**: Dark theme is default — looks great on recordings
- **Browser**: Maximized, inspector closed, no bookmarks bar
- **Mouse**: Move slowly and deliberately so viewers can follow
- **Pauses**: Hover on elements for 2-3 seconds before clicking
- **Narration**: Use talking points from each scene description

---

## Demo 4: Full Stack with On-Chain Settlement

**Audience**: Blockchain engineers, security reviewers
**Duration**: ~5 minutes
**What it shows**: End-to-end with Ethereum settlement on local Anvil

### Setup

```bash
# Start infrastructure
docker compose up -d   # Postgres + Anvil

# Verify Anvil is running
curl -s http://localhost:8545 -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'

# Start agents with ETH RPC
uv run agentpay start --port 9000 --api-port 8080 --eth-rpc http://localhost:8545
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --eth-rpc http://localhost:8545 \
  --identity-path ~/.agentic-payments/identity2.key
```

### Walkthrough

1. Open channel with deposit (locks ETH on Anvil)
2. Send multiple micropayments (all off-chain)
3. Close channel (submits final voucher on-chain)
4. Show Anvil logs for the on-chain transactions
5. Verify fund distribution: receiver got paid, sender got refund

---

## Demo 5: Run the Test Suite

**Audience**: Code reviewers, open source contributors
**Duration**: ~1 minute

```bash
# All 541 tests
make test

# Full CI pipeline (lint + format + typecheck + tests + frontend + contracts)
make ci
```

> **Talking point**: "541 tests covering the protocol codec, channel state machine, voucher cryptography, REST API, Algorand settlement, SLA monitoring, pricing, disputes, reputation, and full integration flows. All passing, lint clean."

---

## Common Questions During Demo

| Question | Answer |
|----------|--------|
| "Is this real ETH?" | No — development uses in-memory channels. On-chain mode uses Anvil (local testnet). |
| "How fast are payments?" | Sub-millisecond for voucher signing. Network RTT depends on transport (TCP/WS). |
| "What prevents double-spending?" | Strictly increasing nonces + cumulative amounts. On-chain challenge period for disputes. |
| "Can this work across the internet?" | Yes — replace mDNS with direct multiaddr connections or DHT discovery. mDNS is for LAN demos. |
| "What about key management?" | Ed25519 identity is persisted. ETH wallet is ephemeral per session (configurable). |
| "How does it compare to Lightning?" | Similar concept (payment channels), but agent-native: libp2p transport, no routing, direct peer channels. |
