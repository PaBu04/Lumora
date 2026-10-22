"""Frame (perceived RGB) -> per-controller byte buffers, with calibration and power limiting.

Steps per frame:
  1. master brightness (perceived)
  2. calibration curve per LED type -> PWM floats (min level, white balance)
  3. RGBW split for RGBW fixtures on RGBW controllers
  4. power estimate per controller; scale down to the controller budget and to the
     shared project budget
  5. quantise to bytes (optional spatial / temporal dithering)
"""

from dataclasses import dataclass, field

import numpy as np

from lsg.geometry.led_table import LedTable
from lsg.model.calibration import LedCalibration
from lsg.model.fixture import LedType
from lsg.model.project import Project
from lsg.output.curve import extract_white, to_pwm
from lsg.output.mapper import ControllerPlan, plan_controllers

LED_TYPES = list(LedType)


@dataclass
class ControllerOutput:
    plan: ControllerPlan
    data: bytes
    ma: float  # estimated current after limiting
    ma_requested: float  # estimated current before limiting
    scale: float  # applied power scale (1 = not limited)


@dataclass
class FrameStats:
    total_ma: float = 0.0
    total_requested_ma: float = 0.0
    controllers: dict[str, dict] = field(default_factory=dict)


def _hash01(n: int, seed: int) -> np.ndarray:
    x = (np.arange(n, dtype=np.uint64) * np.uint64(2654435761) + np.uint64(seed * 97 + 13)) & np.uint64(0xFFFFFFFF)
    x ^= x >> np.uint64(15)
    x = (x * np.uint64(2246822519)) & np.uint64(0xFFFFFFFF)
    x ^= x >> np.uint64(13)
    return (x & np.uint64(0xFFFF)).astype(np.float32) / 65536.0


class OutputPipeline:
    def __init__(self, project: Project, table: LedTable):
        self.project = project
        self.table = table
        self.plans = plan_controllers(project, table)
        type_of_fixture = {f.id: LED_TYPES.index(f.led_type) for f in project.fixtures}
        self.led_type_idx = np.array(
            [type_of_fixture[table.fixture_ids[i]] for i in table.fixture_index], dtype=np.int8
        ) if table.count else np.zeros(0, np.int8)
        self.cal: list[LedCalibration] = [project.calibration[t] for t in LED_TYPES]
        self._residual: dict[str, np.ndarray] = {}
        self._spatial: dict[str, np.ndarray] = {}

    # --- conversion -------------------------------------------------------------------

    def frame_to_pwm(self, frame: np.ndarray, brightness: float = 1.0) -> np.ndarray:
        """Perceived RGB for every LED -> PWM floats (N, 3)."""
        v = frame * brightness if brightness != 1.0 else frame
        out = np.zeros_like(v, dtype=np.float32)
        for k, cal in enumerate(self.cal):
            sel = self.led_type_idx == k
            if sel.any():
                out[sel] = to_pwm(v[sel], cal)
        return out

    def _plan_pwm(self, plan: ControllerPlan, pwm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Controller pixel buffer (pixels, 3 or 4) as floats and the per-pixel LED type."""
        ch = 4 if plan.controller.rgbw else 3
        buf = np.zeros((plan.pixel_count, ch), np.float32)
        types = np.zeros(plan.pixel_count, np.int8)
        if plan.pixel_count:
            buf[plan.pixel_idx, :3] = pwm[plan.table_idx]
            types[plan.pixel_idx] = self.led_type_idx[plan.table_idx]
        if ch == 4 and plan.white_mask.any():
            for k, cal in enumerate(self.cal):
                sel = plan.white_mask & (types == k)
                if sel.any():
                    rgb, w = extract_white(buf[sel, :3], cal)
                    buf[sel, :3] = rgb
                    buf[sel, 3] = w
        return buf, types

    def estimate_ma(self, buf: np.ndarray, types: np.ndarray) -> float:
        ma = 0.0
        for k, cal in enumerate(self.cal):
            sel = types == k
            n = int(sel.sum())
            if n:
                ma += n * cal.ma_idle + float(buf[sel].sum()) / 255.0 * cal.ma_per_channel
        return ma

    def _idle_ma(self, types: np.ndarray) -> float:
        return float(sum(int((types == k).sum()) * cal.ma_idle for k, cal in enumerate(self.cal)))

    def _quantise(self, key: str, buf: np.ndarray, types: np.ndarray) -> bytes:
        modes = {cal.dithering for cal in self.cal}
        if modes == {"none"}:
            return (np.clip(buf, 0, 255) + 0.5).astype(np.uint8).tobytes()
        out = np.floor(np.clip(buf, 0, 255) + 0.5)
        for k, cal in enumerate(self.cal):
            sel = types == k
            if not sel.any() or cal.dithering == "none":
                continue
            vals = buf[sel]
            if cal.dithering == "spatial":
                if key not in self._spatial or len(self._spatial[key]) != len(buf):
                    self._spatial[key] = _hash01(len(buf), len(key))
                thr = self._spatial[key][sel][:, None]
                q = np.floor(vals + thr)
            else:  # temporal error diffusion
                res = self._residual.get(key)
                if res is None or res.shape != buf.shape:
                    res = np.zeros_like(buf)
                    self._residual[key] = res
                target = vals + res[sel]
                q = np.floor(target + 0.5)
                res[sel] = np.where(vals > 0, target - q, 0.0)
            # never dither a lit LED to black or a dark LED to lit
            q = np.where(vals <= 0, 0.0, np.maximum(q, cal.min_level))
            out[sel] = q
        return np.clip(out, 0, 255).astype(np.uint8).tobytes()

    # --- main entry -------------------------------------------------------------------

    def encode_all(self, frame_for, brightness: float = 1.0, raw: bool = False) -> tuple[list[ControllerOutput], FrameStats]:
        """`frame_for(controller)` returns the perceived frame for that controller (latency aware).
        With raw=True the frames already hold PWM values 0..255 (calibration patterns)."""
        staged = []
        cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for plan in self.plans:
            frame = frame_for(plan.controller)
            key = id(frame)
            if key not in cache:  # keep the frame alive so its id cannot be reused
                cache[key] = (frame, frame.astype(np.float32) if raw else self.frame_to_pwm(frame, brightness))
            buf, types = self._plan_pwm(plan, cache[key][1])
            ma = self.estimate_ma(buf, types)
            scale = 1.0
            budget = plan.controller.budget_ma
            idle = self._idle_ma(types)
            if budget and ma > budget:
                scale = max(0.0, (budget - idle) / max(ma - idle, 1e-6))
            staged.append([plan, buf, types, ma, scale, idle])

        total_budget = self.project.power.total_budget_ma
        if total_budget:
            total = sum(idle + (ma - idle) * scale for _, _, _, ma, scale, idle in staged)
            idle_all = sum(s[5] for s in staged)
            if total > total_budget:
                extra = max(0.0, (total_budget - idle_all) / max(total - idle_all, 1e-6))
                for s in staged:
                    s[4] *= extra

        outputs, stats = [], FrameStats()
        for plan, buf, types, ma, scale, idle in staged:
            if scale < 1.0:
                buf = buf * scale
            data = self._quantise(plan.controller.id, buf, types)
            limited_ma = idle + (ma - idle) * scale
            outputs.append(ControllerOutput(plan, data, limited_ma, ma, scale))
            stats.total_ma += limited_ma
            stats.total_requested_ma += ma
            stats.controllers[plan.controller.id] = {
                "ma": round(limited_ma), "requested_ma": round(ma), "scale": round(scale, 3),
                "budget_ma": plan.controller.budget_ma,
            }
        return outputs, stats
