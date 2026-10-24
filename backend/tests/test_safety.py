"""Photosensitivity: large flashes at most LIMIT_HZ times per second, strobes never faster."""

import itertools

import numpy as np
import pytest

from lumora.render import safety
from lumora.render.safety import FlashLimiter


@pytest.fixture(autouse=True)
def _limit():
    old = safety.LIMIT_HZ
    safety.LIMIT_HZ = 3.0
    yield
    safety.LIMIT_HZ = old


def _run(limiter, flashes_hz: float, lit: int, n: int = 300, seconds: float = 2.0, fps: int = 50) -> list[float]:
    """Frames with `lit` of n LEDs flashing at flashes_hz; returns the mean level of every output frame."""
    out = []
    for k in range(int(seconds * fps)):
        t = k / fps
        on = (t * flashes_hz) % 1.0 < 0.3
        frame = np.zeros((n, 3), np.float32)
        frame[:lit] = 0.9 if on else 0.02
        out.append(float(limiter.apply(t, frame).max(axis=1).mean()))
    return out


def _flashes(levels: list[float]) -> int:
    return sum(1 for a, b in itertools.pairwise(levels) if b - a >= safety.RISE)


def test_fast_room_flashes_are_limited():
    levels = _run(FlashLimiter(), flashes_hz=8, lit=300)
    assert _flashes(levels) <= 2 * 3 + 1  # 2 seconds at 3 per second
    limiter = FlashLimiter()
    slow = _run(limiter, flashes_hz=2, lit=300)
    assert _flashes(slow) == 3 and limiter.softened == 0  # slow enough: every flash stays (the first one starts lit)


def test_local_hits_are_untouched():
    limiter = FlashLimiter()
    levels = _run(limiter, flashes_hz=8, lit=12)  # 12 of 300 LEDs
    assert limiter.softened == 0 and max(levels) > 0.03


def test_off_and_strobe_rate():
    safety.LIMIT_HZ = 0
    assert _flashes(_run(FlashLimiter(), flashes_hz=8, lit=300)) >= 15
    safety.LIMIT_HZ = 3.0
    assert safety.max_flash_rate() == 3.0


def test_strobe_effect_respects_the_limit(project):
    from lumora.audio.features import AudioFeatures
    from lumora.geometry.led_table import build_led_table
    from lumora.model.show import Clip, Layer, Show
    from lumora.render.engine import Renderer

    show = Show(layers=[Layer(clips=[Clip(start=0, end=4, effect="strobe", params={"rate": 15, "duty": 0.5})])])
    r = Renderer(project, build_led_table(project), show, AudioFeatures(None, 4.0))
    r.limiter.apply = lambda t, f: f  # type: ignore[method-assign]  # only the effect's own cap counts
    levels = []
    for k in range(200):
        levels.append(float(r.render(k / 50).mean()))
    ons = sum(1 for a, b in itertools.pairwise(levels) if b > 0.1 >= a)
    assert ons <= 13  # 4 s at 3 Hz (15 Hz asked)


def test_settings_api(tmp_path):
    from fastapi.testclient import TestClient

    from lumora.app import create_app

    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        s = c.get("/api/settings").json()
        assert s["flash_limit"] == 3.0 and s["safety_ack"] is False
        s = c.put("/api/settings", json={"flash_limit": 0, "safety_ack": True}).json()
        assert s["flash_limit"] == 0 and s["safety_ack"] and safety.LIMIT_HZ == 0
        assert c.put("/api/settings", json={"flash_limit": 50}).status_code == 422
    # remembered across a restart
    with TestClient(create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")) as c:
        assert c.get("/api/settings").json()["safety_ack"] is True
