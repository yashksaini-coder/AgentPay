---
title: Ecosystem Alignment
layout: default
nav_order: 4
---

# Ecosystem Alignment

> How AgentPay maps to the Filecoin Onchain Cloud agent ecosystem.

---

## Filecoin Agents RFS Alignment

The [Filecoin Agents](https://filecoin.cloud/agents) initiative defines 7 Requests for Startups (RFS) for AI-native infrastructure. AgentPay addresses 6 of them.

| RFS | Title | AgentPay Component | Status |
|-----|-------|-------------------|--------|
| **RFS-1** | Agentic Storage SDK | `storage/` — IPFS content-addressed storage for receipts and capabilities | **Complete** |
| **RFS-2** | Onchain Agent Registry | `identity/` — ERC-8004 Identity Registry (ERC-721), IdentityBridge | **Complete** |
| **RFS-3** | Agent Reputation & Portable Identity | `reputation/` — 4-factor trust scoring, hash-chained receipt audit trail | **Complete** |
| **RFS-4** | Autonomous Agent Economy Testbed | Multi-agent simulation, dashboard simulation tab | **Complete** |
| **RFS-5** | Fee-Gated Agent Communication Protocol | `protocol/` — libp2p P2P streams, `gateway/` — x402 payment verification | **Complete** |
| **RFS-7** | Agent-Generated Data Marketplace | `pricing/` — dynamic pricing, `discovery/` — Bazaar-compatible format | **Complete** |
| **RFS-6** | Autonomous Infrastructure Brokerage | SLA negotiation exists but not storage procurement | Roadmap |

---

## Core Architecture Alignment

### Payment Channel Pattern (Filecoin-derived)

- **Cumulative vouchers** — each voucher replaces the previous one
- **Single on-chain settlement** — lock funds once, exchange vouchers off-chain, settle once
- **ECDSA signatures** — vouchers signed with secp256k1, verified via `ecrecover`
- **Challenge period** — on-chain dispute window before final withdrawal

### Provable Behavioral History (RFS-3)

Receipt chains provide tamper-resistant behavioral history:

```
Receipt #0 → Receipt #1 → Receipt #2 → ... → Receipt #N
  (genesis)     SHA-256       SHA-256              SHA-256
  prev=0x00     prev=H(#0)    prev=H(#1)          prev=H(#N-1)
```

### Fee-Gated Communication (RFS-5)

The x402 gateway implements the server-side payment protocol using [x402 V1 standard](https://www.x402.org/).

### Dynamic Pricing (RFS-7)

```
multiplier = 1.0 - (discount * trust_score) + (premium * congestion_ratio)
final_price = max(base_price * multiplier, floor)
```

---

## x402 Protocol Compliance

AgentPay implements the x402 V1 standard for payment-gated resource access with Bazaar-compatible discovery format.

---

## Multi-Chain Settlement

| Chain | Contract | Status | Token |
|-------|---------|--------|-------|
| **Ethereum** | `PaymentChannel.sol` | Implemented | ETH + ERC-20 |
| **Algorand** | ARC-4 + box storage | Implemented | ALGO |
| **Filecoin** | Same contract on FEVM | Implemented | FIL |

---

## Cross-Ecosystem Alignment

### libp2p-v4-swap-agents

| Feature | libp2p-v4-swap-agents | AgentPay |
|---------|----------------------|----------|
| EIP-191 PeerId binding | `"libp2p-v4-swap-agents:identity:{peer_id}"` | `"AgentPay:identity:{peer_id}"` via `identity/eip191.py` |
| GossipSub peer scoring | Weighted scoring | Same weights + reputation-wired `app_specific_score_fn` |
| Dynamic fee rebates | Uniswap V4 hooks | Trust-based pricing discounts |

### Google a2a-x402

| Feature | a2a-x402 | AgentPay |
|---------|---------|----------|
| TaskId correlation | Every payment linked to work request | `task_id` field on vouchers |
| Standardized error codes | `INSUFFICIENT_FUNDS`, etc. | `PaymentErrorCode` enum (6 ranges) |
| Payment schemes | `exact`, `escrow`, `streaming` | Channels (streaming) + one-shot (exact) |

### P2P-Federated-Learning

| Feature | P2P-FL | AgentPay |
|---------|--------|----------|
| Role-based agents | Bootstrap, Client, Trainer | coordinator, worker, data_provider, validator, gateway |
| Work rounds | Training rounds | `WorkRound` with task assignment |
| Same stack | py-libp2p + trio + GossipSub | py-libp2p + trio + GossipSub |
