"""Browser end-to-end test of the main workflows (run with `pytest -m ui`).

Needs a built frontend (`npm run build` in frontend/) and Playwright Chromium
(`python -m playwright install chromium`). Screenshots are written to tests/ui/artifacts/.
"""

import asyncio
import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from lumora.app import create_app
from lumora.tools import wled_sim

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
        page = browser.new_page(viewport={"width": 1600, "height": 950}, locale="de-DE")  # the German interface
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


def until(fn, timeout: float = 15.0):
    """Poll fn until it returns something truthy (saves are debounced, CI runners are slow)."""
    end = time.time() + timeout
    while True:
        v = fn()
        if v or time.time() > end:
            return v
        time.sleep(0.25)


def test_full_workflow(env):
    page = env["page"]
    page.goto(env["base"])

    # the photosensitivity warning comes first and is confirmed once
    page.get_by_role("button", name="Verstanden").click()
    assert api(env, "/api/settings")["safety_ack"] is True

    # project
    page.fill(".welcome input", "E2E Raum")
    page.click("text=Projekt anlegen")
    page.wait_for_selector("text=Raumhöhe")
    slug = api(env, "/api/projects")["active"]
    assert slug == "e2e-raum"

    # room template (again if the freshly loaded project reset the inputs meanwhile)
    width = lambda: max(p[0] for p in api(env, f"/api/projects/{slug}")["room"]["floor"])  # noqa: E731
    inputs = page.locator(".card:has-text('Breite × Tiefe') input[type=number]")
    for _ in range(3):
        inputs.nth(0).fill("6")
        inputs.nth(1).fill("4.5")
        inputs.nth(1).press("Enter")
        page.click("text=Übernehmen")
        if until(lambda: width() == 6, timeout=6):
            break
    assert width() == 6
    shot(page, "01_room")

    # strips from presets
    page.click("nav >> text=LED-Strips")
    for label in ["Deckenumrandung", "Deckenring", "Wandleiste"]:
        page.click(f"button:has-text('{label}')")
        page.wait_for_timeout(600)
    project = until(lambda: len((p := api(env, f"/api/projects/{slug}"))["fixtures"]) == 3 and p)
    assert project and len(project["fixtures"]) == 3
    leds = api(env, f"/api/projects/{slug}/leds")["count"]
    assert leds > 1000
    shot(page, "02_fixtures")

    # controller (manual, the simulator answers like WLED)
    page.click("nav >> text=Controller")
    page.fill(".card:has-text('Manuell hinzufügen') input", env["sim"].replace("http://", ""))
    page.click(".card:has-text('Manuell hinzufügen') button:has-text('Hinzufügen')")
    page.wait_for_selector("text=Zuordnung")
    page.click("summary:has-text('Erweitert')")
    port = page.locator(".field:has-text('DDP-Port') input")
    port.fill(str(env["ddp"]))
    port.press("Enter")
    page.click("button:has-text('Alle freien Strips anhängen')")
    controller = lambda: (api(env, f"/api/projects/{slug}")["controllers"] or [{"port": None, "mappings": []}])[0]  # noqa: E731
    ctrl = until(lambda: (c := controller())["port"] == env["ddp"] and len(c["mappings"]) == 3 and c) or controller()
    assert ctrl["port"] == env["ddp"] and len(ctrl["mappings"]) == 3, ctrl
    page.wait_for_selector("text=verbunden", timeout=10000)
    shot(page, "03_controller")

    # song
    page.click("nav >> text=Songs")
    page.click("text=Demo-Song erzeugen")
    page.wait_for_selector(".list .badge.ok", timeout=120000)
    shot(page, "04_song")

    # show: starter template, play live
    page.click("nav >> text=Shows")
    page.click("button:has-text('+ Neue Show')")
    page.fill(".card input[type=text]", "E2E Show")
    page.get_by_role("button", name="Erstellen", exact=True).click()
    page.wait_for_selector(".tl-clip")
    show_id = api(env, "/api/playback")["show"]
    assert show_id
    page.click(".mode-switch button:has-text('Live')")
    # play from the chorus: the starter show keeps the drum-less intro dark, and unchanged frames
    # are only sent as keep-alives
    httpx.post(env["base"] + "/api/playback/seek", json={"t": 35.0}, timeout=10)
    page.wait_for_timeout(300)
    before = httpx.get(env["sim"] + "/sim/stats").json()["frames"]
    page.keyboard.press("Space")
    page.wait_for_timeout(2500)
    stats = httpx.get(env["sim"] + "/sim/stats").json()
    # 1200 LEDs on one simulated pin show ~24 FPS: the app sends just below that, evenly
    rate = until(lambda: (r := api(env, "/api/playback")["links"][ctrl["id"]]["rate"]) <= 24 and r)
    assert rate and 18 <= rate <= 24 and stats["frames"] - before > 35
    assert stats["fps"] <= rate + 1.5, stats
    if not os.environ.get("CI"):  # on a busy runner packets arrive bunched and the simulated pin drops some
        assert stats["shown_fps"] >= stats["fps"] - 1.5, stats
    assert api(env, "/api/playback")["power"]["total_ma"] > 0
    page.keyboard.press("Space")
    shot(page, "05_show_live")

    # editor: drop an effect into a layer, undo it
    n0 = sum(len(l["clips"]) for l in api(env, f"/api/projects/{slug}/shows/{show_id}")["layers"])
    row = page.locator(".tl-row:not(.tl-music)").nth(1)
    box = row.bounding_box()
    page.locator(".effect-chip:has-text('Sparkle')").drag_to(
        row, target_position={"x": box["width"] * 0.6, "y": box["height"] / 2}
    )
    clips = lambda: sum(len(l["clips"]) for l in api(env, f"/api/projects/{slug}/shows/{show_id}")["layers"])  # noqa: E731
    assert until(lambda: clips() == n0 + 1)
    shot(page, "06_editor")
    page.keyboard.press("Control+z")
    assert until(lambda: clips() == n0)
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


def test_english_interface(env):
    """With an English browser the interface is English (help, tabs, empty states)."""
    page = env["page"].context.browser.new_page(viewport={"width": 1400, "height": 900}, locale="en-US")
    try:
        page.goto(env["base"])
        page.wait_for_selector("nav")
        page.wait_for_timeout(1500)
        nav = page.locator("nav").inner_text()
        assert "LED strips" in nav and "Calibration" in nav and "Kalibrierung" not in nav
        page.get_by_role("button", name="? Help").click()
        page.get_by_text("Manual", exact=True).click()
        page.wait_for_selector("text=Your first show in six steps")
        shot(page, "10_english_manual")
    finally:
        page.close()
