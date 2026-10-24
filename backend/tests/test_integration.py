"""End-to-end: real HTTP server, WLED simulator receiving DDP, tool client (as Claude Code uses it)."""

import asyncio
import contextlib
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import Client

from lumora.app import create_app
from lumora.tools import wled_sim

# shared CI runners have two slow cores: they render fewer frames than a desktop
MIN_FULL_FPS = 25 if os.environ.get("CI") else 42


def until(fn, timeout: float = 8.0, step: float = 0.2):
    """Poll fn until it returns something truthy; the last value when time runs out."""
    end = time.time() + timeout
    while True:
        v = fn()
        if v or time.time() > end:
            return v
        time.sleep(step)


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


@contextlib.contextmanager
def simulated_wled(leds: int = 200, pins: int = 1):
    http_port, ddp_port = free_port(), free_port(socket.SOCK_DGRAM)
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    stop = asyncio.Event()
    coro = wled_sim.run("Sim", leds, http_port, ddp_port, False, False, stop, pins=pins)
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
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


@pytest.fixture
def wled():
    with simulated_wled() as ports:
        yield ports


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
    # a static frame is sent, repeated twice and then only kept alive (2 per second)
    assert 3 <= stats["frames"] <= 8, stats
    assert frame[:30] == [0] * 30  # pixels 0..9 unmapped
    assert frame[30:33] == [255, 0, 0] and frame[(10 + 119) * 3 : (10 + 120) * 3] == [255, 0, 0]
    state = httpx.get(f"{server}/api/playback").json()
    assert state["links"]["c1"]["rate"] == 50  # 200 LEDs on the simulated pin are no bottleneck

    # moving content goes out at the full, evenly spaced rate
    show["layers"][0]["clips"][0].update(effect="rainbow", params={"speed": 2})
    httpx.put(f"{server}/api/projects/{slug}/shows/{show['id']}", json=show)
    sim_stats = lambda: httpx.get(f"http://127.0.0.1:{http_port}/sim/stats").json()  # noqa: E731
    stats = until(lambda: (s := sim_stats())["fps"] > MIN_FULL_FPS and s) or sim_stats()
    httpx.post(f"{server}/api/playback/stop")
    assert stats["fps"] > MIN_FULL_FPS, stats
    show["layers"][0]["clips"][0].update(effect="solid", params={"color": "#ff0000"})
    httpx.put(f"{server}/api/projects/{slug}/shows/{show['id']}", json=show)

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


def test_slow_controller_gets_frames_it_can_show(server, monkeypatch):
    """900 WS2812B on one pin can show ~31 FPS: the app sends evenly just below that and
    the speed test finds the limit."""
    monkeypatch.setattr("lumora.playback.session.MONITOR_SECONDS", 0.3)
    with simulated_wled(leds=900) as (http_port, ddp_port):
        host = f"127.0.0.1:{http_port}"
        slug = setup_project(server, [{"id": "c1", "host": host, "port": ddp_port, "mappings": [{"fixture_id": "s1"}]}])
        show = httpx.post(f"{server}/api/projects/{slug}/shows", json={"name": "S", "template": "empty"}).json()
        show["duration"] = 60
        show["layers"] = [{"name": "L", "clips": [{"start": 0, "end": 60, "effect": "rainbow", "params": {"speed": 2}}]}]
        httpx.put(f"{server}/api/projects/{slug}/shows/{show['id']}", json=show)
        httpx.post(f"{server}/api/playback/load", json={"project": slug, "show": show["id"]})
        httpx.post(f"{server}/api/playback/mode", json={"mode": "live"})
        httpx.post(f"{server}/api/playback/play")
        # the monitor reads /json/cfg and lowers the rate
        playback = lambda: httpx.get(f"{server}/api/playback").json()  # noqa: E731
        state = until(lambda: (s := playback())["links"]["c1"]["rate"] <= 30 and s) or playback()
        assert 27 <= state["links"]["c1"]["rate"] <= 30, state["links"]
        st = state["controller_status"]["c1"]
        assert "900 LEDs an einem Datenpin" in st["hints"][0]
        time.sleep(1.5)
        stats = httpx.get(f"http://127.0.0.1:{http_port}/sim/stats").json()
        # a busy runner sends unevenly: fewer frames, and bunched ones the simulated pin drops
        if not os.environ.get("CI"):
            assert abs(stats["fps"] - state["links"]["c1"]["rate"]) < 2.5, stats
            assert stats["shown_fps"] >= stats["fps"] - 1.5, stats  # nothing dropped by the controller

        r = httpx.post(f"{server}/api/playback/speedtest", json={"controller_id": "c1"}, timeout=20)
        assert r.status_code == 200, r.text
        res = r.json()
        assert 28 <= res["measured_fps"] <= 33 and res["loss_pct"] == 0, res
        assert 26 <= res["recommended_fps"] <= 30
        assert res["estimated_fps"] == pytest.approx(31, abs=1)

        # a manual rate wins over the automatic one
        p = httpx.get(f"{server}/api/projects/{slug}").json()
        p["controllers"][0]["max_fps"] = 20
        assert httpx.put(f"{server}/api/projects/{slug}", json=p).status_code == 200
        time.sleep(1.2)
        assert httpx.get(f"{server}/api/playback").json()["links"]["c1"]["rate"] == 20
        httpx.post(f"{server}/api/playback/stop")


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
            assert len(a["drums"]["hihat"]) > 10 and "kick_per_bar" in a["drum_density"][0]  # intro: hats only
            inst = a["instruments"]
            assert inst["available"] and inst["sections"] and "drop" in inst["moments"]
            ev = (
                await c.call_tool("get_song_events", {"song_id": song["id"], "tracks": ["kick", "bass"], "end": 16})
            ).structured_content
            assert ev["tracks"]["kick"] and all(len(e) == 4 and e[0] < 16 for e in ev["tracks"]["bass"])
            bad = (await c.call_tool("get_song_events", {"song_id": song["id"], "tracks": ["kazoo"]})).structured_content
            assert not bad["ok"] and "available" in bad["error"]
            fx = ov["fixtures"][0]
            assert 0 <= fx["direct_view_share"] <= 1 and fx["role"] and fx["leds_per_m"] == pytest.approx(30, abs=1)

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
            assert [i for i in res["issues"] if i["severity"] == "error"] == []

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
            light = (await c.call_tool("analyze_light", {"show_id": sid})).structured_content
            assert 0 <= light["room_light"] < 1 and light["sections"] and isinstance(light["hints"], list)
            pw = (await c.call_tool("analyze_power", {"show_id": sid})).structured_content
            assert pw["ok"] is False  # no controllers in this project yet

            looks = (await c.call_tool("list_looks", {})).structured_content["result"]
            assert any(x["id"] == "builtin-drop" for x in looks)
            r = (
                await c.call_tool("apply_look", {"show_id": sid, "look_id": "builtin-drop", "at": 8.1, "layer": "Drops"})
            ).structured_content
            assert r["ok"] and len(r["added"]) == 2 and "Drops" in r["layers"]

            vs = (await c.call_tool("list_show_versions", {"show_id": sid})).structured_content["versions"]
            assert vs[0]["source"] == "ai" and len(vs) >= 3
            r = (await c.call_tool("restore_show_version", {"show_id": sid, "version_id": vs[-1]["id"]})).structured_content
            assert r["ok"] and r["clips"] == 0  # back to the empty show

            st = (await c.call_tool("preview", {"show_id": sid, "start": 2.0})).structured_content
            assert st["playing"] and st["show"] == sid

    asyncio.run(run())
