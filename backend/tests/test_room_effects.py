"""Room- and viewer-aware rendering: drum hits, segment effects, sweeps, visibility, light report."""

import numpy as np
import pytest

from lumora.audio.features import AudioFeatures
from lumora.geometry.led_table import build_led_table
from lumora.model.fixture import Fixture, PolylineGeometry
from lumora.model.show import Clip, Layer, Range, Show, Target
from lumora.model.song import Section
from lumora.render.autoshow import starter_show
from lumora.render.engine import Renderer, select_leds
from lumora.render.validate import light_issues, light_report


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
    # different strips show different instruments in the most intense part
    peak = next(s for s in a.sections if s.peak)
    chorus = [c for c in clips if peak.start - 0.01 <= c.start < peak.end and c.target.fixtures and len(c.target.fixtures) == 1]
    assert len({(c.effect, c.params.get("trigger"), c.params.get("track")) for c in chorus}) >= 3
    rep = light_report(Renderer(project, t, show, AudioFeatures(a)))
    assert rep["room_light"] < 0.04
    # the quiet intro stays darker than the peak
    intro, chorus_rep = rep["sections"][0], rep["sections"][a.sections.index(peak)]
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


def _form_analysis():
    """A song with a song form: quiet intro, verse, chorus (drop, the peak) with a riff and chords."""
    from tests.test_instruments import _analysis_with

    a = _analysis_with(
        {
            "drop": [[24.0, 1.0, 0, 0]],
            "build": [[20.0, 0.9, 4.0, 0]],
            "kick": [[float(x), 1.0, 0, 0] for x in np.arange(8, 40, 0.5)],
            "snare": [[float(x), 0.8, 0, 0] for x in np.arange(9, 40, 1.0)],
            "hihat": [[float(x), 0.5, 0, 0] for x in np.arange(8, 40, 0.25)],
            "motif": [[8.0, 0.8, 2.0, 1], [16.0, 0.8, 2.0, 1], [28.0, 0.9, 2.0, 2], [32.0, 0.9, 2.0, 1]],
            "chord": [[float(x), 0.6, 2.0, 60 + (x // 2) % 12] for x in np.arange(0, 40, 2.0)],
        },
        duration=40.0,
    )
    a.sections = [
        Section(start=0, end=8, name="intro", label="A", energy=0.2, intensity=1),
        Section(start=8, end=20, name="verse", label="B", energy=0.5, intensity=3),
        Section(start=20, end=24, name="build", label="C", energy=0.6, intensity=3),
        Section(start=24, end=40, name="drop", label="D", energy=0.9, intensity=5, peak=True),
    ]
    a.phrases = [[float(t), 4] for t in range(0, 40, 8)]
    a.features["drums"] = [0.0] * 80 + [0.6] * 320
    a.harmony = {"key": "A Moll", "tonic": 9, "mode": "minor", "confidence": 0.8, "chords": []}
    return a


def test_starter_styles_colours_strobe_and_variants(project):
    from lumora.model.show import StarterStyle
    from lumora.render.autoshow import PALETTES

    a, t = _form_analysis(), build_led_table(project)

    def make(**style):
        return starter_show("S", "song", a, None, project, t, StarterStyle(**style))

    party = make(style="party")
    assert party.style.style == "party" and party.dynamics == 0.55
    clips = [c for _, c in party.clips()]
    hihat = [c for c in clips if c.params.get("trigger") == "hihat"]
    assert hihat and all(c.start >= 24 for c in hihat)  # glitter only on the peak
    # the same riff gets the same gesture every time it plays (outside the build-up and the drop moment)
    gestures = {
        (c.start, c.effect, str(c.params.get("axis")))
        for c in clips
        if c.params.get("trigger") == "once" and c.start in (8.0, 16.0, 32.0)
    }
    assert len({g[1:] for g in gestures}) == 1 and len(gestures) == 3
    assert not any(c.effect == "strobe" for c in clips)
    # minor key -> cool colours
    assert "Farben cool" in party.description
    assert {c.params.get("color") for c in clips} & {lk[1] for lk in PALETTES["cool"]}

    calm = make(style="calm", strobe=True)
    calm_clips = [c for _, c in calm.clips()]
    assert calm.dynamics > party.dynamics
    assert any(c.effect == "strobe" and c.start == 24.0 for c in calm_clips)  # strobe only at the peak drop
    assert sum(c.effect == "strobe" for c in calm_clips) == 1

    minimal = make(style="minimal")

    def cues(show):
        return [c for layer, c in show.clips() if layer.name == "Cues"]

    assert len(cues(minimal)) < len(cues(party))  # no riff gestures, crashes or fills

    # the peak is brighter than the verse
    def kick_level(show, t0):
        return max(c.params["brightness"] for _, c in show.clips() if c.params.get("trigger") == "kick" and c.start == t0)

    assert kick_level(party, 24) > kick_level(party, 8)
    # a variant changes the colours; explicit colours win over the key
    warm = make(colors="warm")
    assert {c.params.get("color") for _, c in warm.clips()} & {lk[1] for lk in PALETTES["warm"]}
    v0 = {c.params.get("color") for c in clips}
    v1 = {c.params.get("color") for _, c in make(variant=1).clips()}
    assert v0 != v1


def test_variant_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from lumora.app import create_app

    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "V"}).json()["slug"]
        song = c.post("/api/songs/demo", params={"bpm": 120}).json()
        for _ in range(300):
            if c.get(f"/api/songs/{song['id']}").json()["status"] == "done":
                break
            import time

            time.sleep(0.2)
        show = c.post(
            f"/api/projects/{slug}/shows",
            json={"name": "Party", "song_id": song["id"], "style": {"style": "cinematic", "colors": "neon"}},
        ).json()
        assert show["style"]["style"] == "cinematic" and show["style"]["variant"] == 0
        v = c.post(f"/api/projects/{slug}/shows/{show['id']}/variant").json()
        assert v["name"] == "Party (Variante 1)" and v["style"]["variant"] == 1 and v["style"]["colors"] == "neon"
        v2 = c.post(f"/api/projects/{slug}/shows/{v['id']}/variant").json()
        assert v2["name"] == "Party (Variante 2)"
