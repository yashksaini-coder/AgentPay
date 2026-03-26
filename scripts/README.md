# AgentPay Scripts

## Quick Start

```bash
# Terminal 1 — start agents + dashboard
./scripts/dev.sh

# Terminal 2 — run the demo
./scripts/agent_demo.sh
```

## Script Guide

| Script | What | When to use |
|--------|------|-------------|
| `dev.sh` | Start agents + frontend dashboard | First: run this in Terminal 1 |
| `agent_demo.sh` | Live payment demo (10 phases) | Then: run this in Terminal 2 |
| `demo.sh` | Full API demo (9 phases) | Alternative to agent_demo.sh |
| `video_demo.sh` | Screen recording demo | For recording polished walkthroughs |
| `live_test.sh` | E2E pass/fail test suite | CI or manual validation |
| `deploy_local.sh` | Deploy contracts to Anvil | Only if you need on-chain settlement |

## `dev.sh` Options

```bash
./scripts/dev.sh                          # 2 agents (default)
./scripts/dev.sh --agents 3               # 3 agents
./scripts/dev.sh --no-agents              # frontend only
./scripts/dev.sh --agent-enabled          # enable Agent Runtime
./scripts/dev.sh --agent-enabled --agent-tick 2  # faster tick
```

## `agent_demo.sh` Phases

1. Agent Discovery — PeerID + ETH wallet + EIP-191 binding
2. Peer Connection — Bidirectional connectivity
3. Open Payment Channel — 1 ETH off-chain deposit
4. Micropayments Burst — 10 rapid voucher payments
5. Trust & Reputation — Trust scores from payment history
6. Dynamic Pricing — Price quotes with trust discounts
7. Agent Runtime — Autonomous task execution (requires `--agent-enabled`)
8. x402 Gateway — Payment-gated resources
9. Channel Close — Cooperative settlement
10. Summary — Feature checklist

## On-Chain Demo (Optional)

```bash
# Start Anvil
anvil &

# Deploy contracts
./scripts/deploy_local.sh
source .env.local

# Start agents with contract addresses
./scripts/dev.sh --agents 2

# Run E2E tests
./scripts/live_test.sh
```
