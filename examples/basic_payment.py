"""Basic payment example: two agents, one payment channel, three micropayments."""

from __future__ import annotations

import structlog
import trio

from agentic_payments.config import Settings
from agentic_payments.node.agent_node import AgentNode

structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(structlog.get_level_from_name("INFO")),
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger("example")


async def run_two_agents() -> None:
    """Start two agent nodes and perform a basic payment flow."""
    # Agent A config (payer)
    config_a = Settings()
    config_a.node.port = 9000
    config_a.api.port = 8080

    # Agent B config (payee)
    config_b = Settings()
    config_b.node.port = 9100
    config_b.api.port = 8081

    async with trio.open_nursery() as nursery:
        agent_a = AgentNode(config_a)
        agent_b = AgentNode(config_b)

        # Start both agents
        nursery.start_soon(agent_a.start, nursery)
        await trio.sleep(1)
        nursery.start_soon(agent_b.start, nursery)
        await trio.sleep(1)

        # Agent A connects to Agent B
        b_addr = agent_b.listen_addrs[0] + f"/p2p/{agent_b.peer_id.to_base58()}"
        await agent_a.connect(b_addr)
        logger.info("agents_connected")

        # Open a payment channel: A → B, deposit 1 ETH
        channel = await agent_a.open_payment_channel(
            peer_id=agent_b.peer_id.to_base58(),
            receiver=agent_b.wallet.address,
            deposit=1_000_000_000_000_000_000,  # 1 ETH in wei
        )
        logger.info("channel_opened", channel_id=channel.channel_id.hex()[:16])

        # Send 3 micropayments
        for i in range(1, 4):
            amount = 100_000_000_000_000_000  # 0.1 ETH
            voucher = await agent_a.pay(channel.channel_id, amount)
            logger.info(
                "payment_sent",
                nonce=voucher.nonce,
                cumulative=voucher.amount,
                remaining=channel.remaining_balance,
            )
            await trio.sleep(0.5)

        # Close the channel
        await agent_a.close_channel(channel.channel_id)
        logger.info("channel_closed", total_paid=channel.total_paid)

        # Shutdown
        nursery.cancel_scope.cancel()


if __name__ == "__main__":
    trio.run(run_two_agents)
