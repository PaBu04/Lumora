import io

from fastapi.testclient import TestClient
from PIL import Image

from lumora.app import create_app


def png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


def test_floorplan_upload_scale_and_delete(tmp_path):
    app = create_app(data_dir=tmp_path, audio="null", fps=50, frontend=tmp_path / "x")
    with TestClient(app) as c:
        slug = c.post("/api/projects", json={"name": "Plan"}).json()["slug"]
        r = c.post(f"/api/projects/{slug}/floorplan", files={"file": ("grundriss.png", png(800, 400), "image/png")})
        assert r.status_code == 200, r.text
        fp = r.json()["floorplan"]
        assert (fp["px_width"], fp["px_height"], fp["width_m"], fp["x"], fp["y"]) == (800, 400, 5.0, 0.0, 0.0)
        assert c.get(f"/api/projects/{slug}/floorplan").content[:4] == b"\x89PNG"
        # the UI changes scale / position through the normal project update
        p = c.get(f"/api/projects/{slug}").json()
        p["floorplan"]["width_m"] = 7.5
        assert c.put(f"/api/projects/{slug}", json=p).json()["floorplan"]["width_m"] == 7.5
        assert c.post(f"/api/projects/{slug}/floorplan", files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 422
        assert (
            c.post(f"/api/projects/{slug}/floorplan", files={"file": ("x.png", b"not an image", "image/png")}).status_code == 422
        )
        assert c.delete(f"/api/projects/{slug}/floorplan").json()["floorplan"] is None
        assert c.get(f"/api/projects/{slug}/floorplan").status_code == 404
