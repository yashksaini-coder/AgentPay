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
    """Configure structlog."""
    import logging

    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.dev.ConsoleRenderer()
                if fmt == "console"
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


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


if __name__ == "__main__":
    app()
