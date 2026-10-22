import json
import struct
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lsg.app import create_app
from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import build_led_table
from lsg.model.show import Clip, Layer, Show
from lsg.output.export import export_show
from lsg.output.fseq import read_fseq, write_fseq, zstd_available
from lsg.output.pipeline import OutputPipeline
from lsg.render.engine import Renderer


def frames(n, channels):
    rng = np.random.default_rng(1)
    return [rng.integers(0, 256, channels, dtype=np.uint8).tobytes() for _ in range(n)]


@pytest.mark.parametrize("compress", [False, True])
def test_fseq_roundtrip(tmp_path, compress):
    if compress and not zstd_available():
        pytest.skip("zstd needs Python 3.14")
    data = frames(700, 90)
    path = tmp_path / "a.fseq"
    info = write_fseq(path, iter(data), 90, 700, 25, media="song.mp3", compress=compress)
    assert info["compressed"] == compress
    f = read_fseq(path)
    assert f["version"] == (2, 0) and f["channels"] == 90 and f["frames"] == 700 and f["step_ms"] == 25
    assert f["headers"] == {"mf": "song.mp3", "sp": "Neopixel Light Show Generator"}
    assert f["compression"] == (1 if compress else 0)
    assert f["data_len"] == 700 * 90
    assert all(f["frame"](i) == data[i] for i in (0, 1, 350, 699))
    if compress:
        assert 1 < len(f["blocks"]) <= 255 and f["blocks"][0][0] == 0
        assert all(b[0] < c[0] for b, c in zip(f["blocks"], f["blocks"][1:], strict=False))


def test_header_bytes_follow_the_spec(tmp_path):
    path = tmp_path / "b.fseq"
    write_fseq(path, iter(frames(3, 6)), 6, 3, 50, compress=False)
    raw = path.read_bytes()
    assert raw[:4] == b"PSEQ" and raw[6] == 0 and raw[7] == 2
    assert struct.unpack_from("<H", raw, 8)[0] == 32  # standard header length
    assert struct.unpack_from("<I", raw, 10)[0] == 6 and struct.unpack_from("<I", raw, 14)[0] == 3
    assert raw[18] == 50 and raw[20] == 0 and raw[21] == 0 and raw[22] == 0
    offset = struct.unpack_from("<H", raw, 4)[0]
    assert offset % 4 == 0 and len(raw) == offset + 18
    assert raw[32:34] == struct.pack("<H", 4 + len(b"Neopixel Light Show Generator\0")) and raw[34:36] == b"sp"


def test_export_matches_live_output(project, tmp_path):
    table = build_led_table(project)
    show = Show(
        name="Export Test", duration=2.0, layers=[Layer(clips=[Clip(start=0, end=2, effect="rainbow", params={"speed": 1})])]
    )
    r = Renderer(project, table, show, AudioFeatures(None, 2.0), {})
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"RIFF....")
    out = tmp_path / "export.zip"
    info = export_show(r, out, fps=20, audio=audio)
    assert info["frames"] == 40 and info["layout"][0]["start_channel"] == 1
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert names == {"Export Test.fseq", "Export Test.wav", "channels.json", "README.txt"}
        z.extract("Export Test.fseq", tmp_path)
        layout = json.loads(z.read("channels.json"))
    f = read_fseq(tmp_path / "Export Test.fseq")
    assert f["headers"]["mf"] == "Export Test.wav"
    assert f["channels"] == sum(o["channels"] for o in layout["outputs"])
    pipeline = OutputPipeline(project, table)
    frame = r.render(0.5)
    expected = b"".join(o.data for o in pipeline.encode_all(lambda c: frame)[0])
    assert f["frame"](10) == expected  # frame 10 at 20 fps = 0.5 s


def test_export_endpoint_requires_controllers(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "Ex"}).json()["slug"]
        p = c.get(f"/api/projects/{slug}").json()
        p["fixtures"] = [
            {"id": "f", "name": "F", "geometry": {"type": "polyline", "points": [[0, 1, 1], [2, 1, 1]]}, "led_count": 30}
        ]
        c.put(f"/api/projects/{slug}", json=p)
        show = c.post(f"/api/projects/{slug}/shows", json={"name": "S", "template": "empty"}).json()
        show["duration"] = 3
        show["layers"] = [{"name": "L", "clips": [{"start": 0, "end": 3, "effect": "solid"}]}]
        c.put(f"/api/projects/{slug}/shows/{show['id']}", json=show)
        r = c.get(f"/api/projects/{slug}/shows/{show['id']}/export")
        assert r.status_code == 422 and "controller" in r.json()["detail"]
        p = c.get(f"/api/projects/{slug}").json()
        p["controllers"] = [{"id": "c", "host": "1.2.3.4", "mappings": [{"fixture_id": "f"}]}]
        c.put(f"/api/projects/{slug}", json=p)
        r = c.get(f"/api/projects/{slug}/shows/{show['id']}/export", params={"fps": 25})
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        path = tmp_path / "dl.zip"
        path.write_bytes(r.content)
        with zipfile.ZipFile(path) as z:
            z.extract("S.fseq", tmp_path)
        f = read_fseq(tmp_path / "S.fseq")
        assert f["frames"] == 75 and f["channels"] == 90 and f["frame"](0)[:3] == bytes([255, 255, 255])
