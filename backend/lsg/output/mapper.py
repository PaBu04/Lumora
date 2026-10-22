"""Turns a rendered frame into the byte buffer of each controller."""

from dataclasses import dataclass

import numpy as np

from lsg.geometry.led_table import LedTable
from lsg.geometry.sampling import fixture_led_count
from lsg.model.controller import Controller
from lsg.model.fixture import LedType
from lsg.model.project import Project


@dataclass
class ControllerPlan:
    controller: Controller
    pixel_count: int
    table_idx: np.ndarray  # frame index for each used controller pixel
    pixel_idx: np.ndarray  # controller pixel for each entry of table_idx
    white_mask: np.ndarray  # per controller pixel: extract white channel (RGBW fixtures)


def plan_controllers(project: Project, table: LedTable) -> list[ControllerPlan]:
    plans = []
    for c in project.controllers:
        t_idx, p_idx, w_idx = [], [], []
        for m in c.mappings:
            if m.fixture_id not in table.fixture_ids:
                continue
            fixture = project.fixture(m.fixture_id)
            sl = table.fixture_slice(m.fixture_id)
            count = m.count if m.count is not None else fixture_led_count(fixture) - m.fixture_offset
            src = np.arange(sl.start + m.fixture_offset, sl.start + m.fixture_offset + count)
            dst = np.arange(m.start, m.start + count)
            t_idx.append(src)
            p_idx.append(dst)
            if fixture.led_type is LedType.SK6812_RGBW:
                w_idx.append(dst)
        t = np.concatenate(t_idx) if t_idx else np.zeros(0, int)
        p = np.concatenate(p_idx) if p_idx else np.zeros(0, int)
        n = int(p.max()) + 1 if p.size else 0
        white = np.zeros(n, dtype=bool)
        if w_idx:
            white[np.concatenate(w_idx)] = True
        plans.append(ControllerPlan(c, n, t, p, white))
    return plans


