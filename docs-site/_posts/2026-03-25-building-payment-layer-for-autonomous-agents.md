---
title: "Building the Payment Layer for Autonomous AI Agents"
layout: post
date: 2026-03-25
author: Yash K. Saini
---

*How we built AgentPay — a decentralized micropayment protocol that lets AI agents discover, negotiate, pay, and settle with each other, peer-to-peer, with no middleman.*

---

## The Agent Economy Is Here. The Payment Layer Isn't.

Something fundamental is shifting in how software works. AI agents are no longer just answering questions in a chat window — they're browsing the web, writing code, managing infrastructure, analyzing data, and making decisions autonomously. Projects like [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT), [CrewAI](https://www.crewai.com/), and [LangGraph](https://www.langchain.com/langgraph) have shown that multi-agent systems can tackle problems that no single model can solve alone.

But here's the problem nobody talks about enough: **how do these agents pay each other?**

When Agent A needs Agent B to summarize 10,000 documents, or when a coordinator agent wants to distribute inference tasks across a network of GPU providers, someone needs to get paid. Today, the options are bleak:

- **On-chain per transaction**: $0.50–$50 per tx, 15-second confirmation times. If your agents are making 1,000 requests per minute, this doesn't scale.
- **Centralized payment APIs (Stripe, PayPal)**: Require KYC, human approval, API keys, rate limits. Autonomous agents can't fill out forms.
- **Credit/subscription models**: Require pre-existing trust relationships. But agents are ephemeral — they spin up, do work, and disappear.

We built **AgentPay** to solve this. It's a full economic stack for autonomous agents: discover peers, negotiate terms, lock funds once on-chain, exchange thousands of off-chain micropayments, monitor service quality, resolve disputes, and settle — all peer-to-peer over [libp2p](https://libp2p.io/).

---

## What We Built (And Why It's Different)

AgentPay isn't just a payment channel. It's the full lifecycle of what agents need to transact economically with each other.

![AgentPay system architecture]({{ site.baseurl }}/assets/images/system-architecture.png)
*AgentPay system architecture — networking, protocol, payments, settlement, identity, and trust layers*

### The Seven-Step Agent Payment Lifecycle

Here's how two agents go from strangers to trading partners:

**1. Discovery** — Agents find each other via mDNS on a local network or GossipSub pubsub across the internet. Each agent advertises its capabilities (compute, inference, storage, data) in a format compatible with the [Bazaar protocol](https://github.com/basketprotocol/bazaar).

**2. Negotiation** — Before any money changes hands, agents agree on terms. Our 4-message negotiation protocol handles: proposed price, SLA requirements (max latency, max error rate), deposit amount, and service type.

**3. Channel Open** — The sender locks funds into a payment channel with a single on-chain transaction. This is the *only* gas-intensive operation.

**4. Micropayments** — Now the magic happens. The sender signs cumulative vouchers — just like Filecoin's payment channels — and sends them directly to the receiver over a libp2p stream. No gas. No confirmation wait. Sub-millisecond.

**5. Trust Building** — Every successful payment updates the receiver's trust score for the sender, factoring in success rate, payment volume, response latency, and relationship longevity.

**6. SLA Monitoring** — The channel continuously tracks whether the service provider meets their promised SLA.

**7. Settlement** — When the channel closes, only the final voucher is submitted on-chain. One transaction settles thousands of payments.

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

![Module architecture diagram]({{ site.baseurl }}/assets/images/module-architecture.png)
*Module dependency map — interface, core, network, business, trust, and settlement layers*

### Networking: libp2p All The Way Down

We chose [py-libp2p](https://github.com/libp2p/py-libp2p) over HTTP for a simple reason: **agents shouldn't need servers**. With libp2p, every agent is both a client and a server.

Our custom stream protocol (`/agentic-payments/1.0.0`) uses msgpack with 4-byte length-prefix framing. 13 message types cover the full payment lifecycle.

![Wire protocol diagram]({{ site.baseurl }}/assets/images/wire-protocol.png)
*All 13 message types with fields and framing format*

### Payment Channels: Filecoin's Model, Adapted for Agents

Each voucher replaces the previous one. If Agent A sends voucher #1 for 0.001 ETH, then voucher #2 for 0.003 ETH, only voucher #2 matters.

The channel state machine has 6 states with a challenge period for dispute resolution:

![Channel state machine]({{ site.baseurl }}/assets/images/state-machine.png)
*6-state lifecycle: PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED, with DISPUTED branch*

### Multi-Hop Routing: HTLC Like Lightning

AgentPay supports Hash Time-Locked Contract (HTLC) multi-hop routing — the same primitive that powers Bitcoin's Lightning Network.

![HTLC routing diagram]({{ site.baseurl }}/assets/images/htlc-routing.png)
*Multi-hop payment via intermediaries with reputation-weighted BFS pathfinding*

### Tri-Chain Settlement

| Chain | Contract | Use Case |
|-------|----------|----------|
| **Ethereum** | Solidity `PaymentChannel.sol` | EVM ecosystem, DeFi composability |
| **Algorand** | ARC-4 + box storage | Bazaar/x402 ecosystem interop |
| **Filecoin FEVM** | Same Solidity contract | Storage market alignment |

### Identity: ERC-8004 + EIP-191

Every agent has two key pairs: **Ed25519** for libp2p peer identity and **secp256k1** for Ethereum payments. We bridge these with EIP-191 and implement ERC-8004 for on-chain identity.

![ERC-8004 identity flow]({{ site.baseurl }}/assets/images/erc8004-identity-flow.png)
*Agent registration, identity bridge, reputation sync*

---

## The Trust Layer: Why Payments Alone Aren't Enough

![Trust architecture]({{ site.baseurl }}/assets/images/trust-architecture.png)
*Reputation, SLA monitoring, disputes, policies, and pricing interactions*

### Reputation Scoring

```
trust_score = w1 * success_rate + w2 * volume_score + w3 * latency_score + w4 * longevity_score
```

### Dynamic Pricing

```
final_price = base_price * (1 - trust_discount) * (1 + congestion_premium)
```

---

## The Agent Runtime: The Differentiator

The runtime is a tick-based system with three built-in strategies: **AutonomousNegotiator**, **CoordinatorBehavior**, and **WorkerBehavior**. Submit a task, and the runtime autonomously negotiates, assigns, executes, and settles.

---

## The Numbers

| Metric | Count |
|--------|-------|
| **Tests passing** | 680 |
| **Source modules** | 55 across 19 packages |
| **REST API endpoints** | ~50 |
| **CLI commands** | ~50 |
| **Settlement chains** | 3 |
| **Protocol message types** | 13 |

---

## Running the Demo

```bash
# Terminal 1: Start 2 agents + dashboard
./scripts/dev.sh

# Terminal 2: Run the 10-phase live demo
./scripts/agent_demo.sh
```

---

## Links

- **GitHub**: [github.com/yashksaini-coder/AgentPay](https://github.com/yashksaini-coder/AgentPay)
- **Architecture**: [docs/ARCHITECTURE.md](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/ARCHITECTURE.md)
- **CLI & API Reference**: [docs/COMMANDS.md](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/COMMANDS.md)

*Built by [Yash K. Saini](https://github.com/yashksaini-coder) for the PL Genesis hackathon. 680 tests. 55 modules. 3 chains. Zero middlemen.*
