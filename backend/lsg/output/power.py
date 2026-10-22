"""Power analysis of a whole show: estimated current per controller over time."""

import numpy as np

from lsg.output.pipeline import OutputPipeline
from lsg.render.engine import Renderer


def analyse_power(renderer: Renderer, pipeline: OutputPipeline, fps: float = 4.0, brightness: float = 1.0,
                  start: float = 0.0, end: float | None = None) -> dict:
    """Sample the show and estimate the current each controller would draw (before limiting)."""
    end = renderer.duration if end is None else min(end, renderer.duration)
    times = np.arange(start, max(end, start + 1e-3), 1.0 / fps)
    names = {p.controller.id: p.controller.name for p in pipeline.plans}
    requested = {cid: [] for cid in names}
    scales = {cid: [] for cid in names}
    total = []
    for t in times:
        frame = renderer.render(float(t))
        _, stats = pipeline.encode_all(lambda c: frame, brightness)
        for cid, c in stats.controllers.items():
            requested[cid].append(c["requested_ma"])
            scales[cid].append(c["scale"])
        total.append(stats.total_requested_ma)

    def summary(values: list[float], budget: float | None, scale: list[float] | None = None) -> dict:
        arr = np.asarray(values, dtype=float) if values else np.zeros(1)
        i = int(np.argmax(arr))
        out = {
            "peak_ma": round(float(arr.max())),
            "peak_t": round(float(times[i]), 2) if len(times) else 0.0,
            "mean_ma": round(float(arr.mean())),
            "budget_ma": budget,
        }
        if budget:
            over = arr > budget
            out["limited_seconds"] = round(float(over.sum()) / fps, 1)
            out["min_scale"] = round(float(min(scale)) if scale else min(1.0, budget / max(arr.max(), 1e-6)), 3)
        return out

    controllers = {
        cid: {"name": names[cid], **summary(requested[cid], pipeline_budget(pipeline, cid), scales[cid])}
        for cid in names
    }
    return {
        "fps": fps,
        "times": np.round(times, 2).tolist(),
        "controllers": controllers,
        "total": summary(total, pipeline.project.power.total_budget_ma),
        "curves": {cid: [round(v) for v in vals] for cid, vals in requested.items()},
        "total_curve": [round(v) for v in total],
    }


def pipeline_budget(pipeline: OutputPipeline, controller_id: str) -> float | None:
    for p in pipeline.plans:
        if p.controller.id == controller_id:
            return p.controller.budget_ma
    return None


def power_issues(report: dict) -> list[dict]:
    """Validation warnings for controllers / supplies that would be dimmed by the limiter."""
    issues = []
    for cid, c in report["controllers"].items():
        if c.get("budget_ma") and c["peak_ma"] > c["budget_ma"]:
            issues.append({
                "severity": "warning", "clip": None, "layer": None,
                "message": (
                    f"power: controller {c['name']!r} needs up to {c['peak_ma'] / 1000:.1f} A at t={c['peak_t']}s "
                    f"(budget {c['budget_ma'] / 1000:.1f} A); the limiter dims it to {c['min_scale'] * 100:.0f} % "
                    f"for about {c['limited_seconds']} s. Lower brightness or use fewer full-white LEDs there."
                ),
            })
    t = report["total"]
    if t.get("budget_ma") and t["peak_ma"] > t["budget_ma"]:
        issues.append({
            "severity": "warning", "clip": None, "layer": None,
            "message": (
                f"power: all controllers together need up to {t['peak_ma'] / 1000:.1f} A at t={t['peak_t']}s "
                f"(power supply budget {t['budget_ma'] / 1000:.1f} A); output will be dimmed for about {t['limited_seconds']} s."
            ),
        })
    return issues
