"""Data models for IPFS storage operations."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StorageResult:
    """Result of pinning data to IPFS."""

    cid: str  # Content Identifier (CIDv1 base32)
    size: int  # Size in bytes
    pinned: bool = True

    def to_dict(self) -> dict:
        return {"cid": self.cid, "size": self.size, "pinned": self.pinned}


@dataclass
class PinnedObject:
    """Metadata for a pinned IPFS object."""

    cid: str
    name: str = ""
    size: int = 0
    content_type: str = "application/octet-stream"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "cid": self.cid,
            "name": self.name,
            "size": self.size,
            "content_type": self.content_type,
            "timestamp": self.timestamp,
        }
