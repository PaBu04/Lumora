import time

import numpy as np
import pytest

from lumora.audio.features import AudioFeatures
from lumora.geometry.led_table import build_led_table
from lumora.model.show import Clip, Layer, Range, Show, Target
from lumora.render.colors import palette_at, parse_color, parse_palette
from lumora.render.effects import EFFECTS
from lumora.render.engine import Renderer, select_leds
from lumora.render.shaders import Shader, ShaderError
from lumora.render.snapshot import render_timeline_image, render_top_image, render_viewer_image
from lumora.render.validate import validate_show


def make_renderer(project, clips, features=None, shaders=None, **show_kw):
    show = Show(name="t", layers=[Layer(clips=clips)], **show_kw)
    return Renderer(project, build_led_table(project), show, features or AudioFeatures(None, 30), shaders or {})


def test_colors():
    np.testing.assert_allclose(parse_color("#ff8000"), [1, 128 / 255, 0])
    np.testing.assert_allclose(parse_color("#f00"), [1, 0, 0])
    np.testing.assert_allclose(parse_color("blue"), [0, 0, 1])
    np.testing.assert_allclose(parse_color([255, 0, 255]), [1, 0, 1])
    np.testing.assert_allclose(parse_color("hsv(120,1,1)"), [0, 1, 0], atol=1e-6)
    with pytest.raises(ValueError):
        parse_color("nope")
    assert parse_palette("fire").shape == (5, 3)
    pal = parse_palette(["#000000", "#ffffff"])
    np.testing.assert_allclose(palette_at(pal, np.array([0.0, 0.5, 1.0]), cyclic=False)[:, 0], [0, 0.5, 1])


def test_target_selection(project):
    table = build_led_table(project)
    north = table.fixture_slice("north")
    assert np.array_equal(select_leds(Target(fixtures=["north"]), table, project), np.arange(north.start, north.stop))
    ceiling = select_leds(Target(tags=["ceiling"]), table, project)
    assert len(ceiling) == (north.stop - north.start) + 40
    high = select_leds(Target(where=[Range(field="z", min=2.45)]), table, project)
    assert len(high) == 40  # only the ring hangs at 2.5 m
    left = select_leds(Target(where=[Range(field="azimuth", max=-30)]), table, project)
    assert set(table.fixture_index[left]) >= {table.fixture_ids.index("west")}
    assert len(select_leds(Target(fixtures=["north"], invert=True), table, project)) == table.count - len(
        range(north.start, north.stop)
    )


def test_every_effect_renders_with_defaults(project, demo_analysis):
    _, a = demo_analysis
    feats = AudioFeatures(a)
    clips = [Clip(start=0, end=20, effect=eid) for eid in EFFECTS]
    for clip in clips:
        r = make_renderer(project, [clip], features=feats)
        assert not r.errors, r.errors
        for t in (0.0, 3.3, 7.77, 12.0):
            frame = r.render(t)
            assert frame.shape == (r.table.count, 3)
            assert np.isfinite(frame).all() and frame.min() >= 0 and frame.max() <= 1
        assert not r.errors, (clip.effect, r.errors)


def test_solid_blend_and_layers(project):
    base = Clip(start=0, end=10, effect="solid", params={"color": "#ff0000"})
    top = Clip(start=0, end=10, effect="solid", params={"color": "#0000ff"}, opacity=0.5, target=Target(fixtures=["north"]))
    r = make_renderer(project, [base, top])
    f = r.render(1.0)
    n = r.table.fixture_slice("north")
    np.testing.assert_allclose(f[n.start], [0.5, 0, 0.5], atol=1e-6)
    np.testing.assert_allclose(f[-1], [1, 0, 0])
    assert r.render(10.0).max() == 0  # clip end is exclusive


def test_fades(project):
    clip = Clip(start=0, end=4, effect="solid", fade_in=1, fade_out=2)
    r = make_renderer(project, [clip])
    assert r.render(0.5)[0, 0] == pytest.approx(0.5)
    assert r.render(2.0)[0, 0] == pytest.approx(1.0)
    assert r.render(3.0)[0, 0] == pytest.approx(0.5)


def test_dynamic_params(project, demo_analysis):
    _, a = demo_analysis
    feats = AudioFeatures(a)
    keyed = Clip(start=2, end=6, effect="solid", params={"color": {"keys": [[0, "#000000"], [4, "#ffffff"]]}})
    r = make_renderer(project, [keyed], features=feats)
    assert r.render(4.0)[0, 0] == pytest.approx(0.5, abs=1e-3)
    bound = Clip(start=0, end=20, effect="solid", params={"brightness": {"audio": "low", "min": 0, "max": 1}})
    r = make_renderer(project, [bound], features=feats)
    levels = [r.render(t)[0, 0] for t in np.linspace(5, 15, 50)]
    assert max(levels) > 0.5 and min(levels) < max(levels)
    lfo = Clip(start=0, end=20, effect="solid", params={"brightness": {"lfo": "saw", "beats": 4}})
    r = make_renderer(project, [lfo], features=feats)
    assert not r.errors


def test_param_errors_are_reported(project):
    bad = [
        Clip(start=0, end=1, effect="nope"),
        Clip(start=0, end=1, effect="solid", params={"colour": "red"}),
        Clip(start=0, end=1, effect="solid", params={"color": "not-a-colour"}),
        Clip(start=0, end=1, effect="wave", params={"axis": "sideways"}),
        Clip(start=0, end=1, effect="solid", target=Target(fixtures=["ghost"])),
        Clip(start=0, end=1, effect="shader:missing"),
        Clip(start=0, end=1, effect="pulse", params={"trigger": {"audio": "low"}}),
    ]
    r = make_renderer(project, bad)
    assert len(r.errors) == len(bad)
    assert r.render(0.5).max() == 0


def test_beat_locked_pulse(project, demo_analysis):
    _, a = demo_analysis
    feats = AudioFeatures(a)
    r = make_renderer(project, [Clip(start=0, end=30, effect="pulse", params={"decay": 0.1})], features=feats)
    beat = a.beats[8]
    assert r.render(beat + 0.005)[0, 0] > 0.9
    assert r.render(beat + 0.3)[0, 0] < 0.1


SHADER = """
def render(t, leds, audio, params):
    x = leds.coord('azimuth')
    rgb = hsv(x + t * params.get('speed', 0.1), 1.0, 1.0)
    return rgb, np.full(leds.n, 0.5 + 0.5 * audio.beat_phase)
"""


def test_shader_runs(project):
    shader = Shader("hue_sweep", SHADER)
    r = make_renderer(
        project, [Clip(start=0, end=5, effect="shader:hue_sweep", params={"speed": 0.3})], shaders={"hue_sweep": shader}
    )
    f = r.render(1.0)
    assert not r.errors and f.max() > 0


@pytest.mark.parametrize(
    "src",
    [
        "import os\ndef render(t, leds, audio, params): return 0",
        "def render(t, leds, audio, params):\n    while True: pass",
        "def render(t, leds, audio, params): return open('x')",
        "def render(t, leds, audio, params): return leds.__class__",
        "def render(t, leds, audio, params): return np.load('x')",
        "x = 1",
        "def render(:",
    ],
)
def test_shader_sandbox_rejects(src):
    with pytest.raises(ShaderError):
        Shader("bad", src)


def test_shader_runtime_errors_are_contained(project):
    shader = Shader("broken", "def render(t, leds, audio, params):\n    return np.zeros((leds.n, 2))")
    r = make_renderer(project, [Clip(id="c1", start=0, end=5, effect="shader:broken")], shaders={"broken": shader})
    r.render(1.0)
    assert "shape" in r.errors["c1"]
    loop = Shader("loop", "def render(t, leds, audio, params):\n    for i in range(10**9): pass")
    r = make_renderer(project, [Clip(id="c2", start=0, end=5, effect="shader:loop")], shaders={"loop": loop})
    r.render(1.0)
    assert "range" in r.errors["c2"]


def test_validate_show(project):
    table = build_led_table(project)
    show = Show(
        layers=[
            Layer(
                name="L",
                clips=[
                    Clip(id="ok", start=0, end=5, effect="solid"),
                    Clip(id="bad", start=0, end=5, effect="wave", params={"speed": "fast"}),
                    Clip(id="empty", start=0, end=5, effect="solid", target=Target(where=[Range(field="z", min=10)])),
                    Clip(id="late", start=40, end=50, effect="solid"),
                ],
            )
        ]
    )
    issues = validate_show(show, project, table, AudioFeatures(None, 30), {})
    by = {i["clip"]: i for i in issues}
    assert by["bad"]["severity"] == "error" and "speed" in by["bad"]["message"]
    assert by["empty"]["severity"] == "warning"
    assert by["late"]["severity"] == "warning"
    assert "ok" not in by


def test_render_performance(project):
    """~5000 LEDs, 10 layered clips: well below the 20 ms frame budget."""
    from lumora.model.fixture import Fixture, PolylineGeometry

    big = project.model_copy(deep=True)
    for k in range(6):
        big.fixtures.append(
            Fixture(
                id=f"f{k}",
                geometry=PolylineGeometry(points=[(0.1, 0.1 + k * 0.5, 0.3), (4.9, 0.1 + k * 0.5, 2.3)]),
                leds_per_meter=144,
            )
        )
    effects = ["noise", "wave", "sparkle", "chase", "ripple", "rainbow", "pulse", "spotlight", "gradient", "split"]
    r = make_renderer(big, [Clip(start=0, end=60, effect=e, blend="add") for e in effects])
    assert r.table.count > 4500
    r.render(0.1)
    t0 = time.perf_counter()
    for i in range(50):
        r.render(1 + i / 50)
    per_frame = (time.perf_counter() - t0) / 50
    assert per_frame < 0.02, f"{per_frame * 1000:.1f} ms per frame"


def test_snapshots(project, demo_analysis):
    _, a = demo_analysis
    r = make_renderer(project, [Clip(start=0, end=20, effect="rainbow", params={"axis": "azimuth"})], features=AudioFeatures(a))
    frame = r.render(2.0)
    for png in (
        render_viewer_image(project, r.table, frame),
        render_top_image(project, r.table, frame),
        render_timeline_image(r, 0, 10, width=200),
    ):
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
