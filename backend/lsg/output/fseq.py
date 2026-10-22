"""FSEQ v2 sequence files (Falcon Player / xLights).

Layout (see FPP docs/FSEQ_Sequence_File_Format.txt):
  0-3  'PSEQ'                 4-5  offset of channel data     6 minor (0)  7 major (2)
  8-9  standard header length (32, index of the first variable header)
  10-13 channels per frame    14-17 frame count               18 step time (ms)
  19   flags (0)              20 low nibble: compression (0 none, 1 zstd), high nibble: block count bits 8-11
  21   block count bits 0-7   22 sparse ranges (0)            23 flags (0)    24-31 unique id
then the compression block index (frame number u32, compressed length u32 per block), the
variable headers (u16 length incl. these 4 bytes, 2 char code, NUL terminated text) and
finally the channel data (each zstd block is an independent zstd frame).
"""

import struct
import time
from collections.abc import Iterable
from pathlib import Path

try:  # Python 3.14+
    from compression import zstd
except ImportError:  # pragma: no cover - older Pythons write uncompressed files
    zstd = None

HEADER_SIZE = 32
MAX_BLOCKS = 255


def zstd_available() -> bool:
    return zstd is not None


def _variable_header(code: str, text: str) -> bytes:
    data = text.encode("utf-8") + b"\0"
    return struct.pack("<H", 4 + len(data)) + code.encode("ascii") + data


def write_fseq(
    path: Path,
    frames: Iterable[bytes],
    channels: int,
    frame_count: int,
    step_ms: int,
    media: str | None = None,
    producer: str = "Neopixel Light Show Generator",
    compress: bool = True,
) -> dict:
    """Write frames (each exactly `channels` bytes). Returns a small summary."""
    compress = compress and zstd is not None and frame_count > 0
    variable = (_variable_header("mf", media) if media else b"") + _variable_header("sp", producer)

    if compress:
        frames_per_block = max(1, -(-frame_count // MAX_BLOCKS))
        blocks: list[tuple[int, bytes]] = []
        chunk: list[bytes] = []
        first = 0
        for i, f in enumerate(frames):
            if len(f) != channels:
                raise ValueError(f"frame {i} has {len(f)} bytes, expected {channels}")
            chunk.append(f)
            if len(chunk) == frames_per_block:
                blocks.append((first, zstd.compress(b"".join(chunk), level=3)))
                first, chunk = i + 1, []
        if chunk:
            blocks.append((first, zstd.compress(b"".join(chunk), level=3)))
        index = b"".join(struct.pack("<II", fr, len(data)) for fr, data in blocks)
        payload = [data for _, data in blocks]
        block_count = len(blocks)
    else:
        index = b""
        payload = None
        block_count = 0

    data_offset = HEADER_SIZE + len(index) + len(variable)
    data_offset += (-data_offset) % 4  # keep channel data 4-byte aligned
    if data_offset > 0xFFFF:
        raise ValueError("header too large")
    header = struct.pack(
        "<4sHBBHIIBBBBBBQ",
        b"PSEQ",
        data_offset,
        0,
        2,
        HEADER_SIZE,
        channels,
        frame_count,
        step_ms,
        0,
        (1 if compress else 0) | ((block_count >> 8) & 0x0F) << 4,
        block_count & 0xFF,
        0,
        0,
        int(time.time() * 1_000_000),
    )
    assert len(header) == HEADER_SIZE
    written = 0
    with open(path, "wb") as fh:
        fh.write(header + index + variable)
        fh.write(b"\0" * (data_offset - HEADER_SIZE - len(index) - len(variable)))
        if payload is not None:
            for data in payload:
                fh.write(data)
                written += len(data)
        else:
            for i, f in enumerate(frames):
                if len(f) != channels:
                    raise ValueError(f"frame {i} has {len(f)} bytes, expected {channels}")
                fh.write(f)
                written += len(f)
    return {"frames": frame_count, "channels": channels, "step_ms": step_ms, "compressed": compress, "data_bytes": written}


def read_fseq(path: Path) -> dict:
    """Parse an FSEQ v2 file (used by tests and for sanity checks)."""
    raw = Path(path).read_bytes()
    (magic, data_offset, minor, major, std_len, channels, frames, step, _f, comp, blocks_lo, sparse, _f2, uid) = (
        struct.unpack_from("<4sHBBHIIBBBBBBQ", raw, 0)
    )
    if magic != b"PSEQ" or major != 2:
        raise ValueError("not an FSEQ v2 file")
    ctype = comp & 0x0F
    block_count = ((comp >> 4) << 8) | blocks_lo
    pos = std_len
    blocks = []
    for _ in range(block_count):
        blocks.append(struct.unpack_from("<II", raw, pos))
        pos += 8
    pos += 6 * sparse
    headers = {}
    while pos + 4 <= data_offset:
        (length,) = struct.unpack_from("<H", raw, pos)
        if length < 4:
            break
        headers[raw[pos + 2 : pos + 4].decode("ascii")] = raw[pos + 4 : pos + length].rstrip(b"\0").decode("utf-8")
        pos += length
    if ctype == 0:
        data = raw[data_offset : data_offset + channels * frames]
    elif ctype == 1:
        if zstd is None:
            raise ValueError("zstd not available")
        parts, p = [], data_offset
        for _frame, length in blocks:
            parts.append(zstd.decompress(raw[p : p + length]))
            p += length
        data = b"".join(parts)
    else:
        raise ValueError(f"unsupported compression {ctype}")
    return {
        "version": (major, minor),
        "channels": channels,
        "frames": frames,
        "step_ms": step,
        "compression": ctype,
        "blocks": blocks,
        "headers": headers,
        "unique_id": uid,
        "frame": lambda i: data[i * channels : (i + 1) * channels],
        "data_len": len(data),
    }
