import asyncio

import numpy as np
import pytest
import soundfile as sf

from lumora.output.wled import controller_status
from lumora.playback.sync import click_track, sync_features, sync_show


def test_click_track_has_clicks_on_the_beat(tmp_path):
    path = click_track(tmp_path / "click.wav", bpm=120, seconds=4)
    y, sr = sf.read(path)
    env = np.abs(y[:, 0])
    starts = [i / sr for i in range(1, len(env)) if env[i] > 0.1 and env[i - 1] <= 0.1 and (i / sr) % 0.5 < 0.01]
    assert starts[:4] == pytest.approx([0.0, 0.5, 1.0, 1.5], abs=0.005) or len(starts) >= 7
    assert click_track(tmp_path / "click.wav") == path  # cached


def test_sync_show_flashes_exactly_on_the_beat(project):
    from lumora.geometry.led_table import build_led_table
    from lumora.render.engine import Renderer

    feats = sync_features(100, 20)
    r = Renderer(project, build_led_table(project), sync_show(20), feats, {})
    period = 0.6
    on = r.render(3 * period + 0.002).max()
    off = r.render(3 * period + 0.3).max()
    assert on > 0.7 and off < 0.05


def test_controller_status_warnings(monkeypatch):
    async def fake_info(host, timeout=2.0):
        return {"led_count": 500, "arch": "esp8266", "rssi": -80, "fps": 20}

    monkeypatch.setattr("lumora.output.wled.fetch_info", fake_info)
    cfg = {"buses": [{"type": 22, "len": 900, "pins": [2], "ms": 27.3}], "max_fps": 31.0, "wifi_sleep": True}
    st = asyncio.run(controller_status("x", pixels=900, sent_fps=30, live=True, cfg=cfg))
    text = " ".join(st["warnings"])
    assert st["ok"] and "500 LEDs" in text and "-80 dBm" in text and "20 von 30" in text and "Energiesparen" in text
    assert "900 LEDs an einem Datenpin" in st["hints"][0] and "aufteilen" in st["hints"][0]

    # paused live mode only sends keep-alives: a low WLED frame rate is no problem then
    st = asyncio.run(controller_status("x", pixels=400, sent_fps=2, live=True))
    assert not any("FPS" in w for w in st["warnings"])

    async def down(host, timeout=2.0):
        raise OSError("timeout")

    monkeypatch.setattr("lumora.output.wled.fetch_info", down)
    st = asyncio.run(controller_status("x", pixels=10, sent_fps=0, live=False))
    assert not st["ok"] and "nicht erreichbar" in st["error"]
