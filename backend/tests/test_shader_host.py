import time

import numpy as np
import pytest

from lumora.audio.features import AudioFeatures
from lumora.geometry.led_table import build_led_table
from lumora.model.show import Clip, Layer, Show
from lumora.render import shader_host
from lumora.render.engine import Renderer
from lumora.render.shaders import Shader

GOOD = """
def render(t, leds, audio, params):
    return hsv(leds.coord('azimuth') + t * params.get('speed', 0.1), 1.0, 0.5 + 0.5 * audio.beat_phase), leds.u
"""
SLOW = """
def render(t, leds, audio, params):
    x = 0.0
    for i in range(100000):
        x += float(np.sort(np.random.rand(2000))[0])
    return color('red')
"""


@pytest.fixture(autouse=True)
def fresh_host():
    shader_host.shutdown()
    yield
    shader_host.shutdown()


def renderer(project, name, source, isolated):
    shader = Shader(name, source)
    runner = shader_host.IsolatedShader(shader) if isolated else shader
    show = Show(layers=[Layer(clips=[Clip(id="c", start=0, end=10, effect=f"shader:{name}", params={"speed": 0.3})])])
    return Renderer(project, build_led_table(project), show, AudioFeatures(None, 10), {name: runner})


def test_isolated_output_matches_inline(project):
    inline = renderer(project, "hue", GOOD, False)
    isolated = renderer(project, "hue", GOOD, True)
    for t in (0.0, 1.7, 4.2):
        np.testing.assert_allclose(isolated.render(t), inline.render(t), atol=1e-6)
    assert not isolated.errors
    # per frame cost stays small once the worker is running
    start = time.perf_counter()
    for i in range(20):
        isolated.render(i * 0.05)
    assert (time.perf_counter() - start) / 20 < 0.02


def test_hanging_shader_is_stopped_and_worker_recovers(project):
    slow = renderer(project, "slow", SLOW, True)
    start = time.perf_counter()
    slow.render(1.0)
    assert "longer than" in slow.errors["c"]
    assert time.perf_counter() - start < 10
    good = renderer(project, "hue", GOOD, True)  # a fresh worker serves the next shader
    assert good.render(1.0).max() > 0 and not good.errors


def test_errors_inside_the_worker_are_reported(project):
    broken = renderer(project, "broken", "def render(t, leds, audio, params):\n    return np.zeros((leds.n, 2))", True)
    broken.render(1.0)
    assert "shape" in broken.errors["c"]
