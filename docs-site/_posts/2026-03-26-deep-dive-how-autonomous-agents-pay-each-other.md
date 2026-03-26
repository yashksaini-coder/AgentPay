---
title: "Deep Dive: How Autonomous Agents Pay Each Other"
layout: post
date: 2026-03-26
author: Yash K. Saini
---

*A technical deep-dive into AgentPay — from problem statement to architecture decisions, real code, and a working demo. 680 tests, 55 modules, 3 settlement chains, zero middlemen.*

**Reading time: ~17 minutes**

---

## TL;DR

AgentPay is a decentralized micropayment protocol built on [libp2p](https://libp2p.io/) that lets AI agents discover each other, negotiate service terms, exchange off-chain payments in sub-millisecond, and settle on Ethereum, Algorand, or Filecoin. It uses Filecoin-style cumulative vouchers, HTLC multi-hop routing, a 4-factor trust scoring system, and an autonomous agent runtime. Two on-chain transactions settle thousands of micropayments. The [code is open source](https://github.com/yashksaini-coder/AgentPay).

---

## The Scenario That Started Everything

Imagine this: Agent A is a coordinator managing a research pipeline. It needs to farm out 500 document summarization tasks to the cheapest available GPU inference providers on the network. Agent B offers inference at 0.001 ETH per request with a 200ms latency SLA. Agent C offers the same service at 0.0008 ETH but has a patchy track record.

Agent A needs to answer three questions before spending a single wei:

1. **Who can I pay?** (Discovery)
2. **Can I trust them?** (Reputation)
3. **How do I pay 500 times without going bankrupt on gas?** (Payment channels)

We built AgentPay because autonomous agents need an economic layer that matches their nature — peer-to-peer, instant, trustless, and fully automated.

---

## Why Existing Solutions Fail

### The Per-Transaction Trap

| Metric | Value |
|--------|-------|
| Tasks | 500 |
| Gas per tx | ~65,000 |
| Gas price (20 gwei) | 0.0013 ETH per tx |
| **Total gas cost** | **0.65 ETH (~$1,600)** |
| **Total wait time** | **2+ hours** |

### The Centralized API Trap

Stripe, PayPal fail for agents: no KYC possible, 200-500ms latency, rate limits, single point of failure.

### The x402 Gap

The [x402 protocol](https://www.x402.org/) is elegant for one-shot requests, but doesn't solve persistent relationships. AgentPay bridges this gap with both x402 one-shot payments *and* persistent channels.

---

## Architecture: Six Layers, One Protocol

![AgentPay system architecture]({{ site.baseurl }}/assets/images/system-architecture.png)
*System architecture — networking, wire protocol, payment channels, settlement, identity, and trust.*

![Module dependency map]({{ site.baseurl }}/assets/images/module-architecture.png)
*55 source modules across 19 packages. Dependencies only point downward.*

### Layer 1: Networking — Why libp2p, Not HTTP

With HTTP, someone has to host an endpoint. Agents are ephemeral. [libp2p](https://github.com/libp2p/py-libp2p) gives us TCP + WebSocket transports, Noise encryption, Yamux multiplexing, mDNS discovery, and GossipSub pubsub.

![Wire protocol]({{ site.baseurl }}/assets/images/wire-protocol.png)
*13 message types cover the complete payment lifecycle.*

### Layer 2: Payment Channels — Filecoin's Voucher Model

We chose Filecoin's **cumulative voucher** model over Lightning's **commitment transaction** model:

| | Cumulative (Filecoin/AgentPay) | Commitment (Lightning) |
|---|---|---|
| Each payment | New voucher replaces previous | New commitment tx invalidates previous |
| State to store | 1 voucher (the latest) | All prior commitments |
| Complexity | Lower | Higher (penalty txs, watchtowers) |

The most interesting design decision: we send the voucher to the peer *first*, then commit locally only on success. This prevents state divergence.

### Layer 3: The Channel State Machine

![Channel state machine]({{ site.baseurl }}/assets/images/state-machine.png)
*PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED, with DISPUTED branch*

### Layer 4: Multi-Hop Routing (HTLC)

![HTLC multi-hop routing]({{ site.baseurl }}/assets/images/htlc-routing.png)
*Agent A pays Agent C through Agent B. Each hop has a decrementing timeout.*

The pathfinder uses reputation-weighted Dijkstra — highly trusted intermediaries are preferred.

---

## The Trust Layer

![Trust architecture]({{ site.baseurl }}/assets/images/trust-architecture.png)
*Reputation, SLA, disputes, policies, and pricing tied together.*

### Reputation: A 4-Factor Trust Score

```
trust_score = 0.4*success + 0.3*volume + 0.2*speed + 0.1*longevity
```

Trust scores feed into dynamic pricing and GossipSub peer scoring.

### Receipt Chains: A Mini-Blockchain Per Channel

Every payment generates a signed receipt hash-chained to the previous one, broadcast via GossipSub for network-wide verification.

---

## The Agent Runtime

Three strategies: **AutonomousNegotiator**, **CoordinatorBehavior**, **WorkerBehavior**.

When you submit a task:

1. Task created → `PENDING`
2. Coordinator finds and assigns to best worker (trust-weighted)
3. Worker executes via pluggable executor
4. Payment triggered over existing channel
5. Trust updated

All autonomous. No human intervention.

---

## Tri-Chain Settlement

| Chain | Contract | Why |
|-------|----------|-----|
| **Ethereum** | Solidity `PaymentChannel.sol` | EVM ecosystem |
| **Algorand** | ARC-4 app + box storage | Bazaar alignment |
| **Filecoin FEVM** | Same Solidity contract | Storage market |

Adding a new chain is four methods.

---

## Identity: Two Key Pairs, One Agent

- **Ed25519** — libp2p PeerID
- **secp256k1** — Ethereum wallet

Bound with EIP-191 and registered on-chain via ERC-8004.

![ERC-8004 identity flow]({{ site.baseurl }}/assets/images/erc8004-identity-flow.png)
*Identity bridge maps PeerID to wallet to on-chain agentId.*

---

## By The Numbers

| | |
|---|---|
| **680 tests** across 40 test files | Protocol, payments, routing, trust, API, integration |
| **55 source modules** in 19 packages | Clean separation of concerns |
| **~50 REST API endpoints** | Every feature accessible via HTTP |
| **3 settlement chains** | Ethereum, Algorand, Filecoin FEVM |
| **13 protocol message types** | Complete wire protocol |
| **11 seconds** | Full test suite runtime |

---

## What's Next

- **Mainnet settlement** — live-chain battle testing
- **Encrypted onion routing** — production-secure multi-hop
- **WebRTC transport** — browser-based agents
- **Framework adapters** — LangChain, CrewAI, AutoGPT
- **Cross-chain channels** — open on Ethereum, settle on Filecoin

---

**The code is open source. The demo is two commands. [Try it.](https://github.com/yashksaini-coder/AgentPay)**

*Built by [Yash K. Saini](https://github.com/yashksaini-coder) for the [PL Genesis](https://plgenesis.com/) hackathon.*
