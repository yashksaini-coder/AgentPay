"""Typer CLI entrypoint for agentic-payments."""

from __future__ import annotations

from pathlib import Path

import structlog
import trio
import typer

app = typer.Typer(
    name="agentpay",
    help="Agentic Payments over libp2p — P2P payment framework for AI agents.",
)

identity_app = typer.Typer(help="Manage node identity.")
peer_app = typer.Typer(help="Manage peer connections.")
channel_app = typer.Typer(help="Manage payment channels.")

app.add_typer(identity_app, name="identity")
app.add_typer(peer_app, name="peer")
app.add_typer(channel_app, name="channel")


def _setup_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog with color-coded output.

    Uses ANSI colors inspired by Wireshark-style log output:
    - Timestamps: dim gray
    - Level: colored per severity (green/cyan/yellow/red/bold red)
    - Logger name: dim
    - Event: bright white
    - Key-value pairs: colored by type
    """
    import logging
    import sys

    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    if fmt == "console" and sys.stderr.isatty():
        renderer = _ColorRenderer()
    elif fmt == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="%H:%M:%S.%f"),
            _abbreviate_logger_name,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# ── ANSI escape helpers ────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_ITALIC = "\033[3m"

_FG_BLACK = "\033[30m"
_FG_RED = "\033[31m"
_FG_GREEN = "\033[32m"
_FG_YELLOW = "\033[33m"
_FG_BLUE = "\033[34m"
_FG_MAGENTA = "\033[35m"
_FG_CYAN = "\033[36m"
_FG_WHITE = "\033[37m"
_FG_BRIGHT_RED = "\033[91m"
_FG_BRIGHT_GREEN = "\033[92m"
_FG_BRIGHT_YELLOW = "\033[93m"
_FG_BRIGHT_CYAN = "\033[96m"
_FG_BRIGHT_WHITE = "\033[97m"

_BG_RED = "\033[41m"
_BG_YELLOW = "\033[43m"

_LEVEL_STYLES: dict[str, str] = {
    "debug": f"{_DIM}{_FG_CYAN}",
    "info": f"{_FG_BRIGHT_GREEN}",
    "warning": f"{_BOLD}{_FG_BRIGHT_YELLOW}",
    "error": f"{_BOLD}{_FG_BRIGHT_RED}",
    "critical": f"{_BOLD}{_BG_RED}{_FG_WHITE}",
}

# Event name keywords → highlight color
_EVENT_HIGHLIGHTS: dict[str, str] = {
    "payment": _FG_BRIGHT_GREEN,
    "channel": _FG_BRIGHT_CYAN,
    "htlc": _FG_BRIGHT_YELLOW,
    "peer": _FG_BLUE,
    "error": _FG_BRIGHT_RED,
    "started": _FG_BRIGHT_GREEN,
    "stopped": _FG_RED,
    "route": _FG_MAGENTA,
    "voucher": _FG_GREEN,
    "stream": _FG_CYAN,
    "pubsub": _FG_BLUE,
}


def _abbreviate_logger_name(
    logger: object, method_name: str, event_dict: dict,
) -> dict:
    """Shorten module paths: agentic_payments.node.agent_node → node.agent_node."""
    if "_logger" in event_dict:
        name = str(event_dict["_logger"])
        name = name.replace("agentic_payments.", "")
        event_dict["_logger"] = name
    return event_dict


class _ColorRenderer:
    """Custom structlog renderer with Wireshark-inspired color-coded output.

    Format: HH:MM:SS.fff │ LEVEL    module          event_name  key=value key=value
    """

    def __call__(self, logger: object, method_name: str, event_dict: dict) -> str:
        # Extract standard fields
        ts = event_dict.pop("timestamp", "")
        level = event_dict.pop("log_level", method_name)
        event = event_dict.pop("event", "")
        logger_name = event_dict.pop("_logger", "")

        # Timestamp — dim
        ts_str = f"{_DIM}{ts[:12]}{_RESET}" if ts else ""

        # Level — colored, padded
        level_upper = level.upper()
        level_style = _LEVEL_STYLES.get(level, _FG_WHITE)
        level_str = f"{level_style}{level_upper:<8}{_RESET}"

        # Logger name — dim, truncated
        mod = str(logger_name)[-20:] if logger_name else ""
        mod_str = f"{_DIM}{mod:<20}{_RESET}" if mod else ""

        # Event name — highlight if it contains a known keyword
        event_style = _FG_BRIGHT_WHITE
        event_lower = str(event).lower()
        for keyword, style in _EVENT_HIGHLIGHTS.items():
            if keyword in event_lower:
                event_style = style
                break
        event_str = f"{event_style}{_BOLD}{event}{_RESET}"

        # Key-value pairs — colored by type
        kv_parts = []
        for k, v in event_dict.items():
            if k.startswith("_"):
                continue
            val = _format_value(v)
            kv_parts.append(f"{_DIM}{k}={_RESET}{_FG_CYAN}{val}{_RESET}")

        kv_str = "  ".join(kv_parts)

        # Assemble
        parts = [ts_str, "│", level_str, mod_str, event_str]
        if kv_str:
            parts.append(f" {kv_str}")

        return " ".join(p for p in parts if p)


def _format_value(v: object) -> str:
    """Format a log value for display."""
    if isinstance(v, bytes):
        return v.hex()[:16] + ("…" if len(v) > 8 else "")
    if isinstance(v, str) and len(v) > 40:
        return v[:37] + "..."
    if isinstance(v, list) and len(v) > 3:
        return f"[{len(v)} items]"
    return str(v)


@app.command()
def start(
    port: int = typer.Option(9000, help="TCP listen port"),
    ws_port: int = typer.Option(9001, help="WebSocket listen port"),
    api_port: int = typer.Option(8080, help="REST API port"),
    eth_rpc: str = typer.Option("http://localhost:8545", help="Ethereum RPC URL"),
    log_level: str = typer.Option("INFO", help="Log level"),
    identity_path: Path = typer.Option(
        Path("~/.agentic-payments/identity.key"), help="Identity key file"
    ),
) -> None:
    """Start an agent node."""
    _setup_logging(level=log_level)
    logger = structlog.get_logger("cli")

    from agentic_payments.config import Settings
    from agentic_payments.node.agent_node import AgentNode

    settings = Settings()
    settings.node.port = port
    settings.node.ws_port = ws_port
    settings.node.identity_path = identity_path
    settings.api.port = api_port
    settings.ethereum.rpc_url = eth_rpc

    async def run() -> None:
        async with trio.open_nursery() as nursery:
            node = AgentNode(settings)
            await node.start(nursery)

    logger.info("starting_agent_node", port=port, api_port=api_port)
    try:
        trio.run(run)
    except KeyboardInterrupt:
        logger.info("shutting_down")


@identity_app.command("generate")
def identity_generate(
    path: Path = typer.Option(Path("~/.agentic-payments/identity.key"), help="Output path"),
) -> None:
    """Generate a new node identity."""
    _setup_logging()
    from agentic_payments.node.identity import generate_identity, save_identity

    key_pair = generate_identity()
    save_identity(key_pair, path)

    from agentic_payments.node.identity import peer_id_from_keypair

    pid = peer_id_from_keypair(key_pair)
    typer.echo(f"PeerID: {pid.to_base58()}")
    typer.echo(f"Saved to: {path.expanduser()}")


@identity_app.command("show")
def identity_show(
    path: Path = typer.Option(Path("~/.agentic-payments/identity.key"), help="Identity key file"),
) -> None:
    """Show node identity info."""
    _setup_logging()
    from agentic_payments.node.identity import load_identity, peer_id_from_keypair

    key_pair = load_identity(path)
    pid = peer_id_from_keypair(key_pair)
    typer.echo(f"PeerID: {pid.to_base58()}")
    typer.echo(f"Key file: {path.expanduser()}")


@peer_app.command("list")
def peer_list(
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """List discovered peers."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"{api_url}/peers") as resp:
            data = json.loads(resp.read())
            if data["count"] == 0:
                typer.echo("No peers discovered.")
            else:
                for peer in data["peers"]:
                    typer.echo(f"  {peer['peer_id']}  {peer.get('addrs', [])}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@peer_app.command("connect")
def peer_connect(
    multiaddr: str = typer.Argument(help="Peer multiaddr (e.g., /ip4/.../p2p/QmPeer)"),
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """Connect to a peer by multiaddr."""
    typer.echo(f"Connecting to {multiaddr}...")
    typer.echo("(Direct CLI connect requires a running node — use the API)")


@channel_app.command("open")
def channel_open(
    peer: str = typer.Option(..., help="Peer ID"),
    deposit: int = typer.Option(..., help="Deposit amount in wei"),
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """Open a payment channel with a peer."""
    import json
    import urllib.request

    payload = json.dumps({"peer_id": peer, "receiver": "", "deposit": deposit}).encode()
    req = urllib.request.Request(
        f"{api_url}/channels",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            typer.echo(f"Channel opened: {data['channel']['channel_id']}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@channel_app.command("close")
def channel_close(
    channel: str = typer.Option(..., help="Channel ID (hex)"),
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """Close a payment channel."""
    typer.echo(f"Closing channel {channel}...")
    typer.echo("(Use the REST API for channel close)")


@app.command()
def pay(
    channel: str = typer.Option(..., help="Channel ID (hex)"),
    amount: int = typer.Option(..., help="Payment amount in wei"),
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """Send a micropayment on a channel."""
    import json
    import urllib.request

    payload = json.dumps({"channel_id": channel, "amount": amount}).encode()
    req = urllib.request.Request(
        f"{api_url}/pay",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            typer.echo(f"Payment sent. Nonce: {data['voucher']['nonce']}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def balance(
    api_url: str = typer.Option("http://127.0.0.1:8080", help="API URL"),
) -> None:
    """Check balances across all channels."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"{api_url}/balance") as resp:
            data = json.loads(resp.read())
            typer.echo(f"Address:    {data['address']}")
            typer.echo(f"Deposited:  {data['total_deposited']} wei")
            typer.echo(f"Paid:       {data['total_paid']} wei")
            typer.echo(f"Remaining:  {data['total_remaining']} wei")
            typer.echo(f"Channels:   {data['channel_count']}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def simulate(
    agents: int = typer.Option(3, "--agents", "-n", help="Number of agents (2-20)"),
    topology: str = typer.Option("ring", help="Topology: ring, mesh, or random"),
    deposit: int = typer.Option(5_000_000, help="Deposit per channel in wei"),
    rounds: int = typer.Option(20, "--rounds", "-r", help="Number of payment rounds"),
    min_pay: int = typer.Option(10_000, help="Minimum payment amount in wei"),
    max_pay: int = typer.Option(500_000, help="Maximum payment amount in wei"),
    concurrency: int = typer.Option(5, help="Max concurrent payments per batch"),
    base_port: int = typer.Option(8080, help="Base API port (agents use base+0, base+1, ...)"),
    spawn: bool = typer.Option(True, help="Auto-spawn agent processes (requires dev.sh or manual start if false)"),
) -> None:
    """Run a payment simulation across multiple agents (like the UI simulation panel)."""
    import json
    import os
    import random
    import subprocess
    import urllib.error
    import urllib.request

    _setup_logging(level="INFO")

    if agents < 2 or agents > 20:
        typer.echo("Error: --agents must be between 2 and 20", err=True)
        raise typer.Exit(1)
    if topology not in ("ring", "mesh", "random"):
        typer.echo("Error: --topology must be ring, mesh, or random", err=True)
        raise typer.Exit(1)
    if min_pay > max_pay:
        typer.echo("Error: --min-pay must be <= --max-pay", err=True)
        raise typer.Exit(1)

    # ── Helpers ──────────────────────────────────────────────────
    def api(port: int, path: str, data: dict | None = None) -> dict:
        """Make an API call to an agent."""
        url = f"http://127.0.0.1:{port}{path}"
        if data is not None:
            payload = json.dumps(data).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def probe(port: int) -> bool:
        """Check if an agent is alive on a port."""
        try:
            r = api(port, "/health")
            return r.get("status") == "ok"
        except Exception:
            return False

    import time

    project_root = Path(__file__).resolve().parent.parent.parent
    spawned_procs: list[subprocess.Popen] = []

    def cleanup_procs() -> None:
        for proc in spawned_procs:
            try:
                proc.terminate()
            except OSError:
                pass
        for proc in spawned_procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    # ── Phase 1: Ensure agents are running ──────────────────────
    typer.echo(f"\n{'━' * 50}")
    typer.echo("  AgentPay Simulation")
    typer.echo(f"  {agents} agents • {topology} topology • {rounds} rounds")
    typer.echo(f"{'━' * 50}\n")

    ports: list[int] = [base_port + i for i in range(agents)]

    if spawn:
        typer.echo("[spawn] Starting agent processes...")
        for i, api_port in enumerate(ports):
            if probe(api_port):
                typer.echo(f"  Agent {i} (:{api_port}) already running")
                continue

            p2p_port = 9000 + i * 100
            ws_port = 9001 + i * 100
            identity_idx = api_port - 8080
            identity_file = (
                "identity.key" if identity_idx == 0
                else f"identity{identity_idx + 1}.key"
            )
            identity_path = os.path.expanduser(f"~/.agentic-payments/{identity_file}")

            proc = subprocess.Popen(
                [
                    "uv", "run", "agentpay", "start",
                    "--port", str(p2p_port),
                    "--ws-port", str(ws_port),
                    "--api-port", str(api_port),
                    "--identity-path", identity_path,
                    "--log-level", "WARNING",
                ],
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            spawned_procs.append(proc)
            typer.echo(f"  Agent {i} (:{api_port}) spawned (PID {proc.pid})")
            time.sleep(0.8)

        # Wait for all agents to come online
        typer.echo("[spawn] Waiting for agents to come online...")
        deadline = time.time() + 20
        while time.time() < deadline:
            online = sum(1 for p in ports if probe(p))
            if online >= agents:
                break
            time.sleep(1)

        online = sum(1 for p in ports if probe(p))
        if online < 2:
            typer.echo(f"Error: Only {online} agents online, need at least 2", err=True)
            cleanup_procs()
            raise typer.Exit(1)
        typer.echo(f"  {online}/{agents} agents online\n")
    else:
        online = sum(1 for p in ports if probe(p))
        if online < 2:
            typer.echo(f"Error: Only {online} agents found on ports {ports}. Start agents first.", err=True)
            raise typer.Exit(1)
        typer.echo(f"[check] {online}/{agents} agents online\n")

    # Get identity info for all online agents
    agent_info: list[dict] = []
    for p in ports:
        if probe(p):
            try:
                ident = api(p, "/identity")
                ident["_port"] = p
                agent_info.append(ident)
            except Exception:
                pass

    if len(agent_info) < 2:
        typer.echo("Error: Could not get identity for enough agents", err=True)
        cleanup_procs()
        raise typer.Exit(1)

    # ── Phase 2: Build topology and open channels ───────────────
    typer.echo(f"[connect] Building {topology} topology...")

    # Build index pairs
    n = len(agent_info)
    pairs: list[tuple[int, int]] = []

    if topology == "ring":
        for i in range(n):
            pairs.append((i, (i + 1) % n))
    elif topology == "mesh":
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((i, j))
    else:  # random
        seen: set[str] = set()
        for i in range(n):
            k = random.randint(1, min(2, n - 1))
            for _ in range(k):
                j = random.randint(0, n - 1)
                while j == i:
                    j = random.randint(0, n - 1)
                key = f"{min(i, j)}-{max(i, j)}"
                if key not in seen:
                    seen.add(key)
                    pairs.append((i, j))

    typer.echo(f"  {len(pairs)} channel pairs to open")

    # Connect peers and open channels
    opened = 0
    for si, ri in pairs:
        sender = agent_info[si]
        receiver = agent_info[ri]
        s_port = sender["_port"]

        # Resolve receiver multiaddr
        addrs = receiver.get("addrs", [])
        tcp_addr = next((a for a in addrs if "/tcp/" in a and "/ws" not in a), None)
        if not tcp_addr:
            continue
        tcp_addr = tcp_addr.replace("/ip4/0.0.0.0/", "/ip4/127.0.0.1/")
        if "/p2p/" not in tcp_addr:
            tcp_addr = f"{tcp_addr}/p2p/{receiver['peer_id']}"

        # Connect
        try:
            api(s_port, "/connect", {"multiaddr": tcp_addr})
        except Exception:
            pass

        # Open channel
        try:
            api(s_port, "/channels", {
                "peer_id": receiver["peer_id"],
                "receiver": receiver["eth_address"],
                "deposit": deposit,
            })
            opened += 1
            typer.echo(f"  [{opened}/{len(pairs)}] Agent {si} → Agent {ri} ({deposit:,} wei)")
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            typer.echo(f"  [skip] Agent {si} → Agent {ri}: {body[:80]}")
        except Exception as e:
            typer.echo(f"  [skip] Agent {si} → Agent {ri}: {e}")

    typer.echo(f"  {opened} channels opened\n")

    if opened == 0:
        typer.echo("Error: No channels opened. Cannot simulate.", err=True)
        cleanup_procs()
        raise typer.Exit(1)

    # Brief pause for channels to settle
    time.sleep(1)

    # ── Phase 3: Run payments ───────────────────────────────────
    typer.echo(f"[simulate] Running {rounds} payment rounds...")

    ok_count = 0
    fail_count = 0

    # Refresh channel data
    def get_channels(port: int) -> list[dict]:
        try:
            data = api(port, "/channels")
            return data.get("channels", [])
        except Exception:
            return []

    for r in range(rounds):
        amount = random.randint(min_pay, max_pay)

        # Pick a random sender with an active outbound channel that has balance
        random.shuffle(agent_info)
        sent = False

        for sender in agent_info:
            s_port = sender["_port"]
            channels = get_channels(s_port)
            eligible = [
                c for c in channels
                if c.get("state") == "ACTIVE"
                and c.get("sender") == sender["eth_address"]
                and c.get("remaining_balance", 0) > amount
            ]
            if not eligible:
                continue

            # 60% direct, 40% routed
            use_direct = random.random() < 0.6 or len(agent_info) <= 2

            if use_direct:
                ch = random.choice(eligible)
                try:
                    api(s_port, "/pay", {"channel_id": ch["channel_id"], "amount": amount})
                    ok_count += 1
                    sent = True
                except Exception:
                    fail_count += 1
                    sent = True
            else:
                # Pick a random receiver that isn't the sender
                others = [a for a in agent_info if a["peer_id"] != sender["peer_id"]]
                if not others:
                    continue
                receiver = random.choice(others)
                try:
                    api(s_port, "/route-pay", {
                        "destination": receiver["peer_id"],
                        "amount": amount,
                    })
                    ok_count += 1
                    sent = True
                except Exception:
                    fail_count += 1
                    sent = True
            break

        if not sent:
            fail_count += 1

        total = r + 1
        if total % 10 == 0 or total == rounds:
            typer.echo(f"  [{total}/{rounds}] {ok_count} ok, {fail_count} fail")

    # ── Summary ─────────────────────────────────────────────────
    typer.echo(f"\n{'━' * 50}")
    typer.echo("  Simulation Complete")
    typer.echo(f"  {ok_count} ok / {fail_count} fail / {rounds} total")
    success_rate = (ok_count / rounds * 100) if rounds > 0 else 0
    typer.echo(f"  Success rate: {success_rate:.1f}%")
    typer.echo(f"{'━' * 50}\n")

    # Cleanup spawned processes if we started them
    if spawned_procs:
        typer.echo("[cleanup] Stopping spawned agents...")
        cleanup_procs()
        typer.echo("  Done.\n")


if __name__ == "__main__":
    app()
