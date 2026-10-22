from pydantic import BaseModel, Field

from lsg.model.common import Id, new_id


class FixtureMapping(BaseModel):
    """Maps a range of a fixture's LEDs onto a controller's pixel buffer."""

    fixture_id: Id
    start: int = Field(default=0, ge=0, description="First pixel index on the controller")
    fixture_offset: int = Field(default=0, ge=0, description="First LED of the fixture to send")
    count: int | None = Field(default=None, ge=1, description="Number of LEDs; None = rest of fixture")


class Controller(BaseModel):
    id: Id = Field(default_factory=new_id)
    name: str = "WLED"
    host: str
    port: int = Field(default=4048, ge=1, le=65535)
    mac: str | None = None
    rgbw: bool = False
    latency_ms: float = Field(default=0.0, ge=-1000, le=1000)
    mappings: list[FixtureMapping] = Field(default_factory=list)
