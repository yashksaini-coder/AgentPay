.PHONY: lint fmt fmt-check typecheck test frontend-lint frontend-build contracts-build contracts-fmt ci clean

# ── Colors ────────────────────────────────────────
GREEN  := \033[0;32m
RED    := \033[0;31m
CYAN   := \033[0;36m
BOLD   := \033[1m
DIM    := \033[2m
NC     := \033[0m
CHECK  := $(GREEN)✓$(NC)
CROSS  := $(RED)✗$(NC)

# ── Helper ────────────────────────────────────────
# Usage: $(call run,Label,command)
define run
	@printf "  $(CYAN)$(1)$(NC) ... " && \
	if output=$$($(2) 2>&1); then \
		printf "$(CHECK) $(DIM)passed$(NC)\n"; \
	else \
		printf "$(CROSS) $(RED)FAILED$(NC)\n"; \
		echo "$$output"; \
		exit 1; \
	fi
endef

# ── Targets ───────────────────────────────────────
lint:
	$(call run,ruff check,uv run ruff check src/ tests/)

fmt:
	@uv run ruff format src/ tests/
	@printf "  $(CHECK) $(DIM)formatted$(NC)\n"

fmt-check:
	$(call run,ruff format --check,uv run ruff format --check src/ tests/)

typecheck:
	$(call run,mypy typecheck,uv run mypy src/agentic_payments/ --ignore-missing-imports)

test:
	@printf "  $(CYAN)pytest$(NC) ... " && \
	output=$$(uv run pytest tests/ -x -q 2>&1) && \
	count=$$(echo "$$output" | grep -oP '\d+ passed' | head -1) && \
	printf "$(CHECK) $(DIM)$$count$(NC)\n" || \
	{ printf "$(CROSS) $(RED)FAILED$(NC)\n"; echo "$$output" | tail -20; exit 1; }

frontend-lint:
	@printf "  $(CYAN)eslint$(NC) ... " && \
	output=$$(cd frontend && npm run lint 2>&1) && \
	errors=$$(echo "$$output" | grep -oP '(\d+) error' | head -1 | grep -oP '\d+' || echo "0") && \
	warnings=$$(echo "$$output" | grep -oP '(\d+) warning' | head -1 | grep -oP '\d+' || echo "0") && \
	if [ "$$errors" != "0" ] && [ -n "$$errors" ]; then \
		printf "$(CROSS) $(RED)$$errors errors, $$warnings warnings$(NC)\n"; \
		echo "$$output"; \
		exit 1; \
	else \
		printf "$(CHECK) $(DIM)0 errors, $$warnings warnings$(NC)\n"; \
	fi

frontend-build:
	$(call run,next build,cd frontend && npm run build)

contracts-build:
	$(call run,forge build,cd contracts && ([ -d lib/forge-std ] || git clone --depth 1 https://github.com/foundry-rs/forge-std.git lib/forge-std) && forge build)

contracts-fmt:
	$(call run,forge fmt,cd contracts && forge fmt --check)

# ── CI Pipeline ───────────────────────────────────
ci:
	@printf "\n$(BOLD)$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)\n"
	@printf "$(BOLD)  AgentPay — CI Pipeline$(NC)\n"
	@printf "$(CYAN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)\n\n"
	@$(MAKE) --no-print-directory lint
	@$(MAKE) --no-print-directory fmt-check
	@$(MAKE) --no-print-directory typecheck
	@$(MAKE) --no-print-directory test
	@$(MAKE) --no-print-directory frontend-lint
	@$(MAKE) --no-print-directory frontend-build
	@printf "\n$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)\n"
	@printf "$(GREEN)  All checks passed!$(NC)\n"
	@printf "$(GREEN)━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━$(NC)\n\n"

clean:
	@rm -rf frontend/dist/ contracts/out/ dist/ .mypy_cache/ .ruff_cache/ .pytest_cache/
	@printf "  $(CHECK) $(DIM)cleaned$(NC)\n"
