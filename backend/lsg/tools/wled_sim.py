"""Minimal WLED simulator for testing without hardware.

    python -m lsg.tools.wled_sim --name Sim1 --leds 300 --http 8081 --ddp 4048 [--rgbw]

Answers /json/info, /json/cfg and /json/state, receives DDP frames and registers itself via
mDNS (_wled._tcp). Like a real WLED it can only show a frame when its LED data lines are free
(WS2812B: 30 us per LED and pin, plus loop overhead, at most every 16 ms); /json/info reports
the frames it showed. /sim/stats reports received and shown fps, /sim/frame the last frame.
"""

import argparse
import asyncio
import socket
import time

import uvicorn
from fastapi import FastAPI
from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from lsg.output.ddp import parse_packet
from lsg.output.wled import WLED_OVERHEAD_MS, bus_ms


class SimState:
    def __init__(self, leds: int, rgbw: bool, pins: int = 1):
        self.channels = 4 if rgbw else 3
        self.leds = leds
        self.rgbw = rgbw
        self.bus_type = 30 if rgbw else 22
        sizes = [leds // pins + (1 if i < leds % pins else 0) for i in range(pins)]
        self.buses = [{"start": sum(sizes[:i]), "len": n, "pin": [16 + i], "type": self.bus_type} for i, n in enumerate(sizes)]
        self.frame_s = max(max(bus_ms(self.bus_type, n) for n in sizes) + WLED_OVERHEAD_MS, 16.0) / 1000.0
        self.ready_at = 0.0
        self.pending = False
        self.shown_times: list[float] = []
        self.buffer = bytearray(leds * self.channels)
        self.last_frame = bytes(self.buffer)
        self.frames = 0
        self.packets = 0
        self.frame_times: list[float] = []
        self.state = {"on": True, "bri": 128}


class DdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimState):
        self.sim = sim

    def datagram_received(self, data, addr):
        sim = self.sim
        try:
            p = parse_packet(data)
        except Exception:
            return
        sim.packets += 1
        end = min(len(sim.buffer), p["offset"] + len(p["data"]))
        sim.buffer[p["offset"] : end] = p["data"][: end - p["offset"]]
        if p["push"]:
            sim.frames += 1
            sim.last_frame = bytes(sim.buffer)
            now = time.monotonic()
            sim.frame_times = [t for t in sim.frame_times if now - t < 2.0] + [now]
            _catch_up(sim, now)
            if now >= sim.ready_at:
                _show(sim, now)
            else:  # LEDs still busy: WLED shows the newest data once they are free
                sim.pending = True


def _show(sim: SimState, at: float) -> None:
    sim.shown_times = [t for t in sim.shown_times if at - t < 2.0] + [at]
    sim.ready_at = at + sim.frame_s


def _catch_up(sim: SimState, now: float) -> None:
    if sim.pending and now >= sim.ready_at:
        sim.pending = False
        _show(sim, sim.ready_at)


def _rate(times: list[float]) -> float:
    if len(times) > 1 and times[-1] > times[0] and time.monotonic() - times[-1] < 1.0:
        return (len(times) - 1) / (times[-1] - times[0])
    return 0.0


def _fps(sim: SimState) -> float:
    return _rate(sim.frame_times)


def _shown_fps(sim: SimState) -> float:
    _catch_up(sim, time.monotonic())
    return _rate(sim.shown_times)


def make_app(sim: SimState, name: str) -> FastAPI:
    app = FastAPI()

    @app.get("/json/info")
    def info():
        return {
            "ver": "0.15.0-sim",
            "name": name,
            "mac": "".join(f"{b:02x}" for b in name.encode()[:6].ljust(6, b"0")),
            "arch": "sim",
            "live": bool(sim.frame_times) and time.monotonic() - sim.frame_times[-1] < 2.5,
            "leds": {
                "count": sim.leds,
                "rgbw": sim.rgbw,
                "lc": 3 if sim.rgbw else 1,
                "fps": round(_shown_fps(sim)),
                "maxpwr": 5000,
            },
            "wifi": {"rssi": -58, "signal": 84, "channel": 6},
        }

    @app.get("/json/cfg")
    def cfg():
        return {
            "hw": {"led": {"total": sim.leds, "fps": 42, "ins": sim.buses}},
            "wifi": {"sleep": False},
            "if": {"live": {"en": True, "timeout": 25}},
        }

    @app.get("/json/state")
    def get_state():
        return sim.state

    @app.post("/json/state")
    def post_state(body: dict):
        sim.state.update(body)
        return sim.state

    @app.get("/sim/stats")
    def stats():
        return {
            "frames": sim.frames,
            "packets": sim.packets,
            "fps": round(_fps(sim), 1),
            "shown_fps": round(_shown_fps(sim), 1),
        }

    @app.get("/sim/frame")
    def frame():
        return {"channels": sim.channels, "data": list(sim.last_frame)}

    return app


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


async def run(
    name: str,
    leds: int,
    http_port: int,
    ddp_port: int,
    rgbw: bool,
    mdns: bool,
    stop: asyncio.Event | None = None,
    pins: int = 1,
) -> None:
    sim = SimState(leds, rgbw, pins)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: DdpProtocol(sim), local_addr=("0.0.0.0", ddp_port))
    azc = None
    if mdns:
        ip = _local_ip()
        info = ServiceInfo(
            "_wled._tcp.local.",
            f"{name}._wled._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=http_port,
            properties={"mac": name},
            server=f"{name.lower()}.local.",
        )
        azc = AsyncZeroconf()
        await azc.async_register_service(info)
    server = uvicorn.Server(uvicorn.Config(make_app(sim, name), host="0.0.0.0", port=http_port, log_level="warning"))
    print(
        f"WLED simulator {name}: http :{http_port}, ddp udp :{ddp_port}, {leds} LEDs{' RGBW' if rgbw else ''} on {pins} pin(s), "
        f"shows max. {1 / sim.frame_s:.0f} FPS",
        flush=True,
    )

    async def watch_stop():
        await stop.wait()
        server.should_exit = True

    watcher = asyncio.create_task(watch_stop()) if stop else None
    try:
        await server.serve()
    finally:
        if watcher:
            watcher.cancel()
        transport.close()
        if azc:
            await azc.async_unregister_all_services()
            await azc.async_close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="WLED-Sim")
    ap.add_argument("--leds", type=int, default=300)
    ap.add_argument("--http", type=int, default=8081)
    ap.add_argument("--ddp", type=int, default=4048)
    ap.add_argument("--rgbw", action="store_true")
    ap.add_argument("--pins", type=int, default=1, help="LED data pins the LEDs are split across")
    ap.add_argument("--no-mdns", action="store_true")
    a = ap.parse_args()
    asyncio.run(run(a.name, a.leds, a.http, a.ddp, a.rgbw, not a.no_mdns, pins=a.pins))


if __name__ == "__main__":
    main()
