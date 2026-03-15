"""ERC-8004 agent identity — on-chain registration and reputation sync."""

from agentic_payments.identity.erc8004 import ERC8004Client
from agentic_payments.identity.bridge import IdentityBridge
from agentic_payments.identity.models import AgentIdentity, AgentRegistrationFile

__all__ = [
    "AgentIdentity",
    "AgentRegistrationFile",
    "ERC8004Client",
    "IdentityBridge",
]
