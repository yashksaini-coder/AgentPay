"""Length-prefix framing + msgpack codec for libp2p streams.

Uses py-libp2p's INetStream.read() and INetStream.write() for I/O.
Each message is framed as: [4-byte big-endian length][msgpack payload]
"""

from __future__ import annotations

import struct
from typing import Any

import msgpack
from libp2p.network.stream.net_stream import NetStream

# 4-byte big-endian length prefix
HEADER_FORMAT = ">I"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB


def encode_message(data: dict[str, Any]) -> bytes:
    """Encode a message dict as length-prefixed msgpack bytes."""
    payload = msgpack.packb(data, use_bin_type=True)
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {len(payload)} > {MAX_MESSAGE_SIZE}")
    header = struct.pack(HEADER_FORMAT, len(payload))
    return header + payload


def decode_payload(payload: bytes) -> dict[str, Any]:
    """Decode msgpack payload bytes into a message dict."""
    return msgpack.unpackb(payload, raw=False)


async def write_message(stream: NetStream, data: dict[str, Any]) -> None:
    """Write a length-prefixed msgpack message to a libp2p stream.

    Calls stream.write(bytes) which is provided by py-libp2p's NetStream.
    """
    frame = encode_message(data)
    await stream.write(frame)


async def read_message(stream: NetStream) -> dict[str, Any]:
    """Read a length-prefixed msgpack message from a libp2p stream.

    Calls stream.read(n) which is provided by py-libp2p's NetStream.
    Reads are done in two phases: header (4 bytes), then payload.
    """
    header = await _read_exactly(stream, HEADER_SIZE)
    (length,) = struct.unpack(HEADER_FORMAT, header)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {length} > {MAX_MESSAGE_SIZE}")
    if length == 0:
        raise ValueError("Empty message")
    payload = await _read_exactly(stream, length)
    return decode_payload(payload)


async def _read_exactly(stream: NetStream, n: int) -> bytes:
    """Read exactly n bytes from a libp2p NetStream.

    NetStream.read(n) may return fewer bytes than requested,
    so we loop until we have the full amount.
    """
    buf = b""
    while len(buf) < n:
        chunk = await stream.read(n - len(buf))
        if not chunk:
            raise ConnectionError(f"Stream closed: expected {n} bytes, got {len(buf)}")
        buf += chunk
    return buf
