import os

import pytest

from lsg.audio.analysis import analyse_file
from lsg.audio.demo import make_demo_track
from lsg.model.controller import Controller, FixtureMapping
from lsg.model.fixture import CircleGeometry, Fixture, MatrixGeometry, PolylineGeometry
from lsg.model.project import Project
from lsg.model.room import Room
from lsg.model.viewer import Viewer


@pytest.fixture(autouse=True)
def _no_separation_model(request, monkeypatch):
    """Tests use the fast harmonic / percussive approximation instead of the Demucs model
    (tests marked "ml" run the real model)."""
    if "ml" not in request.keywords:
        from lsg.audio import stems

        monkeypatch.setattr(stems, "installed", lambda: False)
        monkeypatch.setattr(stems, "six_installed", lambda: False)  # also skips importing torch


# analyses that a test started in the background may outlive its monkeypatch: never let them load the models
os.environ["LSG_STEMS"] = "approx"

SHORT_STRUCTURE = [
    ("intro", 2, {"hat", "pad"}),
    ("verse", 4, {"kick", "hat", "bass"}),
    ("chorus", 4, {"kick", "hat", "bass", "snare", "lead"}),
]


@pytest.fixture
def project() -> Project:
    """5 x 4 m room, viewer at the south wall looking north (+y)."""
    return Project(
        name="Test",
        room=Room(floor=[(0, 0), (5, 0), (5, 4), (0, 4)], height=2.5),
        viewer=Viewer(position=(2.5, 0.5, 1.6), yaw_deg=90),
        fixtures=[
            Fixture(
                id="north",
                name="North wall",
                geometry=PolylineGeometry(points=[(0.2, 4, 2.4), (4.8, 4, 2.4)]),
                leds_per_meter=30,
                tags=["wall", "ceiling"],
            ),
            Fixture(
                id="west",
                name="West wall",
                geometry=PolylineGeometry(points=[(0, 0.5, 2.4), (0, 3.8, 2.4)]),
                leds_per_meter=30,
                tags=["wall"],
            ),
            Fixture(
                id="ring", name="Ring", geometry=CircleGeometry(center=(2.5, 2, 2.5), radius=0.6), led_count=40, tags=["ceiling"]
            ),
            Fixture(
                id="panel",
                name="Panel",
                geometry=MatrixGeometry(origin=(2, 3.95, 1.8), col_dir=(1, 0, 0), row_dir=(0, 0, -1), cols=8, rows=8, pitch=0.05),
            ),
        ],
        controllers=[Controller(id="c1", host="127.0.0.1", mappings=[FixtureMapping(fixture_id="north")])],
    )


@pytest.fixture(scope="session")
def demo_analysis(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "demo.wav"
    make_demo_track(path, bpm=120, structure=SHORT_STRUCTURE)
    return path, analyse_file(path, stems="approx")  # session fixture: set the stem mode explicitly
