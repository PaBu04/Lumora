import time

import pytest
from fastapi.testclient import TestClient

from lsg.app import create_app
from lsg.model.show import Clip, Layer, Show
from lsg.storage import history as history_mod
from lsg.storage.history import History, show_summary
from lsg.storage.show_store import ShowStore


def make_show(n: int) -> Show:
    return Show(
        id="s1",
        name="S",
        layers=[Layer(id="l1", name="L", clips=[Clip(id=f"c{i}", start=i, end=i + 1, effect="solid") for i in range(n)])],
    )


def test_ui_saves_coalesce_but_ai_saves_do_not(tmp_path, monkeypatch):
    store = ShowStore(tmp_path)
    store.save(make_show(1), "system")
    store.save(make_show(2), "ui")
    store.save(make_show(3), "ui")  # within the coalesce window -> merged with the previous UI version
    versions = store.history("s1").list()
    assert [v["source"] for v in versions] == ["ui", "system"]
    assert "+1 Clip" in versions[0]["summary"]
    store.save(make_show(4), "ai")
    store.save(make_show(5), "ai")
    assert [v["source"] for v in store.history("s1").list()][:3] == ["ai", "ai", "ui"]
    # identical content is not recorded twice
    store.save(make_show(5), "ui")
    assert len(store.history("s1").list()) == 4
    # outside the window a new UI version is created
    monkeypatch.setattr(history_mod, "COALESCE_SECONDS", 0.0)
    time.sleep(0.01)
    store.save(make_show(6), "ui")
    store.save(make_show(7), "ui")
    assert len(store.history("s1").list()) == 6


def test_restore_keeps_current_state_in_history(tmp_path):
    store = ShowStore(tmp_path)
    store.save(make_show(1), "system")
    store.save(make_show(3), "ai")
    first = store.history("s1").list()[-1]["id"]
    restored = store.restore("s1", first)
    assert sum(len(l.clips) for l in restored.layers) == 1
    assert store.get("s1") == restored
    versions = store.history("s1").list()
    assert versions[0]["source"] == "restore" and len(versions) == 3
    with pytest.raises(KeyError):
        store.restore("s1", "../../etc")
    store.delete("s1")
    assert store.history("s1").list() == []


def test_summaries():
    a = make_show(2).model_dump()
    b = make_show(3).model_dump()
    b["layers"][0]["clips"][0]["end"] = 5
    assert show_summary(a, b) == "+1 Clip, 1 Clip geändert"
    assert show_summary(None, a) == "erstellt (2 Clips)"


def test_history_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(history_mod, "MAX_VERSIONS", 5)
    h = History(tmp_path)
    for i in range(9):
        h.record(f'{{"v": {i}}}', "ai", f"v{i}")
    assert [v["summary"] for v in h.list()] == ["v8", "v7", "v6", "v5", "v4"]


def test_versions_api(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "H"}).json()["slug"]
        p = c.get(f"/api/projects/{slug}").json()
        p["room"]["height"] = 3.0
        c.put(f"/api/projects/{slug}", json=p)
        versions = c.get(f"/api/projects/{slug}/versions").json()
        assert [v["source"] for v in versions] == ["ui", "system"] and versions[0]["summary"] == "Raum"
        restored = c.post(f"/api/projects/{slug}/versions/{versions[1]['id']}/restore").json()
        assert restored["room"]["height"] == 2.5
        assert c.get(f"/api/projects/{slug}").json()["room"]["height"] == 2.5

        show = c.post(f"/api/projects/{slug}/shows", json={"name": "S", "template": "empty"}).json()
        show["layers"] = [{"name": "A", "clips": [{"start": 0, "end": 2, "effect": "solid"}]}]
        c.put(f"/api/projects/{slug}/shows/{show['id']}", json=show)
        vs = c.get(f"/api/projects/{slug}/shows/{show['id']}/versions").json()
        assert len(vs) == 2 and vs[0]["summary"] == "+1 Clip, Ebenen geändert"
        old = c.get(f"/api/projects/{slug}/shows/{show['id']}/versions/{vs[1]['id']}").json()
        assert old["layers"] == []
        c.post(f"/api/projects/{slug}/shows/{show['id']}/versions/{vs[1]['id']}/restore")
        assert c.get(f"/api/projects/{slug}/shows/{show['id']}").json()["layers"] == []
