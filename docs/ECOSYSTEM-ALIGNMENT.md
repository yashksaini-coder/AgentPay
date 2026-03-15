# Ecosystem Alignment

> How AgentPay maps to the Filecoin Onchain Cloud agent ecosystem and PL Genesis programme.

---

## Filecoin Agents RFS Alignment

The [Filecoin Agents](https://filecoin.cloud/agents) initiative defines 7 Requests for Startups (RFS) for AI-native infrastructure. AgentPay directly addresses 4 of them and provides foundational components for 2 more.

### Direct Alignment

| RFS | Title | AgentPay Component | Status |
|-----|-------|-------------------|--------|
| **RFS-3** | Agent Reputation & Portable Identity | `reputation/` — 4-factor trust scoring, `reporting/` — hash-chained signed receipt audit trail, GossipSub broadcast for cross-agent verification | **Complete** |
| **RFS-5** | Fee-Gated Agent Communication Protocol | `protocol/` — libp2p P2P streams (no central relay), `gateway/` — x402 payment verification, `payments/` — Filecoin-style cumulative vouchers | **Complete** |
| **RFS-7** | Agent-Generated Data Marketplace | `pricing/` — dynamic pricing with trust discounts + congestion premiums, `discovery/` — capability registry with Bazaar-compatible format | **Complete** |
| **RFS-4** | Autonomous Agent Economy Testbed | `scripts/dev.sh` — multi-agent simulation, dashboard simulation tab — batch payments, topology control, success rate tracking | **Complete** |

### Partial Alignment (Roadmap)

| RFS | Title | Gap | Path Forward |
|-----|-------|-----|-------------|
| **RFS-2** | Onchain Agent Registry | AgentPay uses GossipSub-based registry, not ERC-8004 | Add ERC-8004 agent identity + on-chain registry on FVM |
| **RFS-1** | Agentic Storage SDK | No storage integration | Add IPFS/Filecoin storage for receipts, reputation snapshots |
| **RFS-6** | Autonomous Infrastructure Brokerage | SLA negotiation exists but not storage procurement | Extend negotiation protocol for storage deals |

---

## Core Architecture Alignment

### Payment Channel Pattern (Filecoin-derived)

AgentPay implements the same payment channel pattern used by Filecoin:

- **Cumulative vouchers** — each voucher replaces the previous one (not incremental)
- **Single on-chain settlement** — lock funds once, exchange vouchers off-chain, settle once
- **ECDSA signatures** — vouchers are signed with secp256k1 and verified via `ecrecover`
- **Challenge period** — on-chain dispute window before final withdrawal

This is documented in [ARCHITECTURE.md](ARCHITECTURE.md) sections 4-6.

### Provable Behavioral History (RFS-3)

AgentPay's receipt chain system directly addresses RFS-3's requirement for "tamper-resistant, long-lived reputation anchored to provable behavioral history":

```
Receipt #0 → Receipt #1 → Receipt #2 → ... → Receipt #N
  (genesis)     SHA-256       SHA-256              SHA-256
  prev=0x00     prev=H(#0)    prev=H(#1)          prev=H(#N-1)
```

- Each receipt is EIP-191 signed by the sender
- Receipts are hash-chained (SHA-256) — tampering breaks the chain
- Broadcast on GossipSub `/agentic/receipts/1.0.0` for cross-agent verification
- `ReceiptStore.verify_chain()` validates full integrity

### Fee-Gated Communication (RFS-5)

The x402 gateway implements the server-side x402 payment protocol:

1. Client requests a gated resource
2. Server responds with `402 Payment Required` + pricing metadata (price, payment types, wallet)
3. Client submits payment proof (channel ID, voucher nonce, amount)
4. Server verifies payment against channel state and grants access

This is fully enforced — not just advertised.

### Dynamic Pricing (RFS-7)

The pricing engine computes per-request prices:

```
multiplier = 1.0 - (discount * trust_score) + (premium * congestion_ratio)
final_price = max(base_price * multiplier, floor)
```

- Higher trust → larger discount (configurable up to 30%)
- More active channels → congestion premium (up to 50%)
- Floor and ceiling prices enforced
- Integrated with negotiation protocol for SLA-based pricing

---

## Bazaar / x402 Compatibility

AgentPay exports agent capabilities in the Algorand x402 Bazaar-compatible format:

```json
{
  "provider": {
    "id": "<peer_id>",
    "wallet": "<eth_address>",
    "protocol": "agentpay"
  },
  "resources": [
    {
      "path": "/api/v1/inference",
      "price": 1000,
      "description": "LLM inference",
      "payment_types": ["payment-channel"],
      "x402_compatible": false,
      "min_trust_score": 0.0
    }
  ]
}
```

This format is used by:
- `GET /gateway/resources` — list gated resources
- `GET /discovery/resources` — list agent capabilities
- GossipSub `/agentic/capabilities/1.0.0` — network-wide discovery

---

## Multi-Chain Settlement

| Chain | Contract | Status | Token |
|-------|---------|--------|-------|
| **Ethereum** | `PaymentChannel.sol` (Solidity ^0.8) | Production | ETH + ERC-20 |
| **Algorand** | ARC-4 application + box storage | Production | ALGO |
| **Filecoin** | FVM deployment (planned) | Roadmap | FIL |

The settlement layer is chain-agnostic by design (`chain/protocols.py` defines `WalletProtocol` and `SettlementProtocol` interfaces). Adding Filecoin requires implementing these interfaces for FVM.

---

## PL Genesis Hackathon

AgentPay fits the **Existing Code** track ($5,000 per team, 10 teams):

- **Timeline**: Hacking Feb 10 – Mar 31, 2026
- **Track**: AI/AGI & Robotics + Crypto & Economic Systems
- **Deliverables**: Working code, 2-minute demo, live interactive examples

### Demo Path

1. Start multi-agent network via `./scripts/dev.sh`
2. Agents auto-discover via mDNS, exchange capabilities on GossipSub
3. Open payment channels, exchange micropayments
4. Show trust scores updating, dynamic pricing adapting
5. Demonstrate x402 gateway access with payment verification
6. Show hash-chained receipt audit trail
7. Settle on Ethereum (or Algorand)

### Automated Demo

Run `./scripts/demo.sh` for a 9-phase automated API demo covering discovery, channels, micropayments, receipts, negotiation, trust, pricing, SLA, and disputes.

---

## Diagrams

10 Excalidraw diagrams document the full architecture. See [ARCHITECTURE.md § 22](ARCHITECTURE.md#22-diagrams) for the complete list.

Key diagrams for ecosystem alignment:
- **Trust Architecture** — reputation, SLA, disputes, policies, pricing interactions
- **Receipt Chain** — hash-chained signed receipts with GossipSub broadcast
- **Settlement Flows** — Ethereum vs Algorand comparison
- **HTLC Multi-Hop Routing** — multi-hop payment via intermediaries
