from pydantic import BaseModel, Field, model_validator

from lsg.geometry.sampling import fixture_led_count
from lsg.model.calibration import LedCalibration, PowerSettings, default_calibration
from lsg.model.controller import Controller
from lsg.model.fixture import Fixture, LedType
from lsg.model.room import FloorplanImage, Room
from lsg.model.viewer import Viewer

SCHEMA_VERSION = 1


class Project(BaseModel):
    schema_version: int = SCHEMA_VERSION
    name: str
    room: Room
    viewer: Viewer = Field(default_factory=Viewer)
    fixtures: list[Fixture] = Field(default_factory=list)
    controllers: list[Controller] = Field(default_factory=list)
    calibration: dict[LedType, LedCalibration] = Field(default_factory=default_calibration)
    power: PowerSettings = Field(default_factory=PowerSettings)
    floorplan: FloorplanImage | None = None

    @model_validator(mode="after")
    def _fill_calibration(self) -> "Project":
        for led_type, cal in default_calibration().items():
            self.calibration.setdefault(led_type, cal)
        return self

    @model_validator(mode="after")
    def _check_references(self) -> "Project":
        _unique([f.id for f in self.fixtures], "fixture")
        _unique([c.id for c in self.controllers], "controller")
        counts = {f.id: fixture_led_count(f) for f in self.fixtures}

        for c in self.controllers:
            used: list[tuple[int, int]] = []
            for m in c.mappings:
                if m.fixture_id not in counts:
                    raise ValueError(f"controller {c.name!r} maps unknown fixture {m.fixture_id!r}")
                available = counts[m.fixture_id] - m.fixture_offset
                count = available if m.count is None else m.count
                if count <= 0 or count > available:
                    raise ValueError(f"controller {c.name!r}: mapping of fixture {m.fixture_id!r} exceeds its LEDs")
                span = (m.start, m.start + count)
                for other in used:
                    if span[0] < other[1] and other[0] < span[1]:
                        raise ValueError(f"controller {c.name!r} has overlapping pixel ranges")
                used.append(span)
        return self

    def fixture(self, fixture_id: str) -> Fixture:
        for f in self.fixtures:
            if f.id == fixture_id:
                return f
        raise KeyError(fixture_id)


def _unique(ids: list[str], kind: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {kind} ids")
