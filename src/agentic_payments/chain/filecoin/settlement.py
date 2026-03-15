"""Filecoin FEVM settlement: on-chain payment channel operations.

Since Filecoin's FEVM is fully EVM-compatible, this reuses the same
PaymentChannel.sol contract and ABI as Ethereum. The key differences:

1. Gas model: Filecoin uses GasFeeCap/GasPremium instead of gasPrice,
   but web3.py handles this transparently via the Lotus Eth JSON-RPC.
2. Address format: Accepts both 0x and f410f addresses (converts internally).
3. Network: Connects to a Lotus node or public RPC like Glif.
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
from agentic_payments.chain.filecoin.wallet import FilecoinWallet, f4_to_eth_address
from agentic_payments.payments.voucher import SignedVoucher

logger = structlog.get_logger(__name__)


def _normalize_address(addr: str) -> str:
    """Convert f410f address to 0x if needed."""
    if addr.startswith("f410f") or addr.startswith("t410f"):
        return f4_to_eth_address(addr)
    return addr


class FilecoinSettlement:
    """Handles on-chain payment channel operations on Filecoin FEVM.

    Uses the same PaymentChannel.sol deployed to FEVM. The contract
    and ABI are identical to Ethereum — only the RPC endpoint and
    address format differ.

    Supported networks:
    - Mainnet (chain_id=314): wss://wss.mainnet.node.glif.io/apigw/lotus/rpc/v1
    - Calibration testnet (chain_id=314159): https://api.calibration.node.glif.io/rpc/v1
    - Local devnet: http://localhost:1234/rpc/v1
    """

    def __init__(self, w3: Web3, contract_address: str, wallet: FilecoinWallet) -> None:
        self.w3 = w3
        self.wallet = wallet
        contract_address = _normalize_address(contract_address)
        self.contract = get_payment_channel_contract(w3, contract_address)

    async def open_channel_onchain(
        self,
        receiver: str,
        deposit_wei: int,
        duration: int = 86400,
    ) -> tuple[bytes, str]:
        """Open a payment channel on Filecoin FEVM.

        Returns (channel_id, tx_hash).
        """
        receiver = _normalize_address(receiver)
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
            "fil_channel_open_tx_sent",
            tx_hash=tx_hash.hex(),
            receiver=receiver,
            deposit=deposit_wei,
        )

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        logs = self.contract.events.ChannelOpened().process_receipt(receipt)
        if not logs:
            raise RuntimeError(
                f"ChannelOpened event not found in tx {tx_hash.hex()}. "
                "Contract may have reverted on FEVM."
            )
        channel_id = logs[0]["args"]["channelId"]
        return channel_id, tx_hash.hex()

    async def close_channel_onchain(
        self,
        channel_id: bytes,
        voucher: SignedVoucher,
    ) -> str:
        """Initiate channel close on Filecoin FEVM. Returns tx_hash."""
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
            "fil_channel_close_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
            amount=voucher.amount,
        )
        return tx_hash.hex()

    async def challenge_close_onchain(
        self,
        channel_id: bytes,
        voucher: SignedVoucher,
    ) -> str:
        """Challenge close with higher-nonce voucher. Returns tx_hash."""
        tx_nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = self.contract.functions.challengeClose(
            channel_id,
            voucher.amount,
            voucher.nonce,
            voucher.timestamp,
            voucher.signature,
        ).build_transaction(
            {"from": self.wallet.address, "nonce": tx_nonce}
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "fil_channel_challenge_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
        )
        return tx_hash.hex()

    async def withdraw_onchain(self, channel_id: bytes) -> str:
        """Withdraw after challenge period. Returns tx_hash."""
        tx_nonce = self.w3.eth.get_transaction_count(self.wallet.address)
        tx = self.contract.functions.withdraw(
            channel_id,
        ).build_transaction(
            {"from": self.wallet.address, "nonce": tx_nonce}
        )
        signed_tx = self.wallet.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx)
        logger.info(
            "fil_channel_withdraw_tx_sent",
            tx_hash=tx_hash.hex(),
            channel_id=channel_id.hex()[:16],
        )

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt["status"] == 0:
            raise RuntimeError(
                f"Withdraw failed for channel {channel_id.hex()[:16]} on FEVM."
            )
        return tx_hash.hex()

    def get_channel_info(self, channel_id: bytes) -> dict[str, Any]:
        """Query on-chain channel state on FEVM."""
        result = self.contract.functions.getChannel(channel_id).call()
        return {
            "sender": result[0],
            "receiver": result[1],
            "deposit": result[2],
            "closing_nonce": result[3],
            "closing_amount": result[4],
            "expiration": result[5],
            "closed": result[6],
            "chain": "filecoin",
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
