"""Show = layers of timed effect clips. This is the format the AI writes via MCP.

Parameter values may be dynamic:
  literal:   0.5, "#ff0080", ["#f00", "#00f"], "x", [1, 0, 0]
  audio:     {"audio": "low", "min": 0.2, "max": 1.0, "pow": 1.0}
  keyframes: {"keys": [[0, "#ff0000"], [4, "#0000ff"]], "ease": "linear"}  (times relative to clip start)
  lfo:       {"lfo": "sine", "beats": 2, "min": 0, "max": 1, "phase": 0}
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from lsg.model.common import Id, new_id

BlendMode = Literal["normal", "add", "max", "multiply", "subtract"]
TargetField = Literal["x", "y", "z", "nx", "ny", "nz", "u", "s", "azimuth", "elevation", "distance", "view"]


class Range(BaseModel):
    """Selects LEDs whose `field` lies in [min, max]. x/y/z/distance/s in metres (s = along the
    strip from its first LED), angles in degrees, nx/ny/nz/u normalised 0..1, view 0..1
    (1 = in the viewer's field of view)."""

    field: TargetField
    min: float | None = None
    max: float | None = None


class Target(BaseModel):
    """Which LEDs a clip affects. Empty target = all LEDs.

    fixtures/tags are combined with OR, `where` ranges are combined with AND on top.
    view: "direct" = LEDs the viewer looks at, "indirect" = behind / beside the viewer (they
    light the room rather than being seen).
    """

    fixtures: list[str] | None = None
    tags: list[str] | None = None
    view: Literal["direct", "indirect"] | None = None
    where: list[Range] = Field(default_factory=list)
    invert: bool = False


class Clip(BaseModel):
    id: Id = Field(default_factory=new_id)
    start: float = Field(ge=0, description="seconds")
    end: float = Field(gt=0, description="seconds")
    effect: str = Field(description='effect id from the library, or "shader:<name>"')
    params: dict[str, Any] = Field(default_factory=dict)
    target: Target = Field(default_factory=Target)
    blend: BlendMode = "normal"
    opacity: float = Field(default=1.0, ge=0, le=1)
    fade_in: float = Field(default=0.0, ge=0)
    fade_out: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def _order(self) -> "Clip":
        if self.end <= self.start:
            raise ValueError(f"clip {self.id}: end must be after start")
        return self


class Layer(BaseModel):
    id: Id = Field(default_factory=new_id)
    name: str = "Layer"
    enabled: bool = True
    opacity: float = Field(default=1.0, ge=0, le=1)
    clips: list[Clip] = Field(default_factory=list)


class Show(BaseModel):
    """Layers are composited bottom (first) to top (last)."""

    id: Id = Field(default_factory=new_id)
    name: str = "Show"
    description: str = ""
    song_id: str | None = None
    duration: float | None = Field(default=None, gt=0, description="defaults to the song duration")
    master: float = Field(default=1.0, ge=0, le=1)
    # 0..1: how much quiet passages of the song darken the whole show (1 = quiet parts nearly dark)
    dynamics: float = Field(default=0.0, ge=0, le=1)
    layers: list[Layer] = Field(default_factory=list)

    def clips(self):
        for layer in self.layers:
            for clip in layer.clips:
                yield layer, clip
