# AgentPay Simulation Report #2 — Post-Fix

**Date:** 2026-03-12
**Simulation:** 5 agents, mesh topology, fast speed
**Previous bug:** Stream response offset (fixed in previous session)

---

## Result: Stream Offset Bug is Fixed

The `Unexpected response type: 6` error that caused ~30% failures in the previous run is **completely eliminated**. All `route-pay` and `pay` operations now correctly read their responses from the stream.

**Evidence:** Zero instances of `Unexpected response type` in the entire log. Every `200` response represents a correctly completed payment with proper stream synchronization.

---

## Remaining Failures: Channel Balance Exhaustion

All failures in this run are **legitimate balance errors**, not protocol bugs:

### Error Type 1: Direct Pay — Deposit Exceeded (HTTP 500)

```
ChannelError: Voucher amount 5,311,053 exceeds deposit 5,000,000
  (total_paid=4,859,940, payment=451,113)
```

**What happens:** Agent C tries to pay 451,113 on a channel that has already spent 4,859,940 of its 5,000,000 deposit. Only 140,060 remains — the payment is too large.

**File:** `payments/manager.py:186` — `send_payment()` correctly rejects the voucher before signing.

### Error Type 2: Routed Pay — Insufficient Balance (HTTP 500)

```
ChannelError: Insufficient balance: need 978,349, available 742,151
```

**What happens:** Agent A tries to route 978,349 through a channel to Agent D, but only 742,151 is unspent. The `lock_htlc()` call correctly refuses to lock funds that don't exist.

**File:** `payments/channel.py:244` — `lock_htlc()` checks `amount > available_balance`.

### Error Type 3: Route-Pay 400s

```
[C] POST /route-pay  400
```

These are the API returning a 400 when routing fails — typically because no route has sufficient capacity. This is correct behavior.

---

## Failure Summary

| Error | Count | HTTP Status | Bug? |
|-------|-------|-------------|------|
| Deposit exceeded (`send_payment`) | ~3 | 500 | No — correct rejection |
| Insufficient balance (`lock_htlc`) | ~1 | 500 | No — correct rejection |
| Route-pay no viable path | ~5 | 400 | No — correct rejection |
| Stream offset / wrong message type | **0** | — | **Fixed** |

---

## Why Channels Run Dry

With 5 agents in a mesh, each channel has a 5,000,000 deposit. The simulation sends random payments of varying sizes (up to ~1M per payment). After ~13-17 payments on a channel, the cumulative total approaches the deposit limit. Since channels are **unidirectional** (sender → receiver), the sender's balance only decreases — there's no rebalancing.

Example from logs — Agent C's channel `f66e...1647`:
- Nonce 16: total_paid = 4,859,940 (97% spent)
- Payment of 451,113 requested → would need 5,311,053 → **rejected**

This is expected behavior in any payment channel system without channel rebalancing or top-ups.

---

## HTTP 500 vs 400

One improvement to note: the deposit-exceeded and insufficient-balance errors return **500** instead of **400**. These are client-caused errors (requesting a payment larger than available balance), so they should arguably return 400. This is a minor API hygiene issue, not a correctness bug.

---

## Comparison with Previous Run

| Metric | Run #1 (before fix) | Run #2 (after fix) |
|--------|---------------------|-------------------|
| Stream offset errors | ~30% of operations | **0** |
| `Unexpected response type: 6` | Frequent | **Gone** |
| Balance exhaustion errors | Present (masked by stream bugs) | Present (now the only failure mode) |
| Protocol correctness | Broken — stale reads | **Correct** |

---

## Recommendations

1. **Return 400 (not 500) for balance errors** — The API route catches `ChannelError` from `pay()` / `route_payment()` but currently lets it fall through to the generic 500 handler. Add explicit handling.

2. **Cap simulation payment amounts** — The frontend/CLI simulation could cap random payment amounts to `min(random_amount, available_balance)` to avoid guaranteed failures on low-balance channels.

3. **Channel top-ups** — For longer simulations, implement `deposit_more()` to add funds to existing channels without closing and reopening.

4. **Bidirectional channels** — Allow both parties to send on the same channel (mutual close with net settlement), which would naturally rebalance over time.
