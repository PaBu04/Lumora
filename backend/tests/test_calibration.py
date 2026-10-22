import numpy as np
import pytest

from lsg.geometry.led_table import build_led_table
from lsg.model.calibration import LedCalibration
from lsg.model.controller import Controller, FixtureMapping
from lsg.output.curve import duty_to_lightness, extract_white, lightness_to_duty, pwm_of_level, to_pwm
from lsg.output.pipeline import OutputPipeline
from lsg.playback.patterns import DARK_STEPS, RAW_STEPS, pattern_frame


def test_cie_curve_is_perceptual_and_invertible():
    cal = LedCalibration()
    v = np.linspace(0, 1, 101)
    d = lightness_to_duty(v, cal)
    assert d[0] == 0 and d[-1] == pytest.approx(1)
    assert d[50] == pytest.approx(0.184, abs=0.002)  # mid grey needs only ~18 % light
    assert np.all(np.diff(d) > 0)
    np.testing.assert_allclose(duty_to_lightness(d, cal), v, atol=1e-6)
    g = LedCalibration(curve="gamma", gamma=2.0)
    assert lightness_to_duty(np.array([0.5]), g)[0] == pytest.approx(0.25)


def test_dim_values_stay_visible():
    """Without the min level, perceived 1-5 % would round to PWM 0 or 1."""
    cal = LedCalibration(min_level=3, cutoff=0.01)
    assert pwm_of_level(0.0, cal) == 0
    assert pwm_of_level(0.005, cal) == 0  # below cutoff -> off
    assert pwm_of_level(0.0101, cal) == pytest.approx(3, abs=0.01)  # just lit -> min level
    # coarse dark steps stay distinguishable; finer ones (1 % -> 2 %) are less than one PWM
    # step apart and need dithering - 8 bit PWM cannot resolve them otherwise
    levels = [pwm_of_level(x, cal) for x in (0.02, 0.05, 0.1, 0.2)]
    assert all(b - a >= 0.5 for a, b in zip(levels, levels[1:]))
    assert pwm_of_level(0.03, cal) - pwm_of_level(0.02, cal) < 1.0
    assert pwm_of_level(1.0, cal) == pytest.approx(255)
    assert pwm_of_level(1.0, LedCalibration(max_level=128)) == pytest.approx(128)


def test_white_balance_and_rgbw():
    cal = LedCalibration(curve="gamma", gamma=1.0, min_level=1, cutoff=0, white_balance=(1.0, 0.9, 0.7))
    pwm = to_pwm(np.array([[1.0, 1.0, 1.0]]), cal)[0]
    np.testing.assert_allclose(pwm, [255, 1 + 254 * 0.9, 1 + 254 * 0.7], rtol=1e-5)
    rgb = np.array([[200.0, 180.0, 150.0], [255.0, 0.0, 0.0]])
    _, w = extract_white(rgb, LedCalibration(white_mode="min"))
    np.testing.assert_allclose(w, [150, 0])
    _, w = extract_white(rgb, LedCalibration(white_mode="color", white_color="#ffffff"))
    np.testing.assert_allclose(w, [150, 0], atol=1e-3)
    out, w = extract_white(rgb, LedCalibration(white_mode="color", white_color="#ffd8b0"))
    assert w[0] > 150  # a warm white LED can carry more of a warm colour
    assert np.all(out >= 0)
    _, w = extract_white(rgb, LedCalibration(white_mode="off"))
    assert w.sum() == 0


def make_pipeline(project, budget=None, total=None, **cal):
    project.controllers = [Controller(id="c", host="x", budget_ma=budget, mappings=[FixtureMapping(fixture_id="north")])]
    project.power.total_budget_ma = total
    for t in project.calibration:
        project.calibration[t] = LedCalibration(**cal)
    table = build_led_table(project)
    return OutputPipeline(project, table), table


def test_power_estimate_and_limit(project):
    pipe, table = make_pipeline(project, ma_per_channel=20, ma_idle=1)
    sl = table.fixture_slice("north")
    n = sl.stop - sl.start
    white = np.ones((table.count, 3), np.float32)
    _, stats = pipe.encode_all(lambda c: white)
    assert stats.total_ma == pytest.approx(n * (1 + 60), rel=1e-3)  # 60 mA per white LED + idle

    pipe, table = make_pipeline(project, budget=2000, ma_per_channel=20, ma_idle=1)
    outs, stats = pipe.encode_all(lambda c: white)
    assert stats.total_requested_ma > 2000
    assert stats.total_ma == pytest.approx(2000, rel=0.01)
    assert outs[0].scale < 0.5
    assert max(outs[0].data) < 255
    dark = np.full((table.count, 3), 0.1, np.float32)
    outs, _ = pipe.encode_all(lambda c: dark)
    assert outs[0].scale == 1.0  # a dim scene stays untouched

    pipe, table = make_pipeline(project, total=1500, ma_per_channel=20, ma_idle=1)
    _, stats = pipe.encode_all(lambda c: white)
    assert stats.total_ma == pytest.approx(1500, rel=0.01)


def test_master_brightness_is_perceptual(project):
    pipe, table = make_pipeline(project)
    white = np.ones((table.count, 3), np.float32)
    full = pipe.encode_all(lambda c: white)[0][0].data
    half = pipe.encode_all(lambda c: white, brightness=0.5)[0][0].data
    assert full[0] == 255
    assert half[0] == pytest.approx(round(pwm_of_level(0.5, LedCalibration())), abs=1)  # ~48, not 128


@pytest.mark.parametrize("mode", ["spatial", "temporal"])
def test_dithering_reproduces_fractional_levels(project, mode):
    pipe, table = make_pipeline(project, curve="gamma", gamma=1.0, min_level=1, cutoff=0.0, dithering=mode)
    d = 1.5 / 254  # pwm = 1 + 254 * d = 2.5
    frame = np.full((table.count, 3), d, np.float32)
    values = np.array([np.frombuffer(pipe.encode_all(lambda c: frame)[0][0].data, np.uint8).astype(float) for _ in range(40)])
    assert values.min() >= 1  # never dithered to black
    assert values.mean() == pytest.approx(2.5, abs=0.15)
    if mode == "temporal":
        assert np.all(values.mean(axis=0) > 2.2)  # every LED averages the level over time


def test_raw_frames_bypass_the_curve(project):
    pipe, table = make_pipeline(project)
    frame, raw = pattern_frame("steps", table, ["north"], {}, 0.0)
    assert raw
    data = np.frombuffer(pipe.encode_all(lambda c: frame, raw=True)[0][0].data, np.uint8)
    assert sorted(set(data.tolist()) - {0}) == RAW_STEPS


def test_patterns(project):
    table = build_led_table(project)
    sl = table.fixture_slice("north")
    frame, raw = pattern_frame("dark", table, ["north"], {"color": "#ff0000"}, 0.0)
    assert not raw and frame[sl, 1].max() == 0 and frame[sl, 0].max() == pytest.approx(0.2)
    assert sorted(set(np.round(frame[sl, 0], 4).tolist()) - {0.0}) == pytest.approx(DARK_STEPS)
    frame, _ = pattern_frame("identify", table, ["west"], {}, 0.0)
    w = table.fixture_slice("west")
    assert frame[w.start].tolist() == [0, 1, 0] and frame[w.stop - 1].tolist() == [1, 0, 0]
    assert frame[sl].max() == 0


def test_power_analysis_and_validation(project):
    from lsg.audio.features import AudioFeatures
    from lsg.model.show import Clip, Layer, Show
    from lsg.output.power import analyse_power
    from lsg.render.engine import Renderer
    from lsg.render.validate import validate_show

    project.controllers = [Controller(id="c", host="x", budget_ma=1500, mappings=[FixtureMapping(fixture_id="north")])]
    table = build_led_table(project)
    show = Show(duration=10, layers=[Layer(clips=[
        Clip(start=0, end=5, effect="solid", params={"color": "#ffffff", "brightness": 0.1}),
        Clip(start=5, end=10, effect="solid", params={"color": "#ffffff"}),
        Clip(id="dim", start=0, end=2, effect="solid", params={"brightness": 0.01}),
    ])])
    r = Renderer(project, table, show, AudioFeatures(None, 10), {})
    report = analyse_power(r, OutputPipeline(project, table), fps=2)
    c = report["controllers"]["c"]
    assert c["peak_t"] >= 5 and c["peak_ma"] > 1500 and c["limited_seconds"] == pytest.approx(5, abs=0.6)
    assert report["curves"]["c"][0] < 500  # the dim half draws little current
    issues = validate_show(show, project, table, AudioFeatures(None, 10), {})
    msgs = [i["message"] for i in issues]
    assert any(m.startswith("power:") and "'WLED'" in m for m in msgs)
    assert any(i["clip"] == "dim" and "bottom of the LED range" in i["message"] for i in issues)
