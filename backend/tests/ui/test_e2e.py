"""Browser end-to-end test of the main workflows (run with `pytest -m ui`).

Needs a built frontend (`npm run build` in frontend/) and Playwright Chromium
(`python -m playwright install chromium`). Screenshots are written to tests/ui/artifacts/.
"""

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from lsg.app import create_app
from lsg.tools import wled_sim

pytestmark = pytest.mark.ui

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "dist"
ARTIFACTS = Path(__file__).parent / "artifacts"


def free_port(kind=socket.SOCK_STREAM) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_http(url: str) -> None:
    for _ in range(200):
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise TimeoutError(url)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    if not (FRONTEND / "index.html").is_file():
        pytest.skip("frontend not built (npm run build)")
    pw = pytest.importorskip("playwright.sync_api")
    import uvicorn

    data = tmp_path_factory.mktemp("data")
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(data_dir=data, audio="null", fps=50, frontend=FRONTEND), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    threading.Thread(target=server.run, daemon=True).start()

    sim_http, sim_ddp = free_port(), free_port(socket.SOCK_DGRAM)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    stop = asyncio.Event()
    sim = asyncio.run_coroutine_threadsafe(wled_sim.run("Sim", 1200, sim_http, sim_ddp, False, False, stop), loop)

    base = f"http://127.0.0.1:{port}"
    wait_http(base + "/api/projects")
    wait_http(f"http://127.0.0.1:{sim_http}/json/info")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        except Exception as exc:  # browser not installed
            pytest.skip(f"Playwright Chromium not available: {exc}")
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        yield {"page": page, "base": base, "sim": f"http://127.0.0.1:{sim_http}", "ddp": sim_ddp, "errors": errors}
        browser.close()
    loop.call_soon_threadsafe(stop.set)
    sim.result(timeout=5)
    server.should_exit = True


def shot(page, name: str) -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=str(ARTIFACTS / f"{name}.png"))


def api(env, path: str):
    return httpx.get(env["base"] + path, timeout=10).json()


def test_full_workflow(env):
    page = env["page"]
    page.goto(env["base"])

    # project
    page.fill(".welcome input", "E2E Raum")
    page.click("text=Projekt anlegen")
    page.wait_for_selector("text=Raumhöhe")
    slug = api(env, "/api/projects")["active"]
    assert slug == "e2e-raum"

    # room template
    inputs = page.locator(".card input[type=number]")
    inputs.nth(0).fill("6")
    inputs.nth(1).fill("4.5")
    inputs.nth(1).press("Enter")
    page.click("text=Übernehmen")
    page.wait_for_timeout(1200)
    xs = [p[0] for p in api(env, f"/api/projects/{slug}")["room"]["floor"]]
    assert max(xs) == 6
    shot(page, "01_room")

    # strips from presets
    page.click("nav >> text=LED-Strips")
    for label in ["Deckenumrandung", "Deckenring", "Wandleiste"]:
        page.click(f"button:has-text('{label}')")
        page.wait_for_timeout(600)
    page.wait_for_timeout(800)
    project = api(env, f"/api/projects/{slug}")
    assert len(project["fixtures"]) == 3
    leds = api(env, f"/api/projects/{slug}/leds")["count"]
    assert leds > 1000
    shot(page, "02_fixtures")

    # controller (manual, the simulator answers like WLED)
    page.click("nav >> text=Controller")
    page.fill(".card:has-text('Manuell hinzufügen') input", env["sim"].replace("http://", ""))
    page.click(".card:has-text('Manuell hinzufügen') button:has-text('Hinzufügen')")
    page.wait_for_selector("text=Zuordnung")
    port = page.locator(".field:has-text('DDP-Port') input")
    port.fill(str(env["ddp"]))
    port.press("Enter")
    page.click("button:has-text('Alle freien Strips anhängen')")
    page.wait_for_timeout(1500)
    ctrl = api(env, f"/api/projects/{slug}")["controllers"][0]
    assert ctrl["port"] == env["ddp"] and len(ctrl["mappings"]) == 3
    page.wait_for_selector("text=verbunden", timeout=10000)
    shot(page, "03_controller")

    # song
    page.click("nav >> text=Songs")
    page.click("text=Demo-Song erzeugen")
    page.wait_for_selector(".list .badge.ok", timeout=120000)
    shot(page, "04_song")

    # show: starter template, play live
    page.click("nav >> text=Shows")
    page.fill(".card input[type=text]", "E2E Show")
    page.click("button:has-text('Erstellen')")
    page.wait_for_selector(".tl-clip")
    show_id = api(env, "/api/playback")["show"]
    assert show_id
    page.click("button:has-text('Vorschau')")  # -> live
    before = httpx.get(env["sim"] + "/sim/stats").json()["frames"]
    page.keyboard.press("Space")
    page.wait_for_timeout(2500)
    stats = httpx.get(env["sim"] + "/sim/stats").json()
    assert stats["frames"] - before > 60 and stats["fps"] > 30
    assert api(env, "/api/playback")["power"]["total_ma"] > 0
    page.keyboard.press("Space")
    shot(page, "05_show_live")

    # editor: drop an effect into a layer, undo it
    n0 = sum(len(l["clips"]) for l in api(env, f"/api/projects/{slug}/shows/{show_id}")["layers"])
    row = page.locator(".tl-row").nth(1)
    box = row.bounding_box()
    page.locator(".effect-chip:has-text('Sparkle')").drag_to(
        row, target_position={"x": box["width"] * 0.6, "y": box["height"] / 2}
    )
    page.wait_for_timeout(1500)
    n1 = sum(len(l["clips"]) for l in api(env, f"/api/projects/{slug}/shows/{show_id}")["layers"])
    assert n1 == n0 + 1
    shot(page, "06_editor")
    page.keyboard.press("Control+z")
    page.wait_for_timeout(1500)
    n2 = sum(len(l["clips"]) for l in api(env, f"/api/projects/{slug}/shows/{show_id}")["layers"])
    assert n2 == n0
    assert api(env, f"/api/projects/{slug}/shows/{show_id}/versions")[0]["source"] == "ui"

    # calibration pattern reaches the LEDs as raw PWM steps
    page.click("nav >> text=Kalibrierung")
    page.click(".card:has-text('Mindeststufe finden') >> button:has-text('Muster zeigen')")
    page.wait_for_timeout(800)
    frame = httpx.get(env["sim"] + "/sim/frame").json()["data"]
    assert {1, 2, 3, 255} <= set(frame)
    shot(page, "07_calibration")
    page.click("button:has-text('Muster beenden')")

    assert env["errors"] == []
