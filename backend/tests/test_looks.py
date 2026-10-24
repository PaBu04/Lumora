import numpy as np
import pytest
from fastapi.testclient import TestClient

from lumora.app import create_app
from lumora.audio.features import AudioFeatures
from lumora.model.show import Clip, Layer, Show
from lumora.model.song import Analysis, Section
from lumora.render.looks import BUILTIN_LOOKS, apply_look, look_from_clips


def grid_features(bpm: float, seconds: float = 120) -> AudioFeatures:
    beats = np.arange(0, seconds, 60 / bpm)
    return AudioFeatures(
        Analysis(
            duration=seconds,
            bpm=bpm,
            beats=beats.tolist(),
            downbeats=beats[::4].tolist(),
            onsets=[],
            sections=[Section(start=0, end=seconds, name="verse", label="A", energy=0.5)],
            frame_rate=10,
            features={k: [0.0] * 10 for k in ("rms", "low", "mid", "high", "onset")},
            waveform=[0.0],
        )
    )


def test_time_at_beat_inverts_beat_position():
    f = grid_features(120)
    for t in (0.0, 1.25, 33.3):
        assert f.time_at_beat(f.beat_position(t)) == pytest.approx(t)


def test_look_keeps_its_musical_length_across_tempos():
    show = Show(
        layers=[
            Layer(name="A", clips=[Clip(id="a", start=10, end=12, effect="solid")]),
            Layer(name="B"),
            Layer(
                name="C",
                clips=[
                    Clip(id="c", start=11, end=14, effect="solid", params={"brightness": {"keys": [[0, 0.1], [3, 1.0]]}}),
                ],
            ),
        ]
    )
    look = look_from_clips("Mix", show, {"a", "c"}, grid_features(120).beat_position)
    assert look.beats == 8 and [c.layer for c in look.clips] == [0, 2]
    assert look.clips[1].clip["start"] == 2 and look.clips[1].clip["params"]["brightness"]["keys"][1][0] == 6

    slow = grid_features(60)
    b0 = slow.beat_position(20)
    placed, ids = apply_look(Show(layers=[Layer(name="X")]), look, 20, 0, lambda b: slow.time_at_beat(b0 + b))
    assert len(ids) == 2 and len(placed.layers) == 3  # missing layers are created
    a = placed.layers[0].clips[0]
    c = placed.layers[2].clips[0]
    assert (a.start, a.end) == (20, 24)  # 4 beats at 60 BPM
    assert (c.start, c.end) == (22, 28)
    assert c.params["brightness"]["keys"][1][0] == pytest.approx(6.0)  # keyframe time doubled as well


def test_builtin_looks_render(project):
    from lumora.geometry.led_table import build_led_table
    from lumora.render.engine import Renderer

    f = grid_features(128)
    for look in BUILTIN_LOOKS:
        show, _ = apply_look(Show(), look, 4.0, 0, lambda b: f.time_at_beat(f.beat_position(4.0) + b))
        r = Renderer(project, build_led_table(project), show, f, {})
        assert not r.errors, (look.name, r.errors)
        r.render(5.0)
        assert not r.errors


def test_looks_api(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "L"}).json()["slug"]
        show = c.post(f"/api/projects/{slug}/shows", json={"name": "S", "template": "empty"}).json()
        show["duration"] = 60
        show["layers"] = [{"name": "A", "clips": [{"id": "x1", "start": 1, "end": 3, "effect": "pulse"}]}]
        c.put(f"/api/projects/{slug}/shows/{show['id']}", json=show)
        looks = c.get(f"/api/projects/{slug}/looks").json()
        assert {x["id"] for x in looks} >= {"builtin-drop", "builtin-riser"}
        look = c.post(f"/api/projects/{slug}/looks", json={"name": "Mein Puls", "show_id": show["id"], "clip_ids": ["x1"]}).json()
        assert look["beats"] == pytest.approx(4)  # 2 s at the 120 BPM fallback grid
        clips = c.post(f"/api/projects/{slug}/looks/{look['id']}/instantiate", json={"show_id": show["id"], "at": 10}).json()
        assert clips[0]["layer"] == 0 and clips[0]["clip"]["start"] == 10 and clips[0]["clip"]["end"] == 12
        riser = c.post(f"/api/projects/{slug}/looks/builtin-riser/instantiate", json={"show_id": show["id"], "at": 0}).json()
        assert [x["layer"] for x in riser] == [0, 1]
        assert c.delete(f"/api/projects/{slug}/looks/builtin-drop").status_code == 404  # built-ins are read only
        assert c.delete(f"/api/projects/{slug}/looks/{look['id']}").json() == {"ok": True}
        assert all(x["builtin"] for x in c.get(f"/api/projects/{slug}/looks").json())
