"""x402 Resource Gateway — payment-gated resource access with Bazaar compatibility.

Implements the x402 payment protocol flow:
1. Client requests a gated resource
2. Server responds with 402 Payment Required + pricing metadata
3. Client submits payment proof (voucher signature or channel reference)
4. Server verifies payment and serves the resource

Compatible with the Algorand x402 Bazaar facilitator discovery format
and the Filecoin Onchain Cloud agent ecosystem.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct

from agentic_payments.protocol.errors import PaymentErrorCode

logger = structlog.get_logger(__name__)


class PaymentType(str, Enum):
    """Supported payment methods for gated resources."""

    CHANNEL = "payment-channel"
    HTLC = "htlc"
    X402 = "x402"
    DIRECT = "direct"


class AccessDecision(str, Enum):
    """Result of a payment verification check."""

    GRANTED = "granted"
    PAYMENT_REQUIRED = "payment_required"
    INSUFFICIENT = "insufficient"
    INVALID_PROOF = "invalid_proof"


@dataclass
class GatedResource:
    """A resource gated behind payment."""

    path: str  # API path, e.g. "/api/v1/inference"
    price: int  # Wei per call
    description: str = ""
    payment_type: str = "payment-channel"  # or "htlc", "x402", "direct"
    min_trust_score: float = 0.0  # Minimum trust score for access (0.0 = open)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "price": self.price,
            "description": self.description,
            "payment_type": self.payment_type,
            "min_trust_score": self.min_trust_score,
        }

    @staticmethod
    def from_dict(d: dict) -> GatedResource:
        return GatedResource(
            path=d["path"],
            price=d["price"],
            description=d.get("description", ""),
            payment_type=d.get("payment_type", "payment-channel"),
            min_trust_score=d.get("min_trust_score", 0.0),
        )


@dataclass
class PaymentProof:
    """Proof of payment submitted with a gated resource request."""

    channel_id: str  # Payment channel hex ID
    voucher_nonce: int  # Voucher nonce proving payment
    amount: int  # Amount covered by this voucher
    sender: str  # Sender ETH address
    signature: str = ""  # Optional: voucher signature for direct verification

    @staticmethod
    def from_dict(d: dict) -> PaymentProof:
        return PaymentProof(
            channel_id=d.get("channel_id", ""),
            voucher_nonce=d.get("voucher_nonce", 0),
            amount=d.get("amount", 0),
            sender=d.get("sender", ""),
            signature=d.get("signature", ""),
        )


@dataclass
class AccessLog:
    """Record of a gated resource access attempt."""

    path: str
    sender: str
    decision: AccessDecision
    price: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "sender": self.sender,
            "decision": self.decision.value,
            "price": self.price,
            "timestamp": self.timestamp,
        }


class X402Gateway:
    """Manages gated resources with payment verification and Bazaar compatibility.

    Provides the server-side implementation of the x402 payment protocol:
    - Resource registration with pricing
    - Payment proof verification against channel state
    - Access logging for audit trails
    - Bazaar-format export for ecosystem discovery
    """

    def __init__(
        self,
        provider_id: str = "",
        wallet_address: str = "",
        network: str = "ethereum-sepolia",
        asset: str = "native",
    ) -> None:
        self.provider_id = provider_id
        self.wallet_address = wallet_address
        self._network = network  # x402 network identifier
        self._asset = asset  # x402 asset (native, ERC-20 address, etc.)
        self._resources: dict[str, GatedResource] = {}  # path -> resource
        self._access_log: list[AccessLog] = []
        self._channel_manager: Any = None  # Set after node init
        self._reputation_tracker: Any = None  # Set after node init

    def set_channel_manager(self, cm: Any) -> None:
        """Wire up the channel manager for payment verification."""
        self._channel_manager = cm

    def set_reputation_tracker(self, rt: Any) -> None:
        """Wire up the reputation tracker for trust-gated access."""
        self._reputation_tracker = rt

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

    def is_gated(self, path: str) -> bool:
        """Check if a path is gated behind payment."""
        return path in self._resources

    def verify_access(
        self, path: str, proof: PaymentProof | None = None
    ) -> tuple[AccessDecision, dict]:
        """Verify whether a request should be granted access to a gated resource.

        Returns (decision, metadata) where metadata contains pricing info
        for 402 responses or access details for granted requests.
        """
        resource = self._resources.get(path)
        if resource is None:
            # Not a gated resource — allow through
            return AccessDecision.GRANTED, {}

        # No payment proof provided → 402
        if proof is None:
            self._log_access(path, "", AccessDecision.PAYMENT_REQUIRED, resource.price)
            return AccessDecision.PAYMENT_REQUIRED, self._payment_required_meta(resource)

        # Trust gate check
        if resource.min_trust_score > 0 and self._reputation_tracker:
            rep = self._reputation_tracker.get_reputation(proof.sender)
            if rep and rep.trust_score < resource.min_trust_score:
                self._log_access(path, proof.sender, AccessDecision.INSUFFICIENT, resource.price)
                return AccessDecision.INSUFFICIENT, {
                    "error": "trust_score_too_low",
                    "error_code": PaymentErrorCode.TRUST_BELOW_MINIMUM.name,
                    "required": resource.min_trust_score,
                    "actual": rep.trust_score,
                }

        # Verify payment amount covers resource price
        if proof.amount < resource.price:
            self._log_access(path, proof.sender, AccessDecision.INSUFFICIENT, resource.price)
            return AccessDecision.INSUFFICIENT, {
                "error": "insufficient_payment",
                "error_code": PaymentErrorCode.INSUFFICIENT_PAYMENT.name,
                "required": resource.price,
                "provided": proof.amount,
            }

        # Verify channel exists and has sufficient balance
        if self._channel_manager and proof.channel_id:
            channel = self._channel_manager.get_channel(bytes.fromhex(proof.channel_id))
            if channel is None:
                self._log_access(path, proof.sender, AccessDecision.INVALID_PROOF, resource.price)
                return AccessDecision.INVALID_PROOF, {
                    "error": "channel_not_found",
                    "error_code": PaymentErrorCode.CHANNEL_NOT_FOUND.name,
                }

            remaining = channel.total_deposit - channel.total_paid
            if remaining < resource.price:
                self._log_access(path, proof.sender, AccessDecision.INSUFFICIENT, resource.price)
                return AccessDecision.INSUFFICIENT, {
                    "error": "channel_balance_insufficient",
                    "error_code": PaymentErrorCode.INSUFFICIENT_FUNDS.name,
                    "remaining": remaining,
                    "required": resource.price,
                }

        # Payment verified
        self._log_access(path, proof.sender, AccessDecision.GRANTED, resource.price)
        logger.info(
            "access_granted",
            path=path,
            sender=proof.sender,
            price=resource.price,
        )
        return AccessDecision.GRANTED, {
            "granted": True,
            "path": path,
            "price_charged": resource.price,
        }

    def settle_oneshot(
        self,
        path: str,
        sender: str,
        amount: int,
        signature: str = "",
        task_id: str = "",
        timestamp: int = 0,
    ) -> tuple[AccessDecision, dict]:
        """One-shot stateless x402 payment for occasional interactions.

        Unlike payment channels (which require setup + teardown), one-shot
        payments are a single pay-and-go transaction. Suitable for infrequent
        peers or first-time interactions.

        Args:
            path: The gated resource path
            sender: Sender ETH address
            amount: Payment amount in wei
            signature: Optional direct voucher signature
            task_id: Optional work-request correlation ID
            timestamp: Unix timestamp included in the signed message for replay protection

        Returns:
            (AccessDecision, metadata) tuple
        """
        resource = self._resources.get(path)
        if resource is None:
            return AccessDecision.GRANTED, {}

        if amount < resource.price:
            self._log_access(path, sender, AccessDecision.INSUFFICIENT, resource.price)
            return AccessDecision.INSUFFICIENT, {
                "error": "insufficient_payment",
                "error_code": PaymentErrorCode.INSUFFICIENT_PAYMENT.name,
                "required": resource.price,
                "provided": amount,
            }

        # Verify EIP-191 signature if provided (proves sender owns the wallet)
        if signature:
            # Replay protection: require timestamp within 60-second window
            if timestamp:
                now = int(time.time())
                if abs(now - timestamp) > 60:
                    self._log_access(path, sender, AccessDecision.INVALID_PROOF, resource.price)
                    return AccessDecision.INVALID_PROOF, {
                        "error": "timestamp_expired",
                        "error_code": PaymentErrorCode.INVALID_SIGNATURE.name,
                        "detail": f"Timestamp {timestamp} is outside the 60-second window",
                    }

            try:
                msg_text = f"x402:oneshot:{path}:{amount}:{sender}:{timestamp}"
                signable = encode_defunct(text=msg_text)
                recovered = Account.recover_message(signable, signature=bytes.fromhex(signature))
                if recovered.lower() != sender.lower():
                    self._log_access(path, sender, AccessDecision.INVALID_PROOF, resource.price)
                    return AccessDecision.INVALID_PROOF, {
                        "error": "signature_mismatch",
                        "error_code": PaymentErrorCode.INVALID_SIGNATURE.name,
                        "detail": "Recovered address does not match sender",
                    }
            except (ValueError, TypeError, Exception) as e:
                self._log_access(path, sender, AccessDecision.INVALID_PROOF, resource.price)
                return AccessDecision.INVALID_PROOF, {
                    "error": "invalid_signature",
                    "error_code": PaymentErrorCode.INVALID_SIGNATURE.name,
                    "detail": str(e),
                }

        # Trust gate check
        if resource.min_trust_score > 0 and self._reputation_tracker:
            rep = self._reputation_tracker.get_reputation(sender)
            if rep and rep.trust_score < resource.min_trust_score:
                self._log_access(path, sender, AccessDecision.INSUFFICIENT, resource.price)
                return AccessDecision.INSUFFICIENT, {
                    "error": "trust_score_too_low",
                    "error_code": PaymentErrorCode.TRUST_BELOW_MINIMUM.name,
                    "required": resource.min_trust_score,
                    "actual": rep.trust_score,
                }

        self._log_access(path, sender, AccessDecision.GRANTED, resource.price)
        logger.info(
            "oneshot_access_granted",
            path=path,
            sender=sender,
            price=resource.price,
            task_id=task_id or None,
        )
        return AccessDecision.GRANTED, {
            "granted": True,
            "path": path,
            "price_charged": resource.price,
            "payment_mode": "oneshot",
            "task_id": task_id or None,
        }

    def get_access_log(self, limit: int = 100) -> list[dict]:
        """Return recent access log entries."""
        return [entry.to_dict() for entry in self._access_log[-limit:]]

    def _log_access(self, path: str, sender: str, decision: AccessDecision, price: int) -> None:
        self._access_log.append(AccessLog(path, sender, decision, price))

    def _payment_required_meta(self, resource: GatedResource) -> dict:
        """Build x402 V1 spec-compliant 402 Payment Required response.

        Follows the x402 standard: https://www.x402.org/
        The `accepts` array contains PaymentRequirement objects with
        scheme, network, maxAmountRequired, payTo, asset, and resource fields.
        """
        return {
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": self._network,
                    "maxAmountRequired": str(resource.price),
                    "payTo": self.wallet_address,
                    "asset": self._asset or "native",
                    "resource": resource.path,
                    "description": resource.description,
                    "maxTimeoutSeconds": 30,
                    "mimeType": "application/json",
                    "extra": {
                        "payment_type": resource.payment_type,
                        "min_trust_score": resource.min_trust_score,
                        "provider_id": self.provider_id,
                    },
                }
            ],
        }

    def to_bazaar_format(self) -> dict:
        """Export resources in x402 Bazaar-compatible format.

        Follows the Bazaar discovery layer spec used by Algorand x402
        and Coinbase x402 facilitators.
        """
        return {
            "provider": {
                "id": self.provider_id,
                "wallet": self.wallet_address,
                "network": self._network,
            },
            "resources": [
                {
                    "scheme": "exact",
                    "network": self._network,
                    "maxAmountRequired": str(r.price),
                    "payTo": self.wallet_address,
                    "asset": self._asset or "native",
                    "resource": r.path,
                    "description": r.description,
                    "mimeType": "application/json",
                    "extra": {
                        "payment_type": r.payment_type,
                        "min_trust_score": r.min_trust_score,
                    },
                }
                for r in self._resources.values()
            ],
        }
