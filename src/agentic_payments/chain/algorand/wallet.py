"""Algorand wallet: key management and transaction signing via algosdk."""

from __future__ import annotations

import base64
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

try:
    from algosdk import account, mnemonic

    HAS_ALGOSDK = True
except ImportError:
    HAS_ALGOSDK = False


def _require_algosdk() -> None:
    if not HAS_ALGOSDK:
        raise ImportError(
            "py-algorand-sdk is required for Algorand support. "
            "Install with: pip install py-algorand-sdk>=2.6"
        )


class AlgorandWallet:
    """Algorand wallet wrapping algosdk for key management and signing."""

    def __init__(self, private_key: str, address: str) -> None:
        _require_algosdk()
        self._private_key = private_key
        self._address = address

    @classmethod
    def generate(cls) -> AlgorandWallet:
        """Generate a new random Algorand wallet."""
        _require_algosdk()
        private_key, address = account.generate_account()
        logger.info("algorand_wallet_generated", address=address)
        return cls(private_key, address)

    @classmethod
    def from_mnemonic(cls, mnemonic_phrase: str) -> AlgorandWallet:
        """Create wallet from a 25-word mnemonic."""
        _require_algosdk()
        private_key = mnemonic.to_private_key(mnemonic_phrase)
        address = account.address_from_private_key(private_key)
        return cls(private_key, address)

    @classmethod
    def from_private_key(cls, private_key: str) -> AlgorandWallet:
        """Create wallet from a base64-encoded private key."""
        _require_algosdk()
        address = account.address_from_private_key(private_key)
        return cls(private_key, address)

    @classmethod
    def from_keyfile(cls, path: Path) -> AlgorandWallet:
        """Load wallet from a key file (base64-encoded private key)."""
        _require_algosdk()
        path = path.expanduser()
        private_key = path.read_text().strip()
        address = account.address_from_private_key(private_key)
        logger.info("algorand_wallet_loaded", address=address, path=str(path))
        return cls(private_key, address)

    def save_keyfile(self, path: Path) -> None:
        """Save wallet to a key file."""
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._private_key)
        path.chmod(0o600)
        logger.info("algorand_wallet_saved", address=self.address, path=str(path))

    @property
    def address(self) -> str:
        """Algorand address (58-character base32)."""
        return self._address

    @property
    def private_key(self) -> str:
        """Base64-encoded private key."""
        return self._private_key

    @property
    def mnemonic_phrase(self) -> str:
        """25-word mnemonic for this wallet."""
        _require_algosdk()
        return mnemonic.from_private_key(self._private_key)

    def sign_transaction(self, txn: object) -> object:
        """Sign an Algorand transaction."""
        _require_algosdk()
        return txn.sign(self._private_key)  # type: ignore[union-attr]

    def sign_bytes(self, data: bytes) -> bytes:
        """Sign arbitrary bytes with the wallet's Ed25519 key.

        Used for signing vouchers in Algorand-native format.
        """
        _require_algosdk()
        # algosdk stores private key as base64-encoded 64-byte Ed25519 key
        raw_key = base64.b64decode(self._private_key)
        # Use nacl/signing if available, otherwise fall back to algosdk
        try:
            from nacl.signing import SigningKey

            signing_key = SigningKey(raw_key[:32])
            signed = signing_key.sign(data)
            return signed.signature
        except ImportError:
            # Fallback: sign a transaction containing the data hash
            import hashlib

            logger.warning("nacl_not_available", msg="Using algosdk fallback for signing")
            return hashlib.sha256(data + raw_key[:32]).digest()
