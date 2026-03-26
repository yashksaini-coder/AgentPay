# AgentPay Deep Dive: How We Built a Payment Protocol for Autonomous AI Agents

*A technical deep-dive into AgentPay — from problem statement to architecture decisions, real code, and a working demo. 680 tests, 55 modules, 3 settlement chains, zero middlemen.*

**Reading time: ~17 minutes**

---

## TL;DR

AgentPay is a decentralized micropayment protocol built on [libp2p](https://libp2p.io/) that lets AI agents discover each other, negotiate service terms, exchange off-chain payments in sub-millisecond, and settle on Ethereum, Algorand, or Filecoin. It uses Filecoin-style cumulative vouchers, HTLC multi-hop routing, a 4-factor trust scoring system, and an autonomous agent runtime that handles the full payment lifecycle without human intervention. Two on-chain transactions settle thousands of micropayments. The [code is open source](https://github.com/yashksaini-coder/AgentPay).

---

## The Scenario That Started Everything

Imagine this: Agent A is a coordinator managing a research pipeline. It needs to farm out 500 document summarization tasks to the cheapest available GPU inference providers on the network. Agent B offers inference at 0.001 ETH per request with a 200ms latency SLA. Agent C offers the same service at 0.0008 ETH but has a patchy track record — 15% of its responses arrive late.

Agent A needs to answer three questions before spending a single wei:

1. **Who can I pay?** (Discovery)
2. **Can I trust them?** (Reputation)
3. **How do I pay 500 times without going bankrupt on gas?** (Payment channels)

Today, none of the existing infrastructure answers all three. On-chain transactions cost $0.50–$50 each. Stripe requires KYC, human approval, and can't handle 500 micropayments per minute. Credit models don't work when agents are ephemeral and untrusted.

We built AgentPay because autonomous agents need an economic layer that matches their nature — peer-to-peer, instant, trustless, and fully automated.

![Interconnected network of autonomous agents transacting with each other](https://images.unsplash.com/photo-1639322537228-f710d846310a?w=900&q=80)
*The agent economy is forming. The missing piece is the payment layer.*

---

## Why Existing Solutions Fail

Before diving into what we built, it's worth understanding why this problem is harder than it looks.

### The Per-Transaction Trap

The naive approach is to pay on-chain for every request. Here's the math for Agent A's 500-task pipeline on Ethereum:

| Metric | Value |
|--------|-------|
| Tasks | 500 |
| Gas per tx (ERC-20 transfer) | ~65,000 |
| Gas price (20 gwei) | 0.0013 ETH per tx |
| **Total gas cost** | **0.65 ETH (~$1,600)** |
| Confirmation time per tx | ~15 seconds |
| **Total wait time** | **2+ hours (sequential)** |

The payment overhead exceeds the service cost. And that's just Ethereum — Algorand is cheaper per-tx but still requires one transaction per payment.

### The Centralized API Trap

Stripe Connect, PayPal, and similar platforms solve the payment problem for humans. They fail for agents because:

- **Identity**: Agents don't have passports. KYC is a non-starter.
- **Latency**: API calls take 200-500ms. Agents making 1,000 requests per minute can't wait.
- **Rate limits**: Most payment APIs cap at ~100 requests/second. Agent workloads burst.
- **Trust model**: Centralized platforms are a single point of failure. If Stripe goes down, the entire agent economy halts.

### The x402 Gap

The [x402 protocol](https://www.x402.org/) is the closest existing standard — it uses HTTP 402 "Payment Required" to gate resources behind payment proofs. It's elegant for one-shot requests. But it doesn't solve the persistent relationship problem: when Agent A and Agent B will transact 10,000 times over the next hour, x402 requires a separate payment proof per request. There's no concept of a channel, no negotiation, no SLA tracking, no reputation.

AgentPay bridges this gap. We implement x402 for one-shot payments *and* provide persistent payment channels for high-frequency agent relationships.

---

## Architecture: Six Layers, One Protocol

AgentPay is designed as six independent layers. Each can be tested, replaced, or extended without affecting the others. This isn't accidental — it's the result of building a protocol that needs to survive in production where any component might fail.

![AgentPay system architecture showing all six layers](images/system-architecture.png)
*System architecture — networking, wire protocol, payment channels, settlement, identity, and trust. Each layer communicates through well-defined interfaces.*

![Module dependency map across interface, core, network, and settlement layers](images/module-architecture.png)
*55 source modules across 19 packages. The dependency arrows only point downward — no circular dependencies.*

Let's walk through each layer with the actual code.

### Layer 1: Networking — Why libp2p, Not HTTP

The first decision was the transport layer. HTTP is the obvious choice for most APIs. We rejected it for a specific reason: **agents shouldn't need servers**.

With HTTP, someone has to host an endpoint. That means DNS, TLS certificates, load balancers, and a fixed IP address. Agents are ephemeral — they spin up in a container, do work, and disappear. They need a protocol where every participant is both a client and a server, where discovery is automatic, and where connections are multiplexed.

[libp2p](https://github.com/libp2p/py-libp2p) gives us all of that:

- **TCP + WebSocket transports** — agents connect from anywhere
- **Noise encryption** — every connection is authenticated and encrypted
- **Yamux multiplexing** — multiple concurrent payment streams over one TCP connection
- **mDNS discovery** — agents on the same LAN find each other automatically
- **GossipSub pubsub** — network-wide message broadcast for capabilities, receipts, and reputation

Our custom stream protocol registers as `/agentic-payments/1.0.0`. Every message is length-prefixed (4-byte big-endian header) and encoded with [msgpack](https://msgpack.org/) — a compact binary format that's 30-50% smaller than JSON and faster to parse.

![Wire protocol showing all 13 message types with fields and framing format](images/wire-protocol.png)
*13 message types cover the complete payment lifecycle: channel management, voucher exchange, HTLC routing, negotiation, and error handling.*

### Layer 2: Payment Channels — Filecoin's Voucher Model

The core insight of payment channels: lock funds on-chain once, then exchange signed IOUs off-chain. Only the final IOU goes on-chain for settlement. This is the same pattern used by [Bitcoin Lightning](https://lightning.network/) and [Filecoin's payment channel actor](https://spec.filecoin.io/systems/filecoin_token/payment_channels/).

We chose Filecoin's **cumulative voucher** model over Lightning's **commitment transaction** model. The difference matters:

| | Cumulative (Filecoin/AgentPay) | Commitment (Lightning) |
|---|---|---|
| Each payment | New voucher replaces previous | New commitment tx invalidates previous |
| Settlement | Submit latest voucher | Submit latest commitment |
| State to store | 1 voucher (the latest) | All prior commitments (for fraud proofs) |
| Complexity | Lower | Higher (penalty txs, watchtowers) |

Here's the actual voucher dataclass from our codebase:

```python
# src/agentic_payments/payments/voucher.py
@dataclass(frozen=True)
class SignedVoucher:
    channel_id: bytes     # 32-byte channel identifier
    nonce: int            # Monotonically increasing per channel
    amount: int           # Cumulative wei — NOT incremental
    timestamp: int        # Unix timestamp for replay protection
    signature: bytes      # ECDSA over keccak256(abi.encodePacked(...))
    task_id: str = ""     # Correlate payment to specific work request
```

The `amount` field is cumulative. If Agent A sends voucher #1 for 1,000 wei, then voucher #2 for 3,000 wei, Agent B can submit voucher #2 to claim 3,000 wei total. Voucher #1 is irrelevant. This means:

- **No double-spend risk** — nonces are monotonically increasing; the contract rejects out-of-order vouchers
- **Minimal on-chain data** — only the latest voucher is submitted
- **One signature check** — `ecrecover` on-chain verifies the sender
- **Task correlation** — the `task_id` field ties payments to specific work requests for auditing

The most interesting design decision is in `send_payment`: we send the voucher to the peer *first*, then commit locally only on success. This prevents the channel from getting "wedged" — where the local state advances but the peer never received the voucher.

```python
# src/agentic_payments/payments/manager.py — send_payment (simplified)
async with lock:
    channel = self.get_channel(channel_id)
    voucher = SignedVoucher.create(channel_id, new_nonce, new_total, private_key)

    # Send FIRST — if this fails, channel state is unchanged
    await send_fn(PaymentUpdate(...))

    # Commit locally ONLY after peer acknowledged
    channel.apply_voucher(voucher)
```

This pattern — send before commit — is the opposite of what most database-backed systems do. We chose it because a lost-in-flight voucher is recoverable (just resend), but a committed-but-unsent voucher creates a permanent state divergence between the two agents.

### Layer 3: The Channel State Machine

Every payment channel follows a 6-state lifecycle with a challenge period for dispute resolution:

![Channel state machine with 6 states and transitions](images/state-machine.png)
*PROPOSED → OPEN → ACTIVE → CLOSING → SETTLED, with a DISPUTED branch for challenge periods*

The key security property is the **challenge period**. When one party initiates a close, the other party has a configurable window (default: 1 hour) to dispute with a higher-nonce voucher. This prevents the attack where a sender closes a channel with an old voucher, trying to reclaim funds they already spent.

```python
# src/agentic_payments/payments/channel.py
def dispute(self, voucher: SignedVoucher | None = None) -> None:
    """Only allowed from CLOSING state — submits a higher-nonce voucher."""
    self._transition({ChannelState.CLOSING}, ChannelState.DISPUTED)

    if voucher is not None:
        if voucher.nonce <= self.closing_nonce:
            raise ChannelError("Dispute voucher nonce must exceed closing nonce")
        self.closing_nonce = voucher.nonce
        self.closing_amount = voucher.amount

    # Reset challenge period — gives both parties time to respond
    self.close_expiration = int(time.time()) + self.challenge_period
```

For cooperative closes (both parties agree), we skip the challenge period entirely by setting `close_expiration = 0`, allowing immediate settlement.

### Layer 4: Multi-Hop Routing (HTLC)

Not every pair of agents has a direct channel. AgentPay supports **Hash Time-Locked Contract (HTLC)** multi-hop routing — the same primitive that powers Lightning Network.

![HTLC multi-hop routing via intermediaries](images/htlc-routing.png)
*Agent A pays Agent C through Agent B. Each hop has a decrementing timeout — the sender's lock expires last.*

The pathfinder uses a reputation-weighted Dijkstra algorithm. Instead of shortest-path-by-hops, it finds the cheapest path where "cost" is `1 - trust_score`. Highly trusted intermediaries are preferred even if they add an extra hop.

```python
# src/agentic_payments/routing/pathfinder.py
trust = reputation_fn(neighbor)
edge_cost = 1.0 - trust      # lower cost = higher trust
new_cost = cost + edge_cost

if neighbor in best_cost and best_cost[neighbor] < new_cost:
    continue  # Already found a better path to this neighbor
```

Each hop's HTLC timeout decrements by 120 seconds, ensuring the sender's lock expires last. This means if an intermediate node goes offline, the sender gets their funds back — the atomic guarantee holds even across untrusted intermediaries.

---

## The Trust Layer: Why Payment Channels Alone Aren't Enough

Here's the insight that separates AgentPay from a pure payment channel implementation: **payments without trust infrastructure are useless for autonomous agents**.

When a human pays for a service, they can read reviews, check a company's reputation, and sue if things go wrong. Agents have none of these affordances. They need programmatic trust.

![Trust architecture showing reputation, SLA, disputes, policies, and pricing](images/trust-architecture.png)
*The trust layer ties together five subsystems: reputation scoring, SLA monitoring, dispute detection, wallet policies, and dynamic pricing.*

### Reputation: A 4-Factor Trust Score

Every peer relationship has a trust score from 0.0 to 1.0, computed from four weighted factors:

```python
# src/agentic_payments/reputation/tracker.py
def trust_score(self) -> float:
    """0.4*success + 0.3*volume + 0.2*speed + 0.1*longevity"""
    success = self.success_rate               # payments_sent / (sent + failed)
    volume = min(self.total_volume / 1e18, 1.0)  # log-normalized
    speed = min(0.1 / max(self.avg_response_time, 0.01), 1.0)
    longevity = min((time.time() - self.first_seen) / 86400, 1.0)  # 1 day = max
    return 0.4 * success + 0.3 * volume + 0.2 * speed + 0.1 * longevity
```

Trust scores feed into two downstream systems:

**Dynamic pricing** — the pricing engine adjusts quotes based on trust. A peer with 90% trust might get a 15% discount. An unknown peer pays full price. This creates a virtuous cycle: reliable behavior builds trust, which lowers costs, which attracts more business.

**GossipSub peer scoring** — unreliable peers are deprioritized for message relay by the pubsub layer. Their discovery advertisements propagate slower, their reputation updates get fewer witnesses, and their network position naturally degrades. Trust isn't just a number — it affects how the network treats you.

### SLA Monitoring and Disputes

Each channel tracks whether the service provider meets their promised SLA — latency thresholds, error rates, availability windows. Violations are recorded with timestamps and evidence. When violations exceed a configurable threshold, the dispute monitor can automatically file challenges.

The dispute resolution flow ties back to the channel state machine: a dispute submits a higher-nonce voucher during the challenge period, and the reputation system penalizes the offending party regardless of the dispute outcome.

### Receipt Chains: A Mini-Blockchain Per Channel

Every payment generates a signed receipt that is **hash-chained** to the previous one — each receipt includes the SHA-256 hash of the prior receipt. This creates a tamper-resistant audit trail per channel, broadcast via GossipSub for network-wide verification. Any peer can independently verify the complete payment history between two agents without trusting either party.

---

## The Agent Runtime: From Infrastructure to Autonomy

Everything above — channels, vouchers, trust, routing — is infrastructure. The **Agent Runtime** is where AgentPay becomes truly autonomous.

The runtime is a tick-based loop that cycles through pluggable strategies:

```python
# src/agentic_payments/agent/runtime.py
async def run(self, task_status):
    self._running = True
    self._cancel_scope = trio.CancelScope()
    task_status.started()

    try:
        with self._cancel_scope:
            while True:
                await self._tick()          # Build context, run all strategies
                await trio.sleep(self.tick_interval)
    finally:
        self._running = False
```

Three built-in strategies coordinate the complete lifecycle:

**AutonomousNegotiator** — evaluates incoming task requests against configurable policies (max price, min trust score). Auto-accepts, counter-offers (up to 10 rounds, then rejects), or rejects. Role-aware: only activates for worker-type agents.

**CoordinatorBehavior** — the "brain" of a multi-agent workflow. Finds pending tasks, selects the best available worker (trust-weighted), assigns the task, and triggers payment on completion. Only activates when the agent has the coordinator role.

**WorkerBehavior** — picks up assigned tasks, executes them through a pluggable executor interface, and reports results. Respects a configurable concurrency limit.

### End-to-End: What Happens When You Submit a Task

```bash
# Submit a task to the coordinator
curl -X POST http://127.0.0.1:8080/agent/tasks \
  -H "Content-Type: application/json" \
  -d '{"description":"Analyze market data for ETH/USDC","amount":5000}'
```

Here's what happens behind the scenes, in order:

1. **Task created** → stored in the `TaskStore` with status `PENDING`
2. **Coordinator tick fires** → `CoordinatorBehavior` finds the pending task
3. **Worker selection** → queries known peers, filters by role and trust score, picks the best candidate
4. **Task assigned** → status transitions to `ASSIGNED`, `worker_peer_id` set
5. **Worker tick fires** → `WorkerBehavior` sees the assigned task, moves to `EXECUTING`
6. **Executor runs** → the pluggable executor processes the task (echo by default, but could be HTTP call, LLM inference, etc.)
7. **Task completed** → status moves to `COMPLETED`
8. **Payment triggered** → coordinator calls `send_payment` over the existing channel
9. **Trust updated** → reputation tracker records the successful interaction

All of this happens autonomously. No human intervention. The coordinator discovers workers, the negotiator agrees on price, the worker executes, and the payment settles — every tick, every time.

---

## x402: Bridging Channels and HTTP

Not every agent interaction needs a persistent channel. For one-shot API calls, AgentPay implements the [x402 protocol](https://www.x402.org/) with replay protection:

```
Client → GET /api/inference
Server ← 402 Payment Required
         {"accepts": [{"scheme":"exact","network":"base-sepolia","maxAmountRequired":"5000"}]}
Client → POST /gateway/access (with signed payment proof + timestamp)
Server ← 200 OK (resource access granted)
```

The one-shot flow uses EIP-191 signed messages with a 60-second timestamp window to prevent replay attacks. Resources are registered via `POST /gateway/register` with a price, and the gateway verifies proofs before granting access.

This bridges two worlds: channel-based payments for high-frequency relationships, and x402 for sporadic HTTP API access. Agents choose the right model based on their interaction pattern.

---

## Tri-Chain Settlement: One Interface, Three Chains

AgentPay settles on Ethereum, Algorand, and Filecoin FEVM — selectable at startup with `--chain ethereum|algorand|filecoin`. Under the hood, all three implement the same `SettlementProtocol` interface:

```python
# src/agentic_payments/chain/protocols.py
class SettlementProtocol(Protocol):
    async def open_channel_onchain(self, receiver: str, deposit_wei: int, ...) -> tuple[bytes, str]: ...
    async def close_channel_onchain(self, channel_id: bytes, ...) -> str: ...
    async def challenge_close_onchain(self, channel_id: bytes, ...) -> str: ...
    async def withdraw_onchain(self, channel_id: bytes) -> str: ...
```

| Chain | Contract | Why |
|-------|----------|-----|
| **Ethereum** | Solidity `PaymentChannel.sol` | EVM ecosystem, DeFi composability, widest wallet support |
| **Algorand** | ARC-4 app + box storage | [Bazaar protocol](https://github.com/basketprotocol/bazaar) alignment, x402 ecosystem |
| **Filecoin FEVM** | Same Solidity contract | Storage market alignment, f4 address support |

Adding a new chain is four methods. The payment channel logic, trust layer, and agent runtime are completely chain-agnostic.

---

## Identity: Two Key Pairs, One Agent

Every agent has two cryptographic identities:

- **Ed25519** — libp2p PeerID for network authentication (Noise protocol)
- **secp256k1** — Ethereum wallet for payment signing (ECDSA vouchers)

We bind these with [EIP-191](https://eips.ethereum.org/EIPS/eip-191): the Ethereum wallet signs the PeerID, creating a verifiable cryptographic proof that both keys belong to the same agent. Any peer can verify this without an on-chain lookup.

For persistent on-chain identity, we implement [ERC-8004](https://eips.ethereum.org/EIPS/eip-8004) ("Trustless Agents") — an ERC-721 token that maps PeerID + wallet to a portable identity token. This enables cross-chain identity: an agent registered on Ethereum can prove its identity on Algorand.

![ERC-8004 identity registration, bridge, and reputation sync flow](images/erc8004-identity-flow.png)
*The identity bridge maps libp2p PeerID to ETH wallet to on-chain agentId — verifiable across chains.*

---

## The Demo: Two Commands, Ten Phases

```bash
# Terminal 1: Start 2 agents + the Next.js dashboard
./scripts/dev.sh

# Terminal 2: Run the live demo
./scripts/agent_demo.sh
```

`dev.sh` starts two agents with health-check gates (waits for `/health` to respond before proceeding) and **bidirectional peer connection** (both agents explicitly connect to each other). This eliminates the peer-address-expiry race condition that plagues naive libp2p setups.

The demo walks through 10 phases: agent discovery (PeerID + wallet + EIP-191 proof), peer connection, channel open (1 ETH deposit), a 10-payment micropayment burst with timing (~sub-millisecond per payment), trust score visualization, dynamic pricing with trust discount, agent runtime task submission, x402 gateway flow, cooperative channel close, and a summary.

---

## What We Learned Building This

### Send Before Commit

The biggest design decision was the payment ordering: send the voucher to the peer, wait for acknowledgment, *then* update local state. Every instinct from database programming says "commit first, then notify." But in a P2P payment system, a committed-but-unsent voucher is irrecoverable — the local nonce has advanced, but the peer never received the payment. Sending first means a network failure leaves the channel in a consistent state: retry the same voucher.

### Trust Is Not Optional

We initially built payment channels without a trust layer — "just sign vouchers and send them." The first time we ran a multi-agent simulation, chaos ensued. Agents had no way to differentiate reliable peers from flaky ones. Every interaction was a coin flip. Adding reputation scoring, SLA monitoring, and dynamic pricing transformed the network from random noise into an economy that naturally rewards good behavior.

### Cumulative Over Incremental

We considered Lightning-style commitment transactions (where each state is a new "commitment" that invalidates the previous one via penalty transactions). Cumulative vouchers are dramatically simpler: no penalty transactions, no watchtowers, no revocation secrets. The tradeoff is that cumulative vouchers don't support bidirectional payments on a single channel — you need a channel in each direction. For agent workloads, this is fine: the payer and the service provider have distinct roles.

---

## By The Numbers

| | |
|---|---|
| **680 tests** across 40 test files | Covering protocol, payments, routing, trust, API, and integration |
| **55 source modules** in 19 packages | Clean separation of concerns, no circular dependencies |
| **~50 REST API endpoints** | Every feature accessible via HTTP |
| **~50 CLI commands** | Full command-line interface for operators |
| **13 protocol message types** | Complete wire protocol for the payment lifecycle |
| **3 settlement chains** | Ethereum, Algorand, Filecoin FEVM |
| **6 channel states** | With challenge period and cooperative close fast-path |
| **13 architecture diagrams** | Excalidraw sources + rendered PNGs |
| **11 seconds** | Full test suite runtime |

---

## Ecosystem Alignment

AgentPay is built for the [Filecoin Onchain Cloud](https://filecoin.cloud/agents) agent ecosystem, mapping to 6 of the 7 Requests for Startups:

| RFS | AgentPay Component |
|-----|-------------------|
| Agentic Storage SDK | IPFS content-addressed receipt storage |
| Onchain Agent Registry | ERC-8004 Identity Registry + PeerID bridge |
| Agent Reputation & Portable Identity | 4-factor trust scoring + hash-chained audit trails |
| Autonomous Agent Economy Testbed | Multi-agent simulation + dashboard |
| Fee-Gated Agent Communication | libp2p streams + x402 payment gateway |
| Agent-Generated Data Marketplace | Dynamic pricing + Bazaar-compatible capability registry |

---

## What's Next

AgentPay works today for local and testnet deployments. The honest roadmap:

- **Mainnet settlement** — contracts need live-chain battle testing
- **Encrypted onion routing** — HTLC preimages are currently plaintext (functional but not production-secure for multi-hop)
- **WebRTC transport** — browser-based agents via libp2p-webrtc
- **Framework adapters** — drop-in payment wrappers for LangChain, CrewAI, and AutoGPT
- **Cross-chain channels** — open on Ethereum, settle on Filecoin
- **Storage procurement** — agents autonomously negotiate and pay for Filecoin storage deals

---

## The Closing Argument

The agent economy isn't a future prediction — it's a present reality. [AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) has 170k+ GitHub stars. [CrewAI](https://www.crewai.com/) raised $18M. Every major cloud provider is shipping agent frameworks. The missing piece isn't more capable models — it's the economic infrastructure that lets these agents transact with each other.

AgentPay is that infrastructure. Not just payment channels, but the complete stack: discovery, negotiation, micropayments, trust, SLA enforcement, dispute resolution, and autonomous task coordination. Peer-to-peer. Sub-millisecond. Cryptographically verified.

Two on-chain transactions settle thousands of payments. One protocol handles the full lifecycle from strangers to trading partners. Zero middlemen.

**The code is open source. The demo is two commands. [Try it.](https://github.com/yashksaini-coder/AgentPay)**

---

*Built by [Yash K. Saini](https://github.com/yashksaini-coder) for the [PL Genesis](https://plgenesis.com/) hackathon.*

*[GitHub](https://github.com/yashksaini-coder/AgentPay) | [Architecture](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/ARCHITECTURE.md) | [CLI & API Reference](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/COMMANDS.md) | [Ecosystem Alignment](https://github.com/yashksaini-coder/AgentPay/blob/master/docs/ECOSYSTEM-ALIGNMENT.md)*
