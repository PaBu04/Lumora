"""Room- and viewer-aware rendering: drum hits, segment effects, sweeps, visibility, light report."""

import numpy as np
import pytest

from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import build_led_table
from lsg.model.fixture import Fixture, PolylineGeometry
from lsg.model.show import Clip, Layer, Range, Show, Target
from lsg.render.autoshow import starter_show
from lsg.render.engine import Renderer, select_leds
from lsg.render.validate import light_issues, light_report


def test_drum_hits_match_the_demo_drums(demo_analysis):
    _, a = demo_analysis
    beat = 60 / 120
    # SHORT_STRUCTURE: 2 bars intro (hats), 4 bars verse (kick), 4 bars chorus (kick + snare on 2 and 4)
    kicks = np.arange(8, 40) * beat
    snares = np.array([(b * 4 + k) * beat for b in range(6, 10) for k in (1, 3)])
    det = {k: np.asarray(v) for k, v in a.drums.items()}

    def recall(found, truth):
        return np.mean([np.min(np.abs(found - t)) < 0.05 for t in truth]) if len(found) else 0.0

    def precision(found, truth):
        return np.mean([np.min(np.abs(truth - f)) < 0.05 for f in found]) if len(found) else 0.0

    assert recall(det["kick"], kicks) > 0.9 and precision(det["kick"], kicks) > 0.75
    assert recall(det["snare"], snares) > 0.85 and precision(det["snare"], snares) > 0.7
    assert len(det["hihat"]) >= 30  # off-beat hats run through the whole demo
    assert not any(t < 8 * beat - 0.05 for t in det["kick"])  # no kick in the intro


def test_old_analyses_get_hits_from_the_curves(demo_analysis):
    _, a = demo_analysis
    old = a.model_copy(update={"drums": {}})
    f = AudioFeatures(old)
    assert len(f.hits["kick"]) >= 20
    frame = f.frame(f.hits["kick"][10] + 0.05)
    assert frame.since_kick == pytest.approx(0.05, abs=0.03)


def test_metres_along_strip_and_visibility(project):
    t = build_led_table(project)
    north = t.fixture_slice("north")
    s = t.s[north]
    assert s[0] == 0 and s[-1] == pytest.approx(4.6, abs=0.05) and np.all(np.diff(s) > 0)
    # viewer at the south wall looking north: the north wall is in view
    assert t.view[north].min() > 0.9
    # a strip behind the viewer (south wall) is indirect
    project.fixtures.append(
        Fixture(id="back", name="Back", geometry=PolylineGeometry(points=[(0.5, 0.05, 2.0), (4.5, 0.05, 2.0)]))
    )
    t = build_led_table(project)
    back = t.fixture_slice("back")
    assert t.view[back].max() < 0.5
    direct = select_leds(Target(view="direct"), t, project)
    indirect = select_leds(Target(view="indirect"), t, project)
    assert set(range(back.start, back.stop)) <= set(indirect) and not set(direct) & set(indirect)
    near = select_leds(Target(fixtures=["north"], where=[Range(field="s", max=1.0)]), t, project)
    assert 25 <= len(near) <= 35  # first metre of a 30 LED/m strip


def test_hits_light_short_segments_on_the_kick(project, demo_analysis):
    _, a = demo_analysis
    f = AudioFeatures(a)
    t = build_led_table(project)
    clip = Clip(start=0, end=30, effect="hits", params={"trigger": "kick", "count": 2, "size": 6, "decay": 0.2, "soft": 0})
    r = Renderer(project, t, Show(layers=[Layer(clips=[clip])]), f)
    kick = float(f.hits["kick"][12])
    lit = r.render(kick + 0.01).max(axis=1) > 0.5
    assert 6 <= lit.sum() <= 12  # two segments of 6 LEDs (they may overlap)
    # segments are contiguous runs on single strips
    idx = np.flatnonzero(lit)
    assert len(set(t.fixture_index[idx])) <= 2
    assert r.render(kick + 1.5).max() < 0.01 or kick + 1.5 > float(f.hits["kick"][13])
    assert not r.errors


def test_sweep_travels_from_floor_to_ceiling(project):
    t = build_led_table(project)
    project.fixtures.append(
        Fixture(id="corner", name="Corner", geometry=PolylineGeometry(points=[(0.05, 3.95, 0.1), (0.05, 3.95, 2.4)]))
    )
    t = build_led_table(project)
    clip = Clip(start=0, end=20, effect="sweep", params={"axis": "z", "trigger": "loop", "beats": 4, "width": 0.1, "tail": 0})
    r = Renderer(project, t, Show(layers=[Layer(clips=[clip])]), AudioFeatures(None, 20))
    sl = t.fixture_slice("corner")
    z = t.pos[sl, 2]
    early, late = r.render(0.5)[sl].max(axis=1), r.render(1.5)[sl].max(axis=1)
    assert z[np.argmax(early)] < z[np.argmax(late)]  # moves up (120 BPM: 4 beats = 2 s)


def test_light_report_flags_a_bright_flat_show(project):
    t = build_led_table(project)
    f = AudioFeatures(None, 40)
    bright = Show(layers=[Layer(clips=[Clip(start=0, end=40, effect="solid", params={"color": "#ffffff", "brightness": 0.8})])])
    rep = light_report(Renderer(project, t, bright, f))
    msgs = " ".join(i["message"] for i in light_issues(rep, bright))
    assert rep["room_light"] > 0.3 and "bright" in msgs and "nothing visibly changes" in msgs
    dark = Show(
        layers=[
            Layer(clips=[Clip(start=0, end=40, effect="noise", params={"brightness": 0.08}, target=Target(fixtures=["north"]))]),
            Layer(
                clips=[
                    Clip(start=0, end=40, effect="hits", params={"trigger": "beat", "size": 4}, target=Target(fixtures=["west"]))
                ]
            ),
        ]
    )
    rep = light_report(Renderer(project, t, dark, f))
    assert rep["room_light"] < 0.03 and not light_issues(rep, dark)


def test_starter_show_follows_the_instruments(project, demo_analysis):
    _, a = demo_analysis
    project.fixtures.append(
        Fixture(id="back", name="Back", geometry=PolylineGeometry(points=[(0.5, 0.05, 2.0), (4.5, 0.05, 2.0)]))
    )
    t = build_led_table(project)
    show = starter_show("S", "x", a, None, project, t)
    assert show.dynamics > 0
    clips = [c for _, c in show.clips()]
    effects = {c.effect for c in clips}
    assert {"hits", "notes"} <= effects
    triggers = {c.params.get("trigger") or c.params.get("track") for c in clips}
    assert {"kick", "snare", "bass"} <= triggers
    # the strip behind the viewer only gets room colour / flashes
    back = [c for c in clips if c.target.fixtures == ["back"]]
    assert back and {c.effect for c in back} <= {"noise", "pulse"}
    # different strips show different instruments in the chorus
    chorus = [c for c in clips if c.start >= a.sections[-1].start - 0.01 and c.target.fixtures and len(c.target.fixtures) == 1]
    assert len({(c.effect, c.params.get("trigger"), c.params.get("track")) for c in chorus}) >= 3
    rep = light_report(Renderer(project, t, show, AudioFeatures(a)))
    assert rep["room_light"] < 0.04
    # the quiet intro stays darker than the chorus
    intro, chorus_rep = rep["sections"][0], rep["sections"][-1]
    assert intro["room_light"] < chorus_rep["room_light"]


def test_starter_show_cues_on_drops_and_builds(project):
    from tests.test_instruments import _analysis_with

    a = _analysis_with(
        {
            "drop": [[12.0, 1.0, 0, 0]],
            "build": [[8.0, 0.9, 4.0, 0]],
            "kick": [[float(x), 1.0, 0, 0] for x in np.arange(12, 20, 0.5)],
            "fill": [[6.0, 0.5, 1.0, 0]],
        }
    )
    t = build_led_table(project)
    show = starter_show("S", "x", a, None, project, t)
    cues = next(l for l in show.layers if l.name == "Cues").clips
    rise = [c for c in cues if c.effect == "rise"]
    assert rise and rise[0].start == 8.0 and rise[0].end == 12.0
    assert any(c.effect == "pulse" and c.params["trigger"] == "once" and c.start == 12.0 for c in cues)
    assert any(c.effect == "sweep" and c.start == 6.0 for c in cues)
