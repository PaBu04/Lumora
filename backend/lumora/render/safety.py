"""Photosensitivity safety: at most a few large flashes per second.

Guideline (WCAG 2.3.1 "three flashes"): content should not flash more than three times per second
over a large area. A flash here is a jump of the room's mean perceived brightness against its level
a moment before. Local hits on a few LEDs barely move the mean and stay untouched; a whole-room
flash that comes sooner than 1 / LIMIT_HZ after the previous one is softened to a small rise.

LIMIT_HZ is an app setting (0 = off); the Strobe effect is limited to the same rate.
"""

import numpy as np

LIMIT_HZ = 3.0
RISE = 0.12  # mean brightness jump that counts as a flash (perceived 0..1)
SETTLE = 0.06  # below this the flash is over
BASE_WINDOW = 0.15  # seconds: the level "a moment before"


class FlashLimiter:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.history: list[tuple[float, float]] = []  # (t, mean level) of what was shown
        self.last_flash = -1e9
        self.in_flash = False
        self.last_t: float | None = None
        self.softened = 0  # frames changed (for tests and diagnostics)

    def apply(self, t: float, frame: np.ndarray) -> np.ndarray:
        if LIMIT_HZ <= 0 or frame.size == 0:
            return frame
        if self.last_t is None or t < self.last_t or t - self.last_t > 0.5:  # seek or a new start
            self.reset()
        self.last_t = t
        self.history = [(ht, m) for ht, m in self.history if t - ht <= BASE_WINDOW]
        base = min((m for _, m in self.history), default=None)
        level = float(frame.max(axis=1).mean())
        if base is not None:
            rise = level - base
            if not self.in_flash and rise >= RISE:
                if t - self.last_flash < 1.0 / LIMIT_HZ:
                    # too soon after the last flash: let it rise only a little
                    target = base + 0.5 * RISE
                    frame = frame * (target / max(level, 1e-6))
                    level = target
                    self.softened += 1
                else:
                    self.in_flash = True
                    self.last_flash = t
            elif self.in_flash and rise < SETTLE:
                self.in_flash = False
        self.history.append((t, level))
        return frame


def max_flash_rate() -> float:
    """Highest flash rate effects may use (Hz); unlimited when the limit is off."""
    return LIMIT_HZ if LIMIT_HZ > 0 else 1e9
