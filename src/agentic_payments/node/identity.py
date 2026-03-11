"""Node identity: key generation, persistence, and PeerID derivation."""

from __future__ import annotations

from pathlib import Path

import structlog
from libp2p.crypto.ed25519 import Ed25519PrivateKey, create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.peer.id import ID as PeerID

logger = structlog.get_logger(__name__)


def generate_identity() -> KeyPair:
    """Generate a new Ed25519 key pair for a libp2p node."""
    key_pair = create_new_key_pair()
    logger.info("generated_new_identity", peer_id=peer_id_from_keypair(key_pair).to_base58())
    return key_pair


def peer_id_from_keypair(key_pair: KeyPair) -> PeerID:
    """Derive PeerID from a key pair."""
    return PeerID.from_pubkey(key_pair.public_key)


def save_identity(key_pair: KeyPair, path: Path) -> None:
    """Save a key pair to disk as raw private key bytes."""
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = key_pair.private_key.to_bytes()
    path.write_bytes(raw_bytes)
    path.chmod(0o600)
    logger.info("identity_saved", path=str(path))


def load_identity(path: Path) -> KeyPair:
    """Load a key pair from a saved private key file."""
    path = path.expanduser()
    raw_bytes = path.read_bytes()
    private_key = Ed25519PrivateKey.from_bytes(raw_bytes)
    key_pair = KeyPair(private_key, private_key.get_public_key())
    logger.info(
        "identity_loaded",
        path=str(path),
        peer_id=peer_id_from_keypair(key_pair).to_base58(),
    )
    return key_pair


def load_or_generate_identity(path: Path) -> KeyPair:
    """Load identity from path, or generate and save a new one."""
    path = path.expanduser()
    if path.exists():
        return load_identity(path)
    key_pair = generate_identity()
    save_identity(key_pair, path)
    return key_pair
