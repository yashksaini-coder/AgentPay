---
title: Architecture
layout: default
nav_order: 2
---

# Architecture

> Decentralized off-chain payment channels between autonomous AI agents over libp2p + Ethereum/Algorand/Filecoin.

---

## 1. System Overview

This system implements **off-chain payment channels** between autonomous AI agents communicating over **libp2p**. The design follows the same pattern used by Filecoin payment channels and Ethereum state channels: lock funds on-chain once, exchange signed vouchers off-chain many times, settle on-chain once.

The core insight is that agent-to-agent micropayments need sub-second latency and near-zero marginal cost per transaction. On-chain transactions are too slow and expensive for per-request payments. Payment channels solve this by moving the payment loop off-chain while preserving the security guarantees of the underlying blockchain.

![System Architecture]({{ site.baseurl }}/assets/images/system-architecture.png)
*System Architecture — Agent nodes, libp2p networking, and Ethereum settlement*

---

## 2. Networking Layer

### 2.1 Host Configuration

The libp2p host is created via `libp2p.new_host()` with:

- **Key pair**: Ed25519 (generated or loaded from disk)
- **Muxer**: Yamux (preferred over mplex for better flow control)
- **Security**: Noise protocol (authenticated encryption, no TLS certificates needed)
- **Discovery**: mDNS via `enable_mDNS=True` (zeroconf broadcast on LAN)
- **Transports**: TCP (default), WebSocket (optional, for browser clients)

```python
# agent_node.py — host creation
self.host = new_host(
    key_pair=key_pair,
    muxer_preference="YAMUX",
    enable_mDNS=self.config.node.enable_mdns,
)
```

The host listens on configurable TCP and WebSocket ports. Multiaddrs are advertised with the `/p2p/<peer_id>` suffix for direct dialing.

### 2.2 Stream Protocol

The custom payment protocol is registered as `/agentic-payments/1.0.0` on the libp2p host. When a remote peer opens a stream, multistream-select negotiates the protocol, then the `PaymentProtocolHandler` takes over.

Streams are **bidirectional byte pipes** multiplexed over Yamux. Multiple concurrent streams can exist between the same two peers without opening additional TCP connections.

### 2.3 Peer Discovery

Discovery has three sources, merged into a unified view:

1. **mDNS** — Automatic LAN discovery. The host's `enable_mDNS=True` flag uses zeroconf to broadcast and listen.
2. **Connected peers** — The host tracks all active connections. `host.get_connected_peers()` returns live peer IDs.
3. **Manual connections** — CLI `peer connect <multiaddr>` adds peers directly via `host.connect()`.

### 2.4 GossipSub Pubsub

Four topics for coordination:

| Topic | Purpose |
|-------|---------|
| `/agentic/discovery/1.0.0` | Agent announcements (peer_id, eth_address, listen addrs) |
| `/agentic/capabilities/1.0.0` | Service advertisements and pricing |
| `/agentic/channels/1.0.0` | Channel announcements for network routing topology |
| `/agentic/receipts/1.0.0` | Payment receipts for transparency/auditing |

GossipSub is configured with `degree=8`, `degree_low=6`, `degree_high=12`, `heartbeat_interval=120s`, and `strict_signing=True`.

---

## 3. Wire Protocol

### 3.1 Framing

Every message on a payment protocol stream uses length-prefix framing:

```
┌──────────────────┬──────────────────────────┐
│  4 bytes         │  N bytes                 │
│  big-endian uint │  msgpack payload         │
│  (payload length)│                          │
└──────────────────┴──────────────────────────┘
```

Maximum message size: **1 MB**.

### 3.2 Message Types

| Type | ID | Fields |
|------|:--:|--------|
| `PAYMENT_OPEN` | 1 | `channel_id`, `sender`, `receiver`, `total_deposit`, `nonce`, `timestamp`, `signature` |
| `PAYMENT_UPDATE` | 2 | `channel_id`, `nonce`, `amount` (cumulative), `timestamp`, `signature` |
| `PAYMENT_CLOSE` | 3 | `channel_id`, `final_nonce`, `final_amount`, `cooperative`, `timestamp`, `signature` |
| `PAYMENT_ACK` | 4 | `channel_id`, `nonce`, `status`, `reason` |
| `HTLC_PROPOSE` | 5 | `channel_id`, `payment_hash`, `amount`, `timeout`, `hop_count` |
| `HTLC_FULFILL` | 6 | `channel_id`, `payment_hash`, `preimage` |
| `HTLC_CANCEL` | 7 | `channel_id`, `payment_hash`, `reason` |
| `CHANNEL_ANNOUNCE` | 8 | `channel_id`, `peer_a`, `peer_b`, `capacity` |
| `NEGOTIATE_PROPOSE` | 9 | `negotiation_id`, `service_type`, `proposed_price`, `channel_deposit`, `timeout` |
| `NEGOTIATE_COUNTER` | 10 | `negotiation_id`, `counter_price` |
| `NEGOTIATE_ACCEPT` | 11 | `negotiation_id` |
| `NEGOTIATE_REJECT` | 12 | `negotiation_id`, `reason` |
| `ERROR` | 15 | `code`, `message` |

![Wire Protocol]({{ site.baseurl }}/assets/images/wire-protocol.png)
*All 13 message types with fields and framing format*

---

## 4. Payment Channel Design

### 4.1 Channel State Machine

![Payment Channel State Machine]({{ site.baseurl }}/assets/images/state-machine.png)
*Payment Channel State Machine — lifecycle of a single payment channel*

**Transitions:**

| From | To | Trigger | Description |
|------|----|---------|-------------|
| `PROPOSED` | `OPEN` | `accept()` | Counterparty accepts the channel open proposal |
| `OPEN` | `ACTIVE` | `activate()` | On-chain deposit confirmed |
| `ACTIVE` | `ACTIVE` | `apply_voucher()` | Micropayment voucher exchange loop |
| `ACTIVE` | `CLOSING` | `request_close()` | Either party initiates close |
| `ACTIVE`/`CLOSING` | `DISPUTED` | `dispute()` | Fraud detected or disagreement |
| `CLOSING`/`DISPUTED` | `SETTLED` | `settle()` | On-chain settlement confirmed |

### 4.2 Voucher Design (Filecoin-style)

Vouchers use **cumulative amounts**, not incremental. Each new voucher replaces the previous one.

```
Voucher n=1: amount=100    (paid 100 total)
Voucher n=2: amount=250    (paid 250 total, not 150 more)
Voucher n=3: amount=400    (paid 400 total)
                            ▲
                            └── Only this one needed for settlement
```

**Signature scheme:**

```
hash = keccak256(abi.encodePacked(channel_id, nonce, amount, timestamp))
signature = EIP-191 personal_sign(hash, sender_private_key)
```

### 4.3 Voucher Validation Rules

1. Channel must be in `ACTIVE` state
2. `voucher.nonce > channel.nonce` (strictly increasing)
3. `voucher.amount > channel.total_paid` (strictly increasing cumulative amount)
4. `voucher.amount <= channel.total_deposit` (cannot exceed locked funds)
5. Signature must recover to the channel sender's Ethereum address

---

## 5. On-Chain Settlement

### Smart Contract

The `PaymentChannel.sol` contract implements unidirectional payment channels with a challenge period:

| Function | Who calls | What it does |
|----------|-----------|--------------|
| `openChannel()` | Sender | Deposits ETH, creates channel struct |
| `closeChannel()` | Receiver | Verifies ECDSA signature, starts challenge period |
| `challengeClose()` | Anyone | Submits higher-nonce voucher, resets challenge timer |
| `withdraw()` | Either | After challenge expiry: receiver gets amount, sender gets refund |

### Signature Compatibility

The voucher hash is computed identically off-chain and on-chain:

```solidity
// Solidity
keccak256(abi.encodePacked(channelId, nonce, amount, timestamp))
```

```python
# Python
Web3.solidity_keccak(
    ["bytes32", "uint256", "uint256", "uint256"],
    [channel_id, nonce, amount, timestamp],
)
```

---

## 6. Payment Flow (End-to-End)

![Payment Channel Lifecycle]({{ site.baseurl }}/assets/images/payment-channel-lifecycle.png)
*Payment Channel Lifecycle — open, pay, close, settle*

---

## 7. API Layer

The REST API runs on Quart-Trio served by Hypercorn with ~50 endpoints across 10 groups. See [CLI & API Reference]({{ site.baseurl }}/commands) for the full endpoint list.

---

## 8. Identity and Cryptography

| Key System | Curve | Purpose | Storage |
|------------|-------|---------|---------|
| **libp2p Identity** | Ed25519 | Peer identification, Noise handshake | `~/.agentic-payments/identity.key` |
| **Ethereum Wallet** | secp256k1 | Voucher signing (ECDSA), on-chain transactions | Generated fresh per session |

---

## 9. Multi-Hop Routing (HTLC)

![HTLC Multi-Hop Routing]({{ site.baseurl }}/assets/images/htlc-routing.png)
*Multi-hop payment via intermediaries with reputation-weighted BFS pathfinding*

The pathfinder uses reputation-weighted Dijkstra. Each hop's HTLC timeout decrements by 120 seconds, ensuring the sender's lock expires last.

---

## 10. Trust Architecture

![Trust Architecture]({{ site.baseurl }}/assets/images/trust-architecture.png)
*Reputation, SLA monitoring, disputes, policies, and pricing interactions*

### Reputation Scoring

```
trust_score = 0.4 * success_rate + 0.3 * normalized_volume + 0.2 * response_speed + 0.1 * longevity
```

### Dynamic Pricing

```
final_price = base_price * (1 - trust_discount) * (1 + congestion_premium)
```

### Receipt Chains

Every payment produces a `SignedReceipt` forming a hash chain per channel, broadcast via GossipSub for network-wide verification.

---

## 11. ERC-8004 Agent Identity

![ERC-8004 Identity Flow]({{ site.baseurl }}/assets/images/erc8004-identity-flow.png)
*Agent registration, identity bridge, reputation sync*

The `IdentityBridge` maps the node's libp2p PeerID + ETH wallet to an ERC-8004 `agentId` (ERC-721 token), enabling cross-chain identity portability and on-chain reputation tracking.

---

## 12. Multi-Chain Settlement

| Chain | Contract | Status |
|-------|---------|--------|
| **Ethereum** | `PaymentChannel.sol` (Solidity ^0.8) | Implemented |
| **Algorand** | ARC-4 application + box storage | Implemented |
| **Filecoin** | Same `PaymentChannel.sol` on FEVM | Implemented |

The settlement layer is chain-agnostic by design. Each chain implements `SettlementProtocol` independently.

---

## 13. Diagrams

| Diagram | Description |
|---------|-------------|
| [System Architecture]({{ site.baseurl }}/assets/images/system-architecture.png) | Full system with all subsystems |
| [Payment Channel Lifecycle]({{ site.baseurl }}/assets/images/payment-channel-lifecycle.png) | 8-step sequence: open, payments, close, settle |
| [Channel State Machine]({{ site.baseurl }}/assets/images/state-machine.png) | 6-state lifecycle |
| [Negotiation Flow]({{ site.baseurl }}/assets/images/negotiation-flow.png) | Discovery → negotiate → open → pay → close |
| [Trust Architecture]({{ site.baseurl }}/assets/images/trust-architecture.png) | Reputation, SLA, disputes, policies |
| [Module Architecture]({{ site.baseurl }}/assets/images/module-architecture.png) | Code module dependencies |
| [Wire Protocol]({{ site.baseurl }}/assets/images/wire-protocol.png) | All 13 message types |
| [HTLC Routing]({{ site.baseurl }}/assets/images/htlc-routing.png) | Multi-hop payment via intermediaries |
| [ERC-8004 Identity]({{ site.baseurl }}/assets/images/erc8004-identity-flow.png) | Agent registration and reputation sync |
| [IPFS Storage]({{ site.baseurl }}/assets/images/ipfs-storage-flow.png) | Receipt pinning and retrieval |
| [E2E Code Flow]({{ site.baseurl }}/assets/images/e2e-code-flow.png) | CLI → node → libp2p → payment → settlement |
