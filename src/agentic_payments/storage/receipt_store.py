"""IPFS-backed receipt chain storage.

Extends the in-memory ReceiptStore by pinning receipts and full chains
to IPFS for tamper-evident, content-addressed persistence. Aligns with
Filecoin Agents RFS-3 (provable behavioral history).
"""

from __future__ import annotations

import structlog

from agentic_payments.reporting.receipts import ReceiptStore, SignedReceipt
from agentic_payments.storage.ipfs import IPFSClient

logger = structlog.get_logger(__name__)


class IPFSReceiptStore:
    """Receipt chain storage backed by IPFS.

    Pins individual receipts and full chains to IPFS for:
    - Tamper-evident audit trail (content-addressed)
    - Cross-agent verification (share CID, verify chain)
    - Long-term persistence on Filecoin (via IPFS pinning services)
    """

    def __init__(self, ipfs: IPFSClient, receipt_store: ReceiptStore) -> None:
        self.ipfs = ipfs
        self.store = receipt_store
        self._receipt_cids: dict[str, str] = {}  # receipt_id hex -> CID
        self._chain_cids: dict[str, str] = {}  # channel_id hex -> latest chain CID

    async def pin_receipt(self, receipt: SignedReceipt) -> str:
        """Pin a single receipt to IPFS. Returns CID."""
        data = receipt.to_dict()
        result = await self.ipfs.add_json(data)
        receipt_id_hex = receipt.receipt_id.hex()
        self._receipt_cids[receipt_id_hex] = result.cid
        logger.info(
            "receipt_pinned",
            cid=result.cid,
            receipt_id=receipt_id_hex[:16],
            channel_id=receipt.channel_id.hex()[:16],
            nonce=receipt.nonce,
        )
        return result.cid

    async def pin_chain(self, channel_id: bytes) -> str:
        """Pin the entire receipt chain for a channel. Returns CID."""
        chain = self.store.get_chain(channel_id)
        if not chain:
            raise ValueError(f"No receipts for channel {channel_id.hex()[:16]}")

        chain_data = {
            "channel_id": channel_id.hex(),
            "receipt_count": len(chain),
            "chain_valid": self.store.verify_chain(channel_id),
            "receipts": [r.to_dict() for r in chain],
        }
        result = await self.ipfs.add_json(chain_data)
        channel_hex = channel_id.hex()
        self._chain_cids[channel_hex] = result.cid
        logger.info(
            "receipt_chain_pinned",
            cid=result.cid,
            channel_id=channel_hex[:16],
            receipt_count=len(chain),
        )
        return result.cid

    async def get_receipt_from_ipfs(self, cid: str) -> SignedReceipt:
        """Retrieve a receipt from IPFS by CID."""
        data = await self.ipfs.cat_json(cid)
        return SignedReceipt.from_dict(data)

    async def get_chain_from_ipfs(self, cid: str) -> list[SignedReceipt]:
        """Retrieve a full receipt chain from IPFS by CID."""
        data = await self.ipfs.cat_json(cid)
        return [SignedReceipt.from_dict(r) for r in data["receipts"]]

    def get_receipt_cid(self, receipt_id: bytes) -> str | None:
        """Look up the IPFS CID for a receipt."""
        return self._receipt_cids.get(receipt_id.hex())

    def get_chain_cid(self, channel_id: bytes) -> str | None:
        """Look up the latest IPFS CID for a channel's receipt chain."""
        return self._chain_cids.get(channel_id.hex())

    def list_pinned(self) -> dict:
        """Summary of all pinned receipts and chains."""
        return {
            "receipt_count": len(self._receipt_cids),
            "chain_count": len(self._chain_cids),
            "receipts": dict(list(self._receipt_cids.items())[:20]),
            "chains": self._chain_cids,
        }
