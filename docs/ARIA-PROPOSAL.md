# AgentPay — ARIA Scaling Trust Proposal

> Track 2: Tooling | Deadline: 24 March 2026

---

## Executive Summary

AgentPay is an open-source framework for decentralized micropayment channels between autonomous AI agents. Built on libp2p with dual-chain settlement (Ethereum + Algorand), it provides the full economic stack agents need to transact autonomously: discovery, negotiation, payment, monitoring, and dispute resolution.

This proposal targets **ARIA Scaling Trust Track 2 (Tooling)** — we provide reusable infrastructure that any agent framework can integrate to enable trusted economic interactions without centralized intermediaries.

---

## Problem Statement

Autonomous AI agents increasingly need to transact with each other — paying for compute, data, inference, and services. Current payment infrastructure fails agents in four ways:

1. **Discovery**: No standard for agents to advertise capabilities and find service providers
2. **Negotiation**: No protocol for agents to agree on terms (price, quality, SLA) before transacting
3. **Security**: On-chain per-transaction is too slow/expensive; centralized APIs require trust
4. **Accountability**: No audit trail, no SLA enforcement, no dispute mechanism when things go wrong

These gaps correspond directly to the four ARIA evaluation pillars.

---

## Solution: AgentPay

### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Agent Node (libp2p)                    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Discovery│  │Negotiation│  │ Payment  │  │Reporting│ │
│  │ Registry │  │ Manager  │  │ Channels │  │ Receipts│ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │              │              │              │      │
│  ┌────┴─────┐  ┌────┴─────┐  ┌────┴─────┐  ┌────┴────┐ │
│  │Reputation│  │   SLA    │  │  Policy  │  │ Dispute │ │
│  │ Tracker  │  │ Monitor  │  │  Engine  │  │ Monitor │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│                                                          │
│  ┌──────────────────────────────────────────────────────┐│
│  │  GossipSub Pubsub (4 topics)  │  Stream Protocol    ││
│  └──────────────────────────────────────────────────────┘│
│                                                          │
│  ┌─────────────────┐  ┌────────────────────────────────┐│
│  │  Ethereum        │  │  Algorand (ARC-4 + Box Storage)││
│  │  PaymentChannel  │  │  AlgorandSettlement            ││
│  └─────────────────┘  └────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘
```

### Technical Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, trio structured concurrency |
| Networking | py-libp2p 0.6.0 (TCP/WS, Noise, Yamux, mDNS, GossipSub) |
| Payments | Cumulative vouchers, ECDSA signatures, HTLC multi-hop routing |
| Settlement | Ethereum (Solidity) + Algorand (ARC-4, box storage, atomic groups) |
| API | Quart-Trio (~40 REST endpoints) + Next.js 15 dashboard |
| Testing | 539 tests, ruff lint clean |

---

## ARIA Pillar Mapping

### Pillar 1: Requirement Gathering

**Feature**: Agent Discovery Protocol

Agents autonomously discover each other's capabilities via two mechanisms:

- **mDNS**: Zero-configuration LAN discovery — agents on the same network find each other automatically
- **GossipSub**: Agents publish `AgentAdvertisement` messages containing their peer ID, wallet address, capabilities (service type, price, description), and listen addresses

The `CapabilityRegistry` indexes advertisements and supports:
- Search by capability type (`GET /discovery/agents?capability=compute`)
- Bazaar-compatible format for x402 ecosystem interop (`GET /discovery/resources`)
- Automatic pruning of stale advertisements (configurable threshold)

**Evaluation metric alignment**: Agents can find suitable service providers without human intervention. The registry is fully decentralized — no central directory.

### Pillar 2: Negotiation

**Feature**: Negotiation Protocol

Before opening a payment channel, agents negotiate terms using a 4-message protocol over libp2p streams:

| Step | Message | Content |
|------|---------|---------|
| 1 | `NEGOTIATE_PROPOSE` | Service type, proposed price, channel deposit, timeout |
| 2 | `NEGOTIATE_COUNTER` | Alternative price (optional) |
| 3 | `NEGOTIATE_ACCEPT` | Agreement confirmation |
| 4 | `NEGOTIATE_REJECT` | Refusal with reason |

Negotiations include **SLA terms**: max latency, max error rate, min throughput, penalty rate, measurement window, and dispute threshold. The state machine handles timeouts and multiple counter-proposals.

On acceptance, the negotiated terms automatically:
- Open a payment channel with the agreed deposit
- Register the channel with the SLA monitor using the agreed thresholds
- Set pricing based on negotiated terms

**Evaluation metric alignment**: Agents autonomously agree on service terms including quality guarantees, without human mediation.

### Pillar 3: Security Reasoning

**Features**: Wallet Policies, Reputation System, On-Chain Settlement, Dispute Resolution

#### Wallet Policies
The `PolicyEngine` enforces spend controls:
- Per-transaction maximum
- Total cumulative spend cap
- Rate limiting (payments per minute)
- Peer whitelist/blacklist

#### Reputation System
The `ReputationTracker` computes per-peer trust scores:
```
trust_score = 0.4 * success_rate + 0.3 * volume + 0.2 * response_speed + 0.1 * longevity
```

Trust scores influence:
- **Routing**: Reputation-weighted BFS prefers trustworthy paths
- **Pricing**: Higher trust → larger discounts
- **Discovery**: Trust-colored nodes in the network graph

#### On-Chain Settlement
Dual-chain support provides flexibility:
- **Ethereum**: `PaymentChannel.sol` with challenge period for fraud protection
- **Algorand**: ARC-4 smart contract with box storage, atomic transaction groups

#### Dispute Resolution
The `DisputeMonitor` automatically detects stale voucher attacks and files disputes. Resolution outcomes feed back into the reputation system.

**Evaluation metric alignment**: Multiple layers of security reasoning — spending limits prevent runaway costs, reputation informs trust decisions, on-chain settlement provides finality, disputes handle adversarial behavior.

### Pillar 4: Reporting

**Features**: Signed Receipt Chains, SLA Monitoring

#### Receipt Chains
Every payment produces a `SignedReceipt` forming a cryptographic hash chain:
- Each receipt contains: receipt ID, channel ID, nonce, amount, timestamp, sender, receiver, previous receipt hash, EIP-191 signature
- Receipts are broadcast on GossipSub for cross-verification
- `ReceiptStore.verify_chain()` validates hash chain integrity

#### SLA Monitoring
The `SLAMonitor` tracks per-channel compliance:
- Records latency (ms) and success/failure for every payment
- Checks against negotiated SLA thresholds
- Generates violations with measured value vs. threshold
- Flags non-compliant channels when violations exceed dispute threshold

**Evaluation metric alignment**: Full audit trail via receipt chains, real-time compliance monitoring via SLA tracker, all data accessible via REST API for external analysis.

---

## Metrics and Evaluation

| Metric | Current Value |
|--------|--------------|
| Test coverage | 539 tests across 27 files |
| REST API endpoints | ~40 |
| CLI commands | 30+ across 10 sub-apps |
| GossipSub topics | 4 (discovery, capabilities, receipts, channels) |
| Wire protocol messages | 12 types |
| Channel state transitions | 7 |
| Supported chains | 2 (Ethereum, Algorand) |
| Frontend panels | 7 (network, discovery, negotiations, trust, SLA, disputes, pricing) |

### Performance Characteristics

- **Payment latency**: Sub-millisecond (off-chain voucher exchange over libp2p stream)
- **On-chain transactions**: 2 per channel lifecycle (open + close)
- **Discovery**: ~10s via mDNS, instant via GossipSub after mesh formation
- **Negotiation**: Single round-trip for propose/accept, multi-round for counter-proposals

---

## Interoperability

### Algorand x402 Ecosystem
- `GET /discovery/resources` returns Bazaar-compatible format
- `X402Gateway` publishes gated resources indexable by x402 facilitators
- `AlgorandSettlement` uses ARC-4 ABI for standard contract interaction

### Agent Framework Integration
AgentPay exposes a REST API that any agent framework can integrate:
- LangChain/LangGraph agents can call `/negotiate`, `/pay`, `/discovery/agents`
- AutoGPT/CrewAI agents can use the CLI (`agentpay negotiate propose ...`)
- Custom agents can use the Python API directly (`AgentNode.negotiate()`, `AgentNode.pay()`)

---

## Roadmap

### Completed (Current Submission)
- Full payment channel lifecycle (open, pay, close, dispute, settle)
- Agent discovery via mDNS + GossipSub
- 4-message negotiation protocol with SLA terms
- Reputation scoring with routing integration
- SLA monitoring and violation tracking
- Dynamic pricing engine
- Dispute detection and resolution
- Signed receipt chains
- Wallet policies
- Dual-chain settlement (Ethereum + Algorand)
- x402 gateway compatibility
- Next.js dashboard with trust panels
- 539 tests, lint clean

### Planned
- Persistent storage (PostgreSQL) for production deployments
- Multi-hop payment optimization (Dijkstra with fee estimation)
- Agent SDK wrappers for LangChain, CrewAI, AutoGPT
- EIP-3009 transfer-with-authorization for x402 direct payments
- WebRTC transport for browser-native agents
- Formal verification of smart contracts

---

## Team

**Yash K. Saini** — Full-stack developer specializing in decentralized systems, P2P networking, and AI agent infrastructure.

- [GitHub](https://github.com/yashksaini-coder)
- [LinkedIn](https://www.linkedin.com/in/yashksaini/)
- [Portfolio](https://www.yashksaini.systems/)

---

## Links

- **Repository**: [github.com/yashksaini-coder/AgentPay](https://github.com/yashksaini-coder/AgentPay)
- **Architecture**: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- **CLI Reference**: [docs/COMMANDS.md](COMMANDS.md)
- **Pitch**: [docs/PITCH.md](PITCH.md)
- **Demo**: [docs/DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md)
