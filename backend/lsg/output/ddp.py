"""DDP (Distributed Display Protocol) packets as understood by WLED (UDP port 4048).

Header (10 bytes):
  0  flags: version 1 (0x40) | push (0x01, last packet of a frame)
  1  sequence number 1..15 (lower nibble)
  2  data type: 0x0B = RGB 8 bit, 0x1B = RGBW 8 bit
  3  destination id: 1 = default output device
  4-7 data offset in bytes (big endian)
  8-9 data length in bytes (big endian)
"""

import contextlib
import socket
import struct

DDP_PORT = 4048
DDP_VERSION = 0x40
DDP_PUSH = 0x01
DDP_TYPE_RGB = 0x0B
DDP_TYPE_RGBW = 0x1B
DDP_ID_DISPLAY = 1
MAX_DATA = 1440  # bytes per packet: 480 RGB or 360 RGBW pixels (WLED limit)


def build_packets(data: bytes, rgbw: bool, sequence: int) -> list[bytes]:
    channels = 4 if rgbw else 3
    chunk = MAX_DATA - (MAX_DATA % channels)
    packets = []
    for offset in range(0, max(len(data), 1), chunk):
        part = data[offset : offset + chunk]
        last = offset + chunk >= len(data)
        flags = DDP_VERSION | (DDP_PUSH if last else 0)
        header = struct.pack(
            ">BBBBIH", flags, sequence & 0x0F, DDP_TYPE_RGBW if rgbw else DDP_TYPE_RGB, DDP_ID_DISPLAY, offset, len(part)
        )
        packets.append(header + part)
    return packets


def parse_packet(packet: bytes) -> dict:
    """Inverse of build_packets for one packet (used by the WLED simulator and tests)."""
    flags, seq, dtype, dest, offset, length = struct.unpack(">BBBBIH", packet[:10])
    return {
        "push": bool(flags & DDP_PUSH),
        "version": flags >> 6,
        "sequence": seq,
        "rgbw": dtype == DDP_TYPE_RGBW,
        "dest": dest,
        "offset": offset,
        "data": packet[10 : 10 + length],
    }


class DdpSender:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # room for a whole frame burst (5000 LEDs = 11 packets); a full buffer would drop frames
        with contextlib.suppress(OSError):
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        self.sock.setblocking(False)
        self._seq: dict[tuple[str, int], int] = {}
        self.errors: dict[str, str] = {}

    def send(self, host: str, port: int, data: bytes, rgbw: bool) -> None:
        key = (host, port)
        seq = self._seq.get(key, 0) % 15 + 1
        self._seq[key] = seq
        try:
            for pkt in build_packets(data, rgbw, seq):
                self.sock.sendto(pkt, (host, port))
            self.errors.pop(host, None)
        except OSError as exc:  # unreachable host, full buffer: drop the frame
            self.errors[host] = str(exc)

    def close(self) -> None:
        self.sock.close()
