import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from lsg.app import create_app
from lsg.audio.demo import make_demo_track
from lsg.audio.live import LiveAudioFeatures
from lsg.playback.sync import click_track


def feed_file(path, until: float | None = None):
    y, sr = sf.read(str(path), dtype="float32")
    y = y.mean(axis=1) if y.ndim > 1 else y
    f = LiveAudioFeatures(sr)
    samples = []
    for i in range(0, len(y), 1024):
        f.feed(y[i : i + 1024])
        if f.t > 12:
            samples.append((f.t, f.bpm, f.beat_position(f.t)))
        if until and f.t > until:
            break
    return f, samples


def test_live_tempo_and_phase_on_clicks(tmp_path):
    f, samples = feed_file(click_track(tmp_path / "c.wav", bpm=120, seconds=20))
    assert np.median([s[1] for s in samples]) == pytest.approx(120, abs=1)
    errs = [((pos % 1) - (t / 0.5) % 1 + 0.5) % 1 - 0.5 for t, _, pos in samples]
    assert np.median(np.abs(errs)) < 0.1
    assert len(f.onsets) > 10


def test_live_locks_to_the_kick_not_the_offbeat_bass(tmp_path):
    path = tmp_path / "d.wav"
    make_demo_track(path, bpm=126, structure=[("verse", 10, {"kick", "hat", "bass", "snare"})])
    f, samples = feed_file(path)
    beat = 60 / 126
    assert np.median([s[1] for s in samples]) == pytest.approx(126, abs=1.5)
    errs = [((pos % 1) - (t / beat) % 1 + 0.5) % 1 - 0.5 for t, _, pos in samples]
    assert np.median(np.abs(errs)) < 0.15
    fr = f.frame(f.t)
    assert 0 <= fr.low <= 1 and 0 <= fr.rms <= 1 and fr.section == "live"
    assert len(f.recent("beat", f.t, 2.0)) >= 3


def test_live_input_mode_via_api(tmp_path, demo_analysis):
    path, _ = demo_analysis
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "Live"}).json()["slug"]
        p = c.get(f"/api/projects/{slug}").json()
        p["fixtures"] = [
            {"id": "f", "name": "F", "geometry": {"type": "polyline", "points": [[0, 1, 1], [3, 1, 1]]}, "led_count": 60}
        ]
        c.put(f"/api/projects/{slug}", json=p)
        with open(path, "rb") as fh:
            song = c.post("/api/songs", files={"file": ("demo.wav", fh, "audio/wav")}).json()
        st = c.post("/api/playback/live-input", json={"enabled": True, "file_song_id": song["id"]}).json()
        assert st["live_input"]["device"].startswith("Datei") and st["show_name"] == "Live (Mikrofon)"
        shows = c.get(f"/api/projects/{slug}/shows").json()
        assert [s["name"] for s in shows] == ["Live (Mikrofon)"]  # editable like any show
        with c.websocket_connect("/ws") as ws:
            got = 0
            for _ in range(300):
                msg = ws.receive()
                if msg.get("bytes"):
                    got += 1
                    if got > 20:
                        break
        assert got > 20
        time.sleep(1.0)
        st = c.get("/api/playback").json()
        assert st["live_input"]["time"] > 0.5 and st["playing"] is False
        st = c.post("/api/playback/live-input", json={"enabled": False}).json()
        assert st["live_input"] is None
        # starting again reuses the existing live show
        c.post("/api/playback/live-input", json={"enabled": True, "file_song_id": song["id"]})
        c.post("/api/playback/live-input", json={"enabled": False})
        assert len(c.get(f"/api/projects/{slug}/shows").json()) == 1
