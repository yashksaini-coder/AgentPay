---
title: Contributing
layout: default
nav_order: 5
---

# Contributing to AgentPay

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/yashksaini-coder/AgentPay.git
cd AgentPay

# Install Python dependencies (with dev tools)
uv sync --group dev

# Install frontend dependencies
cd frontend && npm install && cd ..

# Run the full CI suite locally to verify setup
make ci
```

## Branch Rules

This repository enforces the following rules on **all branches** via GitHub rulesets:

| Rule | What it means |
|------|---------------|
| **Pull requests required** | No direct pushes — all changes go through a PR |
| **1 approving review** | At least one maintainer must approve before merge |
| **Dismiss stale reviews on push** | Pushing new commits resets existing approvals |
| **Linear history required** | Use squash or rebase merges only |
| **No force pushes** | Force-pushing is blocked on all branches |
| **Code quality gate** | GitHub code scanning must pass |

### Workflow for Contributors

```bash
# 1. Fork the repo and clone your fork
git clone https://github.com/<your-username>/AgentPay.git
cd AgentPay

# 2. Create a feature branch
git checkout -b feat/my-feature

# 3. Make changes, then run CI locally
make ci

# 4. Commit with a descriptive message
git commit -m "feat: add bidirectional channel support"

# 5. Push to your fork
git push origin feat/my-feature

# 6. Open a PR against master
```

## Code Quality

All code must pass these checks before merging:

```bash
make lint          # ruff check
make fmt-check     # ruff format --check
make typecheck     # mypy
make test          # pytest (680 tests)
make frontend-lint # eslint
make frontend-build # next build
make contracts-build # forge build
```

### Configuration

- **Line length**: 100 characters
- **Target**: Python 3.12+
- **Async runtime**: Trio (not asyncio)
- **Test framework**: pytest-trio with `trio_mode = true`

## Project Structure

```
src/agentic_payments/
├── cli.py              # Typer CLI entrypoint
├── config.py           # Pydantic settings
├── node/               # Agent node, identity, discovery
├── protocol/           # Wire messages, codec, stream handler
├── payments/           # Channel state machine, vouchers, manager
├── chain/              # Ethereum & Algorand wallet, contracts
├── pubsub/             # GossipSub topics, broadcaster
├── discovery/          # Capability registry
├── negotiation/        # Propose/counter/accept protocol
├── reputation/         # Trust scoring
├── pricing/            # Dynamic pricing engine
├── sla/                # SLA monitoring
├── disputes/           # Dispute detection and resolution
├── routing/            # Multi-hop pathfinding, HTLC
├── gateway/            # x402-compatible resource gating
├── policies/           # Wallet spend limits
├── reporting/          # Signed receipt chains
└── api/                # Quart-Trio REST server + routes

frontend/               # Next.js 15 dashboard
contracts/              # Solidity smart contracts (Foundry)
tests/                  # pytest-trio test suite
scripts/                # Dev startup scripts
docs/                   # Architecture, commands, diagrams
```

## Making Changes

1. **Read first**: Understand existing code before modifying
2. **Write tests**: New features need tests. Bug fixes need regression tests
3. **Keep it simple**: Avoid over-engineering
4. **Follow conventions**: Match the style of surrounding code
5. **Run `make ci` before pushing**

## Commit Messages

```
feat: add bidirectional channel support
fix: prevent voucher replay with stale nonce
test: add edge cases for channel state transitions
docs: update API endpoint documentation
refactor: extract voucher validation into separate module
```

## Areas for Contribution

- **Protocol improvements**: Multi-hop routing, bidirectional channels
- **Smart contract**: ERC-20 support, L2 deployment scripts
- **Frontend**: Mobile responsive, transaction history view
- **Testing**: Property-based tests, load/stress tests
- **Documentation**: Tutorials, API examples, integration guides
- **Bug reports**: Open an issue with reproduction steps

## Questions?

Open an issue on [GitHub](https://github.com/yashksaini-coder/AgentPay/issues).
