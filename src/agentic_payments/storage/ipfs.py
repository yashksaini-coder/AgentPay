"""IPFS HTTP API client — trio-compatible content-addressed storage.

Talks to a local or remote IPFS daemon via its HTTP API (default port 5001).
All blocking HTTP calls are run in trio worker threads to avoid blocking
the event loop.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

import structlog
import trio

from agentic_payments.storage.models import PinnedObject, StorageResult

logger = structlog.get_logger(__name__)


class IPFSError(Exception):
    """Error communicating with the IPFS daemon."""


class IPFSClient:
    """Trio-compatible IPFS HTTP API client.

    Uses urllib (stdlib) wrapped in trio.to_thread.run_sync for
    non-blocking I/O without adding an external HTTP dependency.
    """

    def __init__(self, api_url: str = "http://localhost:5001") -> None:
        self.api_url = api_url.rstrip("/")
        self._pins: dict[str, PinnedObject] = {}  # CID -> metadata

    def _post_sync(self, endpoint: str, data: bytes | None = None, **params: str) -> Any:
        """Synchronous POST to IPFS API (runs in thread)."""
        url = f"{self.api_url}/api/v0/{endpoint}"
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{query}"

        req = urllib.request.Request(url, method="POST")
        if data is not None:
            # Multipart form for /add
            boundary = "----AgentPayBoundary"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="data"\r\n'
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
            req.data = body
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise IPFSError(f"IPFS API error: {e}") from e

    async def add(self, data: bytes, name: str = "") -> StorageResult:
        """Pin data to IPFS, return CID and size."""
        result = await trio.to_thread.run_sync(lambda: self._post_sync("add", data))
        cid = result["Hash"]
        size = int(result.get("Size", len(data)))
        self._pins[cid] = PinnedObject(cid=cid, name=name, size=size)
        logger.info("ipfs_pinned", cid=cid, size=size, name=name)
        return StorageResult(cid=cid, size=size, pinned=True)

    async def add_json(self, obj: dict) -> StorageResult:
        """Pin a JSON object to IPFS."""
        data = json.dumps(obj, separators=(",", ":")).encode()
        return await self.add(data, name="data.json")

    async def cat(self, cid: str) -> bytes:
        """Retrieve raw bytes by CID."""
        def _cat() -> bytes:
            url = f"{self.api_url}/api/v0/cat?arg={cid}"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()

        try:
            return await trio.to_thread.run_sync(_cat)
        except urllib.error.URLError as e:
            raise IPFSError(f"IPFS cat error for {cid}: {e}") from e

    async def cat_json(self, cid: str) -> dict:
        """Retrieve and parse a JSON object by CID."""
        data = await self.cat(cid)
        return json.loads(data)

    async def pin_add(self, cid: str) -> bool:
        """Pin an existing CID."""
        try:
            await trio.to_thread.run_sync(
                lambda: self._post_sync("pin/add", arg=cid)
            )
            logger.info("ipfs_pin_added", cid=cid)
            return True
        except IPFSError:
            return False

    async def pin_rm(self, cid: str) -> bool:
        """Unpin a CID."""
        try:
            await trio.to_thread.run_sync(
                lambda: self._post_sync("pin/rm", arg=cid)
            )
            self._pins.pop(cid, None)
            return True
        except IPFSError:
            return False

    async def is_pinned(self, cid: str) -> bool:
        """Check if a CID is pinned locally."""
        try:
            result = await trio.to_thread.run_sync(
                lambda: self._post_sync("pin/ls", arg=cid, type="all")
            )
            return cid in result.get("Keys", {})
        except IPFSError:
            return False

    async def health(self) -> bool:
        """Check IPFS daemon connectivity."""
        try:
            result = await trio.to_thread.run_sync(
                lambda: self._post_sync("id")
            )
            return "ID" in result
        except IPFSError:
            return False

    def list_pins(self) -> list[PinnedObject]:
        """List locally tracked pinned objects."""
        return list(self._pins.values())
