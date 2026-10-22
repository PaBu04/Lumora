import socket
import struct

import numpy as np
import pytest

from lsg.geometry.led_table import build_led_table
from lsg.model.calibration import LedCalibration
from lsg.model.controller import Controller, FixtureMapping
from lsg.model.fixture import LedType
from lsg.output.ddp import DdpSender, build_packets, parse_packet
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
        Controller(
            id="b",
            host="y",
            mappings=[FixtureMapping(fixture_id="ring"), FixtureMapping(fixture_id="west", start=40, fixture_offset=2)],
        ),
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


# --- live output pacing ------------------------------------------------------------------


def test_output_link_paces_evenly_and_skips_static_frames():
    from lsg.output.link import KEEPALIVE_S, REPEATS, OutputLink

    link = OutputLink(rate=25.0, next_due=0.0)
    sent = []
    t = -0.01
    while t < 0.99:  # a 1 kHz loop asking with changing content
        if link.needs_frame(t, changing=True) and link.offer(bytes([int(t * 1000) % 256]), t):
            sent.append(t)
        t = round(t + 0.001, 6)
    gaps = np.diff(sent)
    assert len(sent) == 25 and np.allclose(gaps, 0.04, atol=0.0011)
    assert link.sent_fps(now=sent[-1]) == pytest.approx(25, rel=0.05)

    # unchanged content: sent, repeated REPEATS times, then only kept alive
    link = OutputLink(rate=50.0, next_due=0.0)
    sent = []
    t = 0.0
    while t < 2.0:
        if link.needs_frame(t, changing=True) and link.offer(b"same", t):
            sent.append(t)
        t = round(t + 0.001, 6)
    assert sent[: REPEATS + 1] == pytest.approx([0.0, 0.017, 0.037], abs=0.002)
    assert np.diff(sent[REPEATS + 1 :]).min() >= KEEPALIVE_S - 0.021
    assert len(sent) <= REPEATS + 1 + 2.0 / KEEPALIVE_S + 1

    # a forced update (seek while paused) goes out at once and restarts the schedule
    assert link.offer(b"new", 2.005, force=True)
    assert link.next_due == pytest.approx(2.025)


def test_wled_frame_rate_estimate():
    from lsg.output.wled import bus_ms, estimate_fps, limit_hint, recommended_fps

    # measured on a real ESP32: 873 WS2812B on one pin showed 32-33 FPS
    ms = bus_ms(22, 873)
    assert ms == pytest.approx(26.5, abs=0.3)
    one_pin = [{"type": 22, "len": 873, "pins": [16], "ms": ms}]
    assert estimate_fps(one_pin) == pytest.approx(32, abs=1)
    assert 28 <= recommended_fps(estimate_fps(one_pin), 50) < 31
    assert "873 LEDs an einem Datenpin" in limit_hint({"buses": one_pin, "max_fps": estimate_fps(one_pin)})

    # split over two pins: they output in parallel
    two = [{"type": 22, "len": 437, "ms": bus_ms(22, 437)}, {"type": 22, "len": 436, "ms": bus_ms(22, 436)}]
    assert estimate_fps(two) > 50 * 0.99 or estimate_fps(two) > 55
    # small RGBW strip (measured: 128 SK6812 show ~51 FPS): WLED itself is the limit, send at full rate
    small = [{"type": 30, "len": 128, "ms": bus_ms(30, 128)}]
    assert recommended_fps(estimate_fps(small), 50) == 50
    assert limit_hint({"buses": small, "max_fps": estimate_fps(small)}) is None
    assert bus_ms(51, 1000) == 0.0  # APA102 (clocked) is not limited by the data line
