"""Fixtures are the physical LED strips / shapes placed in the room."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from lsg.model.common import Id, Vec3, new_id


class LedType(StrEnum):
    WS2812B = "ws2812b"
    SK6812 = "sk6812"
    SK6812_RGBW = "sk6812_rgbw"

    @property
    def channels(self) -> int:
        return 4 if self is LedType.SK6812_RGBW else 3


class PolylineGeometry(BaseModel):
    type: Literal["polyline"] = "polyline"
    points: list[Vec3] = Field(min_length=2)


class BezierGeometry(BaseModel):
    """Chain of cubic Bezier segments: [p0, c0a, c0b, p1, c1a, c1b, p2, ...] (3k + 1 points)."""

    type: Literal["bezier"] = "bezier"
    points: list[Vec3] = Field(min_length=4)

    @model_validator(mode="after")
    def _check_count(self) -> "BezierGeometry":
        if (len(self.points) - 1) % 3 != 0:
            raise ValueError("bezier needs 3k + 1 points (anchor, control, control, anchor, ...)")
        return self


class ArcGeometry(BaseModel):
    """Circular arc around `center` in the plane perpendicular to `normal`.

    Angles are measured from `reference` (an in-plane direction; derived automatically
    when omitted), positive sweep is counter-clockwise around `normal`.
    """

    type: Literal["arc"] = "arc"
    center: Vec3
    radius: float = Field(gt=0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    reference: Vec3 | None = None
    start_deg: float = 0.0
    sweep_deg: float = Field(default=90.0, ge=-360.0, le=360.0)

    @model_validator(mode="after")
    def _non_zero(self) -> "ArcGeometry":
        if self.sweep_deg == 0:
            raise ValueError("sweep_deg must not be 0")
        return self


class CircleGeometry(BaseModel):
    """Closed ring; LEDs start at `start_deg` and run counter-clockwise around `normal`."""

    type: Literal["circle"] = "circle"
    center: Vec3
    radius: float = Field(gt=0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    reference: Vec3 | None = None
    start_deg: float = 0.0


class MatrixGeometry(BaseModel):
    """Rectangular LED panel. `origin` is the first LED, columns run along `col_dir`, rows along `row_dir`."""

    type: Literal["matrix"] = "matrix"
    origin: Vec3
    col_dir: Vec3 = (1.0, 0.0, 0.0)
    row_dir: Vec3 = (0.0, 0.0, -1.0)
    cols: int = Field(ge=1)
    rows: int = Field(ge=1)
    pitch: float = Field(default=1 / 60, gt=0, description="LED spacing in metres")
    serpentine: bool = True
    column_major: bool = False


Geometry = Annotated[
    PolylineGeometry | BezierGeometry | ArcGeometry | CircleGeometry | MatrixGeometry,
    Field(discriminator="type"),
]


class Fixture(BaseModel):
    id: Id = Field(default_factory=new_id)
    name: str = "Strip"
    geometry: Geometry
    led_type: LedType = LedType.WS2812B
    leds_per_meter: float = Field(default=60.0, gt=0, le=1000)
    led_count: int | None = Field(default=None, ge=1, description="Overrides leds_per_meter; ignored for matrices")
    reverse: bool = Field(default=False, description="Data input is at the geometric end")
    tags: list[str] = Field(default_factory=list)
