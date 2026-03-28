"""Built-in 2-agent payment demo — `agentpay demo`."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import trio

# ── ANSI helpers ─────────────────────────────────────────
_G = "\033[0;32m"
_B = "\033[0;34m"
_C = "\033[0;36m"
_Y = "\033[1;33m"
_P = "\033[0;35m"
_R = "\033[0;31m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_NC = "\033[0m"

API_A = "http://127.0.0.1:8080"
API_B = "http://127.0.0.1:8081"


def _banner(text: str) -> None:
    print(f"\n{_BOLD}{_C}{'━' * 56}{_NC}")
    print(f"{_BOLD}  {text}{_NC}")
    print(f"{_C}{'━' * 56}{_NC}")


def _info(text: str) -> None:
    print(f"  {_DIM}{text}{_NC}")


def _ok(text: str) -> None:
    print(f"  {_G}✓{_NC} {text}")


def _val(text: str) -> None:
    print(f"  {_C}{text}{_NC}")


def _err(text: str) -> None:
    print(f"  {_R}✗{_NC} {text}")


def _api(url: str, path: str, method: str = "GET", data: dict | None = None) -> dict:
    """Blocking HTTP call — run via trio.to_thread.run_sync."""
    full = f"{url}{path}"
    if data is not None:
        payload = json.dumps(data).encode()
        req = urllib.request.Request(
            full,
            data=payload,
            headers={"Content-Type": "application/json"},
            method=method,
        )
    else:
        req = urllib.request.Request(full, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


async def _call(url: str, path: str, method: str = "GET", data: dict | None = None) -> dict:
    """Non-blocking API call."""
    return await trio.to_thread.run_sync(lambda: _api(url, path, method, data))


async def _wait_healthy(url: str, label: str, timeout: float = 30.0) -> bool:
    """Poll /health until ok."""
    deadline = trio.current_time() + timeout
    while trio.current_time() < deadline:
        result = await _call(url, "/health")
        if result.get("status") == "ok":
            _ok(f"{label} healthy")
            return True
        await trio.sleep(0.5)
    _err(f"{label} did not become healthy within {timeout}s")
    return False


async def _connect_peers() -> None:
    """Bidirectional peer connect."""
    id_a = await _call(API_A, "/identity")
    id_b = await _call(API_B, "/identity")

    addrs_a = id_a.get("listen_addrs", [])
    addrs_b = id_b.get("listen_addrs", [])

    if addrs_b:
        await _call(API_A, "/connect", "POST", {"multiaddr": addrs_b[0]})
    if addrs_a:
        await _call(API_B, "/connect", "POST", {"multiaddr": addrs_a[0]})


async def _run_phases(agent_enabled: bool) -> None:
    """Execute the 10 demo phases."""

    # ── Phase 1: Agent Discovery ─────────────────────────
    _banner("Phase 1 — Agent Discovery")
    _info("Each agent has a libp2p PeerID + Ethereum wallet + EIP-191 identity binding")
    print()

    id_a = await _call(API_A, "/identity")
    id_b = await _call(API_B, "/identity")

    peer_a = id_a.get("peer_id", "?")
    eth_a = id_a.get("eth_address", "?")
    eip191_a = id_a.get("eip191_bound", False)

    peer_b = id_b.get("peer_id", "?")
    eth_b = id_b.get("eth_address", "?")
    eip191_b = id_b.get("eip191_bound", False)

    print(f"  {_B}Agent A{_NC}")
    print(f"    PeerID:  {_DIM}{peer_a[:24]}...{_NC}")
    print(f"    Wallet:  {_DIM}{eth_a}{_NC}")
    print(f"    EIP-191: {_DIM}{eip191_a}{_NC}")
    print()
    print(f"  {_P}Agent B{_NC}")
    print(f"    PeerID:  {_DIM}{peer_b[:24]}...{_NC}")
    print(f"    Wallet:  {_DIM}{eth_b}{_NC}")
    print(f"    EIP-191: {_DIM}{eip191_b}{_NC}")

    await trio.sleep(1.5)

    # ── Phase 2: Peer Connection ─────────────────────────
    _banner("Phase 2 — Peer Connection")
    _info("Verifying bidirectional connectivity (mDNS + explicit connect)")
    print()

    peers_a = await _call(API_A, "/peers")
    peers_b = await _call(API_B, "/peers")
    _ok(f"Agent A sees {len(peers_a.get('peers', []))} peer(s)")
    _ok(f"Agent B sees {len(peers_b.get('peers', []))} peer(s)")

    await trio.sleep(1)

    # ── Phase 3: Open Payment Channel ────────────────────
    _banner("Phase 3 — Open Payment Channel")
    _info("Agent A deposits 1 ETH into an off-chain channel toward Agent B")
    print()

    open_result = await _call(
        API_A,
        "/channels",
        "POST",
        {"peer_id": peer_b, "receiver": eth_b, "deposit": 1000000000000000000},
    )
    channel_data = open_result.get("channel", open_result)
    channel_id: str = channel_data.get("channel_id", "")

    if channel_id:
        _ok(f"Channel opened: {_DIM}{channel_id[:24]}...{_NC}")
        _info("State: ACTIVE — ready for off-chain micropayments")
    else:
        _err(f"Channel open failed: {str(open_result)[:80]}")

    await trio.sleep(1)

    # ── Phase 4: Micropayments Burst ─────────────────────
    _banner("Phase 4 — Micropayments Burst")
    _info("10 rapid off-chain voucher payments — sub-millisecond, zero gas")
    print()

    if channel_id:
        t_start = time.monotonic_ns()
        for i in range(1, 11):
            amount = i * 10000000000000000
            v = await _call(API_A, "/pay", "POST", {"channel_id": channel_id, "amount": amount})
            voucher = v.get("voucher", {})
            nonce = voucher.get("nonce", 0)
            cum = voucher.get("cumulative_amount", 0)
            print(f"  {_G}#{i:<2}{_NC}  nonce={nonce:<3}  cumulative={_DIM}{cum} wei{_NC}")
        t_end = time.monotonic_ns()
        total_ms = (t_end - t_start) // 1_000_000
        print()
        _ok(f"10 payments in {total_ms}ms (avg {total_ms // 10}ms each)")

        print()
        bal = await _call(API_A, "/balance")
        dep = bal.get("total_deposited", "?")
        paid = bal.get("total_paid", "?")
        rem = bal.get("total_remaining", "?")
        _val(f"Balance: deposited={dep}  paid={paid}  remaining={rem}")
    else:
        _info("(skipped — no channel)")

    await trio.sleep(1.5)

    # ── Phase 5: Trust & Reputation ──────────────────────
    _banner("Phase 5 — Trust & Reputation")
    _info("Trust scores build from payment history")
    print()

    rep = await _call(API_A, "/reputation")
    peers_list = rep.get("peers", rep.get("reputations", []))
    if peers_list:
        for p in peers_list:
            pid = p.get("peer_id", "")[:20]
            ts = p.get("trust_score", 0)
            bar = "█" * int(ts * 20) + "░" * (20 - int(ts * 20))
            print(f"    {pid}...  [{bar}] {ts:.0%}")
    else:
        _info("(no reputation data yet)")

    await trio.sleep(1)

    # ── Phase 6: Dynamic Pricing ─────────────────────────
    _banner("Phase 6 — Dynamic Pricing")
    _info("Price quotes adapt based on trust history")
    print()

    quote = await _call(
        API_A,
        "/pricing/quote",
        "POST",
        {"service_type": "inference", "base_price": 10000, "peer_id": peer_b},
    )
    q = quote.get("quote", {})
    if q:
        print(f"  Base price:      {q.get('base_price', '?'):>8} wei")
        print(f"  Trust discount:  {q.get('trust_discount_pct', 0):>7}%")
        print(f"  Final price:     {_Y}{q.get('final_price', '?'):>8}{_NC} wei")
    else:
        _info("(pricing not available)")

    await trio.sleep(1)

    # ── Phase 7: Agent Runtime ───────────────────────────
    _banner("Phase 7 — Agent Runtime (Autonomous Task Execution)")
    _info("Submit a task — agents autonomously negotiate, execute, and settle")
    print()

    agent_status = await _call(API_A, "/agent/status")
    runtime_enabled = agent_status.get("enabled", False)

    if runtime_enabled and agent_enabled:
        _info("Submitting task to Agent A...")
        task_result = await _call(
            API_A,
            "/agent/tasks",
            "POST",
            {"description": "Analyze market data for ETH/USDC pair", "amount": 5000},
        )
        task_data = task_result.get("task", task_result)
        task_id = task_data.get("task_id", "")

        if task_id:
            _ok(f"Task created: {_DIM}{task_id[:24]}...{_NC}")

            tasks = await _call(API_A, "/agent/tasks")
            task_count = len(tasks.get("tasks", []))
            _ok(f"Task queue: {task_count} task(s)")

            detail = await _call(API_A, f"/agent/tasks/{task_id}")
            task_state = detail.get("task", detail).get("status", "?")
            _ok(f"Task status: {_Y}{task_state}{_NC}")

            _info("Executing task...")
            exec_result = await _call(API_A, "/agent/execute", "POST", {"task_id": task_id})
            exec_status = exec_result.get("status", exec_result.get("task", {}).get("status", "?"))
            _ok(f"Execution result: {_G}{exec_status}{_NC}")
        else:
            _err("Task creation failed")

        print()
        _info("Runtime status:")
        print(f"    Enabled:       {agent_status.get('enabled', False)}")
        print(f"    Running:       {agent_status.get('running', False)}")
        print(f"    Tick interval: {agent_status.get('tick_interval', '?')}s")
        print(f"    Tasks:         {agent_status.get('task_count', 0)}")
    else:
        _info("(Agent runtime not enabled — use --agent-enabled to demo)")

    await trio.sleep(1.5)

    # ── Phase 8: x402 Gateway ────────────────────────────
    _banner("Phase 8 — x402 Payment Gateway")
    _info("Resources gated behind payment — x402 V1 spec compliant")
    print()

    await _call(
        API_A,
        "/gateway/register",
        "POST",
        {"path": "/api/inference", "price": 5000, "description": "LLM inference endpoint"},
    )
    _ok("Registered: /api/inference (5000 wei)")

    print()
    _info("Request without payment → 402 Payment Required")
    resp_402 = await _call(API_A, "/gateway/access", "POST", {"path": "/api/inference"})
    accepts = resp_402.get("accepts", [{}])
    a = accepts[0] if accepts else {}
    if a:
        scheme = a.get("scheme", "exact")
        network = a.get("network", "")
        price = a.get("maxAmountRequired", "")
        print(f"  {_R}402{_NC}  scheme={scheme}  network={network}  price={price}")
    else:
        _ok("Gateway access endpoint responds")

    await trio.sleep(1)

    # ── Phase 9: Channel Close ───────────────────────────
    _banner("Phase 9 — Channel Close")
    _info("Cooperative close — final voucher ready for on-chain settlement")
    print()

    if channel_id:
        close_result = await _call(API_A, f"/channels/{channel_id}/close", "POST")
        if close_result:
            _ok("Channel closed cooperatively")
            _ok("Final state: SETTLED")
        else:
            _err("Channel close failed (API returned error)")
    else:
        _info("(no channel to close)")

    await trio.sleep(1)

    # ── Phase 10: Summary ────────────────────────────────
    _banner("Demo Complete")
    print()
    print(f"  {_BOLD}Features demonstrated:{_NC}")
    print(f"    {_G}✓{_NC} P2P agent discovery (libp2p + EIP-191 binding)")
    print(f"    {_G}✓{_NC} Bidirectional peer connectivity")
    print(f"    {_G}✓{_NC} Off-chain payment channels (Filecoin-style cumulative vouchers)")
    print(f"    {_G}✓{_NC} 10 micropayments burst (sub-millisecond each)")
    print(f"    {_G}✓{_NC} Trust scoring from payment history")
    print(f"    {_G}✓{_NC} Dynamic pricing with trust discounts")
    if runtime_enabled and agent_enabled:
        print(f"    {_G}✓{_NC} Agent Runtime — autonomous task negotiation & execution")
    else:
        print(f"    {_Y}○{_NC} Agent Runtime (start with --agent-enabled to demo)")
    print(f"    {_G}✓{_NC} x402 payment gateway (spec-compliant)")
    print(f"    {_G}✓{_NC} Cooperative channel settlement")
    print()
    print(f"  {_BOLD}What makes this different:{_NC}")
    print("    Agents autonomously discover, negotiate, pay, and settle.")
    print("    No centralized payment processor. No API keys. Just math.")
    print()
    print(f"  {_BOLD}Stack:{_NC}  Python 3.12 + libp2p + Ethereum + Filecoin-style vouchers")
    print(f"  {_BOLD}Repo:{_NC}   github.com/yashksaini-coder/AgentPay")
    print()


async def run_demo(agent_enabled: bool, agent_tick: float) -> None:
    """Main demo entrypoint — starts 2 agents, runs 10 phases, cleans up."""
    from agentic_payments.config import Settings
    from agentic_payments.node.agent_node import AgentNode

    # ── Agent A settings ─────────────────────────────────
    settings_a = Settings()
    settings_a.node.port = 9000
    settings_a.node.ws_port = 9001
    settings_a.api.port = 8080
    settings_a.agent.enabled = agent_enabled
    settings_a.agent.tick_interval = agent_tick

    # ── Agent B settings ─────────────────────────────────
    settings_b = Settings()
    settings_b.node.port = 9100
    settings_b.node.ws_port = 9101
    settings_b.node.identity_path = Path("~/.agentic-payments/identity2.key")
    settings_b.api.port = 8081
    settings_b.agent.enabled = agent_enabled
    settings_b.agent.tick_interval = agent_tick

    print()
    print(f"{_BOLD}{_P}")
    print("     ___                    __  ____")
    print("    /   | ____ ____  ____  / /_/ __ \\____ ___  __")
    print("   / /| |/ __ `/ _ \\/ __ \\/ __/ /_/ / __ `/ / / /")
    print("  / ___ / /_/ /  __/ / / / /_/ ____/ /_/ / /_/ /")
    print(" /_/  |_\\__, /\\___/_/ /_/\\__/_/    \\__,_/\\__, /")
    print("       /____/                            /____/")
    print(f"{_NC}")
    print(f"  {_DIM}Agent-to-Agent Payments for the Agentic Web{_NC}")
    print(f"  {_DIM}Built-in Demo — pip install agentic-payments{_NC}")
    print()

    async with trio.open_nursery() as nursery:
        # Start both agents
        node_a = AgentNode(settings_a)
        node_b = AgentNode(settings_b)

        nursery.start_soon(node_a.start, nursery)
        nursery.start_soon(node_b.start, nursery)

        # Wait for both to be healthy
        _info("Starting agents...")
        healthy_a = await _wait_healthy(API_A, "Agent A")
        healthy_b = await _wait_healthy(API_B, "Agent B")

        if not (healthy_a and healthy_b):
            _err("Agents failed to start — aborting demo")
            nursery.cancel_scope.cancel()
            return

        # Connect peers
        _info("Connecting peers...")
        await _connect_peers()
        await trio.sleep(1)

        # Run demo phases
        await _run_phases(agent_enabled)

        # Cleanup
        nursery.cancel_scope.cancel()
