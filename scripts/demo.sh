#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  AgentPay — Automated API Demo Script
#
#  Exercises the full payment lifecycle via curl while you
#  screen-record. Designed to run alongside ./scripts/dev.sh.
#
#  Usage:
#    # Terminal 1 — start agents + frontend
#    ./scripts/dev.sh --agents 3
#
#    # Terminal 2 — run demo (wait ~10s for agents to boot)
#    ./scripts/demo.sh
#
#  Optional flags:
#    --agents N       Number of agents (default: 3)
#    --speed slow     Longer pauses between steps (default: normal)
#    --skip-cleanup   Don't close channels at the end
# ─────────────────────────────────────────────────────────

set -euo pipefail

# ── Config ──────────────────────────────────────────────
NUM_AGENTS=3
SPEED="normal"
SKIP_CLEANUP=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agents)     NUM_AGENTS="${2:?}"; shift 2 ;;
    --agents=*)   NUM_AGENTS="${1#*=}"; shift ;;
    --speed)      SPEED="${2:?}"; shift 2 ;;
    --skip-cleanup) SKIP_CLEANUP=true; shift ;;
    *)            echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

# ── Colors & Helpers ────────────────────────────────────
GREEN=$'\033[0;32m'
BLUE=$'\033[0;34m'
CYAN=$'\033[0;36m'
YELLOW=$'\033[1;33m'
PURPLE=$'\033[0;35m'
RED=$'\033[0;31m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'

pause() {
  case "$SPEED" in
    slow) sleep "${1:-3}" ;;
    *)    sleep "${2:-1.5}" ;;
  esac
}

step() {
  echo ""
  echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo "${PURPLE}  $1${NC}"
  echo "${PURPLE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  pause 3 1.5
}

api() {
  local port=$1; shift
  curl -s "http://127.0.0.1:${port}$@"
}

api_post() {
  local port=$1; shift
  local path=$1; shift
  curl -s -X POST "http://127.0.0.1:${port}${path}" \
    -H "Content-Type: application/json" \
    "$@"
}

pretty() {
  python3 -m json.tool 2>/dev/null || cat
}

label() {
  printf "%s" "$(printf "\\x$(printf '%02x' $((65 + $1)))")"
}

# ── Banner ──────────────────────────────────────────────
clear
echo ""
echo "${BOLD}${PURPLE}"
echo "    ╔═══════════════════════════════════════════╗"
echo "    ║         AgentPay — Live API Demo          ║"
echo "    ║   P2P Micropayments for AI Agents         ║"
echo "    ╚═══════════════════════════════════════════╝"
echo "${NC}"
echo "  ${DIM}Agents: ${NUM_AGENTS}  |  Speed: ${SPEED}  |  $(date +%H:%M:%S)${NC}"
echo ""
pause 4 2

# ════════════════════════════════════════════════════════
# PHASE 1: Discovery
# ════════════════════════════════════════════════════════

step "PHASE 1 — Agent Discovery"

echo "${CYAN}  Checking which agents are online...${NC}"
echo ""

for (( i=0; i<NUM_AGENTS; i++ )); do
  port=$((8080 + i))
  l=$(label $i)
  echo -n "  ${GREEN}[Agent ${l}]${NC} "
  identity=$(api "$port" /identity)
  peer_id=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['peer_id'])" 2>/dev/null)
  eth_addr=$(echo "$identity" | python3 -c "import sys,json; print(json.load(sys.stdin)['eth_address'])" 2>/dev/null)
  echo "PeerID: ${BLUE}${peer_id:0:16}...${NC}  ETH: ${YELLOW}${eth_addr:0:10}...${NC}  Port: ${port}"

  # Store for later use
  eval "PEER_${i}=${peer_id}"
  eval "ETH_${i}=${eth_addr}"
done

pause 3 2

echo ""
echo "${CYAN}  Checking peer discovery (mDNS)...${NC}"
echo ""

for (( i=0; i<NUM_AGENTS; i++ )); do
  port=$((8080 + i))
  l=$(label $i)
  count=$(api "$port" /peers | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
  echo "  ${GREEN}[Agent ${l}]${NC} Discovered ${BOLD}${count}${NC} peers"
done

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 2: Open Payment Channels
# ════════════════════════════════════════════════════════

step "PHASE 2 — Opening Payment Channels"

CHANNELS=()

# Open channels: A→B, B→C (and A→C if 3+ agents)
open_channel() {
  local from_idx=$1 to_idx=$2 deposit=$3
  local from_port=$((8080 + from_idx))
  local from_label=$(label $from_idx)
  local to_label=$(label $to_idx)
  eval "local to_peer=\$PEER_${to_idx}"
  eval "local to_eth=\$ETH_${to_idx}"

  echo "  ${GREEN}[${from_label} → ${to_label}]${NC} Opening channel with deposit ${YELLOW}${deposit}${NC} wei..."

  result=$(api_post "$from_port" /channels \
    -d "{\"peer_id\":\"${to_peer}\",\"receiver\":\"${to_eth}\",\"deposit\":${deposit}}")

  channel_id=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['channel']['channel_id'])" 2>/dev/null)

  if [[ -n "$channel_id" ]]; then
    echo "  ${GREEN}  ✓${NC} Channel: ${DIM}${channel_id:0:16}...${NC}"
    CHANNELS+=("$channel_id:$from_idx")
  else
    echo "  ${RED}  ✗${NC} Failed: $(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','unknown'))" 2>/dev/null)"
  fi
  pause 2 1
}

open_channel 0 1 1000000    # A → B, 1M wei
open_channel 1 2 1000000    # B → C, 1M wei
if (( NUM_AGENTS >= 3 )); then
  open_channel 0 2 500000   # A → C, 500K wei
fi

pause 3 2

echo ""
echo "${CYAN}  Channel summary:${NC}"
for (( i=0; i<NUM_AGENTS; i++ )); do
  port=$((8080 + i))
  l=$(label $i)
  ch_count=$(api "$port" /channels | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
  echo "  ${GREEN}[Agent ${l}]${NC} ${ch_count} channels"
done

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 3: Micropayments
# ════════════════════════════════════════════════════════

step "PHASE 3 — Sending Micropayments"

send_payment() {
  local channel_entry=$1
  local amount=$2
  local channel_id="${channel_entry%%:*}"
  local from_idx="${channel_entry##*:}"
  local from_port=$((8080 + from_idx))
  local from_label=$(label $from_idx)

  echo -n "  ${GREEN}[${from_label}]${NC} Paying ${YELLOW}${amount}${NC} wei → "

  result=$(api_post "$from_port" /pay \
    -d "{\"channel_id\":\"${channel_id}\",\"amount\":${amount}}")

  nonce=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['voucher']['nonce'])" 2>/dev/null)
  cum=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['voucher']['cumulative_amount'])" 2>/dev/null)

  if [[ -n "$nonce" ]]; then
    echo "nonce=${CYAN}${nonce}${NC}  cumulative=${CYAN}${cum}${NC}"
  else
    echo "${RED}failed${NC}"
  fi
  pause 1.5 0.5
}

echo "${CYAN}  Sending a burst of micropayments across channels...${NC}"
echo ""

# Send 3 payments on each channel
for entry in "${CHANNELS[@]}"; do
  for amount in 10000 25000 50000; do
    send_payment "$entry" "$amount"
  done
  echo ""
done

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 4: Balances & Receipts
# ════════════════════════════════════════════════════════

step "PHASE 4 — Balance Check & Receipts"

for (( i=0; i<NUM_AGENTS; i++ )); do
  port=$((8080 + i))
  l=$(label $i)
  bal=$(api "$port" /balance)
  deposited=$(echo "$bal" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_deposited'])" 2>/dev/null)
  paid=$(echo "$bal" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_paid'])" 2>/dev/null)
  remaining=$(echo "$bal" | python3 -c "import sys,json; print(json.load(sys.stdin)['total_remaining'])" 2>/dev/null)
  echo "  ${GREEN}[Agent ${l}]${NC} Deposited: ${YELLOW}${deposited}${NC}  Paid: ${CYAN}${paid}${NC}  Remaining: ${BOLD}${remaining}${NC}"
done

pause 3 2

echo ""
echo "${CYAN}  Receipt chains:${NC}"
receipts=$(api 8080 /receipts)
ch_count=$(echo "$receipts" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
echo "  ${GREEN}[Agent A]${NC} ${ch_count} receipt chains tracked"
echo "$receipts" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ch in data.get('channels', []):
    valid = '✓' if ch['chain_valid'] else '✗'
    print(f\"    {ch['channel_id'][:16]}...  receipts={ch['receipt_count']}  valid={valid}\")
" 2>/dev/null

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 5: Negotiation
# ════════════════════════════════════════════════════════

step "PHASE 5 — Service Negotiation"

echo "${CYAN}  Agent A proposes a compute service to Agent B...${NC}"
echo ""

neg_result=$(api_post 8080 /negotiate \
  -d "{\"peer_id\":\"${PEER_1}\",\"service_type\":\"compute\",\"proposed_price\":5000,\"channel_deposit\":100000,\"sla_terms\":{\"max_latency_ms\":200,\"max_error_rate\":0.05}}")

neg_id=$(echo "$neg_result" | python3 -c "import sys,json; print(json.load(sys.stdin)['negotiation']['negotiation_id'])" 2>/dev/null)

if [[ -n "$neg_id" ]]; then
  echo "  ${GREEN}✓${NC} Negotiation created: ${DIM}${neg_id:0:16}...${NC}"
  echo "    Service: compute  |  Price: 5000 wei  |  SLA: <200ms, <5% errors"

  pause 2 1

  echo ""
  echo "${CYAN}  Agent B counters with a lower price...${NC}"
  counter=$(api_post 8081 "/negotiations/${neg_id}/counter" \
    -d '{"counter_price":3500}')
  echo "  ${GREEN}✓${NC} Counter-proposal: ${YELLOW}3500${NC} wei"

  pause 2 1

  echo ""
  echo "${CYAN}  Agent A accepts the counter...${NC}"
  accept=$(api_post 8080 "/negotiations/${neg_id}/accept")
  echo "  ${GREEN}✓${NC} Negotiation accepted! Terms locked."
else
  echo "  ${YELLOW}⚠${NC} Negotiation skipped (agents may not be connected)"
fi

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 6: Reputation & Trust
# ════════════════════════════════════════════════════════

step "PHASE 6 — Reputation & Trust Scores"

rep=$(api 8080 /reputation)
echo "$rep" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for p in data.get('peers', []):
    pid = p['peer_id'][:16]
    score = p['trust_score']
    txns = p.get('successful_payments', 0) + p.get('failed_payments', 0)
    bar_len = int(score * 20)
    bar = '█' * bar_len + '░' * (20 - bar_len)
    color = '\033[0;32m' if score >= 0.7 else ('\033[1;33m' if score >= 0.4 else '\033[0;31m')
    print(f\"  {pid}...  {color}{bar}\033[0m  {score:.0%}  ({txns} txns)\")
" 2>/dev/null

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 7: Pricing & SLA
# ════════════════════════════════════════════════════════

step "PHASE 7 — Dynamic Pricing & SLA"

echo "${CYAN}  Getting price quote for compute service...${NC}"
quote=$(api_post 8080 /pricing/quote \
  -d "{\"base_price\":10000,\"peer_id\":\"${PEER_1}\"}")
echo "$quote" | python3 -c "
import sys, json
q = json.load(sys.stdin).get('quote', {})
print(f\"  Base: {q.get('base_price', '?')} wei\")
print(f\"  Trust discount: {q.get('trust_discount', 0):.0%}\")
print(f\"  Congestion premium: {q.get('congestion_premium', 0):.0%}\")
print(f\"  Final price: \033[1;33m{q.get('final_price', '?')}\033[0m wei\")
" 2>/dev/null

pause 2 1

echo ""
echo "${CYAN}  SLA monitoring status:${NC}"
sla=$(api 8080 /sla/violations)
violation_count=$(echo "$sla" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
echo "  Violations detected: ${BOLD}${violation_count}${NC}"

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 8: Dispute Scanning
# ════════════════════════════════════════════════════════

step "PHASE 8 — Dispute Detection"

echo "${CYAN}  Scanning all channels for stale vouchers...${NC}"
scan=$(api_post 8080 /disputes/scan)
new_count=$(echo "$scan" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
echo "  New disputes found: ${BOLD}${new_count}${NC}"

all_disputes=$(api 8080 /disputes)
total_disputes=$(echo "$all_disputes" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])" 2>/dev/null)
echo "  Total disputes: ${BOLD}${total_disputes}${NC}"

pause 3 2

# ════════════════════════════════════════════════════════
# PHASE 9: Cleanup
# ════════════════════════════════════════════════════════

if [[ "$SKIP_CLEANUP" == false ]]; then
  step "PHASE 9 — Closing Channels"

  for entry in "${CHANNELS[@]}"; do
    channel_id="${entry%%:*}"
    from_idx="${entry##*:}"
    from_port=$((8080 + from_idx))
    from_label=$(label $from_idx)

    echo -n "  ${GREEN}[${from_label}]${NC} Closing ${DIM}${channel_id:0:16}...${NC} → "
    result=$(api_post "$from_port" "/channels/${channel_id}/close")
    state=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['channel']['state'])" 2>/dev/null)
    echo "${GREEN}${state}${NC}"
    pause 1 0.5
  done
fi

pause 3 2

# ════════════════════════════════════════════════════════
# Summary
# ════════════════════════════════════════════════════════

echo ""
echo "${BOLD}${GREEN}"
echo "    ╔═══════════════════════════════════════════╗"
echo "    ║            Demo Complete!                 ║"
echo "    ╚═══════════════════════════════════════════╝"
echo "${NC}"
echo "  ${DIM}What was demonstrated:${NC}"
echo "    1. ${CYAN}P2P Discovery${NC}     — mDNS auto-discovery, no config"
echo "    2. ${CYAN}Payment Channels${NC}  — Off-chain deposits"
echo "    3. ${CYAN}Micropayments${NC}     — Signed cumulative vouchers"
echo "    4. ${CYAN}Receipt Chains${NC}    — Cryptographic audit trail"
echo "    5. ${CYAN}Negotiation${NC}       — Propose / counter / accept"
echo "    6. ${CYAN}Trust Scoring${NC}     — Reputation from payment history"
echo "    7. ${CYAN}Dynamic Pricing${NC}   — Trust discounts + congestion"
echo "    8. ${CYAN}SLA Monitoring${NC}    — Latency/error thresholds"
echo "    9. ${CYAN}Dispute Detection${NC} — Stale voucher scanning"
echo "   10. ${CYAN}Channel Close${NC}     — Cooperative settlement"
echo ""
echo "  ${DIM}Dashboard: ${PURPLE}http://localhost:3000${NC}"
echo "  ${DIM}Docs:      docs/ARCHITECTURE.md${NC}"
echo ""
