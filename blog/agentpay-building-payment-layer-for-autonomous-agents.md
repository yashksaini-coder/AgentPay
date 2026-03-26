# Building the Payment Layer for Autonomous AI Agents

*How we built AgentPay — a decentralized micropayment protocol that lets AI agents discover, negotiate, pay, and settle with each other, peer-to-peer, with no middleman.*

---

## The Agent Economy Is Here. The Payment Layer Isn't.

Something fundamental is shifting in how software works. AI agents are no longer just answering questions in a chat window — they're browsing the web, writing code, managing infrastructure, analyzing data, and making decisions autonomously. Projects like [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT), [CrewAI](https://www.crewai.com/), and [LangGraph](https://www.langchain.com/langgraph) have shown that multi-agent systems can tackle problems that no single model can solve alone.

But here's the problem nobody talks about enough: **how do these agents pay each other?**

![AI agents forming an interconnected network](https://images.unsplash.com/photo-1639322537228-f710d846310a?w=800&q=80)

When Agent A needs Agent B to summarize 10,000 documents, or when a coordinator agent wants to distribute inference tasks across a network of GPU providers, someone needs to get paid. Today, the options are bleak:

- **On-chain per transaction**: $0.50–$50 per tx, 15-second confirmation times. If your agents are making 1,000 requests per minute, this doesn't scale.
- **Centralized payment APIs (Stripe, PayPal)**: Require KYC, human approval, API keys, rate limits. Autonomous agents can't fill out forms.
- **Credit/subscription models**: Require pre-existing trust relationships. But agents are ephemeral — they spin up, do work, and disappear.

We built **AgentPay** to solve this. It's a full economic stack for autonomous agents: discover peers, negotiate terms, lock funds once on-chain, exchange thousands of off-chain micropayments, monitor service quality, resolve disputes, and settle — all peer-to-peer over [libp2p](https://libp2p.io/).

---

## What We Built (And Why It's Different)

AgentPay isn't just a payment channel. It's the full lifecycle of what agents need to transact economically with each other.

![AgentPay system architecture](images/system-architecture.png)
*AgentPay system architecture — networking, protocol, payments, settlement, identity, and trust layers*

### The Seven-Step Agent Payment Lifecycle

Here's how two agents go from strangers to trading partners:

**1. Discovery** — Agents find each other via mDNS on a local network or GossipSub pubsub across the internet. Each agent advertises its capabilities (compute, inference, storage, data) in a format compatible with the [Bazaar protocol](https://github.com/basketprotocol/bazaar).

**2. Negotiation** — Before any money changes hands, agents agree on terms. Our 4-message negotiation protocol handles: proposed price, SLA requirements (max latency, max error rate), deposit amount, and service type. One agent proposes, the other can accept, reject, or counter-offer.

**3. Channel Open** — The sender locks funds into a payment channel with a single on-chain transaction. This is the *only* gas-intensive operation. For Ethereum, this deploys to our `PaymentChannel.sol` contract. For Algorand, an ARC-4 application call with box storage. For Filecoin, the same Solidity contract deployed on FEVM.

**4. Micropayments** — Now the magic happens. The sender signs cumulative vouchers — just like Filecoin's payment channels — and sends them directly to the receiver over a libp2p stream. No gas. No confirmation wait. Sub-millisecond. Each voucher supersedes the previous one, so only the latest matters for settlement.

**5. Trust Building** — Every successful payment updates the receiver's trust score for the sender, factoring in success rate, payment volume, response latency, and relationship longevity. Dynamic pricing adapts — trusted peers get discounts, untrusted peers pay premiums.

**6. SLA Monitoring** — The channel continuously tracks whether the service provider meets their promised SLA. Latency violations, error rate spikes — everything is measured. Violations can trigger automatic dispute detection.

**7. Settlement** — When the channel closes (cooperatively or via challenge period), only the final voucher is submitted on-chain. One transaction settles thousands of payments. If there's a dispute, the challenge period lets either party submit evidence of a higher-nonce voucher.

```
Agent A                          Agent B
   │                                │
   │  1. Discover via mDNS/GossipSub│
   │◄──────────────────────────────►│
   │                                │
   │  2. Negotiate terms + SLA      │
   │◄──────────────────────────────►│
   │                                │
   │  3. Open channel (lock 1 ETH)  │ ← single on-chain tx
   │───────────────────────────────►│
   │                                │
   │  4. Pay 0.001 ETH (voucher #1) │
   │───────────────────────────────►│ ← off-chain, instant
   │  5. Pay 0.002 ETH (voucher #2) │
   │───────────────────────────────►│ ← cumulative, replaces #1
   │  ... ×1000 more vouchers ...   │
   │                                │
   │  6. Close + settle on-chain    │ ← single on-chain tx
   │───────────────────────────────►│
```

The result: **thousands of micropayments** with only **2 on-chain transactions** total.

---

## The Technical Architecture

AgentPay is structured as six layers, each independently testable and replaceable:

![Module architecture diagram](images/module-architecture.png)
*Module dependency map — interface, core, network, business, trust, and settlement layers*

### Networking: libp2p All The Way Down

We chose [py-libp2p](https://github.com/libp2p/py-libp2p) over HTTP for a simple reason: **agents shouldn't need servers**. With libp2p, every agent is both a client and a server. They find each other via mDNS on a LAN or through bootstrap peers across the internet. Connections use Noise encryption and Yamux multiplexing — multiple concurrent payment streams over a single TCP connection.

Our custom stream protocol (`/agentic-payments/1.0.0`) uses msgpack with 4-byte length-prefix framing. 13 message types cover the full payment lifecycle: channel open/ack, payment updates, HTLC propose/fulfill/cancel, negotiation messages, and error codes.

![Wire protocol diagram](images/wire-protocol.png)
*All 13 message types with fields and framing format*

### Payment Channels: Filecoin's Model, Adapted for Agents

Our payment channels use the same cumulative voucher pattern that powers Filecoin's storage market:

```python
@dataclass(frozen=True)
class SignedVoucher:
    channel_id: bytes     # 32-byte channel identifier
    nonce: int            # Monotonically increasing
    amount: int           # Cumulative wei (not incremental!)
    timestamp: int        # Unix timestamp
    signature: bytes      # ECDSA over keccak256(abi.encodePacked(...))
    task_id: str = ""     # Correlate payment to specific work request
```

Each voucher replaces the previous one. If Agent A sends voucher #1 for 0.001 ETH, then voucher #2 for 0.003 ETH, only voucher #2 matters. The receiver can submit it on-chain to claim 0.003 ETH. This means:

- **No double-spending risk** — nonces are monotonically increasing
- **Minimal on-chain data** — only the latest voucher is ever submitted
- **Signature verification** — `ecrecover` on-chain confirms the sender
- **Task correlation** — the `task_id` field ties payments to specific work requests, enabling per-request settlement attestation

The channel state machine has 6 states with a challenge period for dispute resolution:

![Channel state machine](images/state-machine.png)
*6-state lifecycle: PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED, with DISPUTED branch*

### Multi-Hop Routing: HTLC Like Lightning

What if Agent A wants to pay Agent C, but they don't have a direct channel? AgentPay supports Hash Time-Locked Contract (HTLC) multi-hop routing — the same primitive that powers Bitcoin's Lightning Network.

![HTLC routing diagram](images/htlc-routing.png)
*Multi-hop payment via intermediaries with reputation-weighted BFS pathfinding*

The pathfinder uses reputation-weighted BFS (Dijkstra with trust scores as edge costs) to find the best route through the network graph. Each hop decrements the HTLC timeout so the sender's lock expires last — ensuring atomic settlement even across untrusted intermediaries.

### Tri-Chain Settlement

AgentPay settles on three chains, selectable at startup:

| Chain | Contract | Address Format | Use Case |
|-------|----------|---------------|----------|
| **Ethereum** | Solidity `PaymentChannel.sol` | 0x... | EVM ecosystem, DeFi composability |
| **Algorand** | ARC-4 + box storage | ALGO... | Bazaar/x402 ecosystem interop |
| **Filecoin FEVM** | Same Solidity contract | f4... | Storage market alignment |

The settlement layer is behind a `SettlementProtocol` interface — adding a new chain requires implementing four methods: `open_channel_onchain`, `close_channel_onchain`, `challenge_close_onchain`, and `withdraw_onchain`.

### Identity: ERC-8004 + EIP-191

Every agent has two key pairs: **Ed25519** for libp2p peer identity (Noise encryption, stream authentication) and **secp256k1** for Ethereum payments (ECDSA voucher signatures, on-chain settlement).

We bridge these with [EIP-191](https://eips.ethereum.org/EIPS/eip-191) — the Ethereum wallet signs the libp2p PeerID, creating a cryptographic binding between the two identities. This proof is verifiable by any peer without on-chain lookups.

For on-chain identity, we implement [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) ("Trustless Agents") — an ERC-721 token that maps an agent's PeerID and wallet to an on-chain identity token. This enables cross-chain identity portability and on-chain reputation tracking.

![ERC-8004 identity flow](images/erc8004-identity-flow.png)
*Agent registration, identity bridge, reputation sync*

---

## The Trust Layer: Why Payments Alone Aren't Enough

Here's something most payment channel projects miss: **payments without trust infrastructure are useless for autonomous agents**.

If Agent B provides inference services, Agent A needs to know:
- Is Agent B reliable? (Do they fulfill requests?)
- Is Agent B fast? (Do they meet latency SLAs?)
- Is Agent B honest? (Do they try to submit stale vouchers?)

AgentPay's trust layer answers all three:

![Trust architecture](images/trust-architecture.png)
*Reputation, SLA monitoring, disputes, policies, and pricing interactions*

### Reputation Scoring

Every peer has a trust score computed from four factors:

```
trust_score = w1 * success_rate      # Completed payments / total attempts
            + w2 * volume_score      # Payment volume (log-scaled)
            + w3 * latency_score     # Response time consistency
            + w4 * longevity_score   # Relationship duration
```

Trust scores feed into GossipSub peer scoring — unreliable peers get deprioritized for message relay, naturally degrading their network position.

### Dynamic Pricing

The pricing engine adjusts quotes based on trust:

```
final_price = base_price * (1 - trust_discount) * (1 + congestion_premium)
```

A peer with a 90% trust score might get a 15% discount. A new, untrusted peer pays full price. Congestion premiums increase during high-demand periods. This creates a virtuous cycle: good behavior → better trust → lower prices → more business.

### SLA Monitoring

Each channel tracks latency and error rates in measurement windows. If a service provider exceeds the negotiated SLA thresholds:

1. Violation is recorded with evidence
2. Dispute can be auto-filed
3. Reputation is penalized
4. Future pricing adjusts upward

### Receipt Chains

Every payment generates a signed receipt that is hash-chained to the previous one — like a mini-blockchain per channel. These receipts are broadcast via GossipSub for network-wide auditability. Anyone can verify the complete payment history between two agents without trusting either party.

---

## The Agent Runtime: The Differentiator

Everything above — channels, vouchers, trust, routing — is infrastructure. The **Agent Runtime** is where it becomes truly autonomous.

The runtime is a tick-based system where agents cycle through strategies every N seconds:

```python
class AgentRuntime:
    async def run(self, task_status):
        while True:
            ctx = self._build_context()      # Snapshot of current state
            for strategy in self.strategies:
                await strategy.tick(ctx)      # Each strategy processes tasks
            await trio.sleep(self.tick_interval)
```

Three built-in strategies coordinate the full lifecycle:

**AutonomousNegotiator** — Evaluates incoming task requests against configurable policies (max price, min trust score). Can auto-accept, counter-offer, or reject. Includes a negotiation round limit to prevent infinite counter-offer loops.

**CoordinatorBehavior** — Assigns tasks to available workers, tracks execution, and sends payment upon completion. Only activates when the agent has the "coordinator" role.

**WorkerBehavior** — Picks up assigned tasks, executes them via a pluggable executor, and reports results. Respects a configurable concurrency limit.

The result: you can submit a task to an agent via `POST /agent/tasks`, and the runtime autonomously negotiates with peers, assigns the work, executes it, settles payment, and updates trust scores — without any human intervention.

```bash
# Submit a task
curl -X POST http://127.0.0.1:8080/agent/tasks \
  -H "Content-Type: application/json" \
  -d '{"description":"Analyze market data for ETH/USDC","amount":5000}'

# The runtime handles everything:
# 1. Negotiates with available workers
# 2. Assigns to the best candidate (trust-weighted)
# 3. Worker executes the task
# 4. Payment is settled via the existing channel
# 5. Trust scores update
```

---

## x402: The HTTP Payment Gateway

Not everything needs a persistent channel. For one-shot requests (like HTTP API calls), AgentPay implements the [x402 protocol](https://www.x402.org/) — the HTTP 402 "Payment Required" flow.

```
Client → GET /api/inference
Server ← 402 Payment Required
         {
           "accepts": [{
             "scheme": "exact",
             "network": "base-sepolia",
             "maxAmountRequired": "5000",
             "resource": "/api/inference"
           }]
         }
Client → POST /gateway/access (with payment proof)
Server ← 200 OK (access granted)
```

Resources are registered with a price, and the gateway verifies payment proofs before granting access. This bridges the channel-based payment world with the HTTP API world — agents can pay for individual API calls without maintaining persistent channels.

---

## The Numbers

After a comprehensive code review and 63 bug fixes across the entire codebase:

| Metric | Count |
|--------|-------|
| **Tests passing** | 680 |
| **Source modules** | 55 across 19 packages |
| **REST API endpoints** | ~50 |
| **CLI commands** | ~50 |
| **Settlement chains** | 3 (Ethereum, Algorand, Filecoin) |
| **Protocol message types** | 13 |
| **Channel states** | 6 |
| **Architecture diagrams** | 13 |
| **Frontend components** | 25 (14 domain + 11 UI primitives) |

The test suite covers the protocol codec, channel state machine, voucher cryptography, REST API, Algorand settlement, SLA monitoring, dynamic pricing, disputes, reputation, multi-hop routing, EIP-191 identity binding, payment error codes, role-based coordination, agent runtime strategies, and full integration flows.

---

## The Dashboard

The Next.js 15 frontend provides a real-time view of the agent network:

- **Interactive network graph** — Force-directed visualization where nodes are agents (color-coded by trust score) and edges are payment channels. Click to open channels or send payments.
- **Trust panels** — Per-peer reputation scores with visual bar charts
- **Simulation controls** — Run batch payment rounds across the network with configurable topology (mesh, ring, star)
- **Live monitoring** — SLA violations, dispute scanning, dynamic pricing quotes, and a real-time event feed

![Payment channel lifecycle](images/payment-channel-lifecycle.png)
*Payment channel lifecycle — the core flow from open to settle*

---

## Running the Demo

The demo path is two commands:

```bash
# Terminal 1: Start 2 agents + dashboard
./scripts/dev.sh

# Terminal 2: Run the 10-phase live demo
./scripts/agent_demo.sh
```

The demo script walks through every feature:

1. **Agent Discovery** — Shows both agents' PeerID, ETH wallet, and EIP-191 binding
2. **Peer Connection** — Verifies bidirectional connectivity
3. **Payment Channel** — Opens a 1 ETH off-chain channel
4. **Micropayment Burst** — 10 rapid payments with timing (sub-millisecond each)
5. **Trust & Reputation** — Shows trust scores building from payment history
6. **Dynamic Pricing** — Price quote with trust discount applied
7. **Agent Runtime** — Submits a task, shows autonomous execution
8. **x402 Gateway** — Registers a gated resource, demonstrates 402 flow
9. **Channel Close** — Cooperative settlement
10. **Summary** — Feature checklist

---

## Ecosystem Alignment

AgentPay is designed for the [Filecoin Onchain Cloud](https://filecoin.cloud/agents) agent ecosystem. We map to 6 of the 7 Requests for Startups (RFS):

| RFS | What We Built |
|-----|---------------|
| **Agentic Storage SDK** | IPFS content-addressed storage for receipts and capabilities |
| **Onchain Agent Registry** | ERC-8004 Identity Registry with PeerID/wallet bridge |
| **Agent Reputation & Portable Identity** | 4-factor trust scoring + hash-chained receipt audit trails |
| **Autonomous Agent Economy Testbed** | Multi-agent simulation with dashboard controls |
| **Fee-Gated Agent Communication** | libp2p P2P streams + x402 payment gateway |
| **Agent-Generated Data Marketplace** | Dynamic pricing + Bazaar-compatible capability registry |

---

## What's Next

AgentPay is functional today for local and testnet deployments. The roadmap includes:

- **Mainnet deployment** — Battle-testing settlement contracts on Ethereum mainnet and Algorand mainnet
- **Cross-chain channels** — Open a channel on Ethereum, settle on Filecoin (or vice versa)
- **Encrypted onion routing** — Full privacy for multi-hop HTLC payments (currently simplified plaintext)
- **WebRTC transport** — Browser-based agents that connect directly via libp2p-webrtc
- **Framework integrations** — Drop-in payment adapters for LangChain, CrewAI, and AutoGPT
- **Storage procurement** — Agents autonomously negotiate and pay for Filecoin storage deals

---

## Why This Matters

The agent economy is inevitable. As AI systems become more capable, they will increasingly operate autonomously — making decisions, consuming services, and producing value without human oversight. When that happens, they need an economic layer that matches their nature:

- **Peer-to-peer** — No centralized payment processor. Agents connect directly.
- **Instant** — Sub-millisecond micropayments. Agents don't wait for block confirmations.
- **Trustless** — Cryptographic guarantees replace human trust relationships.
- **Autonomous** — Discovery, negotiation, payment, monitoring, and dispute resolution — all automated.
- **Auditable** — Every payment is signed, chained, and broadcast for network-wide verification.

AgentPay is our answer to this challenge. Not just payment channels — but the complete economic infrastructure that autonomous agents need to transact, trust, and collaborate in a decentralized world.

**Agents don't need Stripe. They need a native payment layer. We built it.**

---

## Links

- **GitHub**: [github.com/yashksaini-coder/AgentPay](https://github.com/yashksaini-coder/AgentPay)
- **Architecture**: [docs/ARCHITECTURE.md](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/ARCHITECTURE.md)
- **CLI & API Reference**: [docs/COMMANDS.md](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/COMMANDS.md)
- **Ecosystem Alignment**: [docs/ECOSYSTEM-ALIGNMENT.md](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/ECOSYSTEM-ALIGNMENT.md)

---

*Built by [Yash K. Saini](https://github.com/yashksaini-coder) for the PL Genesis hackathon. 680 tests. 55 modules. 3 chains. Zero middlemen.*
