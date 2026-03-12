"""x402 Resource Gateway for Bazaar-compatible resource listing."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class GatedResource:
    """A resource gated behind payment."""

    path: str  # API path, e.g. "/api/v1/inference"
    price: int  # Wei per call
    description: str = ""
    payment_type: str = "payment-channel"  # or "htlc", "x402"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "price": self.price,
            "description": self.description,
            "payment_type": self.payment_type,
        }

    @staticmethod
    def from_dict(d: dict) -> GatedResource:
        return GatedResource(
            path=d["path"],
            price=d["price"],
            description=d.get("description", ""),
            payment_type=d.get("payment_type", "payment-channel"),
        )


class X402Gateway:
    """Manages gated resources and publishes them in Bazaar format."""

    def __init__(self, provider_id: str = "", wallet_address: str = "") -> None:
        self.provider_id = provider_id
        self.wallet_address = wallet_address
        self._resources: dict[str, GatedResource] = {}  # path -> resource

    def register_resource(self, resource: GatedResource) -> None:
        """Register a gated resource."""
        self._resources[resource.path] = resource
        logger.info("resource_registered", path=resource.path, price=resource.price)

    def unregister_resource(self, path: str) -> None:
        """Remove a gated resource."""
        self._resources.pop(path, None)

    def list_resources(self) -> list[GatedResource]:
        """List all gated resources."""
        return list(self._resources.values())

    def get_resource(self, path: str) -> GatedResource | None:
        """Get a resource by path."""
        return self._resources.get(path)

    def to_bazaar_format(self) -> dict:
        """Export resources in Algorand x402 Bazaar-compatible format."""
        return {
            "provider": {
                "id": self.provider_id,
                "wallet": self.wallet_address,
                "protocol": "agentpay",
            },
            "resources": [
                {
                    "path": r.path,
                    "price": r.price,
                    "description": r.description,
                    "payment_types": [r.payment_type],
                    "x402_compatible": r.payment_type == "x402",
                }
                for r in self._resources.values()
            ],
        }
