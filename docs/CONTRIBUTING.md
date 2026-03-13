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

# Run tests to verify setup
uv run pytest -v
```

## Code Quality

All code must pass these checks before merging:

```bash
# Tests (must all pass)
uv run pytest

# Lint (zero violations)
uv run ruff check src/ tests/

# Format (no changes needed)
uv run ruff format --check src/ tests/
```

### Configuration

- **Line length**: 100 characters (`pyproject.toml` → `[tool.ruff]`)
- **Target**: Python 3.12+ (`target-version = "py312"`)
- **Async runtime**: Trio (not asyncio) — this is a hard requirement from py-libp2p
- **Test framework**: pytest-trio with `trio_mode = true`

## Project Structure

```
src/agentic_payments/
├── cli.py              # Typer CLI entrypoint
├── config.py           # Pydantic settings
├── node/               # Agent node, identity, discovery
├── protocol/           # Wire messages, codec, stream handler
├── payments/           # Channel state machine, vouchers, manager
├── chain/              # Ethereum wallet, contracts, settlement
├── pubsub/             # GossipSub topics, broadcaster
└── api/                # Quart-Trio REST server + routes

frontend/               # Next.js 15 dashboard
contracts/              # Solidity smart contracts (Foundry)
tests/                  # pytest-trio test suite
docs/                   # Architecture, commands, demo docs
```

## Making Changes

1. **Read first**: Understand existing code before modifying. Start with [ARCHITECTURE.md](ARCHITECTURE.md).
2. **Write tests**: New features need tests. Bug fixes need regression tests.
3. **Keep it simple**: Avoid over-engineering. Solve the current problem, not hypothetical future ones.
4. **Follow conventions**: Match the style of surrounding code. Use existing patterns.

## Commit Messages

Use clear, descriptive commit messages:

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

Open an issue on GitHub or reach out via the links in the README.
