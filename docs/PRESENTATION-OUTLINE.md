# Presentation Outline

> Slide-by-slide outline for a 10–15 minute conference talk or hackathon presentation.
> Adapt length by skipping or expanding sections marked with *(optional)*.

---

## Slide 1 — Title

**AgentPay**
Decentralized P2P Micropayment Channels for Autonomous AI Agents

Yash K. Saini
github.com/yashksaini-coder/AgentPay

---

## Slide 2 — The Agent Economy

- AI agents are becoming autonomous workers
- They browse, research, code, analyze — and increasingly **transact**
- Agents need to pay for: compute, data, API calls, other agents' services
- The missing piece: **a native payment layer for agent-to-agent transactions**

---

## Slide 3 — Why Current Solutions Fail

| Approach | Problem |
|----------|---------|
| On-chain per tx | $0.50–$50 per transaction, 15s+ latency, doesn't scale to micropayments |
| Centralized APIs (Stripe) | Trust required, KYC, rate limits, single point of failure |
| Subscriptions | Don't work for ephemeral, untrusted agents |
| Custodial wallets | Counterparty risk, centralized control |

**Need**: Sub-second, near-zero cost, trustless, peer-to-peer

---

## Slide 4 — Payment Channels (The Primitive)

```
Lock funds once → Exchange signatures off-chain × 1000s → Settle once
```

- Same idea as Bitcoin Lightning, Filecoin payment channels, Ethereum state channels
- Only 2 on-chain transactions regardless of payment count
- Cryptographic security: ECDSA signed vouchers, on-chain dispute resolution
- Used in production by networks handling billions in volume

---

## Slide 5 — AgentPay Architecture

**Show**: `docs/images/system-architecture.png`

- Two agent nodes communicating over libp2p
- Each node: Identity (Ed25519) + Wallet (secp256k1) + Channel Manager
- libp2p provides: TCP/WS transport, Noise encryption, Yamux muxing, mDNS discovery, GossipSub
- REST API + Next.js dashboard for external access
- Ethereum smart contract for settlement

---

## Slide 6 — The Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Runtime | Python 3.12 + Trio | Structured concurrency, py-libp2p native |
| Networking | libp2p | P2P-native, no servers, battle-tested |
| Payments | Cumulative vouchers | One signature settles everything |
| Settlement | Solidity on Ethereum | Programmable, composable, widely adopted |
| Frontend | Next.js 15 | Fast, modern, great DX |

---

## Slide 7 — How Discovery Works

1. Agent starts → broadcasts on mDNS (zeroconf)
2. Other agents on the LAN detect the broadcast automatically
3. PeerIDs + ETH addresses exchanged via GossipSub `/agentic/discovery/1.0.0`
4. No registry, no DNS, no config — just turn on and find peers

*(optional)* For WAN: replace mDNS with Kademlia DHT or direct multiaddr connections

---

## Slide 8 — Payment Protocol Deep Dive

**Show**: `docs/images/payment-channel-lifecycle.png`

1. **Open**: `PaymentOpen` message → counterparty ACKs → channel ACTIVE
2. **Pay**: `PaymentUpdate(nonce, cumulative_amount, signature)` → verify → ACK
3. **Close**: `PaymentClose(final_nonce, final_amount)` → cooperative ACK
4. **Settle**: Final voucher submitted on-chain → challenge period → withdraw

Wire format: 4-byte length prefix + msgpack payload over libp2p streams

---

## Slide 9 — Voucher Design

```
Voucher n=1: amount=0.1 ETH   (total paid: 0.1)
Voucher n=2: amount=0.3 ETH   (total paid: 0.3, not 0.2 more)
Voucher n=3: amount=0.6 ETH   (total paid: 0.6)
                                ↑ Only this one goes on-chain
```

**Cumulative, not incremental** — same as Filecoin:
- Receiver stores only the latest voucher
- One signature verification on-chain
- Nonce prevents replay, amount cap prevents overpayment

---

## Slide 10 — Channel State Machine

**Show**: `docs/images/state-machine.png`

- 6 states: PROPOSED → OPEN → ACTIVE → CLOSING → DISPUTED → SETTLED
- Fraud protection: challenge period lets sender dispute with higher-nonce voucher
- Happy path: PROPOSED → ACTIVE → CLOSING → SETTLED (no disputes)

---

## Slide 11 — Smart Contract

`PaymentChannel.sol` — 4 functions:

| Function | Purpose |
|----------|---------|
| `openChannel()` | Lock deposit, create channel |
| `closeChannel()` | Submit final voucher, start challenge |
| `challengeClose()` | Submit higher-nonce voucher (fraud proof) |
| `withdraw()` | Distribute funds after challenge expires |

Signature compatible: same hash computation in Python and Solidity (EIP-191)

---

## Slide 12 — Live Demo

> Switch to terminal / browser

**Demo flow** (pick one):
- **Terminal demo**: Start agents → curl open channel → send payments → check balance *(2 min)*
- **Dashboard demo**: Start agents → open browser → open channel → click payments *(2 min)*
- **Full stack**: Add Docker Anvil, show on-chain settlement *(4 min)*

See [DEMO-WALKTHROUGH.md](DEMO-WALKTHROUGH.md) for exact commands.

---

## Slide 13 — Testing & Quality

- **63 tests** across 7 test files (pytest-trio)
- Protocol codec, channel state machine, voucher crypto, REST API, integration
- Ruff lint + format: zero violations
- Typed with Pydantic settings

```
test_api.py          24 tests   REST endpoints, CORS, error handling
test_protocol.py     13 tests   Message codec, framing, wire validation
test_channel.py      12 tests   State machine, voucher application
test_voucher.py       4 tests   Signing, verification, serialization
test_node.py          4 tests   Identity generation, persistence
test_pubsub.py        3 tests   Topic definitions
test_integration.py   3 tests   End-to-end channel lifecycle
```

---

## Slide 14 — Use Cases

1. **Pay-per-query AI services** — Agent charges per inference request
2. **Data marketplaces** — Pay per record/row/document retrieved
3. **Multi-agent workflows** — Coordinator pays specialist agents per task
4. **Decentralized compute** — Pay per token generated, per GPU-second used
5. **Content licensing** — Agents pay for access to copyrighted material

---

## Slide 15 — Future Work *(optional)*

- [ ] Multi-hop payment routing (agent relay networks)
- [ ] ERC-20 token support (not just native ETH)
- [ ] Kademlia DHT for WAN peer discovery
- [ ] Bidirectional payment channels
- [ ] Agent reputation system (based on payment history on GossipSub)
- [ ] WASM-compatible for browser-native agents
- [ ] L2 settlement (Optimism, Arbitrum, Base) for cheaper on-chain ops

---

## Slide 16 — Closing

**AgentPay** — giving AI agents a native way to pay each other.

- Open source, MIT licensed
- 63 tests, clean architecture, full documentation
- Built on battle-tested primitives: libp2p, Ethereum, payment channels

**Links**:
- GitHub: github.com/yashksaini-coder/AgentPay
- Docs: Architecture, CLI Reference, Demo Walkthrough

**Contact**:
- GitHub: @yashksaini-coder
- LinkedIn: /in/yashksaini
- Twitter: @0xCracked_dev

---

## Speaker Notes

### Timing Guide (15 min talk)

| Slides | Duration | Content |
|--------|----------|---------|
| 1–3 | 2 min | Problem framing |
| 4–6 | 2 min | Solution + stack |
| 7–10 | 3 min | Technical deep dive |
| 11 | 1 min | Smart contract |
| 12 | 3 min | Live demo |
| 13–14 | 2 min | Quality + use cases |
| 15–16 | 2 min | Future + close |

### For 5-min hackathon pitch
Use slides: 1, 3, 5, 8, 12, 16 (cut deep dive, focus on demo)

### For 30-min workshop
Expand demo section to include audience following along on their own machines.
