from pydantic import BaseModel, Field

from lumora.model.common import Vec3


class Viewer(BaseModel):
    """Where the audience stands and looks.

    yaw: 0 deg looks along +x, 90 deg along +y (counter-clockwise seen from above).
    pitch: positive looks up.
    """

    position: Vec3 = (0.0, 0.0, 1.6)
    yaw_deg: float = 0.0
    pitch_deg: float = Field(default=0.0, ge=-89.0, le=89.0)
