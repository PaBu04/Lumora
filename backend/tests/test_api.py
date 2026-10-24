import struct
import time

import pytest
from fastapi.testclient import TestClient

from lumora.app import create_app

FIXTURES = [
    {
        "id": "front",
        "name": "Front",
        "geometry": {"type": "polyline", "points": [[0.2, 4, 2.4], [4.8, 4, 2.4]]},
        "leds_per_meter": 30,
        "tags": ["ceiling"],
    },
    {"id": "ring", "name": "Ring", "geometry": {"type": "circle", "center": [2.5, 2, 2.5], "radius": 0.5}, "led_count": 24},
]


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "nofrontend")
    with TestClient(app) as c:
        yield c


def wait_for(fn, timeout=60.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.2)
    raise TimeoutError


def make_project(client) -> str:
    r = client.post("/api/projects", json={"name": "Wohnzimmer"})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]
    project = client.get(f"/api/projects/{slug}").json()
    project["fixtures"] = FIXTURES
    r = client.put(f"/api/projects/{slug}", json=project)
    assert r.status_code == 200, r.text
    return slug


def test_project_crud(client):
    slug = make_project(client)
    listing = client.get("/api/projects").json()
    assert listing["active"] == slug and listing["projects"][0]["fixtures"] == 2
    leds = client.get(f"/api/projects/{slug}/leds").json()
    assert leds["count"] == 138 + 24 and len(leds["positions"]) == leds["count"] * 3
    bad = client.get(f"/api/projects/{slug}").json()
    bad["controllers"] = [{"host": "1.2.3.4", "mappings": [{"fixture_id": "nope"}]}]
    assert client.put(f"/api/projects/{slug}", json=bad).status_code == 422
    assert client.get("/api/projects/missing").status_code == 404
    r = client.post("/api/fixtures/preview", json=FIXTURES[0])
    assert r.json() == {"count": 138, "length": 4.6}


def test_copy_project(client):
    slug = make_project(client)
    show = client.post(f"/api/projects/{slug}/shows", json={"name": "Leer"}).json()
    r = client.post("/api/projects", json={"name": "Wohnzimmer Kopie", "copy_from": slug})
    assert r.status_code == 200, r.text
    copy = r.json()["slug"]
    assert copy != slug and client.get("/api/projects").json()["active"] == copy
    project = client.get(f"/api/projects/{copy}").json()
    assert project["name"] == "Wohnzimmer Kopie" and [f["id"] for f in project["fixtures"]] == ["front", "ring"]
    assert [s["id"] for s in client.get(f"/api/projects/{copy}/shows").json()] == [show["id"]]
    assert len(client.get(f"/api/projects/{copy}/history").json()) == 1  # history starts fresh
    # changing the copy leaves the original alone
    project["fixtures"] = project["fixtures"][:1]
    client.put(f"/api/projects/{copy}", json=project)
    assert len(client.get(f"/api/projects/{slug}").json()["fixtures"]) == 2

    bare = client.post("/api/projects", json={"name": "Nur Raum", "copy_from": slug, "copy_shows": False}).json()["slug"]
    assert client.get(f"/api/projects/{bare}/shows").json() == []
    assert client.post("/api/projects", json={"name": "x", "copy_from": "missing"}).status_code == 404


def test_song_show_playback_flow(client):
    slug = make_project(client)
    song = client.post("/api/songs/demo", params={"bpm": 128}).json()
    done = wait_for(lambda: (s := client.get(f"/api/songs/{song['id']}").json())["status"] == "done" and s)
    assert done["duration"] > 60
    analysis = client.get(f"/api/songs/{song['id']}/analysis").json()
    assert analysis["bpm"] == pytest.approx(128, abs=1)

    show = client.post(f"/api/projects/{slug}/shows", json={"name": "Starter", "song_id": song["id"]}).json()
    assert len(show["layers"]) == 3
    issues = client.post(f"/api/projects/{slug}/shows/{show['id']}/validate").json()
    assert [i for i in issues if i["severity"] == "error"] == []
    png = client.get(f"/api/projects/{slug}/shows/{show['id']}/snapshot.png", params={"t": 40}).content
    assert png[:4] == b"\x89PNG"
    png = client.get(
        f"/api/projects/{slug}/shows/{show['id']}/timeline.png", params={"start": 0, "end": 20, "width": 200}
    ).content
    assert png[:4] == b"\x89PNG"

    with client.websocket_connect("/ws") as ws:
        state = ws.receive_json()
        assert state["type"] == "state"
        r = client.post("/api/playback/load", json={"project": slug, "show": show["id"]})
        assert r.json()["show"] == show["id"] and r.json()["duration"] > 60
        client.post("/api/playback/seek", json={"t": 30})
        client.post("/api/playback/play")
        frame = None
        for _ in range(200):
            msg = ws.receive()
            if msg.get("bytes"):
                frame = msg["bytes"]
                t, n = struct.unpack("<dI", frame[:12])
                if t > 30.05:
                    break
        assert frame is not None and n == 162 and len(frame) == 12 + n * 3
        assert any(frame[12:])
        state = client.post("/api/playback/pause").json()
        assert state["playing"] is False and state["position"] >= 30


def test_show_edit_and_shaders(client):
    slug = make_project(client)
    show = client.post(f"/api/projects/{slug}/shows", json={"name": "Empty", "template": "empty"}).json()
    show["duration"] = 20
    show["layers"] = [{"name": "A", "clips": [{"start": 0, "end": 10, "effect": "shader:glow"}]}]
    assert client.put(f"/api/projects/{slug}/shows/{show['id']}", json=show).status_code == 200
    issues = client.post(f"/api/projects/{slug}/shows/{show['id']}/validate").json()
    assert "unknown shader" in issues[0]["message"]

    r = client.put(f"/api/projects/{slug}/shaders/glow", content="def render(t, leds, audio, params):\n    return color('red')")
    assert r.status_code == 200, r.text
    issues = client.post(f"/api/projects/{slug}/shows/{show['id']}/validate").json()
    assert [i for i in issues if i["severity"] == "error"] == []
    assert "def render" in client.get(f"/api/projects/{slug}/shaders/glow").text
    r = client.put(f"/api/projects/{slug}/shaders/evil", content="import os\ndef render(t, leds, audio, params): pass")
    assert r.status_code == 422 and "import" in r.json()["detail"]
    assert client.get(f"/api/projects/{slug}/shaders").json()["shaders"] == ["glow"]
    assert client.get("/api/effects").json()["effects"][0]["id"] == "solid"


def test_show_order_is_kept(client):
    slug = make_project(client)
    ids = [client.post(f"/api/projects/{slug}/shows", json={"name": n, "template": "empty"}).json()["id"] for n in "ABC"]
    names = lambda: [s["name"] for s in client.get(f"/api/projects/{slug}/shows").json()]  # noqa: E731
    assert names() == ["A", "B", "C"]  # by name until the user sorts
    r = client.put(f"/api/projects/{slug}/shows/order", json={"ids": [ids[2], ids[0], ids[1], "unknown"]})
    assert r.status_code == 200 and [s["name"] for s in r.json()] == ["C", "A", "B"]
    d = client.post(f"/api/projects/{slug}/shows", json={"name": "0 neu", "template": "empty"}).json()
    assert names() == ["C", "A", "B", "0 neu"]  # new shows go to the end
    client.delete(f"/api/projects/{slug}/shows/{ids[0]}")
    assert names() == ["C", "B", "0 neu"]
    assert client.get(f"/api/projects/{slug}/shows/order").status_code == 404
    assert d["id"] != "order"


def test_example_project(client):
    r = client.post("/api/projects/example")
    assert r.status_code == 200, r.text
    slug, song = r.json()["slug"], r.json()["song"]
    project = client.get(f"/api/projects/{slug}").json()
    assert project["name"] == "Beispielraum" and len(project["fixtures"]) == 4
    assert client.get("/api/projects").json()["active"] == slug
    # once the demo song is analysed, the starter show appears
    shows = wait_for(lambda: client.get(f"/api/projects/{slug}/shows").json(), timeout=120)
    assert shows[0]["name"] == "Beispiel-Show" and shows[0]["song_id"] == song["id"] and shows[0]["clips"] > 10


def test_export_and_import_project(client, tmp_path):
    import io
    import zipfile

    slug = make_project(client)
    song = client.post("/api/songs/demo", params={"bpm": 120}).json()
    wait_for(lambda: client.get(f"/api/songs/{song['id']}").json()["status"] == "done")
    show = client.post(f"/api/projects/{slug}/shows", json={"name": "Mit Song", "song_id": song["id"]}).json()
    r = client.get(f"/api/projects/{slug}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert {"manifest.json", "project.json", f"shows/{show['id']}.json", f"songs/{song['id']}/analysis.json"} <= set(names)

    # into another installation: project, show and song arrive
    other = create_app(data_dir=tmp_path / "other", audio="null", fps=50, frontend=tmp_path / "nofrontend")
    with TestClient(other) as c2:
        res = c2.post("/api/projects/import", files={"file": ("p.lumora.zip", r.content, "application/zip")}).json()
        assert res["name"] == "Wohnzimmer" and res["shows"] == 1 and res["songs_added"] == [song["id"]]
        new = res["slug"]
        assert len(c2.get(f"/api/projects/{new}").json()["fixtures"]) == 2
        shows = c2.get(f"/api/projects/{new}/shows").json()
        assert shows[0]["id"] == show["id"] and shows[0]["song_id"] == song["id"]
        assert c2.get(f"/api/songs/{song['id']}").json()["status"] == "done"
        assert c2.get(f"/api/songs/{song['id']}/analysis").status_code == 200
        # importing again: a second project, the song is not copied twice
        again = c2.post("/api/projects/import", files={"file": ("p.lumora.zip", r.content, "application/zip")}).json()
        assert again["name"] == "Wohnzimmer (2)" and again["songs_present"] == [song["id"]]

        # no files outside the project
        evil = io.BytesIO()
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("manifest.json", '{"format": "lumora-project", "version": 1}')
            z.writestr("project.json", c2.get(f"/api/projects/{new}").text)
            z.writestr("../../evil.py", "print(1)")
        bad = c2.post("/api/projects/import", files={"file": ("e.zip", evil.getvalue(), "application/zip")})
        assert bad.status_code == 422 and "unerwartete" in bad.json()["detail"]
        assert c2.post("/api/projects/import", files={"file": ("x.zip", b"nope", "application/zip")}).status_code == 422


def test_creation_and_upload_dates(client, tmp_path):
    slug = make_project(client)
    before = time.time() - 1
    show = client.post(f"/api/projects/{slug}/shows", json={"name": "Datum", "template": "empty"}).json()
    listed = client.get(f"/api/projects/{slug}/shows").json()[0]
    assert before <= listed["created"] <= time.time() + 1 and show["created"] == listed["created"]
    # editing keeps the creation date
    client.put(f"/api/projects/{slug}/shows/{show['id']}", json={**show, "name": "Umbenannt", "created": None})
    assert client.get(f"/api/projects/{slug}/shows").json()[0]["created"] == listed["created"]
    song = client.post("/api/songs/demo", params={"bpm": 120}).json()
    assert before <= song["added"] <= time.time() + 1
    assert client.get("/api/songs").json()[0]["added"] == song["added"]
