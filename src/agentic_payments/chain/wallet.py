"""Ethereum wallet: key management and transaction signing."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from eth_account import Account
from eth_account.signers.local import LocalAccount

logger = structlog.get_logger(__name__)


class Wallet:
    """Ethereum wallet wrapping eth-account for key management and signing."""

    def __init__(self, account: LocalAccount) -> None:
        self._account = account

    @classmethod
    def generate(cls) -> Wallet:
        """Generate a new random wallet."""
        account = Account.create()
        logger.info("wallet_generated", address=account.address)
        return cls(account)

    @classmethod
    def from_private_key(cls, private_key: str) -> Wallet:
        """Create wallet from a hex private key."""
        account = Account.from_key(private_key)
        return cls(account)

    @classmethod
    def from_keyfile(cls, path: Path, password: str) -> Wallet:
        """Load wallet from an encrypted keystore file."""
        path = path.expanduser()
        keyfile_json = json.loads(path.read_text())
        private_key = Account.decrypt(keyfile_json, password)
        account = Account.from_key(private_key)
        logger.info("wallet_loaded", address=account.address, path=str(path))
        return cls(account)

    def save_keyfile(self, path: Path, password: str) -> None:
        """Save wallet to an encrypted keystore file."""
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        keyfile_json = Account.encrypt(self._account.key, password)
        path.write_text(json.dumps(keyfile_json))
        path.chmod(0o600)
        logger.info("wallet_saved", address=self.address, path=str(path))

    @property
    def address(self) -> str:
        """Checksummed Ethereum address."""
        return self._account.address

    @property
    def private_key(self) -> str:
        """Hex-encoded private key."""
        return self._account.key.hex()

    def sign_transaction(self, tx: dict) -> bytes:
        """Sign an Ethereum transaction."""
        signed = self._account.sign_transaction(tx)
        return signed.raw_transaction

    def sign_message(self, message_hash: bytes) -> bytes:
        """Sign a message hash (EIP-191 personal sign)."""
        from eth_account.messages import encode_defunct

        signable = encode_defunct(message_hash)
        signed = self._account.sign_message(signable)
        return signed.signature
