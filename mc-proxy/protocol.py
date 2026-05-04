import asyncio
import zlib
from typing import Tuple


async def read_varint_async(reader: asyncio.StreamReader) -> int:
    result = 0
    shift = 0
    while True:
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result
        shift += 7
        if shift >= 35:
            raise ValueError("VarInt too large")


def decode_varint(data: bytes, pos: int = 0) -> Tuple[int, int]:
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
    raise ValueError("VarInt not terminated")


def write_varint(value: int) -> bytes:
    out = []
    value &= 0xFFFFFFFF
    while True:
        part = value & 0x7F
        value >>= 7
        if value:
            part |= 0x80
        out.append(part)
        if not value:
            return bytes(out)


def decode_string(data: bytes, pos: int = 0) -> Tuple[str, int]:
    length, pos = decode_varint(data, pos)
    s = data[pos : pos + length].decode("utf-8", errors="replace")
    return s, pos + length


def decode_uuid(data: bytes, pos: int = 0) -> Tuple[str, int]:
    import uuid

    raw = data[pos : pos + 16]
    return str(uuid.UUID(bytes=raw)), pos + 16


async def read_raw_packet(
    reader: asyncio.StreamReader, compression: int = -1
) -> Tuple[bytes, bytes]:
    """Return (wire_bytes, decompressed_payload).

    wire_bytes: raw bytes to forward unchanged.
    decompressed_payload: actual packet data (packet_id + fields).
    """
    length = await read_varint_async(reader)
    raw_body = await reader.readexactly(length)
    wire = write_varint(length) + raw_body

    if compression >= 0:
        data_len, pos = decode_varint(raw_body)
        compressed_part = raw_body[pos:]
        if data_len > 0:
            payload = zlib.decompress(compressed_part)
        else:
            payload = compressed_part
    else:
        payload = raw_body

    return wire, payload


def make_packet(payload: bytes, compression: int = -1) -> bytes:
    """Build a wire-format packet from uncompressed payload bytes."""
    if compression >= 0:
        if len(payload) >= compression:
            compressed = zlib.compress(payload)
            body = write_varint(len(payload)) + compressed
        else:
            body = write_varint(0) + payload
        return write_varint(len(body)) + body
    return write_varint(len(payload)) + payload
