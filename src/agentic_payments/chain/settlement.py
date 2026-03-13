"""On-chain payment channel settlement logic.

Handles the full lifecycle of on-chain operations:
- Open channel (deposit ETH or ERC-20 tokens)
- Close channel (submit final voucher, start challenge period)
- Challenge close (submit higher-nonce voucher during challenge)
- Withdraw (settle after challenge period expires)
- Query on-chain state
"""

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
    """Handles on-chain payment channel operations.

    Supports the full settlement lifecycle including challenge period
    enforcement and dispute resolution.
    """

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
        """Initiate channel close on-chain with the final voucher.

        This starts the challenge period. After the period expires,
        call withdraw() to complete settlement.

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
            nonce=voucher.nonce,
        )
        return tx_hash.hex()

    async def challenge_close_onchain(
        self,
        channel_id: bytes,
        voucher: SignedVoucher,
    ) -> str:
        """Challenge an in-progress close with a higher-nonce voucher.

        Must be called during the challenge period. Submits a newer
        voucher to override the closing state.

        Returns tx_hash.
        """
        tx_nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = self.contract.functions.challengeClose(
            channel_id,
            voucher.amount,
            voucher.nonce,
            voucher.timestamp,
            voucher.signature,
        ).build_transaction(
            {
                "from": self.wallet.address,
                "nonce": tx_nonce,
            }
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "channel_challenge_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
            challenge_nonce=voucher.nonce,
            challenge_amount=voucher.amount,
        )
        return tx_hash.hex()

    async def withdraw_onchain(self, channel_id: bytes) -> str:
        """Withdraw funds after challenge period expires.

        Completes settlement: receiver gets closingAmount,
        sender gets deposit - closingAmount.

        Returns tx_hash.
        """
        tx_nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = self.contract.functions.withdraw(
            channel_id,
        ).build_transaction(
            {
                "from": self.wallet.address,
                "nonce": tx_nonce,
            }
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "channel_withdraw_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
        )

        # Wait for receipt
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt["status"] == 0:
            raise RuntimeError(
                f"Withdraw failed for channel {channel_id.hex()[:16]}. "
                "Challenge period may still be active."
            )

        logger.info(
            "channel_withdrawn",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
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

    def is_challenge_active(self, channel_id: bytes) -> bool:
        """Check if a channel is in its challenge period."""
        info = self.get_channel_info(channel_id)
        if info["closed"] or info["expiration"] == 0:
            return False
        current_block = self.w3.eth.get_block("latest")
        return current_block["timestamp"] < info["expiration"]

    def can_withdraw(self, channel_id: bytes) -> bool:
        """Check if a channel is ready for withdrawal."""
        info = self.get_channel_info(channel_id)
        if info["closed"] or info["expiration"] == 0:
            return False
        current_block = self.w3.eth.get_block("latest")
        return current_block["timestamp"] >= info["expiration"]
