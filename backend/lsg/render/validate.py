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
    power: bool = True,
    power_fps: float = 2.0,
    light: bool = True,
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
            issues.append(
                {
                    "severity": "warning",
                    "clip": c.id,
                    "layer": layer.name,
                    "message": f"clip starts after the end of the song ({duration:.1f}s)",
                }
            )
        if c.fade_in + c.fade_out > c.end - c.start + 1e-6:
            issues.append(
                {
                    "severity": "warning",
                    "clip": c.id,
                    "layer": layer.name,
                    "message": "fade_in + fade_out is longer than the clip",
                }
            )
    for cc in renderer.clips:
        if cc.view.n == 0:
            issues.append(
                {
                    "severity": "warning",
                    "clip": cc.clip.id,
                    "layer": layer_of.get(cc.clip.id),
                    "message": "target selects no LEDs",
                }
            )

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

    # perceived brightness below what 8-bit PWM can show (see calibration)
    cutoff = max(c.cutoff for c in project.calibration.values())
    for layer, c in show.clips():
        b = c.params.get("brightness")
        if isinstance(b, (int, float)) and 0 < b * c.opacity < max(0.03, cutoff * 2):
            issues.append(
                {
                    "severity": "warning",
                    "clip": c.id,
                    "layer": layer.name,
                    "message": f"brightness {b * c.opacity:.3f} is at the very bottom of the LED range: it will look "
                    "the same as neighbouring dim levels or switch off. Use >= 0.03 (perceived).",
                }
            )

    if power and project.controllers and (project.power.total_budget_ma or any(c.budget_ma for c in project.controllers)):
        from lsg.output.pipeline import OutputPipeline
        from lsg.output.power import analyse_power, power_issues

        report = analyse_power(renderer, OutputPipeline(project, table), fps=power_fps)
        issues.extend(power_issues(report))
    if light and table.count:
        issues.extend(light_issues(light_report(Renderer(project, table, show, features, shaders)), show))
    return issues


# --- light and variety ---------------------------------------------------------------------
# LEDs in a dark room: what matters for the feel of a show is how much light the whole room
# gets (long strips light the walls even when dim) and how much changes.
ROOM_LIGHT_WARN = 0.04  # mean linear light over the whole show (1 = every LED full white)
ROOM_LIGHT_PEAK = 0.12  # mean linear light over an 8 s stretch
QUIET_LIGHT = 0.008  # quiet passages of the song should stay below this
QUIET_LOUDNESS = 0.55  # a section this quiet (smoothed loudness 0..1) counts as quiet
LIT_SHARE_WARN = 0.85  # share of LEDs lit above 5 % ...
LIT_TIME_WARN = 0.6  # ... for this share of the show
STILL_SECONDS = 20.0  # longer than this without visible change = monotonous


def light_report(renderer: Renderer, fps: float = 2.0) -> dict:
    """Room light, lit share and motion over time and per section."""
    duration = renderer.duration or 0.0
    times = np.arange(0.0, max(duration, 1e-3), 1.0 / fps)
    room, lit, motion, changed = [], [], [], []
    prev = None
    for t in times:
        f = renderer.render(float(t))
        lin = np.power(np.clip(f, 0, 1), 2.2)
        room.append(float((lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)).mean()) if len(f) else 0.0)
        lit.append(float((f.max(axis=1) > 0.05).mean()) if len(f) else 0.0)
        diff = np.abs(f - prev).max(axis=1) if prev is not None and len(f) else np.zeros(0)
        motion.append(float(diff.mean()) if len(diff) else 0.0)
        changed.append(int((diff > 0.04).sum()))  # LEDs that visibly change
        prev = f
    room_a, lit_a, motion_a = np.asarray(room), np.asarray(lit), np.asarray(motion)
    feats = renderer.features
    loud = np.array([feats.level("loudness", float(t)) for t in times]) if len(times) else np.zeros(0)
    sections = []
    for s in feats.sections:
        sel = (times >= s.start) & (times < s.end)
        if sel.any():
            sections.append(
                {
                    "name": s.name,
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "loudness": round(float(loud[sel].mean()), 2),
                    "room_light": round(float(room_a[sel].mean()), 4),
                    "lit_share": round(float(lit_a[sel].mean()), 3),
                    "motion": round(float(motion_a[sel].mean()), 4),
                }
            )
    win = max(1, int(8 * fps))
    peak = (
        float(np.convolve(room_a, np.ones(win) / win, mode="valid").max()) if len(room_a) >= win else float(room_a.max(initial=0))
    )
    still, longest, start_still = 0.0, (0.0, 0.0, 0.0), 0.0
    for i, c in enumerate(changed):
        if c < 3:  # dark is fine, frozen is not: a few LEDs moving keep it alive
            if still == 0:
                start_still = times[i]
            still += 1.0 / fps
            if still > longest[0]:
                longest = (still, start_still, times[i])
        else:
            still = 0.0
    return {
        "room_light": round(float(room_a.mean()) if len(room_a) else 0.0, 4),
        "room_light_peak_8s": round(peak, 4),
        "lit_share": round(float(lit_a.mean()) if len(lit_a) else 0.0, 3),
        "time_mostly_lit": round(float((lit_a > LIT_SHARE_WARN).mean()) if len(lit_a) else 0.0, 3),
        "longest_still": {
            "seconds": round(longest[0], 1),
            "from": round(float(longest[1]), 1),
            "to": round(float(longest[2]), 1),
        },
        # light in the darkest and brightest tenth of the show, and how much the song itself varies
        "contrast": {
            "dark_p10": round(float(np.percentile(room_a, 10)) if len(room_a) else 0.0, 4),
            "bright_p90": round(float(np.percentile(room_a, 90)) if len(room_a) else 0.0, 4),
            "song_loudness_p10_p90": [round(float(np.percentile(loud, q)), 2) for q in (10, 90)] if len(loud) else [0, 0],
        },
        "sections": sections,
        "scale": "room_light: mean linear light of all LEDs, 1 = all full white; a dark, punchy show stays around "
        f"0.002-0.03, above {ROOM_LIGHT_WARN} it feels bright; quiet passages below {QUIET_LIGHT}. motion: mean change "
        "between frames 0.5 s apart.",
    }


def light_issues(report: dict, show: Show) -> list[dict]:
    issues = []

    def warn(msg: str) -> None:
        issues.append({"severity": "warning", "clip": None, "layer": None, "message": msg})

    if report["room_light"] > ROOM_LIGHT_WARN:
        warn(
            f"the show is bright overall (room light {report['room_light']:.3f}, aim for 0.002-0.03): darker base levels, "
            "fewer LEDs lit at once, light as accents. Long strips light the whole room even when dim."
        )
    elif report["room_light_peak_8s"] > ROOM_LIGHT_PEAK:
        warn(f"a passage is very bright for 8 s or more (room light {report['room_light_peak_8s']:.3f}); keep such moments short")
    if report["time_mostly_lit"] > LIT_TIME_WARN:
        warn(
            f"more than {LIT_SHARE_WARN:.0%} of all LEDs are lit {report['time_mostly_lit']:.0%} of the time: leave strips or "
            "segments dark, use hits / chases on parts of the strips instead of whole-strip effects"
        )
    quiet = [
        s
        for s in report["sections"]
        if s["loudness"] < QUIET_LOUDNESS and s["room_light"] > QUIET_LIGHT and s["end"] - s["start"] > 4
    ]
    if quiet:
        where = ", ".join(f"{s['start']:.0f}-{s['end']:.0f}s" for s in quiet[:4])
        warn(
            f"quiet passages are lit ({where}): keep the room nearly dark where the music is quiet - only small accents, "
            "or raise the show's dynamics"
        )
    c = report.get("contrast")
    if c:
        lo, hi = c["song_loudness_p10_p90"]
        if hi - lo > 0.3 and c["bright_p90"] < 2.5 * c["dark_p10"] + 0.002:
            warn(
                "little contrast: the show is about as bright in the quiet parts as in the loud ones. Make quiet parts "
                "darker and give loud parts / drops brighter accents (or raise the show's dynamics)"
            )
    still = report["longest_still"]
    if still["seconds"] > STILL_SECONDS:
        warn(f"nothing visibly changes from {still['from']}s to {still['to']}s ({still['seconds']}s): add movement or accents")
    clips = [c for _, c in show.clips()]
    if len(clips) >= 4 and all(not (c.target.fixtures or c.target.tags or c.target.where or c.target.view) for c in clips):
        warn("every clip targets all LEDs: give strips / groups (tags, view direct/indirect) their own effects for variety")
    return issues
