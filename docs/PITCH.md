# AgentPay — Project Pitch

> For hackathons, grant applications, conference submissions, and the ARIA Scaling Trust programme.

---

## One-Liner

Decentralized micropayment channels that let AI agents discover, negotiate, pay, and audit each other in real time over libp2p, settling on Ethereum or Algorand.

## The Problem

AI agents are becoming autonomous — they browse, code, research, and transact. But **there is no native payment layer for agent-to-agent transactions**.

Current options are broken:

- **On-chain per transaction**: Too slow (seconds to minutes), too expensive ($0.50–$50 per tx), doesn't scale to thousands of micro-requests
- **Centralized payment APIs**: Require trust, KYC, rate limits, single point of failure — antithetical to autonomous agents
- **Credit/subscription models**: Don't work when agents are ephemeral and untrusted

Beyond payments, agents lack infrastructure for **discovering** each other's capabilities, **negotiating** service terms, **monitoring** service quality, and **resolving disputes** — all essential for trust in autonomous multi-agent systems.

## The Solution

**AgentPay** implements a full agent-to-agent economic stack — the same payment channel primitive used by Bitcoin Lightning and Filecoin, plus discovery, negotiation, reputation, SLA monitoring, and dispute resolution:

1. **Discover** agents and capabilities via mDNS + GossipSub pubsub
2. **Negotiate** service terms (price, SLA, deposit) with a 4-message protocol
3. **Lock funds once** on Ethereum or Algorand (single on-chain tx)
4. **Exchange signed vouchers** off-chain over libp2p streams (zero cost, sub-ms latency)
5. **Monitor** SLA compliance (latency, error rates) per channel
6. **Settle once** when the channel closes (single on-chain tx)
7. **Audit** via cryptographically-linked receipt chains broadcast on GossipSub

Result: **thousands of micropayments** between two agents with only **2 on-chain transactions** total, backed by verifiable trust infrastructure.

## How It Works

```
Agent A                          Agent B
   │                                │
   │  1. Discover via mDNS/GossipSub│
   │◄──────────────────────────────►│
   │                                │
   │  2. Negotiate terms + SLA      │
   │◄──────────────────────────────►│
   │                                │
   │  3. Open channel (lock 1 ETH)  │
   │───────────────────────────────►│
   │                                │
   │  4. Pay 0.001 ETH (voucher)    │
   │───────────────────────────────►│  ← off-chain, instant, SLA-tracked
   │  5. Pay 0.001 ETH (voucher)    │
   │───────────────────────────────►│  ← receipt chained, reputation updated
   │  ... ×1000 more ...            │
   │                                │
   │  6. Close + settle on-chain    │
   │───────────────────────────────►│
   │                                │
   │  7. Dispute if stale voucher   │
   │◄──────────────────────────────►│  ← auto-detected, reputation penalized
```

## ARIA Scaling Trust Alignment

AgentPay maps directly to the four ARIA evaluation pillars:

| ARIA Pillar | AgentPay Feature | Implementation |
|-------------|-----------------|----------------|
| **Requirement Gathering** | Agent Discovery Protocol | Capability registry, GossipSub advertisements, Bazaar-compatible format |
| **Negotiation** | Negotiation Protocol | 4-message propose/counter/accept/reject with SLA terms and state machine |
| **Security Reasoning** | Trust Infrastructure | ECDSA vouchers, wallet policies, reputation scoring, on-chain settlement (ETH + Algorand) |
| **Reporting** | Execution Reporting | Signed receipt chains, SLA violation tracking, dispute resolution with evidence |

## Key Technical Choices

| Choice | Why |
|--------|-----|
| **libp2p** (not HTTP) | Peer-to-peer, no servers. Noise encryption, mDNS discovery, multiplexed streams. Agents find each other, not a registry. |
| **Cumulative vouchers** (not incremental) | Only the latest voucher matters for settlement. One signature check on-chain. Simpler, cheaper, more secure. |
| **Dual-chain** (ETH + Algorand) | Ethereum for EVM ecosystem, Algorand for ARC-4/x402/Bazaar interoperability. Chain-selectable at startup. |
| **Trio** (not asyncio) | Structured concurrency prevents leaked connections in long-running daemons. Required by py-libp2p. |
| **Two key systems** | Ed25519 for P2P identity, secp256k1/Ed25519 for payments. Same approach as Filecoin. Clean separation of concerns. |

## What We Built

| Component | Details |
|-----------|---------|
| P2P Networking | py-libp2p with TCP/WS, Noise, Yamux, mDNS, GossipSub (4 topics) |
| Payment Protocol | Custom `/agentic-payments/1.0.0` stream protocol with msgpack framing, 12 message types |
| Channel State Machine | 6 states, 7 transitions, full voucher validation |
| Discovery | Capability registry, GossipSub advertisements, Bazaar-compatible API |
| Negotiation | 4-message protocol with SLA terms, state machine, timeout handling |
| Reputation | Trust scoring (success rate, volume, response time, longevity), reputation-weighted routing |
| SLA Monitoring | Per-channel latency/error tracking, auto-violation detection, compliance reporting |
| Pricing Engine | Dynamic pricing with trust discounts and congestion premiums |
| Disputes | Auto-detection of stale vouchers, manual filing, reputation-linked resolution |
| Receipt Chains | Cryptographically-linked receipts broadcast on GossipSub for auditability |
| Wallet Policies | Per-tx limits, total spend caps, rate limiting, peer whitelist/blacklist |
| Smart Contracts | Ethereum `PaymentChannel.sol` + Algorand ARC-4 contract with box storage |
| Gateway | x402-compatible resource gating for ecosystem interoperability |
| REST API | ~40 endpoints on Quart-Trio + Hypercorn |
| Dashboard | Next.js 15 multi-agent UI with network graph, trust panels, SLA/dispute/pricing panels |
| CLI | 30+ commands across 10 sub-apps (Typer) |
| Test Suite | 541 tests across 27 files (pytest-trio) |

## Use Cases

### Pay-per-query AI services
Agent A asks Agent B to summarize a document. They negotiate terms (price, latency SLA), open a channel, and Agent B charges per request. No subscription, no API key — just a payment channel with SLA monitoring.

### Autonomous data marketplaces
Agents discover data providers via GossipSub, negotiate pricing, open channels, and pay per-record. Reputation scores ensure quality; disputes handle bad data.

### Multi-agent workflows
A coordinator agent discovers specialists via the capability registry, negotiates terms with each, opens channels, and pays for contributions. Receipt chains provide full audit trails.

### Decentralized compute
Agent A offloads GPU inference to Agent B, paying per-token generated. SLA monitoring tracks latency; auto-disputes fire if the provider degrades.

## Differentiation

| | AgentPay | Lightning | Stripe Connect | x402 |
|---|---------|-----------|----------------|------|
| Agent-native | Yes | No | No | Partial |
| P2P discovery | mDNS + GossipSub | Gossip | N/A | Bazaar |
| Negotiation protocol | Yes (4-message) | No | No | No |
| SLA monitoring | Yes | No | No | No |
| Reputation system | Yes | No | No | No |
| Dispute resolution | Yes | HTLC timeout | Stripe | No |
| Multi-chain | ETH + Algorand | Bitcoin | Fiat | Algorand |
| Micropayment cost | ~0 (off-chain) | ~0 (off-chain) | 2.9% + $0.30 | Per-tx |
| Setup complexity | `uv sync && agentpay start` | Run LND + Bitcoin node | Onboarding flow | Facilitator |

## Team

**Yash K. Saini** — [GitHub](https://github.com/yashksaini-coder) · [LinkedIn](https://www.linkedin.com/in/yashksaini/) · [Portfolio](https://www.yashksaini.systems/)

## Links

- **Repository**: [github.com/yashksaini-coder/AgentPay](https://github.com/yashksaini-coder/AgentPay)
- **Architecture**: [docs/ARCHITECTURE.md](ARCHITECTURE.md)
- **CLI Reference**: [docs/COMMANDS.md](COMMANDS.md)
- **Ecosystem Alignment**: [docs/ECOSYSTEM-ALIGNMENT.md](ECOSYSTEM-ALIGNMENT.md)
