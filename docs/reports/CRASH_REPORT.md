# AgentPay Simulation Crash Report

**Date:** 2026-03-12
**Simulation:** 100 rounds, 5 agents, mesh topology, fast speed
**Result:** ~70 OK / ~30 FAIL (30% failure rate)

---

## Executive Summary

Payment failures during high-throughput simulation are caused by a **stream response offset bug** in the `route_payment()` method. After completing an HTLC-routed payment, the method sends a `PAYMENT_UPDATE` voucher but **never reads the `PAYMENT_ACK` response**. This leaves a stale message in the stream buffer, causing all subsequent operations on that stream to read the wrong response — a cascading desynchronization that grows worse with each routed payment.

This is **not** a library bug. It is a protocol-level implementation error in our own code.

---

## Root Cause

### The Bug: Missing `read_message()` in `route_payment()`

**File:** `src/agentic_payments/node/agent_node.py`, lines 585–618

The `route_payment()` method performs a two-phase operation on a single libp2p stream:

1. **Phase 1 — HTLC exchange:** Send `HTLC_PROPOSE`, read `HTLC_FULFILL` response
2. **Phase 2 — Voucher transfer:** Send `PAYMENT_UPDATE` ... *but never read `PAYMENT_ACK`*

```python
# route_payment() — simplified
async with lock:
    stream = await self._get_or_open_stream(peer_id)

    # Phase 1: HTLC — correct (write + read)
    await write_message(stream, to_wire(MessageType.HTLC_PROPOSE, htlc_msg))
    raw = await read_message(stream)        # ← reads HTLC_FULFILL ✓
    msg_type, resp = from_wire(raw)

    if msg_type == MessageType.HTLC_FULFILL:
        # Phase 2: Voucher — BUG (write only, no read)
        async def send_fn(msg):
            await write_message(stream, to_wire(MessageType.PAYMENT_UPDATE, msg))
        await self.channel_manager.send_payment(...)
        # ⚠️ PAYMENT_ACK is NEVER read from the stream
```

Compare with `pay()` (direct payment), which correctly reads the ACK:

```python
# pay() — correct implementation
async def send_fn(msg):
    await write_message(stream, to_wire(MessageType.PAYMENT_UPDATE, msg))

voucher = await self.channel_manager.send_payment(...)

raw = await read_message(stream)        # ← reads PAYMENT_ACK ✓
msg_type, ack = from_wire(raw)
if msg_type != MessageType.PAYMENT_ACK:
    raise RuntimeError(f"Unexpected response type: {msg_type}")
```

### Why the Receiver Sends PAYMENT_ACK

The receiver's protocol handler (`protocol/handler.py`) processes **every** incoming message and writes a response:

```python
# handler.py: handle_stream() — the read loop
while True:
    raw = await read_message(stream)
    msg_type, msg = from_wire(raw)
    response = await self._dispatch(msg_type, msg, remote_peer)
    if response is not None:
        await write_message(stream, to_wire(*response))  # ← always writes back
```

The `_handle_update()` dispatcher always returns a `PAYMENT_ACK`:

```python
async def _handle_update(self, msg, remote_peer):
    await self.channel_manager.handle_payment_update(msg)
    return MessageType.PAYMENT_ACK, PaymentAck(
        channel_id=msg.channel_id, nonce=msg.nonce, status="accepted",
    )
```

So the `PAYMENT_ACK` is written into the stream but **nobody reads it**.

---

## Cascade Failure Mechanism

Streams in libp2p (yamux multiplexer) are **ordered, bidirectional byte streams** — like TCP. Unread messages accumulate in the receive buffer. Here's what happens over successive operations on the same cached stream:

### Timeline (stream between Agent A → Agent B)

| Step | Operation | Writes | Reads | Buffer After |
|------|-----------|--------|-------|-------------|
| 1 | `route_payment()` | HTLC_PROPOSE | HTLC_FULFILL | — |
| 2 | `route_payment()` (cont.) | PAYMENT_UPDATE | *(nothing)* | **[PAYMENT_ACK]** |
| 3 | `pay()` | PAYMENT_UPDATE | **PAYMENT_ACK** ← stale from step 2! | **[PAYMENT_ACK]** (new one) |
| 4 | `pay()` checks type | — | — | *expects PAYMENT_ACK for step 3, got ACK for step 2* |
| 5 | `route_payment()` | HTLC_PROPOSE | **PAYMENT_ACK** ← stale from step 3! | **[HTLC_FULFILL]** |
| 6 | `route_payment()` gets wrong type | — | — | `Unexpected response type: 4` (PAYMENT_ACK ≠ HTLC_FULFILL) |

Or the inverse order:

| Step | Operation | Reads from buffer | Error |
|------|-----------|------------------|-------|
| N | `pay()` | HTLC_FULFILL (type 6) | `Unexpected response type: 6` |

### Error Signatures from Logs

The following errors observed in simulation all trace to this single bug:

```
RuntimeError: Unexpected response type: 6    # pay() reads stale HTLC_FULFILL
RuntimeError: Unexpected response type: 4    # route_payment() reads stale PAYMENT_ACK
400 route-pay: "HTLC cancelled: ..."         # downstream cascade from offset
400 pay: "Insufficient balance"              # channel state drift from partial applies
```

### Why ~30% and Not 100%?

- **Direct payments (`pay()`) on fresh streams work fine** — no prior offset exists
- **The first `route_payment()` on any stream always succeeds** — buffer is clean
- **Failure probability increases with reuse** — each `route_payment()` adds one stale message
- **Per-peer stream caching** means the offset persists for the lifetime of the stream
- **The 60/40 direct/routed split** in simulation means not every operation hits the bug

---

## Affected Components

| Component | File | Role | Bug? |
|-----------|------|------|------|
| `AgentNode.route_payment()` | `node/agent_node.py:585-618` | Sends HTLC + voucher on outbound stream | **YES — missing read** |
| `AgentNode.pay()` | `node/agent_node.py:364-407` | Sends direct voucher on outbound stream | No (reads ACK correctly) |
| `ProtocolHandler.handle_stream()` | `protocol/handler.py:60-107` | Inbound message loop, writes responses | No (correct behavior) |
| `ProtocolHandler._handle_update()` | `protocol/handler.py:165-183` | Processes voucher, returns ACK | No (correct behavior) |
| `ChannelManager.send_payment()` | `payments/manager.py:156-212` | Creates/signs/sends voucher | No (delegates write to send_fn) |
| py-libp2p yamux streams | External library | Stream multiplexing | No (working as designed) |
| Stream locks (`trio.Lock`) | `node/agent_node.py:278` | Serialize stream I/O per peer | No (working as designed) |

**No external library is at fault.** The bug is entirely in our `route_payment()` implementation.

---

## Fix

Add the missing `read_message()` after `send_payment()` in `route_payment()`:

```python
# In route_payment(), after the send_payment() call:
await self.channel_manager.send_payment(
    channel_id=channel.channel_id,
    amount=amount,
    private_key=self.wallet.private_key,
    send_fn=send_fn,
)

# Read and validate the PAYMENT_ACK response
raw = await read_message(stream)
ack_type, ack = from_wire(raw)
if ack_type != MessageType.PAYMENT_ACK:
    raise RuntimeError(f"Unexpected voucher ACK type: {ack_type}")
if ack.status != "accepted":
    raise RuntimeError(f"Voucher rejected by peer: {ack.reason}")
```

This is a **one-line conceptual fix** (add the read + validation) that mirrors what `pay()` already does correctly.

---

## Verification

After applying the fix, run:

```bash
# CLI simulation
agentpay simulate --agents 5 --topology mesh --rounds 100 --concurrency 3

# Frontend simulation
# 5 agents, mesh, fast speed, 100 rounds
```

Expected: failure rate drops from ~30% to near 0% (residual failures may come from legitimate conditions like insufficient balance on heavily-used channels).
