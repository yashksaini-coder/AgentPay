#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  AgentPay — One-command development startup
#
#  Starts:
#    1. Agent A on ports 9000/9001/8080
#    2. Agent B on ports 9100/9101/8081
#    3. Next.js frontend on port 3000
#
#  Usage:
#    ./scripts/dev.sh              # start everything
#    ./scripts/dev.sh --no-agents  # frontend only (use dashboard to boot agents)
#
#  Ctrl+C stops all processes cleanly.
# ─────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NO_AGENTS=false
if [[ "${1:-}" == "--no-agents" ]]; then
  NO_AGENTS=true
fi

# Colors — use $'...' to produce real escape bytes (not literal \033)
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
BLUE=$'\033[0;34m'
PURPLE=$'\033[0;35m'
YELLOW=$'\033[0;33m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'

# Track child PIDs for cleanup (actual process PIDs, not pipe PIDs)
CHILD_PIDS=()
SHUTTING_DOWN=false

cleanup() {
  # Prevent re-entry if called multiple times
  if [[ "$SHUTTING_DOWN" == true ]]; then return; fi
  SHUTTING_DOWN=true

  echo ""
  echo "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo "${YELLOW}  Shutting down...${NC}"
  echo "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  # 1. Send SIGTERM to all tracked children
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ${RED}→${NC} Stopping PID $pid..."
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # 2. Also kill any remaining agentpay/next processes we spawned
  #    (catches grandchildren the pipe may have created)
  pkill -TERM -P $$ 2>/dev/null || true

  # 3. Wait up to 5 seconds for graceful exit
  local timeout=5
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      local waited=0
      while kill -0 "$pid" 2>/dev/null && (( waited < timeout )); do
        sleep 0.5
        waited=$((waited + 1))
      done
      # Force kill if still alive
      if kill -0 "$pid" 2>/dev/null; then
        echo "  ${RED}→${NC} Force killing PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
  done

  # 4. Final sweep — kill any orphaned agentpay or next-server processes
  #    that might have been missed (grandchildren of pipes)
  pkill -9 -f "agentpay start --port 9000" 2>/dev/null || true
  pkill -9 -f "agentpay start --port 9100" 2>/dev/null || true
  pkill -9 -f "next dev.*frontend" 2>/dev/null || true

  # Wait for everything
  wait 2>/dev/null || true

  echo "${GREEN}  All processes stopped.${NC}"
  echo ""
}

trap cleanup EXIT INT TERM

echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${PURPLE}  AgentPay — Development Server${NC}"
echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Ensure dependencies are installed
echo "${BLUE}[setup]${NC} Syncing Python dependencies..."
uv sync --group dev --quiet 2>/dev/null || uv sync --group dev

# Prefix tags with actual ANSI bytes baked in
TAG_A="${GREEN}[A]${NC}"
TAG_B="${BLUE}[B]${NC}"
TAG_UI="${PURPLE}[UI]${NC}"

# Log filter — extracts clean "METHOD /route → STATUS" from Hypercorn access logs,
# passes through app-level structlog lines, drops noise (OPTIONS, browser UA strings).
filter_agent_log() {
  local tag="$1"
  while IFS= read -r line; do
    # Skip OPTIONS preflight requests (CORS noise)
    if [[ "$line" == *'"OPTIONS '* ]]; then
      continue
    fi
    # Match Hypercorn access log: ... "METHOD /route 1.1" STATUS SIZE ...
    if [[ "$line" =~ \"(GET|POST|PUT|DELETE|PATCH)\ (/[^\ ]*)\ [^\"]*\"\ ([0-9]+)\ ([0-9]+) ]]; then
      local method="${BASH_REMATCH[1]}"
      local route="${BASH_REMATCH[2]}"
      local status="${BASH_REMATCH[3]}"
      # Color status code
      local status_color="$GREEN"
      if [[ "$status" =~ ^4 ]]; then status_color="$YELLOW"
      elif [[ "$status" =~ ^5 ]]; then status_color="$RED"; fi
      printf '  %s %s%-4s%s %-20s %s%s%s\n' "$tag" "$DIM" "$method" "$NC" "$route" "$status_color" "$status" "$NC"
    # Pass through app-level log lines (structlog / startup messages)
    elif [[ "$line" == *"[INFO]"* && "$line" != *"127.0.0.1:"* ]] || \
         [[ "$line" == *"[WARNING]"* ]] || \
         [[ "$line" == *"[ERROR]"* ]] || \
         [[ "$line" == *"[DEBUG]"* ]] || \
         [[ "$line" == *"event="* ]] || \
         [[ "$line" == *"Started"* ]] || \
         [[ "$line" == *"Listening"* ]] || \
         [[ "$line" == *"mDNS"* ]] || \
         [[ "$line" == *"channel"* ]] || \
         [[ "$line" == *"peer"* ]] || \
         [[ "$line" == *"payment"* ]] || \
         [[ "$line" == *"Running"* ]]; then
      # Strip timestamp/PID prefix for cleaner output if it matches Hypercorn format
      local clean="$line"
      if [[ "$line" =~ \[INFO\]\ (.*) ]]; then
        clean="${BASH_REMATCH[1]}"
      fi
      printf '  %s %s\n' "$tag" "$clean"
    fi
  done
}

if [[ "$NO_AGENTS" == false ]]; then
  # Start Agent A (use process substitution to get real PID)
  echo "${GREEN}[agent-a]${NC} Starting on ports 9000/9001/8080..."
  uv run agentpay start \
    --port 9000 --ws-port 9001 --api-port 8080 \
    --log-level INFO \
    2>&1 | filter_agent_log "$TAG_A" &
  PIPE_PID=$!
  CHILD_PIDS+=("$PIPE_PID")
  # Also find the actual uv/agentpay PID (child of the pipe)
  sleep 0.5
  AGENT_A_PID=$(pgrep -f "agentpay start --port 9000" 2>/dev/null | head -1 || true)
  if [[ -n "$AGENT_A_PID" ]]; then
    CHILD_PIDS+=("$AGENT_A_PID")
  fi

  # Small delay so identity files don't collide
  sleep 1

  # Start Agent B
  echo "${BLUE}[agent-b]${NC} Starting on ports 9100/9101/8081..."
  uv run agentpay start \
    --port 9100 --ws-port 9101 --api-port 8081 \
    --identity-path ~/.agentic-payments/identity2.key \
    --log-level INFO \
    2>&1 | filter_agent_log "$TAG_B" &
  PIPE_PID=$!
  CHILD_PIDS+=("$PIPE_PID")
  sleep 0.5
  AGENT_B_PID=$(pgrep -f "agentpay start --port 9100" 2>/dev/null | head -1 || true)
  if [[ -n "$AGENT_B_PID" ]]; then
    CHILD_PIDS+=("$AGENT_B_PID")
  fi

  sleep 1
  echo ""
fi

# Start frontend
echo "${PURPLE}[frontend]${NC} Starting Next.js on port 3000..."
cd "$ROOT/frontend"

# Install npm deps if needed
if [ ! -d "node_modules" ]; then
  echo "${PURPLE}[frontend]${NC} Installing npm dependencies..."
  npm install --silent
fi

npm run dev 2>&1 | while IFS= read -r line; do printf '  %s %s\n' "$TAG_UI" "$line"; done &
PIPE_PID=$!
CHILD_PIDS+=("$PIPE_PID")
sleep 0.5
NEXT_PID=$(pgrep -f "next dev" 2>/dev/null | head -1 || true)
if [[ -n "$NEXT_PID" ]]; then
  CHILD_PIDS+=("$NEXT_PID")
fi

echo ""
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${GREEN}  All services started!${NC}"
echo ""
if [[ "$NO_AGENTS" == false ]]; then
  echo "  Agent A API:  ${GREEN}http://127.0.0.1:8080${NC}"
  echo "  Agent B API:  ${BLUE}http://127.0.0.1:8081${NC}"
fi
echo "  Dashboard:    ${PURPLE}http://localhost:3000${NC}"
echo "  Network View: ${PURPLE}http://localhost:3000/network${NC}"
echo ""
echo "  Press ${RED}Ctrl+C${NC} to stop all services."
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Wait for all background processes
wait
