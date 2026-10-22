"""End-to-end: real HTTP server, WLED simulator receiving DDP, MCP client."""

import asyncio
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import Client

from lsg.app import create_app
from lsg.tools import wled_sim


def free_port(kind=socket.SOCK_STREAM) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerThread(threading.Thread):
    def __init__(self, app, port):
        super().__init__(daemon=True)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def run(self):
        self.server.run()

    def stop(self):
        self.server.should_exit = True
        self.join(5)


@pytest.fixture
def server(tmp_path):
    port = free_port()
    t = ServerThread(create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x"), port)
    t.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(base + "/api/projects")
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield base
    t.stop()


@pytest.fixture
def wled():
    http_port, ddp_port = free_port(), free_port(socket.SOCK_DGRAM)
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    stop = asyncio.Event()
    fut = asyncio.run_coroutine_threadsafe(wled_sim.run("Sim", 200, http_port, ddp_port, False, False, stop), loop)
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{http_port}/json/info")
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield http_port, ddp_port
    loop.call_soon_threadsafe(stop.set)
    fut.result(timeout=5)
    loop.call_soon_threadsafe(loop.stop)


def setup_project(base: str, controllers: list | None = None) -> str:
    slug = httpx.post(base + "/api/projects", json={"name": "Live"}).json()["slug"]
    p = httpx.get(f"{base}/api/projects/{slug}").json()
    p["fixtures"] = [
        {
            "id": "s1",
            "name": "Strip",
            "geometry": {"type": "polyline", "points": [[0, 3, 2], [4, 3, 2]]},
            "led_count": 120,
            "tags": ["wall"],
        }
    ]
    p["controllers"] = controllers or []
    r = httpx.put(f"{base}/api/projects/{slug}", json=p)
    assert r.status_code == 200, r.text
    return slug


def test_live_output_reaches_wled(server, wled):
    http_port, ddp_port = wled
    info = httpx.get(f"{server}/api/devices/info", params={"host": f"127.0.0.1:{http_port}"}).json()
    assert info["led_count"] == 200 and info["name"] == "Sim"
    slug = setup_project(
        server,
        [{"id": "c1", "host": f"127.0.0.1:{http_port}", "port": ddp_port, "mappings": [{"fixture_id": "s1", "start": 10}]}],
    )
    show = httpx.post(f"{server}/api/projects/{slug}/shows", json={"name": "S", "template": "empty"}).json()
    show["duration"] = 30
    show["layers"] = [{"name": "L", "clips": [{"start": 0, "end": 30, "effect": "solid", "params": {"color": "#ff0000"}}]}]
    httpx.put(f"{server}/api/projects/{slug}/shows/{show['id']}", json=show)
    p = httpx.get(f"{server}/api/projects/{slug}").json()
    p["calibration"]["ws2812b"] = {"curve": "gamma", "gamma": 1.0, "cutoff": 0.0}  # identity curve
    assert httpx.put(f"{server}/api/projects/{slug}", json=p).status_code == 200
    httpx.post(f"{server}/api/playback/load", json={"project": slug, "show": show["id"]})
    httpx.post(f"{server}/api/playback/mode", json={"mode": "live"})
    httpx.post(f"{server}/api/playback/play")
    time.sleep(1.5)
    stats = httpx.get(f"http://127.0.0.1:{http_port}/sim/stats").json()
    frame = httpx.get(f"http://127.0.0.1:{http_port}/sim/frame").json()["data"]
    httpx.post(f"{server}/api/playback/stop")
    assert stats["frames"] > 30 and stats["fps"] > 35
    assert frame[:30] == [0] * 30  # pixels 0..9 unmapped
    assert frame[30:33] == [255, 0, 0] and frame[(10 + 119) * 3 : (10 + 120) * 3] == [255, 0, 0]

    power = httpx.get(f"{server}/api/projects/{slug}/shows/{show['id']}/power", params={"fps": 1}).json()
    assert power["controllers"]["c1"]["peak_ma"] > 0
    state = httpx.get(f"{server}/api/playback").json()
    assert state["power"]["controllers"]["c1"]["ma"] > 0

    # calibration pattern with raw PWM steps
    httpx.post(f"{server}/api/playback/test", json={"enabled": True, "fixture_id": "s1", "kind": "steps"})
    time.sleep(0.4)
    frame = httpx.get(f"http://127.0.0.1:{http_port}/sim/frame").json()["data"]
    assert sorted(set(frame[30 : (10 + 120) * 3]) - {0}) == [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 24, 32, 48, 64, 96, 128, 192, 255]

    # sync test: click track loops, LEDs flash; the controller monitor reports the simulator
    st = httpx.post(f"{server}/api/playback/sync", json={"enabled": True, "bpm": 120}).json()
    assert st["sync"]["bpm"] == 120 and st["playing"] and st["show"] == "__sync__"
    time.sleep(3.6)
    st = httpx.get(f"{server}/api/playback").json()
    status = st["controller_status"]["c1"]
    assert status["ok"] and status["info"]["name"] == "Sim" and status["warnings"] == []
    st = httpx.post(f"{server}/api/playback/sync", json={"enabled": False}).json()
    assert st["sync"] is None and st["show"] == show["id"]

    # test pattern: first LED green, last red
    httpx.post(f"{server}/api/playback/test", json={"enabled": True, "fixture_id": "s1"})
    time.sleep(0.4)
    frame = httpx.get(f"http://127.0.0.1:{http_port}/sim/frame").json()["data"]
    assert frame[30:33] == [0, 255, 0] and frame[129 * 3 : 130 * 3] == [255, 0, 0]


def test_mcp_tools(server):
    slug = setup_project(server)
    song = httpx.post(f"{server}/api/songs/demo", params={"bpm": 120}).json()

    async def run():
        async with Client(f"{server}/mcp") as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            assert {
                "get_overview",
                "get_song_analysis",
                "create_show",
                "add_clips",
                "render_snapshot",
                "render_timeline",
                "write_shader",
                "validate",
                "preview",
            } <= tools

            ov = (await c.call_tool("get_overview", {})).structured_content
            assert ov["project"] == slug and ov["fixtures"][0]["led_count"] == 120

            for _ in range(120):
                a = (await c.call_tool("get_song_analysis", {"song_id": song["id"], "end": 16})).structured_content
                if a.get("bpm"):
                    break
                await asyncio.sleep(0.5)
            assert a["bpm"] == pytest.approx(120, abs=1) and len(a["curves"]["times"]) == 64

            created = (await c.call_tool("create_show", {"name": "AI", "song_id": song["id"]})).structured_content
            sid = created["show_id"]
            res = (
                await c.call_tool(
                    "add_clips",
                    {
                        "show_id": sid,
                        "layer": "Base",
                        "clips": [
                            {"id": "w", "start": 0, "end": 16, "effect": "wave", "params": {"axis": "azimuth", "beats": 2}},
                            {"id": "bad", "start": 0, "end": 16, "effect": "wave", "params": {"axis": "sideways"}},
                        ],
                    },
                )
            ).structured_content
            assert res["ok"] and any(i["clip"] == "bad" for i in res["issues"])
            res = (
                await c.call_tool("update_clips", {"show_id": sid, "updates": [{"id": "bad", "params": {"axis": "u"}}]})
            ).structured_content
            assert res["issues"] == []

            shader = "def render(t, leds, audio, params):\n    return hsv(leds.u + t, 1, audio.rms)"
            assert (await c.call_tool("write_shader", {"name": "hue", "code": shader})).structured_content["ok"]
            bad = (
                await c.call_tool("write_shader", {"name": "bad", "code": "def render(t, leds, audio, params):\n    return 1/0"})
            ).structured_content
            assert not bad["ok"] and "ZeroDivision" in bad["error"]

            img = await c.call_tool("render_snapshot", {"show_id": sid, "t": 4.0})
            assert img.content[0].type == "image" and img.content[0].mime_type == "image/png"
            img = await c.call_tool("render_timeline", {"show_id": sid, "start": 0, "end": 16})
            assert img.content[0].type == "image"

            ov = (await c.call_tool("get_overview", {})).structured_content
            assert ov["brightness"]["recommended"]["avoid_below"] == 0.03
            assert ov["power"]["full_white_ma"] > 0
            pw = (await c.call_tool("analyze_power", {"show_id": sid})).structured_content
            assert pw["ok"] is False  # no controllers in this project yet

            vs = (await c.call_tool("list_show_versions", {"show_id": sid})).structured_content["versions"]
            assert vs[0]["source"] == "ai" and len(vs) >= 3
            r = (await c.call_tool("restore_show_version", {"show_id": sid, "version_id": vs[-1]["id"]})).structured_content
            assert r["ok"] and r["clips"] == 0  # back to the empty show

            st = (await c.call_tool("preview", {"show_id": sid, "start": 2.0})).structured_content
            assert st["playing"] and st["show"] == sid

    asyncio.run(run())
