# AgentPay Payment Failure Analysis

**Date:** 2026-03-12
**System:** AgentPay — libp2p P2P network with Ethereum-based micropayment channels
**Topology:** 2-node ring (Agent A ↔ Agent B), channels in both directions, rapid simulation payments

---

## Executive Summary

Three distinct failure modes emerged during a simulation run of ~40+ concurrent payments between two agents. All three share a single root cause: **the absence of any synchronization primitives** (`trio.Lock`) protecting shared mutable state — streams and payment channels — accessed concurrently by trio tasks.

| # | Error | Root Cause | Severity |
|---|-------|-----------|----------|
| 1 | `HTLC cancel: Unexpected downstream response` | Stream multiplexing — concurrent read/write on shared stream | **Critical** |
| 2 | `Message too large: 1639887299 > 1048576` | Frame corruption from interleaved writes on same stream | **Critical** |
| 3 | `Voucher nonce 14 must be > current nonce 14` | TOCTOU race on channel nonce during concurrent payments | **High** |

---

## Bug 1: "Unexpected downstream response"

### What happened

Agent B forwarded an HTLC to Agent A (or vice versa). The intermediate node sent `HTLC_PROPOSE` on the stream and waited for `HTLC_FULFILL` or `HTLC_CANCEL`. Instead, it received a message with an unexpected `MessageType` — likely a `PAYMENT_ACK` or `PAYMENT_UPDATE` from a different concurrent payment.

### Where

```
agent_node.py:806-814  (_on_htlc_propose → else branch)
agent_node.py:766-771  (stream = _get_or_open_stream → write → read)
```

### Code path

```
_on_htlc_propose()
  → stream = _get_or_open_stream(next_peer_id)   # returns SHARED cached stream
  → write_message(stream, HTLC_PROPOSE)
  → raw = read_message(stream)                     # reads WRONG response
  → resp_type ≠ HTLC_FULFILL and ≠ HTLC_CANCEL
  → falls into `else` → "Unexpected downstream response"
```

### Why

`_get_or_open_stream()` (`agent_node.py:281-288`) caches one stream per peer in `self._streams: dict[str, NetStream]`. When two concurrent trio tasks both call `pay()` or `_on_htlc_propose()` targeting the same peer, they:

1. Both get the **same** `NetStream` object
2. Both write their message (interleaved on the wire)
3. Both read — but each gets the **other's** response

There is **no lock** on `_streams` or on individual stream I/O. A `grep` for `trio.Lock` across the entire codebase returns zero results.

### Timeline

```
T1: Task-HTLC   writes HTLC_PROPOSE on stream(A→B)
T2: Task-Direct  writes PAYMENT_UPDATE on stream(A→B)   ← same stream!
T3: Task-HTLC   reads from stream(A→B) → gets PAYMENT_ACK (meant for Task-Direct)
T4: resp_type = PAYMENT_ACK ≠ HTLC_FULFILL → "Unexpected downstream response"
```

---

## Bug 2: "Message too large: 1639887299 > 1048576"

### What happened

Agent A tried to read a response from Agent B. The 4-byte length header it read was `b'a\xbe\xb1\xc3'`, which decodes (big-endian uint32) to **1,639,887,299** — far exceeding the 1 MB max. This is not a real header; it's payload bytes from a different message that leaked into the header position.

### Where

```
codec.py:50-53  (read_message → header parse)
agent_node.py:376  (_attempt_pay → read_message)
```

### Code path

```
pay() → _attempt_pay()
  → write_message(stream, PAYMENT_UPDATE)
  → raw = read_message(stream)
    → header = _read_exactly(stream, 4)       # reads 4 bytes
    → length = struct.unpack(">I", header)     # 0x61beb1c3 = 1,639,887,299
    → ValueError("Message too large")
```

### Why — frame corruption from interleaved writes

The wire protocol is `[4-byte big-endian length][msgpack payload]`. When two tasks write to the same stream without a mutex:

```
Wire (what actually lands on the TCP socket):

  [header₁: 4B] [partial payload₂] [rest of payload₁] [header₂: 4B] [payload₂ remainder]
                  ↑ interleaved
```

The receiver reads `header₁` (4 bytes correctly), then reads what it thinks is `payload₁` — but the next bytes are actually part of `payload₂`. After consuming the wrong number of bytes, the **next** "header" read lands in the middle of a msgpack blob. The bytes `0x61 0xBE 0xB1 0xC3` are valid msgpack data (e.g., part of an Ethereum address or signature), not a frame length.

### Evidence

The header bytes `b'a\xbe\xb1\xc3'`:
- `0x61` = ASCII `a` — likely the start of a hex address string
- This is consistent with msgpack-encoded payload content leaking into the header position

The channel's `pending_htlc_amount=1117242` confirms concurrent HTLC activity on the same channel/stream at the time of corruption.

---

## Bug 3: "Voucher nonce 14 must be > current nonce 14"

### What happened

Agent B created a voucher with nonce 14 and sent it successfully over the wire. When it tried to apply the voucher locally with `channel.apply_voucher()`, the channel's nonce was **already** 14 — updated by a concurrent payment that raced ahead.

### Where

```
manager.py:169      (new_nonce = channel.nonce + 1)      ← READ
manager.py:186-194  (await send_fn(...))                  ← NETWORK I/O (yields)
manager.py:197      (channel.apply_voucher(voucher))      ← WRITE (fails)
channel.py:118-121  (voucher.nonce <= self.nonce → raise)
```

### Code path

```
send_payment():
  new_nonce = channel.nonce + 1    # reads nonce=13, computes 14
  voucher = create(nonce=14, ...)
  await send_fn(voucher)            # sends over network — YIELDS to trio scheduler
  channel.apply_voucher(voucher)    # channel.nonce is now 14 already → ERROR
```

### Why — TOCTOU (Time-of-Check-Time-of-Use) race

The nonce is read at line 169, but the channel state is not locked. Between `channel.nonce + 1` and `channel.apply_voucher()`, there's an `await send_fn()` that yields to the trio event loop. During that yield, another concurrent `send_payment()` call on the **same channel** can:

1. Also read `channel.nonce` (still 13, since no one has applied yet)
2. Create its own voucher with nonce 14
3. Complete its `send_fn()` first
4. Call `apply_voucher(14)` — succeeds, updates `channel.nonce = 14`
5. Now the first task's `apply_voucher(14)` fails: `14 <= 14`

### Evidence from locals

The log shows two key data points:
- `new_nonce = 14` (computed by the failing task)
- `channel.nonce = 14` (already advanced by the winning task)
- `channel.total_paid = 3,834,647` but `voucher.amount = 3,605,134` — the channel has advanced **past** where this voucher expected it to be

This also means the **receiver already got a contradictory voucher** — two vouchers with nonce=14 but different cumulative amounts (3,605,134 vs 3,834,647). The receiver accepted the first one that arrived over the wire, but the sender's local state is now inconsistent.

---

## Topological Context

```
┌──────────┐     Channel: A→B (5M deposit)     ┌──────────┐
│ Agent A  │ ──────────────────────────────────→ │ Agent B  │
│ :8080    │ ←────────────────────────────────── │ :8081    │
└──────────┘     Channel: B→A (5M deposit)     └──────────┘
      ↕  shared stream(A→B)  ↕
      ↕  shared stream(B→A)  ↕
```

- **2 agents**, each with a payment channel to the other
- **1 cached stream per direction** — all payments (direct + HTLC) to the same peer funnel through a single `NetStream`
- **Simulation runs rapid-fire**: multiple `pay()` and `route_payment()` calls execute concurrently as independent trio tasks
- With only 2 nodes, every multi-hop route goes A→B or B→A, maximizing contention on the single cached stream

---

## Root Cause: Zero Synchronization

A `grep -r "trio.Lock\|asyncio.Lock\|_lock" src/agentic_payments/` returns **no results**. The system has:

| Resource | Shared By | Lock | Risk |
|----------|-----------|------|------|
| `_streams[peer_id]` (NetStream) | All payments to same peer | **None** | Bugs 1 & 2 |
| `PaymentChannel` (nonce, total_paid) | All payments on same channel | **None** | Bug 3 |
| `_streams` dict itself | All stream operations | **None** | Potential stale eviction race |

---

## Fix Plan

### Fix 1: Per-peer stream lock (Bugs 1 & 2)

```python
# In AgentNode.__init__:
self._stream_locks: dict[str, trio.Lock] = {}

async def _get_stream_lock(self, peer_id: str) -> trio.Lock:
    if peer_id not in self._stream_locks:
        self._stream_locks[peer_id] = trio.Lock()
    return self._stream_locks[peer_id]
```

Then in `pay()` and `_on_htlc_propose()`:

```python
lock = await self._get_stream_lock(peer_id)
async with lock:
    stream = await self._get_or_open_stream(peer_id)
    await write_message(stream, ...)
    raw = await read_message(stream)
```

This ensures write+read is **atomic** per peer — no interleaving.

### Fix 2: Per-channel lock (Bug 3)

```python
# In ChannelManager.__init__:
self._channel_locks: dict[bytes, trio.Lock] = {}

async def send_payment(self, channel_id, amount, private_key, send_fn):
    if channel_id not in self._channel_locks:
        self._channel_locks[channel_id] = trio.Lock()

    async with self._channel_locks[channel_id]:
        # nonce read, voucher create, send, apply — all atomic
        channel = self.get_channel(channel_id)
        new_nonce = channel.nonce + 1
        ...
        channel.apply_voucher(voucher)
```

### Fix 3: Stream eviction under lock

When `_evict_stream()` is called, the stream lock should be held to prevent new writes on the about-to-be-evicted stream.

---

## Impact Assessment

| Metric | Value |
|--------|-------|
| Observed failure rate | ~15-25% of payments in rapid simulation |
| Data corruption risk | Voucher nonce desync between sender/receiver (Bug 3) |
| Stream corruption risk | Frame corruption poisons stream permanently (Bug 2) |
| Recovery | Bug 1: automatic (retry opens new stream). Bug 2: requires stream eviction. Bug 3: channel permanently wedged until nonces realign |
| Funds at risk | None (off-chain simulation), but in production with on-chain settlement, nonce desync could allow double-claim or prevent dispute |
