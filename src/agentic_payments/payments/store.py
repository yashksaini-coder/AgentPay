"""PostgreSQL-backed persistence for channels and vouchers."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# SQL schema for payment channels and vouchers
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS payment_channels (
    channel_id BYTEA PRIMARY KEY,
    sender TEXT NOT NULL,
    receiver TEXT NOT NULL,
    total_deposit BIGINT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PROPOSED',
    nonce BIGINT NOT NULL DEFAULT 0,
    total_paid BIGINT NOT NULL DEFAULT 0,
    peer_id TEXT NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS vouchers (
    id SERIAL PRIMARY KEY,
    channel_id BYTEA NOT NULL REFERENCES payment_channels(channel_id),
    nonce BIGINT NOT NULL,
    amount BIGINT NOT NULL,
    timestamp BIGINT NOT NULL,
    signature BYTEA NOT NULL,
    created_at BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW())::BIGINT),
    UNIQUE (channel_id, nonce)
);

CREATE INDEX IF NOT EXISTS idx_vouchers_channel ON vouchers(channel_id);
CREATE INDEX IF NOT EXISTS idx_channels_state ON payment_channels(state);
"""


class ChannelStore:
    """PostgreSQL persistence layer for payment channels."""

    def __init__(self, database: Any) -> None:
        """Initialize with a databases.Database instance."""
        self.db = database

    async def initialize(self) -> None:
        """Create tables if they don't exist."""
        for statement in SCHEMA_SQL.strip().split(";"):
            statement = statement.strip()
            if statement:
                await self.db.execute(query=statement)
        logger.info("channel_store_initialized")

    async def save_channel(self, channel: Any) -> None:
        """Insert or update a channel record."""
        await self.db.execute(
            query="""
                INSERT INTO payment_channels
                    (channel_id, sender, receiver, total_deposit, state,
                     nonce, total_paid, peer_id, created_at, updated_at)
                VALUES (:channel_id, :sender, :receiver, :total_deposit, :state,
                        :nonce, :total_paid, :peer_id, :created_at, :updated_at)
                ON CONFLICT (channel_id) DO UPDATE SET
                    state = :state, nonce = :nonce, total_paid = :total_paid,
                    updated_at = :updated_at
            """,
            values={
                "channel_id": channel.channel_id,
                "sender": channel.sender,
                "receiver": channel.receiver,
                "total_deposit": channel.total_deposit,
                "state": channel.state.name,
                "nonce": channel.nonce,
                "total_paid": channel.total_paid,
                "peer_id": channel.peer_id,
                "created_at": channel.created_at,
                "updated_at": channel.updated_at,
            },
        )

    async def save_voucher(self, voucher: Any) -> None:
        """Save a voucher record."""
        await self.db.execute(
            query="""
                INSERT INTO vouchers (channel_id, nonce, amount, timestamp, signature)
                VALUES (:channel_id, :nonce, :amount, :timestamp, :signature)
                ON CONFLICT (channel_id, nonce) DO NOTHING
            """,
            values={
                "channel_id": voucher.channel_id,
                "nonce": voucher.nonce,
                "amount": voucher.amount,
                "timestamp": voucher.timestamp,
                "signature": voucher.signature,
            },
        )

    async def load_channel(self, channel_id: bytes) -> dict | None:
        """Load a channel by ID."""
        row = await self.db.fetch_one(
            query="SELECT * FROM payment_channels WHERE channel_id = :channel_id",
            values={"channel_id": channel_id},
        )
        return dict(row._mapping) if row else None

    async def load_channels_by_state(self, state: str) -> list[dict]:
        """Load all channels with a given state."""
        rows = await self.db.fetch_all(
            query="SELECT * FROM payment_channels WHERE state = :state",
            values={"state": state},
        )
        return [dict(row._mapping) for row in rows]

    async def load_latest_voucher(self, channel_id: bytes) -> dict | None:
        """Load the latest (highest-nonce) voucher for a channel."""
        row = await self.db.fetch_one(
            query="""
                SELECT * FROM vouchers
                WHERE channel_id = :channel_id
                ORDER BY nonce DESC LIMIT 1
            """,
            values={"channel_id": channel_id},
        )
        return dict(row._mapping) if row else None
