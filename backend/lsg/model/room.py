from pydantic import BaseModel, Field, field_validator

from lsg.model.common import Vec2


class Wall(BaseModel):
    start: Vec2
    end: Vec2


def _segments_intersect(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool:
    def orient(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def on_segment(p: Vec2, q: Vec2, r: Vec2) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )


def polygon_area(points: list[Vec2]) -> float:
    """Signed area (positive = counter-clockwise)."""
    n = len(points)
    return 0.5 * sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))


class FloorplanImage(BaseModel):
    """Photo / blueprint shown under the floor plan editor to trace walls."""

    filename: str
    px_width: int = Field(gt=0)
    px_height: int = Field(gt=0)
    x: float = 0.0  # world position of the image's lower left corner (metres)
    y: float = 0.0
    width_m: float = Field(default=5.0, gt=0.1, le=500)
    opacity: float = Field(default=0.5, ge=0.05, le=1.0)

    @property
    def height_m(self) -> float:
        return self.width_m * self.px_height / self.px_width


class Room(BaseModel):
    """Room = floor polygon (x/y in metres) extruded to `height`."""

    floor: list[Vec2] = Field(min_length=3)
    height: float = Field(gt=0, le=50)

    @field_validator("floor")
    @classmethod
    def _simple_polygon(cls, floor: list[Vec2]) -> list[Vec2]:
        n = len(floor)
        if abs(polygon_area(floor)) < 1e-6:
            raise ValueError("floor polygon has no area")
        for i in range(n):
            for j in range(i + 1, n):
                # adjacent edges share a vertex and are allowed to touch
                if j == i + 1 or (i == 0 and j == n - 1):
                    continue
                if _segments_intersect(floor[i], floor[(i + 1) % n], floor[j], floor[(j + 1) % n]):
                    raise ValueError(f"floor polygon edges {i} and {j} intersect")
        # store counter-clockwise so wall normals point consistently inwards
        if polygon_area(floor) < 0:
            floor = list(reversed(floor))
        return floor

    @property
    def walls(self) -> list[Wall]:
        n = len(self.floor)
        return [Wall(start=self.floor[i], end=self.floor[(i + 1) % n]) for i in range(n)]

    @property
    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        xs = [p[0] for p in self.floor]
        ys = [p[1] for p in self.floor]
        return (min(xs), min(ys), 0.0), (max(xs), max(ys), self.height)
