.PHONY: lint fmt fmt-check typecheck test frontend-lint frontend-build contracts-build contracts-fmt ci

lint:
	uv run ruff check src/ tests/
fmt:
	uv run ruff format src/ tests/
fmt-check:
	uv run ruff format --check src/ tests/
typecheck:
	uv run mypy src/agentic_payments/ --ignore-missing-imports
test:
	uv run pytest tests/ -x -q
frontend-lint:
	cd frontend && npm run lint
frontend-build:
	cd frontend && npm run build
contracts-build:
	cd contracts && ([ -d lib/forge-std ] || git clone --depth 1 https://github.com/foundry-rs/forge-std.git lib/forge-std) && forge build
contracts-fmt:
	cd contracts && forge fmt --check
ci: lint fmt-check typecheck test frontend-lint frontend-build contracts-build contracts-fmt
