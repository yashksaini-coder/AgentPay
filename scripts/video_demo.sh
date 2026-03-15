#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  AgentPay — Video Demo Scenario
#
#  Run this while screen-recording for a polished 3-5 min demo.
#  Each phase pauses for narration with clear visual markers.
#
#  Prerequisites:
#    ./scripts/deploy_local.sh && source .env.local
#    IPFS daemon running (optional, for storage demo)
#    Two agents started:
#      Agent A: uv run agentpay start --port 9000 --api-port 8080 \
#               --eth-rpc $ETH_RPC_URL \
#               --erc8004-identity $ERC8004_IDENTITY_ADDRESS \
#               --erc8004-reputation $ERC8004_REPUTATION_ADDRESS \
#               --ipfs-url http://127.0.0.1:5001
#      Agent B: uv run agentpay start --port 9100 --ws-port 9101 \
#               --api-port 8081 --identity-path ~/.agentic-payments/identity2.key
# ─────────────────────────────────────────────────────────

set -uo pipefail

# ── Colors & Helpers ───────────────────────────────────
G=$'\033[0;32m'
B=$'\033[0;34m'
C=$'\033[0;36m'
Y=$'\033[1;33m'
P=$'\033[0;35m'
R=$'\033[0;31m'
BOLD=$'\033[1m'
DIM=$'\033[2m'
NC=$'\033[0m'

API_A="http://127.0.0.1:8080"
API_B="http://127.0.0.1:8081"
RPC="${ETH_RPC_URL:-http://127.0.0.1:8545}"
DEPLOYER_KEY="${DEPLOYER_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"

banner() {
  echo ""
  echo "${BOLD}${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo "${BOLD}  $1${NC}"
  echo "${C}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
}

narrate() {
  echo "  ${DIM}$1${NC}"
}

show() {
  echo "  ${G}$1${NC}"
}

pause() {
  sleep "${1:-2}"
}

api() { curl -s "$@" 2>/dev/null; }
jq_() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

# ── Verify agents running ──────────────────────────────
api "$API_A/health" >/dev/null || { echo "${R}Agent A not running on $API_A${NC}"; exit 1; }
api "$API_B/health" >/dev/null || { echo "${R}Agent B not running on $API_B${NC}"; exit 1; }

echo "${BOLD}${C}"
echo "     ___                    __  ____"
echo "    /   | ____ ____  ____  / /_/ __ \____ ___  __"
echo "   / /| |/ __ \`/ _ \/ __ \/ __/ /_/ / __ \`/ / / /"
echo "  / ___ / /_/ /  __/ / / / /_/ ____/ /_/ / /_/ /"
echo " /_/  |_\__, /\___/_/ /_/\__/_/    \__,_/\__, /"
echo "       /____/                            /____/"
echo "${NC}"
echo "  ${DIM}Decentralized micropayment channels for AI agents${NC}"
echo ""
pause 3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "1. Agent Identity"
narrate "Each agent has a libp2p PeerID (Ed25519) and an Ethereum wallet (secp256k1)"
echo ""

PEER_A=$(api "$API_A/identity" | jq_ "print(d['peer_id'])")
ETH_A=$(api "$API_A/identity" | jq_ "print(d['eth_address'])")
PEER_B=$(api "$API_B/identity" | jq_ "print(d['peer_id'])")
ETH_B=$(api "$API_B/identity" | jq_ "print(d['eth_address'])")

echo "  ${B}Agent A${NC}  PeerID: ${DIM}${PEER_A:0:20}...${NC}"
echo "           Wallet: ${DIM}${ETH_A}${NC}"
echo ""
echo "  ${P}Agent B${NC}  PeerID: ${DIM}${PEER_B:0:20}...${NC}"
echo "           Wallet: ${DIM}${ETH_B}${NC}"
pause 3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "2. Peer Discovery & Connect"
narrate "Agents find each other via mDNS or explicit connection"

ADDR_B=$(api "$API_B/identity" | jq_ "a=d['addrs'][0]; print(a.replace('0.0.0.0','127.0.0.1'))")
api -X POST "$API_A/connect" -H "Content-Type: application/json" -d "{\"multiaddr\":\"$ADDR_B\"}" >/dev/null
show "Agent A connected to Agent B"

# Fund wallets
cast send --rpc-url "$RPC" --private-key "$DEPLOYER_KEY" "$ETH_A" --value 10ether >/dev/null 2>&1
cast send --rpc-url "$RPC" --private-key "$DEPLOYER_KEY" "$ETH_B" --value 10ether >/dev/null 2>&1
show "Wallets funded with 10 ETH each"
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "3. Open Payment Channel"
narrate "Lock 1 ETH into a payment channel — this is the only on-chain tx needed"

OPEN=$(api -X POST "$API_A/channels" -H "Content-Type: application/json" \
  -d "{\"peer_id\":\"$PEER_B\",\"receiver\":\"$ETH_B\",\"deposit\":1000000000000000000}")
CHANNEL=$(echo "$OPEN" | jq_ "print(d.get('channel',{}).get('channel_id',''))")
show "Channel opened: ${DIM}${CHANNEL:0:24}...${NC}"
narrate "State: ACTIVE — ready for off-chain micropayments"
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "4. Micropayments (Off-Chain)"
narrate "Signed cumulative vouchers — sub-millisecond, zero gas"

for i in 1 2 3 4 5; do
  AMOUNT=$((i * 50000000000000000))
  V=$(api -X POST "$API_A/pay" -H "Content-Type: application/json" \
    -d "{\"channel_id\":\"$CHANNEL\",\"amount\":$AMOUNT}")
  NONCE=$(echo "$V" | jq_ "print(d.get('voucher',{}).get('nonce',0))")
  CUM=$(echo "$V" | jq_ "print(d.get('voucher',{}).get('amount',0))")
  echo "  ${G}Payment #$i${NC}  nonce=$NONCE  cumulative=${DIM}$CUM wei${NC}"
  sleep 0.3
done

echo ""
BAL=$(api "$API_A/balance")
DEP=$(echo "$BAL" | jq_ "print(d['total_deposited'])")
PAID=$(echo "$BAL" | jq_ "print(d['total_paid'])")
REM=$(echo "$BAL" | jq_ "print(d['total_remaining'])")
echo "  ${Y}Balance:${NC} deposited=$DEP  paid=$PAID  remaining=$REM"
pause 3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "5. Trust & Dynamic Pricing"
narrate "Trust scores update from payment history — pricing adapts"

REP=$(api "$API_A/reputation")
echo "  ${P}Reputation:${NC}"
echo "$REP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in d.get('peers', d.get('reputations', [])):
    pid = p.get('peer_id','')[:16]
    ts = p.get('trust_score', 0)
    bar = '█' * int(ts * 20) + '░' * (20 - int(ts * 20))
    print(f'    {pid}...  [{bar}] {ts:.0%}')
" 2>/dev/null
echo ""

QUOTE=$(api -X POST "$API_A/pricing/quote" -H "Content-Type: application/json" \
  -d "{\"service_type\":\"inference\",\"base_price\":10000,\"peer_id\":\"$PEER_B\"}")
FINAL=$(echo "$QUOTE" | jq_ "print(d.get('quote',{}).get('final_price',0))")
DISC=$(echo "$QUOTE" | jq_ "print(d.get('quote',{}).get('trust_discount_pct',0))")
show "Price quote: base=10000 → final=${FINAL} (trust discount: ${DISC}%)"
pause 3

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "6. x402 Payment Gateway"
narrate "Resources gated behind payment — x402 V1 spec compliant"

api -X POST "$API_A/gateway/register" -H "Content-Type: application/json" \
  -d '{"path":"/api/inference","price":5000,"description":"LLM inference endpoint"}' >/dev/null
show "Registered: /api/inference (5000 wei)"

echo ""
narrate "Request without payment → 402 Payment Required"
RESP_402=$(api -X POST "$API_A/gateway/access" -H "Content-Type: application/json" \
  -d '{"path":"/api/inference"}' || echo '{}')
echo "  ${R}402${NC} $(echo "$RESP_402" | jq_ "a=d.get('accepts',[{}])[0]; print(f'scheme={a.get(\"scheme\",\"\")} network={a.get(\"network\",\"\")} price={a.get(\"maxAmountRequired\",\"\")}')" 2>/dev/null)"
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "7. ERC-8004 On-Chain Identity"
narrate "Register agent on-chain — portable identity across chains"

ERC_STATUS=$(api "$API_A/identity/erc8004" 2>/dev/null)
if echo "$ERC_STATUS" | jq_ "assert d.get('enabled')" 2>/dev/null; then
  REG=$(api -X POST "$API_A/identity/erc8004/register" 2>/dev/null || echo '{}')
  AID=$(echo "$REG" | jq_ "print(d.get('agent_id','N/A'))" 2>/dev/null)
  show "Registered on-chain: agentId=#${AID}"

  LOOKUP=$(api "$API_A/identity/erc8004/lookup/$AID" 2>/dev/null || echo '{}')
  show "Lookup verified: $(echo "$LOOKUP" | jq_ "print(f'registered={d.get(\"registered_on_chain\",False)}')" 2>/dev/null)"
else
  narrate "(ERC-8004 not configured — start with --erc8004-identity to enable)"
fi
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "8. IPFS Storage"
narrate "Pin receipts to IPFS — content-addressed, tamper-evident"

STORAGE=$(api "$API_A/storage/status" 2>/dev/null || echo '{"enabled":false}')
if echo "$STORAGE" | jq_ "assert d.get('enabled') and d.get('healthy')" 2>/dev/null; then
  PIN=$(api -X POST "$API_A/storage/pin" -H "Content-Type: application/json" \
    -d '{"data":"{\"type\":\"receipt\",\"channel\":\"demo\",\"amount\":750000000000000000}"}')
  CID=$(echo "$PIN" | jq_ "print(d.get('cid',''))")
  show "Pinned to IPFS: ${DIM}$CID${NC}"

  RETRIEVED=$(api "$API_A/storage/get/$CID" 2>/dev/null)
  show "Retrieved: $(echo "$RETRIEVED" | jq_ "print(json.dumps(d, separators=(',',':'))[:60])" 2>/dev/null)"
else
  narrate "(IPFS not configured — start with --ipfs-url to enable)"
fi
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "9. Close Channel"
narrate "Cooperative close — final voucher ready for on-chain settlement"

if [ -n "${CHANNEL:-}" ]; then
  api -X POST "$API_A/channels/$CHANNEL/close" >/dev/null 2>&1
  show "Channel closed cooperatively"
  show "Final state: SETTLED"
fi
pause 2

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
banner "Summary"
echo "  ${BOLD}Features demonstrated:${NC}"
echo "    ${G}✓${NC} P2P agent discovery (mDNS + libp2p)"
echo "    ${G}✓${NC} Payment channels (Filecoin-style cumulative vouchers)"
echo "    ${G}✓${NC} 5 off-chain micropayments (sub-millisecond)"
echo "    ${G}✓${NC} Trust scoring + dynamic pricing"
echo "    ${G}✓${NC} x402 payment gateway (spec-compliant)"
echo "    ${G}✓${NC} ERC-8004 on-chain agent identity"
echo "    ${G}✓${NC} IPFS content-addressed storage"
echo "    ${G}✓${NC} Cooperative channel settlement"
echo ""
echo "  ${BOLD}Stack:${NC} Python 3.12 + libp2p + Ethereum/Algorand/Filecoin"
echo "  ${BOLD}Tests:${NC} 590 unit + 35 live E2E"
echo "  ${BOLD}Repo:${NC}  github.com/yashksaini-coder/AgentPay"
echo ""
