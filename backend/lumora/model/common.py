"""Shared primitives for all models.

Coordinate system: right-handed, metres, z points up, the floor lies at z = 0.
"""

import uuid
from typing import Annotated

from pydantic import Field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

Id = Annotated[str, Field(min_length=1, max_length=64)]
# name of a file the app stores next to a JSON document (audio, floor plan image). The documents can
# come from an imported project, so the name must stay inside its folder: no path, no drive, no "..".
FileName = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_. -]*$")]


def new_id() -> str:
    return uuid.uuid4().hex[:12]
