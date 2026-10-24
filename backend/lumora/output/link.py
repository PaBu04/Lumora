"""Per-controller frame pacing for live output.

A WLED controller can only show as many frames per second as its LED data lines allow
(WS281x: ~30 us per RGB LED and pin). Frames that arrive faster are dropped by WLED at
irregular points, which makes motion stutter and wastes WiFi airtime. Each controller
therefore gets its own evenly spaced send schedule at a rate it can actually display.

Unchanged frames are not resent at full rate: a static frame is repeated a couple of
times (UDP may lose a packet) and then only sent as a keep-alive so WLED stays in
realtime mode.
"""

import contextlib
import sys
import time
from collections import deque
from dataclasses import dataclass, field

REPEATS = 2  # extra sends of an unchanged frame (covers lost packets)
KEEPALIVE_S = 0.5  # WLED leaves realtime mode after 2.5 s without data by default
MERGE_S = 0.003  # a link due within this window is served by the current render


@dataclass
class OutputLink:
    rate: float  # frames per second for this controller
    next_due: float = 0.0
    last_data: bytes = b""
    repeats: int = 0
    last_send: float = -1e9
    sends: deque = field(default_factory=lambda: deque(maxlen=400))

    @property
    def period(self) -> float:
        return 1.0 / self.rate

    def is_due(self, now: float) -> bool:
        return now >= self.next_due - MERGE_S

    def needs_frame(self, now: float, changing: bool) -> bool:
        """Whether this link wants a freshly rendered frame now.

        `changing` is False while nothing moves (paused, no test pattern): then only
        pending repeats and keep-alives need a frame."""
        if not self.is_due(now):
            return False
        return changing or self.repeats < REPEATS or now - self.last_send >= KEEPALIVE_S

    def next_wake(self, now: float, changing: bool) -> float:
        if changing or self.repeats < REPEATS:
            return self.next_due
        return max(self.next_due, self.last_send + KEEPALIVE_S)

    def advance(self, now: float) -> None:
        """Schedule the next frame one period after the previous slot (keeps the rate exact)."""
        self.next_due += self.period
        if self.next_due < now - self.period:  # fell behind (paused loop, debugger): resync
            self.next_due = now + self.period

    def offer(self, data: bytes, now: float, force: bool = False) -> bool:
        """Decide whether `data` goes out; records the send. Call once per due slot
        (or with force=True for an immediate update, e.g. after a seek)."""
        if self.is_due(now):
            self.advance(now)
        else:  # early update: restart the schedule from here
            self.next_due = now + self.period
        if data != self.last_data:
            self.last_data, self.repeats = data, 0
        elif not force and self.repeats >= REPEATS and now - self.last_send < KEEPALIVE_S:
            return False
        else:
            self.repeats += 1
        self.last_send = now
        self.sends.append(now)
        return True

    def sent_fps(self, window: float = 3.0, now: float | None = None) -> float:
        now = time.perf_counter() if now is None else now
        recent = [t for t in self.sends if now - t <= window]
        if len(recent) < 2:
            return 0.0
        return (len(recent) - 1) / max(recent[-1] - recent[0], 1e-6)


def set_timer_resolution(fine: bool) -> None:
    """Windows wakes sleeping threads only every 15.6 ms by default, so frames would leave in
    clumps (gaps of 0 and 31 ms instead of 20 ms). 1 ms timer resolution keeps them even."""
    if sys.platform != "win32":
        return
    import ctypes

    with contextlib.suppress(Exception):
        winmm = ctypes.WinDLL("winmm")
        (winmm.timeBeginPeriod if fine else winmm.timeEndPeriod)(1)
