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
