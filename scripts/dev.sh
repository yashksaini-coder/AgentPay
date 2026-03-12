#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  AgentPay — One-command development startup
#
#  Starts N agent nodes + Next.js frontend.
#
#  Usage:
#    ./scripts/dev.sh                # 5 agents (default)
#    ./scripts/dev.sh --agents 3     # 3 agents
#    ./scripts/dev.sh --no-agents    # frontend only
#
#  Port allocation per agent (0-indexed):
#    P2P:  9000 + i*100    (9000, 9100, 9200, ...)
#    WS:   9001 + i*100    (9001, 9101, 9201, ...)
#    API:  8080 + i        (8080, 8081, 8082, ...)
#
#  Ctrl+C stops all processes cleanly.
# ─────────────────────────────────────────────────────────

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ── Parse arguments ──────────────────────────────────────
NUM_AGENTS=5
NO_AGENTS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-agents)
      NO_AGENTS=true
      shift
      ;;
    --agents)
      NUM_AGENTS="${2:?--agents requires a number}"
      shift 2
      ;;
    --agents=*)
      NUM_AGENTS="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--agents N] [--no-agents]" >&2
      exit 1
      ;;
  esac
done

# Validate
if ! [[ "$NUM_AGENTS" =~ ^[0-9]+$ ]] || (( NUM_AGENTS < 1 )); then
  echo "Error: --agents must be a positive integer (got: $NUM_AGENTS)" >&2
  exit 1
fi

# ── Colors ───────────────────────────────────────────────
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
BLUE=$'\033[0;34m'
PURPLE=$'\033[0;35m'
YELLOW=$'\033[0;33m'
CYAN=$'\033[0;36m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'

# Rotating colors for agent tags
AGENT_COLORS=("$GREEN" "$BLUE" "$CYAN" "$YELLOW" "$PURPLE" "$RED")

agent_color() {
  local idx=$1
  echo "${AGENT_COLORS[$((idx % ${#AGENT_COLORS[@]}))]}"
}

agent_label() {
  # 0=A, 1=B, 2=C, ...
  printf "\\x$(printf '%02x' $((65 + $1)))"
}

# ── Process tracking ─────────────────────────────────────
CHILD_PIDS=()
SHUTTING_DOWN=false

cleanup() {
  if [[ "$SHUTTING_DOWN" == true ]]; then return; fi
  SHUTTING_DOWN=true

  echo ""
  echo "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo "${YELLOW}  Shutting down...${NC}"
  echo "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  # Send SIGTERM to all tracked children
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "  ${RED}→${NC} Stopping PID $pid..."
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # Kill any remaining children of this script
  pkill -TERM -P $$ 2>/dev/null || true

  # Wait up to 5 seconds for graceful exit
  local timeout=5
  for pid in "${CHILD_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      local waited=0
      while kill -0 "$pid" 2>/dev/null && (( waited < timeout )); do
        sleep 0.5
        waited=$((waited + 1))
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "  ${RED}→${NC} Force killing PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
  done

  # Final sweep — kill any orphaned agentpay or next processes
  pkill -9 -f "agentpay start" 2>/dev/null || true
  pkill -9 -f "next dev.*frontend" 2>/dev/null || true

  wait 2>/dev/null || true

  echo "${GREEN}  All processes stopped.${NC}"
  echo ""
}

trap cleanup EXIT INT TERM

# ── Banner ───────────────────────────────────────────────
echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${PURPLE}  AgentPay — Development Server${NC}"
if [[ "$NO_AGENTS" == false ]]; then
  echo "${PURPLE}  Starting ${NUM_AGENTS} agent(s)${NC}"
fi
echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Dependencies ─────────────────────────────────────────
echo "${BLUE}[setup]${NC} Syncing Python dependencies..."
uv sync --group dev --quiet 2>/dev/null || uv sync --group dev

# ── Log filter ───────────────────────────────────────────
TAG_UI="${PURPLE}[UI]${NC}"

filter_agent_log() {
  local tag="$1"
  while IFS= read -r line; do
    # Skip OPTIONS preflight requests (CORS noise)
    if [[ "$line" == *'"OPTIONS '* ]]; then continue; fi
    # Skip raw Hypercorn IP-only access log noise
    if [[ "$line" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+\ -\  ]]; then continue; fi
    # Match Hypercorn access log
    if [[ "$line" =~ \"(GET|POST|PUT|DELETE|PATCH)\ (/[^\ ]*)\ [^\"]*\"\ ([0-9]+)\ ([0-9]+) ]]; then
      local method="${BASH_REMATCH[1]}"
      local route="${BASH_REMATCH[2]}"
      local status="${BASH_REMATCH[3]}"
      local status_color="$GREEN"
      if [[ "$status" =~ ^4 ]]; then status_color="$YELLOW"
      elif [[ "$status" =~ ^5 ]]; then status_color="$RED"; fi
      printf '  %s %s%-4s%s %-20s %s%s%s\n' "$tag" "$DIM" "$method" "$NC" "$route" "$status_color" "$status" "$NC"
    # structlog lines (already have ANSI colors)
    elif [[ "$line" == *"│"* ]]; then
      printf '  %s %s\n' "$tag" "$line"
    # Important lifecycle/error lines
    elif [[ "$line" == *"Running"* ]] || \
         [[ "$line" == *"Started"* ]] || \
         [[ "$line" == *"Listening"* ]] || \
         [[ "$line" == *"[WARNING]"* ]] || \
         [[ "$line" == *"[ERROR]"* ]]; then
      printf '  %s %s\n' "$tag" "$line"
    fi
  done
}

# ── Start agents ─────────────────────────────────────────
if [[ "$NO_AGENTS" == false ]]; then
  for (( i=0; i<NUM_AGENTS; i++ )); do
    label=$(agent_label "$i")
    color=$(agent_color "$i")
    p2p_port=$((9000 + i * 100))
    ws_port=$((9001 + i * 100))
    api_port=$((8080 + i))
    tag="${color}[${label}]${NC}"

    # First agent uses default identity path; others use identity{N}.key
    identity_args=""
    if (( i > 0 )); then
      identity_args="--identity-path ~/.agentic-payments/identity$((i + 1)).key"
    fi

    echo "  ${color}[agent-${label,,}]${NC} Starting on ports ${p2p_port}/${ws_port}/${api_port}..."

    # shellcheck disable=SC2086
    uv run agentpay start \
      --port "$p2p_port" --ws-port "$ws_port" --api-port "$api_port" \
      --log-level INFO \
      $identity_args \
      2>&1 | filter_agent_log "$tag" &
    PIPE_PID=$!
    CHILD_PIDS+=("$PIPE_PID")

    sleep 0.5

    # Track the actual agentpay process too
    AGENT_PID=$(pgrep -f "agentpay start --port $p2p_port" 2>/dev/null | head -1 || true)
    if [[ -n "$AGENT_PID" ]]; then
      CHILD_PIDS+=("$AGENT_PID")
    fi

    # Small delay between agents so identity files don't collide
    if (( i < NUM_AGENTS - 1 )); then
      sleep 1
    fi
  done

  sleep 1
  echo ""
fi

# ── Start frontend ───────────────────────────────────────
echo "${PURPLE}[frontend]${NC} Starting Next.js on port 3000..."
cd "$ROOT/frontend"

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

# ── Summary ──────────────────────────────────────────────
echo ""
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${GREEN}  All services started!${NC}"
echo ""
if [[ "$NO_AGENTS" == false ]]; then
  for (( i=0; i<NUM_AGENTS; i++ )); do
    label=$(agent_label "$i")
    color=$(agent_color "$i")
    api_port=$((8080 + i))
    echo "  Agent ${label} API:  ${color}http://127.0.0.1:${api_port}${NC}"
  done
fi
echo "  Dashboard:    ${PURPLE}http://localhost:3000${NC}"
echo ""
echo "  Press ${RED}Ctrl+C${NC} to stop all services."
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Wait for all background processes
wait
