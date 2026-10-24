import numpy as np
import pytest
from pydantic import ValidationError

from lumora.geometry.led_table import build_led_table
from lumora.model.controller import Controller, FixtureMapping
from lumora.model.fixture import Fixture, LedType, MatrixGeometry, PolylineGeometry
from lumora.model.project import Project
from lumora.model.room import Room, polygon_area
from lumora.model.viewer import Viewer
from lumora.storage.project_store import ProjectStore

ROOM = Room(floor=[(0, 0), (4, 0), (4, 3), (0, 3)], height=2.5)


def make_project() -> Project:
    ceiling = Fixture(
        id="ceiling",
        name="Ceiling edge",
        geometry=PolylineGeometry(points=[(0, 0, 2.5), (4, 0, 2.5), (4, 3, 2.5)]),
        leds_per_meter=30,
        tags=["ceiling"],
    )
    panel = Fixture(
        id="panel",
        geometry=MatrixGeometry(origin=(4, 1, 2), col_dir=(0, 1, 0), cols=16, rows=16, pitch=1 / 16),
        led_type=LedType.SK6812_RGBW,
    )
    wled = Controller(
        id="c1",
        host="192.168.1.50",
        mappings=[
            FixtureMapping(fixture_id="ceiling", start=0),
            FixtureMapping(fixture_id="panel", start=210),
        ],
    )
    return Project(
        name="Wohnzimmer",
        room=ROOM,
        viewer=Viewer(position=(1, 1.5, 1.2), yaw_deg=0),
        fixtures=[ceiling, panel],
        controllers=[wled],
    )


def test_room_rejects_self_intersection():
    with pytest.raises(ValidationError):
        Room(floor=[(0, 0), (2, 2), (2, 0), (0, 2)], height=2)


def test_room_normalises_to_ccw():
    room = Room(floor=[(0, 0), (0, 3), (4, 3), (4, 0)], height=2)
    assert room.floor == [(4, 0), (4, 3), (0, 3), (0, 0)]
    assert polygon_area(room.floor) > 0
    assert len(room.walls) == 4


def test_led_type_channels():
    assert LedType.WS2812B.channels == 3
    assert LedType.SK6812_RGBW.channels == 4


def test_mapping_unknown_fixture_rejected():
    p = make_project()
    data = p.model_dump()
    data["controllers"][0]["mappings"][0]["fixture_id"] = "nope"
    with pytest.raises(ValidationError, match="unknown fixture"):
        Project.model_validate(data)


def test_mapping_overlap_rejected():
    data = make_project().model_dump()
    data["controllers"][0]["mappings"][1]["start"] = 100  # ceiling occupies 0..209
    with pytest.raises(ValidationError, match="overlapping"):
        Project.model_validate(data)


def test_led_table():
    t = build_led_table(make_project())
    assert t.count == 210 + 256
    assert t.fixture_slice("panel") == slice(210, 466)
    assert t.u[0] == 0 and t.u[209] == pytest.approx(1)
    assert t.index_in_fixture[210] == 0
    assert np.all((t.norm_pos >= 0) & (t.norm_pos <= 1))
    # panel hangs on the wall in front of the viewer (+x direction)
    panel_az = t.azimuth[t.fixture_slice("panel")]
    assert np.all(np.abs(panel_az) < 45)


def test_store_roundtrip(tmp_path):
    store = ProjectStore(tmp_path)
    p = make_project()
    slug = store.create(p)
    assert slug == "wohnzimmer"
    assert store.create(p) == "wohnzimmer-2"
    assert store.list() == ["wohnzimmer", "wohnzimmer-2"]
    assert (tmp_path / slug / "songs").is_dir()
    assert store.load(slug) == p
