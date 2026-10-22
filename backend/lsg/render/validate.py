"""Show validation with messages written for both humans and the AI."""

import numpy as np

from lsg.audio.features import AudioFeatures
from lsg.geometry.led_table import LedTable
from lsg.model.project import Project
from lsg.model.show import Show
from lsg.render.engine import Renderer
from lsg.render.shaders import Shader


def validate_show(
    show: Show,
    project: Project,
    table: LedTable,
    features: AudioFeatures,
    shaders: dict[str, Shader],
    probe_frames: int = 24,
) -> list[dict]:
    """Errors stop a clip from rendering, warnings are hints. Each issue: severity, clip, layer, message."""
    issues: list[dict] = []
    layer_of = {c.id: layer.name for layer, c in show.clips()}
    renderer = Renderer(project, table, show, features, shaders)

    for clip_id, msg in renderer.errors.items():
        issues.append({"severity": "error", "clip": clip_id, "layer": layer_of.get(clip_id), "message": msg})

    ids = [c.id for _, c in show.clips()]
    for dup in {i for i in ids if ids.count(i) > 1}:
        issues.append({"severity": "error", "clip": dup, "layer": layer_of.get(dup), "message": "duplicate clip id"})

    duration = renderer.duration
    for layer, c in show.clips():
        if duration and c.start >= duration:
            issues.append({"severity": "warning", "clip": c.id, "layer": layer.name,
                           "message": f"clip starts after the end of the song ({duration:.1f}s)"})
        if c.fade_in + c.fade_out > c.end - c.start + 1e-6:
            issues.append({"severity": "warning", "clip": c.id, "layer": layer.name,
                           "message": "fade_in + fade_out is longer than the clip"})
    for cc in renderer.clips:
        if cc.view.n == 0:
            issues.append({"severity": "warning", "clip": cc.clip.id, "layer": layer_of.get(cc.clip.id),
                           "message": "target selects no LEDs"})

    # run every clip a few times to surface runtime errors (bad shader output etc.)
    for cc in renderer.clips:
        c = cc.clip
        for t in np.linspace(c.start, c.end, 3, endpoint=False):
            renderer.render(float(t))
    for t in np.linspace(0, max(duration, 1e-3), probe_frames, endpoint=False):
        renderer.render(float(t))
    reported = {i["clip"] for i in issues}
    for clip_id, msg in renderer.errors.items():
        if clip_id not in reported:
            issues.append({"severity": "error", "clip": clip_id, "layer": layer_of.get(clip_id), "message": msg})
    return issues
