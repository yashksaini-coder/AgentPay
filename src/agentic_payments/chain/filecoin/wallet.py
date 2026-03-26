"""Filecoin FEVM wallet: secp256k1 key management with f4 address support.

Since Filecoin's FEVM is EVM-compatible, we reuse eth-account for key
management and signing. The wallet also provides Filecoin-native f410f
delegated address format for interop with Filecoin tools.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from eth_account import Account
from eth_account.signers.local import LocalAccount

logger = structlog.get_logger(__name__)

# Filecoin f4 address constants
_F4_PREFIX = "f410f"
_BASE32_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def eth_address_to_f4(eth_address: str) -> str:
    """Convert a 0x Ethereum address to Filecoin f410f delegated format.

    The f4 delegated address encodes the EVM address in base32-lower
    with an f4 address namespace (actor ID 10 = EAM, the Ethereum Address
    Manager).

    Format: f410f + base32lower(20-byte EVM address) + checksum
    """
    addr_bytes = bytes.fromhex(eth_address.lower().removeprefix("0x"))
    if len(addr_bytes) != 20:
        raise ValueError(f"Expected 20-byte address, got {len(addr_bytes)}")

    encoded = _base32_encode(addr_bytes)
    # Compute Blake2b-based checksum (simplified: use first 4 bytes of hash)
    checksum = _blake2b_checksum(b"\x04\x0a" + addr_bytes)  # f4 protocol=4, actor=10
    return _F4_PREFIX + encoded + _base32_encode(checksum)


def f4_to_eth_address(f4_address: str) -> str:
    """Convert a Filecoin f410f address back to 0x Ethereum format."""
    if not f4_address.startswith(_F4_PREFIX):
        raise ValueError(f"Not an f410f address: {f4_address}")
    payload = f4_address[len(_F4_PREFIX) :]
    # Last 4 bytes (encoded) are checksum, rest is the address
    decoded = _base32_decode(payload)
    addr_bytes = decoded[:20]
    checksum = decoded[20:24]
    expected_checksum = _blake2b_checksum(b"\x04\x0a" + addr_bytes)
    if checksum != expected_checksum:
        raise ValueError(
            f"f4 address checksum mismatch: expected {expected_checksum.hex()}, "
            f"got {checksum.hex()}"
        )
    return "0x" + addr_bytes.hex()


def _base32_encode(data: bytes) -> str:
    """RFC 4648 base32 lower-case encoding (no padding)."""
    result = []
    bits = 0
    buffer = 0
    for byte in data:
        buffer = (buffer << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            result.append(_BASE32_ALPHABET[(buffer >> bits) & 0x1F])
    if bits > 0:
        result.append(_BASE32_ALPHABET[(buffer << (5 - bits)) & 0x1F])
    return "".join(result)


def _base32_decode(s: str) -> bytes:
    """RFC 4648 base32 lower-case decoding (no padding)."""
    result = []
    bits = 0
    buffer = 0
    for char in s:
        val = _BASE32_ALPHABET.index(char)
        buffer = (buffer << 5) | val
        bits += 5
        if bits >= 8:
            bits -= 8
            result.append((buffer >> bits) & 0xFF)
    return bytes(result)


def _blake2b_checksum(data: bytes) -> bytes:
    """Compute 4-byte Blake2b checksum for Filecoin addresses."""
    import hashlib

    h = hashlib.blake2b(data, digest_size=4)
    return h.digest()


class FilecoinWallet:
    """Filecoin FEVM wallet wrapping eth-account with f4 address support.

    Uses the same secp256k1 key pair as Ethereum (since FEVM is EVM-compatible)
    but also exposes the Filecoin-native f410f delegated address format.
    """

    def __init__(self, account: LocalAccount) -> None:
        self._account = account

    @classmethod
    def generate(cls) -> FilecoinWallet:
        """Generate a new random wallet."""
        account = Account.create()
        logger.info(
            "filecoin_wallet_generated",
            address=account.address,
            f4_address=eth_address_to_f4(account.address),
        )
        return cls(account)

    @classmethod
    def from_private_key(cls, private_key: str) -> FilecoinWallet:
        """Create wallet from a hex private key."""
        account = Account.from_key(private_key)
        return cls(account)

    @classmethod
    def from_keyfile(cls, path: Path, password: str = "") -> FilecoinWallet:
        """Load wallet from an encrypted keystore file."""
        path = path.expanduser()
        keyfile_json = json.loads(path.read_text())
        private_key = Account.decrypt(keyfile_json, password)
        account = Account.from_key(private_key)
        logger.info("filecoin_wallet_loaded", address=account.address, path=str(path))
        return cls(account)

    def save_keyfile(self, path: Path, password: str = "") -> None:
        """Save wallet to an encrypted keystore file."""
        path = path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        keyfile_json = Account.encrypt(self._account.key, password)
        path.write_text(json.dumps(keyfile_json))
        path.chmod(0o600)
        logger.info("filecoin_wallet_saved", address=self.address, path=str(path))

    @property
    def address(self) -> str:
        """EVM-compatible 0x address (used for contract interactions on FEVM)."""
        return self._account.address

    @property
    def f4_address(self) -> str:
        """Filecoin-native f410f delegated address."""
        return eth_address_to_f4(self._account.address)

    @property
    def private_key(self) -> str:
        """Hex-encoded private key."""
        return self._account.key.hex()

    def sign_transaction(self, tx: dict) -> bytes:
        """Sign a transaction (EVM-compatible on FEVM)."""
        signed = self._account.sign_transaction(tx)
        return signed.raw_transaction

    def sign_message(self, message_hash: bytes) -> bytes:
        """Sign a message hash (EIP-191 personal sign)."""
        from eth_account.messages import encode_defunct

        signable = encode_defunct(message_hash)
        signed = self._account.sign_message(signable)
        return signed.signature
