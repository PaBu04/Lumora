"""Hardening against requests from other sites, hostile project files and paths that leave the data folder."""

import io
import json
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient

from lumora.app import create_app
from lumora.model.room import FloorplanImage
from lumora.model.song import Song
from lumora.output.wled import base_url
from lumora.render.shaders import Shader, ShaderError
from lumora.storage.project_store import ProjectStore

ROOM = {"floor": [[0, 0], [5, 0], [5, 4], [0, 4]], "height": 2.5}


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=tmp_path / "data", audio="null", fps=50, frontend=tmp_path / "nofrontend")
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_requests_a_browser_marks_as_cross_site_are_refused(client):
    """A link or <img> on another site sends a GET without an Origin header - only Sec-Fetch-Site gives it away."""
    for site in ("cross-site", "same-site"):
        assert client.get("/api/devices/info", params={"host": "10.0.0.1"}, headers={"sec-fetch-site": site}).status_code == 403
        assert client.get("/api/projects", headers={"sec-fetch-site": site}).status_code == 403
    # the app's own requests, an address typed into the browser and clients that are no browser
    assert client.get("/api/projects", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    assert client.get("/api/projects", headers={"sec-fetch-site": "none"}).status_code == 200
    assert client.get("/api/projects").status_code == 200
    # the app itself may be opened from a link on another site (no frontend built here: not found, not refused)
    assert client.get("/", headers={"sec-fetch-site": "cross-site"}).status_code == 404


@pytest.mark.parametrize("host", ["192.168.1.20", "wled-decke.local", "127.0.0.1:8081", " http://wled.local/ "])
def test_controller_addresses(host):
    assert base_url(host).startswith("http://") and base_url(host).count("/") == 2


@pytest.mark.parametrize(
    "host", ["10.0.0.1/cgi-bin/reboot?x=", "user:pw@10.0.0.1", "10.0.0.1#", "a b", "", "10.0.0.1:80/x", "[::1]"]
)
def test_addresses_that_carry_more_than_a_host_are_refused(host):
    with pytest.raises(ValueError):
        base_url(host)


def test_device_info_does_not_request_arbitrary_urls(client):
    r = client.get("/api/devices/info", params={"host": "192.168.1.1/apply.cgi?reboot=1&x="})
    assert r.status_code == 502 and "not a host name" in r.json()["detail"]


def test_project_slugs_stay_inside_the_projects_folder(client, tmp_path):
    store = ProjectStore(tmp_path / "projects")
    for slug in ("..", "..\\..\\x", "../x", "a/b", "C:x", "", ".hidden", "a..b"):
        with pytest.raises(KeyError):
            store.project_dir(slug)
        assert not store.exists(slug)
    assert store.project_dir("wohnzimmer-2").parent == store.root
    # through the API: a project.json one level up must not be reachable (or deletable) as project ".."
    slug = client.post("/api/projects", json={"name": "Raum"}).json()["slug"]
    outside = tmp_path / "data" / "project.json"
    outside.write_text((tmp_path / "data" / "projects" / slug / "project.json").read_text(encoding="utf-8"), encoding="utf-8")
    for bad in ("%2e%2e", "..%5C..%5Cdata"):
        assert client.get(f"/api/projects/{bad}").status_code == 404
        assert client.delete(f"/api/projects/{bad}").status_code == 404
    assert outside.is_file()


@pytest.mark.parametrize(
    "name", ["../../secret.txt", "..\\secret", "C:\\Windows\\win.ini", "/etc/passwd", "..", ".env", "a/b.png"]
)
def test_stored_file_names_cannot_be_paths(name):
    with pytest.raises(ValueError):
        FloorplanImage(filename=name, px_width=10, px_height=10)
    with pytest.raises(ValueError):
        Song(title="x", filename=name)
    assert FloorplanImage(filename="floorplan.png", px_width=10, px_height=10).filename == "floorplan.png"
    assert Song(title="x", filename="audio.mp3").filename == "audio.mp3"


class _Leds:
    n = 4


ESCAPES = {
    "builtins behind a numpy module": "f = np.ma.core.builtins.open",
    "a numpy submodule that is not listed": "x = np.ma.zeros(3)",
    "the frame of a generator": "g = (i for i in [1])\n    x = g.gi_frame.f_builtins",
    "frames of a traceback": "try:\n        1 / 0\n    except Exception as e:\n        x = e.tb_frame",
    "importlib": "x = np.importlib",
    "changing numpy": "np.zeros = None",
}


@pytest.mark.parametrize("name", ESCAPES)
def test_shaders_cannot_reach_the_interpreter(name):
    source = f"def render(t, leds, audio, params):\n    {ESCAPES[name]}\n    return np.zeros((leds.n, 3))"
    with pytest.raises(ShaderError):
        Shader("x", source).fn(0.0, _Leds(), None, {})


def test_shaders_still_get_numpy():
    source = (
        "import numpy as n2\n"
        "def render(t, leds, audio, params):\n"
        "    r = np.random.default_rng(1).random(leds.n)\n"
        "    v = np.linalg.norm(np.ones((leds.n, 3)), axis=1) + n2.pi + np.fft.fft(np.ones(4)).real[0]\n"
        "    return np.clip(np.stack([r, v * 0, r], axis=1).astype(np.float32), 0, 1) * isinstance(r, np.ndarray)\n"
    )
    out = Shader("ok", source).fn(0.0, _Leds(), None, {})
    assert out.shape == (4, 3) and out.dtype == np.float32


def _archive(project: dict, extra: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"format": "lumora-project", "version": 1}))
        z.writestr("project.json", json.dumps(project))
        for name, data in extra.items():
            z.writestr(name, data)
    return buf.getvalue()


def _import(client, data: bytes):
    return client.post("/api/projects/import", files={"file": ("p.lumora.zip", data, "application/zip")})


def test_import_checks_every_file_and_leaves_nothing_behind(client, tmp_path, monkeypatch):
    project = {"name": "Fremd", "room": ROOM}
    show = {"id": "abc", "name": "S", "layers": []}

    # a floor plan that points outside the project
    evil = {**project, "floorplan": {"filename": "..\\..\\settings.json", "px_width": 1, "px_height": 1}}
    assert _import(client, _archive(evil, {})).status_code == 422
    # a show stored under another id, broken looks
    assert _import(client, _archive(project, {"shows/other.json": json.dumps(show)})).status_code == 422
    assert _import(client, _archive(project, {"looks.json": '[{"nope": 1}]'})).status_code == 422
    assert client.get("/api/projects").json()["projects"] == []

    # an archive that unpacks to more than allowed (its directory may claim anything)
    from lumora.storage import transfer

    monkeypatch.setattr(transfer, "MAX_BYTES", 200_000)
    big = _archive(project, {"shows/abc.json": json.dumps(show), "floorplan.png": b"\0" * 400_000})
    r = _import(client, big)
    assert r.status_code == 422 and "zu groß" in r.json()["detail"]
    assert client.get("/api/projects").json()["projects"] == []
    assert not list((tmp_path / "data" / "projects").glob("*"))
    monkeypatch.undo()
    # the limit holds for what really comes out, whatever the archive's directory says
    with zipfile.ZipFile(io.BytesIO(big)) as z:
        with pytest.raises(transfer.ImportError_):
            transfer._extract(z, "floorplan.png", tmp_path / "out.png", transfer._Budget(100_000))
        with pytest.raises(transfer.ImportError_):
            transfer._read(z, "floorplan.png", transfer._Budget(10**9), limit=1000)

    # a good archive: shaders that fail the code check are left out, the rest arrives
    good = _archive(
        {**project, "floorplan": {"filename": "floorplan.png", "px_width": 1, "px_height": 1}},
        {
            "shows/abc.json": json.dumps(show),
            "shows/order.json": '["abc"]',
            "shaders/fine.py": "def render(t, leds, audio, params):\n    return np.zeros((leds.n, 3))\n",
            "shaders/evil.py": "def render(t, leds, audio, params):\n    return np.ma.core.builtins.open('x', 'w')\n",
        },
    )
    res = _import(client, good)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["shows"] == 1 and body["shaders_refused"] == ["evil"]
    assert client.get(f"/api/projects/{body['slug']}/shaders").json()["shaders"] == ["fine"]
    assert client.get(f"/api/projects/{body['slug']}").json()["floorplan"] is None  # its image was not in the archive


def test_oversized_uploads_are_refused(client):
    slug = client.post("/api/projects", json={"name": "Raum"}).json()["slug"]
    source = "def render(t, leds, audio, params):\n    return np.zeros((leds.n, 3))\n"
    assert client.put(f"/api/projects/{slug}/shaders/ok", content=source).status_code == 200
    assert client.put(f"/api/projects/{slug}/shaders/big", content=source + "#" * 300_000).status_code == 413
    assert client.put(f"/api/projects/{slug}/shaders/bin", content=b"\xff\xfe\x00").status_code == 422
    assert client.get(f"/api/projects/{slug}/shaders").json()["shaders"] == ["ok"]
