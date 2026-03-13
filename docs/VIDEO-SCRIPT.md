# Video Demo Script

> Script for a 3–5 minute recorded demo. Works for YouTube, Loom, hackathon submissions, or conference talks.

---

## Pre-Recording Checklist

- [ ] Three terminal windows ready (Agent A, Agent B, curl commands)
- [ ] Browser open at `http://localhost:3000` (not yet loaded)
- [ ] Screen resolution: 1920x1080
- [ ] Font size: 16pt+ in terminals (readable on small screens)
- [ ] No sensitive data visible (wallet keys, API tokens)
- [ ] Docker running (if showing on-chain settlement)
- [ ] Clean terminal history (`clear` all terminals)

---

## Script

### [0:00–0:20] Hook

**Show**: README header on GitHub (or title slide)

**Say**:
> "What happens when AI agents need to pay each other? Not through Stripe, not through a bank — directly, peer-to-peer, with cryptographic guarantees.
>
> This is AgentPay — decentralized micropayment channels for autonomous AI agents, built on libp2p and Ethereum."

---

### [0:20–0:50] The Problem

**Show**: Simple slide or text overlay

**Say**:
> "AI agents are becoming autonomous. They need to transact — pay for compute, data, API calls. But current payment options don't work:
>
> On-chain transactions? Too slow and expensive for micropayments.
> Centralized APIs? Single point of failure, requires trust.
>
> Payment channels solve this. Lock funds once, exchange signed vouchers thousands of times off-chain, settle once. Two on-chain transactions total."

---

### [0:50–1:30] Start the Agents

**Show**: Two terminal windows side by side

**Do**:
```bash
# Terminal 1
uv run agentpay start --port 9000 --api-port 8080

# Terminal 2
uv run agentpay start --port 9100 --ws-port 9101 --api-port 8081 \
  --identity-path ~/.agentic-payments/identity2.key
```

**Say**:
> "I'm starting two agent nodes. Each has its own Ed25519 identity for P2P networking and an Ethereum wallet for payments.
>
> Notice the log — Agent B just discovered Agent A automatically via mDNS. No configuration, no central registry. They found each other on the local network."

---

### [1:30–2:00] Show the Dashboard

**Show**: Browser at `http://localhost:3000`

**Say**:
> "Here's the dashboard. Agent A on the left, Agent B on the right. Both online, both showing their Peer IDs and Ethereum addresses.
>
> The green indicators confirm they're connected. The peer lists show they've discovered each other."

---

### [2:00–3:00] Open Channel + Send Payments

**Show**: Dashboard center panel

**Do**:
1. Click "Open Channel" tab
2. Select A → B, enter `1000000000000000000` (1 ETH)
3. Click **Open Channel**
4. Switch to "Send Payment" tab
5. Select the channel, enter `100000000000000` (0.0001 ETH)
6. Click **Send Payment** 3–4 times

**Say**:
> "I'm opening a payment channel from Agent A to Agent B with a 1 ETH deposit. This is the one on-chain transaction in production.
>
> Now I'm sending micropayments. Each click sends a signed voucher — ECDSA signature, cumulative amount, strictly increasing nonce. All off-chain. Sub-millisecond.
>
> Watch the balances update. Agent A's remaining balance decreases, Agent B's received amount increases. These are real cryptographic vouchers that could be settled on Ethereum."

---

### [3:00–3:30] Show the API

**Show**: Terminal with curl commands

**Do**:
```bash
curl -s http://127.0.0.1:8080/channels | python3 -m json.tool
curl -s http://127.0.0.1:8080/balance | python3 -m json.tool
```

**Say**:
> "Everything is accessible via REST API. Here's the channel state — active, nonce at 4, total paid amount matches our payments. The balance endpoint shows the aggregate view.
>
> Any agent framework can integrate with these endpoints. No SDK required — just HTTP and JSON."

---

### [3:30–4:00] Architecture Highlight

**Show**: System architecture diagram (`public/system-architecture.png`)

**Say**:
> "Under the hood: libp2p handles networking — Noise encryption, Yamux multiplexing, GossipSub for pub-sub coordination. The payment protocol runs as a custom stream handler.
>
> Vouchers use the same signature scheme as Ethereum transactions, so they can be verified on-chain without any conversion. The smart contract handles disputes with a challenge period."

---

### [4:00–4:30] Tests + Close

**Show**: Terminal running tests

**Do**:
```bash
uv run pytest -v --tb=no -q
```

**Say**:
> "63 tests covering the protocol codec, channel state machine, voucher cryptography, REST API, and end-to-end integration. All passing.
>
> AgentPay is open source, MIT licensed. Check the repo for the full architecture docs, CLI reference, and example scripts. Thanks for watching."

**Show**: GitHub repo URL + social links

---

## Post-Production Notes

- **Thumbnail**: Use the system architecture diagram with "AgentPay" text overlay
- **Description**: Link to repo, architecture doc, and demo walkthrough
- **Tags**: `ai-agents`, `payment-channels`, `libp2p`, `ethereum`, `micropayments`, `p2p`, `python`
- **Music**: Optional — low background ambient, no vocals
- **Captions**: Auto-generate, then review technical terms (libp2p, msgpack, ECDSA, etc.)
