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

## Demo 2: Dashboard UI (Visual)

**Audience**: Non-technical stakeholders, product demos, conference talks
**Duration**: ~3 minutes
**What it shows**: Full visual workflow with real-time updates

### Setup

```bash
# Terminal 1 — Agent A
uv run agentpay start --port 9000 --api-port 8080

# Terminal 2 — Agent B
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key

# Terminal 3 — Frontend
cd frontend && npm run dev
```

### Walkthrough

1. Open **http://localhost:3000**
2. Both agent cards should show **Online** (green indicator)
3. Point out: Peer IDs, ETH addresses, discovered peers
4. **Open Channel** tab → Select "A → B", deposit `1000000000000000000` (1 ETH), click **Open Channel**
5. Watch the channel appear in both agent cards
6. **Send Payment** tab → Select the channel, amount `100000000000000` (0.0001 ETH), click **Send Payment**
7. Send 3-5 payments, watch balances update in real time (4s polling)
8. Show the channel state transition in the status badges

### Screen Recording Tips

- Use a 1920x1080 window, dark theme is already default
- Keep the browser inspector closed
- Resize terminals to show only the key log lines
- Record with OBS or native screen recorder

---

## Demo 3: Full Stack with On-Chain Settlement

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

## Demo 4: Run the Test Suite

**Audience**: Code reviewers, open source contributors
**Duration**: ~1 minute

```bash
# All 541 tests
uv run pytest -v

# Just the integration tests (end-to-end channel lifecycle)
uv run pytest tests/test_integration.py -v

# Lint + format check
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
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
