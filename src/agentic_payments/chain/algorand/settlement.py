"""Algorand on-chain settlement via Application Calls.

Mirrors the Ethereum Settlement interface for payment channel operations
using Algorand Smart Contracts (ARC-4 ABI).
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any

import structlog
import trio

logger = structlog.get_logger(__name__)

try:
    from algosdk.v2client import algod, indexer
    from algosdk import logic, transaction, encoding

    HAS_ALGOSDK = True
except ImportError:
    HAS_ALGOSDK = False


def _require_algosdk() -> None:
    if not HAS_ALGOSDK:
        raise ImportError("py-algorand-sdk>=2.6 is required for Algorand settlement")


def _wait_for_confirmation(client: Any, tx_id: str, timeout: int = 10) -> dict:
    """Wait for a transaction to be confirmed on Algorand.

    Polls the algod client until the transaction is confirmed or timeout rounds pass.
    """
    last_round = client.status()["last-round"]
    current = last_round
    while current < last_round + timeout:
        try:
            pending = client.pending_transaction_info(tx_id)
            if pending.get("confirmed-round", 0) > 0:
                logger.debug("tx_confirmed", tx_id=tx_id, round=pending["confirmed-round"])
                return pending
            if pending.get("pool-error"):
                raise RuntimeError(f"Transaction rejected: {pending['pool-error']}")
        except Exception as e:
            if "not found" not in str(e).lower():
                raise
        client.status_after_block(current)
        current += 1
    raise RuntimeError(f"Transaction {tx_id} not confirmed after {timeout} rounds")


def _decode_channel_box(raw_value: bytes) -> dict[str, Any]:
    """Decode ABI-encoded channel state from box storage.

    Expected ABI tuple: (address, address, uint64, uint64, uint64, uint64, bool)
    = 32 + 32 + 8 + 8 + 8 + 8 + 1 = 97 bytes
    """
    if len(raw_value) < 97:
        return {"error": f"Box value too short: {len(raw_value)} bytes"}

    sender_bytes = raw_value[0:32]
    receiver_bytes = raw_value[32:64]
    deposit = struct.unpack(">Q", raw_value[64:72])[0]
    closing_nonce = struct.unpack(">Q", raw_value[72:80])[0]
    closing_amount = struct.unpack(">Q", raw_value[80:88])[0]
    expiration = struct.unpack(">Q", raw_value[88:96])[0]
    closed = raw_value[96] != 0

    return {
        "sender": encoding.encode_address(sender_bytes),
        "receiver": encoding.encode_address(receiver_bytes),
        "deposit": deposit,
        "closing_nonce": closing_nonce,
        "closing_amount": closing_amount,
        "expiration": expiration,
        "closed": closed,
    }


# ARC-4 ABI methods for the payment channel application
PAYMENT_CHANNEL_METHODS = [
    {
        "name": "open_channel",
        "args": [
            {"name": "receiver", "type": "address"},
            {"name": "duration", "type": "uint64"},
        ],
        "returns": {"type": "byte[32]"},
    },
    {
        "name": "close_channel",
        "args": [
            {"name": "channel_id", "type": "byte[32]"},
            {"name": "amount", "type": "uint64"},
            {"name": "nonce", "type": "uint64"},
            {"name": "timestamp", "type": "uint64"},
            {"name": "signature", "type": "byte[64]"},
        ],
        "returns": {"type": "void"},
    },
    {
        "name": "challenge_close",
        "args": [
            {"name": "channel_id", "type": "byte[32]"},
            {"name": "amount", "type": "uint64"},
            {"name": "nonce", "type": "uint64"},
            {"name": "timestamp", "type": "uint64"},
            {"name": "signature", "type": "byte[64]"},
        ],
        "returns": {"type": "void"},
    },
    {
        "name": "withdraw",
        "args": [{"name": "channel_id", "type": "byte[32]"}],
        "returns": {"type": "void"},
    },
    {
        "name": "get_channel",
        "args": [{"name": "channel_id", "type": "byte[32]"}],
        "returns": {"type": "(address,address,uint64,uint64,uint64,uint64,bool)"},
    },
]


class AlgorandSettlement:
    """Handles Algorand on-chain payment channel operations.

    Uses Application Calls to an ARC-4 smart contract deployed on Algorand.
    Supports the same lifecycle as the Ethereum Settlement: open, close,
    challenge, withdraw.
    """

    def __init__(
        self,
        algod_url: str,
        algod_token: str,
        app_id: int,
        wallet: Any,  # AlgorandWallet
        indexer_url: str = "",
        indexer_token: str = "",
    ) -> None:
        _require_algosdk()
        self.client = algod.AlgodClient(algod_token, algod_url)
        self.app_id = app_id
        self.wallet = wallet
        self.indexer_client = (
            indexer.IndexerClient(indexer_token, indexer_url) if indexer_url else None
        )
        logger.info(
            "algorand_settlement_init",
            app_id=app_id,
            address=wallet.address,
        )

    def _sign_and_submit(self, txn: Any) -> str:
        """Sign a transaction and submit it, waiting for confirmation."""
        signed_txn = self.wallet.sign_transaction(txn)
        tx_id = self.client.send_transaction(signed_txn)
        _wait_for_confirmation(self.client, tx_id)
        return tx_id

    async def open_channel_onchain(
        self,
        receiver: str,
        deposit_microalgos: int,
        duration: int = 86400,
    ) -> tuple[bytes, str]:
        """Open a payment channel on Algorand.

        Creates an atomic group: app call + payment deposit.
        Returns (channel_id, tx_id).
        """
        params = self.client.suggested_params()

        # Application call to create the channel
        app_txn = transaction.ApplicationCallTxn(
            sender=self.wallet.address,
            sp=params,
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"open_channel",
                encoding.decode_address(receiver),
                duration.to_bytes(8, "big"),
            ],
        )

        # Payment transaction for deposit (sent to application address)
        app_address = logic.get_application_address(self.app_id)
        pay_txn = transaction.PaymentTxn(
            sender=self.wallet.address,
            sp=params,
            receiver=app_address,
            amt=deposit_microalgos,
        )

        # Atomic group: both succeed or both fail
        gid = transaction.calculate_group_id([app_txn, pay_txn])
        app_txn.group = gid
        pay_txn.group = gid

        signed_app = self.wallet.sign_transaction(app_txn)
        signed_pay = self.wallet.sign_transaction(pay_txn)

        tx_id = await trio.to_thread.run_sync(
            lambda: self.client.send_transactions([signed_app, signed_pay])
        )
        pending = await trio.to_thread.run_sync(
            lambda: _wait_for_confirmation(self.client, tx_id)
        )

        # Generate deterministic channel_id from confirmed round
        confirmed_round = pending.get("confirmed-round", 0)
        channel_id = hashlib.sha256(
            f"{self.wallet.address}:{receiver}:{tx_id}:{confirmed_round}".encode()
        ).digest()

        logger.info(
            "algorand_channel_opened",
            tx_id=tx_id,
            receiver=receiver,
            deposit=deposit_microalgos,
            channel_id=channel_id.hex()[:16],
        )

        return channel_id, tx_id

    async def close_channel_onchain(
        self,
        channel_id: bytes,
        amount: int,
        nonce: int,
        timestamp: int,
        signature: bytes,
    ) -> str:
        """Initiate channel close on Algorand. Waits for confirmation."""
        params = self.client.suggested_params()

        txn = transaction.ApplicationCallTxn(
            sender=self.wallet.address,
            sp=params,
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"close_channel",
                channel_id,
                amount.to_bytes(8, "big"),
                nonce.to_bytes(8, "big"),
                timestamp.to_bytes(8, "big"),
                signature,
            ],
        )

        tx_id = await trio.to_thread.run_sync(self._sign_and_submit, txn)
        logger.info("algorand_channel_close_confirmed", tx_id=tx_id, channel=channel_id.hex()[:12])
        return tx_id

    async def challenge_close_onchain(
        self,
        channel_id: bytes,
        amount: int,
        nonce: int,
        timestamp: int,
        signature: bytes,
    ) -> str:
        """Challenge a closing channel with a higher-nonce voucher. Waits for confirmation."""
        params = self.client.suggested_params()

        txn = transaction.ApplicationCallTxn(
            sender=self.wallet.address,
            sp=params,
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[
                b"challenge_close",
                channel_id,
                amount.to_bytes(8, "big"),
                nonce.to_bytes(8, "big"),
                timestamp.to_bytes(8, "big"),
                signature,
            ],
        )

        tx_id = await trio.to_thread.run_sync(self._sign_and_submit, txn)
        logger.info("algorand_challenge_confirmed", tx_id=tx_id, channel=channel_id.hex()[:12])
        return tx_id

    async def withdraw_onchain(self, channel_id: bytes) -> str:
        """Withdraw funds after challenge period. Waits for confirmation."""
        params = self.client.suggested_params()

        txn = transaction.ApplicationCallTxn(
            sender=self.wallet.address,
            sp=params,
            index=self.app_id,
            on_complete=transaction.OnComplete.NoOpOC,
            app_args=[b"withdraw", channel_id],
        )

        tx_id = await trio.to_thread.run_sync(self._sign_and_submit, txn)
        logger.info("algorand_withdraw_confirmed", tx_id=tx_id, channel=channel_id.hex()[:12])
        return tx_id

    def get_channel_info(self, channel_id: bytes) -> dict[str, Any]:
        """Query on-chain channel state from Algorand box storage.

        Decodes the ABI-encoded tuple: (address, address, uint64, uint64, uint64, uint64, bool).
        """
        try:
            box = self.client.application_box_by_name(self.app_id, channel_id)
            # Box value is base64-encoded in the response
            import base64

            raw_value = base64.b64decode(box.get("value", ""))
            decoded = _decode_channel_box(raw_value)
            decoded["channel_id"] = channel_id.hex()
            decoded["chain"] = "algorand"
            return decoded
        except Exception as e:
            return {
                "channel_id": channel_id.hex(),
                "chain": "algorand",
                "error": f"Channel not found: {e}",
            }

    def is_challenge_active(self, channel_id: bytes) -> bool:
        """Check if a channel is in its challenge period."""
        info = self.get_channel_info(channel_id)
        if info.get("error") or info.get("closed"):
            return False
        expiration = info.get("expiration", 0)
        if expiration == 0:
            return False
        # Use latest round timestamp as time reference
        try:
            status = self.client.status()
            last_round = status["last-round"]
            block = self.client.block_info(last_round)
            block_ts = block.get("block", {}).get("ts", 0)
            return block_ts < expiration
        except Exception:
            return False

    def can_withdraw(self, channel_id: bytes) -> bool:
        """Check if a channel is ready for withdrawal."""
        info = self.get_channel_info(channel_id)
        if info.get("error") or info.get("closed"):
            return False
        expiration = info.get("expiration", 0)
        if expiration == 0:
            return False
        try:
            status = self.client.status()
            last_round = status["last-round"]
            block = self.client.block_info(last_round)
            block_ts = block.get("block", {}).get("ts", 0)
            return block_ts >= expiration
        except Exception:
            return False
