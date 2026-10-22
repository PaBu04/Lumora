"""Viewer-relative coordinates: what the audience sees where."""

import numpy as np

from lsg.model.viewer import Viewer


def viewer_basis(viewer: Viewer) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(forward, right, up) unit vectors of the viewer."""
    yaw, pitch = np.radians(viewer.yaw_deg), np.radians(viewer.pitch_deg)
    forward = np.array([np.cos(yaw) * np.cos(pitch), np.sin(yaw) * np.cos(pitch), np.sin(pitch)])
    right = np.array([np.sin(yaw), -np.cos(yaw), 0.0])
    up = np.cross(right, forward)
    return forward, right, up


# field of view used to tell LEDs the viewer looks at from those that only light the room
VIEW_H = (60.0, 100.0)  # |azimuth| fully visible up to 60 deg, peripheral up to 100 deg
VIEW_UP = (55.0, 75.0)  # above eye level
VIEW_DOWN = (45.0, 65.0)  # below eye level


def _ramp(x: np.ndarray, full: float, zero: float) -> np.ndarray:
    return np.clip((zero - x) / (zero - full), 0.0, 1.0)


def visibility(azimuth: np.ndarray, elevation: np.ndarray) -> np.ndarray:
    """0..1: 1 = in the viewer's field of view (seen directly), 0 = behind or far to the side
    (only seen indirectly, as light on walls and ceiling). >= 0.5 counts as direct."""
    h = _ramp(np.abs(azimuth), *VIEW_H)
    v = np.where(elevation >= 0, _ramp(elevation, *VIEW_UP), _ramp(-elevation, *VIEW_DOWN))
    return (h * v).astype(np.float32)


def viewer_relative(pos: np.ndarray, viewer: Viewer) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Azimuth / elevation in degrees and distance in metres for each position.

    azimuth: 0 = straight ahead, negative = left, positive = right (-180..180).
    elevation: 0 = eye level, positive = above (-90..90).
    """
    forward, right, up = viewer_basis(viewer)
    d = pos - np.asarray(viewer.position, dtype=np.float64)
    f, r, u = d @ forward, d @ right, d @ up
    azimuth = np.degrees(np.arctan2(r, f))
    elevation = np.degrees(np.arctan2(u, np.hypot(f, r)))
    distance = np.linalg.norm(d, axis=1)
    return azimuth, elevation, distance
