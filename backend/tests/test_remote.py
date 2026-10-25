"""Phone remote: only with the key, play / pause, brightness and live cues that do not change the show."""

import numpy as np
from fastapi.testclient import TestClient

from lumora.app import create_app
from lumora.remote import create_remote_app


def _app(tmp_path, monkeypatch):
    from lumora.remote import RemoteServer

    async def no_network(self, port=0):  # never open a port on all interfaces in tests
        return None

    monkeypatch.setattr(RemoteServer, "start", no_network)
    return create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")


def test_remote_needs_the_key_and_controls_playback(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        slug = c.post("/api/projects", json={"name": "R"}).json()["slug"]
        project = c.get(f"/api/projects/{slug}").json()
        project["fixtures"] = [{"id": "f", "geometry": {"type": "polyline", "points": [[0, 3, 2], [4, 3, 2]]}, "led_count": 60}]
        c.put(f"/api/projects/{slug}", json=project)
        show = c.post(f"/api/projects/{slug}/shows", json={"name": "Leer", "template": "empty"}).json()
        c.put(f"/api/projects/{slug}/shows/{show['id']}", json={**show, "duration": 60})
        c.post("/api/playback/load", json={"project": slug, "show": show["id"]})

        info = c.put("/api/remote", json={"enabled": True}).json()
        assert info["enabled"] and info["url"].endswith(c.app.state.lumora.settings["remote_key"]) and "<svg" in info["qr"]
        st = app.state.lumora
        r = TestClient(create_remote_app(st))
        key = st.settings["remote_key"]
        assert r.get("/state").status_code == 403 and r.get("/state", params={"k": "wrong"}).status_code == 403
        assert "Fernbedienung" in r.get("/", params={"k": key}).text

        s = r.get("/state", params={"k": key}).json()
        assert s["show_name"] == "Leer" and s["shows"][0]["id"] == show["id"]
        assert r.post("/action", params={"k": key}, json={"action": "toggle"}).json()["playing"] is True
        assert r.post("/action", params={"k": key}, json={"action": "pause"}).json()["playing"] is False
        assert r.post("/action", params={"k": key}, json={"action": "brightness", "value": 0.4}).json()["brightness"] == 0.4

        # a cue lights the LEDs for a moment without becoming part of the show
        renderer = st.session.loaded.renderer
        t = st.session.show_time()
        assert float(renderer.render(t + 0.05).max()) == 0.0
        r.post("/action", params={"k": key}, json={"action": "cue", "kind": "flash", "color": "#ff0000"})
        frame = renderer.render(t + 0.05)
        assert frame[:, 0].max() > 0.3 and frame[:, 2].max() < 0.05
        assert c.get(f"/api/projects/{slug}/shows/{show['id']}").json()["layers"] == []
        assert not np.any(renderer.render(t + 30))  # gone afterwards
        assert r.post("/action", params={"k": key}, json={"action": "cue", "kind": "nope"}).status_code == 422

        # a new key locks out the old one
        c.put("/api/remote", json={"new_key": True})
        assert r.get("/state", params={"k": key}).status_code == 403
        assert c.put("/api/remote", json={"enabled": False}).json()["url"] is None
