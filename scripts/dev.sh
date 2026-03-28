#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  AgentPay — Backend development startup
#
#  Starts N agent nodes (backend only).
#  Waits for each agent's /health before proceeding,
#  then connects agents bidirectionally to avoid peer
#  expiry race conditions.
#
#  Frontend runs separately: cd frontend && bun dev
#
#  Usage:
#    ./scripts/dev.sh                # 2 agents (default)
#    ./scripts/dev.sh --agents 3     # 3 agents
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
AGENT_ENABLED=false
AGENT_TICK=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents)
      NUM_AGENTS="${2:?--agents requires a number}"
      shift 2
      ;;
    --agents=*)
      NUM_AGENTS="${1#*=}"
      shift
      ;;
    --agent-enabled)
      AGENT_ENABLED=true
      shift
      ;;
    --agent-tick)
      AGENT_TICK="${2:?--agent-tick requires a number}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: $0 [--agents N] [--agent-enabled] [--agent-tick SECS]" >&2
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

# ── Health-check helper ──────────────────────────────────
wait_for_health() {
  local port=$1 label=$2 max_wait=30
  local elapsed=0
  while (( elapsed < max_wait )); do
    if curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
      echo "  ${GREEN}[${label}]${NC} Ready on port ${port}"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  echo "  ${RED}[${label}]${NC} Failed to start on port ${port}" >&2
  return 1
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
        sleep 1
        waited=$((waited + 1))
      done
      if kill -0 "$pid" 2>/dev/null; then
        echo "  ${RED}→${NC} Force killing PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
  done

  # Final sweep — kill any orphaned agentpay processes
  pkill -9 -f "agentpay start" 2>/dev/null || true

  wait 2>/dev/null || true

  echo "${GREEN}  All processes stopped.${NC}"
  echo ""
}

trap cleanup EXIT INT TERM

# ── Banner ───────────────────────────────────────────────
echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${PURPLE}  AgentPay — Backend Development Server${NC}"
echo "${PURPLE}  Starting ${NUM_AGENTS} agent(s)${NC}"
echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── Dependencies ─────────────────────────────────────────
echo "${BLUE}[setup]${NC} Syncing Python dependencies..."
uv sync --group dev --quiet 2>/dev/null || uv sync --group dev

# ── Log filter ───────────────────────────────────────────
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

    # Agent runtime flags
    agent_args=""
    if [[ "$AGENT_ENABLED" == true ]]; then
      agent_args="--agent-enabled"
      if [[ -n "$AGENT_TICK" ]]; then
        agent_args="$agent_args --agent-tick $AGENT_TICK"
      fi
    fi

    echo "  ${color}[agent-${label,,}]${NC} Starting on ports ${p2p_port}/${ws_port}/${api_port}..."

    # shellcheck disable=SC2086
    uv run agentpay start \
      --port "$p2p_port" --ws-port "$ws_port" --api-port "$api_port" \
      --log-level INFO \
      $identity_args \
      $agent_args \
      2>&1 | filter_agent_log "$tag" &
    PIPE_PID=$!
    CHILD_PIDS+=("$PIPE_PID")

    # Track the actual agentpay process too
    sleep 0.5
    AGENT_PID=$(pgrep -f "agentpay start --port $p2p_port" 2>/dev/null | head -1 || true)
    if [[ -n "$AGENT_PID" ]]; then
      CHILD_PIDS+=("$AGENT_PID")
    fi
done

# ── Wait for all agents to be healthy ──────────────────
echo ""
echo "${BLUE}[setup]${NC} Waiting for agents to become healthy..."
ALL_HEALTHY=true
for (( i=0; i<NUM_AGENTS; i++ )); do
  label=$(agent_label "$i")
  api_port=$((8080 + i))
  if ! wait_for_health "$api_port" "$label"; then
    ALL_HEALTHY=false
  fi
done

if [[ "$ALL_HEALTHY" == false ]]; then
  echo "${RED}  Some agents failed to start. Check logs above.${NC}"
fi

# ── Connect agents bidirectionally ─────────────────────
if [[ "$ALL_HEALTHY" == true ]] && (( NUM_AGENTS > 1 )); then
  echo ""
  echo "${BLUE}[setup]${NC} Connecting agents bidirectionally..."

  for (( i=0; i<NUM_AGENTS; i++ )); do
    for (( j=i+1; j<NUM_AGENTS; j++ )); do
      label_i=$(agent_label "$i")
      label_j=$(agent_label "$j")
      api_i=$((8080 + i))
      api_j=$((8080 + j))

      # Get agent j's multiaddr, connect i→j
      ADDR_J=$(curl -sf "http://127.0.0.1:${api_j}/identity" 2>/dev/null | \
        python3 -c "import sys,json; a=json.load(sys.stdin).get('addrs',[]); print(a[0].replace('0.0.0.0','127.0.0.1') if a else '')" 2>/dev/null || echo "")
      if [[ -n "$ADDR_J" ]]; then
        BODY_J=$(python3 -c "import json,sys; print(json.dumps({'multiaddr':sys.argv[1]}))" "$ADDR_J")
        curl -sf -X POST "http://127.0.0.1:${api_i}/connect" \
          -H "Content-Type: application/json" \
          -d "$BODY_J" >/dev/null 2>&1 || true
        echo "  ${GREEN}${label_i} → ${label_j}${NC} connected"
      fi

      # Get agent i's multiaddr, connect j→i
      ADDR_I=$(curl -sf "http://127.0.0.1:${api_i}/identity" 2>/dev/null | \
        python3 -c "import sys,json; a=json.load(sys.stdin).get('addrs',[]); print(a[0].replace('0.0.0.0','127.0.0.1') if a else '')" 2>/dev/null || echo "")
      if [[ -n "$ADDR_I" ]]; then
        BODY_I=$(python3 -c "import json,sys; print(json.dumps({'multiaddr':sys.argv[1]}))" "$ADDR_I")
        curl -sf -X POST "http://127.0.0.1:${api_j}/connect" \
          -H "Content-Type: application/json" \
          -d "$BODY_I" >/dev/null 2>&1 || true
        echo "  ${GREEN}${label_j} → ${label_i}${NC} connected"
      fi
    done
  done
fi

# ── Summary ──────────────────────────────────────────────
echo ""
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo "${GREEN}  Backend agents started!${NC}"
echo ""
for (( i=0; i<NUM_AGENTS; i++ )); do
  label=$(agent_label "$i")
  color=$(agent_color "$i")
  api_port=$((8080 + i))
  echo "  Agent ${label} API:  ${color}http://127.0.0.1:${api_port}${NC}"
done
echo ""
echo "  ${DIM}Frontend: cd frontend && bun dev${NC}"
echo ""
echo "  Press ${RED}Ctrl+C${NC} to stop all agents."
echo "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Wait for all background processes
wait
