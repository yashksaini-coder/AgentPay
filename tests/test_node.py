"""Tests for node identity and basic operations."""

from __future__ import annotations


from agentic_payments.node.identity import (
    generate_identity,
    load_identity,
    peer_id_from_keypair,
    save_identity,
)


class TestIdentity:
    def test_generate_identity(self):
        """Should generate a valid key pair."""
        key_pair = generate_identity()
        assert key_pair.private_key is not None
        assert key_pair.public_key is not None

    def test_peer_id_derivation(self):
        """Should derive a consistent PeerID from a key pair."""
        key_pair = generate_identity()
        pid1 = peer_id_from_keypair(key_pair)
        pid2 = peer_id_from_keypair(key_pair)
        assert pid1 == pid2
        assert len(pid1.to_base58()) > 0

    def test_save_and_load(self, tmp_path):
        """Should round-trip save/load identity."""
        key_pair = generate_identity()
        path = tmp_path / "test.key"
        save_identity(key_pair, path)

        loaded = load_identity(path)
        assert peer_id_from_keypair(loaded) == peer_id_from_keypair(key_pair)

    def test_key_file_permissions(self, tmp_path):
        """Key file should be created with restricted permissions."""
        key_pair = generate_identity()
        path = tmp_path / "test.key"
        save_identity(key_pair, path)

        import stat

        mode = path.stat().st_mode
        assert not (mode & stat.S_IRGRP)  # No group read
        assert not (mode & stat.S_IROTH)  # No other read
