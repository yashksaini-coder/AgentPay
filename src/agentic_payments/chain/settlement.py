"""On-chain payment channel settlement logic."""

from __future__ import annotations

from typing import Any

import structlog
from web3 import Web3

from agentic_payments.chain.contracts import (
    build_close_channel_tx,
    build_open_channel_tx,
    get_payment_channel_contract,
)
from agentic_payments.chain.wallet import Wallet
from agentic_payments.payments.voucher import SignedVoucher

logger = structlog.get_logger(__name__)


class Settlement:
    """Handles on-chain payment channel operations."""

    def __init__(self, w3: Web3, contract_address: str, wallet: Wallet) -> None:
        self.w3 = w3
        self.wallet = wallet
        self.contract = get_payment_channel_contract(w3, contract_address)

    async def open_channel_onchain(
        self,
        receiver: str,
        deposit_wei: int,
        duration: int = 86400,  # 24 hours default
    ) -> tuple[bytes, str]:
        """Open a payment channel on-chain.

        Returns (channel_id, tx_hash).
        """
        nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = build_open_channel_tx(
            contract=self.contract,
            receiver=receiver,
            duration=duration,
            deposit_wei=deposit_wei,
            sender=self.wallet.address,
            nonce=nonce,
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "channel_open_tx_sent",
            tx_hash=tx_hash.hex(),
            receiver=receiver,
            deposit=deposit_wei,
        )

        # Wait for receipt
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        # Parse ChannelOpened event
        logs = self.contract.events.ChannelOpened().process_receipt(receipt)
        if not logs:
            raise RuntimeError(
                f"ChannelOpened event not found in tx {tx_hash.hex()}. "
                "The contract may have reverted or the ABI may be incorrect."
            )
        channel_id = logs[0]["args"]["channelId"]
        return channel_id, tx_hash.hex()

    async def close_channel_onchain(
        self,
        channel_id: bytes,
        voucher: SignedVoucher,
    ) -> str:
        """Close a payment channel on-chain with the final voucher.

        Returns tx_hash.
        """
        tx_nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = build_close_channel_tx(
            contract=self.contract,
            channel_id=channel_id,
            amount=voucher.amount,
            nonce=voucher.nonce,
            timestamp=voucher.timestamp,
            signature=voucher.signature,
            sender=self.wallet.address,
            tx_nonce=tx_nonce,
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "channel_close_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
            amount=voucher.amount,
        )
        return tx_hash.hex()

    def get_channel_info(self, channel_id: bytes) -> dict[str, Any]:
        """Query on-chain channel state."""
        result = self.contract.functions.getChannel(channel_id).call()
        return {
            "sender": result[0],
            "receiver": result[1],
            "deposit": result[2],
            "closing_nonce": result[3],
            "closing_amount": result[4],
            "expiration": result[5],
            "closed": result[6],
        }
