import socket
import struct
import time

import numpy as np

from lsg.geometry.led_table import build_led_table
from lsg.model.controller import Controller, FixtureMapping
from lsg.model.fixture import LedType
from lsg.output.ddp import DdpSender, build_packets, parse_packet
from lsg.model.calibration import LedCalibration
from lsg.output.pipeline import OutputPipeline


def test_ddp_header_layout():
    data = bytes(range(256)) * 6  # 1536 bytes = 512 RGB pixels -> 2 packets
    pkts = build_packets(data, rgbw=False, sequence=3)
    assert len(pkts) == 2
    flags, seq, dtype, dest, offset, length = struct.unpack(">BBBBIH", pkts[0][:10])
    assert (flags, seq, dtype, dest, offset, length) == (0x40, 3, 0x0B, 1, 0, 1440)
    flags, _, _, _, offset, length = struct.unpack(">BBBBIH", pkts[1][:10])
    assert (flags, offset, length) == (0x41, 1440, 96)  # push flag on the last packet
    assert b"".join(p[10:] for p in pkts) == data


def test_ddp_rgbw_chunks_whole_pixels():
    pkts = build_packets(bytes(400 * 4), rgbw=True, sequence=1)
    assert [parse_packet(p)["rgbw"] for p in pkts] == [True, True]
    assert len(parse_packet(pkts[0])["data"]) % 4 == 0


def test_mapping_and_encoding(project):
    project.fixtures[0].led_type = LedType.SK6812_RGBW
    project.controllers = [
        Controller(id="a", host="x", rgbw=True, mappings=[FixtureMapping(fixture_id="north", start=10, count=5)]),
        Controller(id="b", host="y", mappings=[FixtureMapping(fixture_id="ring"), FixtureMapping(fixture_id="west", start=40, fixture_offset=2)]),
    ]
    # identity curve so byte values are easy to predict
    for t in project.calibration:
        project.calibration[t] = LedCalibration(curve="gamma", gamma=1.0, min_level=1, cutoff=0.0, white_mode="min")
    table = build_led_table(project)
    pipe = OutputPipeline(project, table)
    frame = np.zeros((table.count, 3), np.float32)
    frame[table.fixture_slice("north").start] = [1.0, 1.0, 0.5]
    frame[table.fixture_slice("ring")] = [0.0, 0.0, 1.0]
    outputs, stats = pipe.encode_all(lambda c: frame)
    a, b = outputs[0].data, outputs[1].data
    assert len(a) == 15 * 4
    assert a[40:44] == bytes([127, 127, 0, 128])  # pwm (255, 255, 128): white extracted
    assert a[:40] == bytes(40)
    assert set(stats.controllers) == {"a", "b"}
    west = table.fixture_slice("west")
    assert len(b) == (40 + west.stop - west.start - 2) * 3
    assert b[:3] == bytes([0, 0, 255])


def test_sender_delivers_frames():
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(2)
    port = rx.getsockname()[1]
    sender = DdpSender()
    data = bytes([7]) * (600 * 3)
    sender.send("127.0.0.1", port, data, rgbw=False)
    received = bytearray(len(data))
    push = False
    while not push:
        p = parse_packet(rx.recv(2000))
        received[p["offset"] : p["offset"] + len(p["data"])] = p["data"]
        push = p["push"]
    assert bytes(received) == data
    sender.close()
    rx.close()
