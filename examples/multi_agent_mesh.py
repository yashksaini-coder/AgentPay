"""Multi-agent mesh: N agents discovering and paying each other."""

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
    wrapper_class=structlog.make_filtering_bound_logger(20),
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger("mesh")

NUM_AGENTS = 4
BASE_PORT = 9000
BASE_API_PORT = 8080


async def run_mesh() -> None:
    """Start N agents, connect them in a mesh, and exchange payments."""
    agents: list[AgentNode] = []

    async with trio.open_nursery() as nursery:
        # Start all agents
        for i in range(NUM_AGENTS):
            config = Settings()
            config.node.port = BASE_PORT + i * 100
            config.api.port = BASE_API_PORT + i

            agent = AgentNode(config)
            agents.append(agent)
            nursery.start_soon(agent.start, nursery)
            await trio.sleep(0.5)

        await trio.sleep(2)  # Let all agents start

        # Connect each agent to agent 0 (star topology for simplicity)
        for i in range(1, NUM_AGENTS):
            addr = agents[0].listen_addrs[0] + f"/p2p/{agents[0].peer_id.to_base58()}"
            await agents[i].connect(addr)
            logger.info("connected", from_agent=i, to_agent=0)

        logger.info("mesh_formed", agent_count=NUM_AGENTS)

        # Agent 1 pays Agent 0
        channel = await agents[1].open_payment_channel(
            peer_id=agents[0].peer_id.to_base58(),
            receiver=agents[0].wallet.address,
            deposit=500_000_000_000_000_000,  # 0.5 ETH
        )

        for _ in range(3):
            await agents[1].pay(channel.channel_id, 50_000_000_000_000_000)
            await trio.sleep(0.3)

        await agents[1].close_channel(channel.channel_id)
        logger.info("mesh_payment_complete")

        nursery.cancel_scope.cancel()


if __name__ == "__main__":
    trio.run(run_mesh)
