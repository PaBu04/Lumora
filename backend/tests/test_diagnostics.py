"""The diagnostics package helps with bug reports and leaks no private data."""

import io
import logging
import zipfile

from fastapi.testclient import TestClient

from lsg import diagnostics
from lsg.app import create_app


def test_redact():
    text = (
        r"WLED 10.0.0.14:80 mac aa:bb:cc:dd:ee:ff at C:\Users\alex\Music\x.mp3 /home/kim/a"
        " and wled-desk.local mail me@example.org"
    )
    out = diagnostics.redact(text)
    for secret in ("10.0.0", "aa:bb", "alex", "kim", "wled-desk", "me@example"):
        assert secret not in out, out
    assert "<ip>" in out and "<mac>" in out and "<user>" in out and "<host>" in out and "<e-mail>" in out


def test_package_without_private_data(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "Wohnung Familie Muster"}).json()["slug"]
        project = c.get(f"/api/projects/{slug}").json()
        project["fixtures"] = [
            {"id": "f1", "name": "Bett von Anna", "geometry": {"type": "polyline", "points": [[0, 0, 2], [3, 0, 2]]}}
        ]
        project["controllers"] = [
            {"name": "Arbeitszimmer", "host": "10.0.0.15", "mac": "aa:bb:cc:dd:ee:01", "mappings": [{"fixture_id": "f1"}]}
        ]
        assert c.put(f"/api/projects/{slug}", json=project).status_code == 200
        song = c.post("/api/songs/demo", params={"bpm": 120}).json()
        c.patch(f"/api/songs/{song['id']}", json={"title": "Geheimer Lieblingssong", "artist": "Privat"})
        logging.getLogger("lsg.test").warning("could not reach 10.0.0.15 for Arbeitszimmer.local")

        d = c.get("/api/diagnostics").json()
        assert d["diagnostics"]["projects"][0]["strips"] == 1 and len(d["diagnostics"]["projects"][0]["controllers"]) == 1
        assert d["diagnostics"]["python"] and d["diagnostics"]["packages"]["numpy"]
        r = c.get("/api/diagnostics", params={"download": True})
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert set(z.namelist()) == {"diagnostics.json", "log.txt", "LIESMICH.txt"}
        everything = (z.read("diagnostics.json") + z.read("log.txt")).decode()
        assert "could not reach" in everything  # the log is there ...
        for secret in ("Muster", "Anna", "Arbeitszimmer", "10.0.0", "aa:bb", "Lieblingssong", "Privat", slug, str(tmp_path)):
            assert secret not in everything, secret  # ... but nothing private


def test_preview_is_redacted_too(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        c.post("/api/projects", json={"name": "Wohnung Familie Muster"})
        d = c.get("/api/diagnostics").json()
        assert "Muster" not in str(d) and "muster" not in str(d)


def test_licenses(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")) as c:
        lic = c.get("/api/licenses").json()
        names = {p["name"]: p["license"] for p in lic["python"]}
        assert "MIT" in names["fastapi"] and names["librosa"] and names["onnxruntime"]
        assert any(m["name"].startswith("Basic Pitch") and m["license"] == "Apache-2.0" for m in lic["models"])
