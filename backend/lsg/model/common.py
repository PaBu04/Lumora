"""Shared primitives for all models.

Coordinate system: right-handed, metres, z points up, the floor lies at z = 0.
"""

import uuid
from typing import Annotated

from pydantic import Field

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]

Id = Annotated[str, Field(min_length=1, max_length=64)]


def new_id() -> str:
    return uuid.uuid4().hex[:12]
