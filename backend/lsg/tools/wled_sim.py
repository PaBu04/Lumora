"""Minimal WLED simulator for testing without hardware.

    python -m lsg.tools.wled_sim --name Sim1 --leds 300 --http 8081 --ddp 4048 [--rgbw]

Answers /json/info and /json/state, receives DDP frames and registers itself via mDNS
(_wled._tcp). /sim/stats reports received frames and fps, /sim/frame the last frame.
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


class SimState:
    def __init__(self, leds: int, rgbw: bool):
        self.channels = 4 if rgbw else 3
        self.leds = leds
        self.rgbw = rgbw
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
            "leds": {"count": sim.leds, "rgbw": sim.rgbw, "lc": 3 if sim.rgbw else 1, "fps": 0, "maxpwr": 5000},
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
        ft = sim.frame_times
        fps = (len(ft) - 1) / (ft[-1] - ft[0]) if len(ft) > 1 and ft[-1] > ft[0] else 0.0
        return {"frames": sim.frames, "packets": sim.packets, "fps": round(fps, 1)}

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


async def run(name: str, leds: int, http_port: int, ddp_port: int, rgbw: bool, mdns: bool,
              stop: asyncio.Event | None = None) -> None:
    sim = SimState(leds, rgbw)
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: DdpProtocol(sim), local_addr=("0.0.0.0", ddp_port))
    azc = None
    if mdns:
        ip = _local_ip()
        info = ServiceInfo(
            "_wled._tcp.local.", f"{name}._wled._tcp.local.", addresses=[socket.inet_aton(ip)],
            port=http_port, properties={"mac": name}, server=f"{name.lower()}.local.",
        )
        azc = AsyncZeroconf()
        await azc.async_register_service(info)
    server = uvicorn.Server(uvicorn.Config(make_app(sim, name), host="0.0.0.0", port=http_port, log_level="warning"))
    print(f"WLED simulator {name}: http :{http_port}, ddp udp :{ddp_port}, {leds} LEDs{' RGBW' if rgbw else ''}", flush=True)
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
    ap.add_argument("--no-mdns", action="store_true")
    a = ap.parse_args()
    asyncio.run(run(a.name, a.leds, a.http, a.ddp, a.rgbw, not a.no_mdns))


if __name__ == "__main__":
    main()
