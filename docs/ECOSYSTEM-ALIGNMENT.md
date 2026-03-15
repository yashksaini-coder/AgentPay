# Ecosystem Alignment

> How AgentPay maps to the Filecoin Onchain Cloud agent ecosystem.

---

## Filecoin Agents RFS Alignment

The [Filecoin Agents](https://filecoin.cloud/agents) initiative defines 7 Requests for Startups (RFS) for AI-native infrastructure. AgentPay addresses 6 of them.

| RFS | Title | AgentPay Component | Status |
|-----|-------|-------------------|--------|
| **RFS-1** | Agentic Storage SDK | `storage/` — IPFS content-addressed storage for receipts and capabilities, trio-compatible HTTP client | **Complete** |
| **RFS-2** | Onchain Agent Registry | `identity/` — ERC-8004 Identity Registry (ERC-721), IdentityBridge (PeerID + wallet → agentId), reputation sync | **Complete** |
| **RFS-3** | Agent Reputation & Portable Identity | `reputation/` — 4-factor trust scoring, `reporting/` — hash-chained signed receipt audit trail, GossipSub broadcast | **Complete** |
| **RFS-4** | Autonomous Agent Economy Testbed | `scripts/dev.sh` — multi-agent simulation, dashboard simulation tab — batch payments, topology control | **Complete** |
| **RFS-5** | Fee-Gated Agent Communication Protocol | `protocol/` — libp2p P2P streams (no central relay), `gateway/` — x402 payment verification, `payments/` — Filecoin-style cumulative vouchers | **Complete** |
| **RFS-7** | Agent-Generated Data Marketplace | `pricing/` — dynamic pricing with trust discounts + congestion premiums, `discovery/` — capability registry with Bazaar-compatible format | **Complete** |
| **RFS-6** | Autonomous Infrastructure Brokerage | SLA negotiation exists but not storage procurement | Roadmap |

---

## Core Architecture Alignment

### Payment Channel Pattern (Filecoin-derived)

AgentPay implements the same payment channel pattern used by Filecoin:

- **Cumulative vouchers** — each voucher replaces the previous one (not incremental)
- **Single on-chain settlement** — lock funds once, exchange vouchers off-chain, settle once
- **ECDSA signatures** — vouchers are signed with secp256k1 and verified via `ecrecover`
- **Challenge period** — on-chain dispute window before final withdrawal

### Provable Behavioral History (RFS-3)

Receipt chains provide tamper-resistant behavioral history:

```
Receipt #0 → Receipt #1 → Receipt #2 → ... → Receipt #N
  (genesis)     SHA-256       SHA-256              SHA-256
  prev=0x00     prev=H(#0)    prev=H(#1)          prev=H(#N-1)
```

- Each receipt is EIP-191 signed by the sender
- Receipts are hash-chained (SHA-256) — tampering breaks the chain
- Broadcast on GossipSub for cross-agent verification
- `ReceiptStore.verify_chain()` validates full integrity
- Receipts can be pinned to IPFS for content-addressed persistence

### Fee-Gated Communication (RFS-5)

The x402 gateway implements the server-side payment protocol:

1. Client requests a gated resource
2. Server responds with `402 Payment Required` + pricing metadata
3. Client submits payment proof (channel ID, voucher nonce, amount)
4. Server verifies payment against channel state and grants access

### Dynamic Pricing (RFS-7)

```
multiplier = 1.0 - (discount * trust_score) + (premium * congestion_ratio)
final_price = max(base_price * multiplier, floor)
```

- Higher trust → larger discount (configurable up to 30%)
- More active channels → congestion premium (up to 50%)
- Integrated with negotiation protocol for SLA-based pricing

---

## x402 Protocol Compliance

AgentPay implements the [x402 V1 standard](https://www.x402.org/) for payment-gated resource access. The 402 response follows the spec-compliant format:

```json
{
  "x402Version": 1,
  "accepts": [
    {
      "scheme": "exact",
      "network": "ethereum-sepolia",
      "maxAmountRequired": "1000",
      "payTo": "0xAbC...",
      "asset": "native",
      "resource": "/api/v1/inference",
      "description": "LLM inference",
      "maxTimeoutSeconds": 30,
      "mimeType": "application/json"
    }
  ]
}
```

The Bazaar discovery format uses the same schema, enabling indexing by Algorand, Coinbase, and Filecoin facilitators. Used by `GET /gateway/resources`, `GET /discovery/resources`, and GossipSub capability broadcasts.

---

## Multi-Chain Settlement

| Chain | Contract | Status | Token |
|-------|---------|--------|-------|
| **Ethereum** | `PaymentChannel.sol` (Solidity ^0.8) | Implemented (local Anvil verified) | ETH + ERC-20 |
| **Algorand** | ARC-4 application + box storage | Implemented (testnet ready) | ALGO |
| **Filecoin** | Same `PaymentChannel.sol` on FEVM | Implemented (Calibration ready) | FIL (via FEVM) |

The settlement layer is chain-agnostic by design (`chain/protocols.py` defines `WalletProtocol` and `SettlementProtocol` interfaces). Each chain implements these interfaces independently.

---

## Demo

1. Start multi-agent network via `./scripts/dev.sh`
2. Agents auto-discover via mDNS, exchange capabilities on GossipSub
3. Open payment channels, exchange micropayments
4. Show trust scores updating, dynamic pricing adapting
5. Demonstrate x402 gateway access with payment verification
6. Show hash-chained receipt audit trail
7. Settle on Ethereum, Algorand, or Filecoin

Run `./scripts/demo.sh` for a 9-phase automated API demo, or `./scripts/live_test.sh` for comprehensive end-to-end verification.
