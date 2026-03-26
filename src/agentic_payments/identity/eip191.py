"""EIP-191 identity binding: cryptographic proof linking libp2p PeerId to ETH wallet.

Agents sign "AgentPay:identity:{peer_id}" with their ETH key to prove
PeerId ↔ wallet binding. The proof is broadcast on connection and verified by peers.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from eth_account import Account
from eth_account.messages import encode_defunct

logger = structlog.get_logger(__name__)

# Domain separator for AgentPay identity binding
DOMAIN_PREFIX = "AgentPay:identity:"


@dataclass(frozen=True)
class IdentityProof:
    """Cryptographic proof binding a libp2p PeerId to an Ethereum wallet."""

    peer_id: str  # Base58 libp2p PeerId
    eth_address: str  # Checksummed Ethereum address
    signature: bytes  # EIP-191 signature over the binding message

    def to_dict(self) -> dict:
        return {
            "peer_id": self.peer_id,
            "eth_address": self.eth_address,
            "signature": self.signature.hex(),
        }

    @staticmethod
    def from_dict(d: dict) -> IdentityProof:
        for key in ("peer_id", "eth_address", "signature"):
            if key not in d:
                raise ValueError(f"IdentityProof missing required field: {key}")
        sig = d["signature"]
        if isinstance(sig, str):
            sig = bytes.fromhex(sig)
        return IdentityProof(
            peer_id=d["peer_id"],
            eth_address=d["eth_address"],
            signature=sig,
        )


def _binding_message(peer_id: str) -> str:
    """Construct the message to sign for identity binding."""
    return f"{DOMAIN_PREFIX}{peer_id}"


def sign_identity(peer_id: str, private_key: str) -> IdentityProof:
    """Create an EIP-191 signed identity proof binding PeerId to ETH wallet.

    Args:
        peer_id: Base58 libp2p PeerId string
        private_key: Hex-encoded Ethereum private key

    Returns:
        IdentityProof with signature
    """
    message = _binding_message(peer_id)
    signable = encode_defunct(text=message)
    signed = Account.sign_message(signable, private_key=private_key)
    eth_address = Account.from_key(private_key).address

    logger.info(
        "eip191_identity_signed",
        peer_id=peer_id[:16],
        eth_address=eth_address,
    )

    return IdentityProof(
        peer_id=peer_id,
        eth_address=eth_address,
        signature=signed.signature,
    )


def verify_identity(proof: IdentityProof) -> bool:
    """Verify an EIP-191 identity proof.

    Recovers the signer from the signature and checks it matches
    the claimed eth_address.

    Args:
        proof: The identity proof to verify

    Returns:
        True if the signature is valid and matches the claimed address
    """
    message = _binding_message(proof.peer_id)
    signable = encode_defunct(text=message)
    try:
        recovered = Account.recover_message(signable, signature=proof.signature)
        valid = recovered.lower() == proof.eth_address.lower()
        if not valid:
            logger.warning(
                "eip191_verify_mismatch",
                claimed=proof.eth_address,
                recovered=recovered,
                peer_id=proof.peer_id[:16],
            )
        return valid
    except (ValueError, TypeError) as e:
        logger.warning("eip191_verify_bad_signature", error=str(e))
        return False
    except Exception:
        logger.exception("eip191_verify_unexpected_error")
        return False
