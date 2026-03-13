"""Abstract protocols for cross-chain wallet and settlement interfaces."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WalletProtocol(Protocol):
    """Interface that both Ethereum and Algorand wallets implement."""

    @property
    def address(self) -> str: ...

    @property
    def private_key(self) -> str: ...

    def sign_transaction(self, tx: Any) -> Any: ...


@runtime_checkable
class SettlementProtocol(Protocol):
    """Interface that both Ethereum and Algorand settlement handlers implement."""

    async def open_channel_onchain(
        self, receiver: str, deposit: int, duration: int = 86400
    ) -> tuple[bytes, str]: ...

    async def close_channel_onchain(self, channel_id: bytes, *args: Any, **kwargs: Any) -> str: ...

    async def withdraw_onchain(self, channel_id: bytes) -> str: ...

    def get_channel_info(self, channel_id: bytes) -> dict[str, Any]: ...
